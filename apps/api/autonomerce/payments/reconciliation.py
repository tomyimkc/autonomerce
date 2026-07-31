"""Operator-controlled reconciliation for interrupted Circle payments.

This module never invokes a payment executor. It only exposes durable, idempotent
state transitions after an authenticated API layer has authorized the operator.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from autonomerce.contracts import PaymentReceipt, PaymentState

from .errors import ReceiptVerificationError
from .models import (
    ExecutionResult,
    PaymentMode,
    ReceiptVerification,
    canonical_chain,
)
from .store import PaymentReconciliationStatus, PaymentStore


class TransactionEvidenceHook(Protocol):
    """Independently verify transaction evidence before durable confirmation."""

    def __call__(
        self,
        receipt: PaymentReceipt,
        evidence: ExecutionResult,
    ) -> bool | ReceiptVerification: ...


def _verify_reconciliation_evidence(
    receipt: PaymentReceipt,
    evidence: ExecutionResult,
    *,
    mode: PaymentMode,
    hooks: tuple[TransactionEvidenceHook, ...],
) -> None:
    if not hooks:
        raise ReceiptVerificationError(
            "independent transaction evidence verification hook is required"
        )
    if evidence.state != "CONFIRMED" or evidence.transaction_hash is None:
        raise ReceiptVerificationError(
            "transaction evidence does not prove confirmation"
        )
    if canonical_chain(receipt.chain) != evidence.chain:
        raise ReceiptVerificationError(
            "transaction evidence chain does not match the reserved payment"
        )
    if receipt.token != evidence.token:
        raise ReceiptVerificationError(
            "transaction evidence token does not match the reserved payment"
        )
    if receipt.asset != evidence.asset:
        raise ReceiptVerificationError(
            "transaction evidence asset does not match the reserved payment"
        )
    if mode.is_live and (
        receipt.asset is None or receipt.asset == receipt.token
    ):
        raise ReceiptVerificationError(
            "live reconciliation requires a canonical USDC contract binding"
        )
    if receipt.amount_usdc != evidence.amount_usdc:
        raise ReceiptVerificationError(
            "transaction evidence amount does not match the reserved payment"
        )
    if receipt.payer_wallet.lower() != evidence.payer_wallet.lower():
        raise ReceiptVerificationError(
            "transaction evidence payer does not match the reserved payment"
        )
    if receipt.payee_wallet.lower() != evidence.payee_wallet.lower():
        raise ReceiptVerificationError(
            "transaction evidence payee does not match the reserved payment"
        )
    if mode is PaymentMode.OFFLINE and not evidence.simulated:
        raise ReceiptVerificationError(
            "offline reconciliation requires simulated evidence"
        )
    if mode.is_live and evidence.simulated:
        raise ReceiptVerificationError(
            "live reconciliation rejects simulated evidence"
        )
    for hook in hooks:
        name = getattr(hook, "__name__", hook.__class__.__name__)
        try:
            verdict = hook(receipt, evidence)
        except Exception as exc:
            raise ReceiptVerificationError(
                f"transaction evidence hook {name} raised an exception"
            ) from exc
        if isinstance(verdict, ReceiptVerification):
            if not verdict.verified:
                raise ReceiptVerificationError(
                    f"{verdict.reason_code}: {verdict.explanation}"
                )
        elif verdict is not True:
            raise ReceiptVerificationError(
                f"transaction evidence hook {name} did not verify the transaction"
            )


class PaymentReconciler:
    """Durable reconciliation commands with no automatic resubmission path."""

    def __init__(
        self,
        *,
        store: PaymentStore,
        mode: PaymentMode | str,
        verification_hooks: Iterable[TransactionEvidenceHook] = (),
    ) -> None:
        self.store = store
        self.mode = PaymentMode.parse(mode)
        self.verification_hooks = tuple(verification_hooks)

    def query_status(
        self,
        idempotency_key: str,
    ) -> PaymentReconciliationStatus:
        return self.store.get_reconciliation_status(idempotency_key)

    def mark_proven_not_submitted_retryable(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
        explanation: str,
        evidence_reference: str,
        resolved_by: str,
    ) -> PaymentReconciliationStatus:
        return self.store.mark_reconciliation_retryable(
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
        status = self.store.get_reconciliation_status(idempotency_key)
        if status.receipt.state is PaymentState.FAILED_TERMINAL:
            raise ReceiptVerificationError(
                "terminally cancelled payment cannot be confirmed"
            )
        _verify_reconciliation_evidence(
            status.receipt,
            evidence,
            mode=self.mode,
            hooks=self.verification_hooks,
        )
        return self.store.confirm_reconciliation(
            idempotency_key,
            transaction_hash=evidence.transaction_hash or "",
            explorer_url=evidence.explorer_url,
            confirmed_at=evidence.confirmed_at,
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
        return self.store.cancel_reconciliation(
            idempotency_key,
            reason_code=reason_code,
            explanation=explanation,
            evidence_reference=evidence_reference,
            resolved_by=resolved_by,
        )
