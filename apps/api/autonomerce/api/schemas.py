"""Pydantic request models for the Autonomerce API."""

from __future__ import annotations

from decimal import Decimal
import ipaddress
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


MAX_TEXT_LENGTH = 8_192
MAX_URL_LENGTH = 2_048
MAX_COLLECTION_ITEMS = 128
MAX_MAPPING_ITEMS = 512
_BLOCKED_NETWORK_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
_FIXTURE_HOSTS = {"example.com", "example.net", "example.org"}
_FIXTURE_SUFFIXES = (".example", ".test", ".invalid")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _ip_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _is_public_host(host: str) -> bool:
    address = _ip_address(host)
    if address is not None:
        return not bool(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    if (
        host in _BLOCKED_NETWORK_HOSTS
        or host in _FIXTURE_HOSTS
        or host.endswith((*_FIXTURE_SUFFIXES, ".local", ".internal"))
        or "." not in host
    ):
        return False
    try:
        encoded = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    return bool(
        encoded
        and len(encoded) <= 253
        and all(_DNS_LABEL.fullmatch(part) for part in encoded.split("."))
    )


def _is_offline_fixture_host(host: str) -> bool:
    address = _ip_address(host)
    if address is not None:
        return address.is_loopback
    return bool(
        host in {"localhost", "localhost.localdomain", *_FIXTURE_HOSTS}
        or host.endswith(_FIXTURE_SUFFIXES)
    )


def validate_network_url(
    value: str,
    *,
    offline: bool,
    label: str,
) -> str:
    """Validate an ingested seller/buyer URL without performing a network lookup."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a URL")
    url = value.strip()
    if (
        not url
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise ValueError(f"{label} must be a valid network URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid network URL") from exc
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            f"{label} must be an absolute credential-free HTTP(S) URL"
        )

    public_https = (
        scheme == "https"
        and port in (None, 443)
        and _is_public_host(host)
    )
    if public_https:
        return url

    fixture = _is_offline_fixture_host(host)
    address = _ip_address(host)
    loopback = bool(address is not None and address.is_loopback)
    local_http = host in {"localhost", "localhost.localdomain"} or loopback
    fixture_url = fixture and (
        (local_http and scheme in {"http", "https"})
        or (not local_http and scheme == "https" and port in (None, 443))
    )
    if offline and fixture_url:
        return url
    if offline:
        raise ValueError(
            f"{label} must be public HTTPS or a local offline fixture URL"
        )
    raise ValueError(f"{label} must be a public HTTPS URL")


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )


class SellerCreate(APIModel):
    name: str = Field(min_length=1, max_length=160)
    agent_url: str = Field(
        min_length=1,
        max_length=MAX_URL_LENGTH,
        validation_alias=AliasChoices(
            "agentUrl",
            "agentCardUrl",
            "sellerAgentUrl",
            "agent_url",
            "agent_card_url",
        ),
    )
    source_kind: str = Field(default="a2a", min_length=1, max_length=64)
    manifest: dict[str, Any] = Field(
        default_factory=dict, max_length=MAX_MAPPING_ITEMS
    )
    wallet_address: str | None = Field(
        default=None,
        max_length=256,
        validation_alias=AliasChoices(
            "walletAddress",
            "publicWalletAddress",
            "payeeWallet",
            "wallet_address",
        ),
    )
    network: str = Field(default="ARC-TESTNET", min_length=1, max_length=64)


class CapabilityCreate(APIModel):
    capability_id: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    input_schema: dict[str, Any] = Field(
        default_factory=dict, max_length=MAX_MAPPING_ITEMS
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict, max_length=MAX_MAPPING_ITEMS
    )
    source_kind: str = Field(default="manual", min_length=1, max_length=64)
    source_url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    tags: list[str] = Field(default_factory=list, max_length=MAX_COLLECTION_ITEMS)


class SKUPreviewRequest(APIModel):
    capability_ids: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    base_price_usdc: Decimal = Decimal("1")
    maximum_latency_seconds: int = Field(default=300, ge=1)
    capacity_per_hour: int = Field(default=1, ge=1)
    acceptance_criteria: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    variants: int = Field(default=1, ge=1, le=3)


class PolicyBindRequest(APIModel):
    minimum_price_usdc: Decimal = Field(ge=0)
    maximum_price_usdc: Decimal = Field(ge=0)
    maximum_discount_fraction: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    maximum_open_proposals: int = Field(default=10, ge=1)
    maximum_tasks_per_hour: int = Field(default=20, ge=1)
    allowed_buyer_hosts: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    blocked_buyer_hosts: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    allowed_chains: list[str] = Field(
        default_factory=lambda: ["BASE", "ARC-TESTNET"],
        max_length=MAX_COLLECTION_ITEMS,
    )
    allowed_token: str = Field(default="USDC", min_length=1, max_length=32)
    unattended: bool = True


class ProspectCreate(APIModel):
    buyer_agent_url: str = Field(
        min_length=1,
        max_length=MAX_URL_LENGTH,
        validation_alias=AliasChoices(
            "buyerAgentUrl", "buyerAgent", "buyer_agent_url"
        ),
    )
    desired_outcome: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    maximum_price_usdc: Decimal = Field(ge=0)
    required_tags: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    input_payload: dict[str, Any] = Field(
        default_factory=dict, max_length=MAX_MAPPING_ITEMS
    )
    expires_at: str | None = Field(default=None, max_length=128)
    opted_in: bool = False
    consent_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        validation_alias=AliasChoices(
            "consentReference",
            "consentRef",
            "consent_reference",
        ),
    )


class ProposalCreate(APIModel):
    seller_id: str | None = Field(default=None, max_length=200)
    seller_agent_url: str | None = Field(
        default=None,
        max_length=MAX_URL_LENGTH,
        validation_alias=AliasChoices(
            "sellerAgentUrl", "sellerAgent", "seller_agent_url"
        ),
    )
    buyer_need_id: str = Field(min_length=1, max_length=200)
    sku_id: str = Field(min_length=1, max_length=200)
    problem_observed: str = Field(default="", max_length=MAX_TEXT_LENGTH)
    offered_outcome: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    price_usdc: Decimal | None = Field(default=None, ge=0)
    delivery_seconds: int | None = Field(default=None, ge=1)
    acceptance_criteria: list[str] = Field(
        default_factory=list, max_length=MAX_COLLECTION_ITEMS
    )
    expires_at: str | None = Field(default=None, max_length=128)


class CounterRequest(APIModel):
    price_usdc: Decimal = Field(ge=0)
    delivery_seconds: int | None = Field(default=None, ge=1)
    offered_outcome: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    acceptance_criteria: list[str] | None = Field(
        default=None, max_length=MAX_COLLECTION_ITEMS
    )


class AcceptRequest(APIModel):
    payer_wallet: str | None = Field(default=None, max_length=256)


class NegotiationRequest(APIModel):
    action: Literal["counter", "accept", "decline"]
    price_usdc: Decimal | None = Field(default=None, ge=0)
    delivery_seconds: int | None = Field(default=None, ge=1)
    offered_outcome: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    acceptance_criteria: list[str] | None = Field(
        default=None, max_length=MAX_COLLECTION_ITEMS
    )
    chain: str | None = Field(default=None, min_length=1, max_length=64)
    token: str | None = Field(default=None, min_length=1, max_length=32)
    payer_wallet: str | None = Field(default=None, max_length=256)


class PaymentRequest(APIModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    chain: str = Field(default="ARC-TESTNET", min_length=1, max_length=64)
    token: str = Field(default="USDC", min_length=1, max_length=32)
    payer_wallet: str | None = Field(default=None, max_length=256)
    public_receipt: bool = False


class FulfillmentRequest(APIModel):
    artifact: dict[str, Any] | None = Field(
        default=None, max_length=MAX_MAPPING_ITEMS
    )
    acceptance_results: dict[str, bool] = Field(
        default_factory=dict, max_length=MAX_COLLECTION_ITEMS
    )
    validator: str | None = Field(default=None, max_length=200)


class ReceiptPublishRequest(APIModel):
    consent_reference: str = Field(min_length=1, max_length=512)
    fields: list[
        Literal["payment", "fulfillment", "acceptanceVerdict"]
    ] = Field(
        default_factory=lambda: [
            "payment",
            "fulfillment",
            "acceptanceVerdict",
        ],
        min_length=1,
        max_length=3,
    )
