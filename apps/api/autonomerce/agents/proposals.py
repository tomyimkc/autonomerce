"""Machine-readable proposal drafting constrained to a published SKU."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from autonomerce.contracts import (
    BuyerNeed,
    CommercialPolicy,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
    usdc_text,
)

from .base import (
    AgentDecisionError,
    DecisionProvider,
    DecisionRequest,
    normalize_decision_json,
    provider_identity,
)
from .models import DecisionMetadata, ProposalDecision, ProspectFitDecision
from .providers import OfflineDecisionProvider


_PROPOSAL_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": [
        "problemObserved",
        "offeredOutcome",
        "summary",
        "reasonCodes",
    ],
    "properties": {
        "problemObserved": {"type": "string"},
        "offeredOutcome": {"type": "string"},
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


class ProposalWriter:
    """Draft relevant offers without allowing a model to invent commercial terms."""

    def __init__(self, provider: DecisionProvider | None = None) -> None:
        self._provider = provider or OfflineDecisionProvider()

    def write(
        self,
        *,
        seller_agent_url: str,
        sku: ServiceSKU,
        need: BuyerNeed,
        fit: ProspectFitDecision,
        policy: CommercialPolicy,
        expires_at: str | None = None,
    ) -> ProposalDecision:
        if not fit.recommended:
            raise AgentDecisionError("cannot draft a proposal for a denied prospect fit")
        if not seller_agent_url.strip():
            raise AgentDecisionError("seller_agent_url is required")
        if not (
            policy.minimum_price_usdc
            <= sku.base_price_usdc
            <= policy.maximum_price_usdc
        ):
            raise AgentDecisionError("SKU price is outside commercial policy")
        if sku.base_price_usdc > need.maximum_price_usdc:
            raise AgentDecisionError("SKU price exceeds buyer budget")
        buyer_host = (
            urlparse(need.buyer_agent_url).hostname or ""
        ).lower().rstrip(".")
        if not buyer_host:
            raise AgentDecisionError("buyer_agent_url has no valid host")
        if any(
            _host_matches(buyer_host, entry)
            for entry in policy.blocked_buyer_hosts
        ):
            raise AgentDecisionError("buyer host is blocked by commercial policy")
        if policy.allowed_buyer_hosts and not any(
            _host_matches(buyer_host, entry)
            for entry in policy.allowed_buyer_hosts
        ):
            raise AgentDecisionError("buyer host is not allowed by commercial policy")

        request = DecisionRequest(
            operation="write_proposal",
            instruction=(
                "Draft a concise machine-readable sales proposal. Describe relevance, but "
                "do not invent price, scope, acceptance terms, delivery time, or facts not "
                "present in the supplied need and SKU."
            ),
            payload={
                "sellerAgentUrl": seller_agent_url,
                "sku": sku.to_dict(),
                "need": {
                    "needId": need.need_id,
                    "buyerAgentUrl": need.buyer_agent_url,
                    "desiredOutcome": need.desired_outcome,
                    "maximumPriceUsdc": usdc_text(need.maximum_price_usdc),
                    "requiredTags": list(need.required_tags),
                },
                "fit": fit.to_dict(),
            },
            response_schema=_PROPOSAL_SCHEMA,
        )
        raw = normalize_decision_json(self._provider.generate_json(request))
        problem_observed = str(
            raw.get("problemObserved") or f"Buyer requested: {need.desired_outcome}"
        ).strip()[:500]
        if not problem_observed:
            problem_observed = f"Buyer requested: {need.desired_outcome}"[:500]

        proposal_id = stable_id(
            "proposal",
            seller_agent_url,
            need.buyer_agent_url,
            sku.sku_id,
            need.need_id,
            usdc_text(sku.base_price_usdc),
        )
        proposal = Proposal(
            proposal_id=proposal_id,
            seller_agent_url=seller_agent_url.strip(),
            buyer_agent_url=need.buyer_agent_url,
            sku_id=sku.sku_id,
            problem_observed=problem_observed,
            # The published SKU is the authority; provider prose cannot widen scope.
            offered_outcome=sku.outcome,
            price_usdc=sku.base_price_usdc,
            delivery_seconds=sku.maximum_latency_seconds,
            buyer_need_id=need.need_id,
            acceptance_criteria=sku.acceptance_criteria,
            expires_at=expires_at if expires_at is not None else need.expires_at,
            state=ProposalState.OFFERED,
            revision=1,
        )
        provider_name, model_name = provider_identity(self._provider)
        return ProposalDecision(
            proposal=proposal,
            reason_codes=tuple(
                dict.fromkeys([*_codes(raw.get("reasonCodes")), "POLICY_BOUND"])
            ),
            summary=str(raw.get("summary") or "Proposal drafted.")[:500],
            metadata=DecisionMetadata(
                operation=request.operation,
                provider=provider_name,
                model=model_name,
            ),
        )
