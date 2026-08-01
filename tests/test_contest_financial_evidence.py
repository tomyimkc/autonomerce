from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "evidence" / "templates" / "contest"
sys.path.insert(0, str(ROOT / "scripts"))

import build_contest_financial_evidence as builder  # noqa: E402


LIVE_FIELDS = [
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
]
CUSTOMER = "customer_000000000001"
USER = "user_000000000001"


def _load(name: str) -> dict:
    value = json.loads((TEMPLATES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _answers(evidence: dict) -> dict[int, dict]:
    return {
        item["fieldId"]: item
        for item in evidence["devpostCustomAnswerPayload"]["answers"]
    }


def _refresh_field_map_digest(facts: dict) -> None:
    field_map = facts["fieldMap"]
    digest_input = {
        key: value
        for key, value in field_map.items()
        if key != "snapshotDigest"
    }
    field_map["snapshotDigest"] = builder._canonical_digest(digest_input)


def _refresh_record_digest(record: dict, digest_key: str) -> None:
    record[digest_key] = builder._canonical_digest(
        {
            key: value
            for key, value in record.items()
            if key != digest_key
        }
    )


def _refresh_event_digests(event: dict) -> None:
    _refresh_record_digest(
        event["derivedDealClassification"],
        "sourceDigest",
    )
    _refresh_record_digest(event["relationship"], "evidenceDigest")
    _refresh_record_digest(event["settlement"], "evidenceDigest")
    _refresh_record_digest(event["revenueBasis"], "evidenceDigest")
    for refund in event["refunds"]:
        _refresh_record_digest(refund, "evidenceDigest")


def _with_customer_and_user(facts: dict) -> dict:
    facts["externalCustomers"] = [
        {
            "id": CUSTOMER,
            "nature": "arms_length_customer",
            "firstObservedAt": "2026-06-01T00:00:00Z",
        }
    ]
    facts["externalUsers"] = [
        {
            "id": USER,
            "customerId": CUSTOMER,
            "engagementClassification": "arms_length",
            "firstObservedAt": "2026-06-01T00:00:01Z",
        }
    ]
    return facts


def _valuation(amount: str, at: str, marker: str) -> dict:
    return {
        "amountUsd": amount,
        "rateUsdPerUsdc": "1",
        "valuedAt": at,
        "sourceType": "accounting_statement",
        "sourceDigest": f"sha256:{marker * 64}",
        "methodology": "Explicit documented USDC-to-USD event valuation.",
    }


def _refund(
    *,
    suffix: str = "000000000001",
    amount: str = "2",
    occurred_at: str = "2026-07-20T00:00:00Z",
    marker: str = "d",
) -> dict:
    value = {
        "id": f"refund_{suffix}",
        "occurredAt": occurred_at,
        "amountUsdc": amount,
        "evidenceDigest": f"sha256:{marker * 64}",
        "valuation": _valuation(amount, occurred_at, marker),
    }
    _refresh_record_digest(value, "evidenceDigest")
    return value


def _event(
    *,
    suffix: str = "000000000001",
    classification: str = "mainnet_external_customer",
    recognized_at: str = "2026-07-15T00:00:01Z",
    settlement_at: str = "2026-07-15T00:00:00Z",
    settlement_amount: str = "10",
    recognized_amount: str = "10",
    refunds: list[dict] | None = None,
    relationship_class: str = "arms_length",
    funding_class: str = "customer_funded",
    settlement_class: str = "mainnet",
    confirmed: bool = True,
    mocked: bool = False,
    customer_id: str | None = CUSTOMER,
    user_id: str | None = USER,
    counts_as_revenue: bool = True,
    external_customer: bool = True,
    basis_kind: str = "accepted_fulfillment",
    accepted_fulfillment: bool = True,
) -> dict:
    marker = suffix[-1]
    value = {
        "id": f"revenue_{suffix}",
        "classification": classification,
        "customerId": customer_id,
        "userId": user_id,
        "recognizedAt": recognized_at,
        "recognizedRevenueUsd": recognized_amount,
        "derivedDealClassification": {
            "schemaVersion": "autonomerce.deal-classification.v1",
            "sourceRecordId": f"deal_classification_{suffix}",
            "sourceDigest": f"sha256:{marker * 64}",
            "derivedBy": (
                "autonomerce.api.deal_classification.classify_deal"
            ),
            "derivedAt": recognized_at,
            "classification": classification,
            "settlementClass": settlement_class,
            "paymentConfirmed": confirmed,
            "paymentMocked": mocked,
            "externalCustomer": external_customer,
            "countsAsRevenue": counts_as_revenue,
            "acceptedFulfillment": accepted_fulfillment,
        },
        "relationship": {
            "relationshipClass": relationship_class,
            "fundingClass": funding_class,
            "evidenceDigest": f"sha256:{marker * 64}",
        },
        "settlement": {
            "settlementClass": settlement_class,
            "confirmed": confirmed,
            "mocked": mocked,
            "confirmedAt": settlement_at if confirmed else None,
            "network": "BASE" if settlement_class == "mainnet" else "ARC-TESTNET",
            "token": "USDC",
            "amountUsdc": settlement_amount,
            "transactionHash": (
                f"0x{marker * 64}" if confirmed else None
            ),
            "evidenceDigest": f"sha256:{marker * 64}",
            "valuation": _valuation(
                settlement_amount,
                settlement_at,
                marker,
            ),
        },
        "revenueBasis": {
            "kind": basis_kind,
            "acceptedFulfillment": accepted_fulfillment,
            "basisAt": recognized_at,
            "evidenceDigest": f"sha256:{marker * 64}",
            "description": (
                "Accepted fulfillment evidence establishes earned revenue."
                if basis_kind == "accepted_fulfillment"
                else "Explicit contract evidence establishes earned revenue."
            ),
        },
        "refunds": list(refunds or []),
    }
    _refresh_event_digests(value)
    return value


def _complete_expenses(facts: dict) -> None:
    facts["observedThrough"] = "2026-08-17T20:00:00Z"
    facts["asOf"] = "2026-08-17T20:00:00Z"
    facts["generatedAt"] = "2026-08-17T20:00:01Z"
    for month in facts["expenseMonths"]:
        month["completeness"] = "complete"
    july = next(
        item for item in facts["expenseMonths"] if item["month"] == "2026-07"
    )
    july["items"] = [
        {
            "id": "expense_000000000001",
            "occurredAt": "2026-07-10T00:00:00Z",
            "category": "hosting",
            "devpostCategory": "additional_expenses",
            "amountUsd": "3",
            "evidenceDigest": "sha256:" + ("e" * 64),
        }
    ]


def test_default_is_partial_as_of_and_blocks_unknown_expense_fields():
    facts = _load("contest-financial-facts.default.json")
    expected = _load("contest-financial-evidence.default.json")

    evidence = builder.build_financial_evidence(facts)

    assert evidence == builder.build_financial_evidence(deepcopy(facts))
    assert evidence == expected
    assert evidence["eligibilityWindow"] == {
        "start": "2026-05-19T17:00:00Z",
        "end": "2026-08-17T20:00:00Z",
    }
    assert evidence["observedThrough"] == "2026-08-01T00:00:00Z"
    assert evidence["asOf"] == "2026-08-01T00:00:00Z"
    assert evidence["reportingStatus"] == "partial_as_of"
    august = next(
        item for item in evidence["monthlySummary"] if item["month"] == "2026-08"
    )
    assert august["periodComplete"] is False
    assert august["expenseCompleteness"] == "unknown_total"
    answers = _answers(evidence)
    assert "partial through 2026-08-01T00:00:00Z" in answers[27419][
        "draftAnswer"
    ]
    for field_id in (27460, 27422, 27421, 27464):
        assert answers[field_id]["draftAnswer"] is None
        assert answers[field_id]["readiness"] == "blocked_incomplete_facts"
        assert answers[field_id]["pasteReady"] is False
        assert answers[field_id]["blockers"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda facts: facts.update(
            {"observedThrough": "2026-08-01T00:00:02Z"}
        ),
        lambda facts: facts.update({"asOf": "2026-08-01T00:00:02Z"}),
    ],
)
def test_observed_through_and_as_of_cannot_follow_generation(mutation):
    facts = _load("contest-financial-facts.default.json")
    mutation(facts)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="cannot be after generatedAt",
    ):
        builder.build_financial_evidence(facts)


def test_future_august_expense_month_cannot_be_marked_complete():
    facts = _load("contest-financial-facts.default.json")
    facts["expenseMonths"][-1]["completeness"] = "complete"

    with pytest.raises(
        builder.EvidenceValidationError,
        match="2026-08 cannot be complete",
    ):
        builder.build_financial_evidence(facts)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda event: event["derivedDealClassification"].update(
                {"countsAsRevenue": False}
            ),
            "qualifying revenue evidence",
        ),
        (
            lambda event: event["settlement"].update(
                {"transactionHash": None}
            ),
            "requires transactionHash",
        ),
        (
            lambda event: (
                event["settlement"].update({"mocked": True}),
                event["derivedDealClassification"].update(
                    {"paymentMocked": True}
                ),
            ),
            "qualifying revenue evidence",
        ),
        (
            lambda event: event["relationship"].update(
                {"relationshipClass": "founder"}
            ),
            "qualifying revenue evidence",
        ),
        (
            lambda event: event["revenueBasis"].update(
                {"acceptedFulfillment": False}
            ),
            "accepted-fulfillment basis",
        ),
        (
            lambda event: event.update({"recognizedRevenueUsd": "11"}),
            "qualifying revenue evidence",
        ),
    ],
)
def test_qualifying_revenue_requires_evidence_bound_compatibility(
    mutate,
    message,
):
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    event = _event()
    mutate(event)
    _refresh_event_digests(event)
    facts["revenueEvents"] = [event]

    with pytest.raises(builder.EvidenceValidationError, match=message):
        builder.build_financial_evidence(facts)


def test_explicit_earned_revenue_basis_is_supported_with_evidence():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    event = _event(
        basis_kind="explicit_earned_revenue_basis",
        accepted_fulfillment=False,
    )
    facts["revenueEvents"] = [event]

    evidence = builder.build_financial_evidence(facts)

    assert evidence["profitAndLoss"]["netRecognizedRevenueUsd"] == "10"
    assert "1 explicit earned-basis event(s)" in _answers(evidence)[27659][
        "draftAnswer"
    ]


def test_derived_classification_digest_must_bind_the_supplied_record():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    event = _event()
    event["derivedDealClassification"]["sourceDigest"] = (
        "sha256:" + ("0" * 64)
    )
    facts["revenueEvents"] = [event]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="does not bind the supplied record",
    ):
        builder.build_financial_evidence(facts)


def test_paying_counts_require_positive_net_revenue_after_refunds():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["revenueEvents"] = [
        _event(refunds=[_refund(amount="10")])
    ]

    evidence = builder.build_financial_evidence(facts)

    assert evidence["profitAndLoss"]["grossRecognizedRevenueUsd"] == "10"
    assert evidence["profitAndLoss"]["refundsUsd"] == "10"
    assert evidence["profitAndLoss"]["netRecognizedRevenueUsd"] == "0"
    assert evidence["counts"]["payingExternalCustomers"] == 0
    assert evidence["counts"]["payingExternalUsers"] == 0


def test_user_customer_binding_and_classification_must_match_event():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["externalUsers"][0]["customerId"] = None
    facts["revenueEvents"] = [_event()]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="user.customerId must match",
    ):
        builder.build_financial_evidence(facts)


def test_qualifying_customer_and_user_nature_must_be_compatible():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["externalCustomers"][0]["nature"] = "arms_length_prospect"
    facts["revenueEvents"] = [_event()]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="qualifying revenue evidence",
    ):
        builder.build_financial_evidence(facts)


def test_duplicate_confirmed_transaction_hash_cannot_double_count():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    first = _event(suffix="000000000006")
    second = _event(suffix="000000000007")
    second["settlement"]["transactionHash"] = first["settlement"][
        "transactionHash"
    ]
    _refresh_event_digests(second)
    facts["revenueEvents"] = [first, second]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="duplicate confirmed transaction hash",
    ):
        builder.build_financial_evidence(facts)


def test_one_customer_revenue_flags_100_percent_concentration():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["revenueEvents"] = [
        _event(refunds=[_refund(amount="2")])
    ]

    evidence = builder.build_financial_evidence(facts)
    concentration = evidence["customerConcentration"]

    assert concentration["positiveNetRevenueCustomerCount"] == 1
    assert concentration["largestCustomerNetRevenueUsd"] == "8"
    assert concentration["largestCustomerRevenueSharePercent"] == "100"
    assert concentration["limitationFlag"] is True
    assert "100%" in concentration["limitationReason"]
    assert any("100%" in item for item in evidence["limitations"])


def test_related_party_is_net_of_refunds_and_separate_from_funding_exclusions():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    founder = _event(
        suffix="000000000002",
        classification="mainnet_nonqualifying",
        recognized_amount="0",
        relationship_class="founder",
        funding_class="customer_funded",
        customer_id=None,
        user_id=None,
        counts_as_revenue=False,
        external_customer=False,
        refunds=[
            _refund(
                suffix="000000000002",
                amount="2",
                marker="2",
            )
        ],
    )
    reimbursed = _event(
        suffix="000000000003",
        classification="mainnet_nonqualifying",
        settlement_amount="5",
        recognized_amount="0",
        relationship_class="arms_length",
        funding_class="reimbursed",
        counts_as_revenue=False,
        refunds=[
            _refund(
                suffix="000000000003",
                amount="1",
                marker="3",
            )
        ],
    )
    facts["revenueEvents"] = [founder, reimbursed]

    evidence = builder.build_financial_evidence(facts)
    founder_row = next(
        item
        for item in evidence["relatedPartyReporting"]
        if item["relationshipClass"] == "founder"
    )
    reimbursed_row = next(
        item
        for item in evidence["fundingSourceExclusions"]
        if item["fundingClass"] == "reimbursed"
    )

    assert founder_row["grossSettlementValueUsd"] == "10"
    assert founder_row["refundsUsd"] == "2"
    assert founder_row["netRelatedPartyAmountUsd"] == "8"
    assert reimbursed_row["grossSettlementValueUsd"] == "5"
    assert reimbursed_row["refundsUsd"] == "1"
    assert reimbursed_row["netExcludedFundingUsd"] == "4"
    assert _answers(evidence)[27423]["draftAnswer"] == "$8.00"


@pytest.mark.parametrize(
    ("item_update", "message"),
    [
        (
            {"occurredAt": "2026-05-19T16:59:59Z"},
            "eligible observed interval",
        ),
        (
            {"occurredAt": "2026-06-01T00:00:00Z"},
            "UTC month",
        ),
        (
            {
                "category": "marketing",
                "devpostCategory": "cogs",
            },
            "incompatible Devpost category",
        ),
    ],
)
def test_expense_timestamps_and_category_mapping_fail_closed(
    item_update,
    message,
):
    facts = _load("contest-financial-facts.default.json")
    item = {
        "id": "expense_000000000001",
        "occurredAt": "2026-05-20T00:00:00Z",
        "category": "hosting",
        "devpostCategory": "additional_expenses",
        "amountUsd": "1",
        "evidenceDigest": "sha256:" + ("e" * 64),
    }
    item.update(item_update)
    facts["expenseMonths"][0]["items"] = [item]

    with pytest.raises(builder.EvidenceValidationError, match=message):
        builder.build_financial_evidence(facts)


def test_refunds_are_cash_basis_in_the_refund_month():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    event = _event(
        recognized_at="2026-06-30T23:59:59Z",
        settlement_at="2026-06-30T23:59:58Z",
        refunds=[
            _refund(
                amount="2",
                occurred_at="2026-07-01T00:00:00Z",
            )
        ],
    )
    facts["revenueEvents"] = [event]

    evidence = builder.build_financial_evidence(facts)
    months = {item["month"]: item for item in evidence["monthlySummary"]}

    assert months["2026-06"]["grossRecognizedRevenueUsd"] == "10"
    assert months["2026-06"]["refundsCashBasisUsd"] == "0"
    assert months["2026-06"]["netRecognizedRevenueUsd"] == "10"
    assert months["2026-07"]["grossRecognizedRevenueUsd"] == "0"
    assert months["2026-07"]["refundsCashBasisUsd"] == "2"
    assert months["2026-07"]["netRecognizedRevenueUsd"] == "-2"
    assert evidence["profitAndLoss"]["netRecognizedRevenueUsd"] == "8"


def test_field_map_is_owner_verified_snapshot_not_official_public_metadata():
    facts = _load("contest-financial-facts.default.json")
    evidence = builder.build_financial_evidence(facts)

    assert [
        (item["fieldId"], item["label"])
        for item in evidence["devpostCustomAnswerPayload"]["answers"]
    ] == LIVE_FIELDS
    assert evidence["fieldMapProvenance"]["sourceType"] == (
        "owner_verified_mcp_snapshot"
    )
    assert evidence["fieldMapProvenance"]["independentlyLiveVerified"] is False
    assert (
        evidence["devpostCustomAnswerPayload"][
            "fieldIdsOfficialPublicVerified"
        ]
        is False
    )


def test_field_map_pairing_uniqueness_and_digest_are_enforced():
    facts = _load("contest-financial-facts.default.json")
    facts["fieldMap"]["fields"][0]["label"] = "Wrong Label"
    _refresh_field_map_digest(facts)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="exactly match",
    ):
        builder.build_financial_evidence(facts)

    facts = _load("contest-financial-facts.default.json")
    facts["fieldMap"]["snapshotDigest"] = "sha256:" + ("0" * 64)
    with pytest.raises(
        builder.EvidenceValidationError,
        match="snapshotDigest",
    ):
        builder.build_financial_evidence(facts)


def test_revenue_explanation_states_counts_nature_and_basis():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["externalDesignPartners"] = [
        {
            "id": "design_partner_000000000001",
            "engagementClassification": "testnet_founder_sponsored_pilot",
            "firstObservedAt": "2026-07-01T00:00:00Z",
        }
    ]
    facts["revenueEvents"] = [_event()]

    explanation = _answers(
        builder.build_financial_evidence(facts)
    )[27659]["draftAnswer"]

    assert "1 external customer(s)" in explanation
    assert "1 external user(s)" in explanation
    assert "1 external design partner(s)" in explanation
    assert "arms_length=1" in explanation
    assert "1 accepted-fulfillment event(s)" in explanation
    assert "settlement/GMV" in explanation
    assert "net recognized revenue" in explanation


def test_complete_expenses_allow_explicit_zero_categories_only_after_window():
    facts = _load("contest-financial-facts.default.json")
    _complete_expenses(facts)

    evidence = builder.build_financial_evidence(facts)
    answers = _answers(evidence)

    assert evidence["reportingStatus"] == "complete_window"
    assert answers[27460]["draftAnswer"] == "$3.00"
    assert answers[27422]["draftAnswer"] == "$0.00"
    assert answers[27421]["draftAnswer"] == "$0.00"
    assert answers[27464]["draftAnswer"] == "$3.00"
    for field_id in (27460, 27422, 27421, 27464):
        assert answers[field_id]["readiness"] == "owner_review_required"
        assert answers[field_id]["pasteReady"] is False


def test_cent_rounding_must_reconcile_monthly_display_to_total():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    facts["revenueEvents"] = [
        _event(
            suffix="000000000004",
            recognized_at="2026-06-15T00:00:01Z",
            settlement_at="2026-06-15T00:00:00Z",
            settlement_amount="0.005",
            recognized_amount="0.005",
        ),
        _event(
            suffix="000000000005",
            recognized_at="2026-07-15T00:00:01Z",
            settlement_at="2026-07-15T00:00:00Z",
            settlement_amount="0.005",
            recognized_amount="0.005",
        ),
    ]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="cent-rounded monthly revenue cannot reconcile",
    ):
        builder.build_financial_evidence(facts)


def test_output_digest_and_arithmetic_invariants_are_enforced():
    evidence = builder.build_financial_evidence(
        _load("contest-financial-facts.default.json")
    )
    evidence["devpostCustomAnswerPayload"]["sourceEvidenceDigest"] = (
        "sha256:" + ("0" * 64)
    )

    with pytest.raises(
        builder.EvidenceValidationError,
        match="payload source digest mismatch",
    ):
        builder._validate_output_invariants(
            evidence,
            input_digest=evidence["inputDigestSha256"],
        )


@pytest.mark.parametrize(
    "note",
    [
        "Contact alice@example.com for details.",
        "Bearer customer-private-credential",  # secret-scan: allow-test-fixture
        "password=customer-secret",  # secret-scan: allow-test-fixture
    ],
)
def test_pii_or_credential_like_notes_are_rejected(note):
    facts = _load("contest-financial-facts.default.json")
    facts["notes"] = [note]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="credential/PII-like",
    ):
        builder.build_financial_evidence(facts)


def test_ids_must_be_opaque():
    facts = _load("contest-financial-facts.default.json")
    facts["externalCustomers"] = [
        {
            "id": "customer_alice_company",
            "nature": "arms_length_customer",
            "firstObservedAt": "2026-06-01T00:00:00Z",
        }
    ]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="does not match|opaque",
    ):
        builder.build_financial_evidence(facts)


def test_usdc_usd_valuation_must_have_provenance_and_reconcile():
    facts = _with_customer_and_user(
        _load("contest-financial-facts.default.json")
    )
    event = _event()
    event["settlement"]["valuation"]["amountUsd"] = "9"
    _refresh_event_digests(event)
    facts["revenueEvents"] = [event]

    with pytest.raises(
        builder.EvidenceValidationError,
        match="do not reconcile",
    ):
        builder.build_financial_evidence(facts)


def test_cli_writes_full_evidence_and_blocked_devpost_draft(tmp_path):
    output = tmp_path / "evidence.json"
    devpost = tmp_path / "devpost.json"

    assert (
        builder.main(
            [
                "--input",
                str(TEMPLATES / "contest-financial-facts.default.json"),
                "--output",
                str(output),
                "--devpost-output",
                str(devpost),
            ]
        )
        == 0
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    payload = json.loads(devpost.read_text(encoding="utf-8"))
    assert payload == evidence["devpostCustomAnswerPayload"]
    assert payload["draftOnly"] is True
    assert payload["automaticSubmission"] is False
    assert payload["requiresOwnerReview"] is True
    assert all(item["pasteReady"] is False for item in payload["answers"])
