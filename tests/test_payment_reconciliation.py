from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api.reconciliation import PaymentReconciliationAPI  # noqa: E402
from autonomerce.contracts import PaymentState, ProposalState  # noqa: E402
from autonomerce.payments import (  # noqa: E402
    CircleCLIExecutor,
    CircleExecutionError,
    ExecutionResult,
    InMemoryPaymentStore,
    OfflineCircleExecutor,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    PaymentPolicyDenied,
    PaymentProcessor,
    PaymentReplayError,
    PaymentValidationError,
    ReceiptVerificationError,
    ReconciliationState,
    SQLitePaymentStore,
    SubmissionStatus,
)


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + ("a" * 64)
OTHER_TX_HASH = "0x" + ("b" * 64)
FIXED_TIME = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def executable_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def intent(
    *,
    key: str = "reconcile-1",
    proposal_id: str = "proposal-reconcile-1",
    amount: str = "1",
) -> PaymentIntent:
    return PaymentIntent(
        proposal_id=proposal_id,
        idempotency_key=key,
        amount_usdc=Decimal(amount),
        proposal_state=ProposalState.ACCEPTED,
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
    )


def policy(*, maximum: str = "2") -> PaymentPolicy:
    return PaymentPolicy(
        policy_id="reconciliation-policy",
        mode=PaymentMode.TESTNET,
        maximum_per_payment_usdc=Decimal(maximum),
        maximum_total_usdc=Decimal("5"),
        allowed_chains=("ARC-TESTNET",),
        allowed_token="USDC",
        allowed_payer_wallets=(PAYER,),
        allowed_payee_wallets=(PAYEE,),
    )


def confirmed_evidence(
    *,
    transaction_hash: str = TX_HASH,
) -> ExecutionResult:
    return ExecutionResult(
        state="CONFIRMED",
        amount_usdc=Decimal("1"),
        chain="ARC-TESTNET",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        transaction_hash=transaction_hash,
        confirmed_at="2026-07-31T12:00:00Z",
        explorer_url=f"https://explorer.example/tx/{transaction_hash}",
        simulated=False,
        provider_reference="circle-transfer-reconciled",
    )


def timeout_processor(database: Path):
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    processor = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            runner=runner,
        ),
    )
    return processor, calls


def test_policy_denial_is_proven_pre_submit_and_never_calls_circle():
    store = InMemoryPaymentStore()
    payment_intent = intent(amount="1")
    executor = OfflineCircleExecutor()
    processor = PaymentProcessor(
        policy=PaymentPolicy(
            policy_id="denied-policy",
            mode=PaymentMode.OFFLINE,
            maximum_per_payment_usdc=Decimal("0.5"),
            maximum_total_usdc=Decimal("5"),
            allowed_chains=("ARC-TESTNET",),
            allowed_token="USDC",
            allowed_payer_wallets=(PAYER,),
            allowed_payee_wallets=(PAYEE,),
        ),
        store=store,
        executor=executor,
    )

    with pytest.raises(PaymentPolicyDenied) as denied:
        processor.pay(payment_intent)

    assert denied.value.reason_code == "per_payment_limit"
    assert executor.calls == []
    assert store.get(payment_intent.idempotency_key) is None


@pytest.mark.parametrize(
    ("stderr", "expected_reason"),
    [
        (
            "insufficient balance; no transfer submitted",
            "circle_cli_insufficient_balance",
        ),
        (
            json.dumps(
                {
                    "error": {
                        "code": "WALLET_POLICY_DENIED",
                        "submitted": False,
                    }
                }
            ),
            "circle_cli_policy_denied",
        ),
        (
            json.dumps(
                {
                    "error": {
                        "code": "INVALID_CONFIGURATION",
                        "stage": "pre-submit",
                    }
                }
            ),
            "circle_cli_invalid_configuration",
        ),
    ],
)
def test_proven_circle_rejection_becomes_retryable_without_auto_resubmit(
    tmp_path, stderr, expected_reason
):
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 2, "", stderr)

    database = tmp_path / "rejected.sqlite3"
    payment_intent = intent()
    processor = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            runner=runner,
        ),
    )

    with pytest.raises(CircleExecutionError) as failure:
        processor.pay(payment_intent)

    assert failure.value.proven_not_submitted
    assert not failure.value.reconciliation_required
    reopened = SQLitePaymentStore(database)
    status = reopened.get_reconciliation_status(payment_intent.idempotency_key)
    assert status.receipt.state is PaymentState.FAILED_RETRYABLE
    assert status.reconciliation is not None
    assert status.reconciliation.state is ReconciliationState.RETRYABLE
    assert (
        status.reconciliation.submission_status
        is SubmissionStatus.NOT_SUBMITTED
    )
    assert status.reconciliation.reason_code == expected_reason
    assert reopened.snapshot("reconciliation-policy").committed_usdc == Decimal("0")

    replay = PaymentProcessor(
        policy=policy(),
        store=reopened,
        executor=processor.executor,
    ).pay(payment_intent)
    assert replay.state is PaymentState.FAILED_RETRYABLE
    assert len(calls) == 1


def test_timeout_stays_ambiguous_durable_and_blocked_from_replay(tmp_path):
    database = tmp_path / "timeout.sqlite3"
    processor, calls = timeout_processor(database)
    payment_intent = intent()

    with pytest.raises(CircleExecutionError) as failure:
        processor.pay(payment_intent)

    assert failure.value.reconciliation_required
    reopened = SQLitePaymentStore(database)
    status = reopened.get_reconciliation_status(payment_intent.idempotency_key)
    assert status.receipt.state is PaymentState.SUBMITTING
    assert status.requires_operator_action
    assert status.reconciliation is not None
    assert status.reconciliation.state is ReconciliationState.PENDING
    assert status.reconciliation.submission_status is SubmissionStatus.AMBIGUOUS

    replay = PaymentProcessor(
        policy=policy(),
        store=reopened,
        executor=processor.executor,
    ).pay(payment_intent)
    assert replay.state is PaymentState.SUBMITTING
    assert len(calls) == 1


def test_structured_post_submit_failure_remains_ambiguous(tmp_path):
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            2,
            "",
            json.dumps(
                {
                    "error": {
                        "code": "INSUFFICIENT_BALANCE",
                        "submitted": True,
                        "transferId": "circle-transfer-pending",
                    }
                }
            ),
        )

    database = tmp_path / "post-submit.sqlite3"
    processor = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            runner=runner,
        ),
    )

    with pytest.raises(CircleExecutionError) as failure:
        processor.pay(intent())

    assert failure.value.reconciliation_required
    assert not failure.value.proven_not_submitted
    status = SQLitePaymentStore(database).get_reconciliation_status("reconcile-1")
    assert status.receipt.state is PaymentState.SUBMITTING
    assert status.reconciliation is not None
    assert (
        status.reconciliation.reason_code
        == "circle_cli_rejection_ambiguous"
    )
    assert len(calls) == 1


def test_authenticated_api_can_mark_ambiguity_proven_not_submitted(tmp_path):
    database = tmp_path / "manual-retryable.sqlite3"
    processor, calls = timeout_processor(database)
    payment_intent = intent()
    with pytest.raises(CircleExecutionError):
        processor.pay(payment_intent)

    api = PaymentReconciliationAPI(
        store=SQLitePaymentStore(database),
        mode=PaymentMode.TESTNET,
    )
    status = api.mark_proven_not_submitted_retryable(
        payment_intent.idempotency_key,
        reason_code="operator_lookup_not_found",
        explanation="Circle lookup proved no transfer or transaction exists",
        evidence_reference="circle-lookup:audit-123",
        resolved_by="owner:alice",
    )
    assert status.receipt.state is PaymentState.FAILED_RETRYABLE
    assert status.reconciliation is not None
    assert status.reconciliation.state is ReconciliationState.RETRYABLE

    same = api.mark_proven_not_submitted_retryable(
        payment_intent.idempotency_key,
        reason_code="operator_lookup_not_found",
        explanation="Circle lookup proved no transfer or transaction exists",
        evidence_reference="circle-lookup:audit-123",
        resolved_by="owner:alice",
    )
    assert same == status
    with pytest.raises(PaymentReplayError):
        api.mark_proven_not_submitted_retryable(
            payment_intent.idempotency_key,
            reason_code="operator_lookup_not_found",
            explanation="Circle lookup proved no transfer or transaction exists",
            evidence_reference="circle-lookup:different-audit",
            resolved_by="owner:alice",
        )

    replay = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=processor.executor,
    ).pay(payment_intent)
    assert replay.state is PaymentState.FAILED_RETRYABLE
    assert len(calls) == 1


def test_verified_transaction_confirmation_is_durable_and_replay_safe(tmp_path):
    database = tmp_path / "confirmed.sqlite3"
    processor, calls = timeout_processor(database)
    payment_intent = intent()
    with pytest.raises(CircleExecutionError):
        processor.pay(payment_intent)

    hook_calls = []

    def verified_lookup(receipt, evidence):
        hook_calls.append((receipt.payment_id, evidence.transaction_hash))
        return True

    api = PaymentReconciliationAPI(
        store=SQLitePaymentStore(database),
        mode=PaymentMode.TESTNET,
        verification_hooks=(verified_lookup,),
    )
    evidence = confirmed_evidence()
    status = api.confirm_from_verified_transaction(
        payment_intent.idempotency_key,
        evidence=evidence,
        evidence_reference="base-rpc:block-123:receipt-7",
        resolved_by="owner:alice",
    )
    assert status.receipt.state is PaymentState.CONFIRMED
    assert status.receipt.transaction_hash == TX_HASH
    assert status.reconciliation is not None
    assert status.reconciliation.state is ReconciliationState.CONFIRMED

    reopened = PaymentReconciliationAPI(
        store=SQLitePaymentStore(database),
        mode=PaymentMode.TESTNET,
        verification_hooks=(verified_lookup,),
    )
    assert (
        reopened.query_status(payment_intent.idempotency_key).receipt.state
        is PaymentState.CONFIRMED
    )
    replay = reopened.confirm_from_verified_transaction(
        payment_intent.idempotency_key,
        evidence=evidence,
        evidence_reference="base-rpc:block-123:receipt-7",
        resolved_by="owner:alice",
    )
    assert replay == status
    with pytest.raises(PaymentReplayError):
        reopened.confirm_from_verified_transaction(
            payment_intent.idempotency_key,
            evidence=confirmed_evidence(transaction_hash=OTHER_TX_HASH),
            evidence_reference="base-rpc:block-124:receipt-8",
            resolved_by="owner:alice",
        )

    ordinary_replay = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=processor.executor,
    ).pay(payment_intent)
    assert ordinary_replay.state is PaymentState.CONFIRMED
    assert len(calls) == 1
    assert len(hook_calls) == 3


def test_confirmation_requires_independent_verified_evidence(tmp_path):
    database = tmp_path / "unverified.sqlite3"
    processor, _ = timeout_processor(database)
    with pytest.raises(CircleExecutionError):
        processor.pay(intent())

    api = PaymentReconciliationAPI(
        store=SQLitePaymentStore(database),
        mode=PaymentMode.TESTNET,
    )
    with pytest.raises(ReceiptVerificationError, match="hook is required"):
        api.confirm_from_verified_transaction(
            "reconcile-1",
            evidence=confirmed_evidence(),
            evidence_reference="unverified-input",
            resolved_by="owner:alice",
        )
    assert api.query_status("reconcile-1").receipt.state is PaymentState.SUBMITTING


def test_terminal_cancel_is_durable_and_never_resubmits(tmp_path):
    database = tmp_path / "cancelled.sqlite3"
    processor, calls = timeout_processor(database)
    payment_intent = intent()
    with pytest.raises(CircleExecutionError):
        processor.pay(payment_intent)

    api = PaymentReconciliationAPI(
        store=SQLitePaymentStore(database),
        mode=PaymentMode.TESTNET,
        verification_hooks=(lambda receipt, evidence: True,),
    )
    status = api.cancel_terminal(
        payment_intent.idempotency_key,
        reason_code="owner_cancelled",
        explanation="Owner chose not to settle or retry this order",
        evidence_reference="support-case:cancel-9",
        resolved_by="owner:alice",
    )
    assert status.receipt.state is PaymentState.FAILED_TERMINAL
    assert status.reconciliation is not None
    assert status.reconciliation.state is ReconciliationState.CANCELLED

    same = api.cancel_terminal(
        payment_intent.idempotency_key,
        reason_code="owner_cancelled",
        explanation="Owner chose not to settle or retry this order",
        evidence_reference="support-case:cancel-9",
        resolved_by="owner:alice",
    )
    assert same == status
    with pytest.raises(ReceiptVerificationError, match="terminally cancelled"):
        api.confirm_from_verified_transaction(
            payment_intent.idempotency_key,
            evidence=confirmed_evidence(),
            evidence_reference="base-rpc:block-123:receipt-7",
            resolved_by="owner:alice",
        )

    replay = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=processor.executor,
    ).pay(payment_intent)
    assert replay.state is PaymentState.FAILED_TERMINAL
    assert len(calls) == 1


def test_circle_cli_requires_explicit_absolute_path():
    with pytest.raises(PaymentValidationError, match="absolute executable path"):
        CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            binary="circle",
            runner=lambda *args, **kwargs: None,
        )


def test_circle_cli_uses_sanitized_environment_and_fixed_cwd(
    tmp_path, monkeypatch
):
    executable = tmp_path / "circle-fixture"
    payload = {
        "data": {
            "id": "circle-transfer-1",
            "state": "CONFIRMED",
            "blockchain": "ARC-TESTNET",
            "amounts": ["1"],
            "sourceAddress": PAYER,
            "destinationAddress": PAYEE,
            "txHash": TX_HASH,
            "updateDate": "2026-07-31T12:00:00Z",
        }
    }
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os\n"
        f"payload = {payload!r}\n"
        "payload['data']['cwd'] = os.getcwd()\n"
        "payload['data']['leaked'] = os.environ.get('AUTONOMERCE_SHOULD_NOT_LEAK')\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    monkeypatch.setenv("AUTONOMERCE_SHOULD_NOT_LEAK", "secret-value")

    result = CircleCLIExecutor(
        mode=PaymentMode.TESTNET,
        binary=str(executable),
        binary_sha256=executable_sha256(executable),
        working_directory="/",
        timeout_seconds=5,
    ).execute(intent())

    assert result.raw["cwd"] == "/"
    assert result.raw["leaked"] is None


def test_circle_cli_refuses_an_unpinned_or_changed_binary(tmp_path):
    executable = tmp_path / "circle-fixture"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)

    with pytest.raises(
        PaymentValidationError,
        match="requires a pinned executable SHA-256",
    ):
        CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            binary=str(executable),
        )
    with pytest.raises(
        PaymentValidationError,
        match="does not match the pinned value",
    ):
        CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            binary=str(executable),
            binary_sha256="0" * 64,
        )


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_circle_cli_hard_output_caps_record_ambiguous_state(tmp_path, stream):
    executable = tmp_path / f"circle-noisy-{stream}"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.{stream}.write('x' * 4096)\n"
        f"sys.{stream}.flush()\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    database = tmp_path / f"{stream}-cap.sqlite3"
    processor = PaymentProcessor(
        policy=policy(),
        store=SQLitePaymentStore(database),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            binary=str(executable),
            binary_sha256=executable_sha256(executable),
            timeout_seconds=5,
            max_output_bytes=1024,
        ),
    )

    with pytest.raises(CircleExecutionError) as failure:
        processor.pay(intent())

    assert failure.value.reason_code == "circle_cli_output_limit"
    assert failure.value.reconciliation_required
    assert len(str(failure.value)) < 200
    status = SQLitePaymentStore(database).get_reconciliation_status("reconcile-1")
    assert status.receipt.state is PaymentState.SUBMITTING
    assert status.reconciliation is not None
    assert status.reconciliation.reason_code == "circle_cli_output_limit"
