"""Deterministic need/capability matching for opted-in A2A sales."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable

from autonomerce.contracts import BuyerNeed, CapabilityDescriptor, ServiceSKU


_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)


def _tokens(*values: object) -> set[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, (tuple, list, set)):
            result.update(_tokens(*value))
        else:
            result.update(token.casefold() for token in _TOKEN.findall(str(value)))
    return result


@dataclass(frozen=True)
class NeedCapabilityMatch:
    need_id: str
    capability_id: str
    sku_id: str | None
    eligible: bool
    score: Decimal
    reason_codes: tuple[str, ...]
    matched_tags: tuple[str, ...] = ()
    token_overlap: tuple[str, ...] = ()


def match_need_to_capability(
    need: BuyerNeed,
    capability: CapabilityDescriptor,
    sku: ServiceSKU | None = None,
) -> NeedCapabilityMatch:
    """Score a match while treating price, tags, and required inputs as gates."""

    reasons: list[str] = []
    required_tags = {tag.casefold() for tag in need.required_tags}
    capability_tags = {tag.casefold() for tag in capability.tags}
    matched_tags = tuple(sorted(required_tags.intersection(capability_tags)))

    if required_tags and not required_tags.issubset(capability_tags):
        reasons.append("missing_required_tags")

    if sku is not None:
        if sku.capability_id != capability.capability_id:
            reasons.append("sku_capability_mismatch")
        if sku.base_price_usdc > need.maximum_price_usdc:
            reasons.append("price_exceeds_buyer_limit")
        required_inputs = sku.input_schema.get("required", ())
        if isinstance(required_inputs, (list, tuple)):
            missing_inputs = [
                str(key) for key in required_inputs if key not in need.input_payload
            ]
            if missing_inputs:
                reasons.append("missing_required_inputs")

    need_tokens = _tokens(need.desired_outcome, need.required_tags)
    capability_tokens = _tokens(
        capability.name,
        capability.description,
        capability.tags,
        sku.name if sku else "",
        sku.outcome if sku else "",
    )
    overlap = tuple(sorted(need_tokens.intersection(capability_tokens)))
    if not overlap and not matched_tags:
        reasons.append("no_capability_signal")

    union = need_tokens.union(capability_tokens)
    lexical = (
        Decimal(len(overlap)) / Decimal(len(union))
        if union
        else Decimal("0")
    )
    tag_score = (
        Decimal(len(matched_tags)) / Decimal(len(required_tags))
        if required_tags
        else Decimal("0")
    )
    score = (lexical * Decimal("0.7") + tag_score * Decimal("0.3")).quantize(
        Decimal("0.0001")
    )

    return NeedCapabilityMatch(
        need_id=need.need_id,
        capability_id=capability.capability_id,
        sku_id=sku.sku_id if sku else None,
        eligible=not reasons,
        score=score,
        reason_codes=tuple(reasons) or ("matched",),
        matched_tags=matched_tags,
        token_overlap=overlap,
    )


def match_need_to_sku(
    need: BuyerNeed,
    sku: ServiceSKU,
    capability: CapabilityDescriptor,
) -> NeedCapabilityMatch:
    return match_need_to_capability(need, capability, sku)


def rank_matches(
    need: BuyerNeed,
    candidates: Iterable[tuple[ServiceSKU, CapabilityDescriptor]],
) -> tuple[NeedCapabilityMatch, ...]:
    """Return eligible matches first, then deterministic score/ID ordering."""

    matches = [
        match_need_to_sku(need, sku, capability)
        for sku, capability in candidates
    ]
    return tuple(
        sorted(
            matches,
            key=lambda match: (
                not match.eligible,
                -match.score,
                match.sku_id or "",
                match.capability_id,
            ),
        )
    )
