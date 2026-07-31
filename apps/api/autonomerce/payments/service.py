"""End-to-end autonomous payment orchestration."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from autonomerce.contracts import PaymentReceipt, PaymentState

from .errors import CircleExecutionError, ReceiptVerificationError
from .executors import CircleExecutor
from .models import PaymentIntent, PaymentPolicy
from .policy import PaymentPolicyGate
from .store import PaymentStore
from .verification import ReceiptHook, verify_receipt


class PaymentProcessor:
    """Reserve, execute once, verify, and persist one policy-authorized payment."""

    def __init__(
        self,
        *,
        policy: PaymentPolicy,
        store: PaymentStore,
        executor: CircleExecutor,
        gate: PaymentPolicyGate | None = None,
        verification_hooks: Iterable[ReceiptHook] = (),
    ) -> None:
        if policy.mode is not executor.mode:
            raise ValueError("payment policy and executor modes must match")
        self.policy = policy
        self.store = store
        self.executor = executor
        self.gate = gate or PaymentPolicyGate()
        self.verification_hooks = tuple(verification_hooks)

    def pay(self, intent: PaymentIntent) -> PaymentReceipt:
        reservation = self.store.reserve(intent, self.policy, self.gate)
        if not reservation.created:
            # Idempotent retries never call the executor again, regardless of state.
            return reservation.receipt
        self.store.transition(intent.idempotency_key, PaymentState.SUBMITTING)
        try:
            execution = self.executor.execute(intent)
        except CircleExecutionError as exc:
            if exc.proven_not_submitted:
                self.store.mark_reconciliation_retryable(
                    intent.idempotency_key,
                    reason_code=exc.reason_code,
                    explanation=str(exc),
                    evidence_reference=(
                        f"circle-cli:returncode:"
                        f"{exc.returncode if exc.returncode is not None else 'not-started'}"
                    ),
                    resolved_by="system:circle-cli",
                    returncode=exc.returncode,
                )
            elif exc.terminal:
                self.store.transition(
                    intent.idempotency_key, PaymentState.FAILED_TERMINAL
                )
            else:
                self.store.record_reconciliation(
                    intent.idempotency_key,
                    reason_code=exc.reason_code,
                    explanation=str(exc),
                    returncode=exc.returncode,
                    submission_status=exc.submission_status,
                )
            # Ambiguous failures remain SUBMITTING and consume policy capacity.
            # Proven pre-submit failures become retryable and release capacity, but
            # ordinary pay() replay still returns stored state and never invokes the
            # executor a second time.
            raise
        candidate = replace(
            reservation.receipt,
            state=PaymentState.CONFIRMED,
            transaction_hash=execution.transaction_hash,
            explorer_url=execution.explorer_url,
            confirmed_at=execution.confirmed_at,
        )
        verdict = verify_receipt(
            candidate,
            intent,
            execution,
            mode=self.policy.mode,
            hooks=self.verification_hooks,
        )
        if not verdict.verified:
            # Keep SUBMITTING as an ambiguous reconciliation state. Never auto-retry.
            self.store.record_reconciliation(
                intent.idempotency_key,
                reason_code=verdict.reason_code,
                explanation=verdict.explanation,
            )
            raise ReceiptVerificationError(
                f"{verdict.reason_code}: {verdict.explanation}"
            )
        return self.store.transition(
            intent.idempotency_key,
            PaymentState.CONFIRMED,
            transaction_hash=candidate.transaction_hash,
            explorer_url=candidate.explorer_url,
            confirmed_at=candidate.confirmed_at,
        )
