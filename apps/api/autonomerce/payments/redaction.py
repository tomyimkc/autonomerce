"""Public-receipt and log redaction for payment data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from autonomerce.contracts import PaymentReceipt

from .models import PaymentMode


REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|api[-_]?key|access[-_]?token|session[-_]?token|"
    r"private[-_]?key|mnemonic|seed[-_]?phrase|otp|password|client[-_]?secret|"
    r"recovery|cookie|set[-_]?cookie|google[-_]?application[-_]?credentials)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|session[-_]?token|password|secret|otp)"
    r"\s*[:=]\s*[^\s,;]+"
)


def redact_text(value: str) -> str:
    redacted = _BEARER.sub("Bearer [REDACTED]", str(value))
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if _SENSITIVE_KEY.search(str(key))
                else redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_sensitive(item) for item in value]
    return value


def redact_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    return dict(redact_sensitive(headers))


def public_payment_receipt(
    receipt: PaymentReceipt,
    *,
    mode: PaymentMode | str,
    verified: bool,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_mode = PaymentMode.parse(mode)
    result = receipt.to_public_dict()
    result["mode"] = normalized_mode.value
    result["settlementKind"] = (
        "simulated"
        if normalized_mode is PaymentMode.OFFLINE
        else normalized_mode.value
    )
    result["receiptVerified"] = bool(verified)
    if metadata:
        result["metadata"] = redact_sensitive(metadata)
    # The shared public projection intentionally excludes the idempotency key and
    # private identity. Run the complete structure through redaction as defense in depth.
    return dict(redact_sensitive(result))
