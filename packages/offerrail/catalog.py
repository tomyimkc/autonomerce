"""Deterministic capability-to-SKU productization helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Mapping

from autonomerce.contracts import (
    CapabilityDescriptor,
    ContractError,
    ServiceSKU,
    stable_id,
    usdc,
    usdc_text,
)

from ._canonical import canonical_clone, canonical_json


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    text = value.strip()
    if not text:
        raise ContractError(f"{field_name} is required")
    return text


def _criteria(values: Iterable[object]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ContractError("acceptance_criteria must be an iterable of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ContractError("acceptance criteria must be strings")
        text = value.strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return tuple(normalized)


def capability_to_sku(
    capability: CapabilityDescriptor,
    *,
    base_price_usdc: Decimal | int | str,
    name: str | None = None,
    outcome: str | None = None,
    acceptance_criteria: Iterable[object] = (),
    maximum_latency_seconds: int = 300,
    capacity_per_hour: int = 1,
    input_schema: Mapping[str, object] | None = None,
    output_schema: Mapping[str, object] | None = None,
) -> ServiceSKU:
    """Build a stable SKU from one shared capability descriptor.

    The SKU identifier covers the complete sellable contract. Mapping key order
    and insignificant Decimal trailing zeroes therefore do not change the ID,
    while a real contract or price change does.
    """

    if not isinstance(capability, CapabilityDescriptor):
        raise ContractError("capability must be a CapabilityDescriptor")
    if (
        isinstance(maximum_latency_seconds, bool)
        or not isinstance(maximum_latency_seconds, int)
        or maximum_latency_seconds < 1
    ):
        raise ContractError("maximum_latency_seconds must be a positive integer")
    if (
        isinstance(capacity_per_hour, bool)
        or not isinstance(capacity_per_hour, int)
        or capacity_per_hour < 1
    ):
        raise ContractError("capacity_per_hour must be a positive integer")

    product_name = _required_text(
        capability.name if name is None else name, field_name="SKU name"
    )
    product_outcome = _required_text(
        capability.description if outcome is None else outcome,
        field_name="SKU outcome",
    )
    if isinstance(base_price_usdc, float):
        raise ContractError("binary float is not allowed for USDC")
    price = usdc(base_price_usdc)
    criteria = _criteria(acceptance_criteria)
    selected_input = capability.input_schema if input_schema is None else input_schema
    selected_output = capability.output_schema if output_schema is None else output_schema
    if not isinstance(selected_input, Mapping) or not isinstance(selected_output, Mapping):
        raise ContractError("SKU schemas must be mappings")
    detached_input = canonical_clone(selected_input)
    detached_output = canonical_clone(selected_output)

    sku_id = stable_id(
        "sku",
        capability.capability_id,
        product_name,
        product_outcome,
        usdc_text(price),
        canonical_json(detached_input),
        canonical_json(detached_output),
        canonical_json(criteria),
        maximum_latency_seconds,
        capacity_per_hour,
    )
    return ServiceSKU(
        sku_id=sku_id,
        capability_id=capability.capability_id,
        name=product_name,
        outcome=product_outcome,
        base_price_usdc=price,
        input_schema=detached_input,
        output_schema=detached_output,
        acceptance_criteria=criteria,
        maximum_latency_seconds=maximum_latency_seconds,
        capacity_per_hour=capacity_per_hour,
    )


def build_sku_catalog(
    capabilities: Iterable[CapabilityDescriptor],
    *,
    base_price_usdc: Decimal | int | str,
    acceptance_criteria: Iterable[object] = (),
    maximum_latency_seconds: int = 300,
    capacity_per_hour: int = 1,
) -> tuple[ServiceSKU, ...]:
    """Build a stable, capability-ID-ordered catalog.

    Duplicate capability IDs are rejected because silently choosing one would
    make catalog construction depend on input order.
    """

    by_id: dict[str, CapabilityDescriptor] = {}
    if isinstance(base_price_usdc, float):
        raise ContractError("binary float is not allowed for USDC")
    selected_criteria = tuple(acceptance_criteria)
    for capability in capabilities:
        if not isinstance(capability, CapabilityDescriptor):
            raise ContractError("all capabilities must be CapabilityDescriptor values")
        if capability.capability_id in by_id:
            raise ContractError(
                f"duplicate capability_id: {capability.capability_id}"
            )
        by_id[capability.capability_id] = capability
    return tuple(
        capability_to_sku(
            by_id[capability_id],
            base_price_usdc=base_price_usdc,
            acceptance_criteria=selected_criteria,
            maximum_latency_seconds=maximum_latency_seconds,
            capacity_per_hour=capacity_per_hour,
        )
        for capability_id in sorted(by_id)
    )


productize_capability = capability_to_sku
productize_capabilities = build_sku_catalog
