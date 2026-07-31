"""Explicit-consent, local prospect registry.

The registry is intentionally caller-owned and in-memory.  It is not a central
marketplace, crawler, lead scraper, or implicit directory of reachable agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from autonomerce.contracts import ContractError, stable_id

from .agent_cards import AgentCard


class ProspectRegistryError(ContractError):
    """Prospect consent or registry state is invalid."""


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProspectRegistryError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectRegistryError("invalid consent timestamp") from exc
    return _utc(parsed)


def _topics(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list)):
        raise ProspectRegistryError("contact topics must be an array of strings")
    result: list[str] = []
    for value in values:
        topic = str(value).strip().casefold()
        if topic and topic not in result:
            result.append(topic)
    return tuple(result)


@dataclass(frozen=True)
class ProspectRecord:
    prospect_id: str
    agent_card: AgentCard
    consent_reference: str
    opted_in_at: str
    allowed_topics: tuple[str, ...] = ("*",)
    consent_expires_at: str | None = None
    revoked_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def agent_url(self) -> str:
        return self.agent_card.url

    def is_active(self, now: datetime | None = None) -> bool:
        current = _utc(now)
        if self.revoked_at is not None:
            return False
        expires = _parse_iso(self.consent_expires_at)
        return expires is None or current < expires

    def permits_topics(self, topics: tuple[str, ...] | list[str]) -> bool:
        allowed = set(self.allowed_topics)
        requested = set(_topics(topics))
        return "*" in allowed or not requested or requested.issubset(allowed)


class OptedInProspectRegistry:
    """A local registry that only accepts explicit, auditable opt-in."""

    def __init__(self) -> None:
        self._records: dict[str, ProspectRecord] = {}
        self._by_url: dict[str, str] = {}

    def register(
        self,
        card: AgentCard,
        *,
        opted_in: bool,
        consent_reference: str,
        allowed_topics: tuple[str, ...] | list[str] = ("*",),
        opted_in_at: datetime | None = None,
        consent_expires_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProspectRecord:
        if not opted_in:
            raise ProspectRegistryError("prospects require explicit opt-in")
        reference = str(consent_reference).strip()
        if not reference:
            raise ProspectRegistryError("consent_reference is required")
        start = _utc(opted_in_at)
        expiry = _utc(consent_expires_at) if consent_expires_at else None
        if expiry is not None and expiry <= start:
            raise ProspectRegistryError("consent expiry must follow opt-in time")
        normalized_topics = _topics(list(allowed_topics))
        if not normalized_topics:
            raise ProspectRegistryError("at least one allowed contact topic is required")

        prospect_id = stable_id("prospect", card.url)
        record = ProspectRecord(
            prospect_id=prospect_id,
            agent_card=card,
            consent_reference=reference,
            opted_in_at=_iso(start) or "",
            allowed_topics=normalized_topics,
            consent_expires_at=_iso(expiry),
            metadata=dict(metadata or {}),
        )
        self._records[prospect_id] = record
        self._by_url[card.url] = prospect_id
        return record

    def revoke(
        self, prospect_id: str, *, revoked_at: datetime | None = None
    ) -> ProspectRecord:
        record = self.get(prospect_id)
        revoked = replace(record, revoked_at=_iso(_utc(revoked_at)))
        self._records[prospect_id] = revoked
        return revoked

    def get(self, prospect_id: str) -> ProspectRecord:
        try:
            return self._records[prospect_id]
        except KeyError as exc:
            raise ProspectRegistryError("unknown prospect") from exc

    def get_by_url(self, agent_url: str) -> ProspectRecord:
        try:
            return self.get(self._by_url[agent_url])
        except KeyError as exc:
            raise ProspectRegistryError("agent is not in the opted-in registry") from exc

    def active(self, now: datetime | None = None) -> tuple[ProspectRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.is_active(now)
        )

    def __len__(self) -> int:
        return len(self._records)
