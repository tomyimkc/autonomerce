"""One-command offline Autonomerce sale from Agent Cards to public receipt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.resources import files
from importlib.resources.abc import Traversable
import json
from pathlib import Path
from typing import Any, Mapping

from autonomerce.contracts import (
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    ProposalState,
    stable_id,
    usdc_text,
)

from .adapters import (
    AgentDeliveryValidatorAdapter,
    LaneBindings,
    implementation_path,
)


DEMO_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
PAYER_WALLET = "0x1111111111111111111111111111111111111111"
PAYEE_WALLET = "0x2222222222222222222222222222222222222222"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def default_fixture_dir() -> Traversable:
    repository_fixtures = (
        Path(__file__).resolve().parents[4] / "examples" / "fixtures"
    )
    if repository_fixtures.is_dir():
        return repository_fixtures
    return files("autonomerce.demo").joinpath("fixtures")


def _load_json(path: Traversable) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"demo fixture must contain a JSON object: {path}")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _seller_capability(
    seller_payload: Mapping[str, Any],
    seller_card: Any,
) -> CapabilityDescriptor:
    raw_skills = seller_payload.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise ValueError("seller Agent Card fixture requires at least one skill")
    raw_skill = raw_skills[0]
    if not isinstance(raw_skill, Mapping):
        raise ValueError("seller Agent Card skill must be an object")
    parsed = seller_card.capability_descriptors()[0]
    input_schema = raw_skill.get("inputSchema", {})
    output_schema = raw_skill.get("outputSchema", {})
    if not isinstance(input_schema, Mapping) or not isinstance(output_schema, Mapping):
        raise ValueError("seller Agent Card schemas must be JSON objects")
    return CapabilityDescriptor(
        capability_id=parsed.capability_id,
        name=parsed.name,
        description=parsed.description,
        input_schema=dict(input_schema),
        output_schema=dict(output_schema),
        source_kind=parsed.source_kind,
        source_url=parsed.source_url,
        tags=parsed.tags,
    )


def _buyer_need(
    payload: Mapping[str, Any],
    *,
    buyer_agent_url: str,
) -> BuyerNeed:
    desired_outcome = str(payload["desiredOutcome"]).strip()
    maximum_price = str(payload["maximumPriceUsdc"]).strip()
    required_tags = tuple(str(item).strip() for item in payload["requiredTags"])
    input_payload = payload["inputPayload"]
    if not isinstance(input_payload, Mapping):
        raise ValueError("buyer need inputPayload must be an object")
    expires_at = str(payload["expiresAt"]).strip()
    need_id = stable_id(
        "need",
        buyer_agent_url,
        desired_outcome,
        maximum_price,
        _canonical_json(required_tags),
        _canonical_json(input_payload),
        expires_at,
    )
    return BuyerNeed(
        need_id=need_id,
        buyer_agent_url=buyer_agent_url,
        desired_outcome=desired_outcome,
        maximum_price_usdc=Decimal(maximum_price),
        required_tags=required_tags,
        input_payload=dict(input_payload),
        expires_at=expires_at,
    )


def _commercial_policy(buyer_agent_url: str) -> CommercialPolicy:
    host = buyer_agent_url.split("://", 1)[-1].split("/", 1)[0]
    return CommercialPolicy(
        policy_id="policy_offline_demo",
        owner_id="owner_offline_seller",
        minimum_price_usdc=Decimal("0.50"),
        maximum_price_usdc=Decimal("2.00"),
        maximum_discount_fraction=Decimal("0.20"),
        maximum_open_proposals=4,
        maximum_tasks_per_hour=10,
        allowed_buyer_hosts=(host,),
        blocked_buyer_hosts=(),
        allowed_chains=("ARC-TESTNET",),
        allowed_token="USDC",
        unattended=True,
    )


def _increment(seconds: int) -> datetime:
    return DEMO_NOW + timedelta(seconds=seconds)


@dataclass(frozen=True)
class OfflineDemoRun:
    """JSON-ready evidence returned by the deterministic offline scenario."""

    public_receipt: Mapping[str, Any]
    trace: tuple[Mapping[str, Any], ...]
    diagnostics: Mapping[str, Any]
    implementations: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        # A JSON round trip detaches nested values and proves the public result is
        # serializable without custom encoders or binary-float money.
        return json.loads(
            json.dumps(
                {
                    "publicReceipt": self.public_receipt,
                    "trace": list(self.trace),
                    "diagnostics": self.diagnostics,
                    "implementations": self.implementations,
                },
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def run_offline_demo(
    *,
    fixture_dir: str | Path | None = None,
    bindings: LaneBindings | None = None,
) -> OfflineDemoRun:
    """Execute a deterministic sale without network, credentials, or real funds."""

    selected = (bindings or LaneBindings.discover()).require_all()
    agents = selected.require("agents")
    payments = selected.require("payments")
    sales = selected.require("sales")
    offerrail = selected.require("offerrail")

    fixtures: Traversable = (
        Path(fixture_dir) if fixture_dir is not None else default_fixture_dir()
    )
    seller_payload = _load_json(fixtures.joinpath("seller-agent-card.json"))
    buyer_payload = _load_json(fixtures.joinpath("buyer-agent-card.json"))
    need_payload = _load_json(fixtures.joinpath("buyer-need.json"))
    artifact = _load_json(fixtures.joinpath("fulfillment-artifact.json"))

    seller_card = sales.parse_agent_card(seller_payload)
    buyer_card = sales.parse_agent_card(buyer_payload)
    capability = _seller_capability(seller_payload, seller_card)
    policy = _commercial_policy(buyer_card.url)

    productizer = agents.CapabilityProductizer()
    productization = productizer.productize(
        capability,
        policy,
        maximum_skus=1,
    )
    recommended_sku = productization.skus[0]
    # Gemini/offline-provider terms remain recommendations. OfferRail rebuilds
    # the authoritative SKU so its ID covers the complete sellable contract.
    sku = offerrail.capability_to_sku(
        capability,
        base_price_usdc=recommended_sku.base_price_usdc,
        name=recommended_sku.name,
        outcome=recommended_sku.outcome,
        acceptance_criteria=recommended_sku.acceptance_criteria,
        maximum_latency_seconds=recommended_sku.maximum_latency_seconds,
        capacity_per_hour=recommended_sku.capacity_per_hour,
        input_schema=recommended_sku.input_schema,
        output_schema=recommended_sku.output_schema,
    )

    need = _buyer_need(need_payload, buyer_agent_url=buyer_card.url)
    consent = need_payload.get("consent")
    if not isinstance(consent, Mapping):
        raise ValueError("buyer need fixture requires explicit consent evidence")
    registry = sales.OptedInProspectRegistry()
    prospect = registry.register(
        buyer_card,
        opted_in=consent.get("optedIn") is True,
        consent_reference=str(consent["reference"]),
        allowed_topics=tuple(str(item) for item in consent["allowedTopics"]),
        opted_in_at=DEMO_NOW,
        consent_expires_at=datetime.fromisoformat(
            str(consent["expiresAt"]).replace("Z", "+00:00")
        ),
        metadata={"fixture": True},
    )
    match = sales.match_need_to_sku(need, sku, capability)

    fit_scorer = agents.ProspectFitScorer()
    fit = fit_scorer.score(
        sku,
        need,
        opted_in=prospect.is_active(DEMO_NOW),
        capability=capability,
        policy=policy,
    )
    if not match.eligible or not fit.recommended:
        raise RuntimeError(
            "offline fixture failed opted-in deterministic matching: "
            f"match={match.reason_codes}, fit={fit.reason_codes}"
        )

    pitch_workflow = sales.PitchWorkflow(
        seller_agent_url=seller_card.url,
        commercial_policy=policy,
        registry=registry,
        anti_spam=sales.AntiSpamPolicy(cooldown_seconds=1),
    )
    pitch = pitch_workflow.pitch(
        need=need,
        sku=sku,
        match=match,
        now=DEMO_NOW,
    )
    if not pitch.sent or pitch.proposal is None:
        raise RuntimeError(f"offline pitch denied: {pitch.reason_code}")
    offered = pitch.proposal
    offer_policy = offerrail.evaluate_commercial_policy(
        policy,
        sku,
        offered,
        context=offerrail.PolicyContext(
            chain="ARC-TESTNET",
            token="USDC",
            current_open_proposals=0,
            current_tasks_last_hour=0,
            current_sku_tasks_last_hour=0,
            reserving_new_proposal=False,
            now=DEMO_NOW,
        ),
    )
    if not offer_policy.allowed:
        raise RuntimeError(
            "OfferRail denied the sales proposal: "
            + ",".join(offer_policy.reason_codes)
        )

    negotiation = sales.NegotiationOrchestrator(
        commercial_policy=policy,
        max_rounds=2,
    )
    session = negotiation.start(offered)
    requested_price = Decimal(str(need_payload["counterOffer"]["priceUsdc"]))
    decision = negotiation.advance(
        session,
        sales.BuyerResponse(
            sales.NegotiationAction.COUNTER,
            price_usdc=requested_price,
            reason="fixture buyer requests the pre-authorized bounded discount",
        ),
        now=_increment(1),
    )
    if not decision.accepted:
        raise RuntimeError(
            f"offline bounded negotiation was not accepted: {decision.reason_code}"
        )
    accepted = decision.proposal
    accepted_policy = offerrail.evaluate_commercial_policy(
        policy,
        sku,
        accepted,
        context=offerrail.PolicyContext(
            chain="ARC-TESTNET",
            token="USDC",
            current_open_proposals=1,
            current_tasks_last_hour=0,
            current_sku_tasks_last_hour=0,
            reserving_new_proposal=False,
            now=_increment(1),
        ),
    )
    if not accepted_policy.allowed:
        raise RuntimeError(
            "OfferRail denied the accepted terms: "
            + ",".join(accepted_policy.reason_codes)
        )
    pitch_workflow.update_proposal(accepted)

    payment_policy = payments.PaymentPolicy.from_commercial_policy(
        policy,
        mode=payments.PaymentMode.OFFLINE,
        payer_wallets=(PAYER_WALLET,),
        payee_wallets=(PAYEE_WALLET,),
        maximum_total_usdc=Decimal("5"),
        maximum_payment_count=5,
    )
    payment_key = offerrail.make_idempotency_key(
        "offline-payment",
        accepted.proposal_id,
    )
    payment_intent = payments.PaymentIntent.from_proposal(
        accepted,
        idempotency_key=payment_key,
        chain="ARC-TESTNET",
        payer_wallet=PAYER_WALLET,
        payee_wallet=PAYEE_WALLET,
        token="USDC",
        metadata={"offlineDemo": True},
    )
    payment_store = payments.InMemoryPaymentStore()
    payment_executor = payments.OfflineCircleExecutor(clock=lambda: _increment(2))
    payment_processor = payments.PaymentProcessor(
        policy=payment_policy,
        store=payment_store,
        executor=payment_executor,
    )
    payment = payment_processor.pay(payment_intent)
    duplicate_payment = payment_processor.pay(payment_intent)
    public_payment = payments.public_payment_receipt(
        payment,
        mode=payments.PaymentMode.OFFLINE,
        verified=True,
        metadata={"simulated": True},
    )

    paid = offerrail.transition_proposal(
        accepted,
        ProposalState.PAID,
        expected_revision=accepted.revision,
        now=_increment(2),
    )
    seller_adapter = sales.FixtureSellerFulfillmentAdapter({sku.sku_id: artifact})
    agent_delivery_validator = agents.DeliveryValidator()
    validation_adapter = AgentDeliveryValidatorAdapter(
        sales_module=sales,
        validator=agent_delivery_validator,
        sku=sku,
        payment=payment,
        delivered_at=_iso(_increment(3)),
    )
    fulfillment_orchestrator = sales.FulfillmentOrchestrator(
        adapter=seller_adapter,
        validator=validation_adapter,
        validator_name=agent_delivery_validator.validator_name,
    )
    fulfillment = fulfillment_orchestrator.fulfill(
        proposal=paid,
        payment=payment,
        input_payload=need.input_payload,
        now=_increment(3),
    )
    if not fulfillment.receipt.accepted:
        raise RuntimeError("offline seller artifact failed contract validation")
    fulfilling = offerrail.transition_proposal(
        paid,
        ProposalState.FULFILLING,
        expected_revision=paid.revision,
        now=_increment(3),
    )
    delivered = offerrail.transition_proposal(
        fulfilling,
        ProposalState.DELIVERED,
        expected_revision=fulfilling.revision,
        now=_increment(4),
    )
    public_delivery = sales.delivery_receipt_to_public_dict(
        fulfillment.receipt
    )

    order_id = stable_id(
        "order",
        accepted.proposal_id,
        payment.payment_id,
        fulfillment.receipt.fulfillment_id,
    )
    ledger = offerrail.CommercialReceiptLedger()
    ledger.append(
        event_type="proposal.accepted",
        proposal_id=accepted.proposal_id,
        payload={
            "orderId": order_id,
            "skuId": sku.sku_id,
            "state": accepted.state.value,
            "amountUsdc": usdc_text(accepted.price_usdc),
            "acceptanceVerdict": decision.reason_code,
        },
        occurred_at=_increment(1),
        idempotency_key=stable_id("event", order_id, "proposal.accepted"),
    )
    ledger.append(
        event_type="payment.confirmed",
        proposal_id=accepted.proposal_id,
        payload={
            "orderId": order_id,
            "payment": public_payment,
        },
        occurred_at=_increment(2),
        idempotency_key=stable_id("event", order_id, "payment.confirmed"),
    )
    ledger.append(
        event_type="delivery.accepted",
        proposal_id=accepted.proposal_id,
        payload={
            "orderId": order_id,
            "delivery": public_delivery,
        },
        occurred_at=_increment(3),
        idempotency_key=stable_id("event", order_id, "delivery.accepted"),
    )
    revenue_receipt = ledger.append(
        event_type="revenue.recorded",
        proposal_id=accepted.proposal_id,
        payload={
            "orderId": order_id,
            "amountUsdc": usdc_text(payment.amount_usdc),
            "token": "USDC",
            "network": payment.chain,
            "settlementKind": "simulated",
            "paymentId": payment.payment_id,
            "fulfillmentId": fulfillment.receipt.fulfillment_id,
            "acceptanceVerdict": "accepted",
        },
        occurred_at=_increment(4),
        idempotency_key=stable_id("event", order_id, "revenue.recorded"),
    )

    public_receipt = {
        "schema": "autonomerce.public_delivery_revenue_receipt.v1",
        "orderId": order_id,
        "proposalId": accepted.proposal_id,
        "skuId": sku.sku_id,
        "status": delivered.state.value,
        "acceptanceVerdict": "accepted",
        "revenue": {
            "amountUsdc": usdc_text(payment.amount_usdc),
            "token": "USDC",
            "network": payment.chain,
            "settlementKind": "simulated",
            "movesFunds": False,
            "paymentId": payment.payment_id,
            "transactionHash": payment.transaction_hash,
            "confirmedAt": payment.confirmed_at,
        },
        "delivery": public_delivery,
        "ledger": {
            "receiptId": revenue_receipt.receipt_id,
            "sequence": revenue_receipt.sequence,
            "receiptHash": revenue_receipt.receipt_hash,
            "previousHash": revenue_receipt.previous_hash,
            "chainVerified": ledger.verify(),
        },
        "generatedAt": _iso(_increment(4)),
        "scope": (
            "Offline fixture delivery passed its declared service contract; "
            "this receipt makes no external factual claim."
        ),
    }

    trace = (
        {
            "step": "seller_capability",
            "capabilityId": capability.capability_id,
            "source": capability.source_kind,
        },
        {
            "step": "sku",
            "skuId": sku.sku_id,
            "priceUsdc": usdc_text(sku.base_price_usdc),
            "provider": productization.metadata.provider,
        },
        {
            "step": "opted_in_buyer_need",
            "needId": need.need_id,
            "prospectId": prospect.prospect_id,
            "matchEligible": match.eligible,
            "fitRecommended": fit.recommended,
        },
        {
            "step": "proposal",
            "proposalId": offered.proposal_id,
            "state": offered.state.value,
            "policyAllowed": offer_policy.allowed,
        },
        {
            "step": "bounded_acceptance",
            "proposalId": accepted.proposal_id,
            "state": accepted.state.value,
            "reasonCode": decision.reason_code,
            "amountUsdc": usdc_text(accepted.price_usdc),
        },
        {
            "step": "mock_payment",
            "paymentId": payment.payment_id,
            "state": payment.state.value,
            "settlementKind": "simulated",
        },
        {
            "step": "fulfillment",
            "fulfillmentId": fulfillment.receipt.fulfillment_id,
            "accepted": fulfillment.receipt.accepted,
            "artifactHash": fulfillment.receipt.artifact_hash,
        },
        {
            "step": "public_delivery_revenue_receipt",
            "orderId": order_id,
            "receiptId": revenue_receipt.receipt_id,
            "status": delivered.state.value,
        },
    )

    implementations = {
        "productizer": implementation_path(productizer),
        "catalog": (
            f"{offerrail.capability_to_sku.__module__}."
            f"{offerrail.capability_to_sku.__qualname__}"
        ),
        "prospectRegistry": implementation_path(registry),
        "matcher": (
            f"{sales.match_need_to_sku.__module__}."
            f"{sales.match_need_to_sku.__qualname__}"
        ),
        "fitScorer": implementation_path(fit_scorer),
        "pitchWorkflow": implementation_path(pitch_workflow),
        "negotiation": implementation_path(negotiation),
        "paymentProcessor": implementation_path(payment_processor),
        "paymentExecutor": implementation_path(payment_executor),
        "fulfillment": implementation_path(fulfillment_orchestrator),
        "deliveryValidator": implementation_path(agent_delivery_validator),
        "receiptLedger": implementation_path(ledger),
    }
    diagnostics = {
        "offline": True,
        "networkCalls": 0,
        "credentialsUsed": False,
        "realFundsMoved": False,
        "allLanesAvailable": not selected.missing_lanes,
        "availableLanes": list(selected.available_lanes),
        "paymentExecutorCalls": len(payment_executor.calls),
        "idempotentPaymentReplay": duplicate_payment == payment,
        "sellerFulfillmentCalls": len(seller_adapter.calls),
        "ledgerEntries": len(ledger.records),
        "ledgerVerified": ledger.verify(),
        "commercialPolicyAllowed": offer_policy.allowed
        and accepted_policy.allowed,
        "artifactPublished": False,
    }
    return OfflineDemoRun(
        public_receipt=public_receipt,
        trace=trace,
        diagnostics=diagnostics,
        implementations=implementations,
    )
