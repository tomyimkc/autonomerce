"""Shared, dependency-free Autonomerce domain contracts.

Parallel lanes import these types rather than defining incompatible copies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


_HEX_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_ID_PREFIX = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class ContractError(ValueError):
    """Invalid or unsafe domain input."""


class ProposalState(str, Enum):
    DRAFT = "draft"
    OFFERED = "offered"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    PAID = "paid"
    FULFILLING = "fulfilling"
    DELIVERED = "delivered"
    FAILED = "failed"


class PaymentState(str, Enum):
    CREATED = "created"
    POLICY_APPROVED = "policy_approved"
    SUBMITTING = "submitting"
    CONFIRMED = "confirmed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


def stable_id(prefix: str, *parts: object) -> str:
    if not _ID_PREFIX.fullmatch(prefix):
        raise ContractError("invalid identifier prefix")
    normalized = json.dumps(
        [str(part).strip() for part in parts],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def usdc(value: Decimal | int | str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("invalid USDC amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ContractError("USDC amount must be finite and non-negative")
    if amount.as_tuple().exponent < -6:
        raise ContractError("USDC supports at most six decimal places")
    return amount


def usdc_text(value: Decimal | int | str) -> str:
    amount = usdc(value)
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _tuple_strings(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    source_kind: str = "manual"
    source_url: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.name or not self.description:
            raise ContractError("capability_id, name, and description are required")
        object.__setattr__(self, "tags", _tuple_strings(self.tags))


@dataclass(frozen=True)
class ServiceSKU:
    sku_id: str
    capability_id: str
    name: str
    outcome: str
    base_price_usdc: Decimal
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = ()
    maximum_latency_seconds: int = 300
    capacity_per_hour: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_price_usdc", usdc(self.base_price_usdc))
        object.__setattr__(
            self, "acceptance_criteria", _tuple_strings(self.acceptance_criteria)
        )
        if not self.sku_id or not self.capability_id or not self.name or not self.outcome:
            raise ContractError("SKU identity and outcome are required")
        if self.maximum_latency_seconds < 1 or self.capacity_per_hour < 1:
            raise ContractError("latency and capacity must be positive")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["base_price_usdc"] = usdc_text(self.base_price_usdc)
        return value


@dataclass(frozen=True)
class BuyerNeed:
    need_id: str
    buyer_agent_url: str
    desired_outcome: str
    maximum_price_usdc: Decimal
    required_tags: tuple[str, ...] = ()
    input_payload: Mapping[str, Any] = field(default_factory=dict)
    expires_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "maximum_price_usdc", usdc(self.maximum_price_usdc))
        object.__setattr__(self, "required_tags", _tuple_strings(self.required_tags))
        if not self.need_id or not self.buyer_agent_url or not self.desired_outcome:
            raise ContractError("buyer need identity, URL, and outcome are required")


@dataclass(frozen=True)
class CommercialPolicy:
    policy_id: str
    owner_id: str
    minimum_price_usdc: Decimal
    maximum_price_usdc: Decimal
    maximum_discount_fraction: Decimal = Decimal("0")
    maximum_open_proposals: int = 10
    maximum_tasks_per_hour: int = 20
    allowed_buyer_hosts: tuple[str, ...] = ()
    blocked_buyer_hosts: tuple[str, ...] = ()
    allowed_chains: tuple[str, ...] = ("BASE", "ARC-TESTNET")
    allowed_token: str = "USDC"
    unattended: bool = True

    def __post_init__(self) -> None:
        minimum = usdc(self.minimum_price_usdc)
        maximum = usdc(self.maximum_price_usdc)
        discount = Decimal(str(self.maximum_discount_fraction))
        if minimum > maximum:
            raise ContractError("minimum price exceeds maximum price")
        if not Decimal("0") <= discount <= Decimal("1"):
            raise ContractError("maximum_discount_fraction must be between 0 and 1")
        if self.maximum_open_proposals < 1 or self.maximum_tasks_per_hour < 1:
            raise ContractError("policy capacities must be positive")
        object.__setattr__(self, "minimum_price_usdc", minimum)
        object.__setattr__(self, "maximum_price_usdc", maximum)
        object.__setattr__(self, "maximum_discount_fraction", discount)
        object.__setattr__(
            self, "allowed_buyer_hosts", _tuple_strings(self.allowed_buyer_hosts)
        )
        object.__setattr__(
            self, "blocked_buyer_hosts", _tuple_strings(self.blocked_buyer_hosts)
        )
        object.__setattr__(self, "allowed_chains", _tuple_strings(self.allowed_chains))


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    seller_agent_url: str
    buyer_agent_url: str
    sku_id: str
    problem_observed: str
    offered_outcome: str
    price_usdc: Decimal
    delivery_seconds: int
    buyer_need_id: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    expires_at: str | None = None
    state: ProposalState = ProposalState.DRAFT
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "price_usdc", usdc(self.price_usdc))
        buyer_need_id = (
            str(self.buyer_need_id).strip()
            if self.buyer_need_id is not None
            else None
        )
        if self.buyer_need_id is not None and not buyer_need_id:
            raise ContractError("buyer_need_id cannot be blank")
        object.__setattr__(self, "buyer_need_id", buyer_need_id)
        object.__setattr__(
            self, "acceptance_criteria", _tuple_strings(self.acceptance_criteria)
        )
        if not all(
            (
                self.proposal_id,
                self.seller_agent_url,
                self.buyer_agent_url,
                self.sku_id,
                self.offered_outcome,
            )
        ):
            raise ContractError("proposal identity and parties are required")
        if self.delivery_seconds < 1 or self.revision < 1:
            raise ContractError("delivery_seconds and revision must be positive")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["price_usdc"] = usdc_text(self.price_usdc)
        value["state"] = self.state.value
        return value


@dataclass(frozen=True)
class NegotiationDecision:
    accepted: bool
    reason_code: str
    proposal: Proposal
    policy_id: str
    explanation: str = ""


@dataclass(frozen=True)
class PaymentReceipt:
    payment_id: str
    proposal_id: str
    idempotency_key: str
    state: PaymentState
    amount_usdc: Decimal
    chain: str
    payer_wallet: str
    payee_wallet: str
    transaction_hash: str | None = None
    explorer_url: str | None = None
    confirmed_at: str | None = None
    public: bool = False
    token: str = "USDC"
    asset: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount_usdc", usdc(self.amount_usdc))
        if not self.payment_id or not self.proposal_id or not self.idempotency_key:
            raise ContractError("payment identity fields are required")
        token = str(self.token).strip().upper()
        if not token or len(token) > 32 or not token.replace("-", "").isalnum():
            raise ContractError("invalid payment token")
        asset = str(self.asset).strip() if self.asset else None
        if asset:
            if asset.upper() == token:
                asset = token
            elif not _HEX_ADDRESS.fullmatch(asset):
                raise ContractError("invalid payment asset contract")
            else:
                asset = asset.lower()
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "asset", asset)
        if self.chain.upper() == "BASE":
            for wallet in (self.payer_wallet, self.payee_wallet):
                if wallet and not _HEX_ADDRESS.fullmatch(wallet):
                    raise ContractError("invalid Base wallet address")
        if self.state == PaymentState.CONFIRMED and not self.transaction_hash:
            raise ContractError("confirmed payment requires transaction_hash")

    def to_public_dict(self) -> dict[str, Any]:
        value = {
            "paymentId": self.payment_id,
            "proposalId": self.proposal_id,
            "state": self.state.value,
            "amountUsdc": usdc_text(self.amount_usdc),
            "chain": self.chain,
            "token": self.token,
            "asset": self.asset,
            "transactionHash": self.transaction_hash,
            "explorerUrl": self.explorer_url,
            "confirmedAt": self.confirmed_at,
        }
        if self.public:
            value["payerWallet"] = self.payer_wallet
            value["payeeWallet"] = self.payee_wallet
        return value


@dataclass(frozen=True)
class FulfillmentReceipt:
    fulfillment_id: str
    proposal_id: str
    payment_id: str
    seller_agent_url: str
    artifact_hash: str
    accepted: bool
    validator: str
    acceptance_results: Mapping[str, bool] = field(default_factory=dict)
    delivered_at: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            (
                self.fulfillment_id,
                self.proposal_id,
                self.payment_id,
                self.seller_agent_url,
                self.artifact_hash,
                self.validator,
            )
        ):
            raise ContractError("fulfillment identity and artifact fields are required")
