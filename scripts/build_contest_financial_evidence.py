#!/usr/bin/env python3
"""Build fail-closed contest financial evidence from explicit JSON facts."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "evidence" / "templates" / "contest"
DEFAULT_FACTS = TEMPLATE_DIR / "contest-financial-facts.default.json"

FACTS_VERSION = "autonomerce.contest.financial-facts.v2"
EVIDENCE_VERSION = "autonomerce.contest.financial-evidence.v2"
PAYLOAD_VERSION = "autonomerce.devpost.custom-answer-payload.v2"
ELIGIBLE_START = "2026-05-19T17:00:00Z"
ELIGIBLE_END = "2026-08-17T20:00:00Z"
QUALIFYING_CLASS = "mainnet_external_customer"
DERIVED_BY = "autonomerce.api.deal_classification.classify_deal"

DEVPOST_FIELDS = (
    (27418, "Total Revenue"),
    (27419, "Monthly Revenue"),
    (27659, "Revenue Explanation"),
    (27423, "Related-Party Revenue"),
    (27460, "Total Expenses"),
    (27422, "COGS"),
    (27421, "Marketing/CAC"),
    (27463, "Marketing Explanation"),
    (27464, "Additional Expenses"),
    (27465, "Users Acquired"),
    (27466, "Paying Users"),
)
REPORTING_MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08")
RELATED_RELATIONSHIPS = (
    "related_party",
    "self",
    "founder",
    "affiliate",
)
FUNDING_EXCLUSIONS = ("reimbursed", "circular")
NONQUALIFYING_CLASSES = (
    "synthetic",
    "offline_mock",
    "testnet",
    "mainnet_nonqualifying",
    "unsettled",
)
EXPENSE_CATEGORY_MAP = {
    "gemini": "cogs",
    "circle_network": "cogs",
    "external_service": "cogs",
    "seller_compute": "cogs",
    "infrastructure": "cogs",
    "marketing": "marketing_cac",
    "customer_acquisition": "marketing_cac",
    "hosting": "additional_expenses",
    "contractor": "additional_expenses",
    "other": "additional_expenses",
}

MONEY_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$")
SIGNED_MONEY_PATTERN = re.compile(
    r"^-?(0|[1-9][0-9]*)(\.[0-9]{1,6})?$"
)
DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
OPAQUE_ID_PATTERN = re.compile(
    r"^(customer|user|design_partner|revenue|refund|expense|"
    r"deal_classification)_[a-f0-9]{12}$"
)
PII_OR_CREDENTIAL_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret)\b\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:\+?[0-9][0-9 ()-]{7,}[0-9])\b"),
)


class EvidenceValidationError(ValueError):
    """Raised when input or generated evidence fails closed."""


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise EvidenceValidationError(f"unsupported schema type: {expected}")


def _validate_format(value: str, format_name: str, path: str) -> None:
    if format_name != "date-time":
        raise EvidenceValidationError(
            f"{path}: unsupported schema format {format_name!r}"
        )
    _parse_timestamp(value, path=path)


def validate_against_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "$",
) -> None:
    """Validate the strict JSON-Schema subset used by these templates."""

    expected_type = schema.get("type")
    if expected_type is not None:
        types = (
            list(expected_type)
            if isinstance(expected_type, list)
            else [expected_type]
        )
        if not any(_json_type_matches(value, item) for item in types):
            raise EvidenceValidationError(
                f"{path}: expected type {' or '.join(types)}, "
                f"got {type(value).__name__}"
            )

    if "const" in schema and value != schema["const"]:
        raise EvidenceValidationError(
            f"{path}: expected constant {schema['const']!r}"
        )
    if "enum" in schema and value not in schema["enum"]:
        raise EvidenceValidationError(
            f"{path}: value {value!r} is not in the allowed enum"
        )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise EvidenceValidationError(
                    f"{path}: missing required property {key!r}"
                )
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise EvidenceValidationError(
                    f"{path}: unexpected properties {extras}"
                )
        for key, item in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                validate_against_schema(
                    item,
                    child_schema,
                    path=f"{path}.{key}",
                )

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise EvidenceValidationError(
                f"{path}: expected at least {schema['minItems']} items"
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise EvidenceValidationError(
                f"{path}: expected at most {schema['maxItems']} items"
            )
        if schema.get("uniqueItems"):
            serialized = [
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(serialized) != len(set(serialized)):
                raise EvidenceValidationError(
                    f"{path}: duplicate array items are not allowed"
                )
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                validate_against_schema(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                )

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise EvidenceValidationError(
                f"{path}: string is shorter than {schema['minLength']}"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise EvidenceValidationError(
                f"{path}: string is longer than {schema['maxLength']}"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise EvidenceValidationError(
                f"{path}: value {value!r} does not match {pattern!r}"
            )
        format_name = schema.get("format")
        if format_name is not None:
            _validate_format(value, format_name, path)

    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        raise EvidenceValidationError(
            f"{path}: value must be at least {schema['minimum']}"
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{path}: top-level JSON must be an object")
    return value


def _parse_timestamp(value: str, *, path: str = "timestamp") -> datetime:
    if TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise EvidenceValidationError(
            f"{path}: timestamp must use exact UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _parse_money(value: str, *, path: str = "money") -> Decimal:
    if MONEY_PATTERN.fullmatch(value) is None:
        raise EvidenceValidationError(
            f"{path}: expected a non-negative decimal string with at most "
            "six fractional digits"
        )
    return Decimal(value)


def _format_money(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _round_cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _display_money(value: Decimal | str) -> str:
    decimal_value = (
        value if isinstance(value, Decimal) else Decimal(value)
    )
    return f"${_round_cents(decimal_value):,.2f}"


def _canonical_digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def _require_canonical_record_digest(
    record: Mapping[str, Any],
    *,
    digest_key: str,
    path: str,
) -> None:
    expected = _canonical_digest(
        {
            key: value
            for key, value in record.items()
            if key != digest_key
        }
    )
    if record[digest_key] != expected:
        raise EvidenceValidationError(
            f"{path}.{digest_key} does not bind the supplied record"
        )


def _month(timestamp: str) -> str:
    return _parse_timestamp(timestamp).strftime("%Y-%m")


def _require_unique_ids(
    records: Sequence[Mapping[str, Any]],
    label: str,
) -> None:
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise EvidenceValidationError(f"{label}: duplicate ids are not allowed")
    for record_id in ids:
        if OPAQUE_ID_PATTERN.fullmatch(record_id) is None:
            raise EvidenceValidationError(
                f"{label}: id {record_id!r} is not an opaque public-safe id"
            )


def _reject_sensitive_text(value: str, *, path: str) -> None:
    for pattern in PII_OR_CREDENTIAL_PATTERNS:
        if pattern.search(value):
            raise EvidenceValidationError(
                f"{path}: credential/PII-like text is not allowed"
            )


def _require_observed_timestamp(
    value: str,
    *,
    path: str,
    eligible_start: datetime,
    observed_through: datetime,
) -> datetime:
    parsed = _parse_timestamp(value, path=path)
    if parsed < eligible_start or parsed > observed_through:
        raise EvidenceValidationError(
            f"{path}: timestamp must be inside the eligible observed interval"
        )
    return parsed


def _month_eligible_end(month: str, eligible_end: datetime) -> datetime:
    year, month_number = (int(item) for item in month.split("-"))
    if month_number == 12:
        next_month = datetime(
            year + 1,
            1,
            1,
            tzinfo=timezone.utc,
        )
    else:
        next_month = datetime(
            year,
            month_number + 1,
            1,
            tzinfo=timezone.utc,
        )
    month_end = next_month - timedelta(seconds=1)
    return min(month_end, eligible_end)


def _validate_field_map(
    field_map: Mapping[str, Any],
    *,
    generated_at: datetime,
) -> None:
    if field_map["sourceType"] != "owner_verified_mcp_snapshot":
        raise EvidenceValidationError(
            "fieldMap.sourceType must be owner_verified_mcp_snapshot"
        )
    if field_map["independentlyLiveVerified"] is not False:
        raise EvidenceValidationError(
            "fieldMap must state independentlyLiveVerified=false"
        )
    if (
        field_map["numericIdStatus"]
        != "owner_verified_draft_values_not_official_public_ids"
    ):
        raise EvidenceValidationError(
            "fieldMap.numericIdStatus must preserve the draft-only boundary"
        )
    if _parse_timestamp(field_map["retrievedAt"]) > generated_at:
        raise EvidenceValidationError(
            "fieldMap.retrievedAt cannot be after generatedAt"
        )
    actual_pairs = [
        (item["fieldId"], item["label"]) for item in field_map["fields"]
    ]
    if actual_pairs != list(DEVPOST_FIELDS):
        raise EvidenceValidationError(
            "fieldMap fields must exactly match the owner-verified draft mapping"
        )
    if len({item[0] for item in actual_pairs}) != len(actual_pairs):
        raise EvidenceValidationError("fieldMap field IDs must be unique")
    if len({item[1] for item in actual_pairs}) != len(actual_pairs):
        raise EvidenceValidationError("fieldMap labels must be unique")
    digest_input = {
        key: value
        for key, value in field_map.items()
        if key != "snapshotDigest"
    }
    if field_map["snapshotDigest"] != _canonical_digest(digest_input):
        raise EvidenceValidationError(
            "fieldMap.snapshotDigest does not match the field-map snapshot"
        )


def _validate_valuation(
    *,
    amount_usdc: str,
    valuation: Mapping[str, Any],
    path: str,
    eligible_start: datetime,
    observed_through: datetime,
) -> Decimal:
    usdc = _parse_money(amount_usdc, path=f"{path}.amountUsdc")
    usd = _parse_money(valuation["amountUsd"], path=f"{path}.valuation.amountUsd")
    rate = _parse_money(
        valuation["rateUsdPerUsdc"],
        path=f"{path}.valuation.rateUsdPerUsdc",
    )
    if usdc * rate != usd:
        raise EvidenceValidationError(
            f"{path}: USDC amount, USD rate, and USD valuation do not reconcile"
        )
    _require_observed_timestamp(
        valuation["valuedAt"],
        path=f"{path}.valuation.valuedAt",
        eligible_start=eligible_start,
        observed_through=observed_through,
    )
    if not DIGEST_PATTERN.fullmatch(valuation["sourceDigest"]):
        raise EvidenceValidationError(
            f"{path}.valuation.sourceDigest must be a SHA-256 digest"
        )
    return usd


def _validate_semantics(facts: Mapping[str, Any]) -> dict[str, Any]:
    if facts["schemaVersion"] != FACTS_VERSION:
        raise EvidenceValidationError("unsupported facts schemaVersion")
    window = facts["eligibilityWindow"]
    if window != {"start": ELIGIBLE_START, "end": ELIGIBLE_END}:
        raise EvidenceValidationError(
            "eligibilityWindow must exactly match the XPRIZE window"
        )
    eligible_start = _parse_timestamp(ELIGIBLE_START)
    eligible_end = _parse_timestamp(ELIGIBLE_END)
    generated_at = _parse_timestamp(facts["generatedAt"], path="generatedAt")
    observed_through = _parse_timestamp(
        facts["observedThrough"],
        path="observedThrough",
    )
    as_of = _parse_timestamp(facts["asOf"], path="asOf")
    if observed_through > generated_at or as_of > generated_at:
        raise EvidenceValidationError(
            "observedThrough/asOf cannot be after generatedAt"
        )
    if observed_through != as_of:
        raise EvidenceValidationError(
            "observedThrough and asOf must match for this deterministic snapshot"
        )
    if observed_through < eligible_start or observed_through > eligible_end:
        raise EvidenceValidationError(
            "observedThrough must be inside the eligibility window"
        )

    _validate_field_map(facts["fieldMap"], generated_at=generated_at)
    valuation_policy = facts["usdcUsdValuationPolicy"]
    if valuation_policy != {
        "asset": "USDC",
        "reportingCurrency": "USD",
        "method": "event_level_explicit",
        "noPegInference": True,
    }:
        raise EvidenceValidationError(
            "usdcUsdValuationPolicy must require explicit event-level valuation"
        )

    customers = facts["externalCustomers"]
    users = facts["externalUsers"]
    design_partners = facts["externalDesignPartners"]
    events = facts["revenueEvents"]
    _require_unique_ids(customers, "externalCustomers")
    _require_unique_ids(users, "externalUsers")
    _require_unique_ids(design_partners, "externalDesignPartners")
    _require_unique_ids(events, "revenueEvents")

    customer_by_id = {item["id"]: item for item in customers}
    user_by_id = {item["id"]: item for item in users}
    for customer in customers:
        _require_observed_timestamp(
            customer["firstObservedAt"],
            path=f"externalCustomers[{customer['id']}].firstObservedAt",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
    for user in users:
        _require_observed_timestamp(
            user["firstObservedAt"],
            path=f"externalUsers[{user['id']}].firstObservedAt",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
        customer_id = user["customerId"]
        if customer_id is not None and customer_id not in customer_by_id:
            raise EvidenceValidationError(
                f"external user {user['id']!r} references an unknown customer"
            )
    for partner in design_partners:
        _require_observed_timestamp(
            partner["firstObservedAt"],
            path=(
                "externalDesignPartners"
                f"[{partner['id']}].firstObservedAt"
            ),
            eligible_start=eligible_start,
            observed_through=observed_through,
        )

    expense_months = facts["expenseMonths"]
    if [item["month"] for item in expense_months] != list(REPORTING_MONTHS):
        raise EvidenceValidationError(
            "expenseMonths must be May, June, July, August in order"
        )
    expense_items: list[Mapping[str, Any]] = []
    for month_record in expense_months:
        complete_through = _month_eligible_end(
            month_record["month"],
            eligible_end,
        )
        if (
            month_record["completeness"] == "complete"
            and observed_through < complete_through
        ):
            raise EvidenceValidationError(
                f"{month_record['month']} cannot be complete before "
                f"{complete_through.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            )
        for item in month_record["items"]:
            expense_items.append(item)
            occurred_at = _require_observed_timestamp(
                item["occurredAt"],
                path=f"expenseMonths[{month_record['month']}].occurredAt",
                eligible_start=eligible_start,
                observed_through=observed_through,
            )
            if occurred_at.strftime("%Y-%m") != month_record["month"]:
                raise EvidenceValidationError(
                    f"expense item {item['id']!r} must be in its UTC month"
                )
            expected_category = EXPENSE_CATEGORY_MAP[item["category"]]
            if item["devpostCategory"] != expected_category:
                raise EvidenceValidationError(
                    f"expense item {item['id']!r} has an incompatible "
                    "Devpost category"
                )
    _require_unique_ids(expense_items, "expense items")

    refund_records: list[Mapping[str, Any]] = []
    derived_ids: set[str] = set()
    transaction_hashes: set[str] = set()
    for event in events:
        event_path = f"revenueEvents[{event['id']}]"
        recognized_at = _require_observed_timestamp(
            event["recognizedAt"],
            path=f"{event_path}.recognizedAt",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
        recognized = _parse_money(
            event["recognizedRevenueUsd"],
            path=f"{event_path}.recognizedRevenueUsd",
        )
        customer_id = event["customerId"]
        user_id = event["userId"]
        if customer_id is not None and customer_id not in customer_by_id:
            raise EvidenceValidationError(
                f"{event_path}: unknown external customer"
            )
        if user_id is not None:
            user = user_by_id.get(user_id)
            if user is None:
                raise EvidenceValidationError(
                    f"{event_path}: unknown external user"
                )
            if user["customerId"] != customer_id:
                raise EvidenceValidationError(
                    f"{event_path}: user.customerId must match event.customerId"
                )

        relationship = event["relationship"]
        derived = event["derivedDealClassification"]
        settlement = event["settlement"]
        basis = event["revenueBasis"]
        derived_id = derived["sourceRecordId"]
        if derived_id in derived_ids:
            raise EvidenceValidationError(
                "derived deal-classification record IDs must be unique"
            )
        derived_ids.add(derived_id)
        if OPAQUE_ID_PATTERN.fullmatch(derived_id) is None:
            raise EvidenceValidationError(
                f"{event_path}: derived sourceRecordId must be opaque"
            )
        derived_at = _require_observed_timestamp(
            derived["derivedAt"],
            path=f"{event_path}.derivedDealClassification.derivedAt",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
        if derived["derivedBy"] != DERIVED_BY:
            raise EvidenceValidationError(
                f"{event_path}: unsupported deal-classification provenance"
            )
        _require_canonical_record_digest(
            derived,
            digest_key="sourceDigest",
            path=f"{event_path}.derivedDealClassification",
        )
        _require_canonical_record_digest(
            relationship,
            digest_key="evidenceDigest",
            path=f"{event_path}.relationship",
        )
        _require_canonical_record_digest(
            settlement,
            digest_key="evidenceDigest",
            path=f"{event_path}.settlement",
        )
        _require_canonical_record_digest(
            basis,
            digest_key="evidenceDigest",
            path=f"{event_path}.revenueBasis",
        )
        if derived["classification"] != event["classification"]:
            raise EvidenceValidationError(
                f"{event_path}: derived classification mismatch"
            )
        if derived["settlementClass"] != settlement["settlementClass"]:
            raise EvidenceValidationError(
                f"{event_path}: derived settlement class mismatch"
            )
        if derived["paymentConfirmed"] != settlement["confirmed"]:
            raise EvidenceValidationError(
                f"{event_path}: derived payment confirmation mismatch"
            )
        if derived["paymentMocked"] != settlement["mocked"]:
            raise EvidenceValidationError(
                f"{event_path}: derived mocked-payment mismatch"
            )

        settlement_usd = _validate_valuation(
            amount_usdc=settlement["amountUsdc"],
            valuation=settlement["valuation"],
            path=f"{event_path}.settlement",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
        confirmed_at: datetime | None = None
        if settlement["confirmedAt"] is not None:
            confirmed_at = _require_observed_timestamp(
                settlement["confirmedAt"],
                path=f"{event_path}.settlement.confirmedAt",
                eligible_start=eligible_start,
                observed_through=observed_through,
            )
        if settlement["confirmed"] and confirmed_at is None:
            raise EvidenceValidationError(
                f"{event_path}: confirmed settlement requires confirmedAt"
            )
        if settlement["confirmed"] and settlement["transactionHash"] is None:
            raise EvidenceValidationError(
                f"{event_path}: confirmed settlement requires transactionHash"
            )
        if settlement["confirmed"]:
            transaction_hash = settlement["transactionHash"].lower()
            if transaction_hash in transaction_hashes:
                raise EvidenceValidationError(
                    f"{event_path}: duplicate confirmed transaction hash"
                )
            transaction_hashes.add(transaction_hash)

        basis_at = _require_observed_timestamp(
            basis["basisAt"],
            path=f"{event_path}.revenueBasis.basisAt",
            eligible_start=eligible_start,
            observed_through=observed_through,
        )
        if basis_at != recognized_at:
            raise EvidenceValidationError(
                f"{event_path}: recognizedAt must equal revenue basis timestamp"
            )
        if basis["kind"] == "accepted_fulfillment":
            if not basis["acceptedFulfillment"]:
                raise EvidenceValidationError(
                    f"{event_path}: accepted-fulfillment basis must be accepted"
                )
        elif len(basis["description"].strip()) < 20:
            raise EvidenceValidationError(
                f"{event_path}: explicit earned-revenue basis is too vague"
            )
        if (
            derived["acceptedFulfillment"]
            != basis["acceptedFulfillment"]
        ):
            raise EvidenceValidationError(
                f"{event_path}: fulfillment provenance mismatch"
            )
        if confirmed_at is not None and confirmed_at > basis_at:
            raise EvidenceValidationError(
                f"{event_path}: revenue basis cannot predate settlement"
            )
        if derived_at < basis_at:
            raise EvidenceValidationError(
                f"{event_path}: derived classification cannot predate its basis"
            )

        event_refund_usd = Decimal("0")
        event_refund_usdc = Decimal("0")
        for refund in event["refunds"]:
            refund_records.append(refund)
            _require_canonical_record_digest(
                refund,
                digest_key="evidenceDigest",
                path=f"{event_path}.refunds[{refund['id']}]",
            )
            refund_at = _require_observed_timestamp(
                refund["occurredAt"],
                path=f"{event_path}.refunds[{refund['id']}].occurredAt",
                eligible_start=eligible_start,
                observed_through=observed_through,
            )
            if refund_at < recognized_at:
                raise EvidenceValidationError(
                    f"{event_path}: refund cannot predate recognized revenue"
                )
            refund_usd = _validate_valuation(
                amount_usdc=refund["amountUsdc"],
                valuation=refund["valuation"],
                path=f"{event_path}.refunds[{refund['id']}]",
                eligible_start=eligible_start,
                observed_through=observed_through,
            )
            event_refund_usd += refund_usd
            event_refund_usdc += _parse_money(refund["amountUsdc"])
        if event_refund_usdc > _parse_money(settlement["amountUsdc"]):
            raise EvidenceValidationError(
                f"{event_path}: refunds exceed settlement amount"
            )

        qualifying = event["classification"] == QUALIFYING_CLASS
        if qualifying:
            network = (settlement["network"] or "").upper()
            required_checks = (
                derived["countsAsRevenue"],
                derived["externalCustomer"],
                settlement["confirmed"],
                not settlement["mocked"],
                settlement["settlementClass"] == "mainnet",
                relationship["relationshipClass"] == "arms_length",
                relationship["fundingClass"] == "customer_funded",
                customer_id is not None,
                customer_by_id.get(customer_id, {}).get("nature")
                == "arms_length_customer",
                bool(network),
                not any(
                    marker in network
                    for marker in ("TEST", "SEPOLIA", "DEVNET")
                ),
                recognized > 0,
                recognized <= settlement_usd,
            )
            if not all(required_checks):
                raise EvidenceValidationError(
                    f"{event_path}: qualifying revenue evidence is incomplete "
                    "or incompatible"
                )
            if (
                user_id is not None
                and user_by_id[user_id]["engagementClassification"]
                != "arms_length"
            ):
                raise EvidenceValidationError(
                    f"{event_path}: qualifying user classification is incompatible"
                )
            if event_refund_usd > recognized:
                raise EvidenceValidationError(
                    f"{event_path}: refunds exceed recognized revenue"
                )
        else:
            if derived["countsAsRevenue"] or recognized != 0:
                raise EvidenceValidationError(
                    f"{event_path}: non-qualifying activity cannot recognize revenue"
                )
            expected_settlement_class = {
                "synthetic": "synthetic",
                "offline_mock": "offline_mock",
                "testnet": "testnet",
                "mainnet_nonqualifying": "mainnet",
                "unsettled": "unsettled",
            }[event["classification"]]
            if settlement["settlementClass"] != expected_settlement_class:
                raise EvidenceValidationError(
                    f"{event_path}: classification/settlement incompatibility"
                )
        if (
            relationship["fundingClass"] in FUNDING_EXCLUSIONS
            and qualifying
        ):
            raise EvidenceValidationError(
                f"{event_path}: reimbursed/circular funding cannot qualify"
            )
    _require_unique_ids(refund_records, "refund records")

    for note_index, note in enumerate(facts["notes"]):
        _reject_sensitive_text(note, path=f"notes[{note_index}]")

    return {
        "eligibleStart": eligible_start,
        "eligibleEnd": eligible_end,
        "generatedAt": generated_at,
        "observedThrough": observed_through,
        "customerById": customer_by_id,
        "userById": user_by_id,
    }


def _sum_money(values: Sequence[str]) -> Decimal:
    return sum((_parse_money(value) for value in values), Decimal("0"))


def _event_refunds_usd(event: Mapping[str, Any]) -> Decimal:
    return sum(
        (
            _parse_money(refund["valuation"]["amountUsd"])
            for refund in event["refunds"]
        ),
        Decimal("0"),
    )


def _event_settlement_usd(event: Mapping[str, Any]) -> Decimal:
    return _parse_money(event["settlement"]["valuation"]["amountUsd"])


def _expense_totals(
    facts: Mapping[str, Any],
) -> tuple[dict[str, Decimal], bool]:
    totals = {
        "cogs": Decimal("0"),
        "marketing_cac": Decimal("0"),
        "additional_expenses": Decimal("0"),
    }
    for month_record in facts["expenseMonths"]:
        for item in month_record["items"]:
            totals[item["devpostCategory"]] += _parse_money(item["amountUsd"])
    complete = all(
        item["completeness"] == "complete"
        for item in facts["expenseMonths"]
    )
    return totals, complete


def _classification_exclusions(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for classification in NONQUALIFYING_CLASSES:
        matching = [
            event
            for event in events
            if event["classification"] == classification
        ]
        gross = sum(
            (_event_settlement_usd(event) for event in matching),
            Decimal("0"),
        )
        refunds = sum(
            (_event_refunds_usd(event) for event in matching),
            Decimal("0"),
        )
        rows.append(
            {
                "classification": classification,
                "eventCount": len(matching),
                "grossSettlementValueUsd": _format_money(gross),
                "refundsUsd": _format_money(refunds),
                "netSettlementValueUsd": _format_money(gross - refunds),
                "eventIds": sorted(event["id"] for event in matching),
            }
        )
    return rows


def _relationship_rows(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relationship_class in RELATED_RELATIONSHIPS:
        matching = [
            event
            for event in events
            if event["relationship"]["relationshipClass"]
            == relationship_class
            and event["settlement"]["confirmed"]
        ]
        gross = sum(
            (_event_settlement_usd(event) for event in matching),
            Decimal("0"),
        )
        refunds = sum(
            (_event_refunds_usd(event) for event in matching),
            Decimal("0"),
        )
        rows.append(
            {
                "relationshipClass": relationship_class,
                "eventCount": len(matching),
                "grossSettlementValueUsd": _format_money(gross),
                "refundsUsd": _format_money(refunds),
                "netRelatedPartyAmountUsd": _format_money(gross - refunds),
                "eventIds": sorted(event["id"] for event in matching),
            }
        )
    return rows


def _funding_rows(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for funding_class in FUNDING_EXCLUSIONS:
        matching = [
            event
            for event in events
            if event["relationship"]["fundingClass"] == funding_class
            and event["settlement"]["confirmed"]
        ]
        gross = sum(
            (_event_settlement_usd(event) for event in matching),
            Decimal("0"),
        )
        refunds = sum(
            (_event_refunds_usd(event) for event in matching),
            Decimal("0"),
        )
        rows.append(
            {
                "fundingClass": funding_class,
                "eventCount": len(matching),
                "grossSettlementValueUsd": _format_money(gross),
                "refundsUsd": _format_money(refunds),
                "netExcludedFundingUsd": _format_money(gross - refunds),
                "eventIds": sorted(event["id"] for event in matching),
            }
        )
    return rows


def _answer(
    field_id: int,
    label: str,
    draft_answer: str | None,
    *,
    readiness: str,
    blockers: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "fieldId": field_id,
        "label": label,
        "draftAnswer": draft_answer,
        "readiness": readiness,
        "pasteReady": False,
        "blockers": list(blockers),
    }


def _validate_output_invariants(
    evidence: Mapping[str, Any],
    *,
    input_digest: str,
) -> None:
    if evidence["inputDigestSha256"] != input_digest:
        raise EvidenceValidationError("output input digest mismatch")
    payload = evidence["devpostCustomAnswerPayload"]
    if payload["sourceEvidenceDigest"] != input_digest:
        raise EvidenceValidationError("payload source digest mismatch")
    answer_pairs = [
        (item["fieldId"], item["label"]) for item in payload["answers"]
    ]
    if answer_pairs != list(DEVPOST_FIELDS):
        raise EvidenceValidationError("answer field ID/label pairing mismatch")
    if len({item[0] for item in answer_pairs}) != len(answer_pairs):
        raise EvidenceValidationError("answer field IDs are not unique")
    if len({item[1] for item in answer_pairs}) != len(answer_pairs):
        raise EvidenceValidationError("answer labels are not unique")

    pnl = evidence["profitAndLoss"]
    gross = Decimal(pnl["grossRecognizedRevenueUsd"])
    refunds = Decimal(pnl["refundsUsd"])
    net = Decimal(pnl["netRecognizedRevenueUsd"])
    if gross - refunds != net:
        raise EvidenceValidationError("P&L revenue arithmetic mismatch")
    monthly_gross = sum(
        (
            Decimal(item["grossRecognizedRevenueUsd"])
            for item in evidence["monthlySummary"]
        ),
        Decimal("0"),
    )
    monthly_refunds = sum(
        (
            Decimal(item["refundsCashBasisUsd"])
            for item in evidence["monthlySummary"]
        ),
        Decimal("0"),
    )
    monthly_net = sum(
        (
            Decimal(item["netRecognizedRevenueUsd"])
            for item in evidence["monthlySummary"]
        ),
        Decimal("0"),
    )
    if (monthly_gross, monthly_refunds, monthly_net) != (
        gross,
        refunds,
        net,
    ):
        raise EvidenceValidationError("monthly P&L arithmetic mismatch")
    known_categories = sum(
        (
            Decimal(pnl["knownCogsUsd"]),
            Decimal(pnl["knownMarketingCacUsd"]),
            Decimal(pnl["knownAdditionalExpensesUsd"]),
        ),
        Decimal("0"),
    )
    if known_categories != Decimal(pnl["knownExpensesUsd"]):
        raise EvidenceValidationError("expense category arithmetic mismatch")
    if pnl["totalExpensesUsd"] is not None:
        total_categories = sum(
            (
                Decimal(pnl["cogsUsd"]),
                Decimal(pnl["marketingCacUsd"]),
                Decimal(pnl["additionalExpensesUsd"]),
            ),
            Decimal("0"),
        )
        if total_categories != Decimal(pnl["totalExpensesUsd"]):
            raise EvidenceValidationError(
                "complete expense arithmetic mismatch"
            )

    reconciliation = evidence["displayReconciliation"]
    month_sum = sum(
        (
            Decimal(item["displayNetRevenueUsd"])
            for item in reconciliation["months"]
        ),
        Decimal("0"),
    )
    if month_sum != Decimal(reconciliation["displayTotalRevenueUsd"]):
        raise EvidenceValidationError(
            "displayed monthly revenue does not reconcile to displayed total"
        )
    if reconciliation["differenceUsd"] != "0":
        raise EvidenceValidationError(
            "display reconciliation difference must be zero"
        )
    if (
        payload["fieldMapSnapshotDigest"]
        != evidence["fieldMapProvenance"]["snapshotDigest"]
    ):
        raise EvidenceValidationError("field-map digest propagation mismatch")
    for answer in payload["answers"]:
        if answer["readiness"] == "blocked_incomplete_facts":
            if answer["draftAnswer"] is not None or not answer["blockers"]:
                raise EvidenceValidationError(
                    "blocked answer readiness invariant failed"
                )
        if answer["pasteReady"] is not False:
            raise EvidenceValidationError(
                "all generated answers must remain non-paste-ready"
            )

    for row in evidence["relatedPartyReporting"]:
        if (
            Decimal(row["grossSettlementValueUsd"])
            - Decimal(row["refundsUsd"])
            != Decimal(row["netRelatedPartyAmountUsd"])
        ):
            raise EvidenceValidationError(
                "related-party net-of-refund arithmetic mismatch"
            )


def build_financial_evidence(
    facts: Mapping[str, Any],
    *,
    template_dir: Path = TEMPLATE_DIR,
) -> dict[str, Any]:
    """Validate explicit facts and build deterministic fail-closed evidence."""

    facts_schema = _load_json(
        template_dir / "contest-financial-facts.schema.json"
    )
    evidence_schema = _load_json(
        template_dir / "contest-financial-evidence.schema.json"
    )
    validate_against_schema(facts, facts_schema)
    semantic = _validate_semantics(facts)
    input_digest = _canonical_digest(facts)
    events = facts["revenueEvents"]
    qualifying = [
        event for event in events if event["classification"] == QUALIFYING_CLASS
    ]

    gross_revenue = sum(
        (
            _parse_money(event["recognizedRevenueUsd"])
            for event in qualifying
        ),
        Decimal("0"),
    )
    qualifying_refunds = sum(
        (_event_refunds_usd(event) for event in qualifying),
        Decimal("0"),
    )
    net_revenue = gross_revenue - qualifying_refunds
    observed_settlement_gmv = sum(
        (
            _event_settlement_usd(event)
            for event in events
            if event["settlement"]["confirmed"]
        ),
        Decimal("0"),
    )

    customer_net: dict[str, Decimal] = defaultdict(Decimal)
    user_net: dict[str, Decimal] = defaultdict(Decimal)
    for event in qualifying:
        event_net = (
            _parse_money(event["recognizedRevenueUsd"])
            - _event_refunds_usd(event)
        )
        customer_net[event["customerId"]] += event_net
        if event["userId"] is not None:
            user_net[event["userId"]] += event_net
    paying_customers = {
        customer_id
        for customer_id, amount in customer_net.items()
        if amount > 0
    }
    paying_users = {
        user_id for user_id, amount in user_net.items() if amount > 0
    }

    positive_customer_revenue = {
        customer_id: amount
        for customer_id, amount in customer_net.items()
        if amount > 0
    }
    if positive_customer_revenue and net_revenue > 0:
        largest_revenue = max(positive_customer_revenue.values())
        share = (
            largest_revenue / net_revenue * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        concentration_flag = share > Decimal("40")
        if len(positive_customer_revenue) == 1:
            concentration_reason = (
                "One paying customer accounts for 100% of net recognized "
                "revenue in the observed period."
            )
        elif concentration_flag:
            concentration_reason = (
                "The largest paying customer exceeds the 40% net recognized "
                "revenue concentration threshold."
            )
        else:
            concentration_reason = None
    else:
        largest_revenue = Decimal("0")
        share = None
        concentration_flag = False
        concentration_reason = None

    expense_totals, expenses_complete = _expense_totals(facts)
    known_expenses = sum(expense_totals.values(), Decimal("0"))
    total_expenses = known_expenses if expenses_complete else None
    net_profit_loss = (
        net_revenue - total_expenses
        if total_expenses is not None
        else None
    )

    monthly_summary: list[dict[str, Any]] = []
    raw_monthly_net: dict[str, Decimal] = {}
    for month in REPORTING_MONTHS:
        month_gross = sum(
            (
                _parse_money(event["recognizedRevenueUsd"])
                for event in qualifying
                if _month(event["recognizedAt"]) == month
            ),
            Decimal("0"),
        )
        month_refunds = sum(
            (
                _parse_money(refund["valuation"]["amountUsd"])
                for event in qualifying
                for refund in event["refunds"]
                if _month(refund["occurredAt"]) == month
            ),
            Decimal("0"),
        )
        month_net = month_gross - month_refunds
        raw_monthly_net[month] = month_net
        month_record = next(
            item for item in facts["expenseMonths"] if item["month"] == month
        )
        month_known_expenses = sum(
            (
                _parse_money(item["amountUsd"])
                for item in month_record["items"]
            ),
            Decimal("0"),
        )
        month_complete = month_record["completeness"] == "complete"
        month_total_expenses = (
            month_known_expenses if month_complete else None
        )
        eligible_end = _month_eligible_end(
            month,
            semantic["eligibleEnd"],
        )
        monthly_summary.append(
            {
                "month": month,
                "eligibleThrough": eligible_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "observedThrough": facts["observedThrough"],
                "periodComplete": (
                    semantic["observedThrough"] >= eligible_end
                ),
                "grossRecognizedRevenueUsd": _format_money(month_gross),
                "refundsCashBasisUsd": _format_money(month_refunds),
                "netRecognizedRevenueUsd": _format_money(month_net),
                "knownExpensesUsd": _format_money(month_known_expenses),
                "totalExpensesUsd": (
                    _format_money(month_total_expenses)
                    if month_total_expenses is not None
                    else None
                ),
                "netProfitLossUsd": (
                    _format_money(month_net - month_total_expenses)
                    if month_total_expenses is not None
                    else None
                ),
                "expenseCompleteness": month_record["completeness"],
            }
        )

    display_months = [
        {
            "month": month,
            "displayNetRevenueUsd": format(
                _round_cents(raw_monthly_net[month]),
                ".2f",
            ),
        }
        for month in REPORTING_MONTHS
    ]
    displayed_month_sum = sum(
        (Decimal(item["displayNetRevenueUsd"]) for item in display_months),
        Decimal("0"),
    )
    displayed_total = _round_cents(net_revenue)
    if displayed_month_sum != displayed_total:
        raise EvidenceValidationError(
            "cent-rounded monthly revenue cannot reconcile to the total"
        )

    relationship_rows = _relationship_rows(events)
    related_net = sum(
        (
            Decimal(row["netRelatedPartyAmountUsd"])
            for row in relationship_rows
        ),
        Decimal("0"),
    )
    classification_rows = _classification_exclusions(events)
    funding_rows = _funding_rows(events)

    basis_counts = {
        "accepted_fulfillment": sum(
            1
            for event in qualifying
            if event["revenueBasis"]["kind"] == "accepted_fulfillment"
        ),
        "explicit_earned_revenue_basis": sum(
            1
            for event in qualifying
            if event["revenueBasis"]["kind"]
            == "explicit_earned_revenue_basis"
        ),
    }
    customer_natures: dict[str, int] = defaultdict(int)
    for customer in facts["externalCustomers"]:
        customer_natures[customer["nature"]] += 1
    user_natures: dict[str, int] = defaultdict(int)
    for user in facts["externalUsers"]:
        user_natures[user["engagementClassification"]] += 1
    design_partner_natures: dict[str, int] = defaultdict(int)
    for partner in facts["externalDesignPartners"]:
        design_partner_natures[partner["engagementClassification"]] += 1

    def nature_text(values: Mapping[str, int]) -> str:
        return (
            ", ".join(
                f"{key}={values[key]}"
                for key in sorted(values)
            )
            if values
            else "none"
        )

    customer_nature_text = nature_text(customer_natures)
    user_nature_text = nature_text(user_natures)
    design_partner_nature_text = nature_text(design_partner_natures)
    revenue_explanation = (
        f"Eligible window: {ELIGIBLE_START} through {ELIGIBLE_END}; financial "
        f"facts are observed only through {facts['observedThrough']} and "
        f"generated at {facts['generatedAt']}. The observed facts contain "
        f"{len(facts['externalCustomers'])} external customer(s), "
        f"{len(facts['externalUsers'])} external user(s), and "
        f"{len(facts['externalDesignPartners'])} external design partner(s); "
        f"customer nature counts: {customer_nature_text}; user nature counts: "
        f"{user_nature_text}; design-partner nature counts: "
        f"{design_partner_nature_text}. Paying counts require positive "
        f"net recognized revenue after cash-basis refunds: "
        f"{len(paying_customers)} paying customer(s) and "
        f"{len(paying_users)} paying user(s). Revenue is recognized only from "
        f"evidence-bound mainnet_external_customer classifications: "
        f"{basis_counts['accepted_fulfillment']} accepted-fulfillment event(s) "
        "and "
        f"{basis_counts['explicit_earned_revenue_basis']} explicit earned-basis "
        f"event(s). Confirmed settlement/GMV "
        f"({_display_money(observed_settlement_gmv)}) is distinct from net "
        f"recognized revenue ({_display_money(net_revenue)}). USDC-to-USD "
        "values require event-level source digests and no peg value is inferred."
    )
    if concentration_reason:
        revenue_explanation += f" Concentration limitation: {concentration_reason}"

    expense_blocker = (
        "Expense facts are incomplete through the full eligible window; "
        "the field is blocked and no missing amount is inferred as zero."
    )
    owner_review = "owner_review_required"
    blocked = "blocked_incomplete_facts"
    completion_by_month = {
        item["month"]: item["periodComplete"] for item in monthly_summary
    }
    monthly_answer = "; ".join(
        (
            f"{item['month']}: ${item['displayNetRevenueUsd']}"
            if completion_by_month[item["month"]]
            else (
                f"{item['month']}: ${item['displayNetRevenueUsd']} "
                f"(partial through {facts['observedThrough']})"
            )
        )
        for item in display_months
    )
    marketing_explanation = (
        (
            "All eligible expense periods are explicitly complete. "
            f"Marketing/CAC is {_display_money(expense_totals['marketing_cac'])} "
            "from items whose detailed category is mapped deterministically to "
            "devpostCategory=marketing_cac."
        )
        if expenses_complete
        else (
            "Marketing/CAC is blocked because the expense record is incomplete. "
            "Known marketing/CAC items total "
            f"{_display_money(expense_totals['marketing_cac'])}, but unknown "
            "amounts are not rendered as zero."
        )
    )

    answers = [
        _answer(
            27418,
            "Total Revenue",
            _display_money(net_revenue),
            readiness=owner_review,
        ),
        _answer(
            27419,
            "Monthly Revenue",
            monthly_answer,
            readiness=owner_review,
        ),
        _answer(
            27659,
            "Revenue Explanation",
            revenue_explanation,
            readiness=owner_review,
        ),
        _answer(
            27423,
            "Related-Party Revenue",
            _display_money(related_net),
            readiness=owner_review,
        ),
        _answer(
            27460,
            "Total Expenses",
            (
                _display_money(total_expenses)
                if total_expenses is not None
                else None
            ),
            readiness=(owner_review if expenses_complete else blocked),
            blockers=(() if expenses_complete else (expense_blocker,)),
        ),
        _answer(
            27422,
            "COGS",
            (
                _display_money(expense_totals["cogs"])
                if expenses_complete
                else None
            ),
            readiness=(owner_review if expenses_complete else blocked),
            blockers=(() if expenses_complete else (expense_blocker,)),
        ),
        _answer(
            27421,
            "Marketing/CAC",
            (
                _display_money(expense_totals["marketing_cac"])
                if expenses_complete
                else None
            ),
            readiness=(owner_review if expenses_complete else blocked),
            blockers=(() if expenses_complete else (expense_blocker,)),
        ),
        _answer(
            27463,
            "Marketing Explanation",
            marketing_explanation,
            readiness=owner_review,
        ),
        _answer(
            27464,
            "Additional Expenses",
            (
                _display_money(expense_totals["additional_expenses"])
                if expenses_complete
                else None
            ),
            readiness=(owner_review if expenses_complete else blocked),
            blockers=(() if expenses_complete else (expense_blocker,)),
        ),
        _answer(
            27465,
            "Users Acquired",
            str(len(facts["externalUsers"])),
            readiness=owner_review,
        ),
        _answer(
            27466,
            "Paying Users",
            str(len(paying_users)),
            readiness=owner_review,
        ),
    ]

    limitations = list(facts["notes"])
    if semantic["observedThrough"] < semantic["eligibleEnd"]:
        limitations.append(
            "This is a partial-period snapshot; dates after observedThrough "
            "are not certified as zero or complete."
        )
    if not expenses_complete:
        limitations.append(
            "Expense answers are blocked because the full eligible expense "
            "record is incomplete."
        )
    if concentration_reason:
        limitations.append(concentration_reason)
    if not qualifying:
        limitations.append(
            "No evidence-bound qualifying recognized-revenue event was supplied."
        )

    evidence = {
        "schemaVersion": EVIDENCE_VERSION,
        "recordKind": "contest_financial_evidence",
        "projectName": facts["projectName"],
        "eligibilityWindow": dict(facts["eligibilityWindow"]),
        "observedThrough": facts["observedThrough"],
        "asOf": facts["asOf"],
        "generatedAt": facts["generatedAt"],
        "reportingStatus": (
            "complete_window"
            if semantic["observedThrough"] >= semantic["eligibleEnd"]
            else "partial_as_of"
        ),
        "currency": "USD",
        "inputDigestSha256": input_digest,
        "usdcUsdValuationPolicy": dict(facts["usdcUsdValuationPolicy"]),
        "profitAndLoss": {
            "observedSettlementGmvUsd": _format_money(
                observed_settlement_gmv
            ),
            "grossRecognizedRevenueUsd": _format_money(gross_revenue),
            "refundsUsd": _format_money(qualifying_refunds),
            "netRecognizedRevenueUsd": _format_money(net_revenue),
            "knownExpensesUsd": _format_money(known_expenses),
            "knownCogsUsd": _format_money(expense_totals["cogs"]),
            "knownMarketingCacUsd": _format_money(
                expense_totals["marketing_cac"]
            ),
            "knownAdditionalExpensesUsd": _format_money(
                expense_totals["additional_expenses"]
            ),
            "totalExpensesUsd": (
                _format_money(total_expenses)
                if total_expenses is not None
                else None
            ),
            "cogsUsd": (
                _format_money(expense_totals["cogs"])
                if expenses_complete
                else None
            ),
            "marketingCacUsd": (
                _format_money(expense_totals["marketing_cac"])
                if expenses_complete
                else None
            ),
            "additionalExpensesUsd": (
                _format_money(expense_totals["additional_expenses"])
                if expenses_complete
                else None
            ),
            "netProfitLossUsd": (
                _format_money(net_profit_loss)
                if net_profit_loss is not None
                else None
            ),
            "expenseCompleteness": (
                "complete" if expenses_complete else "unknown_total"
            ),
        },
        "monthlySummary": monthly_summary,
        "counts": {
            "externalCustomers": len(facts["externalCustomers"]),
            "externalUsers": len(facts["externalUsers"]),
            "externalDesignPartners": len(
                facts["externalDesignPartners"]
            ),
            "payingExternalCustomers": len(paying_customers),
            "payingExternalUsers": len(paying_users),
            "qualifyingRevenueEvents": len(qualifying),
        },
        "customerConcentration": {
            "positiveNetRevenueCustomerCount": len(
                positive_customer_revenue
            ),
            "largestCustomerNetRevenueUsd": _format_money(largest_revenue),
            "largestCustomerRevenueSharePercent": (
                _format_money(share) if share is not None else None
            ),
            "thresholdPercent": "40",
            "limitationFlag": concentration_flag,
            "limitationReason": concentration_reason,
        },
        "classificationExclusions": classification_rows,
        "relatedPartyReporting": relationship_rows,
        "fundingSourceExclusions": funding_rows,
        "displayReconciliation": {
            "roundingMode": "ROUND_HALF_UP_TO_CENTS",
            "months": display_months,
            "displayTotalRevenueUsd": format(displayed_total, ".2f"),
            "displayMonthlySumUsd": format(displayed_month_sum, ".2f"),
            "differenceUsd": _format_money(
                displayed_month_sum - displayed_total
            ),
        },
        "fieldMapProvenance": {
            key: value
            for key, value in facts["fieldMap"].items()
            if key != "fields"
        },
        "devpostCustomAnswerPayload": {
            "schemaVersion": PAYLOAD_VERSION,
            "draftOnly": True,
            "automaticSubmission": False,
            "requiresOwnerReview": True,
            "fieldIdsOfficialPublicVerified": False,
            "sourceEvidenceDigest": input_digest,
            "fieldMapSnapshotDigest": facts["fieldMap"]["snapshotDigest"],
            "answers": answers,
        },
        "privacyValidation": {
            "status": "passed",
            "opaqueIdsRequired": True,
            "credentialOrPiiLikeNotesRejected": True,
        },
        "limitations": limitations,
    }
    _validate_output_invariants(evidence, input_digest=input_digest)
    validate_against_schema(evidence, evidence_schema)
    return evidence


def _serialize(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize(value), encoding="utf-8")
    path.chmod(0o600)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic contest financial evidence from explicit, "
            "provenance-bound JSON facts."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_FACTS,
        help=f"facts JSON (default: {DEFAULT_FACTS})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write full evidence JSON here; otherwise print to stdout",
    )
    parser.add_argument(
        "--devpost-output",
        type=Path,
        help="optionally write only the blocked/draft answer payload",
    )
    args = parser.parse_args(argv)

    try:
        facts = _load_json(args.input)
        evidence = build_financial_evidence(facts)
        if args.output is None:
            print(_serialize(evidence), end="")
        else:
            _write_json(args.output, evidence)
        if args.devpost_output is not None:
            _write_json(
                args.devpost_output,
                evidence["devpostCustomAnswerPayload"],
            )
    except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
