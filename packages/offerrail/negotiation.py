"""Bounded negotiation that cannot override owner commercial policy."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Iterable

from autonomerce.contracts import (
    CommercialPolicy,
    ContractError,
    NegotiationDecision,
    Proposal,
    ProposalState,
    ServiceSKU,
    usdc,
)

from .policy import PolicyContext, evaluate_commercial_policy


def _reject(
    proposal: Proposal,
    policy: CommercialPolicy,
    reason_code: str,
    explanation: str,
) -> NegotiationDecision:
    return NegotiationDecision(
        accepted=False,
        reason_code=reason_code,
        proposal=proposal,
        policy_id=policy.policy_id,
        explanation=explanation,
    )


def _criteria(values: Iterable[object]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ContractError("acceptance criteria must be an iterable of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ContractError("acceptance criteria must be strings")
        text = value.strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return tuple(normalized)


def negotiate_counteroffer(
    proposal: Proposal,
    sku: ServiceSKU,
    policy: CommercialPolicy,
    *,
    requested_price_usdc: Decimal | int | str | None = None,
    requested_delivery_seconds: int | None = None,
    requested_outcome: str | None = None,
    requested_acceptance_criteria: Iterable[object] | None = None,
    buyer_maximum_price_usdc: Decimal | int | str | None = None,
    context: PolicyContext | None = None,
) -> NegotiationDecision:
    """Return an immutable counter revision only when every bound passes.

    The deterministic lane intentionally supports only fields represented by the
    shared ``Proposal`` contract. Criteria may be strengthened but not removed,
    and the outcome may not be changed into an unapproved service.
    """

    if not isinstance(proposal, Proposal):
        raise ContractError("proposal must be a Proposal")
    if not isinstance(sku, ServiceSKU):
        raise ContractError("sku must be a ServiceSKU")
    if not isinstance(policy, CommercialPolicy):
        raise ContractError("policy must be a CommercialPolicy")
    if proposal.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
        return _reject(
            proposal,
            policy,
            "proposal_not_negotiable",
            "Only offered or countered proposals can be negotiated.",
        )
    try:
        if isinstance(requested_price_usdc, float):
            raise ContractError("binary float is not allowed for USDC")
        price = (
            proposal.price_usdc
            if requested_price_usdc is None
            else usdc(requested_price_usdc)
        )
    except ContractError:
        return _reject(
            proposal,
            policy,
            "invalid_price",
            "The requested price is not a valid USDC amount.",
        )
    if buyer_maximum_price_usdc is not None:
        try:
            if isinstance(buyer_maximum_price_usdc, float):
                raise ContractError("binary float is not allowed for USDC")
            buyer_maximum = usdc(buyer_maximum_price_usdc)
        except ContractError:
            return _reject(
                proposal,
                policy,
                "invalid_buyer_price_limit",
                "The buyer price limit is not a valid USDC amount.",
            )
        if price > buyer_maximum:
            return _reject(
                proposal,
                policy,
                "buyer_price_limit_exceeded",
                "The requested price exceeds the buyer's declared limit.",
            )

    delivery = (
        proposal.delivery_seconds
        if requested_delivery_seconds is None
        else requested_delivery_seconds
    )
    if isinstance(delivery, bool) or not isinstance(delivery, int) or delivery < 1:
        return _reject(
            proposal,
            policy,
            "invalid_delivery_seconds",
            "Delivery time must be a positive integer.",
        )
    outcome = (
        proposal.offered_outcome
        if requested_outcome is None
        else str(requested_outcome).strip()
    )
    if not outcome or outcome not in {proposal.offered_outcome, sku.outcome}:
        return _reject(
            proposal,
            policy,
            "scope_change_not_authorized",
            "The requested outcome is outside the authorized SKU scope.",
        )

    try:
        criteria = (
            proposal.acceptance_criteria
            if requested_acceptance_criteria is None
            else _criteria(requested_acceptance_criteria)
        )
    except ContractError:
        return _reject(
            proposal,
            policy,
            "invalid_acceptance_criteria",
            "Acceptance criteria must be non-empty strings.",
        )
    required_criteria = set(proposal.acceptance_criteria) | set(
        sku.acceptance_criteria
    )
    if not required_criteria.issubset(criteria):
        return _reject(
            proposal,
            policy,
            "acceptance_criteria_weakened",
            "A counteroffer cannot remove existing acceptance criteria.",
        )

    candidate = replace(
        proposal,
        price_usdc=price,
        delivery_seconds=delivery,
        offered_outcome=outcome,
        acceptance_criteria=criteria,
        state=ProposalState.COUNTERED,
        revision=proposal.revision + 1,
    )
    evaluation = evaluate_commercial_policy(
        policy,
        sku,
        candidate,
        context=context or PolicyContext(reserving_new_proposal=False),
        reserving_new_proposal=False,
    )
    if not evaluation.allowed:
        return _reject(
            proposal,
            policy,
            evaluation.reason_code,
            "Counteroffer denied by deterministic policy: "
            + ", ".join(evaluation.reason_codes),
        )
    return NegotiationDecision(
        accepted=True,
        reason_code="within_policy",
        proposal=candidate,
        policy_id=policy.policy_id,
        explanation="Counteroffer is within deterministic commercial bounds.",
    )


evaluate_counteroffer = negotiate_counteroffer
bounded_negotiate = negotiate_counteroffer
