"""Append-only hash-chained commercial receipts with public redaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import threading
from types import MappingProxyType
from typing import Any, Mapping

from autonomerce.contracts import ContractError, stable_id

from ._canonical import (
    canonical_clone,
    canonical_timestamp,
    canonical_value,
    sha256_text,
)


_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_REDACTED = "[REDACTED]"
_SECRET_KEYS = {
    "apikey",
    "authorization",
    "authorizationheader",
    "authorizationheaders",
    "clientsecret",
    "credential",
    "credentials",
    "googleapplicationcredentials",
    "googlecredentials",
    "mnemonic",
    "onetimepassword",
    "otp",
    "password",
    "privatekey",
    "recoverycode",
    "recoverymaterial",
    "refreshtoken",
    "seedphrase",
    "secret",
    "sessiontoken",
    "token",
    "idtoken",
}
_PRIVATE_IDENTITY_KEYS = {
    "buyeragenturl",
    "buyeremail",
    "buyerid",
    "buyeridentity",
    "buyername",
    "customeremail",
    "customerid",
    "customeridentity",
    "customername",
    "email",
}
_PROMPT_KEYS = {
    "buyerprompt",
    "customerprompt",
    "inputpayload",
    "prompt",
    "rawprompt",
    "userprompt",
}
_AUTH_VALUE = re.compile(
    r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/\-=]{4,}"
)
_QUERY_SECRET = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)"
    r"(\s*[=:]\s*)[^&\s,;]+"
)
_OPENAI_LIKE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class ReceiptError(ContractError):
    pass


class ReceiptConflict(ReceiptError):
    pass


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _redact_string(value: str) -> str:
    if "-----BEGIN" in value and "PRIVATE KEY-----" in value:
        return _REDACTED
    sanitized = _AUTH_VALUE.sub(lambda match: f"{match.group(1)} {_REDACTED}", value)
    sanitized = _QUERY_SECRET.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
        sanitized,
    )
    return _OPENAI_LIKE_KEY.sub(_REDACTED, sanitized)


def redact_commercial_data(
    value: Any,
    *,
    allow_customer_prompt: bool = False,
) -> Any:
    """Recursively detach and redact receipt-safe JSON data."""

    normalized = canonical_value(value)

    def redact(item: Any) -> Any:
        if isinstance(item, str):
            return _redact_string(item)
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key in sorted(item):
                normalized_key = _normalized_key(key)
                if (
                    normalized_key in _SECRET_KEYS
                    or normalized_key.endswith("accesstoken")
                    or normalized_key.endswith("sessiontoken")
                ):
                    result[key] = _REDACTED
                elif (
                    normalized_key in _PRIVATE_IDENTITY_KEYS
                ):
                    result[key] = _REDACTED
                elif normalized_key in _PROMPT_KEYS and not allow_customer_prompt:
                    result[key] = _REDACTED
                else:
                    result[key] = redact(item[key])
            return result
        return item

    return redact(normalized)


@dataclass(frozen=True)
class CommercialReceipt:
    receipt_id: str
    sequence: int
    event_type: str
    occurred_at: str
    proposal_id: str
    payload: Mapping[str, Any]
    previous_hash: str | None
    receipt_hash: str
    idempotency_key: str | None = None
    customer_prompt_consented: bool = False
    schema: str = "offerrail.commercial_receipt.v1"

    def __post_init__(self) -> None:
        if (
            not self.receipt_id
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ReceiptError("receipt identity and positive sequence are required")
        if not _EVENT_TYPE.fullmatch(self.event_type):
            raise ReceiptError("invalid commercial receipt event type")
        canonical_timestamp(self.occurred_at)
        if not self.proposal_id:
            raise ReceiptError("proposal_id is required")
        if not isinstance(self.payload, Mapping):
            raise ReceiptError("receipt payload must be a mapping")
        if not isinstance(self.customer_prompt_consented, bool):
            raise ReceiptError("customer_prompt_consented must be boolean")
        if redact_commercial_data(
            self.payload,
            allow_customer_prompt=self.customer_prompt_consented,
        ) != canonical_value(self.payload):
            raise ReceiptError("commercial receipt payload is not safely redacted")
        if self.previous_hash is not None and not re.fullmatch(
            r"sha256:[a-f0-9]{64}", self.previous_hash
        ):
            raise ReceiptError("invalid previous receipt hash")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.receipt_hash):
            raise ReceiptError("invalid receipt hash")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "receiptId": self.receipt_id,
            "sequence": self.sequence,
            "eventType": self.event_type,
            "occurredAt": self.occurred_at,
            "proposalId": self.proposal_id,
            "payload": canonical_clone(self.payload),
            "previousHash": self.previous_hash,
            "receiptHash": self.receipt_hash,
            "idempotencyKey": self.idempotency_key,
            "customerPromptConsented": self.customer_prompt_consented,
        }


def _receipt_body(
    *,
    sequence: int,
    event_type: str,
    occurred_at: str,
    proposal_id: str,
    payload: Mapping[str, Any],
    previous_hash: str | None,
    idempotency_key: str | None,
    customer_prompt_consented: bool,
) -> dict[str, Any]:
    return {
        "schema": "offerrail.commercial_receipt.v1",
        "sequence": sequence,
        "eventType": event_type,
        "occurredAt": occurred_at,
        "proposalId": proposal_id,
        "payload": payload,
        "previousHash": previous_hash,
        "idempotencyKey": idempotency_key,
        "customerPromptConsented": customer_prompt_consented,
    }


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


class CommercialReceiptLedger:
    """In-memory append-only receipt chain.

    Payloads are redacted before hashing or storage. Accessors return immutable
    receipt objects and detached payload copies, so callers cannot mutate history.
    """

    def __init__(self) -> None:
        self._records: list[CommercialReceipt] = []
        self._by_idempotency_key: dict[str, tuple[str, CommercialReceipt]] = {}
        self._lock = threading.RLock()

    def append(
        self,
        *,
        event_type: str,
        proposal_id: str,
        payload: Mapping[str, Any],
        occurred_at: str | datetime | None = None,
        idempotency_key: str | None = None,
        allow_customer_prompt: bool = False,
    ) -> CommercialReceipt:
        if not isinstance(event_type, str) or not isinstance(proposal_id, str):
            raise ReceiptError("event_type and proposal_id must be text")
        normalized_event = event_type.strip().lower()
        normalized_proposal = proposal_id.strip()
        if not _EVENT_TYPE.fullmatch(normalized_event):
            raise ReceiptError("invalid commercial receipt event type")
        if not normalized_proposal:
            raise ReceiptError("proposal_id is required")
        if not isinstance(payload, Mapping):
            raise ReceiptError("receipt payload must be a mapping")
        selected_time = canonical_timestamp(
            datetime.now(timezone.utc) if occurred_at is None else occurred_at
        )
        if idempotency_key is not None and not isinstance(idempotency_key, str):
            raise ReceiptError("idempotency_key must be text")
        selected_key = None if idempotency_key is None else idempotency_key.strip()
        if idempotency_key is not None and not selected_key:
            raise ReceiptError("idempotency_key cannot be empty")
        redacted = redact_commercial_data(
            payload,
            allow_customer_prompt=allow_customer_prompt,
        )
        if not isinstance(redacted, dict):
            raise ReceiptError("receipt payload must normalize to an object")
        detached_payload = canonical_clone(redacted)
        intent = {
            "eventType": normalized_event,
            "proposalId": normalized_proposal,
            "payload": detached_payload,
        }
        intent_hash = f"sha256:{sha256_text(intent)}"

        with self._lock:
            if selected_key is not None and selected_key in self._by_idempotency_key:
                previous_intent, previous_receipt = self._by_idempotency_key[selected_key]
                if previous_intent != intent_hash:
                    raise ReceiptConflict(
                        "receipt idempotency key was reused for different content"
                    )
                return previous_receipt

            sequence = len(self._records) + 1
            previous_hash = (
                None if not self._records else self._records[-1].receipt_hash
            )
            body = _receipt_body(
                sequence=sequence,
                event_type=normalized_event,
                occurred_at=selected_time,
                proposal_id=normalized_proposal,
                payload=detached_payload,
                previous_hash=previous_hash,
                idempotency_key=selected_key,
                customer_prompt_consented=allow_customer_prompt,
            )
            receipt_hash = f"sha256:{sha256_text(body)}"
            receipt_id = stable_id(
                "receipt",
                normalized_proposal,
                sequence,
                receipt_hash,
            )
            receipt = CommercialReceipt(
                receipt_id=receipt_id,
                sequence=sequence,
                event_type=normalized_event,
                occurred_at=selected_time,
                proposal_id=normalized_proposal,
                payload=_deep_freeze(detached_payload),
                previous_hash=previous_hash,
                receipt_hash=receipt_hash,
                idempotency_key=selected_key,
                customer_prompt_consented=allow_customer_prompt,
            )
            self._records.append(receipt)
            if selected_key is not None:
                self._by_idempotency_key[selected_key] = (intent_hash, receipt)
            return receipt

    @property
    def records(self) -> tuple[CommercialReceipt, ...]:
        with self._lock:
            return tuple(self._records)

    def verify(self) -> bool:
        with self._lock:
            previous_hash: str | None = None
            for expected_sequence, receipt in enumerate(self._records, start=1):
                if (
                    receipt.sequence != expected_sequence
                    or receipt.previous_hash != previous_hash
                ):
                    return False
                body = _receipt_body(
                    sequence=receipt.sequence,
                    event_type=receipt.event_type,
                    occurred_at=receipt.occurred_at,
                    proposal_id=receipt.proposal_id,
                    payload=canonical_clone(receipt.payload),
                    previous_hash=receipt.previous_hash,
                    idempotency_key=receipt.idempotency_key,
                    customer_prompt_consented=receipt.customer_prompt_consented,
                )
                expected_hash = f"sha256:{sha256_text(body)}"
                expected_id = stable_id(
                    "receipt",
                    receipt.proposal_id,
                    receipt.sequence,
                    expected_hash,
                )
                if (
                    receipt.receipt_hash != expected_hash
                    or receipt.receipt_id != expected_id
                ):
                    return False
                previous_hash = receipt.receipt_hash
            return True

    def to_jsonl(self) -> str:
        with self._lock:
            return "".join(
                json.dumps(
                    receipt.to_dict(),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
                for receipt in self._records
            )


ReceiptLedger = CommercialReceiptLedger
