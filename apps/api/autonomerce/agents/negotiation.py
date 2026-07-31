"""Gemini-recommended, deterministically bounded commercial negotiation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any, Callable
from urllib.parse import urlparse

from autonomerce.contracts import (
    CommercialPolicy,
    NegotiationDecision,
    Proposal,
    ProposalState,
    usdc,
    usdc_text,
)

from .base import (
    AgentDecisionError,
    DecisionProvider,
    DecisionRequest,
    normalize_decision_json,
    provider_identity,
)
from .models import (
    CounterOffer,
    DecisionMetadata,
    NegotiationAction,
    NegotiationRecommendation,
)
from .providers import OfflineDecisionProvider


_NEGOTIATION_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["action", "summary", "reasonCodes"],
    "properties": {
        "action": {"type": "string", "enum": ["accept", "counter", "decline"]},
        "suggestedPriceUsdc": {"type": ["string", "null"]},
        "suggestedDeliverySeconds": {"type": ["integer", "null"], "minimum": 1},
        "summary": {"type": "string"},
        "reasonCodes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def _codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        str(item).strip().upper().replace(" ", "_")
        for item in value
        if str(item).strip()
    )


def _host_matches(host: str, configured: str) -> bool:
    candidate = configured.strip().lower().rstrip(".")
    return bool(candidate) and (host == candidate or host.endswith(f".{candidate}"))


def _policy_host_denial(proposal: Proposal, policy: CommercialPolicy) -> str | None:
    host = (urlparse(proposal.buyer_agent_url).hostname or "").lower().rstrip(".")
    if not host:
        return "INVALID_BUYER_URL"
    if any(_host_matches(host, entry) for entry in policy.blocked_buyer_hosts):
        return "BUYER_HOST_BLOCKED"
    if policy.allowed_buyer_hosts and not any(
        _host_matches(host, entry) for entry in policy.allowed_buyer_hosts
    ):
        return "BUYER_HOST_NOT_ALLOWED"
    return None


def _parse_expiry(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class NegotiationRecommender:
    """Let a provider choose only among actions authorized by deterministic code."""

    def __init__(
        self,
        provider: DecisionProvider | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider or OfflineDecisionProvider()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def recommend(
        self,
        proposal: Proposal,
        counter: CounterOffer,
        policy: CommercialPolicy,
        *,
        list_price_usdc: Decimal | int | str | None = None,
        minimum_delivery_seconds: int | None = None,
        available_capacity: bool = True,
        now: datetime | None = None,
    ) -> NegotiationRecommendation:
        if proposal.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
            raise AgentDecisionError("proposal is not open for negotiation")
        if minimum_delivery_seconds is None:
            minimum_delivery_seconds = proposal.delivery_seconds
        if minimum_delivery_seconds < 1:
            raise ValueError("minimum_delivery_seconds must be positive")

        list_price = usdc(
            proposal.price_usdc if list_price_usdc is None else list_price_usdc
        )
        discount_floor = (
            list_price * (Decimal("1") - policy.maximum_discount_fraction)
        ).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
        price_floor = max(policy.minimum_price_usdc, discount_floor)
        price_ceiling = policy.maximum_price_usdc

        hard_declines: list[str] = []
        counter_reasons: list[str] = []
        if not policy.unattended:
            hard_declines.append("POLICY_REQUIRES_ATTENDED_MODE")
        host_denial = _policy_host_denial(proposal, policy)
        if host_denial:
            hard_declines.append(host_denial)
        if not available_capacity:
            hard_declines.append("NO_AVAILABLE_CAPACITY")
        if proposal.expires_at:
            try:
                current = (now or self._clock()).astimezone(timezone.utc)
                if current >= _parse_expiry(proposal.expires_at):
                    hard_declines.append("PROPOSAL_EXPIRED")
            except (TypeError, ValueError):
                hard_declines.append("INVALID_PROPOSAL_EXPIRY")
        if counter.requested_outcome and (
            counter.requested_outcome.strip() != proposal.offered_outcome
        ):
            hard_declines.append("SCOPE_CHANGE_REQUIRES_NEW_PROPOSAL")
        extra_criteria = set(counter.acceptance_criteria) - set(
            proposal.acceptance_criteria
        )
        if extra_criteria:
            hard_declines.append("NEW_UNBOUNDED_TERM")

        if counter.price_usdc < price_floor:
            counter_reasons.append("PRICE_BELOW_DISCOUNT_FLOOR")
        if counter.price_usdc > price_ceiling:
            counter_reasons.append("PRICE_ABOVE_POLICY_MAXIMUM")
        if counter.delivery_seconds < minimum_delivery_seconds:
            counter_reasons.append("DELIVERY_BELOW_SAFE_MINIMUM")

        if hard_declines:
            allowed_actions = (NegotiationAction.DECLINE,)
            default_action = NegotiationAction.DECLINE
        elif counter_reasons:
            allowed_actions = (NegotiationAction.COUNTER, NegotiationAction.DECLINE)
            default_action = NegotiationAction.COUNTER
        else:
            allowed_actions = (
                NegotiationAction.ACCEPT,
                NegotiationAction.COUNTER,
                NegotiationAction.DECLINE,
            )
            default_action = NegotiationAction.ACCEPT

        request = DecisionRequest(
            operation="recommend_negotiation",
            instruction=(
                "Recommend accept, counter, or decline using only the supplied allowed "
                "actions. Never widen scope or exceed deterministic price, delivery, "
                "capacity, buyer, or expiry bounds."
            ),
            payload={
                "proposal": proposal.to_dict(),
                "counterOffer": counter.to_dict(),
                "policyId": policy.policy_id,
                "priceFloorUsdc": usdc_text(price_floor),
                "priceCeilingUsdc": usdc_text(price_ceiling),
                "minimumDeliverySeconds": minimum_delivery_seconds,
                "allowedActions": [action.value for action in allowed_actions],
                "hardDenyReasons": hard_declines,
                "counterReasons": counter_reasons,
            },
            response_schema=_NEGOTIATION_SCHEMA,
        )
        raw = normalize_decision_json(self._provider.generate_json(request))
        try:
            requested_action = NegotiationAction(
                str(raw.get("action", default_action.value)).strip().lower()
            )
        except ValueError:
            requested_action = default_action

        reason_codes = [
            *hard_declines,
            *counter_reasons,
            *_codes(raw.get("reasonCodes")),
        ]
        if requested_action not in allowed_actions:
            action = default_action
            reason_codes.append("PROVIDER_ACTION_OVERRIDDEN")
        else:
            action = requested_action

        if action is NegotiationAction.ACCEPT:
            next_price = counter.price_usdc
            next_delivery = counter.delivery_seconds
            state = ProposalState.ACCEPTED
        elif action is NegotiationAction.COUNTER:
            suggested_price = raw.get("suggestedPriceUsdc")
            if suggested_price is None:
                next_price = min(max(counter.price_usdc, price_floor), price_ceiling)
            else:
                try:
                    recommended_price = usdc(suggested_price)
                except Exception:
                    recommended_price = min(
                        max(counter.price_usdc, price_floor), price_ceiling
                    )
                    reason_codes.append("INVALID_PROVIDER_PRICE_IGNORED")
                next_price = min(max(recommended_price, price_floor), price_ceiling)

            suggested_delivery = raw.get("suggestedDeliverySeconds")
            try:
                recommended_delivery = int(suggested_delivery)
            except (TypeError, ValueError):
                recommended_delivery = counter.delivery_seconds
            next_delivery = max(recommended_delivery, minimum_delivery_seconds)
            state = ProposalState.COUNTERED
        else:
            next_price = proposal.price_usdc
            next_delivery = proposal.delivery_seconds
            state = ProposalState.DECLINED

        next_proposal = replace(
            proposal,
            price_usdc=next_price,
            delivery_seconds=next_delivery,
            acceptance_criteria=proposal.acceptance_criteria,
            state=state,
            revision=proposal.revision + 1,
        )
        deduplicated_reasons = tuple(dict.fromkeys(reason_codes or ["NO_SAFE_ACTION"]))
        primary_reason = deduplicated_reasons[0]
        summary = str(raw.get("summary") or "Negotiation decision completed.")[:500]
        shared_decision = NegotiationDecision(
            accepted=action is NegotiationAction.ACCEPT,
            reason_code=primary_reason,
            proposal=next_proposal,
            policy_id=policy.policy_id,
            explanation=summary,
        )
        provider_name, model_name = provider_identity(self._provider)
        return NegotiationRecommendation(
            action=action,
            decision=shared_decision,
            reason_codes=deduplicated_reasons,
            summary=summary,
            metadata=DecisionMetadata(
                operation=request.operation,
                provider=provider_name,
                model=model_name,
            ),
        )
