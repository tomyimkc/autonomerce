"""Claim-bounded customer, settlement, revenue, and margin classification.

Owner-provided commercial evidence is immutable and must be independently
verified before it can become an external-customer or user-acquisition claim.
Payment network, confirmation, delivery acceptance, revenue, and margin remain
derived from durable commerce records.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Iterable

from autonomerce.contracts import (
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    usdc,
    usdc_text,
)


_CUSTOMER_ID = re.compile(r"^customer_[0-9a-f]{16,64}$")
_USER_ID = re.compile(r"^user_[0-9a-f]{16,64}$")
_CONSENT_REFERENCE = re.compile(r"^consent_[0-9a-f]{16,64}$")
_EVIDENCE_REFERENCE = re.compile(r"^evidence_[0-9a-f]{16,64}$")
_VERIFIER_REFERENCE = re.compile(r"^verification_[0-9a-f]{16,64}$")
SUPPORTED_MAINNET_CHAINS = frozenset({"BASE"})
SUPPORTED_TESTNET_CHAINS = frozenset(
    {
        "ARC-TESTNET",
        "ARBITRUM-SEPOLIA",
        "BASE-SEPOLIA",
        "ETHEREUM-SEPOLIA",
        "SEPOLIA",
    }
)


class CustomerRelationship(str, Enum):
    """Commercial relationship asserted by the authenticated owner."""

    ARMS_LENGTH = "arms_length"
    RELATED_PARTY = "related_party"
    SELF = "self"


class FundingSource(str, Enum):
    """Who economically funded the settlement."""

    CUSTOMER_FUNDED = "customer_funded"
    FOUNDER_SPONSORED = "founder_sponsored"
    REIMBURSED = "reimbursed"
    UNKNOWN = "unknown"


class SettlementClass(str, Enum):
    """Settlement class derived from a canonical payment record."""

    UNSETTLED = "unsettled"
    OFFLINE_MOCK = "offline_mock"
    TESTNET = "testnet"
    MAINNET = "mainnet"
    UNSUPPORTED = "unsupported"


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} requires a UTC offset")
    return parsed


@dataclass(frozen=True)
class VariableCosts:
    """Explicitly measured per-deal variable costs in USDC-equivalent units."""

    network_fees_usdc: Decimal
    infrastructure_usdc: Decimal
    fulfillment_usdc: Decimal
    other_usdc: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "network_fees_usdc",
            "infrastructure_usdc",
            "fulfillment_usdc",
            "other_usdc",
        ):
            object.__setattr__(self, field_name, usdc(getattr(self, field_name)))

    @property
    def total_usdc(self) -> Decimal:
        return sum(
            (
                self.network_fees_usdc,
                self.infrastructure_usdc,
                self.fulfillment_usdc,
                self.other_usdc,
            ),
            Decimal("0"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "networkFeesUsdc": usdc_text(self.network_fees_usdc),
            "infrastructureUsdc": usdc_text(self.infrastructure_usdc),
            "fulfillmentUsdc": usdc_text(self.fulfillment_usdc),
            "otherUsdc": usdc_text(self.other_usdc),
            "totalUsdc": usdc_text(self.total_usdc),
        }


@dataclass(frozen=True)
class DealEvidence:
    """One verified, complete, append-only commercial record for a proposal."""

    evidence_id: str
    proposal_id: str
    owner_id: str
    customer_relationship: CustomerRelationship
    funding_source: FundingSource
    customer_id: str | None
    user_id: str | None
    consent_reference: str
    evidence_reference: str
    relationship_verified: bool
    verifier_reference: str
    refunds_usdc: Decimal
    refund_window_closed: bool
    refund_window_closed_at: str
    variable_costs: VariableCosts
    costs_measured: bool
    measured_at: str
    recorded_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "refunds_usdc", usdc(self.refunds_usdc))
        required = (
            self.evidence_id,
            self.proposal_id,
            self.owner_id,
            self.consent_reference,
            self.evidence_reference,
            self.verifier_reference,
            self.refund_window_closed_at,
            self.measured_at,
            self.recorded_at,
        )
        if not all(str(item).strip() for item in required):
            raise ValueError("deal evidence requires complete immutable references")
        if not self.relationship_verified:
            raise ValueError("deal evidence requires independent relationship verification")
        if not self.costs_measured:
            raise ValueError("deal evidence requires explicit measured variable costs")
        if not self.refund_window_closed:
            raise ValueError("deal evidence requires a closed refund measurement window")
        if (
            self.customer_relationship is CustomerRelationship.ARMS_LENGTH
            and not self.customer_id
        ):
            raise ValueError("arms-length deal evidence requires a customer identifier")
        for label, identifier, pattern in (
            ("customer", self.customer_id, _CUSTOMER_ID),
            ("user", self.user_id, _USER_ID),
        ):
            if identifier is not None and pattern.fullmatch(identifier) is None:
                raise ValueError(
                    f"{label} identifier must use its hash-shaped typed format"
                )
        for label, reference, pattern in (
            ("consent", self.consent_reference, _CONSENT_REFERENCE),
            ("evidence", self.evidence_reference, _EVIDENCE_REFERENCE),
            ("verifier", self.verifier_reference, _VERIFIER_REFERENCE),
        ):
            if pattern.fullmatch(reference) is None:
                raise ValueError(
                    f"{label} reference must use its hash-shaped typed format"
                )
        _timestamp(
            self.refund_window_closed_at,
            label="deal evidence refund_window_closed_at",
        )
        _timestamp(self.measured_at, label="deal evidence measured_at")
        _timestamp(self.recorded_at, label="deal evidence recorded_at")

    def semantic_key(self) -> tuple[Any, ...]:
        """Content compared for idempotency; excludes server recording time."""

        return (
            self.evidence_id,
            self.proposal_id,
            self.owner_id,
            self.customer_relationship,
            self.funding_source,
            self.customer_id,
            self.user_id,
            self.consent_reference,
            self.evidence_reference,
            self.relationship_verified,
            self.verifier_reference,
            self.refunds_usdc,
            self.refund_window_closed,
            self.refund_window_closed_at,
            self.variable_costs,
            self.costs_measured,
            self.measured_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "proposalId": self.proposal_id,
            "ownerId": self.owner_id,
            "customerRelationship": self.customer_relationship.value,
            "fundingSource": self.funding_source.value,
            "customerId": self.customer_id,
            "userId": self.user_id,
            "consentReference": self.consent_reference,
            "evidenceReference": self.evidence_reference,
            "relationshipVerified": self.relationship_verified,
            "verifierReference": self.verifier_reference,
            "refundsUsdc": usdc_text(self.refunds_usdc),
            "refundWindowClosed": self.refund_window_closed,
            "refundWindowClosedAt": self.refund_window_closed_at,
            "variableCosts": self.variable_costs.to_dict(),
            "costsMeasured": self.costs_measured,
            "measuredAt": self.measured_at,
            "recordedAt": self.recorded_at,
        }


@dataclass(frozen=True)
class DealClassification:
    """Business classification derived from verified evidence and receipts."""

    evidence: DealEvidence
    settlement_class: SettlementClass
    payment_confirmed: bool
    accepted_fulfillment: bool
    external_customer: bool
    counts_as_revenue: bool
    user_acquired: bool
    paid_user: bool
    paid_task: bool
    paid_external_task: bool
    accepted_paid_external_task: bool
    payment_amount_usdc: Decimal
    gross_external_revenue_usdc: Decimal
    refunds_usdc: Decimal
    net_external_revenue_usdc: Decimal
    variable_costs_usdc: Decimal
    excluded_pilot_spend_usdc: Decimal
    gross_margin_usdc: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "settlementClass": self.settlement_class.value,
            "paymentConfirmed": self.payment_confirmed,
            "acceptedFulfillment": self.accepted_fulfillment,
            "externalCustomer": self.external_customer,
            "countsAsRevenue": self.counts_as_revenue,
            "userAcquired": self.user_acquired,
            "paidUser": self.paid_user,
            "paidTask": self.paid_task,
            "paidExternalTask": self.paid_external_task,
            "acceptedPaidExternalTask": self.accepted_paid_external_task,
            "paymentAmountUsdc": usdc_text(self.payment_amount_usdc),
            "grossExternalRevenueUsdc": usdc_text(
                self.gross_external_revenue_usdc
            ),
            "refundsUsdc": usdc_text(self.refunds_usdc),
            "netExternalRevenueUsdc": usdc_text(
                self.net_external_revenue_usdc
            ),
            "variableCostsUsdc": usdc_text(self.variable_costs_usdc),
            "excludedPilotSpendUsdc": usdc_text(
                self.excluded_pilot_spend_usdc
            ),
            "grossMarginUsdc": _decimal_text(self.gross_margin_usdc),
        }


def settlement_class_for_payment(
    payment: PaymentReceipt | None,
    *,
    mocked: bool,
) -> SettlementClass:
    """Classify only explicitly supported chains; unknown networks fail closed."""

    if payment is None or payment.state is not PaymentState.CONFIRMED:
        return SettlementClass.UNSETTLED
    if mocked:
        return SettlementClass.OFFLINE_MOCK
    normalized = payment.chain.strip().upper().replace("_", "-")
    if normalized in SUPPORTED_TESTNET_CHAINS:
        return SettlementClass.TESTNET
    if normalized in SUPPORTED_MAINNET_CHAINS:
        return SettlementClass.MAINNET
    return SettlementClass.UNSUPPORTED


def classify_deal(
    evidence: DealEvidence,
    *,
    payment: PaymentReceipt | None,
    mocked: bool,
    fulfillment: FulfillmentReceipt | None,
) -> DealClassification:
    """Derive all contest-sensitive claims from immutable commerce records."""

    payment_confirmed = bool(
        payment is not None and payment.state is PaymentState.CONFIRMED
    )
    if not payment_confirmed or payment is None:
        raise ValueError("complete deal evidence requires a confirmed payment")
    if fulfillment is None:
        raise ValueError("complete deal evidence requires a fulfillment record")
    if (
        payment.proposal_id != evidence.proposal_id
        or fulfillment.proposal_id != evidence.proposal_id
        or fulfillment.payment_id != payment.payment_id
    ):
        raise ValueError("deal evidence, payment, and fulfillment are not identity-bound")
    if not payment.confirmed_at:
        raise ValueError("complete deal evidence requires payment confirmation time")
    if not fulfillment.delivered_at:
        raise ValueError("complete deal evidence requires fulfillment delivery time")
    confirmed_at = _timestamp(
        payment.confirmed_at,
        label="payment confirmed_at",
    )
    delivered_at = _timestamp(
        fulfillment.delivered_at,
        label="fulfillment delivered_at",
    )
    refund_closed_at = _timestamp(
        evidence.refund_window_closed_at,
        label="deal evidence refund_window_closed_at",
    )
    measured_at = _timestamp(
        evidence.measured_at,
        label="deal evidence measured_at",
    )
    if refund_closed_at < delivered_at:
        raise ValueError("refund measurement window cannot close before delivery")
    if measured_at < max(confirmed_at, delivered_at, refund_closed_at):
        raise ValueError(
            "financial measurement must follow payment, delivery, and refund cutoff"
        )
    payment_amount = payment.amount_usdc
    if evidence.refunds_usdc > payment_amount:
        raise ValueError("refunds cannot exceed the confirmed payment amount")

    settlement = settlement_class_for_payment(payment, mocked=mocked)
    external_customer = bool(
        evidence.relationship_verified
        and evidence.customer_relationship is CustomerRelationship.ARMS_LENGTH
    )
    accepted_fulfillment = fulfillment.accepted
    counts_as_revenue = bool(
        settlement is SettlementClass.MAINNET
        and external_customer
        and evidence.funding_source is FundingSource.CUSTOMER_FUNDED
        and accepted_fulfillment
    )
    user_acquired = bool(
        external_customer and accepted_fulfillment and evidence.user_id
    )
    paid_user = bool(user_acquired and counts_as_revenue)
    paid_task = payment_confirmed
    paid_external_task = counts_as_revenue
    accepted_paid_external_task = bool(
        counts_as_revenue and accepted_fulfillment
    )
    gross_revenue = payment_amount if counts_as_revenue else Decimal("0")
    qualifying_refunds = (
        evidence.refunds_usdc if counts_as_revenue else Decimal("0")
    )
    net_revenue = gross_revenue - qualifying_refunds
    qualifying_costs = (
        evidence.variable_costs.total_usdc
        if counts_as_revenue
        else Decimal("0")
    )
    excluded_spend = (
        Decimal("0")
        if counts_as_revenue
        else evidence.variable_costs.total_usdc
    )

    return DealClassification(
        evidence=evidence,
        settlement_class=settlement,
        payment_confirmed=payment_confirmed,
        accepted_fulfillment=accepted_fulfillment,
        external_customer=external_customer,
        counts_as_revenue=counts_as_revenue,
        user_acquired=user_acquired,
        paid_user=paid_user,
        paid_task=paid_task,
        paid_external_task=paid_external_task,
        accepted_paid_external_task=accepted_paid_external_task,
        payment_amount_usdc=payment_amount,
        gross_external_revenue_usdc=gross_revenue,
        refunds_usdc=qualifying_refunds,
        net_external_revenue_usdc=net_revenue,
        variable_costs_usdc=qualifying_costs,
        excluded_pilot_spend_usdc=excluded_spend,
        gross_margin_usdc=net_revenue - qualifying_costs,
    )


def aggregate_deal_metrics(
    classifications: Iterable[DealClassification],
) -> dict[str, Any]:
    """Aggregate owner-scoped classifications without inflating one customer."""

    values = list(classifications)
    acquired_users = {
        item.evidence.user_id
        for item in values
        if item.user_acquired and item.evidence.user_id
    }
    paying_users = {
        item.evidence.user_id
        for item in values
        if item.paid_user and item.evidence.user_id
    }
    paying_customer_counts = Counter(
        item.evidence.customer_id
        for item in values
        if item.counts_as_revenue and item.evidence.customer_id
    )
    paying_customer_count = len(paying_customer_counts)
    repeat_customer_count = sum(
        1 for count in paying_customer_counts.values() if count >= 2
    )
    repeat_rate = (
        Decimal(repeat_customer_count) / Decimal(paying_customer_count)
        if paying_customer_count
        else None
    )
    gross_revenue = sum(
        (item.gross_external_revenue_usdc for item in values),
        Decimal("0"),
    )
    refunds = sum((item.refunds_usdc for item in values), Decimal("0"))
    net_revenue = sum(
        (item.net_external_revenue_usdc for item in values),
        Decimal("0"),
    )
    qualifying_costs = sum(
        (item.variable_costs_usdc for item in values),
        Decimal("0"),
    )
    excluded_spend = sum(
        (item.excluded_pilot_spend_usdc for item in values),
        Decimal("0"),
    )
    gross_margin = net_revenue - qualifying_costs
    gross_margin_percent = (
        gross_margin / net_revenue * Decimal("100")
        if net_revenue > 0
        else None
    )
    return {
        "dealEvidenceCount": len(values),
        "usersAcquired": len(acquired_users),
        "payingUsers": len(paying_users),
        "acceptedExternalFulfillments": sum(
            1
            for item in values
            if item.external_customer and item.accepted_fulfillment
        ),
        "paidTasks": sum(1 for item in values if item.paid_task),
        "paidExternalTasks": sum(
            1 for item in values if item.paid_external_task
        ),
        "acceptedPaidExternalTasks": sum(
            1 for item in values if item.accepted_paid_external_task
        ),
        "grossExternalRevenueUsdc": usdc_text(gross_revenue),
        "refundsUsdc": usdc_text(refunds),
        "netExternalRevenueUsdc": usdc_text(net_revenue),
        "variableCostsUsdc": usdc_text(qualifying_costs),
        "excludedPilotSpendUsdc": usdc_text(excluded_spend),
        "grossMarginUsdc": _decimal_text(gross_margin),
        "grossMarginPercent": (
            _decimal_text(gross_margin_percent)
            if gross_margin_percent is not None
            else None
        ),
        "repeatPurchaseRate": (
            format(repeat_rate, "f") if repeat_rate is not None else None
        ),
    }


__all__ = [
    "CustomerRelationship",
    "DealClassification",
    "DealEvidence",
    "FundingSource",
    "SUPPORTED_MAINNET_CHAINS",
    "SUPPORTED_TESTNET_CHAINS",
    "SettlementClass",
    "VariableCosts",
    "aggregate_deal_metrics",
    "classify_deal",
    "settlement_class_for_payment",
]
