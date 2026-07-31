"""Gemini and credential-free offline providers for JSON decisions."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import importlib
import json
import re
from typing import Any, Callable, Mapping

from autonomerce.contracts import usdc, usdc_text

from .base import (
    DecisionRequest,
    ProviderResponseError,
    ProviderUnavailableError,
    normalize_decision_json,
)


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(value: object) -> set[str]:
    return set(_TOKEN.findall(str(value).lower()))


def _midpoint_usdc(minimum: object, maximum: object) -> str:
    low = usdc(str(minimum))
    high = usdc(str(maximum))
    midpoint = ((low + high) / Decimal("2")).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    return usdc_text(min(max(midpoint, low), high))


def _reason_codes(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value).strip().upper() for value in values if str(value).strip()]


class OfflineDecisionProvider:
    """Deterministic local provider used by tests and credential-free demos."""

    provider_name = "offline"
    model_name = "deterministic-rules-v1"

    def generate_json(self, request: DecisionRequest) -> Mapping[str, Any]:
        handlers: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
            "productize_capability": self._productize,
            "score_prospect_fit": self._score_fit,
            "write_proposal": self._write_proposal,
            "recommend_negotiation": self._recommend_negotiation,
            "summarize_delivery": self._summarize_delivery,
        }
        handler = handlers.get(request.operation)
        if handler is None:
            raise ProviderResponseError(
                f"offline provider does not support operation {request.operation!r}"
            )
        return normalize_decision_json(handler(request.payload))

    @staticmethod
    def _productize(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        capability = payload["capability"]
        policy = payload["policy"]
        output_schema = capability.get("outputSchema") or {}
        criteria = ["non_empty_artifact"]
        if output_schema:
            criteria.append("output_schema_valid")
            for field_name in output_schema.get("required", []):
                criteria.append(f"required_field:{field_name}")
        return {
            "skus": [
                {
                    "name": capability["name"],
                    "outcome": capability["description"],
                    "basePriceUsdc": _midpoint_usdc(
                        policy["minimumPriceUsdc"], policy["maximumPriceUsdc"]
                    ),
                    "acceptanceCriteria": criteria,
                    "maximumLatencySeconds": 300,
                    "capacityPerHour": min(
                        20, int(policy.get("maximumTasksPerHour", 1))
                    ),
                }
            ],
            "summary": "Created one deterministic SKU from the declared capability.",
            "reasonCodes": ["DECLARED_CAPABILITY_PRODUCTIZED", "OFFLINE_RULES"],
        }

    @staticmethod
    def _score_fit(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not payload.get("optedIn", False):
            return {
                "score": 0,
                "recommended": False,
                "reasonCodes": ["NOT_OPTED_IN"],
                "summary": "Prospect is not opted in.",
            }
        hard_reasons = _reason_codes(payload.get("hardDenyReasons"))
        if hard_reasons:
            return {
                "score": 0,
                "recommended": False,
                "reasonCodes": hard_reasons,
                "summary": "Deterministic commercial constraints deny outreach.",
            }

        sku = payload["sku"]
        need = payload["need"]
        need_tokens = _tokens(need.get("desiredOutcome", ""))
        sku_tokens = _tokens(f"{sku.get('name', '')} {sku.get('outcome', '')}")
        overlap = len(need_tokens & sku_tokens) / max(1, len(need_tokens))
        lexical_score = round(overlap * 60)

        required_tags = {
            str(value).strip().lower()
            for value in need.get("requiredTags", [])
            if str(value).strip()
        }
        capability_tags = {
            str(value).strip().lower()
            for value in payload.get("capabilityTags", [])
            if str(value).strip()
        }
        if required_tags:
            tag_score = round(
                15 * len(required_tags & capability_tags) / len(required_tags)
            )
        else:
            tag_score = 15

        budget_score = 25
        score = min(100, lexical_score + tag_score + budget_score)
        reasons = ["BUDGET_COMPATIBLE"]
        reasons.append("TAG_COMPATIBLE" if tag_score == 15 else "PARTIAL_TAG_MATCH")
        reasons.append("OUTCOME_MATCH" if lexical_score >= 30 else "WEAK_OUTCOME_MATCH")
        return {
            "score": score,
            "recommended": score >= int(payload.get("minimumScore", 60)),
            "reasonCodes": reasons,
            "summary": "Scored fit from outcome, tags, budget, and opt-in status.",
        }

    @staticmethod
    def _write_proposal(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        need = payload["need"]
        sku = payload["sku"]
        return {
            "problemObserved": f"Buyer requested: {need['desiredOutcome']}",
            "offeredOutcome": sku["outcome"],
            "summary": "Drafted a proposal limited to the published SKU contract.",
            "reasonCodes": ["FIT_APPROVED", "SKU_TERMS_PRESERVED"],
        }

    @staticmethod
    def _recommend_negotiation(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = [
            str(value).strip().lower()
            for value in payload.get("allowedActions", [])
            if str(value).strip()
        ]
        if "accept" in allowed:
            action = "accept"
        elif "counter" in allowed:
            action = "counter"
        else:
            action = "decline"
        return {
            "action": action,
            "summary": "Recommended an action from the deterministic allowed-action set.",
            "reasonCodes": ["WITHIN_DETERMINISTIC_BOUNDS"],
        }

    @staticmethod
    def _summarize_delivery(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        accepted = bool(payload.get("accepted"))
        return {
            "summary": (
                "Delivery passed deterministic contract validation."
                if accepted
                else "Delivery did not pass deterministic contract validation."
            ),
            "reasonCodes": _reason_codes(payload.get("reasonCodes")),
        }


class GeminiDecisionProvider:
    """Thin Google Gen AI adapter with optional import and JSON-schema output."""

    provider_name = "google"

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        client: Any | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Gemini model name is required")
        self._model = model.strip()
        self._client = client

    @property
    def model_name(self) -> str:
        return self._model

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            genai = importlib.import_module("google.genai")
        except (ImportError, ModuleNotFoundError) as exc:
            raise ProviderUnavailableError(
                "Google GenAI support is optional; install the 'autonomerce[gemini]' "
                "extra to enable GeminiDecisionProvider"
            ) from exc
        try:
            self._client = genai.Client()
        except Exception as exc:
            raise ProviderUnavailableError(
                "Google GenAI client initialization failed; authenticate with "
                "Application Default Credentials or configured Google GenAI environment"
            ) from exc
        return self._client

    def generate_json(self, request: DecisionRequest) -> Mapping[str, Any]:
        client = self._client_or_raise()
        contents = json.dumps(
            request.payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        config = {
            "system_instruction": (
                f"{request.instruction}\n"
                "Return only the requested JSON decision. Do not include chain-of-thought, "
                "scratchpad content, credentials, or hidden reasoning."
            ),
            "response_mime_type": "application/json",
            "response_json_schema": dict(request.response_schema),
            "temperature": 0,
        }
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise ProviderResponseError(
                "Gemini structured-decision request failed"
            ) from exc

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if hasattr(parsed, "model_dump"):
                parsed = parsed.model_dump()
            return normalize_decision_json(parsed)

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ProviderResponseError("Gemini returned no structured JSON decision")
        try:
            return normalize_decision_json(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "Gemini response was not a valid JSON object"
            ) from exc
