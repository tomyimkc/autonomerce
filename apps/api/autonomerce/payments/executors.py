"""Credential-free mock execution and a guarded Circle CLI adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
from typing import Any, Mapping, Protocol

from autonomerce.contracts import usdc, usdc_text

from .errors import (
    CircleExecutionError,
    PaymentValidationError,
    SubmissionStatus,
)
from .models import (
    KNOWN_USDC_ASSETS,
    ExecutionResult,
    PaymentIntent,
    PaymentMode,
    canonical_chain,
    is_mainnet_chain,
    is_testnet_chain,
    normalize_asset_contract,
    normalize_token,
    normalize_transaction_hash,
    normalize_wallet_address,
)
from .redaction import redact_text


Clock = Callable[[], datetime]
Runner = Callable[..., subprocess.CompletedProcess[str]]
MAINNET_CONFIRMATION = "ENABLE_REAL_MAINNET_PAYMENTS"
DEFAULT_CIRCLE_BINARY = "/usr/local/bin/circle"
DEFAULT_CIRCLE_CWD = "/"
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
_MIN_OUTPUT_BYTES = 1024
_MAX_OUTPUT_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 8192
_FIXED_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
_INHERITED_ENVIRONMENT_KEYS = (
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "CIRCLE_API_KEY",
    "CIRCLE_BASE_URL",
)
_ALLOWED_ENVIRONMENT_KEYS = frozenset(
    (*_INHERITED_ENVIRONMENT_KEYS, "PATH")
)
_PRE_SUBMISSION_CODES = {
    "insufficient_balance": "insufficient_balance",
    "insufficient_funds": "insufficient_balance",
    "wallet_policy_denied": "policy_denied",
    "policy_denied": "policy_denied",
    "policy_rejected": "policy_denied",
    "invalid_configuration": "invalid_configuration",
    "configuration_error": "invalid_configuration",
    "invalid_config": "invalid_configuration",
    "authentication_failed": "authentication_failed",
    "not_authenticated": "authentication_failed",
    "invalid_request": "invalid_request",
    "invalid_argument": "invalid_request",
    "validation_error": "invalid_request",
    "wallet_not_found": "invalid_configuration",
    "unsupported_chain": "invalid_configuration",
}
_NO_SUBMISSION_TEXT = re.compile(
    r"(?i)\b(?:no|not)\s+(?:transfer|transaction|payment)\s+"
    r"(?:was\s+)?submitted\b|\bsubmission\s+(?:did\s+not|never)\s+occur(?:red)?\b"
)
_TEXT_REJECTION_REASONS = (
    (re.compile(r"(?i)\binsufficient\s+(?:balance|funds)\b"), "insufficient_balance"),
    (re.compile(r"(?i)\b(?:wallet\s+)?policy\s+(?:denied|rejected)\b"), "policy_denied"),
    (re.compile(r"(?i)\binvalid\s+(?:configuration|config)\b"), "invalid_configuration"),
    (
        re.compile(r"(?i)\b(?:authentication\s+failed|not\s+authenticated)\b"),
        "authentication_failed",
    ),
    (re.compile(r"(?i)\binvalid\s+(?:request|argument|command)\b"), "invalid_request"),
)
_UNSET_BINARY = object()
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_TOKEN_OUTPUT_KEYS = ("token", "tokenSymbol", "currency", "assetSymbol")
_ASSET_OUTPUT_KEYS = ("asset", "assetAddress", "tokenAddress", "contractAddress")


class _OutputLimitExceeded(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(clock: Clock) -> str:
    return clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_circle_binary_sha256(binary: str | Path, expected_sha256: str) -> str:
    """Resolve and hash one executable, returning its immutable argv path."""

    expected = str(expected_sha256).strip().lower()
    if not _SHA256.fullmatch(expected):
        raise PaymentValidationError(
            "Circle CLI SHA-256 must be exactly 64 lowercase hexadecimal characters"
        )
    try:
        path = Path(binary).resolve(strict=True)
    except OSError as exc:
        raise PaymentValidationError("Circle CLI executable does not exist") from exc
    if not path.is_file() or not os.access(path, os.X_OK):
        raise PaymentValidationError(
            "Circle CLI path must resolve to an executable regular file"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as executable:
            for chunk in iter(lambda: executable.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PaymentValidationError("Circle CLI executable could not be hashed") from exc
    if not hmac.compare_digest(digest.hexdigest(), expected):
        raise PaymentValidationError("Circle CLI SHA-256 does not match the pinned value")
    return str(path)


def _canonical_usdc_assets(
    values: Mapping[str, str] | None,
) -> dict[str, str]:
    assets: dict[str, str] = {}
    source = values or {
        chain: chain_assets[0]
        for chain, chain_assets in KNOWN_USDC_ASSETS.items()
        if chain_assets
    }
    for raw_chain, raw_asset in source.items():
        chain = canonical_chain(raw_chain)
        asset = normalize_asset_contract(raw_asset, chain, token="USDC")
        if asset is None or asset == "USDC":
            raise PaymentValidationError(
                f"canonical USDC asset for {chain} must be a contract address"
            )
        assets[chain] = asset
    if not assets:
        raise PaymentValidationError(
            "live Circle execution requires configured canonical USDC assets"
        )
    return assets


def _evidence_values(
    data: Mapping[str, Any],
    amount_entry: Mapping[str, Any] | None,
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for source in (data, amount_entry or {}):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                values.append(str(value).strip())
    return tuple(dict.fromkeys(values))


def _verify_optional_asset_descriptors(
    *,
    token_values: tuple[str, ...],
    asset_values: tuple[str, ...],
    chain: str,
    expected_token: str,
    expected_asset: str,
) -> None:
    """Reject any explicit CLI descriptor that is not the bound canonical USDC."""

    for label, values in (("token", token_values), ("asset", asset_values)):
        for value in values:
            if _EVM_ADDRESS.fullmatch(value):
                actual_asset = normalize_asset_contract(
                    value, chain, token=expected_token
                )
                if actual_asset != expected_asset:
                    raise CircleExecutionError(
                        f"Circle CLI confirmed an unexpected {label} contract",
                        reason_code="circle_cli_asset_mismatch",
                    )
            elif normalize_token(value) != expected_token:
                raise CircleExecutionError(
                    f"Circle CLI confirmed an unexpected {label}",
                    reason_code="circle_cli_token_mismatch",
                )


def _minimal_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = {"PATH": _FIXED_PATH, "LANG": "C.UTF-8"}
    for name in _INHERITED_ENVIRONMENT_KEYS:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    if overrides:
        unknown = sorted(set(overrides) - _ALLOWED_ENVIRONMENT_KEYS)
        if unknown:
            raise PaymentValidationError(
                "Circle CLI environment contains non-allowlisted keys: "
                + ", ".join(unknown)
            )
        for name, value in overrides.items():
            text = str(value)
            if "\x00" in text:
                raise PaymentValidationError(
                    f"Circle CLI environment value contains NUL: {name}"
                )
            environment[name] = text
    return environment


def _stop_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        # This is the exact child process created by this executor, not an
        # arbitrary system PID.
        process.kill()
        process.wait(timeout=1)


def _bounded_subprocess_run(
    argv: list[str],
    *,
    timeout: int,
    environment: Mapping[str, str],
    working_directory: str,
    max_output_bytes: int,
) -> subprocess.CompletedProcess[str]:
    """Run one child while enforcing hard per-stream output limits."""

    process = subprocess.Popen(
        argv,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=working_directory,
        env=dict(environment),
        text=False,
        close_fds=True,
    )
    if process.stdout is None or process.stderr is None:
        _stop_child(process)
        raise OSError("Circle CLI output pipes were not created")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_child(process)
                raise subprocess.TimeoutExpired(
                    argv,
                    timeout,
                    output=bytes(output["stdout"]),
                    stderr=bytes(output["stderr"]),
                )
            events = selector.select(min(remaining, 0.25))
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), _READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = output[key.data]
                remaining_capacity = max_output_bytes - len(target)
                if len(chunk) > remaining_capacity:
                    if remaining_capacity > 0:
                        target.extend(chunk[:remaining_capacity])
                    _stop_child(process)
                    raise _OutputLimitExceeded(
                        f"Circle CLI {key.data} exceeded {max_output_bytes} bytes"
                    )
                target.extend(chunk)
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _stop_child(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()

    return subprocess.CompletedProcess(
        argv,
        returncode,
        bytes(output["stdout"]).decode("utf-8", errors="replace"),
        bytes(output["stderr"]).decode("utf-8", errors="replace"),
    )


def _completed_text(value: Any, *, max_output_bytes: int, stream: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        encoded = value
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
        encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > max_output_bytes:
        raise _OutputLimitExceeded(
            f"Circle CLI {stream} exceeded {max_output_bytes} bytes"
        )
    return text


def _normalized_code(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _structured_rejection(
    stdout: str,
    stderr: str,
) -> tuple[str, SubmissionStatus] | None:
    for raw in (stderr, stdout):
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        queue: list[tuple[Any, int]] = [(payload, 0)]
        codes: list[str] = []
        explicitly_not_submitted = False
        explicitly_submitted = False
        visited = 0
        while queue and visited < 256:
            value, depth = queue.pop(0)
            visited += 1
            if depth > 8:
                continue
            if isinstance(value, Mapping):
                for key, item in value.items():
                    normalized_key = _normalized_code(key)
                    if normalized_key in {
                        "code",
                        "error_code",
                        "reason_code",
                        "reason",
                        "type",
                    }:
                        codes.append(_normalized_code(item))
                    if normalized_key in {
                        "submitted",
                        "transfer_submitted",
                        "transaction_submitted",
                        "payment_submitted",
                    }:
                        if item is False:
                            explicitly_not_submitted = True
                        elif item is True:
                            explicitly_submitted = True
                    if normalized_key in {"state", "status", "stage", "phase"}:
                        normalized_value = _normalized_code(item)
                        if normalized_value in {
                            "not_submitted",
                            "pre_submit",
                            "pre_submission",
                            "validation",
                            "configuration",
                        }:
                            explicitly_not_submitted = True
                        elif normalized_value in {
                            "submitted",
                            "pending",
                            "processing",
                            "broadcast",
                            "broadcasted",
                        }:
                            explicitly_submitted = True
                    if isinstance(item, (Mapping, list, tuple)):
                        queue.append((item, depth + 1))
            elif isinstance(value, (list, tuple)):
                queue.extend((item, depth + 1) for item in value)
        if explicitly_submitted:
            continue
        if explicitly_not_submitted:
            for code in codes:
                mapped = _PRE_SUBMISSION_CODES.get(code)
                if mapped:
                    return (
                        f"circle_cli_{mapped}",
                        SubmissionStatus.NOT_SUBMITTED,
                    )
            return "circle_cli_not_submitted", SubmissionStatus.NOT_SUBMITTED
        for code in codes:
            mapped = _PRE_SUBMISSION_CODES.get(code)
            if mapped:
                return f"circle_cli_{mapped}", SubmissionStatus.NOT_SUBMITTED
    return None


def _classify_rejection(
    stdout: str,
    stderr: str,
) -> tuple[str, SubmissionStatus]:
    structured = _structured_rejection(stdout, stderr)
    if structured is not None:
        return structured
    combined = "\n".join(value for value in (stderr, stdout) if value)
    if _NO_SUBMISSION_TEXT.search(combined):
        for pattern, reason in _TEXT_REJECTION_REASONS:
            if pattern.search(combined):
                return (
                    f"circle_cli_{reason}",
                    SubmissionStatus.NOT_SUBMITTED,
                )
        return "circle_cli_not_submitted", SubmissionStatus.NOT_SUBMITTED
    return "circle_cli_rejection_ambiguous", SubmissionStatus.AMBIGUOUS


class CircleExecutor(Protocol):
    mode: PaymentMode

    def execute(self, intent: PaymentIntent) -> ExecutionResult: ...


class OfflineCircleExecutor:
    """Deterministic Circle mock that performs no I/O and moves no funds."""

    mode = PaymentMode.OFFLINE

    def __init__(
        self,
        *,
        clock: Clock = _utc_now,
        fail_payment_ids: Sequence[str] = (),
    ) -> None:
        self.clock = clock
        self.fail_payment_ids = frozenset(fail_payment_ids)
        self.calls: list[PaymentIntent] = []

    def execute(self, intent: PaymentIntent) -> ExecutionResult:
        self.calls.append(intent)
        if intent.payment_id in self.fail_payment_ids:
            raise CircleExecutionError(
                "offline Circle executor injected failure",
                terminal=True,
                reason_code="offline_injected_failure",
            )
        digest = hashlib.sha256(
            f"autonomerce-offline:{intent.fingerprint}".encode("utf-8")
        ).hexdigest()
        return ExecutionResult(
            state="CONFIRMED",
            amount_usdc=intent.amount_usdc,
            chain=intent.chain,
            payer_wallet=intent.payer_wallet,
            payee_wallet=intent.payee_wallet,
            transaction_hash=f"0x{digest}",
            confirmed_at=_timestamp(self.clock),
            simulated=True,
            provider_reference=f"offline:{intent.payment_id}",
            raw={"provider": "circle-mock", "simulated": True},
            token=intent.token,
            asset=intent.asset,
        )


class CircleCLIExecutor:
    """Execute one pre-authorized USDC transfer via safe subprocess argv.

    The adapter never invokes a shell, never accepts arbitrary extra arguments, omits
    `--token` so Circle's USDC default is used, and requires an exact confirmed JSON
    response whose amount/chain/source/destination match the authorized intent.
    """

    def __init__(
        self,
        *,
        mode: PaymentMode | str,
        binary: str | None | object = _UNSET_BINARY,
        timeout_seconds: int = 120,
        runner: Runner | None = None,
        clock: Clock = _utc_now,
        allow_mainnet: bool = False,
        mainnet_confirmation: str | None = None,
        working_directory: str | Path = DEFAULT_CIRCLE_CWD,
        environment: Mapping[str, str] | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        canonical_usdc_assets_by_chain: Mapping[str, str] | None = None,
        binary_sha256: str | None = None,
    ) -> None:
        self.mode = PaymentMode.parse(mode)
        if self.mode is PaymentMode.OFFLINE:
            raise PaymentValidationError(
                "CircleCLIExecutor cannot be used in offline mode"
            )
        if (
            self.mode is PaymentMode.MAINNET
            and (
                not allow_mainnet
                or mainnet_confirmation != MAINNET_CONFIRMATION
            )
        ):
            raise PaymentValidationError(
                "mainnet Circle CLI execution requires two explicit opt-ins"
            )
        if binary is _UNSET_BINARY:
            # Dependency-injected runners may use a logical command name in unit
            # tests. Real subprocess execution always uses an absolute path.
            binary = "circle" if runner is not None else DEFAULT_CIRCLE_BINARY
        elif binary is None or not Path(binary).is_absolute():
            raise PaymentValidationError(
                "live Circle CLI execution requires an absolute executable path"
            )
        if not str(binary).strip() or "\x00" in str(binary):
            raise PaymentValidationError("Circle CLI binary path is invalid")
        self.canonical_usdc_assets_by_chain = _canonical_usdc_assets(
            canonical_usdc_assets_by_chain
        )
        self.binary_sha256 = (
            str(binary_sha256).strip().lower() if binary_sha256 is not None else None
        )
        if runner is None:
            if self.binary_sha256 is None:
                raise PaymentValidationError(
                    "live Circle CLI execution requires a pinned executable SHA-256"
                )
            binary = verify_circle_binary_sha256(str(binary), self.binary_sha256)
        if timeout_seconds < 1 or timeout_seconds > 900:
            raise PaymentValidationError("Circle CLI timeout is outside safe bounds")
        if max_output_bytes < _MIN_OUTPUT_BYTES or max_output_bytes > _MAX_OUTPUT_BYTES:
            raise PaymentValidationError(
                "Circle CLI output cap is outside safe bounds"
            )
        cwd = Path(working_directory)
        if not cwd.is_absolute() or not cwd.is_dir():
            raise PaymentValidationError(
                "Circle CLI working directory must be an existing absolute directory"
            )
        self.binary = str(binary)
        self.timeout_seconds = timeout_seconds
        self.runner = runner
        self._uses_bounded_runner = runner is None
        self.clock = clock
        self.working_directory = str(cwd)
        self.environment = _minimal_environment(environment)
        self.max_output_bytes = max_output_bytes

    def build_argv(self, intent: PaymentIntent) -> list[str]:
        if self.mode is PaymentMode.TESTNET and not is_testnet_chain(intent.chain):
            raise PaymentValidationError("testnet executor refuses a mainnet chain")
        if self.mode is PaymentMode.MAINNET and not is_mainnet_chain(intent.chain):
            raise PaymentValidationError("mainnet executor refuses a testnet chain")
        if intent.token != "USDC":
            raise PaymentValidationError("Circle CLI payment lane supports USDC only")
        expected_asset = self.canonical_usdc_assets_by_chain.get(intent.chain)
        if expected_asset is None:
            raise PaymentValidationError(
                f"no canonical USDC asset is configured for {intent.chain}"
            )
        if intent.asset != expected_asset:
            raise PaymentValidationError(
                "payment intent asset does not match configured canonical USDC"
            )
        return [
            self.binary,
            "wallet",
            "transfer",
            intent.payee_wallet,
            "--amount",
            usdc_text(intent.amount_usdc),
            "--address",
            intent.payer_wallet,
            "--chain",
            intent.chain,
            "--output",
            "json",
        ]

    def execute(self, intent: PaymentIntent) -> ExecutionResult:
        argv = self.build_argv(intent)
        expected_asset = self.canonical_usdc_assets_by_chain[intent.chain]
        try:
            if self._uses_bounded_runner:
                # Re-hash immediately before every transfer so a post-startup binary
                # replacement cannot silently bypass the startup preflight.
                verify_circle_binary_sha256(self.binary, self.binary_sha256 or "")
                completed = _bounded_subprocess_run(
                    argv,
                    timeout=self.timeout_seconds,
                    environment=self.environment,
                    working_directory=self.working_directory,
                    max_output_bytes=self.max_output_bytes,
                )
            else:
                completed = self.runner(
                    argv,
                    shell=False,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=dict(self.environment),
                    cwd=self.working_directory,
                )
            stdout = _completed_text(
                completed.stdout,
                max_output_bytes=self.max_output_bytes,
                stream="stdout",
            )
            stderr = _completed_text(
                completed.stderr,
                max_output_bytes=self.max_output_bytes,
                stream="stderr",
            )
        except _OutputLimitExceeded as exc:
            raise CircleExecutionError(
                str(exc) + "; settlement status is ambiguous",
                reason_code="circle_cli_output_limit",
                submission_status=SubmissionStatus.AMBIGUOUS,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CircleExecutionError(
                "Circle CLI timed out; settlement status is ambiguous",
                reason_code="circle_cli_timeout",
                submission_status=SubmissionStatus.AMBIGUOUS,
            ) from exc
        except OSError as exc:
            raise CircleExecutionError(
                "Circle CLI could not be started; no transfer was submitted",
                reason_code="circle_cli_start_failed",
                submission_status=SubmissionStatus.NOT_SUBMITTED,
            ) from exc

        if completed.returncode != 0:
            reason_code, submission_status = _classify_rejection(stdout, stderr)
            detail = redact_text((stderr or stdout or "").strip())
            message = "Circle CLI rejected the transfer"
            if detail:
                message = f"{message}: {detail[:400]}"
            raise CircleExecutionError(
                message,
                terminal=False,
                returncode=completed.returncode,
                reason_code=reason_code,
                submission_status=submission_status,
            )
        try:
            payload = json.loads(stdout, parse_float=Decimal)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CircleExecutionError(
                "Circle CLI returned malformed JSON; settlement status is ambiguous",
                reason_code="circle_cli_malformed_response",
            ) from exc
        if not isinstance(payload, dict):
            raise CircleExecutionError(
                "Circle CLI response must be a JSON object",
                reason_code="circle_cli_malformed_response",
            )
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise CircleExecutionError(
                "Circle CLI response data must be an object",
                reason_code="circle_cli_malformed_response",
            )

        try:
            state = str(data.get("state", "")).strip().upper()
            if state != "CONFIRMED":
                raise CircleExecutionError(
                    f"Circle CLI did not prove confirmation (state={state or 'missing'})",
                    reason_code="circle_cli_unconfirmed_state",
                )
            chain = canonical_chain(data.get("blockchain") or data.get("chain") or "")
            source = normalize_wallet_address(
                data.get("sourceAddress") or data.get("from") or "", chain
            )
            destination = normalize_wallet_address(
                data.get("destinationAddress") or data.get("to") or "", chain
            )
            amounts = data.get("amounts")
            raw_amount: Any
            amount_entry: Mapping[str, Any] | None = None
            if isinstance(amounts, list) and len(amounts) == 1:
                if isinstance(amounts[0], Mapping):
                    amount_entry = amounts[0]
                    raw_amount = (
                        amount_entry.get("amount")
                        or amount_entry.get("value")
                        or amount_entry.get("amountUsdc")
                    )
                else:
                    raw_amount = amounts[0]
            else:
                raw_amount = data.get("amount")
            amount = usdc(raw_amount)
            _verify_optional_asset_descriptors(
                token_values=_evidence_values(
                    data, amount_entry, _TOKEN_OUTPUT_KEYS
                ),
                asset_values=_evidence_values(
                    data, amount_entry, _ASSET_OUTPUT_KEYS
                ),
                chain=chain,
                expected_token=intent.token,
                expected_asset=expected_asset,
            )
            transaction_hash = normalize_transaction_hash(
                data.get("txHash") or data.get("transactionHash") or ""
            )
        except CircleExecutionError:
            raise
        except (TypeError, ValueError) as exc:
            raise CircleExecutionError(
                "Circle CLI returned malformed confirmation evidence",
                reason_code="circle_cli_malformed_confirmation",
            ) from exc
        if chain != intent.chain:
            raise CircleExecutionError("Circle CLI confirmed an unexpected chain")
        if source.lower() != intent.payer_wallet.lower():
            raise CircleExecutionError("Circle CLI confirmed an unexpected payer wallet")
        if destination.lower() != intent.payee_wallet.lower():
            raise CircleExecutionError("Circle CLI confirmed an unexpected payee wallet")
        if amount != intent.amount_usdc:
            raise CircleExecutionError("Circle CLI confirmed an unexpected amount")
        confirmed_at = data.get("confirmedAt") or data.get("updateDate") or _timestamp(
            self.clock
        )
        return ExecutionResult(
            state="CONFIRMED",
            amount_usdc=amount,
            chain=chain,
            payer_wallet=source,
            payee_wallet=destination,
            transaction_hash=transaction_hash,
            confirmed_at=str(confirmed_at),
            explorer_url=(
                str(data["explorerUrl"]).strip()
                if data.get("explorerUrl")
                else None
            ),
            simulated=False,
            provider_reference=(
                str(data["id"]).strip() if data.get("id") else None
            ),
            raw=data,
            token=intent.token,
            asset=expected_asset,
        )
