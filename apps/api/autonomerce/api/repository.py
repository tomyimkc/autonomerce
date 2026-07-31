"""Thread-safe in-memory repository for offline Autonomerce API operation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from statistics import median
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from autonomerce.contracts import (
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    usdc,
    usdc_text,
)


@dataclass(frozen=True)
class ProspectRecord:
    need: BuyerNeed
    opted_in: bool
    owner_id: str
    consent_reference: str


@dataclass(frozen=True)
class ReceiptPublication:
    receipt_id: str
    proposal_id: str
    owner_id: str
    approved_by: str
    consent_reference: str
    fields: tuple[str, ...]
    published_at: str
    version: int = 1


@dataclass(frozen=True)
class SettlementAuthorization:
    """Immutable acceptance-time authorization for one exact settlement."""

    authorization_id: str
    proposal_id: str
    proposal_revision: int
    proposal_contract_hash: str
    amount_usdc: Decimal
    payer_wallet: str
    payee_wallet: str
    chain: str
    token: str
    asset: str
    commercial_policy_id: str
    commercial_policy_version: str
    seller_configuration_id: str
    seller_configuration_version: str
    expires_at: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount_usdc", usdc(self.amount_usdc))
        object.__setattr__(self, "chain", self.chain.upper())
        object.__setattr__(self, "token", self.token.upper())
        asset = str(self.asset).strip().lower()
        if (
            len(asset) != 42
            or not asset.startswith("0x")
            or any(character not in "0123456789abcdef" for character in asset[2:])
        ):
            raise ValueError(
                "settlement authorization requires a canonical asset contract"
            )
        object.__setattr__(self, "asset", asset)
        required = (
            self.authorization_id,
            self.proposal_id,
            self.proposal_contract_hash,
            self.payer_wallet,
            self.payee_wallet,
            self.chain,
            self.token,
            self.asset,
            self.commercial_policy_id,
            self.commercial_policy_version,
            self.seller_configuration_id,
            self.seller_configuration_version,
            self.expires_at,
            self.created_at,
        )
        if not all(required) or self.proposal_revision < 1:
            raise ValueError(
                "settlement authorization requires complete immutable bindings"
            )


def payment_matches_settlement_authorization(
    payment: PaymentReceipt,
    authorization: SettlementAuthorization,
) -> bool:
    return (
        payment.proposal_id == authorization.proposal_id
        and payment.amount_usdc == authorization.amount_usdc
        and payment.chain.upper() == authorization.chain
        and payment.token.upper() == authorization.token
        and payment.asset == authorization.asset
        and payment.payer_wallet.lower() == authorization.payer_wallet.lower()
        and payment.payee_wallet.lower() == authorization.payee_wallet.lower()
        and payment.state == PaymentState.CONFIRMED
        and not payment.public
    )


class RepositoryDurability(str, Enum):
    PROCESS_LOCAL = "process-local"
    SINGLE_NODE = "single-node"
    DISTRIBUTED = "distributed"


_PROPOSAL_STATE_RANK = {
    ProposalState.DRAFT: 0,
    ProposalState.OFFERED: 1,
    ProposalState.COUNTERED: 2,
    ProposalState.ACCEPTED: 3,
    ProposalState.PAID: 4,
    ProposalState.FULFILLING: 5,
    ProposalState.DECLINED: 6,
    ProposalState.EXPIRED: 6,
    ProposalState.DELIVERED: 6,
    ProposalState.FAILED: 6,
}
_POST_ACCEPTANCE_STATES = {
    ProposalState.ACCEPTED,
    ProposalState.PAID,
    ProposalState.FULFILLING,
    ProposalState.DELIVERED,
    ProposalState.FAILED,
}
_ALLOWED_PROPOSAL_TRANSITIONS = {
    ProposalState.DRAFT: {
        ProposalState.OFFERED,
        ProposalState.EXPIRED,
        ProposalState.FAILED,
    },
    ProposalState.OFFERED: {
        ProposalState.COUNTERED,
        ProposalState.ACCEPTED,
        ProposalState.DECLINED,
        ProposalState.EXPIRED,
        ProposalState.FAILED,
    },
    ProposalState.COUNTERED: {
        ProposalState.COUNTERED,
        ProposalState.ACCEPTED,
        ProposalState.DECLINED,
        ProposalState.EXPIRED,
        ProposalState.FAILED,
    },
    ProposalState.ACCEPTED: {
        ProposalState.PAID,
        ProposalState.FAILED,
    },
    ProposalState.PAID: {
        ProposalState.FULFILLING,
        ProposalState.FAILED,
    },
    ProposalState.FULFILLING: {
        ProposalState.DELIVERED,
        ProposalState.FAILED,
    },
    ProposalState.DECLINED: set(),
    ProposalState.EXPIRED: set(),
    ProposalState.DELIVERED: set(),
    ProposalState.FAILED: set(),
}


def _proposal_contract_binding(proposal: Proposal) -> tuple[Any, ...]:
    return (
        proposal.seller_agent_url,
        proposal.buyer_agent_url,
        proposal.buyer_need_id,
        proposal.sku_id,
        proposal.problem_observed,
        proposal.offered_outcome,
        proposal.price_usdc,
        proposal.delivery_seconds,
        proposal.acceptance_criteria,
        proposal.expires_at,
    )


def monotonic_proposal(
    existing: Proposal | None,
    incoming: Proposal,
) -> Proposal:
    """Return the only proposal state that may be durably persisted.

    Replayed workflow requests are allowed to re-submit an older projection, but
    they may never move a proposal backwards or rewrite an accepted contract.
    """

    if existing is None:
        return incoming
    if existing.proposal_id != incoming.proposal_id:
        raise ValueError("proposal identity cannot be changed")

    existing_rank = _PROPOSAL_STATE_RANK[existing.state]
    incoming_rank = _PROPOSAL_STATE_RANK[incoming.state]
    if (
        incoming.revision < existing.revision
        or incoming_rank < existing_rank
    ):
        return existing
    if (
        incoming.state == existing.state
        and incoming.revision == existing.revision
    ):
        if incoming != existing:
            raise ValueError(
                "same-revision proposal replay conflicts with durable content"
            )
        return existing
    if incoming.state not in _ALLOWED_PROPOSAL_TRANSITIONS[existing.state]:
        raise ValueError(
            "proposal state transition is not allowed: "
            f"{existing.state.value} -> {incoming.state.value}"
        )
    if incoming.revision not in {
        existing.revision,
        existing.revision + 1,
    }:
        raise ValueError("proposal revision transition is not allowed")
    if (
        existing.state in _POST_ACCEPTANCE_STATES
        and _proposal_contract_binding(incoming)
        != _proposal_contract_binding(existing)
    ):
        raise ValueError("accepted proposal contract cannot be changed")
    return incoming


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Structural hook for a durable commerce repository implementation."""

    storage_name: str
    durability: RepositoryDurability

    @property
    def is_durable(self) -> bool:
        """Whether state survives an application-process restart."""
        ...


class InMemoryRepository:
    """Process-local state with deterministic read and idempotency behavior."""

    storage_name = "memory"
    durability = RepositoryDurability.PROCESS_LOCAL

    def __init__(self) -> None:
        self._lock = RLock()
        self.sellers: dict[str, dict[str, Any]] = {}
        self.seller_owners: dict[str, str] = {}
        self.capabilities: dict[str, CapabilityDescriptor] = {}
        self.capability_sellers: dict[str, str] = {}
        self.skus: dict[str, ServiceSKU] = {}
        self.sku_sellers: dict[str, str] = {}
        self.policies: dict[str, CommercialPolicy] = {}
        self.prospects: dict[str, ProspectRecord] = {}
        self.proposals: dict[str, Proposal] = {}
        self.proposal_owners: dict[str, str] = {}
        self.proposal_contract_hashes: dict[str, str] = {}
        self.settlement_authorizations: dict[str, SettlementAuthorization] = {}
        self.payments: dict[str, PaymentReceipt] = {}
        self.payment_by_proposal: dict[str, str] = {}
        self.payment_by_idempotency: dict[str, str] = {}
        self.payment_by_transaction_hash: dict[str, str] = {}
        self.payment_mocked: dict[str, bool] = {}
        self.fulfillments: dict[str, FulfillmentReceipt] = {}
        self.fulfillment_by_proposal: dict[str, str] = {}
        self.receipt_publications: dict[str, ReceiptPublication] = {}
        self.publication_by_proposal: dict[str, str] = {}
        self.accepted_proposal_ids: set[str] = set()
        self.negotiation_deltas: list[Decimal] = []
        self.policy_denials = 0
        self.duplicate_payment_attempts = 0

    @property
    def is_durable(self) -> bool:
        return False

    def save_seller(
        self, seller: dict[str, Any], *, owner_id: str = "offline-demo"
    ) -> dict[str, Any]:
        with self._lock:
            self.sellers[seller["seller_id"]] = deepcopy(seller)
            self.seller_owners[seller["seller_id"]] = owner_id
            return deepcopy(seller)

    def get_seller(self, seller_id: str) -> dict[str, Any] | None:
        with self._lock:
            seller = self.sellers.get(seller_id)
            return deepcopy(seller) if seller else None

    def find_seller_by_url(self, agent_url: str) -> dict[str, Any] | None:
        with self._lock:
            for seller in self.sellers.values():
                if seller["agent_url"] == agent_url:
                    return deepcopy(seller)
        return None

    def owner_for_seller(self, seller_id: str) -> str | None:
        with self._lock:
            return self.seller_owners.get(seller_id)

    def save_capability(
        self, seller_id: str, capability: CapabilityDescriptor
    ) -> CapabilityDescriptor:
        with self._lock:
            self.capabilities[capability.capability_id] = capability
            self.capability_sellers[capability.capability_id] = seller_id
        return capability

    def list_capabilities(self, seller_id: str) -> list[CapabilityDescriptor]:
        with self._lock:
            return [
                capability
                for capability_id, capability in self.capabilities.items()
                if self.capability_sellers.get(capability_id) == seller_id
            ]

    def get_capability(self, capability_id: str) -> CapabilityDescriptor | None:
        with self._lock:
            return self.capabilities.get(capability_id)

    def save_sku(self, seller_id: str, sku: ServiceSKU) -> ServiceSKU:
        with self._lock:
            self.skus[sku.sku_id] = sku
            self.sku_sellers[sku.sku_id] = seller_id
        return sku

    def get_sku(self, sku_id: str) -> ServiceSKU | None:
        with self._lock:
            return self.skus.get(sku_id)

    def seller_for_sku(self, sku_id: str) -> str | None:
        with self._lock:
            return self.sku_sellers.get(sku_id)

    def list_skus(self, seller_id: str) -> list[ServiceSKU]:
        with self._lock:
            return [
                sku
                for sku_id, sku in self.skus.items()
                if self.sku_sellers.get(sku_id) == seller_id
            ]

    def save_policy(self, seller_id: str, policy: CommercialPolicy) -> CommercialPolicy:
        with self._lock:
            self.policies[seller_id] = policy
        return policy

    def get_policy(self, seller_id: str) -> CommercialPolicy | None:
        with self._lock:
            return self.policies.get(seller_id)

    def save_prospect(self, prospect: ProspectRecord) -> ProspectRecord:
        with self._lock:
            self.prospects[prospect.need.need_id] = prospect
        return prospect

    def owner_for_prospect(self, need_id: str) -> str | None:
        with self._lock:
            prospect = self.prospects.get(need_id)
            return prospect.owner_id if prospect else None

    def get_prospect(self, need_id: str) -> ProspectRecord | None:
        with self._lock:
            return self.prospects.get(need_id)

    def find_prospect_by_url(self, buyer_agent_url: str) -> ProspectRecord | None:
        with self._lock:
            for prospect in self.prospects.values():
                if prospect.need.buyer_agent_url == buyer_agent_url:
                    return prospect
        return None

    def list_prospects(
        self, *, owner_id: str | None = None
    ) -> list[ProspectRecord]:
        with self._lock:
            prospects = list(self.prospects.values())
            if owner_id is not None:
                prospects = [
                    prospect
                    for prospect in prospects
                    if prospect.owner_id == owner_id
                ]
            return prospects

    def save_proposal(
        self,
        proposal: Proposal,
        *,
        owner_id: str | None = None,
        contract_hash: str | None = None,
    ) -> Proposal:
        with self._lock:
            existing_owner = self.proposal_owners.get(proposal.proposal_id)
            existing_proposal = self.proposals.get(proposal.proposal_id)
            selected_owner = owner_id or existing_owner
            if selected_owner is None:
                raise ValueError("proposal owner is required")
            if existing_owner is not None and existing_owner != selected_owner:
                raise ValueError("proposal owner cannot be changed")
            selected_proposal = monotonic_proposal(existing_proposal, proposal)
            existing_authorization = self.settlement_authorizations.get(
                proposal.proposal_id
            )
            selected_hash = (
                self.proposal_contract_hashes.get(proposal.proposal_id)
                if selected_proposal is existing_proposal
                else contract_hash
            )
            if selected_hash is None:
                selected_hash = self.proposal_contract_hashes.get(
                    proposal.proposal_id
                )
            if (
                existing_authorization is not None
                and selected_hash != existing_authorization.proposal_contract_hash
            ):
                raise ValueError(
                    "accepted proposal contract hash cannot be changed"
                )
            self.proposals[proposal.proposal_id] = selected_proposal
            self.proposal_owners[proposal.proposal_id] = selected_owner
            if selected_hash is not None:
                self.proposal_contract_hashes[proposal.proposal_id] = selected_hash
        return selected_proposal

    def accept_proposal(
        self,
        proposal: Proposal,
        authorization: SettlementAuthorization,
        *,
        owner_id: str,
        contract_hash: str,
    ) -> tuple[Proposal, SettlementAuthorization]:
        with self._lock:
            existing = self.proposals.get(proposal.proposal_id)
            if existing is None:
                raise ValueError("proposal does not exist")
            if self.proposal_owners.get(proposal.proposal_id) != owner_id:
                raise ValueError("proposal owner cannot be changed")
            selected = monotonic_proposal(existing, proposal)
            if selected.state not in _POST_ACCEPTANCE_STATES:
                raise ValueError("proposal acceptance did not reach an accepted state")
            if (
                authorization.proposal_id != selected.proposal_id
                or authorization.proposal_revision != selected.revision
                or authorization.proposal_contract_hash != contract_hash
                or authorization.amount_usdc != selected.price_usdc
            ):
                raise ValueError(
                    "settlement authorization does not match accepted proposal"
                )
            existing_authorization = self.settlement_authorizations.get(
                proposal.proposal_id
            )
            if (
                existing_authorization is not None
                and existing_authorization != authorization
            ):
                raise ValueError(
                    "settlement authorization is immutable once accepted"
                )
            self.proposals[proposal.proposal_id] = selected
            self.proposal_contract_hashes[proposal.proposal_id] = contract_hash
            self.settlement_authorizations[proposal.proposal_id] = (
                existing_authorization or authorization
            )
            self.accepted_proposal_ids.add(proposal.proposal_id)
            return (
                selected,
                self.settlement_authorizations[proposal.proposal_id],
            )

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        with self._lock:
            return self.proposals.get(proposal_id)

    def owner_for_proposal(self, proposal_id: str) -> str | None:
        with self._lock:
            return self.proposal_owners.get(proposal_id)

    def contract_hash_for_proposal(self, proposal_id: str) -> str | None:
        with self._lock:
            return self.proposal_contract_hashes.get(proposal_id)

    def get_settlement_authorization(
        self, proposal_id: str
    ) -> SettlementAuthorization | None:
        with self._lock:
            return self.settlement_authorizations.get(proposal_id)

    def list_proposals(
        self,
        *,
        seller_id: str | None = None,
        state: ProposalState | None = None,
        owner_id: str | None = None,
    ) -> list[Proposal]:
        with self._lock:
            proposals = list(self.proposals.values())
            if owner_id is not None:
                proposals = [
                    proposal
                    for proposal in proposals
                    if self.proposal_owners.get(proposal.proposal_id) == owner_id
                ]
            if seller_id is not None:
                seller_url = self.sellers.get(seller_id, {}).get("agent_url")
                proposals = [
                    proposal
                    for proposal in proposals
                    if proposal.seller_agent_url == seller_url
                ]
            if state is not None:
                proposals = [
                    proposal for proposal in proposals if proposal.state == state
                ]
            return proposals

    def mark_accepted(self, proposal_id: str) -> None:
        with self._lock:
            self.accepted_proposal_ids.add(proposal_id)

    def record_negotiation(self, delta: Decimal) -> None:
        with self._lock:
            self.negotiation_deltas.append(delta)

    def note_policy_denial(self) -> None:
        with self._lock:
            self.policy_denials += 1

    def note_duplicate_payment(self) -> None:
        with self._lock:
            self.duplicate_payment_attempts += 1

    def get_payment(self, payment_id: str) -> PaymentReceipt | None:
        with self._lock:
            return self.payments.get(payment_id)

    def owner_for_payment(self, payment_id: str) -> str | None:
        with self._lock:
            payment = self.payments.get(payment_id)
            return (
                self.proposal_owners.get(payment.proposal_id)
                if payment is not None
                else None
            )

    def payment_for_proposal(self, proposal_id: str) -> PaymentReceipt | None:
        with self._lock:
            payment_id = self.payment_by_proposal.get(proposal_id)
            return self.payments.get(payment_id) if payment_id else None

    def payment_for_idempotency(self, key: str) -> PaymentReceipt | None:
        with self._lock:
            payment_id = self.payment_by_idempotency.get(key)
            return self.payments.get(payment_id) if payment_id else None

    def save_payment(self, receipt: PaymentReceipt, *, mocked: bool) -> PaymentReceipt:
        with self._lock:
            existing_for_proposal = self.payment_by_proposal.get(receipt.proposal_id)
            existing_for_key = self.payment_by_idempotency.get(receipt.idempotency_key)
            transaction_hash_key = (
                receipt.transaction_hash.lower()
                if receipt.transaction_hash is not None
                else None
            )
            existing_for_transaction = (
                self.payment_by_transaction_hash.get(transaction_hash_key)
                if transaction_hash_key is not None
                else None
            )
            if existing_for_proposal and existing_for_proposal != receipt.payment_id:
                raise ValueError("proposal already has a different payment")
            if existing_for_key and existing_for_key != receipt.payment_id:
                raise ValueError("idempotency key already has a different payment")
            if (
                existing_for_transaction
                and existing_for_transaction != receipt.payment_id
            ):
                raise ValueError(
                    "transaction hash already has a different payment"
                )
            existing_receipt = self.payments.get(receipt.payment_id)
            if existing_receipt is not None:
                if (
                    existing_receipt != receipt
                    or self.payment_mocked.get(receipt.payment_id) != mocked
                ):
                    raise ValueError(
                        "existing payment evidence cannot be rewritten"
                    )
                return existing_receipt
            proposal = self.proposals.get(receipt.proposal_id)
            if proposal is None:
                raise ValueError("payment proposal does not exist")
            authorization = self.settlement_authorizations.get(
                receipt.proposal_id
            )
            if authorization is None or not (
                payment_matches_settlement_authorization(
                    receipt, authorization
                )
            ):
                raise ValueError(
                    "payment does not match immutable settlement authorization"
                )
            self.payments[receipt.payment_id] = receipt
            self.payment_by_proposal[receipt.proposal_id] = receipt.payment_id
            self.payment_by_idempotency[receipt.idempotency_key] = receipt.payment_id
            if transaction_hash_key is not None:
                self.payment_by_transaction_hash[transaction_hash_key] = (
                    receipt.payment_id
                )
            self.payment_mocked[receipt.payment_id] = mocked
            if proposal.state == ProposalState.ACCEPTED:
                self.proposals[proposal.proposal_id] = replace(
                    proposal,
                    state=ProposalState.PAID,
                )
        return receipt

    def is_mocked_payment(self, payment_id: str) -> bool:
        with self._lock:
            return self.payment_mocked.get(payment_id, False)

    def recent_paid_count(self, seller_id: str, *, hours: int = 1) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._lock:
            seller_url = self.sellers.get(seller_id, {}).get("agent_url")
            count = 0
            for payment in self.payments.values():
                proposal = self.proposals.get(payment.proposal_id)
                if not proposal or proposal.seller_agent_url != seller_url:
                    continue
                if not payment.confirmed_at:
                    count += 1
                    continue
                try:
                    timestamp = datetime.fromisoformat(payment.confirmed_at)
                except ValueError:
                    count += 1
                    continue
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if timestamp >= cutoff:
                    count += 1
            return count

    def get_fulfillment(self, fulfillment_id: str) -> FulfillmentReceipt | None:
        with self._lock:
            return self.fulfillments.get(fulfillment_id)

    def owner_for_fulfillment(self, fulfillment_id: str) -> str | None:
        with self._lock:
            fulfillment = self.fulfillments.get(fulfillment_id)
            return (
                self.proposal_owners.get(fulfillment.proposal_id)
                if fulfillment is not None
                else None
            )

    def fulfillment_for_proposal(
        self, proposal_id: str
    ) -> FulfillmentReceipt | None:
        with self._lock:
            fulfillment_id = self.fulfillment_by_proposal.get(proposal_id)
            return self.fulfillments.get(fulfillment_id) if fulfillment_id else None

    def save_fulfillment(self, receipt: FulfillmentReceipt) -> FulfillmentReceipt:
        with self._lock:
            existing_for_proposal = self.fulfillment_by_proposal.get(
                receipt.proposal_id
            )
            if (
                existing_for_proposal
                and existing_for_proposal != receipt.fulfillment_id
            ):
                raise ValueError("proposal already has a different fulfillment")
            existing_receipt = self.fulfillments.get(receipt.fulfillment_id)
            if existing_receipt is not None:
                if existing_receipt != receipt:
                    raise ValueError(
                        "existing fulfillment evidence cannot be rewritten"
                    )
                return existing_receipt
            payment = self.payments.get(receipt.payment_id)
            if payment is None or payment.proposal_id != receipt.proposal_id:
                raise ValueError(
                    "fulfillment payment is missing or belongs to another proposal"
                )
            for existing in self.fulfillments.values():
                if existing.payment_id == receipt.payment_id:
                    raise ValueError(
                        "payment already has a different fulfillment"
                    )
            proposal = self.proposals.get(receipt.proposal_id)
            if proposal is None:
                raise ValueError("fulfillment proposal does not exist")
            self.fulfillments[receipt.fulfillment_id] = receipt
            self.fulfillment_by_proposal[receipt.proposal_id] = receipt.fulfillment_id
            self.proposals[receipt.proposal_id] = replace(
                proposal,
                state=(
                    ProposalState.DELIVERED
                    if receipt.accepted
                    else ProposalState.FAILED
                ),
            )
        return receipt

    def save_receipt_publication(
        self, publication: ReceiptPublication
    ) -> ReceiptPublication:
        with self._lock:
            proposal_owner = self.proposal_owners.get(publication.proposal_id)
            if proposal_owner != publication.owner_id:
                raise ValueError("receipt publication owner does not match proposal")
            existing_id = self.publication_by_proposal.get(publication.proposal_id)
            existing = (
                self.receipt_publications.get(existing_id)
                if existing_id is not None
                else None
            )
            if existing is not None:
                if (
                    existing.owner_id != publication.owner_id
                    or existing.consent_reference != publication.consent_reference
                    or existing.fields != publication.fields
                ):
                    raise ValueError(
                        "receipt is already published under a different authorization"
                    )
                return existing
            self.receipt_publications[publication.receipt_id] = publication
            self.publication_by_proposal[publication.proposal_id] = (
                publication.receipt_id
            )
            return publication

    def get_receipt_publication(
        self, receipt_id: str
    ) -> ReceiptPublication | None:
        with self._lock:
            direct = self.receipt_publications.get(receipt_id)
            if direct is not None:
                return direct
            publication_id = self.publication_by_proposal.get(receipt_id)
            return (
                self.receipt_publications.get(publication_id)
                if publication_id is not None
                else None
            )

    def metrics(self, *, owner_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            proposal_ids = {
                proposal_id
                for proposal_id in self.proposals
                if owner_id is None
                or self.proposal_owners.get(proposal_id) == owner_id
            }
            proposals = [
                proposal
                for proposal_id, proposal in self.proposals.items()
                if proposal_id in proposal_ids
            ]
            confirmed = [
                payment
                for payment in self.payments.values()
                if payment.state == PaymentState.CONFIRMED
                and payment.proposal_id in proposal_ids
            ]
            live = [
                payment
                for payment in confirmed
                if not self.payment_mocked.get(payment.payment_id, False)
                and "TEST" not in payment.chain.upper()
            ]
            mocked = [
                payment
                for payment in confirmed
                if self.payment_mocked.get(payment.payment_id, False)
                or "TEST" in payment.chain.upper()
            ]
            successful = [
                receipt
                for receipt in self.fulfillments.values()
                if receipt.accepted and receipt.proposal_id in proposal_ids
            ]
            activated = sum(
                1
                for seller_id in self.sellers
                if (
                    owner_id is None
                    or self.seller_owners.get(seller_id) == owner_id
                )
                if seller_id in self.policies
                and any(
                    mapped_seller == seller_id
                    for mapped_seller in self.sku_sellers.values()
                )
            )
            accepted_count = len(self.accepted_proposal_ids & proposal_ids)
            acceptance_rate = (
                Decimal(accepted_count) / Decimal(len(proposals)) if proposals else Decimal("0")
            )
            negotiated_total = sum(
                (abs(delta) for delta in self.negotiation_deltas), Decimal("0")
            )
            delivery_seconds: list[float] = []
            for payment in confirmed:
                fulfillment_id = self.fulfillment_by_proposal.get(payment.proposal_id)
                fulfillment = (
                    self.fulfillments.get(fulfillment_id) if fulfillment_id else None
                )
                if (
                    not fulfillment
                    or not fulfillment.accepted
                    or not payment.confirmed_at
                    or not fulfillment.delivered_at
                ):
                    continue
                try:
                    confirmed_at = datetime.fromisoformat(
                        payment.confirmed_at.replace("Z", "+00:00")
                    )
                    delivered_at = datetime.fromisoformat(
                        fulfillment.delivered_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if confirmed_at.tzinfo is None:
                    confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
                if delivered_at.tzinfo is None:
                    delivered_at = delivered_at.replace(tzinfo=timezone.utc)
                elapsed = (delivered_at - confirmed_at).total_seconds()
                if elapsed >= 0:
                    delivery_seconds.append(elapsed)

            registered_sellers = sum(
                1
                for seller_id in self.sellers
                if owner_id is None
                or self.seller_owners.get(seller_id) == owner_id
            )
            return {
                "registeredSellerAgents": registered_sellers,
                "activatedSellerAgents": activated,
                "proposalsSent": len(proposals),
                "proposalAcceptanceRate": format(acceptance_rate, "f"),
                "negotiatedPriceChangeUsdc": usdc_text(abs(negotiated_total)),
                "paidTasks": None,
                "paidTasksStatus": "requires_external_customer_classification",
                "confirmedLivePayments": len(live),
                "mockedPaymentCount": len(mocked),
                "usdcRevenue": None,
                "liveSettlementVolumeUsdc": usdc_text(
                    sum((payment.amount_usdc for payment in live), Decimal("0"))
                ),
                "mockedPaymentVolumeUsdc": usdc_text(
                    sum((payment.amount_usdc for payment in mocked), Decimal("0"))
                ),
                "successfulFulfillment": len(successful),
                "medianDeliverySeconds": (
                    float(median(delivery_seconds)) if delivery_seconds else None
                ),
                "repeatPurchaseRate": None,
                "repeatPurchaseRateStatus": (
                    "requires_external_customer_classification"
                ),
                "paymentFailures": sum(
                    1
                    for payment in self.payments.values()
                    if payment.proposal_id in proposal_ids
                    if payment.state
                    in (PaymentState.FAILED_RETRYABLE, PaymentState.FAILED_TERMINAL)
                ),
                "policyDenials": self.policy_denials,
                "duplicatePaymentCount": self.duplicate_payment_attempts,
                "grossMarginUsdc": None,
                "grossMarginStatus": "requires_measured_variable_costs",
                "revenueClassification": "unmeasured_external_customer_status",
            }
