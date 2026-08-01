#!/usr/bin/env python3
"""Build and verify a deterministic, public-safe XPRIZE evidence archive."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "Product_Evidence" / "archive-files.json"
DEFAULT_OUTPUT = ROOT / "dist" / "autonomerce-xprize-product-evidence.zip"

SPEC_VERSION = "autonomerce.xprize.archive-spec.v1"
MANIFEST_VERSION = "autonomerce.xprize.archive-manifest.v1"
FINANCIAL_VERSION = "autonomerce.xprize.financial-summary.v1"
ARCHIVE_ROOT = "Product_Evidence"
MANIFEST_PATH = f"{ARCHIVE_ROOT}/MANIFEST.json"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_FILE_BYTES = 2_000_000

PROHIBITED_PARTS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "private",
    "publication-staging",
    "runtime",
    "secret",
    "secrets",
}
PROHIBITED_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = {
    "private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "bearer": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|private[_-]?key|"
        r"session[_-]?token)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}"
    ),
}
PII_PATTERNS = {
    "email-address": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    "local-home-path": re.compile(
        r"(?:/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"
    ),
}
MONEY_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$")
SIGNED_MONEY_PATTERN = re.compile(
    r"^-?(0|[1-9][0-9]*)(\.[0-9]{1,6})?$"
)


class ArchiveValidationError(ValueError):
    """Raised when an evidence archive would cross a public-safety boundary."""


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveValidationError(f"{label}: expected UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ArchiveValidationError(f"{label}: top-level JSON must be an object")
    return value


def _relative_posix(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ArchiveValidationError(f"{label}: path must be a non-empty string")
    if "\\" in value or "\x00" in value or value.startswith("/") or "//" in value:
        raise ArchiveValidationError(f"{label}: unsafe path syntax")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchiveValidationError(f"{label}: path must remain relative")
    return path


def _reject_prohibited_path(path: PurePosixPath, *, label: str) -> None:
    lowered = tuple(part.casefold() for part in path.parts)
    if any(part in PROHIBITED_PARTS or part.startswith(".env") for part in lowered):
        raise ArchiveValidationError(f"{label}: prohibited private/generated path")
    if path.suffix.casefold() in PROHIBITED_SUFFIXES:
        raise ArchiveValidationError(f"{label}: prohibited file type")


def _real_regular_file(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    root = root.resolve(strict=True)
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise ArchiveValidationError(f"{label}: source file is missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ArchiveValidationError(f"{label}: symlinks are not allowed")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ArchiveValidationError(
                f"{label}: source parent must be a real directory"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ArchiveValidationError(f"{label}: source must be a regular file")
    try:
        current.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise ArchiveValidationError(f"{label}: source escapes project root") from exc
    return current


def _scan_public_text(data: bytes, *, label: str) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ArchiveValidationError(f"{label}: file exceeds public archive limit")
    if b"\x00" in data:
        raise ArchiveValidationError(f"{label}: binary/NUL content is not allowed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveValidationError(
            f"{label}: only reviewable UTF-8 text artifacts are allowed"
        ) from exc
    for name, pattern in {**SECRET_PATTERNS, **PII_PATTERNS}.items():
        if pattern.search(text):
            raise ArchiveValidationError(f"{label}: detected {name}")


def _spec_path(project_root: Path, spec_path: Path) -> Path:
    project_root = project_root.resolve(strict=True)
    candidate = spec_path if spec_path.is_absolute() else project_root / spec_path
    absolute = Path(os.path.abspath(candidate))
    try:
        relative = absolute.relative_to(project_root)
    except ValueError as exc:
        raise ArchiveValidationError("archive spec must be inside project root") from exc
    pure = _relative_posix(relative.as_posix(), label="archive spec")
    return _real_regular_file(project_root, pure, label="archive spec")


def _load_spec(
    project_root: Path,
    spec_path: Path,
) -> list[tuple[PurePosixPath, PurePosixPath]]:
    resolved_spec = _spec_path(project_root, spec_path)
    spec = _json_object(resolved_spec.read_bytes(), label="archive spec")
    if set(spec) != {"schemaVersion", "archiveRoot", "files"}:
        raise ArchiveValidationError("archive spec: unexpected properties")
    if spec["schemaVersion"] != SPEC_VERSION:
        raise ArchiveValidationError("archive spec: unsupported schemaVersion")
    if spec["archiveRoot"] != ARCHIVE_ROOT:
        raise ArchiveValidationError(
            f"archive spec: archiveRoot must be {ARCHIVE_ROOT!r}"
        )
    files = spec["files"]
    if not isinstance(files, list) or not files:
        raise ArchiveValidationError("archive spec: files must be a non-empty list")

    mappings: list[tuple[PurePosixPath, PurePosixPath]] = []
    source_keys: set[str] = set()
    archive_keys: set[str] = set()
    archive_casefold_keys: set[str] = set()
    for index, item in enumerate(files):
        label = f"archive spec files[{index}]"
        if not isinstance(item, dict) or set(item) != {"source", "archive"}:
            raise ArchiveValidationError(f"{label}: unexpected properties")
        source = _relative_posix(item["source"], label=f"{label}.source")
        archive = _relative_posix(item["archive"], label=f"{label}.archive")
        _reject_prohibited_path(source, label=f"{label}.source")
        _reject_prohibited_path(archive, label=f"{label}.archive")
        if not archive.parts or archive.parts[0] != ARCHIVE_ROOT:
            raise ArchiveValidationError(
                f"{label}.archive: path must start with {ARCHIVE_ROOT}/"
            )
        source_key = source.as_posix()
        archive_key = archive.as_posix()
        archive_casefold = archive_key.casefold()
        if source_key in source_keys:
            raise ArchiveValidationError(f"{label}: duplicate source path")
        if archive_key in archive_keys or archive_casefold in archive_casefold_keys:
            raise ArchiveValidationError(f"{label}: duplicate archive path")
        if archive_key == MANIFEST_PATH:
            raise ArchiveValidationError(
                f"{label}: {MANIFEST_PATH} is generated by the builder"
            )
        source_keys.add(source_key)
        archive_keys.add(archive_key)
        archive_casefold_keys.add(archive_casefold)
        mappings.append((source, archive))
    return sorted(mappings, key=lambda item: item[1].as_posix())


def _money(value: Any, *, label: str) -> Decimal:
    if not isinstance(value, str) or MONEY_PATTERN.fullmatch(value) is None:
        raise ArchiveValidationError(f"{label}: expected non-negative money string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ArchiveValidationError(f"{label}: invalid money value") from exc


def _signed_money(value: Any, *, label: str) -> Decimal:
    if not isinstance(value, str) or SIGNED_MONEY_PATTERN.fullmatch(value) is None:
        raise ArchiveValidationError(f"{label}: expected signed money string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ArchiveValidationError(f"{label}: invalid money value") from exc


def _validate_financial_truth(data: bytes, *, label: str) -> None:
    value = _json_object(data, label=label)
    required = {
        "schemaVersion",
        "recordKind",
        "candidateOnly",
        "canClaimAGI",
        "projectName",
        "eligibilityWindow",
        "observedThrough",
        "reportingBasis",
        "currency",
        "profitAndLoss",
        "userCounts",
        "monthlyBreakdown",
        "excludedTechnicalEvidence",
        "sources",
        "limitations",
    }
    if set(value) != required:
        raise ArchiveValidationError(f"{label}: unexpected financial properties")
    if value["schemaVersion"] != FINANCIAL_VERSION:
        raise ArchiveValidationError(f"{label}: unsupported financial schema")
    if value["recordKind"] != "xprize_financial_summary":
        raise ArchiveValidationError(f"{label}: invalid recordKind")
    if value["candidateOnly"] is not True or value["canClaimAGI"] is not False:
        raise ArchiveValidationError(f"{label}: claim guard flags changed")
    if value["currency"] != "USD":
        raise ArchiveValidationError(f"{label}: currency must be USD")

    profit_and_loss = value["profitAndLoss"]
    if not isinstance(profit_and_loss, dict):
        raise ArchiveValidationError(f"{label}: profitAndLoss must be an object")
    gross_revenue = _money(
        profit_and_loss.get("grossRecognizedRevenueUsd"),
        label=f"{label}.profitAndLoss.grossRecognizedRevenueUsd",
    )
    verified_expenses = _money(
        profit_and_loss.get("verifiedExpenseRecordsUsd"),
        label=f"{label}.profitAndLoss.verifiedExpenseRecordsUsd",
    )
    expense_completeness = profit_and_loss.get("expenseCompleteness")
    if expense_completeness not in {"complete", "unknown_total"}:
        raise ArchiveValidationError(f"{label}: invalid expense completeness")
    actual_expenses = profit_and_loss.get("actualTotalExpensesUsd")
    actual_net = profit_and_loss.get("actualNetProfitLossUsd")
    if expense_completeness == "unknown_total":
        if actual_expenses is not None or actual_net is not None:
            raise ArchiveValidationError(
                f"{label}: incomplete expenses require null actual P&L values"
            )
    else:
        actual_expense_value = _money(
            actual_expenses,
            label=f"{label}.profitAndLoss.actualTotalExpensesUsd",
        )
        actual_net_value = _signed_money(
            actual_net,
            label=f"{label}.profitAndLoss.actualNetProfitLossUsd",
        )
        expected_net = gross_revenue - actual_expense_value
        if actual_net_value != expected_net:
            raise ArchiveValidationError(f"{label}: actual net P&L mismatch")

    months = value["monthlyBreakdown"]
    expected_months = ("2026-05", "2026-06", "2026-07", "2026-08")
    if not isinstance(months, list) or tuple(
        item.get("month") for item in months if isinstance(item, dict)
    ) != expected_months:
        raise ArchiveValidationError(
            f"{label}: monthlyBreakdown must be May through August in order"
        )

    monthly_revenue = Decimal("0")
    monthly_verified_expenses = Decimal("0")
    for index, month in enumerate(months):
        month_label = f"{label}.monthlyBreakdown[{index}]"
        monthly_revenue += _money(
            month.get("qualifyingRecognizedRevenueUsd"),
            label=f"{month_label}.qualifyingRecognizedRevenueUsd",
        )
        monthly_verified_expenses += _money(
            month.get("verifiedExpenseRecordsUsd"),
            label=f"{month_label}.verifiedExpenseRecordsUsd",
        )
        if month.get("expenseCompleteness") == "unknown_total":
            if month.get("actualTotalExpensesUsd") is not None:
                raise ArchiveValidationError(
                    f"{month_label}: unknown expenses cannot be rendered as actual zero"
                )
        testnet = month.get("testnetEvidence")
        if not isinstance(testnet, dict):
            raise ArchiveValidationError(f"{month_label}: missing testnetEvidence")
        count = testnet.get("transferCount")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ArchiveValidationError(
                f"{month_label}.testnetEvidence.transferCount: invalid count"
            )
        _money(
            testnet.get("transferVolumeUsdc"),
            label=f"{month_label}.testnetEvidence.transferVolumeUsdc",
        )
        if testnet.get("countedAsRevenue") is not False:
            raise ArchiveValidationError(
                f"{month_label}: testnet evidence must never count as revenue"
            )
    if monthly_revenue != gross_revenue:
        raise ArchiveValidationError(f"{label}: monthly revenue does not reconcile")
    if monthly_verified_expenses != verified_expenses:
        raise ArchiveValidationError(
            f"{label}: monthly verified expenses do not reconcile"
        )


def _payloads(
    project_root: Path,
    spec_path: Path,
) -> dict[str, bytes]:
    project_root = project_root.resolve(strict=True)
    payloads: dict[str, bytes] = {}
    for source, archive in _load_spec(project_root, spec_path):
        source_path = _real_regular_file(
            project_root,
            source,
            label=f"source {source.as_posix()}",
        )
        data = source_path.read_bytes()
        archive_name = archive.as_posix()
        _scan_public_text(data, label=archive_name)
        payloads[archive_name] = data
    financial_path = f"{ARCHIVE_ROOT}/financial/may-august-breakdown.json"
    if financial_path not in payloads:
        raise ArchiveValidationError(
            f"archive spec must include {financial_path}"
        )
    _validate_financial_truth(payloads[financial_path], label=financial_path)
    return payloads


def _manifest(payloads: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "schemaVersion": MANIFEST_VERSION,
        "archiveRoot": ARCHIVE_ROOT,
        "deterministic": True,
        "fixedZipTimestamp": "1980-01-01T00:00:00Z",
        "hashAlgorithm": "sha256",
        "files": [
            {
                "path": path,
                "sha256": _sha256(data),
                "sizeBytes": len(data),
            }
            for path, data in sorted(payloads.items())
        ],
    }


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _write_archive(output_path: Path, payloads: Mapping[str, bytes]) -> None:
    requested_output = Path(os.path.abspath(output_path))
    requested_output.parent.mkdir(parents=True, exist_ok=True)
    if requested_output.exists() and (
        requested_output.is_symlink() or not requested_output.is_file()
    ):
        raise ArchiveValidationError(
            "archive output must be absent or a regular non-symlink file"
        )
    output_parent = requested_output.parent.resolve(strict=True)
    if not output_parent.is_dir():
        raise ArchiveValidationError("archive output parent must be a directory")
    output_path = output_parent / requested_output.name

    manifest_bytes = _canonical_json_bytes(_manifest(payloads))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for path, data in sorted(payloads.items()):
                archive.writestr(
                    _zip_info(path),
                    data,
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
            archive.writestr(
                _zip_info(MANIFEST_PATH),
                manifest_bytes,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
        os.replace(temporary_path, output_path)
        output_path.chmod(0o644)
    finally:
        temporary_path.unlink(missing_ok=True)


def verify_archive(archive_path: Path) -> dict[str, Any]:
    """Verify paths, metadata, public text, and every manifest-bound payload hash."""

    if archive_path.is_symlink() or not archive_path.is_file():
        raise ArchiveValidationError(
            "archive must be a regular non-symlink file"
        )
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ArchiveValidationError("archive contains duplicate paths")
            casefolded_names = [name.casefold() for name in names]
            if len(casefolded_names) != len(set(casefolded_names)):
                raise ArchiveValidationError(
                    "archive contains case-insensitive duplicate paths"
                )
            payloads: dict[str, bytes] = {}
            for info in infos:
                pure = _relative_posix(info.filename, label="archive member")
                _reject_prohibited_path(pure, label=f"archive member {info.filename}")
                if not pure.parts or pure.parts[0] != ARCHIVE_ROOT:
                    raise ArchiveValidationError(
                        "archive member is outside Product_Evidence/"
                    )
                if info.is_dir():
                    raise ArchiveValidationError(
                        "archive must contain files, not directory entries"
                    )
                if info.date_time != FIXED_ZIP_TIMESTAMP:
                    raise ArchiveValidationError(
                        f"{info.filename}: non-deterministic timestamp"
                    )
                if info.flag_bits & 0x1:
                    raise ArchiveValidationError(
                        f"{info.filename}: encrypted ZIP entries are not allowed"
                    )
                mode = info.external_attr >> 16
                if not stat.S_ISREG(mode):
                    raise ArchiveValidationError(
                        f"{info.filename}: non-regular ZIP member"
                    )
                data = archive.read(info)
                _scan_public_text(data, label=info.filename)
                payloads[info.filename] = data
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError("invalid ZIP archive") from exc

    if MANIFEST_PATH not in payloads:
        raise ArchiveValidationError("archive manifest is missing")
    manifest = _json_object(payloads.pop(MANIFEST_PATH), label=MANIFEST_PATH)
    if set(manifest) != {
        "schemaVersion",
        "archiveRoot",
        "deterministic",
        "fixedZipTimestamp",
        "hashAlgorithm",
        "files",
    }:
        raise ArchiveValidationError("archive manifest has unexpected properties")
    if (
        manifest["schemaVersion"] != MANIFEST_VERSION
        or manifest["archiveRoot"] != ARCHIVE_ROOT
        or manifest["deterministic"] is not True
        or manifest["fixedZipTimestamp"] != "1980-01-01T00:00:00Z"
        or manifest["hashAlgorithm"] != "sha256"
    ):
        raise ArchiveValidationError("archive manifest metadata changed")
    if not isinstance(manifest["files"], list):
        raise ArchiveValidationError("archive manifest files must be a list")

    expected_paths: set[str] = set()
    for index, item in enumerate(manifest["files"]):
        label = f"archive manifest files[{index}]"
        if not isinstance(item, dict) or set(item) != {
            "path",
            "sha256",
            "sizeBytes",
        }:
            raise ArchiveValidationError(f"{label}: unexpected properties")
        path = item["path"]
        if not isinstance(path, str) or path in expected_paths:
            raise ArchiveValidationError(f"{label}: duplicate or invalid path")
        expected_paths.add(path)
        if path not in payloads:
            raise ArchiveValidationError(f"{label}: payload is missing")
        data = payloads[path]
        if item["sha256"] != _sha256(data) or item["sizeBytes"] != len(data):
            raise ArchiveValidationError(f"{path}: manifest hash/size mismatch")
    if expected_paths != set(payloads):
        raise ArchiveValidationError("archive contains unmanifested payloads")

    financial_path = f"{ARCHIVE_ROOT}/financial/may-august-breakdown.json"
    _validate_financial_truth(payloads[financial_path], label=financial_path)
    return manifest


def build_archive(
    *,
    project_root: Path = ROOT,
    spec_path: Path = DEFAULT_SPEC,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Build the archive and immediately verify every generated manifest hash."""

    payloads = _payloads(project_root, spec_path)
    _write_archive(output_path, payloads)
    return verify_archive(output_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic Product_Evidence ZIP from an explicit "
            "public-text allowlist, or verify an existing ZIP."
        )
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help=f"archive allowlist spec (default: {DEFAULT_SPEC})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"archive output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="verify an existing archive instead of building",
    )
    args = parser.parse_args(argv)

    manifest: dict[str, Any] | None = None
    digest: str | None = None
    try:
        if args.verify is not None:
            manifest = verify_archive(args.verify)
            archive_path = args.verify
        else:
            manifest = build_archive(
                project_root=ROOT,
                spec_path=args.spec,
                output_path=args.output,
            )
            archive_path = args.output
        digest = _sha256(archive_path.read_bytes())
    except (OSError, ArchiveValidationError) as exc:
        parser.error(str(exc))

    if manifest is None or digest is None:
        raise AssertionError("archive command completed without a result")
    print(
        f"XPRIZE PRODUCT EVIDENCE: PASS "
        f"files={len(manifest['files'])} sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
