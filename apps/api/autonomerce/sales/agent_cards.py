"""Offline parsing and validation for A2A Agent Cards.

This module deliberately accepts card content supplied by the caller.  It does
not fetch URLs, crawl agents, or maintain a global directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from autonomerce.contracts import CapabilityDescriptor, ContractError, stable_id


MAX_AGENT_CARD_BYTES = 256 * 1024
MAX_AGENT_SKILLS = 100
MAX_AGENT_CARD_DEPTH = 20
MAX_AGENT_CARD_NODES = 10_000
MAX_AGENT_CARD_STRING_LENGTH = 8_192
MAX_AGENT_CARD_LIST_ITEMS = 128
MAX_AGENT_CARD_MAPPING_ITEMS = 512
_BLOCKED_AGENT_HOSTS = {
    "metadata",
    "metadata.google.internal",
}
_OFFLINE_FIXTURE_HOSTS = {
    "example.com",
    "example.net",
    "example.org",
}
_OFFLINE_FIXTURE_SUFFIXES = (".example", ".test", ".invalid")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class AgentCardError(ContractError):
    """The supplied Agent Card is malformed or unsafe."""


def _nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentCardError(f"{field_name} must be a non-empty string")
    return value.strip()


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise AgentCardError(f"{field_name} must be an array of strings")
    result: list[str] = []
    for item in value:
        text = _nonempty_string(item, field_name)
        if text not in result:
            result.append(text)
    return tuple(result)


def _validate_agent_url(value: object) -> str:
    url = _nonempty_string(value, "url")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise AgentCardError("Agent Card URL contains invalid characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AgentCardError("Agent Card URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AgentCardError("Agent Card URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise AgentCardError("Agent Card URL must not contain credentials or a fragment")
    host = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    fixture_host = bool(
        host in {"localhost", "localhost.localdomain", *_OFFLINE_FIXTURE_HOSTS}
        or host.endswith(_OFFLINE_FIXTURE_SUFFIXES)
        or (address is not None and address.is_loopback)
    )
    unsafe_host = bool(
        host in _BLOCKED_AGENT_HOSTS
        or host.endswith((".local", ".internal"))
        or (
            address is not None
            and (
                address.is_private
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            )
            and not address.is_loopback
        )
    )
    if unsafe_host:
        raise AgentCardError("Agent Card URL must not target a private network")
    if address is None:
        try:
            encoded_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise AgentCardError("Agent Card URL has an invalid hostname") from exc
        public_host = bool(
            encoded_host
            and len(encoded_host) <= 253
            and "." in encoded_host
            and all(
                _DNS_LABEL.fullmatch(part)
                for part in encoded_host.split(".")
            )
            and not encoded_host.endswith(
                (*_OFFLINE_FIXTURE_SUFFIXES, ".local", ".internal")
            )
            and encoded_host not in _OFFLINE_FIXTURE_HOSTS
        )
    else:
        public_host = not bool(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    if not fixture_host and not public_host:
        raise AgentCardError(
            "Agent Card URL must use a public host or local offline fixture"
        )
    if parsed.scheme == "http" and not (
        fixture_host
        and (
            host in {"localhost", "localhost.localdomain"}
            or (address is not None and address.is_loopback)
        )
    ):
        raise AgentCardError("non-local Agent Card URLs must use HTTPS")
    loopback_fixture = bool(
        host in {"localhost", "localhost.localdomain"}
        or (address is not None and address.is_loopback)
    )
    if (
        parsed.scheme == "https"
        and (not fixture_host or not loopback_fixture)
        and port not in (None, 443)
    ):
        raise AgentCardError("public Agent Card URLs must use the HTTPS default port")
    return url


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AgentCardError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_agent_card_size(payload: Mapping[str, Any]) -> int:
    try:
        encoder = json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        total = 0
        for chunk in encoder.iterencode(payload):
            total += len(chunk.encode("utf-8"))
            if total > MAX_AGENT_CARD_BYTES:
                raise AgentCardError(
                    "Agent Card exceeds the maximum fixture size"
                )
    except AgentCardError:
        raise
    except (RecursionError, TypeError, ValueError) as exc:
        raise AgentCardError("Agent Card must contain finite JSON values") from exc
    return total


def _validate_agent_card_shape(payload: Mapping[str, Any]) -> None:
    nodes = 0
    stack: list[tuple[Any, int, str]] = [(payload, 1, "$")]
    while stack:
        current, depth, path = stack.pop()
        nodes += 1
        if nodes > MAX_AGENT_CARD_NODES:
            raise AgentCardError("Agent Card contains too many values")
        if depth > MAX_AGENT_CARD_DEPTH:
            raise AgentCardError("Agent Card nesting is too deep")
        if isinstance(current, Mapping):
            if len(current) > MAX_AGENT_CARD_MAPPING_ITEMS:
                raise AgentCardError(f"{path} contains too many fields")
            for key, item in current.items():
                if not isinstance(key, str):
                    raise AgentCardError(f"{path} contains a non-string JSON key")
                if len(key) > MAX_AGENT_CARD_STRING_LENGTH:
                    raise AgentCardError(f"{path} contains an oversized field name")
                stack.append((item, depth + 1, f"{path}.{key}"))
        elif isinstance(current, (list, tuple)):
            if len(current) > MAX_AGENT_CARD_LIST_ITEMS:
                raise AgentCardError(f"{path} contains too many items")
            for index, item in enumerate(current):
                stack.append((item, depth + 1, f"{path}[{index}]"))
        elif isinstance(current, str):
            if len(current) > MAX_AGENT_CARD_STRING_LENGTH:
                raise AgentCardError(f"{path} exceeds the maximum string length")
        elif current is not None and not isinstance(
            current, (bool, int, float)
        ):
            raise AgentCardError(f"{path} is not a JSON value")


@dataclass(frozen=True)
class AgentSkill:
    """A single callable skill advertised by an A2A agent."""

    skill_id: str
    name: str
    description: str
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    input_modes: tuple[str, ...] = ()
    output_modes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
        }
        if self.tags:
            value["tags"] = list(self.tags)
        if self.examples:
            value["examples"] = list(self.examples)
        if self.input_modes:
            value["inputModes"] = list(self.input_modes)
        if self.output_modes:
            value["outputModes"] = list(self.output_modes)
        return value


@dataclass(frozen=True)
class AgentCard:
    """Validated, dependency-free representation of an A2A Agent Card."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...]
    protocol_version: str | None = None
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    default_input_modes: tuple[str, ...] = ()
    default_output_modes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "skills": [skill.to_dict() for skill in self.skills],
            "capabilities": dict(self.capabilities),
        }
        if self.protocol_version:
            value["protocolVersion"] = self.protocol_version
        if self.default_input_modes:
            value["defaultInputModes"] = list(self.default_input_modes)
        if self.default_output_modes:
            value["defaultOutputModes"] = list(self.default_output_modes)
        return value

    def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        """Convert advertised skills to shared capability contracts."""

        return tuple(
            CapabilityDescriptor(
                capability_id=stable_id("cap", self.url, skill.skill_id),
                name=skill.name,
                description=skill.description,
                source_kind="a2a-agent-card",
                source_url=self.url,
                tags=skill.tags,
            )
            for skill in self.skills
        )


def _card_url(payload: Mapping[str, Any]) -> object:
    direct = payload.get("url") or payload.get("endpoint")
    if direct:
        return direct
    interfaces = payload.get("supportedInterfaces")
    if isinstance(interfaces, list):
        for interface in interfaces:
            if isinstance(interface, Mapping) and interface.get("url"):
                return interface["url"]
    raise AgentCardError("Agent Card requires a URL or supported interface URL")


def validate_agent_card(payload: Mapping[str, Any]) -> AgentCard:
    """Validate an already-decoded Agent Card mapping."""

    if not isinstance(payload, Mapping):
        raise AgentCardError("Agent Card must be a JSON object")
    _validate_agent_card_shape(payload)
    _canonical_agent_card_size(payload)

    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise AgentCardError("Agent Card must advertise at least one skill")
    if len(raw_skills) > MAX_AGENT_SKILLS:
        raise AgentCardError("Agent Card advertises too many skills")

    skills: list[AgentSkill] = []
    seen_ids: set[str] = set()
    for index, raw_skill in enumerate(raw_skills):
        if not isinstance(raw_skill, Mapping):
            raise AgentCardError(f"skills[{index}] must be an object")
        skill_id = _nonempty_string(
            raw_skill.get("id") or raw_skill.get("skillId"),
            f"skills[{index}].id",
        )
        if skill_id in seen_ids:
            raise AgentCardError(f"duplicate skill id: {skill_id}")
        seen_ids.add(skill_id)
        skills.append(
            AgentSkill(
                skill_id=skill_id,
                name=_nonempty_string(
                    raw_skill.get("name"), f"skills[{index}].name"
                ),
                description=_nonempty_string(
                    raw_skill.get("description"), f"skills[{index}].description"
                ),
                tags=_string_tuple(raw_skill.get("tags"), f"skills[{index}].tags"),
                examples=_string_tuple(
                    raw_skill.get("examples"), f"skills[{index}].examples"
                ),
                input_modes=_string_tuple(
                    raw_skill.get("inputModes"), f"skills[{index}].inputModes"
                ),
                output_modes=_string_tuple(
                    raw_skill.get("outputModes"), f"skills[{index}].outputModes"
                ),
            )
        )

    capabilities = payload.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        raise AgentCardError("capabilities must be an object")

    protocol_version = payload.get("protocolVersion")
    if protocol_version is not None:
        protocol_version = _nonempty_string(protocol_version, "protocolVersion")

    return AgentCard(
        name=_nonempty_string(payload.get("name"), "name"),
        description=_nonempty_string(payload.get("description"), "description"),
        url=_validate_agent_url(_card_url(payload)),
        version=_nonempty_string(payload.get("version"), "version"),
        protocol_version=protocol_version,
        capabilities=dict(capabilities),
        default_input_modes=_string_tuple(
            payload.get("defaultInputModes"), "defaultInputModes"
        ),
        default_output_modes=_string_tuple(
            payload.get("defaultOutputModes"), "defaultOutputModes"
        ),
        skills=tuple(skills),
    )


def parse_agent_card(source: Mapping[str, Any] | str | bytes) -> AgentCard:
    """Parse an Agent Card fixture without performing network access."""

    if isinstance(source, Mapping):
        return validate_agent_card(source)
    if isinstance(source, str):
        encoded = source.encode("utf-8")
    elif isinstance(source, bytes):
        encoded = source
    else:
        raise AgentCardError("Agent Card source must be a mapping, JSON string, or bytes")
    if len(encoded) > MAX_AGENT_CARD_BYTES:
        raise AgentCardError("Agent Card exceeds the maximum fixture size")
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentCardError("Agent Card is not valid UTF-8 JSON") from exc
    return validate_agent_card(payload)


def capability_descriptors(card: AgentCard) -> tuple[CapabilityDescriptor, ...]:
    """Functional form of :meth:`AgentCard.capability_descriptors`."""

    return card.capability_descriptors()
