from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api import AdapterBundle, create_app  # noqa: E402
from autonomerce.api.reconciliation import PaymentReconciliationAPI  # noqa: E402
from autonomerce.api.rate_limit import (  # noqa: E402
    RateLimitPolicy,
    RequestLimiter,
    RouteBudget,
)
from autonomerce.api.repository import SettlementAuthorization  # noqa: E402
from autonomerce.api.sqlite_repository import SQLiteRepository  # noqa: E402
from autonomerce.contracts import (  # noqa: E402
    CapabilityDescriptor,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
)
from autonomerce.payments import (  # noqa: E402
    ExecutionResult,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    SQLitePaymentStore,
)


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + ("a" * 64)
AUTHORIZATION = {"Authorization": "Bearer owner-token"}


class ReconciliationPaymentAdapter:
    mode = PaymentMode.TESTNET
    independent_verification = True

    def __init__(self, store: SQLitePaymentStore) -> None:
        self.store = store
        self.execute_calls = 0

    def execute_payment(self, *_: Any, **__: Any) -> Any:
        self.execute_calls += 1
        raise AssertionError("reconciliation routes must never submit a payment")


def _budget(requests: int) -> RouteBudget:
    return RouteBudget(
        owner_requests=requests,
        ip_requests=requests,
        window_seconds=60,
        owner_concurrency=4,
        ip_concurrency=4,
    )


def _build_fixture(
    tmp_path: Path,
    *,
    proposal_owner: str = "tenant-a",
    app_owner: str = "tenant-a",
    verification_hooks=(),
    rate_limiter: RequestLimiter | None = None,
):
    repository = SQLiteRepository(str(tmp_path / "commerce.sqlite3"))
    store = SQLitePaymentStore(tmp_path / "payments.sqlite3")
    adapter = ReconciliationPaymentAdapter(store)
    seller_id = "seller-reconciliation-route"
    seller_url = "https://seller.example/agent"
    capability = CapabilityDescriptor(
        capability_id="capability-reconciliation-route",
        name="Reconciliation fixture",
        description="Provide a proposal owner for payment reconciliation",
    )
    sku = ServiceSKU(
        sku_id="sku-reconciliation-route",
        capability_id=capability.capability_id,
        name="Reconciliation fixture",
        outcome="Resolve one interrupted payment",
        base_price_usdc=Decimal("1"),
        maximum_latency_seconds=60,
        capacity_per_hour=1,
    )
    repository.save_seller(
        {
            "seller_id": seller_id,
            "name": "Reconciliation seller",
            "agent_url": seller_url,
            "source_kind": "test",
            "manifest": {},
            "wallet_address": PAYEE,
            "network": "ARC-TESTNET",
            "created_at": "2026-07-31T00:00:00Z",
        },
        owner_id=proposal_owner,
    )
    repository.save_capability(seller_id, capability)
    repository.save_sku(seller_id, sku)
    proposal = Proposal(
        proposal_id="proposal-reconciliation-route",
        seller_agent_url=seller_url,
        buyer_agent_url="https://buyer.example/agent",
        sku_id=sku.sku_id,
        problem_observed="A payment result needs reconciliation",
        offered_outcome="Resolve the durable payment state",
        price_usdc=Decimal("1"),
        delivery_seconds=60,
        state=ProposalState.ACCEPTED,
    )
    repository.save_proposal(
        proposal,
        owner_id=proposal_owner,
        contract_hash="sha256:" + ("c" * 64),
    )
    repository.accept_proposal(
        proposal,
        SettlementAuthorization(
            authorization_id="settlement-reconciliation-route",
            proposal_id=proposal.proposal_id,
            proposal_revision=proposal.revision,
            proposal_contract_hash="sha256:" + ("c" * 64),
            amount_usdc=proposal.price_usdc,
            payer_wallet=PAYER,
            payee_wallet=PAYEE,
            chain="ARC-TESTNET",
            token="USDC",
            asset="0x3600000000000000000000000000000000000000",
            commercial_policy_id="route-reconciliation-policy",
            commercial_policy_version="sha256:route-policy",
            seller_configuration_id=seller_id,
            seller_configuration_version="sha256:route-seller",
            expires_at="2030-01-01T00:00:00Z",
            created_at="2026-07-31T00:00:00Z",
        ),
        owner_id=proposal_owner,
        contract_hash="sha256:" + ("c" * 64),
    )
    payment_intent = PaymentIntent(
        proposal_id=proposal.proposal_id,
        idempotency_key="reconciliation-route-1",
        amount_usdc=proposal.price_usdc,
        proposal_state=ProposalState.ACCEPTED,
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
    )
    policy = PaymentPolicy(
        policy_id="route-reconciliation-policy",
        mode=PaymentMode.TESTNET,
        maximum_per_payment_usdc=Decimal("2"),
        maximum_total_usdc=Decimal("5"),
        allowed_chains=("ARC-TESTNET",),
        allowed_token="USDC",
        allowed_payer_wallets=(PAYER,),
        allowed_payee_wallets=(PAYEE,),
    )
    store.reserve(payment_intent, policy)
    store.transition(payment_intent.idempotency_key, PaymentState.SUBMITTING)
    store.record_reconciliation(
        payment_intent.idempotency_key,
        reason_code="circle_cli_timeout",
        explanation="Circle CLI timed out; settlement status is ambiguous",
    )
    app = create_app(
        repository=repository,
        adapters=AdapterBundle(payment=adapter),
        bearer_token="owner-token",
        owner_id=app_owner,
        payment_mode="testnet",
        trusted_hosts=["testserver"],
        rate_limiter=rate_limiter,
        transaction_verification_hooks=verification_hooks,
    )
    return app, repository, store, adapter, proposal


def _resolution_payload() -> dict[str, str]:
    return {
        "reasonCode": "operator_lookup_not_found",
        "explanation": "Verified provider lookup found no submitted transfer",
        "evidenceReference": "circle-audit:lookup-123",
    }


def _confirmation_payload() -> dict[str, str]:
    return {
        "transactionHash": TX_HASH,
        "amountUsdc": "1",
        "chain": "ARC-TESTNET",
        "payerWallet": PAYER,
        "payeeWallet": PAYEE,
        "confirmedAt": "2026-07-31T12:00:00Z",
        "explorerUrl": f"https://explorer.example/tx/{TX_HASH}",
        "providerReference": "circle-transfer-verified",
        "evidenceReference": "base-rpc:block-123:receipt-7",
    }


def test_reconciliation_routes_require_bearer_authentication(tmp_path):
    app, _, _, _, _ = _build_fixture(tmp_path)
    with TestClient(app) as client:
        missing = client.get(
            "/payment-reconciliations/reconciliation-route-1"
        )
        wrong = client.get(
            "/payment-reconciliations/reconciliation-route-1",
            headers={"Authorization": "Bearer wrong-token"},
        )
    with TestClient(create_app()) as offline_client:
        offline_without_auth = offline_client.get(
            "/payment-reconciliations/reconciliation-route-1"
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert offline_without_auth.status_code == 401


def test_reconciliation_routes_enforce_proposal_owner_scope(tmp_path):
    app, _, _, _, _ = _build_fixture(
        tmp_path,
        proposal_owner="tenant-b",
        app_owner="tenant-a",
    )
    with TestClient(app) as client:
        response = client.get(
            "/payment-reconciliations/reconciliation-route-1",
            headers=AUTHORIZATION,
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": (
            "payment reconciliation is not owned by the authenticated tenant"
        )
    }


def test_query_and_mark_retryable_are_durable_idempotent_and_never_submit(
    tmp_path,
):
    app, _, store, adapter, _ = _build_fixture(tmp_path)
    path = "/payment-reconciliations/reconciliation-route-1"
    with TestClient(app) as client:
        pending = client.get(path, headers=AUTHORIZATION)
        marked = client.post(
            f"{path}/mark-retryable",
            headers=AUTHORIZATION,
            json=_resolution_payload(),
        )
        replay = client.post(
            f"{path}/mark-retryable",
            headers=AUTHORIZATION,
            json=_resolution_payload(),
        )
        conflict_payload = {
            **_resolution_payload(),
            "evidenceReference": "circle-audit:different",
        }
        conflict = client.post(
            f"{path}/mark-retryable",
            headers=AUTHORIZATION,
            json=conflict_payload,
        )

    assert pending.status_code == 200
    assert pending.json()["paymentState"] == "submitting"
    assert pending.json()["requiresOperatorAction"] is True
    assert pending.json()["reconciliation"]["state"] == "pending"
    assert marked.status_code == 200
    assert marked.json()["paymentState"] == "failed_retryable"
    assert (
        marked.json()["reconciliation"]["state"]
        == "proven_not_submitted_retryable"
    )
    assert marked.json()["reconciliation"]["resolvedBy"] == "owner:tenant-a"
    assert replay.status_code == 200
    assert replay.json() == marked.json()
    assert conflict.status_code == 409
    assert (
        store.get("reconciliation-route-1").state
        is PaymentState.FAILED_RETRYABLE
    )
    assert adapter.execute_calls == 0


def test_confirm_fails_closed_without_independent_verification_hooks(tmp_path):
    app, repository, store, adapter, proposal = _build_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/payment-reconciliations/reconciliation-route-1/confirm",
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "independent transaction verification is not configured"
    }
    assert store.get("reconciliation-route-1").state is PaymentState.SUBMITTING
    assert repository.payment_for_proposal(proposal.proposal_id) is None
    assert adapter.execute_calls == 0


def test_confirm_requires_verified_evidence_and_projects_commerce_state(
    tmp_path,
):
    hook_calls = []

    def verified_transaction(receipt, evidence):
        hook_calls.append((receipt.payment_id, evidence.transaction_hash))
        return evidence.provider_reference == "circle-transfer-verified"

    app, repository, store, adapter, proposal = _build_fixture(
        tmp_path,
        verification_hooks=(verified_transaction,),
    )
    path = "/payment-reconciliations/reconciliation-route-1/confirm"
    with TestClient(app) as client:
        confirmed = client.post(
            path,
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )
        replay = client.post(
            path,
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["paymentState"] == "confirmed"
    assert confirmed.json()["transactionHash"] == TX_HASH
    assert confirmed.json()["reconciliation"]["state"] == "confirmed"
    assert replay.status_code == 200
    assert replay.json() == confirmed.json()
    assert store.get("reconciliation-route-1").state is PaymentState.CONFIRMED
    commerce_payment = repository.payment_for_proposal(proposal.proposal_id)
    assert commerce_payment is not None
    assert commerce_payment.transaction_hash == TX_HASH
    assert (
        repository.get_proposal(proposal.proposal_id).state
        is ProposalState.PAID
    )
    assert hook_calls == [
        (confirmed.json()["paymentId"], TX_HASH),
        (confirmed.json()["paymentId"], TX_HASH),
    ]
    assert adapter.execute_calls == 0


def test_confirm_replay_recovers_missing_commerce_projection(tmp_path):
    def verified_transaction(receipt, evidence):
        return evidence.transaction_hash == TX_HASH

    app, repository, store, adapter, proposal = _build_fixture(
        tmp_path,
        verification_hooks=(verified_transaction,),
    )
    evidence = ExecutionResult(
        state="CONFIRMED",
        amount_usdc=Decimal("1"),
        chain="ARC-TESTNET",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        transaction_hash=TX_HASH,
        confirmed_at="2026-07-31T12:00:00Z",
        explorer_url=f"https://explorer.example/tx/{TX_HASH}",
        simulated=False,
        provider_reference="circle-transfer-verified",
    )
    PaymentReconciliationAPI(
        store=store,
        mode=PaymentMode.TESTNET,
        verification_hooks=(verified_transaction,),
    ).confirm_from_verified_transaction(
        "reconciliation-route-1",
        evidence=evidence,
        evidence_reference="base-rpc:block-123:receipt-7",
        resolved_by="owner:tenant-a",
    )
    assert repository.payment_for_proposal(proposal.proposal_id) is None

    with TestClient(app) as client:
        recovered = client.post(
            "/payment-reconciliations/reconciliation-route-1/confirm",
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )

    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["paymentState"] == "confirmed"
    assert (
        repository.payment_for_proposal(proposal.proposal_id).transaction_hash
        == TX_HASH
    )
    assert (
        repository.get_proposal(proposal.proposal_id).state
        is ProposalState.PAID
    )
    assert adapter.execute_calls == 0


def test_rejected_evidence_and_terminal_cancel_fail_closed(tmp_path):
    app, repository, store, adapter, proposal = _build_fixture(
        tmp_path,
        verification_hooks=(lambda receipt, evidence: False,),
    )
    base = "/payment-reconciliations/reconciliation-route-1"
    with TestClient(app) as client:
        rejected = client.post(
            f"{base}/confirm",
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )
        cancelled = client.post(
            f"{base}/cancel",
            headers=AUTHORIZATION,
            json={
                "reasonCode": "owner_cancelled",
                "explanation": "Owner terminally cancelled the payment",
                "evidenceReference": "support-case:cancel-9",
            },
        )
        confirm_after_cancel = client.post(
            f"{base}/confirm",
            headers=AUTHORIZATION,
            json=_confirmation_payload(),
        )

    assert rejected.status_code == 409
    assert rejected.json() == {
        "detail": "transaction evidence was not independently verified"
    }
    assert cancelled.status_code == 200
    assert cancelled.json()["paymentState"] == "failed_terminal"
    assert cancelled.json()["reconciliation"]["state"] == "cancelled"
    assert confirm_after_cancel.status_code == 409
    assert repository.payment_for_proposal(proposal.proposal_id) is None
    assert store.get("reconciliation-route-1").state is PaymentState.FAILED_TERMINAL
    assert adapter.execute_calls == 0


def test_reconciliation_commands_use_existing_strict_payment_rate_budget(
    tmp_path,
):
    limiter = RequestLimiter(
        policy=RateLimitPolicy(
            standard=_budget(20),
            gemini=_budget(20),
            payment=_budget(1),
            fulfillment=_budget(20),
        )
    )
    app, _, _, _, _ = _build_fixture(
        tmp_path,
        rate_limiter=limiter,
    )
    path = "/payment-reconciliations/reconciliation-route-1/cancel"
    payload = {
        "reasonCode": "owner_cancelled",
        "explanation": "Owner terminally cancelled the payment",
        "evidenceReference": "support-case:cancel-rate-limit",
    }
    with TestClient(app) as client:
        first = client.post(path, headers=AUTHORIZATION, json=payload)
        limited = client.post(path, headers=AUTHORIZATION, json=payload)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json() == {"detail": "request rate limit exceeded"}
    assert limited.headers["retry-after"] == "60"
