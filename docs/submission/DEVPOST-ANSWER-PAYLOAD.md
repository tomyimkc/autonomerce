# Devpost financial-answer payload

`draft only` · `owner review required` · `never automatic submission`

The generated object is an internal answer draft, not a Devpost API request and
not a claim that the field metadata was independently verified against an
official public source.

## Owner-verified field-map snapshot

The following numeric IDs and labels come from an owner-verified MCP snapshot
retrieved on `2026-08-01T00:00:00Z`, revision
`owner-verified-mcp-snapshot-2026-08-01-r1`.

They are preserved as `owner_verified_draft_values_not_official_public_ids`.
The payload sets `fieldIdsOfficialPublicVerified: false`.

| Field ID | Owner-verified label |
|---:|---|
| `27418` | `Total Revenue` |
| `27419` | `Monthly Revenue` |
| `27659` | `Revenue Explanation` |
| `27423` | `Related-Party Revenue` |
| `27460` | `Total Expenses` |
| `27422` | `COGS` |
| `27421` | `Marketing/CAC` |
| `27463` | `Marketing Explanation` |
| `27464` | `Additional Expenses` |
| `27465` | `Users Acquired` |
| `27466` | `Paying Users` |

The ordered mapping is digest-bound. Duplicate IDs, duplicate labels, changed
pairing, or a stale digest fails closed.

## Eligibility and as-of boundary

The exact eligibility window is:

```text
2026-05-19T17:00:00Z through 2026-08-17T20:00:00Z
```

The committed default is generated on August 1, 2026 and observed only through
`2026-08-01T00:00:00Z`. It is a partial-period snapshot. It does not certify
future August days as zero and does not mark August expenses complete.

## Answer readiness

Every answer contains:

- `readiness`;
- `pasteReady: false`;
- zero or more blockers.

Known revenue and count values use `readiness: owner_review_required`. Expense
fields remain `blocked_incomplete_facts` with `draftAnswer: null` until all four
eligible monthly expense intervals are explicitly complete.

Therefore the default's known expense-item sum of zero is **not** rendered as
zero total expenses, zero COGS, zero marketing/CAC, or zero additional
expenses. The marketing explanation states that missing amounts are not
inferred.

The entire payload also preserves:

```json
{
  "draftOnly": true,
  "automaticSubmission": false,
  "requiresOwnerReview": true,
  "fieldIdsOfficialPublicVerified": false
}
```

## Evidence-bound revenue

Qualifying revenue is net recognized revenue, not transaction volume. Each
qualifying event must be tied to:

- derived deal-classification provenance;
- confirmed non-mocked mainnet settlement;
- transaction and evidence digests;
- explicit USDC/USD valuation provenance;
- arms-length, customer-funded facts;
- accepted fulfillment or an explicit earned-revenue basis.

The builder recomputes the derived-classification, relationship, settlement,
revenue-basis, and refund digests from the supplied records. Digest-shaped text
alone does not satisfy the gate.

Refunds are subtracted in the month in which their cash event occurs. Paying
customers and users require positive aggregate net recognized revenue after
refunds.

The revenue explanation states the number and nature of observed customers,
users, and design partners, the number of paying customers/users, the revenue
basis mix, settlement/GMV versus recognized revenue, valuation policy, and any
customer-concentration limitation.

## Related-party and concentration boundary

Related-party values are grouped by explicit relationship class and reported
net of refunds. Reimbursed and circular funding are disclosed separately and
are not automatically mixed into related-party totals.

The output calculates largest-customer net-revenue share. A single paying
customer produces a 100% concentration limitation; any share above 40% is also
flagged.

## Generate

```bash
python3 scripts/build_contest_financial_evidence.py \
  --input evidence/templates/contest/contest-financial-facts.default.json \
  --output /tmp/contest-financial-evidence.json \
  --devpost-output /tmp/devpost-custom-answers.json
```

The owner must resolve every blocked field, inspect the source evidence, verify
the live form independently, and decide what—if anything—to enter manually.
