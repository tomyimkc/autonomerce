"""Thread-safe, fail-closed in-memory idempotency primitives."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import threading
from types import MappingProxyType
from typing import Any, Callable, Generic, TypeVar

from autonomerce.contracts import ContractError, stable_id

from ._canonical import canonical_clone, canonical_json, sha256_text


T = TypeVar("T")


class IdempotencyStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class IdempotencyRecord(Generic[T]):
    key: str
    request_fingerprint: str
    status: IdempotencyStatus
    response: T | None = None
    response_fingerprint: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class IdempotencyReservation(Generic[T]):
    acquired: bool
    record: IdempotencyRecord[T]


class IdempotencyError(ContractError):
    pass


class IdempotencyConflict(IdempotencyError):
    pass


class IdempotencyInProgress(IdempotencyError):
    pass


class IdempotencyFailed(IdempotencyError):
    pass


def make_idempotency_key(namespace: str, *parts: object) -> str:
    if not isinstance(namespace, str):
        raise ContractError("idempotency namespace must be text")
    normalized_namespace = namespace.strip().lower()
    if not normalized_namespace:
        raise ContractError("idempotency namespace is required")
    return stable_id(
        "idem",
        normalized_namespace,
        *(canonical_json(part) for part in parts),
    )


def request_fingerprint(request: object) -> str:
    return f"sha256:{sha256_text(request)}"


class IdempotencyStore:
    """At-most-once execution registry for one service process.

    A failed operation remains blocked because an external payment may have
    settled before the local exception. Retrying requires operator
    reconciliation and a deliberately new key.
    """

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord[Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(value: object) -> str:
        if not isinstance(value, str):
            raise ContractError("idempotency key must be text")
        key = value.strip()
        if not key or len(key) > 256:
            raise ContractError("idempotency key must contain 1 to 256 characters")
        return key

    def reserve(
        self, key: str, request: object
    ) -> IdempotencyReservation[Any]:
        selected_key = self._key(key)
        fingerprint = request_fingerprint(request)
        with self._lock:
            existing = self._records.get(selected_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IdempotencyConflict(
                        "idempotency key was already used for a different request"
                    )
                return IdempotencyReservation(acquired=False, record=existing)
            record = IdempotencyRecord(
                key=selected_key,
                request_fingerprint=fingerprint,
                status=IdempotencyStatus.PENDING,
            )
            self._records[selected_key] = record
            return IdempotencyReservation(acquired=True, record=record)

    def complete(self, key: str, request: object, response: T) -> IdempotencyRecord[T]:
        selected_key = self._key(key)
        fingerprint = request_fingerprint(request)
        detached_response = canonical_clone(response)
        response_hash = request_fingerprint(detached_response)
        frozen_response = _deep_freeze(detached_response)
        with self._lock:
            existing = self._records.get(selected_key)
            if existing is None:
                raise IdempotencyError("idempotency key was not reserved")
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "idempotency key was reserved for a different request"
                )
            if existing.status == IdempotencyStatus.SUCCEEDED:
                if existing.response_fingerprint != response_hash:
                    raise IdempotencyConflict(
                        "completed idempotency response cannot be changed"
                    )
                return existing
            if existing.status == IdempotencyStatus.FAILED:
                raise IdempotencyFailed("failed idempotency record cannot be completed")
            completed: IdempotencyRecord[T] = replace(
                existing,
                status=IdempotencyStatus.SUCCEEDED,
                response=frozen_response,
                response_fingerprint=response_hash,
            )
            self._records[selected_key] = completed
            return completed

    def fail(
        self, key: str, request: object, *, error_code: str
    ) -> IdempotencyRecord[Any]:
        selected_key = self._key(key)
        fingerprint = request_fingerprint(request)
        if not isinstance(error_code, str):
            raise ContractError("error_code must be text")
        normalized_error = error_code.strip()
        if not normalized_error:
            raise ContractError("error_code is required")
        with self._lock:
            existing = self._records.get(selected_key)
            if existing is None:
                raise IdempotencyError("idempotency key was not reserved")
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "idempotency key was reserved for a different request"
                )
            if existing.status == IdempotencyStatus.SUCCEEDED:
                raise IdempotencyConflict("successful idempotency record cannot fail")
            if existing.status == IdempotencyStatus.FAILED:
                if existing.error_code != normalized_error:
                    raise IdempotencyConflict(
                        "failed idempotency result cannot be changed"
                    )
                return existing
            failed = replace(
                existing,
                status=IdempotencyStatus.FAILED,
                error_code=normalized_error,
            )
            self._records[selected_key] = failed
            return failed

    def get(self, key: str) -> IdempotencyRecord[Any] | None:
        with self._lock:
            return self._records.get(self._key(key))

    def snapshot(self) -> tuple[IdempotencyRecord[Any], ...]:
        with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))

    def run_once(
        self,
        key: str,
        request: object,
        operation: Callable[[], T],
        *,
        failure_code: str = "operation_failed_unknown_outcome",
    ) -> T:
        reservation = self.reserve(key, request)
        if not reservation.acquired:
            record = reservation.record
            if record.status == IdempotencyStatus.SUCCEEDED:
                return canonical_clone(record.response)  # type: ignore[return-value]
            if record.status == IdempotencyStatus.PENDING:
                raise IdempotencyInProgress("idempotent operation is already in progress")
            raise IdempotencyFailed(
                f"idempotent operation is blocked after failure: {record.error_code}"
            )
        try:
            response = operation()
        except Exception:
            self.fail(key, request, error_code=failure_code)
            raise
        try:
            completed = self.complete(key, request, response)
        except Exception:
            self.fail(key, request, error_code=failure_code)
            raise
        return canonical_clone(completed.response)  # type: ignore[return-value]


InMemoryIdempotencyStore = IdempotencyStore


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value
