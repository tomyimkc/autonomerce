"""Seller fulfillment adapters, artifact hashing, and delivery receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Callable, Mapping, Protocol

from autonomerce.contracts import (
    ContractError,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    stable_id,
)


class FulfillmentError(ContractError):
    """Fulfillment cannot proceed safely."""


ArtifactPayload = Mapping[str, Any] | list[Any] | tuple[Any, ...] | str | bytes


def _json_default(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"unsupported artifact type: {type(value).__name__}")


def canonical_artifact_bytes(artifact: ArtifactPayload) -> bytes:
    """Serialize artifacts deterministically before hashing."""

    if isinstance(artifact, bytes):
        return artifact
    if isinstance(artifact, str):
        return artifact.encode("utf-8")
    try:
        return json.dumps(
            artifact,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FulfillmentError("artifact is not canonically serializable") from exc


def artifact_hash(artifact: ArtifactPayload) -> str:
    return "sha256:" + hashlib.sha256(canonical_artifact_bytes(artifact)).hexdigest()


hash_artifact = artifact_hash


@dataclass(frozen=True)
class FulfillmentRequest:
    proposal: Proposal
    payment: PaymentReceipt
    input_payload: Mapping[str, Any]


class SellerFulfillmentAdapter(Protocol):
    """Boundary for invoking a seller agent after confirmed payment."""

    def fulfill(self, request: FulfillmentRequest) -> ArtifactPayload: ...


class CallableSellerFulfillmentAdapter:
    def __init__(
        self, handler: Callable[[FulfillmentRequest], ArtifactPayload]
    ) -> None:
        self._handler = handler

    def fulfill(self, request: FulfillmentRequest) -> ArtifactPayload:
        return self._handler(request)


class FixtureSellerFulfillmentAdapter:
    """Credential-free adapter for offline demos and tests."""

    def __init__(
        self,
        fixtures: Mapping[str, ArtifactPayload],
        *,
        default: ArtifactPayload | None = None,
    ) -> None:
        self._fixtures = dict(fixtures)
        self._default = default
        self.calls: list[FulfillmentRequest] = []

    def fulfill(self, request: FulfillmentRequest) -> ArtifactPayload:
        self.calls.append(request)
        if request.proposal.sku_id in self._fixtures:
            return self._fixtures[request.proposal.sku_id]
        if self._default is not None:
            return self._default
        raise FulfillmentError("no offline fixture for SKU")


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    acceptance_results: Mapping[str, bool]
    reason_code: str


class ArtifactValidator(Protocol):
    def validate(
        self,
        artifact: ArtifactPayload,
        proposal: Proposal,
    ) -> ValidationResult: ...


def _json_type_matches(value: object, expected: str) -> bool:
    checks: dict[str, Callable[[object], bool]] = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, (list, tuple)),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(item),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return bool(check and check(value))


class SchemaArtifactValidator:
    """Small fail-closed JSON-schema subset plus explicit criterion checks."""

    def __init__(
        self,
        output_schema: Mapping[str, Any] | None = None,
        *,
        criterion_checks: Mapping[
            str, Callable[[ArtifactPayload], bool]
        ] | None = None,
        name: str = "schema-v1",
    ) -> None:
        self.output_schema = dict(output_schema or {})
        self.criterion_checks = dict(criterion_checks or {})
        self.name = name

    def validate(
        self,
        artifact: ArtifactPayload,
        proposal: Proposal,
    ) -> ValidationResult:
        results: dict[str, bool] = {}
        validation_configured = bool(self.output_schema) or bool(
            proposal.acceptance_criteria
        )
        schema_ok = validation_configured
        if not validation_configured:
            results["validator.configured"] = False
        schema_type = self.output_schema.get("type")
        if isinstance(schema_type, str):
            schema_ok = _json_type_matches(artifact, schema_type)
            results["$schema.type"] = schema_ok

        if schema_ok and isinstance(artifact, Mapping):
            required = self.output_schema.get("required", ())
            if isinstance(required, (list, tuple)):
                for key in required:
                    present = str(key) in artifact
                    results[f"$schema.required.{key}"] = present
                    schema_ok = schema_ok and present
            properties = self.output_schema.get("properties", {})
            if isinstance(properties, Mapping):
                for key, rule in properties.items():
                    if (
                        key in artifact
                        and isinstance(rule, Mapping)
                        and isinstance(rule.get("type"), str)
                    ):
                        valid = _json_type_matches(artifact[key], rule["type"])
                        results[f"$schema.property.{key}"] = valid
                        schema_ok = schema_ok and valid

        criteria_ok = True
        for criterion in proposal.acceptance_criteria:
            check = self.criterion_checks.get(criterion)
            if check is None:
                passed = False
            else:
                try:
                    passed = bool(check(artifact))
                except Exception:
                    passed = False
            results[criterion] = passed
            criteria_ok = criteria_ok and passed

        accepted = schema_ok and criteria_ok
        return ValidationResult(
            accepted=accepted,
            acceptance_results=results,
            reason_code="accepted" if accepted else "contract_validation_failed",
        )


@dataclass(frozen=True)
class FulfillmentResult:
    artifact: ArtifactPayload | None
    receipt: FulfillmentReceipt


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise FulfillmentError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def generate_delivery_receipt(
    *,
    proposal: Proposal,
    payment: PaymentReceipt,
    seller_agent_url: str,
    artifact_digest: str,
    validation: ValidationResult,
    validator: str,
    delivered_at: datetime | None = None,
) -> FulfillmentReceipt:
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact_digest):
        raise FulfillmentError("artifact digest must be a canonical SHA-256 hash")
    fulfillment_id = stable_id(
        "fulfillment",
        proposal.proposal_id,
        payment.payment_id,
        artifact_digest,
    )
    return FulfillmentReceipt(
        fulfillment_id=fulfillment_id,
        proposal_id=proposal.proposal_id,
        payment_id=payment.payment_id,
        seller_agent_url=seller_agent_url,
        artifact_hash=artifact_digest,
        accepted=validation.accepted,
        validator=validator,
        acceptance_results=dict(validation.acceptance_results),
        delivered_at=_iso(_utc(delivered_at)),
        detail={"reasonCode": validation.reason_code},
    )


_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "cookie",
    "credential",
    "private_key",
)


def _public_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _public_value(item)
            for key, item in value.items()
            if not any(part in str(key).casefold() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return value


def delivery_receipt_to_public_dict(
    receipt: FulfillmentReceipt,
) -> dict[str, Any]:
    """Return receipt evidence without prompts, artifacts, or credentials."""

    return {
        "fulfillmentId": receipt.fulfillment_id,
        "proposalId": receipt.proposal_id,
        "paymentId": receipt.payment_id,
        "artifactHash": receipt.artifact_hash,
        "accepted": receipt.accepted,
        "validator": receipt.validator,
        "acceptanceResults": _public_value(receipt.acceptance_results),
        "deliveredAt": receipt.delivered_at,
        "detail": _public_value(receipt.detail),
    }


class FulfillmentOrchestrator:
    """Invoke, hash, validate, and receipt seller output after payment."""

    def __init__(
        self,
        *,
        adapter: SellerFulfillmentAdapter,
        validator: ArtifactValidator,
        validator_name: str = "seller-contract-validator",
        max_artifact_bytes: int = 1_000_000,
    ) -> None:
        if max_artifact_bytes < 1:
            raise FulfillmentError("max_artifact_bytes must be positive")
        self.adapter = adapter
        self.validator = validator
        self.validator_name = validator_name
        self.max_artifact_bytes = max_artifact_bytes

    def fulfill(
        self,
        *,
        proposal: Proposal,
        payment: PaymentReceipt,
        input_payload: Mapping[str, Any],
        now: datetime | None = None,
    ) -> FulfillmentResult:
        if payment.state != PaymentState.CONFIRMED:
            raise FulfillmentError("fulfillment requires confirmed payment")
        if payment.proposal_id != proposal.proposal_id:
            raise FulfillmentError("payment does not belong to proposal")
        if payment.amount_usdc != proposal.price_usdc:
            raise FulfillmentError("payment amount does not match accepted proposal")
        if proposal.state not in {ProposalState.ACCEPTED, ProposalState.PAID}:
            raise FulfillmentError("proposal must be accepted or paid")

        request = FulfillmentRequest(
            proposal=proposal,
            payment=payment,
            input_payload=dict(input_payload),
        )
        artifact = self.adapter.fulfill(request)
        canonical = canonical_artifact_bytes(artifact)
        if len(canonical) > self.max_artifact_bytes:
            raise FulfillmentError("seller artifact exceeds size limit")
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        try:
            validation = self.validator.validate(artifact, proposal)
        except Exception:
            validation = ValidationResult(
                accepted=False,
                acceptance_results={"validator_completed": False},
                reason_code="validator_error",
            )
        receipt = generate_delivery_receipt(
            proposal=proposal,
            payment=payment,
            seller_agent_url=proposal.seller_agent_url,
            artifact_digest=digest,
            validation=validation,
            validator=self.validator_name,
            delivered_at=_utc(now),
        )
        return FulfillmentResult(artifact=artifact, receipt=receipt)
