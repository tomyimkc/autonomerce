"""Provider-neutral primitives for structured Autonomerce agent decisions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol, runtime_checkable


class AgentDecisionError(ValueError):
    """A requested agent action is invalid or cannot be made safely."""


class ProviderUnavailableError(RuntimeError):
    """An optional decision provider is not installed or authenticated."""


class ProviderResponseError(RuntimeError):
    """A provider returned an invalid structured decision."""


_PRIVATE_REASONING_KEYS = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "chainofthought",
        "hidden_reasoning",
        "reasoning",
        "scratchpad",
        "thoughts",
    }
)


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def ensure_json_value(value: Any, *, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AgentDecisionError(f"{label} must be finite JSON data") from exc


def reject_private_reasoning(value: Any) -> None:
    """Reject provider output that attempts to persist hidden reasoning traces."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _normalized_key(key) in _PRIVATE_REASONING_KEYS:
                raise ProviderResponseError(
                    "provider response included a prohibited private-reasoning field"
                )
            reject_private_reasoning(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            reject_private_reasoning(nested)


def normalize_decision_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderResponseError("provider response must be a JSON object")
    decision = dict(value)
    ensure_json_value(decision, label="provider response")
    reject_private_reasoning(decision)
    return decision


@dataclass(frozen=True)
class DecisionRequest:
    """One stateless request for a JSON-only commercial recommendation."""

    operation: str
    instruction: str
    payload: Mapping[str, Any]
    response_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.instruction.strip():
            raise AgentDecisionError("decision operation and instruction are required")
        ensure_json_value(self.payload, label="decision payload")
        ensure_json_value(self.response_schema, label="response schema")


@runtime_checkable
class DecisionProvider(Protocol):
    """Provider-neutral interface implemented by Gemini and offline rules."""

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    def generate_json(self, request: DecisionRequest) -> Mapping[str, Any]:
        """Return one JSON object, without hidden chain-of-thought fields."""


def provider_identity(provider: DecisionProvider) -> tuple[str, str]:
    provider_name = str(getattr(provider, "provider_name", "")).strip()
    model_name = str(getattr(provider, "model_name", "")).strip()
    if not provider_name or not model_name:
        raise AgentDecisionError(
            "decision provider must expose non-empty provider_name and model_name"
        )
    return provider_name, model_name
