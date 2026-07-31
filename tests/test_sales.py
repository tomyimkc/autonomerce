from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CommercialPolicy,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
)
from autonomerce.sales import (  # noqa: E402
    AgentCardError,
    AntiSpamPolicy,
    BuyerResponse,
    FixtureSellerFulfillmentAdapter,
    FulfillmentError,
    FulfillmentOrchestrator,
    NegotiationAction,
    NegotiationOrchestrator,
    OptedInProspectRegistry,
    PitchWorkflow,
    ProspectRegistryError,
    SchemaArtifactValidator,
    artifact_hash,
    delivery_receipt_to_public_dict,
    match_need_to_sku,
    parse_agent_card,
)


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def agent_card_payload(url: str = "https://buyer.example/a2a"):
    return {
        "name": "Evidence Buyer",
        "description": "Buys provenance verification services",
        "url": url,
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        "capabilities": {"streaming": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "verify-source",
                "name": "Verify source",
                "description": "Verify evidence and source provenance",
                "tags": ["verification", "provenance"],
            }
        ],
    }


def capability_and_sku():
    card = parse_agent_card(agent_card_payload())
    capability = card.capability_descriptors()[0]
    sku = ServiceSKU(
        sku_id="sku_verify",
        capability_id=capability.capability_id,
        name="Source verification",
        outcome="Return source provenance evidence",
        base_price_usdc=Decimal("2.50"),
        input_schema={
            "type": "object",
            "required": ["claim"],
            "properties": {"claim": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["verdict", "evidence"],
            "properties": {
                "verdict": {"type": "string"},
                "evidence": {"type": "array"},
            },
        },
        acceptance_criteria=("contains verdict",),
        maximum_latency_seconds=60,
    )
    return card, capability, sku


def buyer_need(
    *,
    need_id: str = "need_verify",
    buyer_url: str = "https://buyer.example/a2a",
    maximum_price: str = "3",
):
    return BuyerNeed(
        need_id=need_id,
        buyer_agent_url=buyer_url,
        desired_outcome="Verify claim provenance and return evidence",
        maximum_price_usdc=Decimal(maximum_price),
        required_tags=("verification", "provenance"),
        input_payload={"claim": "A supplied offline fixture"},
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )


def commercial_policy(**overrides):
    values = {
        "policy_id": "policy_sales",
        "owner_id": "seller_owner",
        "minimum_price_usdc": Decimal("2"),
        "maximum_price_usdc": Decimal("10"),
        "maximum_discount_fraction": Decimal("0.20"),
        "maximum_open_proposals": 3,
        "allowed_buyer_hosts": ("buyer.example",),
    }
    values.update(overrides)
    return CommercialPolicy(**values)


def offered_proposal(**overrides):
    values = {
        "proposal_id": "proposal_sales",
        "seller_agent_url": "https://seller.example/a2a",
        "buyer_agent_url": "https://buyer.example/a2a",
        "sku_id": "sku_verify",
        "problem_observed": "Need provenance evidence",
        "offered_outcome": "Return source provenance evidence",
        "price_usdc": Decimal("5"),
        "delivery_seconds": 60,
        "acceptance_criteria": ("contains verdict",),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "state": ProposalState.OFFERED,
    }
    values.update(overrides)
    return Proposal(**values)


def confirmed_payment(proposal_id: str = "proposal_sales"):
    return PaymentReceipt(
        payment_id="payment_sales",
        proposal_id=proposal_id,
        idempotency_key="idem_sales",
        state=PaymentState.CONFIRMED,
        amount_usdc=Decimal("5"),
        chain="ARC-TESTNET",
        payer_wallet="fixture-payer",
        payee_wallet="fixture-seller",
        transaction_hash="0xofflinefixture",
        confirmed_at=NOW.isoformat(),
    )


def test_agent_card_parses_offline_json_and_builds_capabilities():
    card = parse_agent_card(json.dumps(agent_card_payload()))
    assert card.url == "https://buyer.example/a2a"
    assert card.skills[0].skill_id == "verify-source"
    capability = card.capability_descriptors()[0]
    assert capability.capability_id.startswith("cap_")
    assert capability.source_kind == "a2a-agent-card"
    assert set(capability.tags) == {"verification", "provenance"}


def test_agent_card_supports_interface_url_and_rejects_insecure_remote_url():
    payload = agent_card_payload()
    payload.pop("url")
    payload["supportedInterfaces"] = [
        {
            "url": "https://buyer.example/a2a",
            "protocolBinding": "JSONRPC",
        }
    ]
    assert parse_agent_card(payload).url == "https://buyer.example/a2a"

    payload["supportedInterfaces"][0]["url"] = "http://buyer.example/a2a"
    with pytest.raises(AgentCardError):
        parse_agent_card(payload)


def test_agent_card_rejects_duplicate_skill_ids_and_duplicate_json_keys():
    payload = agent_card_payload()
    payload["skills"].append(dict(payload["skills"][0]))
    with pytest.raises(AgentCardError, match="duplicate skill id"):
        parse_agent_card(payload)

    with pytest.raises(AgentCardError, match="duplicate JSON key"):
        parse_agent_card(
            '{"name":"one","name":"two","description":"d","url":'
            '"https://buyer.example","version":"1","skills":[]}'
        )


def test_registry_requires_explicit_opt_in_and_honors_revocation():
    card = parse_agent_card(agent_card_payload())
    registry = OptedInProspectRegistry()
    with pytest.raises(ProspectRegistryError, match="explicit opt-in"):
        registry.register(
            card,
            opted_in=False,
            consent_reference="consent-1",
        )

    record = registry.register(
        card,
        opted_in=True,
        consent_reference="consent-1",
        allowed_topics=("provenance",),
        opted_in_at=NOW,
    )
    assert record.is_active(NOW)
    assert record.permits_topics(("provenance",))
    assert not record.permits_topics(("translation",))

    revoked = registry.revoke(record.prospect_id, revoked_at=NOW + timedelta(seconds=1))
    assert not revoked.is_active(NOW + timedelta(seconds=2))


def test_need_matching_fails_closed_on_tags_price_and_required_input():
    _, capability, sku = capability_and_sku()
    good = match_need_to_sku(buyer_need(), sku, capability)
    assert good.eligible
    assert good.score > 0

    expensive = match_need_to_sku(
        buyer_need(maximum_price="1"),
        sku,
        capability,
    )
    assert not expensive.eligible
    assert "price_exceeds_buyer_limit" in expensive.reason_codes

    missing_input = replace(buyer_need(), input_payload={})
    result = match_need_to_sku(missing_input, sku, capability)
    assert not result.eligible
    assert "missing_required_inputs" in result.reason_codes


def test_pitch_workflow_requires_registry_opt_in():
    _, capability, sku = capability_and_sku()
    need = buyer_need()
    match = match_need_to_sku(need, sku, capability)
    workflow = PitchWorkflow(
        seller_agent_url="https://seller.example/a2a",
        commercial_policy=commercial_policy(),
        registry=OptedInProspectRegistry(),
    )
    result = workflow.pitch(need=need, sku=sku, match=match, now=NOW)
    assert not result.sent
    assert result.reason_code == "prospect_not_opted_in"


def test_pitch_workflow_creates_offer_and_suppresses_duplicate():
    card, capability, sku = capability_and_sku()
    need = buyer_need()
    registry = OptedInProspectRegistry()
    registry.register(
        card,
        opted_in=True,
        consent_reference="consent-sales",
        allowed_topics=("verification", "provenance"),
        opted_in_at=NOW,
    )

    workflow = PitchWorkflow(
        seller_agent_url="https://seller.example/a2a",
        commercial_policy=commercial_policy(),
        registry=registry,
        anti_spam=AntiSpamPolicy(cooldown_seconds=1),
    )
    match = match_need_to_sku(need, sku, capability)
    first = workflow.pitch(need=need, sku=sku, match=match, now=NOW)
    assert first.sent
    assert first.proposal is not None
    assert first.proposal.state == ProposalState.OFFERED
    assert first.proposal.problem_observed == need.desired_outcome
    assert "claim" not in first.proposal.to_dict()

    duplicate = workflow.pitch(
        need=need,
        sku=sku,
        match=match,
        now=NOW + timedelta(seconds=2),
    )
    assert not duplicate.sent
    assert duplicate.reason_code == "duplicate_pitch_suppressed"


def test_pitch_workflow_enforces_per_prospect_cooldown_across_needs():
    card, capability, sku = capability_and_sku()
    registry = OptedInProspectRegistry()
    registry.register(
        card,
        opted_in=True,
        consent_reference="consent-sales",
        opted_in_at=NOW,
    )

    workflow = PitchWorkflow(
        seller_agent_url="https://seller.example/a2a",
        commercial_policy=commercial_policy(),
        registry=registry,
        anti_spam=AntiSpamPolicy(cooldown_seconds=300),
    )
    first_need = buyer_need(need_id="need_one")
    second_need = buyer_need(need_id="need_two")
    assert workflow.pitch(
        need=first_need,
        sku=sku,
        match=match_need_to_sku(first_need, sku, capability),
        now=NOW,
    ).sent
    blocked = workflow.pitch(
        need=second_need,
        sku=sku,
        match=match_need_to_sku(second_need, sku, capability),
        now=NOW + timedelta(seconds=30),
    )
    assert not blocked.sent
    assert blocked.reason_code == "prospect_cooldown"
    assert blocked.retry_after_seconds == 270


def test_negotiation_accepts_only_bounded_discount():
    orchestrator = NegotiationOrchestrator(
        commercial_policy=commercial_policy(),
        max_rounds=2,
    )
    session = orchestrator.start(offered_proposal())
    accepted = orchestrator.advance(
        session,
        BuyerResponse(NegotiationAction.COUNTER, Decimal("4.25")),
        now=NOW,
    )
    assert accepted.accepted
    assert accepted.reason_code == "accepted_bounded_counter"
    assert accepted.proposal.price_usdc == Decimal("4.25")
    assert accepted.proposal.state == ProposalState.ACCEPTED


def test_negotiation_counters_at_floor_then_stops_at_round_limit():
    orchestrator = NegotiationOrchestrator(
        commercial_policy=commercial_policy(),
        max_rounds=1,
    )
    session = orchestrator.start(offered_proposal())
    counter = orchestrator.advance(
        session,
        BuyerResponse(NegotiationAction.COUNTER, Decimal("1")),
        now=NOW,
    )
    assert not counter.accepted
    assert counter.reason_code == "seller_countered"
    assert counter.proposal.price_usdc == Decimal("4")
    assert counter.proposal.state == ProposalState.COUNTERED

    declined = orchestrator.advance(
        session,
        BuyerResponse(NegotiationAction.COUNTER, Decimal("1")),
        now=NOW,
    )
    assert not declined.accepted
    assert declined.reason_code == "negotiation_round_limit"
    assert declined.proposal.state == ProposalState.DECLINED


def test_artifact_hash_is_canonical_for_mapping_order():
    first = artifact_hash({"verdict": "pass", "evidence": ["a", "b"]})
    second = artifact_hash({"evidence": ["a", "b"], "verdict": "pass"})
    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_fulfillment_requires_confirmed_matching_payment():
    proposal = replace(offered_proposal(), state=ProposalState.ACCEPTED)
    payment = replace(
        confirmed_payment(),
        state=PaymentState.POLICY_APPROVED,
        transaction_hash=None,
    )
    orchestrator = FulfillmentOrchestrator(
        adapter=FixtureSellerFulfillmentAdapter(
            {"sku_verify": {"verdict": "pass", "evidence": []}}
        ),
        validator=SchemaArtifactValidator({"type": "object"}),
    )
    with pytest.raises(FulfillmentError, match="confirmed payment"):
        orchestrator.fulfill(
            proposal=proposal,
            payment=payment,
            input_payload={"claim": "offline"},
            now=NOW,
        )


def test_fulfillment_hashes_validates_and_generates_safe_receipt():
    proposal = replace(offered_proposal(), state=ProposalState.ACCEPTED)
    adapter = FixtureSellerFulfillmentAdapter(
        {
            "sku_verify": {
                "verdict": "supported",
                "evidence": ["fixture://source-1"],
                "authorization": "must-not-enter-receipt",
            }
        }
    )
    validator = SchemaArtifactValidator(
        {
            "type": "object",
            "required": ["verdict", "evidence"],
            "properties": {
                "verdict": {"type": "string"},
                "evidence": {"type": "array"},
            },
        },
        criterion_checks={
            "contains verdict": lambda artifact: bool(artifact.get("verdict"))
        },
    )
    result = FulfillmentOrchestrator(
        adapter=adapter,
        validator=validator,
        validator_name="offline-contract-v1",
    ).fulfill(
        proposal=proposal,
        payment=confirmed_payment(),
        input_payload={"claim": "private buyer prompt"},
        now=NOW,
    )

    assert len(adapter.calls) == 1
    assert result.receipt.accepted
    assert result.receipt.fulfillment_id.startswith("fulfillment_")
    assert result.receipt.artifact_hash == artifact_hash(result.artifact)
    assert result.receipt.detail == {"reasonCode": "accepted"}

    public = delivery_receipt_to_public_dict(result.receipt)
    encoded = json.dumps(public)
    assert "private buyer prompt" not in encoded
    assert "must-not-enter-receipt" not in encoded
    assert "authorization" not in encoded


def test_unknown_acceptance_criterion_fails_closed():
    proposal = replace(
        offered_proposal(),
        state=ProposalState.ACCEPTED,
        acceptance_criteria=("unconfigured factual assertion",),
    )
    result = FulfillmentOrchestrator(
        adapter=FixtureSellerFulfillmentAdapter(
            {"sku_verify": {"verdict": "supported", "evidence": []}}
        ),
        validator=SchemaArtifactValidator({"type": "object"}),
    ).fulfill(
        proposal=proposal,
        payment=confirmed_payment(),
        input_payload={},
        now=NOW,
    )
    assert not result.receipt.accepted
    assert result.receipt.acceptance_results == {
        "$schema.type": True,
        "unconfigured factual assertion": False,
    }
