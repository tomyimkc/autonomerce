"""Rate-limited, consent-bound pitch creation.

Pitch creation is a local state transition.  Sending the resulting proposal is
left to an API-composition adapter so this lane never performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlsplit

from autonomerce.contracts import (
    BuyerNeed,
    CommercialPolicy,
    ContractError,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
)

from .matching import NeedCapabilityMatch
from .prospects import OptedInProspectRegistry, ProspectRegistryError


class PitchError(ContractError):
    """Pitch workflow configuration is invalid."""


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise PitchError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise PitchError("invalid proposal or need expiry") from exc


def _host(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise PitchError("buyer agent URL has no host")
    return host.casefold()


@dataclass(frozen=True)
class AntiSpamPolicy:
    per_prospect_per_hour: int = 2
    per_host_per_hour: int = 5
    global_per_hour: int = 20
    cooldown_seconds: int = 300
    duplicate_window_seconds: int = 86_400
    proposal_ttl_seconds: int = 900

    def __post_init__(self) -> None:
        values = (
            self.per_prospect_per_hour,
            self.per_host_per_hour,
            self.global_per_hour,
            self.cooldown_seconds,
            self.duplicate_window_seconds,
            self.proposal_ttl_seconds,
        )
        if any(value < 1 for value in values):
            raise PitchError("anti-spam limits must be positive")


@dataclass(frozen=True)
class PitchEvent:
    prospect_id: str
    buyer_agent_url: str
    buyer_host: str
    need_id: str
    sku_id: str
    proposal_id: str
    sent_at: datetime


@dataclass(frozen=True)
class PitchGuardDecision:
    allowed: bool
    reason_code: str
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class PitchOutcome:
    sent: bool
    reason_code: str
    proposal: Proposal | None = None
    retry_after_seconds: int | None = None


class PitchWorkflow:
    """Create machine-readable offers only after every deterministic gate passes."""

    def __init__(
        self,
        *,
        seller_agent_url: str,
        commercial_policy: CommercialPolicy,
        registry: OptedInProspectRegistry,
        anti_spam: AntiSpamPolicy | None = None,
    ) -> None:
        if not seller_agent_url.strip():
            raise PitchError("seller_agent_url is required")
        self.seller_agent_url = seller_agent_url.strip()
        self.commercial_policy = commercial_policy
        self.registry = registry
        self.anti_spam = anti_spam or AntiSpamPolicy()
        self._events: list[PitchEvent] = []
        self._proposals: dict[str, Proposal] = {}

    @property
    def events(self) -> tuple[PitchEvent, ...]:
        return tuple(self._events)

    @property
    def proposals(self) -> tuple[Proposal, ...]:
        return tuple(self._proposals.values())

    def update_proposal(self, proposal: Proposal) -> None:
        if proposal.proposal_id not in self._proposals:
            raise PitchError("cannot update an unknown proposal")
        self._proposals[proposal.proposal_id] = proposal

    def _recent(self, now: datetime, seconds: int) -> Iterable[PitchEvent]:
        cutoff = now - timedelta(seconds=seconds)
        return (event for event in self._events if event.sent_at > cutoff)

    def check(
        self,
        *,
        need: BuyerNeed,
        sku: ServiceSKU,
        match: NeedCapabilityMatch,
        now: datetime | None = None,
    ) -> PitchGuardDecision:
        current = _utc(now)
        try:
            prospect = self.registry.get_by_url(need.buyer_agent_url)
        except ProspectRegistryError:
            return PitchGuardDecision(False, "prospect_not_opted_in")
        if not prospect.is_active(current):
            return PitchGuardDecision(False, "prospect_consent_inactive")
        if not prospect.permits_topics(list(need.required_tags)):
            return PitchGuardDecision(False, "contact_topic_not_consented")
        if not self.commercial_policy.unattended:
            return PitchGuardDecision(False, "unattended_sales_disabled")

        buyer_host = _host(need.buyer_agent_url)
        allowed_hosts = {
            host.casefold() for host in self.commercial_policy.allowed_buyer_hosts
        }
        blocked_hosts = {
            host.casefold() for host in self.commercial_policy.blocked_buyer_hosts
        }
        if buyer_host in blocked_hosts:
            return PitchGuardDecision(False, "buyer_host_blocked")
        if allowed_hosts and buyer_host not in allowed_hosts:
            return PitchGuardDecision(False, "buyer_host_not_allowed")
        if not match.eligible or match.need_id != need.need_id:
            return PitchGuardDecision(False, "need_capability_mismatch")
        if match.sku_id != sku.sku_id:
            return PitchGuardDecision(False, "match_sku_mismatch")
        if not (
            self.commercial_policy.minimum_price_usdc
            <= sku.base_price_usdc
            <= self.commercial_policy.maximum_price_usdc
        ):
            return PitchGuardDecision(False, "sku_price_outside_seller_policy")
        if sku.base_price_usdc > need.maximum_price_usdc:
            return PitchGuardDecision(False, "price_exceeds_buyer_limit")

        expiry = _parse_iso(need.expires_at)
        if expiry is not None and current >= expiry:
            return PitchGuardDecision(False, "buyer_need_expired")

        open_states = {ProposalState.OFFERED, ProposalState.COUNTERED}
        open_count = sum(
            proposal.state in open_states for proposal in self._proposals.values()
        )
        if open_count >= self.commercial_policy.maximum_open_proposals:
            return PitchGuardDecision(False, "seller_open_proposal_limit")

        duplicate_events = list(
            self._recent(current, self.anti_spam.duplicate_window_seconds)
        )
        if any(
            event.need_id == need.need_id and event.sku_id == sku.sku_id
            for event in duplicate_events
        ):
            return PitchGuardDecision(False, "duplicate_pitch_suppressed")

        hour_events = list(self._recent(current, 3600))
        global_limit = min(
            self.anti_spam.global_per_hour,
            self.commercial_policy.maximum_tasks_per_hour,
        )
        if len(hour_events) >= global_limit:
            return PitchGuardDecision(False, "global_rate_limit", 3600)
        if (
            sum(event.prospect_id == prospect.prospect_id for event in hour_events)
            >= self.anti_spam.per_prospect_per_hour
        ):
            return PitchGuardDecision(False, "prospect_rate_limit", 3600)
        if (
            sum(event.buyer_host == buyer_host for event in hour_events)
            >= self.anti_spam.per_host_per_hour
        ):
            return PitchGuardDecision(False, "host_rate_limit", 3600)

        prospect_events = [
            event for event in self._events if event.prospect_id == prospect.prospect_id
        ]
        if prospect_events:
            elapsed = (current - prospect_events[-1].sent_at).total_seconds()
            if elapsed < self.anti_spam.cooldown_seconds:
                return PitchGuardDecision(
                    False,
                    "prospect_cooldown",
                    max(1, int(self.anti_spam.cooldown_seconds - elapsed)),
                )
        return PitchGuardDecision(True, "allowed")

    def pitch(
        self,
        *,
        need: BuyerNeed,
        sku: ServiceSKU,
        match: NeedCapabilityMatch,
        now: datetime | None = None,
    ) -> PitchOutcome:
        current = _utc(now)
        guard = self.check(need=need, sku=sku, match=match, now=current)
        if not guard.allowed:
            return PitchOutcome(
                sent=False,
                reason_code=guard.reason_code,
                retry_after_seconds=guard.retry_after_seconds,
            )

        prospect = self.registry.get_by_url(need.buyer_agent_url)
        need_expiry = _parse_iso(need.expires_at)
        workflow_expiry = current + timedelta(
            seconds=self.anti_spam.proposal_ttl_seconds
        )
        expires_at = min(need_expiry, workflow_expiry) if need_expiry else workflow_expiry
        proposal_id = stable_id(
            "proposal",
            self.seller_agent_url,
            need.buyer_agent_url,
            need.need_id,
            sku.sku_id,
        )
        proposal = Proposal(
            proposal_id=proposal_id,
            seller_agent_url=self.seller_agent_url,
            buyer_agent_url=need.buyer_agent_url,
            sku_id=sku.sku_id,
            problem_observed=need.desired_outcome,
            offered_outcome=sku.outcome,
            price_usdc=sku.base_price_usdc,
            delivery_seconds=sku.maximum_latency_seconds,
            acceptance_criteria=sku.acceptance_criteria,
            expires_at=_iso(expires_at),
            state=ProposalState.OFFERED,
        )
        self._proposals[proposal_id] = proposal
        self._events.append(
            PitchEvent(
                prospect_id=prospect.prospect_id,
                buyer_agent_url=need.buyer_agent_url,
                buyer_host=_host(need.buyer_agent_url),
                need_id=need.need_id,
                sku_id=sku.sku_id,
                proposal_id=proposal_id,
                sent_at=current,
            )
        )
        return PitchOutcome(True, "offered", proposal)


RateLimitedPitchWorkflow = PitchWorkflow
