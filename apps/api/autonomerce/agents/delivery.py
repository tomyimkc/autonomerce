"""Deterministic seller-output validation with provider-only summarization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from autonomerce.contracts import (
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
)

from .base import (
    AgentDecisionError,
    DecisionProvider,
    DecisionRequest,
    normalize_decision_json,
    provider_identity,
)
from .models import DecisionMetadata, DeliveryValidationDecision
from .providers import OfflineDecisionProvider


_DELIVERY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["summary", "reasonCodes"],
    "properties": {
        "summary": {"type": "string"},
        "reasonCodes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def _codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        str(item).strip().upper().replace(" ", "_")
        for item in value
        if str(item).strip()
    )


def _json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AgentDecisionError("delivery artifact must be finite JSON data") from exc
    return text.encode("utf-8")


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _schema_errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    expected_types = (
        [expected_type] if isinstance(expected_type, str) else list(expected_type or [])
    )
    if expected_types and not any(_matches_type(value, item) for item in expected_types):
        return [f"{path}:type"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}:enum")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        for key in required if isinstance(required, list) else []:
            if key not in value:
                errors.append(f"{path}.{key}:required")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, nested_schema in properties.items():
                if key in value and isinstance(nested_schema, Mapping):
                    errors.extend(_schema_errors(value[key], nested_schema, f"{path}.{key}"))
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key}:additional")

    if isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            errors.append(f"{path}:minItems")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            errors.append(f"{path}:maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            errors.append(f"{path}:minLength")
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
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


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, Mapping, Sequence)):
        return len(value) > 0
    return True


class DeliveryValidator:
    """Validate contract acceptance in code; a model may summarize but never accept."""

    validator_name = "autonomerce.deterministic-contract-v1"

    def __init__(self, provider: DecisionProvider | None = None) -> None:
        self._provider = provider or OfflineDecisionProvider()

    def validate(
        self,
        *,
        sku: ServiceSKU,
        proposal: Proposal,
        payment: PaymentReceipt,
        artifact: Any,
        criterion_results: Mapping[str, bool] | None = None,
        delivered_at: str | None = None,
    ) -> DeliveryValidationDecision:
        if proposal.sku_id != sku.sku_id:
            raise AgentDecisionError("proposal SKU does not match validation SKU")
        artifact_hash = hashlib.sha256(_json_bytes(artifact)).hexdigest()
        schema_errors = tuple(_schema_errors(artifact, sku.output_schema))
        provided_results = dict(criterion_results or {})

        acceptance_results: dict[str, bool] = {}
        for criterion in sku.acceptance_criteria:
            if criterion == "non_empty_artifact":
                result = _non_empty(artifact)
            elif criterion == "artifact_is_json":
                result = True
            elif criterion == "output_schema_valid":
                result = not schema_errors
            elif criterion.startswith("required_field:"):
                field_name = criterion.split(":", 1)[1]
                result = isinstance(artifact, Mapping) and field_name in artifact
            else:
                # Unknown natural-language criteria require an external deterministic
                # validator result. A provider recommendation is never sufficient.
                result = provided_results.get(criterion) is True
            acceptance_results[criterion] = result

        reason_codes: list[str] = []
        if proposal.state not in {
            ProposalState.ACCEPTED,
            ProposalState.PAID,
            ProposalState.FULFILLING,
        }:
            reason_codes.append("PROPOSAL_NOT_ACCEPTED")
        if proposal.acceptance_criteria != sku.acceptance_criteria:
            reason_codes.append("PROPOSAL_CONTRACT_MISMATCH")
        if payment.state is not PaymentState.CONFIRMED:
            reason_codes.append("PAYMENT_NOT_CONFIRMED")
        if payment.proposal_id != proposal.proposal_id:
            reason_codes.append("PAYMENT_PROPOSAL_MISMATCH")
        if payment.amount_usdc != proposal.price_usdc:
            reason_codes.append("PAYMENT_AMOUNT_MISMATCH")
        if schema_errors:
            reason_codes.append("OUTPUT_SCHEMA_INVALID")
        if not _non_empty(artifact):
            reason_codes.append("EMPTY_ARTIFACT")
        if not sku.output_schema and not sku.acceptance_criteria:
            reason_codes.append("NO_VALIDATABLE_ACCEPTANCE_CONTRACT")
        if acceptance_results and not all(acceptance_results.values()):
            reason_codes.append("ACCEPTANCE_CRITERIA_FAILED")

        accepted = not reason_codes
        request = DecisionRequest(
            operation="summarize_delivery",
            instruction=(
                "Summarize the supplied deterministic validation result. Do not change "
                "acceptance, infer payment state, or request the private artifact."
            ),
            payload={
                "accepted": accepted,
                "proposalId": proposal.proposal_id,
                "paymentId": payment.payment_id,
                "artifactHash": artifact_hash,
                "acceptanceResults": acceptance_results,
                "schemaErrorCodes": list(schema_errors),
                "reasonCodes": reason_codes,
            },
            response_schema=_DELIVERY_SCHEMA,
        )
        raw = normalize_decision_json(self._provider.generate_json(request))
        provider_reasons = _codes(raw.get("reasonCodes"))
        all_reasons = tuple(dict.fromkeys([*reason_codes, *provider_reasons]))
        summary = str(raw.get("summary") or "Delivery validation completed.")[:500]

        receipt = FulfillmentReceipt(
            fulfillment_id=stable_id(
                "fulfillment",
                proposal.proposal_id,
                payment.payment_id,
                artifact_hash,
            ),
            proposal_id=proposal.proposal_id,
            payment_id=payment.payment_id,
            seller_agent_url=proposal.seller_agent_url,
            artifact_hash=artifact_hash,
            accepted=accepted,
            validator=self.validator_name,
            acceptance_results=acceptance_results,
            delivered_at=delivered_at,
            # Deliberately omit the artifact, prompt, provider response, and credentials.
            detail={
                "summary": summary,
                "reasonCodes": list(all_reasons),
            },
        )
        provider_name, model_name = provider_identity(self._provider)
        return DeliveryValidationDecision(
            accepted=accepted,
            receipt=receipt,
            reason_codes=all_reasons,
            summary=summary,
            schema_errors=schema_errors,
            metadata=DecisionMetadata(
                operation=request.operation,
                provider=provider_name,
                model=model_name,
            ),
        )
