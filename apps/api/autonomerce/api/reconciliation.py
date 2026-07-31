"""API-facing payment reconciliation facade.

The FastAPI application can wire this class into authenticated, owner-scoped routes
later. This module deliberately defines no public route and does not modify app.py.
Authentication and object authorization must complete before invoking a command;
the durable ``resolved_by`` audit field should be derived from that principal.
"""

from __future__ import annotations

from collections.abc import Iterable

from autonomerce.payments.models import ExecutionResult, PaymentMode
from autonomerce.payments.reconciliation import (
    PaymentReconciler,
    TransactionEvidenceHook,
)
from autonomerce.payments.store import (
    PaymentReconciliationStatus,
    PaymentStore,
)


class PaymentReconciliationAPI:
    """Stable command/query surface for a future authenticated HTTP layer."""

    def __init__(
        self,
        *,
        store: PaymentStore,
        mode: PaymentMode | str,
        verification_hooks: Iterable[TransactionEvidenceHook] = (),
    ) -> None:
        self._reconciler = PaymentReconciler(
            store=store,
            mode=mode,
            verification_hooks=verification_hooks,
        )

    def query_status(
        self,
        idempotency_key: str,
    ) -> PaymentReconciliationStatus:
        return self._reconciler.query_status(idempotency_key)

    def mark_proven_not_submitted_retryable(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        return self._reconciler.mark_proven_not_submitted_retryable(
            idempotency_key,
            reason_code=reason_code,
            explanation=explanation,
            evidence_reference=evidence_reference,
            resolved_by=resolved_by,
        )

    def confirm_from_verified_transaction(
        self,
        idempotency_key: str,
        *,
        evidence: ExecutionResult,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        return self._reconciler.confirm_from_verified_transaction(
            idempotency_key,
            evidence=evidence,
            evidence_reference=evidence_reference,
            resolved_by=resolved_by,
        )

    def cancel_terminal(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        return self._reconciler.cancel_terminal(
            idempotency_key,
            reason_code=reason_code,
            explanation=explanation,
            evidence_reference=evidence_reference,
            resolved_by=resolved_by,
        )
