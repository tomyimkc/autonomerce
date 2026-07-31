"""Typed decision records emitted by Autonomerce's agent lane."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from autonomerce.contracts import (
    FulfillmentReceipt,
    NegotiationDecision,
    Proposal,
    ServiceSKU,
    usdc,
    usdc_text,
)


def _strings(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


@dataclass(frozen=True)
class DecisionMetadata:
    operation: str
    provider: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {
            "operation": self.operation,
            "provider": self.provider,
            "model": self.model,
        }


@dataclass(frozen=True)
class ProductizationDecision:
    skus: tuple[ServiceSKU, ...]
    summary: str
    reason_codes: tuple[str, ...]
    metadata: DecisionMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _strings(self.reason_codes))
        if not self.skus:
            raise ValueError("productization decision requires at least one SKU")

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata.to_dict(),
            "summary": self.summary,
            "reasonCodes": list(self.reason_codes),
            "skus": [sku.to_dict() for sku in self.skus],
        }


@dataclass(frozen=True)
class ProspectFitDecision:
    score: int
    recommended: bool
    reason_codes: tuple[str, ...]
    summary: str
    metadata: DecisionMetadata

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("prospect-fit score must be between 0 and 100")
        object.__setattr__(self, "reason_codes", _strings(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata.to_dict(),
            "score": self.score,
            "recommended": self.recommended,
            "reasonCodes": list(self.reason_codes),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ProposalDecision:
    proposal: Proposal
    reason_codes: tuple[str, ...]
    summary: str
    metadata: DecisionMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _strings(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata.to_dict(),
            "summary": self.summary,
            "reasonCodes": list(self.reason_codes),
            "proposal": self.proposal.to_dict(),
        }


class NegotiationAction(str, Enum):
    ACCEPT = "accept"
    COUNTER = "counter"
    DECLINE = "decline"


@dataclass(frozen=True)
class CounterOffer:
    price_usdc: Decimal
    delivery_seconds: int
    requested_outcome: str | None = None
    acceptance_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "price_usdc", usdc(self.price_usdc))
        object.__setattr__(
            self, "acceptance_criteria", _strings(self.acceptance_criteria)
        )
        if self.delivery_seconds < 1:
            raise ValueError("counter-offer delivery_seconds must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "priceUsdc": usdc_text(self.price_usdc),
            "deliverySeconds": self.delivery_seconds,
            "requestedOutcome": self.requested_outcome,
            "acceptanceCriteria": list(self.acceptance_criteria),
        }


@dataclass(frozen=True)
class NegotiationRecommendation:
    action: NegotiationAction
    decision: NegotiationDecision
    reason_codes: tuple[str, ...]
    summary: str
    metadata: DecisionMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _strings(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata.to_dict(),
            "action": self.action.value,
            "accepted": self.decision.accepted,
            "policyId": self.decision.policy_id,
            "reasonCode": self.decision.reason_code,
            "reasonCodes": list(self.reason_codes),
            "summary": self.summary,
            "proposal": self.decision.proposal.to_dict(),
        }


@dataclass(frozen=True)
class DeliveryValidationDecision:
    accepted: bool
    receipt: FulfillmentReceipt
    reason_codes: tuple[str, ...]
    summary: str
    schema_errors: tuple[str, ...]
    metadata: DecisionMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _strings(self.reason_codes))
        object.__setattr__(self, "schema_errors", _strings(self.schema_errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata.to_dict(),
            "accepted": self.accepted,
            "summary": self.summary,
            "reasonCodes": list(self.reason_codes),
            "schemaErrors": list(self.schema_errors),
            "receipt": {
                "fulfillmentId": self.receipt.fulfillment_id,
                "proposalId": self.receipt.proposal_id,
                "paymentId": self.receipt.payment_id,
                "sellerAgentUrl": self.receipt.seller_agent_url,
                "artifactHash": self.receipt.artifact_hash,
                "accepted": self.receipt.accepted,
                "validator": self.receipt.validator,
                "acceptanceResults": dict(self.receipt.acceptance_results),
                "deliveredAt": self.receipt.delivered_at,
                "detail": dict(self.receipt.detail),
            },
        }
