from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
import json
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages"))

from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    ContractError,
    Proposal,
    ProposalState,
    ServiceSKU,
)
from offerrail import (  # noqa: E402
    CommercialReceipt,
    CommercialReceiptLedger,
    IdempotencyConflict,
    IdempotencyFailed,
    IdempotencyStatus,
    IdempotencyStore,
    PolicyContext,
    ProposalTransitionError,
    ReceiptConflict,
    ReceiptError,
    build_sku_catalog,
    capability_to_sku,
    create_proposal,
    evaluate_commercial_policy,
    make_idempotency_key,
    negotiate_counteroffer,
    redact_commercial_data,
    request_fingerprint,
    transition_proposal,
)


NOW = "2026-08-01T12:00:00Z"
LATER = "2026-08-01T13:00:00Z"


def capability(
    capability_id: str = "cap_verify",
    *,
    input_schema: dict | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        name="Verify a claim",
        description="Return a cited support, refute, or abstain verdict",
        input_schema=input_schema or {"type": "object", "required": ["claim"]},
        output_schema={"type": "object", "required": ["verdict", "sources"]},
        tags=("verification", "evidence"),
    )


def sku(
    *,
    base_price: str = "1.00",
    latency: int = 300,
    capacity: int = 4,
) -> ServiceSKU:
    return capability_to_sku(
        capability(),
        base_price_usdc=base_price,
        acceptance_criteria=("valid JSON", "sources present"),
        maximum_latency_seconds=latency,
        capacity_per_hour=capacity,
    )


def policy(
    *,
    minimum: str = "0.80",
    maximum: str = "2.00",
    discount: str = "0.20",
    allowed_hosts: tuple[str, ...] = ("*.buyers.example",),
    blocked_hosts: tuple[str, ...] = ("blocked.buyers.example",),
    unattended: bool = True,
    maximum_open: int = 3,
    maximum_tasks: int = 5,
) -> CommercialPolicy:
    return CommercialPolicy(
        policy_id="policy_seller",
        owner_id="seller_owner",
        minimum_price_usdc=Decimal(minimum),
        maximum_price_usdc=Decimal(maximum),
        maximum_discount_fraction=Decimal(discount),
        maximum_open_proposals=maximum_open,
        maximum_tasks_per_hour=maximum_tasks,
        allowed_buyer_hosts=allowed_hosts,
        blocked_buyer_hosts=blocked_hosts,
        allowed_chains=("BASE", "ARC-TESTNET"),
        allowed_token="USDC",
        unattended=unattended,
    )


def proposal(
    product: ServiceSKU | None = None,
    *,
    price: str = "1.00",
    state: ProposalState = ProposalState.DRAFT,
    buyer_url: str = "https://alpha.buyers.example/agent",
    delivery: int = 240,
    expires_at: str | None = LATER,
    revision: int = 1,
) -> Proposal:
    selected_sku = product or sku()
    return Proposal(
        proposal_id="proposal_test",
        seller_agent_url="https://seller.example/agent",
        buyer_agent_url=buyer_url,
        sku_id=selected_sku.sku_id,
        problem_observed="Claims need evidence",
        offered_outcome=selected_sku.outcome,
        price_usdc=Decimal(price),
        delivery_seconds=delivery,
        acceptance_criteria=selected_sku.acceptance_criteria,
        expires_at=expires_at,
        state=state,
        revision=revision,
    )


def test_capability_to_sku_is_stable_and_uses_shared_contract_type():
    first = capability_to_sku(
        capability(input_schema={"required": ["claim"], "type": "object"}),
        base_price_usdc="1.000000",
        acceptance_criteria=("valid JSON", "valid JSON", "sources present"),
        maximum_latency_seconds=120,
        capacity_per_hour=10,
    )
    second = capability_to_sku(
        capability(input_schema={"type": "object", "required": ["claim"]}),
        base_price_usdc=Decimal("1"),
        acceptance_criteria=("valid JSON", "sources present"),
        maximum_latency_seconds=120,
        capacity_per_hour=10,
    )
    assert isinstance(first, ServiceSKU)
    assert first == second
    assert first.sku_id.startswith("sku_")
    assert first.acceptance_criteria == ("valid JSON", "sources present")


def test_capability_to_sku_changes_id_when_sellable_contract_changes():
    original = sku(base_price="1")
    repriced = sku(base_price="1.01")
    slower = sku(base_price="1", latency=301)
    assert len({original.sku_id, repriced.sku_id, slower.sku_id}) == 3


def test_capability_to_sku_rejects_float_and_unsupported_schema_values():
    with pytest.raises(ContractError):
        capability_to_sku(capability(), base_price_usdc=1.5)
    with pytest.raises(ContractError):
        capability_to_sku(
            capability(input_schema={"default": object()}),
            base_price_usdc="1",
        )
    with pytest.raises(ContractError, match="criteria"):
        capability_to_sku(
            capability(),
            base_price_usdc="1",
            acceptance_criteria="valid JSON",
        )


def test_catalog_is_sorted_and_duplicate_capabilities_fail_closed():
    catalog = build_sku_catalog(
        [capability("cap_z"), capability("cap_a")],
        base_price_usdc="0.10",
    )
    assert [item.capability_id for item in catalog] == ["cap_a", "cap_z"]
    with pytest.raises(ContractError, match="duplicate"):
        build_sku_catalog(
            [capability("cap_same"), capability("cap_same")],
            base_price_usdc="0.10",
        )


def test_policy_allows_offer_inside_every_bound():
    product = sku()
    evaluation = evaluate_commercial_policy(
        policy(),
        product,
        proposal(product),
        context=PolicyContext(
            chain="base",
            token="usdc",
            current_open_proposals=1,
            current_tasks_last_hour=2,
            current_sku_tasks_last_hour=1,
            now=NOW,
        ),
    )
    assert evaluation.allowed
    assert evaluation.reason_code == "policy_allowed"
    assert evaluation.reason_codes == ()


def test_policy_collects_price_chain_token_capacity_and_expiry_denials():
    product = sku(capacity=2)
    evaluation = evaluate_commercial_policy(
        policy(maximum_open=2, maximum_tasks=3),
        product,
        proposal(
            product,
            price="0.79",
            delivery=301,
            expires_at=NOW,
        ),
        context=PolicyContext(
            chain="ETHEREUM",
            token="DAI",
            current_open_proposals=2,
            current_tasks_last_hour=3,
            current_sku_tasks_last_hour=2,
            now=NOW,
        ),
    )
    assert not evaluation.allowed
    assert set(evaluation.reason_codes) >= {
        "price_below_policy_minimum",
        "discount_exceeds_policy",
        "delivery_exceeds_sku_latency",
        "chain_not_allowed",
        "token_not_allowed",
        "open_proposal_capacity_exceeded",
        "hourly_task_capacity_exceeded",
        "sku_capacity_exceeded",
        "proposal_expired",
    }


def test_policy_blocklist_precedes_allowlist_and_host_matches_are_bounded():
    product = sku()
    blocked = evaluate_commercial_policy(
        policy(),
        product,
        proposal(product, buyer_url="https://blocked.buyers.example/agent"),
        now=NOW,
    )
    suffix_attack = evaluate_commercial_policy(
        policy(),
        product,
        proposal(product, buyer_url="https://buyers.example.attacker.test/agent"),
        now=NOW,
    )
    assert "buyer_blocked" in blocked.reason_codes
    assert "buyer_not_allowlisted" in suffix_attack.reason_codes


def test_plain_allowlist_host_includes_real_subdomains_not_suffix_attacks():
    product = sku()
    allowed = evaluate_commercial_policy(
        policy(allowed_hosts=("buyers.example",), blocked_hosts=()),
        product,
        proposal(product, buyer_url="https://team.buyers.example/agent"),
        now=NOW,
    )
    attacked = evaluate_commercial_policy(
        policy(allowed_hosts=("buyers.example",), blocked_hosts=()),
        product,
        proposal(product, buyer_url="https://buyers.example.attacker.test/agent"),
        now=NOW,
    )
    assert allowed.allowed
    assert "buyer_not_allowlisted" in attacked.reason_codes


def test_policy_malformed_url_and_capacity_context_fail_closed():
    product = sku()
    evaluation = evaluate_commercial_policy(
        policy(allowed_hosts=()),
        product,
        proposal(product, buyer_url="https://user:pass@buyers.example/agent"),
        current_open_proposals=-1,
        now=NOW,
    )
    assert not evaluation.allowed
    assert "invalid_buyer_url" in evaluation.reason_codes
    assert "invalid_capacity_context" in evaluation.reason_codes


def test_existing_counter_does_not_consume_a_new_open_proposal_slot():
    product = sku()
    existing = proposal(product, state=ProposalState.COUNTERED)
    evaluation = evaluate_commercial_policy(
        policy(maximum_open=1),
        product,
        existing,
        current_open_proposals=1,
        now=NOW,
    )
    assert evaluation.allowed


def test_create_proposal_is_deterministic_and_policy_checked():
    product = sku()
    buyer_need = BuyerNeed(
        need_id="need_1",
        buyer_agent_url="https://alpha.buyers.example/agent",
        desired_outcome=product.outcome,
        maximum_price_usdc=Decimal("1.50"),
        expires_at=LATER,
    )
    first = create_proposal(
        sku=product,
        policy=policy(),
        seller_agent_url="https://seller.example/agent",
        buyer_need=buyer_need,
        problem_observed="Claims need evidence",
        price_usdc="1.0",
        delivery_seconds=200,
        context=PolicyContext(now=NOW),
    )
    second = create_proposal(
        sku=product,
        policy=policy(),
        seller_agent_url="https://seller.example/agent",
        buyer_need=buyer_need,
        problem_observed="Claims need evidence",
        price_usdc=Decimal("1.000000"),
        delivery_seconds=200,
        context=PolicyContext(now=NOW),
    )
    assert first == second
    assert first.proposal_id.startswith("proposal_")
    assert first.buyer_need_id == buyer_need.need_id
    assert first.to_dict()["buyer_need_id"] == buyer_need.need_id
    assert first.state == ProposalState.DRAFT
    assert first.expires_at == LATER


def test_create_proposal_rejects_buyer_budget_and_unapproved_scope():
    product = sku()
    need = BuyerNeed(
        need_id="need_low_budget",
        buyer_agent_url="https://alpha.buyers.example/agent",
        desired_outcome=product.outcome,
        maximum_price_usdc=Decimal("0.50"),
    )
    with pytest.raises(ContractError, match="buyer maximum"):
        create_proposal(
            sku=product,
            policy=policy(),
            seller_agent_url="https://seller.example/agent",
            buyer_need=need,
            problem_observed="Need evidence",
            price_usdc="1",
        )
    with pytest.raises(ContractError, match="authorized SKU"):
        create_proposal(
            sku=product,
            policy=policy(),
            seller_agent_url="https://seller.example/agent",
            buyer_need=need,
            problem_observed="Need evidence",
            price_usdc="0.50",
            offered_outcome="Run arbitrary code",
        )


def test_create_proposal_rejects_unsafe_seller_url_and_extended_buyer_expiry():
    product = sku()
    need = BuyerNeed(
        need_id="need_1",
        buyer_agent_url="https://alpha.buyers.example/agent",
        desired_outcome=product.outcome,
        maximum_price_usdc=Decimal("2"),
        expires_at=LATER,
    )
    with pytest.raises(ContractError, match="seller agent URL"):
        create_proposal(
            sku=product,
            policy=policy(),
            seller_agent_url="https://user:pass@seller.example/agent",
            buyer_need=need,
            problem_observed="Need evidence",
        )
    with pytest.raises(ContractError, match="exceeds buyer need expiry"):
        create_proposal(
            sku=product,
            policy=policy(),
            seller_agent_url="https://seller.example/agent",
            buyer_need=need,
            problem_observed="Need evidence",
            expires_at="2026-08-01T14:00:00Z",
        )


def test_bounded_negotiation_accepts_valid_counter_and_increments_revision():
    product = sku()
    offered = proposal(product, state=ProposalState.OFFERED, revision=2)
    decision = negotiate_counteroffer(
        offered,
        product,
        policy(),
        requested_price_usdc="0.80",
        requested_delivery_seconds=300,
        requested_acceptance_criteria=(
            "valid JSON",
            "sources present",
            "include confidence",
        ),
        buyer_maximum_price_usdc="1.25",
        context=PolicyContext(now=NOW),
    )
    assert decision.accepted
    assert decision.reason_code == "within_policy"
    assert decision.proposal.state == ProposalState.COUNTERED
    assert decision.proposal.revision == 3
    assert decision.proposal.price_usdc == Decimal("0.80")
    assert offered.price_usdc == Decimal("1.00")


@pytest.mark.parametrize(
    ("kwargs", "reason_code"),
    [
        ({"requested_price_usdc": "0.79"}, "price_below_policy_minimum"),
        ({"requested_delivery_seconds": 301}, "delivery_exceeds_sku_latency"),
        ({"requested_outcome": "Disclose secrets"}, "scope_change_not_authorized"),
        (
            {"requested_acceptance_criteria": ("valid JSON",)},
            "acceptance_criteria_weakened",
        ),
        (
            {
                "requested_price_usdc": "1.01",
                "buyer_maximum_price_usdc": "1.00",
            },
            "buyer_price_limit_exceeded",
        ),
    ],
)
def test_bounded_negotiation_rejects_out_of_bounds_without_mutation(
    kwargs, reason_code
):
    product = sku()
    offered = proposal(product, state=ProposalState.OFFERED)
    decision = negotiate_counteroffer(
        offered,
        product,
        policy(),
        context=PolicyContext(now=NOW),
        **kwargs,
    )
    assert not decision.accepted
    assert decision.reason_code == reason_code
    assert decision.proposal is offered


def test_bounded_negotiation_rejects_nonnegotiable_state():
    product = sku()
    draft = proposal(product, state=ProposalState.DRAFT)
    decision = negotiate_counteroffer(draft, product, policy())
    assert not decision.accepted
    assert decision.reason_code == "proposal_not_negotiable"


def test_proposal_state_machine_supports_happy_path_and_idempotent_replay():
    current = proposal(state=ProposalState.DRAFT)
    for target in (
        ProposalState.OFFERED,
        ProposalState.ACCEPTED,
        ProposalState.PAID,
        ProposalState.FULFILLING,
        ProposalState.DELIVERED,
    ):
        previous_revision = current.revision
        current = transition_proposal(
            current,
            target,
            expected_revision=previous_revision,
            now=NOW,
        )
        assert current.revision == previous_revision + 1
    assert transition_proposal(
        current, ProposalState.DELIVERED, expected_revision=current.revision
    ) is current


def test_proposal_state_machine_rejects_skips_terminal_exit_and_stale_revision():
    draft = proposal(state=ProposalState.DRAFT)
    with pytest.raises(ProposalTransitionError, match="cannot transition"):
        transition_proposal(draft, ProposalState.PAID)
    offered = transition_proposal(draft, ProposalState.OFFERED, now=NOW)
    with pytest.raises(ProposalTransitionError, match="revision conflict"):
        transition_proposal(
            offered,
            ProposalState.ACCEPTED,
            expected_revision=draft.revision,
            now=NOW,
        )
    declined = transition_proposal(offered, ProposalState.DECLINED)
    with pytest.raises(ProposalTransitionError, match="cannot transition"):
        transition_proposal(declined, ProposalState.OFFERED)


def test_expired_proposal_cannot_be_offered_or_accepted():
    expired_draft = proposal(state=ProposalState.DRAFT, expires_at=NOW)
    with pytest.raises(ProposalTransitionError, match="expired"):
        transition_proposal(expired_draft, ProposalState.OFFERED, now=NOW)
    expired_offer = proposal(state=ProposalState.OFFERED, expires_at=NOW)
    with pytest.raises(ProposalTransitionError, match="expired"):
        transition_proposal(expired_offer, ProposalState.ACCEPTED, now=NOW)


def test_redaction_removes_nested_secrets_identity_prompts_and_auth_values():
    redacted = redact_commercial_data(
        {
            "apiKey": "circle-secret",
            "allowedToken": "USDC",
            "buyer": {
                "buyerEmail": "private@example.com",
                "prompt": "confidential request",
            },
            "headers": {"Authorization": "Bearer very-secret-token"},  # secret-scan: allow-test-fixture
            "note": "send api_key=visible-secret and sk-abcdefghijk",  # secret-scan: allow-test-fixture
            "transactionHash": "0xpublic",
        }
    )
    serialized = json.dumps(redacted, sort_keys=True)
    assert "circle-secret" not in serialized
    assert "private@example.com" not in serialized
    assert "confidential request" not in serialized
    assert "very-secret-token" not in serialized
    assert "visible-secret" not in serialized
    assert "sk-abcdefghijk" not in serialized
    assert redacted["allowedToken"] == "USDC"
    assert redacted["transactionHash"] == "0xpublic"


def test_redaction_requires_prompt_consent_and_never_exposes_private_identity():
    value = {"buyerId": "buyer_1", "prompt": "public by consent"}
    assert redact_commercial_data(value) == {
        "buyerId": "[REDACTED]",
        "prompt": "[REDACTED]",
    }
    assert redact_commercial_data(
        value,
        allow_customer_prompt=True,
    ) == {"buyerId": "[REDACTED]", "prompt": "public by consent"}


def test_receipt_ledger_is_hash_chained_redacted_and_append_only():
    ledger = CommercialReceiptLedger()
    source_payload = {
        "amountUsdc": Decimal("1.000000"),
        "authorization": "Bearer do-not-store",  # secret-scan: allow-test-fixture
        "nested": {"values": [1, 2]},
    }
    first = ledger.append(
        event_type="proposal.accepted",
        proposal_id="proposal_1",
        payload=source_payload,
        occurred_at=NOW,
    )
    source_payload["nested"]["values"].append(3)
    second = ledger.append(
        event_type="payment.confirmed",
        proposal_id="proposal_1",
        payload={"transactionHash": "0xabc", "sessionToken": "private"},
        occurred_at=LATER,
    )
    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.receipt_hash
    assert ledger.verify()
    assert first.payload["amountUsdc"] == "1"
    assert first.payload["authorization"] == "[REDACTED]"
    assert first.payload["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        first.payload["nested"]["values"][0] = 99
    assert "do-not-store" not in ledger.to_jsonl()
    assert "private" not in ledger.to_jsonl()


def test_receipt_append_is_idempotent_and_conflicting_reuse_fails():
    ledger = CommercialReceiptLedger()
    first = ledger.append(
        event_type="payment.confirmed",
        proposal_id="proposal_1",
        payload={"transactionHash": "0xabc"},
        occurred_at=NOW,
        idempotency_key="payment_attempt_1",
    )
    replay = ledger.append(
        event_type="payment.confirmed",
        proposal_id="proposal_1",
        payload={"transactionHash": "0xabc"},
        occurred_at=LATER,
        idempotency_key="payment_attempt_1",
    )
    assert replay is first
    assert len(ledger.records) == 1
    with pytest.raises(ReceiptConflict):
        ledger.append(
            event_type="payment.confirmed",
            proposal_id="proposal_1",
            payload={"transactionHash": "0xdifferent"},
            occurred_at=LATER,
            idempotency_key="payment_attempt_1",
        )


def test_commercial_receipt_is_frozen():
    receipt = CommercialReceiptLedger().append(
        event_type="proposal.offered",
        proposal_id="proposal_1",
        payload={},
        occurred_at=NOW,
    )
    with pytest.raises(FrozenInstanceError):
        receipt.sequence = 99


def test_direct_commercial_receipt_rejects_unredacted_payload():
    with pytest.raises(ReceiptError, match="not safely redacted"):
        CommercialReceipt(
            receipt_id="receipt_test",
            sequence=1,
            event_type="payment.confirmed",
            occurred_at=NOW,
            proposal_id="proposal_1",
            payload={"authorization": "Bearer secret-token"},  # secret-scan: allow-test-fixture
            previous_hash=None,
            receipt_hash="sha256:" + ("0" * 64),
        )


def test_idempotency_key_and_fingerprint_are_canonical():
    assert make_idempotency_key(
        "payment", {"amount": Decimal("1.000"), "chain": "BASE"}
    ) == make_idempotency_key(
        "payment", {"chain": "BASE", "amount": Decimal("1")}
    )
    assert request_fingerprint({"b": 2, "a": 1}) == request_fingerprint(
        {"a": 1, "b": 2}
    )
    with pytest.raises(ContractError, match="binary float"):
        request_fingerprint({"amount": 1.0})


def test_idempotency_reservation_replays_same_request_and_rejects_conflict():
    store = IdempotencyStore()
    first = store.reserve("idem_1", {"proposal": "proposal_1"})
    replay = store.reserve("idem_1", {"proposal": "proposal_1"})
    assert first.acquired
    assert not replay.acquired
    assert replay.record.status == IdempotencyStatus.PENDING
    with pytest.raises(IdempotencyConflict):
        store.reserve("idem_1", {"proposal": "proposal_2"})


def test_idempotency_complete_is_immutable_and_replayable():
    store = IdempotencyStore()
    request = {"proposal": "proposal_1", "amount": Decimal("1")}
    store.reserve("idem_1", request)
    completed = store.complete("idem_1", request, {"transactionHash": "0xabc"})
    replay = store.complete("idem_1", request, {"transactionHash": "0xabc"})
    assert replay == completed
    assert completed.status == IdempotencyStatus.SUCCEEDED
    with pytest.raises(IdempotencyConflict):
        store.complete("idem_1", request, {"transactionHash": "0xdifferent"})


def test_run_once_executes_payment_operation_at_most_once():
    store = IdempotencyStore()
    calls = 0

    def settle():
        nonlocal calls
        calls += 1
        return {"transactionHash": "0xabc"}

    first = store.run_once("payment_1", {"proposal": "proposal_1"}, settle)
    second = store.run_once("payment_1", {"proposal": "proposal_1"}, settle)
    assert first == second == {"transactionHash": "0xabc"}
    assert calls == 1


def test_failed_idempotent_operation_is_blocked_from_automatic_retry():
    store = IdempotencyStore()
    calls = 0

    def uncertain_failure():
        nonlocal calls
        calls += 1
        raise RuntimeError("connection lost after submission")

    with pytest.raises(RuntimeError):
        store.run_once(
            "payment_1",
            {"proposal": "proposal_1"},
            uncertain_failure,
        )
    with pytest.raises(IdempotencyFailed):
        store.run_once(
            "payment_1",
            {"proposal": "proposal_1"},
            uncertain_failure,
        )
    assert calls == 1
    assert store.get("payment_1").status == IdempotencyStatus.FAILED


def test_noncanonical_operation_response_is_blocked_after_execution():
    store = IdempotencyStore()
    calls = 0

    def settle_with_float():
        nonlocal calls
        calls += 1
        return {"fee": 0.01}

    with pytest.raises(ContractError, match="binary float"):
        store.run_once("payment_1", {"proposal": "proposal_1"}, settle_with_float)
    with pytest.raises(IdempotencyFailed):
        store.run_once("payment_1", {"proposal": "proposal_1"}, settle_with_float)
    assert calls == 1
