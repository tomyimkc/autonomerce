"""Opt-in prospect-fit scoring with deterministic commercial hard gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from autonomerce.contracts import (
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    ServiceSKU,
    usdc_text,
)

from .base import (
    DecisionProvider,
    DecisionRequest,
    ProviderResponseError,
    normalize_decision_json,
    provider_identity,
)
from .models import DecisionMetadata, ProspectFitDecision
from .providers import OfflineDecisionProvider


_FIT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["score", "recommended", "reasonCodes", "summary"],
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "recommended": {"type": "boolean"},
        "reasonCodes": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
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


def _buyer_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().rstrip(".")


class ProspectFitScorer:
    """Score relevance only after explicit opt-in and deterministic host/budget checks."""

    def __init__(
        self,
        provider: DecisionProvider | None = None,
        *,
        minimum_score: int = 60,
    ) -> None:
        if not 0 <= minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100")
        self._provider = provider or OfflineDecisionProvider()
        self._minimum_score = minimum_score

    def score(
        self,
        sku: ServiceSKU,
        need: BuyerNeed,
        *,
        opted_in: bool,
        capability: CapabilityDescriptor | None = None,
        policy: CommercialPolicy | None = None,
    ) -> ProspectFitDecision:
        hard_reasons: list[str] = []
        if not opted_in:
            hard_reasons.append("NOT_OPTED_IN")

        host = _buyer_host(need.buyer_agent_url)
        if not host:
            hard_reasons.append("INVALID_BUYER_URL")
        if policy is not None and host:
            if any(_host_matches(host, entry) for entry in policy.blocked_buyer_hosts):
                hard_reasons.append("BUYER_HOST_BLOCKED")
            if policy.allowed_buyer_hosts and not any(
                _host_matches(host, entry) for entry in policy.allowed_buyer_hosts
            ):
                hard_reasons.append("BUYER_HOST_NOT_ALLOWED")
        if need.maximum_price_usdc < sku.base_price_usdc:
            hard_reasons.append("BUDGET_BELOW_SKU_PRICE")

        request = DecisionRequest(
            operation="score_prospect_fit",
            instruction=(
                "Score an opted-in buyer need against a published service SKU. Treat the "
                "deterministic deny reasons as absolute and return a compact JSON decision."
            ),
            payload={
                "sku": {
                    "skuId": sku.sku_id,
                    "name": sku.name,
                    "outcome": sku.outcome,
                    "basePriceUsdc": usdc_text(sku.base_price_usdc),
                    "inputSchema": dict(sku.input_schema),
                    "outputSchema": dict(sku.output_schema),
                },
                "need": {
                    "needId": need.need_id,
                    "buyerAgentUrl": need.buyer_agent_url,
                    "desiredOutcome": need.desired_outcome,
                    "maximumPriceUsdc": usdc_text(need.maximum_price_usdc),
                    "requiredTags": list(need.required_tags),
                    "inputPayloadKeys": sorted(str(key) for key in need.input_payload),
                },
                "capabilityTags": list(capability.tags if capability else ()),
                "optedIn": opted_in,
                "hardDenyReasons": hard_reasons,
                "minimumScore": self._minimum_score,
            },
            response_schema=_FIT_SCHEMA,
        )
        raw = normalize_decision_json(self._provider.generate_json(request))
        try:
            score = min(max(int(raw.get("score", 0)), 0), 100)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError("provider returned an invalid fit score") from exc

        provider_recommended = bool(raw.get("recommended", False))
        if hard_reasons:
            score = 0
            recommended = False
        else:
            recommended = provider_recommended and score >= self._minimum_score

        reason_codes = tuple(
            dict.fromkeys([*hard_reasons, *_codes(raw.get("reasonCodes"))])
        )
        provider_name, model_name = provider_identity(self._provider)
        return ProspectFitDecision(
            score=score,
            recommended=recommended,
            reason_codes=reason_codes,
            summary=str(raw.get("summary") or "Prospect fit scored.")[:500],
            metadata=DecisionMetadata(
                operation=request.operation,
                provider=provider_name,
                model=model_name,
            ),
        )
