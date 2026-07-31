"""Fail-closed security helpers for untrusted A2A commerce inputs."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit


class SecurityError(ValueError):
    pass


_SECRET_KEY = re.compile(
    r"(?:authorization|api[_-]?key|secret|token|password|passwd|credential|"
    r"private[_-]?key|recovery|otp|session)",
    re.I,
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(secret|token|password|passwd|credential|api[_-]?key|"
    r"private[_-]?key|authorization|otp)\s*[:=]\s*([^,;\s]+)"
)
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def redact(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, key=key) for item in value)
    if isinstance(value, str):
        value = _BEARER.sub("Bearer [REDACTED]", value)
        return _ASSIGNMENT.sub(r"\1=[REDACTED]", value)
    return value


def _unsafe_ip(host: str) -> bool:
    try:
        value = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_reserved
        or value.is_unspecified
    )


def is_public_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTS or host.endswith(".local") or _unsafe_ip(host):
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    return True


def require_public_https_url(value: str, *, label: str = "URL") -> str:
    if not is_public_https_url(value):
        raise SecurityError(f"{label} must be a public HTTPS URL")
    return value


def validate_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or not _IDEMPOTENCY.fullmatch(value):
        raise SecurityError("invalid idempotency key")
    return value
