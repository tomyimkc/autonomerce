"""Deterministic serialization and time helpers for OfferRail."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from autonomerce.contracts import ContractError


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ContractError("non-finite Decimal is not canonical")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def canonical_value(value: Any) -> Any:
    """Convert supported domain values to deterministic JSON-compatible values.

    Unsupported objects fail closed rather than depending on their process-specific
    ``repr`` implementation.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ContractError("binary float is not allowed in canonical domain data")
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ContractError("canonical mapping keys must be non-empty strings")
            normalized[key] = canonical_value(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized_items = [canonical_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(
                item, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
        )
    raise ContractError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_clone(value: Any) -> Any:
    """Return a detached JSON-compatible copy of ``value``."""

    return json.loads(canonical_json(value))


def sha256_text(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_timestamp(value: str | datetime, *, field_name: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ContractError(f"invalid {field_name}") from exc
    else:
        raise ContractError(f"{field_name} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_timestamp(value: str | datetime) -> str:
    parsed = parse_timestamp(value)
    text = parsed.isoformat(timespec="microseconds")
    if text.endswith(".000000+00:00"):
        text = text.replace(".000000+00:00", "Z")
    elif text.endswith("+00:00"):
        text = f"{text[:-6]}Z"
    return text
