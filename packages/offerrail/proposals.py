"""Proposal construction and explicit lifecycle transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit

from autonomerce.contracts import (
    BuyerNeed,
    CommercialPolicy,
    ContractError,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
    usdc,
    usdc_text,
)

from ._canonical import canonical_json, canonical_timestamp, parse_timestamp
from .policy import PolicyContext, require_policy_approval


class ProposalTransitionError(ContractError):
    """An invalid or stale proposal lifecycle transition."""


ALLOWED_PROPOSAL_TRANSITIONS: dict[ProposalState, frozenset[ProposalState]] = {
    ProposalState.DRAFT: frozenset(
        {ProposalState.OFFERED, ProposalState.EXPIRED, ProposalState.FAILED}
    ),
    ProposalState.OFFERED: frozenset(
        {
            ProposalState.COUNTERED,
            ProposalState.ACCEPTED,
            ProposalState.DECLINED,
            ProposalState.EXPIRED,
            ProposalState.FAILED,
        }
    ),
    ProposalState.COUNTERED: frozenset(
        {
            ProposalState.COUNTERED,
            ProposalState.ACCEPTED,
            ProposalState.DECLINED,
            ProposalState.EXPIRED,
            ProposalState.FAILED,
        }
    ),
    ProposalState.ACCEPTED: frozenset(
        {ProposalState.PAID, ProposalState.FAILED}
    ),
    ProposalState.PAID: frozenset(
        {ProposalState.FULFILLING, ProposalState.FAILED}
    ),
    ProposalState.FULFILLING: frozenset(
        {ProposalState.DELIVERED, ProposalState.FAILED}
    ),
    ProposalState.DECLINED: frozenset(),
    ProposalState.EXPIRED: frozenset(),
    ProposalState.DELIVERED: frozenset(),
    ProposalState.FAILED: frozenset(),
}


def _proposal_is_expired(
    proposal: Proposal, now: str | datetime | None = None
) -> bool:
    if proposal.expires_at is None:
        return False
    expires_at = parse_timestamp(
        proposal.expires_at, field_name="proposal expires_at"
    )
    current = (
        datetime.now(timezone.utc)
        if now is None
        else parse_timestamp(now, field_name="transition now")
    )
    return current >= expires_at


def can_transition_proposal(
    current: ProposalState | str, target: ProposalState | str
) -> bool:
    try:
        current_state = ProposalState(current)
        target_state = ProposalState(target)
    except (TypeError, ValueError):
        return False
    return (
        current_state == target_state
        or target_state in ALLOWED_PROPOSAL_TRANSITIONS[current_state]
    )


def transition_proposal(
    proposal: Proposal,
    target: ProposalState | str,
    *,
    expected_revision: int | None = None,
    now: str | datetime | None = None,
) -> Proposal:
    """Apply a checked transition with optimistic revision protection.

    Repeating a transition already applied is idempotent and returns the same
    immutable proposal. Every real transition increments ``revision``.
    """

    if not isinstance(proposal, Proposal):
        raise ContractError("proposal must be a Proposal")
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ProposalTransitionError("expected_revision must be an integer")
        if expected_revision != proposal.revision:
            raise ProposalTransitionError("proposal revision conflict")
    try:
        target_state = ProposalState(target)
    except (TypeError, ValueError) as exc:
        raise ProposalTransitionError("unknown proposal state") from exc
    if target_state == proposal.state:
        return proposal
    if target_state not in ALLOWED_PROPOSAL_TRANSITIONS[proposal.state]:
        raise ProposalTransitionError(
            f"cannot transition proposal from {proposal.state.value} "
            f"to {target_state.value}"
        )
    if target_state in {ProposalState.OFFERED, ProposalState.ACCEPTED}:
        try:
            if _proposal_is_expired(proposal, now):
                raise ProposalTransitionError("expired proposal cannot advance")
        except ContractError as exc:
            if isinstance(exc, ProposalTransitionError):
                raise
            raise ProposalTransitionError("invalid proposal expiry") from exc
    return replace(
        proposal,
        state=target_state,
        revision=proposal.revision + 1,
    )


def create_proposal(
    *,
    sku: ServiceSKU,
    policy: CommercialPolicy,
    seller_agent_url: str,
    buyer_need: BuyerNeed,
    problem_observed: str,
    price_usdc: Decimal | int | str | None = None,
    delivery_seconds: int | None = None,
    offered_outcome: str | None = None,
    expires_at: str | datetime | None = None,
    context: PolicyContext | None = None,
) -> Proposal:
    """Create a deterministic draft after budget and policy validation."""

    if not isinstance(sku, ServiceSKU):
        raise ContractError("sku must be a ServiceSKU")
    if not isinstance(policy, CommercialPolicy):
        raise ContractError("policy must be a CommercialPolicy")
    if not isinstance(buyer_need, BuyerNeed):
        raise ContractError("buyer_need must be a BuyerNeed")
    if not isinstance(seller_agent_url, str) or not isinstance(problem_observed, str):
        raise ContractError("seller URL and observed problem must be text")
    if offered_outcome is not None and not isinstance(offered_outcome, str):
        raise ContractError("offered outcome must be text")
    seller_url = seller_agent_url.strip()
    problem = problem_observed.strip()
    outcome = (sku.outcome if offered_outcome is None else offered_outcome).strip()
    if not seller_url or not problem or not outcome:
        raise ContractError("seller URL, observed problem, and outcome are required")
    try:
        parsed_seller = urlsplit(seller_url)
        seller_port = parsed_seller.port
    except ValueError as exc:
        raise ContractError("invalid seller agent URL") from exc
    if (
        parsed_seller.scheme.lower() not in {"http", "https"}
        or not parsed_seller.hostname
        or parsed_seller.username is not None
        or parsed_seller.password is not None
        or (seller_port is not None and not 1 <= seller_port <= 65535)
    ):
        raise ContractError("seller agent URL must be absolute safe HTTP(S)")
    if outcome != sku.outcome:
        raise ContractError("proposal outcome must match the authorized SKU outcome")
    if isinstance(price_usdc, float):
        raise ContractError("binary float is not allowed for USDC")
    price = sku.base_price_usdc if price_usdc is None else usdc(price_usdc)
    if price > buyer_need.maximum_price_usdc:
        raise ContractError("proposal exceeds buyer maximum price")
    selected_delivery = (
        sku.maximum_latency_seconds
        if delivery_seconds is None
        else delivery_seconds
    )
    if isinstance(selected_delivery, bool) or not isinstance(selected_delivery, int):
        raise ContractError("delivery_seconds must be an integer")
    selected_expiry = expires_at if expires_at is not None else buyer_need.expires_at
    expiry_text = (
        None
        if selected_expiry is None
        else canonical_timestamp(selected_expiry)
    )
    if expiry_text is not None and buyer_need.expires_at is not None:
        if parse_timestamp(
            expiry_text, field_name="proposal expires_at"
        ) > parse_timestamp(
            buyer_need.expires_at, field_name="buyer need expires_at"
        ):
            raise ContractError("proposal expiry exceeds buyer need expiry")
    proposal_id = stable_id(
        "proposal",
        seller_url,
        buyer_need.buyer_agent_url,
        buyer_need.need_id,
        sku.sku_id,
        problem,
        outcome,
        usdc_text(price),
        selected_delivery,
        canonical_json(sku.acceptance_criteria),
        expiry_text or "",
    )
    proposal = Proposal(
        proposal_id=proposal_id,
        seller_agent_url=seller_url,
        buyer_agent_url=buyer_need.buyer_agent_url,
        sku_id=sku.sku_id,
        problem_observed=problem,
        offered_outcome=outcome,
        price_usdc=price,
        delivery_seconds=selected_delivery,
        buyer_need_id=buyer_need.need_id,
        acceptance_criteria=sku.acceptance_criteria,
        expires_at=expiry_text,
    )
    require_policy_approval(
        policy,
        sku,
        proposal,
        context=context or PolicyContext(reserving_new_proposal=True),
        reserving_new_proposal=True,
    )
    return proposal
