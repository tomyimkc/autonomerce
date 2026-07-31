"""Strict x402 PAYMENT-REQUIRED parsing.

x402 headers are untrusted network input. Parsing is size-bounded, rejects duplicate
JSON keys, validates addresses, preserves the asset address for policy matching, and
never chooses an option without exposing it to the deterministic payment gate.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Mapping

from autonomerce.contracts import Proposal, usdc, usdc_text

from .errors import PaymentValidationError, X402ParseError
from .models import (
    KNOWN_USDC_ASSETS,
    PaymentIntent,
    canonical_chain,
    normalize_idempotency_key,
    normalize_wallet_address,
    resource_host,
)


MAX_X402_HEADER_BYTES = 64 * 1024
MAX_X402_OPTIONS = 16


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise X402ParseError(f"duplicate JSON key in x402 requirement: {key}")
        result[key] = value
    return result


def _decode_header(value: str | bytes) -> Mapping[str, Any]:
    raw = value.encode("ascii") if isinstance(value, str) else bytes(value)
    if not raw or len(raw) > MAX_X402_HEADER_BYTES:
        raise X402ParseError("x402 PAYMENT-REQUIRED header is empty or too large")
    try:
        padded = raw + (b"=" * (-len(raw) % 4))
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, UnicodeError) as exc:
        raise X402ParseError("invalid base64 x402 PAYMENT-REQUIRED header") from exc
    if not decoded or len(decoded) > MAX_X402_HEADER_BYTES:
        raise X402ParseError("decoded x402 requirement is empty or too large")
    try:
        payload = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise X402ParseError("x402 PAYMENT-REQUIRED is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise X402ParseError("x402 PAYMENT-REQUIRED must be a JSON object")
    return payload


def _header_value(headers: Mapping[str, Any]) -> Any:
    for key, value in headers.items():
        if str(key).lower().replace("_", "-") == "payment-required":
            return value
    raise X402ParseError("missing PAYMENT-REQUIRED header")


def _as_payload(value: str | bytes | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, (str, bytes)):
        return _decode_header(value)
    if not isinstance(value, Mapping):
        raise X402ParseError("x402 requirement must be a header or mapping")
    if any(
        str(key).lower().replace("_", "-") == "payment-required"
        for key in value
    ):
        header = _header_value(value)
        if not isinstance(header, (str, bytes)):
            raise X402ParseError("PAYMENT-REQUIRED header must be text")
        return _decode_header(header)
    return dict(value)


def _atomic_usdc(value: Any, field_name: str) -> Decimal:
    text = str(value).strip()
    if not text.isdigit():
        raise X402ParseError(f"{field_name} must be a non-negative atomic-unit integer")
    try:
        return usdc(Decimal(text) / Decimal("1000000"))
    except (InvalidOperation, ValueError) as exc:
        raise X402ParseError(f"invalid {field_name}") from exc


def _decimal_usdc(value: Any, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise X402ParseError(f"{field_name} must not use binary floating point")
    text = str(value).strip()
    if text.startswith("$"):
        text = text[1:]
    try:
        return usdc(text)
    except (InvalidOperation, ValueError) as exc:
        raise X402ParseError(f"invalid {field_name}") from exc


def _amount(option: Mapping[str, Any]) -> Decimal:
    parsers = {
        "amountUsdc": _decimal_usdc,
        "price": _decimal_usdc,
        "amount": _atomic_usdc,
        "maxAmountRequired": _atomic_usdc,
    }
    supplied = [
        parser(option[field_name], field_name)
        for field_name, parser in parsers.items()
        if field_name in option
    ]
    if not supplied:
        raise X402ParseError("x402 payment option is missing an amount")
    if len(set(supplied)) != 1:
        raise X402ParseError("conflicting x402 amount aliases")
    amount = supplied[0]
    if amount <= 0:
        raise X402ParseError("x402 amount must be greater than zero")
    return amount


def _optional_identifier(
    option: Mapping[str, Any], payload: Mapping[str, Any]
) -> str | None:
    containers: list[Mapping[str, Any]] = [option, payload]
    for key in ("extra", "extensions"):
        nested = option.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    identifiers: list[str] = []
    for container in containers:
        for key in (
            "paymentIdentifier",
            "payment-identifier",
            "payment_id",
            "idempotencyKey",
        ):
            value = container.get(key)
            if isinstance(value, Mapping):
                value = value.get("id") or value.get("value")
            if value is not None and str(value).strip():
                try:
                    identifiers.append(normalize_idempotency_key(str(value)))
                except ValueError as exc:
                    raise X402ParseError(
                        "invalid x402 payment identifier"
                    ) from exc
    unique = tuple(dict.fromkeys(identifiers))
    if len(unique) > 1:
        raise X402ParseError("conflicting x402 payment identifier aliases")
    return unique[0] if unique else None


def _resource_url(payload: Mapping[str, Any]) -> str | None:
    resource = payload.get("resource")
    values: list[str] = []
    if isinstance(resource, Mapping):
        value = resource.get("url")
        if value:
            values.append(str(value).strip())
    value = payload.get("resourceUrl")
    if value:
        values.append(str(value).strip())
    unique = tuple(dict.fromkeys(values))
    if len(unique) > 1:
        raise X402ParseError("conflicting x402 resource URL aliases")
    return unique[0] if unique else None


def _classify_token(chain: str, asset: str | None, option: Mapping[str, Any]) -> str:
    explicit_values = [
        str(option[key]).strip().upper()
        for key in ("token", "currency")
        if option.get(key) is not None and str(option[key]).strip()
    ]
    unique_explicit = tuple(dict.fromkeys(explicit_values))
    if len(unique_explicit) > 1:
        raise X402ParseError("conflicting x402 token aliases")
    if unique_explicit:
        return unique_explicit[0]
    if asset:
        if asset.upper() == "USDC":
            return "USDC"
        if asset.lower() in KNOWN_USDC_ASSETS.get(chain, ()):
            return "USDC"
    return "UNKNOWN"


def _canonical_json(value: Any) -> Any:
    """Return a stable JSON-compatible copy for requirement fingerprinting."""

    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        raise X402ParseError(
            "x402 requirement metadata must not use binary floating point"
        )
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise X402ParseError("x402 requirement metadata is not JSON-compatible")


@dataclass(frozen=True)
class X402PaymentRequirement:
    x402_version: int
    scheme: str
    network: str
    chain: str
    amount_usdc: Decimal
    pay_to: str
    token: str
    asset: str | None = None
    requirement_id: str | None = None
    resource_url: str | None = None
    max_timeout_seconds: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    _fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            chain = canonical_chain(self.chain)
            pay_to = normalize_wallet_address(self.pay_to, chain)
            amount = usdc(self.amount_usdc)
            requirement_id = (
                normalize_idempotency_key(self.requirement_id)
                if self.requirement_id is not None
                else None
            )
        except ValueError as exc:
            raise X402ParseError("invalid normalized x402 requirement") from exc
        if amount <= 0:
            raise X402ParseError("x402 amount must be greater than zero")
        scheme = str(self.scheme).strip().lower()
        network = str(self.network).strip()
        token = str(self.token).strip().upper()
        if not scheme or not network or not token:
            raise X402ParseError(
                "x402 scheme, network, and token are required"
            )
        asset = str(self.asset).strip() if self.asset else None
        if asset:
            if asset.upper() == token:
                asset = token
            else:
                try:
                    asset = normalize_wallet_address(asset, chain)
                except ValueError as exc:
                    raise X402ParseError("invalid x402 asset") from exc
        resource_url = str(self.resource_url).strip() if self.resource_url else None
        if resource_url and resource_host(resource_url) is None:
            raise X402ParseError("invalid x402 resource URL")
        canonical_extra = _canonical_json(self.extra)
        fingerprint_payload = {
            "version": int(self.x402_version),
            "scheme": scheme,
            "network": network,
            "chain": chain,
            "amountUsdc": usdc_text(amount),
            "payTo": pay_to.lower(),
            "token": token,
            "asset": asset.lower() if asset else None,
            "requirementId": requirement_id,
            "resourceUrl": resource_url,
            "maxTimeoutSeconds": self.max_timeout_seconds,
            "extra": canonical_extra,
        }
        encoded = json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "chain", chain)
        object.__setattr__(self, "amount_usdc", amount)
        object.__setattr__(self, "pay_to", pay_to)
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "requirement_id", requirement_id)
        object.__setattr__(self, "resource_url", resource_url)
        object.__setattr__(self, "extra", canonical_extra)
        object.__setattr__(
            self,
            "_fingerprint",
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def to_intent(
        self,
        proposal: Proposal,
        *,
        idempotency_key: str,
        payer_wallet: str,
        expected_chain: str,
        expected_token: str,
        expected_asset: str | None,
        expected_payee_wallet: str,
        expected_resource_url: str | None,
        expected_requirement_id: str,
        expected_scheme: str = "exact",
    ) -> PaymentIntent:
        """Bind an x402 requirement to independently expected payment fields."""

        if self.amount_usdc != proposal.price_usdc:
            raise PaymentValidationError(
                "x402 amount does not exactly match the accepted proposal"
            )
        normalized_chain = canonical_chain(expected_chain)
        if self.chain != normalized_chain:
            raise PaymentValidationError(
                "x402 chain does not match the expected payment chain"
            )
        normalized_token = str(expected_token).strip().upper()
        if self.token != normalized_token:
            raise PaymentValidationError(
                "x402 token does not match the expected payment token"
            )
        normalized_asset = str(expected_asset).strip() if expected_asset else None
        if normalized_asset:
            if normalized_asset.upper() == normalized_token:
                normalized_asset = normalized_token
            else:
                normalized_asset = normalize_wallet_address(
                    normalized_asset, normalized_chain
                )
        actual_asset = self.asset.lower() if self.asset else None
        compared_asset = normalized_asset.lower() if normalized_asset else None
        if actual_asset != compared_asset:
            raise PaymentValidationError(
                "x402 asset does not match the expected payment asset"
            )
        normalized_payee = normalize_wallet_address(
            expected_payee_wallet, normalized_chain
        )
        if self.pay_to.lower() != normalized_payee.lower():
            raise PaymentValidationError(
                "x402 payee does not match the expected destination wallet"
            )
        normalized_resource = (
            str(expected_resource_url).strip()
            if expected_resource_url
            else None
        )
        if self.resource_url != normalized_resource:
            raise PaymentValidationError(
                "x402 resource does not match the expected resource URL"
            )
        if self.resource_url:
            seller_host = resource_host(proposal.seller_agent_url)
            if (
                seller_host is None
                or resource_host(self.resource_url) != seller_host
            ):
                raise PaymentValidationError(
                    "x402 resource host does not match the proposal seller"
                )
        normalized_requirement_id = normalize_idempotency_key(
            expected_requirement_id
        )
        if (
            self.requirement_id is None
            or self.requirement_id != normalized_requirement_id
        ):
            raise PaymentValidationError(
                "x402 identifier does not match the expected payment identifier"
            )
        normalized_scheme = str(expected_scheme).strip().lower()
        if self.scheme != normalized_scheme:
            raise PaymentValidationError(
                "x402 scheme does not match the expected payment scheme"
            )
        return PaymentIntent.from_proposal(
            proposal,
            idempotency_key=idempotency_key,
            chain=self.chain,
            payer_wallet=payer_wallet,
            payee_wallet=self.pay_to,
            token=self.token,
            asset=self.asset,
            scheme=self.scheme,
            x402_requirement_id=self.requirement_id,
            x402_requirement_fingerprint=self.fingerprint,
            resource_url=self.resource_url,
            metadata={
                "x402Version": self.x402_version,
                "x402RequirementFingerprint": self.fingerprint,
            },
        )


def parse_x402_payment_requirements(
    value: str | bytes | Mapping[str, Any],
) -> tuple[X402PaymentRequirement, ...]:
    payload = _as_payload(value)
    try:
        version = int(payload.get("x402Version", 1))
    except (TypeError, ValueError) as exc:
        raise X402ParseError("invalid x402Version") from exc
    if version not in {1, 2}:
        raise X402ParseError("unsupported x402Version")

    raw_options = payload.get("accepts")
    if raw_options is None and all(
        field in payload for field in ("scheme", "network", "payTo")
    ):
        raw_options = [payload]
    if (
        not isinstance(raw_options, list)
        or not raw_options
        or len(raw_options) > MAX_X402_OPTIONS
    ):
        raise X402ParseError("x402 accepts must contain 1-16 payment options")

    resource_url = _resource_url(payload)
    parsed: list[X402PaymentRequirement] = []
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            raise X402ParseError("x402 payment option must be an object")
        scheme = str(raw_option.get("scheme", "")).strip().lower()
        network = str(raw_option.get("network", "")).strip()
        pay_to = str(raw_option.get("payTo", "")).strip()
        if not scheme or not network or not pay_to:
            raise X402ParseError(
                "x402 payment option requires scheme, network, and payTo"
            )
        try:
            chain = canonical_chain(network)
            pay_to = normalize_wallet_address(pay_to, chain)
            asset_value = raw_option.get("asset")
            asset = str(asset_value).strip() if asset_value else None
            if asset and asset.upper() != "USDC":
                asset = normalize_wallet_address(asset, chain)
        except ValueError as exc:
            raise X402ParseError(
                "x402 option contains an invalid chain, payee, or asset address"
            ) from exc
        token = _classify_token(chain, asset, raw_option)
        timeout_value = raw_option.get("maxTimeoutSeconds")
        timeout: int | None = None
        if timeout_value is not None:
            try:
                timeout = int(timeout_value)
            except (TypeError, ValueError) as exc:
                raise X402ParseError("invalid maxTimeoutSeconds") from exc
            if timeout < 1 or timeout > 86400:
                raise X402ParseError("maxTimeoutSeconds is outside safe bounds")
        extra = raw_option.get("extra")
        parsed.append(
            X402PaymentRequirement(
                x402_version=version,
                scheme=scheme,
                network=network,
                chain=chain,
                amount_usdc=_amount(raw_option),
                pay_to=pay_to,
                token=token,
                asset=asset,
                requirement_id=_optional_identifier(raw_option, payload),
                resource_url=resource_url,
                max_timeout_seconds=timeout,
                extra=dict(extra) if isinstance(extra, Mapping) else {},
            )
        )
    return tuple(parsed)


def parse_x402_payment_requirement(
    value: str | bytes | Mapping[str, Any],
    *,
    option_index: int = 0,
) -> X402PaymentRequirement:
    requirements = parse_x402_payment_requirements(value)
    if option_index < 0 or option_index >= len(requirements):
        raise X402ParseError("x402 payment option index is out of range")
    return requirements[option_index]
