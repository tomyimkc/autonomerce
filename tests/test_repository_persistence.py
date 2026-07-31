from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api.adapters import AdapterBundle  # noqa: E402
from autonomerce.api.app import create_app  # noqa: E402
from autonomerce.api.repository import (  # noqa: E402
    InMemoryRepository,
    ProspectRecord,
    ReceiptPublication,
    RepositoryDurability,
    SettlementAuthorization,
    monotonic_proposal,
)
from autonomerce.api.sqlite_repository import SQLiteRepository  # noqa: E402
from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
)
from autonomerce.payments import (  # noqa: E402
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    SQLitePaymentStore,
)


def _seed_commerce(repo: SQLiteRepository, *, include_receipts: bool = True) -> None:
    repo.save_seller(
        {
            "seller_id": "seller_1",
            "name": "Durable seller",
            "agent_url": "https://seller.example/agent",
            "source_kind": "a2a",
            "manifest": {"version": 1},
            "wallet_address": "0x" + ("1" * 40),
            "network": "ARC-TESTNET",
            "created_at": "2026-07-31T00:00:00+00:00",
        },
        owner_id="owner_1",
    )
    capability = CapabilityDescriptor(
        capability_id="capability_1",
        name="Durable capability",
        description="Return a durable result",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        tags=("durable",),
    )
    repo.save_capability("seller_1", capability)
    sku = ServiceSKU(
        sku_id="sku_1",
        capability_id=capability.capability_id,
        name="Durable SKU",
        outcome=capability.description,
        base_price_usdc=Decimal("1"),
        input_schema=capability.input_schema,
        output_schema=capability.output_schema,
        acceptance_criteria=("non_empty_artifact",),
        maximum_latency_seconds=60,
        capacity_per_hour=5,
    )
    repo.save_sku("seller_1", sku)
    repo.save_policy(
        "seller_1",
        CommercialPolicy(
            policy_id="policy_1",
            owner_id="seller_1",
            minimum_price_usdc=Decimal("0.5"),
            maximum_price_usdc=Decimal("2"),
            allowed_buyer_hosts=("buyer.example",),
            allowed_chains=("ARC-TESTNET",),
        ),
    )
    repo.save_prospect(
        ProspectRecord(
            need=BuyerNeed(
                need_id="need_1",
                buyer_agent_url="https://buyer.example/agent",
                desired_outcome="Return a durable result",
                maximum_price_usdc=Decimal("2"),
                required_tags=("durable",),
                input_payload={"claim": "persist me"},
            ),
            opted_in=True,
            owner_id="owner_1",
            consent_reference="consent:durable:v1",
        )
    )
    proposal = Proposal(
        proposal_id="proposal_1",
        seller_agent_url="https://seller.example/agent",
        buyer_agent_url="https://buyer.example/agent",
        sku_id=sku.sku_id,
        problem_observed="State must survive restart",
        offered_outcome=sku.outcome,
        price_usdc=Decimal("1"),
        delivery_seconds=60,
        buyer_need_id="need_1",
        acceptance_criteria=sku.acceptance_criteria,
        state=ProposalState.ACCEPTED,
    )
    repo.save_proposal(
        proposal,
        owner_id="owner_1",
        contract_hash="sha256:contract",
    )
    repo.accept_proposal(
        proposal,
        SettlementAuthorization(
            authorization_id="settlement_1",
            proposal_id=proposal.proposal_id,
            proposal_revision=proposal.revision,
            proposal_contract_hash="sha256:contract",
            amount_usdc=proposal.price_usdc,
            payer_wallet="0x" + ("2" * 40),
            payee_wallet="0x" + ("1" * 40),
            chain="ARC-TESTNET",
            token="USDC",
            asset="0x3600000000000000000000000000000000000000",
            commercial_policy_id="policy_1",
            commercial_policy_version="sha256:policy",
            seller_configuration_id="seller_1",
            seller_configuration_version="sha256:seller",
            expires_at="2030-01-01T00:00:00Z",
            created_at="2026-07-31T00:00:00Z",
        ),
        owner_id="owner_1",
        contract_hash="sha256:contract",
    )
    repo.mark_accepted(proposal.proposal_id)
    repo.record_negotiation(Decimal("-0.25"))
    repo.note_policy_denial()
    repo.note_duplicate_payment()

    if not include_receipts:
        return

    payment = PaymentReceipt(
        payment_id="payment_1",
        proposal_id=proposal.proposal_id,
        idempotency_key="idempotency_1",
        state=PaymentState.CONFIRMED,
        amount_usdc=proposal.price_usdc,
        chain="ARC-TESTNET",
        token="USDC",
        asset="0x3600000000000000000000000000000000000000",
        payer_wallet="0x" + ("2" * 40),
        payee_wallet="0x" + ("1" * 40),
        transaction_hash="0x" + ("a" * 64),
        confirmed_at="2026-07-31T00:00:00+00:00",
    )
    repo.save_payment(payment, mocked=True)
    fulfillment = FulfillmentReceipt(
        fulfillment_id="fulfillment_1",
        proposal_id=proposal.proposal_id,
        payment_id=payment.payment_id,
        seller_agent_url=proposal.seller_agent_url,
        artifact_hash="sha256:artifact",
        accepted=True,
        validator="contract-validator",
        acceptance_results={"non_empty_artifact": True},
        delivered_at="2026-07-31T00:00:01+00:00",
        detail={"artifactMetadata": {"sizeBytes": 10}},
    )
    repo.save_fulfillment(fulfillment)
    repo.save_receipt_publication(
        ReceiptPublication(
            receipt_id="receipt_1",
            proposal_id=proposal.proposal_id,
            owner_id="owner_1",
            approved_by="owner_1",
            consent_reference="publication:durable:v1",
            fields=("payment", "fulfillment", "acceptanceVerdict"),
            published_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def test_all_commerce_state_survives_repository_restart(tmp_path: Path):
    path = tmp_path / "commerce.sqlite3"
    first = SQLiteRepository(path)
    _seed_commerce(first)
    first.close()

    reopened = SQLiteRepository(path)
    assert reopened.durability is RepositoryDurability.SINGLE_NODE
    assert reopened.is_durable is True
    assert reopened.owner_for_seller("seller_1") == "owner_1"
    assert reopened.get_capability("capability_1") is not None
    assert reopened.get_sku("sku_1") is not None
    assert reopened.get_policy("seller_1") is not None
    assert reopened.owner_for_prospect("need_1") == "owner_1"
    assert reopened.owner_for_proposal("proposal_1") == "owner_1"
    assert (
        reopened.contract_hash_for_proposal("proposal_1")
        == "sha256:contract"
    )
    settlement = reopened.get_settlement_authorization("proposal_1")
    assert settlement is not None
    assert settlement.payee_wallet == "0x" + ("1" * 40)
    assert settlement.proposal_contract_hash == "sha256:contract"
    assert reopened.get_proposal("proposal_1").state is ProposalState.DELIVERED
    assert (
        reopened.payment_for_idempotency("idempotency_1").payment_id
        == "payment_1"
    )
    assert reopened.payment_for_proposal("proposal_1").payment_id == "payment_1"
    assert reopened.is_mocked_payment("payment_1") is True
    assert (
        reopened.fulfillment_for_proposal("proposal_1").fulfillment_id
        == "fulfillment_1"
    )
    publication = reopened.get_receipt_publication("proposal_1")
    assert publication is not None
    assert publication.receipt_id == "receipt_1"
    assert publication.owner_id == "owner_1"
    metrics = reopened.metrics(owner_id="owner_1")
    assert metrics["registeredSellerAgents"] == 1
    assert metrics["activatedSellerAgents"] == 1
    assert metrics["proposalsSent"] == 1
    assert metrics["proposalAcceptanceRate"] == "1"
    assert metrics["mockedPaymentCount"] == 1
    assert metrics["successfulFulfillment"] == 1
    assert metrics["policyDenials"] == 1
    assert metrics["duplicatePaymentCount"] == 1
    reopened.close()


def test_payment_and_proposal_projection_commit_atomically(tmp_path: Path):
    path = tmp_path / "commerce.sqlite3"
    repo = SQLiteRepository(path)
    _seed_commerce(repo, include_receipts=False)
    payment = PaymentReceipt(
        payment_id="payment_crash",
        proposal_id="proposal_1",
        idempotency_key="idempotency_crash",
        state=PaymentState.CONFIRMED,
        amount_usdc=Decimal("1"),
        chain="ARC-TESTNET",
        token="USDC",
        asset="0x3600000000000000000000000000000000000000",
        payer_wallet="0x" + ("2" * 40),
        payee_wallet="0x" + ("1" * 40),
        transaction_hash="0x" + ("b" * 64),
        confirmed_at="2026-07-31T00:00:00+00:00",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER simulate_projection_crash
            BEFORE UPDATE ON commerce_proposals
            BEGIN
                SELECT RAISE(ABORT, 'simulated crash');
            END
            """
        )
    with pytest.raises(ValueError):
        repo.save_payment(payment, mocked=False)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER simulate_projection_crash")
    repo.close()

    reopened = SQLiteRepository(path)
    assert reopened.get_payment("payment_crash") is None
    assert reopened.payment_for_idempotency("idempotency_crash") is None
    assert reopened.get_proposal("proposal_1").state is ProposalState.ACCEPTED
    reopened.close()


def test_shared_store_crash_recovery_preserves_asset_authorization(
    tmp_path: Path,
):
    path = tmp_path / "shared.sqlite3"
    repo = SQLiteRepository(path)
    _seed_commerce(repo, include_receipts=False)
    authorization = repo.get_settlement_authorization("proposal_1")
    assert authorization is not None
    repo.close()

    intent = PaymentIntent(
        proposal_id="proposal_1",
        idempotency_key="crash-window-payment",
        amount_usdc=Decimal("1"),
        expected_amount_usdc=Decimal("1"),
        proposal_state=ProposalState.ACCEPTED,
        chain=authorization.chain,
        token=authorization.token,
        asset=authorization.asset,
        payer_wallet=authorization.payer_wallet,
        payee_wallet=authorization.payee_wallet,
    )
    policy = PaymentPolicy(
        policy_id="policy_1",
        mode=PaymentMode.TESTNET,
        maximum_per_payment_usdc=Decimal("1"),
        maximum_total_usdc=Decimal("2"),
        allowed_chains=(authorization.chain,),
        allowed_token=authorization.token,
        allowed_payer_wallets=(authorization.payer_wallet,),
        allowed_payee_wallets=(authorization.payee_wallet,),
        allowed_assets_by_chain={
            authorization.chain: (authorization.asset,)
        },
    )
    payment_store = SQLitePaymentStore(path)
    payment_store.reserve(intent, policy)
    payment_store.transition(
        intent.idempotency_key, PaymentState.POLICY_APPROVED
    )
    payment_store.transition(intent.idempotency_key, PaymentState.SUBMITTING)
    payment_store.transition(
        intent.idempotency_key,
        PaymentState.CONFIRMED,
        transaction_hash="0x" + ("c" * 64),
        confirmed_at="2026-07-31T12:00:00Z",
    )

    reopened = SQLiteRepository(path)
    recovered = reopened.payment_for_proposal("proposal_1")
    assert recovered is not None
    assert recovered.token == authorization.token
    assert recovered.asset == authorization.asset
    assert recovered.amount_usdc == authorization.amount_usdc
    assert recovered.payer_wallet == authorization.payer_wallet
    assert recovered.payee_wallet == authorization.payee_wallet
    assert reopened.get_proposal("proposal_1").state is ProposalState.PAID
    reopened.close()


def test_in_memory_repository_matches_payment_and_fulfillment_invariants():
    repo = InMemoryRepository()
    _seed_commerce(repo, include_receipts=False)
    authorization = repo.get_settlement_authorization("proposal_1")
    assert authorization is not None
    payment = PaymentReceipt(
        payment_id="payment_memory_1",
        proposal_id="proposal_1",
        idempotency_key="memory-payment-1",
        state=PaymentState.CONFIRMED,
        amount_usdc=authorization.amount_usdc,
        chain=authorization.chain,
        token=authorization.token,
        asset=authorization.asset,
        payer_wallet=authorization.payer_wallet,
        payee_wallet=authorization.payee_wallet,
        transaction_hash="0x" + ("d" * 64),
        confirmed_at="2026-07-31T12:00:00Z",
    )
    repo.save_payment(payment, mocked=False)

    second_proposal = replace(
        repo.get_proposal("proposal_1"),
        proposal_id="proposal_2",
        state=ProposalState.ACCEPTED,
    )
    repo.save_proposal(
        second_proposal,
        owner_id="owner_1",
        contract_hash="sha256:contract-2",
    )
    repo.accept_proposal(
        second_proposal,
        replace(
            authorization,
            authorization_id="settlement_2",
            proposal_id="proposal_2",
            proposal_contract_hash="sha256:contract-2",
        ),
        owner_id="owner_1",
        contract_hash="sha256:contract-2",
    )
    with pytest.raises(
        ValueError, match="transaction hash already has a different payment"
    ):
        repo.save_payment(
            replace(
                payment,
                payment_id="payment_memory_2",
                proposal_id="proposal_2",
                idempotency_key="memory-payment-2",
            ),
            mocked=False,
        )

    with pytest.raises(
        ValueError,
        match="fulfillment payment is missing or belongs to another proposal",
    ):
        repo.save_fulfillment(
            FulfillmentReceipt(
                fulfillment_id="fulfillment_missing_payment",
                proposal_id="proposal_2",
                payment_id="payment_missing",
                seller_agent_url=second_proposal.seller_agent_url,
                artifact_hash="sha256:missing",
                accepted=True,
                validator="contract-validator",
            )
        )


def test_monotonic_proposal_enforces_transition_graph_and_revision_semantics():
    accepted = Proposal(
        proposal_id="proposal_transition",
        seller_agent_url="https://seller.example/agent",
        buyer_agent_url="https://buyer.example/agent",
        buyer_need_id="need_transition",
        sku_id="sku_transition",
        problem_observed="Preserve one accepted contract",
        offered_outcome="Return one result",
        price_usdc=Decimal("1"),
        delivery_seconds=60,
        state=ProposalState.ACCEPTED,
        revision=2,
    )
    paid = replace(
        accepted,
        state=ProposalState.PAID,
        revision=3,
    )
    assert monotonic_proposal(accepted, paid) == paid

    with pytest.raises(ValueError, match="state transition is not allowed"):
        monotonic_proposal(
            accepted,
            replace(accepted, state=ProposalState.DECLINED),
        )

    stale_offer = replace(
        accepted,
        state=ProposalState.OFFERED,
        revision=1,
        price_usdc=Decimal("1.20"),
    )
    assert monotonic_proposal(accepted, stale_offer) == accepted


def test_factory_uses_configured_sqlite_path_and_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "factory.sqlite3"
    monkeypatch.setenv("AUTONOMERCE_COMMERCE_SQLITE_PATH", str(path))
    for name in (
        "AUTONOMERCE_API_WORKERS",
        "UVICORN_WORKERS",
        "WEB_CONCURRENCY",
        "GUNICORN_WORKERS",
        "GUNICORN_CMD_ARGS",
        "UVICORN_CMD_ARGS",
    ):
        monkeypatch.delenv(name, raising=False)

    with TestClient(
        create_app(adapters=AdapterBundle(), payment_mode="offline")
    ) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["storage"] == "sqlite"
        assert health.json()["storageDurability"] == "single-node"
        client.app.state.repository.save_seller(
            {
                "seller_id": "seller_factory",
                "name": "Factory seller",
                "agent_url": "https://factory.example/agent",
            },
            owner_id="owner_factory",
        )

    with TestClient(
        create_app(adapters=AdapterBundle(), payment_mode="offline")
    ) as client:
        assert (
            client.app.state.repository.owner_for_seller("seller_factory")
            == "owner_factory"
        )


def test_sqlite_repository_rejects_multi_worker_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="single-worker"):
        SQLiteRepository(tmp_path / "commerce.sqlite3")
