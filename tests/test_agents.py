from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.agents import (  # noqa: E402
    AgentDecisionError,
    CapabilityProductizer,
    CounterOffer,
    DecisionRequest,
    DeliveryValidator,
    GeminiDecisionProvider,
    NegotiationAction,
    NegotiationRecommender,
    OfflineDecisionProvider,
    ProposalWriter,
    ProspectFitScorer,
    ProviderResponseError,
    ProviderUnavailableError,
)
from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
)


class StaticProvider:
    provider_name = "test"
    model_name = "static-json-v1"

    def __init__(self, response):
        self.response = response
        self.requests = []

    def generate_json(self, request):
        self.requests.append(request)
        return dict(self.response)


def capability():
    return CapabilityDescriptor(
        capability_id="cap_verify",
        name="Source verification",
        description="Verify a claim and return a cited support or refute verdict.",
        input_schema={
            "type": "object",
            "required": ["claim"],
            "properties": {"claim": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["verdict", "sources"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["support", "refute", "abstain"],
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "additionalProperties": False,
        },
        tags=("verification", "evidence"),
    )


def policy(**overrides):
    values = {
        "policy_id": "policy_seller",
        "owner_id": "owner_seller",
        "minimum_price_usdc": Decimal("0.10"),
        "maximum_price_usdc": Decimal("1.00"),
        "maximum_discount_fraction": Decimal("0.20"),
        "maximum_tasks_per_hour": 8,
        "allowed_buyer_hosts": ("buyer.example",),
        "blocked_buyer_hosts": ("blocked.example",),
    }
    values.update(overrides)
    return CommercialPolicy(**values)


def buyer_need(**overrides):
    values = {
        "need_id": "need_verify",
        "buyer_agent_url": "https://buyer.example/a2a",
        "desired_outcome": (
            "Source verification with a cited support or refute verdict"
        ),
        "maximum_price_usdc": Decimal("1.00"),
        "required_tags": ("verification",),
        "input_payload": {"claim": "A public claim"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    values.update(overrides)
    return BuyerNeed(**values)


def offline_sku():
    return CapabilityProductizer().productize(capability(), policy()).skus[0]


def offered_proposal(
    *,
    price="0.50",
    criteria=("output_schema_valid",),
    state=ProposalState.OFFERED,
):
    return Proposal(
        proposal_id="proposal_open",
        seller_agent_url="https://seller.example/a2a",
        buyer_agent_url="https://buyer.example/a2a",
        sku_id="sku_verify",
        problem_observed="Buyer needs claim verification.",
        offered_outcome="Return a cited verdict.",
        price_usdc=Decimal(price),
        delivery_seconds=300,
        acceptance_criteria=criteria,
        expires_at="2030-01-01T00:00:00Z",
        state=state,
    )


def confirmed_payment(proposal, **overrides):
    values = {
        "payment_id": "payment_confirmed",
        "proposal_id": proposal.proposal_id,
        "idempotency_key": "idem_once",
        "state": PaymentState.CONFIRMED,
        "amount_usdc": proposal.price_usdc,
        "chain": "ARC-TESTNET",
        "payer_wallet": "payer",
        "payee_wallet": "payee",
        "transaction_hash": "0xtesttransaction",
    }
    values.update(overrides)
    return PaymentReceipt(**values)


def test_offline_productizer_is_deterministic_typed_and_policy_bound():
    first = CapabilityProductizer().productize(capability(), policy())
    second = CapabilityProductizer().productize(capability(), policy())

    assert first.to_dict() == second.to_dict()
    assert first.metadata.provider == "offline"
    assert len(first.skus) == 1
    sku = first.skus[0]
    assert sku.sku_id.startswith("sku_")
    assert policy().minimum_price_usdc <= sku.base_price_usdc <= policy().maximum_price_usdc
    assert sku.input_schema == capability().input_schema
    assert sku.output_schema == capability().output_schema
    assert sku.capacity_per_hour <= policy().maximum_tasks_per_hour
    assert "output_schema_valid" in sku.acceptance_criteria
    assert "required_field:verdict" in sku.acceptance_criteria
    json.dumps(first.to_dict())


def test_productizer_ignores_provider_terms_without_widening_declared_contract():
    provider = StaticProvider(
        {
            "skus": [
                {
                    "name": "Premium verifier",
                    "outcome": "Verify one claim.",
                    "basePriceUsdc": "99",
                    "acceptanceCriteria": ["human_reviewed"],
                    "maximumLatencySeconds": 999999,
                    "capacityPerHour": 999,
                }
            ],
            "summary": "Recommended premium terms.",
            "reasonCodes": ["MODEL_RECOMMENDATION"],
        }
    )
    decision = CapabilityProductizer(provider).productize(capability(), policy())
    sku = decision.skus[0]

    assert sku.base_price_usdc == Decimal("0.550000")
    assert sku.maximum_latency_seconds == 300
    assert sku.capacity_per_hour == 8
    # Legacy providers may still supply a scope-preserving display paraphrase,
    # but they cannot control any commercial or validation term.
    assert sku.outcome == "Verify one claim."
    assert sku.input_schema == capability().input_schema
    assert sku.output_schema == capability().output_schema
    assert sku.acceptance_criteria == (
        "non_empty_artifact",
        "output_schema_valid",
        "required_field:verdict",
        "required_field:sources",
    )
    assert "MODEL_CONTRACT_TERMS_IGNORED" in decision.reason_codes
    assert "PRICE_CLAMPED_TO_POLICY" in decision.reason_codes
    assert "LATENCY_CLAMPED" in decision.reason_codes
    assert "CAPACITY_CLAMPED_TO_POLICY" in decision.reason_codes


def test_prospect_fit_requires_explicit_opt_in_and_obeys_host_policy():
    sku = offline_sku()
    scorer = ProspectFitScorer()

    not_opted_in = scorer.score(
        sku, buyer_need(), opted_in=False, capability=capability(), policy=policy()
    )
    assert not not_opted_in.recommended
    assert not_opted_in.score == 0
    assert "NOT_OPTED_IN" in not_opted_in.reason_codes

    blocked = scorer.score(
        sku,
        buyer_need(buyer_agent_url="https://blocked.example/a2a"),
        opted_in=True,
        capability=capability(),
        policy=policy(),
    )
    assert not blocked.recommended
    assert "BUYER_HOST_BLOCKED" in blocked.reason_codes


def test_prospect_fit_and_proposal_writer_emit_machine_readable_offer():
    sku = offline_sku()
    fit = ProspectFitScorer().score(
        sku, buyer_need(), opted_in=True, capability=capability(), policy=policy()
    )
    assert fit.recommended

    writer = ProposalWriter()
    first = writer.write(
        seller_agent_url="https://seller.example/a2a",
        sku=sku,
        need=buyer_need(),
        fit=fit,
        policy=policy(),
    )
    second = writer.write(
        seller_agent_url="https://seller.example/a2a",
        sku=sku,
        need=buyer_need(),
        fit=fit,
        policy=policy(),
    )

    assert first.proposal == second.proposal
    assert first.proposal.proposal_id.startswith("proposal_")
    assert first.proposal.buyer_need_id == buyer_need().need_id
    assert first.proposal.state is ProposalState.OFFERED
    assert first.proposal.price_usdc == sku.base_price_usdc
    assert first.proposal.offered_outcome == sku.outcome
    assert first.proposal.acceptance_criteria == sku.acceptance_criteria
    assert first.to_dict()["proposal"]["price_usdc"] == str(
        sku.base_price_usdc.normalize()
    )
    json.dumps(first.to_dict())


def test_proposal_writer_refuses_denied_fit():
    sku = offline_sku()
    fit = ProspectFitScorer().score(
        sku, buyer_need(), opted_in=False, capability=capability(), policy=policy()
    )
    with pytest.raises(AgentDecisionError, match="denied prospect"):
        ProposalWriter().write(
            seller_agent_url="https://seller.example/a2a",
            sku=sku,
            need=buyer_need(),
            fit=fit,
            policy=policy(),
        )


def test_proposal_writer_rechecks_host_policy_instead_of_trusting_fit_object():
    sku = offline_sku()
    approved_fit = ProspectFitScorer().score(
        sku, buyer_need(), opted_in=True, capability=capability(), policy=policy()
    )
    with pytest.raises(AgentDecisionError, match="blocked"):
        ProposalWriter().write(
            seller_agent_url="https://seller.example/a2a",
            sku=sku,
            need=buyer_need(buyer_agent_url="https://blocked.example/a2a"),
            fit=approved_fit,
            policy=policy(),
        )


def test_negotiation_accepts_safe_terms_and_counters_below_discount_floor():
    proposal = offered_proposal()
    fixed_now = datetime(2029, 1, 1, tzinfo=timezone.utc)

    accepted = NegotiationRecommender().recommend(
        proposal,
        CounterOffer(price_usdc=Decimal("0.45"), delivery_seconds=300),
        policy(),
        list_price_usdc=Decimal("0.50"),
        now=fixed_now,
    )
    assert accepted.action is NegotiationAction.ACCEPT
    assert accepted.decision.accepted
    assert accepted.decision.proposal.state is ProposalState.ACCEPTED
    assert accepted.decision.proposal.price_usdc == Decimal("0.45")

    unsafe_provider = StaticProvider(
        {
            "action": "accept",
            "summary": "Accept the low price.",
            "reasonCodes": ["MODEL_ACCEPT"],
        }
    )
    countered = NegotiationRecommender(unsafe_provider).recommend(
        proposal,
        CounterOffer(price_usdc=Decimal("0.39"), delivery_seconds=200),
        policy(),
        list_price_usdc=Decimal("0.50"),
        minimum_delivery_seconds=300,
        now=fixed_now,
    )
    assert countered.action is NegotiationAction.COUNTER
    assert not countered.decision.accepted
    assert countered.decision.proposal.price_usdc == Decimal("0.400000")
    assert countered.decision.proposal.delivery_seconds == 300
    assert "PROVIDER_ACTION_OVERRIDDEN" in countered.reason_codes


def test_negotiation_declines_unbounded_scope_or_terms():
    proposal = offered_proposal(criteria=("output_schema_valid",))
    decision = NegotiationRecommender().recommend(
        proposal,
        CounterOffer(
            price_usdc=Decimal("0.50"),
            delivery_seconds=300,
            requested_outcome="Also write a legal opinion.",
            acceptance_criteria=("output_schema_valid", "unlimited_rework"),
        ),
        policy(),
        now=datetime(2029, 1, 1, tzinfo=timezone.utc),
    )
    assert decision.action is NegotiationAction.DECLINE
    assert "SCOPE_CHANGE_REQUIRES_NEW_PROPOSAL" in decision.reason_codes
    assert "NEW_UNBOUNDED_TERM" in decision.reason_codes


def test_delivery_validator_accepts_only_confirmed_schema_valid_contract():
    sku = ServiceSKU(
        sku_id="sku_verify",
        capability_id="cap_verify",
        name="Verify",
        outcome="Return a cited verdict.",
        base_price_usdc=Decimal("0.50"),
        output_schema=capability().output_schema,
        acceptance_criteria=(
            "non_empty_artifact",
            "output_schema_valid",
            "required_field:verdict",
        ),
    )
    proposal = offered_proposal(
        criteria=(
            "non_empty_artifact",
            "output_schema_valid",
            "required_field:verdict",
        ),
        state=ProposalState.FULFILLING,
    )
    artifact = {"verdict": "support", "sources": ["https://source.example"]}

    first = DeliveryValidator().validate(
        sku=sku,
        proposal=proposal,
        payment=confirmed_payment(proposal),
        artifact=artifact,
        delivered_at="2029-01-01T00:05:00Z",
    )
    second = DeliveryValidator().validate(
        sku=sku,
        proposal=proposal,
        payment=confirmed_payment(proposal),
        artifact=artifact,
        delivered_at="2029-01-01T00:05:00Z",
    )

    assert first.accepted
    assert first.receipt == second.receipt
    assert first.receipt.fulfillment_id.startswith("fulfillment_")
    assert first.receipt.acceptance_results["output_schema_valid"]
    assert set(first.receipt.detail) == {"summary", "reasonCodes"}
    assert "artifact" not in first.to_dict()["receipt"]["detail"]
    json.dumps(first.to_dict())


def test_delivery_validator_fails_closed_for_invalid_output_or_payment():
    sku = ServiceSKU(
        sku_id="sku_verify",
        capability_id="cap_verify",
        name="Verify",
        outcome="Return a cited verdict.",
        base_price_usdc=Decimal("0.50"),
        output_schema=capability().output_schema,
        acceptance_criteria=("output_schema_valid", "customer_specific_check"),
    )
    proposal = offered_proposal(
        criteria=("output_schema_valid", "customer_specific_check"),
        state=ProposalState.FULFILLING,
    )
    payment = confirmed_payment(
        proposal,
        proposal_id="proposal_other",
        amount_usdc=Decimal("0.40"),
    )
    decision = DeliveryValidator().validate(
        sku=sku,
        proposal=proposal,
        payment=payment,
        artifact={"verdict": "unsupported"},
    )

    assert not decision.accepted
    assert "PAYMENT_PROPOSAL_MISMATCH" in decision.reason_codes
    assert "PAYMENT_AMOUNT_MISMATCH" in decision.reason_codes
    assert "OUTPUT_SCHEMA_INVALID" in decision.reason_codes
    assert "ACCEPTANCE_CRITERIA_FAILED" in decision.reason_codes
    assert decision.receipt.acceptance_results["customer_specific_check"] is False


def test_external_criterion_must_be_explicitly_validated_not_model_approved():
    sku = ServiceSKU(
        sku_id="sku_verify",
        capability_id="cap_verify",
        name="Verify",
        outcome="Return a verdict.",
        base_price_usdc=Decimal("0.50"),
        output_schema={"type": "object"},
        acceptance_criteria=("customer_specific_check",),
    )
    proposal = offered_proposal(
        criteria=("customer_specific_check",),
        state=ProposalState.FULFILLING,
    )
    payment = confirmed_payment(proposal)

    denied = DeliveryValidator(
        StaticProvider(
            {
                "summary": "The model recommends acceptance.",
                "reasonCodes": ["MODEL_APPROVES"],
            }
        )
    ).validate(
        sku=sku,
        proposal=proposal,
        payment=payment,
        artifact={"result": "done"},
    )
    assert not denied.accepted

    accepted = DeliveryValidator().validate(
        sku=sku,
        proposal=proposal,
        payment=payment,
        artifact={"result": "done"},
        criterion_results={"customer_specific_check": True},
    )
    assert accepted.accepted


def test_delivery_validator_rejects_unaccepted_or_unverifiable_contract():
    sku = ServiceSKU(
        sku_id="sku_verify",
        capability_id="cap_verify",
        name="Verify",
        outcome="Return a verdict.",
        base_price_usdc=Decimal("0.50"),
    )
    proposal = offered_proposal(criteria=())
    decision = DeliveryValidator().validate(
        sku=sku,
        proposal=proposal,
        payment=confirmed_payment(proposal),
        artifact={"result": "done"},
    )
    assert not decision.accepted
    assert "PROPOSAL_NOT_ACCEPTED" in decision.reason_codes
    assert "NO_VALIDATABLE_ACCEPTANCE_CONTRACT" in decision.reason_codes


def test_gemini_import_is_optional_and_fails_with_clear_message(monkeypatch):
    import autonomerce.agents.providers as providers

    real_import = providers.importlib.import_module

    def missing_google(name):
        if name == "google.genai":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(providers.importlib, "import_module", missing_google)
    provider = GeminiDecisionProvider()
    request = DecisionRequest(
        operation="test",
        instruction="Return a test decision.",
        payload={"value": 1},
        response_schema={"type": "object"},
    )
    with pytest.raises(ProviderUnavailableError, match="optional"):
        provider.generate_json(request)


def test_gemini_adapter_uses_json_schema_without_live_credentials():
    class FakeModels:
        def __init__(self):
            self.call = None

        def generate_content(self, **kwargs):
            self.call = kwargs
            return SimpleNamespace(parsed={"summary": "ok", "reasonCodes": []})

    fake_models = FakeModels()
    provider = GeminiDecisionProvider(
        model="gemini-test-model",
        client=SimpleNamespace(models=fake_models),
    )
    request = DecisionRequest(
        operation="test",
        instruction="Return a compact decision.",
        payload={"publicValue": "safe"},
        response_schema={
            "type": "object",
            "required": ["summary", "reasonCodes"],
        },
    )
    result = provider.generate_json(request)

    assert result == {"summary": "ok", "reasonCodes": []}
    assert fake_models.call["model"] == "gemini-test-model"
    assert fake_models.call["config"]["response_mime_type"] == "application/json"
    assert (
        fake_models.call["config"]["response_json_schema"]
        == request.response_schema
    )


def test_provider_output_cannot_store_chain_of_thought():
    provider = GeminiDecisionProvider(
        client=SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **_: SimpleNamespace(
                    parsed={
                        "summary": "decision",
                        "reasoning": "private hidden trace",
                    }
                )
            )
        )
    )
    request = DecisionRequest(
        operation="test",
        instruction="Return a decision.",
        payload={"value": 1},
        response_schema={"type": "object"},
    )
    with pytest.raises(ProviderResponseError, match="private-reasoning"):
        provider.generate_json(request)


def test_stable_ids_use_shared_contract_implementation():
    sku = offline_sku()
    expected = stable_id(
        "sku",
        capability().capability_id,
        sku.name,
        sku.outcome,
        str(sku.base_price_usdc.normalize()),
    )
    assert sku.sku_id == expected
