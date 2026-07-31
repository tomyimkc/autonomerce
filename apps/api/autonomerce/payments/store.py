"""Atomic idempotent payment stores.

Both stores reserve an idempotency key and enforce cumulative policy limits while
holding a lock/transaction. A process that crashes after entering SUBMITTING remains
blocked from automatic re-submission, because the Circle transfer CLI does not expose a
transfer idempotency flag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol

from autonomerce.contracts import PaymentReceipt, PaymentState, usdc_text

from .errors import (
    PaymentPolicyDenied,
    PaymentReplayError,
    PaymentValidationError,
    SubmissionStatus,
)
from .models import (
    PaymentIntent,
    PaymentPolicy,
    PaymentPolicyDecision,
    SpendingSnapshot,
    normalize_transaction_hash,
)
from .policy import PaymentPolicyGate


_COMMITTED_STATES = {
    PaymentState.POLICY_APPROVED,
    PaymentState.SUBMITTING,
    PaymentState.CONFIRMED,
}

_TRANSITIONS = {
    PaymentState.POLICY_APPROVED: {
        PaymentState.SUBMITTING,
        PaymentState.FAILED_TERMINAL,
    },
    PaymentState.SUBMITTING: {
        PaymentState.CONFIRMED,
        PaymentState.FAILED_RETRYABLE,
        PaymentState.FAILED_TERMINAL,
    },
    PaymentState.FAILED_RETRYABLE: {PaymentState.FAILED_TERMINAL},
    PaymentState.CONFIRMED: set(),
    PaymentState.FAILED_TERMINAL: set(),
    PaymentState.CREATED: {PaymentState.POLICY_APPROVED, PaymentState.FAILED_TERMINAL},
}


class StoreDurability(str, Enum):
    """Persistence capability exposed by every payment store."""

    PROCESS = "process"
    SINGLE_NODE = "single_node"
    DISTRIBUTED = "distributed"

    @property
    def is_durable(self) -> bool:
        return self is not StoreDurability.PROCESS


class ReconciliationState(str, Enum):
    """Durable operator disposition for a payment requiring reconciliation."""

    PENDING = "pending"
    RETRYABLE = "proven_not_submitted_retryable"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PaymentReservation:
    receipt: PaymentReceipt
    created: bool
    decision: PaymentPolicyDecision


@dataclass(frozen=True)
class PaymentReconciliation:
    """Durable current disposition of an interrupted Circle payment."""

    idempotency_key: str
    payment_id: str
    reason_code: str
    explanation: str
    returncode: int | None = None
    state: ReconciliationState = ReconciliationState.PENDING
    submission_status: SubmissionStatus = SubmissionStatus.AMBIGUOUS
    evidence_reference: str | None = None
    transaction_hash: str | None = None
    resolved_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PaymentReconciliationStatus:
    """Atomic payment and reconciliation projection for an API response."""

    receipt: PaymentReceipt
    reconciliation: PaymentReconciliation | None

    @property
    def requires_operator_action(self) -> bool:
        return (
            self.receipt.state is PaymentState.SUBMITTING
            and (
                self.reconciliation is None
                or self.reconciliation.state is ReconciliationState.PENDING
            )
        )


class PaymentStore(Protocol):
    durability: StoreDurability

    def reserve(
        self,
        intent: PaymentIntent,
        policy: PaymentPolicy,
        gate: PaymentPolicyGate | None = None,
    ) -> PaymentReservation: ...

    def get(self, idempotency_key: str) -> PaymentReceipt | None: ...

    def transition(
        self,
        idempotency_key: str,
        state: PaymentState,
        *,
        transaction_hash: str | None = None,
        explorer_url: str | None = None,
        confirmed_at: str | None = None,
    ) -> PaymentReceipt: ...

    def snapshot(self, policy_id: str) -> SpendingSnapshot: ...

    def record_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        returncode: int | None = None,
        submission_status: SubmissionStatus = SubmissionStatus.AMBIGUOUS,
    ) -> PaymentReconciliation: ...

    def get_reconciliation(
        self, idempotency_key: str
    ) -> PaymentReconciliation | None: ...

    def get_reconciliation_status(
        self, idempotency_key: str
    ) -> PaymentReconciliationStatus: ...

    def mark_reconciliation_retryable(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
        returncode: int | None = None,
    ) -> PaymentReconciliationStatus: ...

    def confirm_reconciliation(
        self,
        idempotency_key: str,
        *,
        transaction_hash: str,
        explorer_url: str | None,
        confirmed_at: str | None,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus: ...

    def cancel_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus: ...


@dataclass
class _Record:
    receipt: PaymentReceipt
    fingerprint: str
    policy_id: str
    token: str
    asset: str | None
    x402_requirement_id: str | None
    reconciliation: PaymentReconciliation | None = None


def _new_receipt(intent: PaymentIntent) -> PaymentReceipt:
    return PaymentReceipt(
        payment_id=intent.payment_id,
        proposal_id=intent.proposal_id,
        idempotency_key=intent.idempotency_key,
        state=PaymentState.POLICY_APPROVED,
        amount_usdc=intent.amount_usdc,
        chain=intent.chain,
        payer_wallet=intent.payer_wallet,
        payee_wallet=intent.payee_wallet,
        token=intent.token,
        asset=intent.asset,
    )


def _idempotent_decision(
    intent: PaymentIntent, policy: PaymentPolicy
) -> PaymentPolicyDecision:
    return PaymentPolicyDecision(
        authorized=True,
        reason_code="idempotent_existing",
        explanation="an identical payment reservation already exists",
        policy_id=policy.policy_id,
        payment_id=intent.payment_id,
    )


def _check_transition(current: PaymentReceipt, target: PaymentState) -> None:
    if target == current.state:
        return
    if target not in _TRANSITIONS[current.state]:
        raise PaymentValidationError(
            f"invalid payment state transition {current.state.value}->{target.value}"
        )


def _check_idempotent_transition(
    current: PaymentReceipt,
    target: PaymentState,
    *,
    transaction_hash: str | None,
    explorer_url: str | None,
    confirmed_at: str | None,
) -> bool:
    """Return True for an exact same-state retry; reject attempts to rewrite evidence."""

    if target != current.state:
        return False
    supplied = {
        "transaction_hash": transaction_hash,
        "explorer_url": explorer_url,
        "confirmed_at": confirmed_at,
    }
    for field_name, value in supplied.items():
        existing = getattr(current, field_name)
        if value is not None and existing is not None:
            left = value.lower() if field_name == "transaction_hash" else value
            right = existing.lower() if field_name == "transaction_hash" else existing
            if left != right:
                raise PaymentReplayError(
                    f"same-state transition attempted to rewrite {field_name}"
                )
        elif value is not None and existing is None:
            raise PaymentValidationError(
                f"same-state transition cannot add {field_name}"
            )
    return True


def _reconciliation_values(
    reason_code: str,
    explanation: str,
) -> tuple[str, str]:
    normalized_reason = str(reason_code).strip().lower()
    normalized_explanation = str(explanation).strip()
    if (
        not normalized_reason
        or len(normalized_reason) > 96
        or not normalized_reason.replace("_", "").isalnum()
    ):
        raise PaymentValidationError("invalid reconciliation reason code")
    if not normalized_explanation:
        raise PaymentValidationError("reconciliation explanation is required")
    return normalized_reason, normalized_explanation[:400]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolution_values(
    evidence_reference: str,
    resolved_by: str,
) -> tuple[str, str]:
    normalized_evidence = str(evidence_reference).strip()
    normalized_actor = str(resolved_by).strip()
    if not normalized_evidence:
        raise PaymentValidationError(
            "reconciliation evidence reference is required"
        )
    if len(normalized_evidence) > 400:
        raise PaymentValidationError(
            "reconciliation evidence reference is too long"
        )
    if not normalized_actor or len(normalized_actor) > 160:
        raise PaymentValidationError("reconciliation actor is invalid")
    return normalized_evidence, normalized_actor


def _assert_resolution_replay(
    reconciliation: PaymentReconciliation,
    *,
    state: ReconciliationState,
    reason_code: str,
    explanation: str,
    evidence_reference: str,
    resolved_by: str,
    transaction_hash: str | None = None,
) -> None:
    expected = (
        state,
        reason_code,
        explanation,
        evidence_reference,
        resolved_by,
        transaction_hash.lower() if transaction_hash else None,
    )
    existing = (
        reconciliation.state,
        reconciliation.reason_code,
        reconciliation.explanation,
        reconciliation.evidence_reference,
        reconciliation.resolved_by,
        (
            reconciliation.transaction_hash.lower()
            if reconciliation.transaction_hash
            else None
        ),
    )
    if existing != expected:
        raise PaymentReplayError(
            "reconciliation replay attempted to rewrite the durable resolution"
        )


class InMemoryPaymentStore:
    """Thread-safe idempotent store for offline mode and unit tests."""

    durability = StoreDurability.PROCESS

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._payment_ids: dict[str, str] = {}
        self._proposal_ids: dict[str, str] = {}
        self._x402_ids: dict[str, str] = {}
        self._transaction_hashes: dict[str, str] = {}
        self._lock = RLock()

    def reserve(
        self,
        intent: PaymentIntent,
        policy: PaymentPolicy,
        gate: PaymentPolicyGate | None = None,
    ) -> PaymentReservation:
        evaluator = gate or PaymentPolicyGate()
        with self._lock:
            existing = self._records.get(intent.idempotency_key)
            if existing:
                if existing.fingerprint != intent.fingerprint:
                    raise PaymentReplayError(
                        "idempotency key was reused for a different payment intent"
                    )
                if existing.policy_id != policy.policy_id:
                    raise PaymentReplayError(
                        "idempotency key was reused under a different payment policy"
                    )
                return PaymentReservation(
                    existing.receipt, False, _idempotent_decision(intent, policy)
                )
            if intent.payment_id in self._payment_ids:
                raise PaymentReplayError("deterministic payment ID already exists")
            prior_proposal = self._proposal_ids.get(intent.proposal_id)
            if prior_proposal and prior_proposal != intent.idempotency_key:
                raise PaymentReplayError(
                    "proposal is already bound to another payment reservation"
                )
            if intent.x402_requirement_id:
                prior = self._x402_ids.get(intent.x402_requirement_id)
                if prior and prior != intent.idempotency_key:
                    raise PaymentReplayError(
                        "x402 payment identifier was already reserved"
                    )
            decision = evaluator.evaluate(intent, policy, self._snapshot_unlocked(policy.policy_id))
            if not decision.authorized:
                raise PaymentPolicyDenied(decision.reason_code, decision.explanation)
            receipt = _new_receipt(intent)
            self._records[intent.idempotency_key] = _Record(
                receipt=receipt,
                fingerprint=intent.fingerprint,
                policy_id=policy.policy_id,
                token=intent.token,
                asset=intent.asset,
                x402_requirement_id=intent.x402_requirement_id,
            )
            self._payment_ids[receipt.payment_id] = intent.idempotency_key
            self._proposal_ids[receipt.proposal_id] = intent.idempotency_key
            if intent.x402_requirement_id:
                self._x402_ids[intent.x402_requirement_id] = intent.idempotency_key
            return PaymentReservation(receipt, True, decision)

    def _snapshot_unlocked(self, policy_id: str) -> SpendingSnapshot:
        committed = [
            record.receipt
            for record in self._records.values()
            if record.policy_id == policy_id and record.receipt.state in _COMMITTED_STATES
        ]
        return SpendingSnapshot(
            committed_usdc=sum(
                (receipt.amount_usdc for receipt in committed), Decimal("0")
            ),
            committed_payment_count=len(committed),
        )

    def snapshot(self, policy_id: str) -> SpendingSnapshot:
        with self._lock:
            return self._snapshot_unlocked(policy_id)

    def get(self, idempotency_key: str) -> PaymentReceipt | None:
        with self._lock:
            record = self._records.get(idempotency_key)
            return record.receipt if record else None

    def get_by_payment_id(self, payment_id: str) -> PaymentReceipt | None:
        with self._lock:
            key = self._payment_ids.get(payment_id)
            return self._records[key].receipt if key else None

    def list(self) -> tuple[PaymentReceipt, ...]:
        with self._lock:
            return tuple(record.receipt for record in self._records.values())

    def record_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        returncode: int | None = None,
        submission_status: SubmissionStatus = SubmissionStatus.AMBIGUOUS,
    ) -> PaymentReconciliation:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        submission_status = SubmissionStatus(submission_status)
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise PaymentValidationError("payment reservation does not exist")
            if record.reconciliation is None:
                now = _utc_timestamp()
                record.reconciliation = PaymentReconciliation(
                    idempotency_key=idempotency_key,
                    payment_id=record.receipt.payment_id,
                    reason_code=reason_code,
                    explanation=explanation,
                    returncode=returncode,
                    submission_status=submission_status,
                    created_at=now,
                    updated_at=now,
                )
            elif record.reconciliation.state is not ReconciliationState.PENDING:
                raise PaymentReplayError(
                    "resolved reconciliation cannot be replaced by a new failure"
                )
            return record.reconciliation

    def get_reconciliation(
        self, idempotency_key: str
    ) -> PaymentReconciliation | None:
        with self._lock:
            record = self._records.get(idempotency_key)
            return record.reconciliation if record else None

    def _status_unlocked(
        self, idempotency_key: str
    ) -> PaymentReconciliationStatus:
        record = self._records.get(idempotency_key)
        if record is None:
            raise PaymentValidationError("payment reservation does not exist")
        return PaymentReconciliationStatus(
            receipt=record.receipt,
            reconciliation=record.reconciliation,
        )

    def get_reconciliation_status(
        self, idempotency_key: str
    ) -> PaymentReconciliationStatus:
        with self._lock:
            return self._status_unlocked(idempotency_key)

    def mark_reconciliation_retryable(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
        returncode: int | None = None,
    ) -> PaymentReconciliationStatus:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise PaymentValidationError("payment reservation does not exist")
            existing = record.reconciliation
            if (
                record.receipt.state is PaymentState.FAILED_RETRYABLE
                and existing is not None
            ):
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.RETRYABLE,
                    reason_code=reason_code,
                    explanation=explanation,
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                )
                return self._status_unlocked(idempotency_key)
            if record.receipt.state is not PaymentState.SUBMITTING:
                raise PaymentValidationError(
                    "only a submitting payment can be marked retryable"
                )
            now = _utc_timestamp()
            record.receipt = replace(
                record.receipt,
                state=PaymentState.FAILED_RETRYABLE,
            )
            record.reconciliation = PaymentReconciliation(
                idempotency_key=idempotency_key,
                payment_id=record.receipt.payment_id,
                reason_code=reason_code,
                explanation=explanation,
                returncode=existing.returncode if existing else returncode,
                state=ReconciliationState.RETRYABLE,
                submission_status=SubmissionStatus.NOT_SUBMITTED,
                evidence_reference=evidence_reference,
                resolved_by=resolved_by,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            return self._status_unlocked(idempotency_key)

    def confirm_reconciliation(
        self,
        idempotency_key: str,
        *,
        transaction_hash: str,
        explorer_url: str | None,
        confirmed_at: str | None,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        transaction_hash = normalize_transaction_hash(transaction_hash)
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise PaymentValidationError("payment reservation does not exist")
            existing = record.reconciliation
            if record.receipt.state is PaymentState.CONFIRMED:
                if existing is None:
                    raise PaymentReplayError(
                        "confirmed payment has no reconciliation resolution"
                    )
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.CONFIRMED,
                    reason_code="verified_transaction",
                    explanation="verified transaction evidence confirms settlement",
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                    transaction_hash=transaction_hash,
                )
                return self._status_unlocked(idempotency_key)
            if record.receipt.state not in {
                PaymentState.SUBMITTING,
                PaymentState.FAILED_RETRYABLE,
            }:
                raise PaymentValidationError(
                    "payment state cannot be reconciled as confirmed"
                )
            owner = self._transaction_hashes.get(transaction_hash.lower())
            if owner and owner != idempotency_key:
                raise PaymentReplayError(
                    "transaction hash is already bound to another payment"
                )
            now = _utc_timestamp()
            record.receipt = replace(
                record.receipt,
                state=PaymentState.CONFIRMED,
                transaction_hash=transaction_hash,
                explorer_url=explorer_url,
                confirmed_at=confirmed_at,
            )
            self._transaction_hashes[transaction_hash.lower()] = idempotency_key
            record.reconciliation = PaymentReconciliation(
                idempotency_key=idempotency_key,
                payment_id=record.receipt.payment_id,
                reason_code="verified_transaction",
                explanation="verified transaction evidence confirms settlement",
                returncode=existing.returncode if existing else None,
                state=ReconciliationState.CONFIRMED,
                submission_status=(
                    existing.submission_status
                    if existing
                    else SubmissionStatus.AMBIGUOUS
                ),
                evidence_reference=evidence_reference,
                transaction_hash=transaction_hash,
                resolved_by=resolved_by,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            return self._status_unlocked(idempotency_key)

    def cancel_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise PaymentValidationError("payment reservation does not exist")
            existing = record.reconciliation
            if (
                record.receipt.state is PaymentState.FAILED_TERMINAL
                and existing is not None
            ):
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.CANCELLED,
                    reason_code=reason_code,
                    explanation=explanation,
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                )
                return self._status_unlocked(idempotency_key)
            if record.receipt.state not in {
                PaymentState.POLICY_APPROVED,
                PaymentState.SUBMITTING,
                PaymentState.FAILED_RETRYABLE,
            }:
                raise PaymentValidationError(
                    "payment state cannot be terminally cancelled"
                )
            now = _utc_timestamp()
            record.receipt = replace(
                record.receipt,
                state=PaymentState.FAILED_TERMINAL,
            )
            record.reconciliation = PaymentReconciliation(
                idempotency_key=idempotency_key,
                payment_id=record.receipt.payment_id,
                reason_code=reason_code,
                explanation=explanation,
                returncode=existing.returncode if existing else None,
                state=ReconciliationState.CANCELLED,
                submission_status=(
                    existing.submission_status
                    if existing
                    else SubmissionStatus.AMBIGUOUS
                ),
                evidence_reference=evidence_reference,
                resolved_by=resolved_by,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            return self._status_unlocked(idempotency_key)

    def transition(
        self,
        idempotency_key: str,
        state: PaymentState,
        *,
        transaction_hash: str | None = None,
        explorer_url: str | None = None,
        confirmed_at: str | None = None,
    ) -> PaymentReceipt:
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise PaymentValidationError("payment reservation does not exist")
            if _check_idempotent_transition(
                record.receipt,
                state,
                transaction_hash=transaction_hash,
                explorer_url=explorer_url,
                confirmed_at=confirmed_at,
            ):
                return record.receipt
            _check_transition(record.receipt, state)
            if transaction_hash:
                owner = self._transaction_hashes.get(transaction_hash.lower())
                if owner and owner != idempotency_key:
                    raise PaymentReplayError(
                        "transaction hash is already bound to another payment"
                    )
            updated = replace(
                record.receipt,
                state=state,
                transaction_hash=transaction_hash or record.receipt.transaction_hash,
                explorer_url=explorer_url or record.receipt.explorer_url,
                confirmed_at=confirmed_at or record.receipt.confirmed_at,
            )
            record.receipt = updated
            if updated.transaction_hash:
                self._transaction_hashes[updated.transaction_hash.lower()] = idempotency_key
            return updated


class SQLitePaymentStore:
    """Durable SQLite idempotency store suitable for a single API deployment."""

    durability = StoreDurability.SINGLE_NODE

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path == ":memory:" or self.path.startswith("file::memory:"):
            raise PaymentValidationError(
                "SQLitePaymentStore requires a durable filesystem path"
            )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    idempotency_key TEXT PRIMARY KEY,
                    payment_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    amount_usdc TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    token TEXT NOT NULL,
                    asset TEXT,
                    payer_wallet TEXT NOT NULL,
                    payee_wallet TEXT NOT NULL,
                    transaction_hash TEXT UNIQUE,
                    explorer_url TEXT,
                    confirmed_at TEXT,
                    public INTEGER NOT NULL DEFAULT 0,
                    fingerprint TEXT NOT NULL,
                    x402_requirement_id TEXT UNIQUE,
                    policy_id TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_proposal_id
                ON payments(proposal_id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_reconciliations (
                    idempotency_key TEXT PRIMARY KEY,
                    payment_id TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    returncode INTEGER,
                    state TEXT NOT NULL DEFAULT 'pending',
                    submission_status TEXT NOT NULL DEFAULT 'ambiguous',
                    evidence_reference TEXT,
                    transaction_hash TEXT,
                    resolved_by TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(idempotency_key)
                        REFERENCES payments(idempotency_key)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(payment_reconciliations)"
                ).fetchall()
            }
            migrations = {
                "state": "TEXT NOT NULL DEFAULT 'pending'",
                "submission_status": "TEXT NOT NULL DEFAULT 'ambiguous'",
                "evidence_reference": "TEXT",
                "transaction_hash": "TEXT",
                "resolved_by": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE payment_reconciliations "
                        f"ADD COLUMN {name} {definition}"
                    )

    @staticmethod
    def _receipt(row: sqlite3.Row) -> PaymentReceipt:
        return PaymentReceipt(
            payment_id=row["payment_id"],
            proposal_id=row["proposal_id"],
            idempotency_key=row["idempotency_key"],
            state=PaymentState(row["state"]),
            amount_usdc=Decimal(row["amount_usdc"]),
            chain=row["chain"],
            payer_wallet=row["payer_wallet"],
            payee_wallet=row["payee_wallet"],
            transaction_hash=row["transaction_hash"],
            explorer_url=row["explorer_url"],
            confirmed_at=row["confirmed_at"],
            # Financial records are always private. Publication is a separate
            # authenticated concern outside the payment adapter/store.
            public=False,
            token=row["token"],
            asset=row["asset"],
        )

    @staticmethod
    def _reconciliation(
        row: sqlite3.Row | None,
    ) -> PaymentReconciliation | None:
        if row is None:
            return None
        return PaymentReconciliation(
            idempotency_key=row["idempotency_key"],
            payment_id=row["payment_id"],
            reason_code=row["reason_code"],
            explanation=row["explanation"],
            returncode=row["returncode"],
            state=ReconciliationState(row["state"]),
            submission_status=SubmissionStatus(row["submission_status"]),
            evidence_reference=row["evidence_reference"],
            transaction_hash=row["transaction_hash"],
            resolved_by=row["resolved_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _snapshot_in_transaction(
        connection: sqlite3.Connection, policy_id: str
    ) -> SpendingSnapshot:
        placeholders = ",".join("?" for _ in _COMMITTED_STATES)
        states = tuple(state.value for state in _COMMITTED_STATES)
        rows = connection.execute(
            f"""
            SELECT amount_usdc FROM payments
            WHERE policy_id = ? AND state IN ({placeholders})
            """,
            (policy_id, *states),
        ).fetchall()
        return SpendingSnapshot(
            committed_usdc=sum(
                (Decimal(row["amount_usdc"]) for row in rows), Decimal("0")
            ),
            committed_payment_count=len(rows),
        )

    def reserve(
        self,
        intent: PaymentIntent,
        policy: PaymentPolicy,
        gate: PaymentPolicyGate | None = None,
    ) -> PaymentReservation:
        evaluator = gate or PaymentPolicyGate()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM payments WHERE idempotency_key = ?",
                (intent.idempotency_key,),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != intent.fingerprint:
                    raise PaymentReplayError(
                        "idempotency key was reused for a different payment intent"
                    )
                if existing["policy_id"] != policy.policy_id:
                    raise PaymentReplayError(
                        "idempotency key was reused under a different payment policy"
                    )
                connection.commit()
                return PaymentReservation(
                    self._receipt(existing),
                    False,
                    _idempotent_decision(intent, policy),
                )
            if intent.x402_requirement_id:
                replay = connection.execute(
                    "SELECT idempotency_key FROM payments WHERE x402_requirement_id = ?",
                    (intent.x402_requirement_id,),
                ).fetchone()
                if replay:
                    raise PaymentReplayError(
                        "x402 payment identifier was already reserved"
                    )
            prior_proposal = connection.execute(
                "SELECT idempotency_key FROM payments WHERE proposal_id = ?",
                (intent.proposal_id,),
            ).fetchone()
            if prior_proposal:
                raise PaymentReplayError(
                    "proposal is already bound to another payment reservation"
                )
            snapshot = self._snapshot_in_transaction(connection, policy.policy_id)
            decision = evaluator.evaluate(intent, policy, snapshot)
            if not decision.authorized:
                raise PaymentPolicyDenied(decision.reason_code, decision.explanation)
            receipt = _new_receipt(intent)
            connection.execute(
                """
                INSERT INTO payments (
                    idempotency_key, payment_id, proposal_id, state, amount_usdc,
                    chain, token, asset, payer_wallet, payee_wallet, fingerprint,
                    x402_requirement_id, policy_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.idempotency_key,
                    receipt.payment_id,
                    receipt.proposal_id,
                    receipt.state.value,
                    usdc_text(receipt.amount_usdc),
                    receipt.chain,
                    intent.token,
                    intent.asset,
                    receipt.payer_wallet,
                    receipt.payee_wallet,
                    intent.fingerprint,
                    intent.x402_requirement_id,
                    policy.policy_id,
                ),
            )
            connection.commit()
            return PaymentReservation(receipt, True, decision)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise PaymentReplayError("duplicate payment reservation") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, idempotency_key: str) -> PaymentReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM payments WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return self._receipt(row) if row else None

    def get_by_payment_id(self, payment_id: str) -> PaymentReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
            ).fetchone()
            return self._receipt(row) if row else None

    def list(self) -> tuple[PaymentReceipt, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM payments ORDER BY rowid"
            ).fetchall()
            return tuple(self._receipt(row) for row in rows)

    def snapshot(self, policy_id: str) -> SpendingSnapshot:
        with self._connect() as connection:
            return self._snapshot_in_transaction(connection, policy_id)

    def record_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        returncode: int | None = None,
        submission_status: SubmissionStatus = SubmissionStatus.AMBIGUOUS,
    ) -> PaymentReconciliation:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        submission_status = SubmissionStatus(submission_status)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            payment = connection.execute(
                """
                SELECT payment_id FROM payments
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if payment is None:
                raise PaymentValidationError("payment reservation does not exist")
            existing = connection.execute(
                """
                SELECT * FROM payment_reconciliations
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if (
                existing is not None
                and ReconciliationState(existing["state"])
                is not ReconciliationState.PENDING
            ):
                raise PaymentReplayError(
                    "resolved reconciliation cannot be replaced by a new failure"
                )
            now = _utc_timestamp()
            connection.execute(
                """
                INSERT OR IGNORE INTO payment_reconciliations (
                    idempotency_key, payment_id, reason_code, explanation,
                    returncode, state, submission_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    payment["payment_id"],
                    reason_code,
                    explanation,
                    returncode,
                    ReconciliationState.PENDING.value,
                    submission_status.value,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM payment_reconciliations
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            connection.commit()
            reconciliation = self._reconciliation(row)
            if reconciliation is None:
                raise PaymentValidationError(
                    "payment reconciliation was not persisted"
                )
            return reconciliation
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_reconciliation(
        self, idempotency_key: str
    ) -> PaymentReconciliation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM payment_reconciliations
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            return self._reconciliation(row)

    @staticmethod
    def _status_in_transaction(
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> PaymentReconciliationStatus:
        payment = connection.execute(
            "SELECT * FROM payments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if payment is None:
            raise PaymentValidationError("payment reservation does not exist")
        reconciliation = connection.execute(
            """
            SELECT * FROM payment_reconciliations
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return PaymentReconciliationStatus(
            receipt=SQLitePaymentStore._receipt(payment),
            reconciliation=SQLitePaymentStore._reconciliation(reconciliation),
        )

    def get_reconciliation_status(
        self, idempotency_key: str
    ) -> PaymentReconciliationStatus:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            status = self._status_in_transaction(connection, idempotency_key)
            connection.commit()
            return status
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_reconciliation_retryable(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
        returncode: int | None = None,
    ) -> PaymentReconciliationStatus:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            status = self._status_in_transaction(connection, idempotency_key)
            existing = status.reconciliation
            if (
                status.receipt.state is PaymentState.FAILED_RETRYABLE
                and existing is not None
            ):
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.RETRYABLE,
                    reason_code=reason_code,
                    explanation=explanation,
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                )
                connection.commit()
                return status
            if status.receipt.state is not PaymentState.SUBMITTING:
                raise PaymentValidationError(
                    "only a submitting payment can be marked retryable"
                )
            now = _utc_timestamp()
            connection.execute(
                """
                UPDATE payments SET state = ?
                WHERE idempotency_key = ?
                """,
                (PaymentState.FAILED_RETRYABLE.value, idempotency_key),
            )
            connection.execute(
                """
                INSERT INTO payment_reconciliations (
                    idempotency_key, payment_id, reason_code, explanation,
                    returncode, state, submission_status, evidence_reference,
                    resolved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    reason_code = excluded.reason_code,
                    explanation = excluded.explanation,
                    state = excluded.state,
                    submission_status = excluded.submission_status,
                    evidence_reference = excluded.evidence_reference,
                    transaction_hash = NULL,
                    resolved_by = excluded.resolved_by,
                    updated_at = excluded.updated_at
                """,
                (
                    idempotency_key,
                    status.receipt.payment_id,
                    reason_code,
                    explanation,
                    existing.returncode if existing else returncode,
                    ReconciliationState.RETRYABLE.value,
                    SubmissionStatus.NOT_SUBMITTED.value,
                    evidence_reference,
                    resolved_by,
                    existing.created_at if existing else now,
                    now,
                ),
            )
            updated = self._status_in_transaction(connection, idempotency_key)
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def confirm_reconciliation(
        self,
        idempotency_key: str,
        *,
        transaction_hash: str,
        explorer_url: str | None,
        confirmed_at: str | None,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        transaction_hash = normalize_transaction_hash(transaction_hash)
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            status = self._status_in_transaction(connection, idempotency_key)
            existing = status.reconciliation
            if status.receipt.state is PaymentState.CONFIRMED:
                if existing is None:
                    raise PaymentReplayError(
                        "confirmed payment has no reconciliation resolution"
                    )
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.CONFIRMED,
                    reason_code="verified_transaction",
                    explanation="verified transaction evidence confirms settlement",
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                    transaction_hash=transaction_hash,
                )
                connection.commit()
                return status
            if status.receipt.state not in {
                PaymentState.SUBMITTING,
                PaymentState.FAILED_RETRYABLE,
            }:
                raise PaymentValidationError(
                    "payment state cannot be reconciled as confirmed"
                )
            now = _utc_timestamp()
            connection.execute(
                """
                UPDATE payments
                SET state = ?, transaction_hash = ?, explorer_url = ?,
                    confirmed_at = ?
                WHERE idempotency_key = ?
                """,
                (
                    PaymentState.CONFIRMED.value,
                    transaction_hash,
                    explorer_url,
                    confirmed_at,
                    idempotency_key,
                ),
            )
            connection.execute(
                """
                INSERT INTO payment_reconciliations (
                    idempotency_key, payment_id, reason_code, explanation,
                    returncode, state, submission_status, evidence_reference,
                    transaction_hash, resolved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    reason_code = excluded.reason_code,
                    explanation = excluded.explanation,
                    state = excluded.state,
                    evidence_reference = excluded.evidence_reference,
                    transaction_hash = excluded.transaction_hash,
                    resolved_by = excluded.resolved_by,
                    updated_at = excluded.updated_at
                """,
                (
                    idempotency_key,
                    status.receipt.payment_id,
                    "verified_transaction",
                    "verified transaction evidence confirms settlement",
                    existing.returncode if existing else None,
                    ReconciliationState.CONFIRMED.value,
                    (
                        existing.submission_status.value
                        if existing
                        else SubmissionStatus.AMBIGUOUS.value
                    ),
                    evidence_reference,
                    transaction_hash,
                    resolved_by,
                    existing.created_at if existing else now,
                    now,
                ),
            )
            updated = self._status_in_transaction(connection, idempotency_key)
            connection.commit()
            return updated
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise PaymentReplayError(
                "transaction hash is already bound to another payment"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cancel_reconciliation(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        reason_code, explanation = _reconciliation_values(
            reason_code, explanation
        )
        evidence_reference, resolved_by = _resolution_values(
            evidence_reference, resolved_by
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            status = self._status_in_transaction(connection, idempotency_key)
            existing = status.reconciliation
            if (
                status.receipt.state is PaymentState.FAILED_TERMINAL
                and existing is not None
            ):
                _assert_resolution_replay(
                    existing,
                    state=ReconciliationState.CANCELLED,
                    reason_code=reason_code,
                    explanation=explanation,
                    evidence_reference=evidence_reference,
                    resolved_by=resolved_by,
                )
                connection.commit()
                return status
            if status.receipt.state not in {
                PaymentState.POLICY_APPROVED,
                PaymentState.SUBMITTING,
                PaymentState.FAILED_RETRYABLE,
            }:
                raise PaymentValidationError(
                    "payment state cannot be terminally cancelled"
                )
            now = _utc_timestamp()
            connection.execute(
                """
                UPDATE payments SET state = ?
                WHERE idempotency_key = ?
                """,
                (PaymentState.FAILED_TERMINAL.value, idempotency_key),
            )
            connection.execute(
                """
                INSERT INTO payment_reconciliations (
                    idempotency_key, payment_id, reason_code, explanation,
                    returncode, state, submission_status, evidence_reference,
                    resolved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    reason_code = excluded.reason_code,
                    explanation = excluded.explanation,
                    state = excluded.state,
                    evidence_reference = excluded.evidence_reference,
                    transaction_hash = NULL,
                    resolved_by = excluded.resolved_by,
                    updated_at = excluded.updated_at
                """,
                (
                    idempotency_key,
                    status.receipt.payment_id,
                    reason_code,
                    explanation,
                    existing.returncode if existing else None,
                    ReconciliationState.CANCELLED.value,
                    (
                        existing.submission_status.value
                        if existing
                        else SubmissionStatus.AMBIGUOUS.value
                    ),
                    evidence_reference,
                    resolved_by,
                    existing.created_at if existing else now,
                    now,
                ),
            )
            updated = self._status_in_transaction(connection, idempotency_key)
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def transition(
        self,
        idempotency_key: str,
        state: PaymentState,
        *,
        transaction_hash: str | None = None,
        explorer_url: str | None = None,
        confirmed_at: str | None = None,
    ) -> PaymentReceipt:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM payments WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise PaymentValidationError("payment reservation does not exist")
            current = self._receipt(row)
            if _check_idempotent_transition(
                current,
                state,
                transaction_hash=transaction_hash,
                explorer_url=explorer_url,
                confirmed_at=confirmed_at,
            ):
                connection.commit()
                return current
            _check_transition(current, state)
            transaction_hash = transaction_hash or current.transaction_hash
            explorer_url = explorer_url or current.explorer_url
            confirmed_at = confirmed_at or current.confirmed_at
            connection.execute(
                """
                UPDATE payments
                SET state = ?, transaction_hash = ?, explorer_url = ?, confirmed_at = ?
                WHERE idempotency_key = ?
                """,
                (
                    state.value,
                    transaction_hash,
                    explorer_url,
                    confirmed_at,
                    idempotency_key,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM payments WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            connection.commit()
            return self._receipt(updated)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise PaymentReplayError(
                "transaction hash is already bound to another payment"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


IdempotentPaymentStore = InMemoryPaymentStore
