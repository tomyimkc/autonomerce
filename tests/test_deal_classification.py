from __future__ import annotations

from dataclasses import replace
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
from autonomerce.api.deal_classification import (  # noqa: E402
    CustomerRelationship,
    DealEvidence,
    FundingSource,
    SettlementClass,
    VariableCosts,
    aggregate_deal_metrics,
    classify_deal,
)
from autonomerce.api.repository import (  # noqa: E402
    InMemoryRepository,
    ProspectRecord,
    SettlementAuthorization,
)
from autonomerce.api.sqlite_repository import SQLiteRepository  # noqa: E402
from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
)


PAYER = "0x" + ("2" * 40)
PAYEE = "0x" + ("1" * 40)
ASSET = "0x3600000000000000000000000000000000000000"
CUSTOMER_ID = "customer_" + ("a" * 24)
USER_ID = "user_" + ("b" * 24)
CONSENT_REFERENCE = "consent_" + ("c" * 24)
EVIDENCE_REFERENCE = "evidence_" + ("d" * 24)
VERIFIER_REFERENCE = "verification_" + ("e" * 24)


def _proposal(
    *,
    proposal_id: str = "proposal_deal",
    state: ProposalState = ProposalState.ACCEPTED,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id,
        seller_agent_url="https://seller.example/agent",
        buyer_agent_url="https://buyer.example/agent",
        buyer_need_id="need_deal",
        sku_id="sku_deal",
        problem_observed="Verify one bounded launch claim",
        offered_outcome="Return one source-verification evidence pack",
        price_usdc=Decimal("10"),
        delivery_seconds=60,
        acceptance_criteria=("non_empty_artifact",),
        state=state,
    )


def _payment(
    *,
    proposal_id: str = "proposal_deal",
    chain: str = "BASE",
    amount: str = "10",
) -> PaymentReceipt:
    return PaymentReceipt(
        payment_id=f"payment_{proposal_id}",
        proposal_id=proposal_id,
        idempotency_key=f"idempotency_{proposal_id}",
        state=PaymentState.CONFIRMED,
        amount_usdc=Decimal(amount),
        chain=chain,
        token="USDC",
        asset=ASSET,
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        transaction_hash="0x" + ("a" * 64),
        confirmed_at="2026-08-01T00:00:00Z",
    )


def _fulfillment(
    *,
    proposal_id: str = "proposal_deal",
    accepted: bool = True,
) -> FulfillmentReceipt:
    return FulfillmentReceipt(
        fulfillment_id=f"fulfillment_{proposal_id}",
        proposal_id=proposal_id,
        payment_id=f"payment_{proposal_id}",
        seller_agent_url="https://seller.example/agent",
        artifact_hash="sha256:artifact",
        accepted=accepted,
        validator="source-verification-validator",
        delivered_at="2026-08-01T00:00:01Z",
    )


def _evidence(
    *,
    proposal_id: str = "proposal_deal",
    relationship: CustomerRelationship = CustomerRelationship.ARMS_LENGTH,
    funding: FundingSource = FundingSource.CUSTOMER_FUNDED,
    refunds: str = "2",
    costs: VariableCosts | None = None,
) -> DealEvidence:
    return DealEvidence(
        evidence_id=f"dealevidence_{proposal_id}",
        proposal_id=proposal_id,
        owner_id="owner_deal",
        customer_relationship=relationship,
        funding_source=funding,
        customer_id=CUSTOMER_ID,
        user_id=USER_ID,
        consent_reference=CONSENT_REFERENCE,
        evidence_reference=EVIDENCE_REFERENCE,
        relationship_verified=True,
        verifier_reference=VERIFIER_REFERENCE,
        refunds_usdc=Decimal(refunds),
        variable_costs=costs
        or VariableCosts(
            network_fees_usdc=Decimal("1"),
            infrastructure_usdc=Decimal("0.5"),
            fulfillment_usdc=Decimal("1"),
            other_usdc=Decimal("0.5"),
        ),
        refund_window_closed=True,
        refund_window_closed_at="2026-08-01T00:00:01Z",
        costs_measured=True,
        measured_at="2026-08-01T00:00:02Z",
        recorded_at="2026-08-01T00:00:02Z",
    )


def _seed_repository(repo: InMemoryRepository | SQLiteRepository) -> Proposal:
    repo.save_seller(
        {
            "seller_id": "seller_deal",
            "name": "Deal seller",
            "agent_url": "https://seller.example/agent",
            "wallet_address": PAYEE,
            "network": "ARC-TESTNET",
        },
        owner_id="owner_deal",
    )
    capability = CapabilityDescriptor(
        capability_id="capability_deal",
        name="Evidence pack",
        description="Return one bounded evidence pack",
        output_schema={"type": "object"},
    )
    repo.save_capability("seller_deal", capability)
    repo.save_sku(
        "seller_deal",
        ServiceSKU(
            sku_id="sku_deal",
            capability_id=capability.capability_id,
            name="Evidence pack",
            outcome="Return one source-verification evidence pack",
            base_price_usdc=Decimal("10"),
            output_schema=capability.output_schema,
            acceptance_criteria=("non_empty_artifact",),
            maximum_latency_seconds=60,
        ),
    )
    repo.save_prospect(
        ProspectRecord(
            need=BuyerNeed(
                need_id="need_deal",
                buyer_agent_url="https://buyer.example/agent",
                desired_outcome="Return one source-verification evidence pack",
                maximum_price_usdc=Decimal("10"),
            ),
            opted_in=True,
            owner_id="owner_deal",
            consent_reference=CONSENT_REFERENCE,
        )
    )
    proposal = _proposal()
    repo.save_proposal(
        proposal,
        owner_id="owner_deal",
        contract_hash="sha256:deal-contract",
    )
    repo.accept_proposal(
        proposal,
        SettlementAuthorization(
            authorization_id="settlement_deal",
            proposal_id=proposal.proposal_id,
            proposal_revision=proposal.revision,
            proposal_contract_hash="sha256:deal-contract",
            amount_usdc=proposal.price_usdc,
            payer_wallet=PAYER,
            payee_wallet=PAYEE,
            chain="BASE",
            token="USDC",
            asset=ASSET,
            commercial_policy_id="policy_deal",
            commercial_policy_version="sha256:policy",
            seller_configuration_id="seller_deal",
            seller_configuration_version="sha256:seller",
            expires_at="2026-08-17T20:00:00Z",
            created_at="2026-08-01T00:00:00Z",
        ),
        owner_id="owner_deal",
        contract_hash="sha256:deal-contract",
    )
    payment = _payment()
    repo.save_payment(payment, mocked=False)
    repo.save_fulfillment(_fulfillment())
    return proposal


def test_external_customer_funded_mainnet_counts_exact_revenue_and_margin():
    classification = classify_deal(
        _evidence(),
        payment=_payment(),
        mocked=False,
        fulfillment=_fulfillment(),
    )

    assert classification.settlement_class is SettlementClass.MAINNET
    assert classification.external_customer is True
    assert classification.counts_as_revenue is True
    assert classification.user_acquired is True
    assert classification.paid_user is True
    assert classification.paid_task is True
    assert classification.gross_external_revenue_usdc == Decimal("10")
    assert classification.refunds_usdc == Decimal("2")
    assert classification.net_external_revenue_usdc == Decimal("8")
    assert classification.variable_costs_usdc == Decimal("3")
    assert classification.gross_margin_usdc == Decimal("5")

    metrics = aggregate_deal_metrics([classification])
    assert metrics["usersAcquired"] == 1
    assert metrics["payingUsers"] == 1
    assert metrics["paidTasks"] == 1
    assert metrics["paidExternalTasks"] == 1
    assert metrics["acceptedPaidExternalTasks"] == 1
    assert metrics["grossExternalRevenueUsdc"] == "10"
    assert metrics["refundsUsdc"] == "2"
    assert metrics["netExternalRevenueUsdc"] == "8"
    assert metrics["grossMarginUsdc"] == "5"
    assert metrics["grossMarginPercent"] == "62.5"


def test_founder_sponsored_testnet_is_user_proof_not_revenue_or_paid_user():
    classification = classify_deal(
        _evidence(
            funding=FundingSource.FOUNDER_SPONSORED,
            refunds="0",
            costs=VariableCosts(
                network_fees_usdc=Decimal("0"),
                infrastructure_usdc=Decimal("0"),
                fulfillment_usdc=Decimal("0"),
                other_usdc=Decimal("0"),
            ),
        ),
        payment=_payment(chain="ARC-TESTNET"),
        mocked=False,
        fulfillment=_fulfillment(),
    )

    assert classification.settlement_class is SettlementClass.TESTNET
    assert classification.external_customer is True
    assert classification.user_acquired is True
    assert classification.accepted_fulfillment is True
    assert classification.counts_as_revenue is False
    assert classification.paid_user is False
    assert classification.paid_task is True
    assert classification.paid_external_task is False
    assert classification.accepted_paid_external_task is False
    assert classification.net_external_revenue_usdc == Decimal("0")


@pytest.mark.parametrize("chain", ["GOERLI", "LOCAL", "ANVIL"])
def test_unknown_or_local_networks_fail_closed_as_unsupported(chain: str):
    classification = classify_deal(
        _evidence(refunds="0"),
        payment=_payment(chain=chain),
        mocked=False,
        fulfillment=_fulfillment(),
    )
    assert classification.settlement_class is SettlementClass.UNSUPPORTED
    assert classification.counts_as_revenue is False


def test_repeat_purchase_rate_counts_repeat_customers_and_zero_is_unknown():
    classifications = []
    for proposal_id, customer_id in (
        ("proposal_repeat_1", "customer_" + ("1" * 24)),
        ("proposal_repeat_2", "customer_" + ("1" * 24)),
        ("proposal_repeat_3", "customer_" + ("2" * 24)),
    ):
        evidence = replace(
            _evidence(proposal_id=proposal_id, refunds="0"),
            customer_id=customer_id,
            user_id=(
                "user_" + ("3" * 24)
                if customer_id.endswith("1" * 24)
                else "user_" + ("4" * 24)
            ),
        )
        classifications.append(
            classify_deal(
                evidence,
                payment=_payment(proposal_id=proposal_id),
                mocked=False,
                fulfillment=_fulfillment(proposal_id=proposal_id),
            )
        )
    assert (
        aggregate_deal_metrics(classifications)["repeatPurchaseRate"]
        == "0.5"
    )

    testnet_only = classify_deal(
        _evidence(
            proposal_id="proposal_testnet_only",
            funding=FundingSource.FOUNDER_SPONSORED,
            refunds="0",
        ),
        payment=_payment(
            proposal_id="proposal_testnet_only",
            chain="BASE-SEPOLIA",
        ),
        mocked=False,
        fulfillment=_fulfillment(proposal_id="proposal_testnet_only"),
    )
    assert aggregate_deal_metrics([testnet_only])["repeatPurchaseRate"] is None


def test_gross_margin_excludes_nonrevenue_pilot_spend():
    revenue = classify_deal(
        _evidence(refunds="2"),
        payment=_payment(),
        mocked=False,
        fulfillment=_fulfillment(),
    )
    pilot = classify_deal(
        _evidence(
            proposal_id="proposal_pilot_cost",
            funding=FundingSource.FOUNDER_SPONSORED,
            refunds="0",
            costs=VariableCosts(
                network_fees_usdc=Decimal("100"),
                infrastructure_usdc=Decimal("0"),
                fulfillment_usdc=Decimal("0"),
                other_usdc=Decimal("0"),
            ),
        ),
        payment=_payment(
            proposal_id="proposal_pilot_cost",
            chain="ARC-TESTNET",
        ),
        mocked=False,
        fulfillment=_fulfillment(proposal_id="proposal_pilot_cost"),
    )
    metrics = aggregate_deal_metrics([revenue, pilot])
    assert metrics["variableCostsUsdc"] == "3"
    assert metrics["excludedPilotSpendUsdc"] == "100"
    assert metrics["grossMarginUsdc"] == "5"


@pytest.mark.parametrize(
    ("relationship", "funding"),
    [
        (CustomerRelationship.RELATED_PARTY, FundingSource.CUSTOMER_FUNDED),
        (CustomerRelationship.ARMS_LENGTH, FundingSource.REIMBURSED),
        (CustomerRelationship.SELF, FundingSource.FOUNDER_SPONSORED),
    ],
)
def test_related_or_reimbursed_mainnet_settlement_is_excluded(
    relationship: CustomerRelationship,
    funding: FundingSource,
):
    classification = classify_deal(
        _evidence(
            relationship=relationship,
            funding=funding,
            refunds="0",
        ),
        payment=_payment(),
        mocked=False,
        fulfillment=_fulfillment(),
    )
    assert classification.settlement_class is SettlementClass.MAINNET
    assert classification.counts_as_revenue is False
    assert classification.paid_user is False
    assert classification.gross_external_revenue_usdc == Decimal("0")


def test_refunds_are_fail_closed_against_confirmed_payment():
    with pytest.raises(ValueError, match="cannot exceed"):
        classify_deal(
            _evidence(refunds="10.000001"),
            payment=_payment(),
            mocked=False,
            fulfillment=_fulfillment(),
        )
    with pytest.raises(ValueError, match="requires a confirmed payment"):
        classify_deal(
            _evidence(refunds="1"),
            payment=None,
            mocked=False,
            fulfillment=None,
        )


def test_measurement_timing_and_receipt_identity_are_fail_closed():
    with pytest.raises(ValueError, match="financial measurement must follow"):
        classify_deal(
            replace(
                _evidence(refunds="0"),
                measured_at="2020-01-01T00:00:00Z",
            ),
            payment=_payment(),
            mocked=False,
            fulfillment=_fulfillment(),
        )

    with pytest.raises(ValueError, match="identity-bound"):
        classify_deal(
            _evidence(refunds="0"),
            payment=_payment(proposal_id="proposal_other"),
            mocked=False,
            fulfillment=_fulfillment(proposal_id="proposal_third"),
        )


def test_route_derives_status_rejects_caller_claims_and_is_idempotent():
    repository = InMemoryRepository()
    proposal = _seed_repository(repository)
    app = create_app(
        repository=repository,
        adapters=AdapterBundle(),
        bearer_token="owner-token",
        owner_id="owner_deal",
        payment_mode="offline",
        deal_evidence_verifier=lambda **_kwargs: {
            "verified": True,
            "reference": VERIFIER_REFERENCE,
            "refundWindowClosedAt": "2026-08-01T00:00:01Z",
        },
    )
    headers = {"Authorization": "Bearer owner-token"}
    payload = {
        "customerRelationship": "arms_length",
        "fundingSource": "founder_sponsored",
        "customerId": CUSTOMER_ID,
        "userId": USER_ID,
        "consentReference": CONSENT_REFERENCE,
        "evidenceReference": EVIDENCE_REFERENCE,
        "refundsUsdc": "0",
        "refundWindowClosed": True,
        "variableCosts": {
            "networkFeesUsdc": "0.01",
            "infrastructureUsdc": "0.02",
            "fulfillmentUsdc": "0.01",
            "otherUsdc": "0.06",
        },
        "costsMeasured": True,
        "measuredAt": "2026-08-01T00:00:02Z",
    }

    with TestClient(app) as client:
        unauthenticated = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json=payload,
        )
        assert unauthenticated.status_code == 401

        first = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json=payload,
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["settlementClass"] == "mainnet"
        assert first.json()["externalCustomer"] is True
        assert first.json()["countsAsRevenue"] is False
        assert first.json()["userAcquired"] is True
        assert first.json()["evidence"]["relationshipVerified"] is True
        assert first.json()["excludedPilotSpendUsdc"] == "0.1"
        assert first.json()["idempotentReplay"] is False

        replay = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json=payload,
            headers=headers,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["idempotentReplay"] is True

        conflicting = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json={**payload, "fundingSource": "customer_funded"},
            headers=headers,
        )
        assert conflicting.status_code == 409
        assert "append-only" in conflicting.json()["detail"]

        for forbidden in (
            "settlementClass",
            "paymentConfirmed",
            "acceptedFulfillment",
            "countsAsRevenue",
            "paidUser",
            "userAcquired",
        ):
            rejected = client.post(
                f"/proposals/{proposal.proposal_id}/deal-evidence",
                json={**payload, forbidden: True},
                headers=headers,
            )
            assert rejected.status_code == 422

        incomplete = dict(payload)
        incomplete.pop("costsMeasured")
        rejected = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json=incomplete,
            headers=headers,
        )
        assert rejected.status_code == 422

        pii_reference = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json={
                **payload,
                "evidenceReference": "customer@example.com",
            },
            headers=headers,
        )
        assert pii_reference.status_code == 422

        name_like_customer = client.post(
            f"/proposals/{proposal.proposal_id}/deal-evidence",
            json={
                **payload,
                "customerId": "Alice.Smith",
            },
            headers=headers,
        )
        assert name_like_customer.status_code == 422


def test_sqlite_v1_migration_restart_and_append_only_idempotency(
    tmp_path: Path,
):
    path = tmp_path / "commerce.sqlite3"
    initial = SQLiteRepository(path)
    _seed_repository(initial)
    initial.close()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE commerce_deal_evidence")
        connection.execute(
            """
            UPDATE commerce_metadata
            SET value = '1'
            WHERE key = 'schema_version'
            """
        )

    migrated = SQLiteRepository(path)
    evidence = _evidence(refunds="0")
    assert migrated.save_deal_evidence(evidence) == evidence
    assert migrated.save_deal_evidence(
        replace(evidence, recorded_at="2026-08-01T00:00:03Z")
    ) == evidence
    migrated.close()

    reopened = SQLiteRepository(path)
    assert reopened.deal_evidence_for_proposal("proposal_deal") == evidence
    assert reopened.list_deal_evidence(owner_id="owner_deal") == [evidence]
    with pytest.raises(ValueError, match="append-only"):
        reopened.save_deal_evidence(
            replace(evidence, funding_source=FundingSource.REIMBURSED)
        )
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            """
            SELECT value FROM commerce_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()[0]
    assert version == "2"
    reopened.close()
