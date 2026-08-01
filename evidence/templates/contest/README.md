# Contest financial evidence templates

`draft tooling only` · `not public evidence` · `fail closed`

The builder reads only explicit JSON facts. It has no network, wallet, billing,
deployment, credential, environment-variable, or clock access.

## Exact time boundary

The eligibility window is fixed:

```text
2026-05-19T17:00:00Z through 2026-08-17T20:00:00Z
```

Every snapshot supplies `observedThrough`, `asOf`, and `generatedAt`.
`observedThrough` and `asOf` must match and cannot be after generation time.
Records must fall between the eligibility start and `observedThrough`.

The default was generated on August 1, 2026 and is observed only through
`2026-08-01T00:00:00Z`. It does **not** certify later August dates as zero or
complete. The August monthly answer is explicitly marked partial.

## Revenue gate

`classification: mainnet_external_customer` is necessary but insufficient.
Qualifying recognized revenue additionally requires:

- provenance from `autonomerce.api.deal_classification.classify_deal`;
- a unique derived-classification record and SHA-256 digest;
- confirmed, non-mocked mainnet settlement;
- transaction hash and settlement-evidence digest;
- explicit event-level USDC/USD valuation and valuation-source digest;
- `arms_length` relationship and `customer_funded` funding;
- an explicitly listed external customer;
- `recognizedRevenueUsd` separate from settlement/GMV;
- accepted fulfillment or an explicit earned-revenue basis with evidence.

Derived-classification, relationship, settlement, revenue-basis, and refund
digests are recomputed over their supplied records. A syntactically valid but
stale/arbitrary digest is rejected.

Nonqualifying records must have zero recognized revenue. Testnet, offline mock,
synthetic, unsettled, related-party, founder-funded, reimbursed, and circular
activity cannot enter qualifying revenue by changing a string.

Paying customers and paying users require positive aggregate net recognized
revenue after refunds. If an event has a `userId`, that user's `customerId` must
equal the event customer and the user classification must be compatible.

## Refund and concentration accounting

Refund records require their own timestamp, evidence digest, and USDC/USD
valuation. Gross recognized revenue is assigned to `recognizedAt`; refunds are
subtracted in the UTC month in which the refund occurred.

The output computes the largest-customer share of net recognized revenue.
One-customer 100% concentration and any share above 40% produce an explicit
limitation.

Related-party reporting uses `relationshipClass` and net-of-refund settlement
value. `reimbursed` and `circular` are separate funding-source exclusions; they
are not mechanically labeled related-party revenue.

## Expense gate

Each expense requires:

- an `occurredAt` timestamp inside the observed eligible interval;
- a SHA-256 evidence digest;
- a detailed category;
- a compatible Devpost category.

The deterministic mapping is:

| Detailed category | Devpost category |
|---|---|
| Gemini, Circle/network, external service, seller compute, infrastructure | `cogs` |
| marketing, customer acquisition | `marketing_cac` |
| hosting, contractor, other | `additional_expenses` |

A month cannot be marked complete before its eligible interval ends. Because
the August 1 default precedes the August 17 eligibility end, August cannot be
complete. Unknown expense fields have `draftAnswer: null`,
`readiness: blocked_incomplete_facts`, and `pasteReady: false`.

## Field-map boundary

The numeric Devpost IDs are preserved from an **owner-verified MCP snapshot**.
They are not claimed as independently live-verified or official-public IDs.
The facts include `retrievedAt`, `revision`, exact ordered ID/label pairs, and a
canonical snapshot digest. Generated answers enforce unique IDs, unique labels,
and exact pairing.

## Privacy and deterministic display

Public-facing IDs must use opaque fixed-format identifiers. Notes containing
email addresses, phone-like strings, bearer credentials, passwords, API keys,
secrets, or private-key material are rejected.

Money uses exact `Decimal` arithmetic. Display values use deterministic
`ROUND_HALF_UP` cents. If rounded monthly revenue cannot reconcile exactly to
the rounded total, generation fails closed.

## Files and command

- `contest-financial-facts.schema.json` — strict v2 input contract.
- `contest-financial-facts.default.json` — August 1 partial-period default.
- `contest-financial-evidence.schema.json` — strict v2 output contract.
- `contest-financial-evidence.default.json` — deterministic default output.

```bash
python3 scripts/build_contest_financial_evidence.py \
  --input evidence/templates/contest/contest-financial-facts.default.json \
  --output /tmp/contest-financial-evidence.json \
  --devpost-output /tmp/devpost-custom-answers.json
```
