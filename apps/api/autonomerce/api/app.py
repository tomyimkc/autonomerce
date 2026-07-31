"""FastAPI application factory composing the offline Autonomerce workflow."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from importlib import import_module
import inspect
import json
import os
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from autonomerce.contracts import (
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    ContractError,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
    usdc_text,
)
from autonomerce.payments import (
    ExecutionResult,
    KNOWN_USDC_ASSETS,
    PaymentReplayError,
    PaymentValidationError,
    ReceiptVerificationError,
    normalize_wallet_address,
)
from autonomerce.payments.reconciliation import TransactionEvidenceHook
from autonomerce.payments.store import PaymentReconciliationStatus

from .adapters import (
    AdapterBundle,
    FulfillmentExecution,
    PaymentExecution,
    load_optional_adapters,
)
from .auth import BearerAuthenticator, Principal, principal_from_request
from .rate_limit import RateLimitExceeded, RequestLimiter
from .reconciliation import PaymentReconciliationAPI
from .repository import (
    InMemoryRepository,
    ProspectRecord,
    ReceiptPublication,
    RepositoryDurability,
    RepositoryProtocol,
    SettlementAuthorization,
    payment_matches_settlement_authorization,
)
from .schemas import (
    AcceptRequest,
    APIModel,
    CapabilityCreate,
    CounterRequest,
    FulfillmentRequest,
    NegotiationRequest,
    PaymentRequest,
    PolicyBindRequest,
    ProposalCreate,
    ProspectCreate,
    ReceiptPublishRequest,
    SellerCreate,
    SKUPreviewRequest,
    validate_network_url,
)


_NORMALIZED_SECRET_KEYS = {
    "apikey",
    "accesstoken",
    "authorization",
    "bearertoken",
    "circlesessiontoken",
    "clientsecret",
    "credential",
    "credentials",
    "googlecredentials",
    "otp",
    "password",
    "privatekey",
    "privatekeypem",
    "recoverycode",
    "recoverymaterial",
    "refreshtoken",
    "secret",
    "seedphrase",
    "sessiontoken",
}
_SECRET_KEY_SUFFIXES = (
    "accesstoken",
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwd",
    "privatekey",
    "privatekeypem",
    "recoverycode",
    "recoverymaterial",
    "refreshtoken",
    "secret",
    "seedphrase",
    "sessiontoken",
    "token",
)
_BEARER_CREDENTIAL = re.compile(
    r"(?i)(?:^|[\s:=,;])bearer\s+[A-Za-z0-9._~+/=-]{4,}"
)
_BASIC_CREDENTIAL = re.compile(
    r"(?i)(?:^|[\s:=,;])basic\s+([A-Za-z0-9+/]{4,}={0,2})(?=$|[\s,;])"
)
_PEM_CREDENTIAL = re.compile(
    r"-----BEGIN [A-Z0-9][A-Z0-9 -]{0,80}-----"
)
_CREDENTIALIZED_URL = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s@]+@"
)
_OPEN_PROPOSAL_STATES = {
    ProposalState.OFFERED,
    ProposalState.COUNTERED,
    ProposalState.ACCEPTED,
}
_MAX_REQUEST_BODY_BYTES = 256 * 1024
_MAX_JSON_DEPTH = 20
_MAX_JSON_NODES = 10_000
_OFFLINE_PUBLIC_PATHS = {
    "/health",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}
_NON_OFFLINE_PUBLIC_PATHS = {"/health"}
_SUPPORTED_SCHEMA_KEYS = {
    "$id",
    "$schema",
    "additionalProperties",
    "description",
    "enum",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "properties",
    "required",
    "title",
    "type",
}
_JSON_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}


class ReconciliationResolutionRequest(APIModel):
    reason_code: str = Field(min_length=1, max_length=96)
    explanation: str = Field(min_length=1, max_length=400)
    evidence_reference: str = Field(min_length=1, max_length=400)


class ReconciliationConfirmationRequest(APIModel):
    transaction_hash: str = Field(min_length=1, max_length=256)
    amount_usdc: Decimal = Field(gt=0)
    chain: str = Field(min_length=1, max_length=64)
    payer_wallet: str = Field(min_length=1, max_length=256)
    payee_wallet: str = Field(min_length=1, max_length=256)
    evidence_reference: str = Field(min_length=1, max_length=400)
    confirmed_at: str | None = Field(default=None, max_length=128)
    explorer_url: str | None = Field(default=None, max_length=2048)
    provider_reference: str | None = Field(default=None, max_length=256)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = _json_bytes(value)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="payload must contain finite JSON values"
        ) from exc
    return encoded


def _default_wallet(identifier: str) -> str:
    return f"0x{hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:40]}"


def _load_publication_consent_verifier(specification: str) -> Any:
    module_name, separator, attribute = specification.partition(":")
    if (
        separator != ":"
        or not module_name.strip()
        or not attribute.strip()
    ):
        raise RuntimeError(
            "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY must be "
            "module:function"
        )
    try:
        factory = getattr(import_module(module_name.strip()), attribute.strip())
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "publication consent verifier factory could not be imported"
        ) from exc
    if not callable(factory):
        raise RuntimeError("publication consent verifier factory is not callable")
    verifier = factory()
    if not callable(verifier):
        raise RuntimeError(
            "publication consent verifier factory returned no callable verifier"
        )
    return verifier


def _accepted_payer_wallet(
    payment_adapter: Any,
    *,
    chain: str,
    requested_payer_wallet: str | None,
    non_offline: bool,
    offline_identifier: str,
) -> str:
    raw_allowed = getattr(payment_adapter, "allowed_payer_wallets", ())
    if raw_allowed is None:
        raw_allowed = ()
    if isinstance(raw_allowed, str):
        raw_allowed = (raw_allowed,)
    try:
        allowed = tuple(
            dict.fromkeys(
                normalize_wallet_address(str(value), chain).lower()
                for value in raw_allowed
            )
        )
    except (TypeError, PaymentValidationError) as exc:
        raise HTTPException(
            status_code=503,
            detail="payment adapter has an invalid payer-wallet configuration",
        ) from exc

    if non_offline and not allowed:
        raise HTTPException(
            status_code=409,
            detail="live acceptance requires an owner-configured payer allowlist",
        )
    if requested_payer_wallet is not None:
        try:
            requested = normalize_wallet_address(
                requested_payer_wallet, chain
            ).lower()
        except PaymentValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if allowed and requested not in allowed:
            raise HTTPException(
                status_code=409,
                detail="requested payer wallet is not owner-allowlisted",
            )
        return requested

    if len(allowed) == 1:
        return allowed[0]
    if non_offline:
        detail = (
            "live acceptance requires one configured payer wallet"
            if not allowed
            else "live acceptance requires an explicit payer wallet when "
            "multiple owner-allowlisted wallets exist"
        )
        raise HTTPException(status_code=409, detail=detail)
    return _default_wallet(offline_identifier)


def _json_type_matches(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, (list, tuple)),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float, Decimal))
        and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return bool(check and check(value))


def _schema_definition_errors(
    schema: Mapping[str, Any], path: str = "$"
) -> list[str]:
    errors: list[str] = []
    unknown = set(schema) - _SUPPORTED_SCHEMA_KEYS
    if unknown:
        errors.append(f"{path}: unsupported keywords {sorted(unknown)}")

    expected_type = schema.get("type")
    if expected_type is not None:
        types = (
            [expected_type]
            if isinstance(expected_type, str)
            else expected_type
            if isinstance(expected_type, list)
            else []
        )
        if (
            not types
            or any(
                not isinstance(item, str) or item not in _JSON_TYPES
                for item in types
            )
        ):
            errors.append(f"{path}.type: invalid JSON type")

    enum = schema.get("enum")
    if enum is not None and (
        not isinstance(enum, list) or not enum
    ):
        errors.append(f"{path}.enum: must be a non-empty array")

    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or any(not isinstance(item, str) or not item for item in required)
        or len(set(required)) != len(required)
    ):
        errors.append(f"{path}.required: must contain unique non-empty strings")

    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, Mapping):
        errors.append(f"{path}.properties: must be an object")
    elif isinstance(properties, Mapping):
        for key, nested in properties.items():
            if not isinstance(key, str) or not key:
                errors.append(f"{path}.properties: property names must be non-empty")
            if not isinstance(nested, Mapping):
                errors.append(f"{path}.{key}: schema must be an object")
            else:
                errors.extend(_schema_definition_errors(nested, f"{path}.{key}"))

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, Mapping)):
        errors.append(
            f"{path}.additionalProperties: must be boolean or a schema object"
        )
    elif isinstance(additional, Mapping):
        errors.extend(
            _schema_definition_errors(
                additional, f"{path}.additionalProperties"
            )
        )

    items = schema.get("items")
    if items is not None and not isinstance(items, Mapping):
        errors.append(f"{path}.items: must be a schema object")
    elif isinstance(items, Mapping):
        errors.extend(_schema_definition_errors(items, f"{path}.items"))

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        value = schema.get(keyword)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            errors.append(f"{path}.{keyword}: must be a non-negative integer")
    for minimum_key, maximum_key in (
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
    ):
        minimum = schema.get(minimum_key)
        maximum = schema.get(maximum_key)
        if (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            errors.append(f"{path}: {minimum_key} exceeds {maximum_key}")
    for keyword in ("minimum", "maximum"):
        value = schema.get(keyword)
        if value is not None:
            try:
                Decimal(str(value))
            except (InvalidOperation, ValueError):
                errors.append(f"{path}.{keyword}: must be numeric")
    return errors


def _require_valid_schema(
    schema: Mapping[str, Any], *, subject: str, status_code: int
) -> None:
    errors = _schema_definition_errors(schema)
    if errors:
        raise HTTPException(
            status_code=status_code,
            detail=f"{subject} is not a supported JSON schema: {errors[0]}",
        )


def _schema_errors(
    value: Any, schema: Mapping[str, Any], path: str = "$"
) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    expected_types = (
        [expected_type]
        if isinstance(expected_type, str)
        else list(expected_type)
        if isinstance(expected_type, list)
        else []
    )
    if expected_types and not any(
        _json_type_matches(value, item) for item in expected_types
    ):
        return [f"{path}:type"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}:enum")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key}:required")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, nested_schema in properties.items():
                if key in value and isinstance(nested_schema, Mapping):
                    errors.extend(
                        _schema_errors(value[key], nested_schema, f"{path}.{key}")
                    )
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key}:additionalProperties")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                additional_schema = schema["additionalProperties"]
                for key in value:
                    if key not in properties:
                        errors.extend(
                            _schema_errors(
                                value[key],
                                additional_schema,
                                f"{path}.{key}",
                            )
                        )

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{path}:minItems")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            errors.append(f"{path}:maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(
                    _schema_errors(item, item_schema, f"{path}[{index}]")
                )

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{path}:minLength")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            errors.append(f"{path}:maxLength")

    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        try:
            number = Decimal(str(value))
            if "minimum" in schema and number < Decimal(str(schema["minimum"])):
                errors.append(f"{path}:minimum")
            if "maximum" in schema and number > Decimal(str(schema["maximum"])):
                errors.append(f"{path}:maximum")
        except (InvalidOperation, ValueError):
            errors.append(f"{path}:number")
    return errors


def _validate_artifact(
    artifact: Mapping[str, Any],
    sku: ServiceSKU,
    proposal: Proposal,
    adapter_results: Mapping[str, bool],
) -> tuple[dict[str, bool], bool]:
    """Apply deterministic schema and named-criterion validation."""

    results = dict(adapter_results)
    non_empty = bool(artifact)
    results["non_empty_artifact"] = non_empty
    schema = sku.output_schema
    schema_errors = _schema_errors(artifact, schema)
    schema_ok = not schema_errors
    for error in schema_errors:
        results[f"$schema.{error}"] = False
    required = schema.get("required", ())
    if isinstance(required, list):
        for name in required:
            present = name in artifact
            results[f"$schema.required.{name}"] = present
            results[f"required_field:{name}"] = present
    results["output_schema_valid"] = schema_ok

    criteria_ok = all(
        bool(results.get(criterion, False))
        for criterion in proposal.acceptance_criteria
    )
    return results, non_empty and schema_ok and criteria_ok


def _normalize_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _is_secret_key(normalized: str) -> bool:
    return normalized in _NORMALIZED_SECRET_KEYS or normalized.endswith(
        _SECRET_KEY_SUFFIXES
    )


def _contains_basic_credential(value: str) -> bool:
    for match in _BASIC_CREDENTIAL.finditer(value):
        encoded = match.group(1)
        padding = "=" * (-len(encoded) % 4)
        try:
            decoded = base64.b64decode(
                encoded + padding,
                validate=True,
            )
        except (binascii.Error, ValueError):
            continue
        if b":" in decoded:
            return True
    return False


def _contains_credential_value(value: str) -> bool:
    return bool(
        _BEARER_CREDENTIAL.search(value)
        or _contains_basic_credential(value)
        or _PEM_CREDENTIAL.search(value)
        or _CREDENTIALIZED_URL.search(value)
    )


def _reject_secret_fields(
    value: Any,
    path: str = "payload",
    *,
    status_code: int = 400,
    allowed_root_keys: frozenset[str] = frozenset(),
) -> None:
    root_path = path
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        current, current_path = stack.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                normalized = _normalize_key(key)
                if (
                    _is_secret_key(normalized)
                    and not (
                        current_path == root_path
                        and normalized in allowed_root_keys
                    )
                ):
                    raise HTTPException(
                        status_code=status_code,
                        detail=(
                            "secret-bearing field is not accepted: "
                            f"{current_path}.{key}"
                        ),
                    )
                stack.append((item, f"{current_path}.{key}"))
        elif isinstance(current, (list, tuple)):
            for index, item in enumerate(current):
                stack.append((item, f"{current_path}[{index}]"))
        elif isinstance(current, str) and _contains_credential_value(current):
            raise HTTPException(
                status_code=status_code,
                detail=(
                    "credential-bearing value is not accepted: "
                    f"{current_path}"
                ),
            )


def _validate_json_shape(value: Any) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise HTTPException(
                status_code=413, detail="JSON payload contains too many values"
            )
        if depth > _MAX_JSON_DEPTH:
            raise HTTPException(
                status_code=413, detail="JSON payload nesting is too deep"
            )
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _invoke_adapter(method: Any, /, *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await asyncio.to_thread(method, *args, **kwargs)
    return await _resolve(result)


def _capability_dict(capability: CapabilityDescriptor) -> dict[str, Any]:
    return {
        "capabilityId": capability.capability_id,
        "name": capability.name,
        "description": capability.description,
        "inputSchema": dict(capability.input_schema),
        "outputSchema": dict(capability.output_schema),
        "sourceKind": capability.source_kind,
        "sourceUrl": capability.source_url,
        "tags": list(capability.tags),
    }


def _sku_dict(sku: ServiceSKU) -> dict[str, Any]:
    value = sku.to_dict()
    return {
        "skuId": value["sku_id"],
        "capabilityId": value["capability_id"],
        "name": value["name"],
        "outcome": value["outcome"],
        "basePriceUsdc": value["base_price_usdc"],
        "inputSchema": value["input_schema"],
        "outputSchema": value["output_schema"],
        "acceptanceCriteria": list(value["acceptance_criteria"]),
        "maximumLatencySeconds": value["maximum_latency_seconds"],
        "capacityPerHour": value["capacity_per_hour"],
    }


def _policy_dict(policy: CommercialPolicy) -> dict[str, Any]:
    return {
        "policyId": policy.policy_id,
        "ownerId": policy.owner_id,
        "minimumPriceUsdc": usdc_text(policy.minimum_price_usdc),
        "maximumPriceUsdc": usdc_text(policy.maximum_price_usdc),
        "maximumDiscountFraction": format(policy.maximum_discount_fraction, "f"),
        "maximumOpenProposals": policy.maximum_open_proposals,
        "maximumTasksPerHour": policy.maximum_tasks_per_hour,
        "allowedBuyerHosts": list(policy.allowed_buyer_hosts),
        "blockedBuyerHosts": list(policy.blocked_buyer_hosts),
        "allowedChains": list(policy.allowed_chains),
        "allowedToken": policy.allowed_token,
        "unattended": policy.unattended,
    }


def _prospect_dict(prospect: ProspectRecord) -> dict[str, Any]:
    need = prospect.need
    return {
        "needId": need.need_id,
        "buyerAgentUrl": need.buyer_agent_url,
        "desiredOutcome": need.desired_outcome,
        "maximumPriceUsdc": usdc_text(need.maximum_price_usdc),
        "requiredTags": list(need.required_tags),
        "expiresAt": need.expires_at,
        "optedIn": prospect.opted_in,
        "consentReference": prospect.consent_reference,
    }


def _proposal_dict(
    proposal: Proposal, *, contract_hash: str | None = None
) -> dict[str, Any]:
    value = proposal.to_dict()
    result = {
        "proposalId": value["proposal_id"],
        "sellerAgentUrl": value["seller_agent_url"],
        "buyerAgentUrl": value["buyer_agent_url"],
        "buyerNeedId": value["buyer_need_id"],
        "skuId": value["sku_id"],
        "problemObserved": value["problem_observed"],
        "offeredOutcome": value["offered_outcome"],
        "priceUsdc": value["price_usdc"],
        "deliverySeconds": value["delivery_seconds"],
        "acceptanceCriteria": list(value["acceptance_criteria"]),
        "expiresAt": value["expires_at"],
        "state": value["state"],
        "revision": value["revision"],
    }
    if contract_hash is not None:
        result["contractHash"] = contract_hash
    return result


def _payment_dict(
    payment: PaymentReceipt, *, mocked: bool, idempotent_replay: bool = False
) -> dict[str, Any]:
    value = payment.to_public_dict()
    value["mocked"] = mocked
    value["idempotentReplay"] = idempotent_replay
    return value


def _fulfillment_dict(fulfillment: FulfillmentReceipt) -> dict[str, Any]:
    return {
        "fulfillmentId": fulfillment.fulfillment_id,
        "proposalId": fulfillment.proposal_id,
        "paymentId": fulfillment.payment_id,
        "sellerAgentUrl": fulfillment.seller_agent_url,
        "artifactHash": fulfillment.artifact_hash,
        "accepted": fulfillment.accepted,
        "validator": fulfillment.validator,
        "acceptanceResults": dict(fulfillment.acceptance_results),
        "artifactMetadata": dict(
            fulfillment.detail.get("artifactMetadata", {})
        ),
        "deliveredAt": fulfillment.delivered_at,
    }


def _artifact_metadata(artifact: Mapping[str, Any], encoded: bytes) -> dict[str, Any]:
    return {
        "contentType": "application/json",
        "sizeBytes": len(encoded),
        "topLevelFieldCount": len(artifact),
    }


def _proposal_contract_hash(proposal: Proposal) -> str:
    return _canonical_hash(
        {
            "sellerAgentUrl": proposal.seller_agent_url,
            "buyerAgentUrl": proposal.buyer_agent_url,
            "buyerNeedId": proposal.buyer_need_id,
            "skuId": proposal.sku_id,
            "problemObserved": proposal.problem_observed,
            "offeredOutcome": proposal.offered_outcome,
            "priceUsdc": usdc_text(proposal.price_usdc),
            "deliverySeconds": proposal.delivery_seconds,
            "acceptanceCriteria": list(proposal.acceptance_criteria),
            "expiresAt": proposal.expires_at,
            "revision": proposal.revision,
        }
    )


def _seller_configuration_version(seller: Mapping[str, Any]) -> str:
    return _canonical_hash(
        {
            "sellerId": seller["seller_id"],
            "agentUrl": seller["agent_url"],
            "walletAddress": seller["wallet_address"],
            "network": seller["network"],
            "sourceKind": seller.get("source_kind"),
            "manifest": dict(seller.get("manifest", {})),
        }
    )


def _commercial_policy_version(policy: CommercialPolicy) -> str:
    return _canonical_hash(_policy_dict(policy))


def _host_matches(host: str, rule: str) -> bool:
    normalized = rule.strip().lower().lstrip(".")
    return bool(normalized) and (
        host == normalized or host.endswith(f".{normalized}")
    )


def _buyer_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="buyer agent URL must be HTTP(S)")
    return parsed.hostname.lower()


def _validated_ingestion_url(
    value: str,
    *,
    offline: bool,
    label: str,
) -> str:
    try:
        return validate_network_url(
            value,
            offline=offline,
            label=label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ensure_not_expired(expires_at: str | None, subject: str) -> None:
    if not expires_at:
        return
    normalized = expires_at[:-1] + "+00:00" if expires_at.endswith("Z") else expires_at
    try:
        expiry = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{subject} expiry must be ISO-8601"
        ) from exc
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=f"{subject} has expired")


def _seller_or_404(repository: RepositoryProtocol, seller_id: str) -> dict[str, Any]:
    seller = repository.get_seller(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="seller not found")
    return seller


def _proposal_or_404(
    repository: RepositoryProtocol, proposal_id: str
) -> Proposal:
    proposal = repository.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return proposal


def _prospect_for_proposal(
    repository: RepositoryProtocol, proposal: Proposal
) -> ProspectRecord | None:
    if proposal.buyer_need_id is None:
        return None
    prospect = repository.get_prospect(proposal.buyer_need_id)
    if (
        prospect is None
        or prospect.need.buyer_agent_url != proposal.buyer_agent_url
    ):
        return None
    return prospect


def _policy_for_proposal(
    repository: RepositoryProtocol, proposal: Proposal
) -> tuple[str, CommercialPolicy]:
    seller = repository.find_seller_by_url(proposal.seller_agent_url)
    if seller is None:
        raise HTTPException(status_code=404, detail="proposal seller not found")
    policy = repository.get_policy(seller["seller_id"])
    if policy is None:
        repository.note_policy_denial()
        raise HTTPException(status_code=403, detail="seller has no bound policy")
    return seller["seller_id"], policy


def _authorize_offer(
    repository: RepositoryProtocol,
    *,
    seller_id: str,
    policy: CommercialPolicy,
    sku: ServiceSKU,
    prospect: ProspectRecord,
    price: Decimal,
    exclude_proposal_id: str | None = None,
) -> None:
    def deny(message: str) -> None:
        repository.note_policy_denial()
        raise HTTPException(status_code=403, detail=message)

    if not prospect.opted_in:
        deny("buyer has not opted in")
    _ensure_not_expired(prospect.need.expires_at, "buyer need")
    if price < policy.minimum_price_usdc or price > policy.maximum_price_usdc:
        deny("price is outside the bound policy")
    if price > prospect.need.maximum_price_usdc:
        deny("price exceeds buyer maximum")
    minimum_discounted = sku.base_price_usdc * (
        Decimal("1") - policy.maximum_discount_fraction
    )
    if price < minimum_discounted:
        deny("price exceeds maximum allowed discount")

    host = _buyer_host(prospect.need.buyer_agent_url)
    if any(_host_matches(host, rule) for rule in policy.blocked_buyer_hosts):
        deny("buyer host is blocked")
    if policy.allowed_buyer_hosts and not any(
        _host_matches(host, rule) for rule in policy.allowed_buyer_hosts
    ):
        deny("buyer host is not allowed")

    open_count = sum(
        1
        for proposal in repository.list_proposals(seller_id=seller_id)
        if proposal.state in _OPEN_PROPOSAL_STATES
        and proposal.proposal_id != exclude_proposal_id
    )
    if open_count >= policy.maximum_open_proposals:
        deny("maximum open proposals reached")


def _require_owner(
    principal: Principal, actual_owner: str | None, *, subject: str
) -> None:
    if actual_owner is None or actual_owner != principal.owner_id:
        raise HTTPException(
            status_code=403,
            detail=f"{subject} is not owned by the authenticated tenant",
        )


def _require_authenticated_owner(http_request: Request) -> Principal:
    principal = principal_from_request(http_request)
    if not principal.authenticated:
        raise HTTPException(
            status_code=401,
            detail="authenticated owner access is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def _reconciliation_status_dict(
    status: PaymentReconciliationStatus,
) -> dict[str, Any]:
    receipt = status.receipt
    reconciliation = status.reconciliation
    result: dict[str, Any] = {
        "paymentId": receipt.payment_id,
        "proposalId": receipt.proposal_id,
        "idempotencyKey": receipt.idempotency_key,
        "paymentState": receipt.state.value,
        "amountUsdc": usdc_text(receipt.amount_usdc),
        "chain": receipt.chain,
        "token": receipt.token,
        "asset": receipt.asset,
        "transactionHash": receipt.transaction_hash,
        "explorerUrl": receipt.explorer_url,
        "confirmedAt": receipt.confirmed_at,
        "requiresOperatorAction": status.requires_operator_action,
        "reconciliation": None,
    }
    if reconciliation is not None:
        result["reconciliation"] = {
            "state": reconciliation.state.value,
            "submissionStatus": reconciliation.submission_status.value,
            "reasonCode": reconciliation.reason_code,
            "explanation": reconciliation.explanation,
            "returnCode": reconciliation.returncode,
            "evidenceReference": reconciliation.evidence_reference,
            "transactionHash": reconciliation.transaction_hash,
            "resolvedBy": reconciliation.resolved_by,
            "createdAt": reconciliation.created_at,
            "updatedAt": reconciliation.updated_at,
        }
    return result


def _normalized_payment_mode(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().lower()
    if not normalized:
        return None
    if normalized not in {"offline", "testnet", "mainnet", "live"}:
        raise RuntimeError(f"unsupported payment mode: {normalized}")
    return normalized


def _configured_payment_mode(
    adapters: AdapterBundle, explicit_mode: str | None
) -> str:
    raw = (
        explicit_mode
        or os.getenv("AUTONOMERCE_PAYMENT_MODE")
        or os.getenv("AUTONOMERCE_MODE")
    )
    configured = _normalized_payment_mode(raw)
    if configured is not None:
        return configured
    return _normalized_payment_mode(getattr(adapters.payment, "mode", None)) or "offline"


def _configured_trusted_hosts(
    *,
    non_offline: bool,
    explicit_hosts: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if explicit_hosts is None:
        configured = os.getenv("AUTONOMERCE_TRUSTED_HOSTS", "")
        values = configured.split(",") if configured else []
    else:
        values = list(explicit_hosts)
    hosts = tuple(dict.fromkeys(host.strip().lower() for host in values if host.strip()))
    if not hosts and not non_offline:
        return (
            "testserver",
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "[::1]",
        )
    if not hosts:
        raise RuntimeError(
            "non-offline startup requires AUTONOMERCE_TRUSTED_HOSTS"
        )
    if non_offline and "*" in hosts:
        raise RuntimeError(
            "non-offline AUTONOMERCE_TRUSTED_HOSTS must not contain a wildcard"
        )
    if any("://" in host or "/" in host for host in hosts):
        raise RuntimeError(
            "AUTONOMERCE_TRUSTED_HOSTS entries must be hostnames, not URLs"
        )
    return hosts


def _security_headers(*, non_offline: bool) -> dict[str, str]:
    content_security_policy = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'"
        if non_offline
        else (
            "default-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
    )
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": content_security_policy,
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    if non_offline:
        headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    return headers


def _resolve_receipt_records(
    repository: RepositoryProtocol, receipt_id: str
) -> tuple[Proposal | None, PaymentReceipt | None, FulfillmentReceipt | None]:
    payment = repository.get_payment(receipt_id)
    fulfillment = repository.get_fulfillment(receipt_id)
    proposal = repository.get_proposal(receipt_id)
    publication = repository.get_receipt_publication(receipt_id)
    if publication is not None:
        proposal = repository.get_proposal(publication.proposal_id)
    if payment is not None:
        proposal = repository.get_proposal(payment.proposal_id)
        fulfillment = repository.fulfillment_for_proposal(payment.proposal_id)
    elif fulfillment is not None:
        proposal = repository.get_proposal(fulfillment.proposal_id)
        payment = repository.get_payment(fulfillment.payment_id)
    elif proposal is not None:
        payment = repository.payment_for_proposal(proposal.proposal_id)
        fulfillment = repository.fulfillment_for_proposal(proposal.proposal_id)
    if proposal is not None and publication is None:
        publication = repository.get_receipt_publication(proposal.proposal_id)
    return proposal, payment, fulfillment


def create_app(
    *,
    repository: RepositoryProtocol | None = None,
    adapters: AdapterBundle | None = None,
    bearer_token: str | None = None,
    owner_id: str | None = None,
    payment_mode: str | None = None,
    trusted_hosts: tuple[str, ...] | list[str] | None = None,
    rate_limiter: RequestLimiter | None = None,
    transaction_verification_hooks: Iterable[TransactionEvidenceHook] = (),
    publication_consent_verifier: Any | None = None,
) -> FastAPI:
    """Build an independently testable API with injectable integration lanes."""

    owns_repository = repository is None
    if repository is None:
        sqlite_path = os.getenv(
            "AUTONOMERCE_COMMERCE_SQLITE_PATH", ""
        ).strip()
        if sqlite_path:
            from .sqlite_repository import SQLiteRepository

            repository = SQLiteRepository(sqlite_path)
        else:
            repository = InMemoryRepository()
    adapters = adapters if adapters is not None else load_optional_adapters()
    configured_mode = _configured_payment_mode(adapters, payment_mode)
    non_offline = configured_mode != "offline"
    deployment_mode = os.getenv(
        "AUTONOMERCE_DEPLOYMENT_MODE", ""
    ).strip().lower()
    protected_api = non_offline or deployment_mode not in {
        "",
        "local-offline",
    }
    configured_token = (
        os.getenv("AUTONOMERCE_API_BEARER_TOKEN")
        if bearer_token is None
        else bearer_token
    )
    configured_owner = (
        owner_id
        or os.getenv("AUTONOMERCE_API_OWNER_ID")
        or "autonomerce-owner"
    )
    authenticator = BearerAuthenticator(
        token=configured_token,
        owner_id=configured_owner,
    )
    if protected_api and not authenticator.enabled:
        raise RuntimeError(
            "protected API startup requires AUTONOMERCE_API_BEARER_TOKEN"
        )
    if non_offline and (
        isinstance(repository, InMemoryRepository)
        or not bool(getattr(repository, "is_durable", False))
        or getattr(repository, "durability", RepositoryDurability.PROCESS_LOCAL)
        == RepositoryDurability.PROCESS_LOCAL
    ):
        raise RuntimeError(
            "non-offline startup requires a durable commerce repository; "
            "InMemoryRepository is offline-only"
        )
    effective_adapter_mode = _normalized_payment_mode(
        getattr(adapters.payment, "mode", None)
    )
    if non_offline and effective_adapter_mode in {None, "offline"}:
        raise RuntimeError(
            "non-offline startup requires a configured non-offline payment adapter"
        )
    if non_offline and not bool(
        getattr(adapters.payment, "independent_verification", False)
    ):
        raise RuntimeError(
            "non-offline startup requires independent transaction verification"
        )
    configured_trusted_hosts = _configured_trusted_hosts(
        non_offline=protected_api,
        explicit_hosts=trusted_hosts,
    )
    configured_verification_hooks = tuple(transaction_verification_hooks)
    configured_publication_verifier = publication_consent_verifier
    verifier_factory = os.getenv(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY", ""
    ).strip()
    if configured_publication_verifier is None and verifier_factory:
        configured_publication_verifier = _load_publication_consent_verifier(
            verifier_factory
        )
    payment_store = getattr(adapters.payment, "store", None)
    reconciliation_api = (
        PaymentReconciliationAPI(
            store=payment_store,
            mode=effective_adapter_mode or configured_mode,
            verification_hooks=configured_verification_hooks,
        )
        if payment_store is not None
        else None
    )

    app = FastAPI(
        title="Autonomerce API",
        version="0.1.0",
        description="Authenticated, contract-bound API composition for agent commerce.",
        openapi_url=None if protected_api else "/openapi.json",
        docs_url=None if protected_api else "/docs",
        redoc_url=None if protected_api else "/redoc",
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(configured_trusted_hosts),
        www_redirect=False,
    )
    app.state.repository = repository
    app.state.adapters = adapters
    app.state.authenticator = authenticator
    app.state.payment_mode = configured_mode
    app.state.rate_limiter = rate_limiter or RequestLimiter()
    app.state.payment_reconciliation = reconciliation_api
    app.state.transaction_verification_hooks = configured_verification_hooks
    app.state.publication_consent_verifier = configured_publication_verifier
    app.state.trusted_hosts = configured_trusted_hosts
    app.state.payment_lock = asyncio.Lock()
    app.state.fulfillment_lock = asyncio.Lock()
    if owns_repository and callable(getattr(repository, "close", None)):
        app.router.add_event_handler("shutdown", repository.close)

    @app.middleware("http")
    async def security_boundary(request: Request, call_next: Any) -> Any:
        lease = None
        try:
            public_paths = (
                _NON_OFFLINE_PUBLIC_PATHS
                if protected_api
                else _OFFLINE_PUBLIC_PATHS
            )
            public_request = request.url.path in public_paths or (
                request.method == "GET"
                and request.url.path.startswith("/receipts/")
            )
            peer_ip = request.client.host if request.client else "unknown"
            rate_limit_path = request.url.path
            if (
                request.method == "POST"
                and rate_limit_path.startswith("/payment-reconciliations/")
            ):
                # Reuse the existing strict payment budget for all fund-state
                # reconciliation commands. Queries retain the standard GET budget.
                rate_limit_path = "/payment-reconciliations/pay"
            lease = await app.state.rate_limiter.acquire(
                owner_id=(
                    "anonymous" if public_request else authenticator.owner_id
                ),
                ip_address=peer_ip,
                method=request.method,
                path=rate_limit_path,
            )
            if not public_request:
                request.state.principal = authenticator.authenticate(request)

            if request.method in {"POST", "PUT", "PATCH"}:
                content_encoding = request.headers.get(
                    "content-encoding", "identity"
                ).strip().lower()
                if content_encoding not in {"", "identity"}:
                    raise HTTPException(
                        status_code=415,
                        detail="compressed request bodies are not accepted",
                    )
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=400, detail="invalid Content-Length header"
                        ) from exc
                    if declared_length > _MAX_REQUEST_BODY_BYTES:
                        raise HTTPException(
                            status_code=413, detail="request body is too large"
                        )
                body = await request.body()
                if len(body) > _MAX_REQUEST_BODY_BYTES:
                    raise HTTPException(
                        status_code=413, detail="request body is too large"
                    )
                content_type = request.headers.get("content-type", "").lower()
                if body and "json" in content_type:
                    try:
                        parsed = json.loads(
                            body,
                            parse_constant=lambda value: (_ for _ in ()).throw(
                                ValueError(f"non-finite JSON value: {value}")
                            ),
                        )
                    except RecursionError as exc:
                        raise HTTPException(
                            status_code=413,
                            detail="JSON payload nesting is too deep",
                        ) from exc
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        parsed = None
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=422,
                            detail="request body must contain finite JSON values",
                        ) from exc
                    if parsed is not None:
                        _validate_json_shape(parsed)
                        path_parts = [
                            part
                            for part in request.url.path.split("/")
                            if part
                        ]
                        allowed_root_keys = (
                            frozenset({"token"})
                            if (
                                request.method == "POST"
                                and request.url.path.endswith("/pay")
                            )
                            else frozenset({"allowedtoken"})
                            if (
                                request.method == "POST"
                                and len(path_parts) == 3
                                and path_parts[0] == "sellers"
                                and path_parts[2] == "policies"
                            )
                            else frozenset()
                        )
                        _reject_secret_fields(
                            parsed,
                            allowed_root_keys=allowed_root_keys,
                        )
            response = await call_next(request)
        except RateLimitExceeded as exc:
            response = JSONResponse(
                status_code=429,
                content={"detail": exc.detail},
                headers={"Retry-After": str(exc.retry_after)},
            )
        except HTTPException as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        finally:
            if lease is not None:
                await lease.release()
        for header, value in _security_headers(
            non_offline=protected_api
        ).items():
            response.headers[header] = value
        return response

    @app.exception_handler(ContractError)
    async def contract_error_handler(
        request: Request, exc: ContractError
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def reconciliation_or_503() -> PaymentReconciliationAPI:
        reconciliation = app.state.payment_reconciliation
        if not isinstance(reconciliation, PaymentReconciliationAPI):
            raise HTTPException(
                status_code=503,
                detail="durable payment reconciliation is not configured",
            )
        return reconciliation

    def owned_reconciliation_status(
        idempotency_key: str,
        principal: Principal,
    ) -> tuple[PaymentReconciliationAPI, PaymentReconciliationStatus]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise HTTPException(
                status_code=422,
                detail="invalid payment idempotency key",
            )
        reconciliation = reconciliation_or_503()
        try:
            status = reconciliation.query_status(idempotency_key)
        except PaymentValidationError as exc:
            raise HTTPException(
                status_code=404,
                detail="payment reconciliation not found",
            ) from exc
        _require_owner(
            principal,
            repository.owner_for_proposal(status.receipt.proposal_id),
            subject="payment reconciliation",
        )
        return reconciliation, status

    @app.get("/health")
    async def health() -> dict[str, Any]:
        adapter_diagnostics = dict(adapters.diagnostics)
        return {
            "status": "ok",
            "service": "autonomerce-api",
            "runtimeMode": configured_mode,
            "storage": getattr(repository, "storage_name", "custom"),
            "storageDurability": str(
                getattr(
                    repository,
                    "durability",
                    RepositoryDurability.PROCESS_LOCAL,
                ).value
                if isinstance(
                    getattr(repository, "durability", None),
                    RepositoryDurability,
                )
                else getattr(repository, "durability", "unknown")
            ),
            "paymentMode": adapter_diagnostics.get("paymentMode", "unknown"),
            "movesFunds": bool(adapter_diagnostics.get("movesFunds", False)),
            "integrations": adapter_diagnostics,
            "optionalImportErrors": list(adapters.optional_import_errors),
            "authenticationRequired": authenticator.enabled,
            "tenantMode": "single-owner",
        }

    @app.post("/sellers", status_code=201)
    async def create_seller(
        request: SellerCreate, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        payload = request.model_dump()
        _reject_secret_fields(payload)
        agent_url = _validated_ingestion_url(
            request.agent_url,
            offline=not non_offline,
            label="seller agent URL",
        )
        seller_id = stable_id("seller", request.name, agent_url)
        wallet = request.wallet_address or _default_wallet(seller_id)
        seller = {
            "seller_id": seller_id,
            "name": request.name,
            "agent_url": agent_url,
            "source_kind": request.source_kind,
            "manifest": dict(request.manifest),
            "wallet_address": wallet,
            "network": request.network.upper(),
            "created_at": _utc_now(),
        }
        repository.save_seller(seller, owner_id=principal.owner_id)
        return {
            "sellerId": seller_id,
            "name": request.name,
            "agentUrl": agent_url,
            "sourceKind": request.source_kind,
            "walletAddress": wallet,
            "network": seller["network"],
            "status": "onboarded",
            "createdAt": seller["created_at"],
        }

    @app.post("/sellers/{seller_id}/capabilities", status_code=201)
    async def add_capability(
        seller_id: str, request: CapabilityCreate, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        seller = _seller_or_404(repository, seller_id)
        _require_owner(
            principal,
            repository.owner_for_seller(seller_id),
            subject="seller",
        )
        _reject_secret_fields(request.model_dump())
        _require_valid_schema(
            request.input_schema,
            subject="inputSchema",
            status_code=422,
        )
        _require_valid_schema(
            request.output_schema,
            subject="outputSchema",
            status_code=422,
        )
        source_url = (
            _validated_ingestion_url(
                request.source_url,
                offline=not non_offline,
                label="capability source URL",
            )
            if request.source_url
            else seller["agent_url"]
        )
        capability_id = request.capability_id or stable_id(
            "capability", seller_id, request.name, request.description
        )
        capability = CapabilityDescriptor(
            capability_id=capability_id,
            name=request.name,
            description=request.description,
            input_schema=request.input_schema,
            output_schema=request.output_schema,
            source_kind=request.source_kind,
            source_url=source_url,
            tags=tuple(request.tags),
        )
        repository.save_capability(seller_id, capability)
        return _capability_dict(capability)

    @app.post("/sellers/{seller_id}/skus/preview")
    async def preview_skus(
        seller_id: str, request: SKUPreviewRequest, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        seller = _seller_or_404(repository, seller_id)
        _require_owner(
            principal,
            repository.owner_for_seller(seller_id),
            subject="seller",
        )
        capabilities = repository.list_capabilities(seller_id)
        if request.capability_ids:
            requested = set(request.capability_ids)
            capabilities = [
                capability
                for capability in capabilities
                if capability.capability_id in requested
            ]
            missing = requested - {item.capability_id for item in capabilities}
            if missing:
                raise HTTPException(
                    status_code=404,
                    detail=f"capabilities not found for seller: {sorted(missing)}",
                )
        if not capabilities:
            raise HTTPException(
                status_code=400, detail="seller has no capabilities to productize"
            )

        options = request.model_dump()
        generated = await _invoke_adapter(
            adapters.productizer.preview_skus,
            seller,
            capabilities,
            options,
        )
        skus: list[ServiceSKU] = []
        for sku in generated:
            if not isinstance(sku, ServiceSKU):
                raise HTTPException(
                    status_code=502,
                    detail="productizer must return shared ServiceSKU contracts",
                )
            if repository.get_capability(sku.capability_id) is None:
                raise HTTPException(
                    status_code=502,
                    detail="productizer returned an unknown capability",
                )
            _reject_secret_fields(
                sku.to_dict(), "productizer.sku", status_code=502
            )
            _require_valid_schema(
                sku.input_schema,
                subject="productizer inputSchema",
                status_code=502,
            )
            _require_valid_schema(
                sku.output_schema,
                subject="productizer outputSchema",
                status_code=502,
            )
            repository.save_sku(seller_id, sku)
            skus.append(sku)
        return {"sellerId": seller_id, "skus": [_sku_dict(sku) for sku in skus]}

    @app.post("/sellers/{seller_id}/policies", status_code=201)
    async def bind_policy(
        seller_id: str, request: PolicyBindRequest, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        _seller_or_404(repository, seller_id)
        _require_owner(
            principal,
            repository.owner_for_seller(seller_id),
            subject="seller",
        )
        policy_id = stable_id(
            "policy",
            seller_id,
            request.minimum_price_usdc,
            request.maximum_price_usdc,
            request.maximum_discount_fraction,
            tuple(request.allowed_buyer_hosts),
            tuple(request.blocked_buyer_hosts),
            tuple(request.allowed_chains),
        )
        policy = CommercialPolicy(
            policy_id=policy_id,
            owner_id=seller_id,
            minimum_price_usdc=request.minimum_price_usdc,
            maximum_price_usdc=request.maximum_price_usdc,
            maximum_discount_fraction=request.maximum_discount_fraction,
            maximum_open_proposals=request.maximum_open_proposals,
            maximum_tasks_per_hour=request.maximum_tasks_per_hour,
            allowed_buyer_hosts=tuple(request.allowed_buyer_hosts),
            blocked_buyer_hosts=tuple(request.blocked_buyer_hosts),
            allowed_chains=tuple(chain.upper() for chain in request.allowed_chains),
            allowed_token=request.allowed_token.upper(),
            unattended=request.unattended,
        )
        repository.save_policy(seller_id, policy)
        return {"bound": True, "policy": _policy_dict(policy)}

    @app.post("/prospects", status_code=201)
    async def create_prospect(
        request: ProspectCreate, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        _reject_secret_fields(request.model_dump())
        if not request.opted_in:
            repository.note_policy_denial()
            raise HTTPException(
                status_code=403, detail="prospects must explicitly opt in"
            )
        if not request.consent_reference:
            raise HTTPException(
                status_code=422,
                detail="consentReference is required for opted-in prospects",
            )
        buyer_agent_url = _validated_ingestion_url(
            request.buyer_agent_url,
            offline=not non_offline,
            label="buyer agent URL",
        )
        _buyer_host(buyer_agent_url)
        _ensure_not_expired(request.expires_at, "buyer need")
        need_id = stable_id(
            "need",
            buyer_agent_url,
            request.desired_outcome,
            request.maximum_price_usdc,
            tuple(sorted(str(tag).strip() for tag in request.required_tags)),
            _canonical_hash(request.input_payload),
            request.expires_at,
            request.consent_reference,
        )
        need = BuyerNeed(
            need_id=need_id,
            buyer_agent_url=buyer_agent_url,
            desired_outcome=request.desired_outcome,
            maximum_price_usdc=request.maximum_price_usdc,
            required_tags=tuple(request.required_tags),
            input_payload=request.input_payload,
            expires_at=request.expires_at,
        )
        prospect = ProspectRecord(
            need=need,
            opted_in=True,
            owner_id=principal.owner_id,
            consent_reference=request.consent_reference,
        )
        repository.save_prospect(prospect)
        return _prospect_dict(prospect)

    @app.get("/prospects")
    async def list_prospects(http_request: Request) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        prospects = [
            _prospect_dict(item)
            for item in repository.list_prospects(owner_id=principal.owner_id)
        ]
        return {"prospects": prospects, "count": len(prospects)}

    @app.post("/proposals", status_code=201)
    async def create_proposal(
        request: ProposalCreate, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        _reject_secret_fields(request.model_dump())
        seller_agent_url = (
            _validated_ingestion_url(
                request.seller_agent_url,
                offline=not non_offline,
                label="seller agent URL",
            )
            if request.seller_agent_url
            else None
        )
        sku = repository.get_sku(request.sku_id)
        if sku is None:
            raise HTTPException(status_code=404, detail="SKU not found")
        sku_seller_id = repository.seller_for_sku(sku.sku_id)
        seller = (
            repository.get_seller(request.seller_id)
            if request.seller_id
            else repository.find_seller_by_url(seller_agent_url)
            if seller_agent_url
            else repository.get_seller(sku_seller_id or "")
        )
        if seller is None or seller["seller_id"] != sku_seller_id:
            raise HTTPException(status_code=400, detail="SKU does not belong to seller")
        _require_owner(
            principal,
            repository.owner_for_seller(seller["seller_id"]),
            subject="seller",
        )
        policy = repository.get_policy(seller["seller_id"])
        if policy is None:
            repository.note_policy_denial()
            raise HTTPException(status_code=403, detail="seller has no bound policy")

        prospect = repository.get_prospect(request.buyer_need_id)
        if prospect is None:
            repository.note_policy_denial()
            raise HTTPException(
                status_code=403, detail="buyer must be an opted-in prospect"
            )
        _require_owner(principal, prospect.owner_id, subject="prospect")
        price = (
            request.price_usdc
            if request.price_usdc is not None
            else sku.base_price_usdc
        )
        _authorize_offer(
            repository,
            seller_id=seller["seller_id"],
            policy=policy,
            sku=sku,
            prospect=prospect,
            price=price,
        )
        if (
            request.offered_outcome is not None
            and request.offered_outcome != sku.outcome
        ):
            raise HTTPException(
                status_code=409,
                detail="proposal scope must match the authorized SKU outcome",
            )
        if (
            "acceptance_criteria" in request.model_fields_set
            and tuple(request.acceptance_criteria) != sku.acceptance_criteria
        ):
            raise HTTPException(
                status_code=409,
                detail="proposal acceptance criteria must match the SKU contract",
            )
        if (
            request.delivery_seconds is not None
            and request.delivery_seconds != sku.maximum_latency_seconds
        ):
            raise HTTPException(
                status_code=409,
                detail="proposal delivery must match the SKU delivery bound",
            )
        delivery_seconds = sku.maximum_latency_seconds
        outcome = sku.outcome
        criteria = sku.acceptance_criteria
        _ensure_not_expired(request.expires_at, "proposal")
        proposal_id = stable_id(
            "proposal",
            seller["agent_url"],
            prospect.need.buyer_agent_url,
            prospect.need.need_id,
            sku.sku_id,
            request.problem_observed,
            outcome,
            price,
            delivery_seconds,
            request.expires_at,
        )
        proposal = Proposal(
            proposal_id=proposal_id,
            seller_agent_url=seller["agent_url"],
            buyer_agent_url=prospect.need.buyer_agent_url,
            sku_id=sku.sku_id,
            problem_observed=request.problem_observed,
            offered_outcome=outcome,
            price_usdc=price,
            delivery_seconds=delivery_seconds,
            buyer_need_id=prospect.need.need_id,
            acceptance_criteria=criteria,
            expires_at=request.expires_at,
            state=ProposalState.OFFERED,
        )
        contract_hash = _proposal_contract_hash(proposal)
        proposal = repository.save_proposal(
            proposal,
            owner_id=principal.owner_id,
            contract_hash=contract_hash,
        )
        persisted_hash = repository.contract_hash_for_proposal(proposal.proposal_id)
        value = _proposal_dict(proposal, contract_hash=persisted_hash)
        value["policyId"] = policy.policy_id
        return value

    @app.get("/proposals")
    async def list_proposals(
        http_request: Request,
        seller_id: str | None = Query(default=None, alias="sellerId"),
        state: ProposalState | None = None,
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        if seller_id is not None:
            _seller_or_404(repository, seller_id)
            _require_owner(
                principal,
                repository.owner_for_seller(seller_id),
                subject="seller",
            )
        proposals = repository.list_proposals(
            seller_id=seller_id,
            state=state,
            owner_id=principal.owner_id,
        )
        return {
            "proposals": [
                _proposal_dict(
                    proposal,
                    contract_hash=repository.contract_hash_for_proposal(
                        proposal.proposal_id
                    ),
                )
                for proposal in proposals
            ],
            "count": len(proposals),
        }

    async def apply_counter(
        proposal_id: str, request: CounterRequest, principal: Principal
    ) -> dict[str, Any]:
        current = _proposal_or_404(repository, proposal_id)
        _require_owner(
            principal,
            repository.owner_for_proposal(proposal_id),
            subject="proposal",
        )
        _ensure_not_expired(current.expires_at, "proposal")
        if current.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
            raise HTTPException(
                status_code=409, detail="proposal cannot be countered in its current state"
            )
        seller_id, policy = _policy_for_proposal(repository, current)
        sku = repository.get_sku(current.sku_id)
        prospect = _prospect_for_proposal(repository, current)
        if sku is None or prospect is None:
            raise HTTPException(status_code=409, detail="proposal dependencies are missing")
        _require_owner(principal, prospect.owner_id, subject="prospect")
        if (
            current.offered_outcome != sku.outcome
            or current.acceptance_criteria != sku.acceptance_criteria
            or current.delivery_seconds != sku.maximum_latency_seconds
        ):
            raise HTTPException(
                status_code=409,
                detail="proposal is not bound to the current SKU contract",
            )
        if (
            request.offered_outcome is not None
            and request.offered_outcome != current.offered_outcome
        ):
            raise HTTPException(
                status_code=409,
                detail="scope changes require a new proposal",
            )
        if (
            request.acceptance_criteria is not None
            and tuple(request.acceptance_criteria)
            != current.acceptance_criteria
        ):
            raise HTTPException(
                status_code=409,
                detail="acceptance-criteria changes require a new proposal",
            )
        if (
            request.delivery_seconds is not None
            and request.delivery_seconds != current.delivery_seconds
        ):
            raise HTTPException(
                status_code=409,
                detail="delivery changes require a new proposal",
            )
        _authorize_offer(
            repository,
            seller_id=seller_id,
            policy=policy,
            sku=sku,
            prospect=prospect,
            price=request.price_usdc,
            exclude_proposal_id=current.proposal_id,
        )
        revised = replace(
            current,
            price_usdc=request.price_usdc,
            state=ProposalState.COUNTERED,
            revision=current.revision + 1,
        )
        contract_hash = _proposal_contract_hash(revised)
        repository.record_negotiation(revised.price_usdc - current.price_usdc)
        repository.save_proposal(
            revised,
            owner_id=principal.owner_id,
            contract_hash=contract_hash,
        )
        return {
            "accepted": True,
            "reasonCode": "counter_within_policy",
            "policyId": policy.policy_id,
            "proposal": _proposal_dict(revised, contract_hash=contract_hash),
        }

    async def apply_accept(
        proposal_id: str,
        principal: Principal,
        *,
        requested_payer_wallet: str | None = None,
    ) -> dict[str, Any]:
        current = _proposal_or_404(repository, proposal_id)
        _require_owner(
            principal,
            repository.owner_for_proposal(proposal_id),
            subject="proposal",
        )
        _ensure_not_expired(current.expires_at, "proposal")
        existing_authorization = repository.get_settlement_authorization(
            proposal_id
        )
        if existing_authorization is not None:
            if current.state not in {
                ProposalState.ACCEPTED,
                ProposalState.PAID,
                ProposalState.FULFILLING,
                ProposalState.DELIVERED,
                ProposalState.FAILED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="settlement authorization exists for an invalid proposal state",
                )
            accepted = current
            authorization = existing_authorization
            if requested_payer_wallet is not None:
                try:
                    requested = normalize_wallet_address(
                        requested_payer_wallet,
                        authorization.chain,
                    )
                except PaymentValidationError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if requested.lower() != authorization.payer_wallet.lower():
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "payer wallet differs from the immutable "
                            "settlement authorization"
                        ),
                    )
        else:
            seller_id, policy = _policy_for_proposal(repository, current)
            sku = repository.get_sku(current.sku_id)
            prospect = _prospect_for_proposal(repository, current)
            if sku is None or prospect is None:
                raise HTTPException(
                    status_code=409, detail="proposal dependencies are missing"
                )
            _require_owner(principal, prospect.owner_id, subject="prospect")
            if (
                current.offered_outcome != sku.outcome
                or current.acceptance_criteria != sku.acceptance_criteria
                or current.delivery_seconds != sku.maximum_latency_seconds
            ):
                raise HTTPException(
                    status_code=409,
                    detail="proposal is not bound to the current SKU contract",
                )
            _authorize_offer(
                repository,
                seller_id=seller_id,
                policy=policy,
                sku=sku,
                prospect=prospect,
                price=current.price_usdc,
                exclude_proposal_id=current.proposal_id,
            )
            if current.state == ProposalState.ACCEPTED:
                accepted = current
            elif current.state in {
                ProposalState.OFFERED,
                ProposalState.COUNTERED,
            }:
                accepted = replace(current, state=ProposalState.ACCEPTED)
            else:
                raise HTTPException(
                    status_code=409,
                    detail="proposal cannot be accepted in its current state",
                )

            seller = _seller_or_404(repository, seller_id)
            allowed_chains = tuple(
                str(chain).upper() for chain in policy.allowed_chains
            )
            seller_network = str(seller["network"]).upper()
            chain = (
                seller_network
                if seller_network in allowed_chains
                else allowed_chains[0]
            )
            token = policy.allowed_token.upper()
            if token != "USDC":
                raise HTTPException(
                    status_code=409,
                    detail="accepted settlement token must be USDC",
                )
            known_assets = KNOWN_USDC_ASSETS.get(chain, ())
            if not known_assets:
                raise HTTPException(
                    status_code=409,
                    detail="accepted settlement chain has no canonical USDC asset",
                )
            asset = known_assets[0]
            payer_wallet = _accepted_payer_wallet(
                adapters.payment,
                chain=chain,
                requested_payer_wallet=requested_payer_wallet,
                non_offline=non_offline,
                offline_identifier=f"payer:{accepted.buyer_agent_url}",
            )
            payee_wallet = str(seller["wallet_address"])
            contract_hash = _proposal_contract_hash(accepted)
            created_dt = datetime.now(timezone.utc)
            created_at = created_dt.isoformat()
            expires_at = accepted.expires_at or (
                created_dt + timedelta(hours=1)
            ).isoformat()
            policy_version = _commercial_policy_version(policy)
            seller_version = _seller_configuration_version(seller)
            authorization = SettlementAuthorization(
                authorization_id=stable_id(
                    "settlement",
                    accepted.proposal_id,
                    accepted.revision,
                    contract_hash,
                    payer_wallet,
                    payee_wallet,
                    chain,
                    token,
                    asset,
                    policy.policy_id,
                    policy_version,
                    seller_id,
                    seller_version,
                    expires_at,
                ),
                proposal_id=accepted.proposal_id,
                proposal_revision=accepted.revision,
                proposal_contract_hash=contract_hash,
                amount_usdc=accepted.price_usdc,
                payer_wallet=payer_wallet,
                payee_wallet=payee_wallet,
                chain=chain,
                token=token,
                asset=asset,
                commercial_policy_id=policy.policy_id,
                commercial_policy_version=policy_version,
                seller_configuration_id=seller_id,
                seller_configuration_version=seller_version,
                expires_at=expires_at,
                created_at=created_at,
            )
            try:
                accepted, authorization = repository.accept_proposal(
                    accepted,
                    authorization,
                    owner_id=principal.owner_id,
                    contract_hash=contract_hash,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        repository.mark_accepted(proposal_id)
        return {
            "accepted": True,
            "proposal": _proposal_dict(
                accepted,
                contract_hash=repository.contract_hash_for_proposal(proposal_id),
            ),
            "settlementAuthorization": {
                "authorizationId": authorization.authorization_id,
                "proposalRevision": authorization.proposal_revision,
                "amountUsdc": usdc_text(authorization.amount_usdc),
                "payerWallet": authorization.payer_wallet,
                "payeeWallet": authorization.payee_wallet,
                "chain": authorization.chain,
                "token": authorization.token,
                "asset": authorization.asset,
                "expiresAt": authorization.expires_at,
            },
        }

    @app.post("/proposals/{proposal_id}/counter")
    async def counter_proposal(
        proposal_id: str, request: CounterRequest, http_request: Request
    ) -> dict[str, Any]:
        return await apply_counter(
            proposal_id, request, principal_from_request(http_request)
        )

    @app.post("/proposals/{proposal_id}/accept")
    async def accept_proposal(
        proposal_id: str,
        http_request: Request,
        request: AcceptRequest | None = None,
    ) -> dict[str, Any]:
        return await apply_accept(
            proposal_id,
            principal_from_request(http_request),
            requested_payer_wallet=(
                request.payer_wallet if request is not None else None
            ),
        )

    @app.post("/proposals/{proposal_id}/negotiate")
    async def negotiate_proposal(
        proposal_id: str, request: NegotiationRequest, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        if request.action == "accept":
            return await apply_accept(
                proposal_id,
                principal,
                requested_payer_wallet=request.payer_wallet,
            )
        if request.action == "decline":
            current = _proposal_or_404(repository, proposal_id)
            _require_owner(
                principal,
                repository.owner_for_proposal(proposal_id),
                subject="proposal",
            )
            if current.state not in {ProposalState.OFFERED, ProposalState.COUNTERED}:
                raise HTTPException(
                    status_code=409,
                    detail="proposal cannot be declined in its current state",
                )
            declined = replace(current, state=ProposalState.DECLINED)
            repository.save_proposal(
                declined,
                owner_id=principal.owner_id,
                contract_hash=_proposal_contract_hash(declined),
            )
            return {
                "accepted": False,
                "proposal": _proposal_dict(
                    declined,
                    contract_hash=repository.contract_hash_for_proposal(
                        proposal_id
                    ),
                ),
            }
        if request.price_usdc is None:
            raise HTTPException(
                status_code=422, detail="priceUsdc is required for a counter"
            )
        return await apply_counter(
            proposal_id,
            CounterRequest(
                price_usdc=request.price_usdc,
                delivery_seconds=request.delivery_seconds,
                offered_outcome=request.offered_outcome,
                acceptance_criteria=request.acceptance_criteria,
            ),
            principal,
        )

    @app.post("/proposals/{proposal_id}/pay")
    async def pay_proposal(
        proposal_id: str, request: PaymentRequest, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        _reject_secret_fields(
            request.model_dump(),
            allowed_root_keys=frozenset({"token"}),
        )
        if request.public_receipt:
            raise HTTPException(
                status_code=400,
                detail="receipt publication requires the explicit publish action",
            )
        async with app.state.payment_lock:
            proposal = _proposal_or_404(repository, proposal_id)
            _require_owner(
                principal,
                repository.owner_for_proposal(proposal_id),
                subject="proposal",
            )
            authorization = repository.get_settlement_authorization(proposal_id)
            if authorization is None:
                raise HTTPException(
                    status_code=409,
                    detail="proposal has no immutable settlement authorization",
                )
            expected_contract_hash = _proposal_contract_hash(proposal)
            if (
                repository.contract_hash_for_proposal(proposal_id)
                != expected_contract_hash
                or authorization.proposal_contract_hash
                != expected_contract_hash
                or authorization.proposal_revision != proposal.revision
                or authorization.amount_usdc != proposal.price_usdc
            ):
                raise HTTPException(
                    status_code=409,
                    detail="proposal settlement binding is missing or stale",
                )
            chain = request.chain.upper()
            token = request.token.upper()
            if chain != authorization.chain:
                repository.note_policy_denial()
                raise HTTPException(
                    status_code=409,
                    detail="payment chain differs from the accepted settlement",
                )
            if token != authorization.token or token != "USDC":
                repository.note_policy_denial()
                raise HTTPException(
                    status_code=409,
                    detail="payment token differs from the accepted settlement",
                )
            payer_wallet = request.payer_wallet or authorization.payer_wallet
            if payer_wallet.lower() != authorization.payer_wallet.lower():
                raise HTTPException(
                    status_code=409,
                    detail="payer wallet differs from the accepted settlement",
                )
            payee_wallet = authorization.payee_wallet

            existing_key = repository.payment_for_idempotency(
                request.idempotency_key
            )
            if existing_key is not None:
                if existing_key.proposal_id != proposal_id:
                    repository.note_duplicate_payment()
                    raise HTTPException(
                        status_code=409,
                        detail="idempotency key is already bound to another proposal",
                    )
                if not payment_matches_settlement_authorization(
                    existing_key, authorization
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "existing payment no longer matches the immutable "
                            "settlement authorization"
                        ),
                    )
                return _payment_dict(
                    existing_key,
                    mocked=repository.is_mocked_payment(existing_key.payment_id),
                    idempotent_replay=True,
                )

            existing_proposal = repository.payment_for_proposal(proposal_id)
            if existing_proposal is not None:
                repository.note_duplicate_payment()
                raise HTTPException(
                    status_code=409,
                    detail="proposal is already bound to a different payment",
                )
            _ensure_not_expired(
                authorization.expires_at, "settlement authorization"
            )
            if proposal.state != ProposalState.ACCEPTED:
                raise HTTPException(
                    status_code=409, detail="only accepted proposals can be paid"
                )
            execution = await _invoke_adapter(
                adapters.payment.execute_payment,
                proposal,
                idempotency_key=request.idempotency_key,
                chain=chain,
                token=token,
                payer_wallet=payer_wallet,
                payee_wallet=payee_wallet,
                public=False,
            )
            if isinstance(execution, PaymentReceipt):
                execution = PaymentExecution(receipt=execution, mocked=False)
            if not isinstance(execution, PaymentExecution):
                raise HTTPException(
                    status_code=502,
                    detail="payment adapter returned an invalid result",
                )
            receipt = execution.receipt
            _reject_secret_fields(
                {
                    "paymentId": receipt.payment_id,
                    "proposalId": receipt.proposal_id,
                    "idempotencyKey": receipt.idempotency_key,
                    "chain": receipt.chain,
                    "payerWallet": receipt.payer_wallet,
                    "payeeWallet": receipt.payee_wallet,
                    "transactionHash": receipt.transaction_hash,
                    "explorerUrl": receipt.explorer_url,
                    "confirmedAt": receipt.confirmed_at,
                },
                "payment.receipt",
                status_code=502,
            )
            if (
                not payment_matches_settlement_authorization(
                    receipt, authorization
                )
                or receipt.idempotency_key != request.idempotency_key
            ):
                raise HTTPException(
                    status_code=502,
                    detail="payment receipt failed contract validation",
                )
            try:
                repository.save_payment(receipt, mocked=execution.mocked)
            except ValueError as exc:
                repository.note_duplicate_payment()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            repository.save_proposal(
                replace(proposal, state=ProposalState.PAID),
                owner_id=principal.owner_id,
                contract_hash=expected_contract_hash,
            )
            return _payment_dict(receipt, mocked=execution.mocked)

    @app.get("/payment-reconciliations/{idempotency_key}")
    async def get_payment_reconciliation(
        idempotency_key: str,
        http_request: Request,
    ) -> dict[str, Any]:
        principal = _require_authenticated_owner(http_request)
        _, status = owned_reconciliation_status(
            idempotency_key,
            principal,
        )
        return _reconciliation_status_dict(status)

    @app.post(
        "/payment-reconciliations/{idempotency_key}/mark-retryable"
    )
    async def mark_payment_reconciliation_retryable(
        idempotency_key: str,
        request: ReconciliationResolutionRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        principal = _require_authenticated_owner(http_request)
        async with app.state.payment_lock:
            reconciliation, _ = owned_reconciliation_status(
                idempotency_key,
                principal,
            )
            try:
                status = reconciliation.mark_proven_not_submitted_retryable(
                    idempotency_key,
                    reason_code=request.reason_code,
                    explanation=request.explanation,
                    evidence_reference=request.evidence_reference,
                    resolved_by=principal.subject,
                )
            except PaymentReplayError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except PaymentValidationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _reconciliation_status_dict(status)

    @app.post("/payment-reconciliations/{idempotency_key}/confirm")
    async def confirm_payment_reconciliation(
        idempotency_key: str,
        request: ReconciliationConfirmationRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        principal = _require_authenticated_owner(http_request)
        async with app.state.payment_lock:
            reconciliation, current = owned_reconciliation_status(
                idempotency_key,
                principal,
            )
            if not app.state.transaction_verification_hooks:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "independent transaction verification is not configured"
                    ),
                )
            proposal = _proposal_or_404(
                repository,
                current.receipt.proposal_id,
            )
            if proposal.state not in {
                ProposalState.ACCEPTED,
                ProposalState.PAID,
                ProposalState.FULFILLING,
                ProposalState.DELIVERED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "proposal state does not permit payment confirmation"
                    ),
                )
            try:
                evidence = ExecutionResult(
                    state="CONFIRMED",
                    amount_usdc=request.amount_usdc,
                    chain=request.chain,
                    payer_wallet=request.payer_wallet,
                    payee_wallet=request.payee_wallet,
                    transaction_hash=request.transaction_hash,
                    confirmed_at=request.confirmed_at,
                    explorer_url=request.explorer_url,
                    simulated=False,
                    provider_reference=request.provider_reference,
                    raw={"source": "authenticated-reconciliation-api"},
                )
            except PaymentValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            try:
                status = reconciliation.confirm_from_verified_transaction(
                    idempotency_key,
                    evidence=evidence,
                    evidence_reference=request.evidence_reference,
                    resolved_by=principal.subject,
                )
            except ReceiptVerificationError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="transaction evidence was not independently verified",
                ) from exc
            except PaymentReplayError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except PaymentValidationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            try:
                repository.save_payment(status.receipt, mocked=False)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if proposal.state is ProposalState.ACCEPTED:
                repository.save_proposal(
                    replace(proposal, state=ProposalState.PAID),
                    owner_id=principal.owner_id,
                    contract_hash=(
                        repository.contract_hash_for_proposal(
                            proposal.proposal_id
                        )
                        or _proposal_contract_hash(proposal)
                    ),
                )
        return _reconciliation_status_dict(status)

    @app.post("/payment-reconciliations/{idempotency_key}/cancel")
    async def cancel_payment_reconciliation(
        idempotency_key: str,
        request: ReconciliationResolutionRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        principal = _require_authenticated_owner(http_request)
        async with app.state.payment_lock:
            reconciliation, _ = owned_reconciliation_status(
                idempotency_key,
                principal,
            )
            try:
                status = reconciliation.cancel_terminal(
                    idempotency_key,
                    reason_code=request.reason_code,
                    explanation=request.explanation,
                    evidence_reference=request.evidence_reference,
                    resolved_by=principal.subject,
                )
            except PaymentReplayError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except PaymentValidationError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _reconciliation_status_dict(status)

    @app.post("/proposals/{proposal_id}/fulfill")
    async def fulfill_proposal(
        proposal_id: str, request: FulfillmentRequest, http_request: Request
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        _reject_secret_fields(request.model_dump())
        async with app.state.fulfillment_lock:
            proposal = _proposal_or_404(repository, proposal_id)
            _require_owner(
                principal,
                repository.owner_for_proposal(proposal_id),
                subject="proposal",
            )
            payment = repository.payment_for_proposal(proposal_id)
            if payment is None or payment.state != PaymentState.CONFIRMED:
                raise HTTPException(
                    status_code=409,
                    detail="confirmed payment is required before fulfillment",
                )
            existing = repository.fulfillment_for_proposal(proposal_id)
            if existing is not None:
                return _fulfillment_dict(existing)
            if proposal.state not in {
                ProposalState.PAID,
                ProposalState.FULFILLING,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="proposal cannot be fulfilled in its current state",
                )
            repository.save_proposal(
                replace(proposal, state=ProposalState.FULFILLING),
                owner_id=principal.owner_id,
                contract_hash=repository.contract_hash_for_proposal(proposal_id),
            )
            prospect = _prospect_for_proposal(repository, proposal)
            if prospect is None:
                raise HTTPException(
                    status_code=409,
                    detail="proposal buyer input is missing",
                )
            execution = await _invoke_adapter(
                adapters.fulfillment.fulfill,
                proposal,
                artifact=request.artifact,
                context={
                    "acceptance_results": request.acceptance_results,
                    "payment_id": payment.payment_id,
                    "buyerInput": dict(prospect.need.input_payload),
                },
            )
            if isinstance(execution, Mapping):
                execution = FulfillmentExecution(artifact=dict(execution))
            if not isinstance(execution, FulfillmentExecution):
                raise HTTPException(
                    status_code=502,
                    detail="fulfillment adapter returned an invalid result",
                )
            artifact = dict(execution.artifact)
            _reject_secret_fields(
                {
                    "artifact": artifact,
                    "acceptanceResults": dict(
                        execution.acceptance_results
                    ),
                    "validator": execution.validator,
                },
                "fulfillment",
                status_code=502,
            )
            artifact_bytes = _json_bytes(artifact)
            sku = repository.get_sku(proposal.sku_id)
            if sku is None:
                raise HTTPException(
                    status_code=409, detail="fulfillment SKU is missing"
                )
            acceptance_results, accepted = _validate_artifact(
                artifact,
                sku,
                proposal,
                execution.acceptance_results,
            )
            validator = execution.validator
            artifact_hash = (
                f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
            )
            fulfillment_id = stable_id(
                "fulfillment",
                proposal.proposal_id,
                payment.payment_id,
                artifact_hash,
            )
            fulfillment = FulfillmentReceipt(
                fulfillment_id=fulfillment_id,
                proposal_id=proposal.proposal_id,
                payment_id=payment.payment_id,
                seller_agent_url=proposal.seller_agent_url,
                artifact_hash=artifact_hash,
                accepted=accepted,
                validator=validator,
                acceptance_results=acceptance_results,
                delivered_at=execution.delivered_at or _utc_now(),
                detail={
                    "artifactMetadata": _artifact_metadata(
                        artifact, artifact_bytes
                    )
                },
            )
            repository.save_fulfillment(fulfillment)
            repository.save_proposal(
                replace(
                    proposal,
                    state=(
                        ProposalState.DELIVERED
                        if accepted
                        else ProposalState.FAILED
                    ),
                ),
                owner_id=principal.owner_id,
                contract_hash=repository.contract_hash_for_proposal(proposal_id),
            )
            return _fulfillment_dict(fulfillment)

    @app.post("/receipts/{receipt_id}/publish")
    async def publish_receipt(
        receipt_id: str,
        request: ReceiptPublishRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        proposal, payment, fulfillment = _resolve_receipt_records(
            repository, receipt_id
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        _require_owner(
            principal,
            repository.owner_for_proposal(proposal.proposal_id),
            subject="receipt",
        )
        if payment is None:
            raise HTTPException(
                status_code=409,
                detail="a payment record is required before publication",
            )
        prospect = _prospect_for_proposal(repository, proposal)
        if prospect is None:
            raise HTTPException(
                status_code=409,
                detail="buyer consent record is missing",
            )
        if request.consent_reference == prospect.consent_reference:
            raise HTTPException(
                status_code=409,
                detail=(
                    "receipt publication requires consent separate from "
                    "buyer contact opt-in"
                ),
            )
        if not request.consent_reference.startswith("publication:"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "receipt publication requires a purpose-scoped "
                    "publication consent reference"
                ),
            )
        if non_offline:
            verifier = app.state.publication_consent_verifier
            if not callable(verifier):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "live receipt publication requires a configured "
                        "publication consent verifier"
                    ),
                )
            verdict = await _invoke_adapter(
                verifier,
                proposal=proposal,
                prospect=prospect,
                consent_reference=request.consent_reference,
                fields=tuple(dict.fromkeys(request.fields)),
            )
            if verdict is not True:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "publication consent was not independently verified "
                        "for this receipt"
                    ),
                )
        public_receipt_id = stable_id("receipt", proposal.proposal_id)
        publication = ReceiptPublication(
            receipt_id=public_receipt_id,
            proposal_id=proposal.proposal_id,
            owner_id=principal.owner_id,
            approved_by=principal.subject,
            consent_reference=request.consent_reference,
            fields=tuple(dict.fromkeys(request.fields)),
            published_at=_utc_now(),
        )
        try:
            publication = repository.save_receipt_publication(publication)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "published": True,
            "receiptId": publication.receipt_id,
            "proposalId": publication.proposal_id,
            "publishedAt": publication.published_at,
            "version": publication.version,
            "fields": list(publication.fields),
            "fulfillmentAvailable": fulfillment is not None,
        }

    @app.get("/receipts/{receipt_id}")
    async def public_receipt(receipt_id: str) -> dict[str, Any]:
        proposal, payment, fulfillment = _resolve_receipt_records(
            repository, receipt_id
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        publication = repository.get_receipt_publication(proposal.proposal_id)
        if publication is None:
            raise HTTPException(status_code=404, detail="receipt not found")

        acceptance_verdict = (
            "accepted"
            if fulfillment and fulfillment.accepted
            else "rejected"
            if fulfillment
            else "pending"
        )
        result: dict[str, Any] = {
            "receiptId": publication.receipt_id,
            "proposalId": proposal.proposal_id,
            "anonymizedOrderId": stable_id("order", proposal.proposal_id),
            "publicationVersion": publication.version,
        }
        if "payment" in publication.fields:
            result["payment"] = (
                payment.to_public_dict()
                if payment is not None
                else None
            )
        if "fulfillment" in publication.fields:
            result["fulfillment"] = (
                {
                    "fulfillmentId": fulfillment.fulfillment_id,
                    "artifactHash": fulfillment.artifact_hash,
                    "validator": fulfillment.validator,
                    "acceptanceResults": dict(fulfillment.acceptance_results),
                    "deliveredAt": fulfillment.delivered_at,
                }
                if fulfillment is not None
                else None
            )
        if "acceptanceVerdict" in publication.fields:
            result["acceptanceVerdict"] = acceptance_verdict
        return result

    @app.get("/metrics")
    async def metrics(http_request: Request) -> dict[str, Any]:
        principal = principal_from_request(http_request)
        return repository.metrics(owner_id=principal.owner_id)

    return app


app = create_app()
