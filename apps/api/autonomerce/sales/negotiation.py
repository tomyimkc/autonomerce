"""Bounded negotiation orchestration with deterministic policy authorization."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit

from autonomerce.contracts import (
    CommercialPolicy,
    ContractError,
    NegotiationDecision,
    Proposal,
    ProposalState,
    usdc,
)


class NegotiationError(ContractError):
    """Negotiation input or transition is invalid."""


class NegotiationAction(str, Enum):
    ACCEPT = "accept"
    COUNTER = "counter"
    DECLINE = "decline"


@dataclass(frozen=True)
class BuyerResponse:
    action: NegotiationAction
    price_usdc: Decimal | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        try:
            action = (
                self.action
                if isinstance(self.action, NegotiationAction)
                else NegotiationAction(str(self.action))
            )
        except ValueError as exc:
            raise NegotiationError("unsupported buyer negotiation action") from exc
        object.__setattr__(self, "action", action)
        if self.price_usdc is not None:
            object.__setattr__(self, "price_usdc", usdc(self.price_usdc))
        if action == NegotiationAction.COUNTER and self.price_usdc is None:
            raise NegotiationError("counter responses require a price")


@dataclass(frozen=True)
class NegotiationRecommendation:
    action: NegotiationAction
    price_usdc: Decimal | None = None
    explanation: str = ""

    def __post_init__(self) -> None:
        try:
            action = (
                self.action
                if isinstance(self.action, NegotiationAction)
                else NegotiationAction(str(self.action))
            )
        except ValueError as exc:
            raise NegotiationError("unsupported negotiation recommendation") from exc
        object.__setattr__(self, "action", action)
        if self.price_usdc is not None:
            object.__setattr__(self, "price_usdc", usdc(self.price_usdc))


class NegotiationAdvisor(Protocol):
    """Optional Gemini-facing interface; recommendations never authorize action."""

    def recommend(
        self,
        session: "NegotiationSession",
        buyer_response: BuyerResponse,
    ) -> NegotiationRecommendation: ...


@dataclass
class NegotiationSession:
    initial_proposal: Proposal
    current_proposal: Proposal
    rounds: int = 0
    decisions: list[NegotiationDecision] = field(default_factory=list)


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise NegotiationError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _expired(proposal: Proposal, now: datetime) -> bool:
    if not proposal.expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(proposal.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NegotiationError("proposal expiry is invalid") from exc
    return _utc(now) >= _utc(expiry)


class NegotiationOrchestrator:
    """Apply bounded counteroffers while failing closed outside owner policy."""

    def __init__(
        self,
        *,
        commercial_policy: CommercialPolicy,
        max_rounds: int = 3,
        advisor: NegotiationAdvisor | None = None,
    ) -> None:
        if max_rounds < 1:
            raise NegotiationError("max_rounds must be positive")
        self.commercial_policy = commercial_policy
        self.max_rounds = max_rounds
        self.advisor = advisor

    def start(self, proposal: Proposal) -> NegotiationSession:
        if proposal.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
            raise NegotiationError("negotiation requires an offered proposal")
        return NegotiationSession(proposal, proposal)

    def _decision(
        self,
        session: NegotiationSession,
        *,
        accepted: bool,
        reason_code: str,
        proposal: Proposal,
        explanation: str = "",
    ) -> NegotiationDecision:
        decision = NegotiationDecision(
            accepted=accepted,
            reason_code=reason_code,
            proposal=proposal,
            policy_id=self.commercial_policy.policy_id,
            explanation=explanation,
        )
        session.current_proposal = proposal
        session.decisions.append(decision)
        return decision

    def _buyer_host_allowed(self, proposal: Proposal) -> bool:
        host = (urlsplit(proposal.buyer_agent_url).hostname or "").casefold()
        allowed = {
            value.casefold() for value in self.commercial_policy.allowed_buyer_hosts
        }
        blocked = {
            value.casefold() for value in self.commercial_policy.blocked_buyer_hosts
        }
        return bool(host) and host not in blocked and (not allowed or host in allowed)

    def _floor(self, session: NegotiationSession) -> Decimal:
        discounted = session.initial_proposal.price_usdc * (
            Decimal("1") - self.commercial_policy.maximum_discount_fraction
        )
        discounted = discounted.quantize(
            Decimal("0.000001"),
            rounding=ROUND_CEILING,
        )
        return max(self.commercial_policy.minimum_price_usdc, discounted)

    def advance(
        self,
        session: NegotiationSession,
        buyer_response: BuyerResponse,
        *,
        now: datetime | None = None,
    ) -> NegotiationDecision:
        current = session.current_proposal
        if current.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
            raise NegotiationError("proposal is no longer negotiable")
        if not self.commercial_policy.unattended:
            return self._decision(
                session,
                accepted=False,
                reason_code="unattended_sales_disabled",
                proposal=replace(current, state=ProposalState.DECLINED),
            )
        if _expired(current, _utc(now)):
            return self._decision(
                session,
                accepted=False,
                reason_code="proposal_expired",
                proposal=replace(current, state=ProposalState.EXPIRED),
            )
        if not self._buyer_host_allowed(current):
            return self._decision(
                session,
                accepted=False,
                reason_code="buyer_host_not_authorized",
                proposal=replace(current, state=ProposalState.DECLINED),
            )
        if not (
            self.commercial_policy.minimum_price_usdc
            <= current.price_usdc
            <= self.commercial_policy.maximum_price_usdc
        ):
            return self._decision(
                session,
                accepted=False,
                reason_code="current_price_outside_policy",
                proposal=replace(current, state=ProposalState.DECLINED),
            )

        if buyer_response.action == NegotiationAction.DECLINE:
            return self._decision(
                session,
                accepted=False,
                reason_code="buyer_declined",
                proposal=replace(current, state=ProposalState.DECLINED),
                explanation=buyer_response.reason,
            )

        floor = self._floor(session)
        recommendation = (
            self.advisor.recommend(session, buyer_response)
            if self.advisor is not None
            else None
        )

        if buyer_response.action == NegotiationAction.ACCEPT:
            if recommendation and recommendation.action == NegotiationAction.DECLINE:
                return self._decision(
                    session,
                    accepted=False,
                    reason_code="advisor_decline_policy_safe",
                    proposal=replace(current, state=ProposalState.DECLINED),
                    explanation=recommendation.explanation,
                )
            return self._decision(
                session,
                accepted=True,
                reason_code="accepted_at_offered_price",
                proposal=replace(current, state=ProposalState.ACCEPTED),
                explanation=recommendation.explanation if recommendation else "",
            )

        buyer_price = buyer_response.price_usdc
        if buyer_price is None:
            raise NegotiationError("counter response requires a price")
        if buyer_price >= current.price_usdc:
            return self._decision(
                session,
                accepted=True,
                reason_code="accepted_at_offered_price",
                proposal=replace(current, state=ProposalState.ACCEPTED),
            )
        if buyer_price >= floor:
            return self._decision(
                session,
                accepted=True,
                reason_code="accepted_bounded_counter",
                proposal=replace(
                    current,
                    price_usdc=buyer_price,
                    state=ProposalState.ACCEPTED,
                    revision=current.revision + 1,
                ),
            )
        if session.rounds >= self.max_rounds:
            return self._decision(
                session,
                accepted=False,
                reason_code="negotiation_round_limit",
                proposal=replace(current, state=ProposalState.DECLINED),
            )

        counter_price = floor
        if recommendation and recommendation.action == NegotiationAction.COUNTER:
            advised = recommendation.price_usdc
            if advised is not None and floor <= advised <= current.price_usdc:
                counter_price = advised
        session.rounds += 1
        return self._decision(
            session,
            accepted=False,
            reason_code="seller_countered",
            proposal=replace(
                current,
                price_usdc=counter_price,
                state=ProposalState.COUNTERED,
                revision=current.revision + 1,
            ),
            explanation=recommendation.explanation if recommendation else "",
        )

    def evaluate(
        self,
        proposal: Proposal,
        buyer_response: BuyerResponse,
        *,
        now: datetime | None = None,
    ) -> NegotiationDecision:
        """Convenience interface for a one-step negotiation."""

        return self.advance(self.start(proposal), buyer_response, now=now)
