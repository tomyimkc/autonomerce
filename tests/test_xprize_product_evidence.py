from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
FINANCIAL_PATH = (
    ROOT
    / "Product_Evidence"
    / "financial"
    / "may-august-breakdown.json"
)
CIRCLE_PATH = (
    ROOT
    / "evidence"
    / "public"
    / "circle-arc-testnet-transaction.public.json"
)
sys.path.insert(0, str(ROOT / "scripts"))

import build_xprize_product_evidence as builder  # noqa: E402


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_spec(
    root: Path,
    *,
    extra_source: str = "Product_Evidence/README.md",
    extra_archive: str = "Product_Evidence/README.md",
    extra_content: str = "safe public evidence\n",
) -> Path:
    financial = root / "Product_Evidence" / "financial"
    financial.mkdir(parents=True)
    (financial / "may-august-breakdown.json").write_text(
        FINANCIAL_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    if (
        not extra_source.startswith("/")
        and "\\" not in extra_source
        and ".." not in Path(extra_source).parts
        and not extra_source.startswith("evidence/private/")
    ):
        source_path = root / extra_source
        if extra_source != "Product_Evidence/financial/may-august-breakdown.json":
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(extra_content, encoding="utf-8")

    spec = root / "Product_Evidence" / "archive-files.json"
    spec.write_text(
        json.dumps(
            {
                "schemaVersion": builder.SPEC_VERSION,
                "archiveRoot": builder.ARCHIVE_ROOT,
                "files": [
                    {
                        "source": extra_source,
                        "archive": extra_archive,
                    },
                    {
                        "source": (
                            "Product_Evidence/financial/"
                            "may-august-breakdown.json"
                        ),
                        "archive": (
                            "Product_Evidence/financial/"
                            "may-august-breakdown.json"
                        ),
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return spec


def test_archive_is_byte_deterministic_and_manifest_hashes_verify(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_manifest = builder.build_archive(output_path=first)
    second_manifest = builder.build_archive(output_path=second)

    assert first.read_bytes() == second.read_bytes()
    assert first_manifest == second_manifest
    assert builder.verify_archive(first) == first_manifest
    assert len(first_manifest["files"]) == 17

    with zipfile.ZipFile(first, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names[:-1]) + [builder.MANIFEST_PATH]
        assert builder.MANIFEST_PATH in names
        assert all(name.startswith("Product_Evidence/") for name in names)
        assert all("/private/" not in name.casefold() for name in names)
        assert all(
            info.date_time == builder.FIXED_ZIP_TIMESTAMP for info in infos
        )
        assert all(
            stat.S_ISREG(info.external_attr >> 16) for info in infos
        )
        manifest = json.loads(archive.read(builder.MANIFEST_PATH))
        for item in manifest["files"]:
            data = archive.read(item["path"])
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
            assert len(data) == item["sizeBytes"]


def test_archive_verifier_rejects_payload_tampering(tmp_path):
    original = tmp_path / "original.zip"
    tampered = tmp_path / "tampered.zip"
    builder.build_archive(output_path=original)

    with (
        zipfile.ZipFile(original, "r") as source,
        zipfile.ZipFile(tampered, "w") as destination,
    ):
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "Product_Evidence/README.md":
                data += b"tampered\n"
            destination.writestr(info, data)

    with pytest.raises(
        builder.ArchiveValidationError,
        match="manifest hash/size mismatch",
    ):
        builder.verify_archive(tampered)


def test_archive_verifier_rejects_case_insensitive_duplicate_paths(tmp_path):
    archive_path = tmp_path / "case-collision.zip"
    builder.build_archive(output_path=archive_path)

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(
            builder._zip_info("Product_Evidence/readme.md"),
            b"case-colliding public evidence\n",
        )

    with pytest.raises(
        builder.ArchiveValidationError,
        match="case-insensitive duplicate paths",
    ):
        builder.verify_archive(archive_path)


def test_archive_verifier_rejects_oversized_member_before_read(
    tmp_path,
    monkeypatch,
):
    archive_path = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            builder._zip_info("Product_Evidence/oversized.txt"),
            b"x" * (builder.MAX_FILE_BYTES + 1),
        )

    def fail_if_opened(*_args, **_kwargs):
        raise AssertionError("oversized ZIP member was opened")

    monkeypatch.setattr(builder.zipfile.ZipFile, "open", fail_if_opened)
    with pytest.raises(
        builder.ArchiveValidationError,
        match="file exceeds public archive limit",
    ):
        builder.verify_archive(archive_path)


def test_archive_verifier_bounds_every_decompressed_member(tmp_path, monkeypatch):
    archive_path = tmp_path / "bounded-read.zip"
    builder.build_archive(output_path=archive_path)
    original_read = builder.zipfile.ZipExtFile.read
    requested_sizes = []

    def record_bounded_read(member, size=-1):
        requested_sizes.append(size)
        return original_read(member, size)

    monkeypatch.setattr(builder.zipfile.ZipExtFile, "read", record_bounded_read)
    builder.verify_archive(archive_path)

    assert requested_sizes
    assert all(
        0 < requested_size <= builder.MAX_FILE_BYTES + 1
        for requested_size in requested_sizes
    )


def test_archive_verifier_rejects_unsupported_compression(tmp_path):
    archive_path = tmp_path / "stored.zip"
    info = builder._zip_info("Product_Evidence/stored.txt")
    info.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"safe but non-deterministic compression\n")

    with pytest.raises(
        builder.ArchiveValidationError,
        match="unsupported ZIP compression",
    ):
        builder.verify_archive(archive_path)


def test_archive_verifier_rejects_unsorted_manifest_paths(tmp_path):
    original = tmp_path / "original.zip"
    unsorted = tmp_path / "unsorted-manifest.zip"
    builder.build_archive(output_path=original)

    with (
        zipfile.ZipFile(original, "r") as source,
        zipfile.ZipFile(unsorted, "w") as destination,
    ):
        for info in source.infolist():
            data = source.read(info)
            if info.filename == builder.MANIFEST_PATH:
                manifest = json.loads(data)
                manifest["files"].reverse()
                data = builder._canonical_json_bytes(manifest)
            destination.writestr(info, data)

    with pytest.raises(
        builder.ArchiveValidationError,
        match="manifest files must be sorted",
    ):
        builder.verify_archive(unsorted)


@pytest.mark.parametrize(
    ("source", "archive", "message"),
    [
        ("../outside.txt", "Product_Evidence/outside.txt", "remain relative"),
        ("/absolute.txt", "Product_Evidence/absolute.txt", "unsafe path"),
        (
            "evidence/private/okf/record.json",
            "Product_Evidence/record.json",
            "prohibited private/generated path",
        ),
        (
            "Product_Evidence\\README.md",
            "Product_Evidence/README.md",
            "unsafe path",
        ),
        (
            "Product_Evidence/README.md",
            "../escaped.txt",
            "remain relative",
        ),
    ],
)
def test_archive_spec_rejects_unsafe_paths(
    tmp_path,
    source,
    archive,
    message,
):
    root = tmp_path / "project"
    root.mkdir()
    spec = _write_spec(root, extra_source=source, extra_archive=archive)

    with pytest.raises(builder.ArchiveValidationError, match=message):
        builder.build_archive(
            project_root=root,
            spec_path=spec,
            output_path=tmp_path / "unsafe.zip",
        )


def test_archive_rejects_source_file_symlink(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    spec = _write_spec(root)
    readme = root / "Product_Evidence" / "README.md"
    target = root / "safe-target.md"
    target.write_text("safe target\n", encoding="utf-8")
    readme.unlink()
    readme.symlink_to(target)

    with pytest.raises(builder.ArchiveValidationError, match="symlinks"):
        builder.build_archive(
            project_root=root,
            spec_path=spec,
            output_path=tmp_path / "symlink.zip",
        )


def test_archive_rejects_symlinked_source_parent(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    spec = _write_spec(
        root,
        extra_source="Product_Evidence/linked/README.md",
        extra_archive="Product_Evidence/README.md",
    )
    linked = root / "Product_Evidence" / "linked"
    real = root / "real"
    real.mkdir()
    (real / "README.md").write_text("safe target\n", encoding="utf-8")
    (linked / "README.md").unlink()
    linked.rmdir()
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(builder.ArchiveValidationError, match="symlinks"):
        builder.build_archive(
            project_root=root,
            spec_path=spec,
            output_path=tmp_path / "parent-symlink.zip",
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("api_key = abcdefghijklmnop\n", "assigned-secret"),  # secret-scan: allow-test-fixture
        ("contact owner@example.com\n", "email-address"),
        ("artifact at /Users/alice/private.txt\n", "local-home-path"),
        ("binary\x00content", "binary/NUL"),
    ],
)
def test_archive_rejects_secret_pii_and_binary_content(
    tmp_path,
    content,
    message,
):
    root = tmp_path / "project"
    root.mkdir()
    spec = _write_spec(
        root,
        extra_source="Product_Evidence/unsafe.txt",
        extra_archive="Product_Evidence/unsafe.txt",
        extra_content=content,
    )

    with pytest.raises(builder.ArchiveValidationError, match=message):
        builder.build_archive(
            project_root=root,
            spec_path=spec,
            output_path=tmp_path / "unsafe-content.zip",
        )


def test_financial_summary_preserves_zero_and_unknown_boundaries():
    financial = _load(FINANCIAL_PATH)
    circle = _load(CIRCLE_PATH)

    assert financial["candidateOnly"] is True
    assert financial["canClaimAGI"] is False
    assert financial["profitAndLoss"] == {
        "actualNetProfitLossUsd": None,
        "actualTotalExpensesUsd": None,
        "expenseCompleteness": "unknown_total",
        "grossRecognizedRevenueUsd": "0",
        "verifiedExpenseRecordsUsd": "0",
    }
    assert financial["userCounts"] == {
        "verifiedExternalCustomers": 0,
        "verifiedExternalDesignPartners": 0,
        "verifiedExternalUsers": 0,
        "verifiedPayingCustomers": 0,
        "verifiedPayingUsers": 0,
    }
    assert [item["month"] for item in financial["monthlyBreakdown"]] == [
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
    ]
    assert all(
        item["qualifyingRecognizedRevenueUsd"] == "0"
        for item in financial["monthlyBreakdown"]
    )
    assert all(
        item["verifiedExpenseRecordsUsd"] == "0"
        and item["actualTotalExpensesUsd"] is None
        and item["verifiedExternalUsers"] == 0
        and item["verifiedPayingUsers"] == 0
        for item in financial["monthlyBreakdown"]
    )

    july = financial["monthlyBreakdown"][2]
    assert july["testnetEvidence"] == {
        "countedAsRevenue": False,
        "transferCount": 1,
        "transferVolumeUsdc": "0.1",
    }
    excluded = financial["excludedTechnicalEvidence"][0]
    assert excluded["amountUsdc"] == circle["amountUsdc"] == "0.1"
    assert excluded["network"] == circle["network"] == "ARC-TESTNET"
    assert excluded["occurredAt"] == circle["confirmedAt"]
    assert excluded["customerRelationship"] == circle["customerRelationship"]
    assert excluded["countedAsRevenue"] is circle["countedAsRevenue"] is False
    assert excluded["externalCustomer"] is circle["externalCustomer"] is False

    builder._validate_financial_truth(
        FINANCIAL_PATH.read_bytes(),
        label="financial",
    )


def test_financial_truth_rejects_testnet_revenue_and_inferred_expense_zero():
    financial = _load(FINANCIAL_PATH)

    testnet_as_revenue = deepcopy(financial)
    testnet_as_revenue["monthlyBreakdown"][2]["testnetEvidence"][
        "countedAsRevenue"
    ] = True
    with pytest.raises(
        builder.ArchiveValidationError,
        match="testnet evidence must never count as revenue",
    ):
        builder._validate_financial_truth(
            builder._canonical_json_bytes(testnet_as_revenue),
            label="financial",
        )

    inferred_zero = deepcopy(financial)
    inferred_zero["profitAndLoss"]["actualTotalExpensesUsd"] = "0"
    inferred_zero["profitAndLoss"]["actualNetProfitLossUsd"] = "0"
    with pytest.raises(
        builder.ArchiveValidationError,
        match="incomplete expenses require null actual P&L",
    ):
        builder._validate_financial_truth(
            builder._canonical_json_bytes(inferred_zero),
            label="financial",
        )


def test_financial_truth_rejects_unexpected_nested_properties():
    financial = _load(FINANCIAL_PATH)
    cases = [
        ("eligibilityWindow", lambda value: value["eligibilityWindow"]),
        ("profitAndLoss", lambda value: value["profitAndLoss"]),
        ("userCounts", lambda value: value["userCounts"]),
        (
            r"excludedTechnicalEvidence\[0\]",
            lambda value: value["excludedTechnicalEvidence"][0],
        ),
        (
            r"monthlyBreakdown\[0\]",
            lambda value: value["monthlyBreakdown"][0],
        ),
        (
            r"monthlyBreakdown\[0\]\.testnetEvidence",
            lambda value: value["monthlyBreakdown"][0]["testnetEvidence"],
        ),
    ]

    for label, nested_object in cases:
        unexpected = deepcopy(financial)
        nested_object(unexpected)["unreviewedField"] = "value"
        with pytest.raises(
            builder.ArchiveValidationError,
            match=rf"{label}: unexpected properties",
        ):
            builder._validate_financial_truth(
                builder._canonical_json_bytes(unexpected),
                label="financial",
            )


@pytest.mark.parametrize("invalid_net", [None, {}, "not-money"])
def test_financial_truth_rejects_invalid_complete_actual_net(invalid_net):
    financial = _load(FINANCIAL_PATH)
    financial["profitAndLoss"].update(
        {
            "expenseCompleteness": "complete",
            "actualTotalExpensesUsd": "0",
            "actualNetProfitLossUsd": invalid_net,
        }
    )

    with pytest.raises(
        builder.ArchiveValidationError,
        match="actualNetProfitLossUsd: expected signed money string",
    ):
        builder._validate_financial_truth(
            builder._canonical_json_bytes(financial),
            label="financial",
        )


def test_financial_truth_accepts_reconciled_net_loss():
    financial = _load(FINANCIAL_PATH)
    financial["profitAndLoss"].update(
        {
            "expenseCompleteness": "complete",
            "actualTotalExpensesUsd": "1",
            "actualNetProfitLossUsd": "-1",
        }
    )

    builder._validate_financial_truth(
        builder._canonical_json_bytes(financial),
        label="financial",
    )
