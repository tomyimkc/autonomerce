# Autonomerce metrics definitions

`version: 1` · `effective: 2026-07-31`

Metrics must be reproducible from transaction-level records over an explicit UTC
window. Synthetic, testnet, self, founder, reimbursed, circular, and affiliate
activity must remain visible as excluded classes rather than disappear.

## 1. Measurement record requirements

Every published snapshot must include:

- `periodStart` and `periodEnd` in UTC;
- generation timestamp;
- repository commit and deployed revision;
- schema version;
- source transaction IDs;
- evidence classification;
- inclusion/exclusion counts;
- calculation method;
- known gaps or late-arriving records.

Use exact decimal USDC strings. Do not use binary floating-point arithmetic.

## 2. Entity classifications

### Seller

- **Registered seller agent:** a unique seller record created during the window.
- **Activated seller agent:** a registered seller with at least one published
  SKU and an owner-bound commercial policy.
- **Externally activated seller agent:** an activated seller owned by a party
  outside the entrant/founder/affiliate group.

### Customer

- **External customer:** an arms-length person or organization outside the
  entrant, team, household, employer, controlled entities, and affiliates.
- **Paying external customer:** an external customer with at least one qualifying
  external mainnet settlement.
- **Delivered paying external customer:** a paying external customer with at
  least one contract-accepted delivery.

One organization counts once regardless of wallets, orders, or users, unless the
published method explains a different unit.

### Transaction classifications

| Classification | Moves funds | Counts as customer revenue |
|---|---:|---:|
| `synthetic` | no | no |
| `offline_mock` | no | no |
| `testnet` | test-value only | no |
| `mainnet_self` | yes | no |
| `mainnet_founder_or_affiliate` | yes | no |
| `mainnet_reimbursed_or_circular` | yes | no |
| `mainnet_external_customer` | yes | yes, subject to refund/cancellation treatment |

## 3. Product and funnel metrics

| Metric | Definition | Formula / notes |
|---|---|---|
| Registered seller agents | Unique seller records created | count distinct seller IDs |
| Activated seller agents | Sellers with policy + at least one SKU | count distinct qualifying seller IDs |
| External design partners | External parties with explicit design-partner agreement | count distinct parties; not customers unless paid |
| Proposals sent | Proposals transmitted to opted-in buyer needs | count proposal IDs; exclude drafts |
| Proposal acceptance rate | Share of sent proposals reaching accepted state | accepted distinct proposals / sent distinct proposals |
| Negotiated price change | Absolute and signed movement from first offered price to accepted price | report total/median and direction; do not use revision-to-revision double counting |
| Opt-in denial rate | Buyer/prospect attempts rejected for missing or expired opt-in | opt-in denials / prospect attempts |
| Policy denial rate | Commercial/payment attempts denied by deterministic policy | denials / authorization attempts |

If the denominator is zero, publish `null`, not `0%`, unless the schema explicitly
requires another representation.

## 4. Payment and revenue metrics

| Metric | Definition | Inclusion |
|---|---|---|
| Paid tasks | Distinct proposals with confirmed settlements | publish by classification; do not imply all are customers |
| Paid external tasks | Distinct proposals with `mainnet_external_customer` settlement | excludes self/founder/affiliate/reimbursed/testnet/synthetic |
| Gross external USDC revenue | Sum of qualifying external mainnet settlement amounts | before refunds and variable costs |
| Refunds/credits | USDC returned or credited for qualifying orders | subtract from gross revenue |
| Net external USDC revenue | Gross external revenue minus refunds/credits | recognized measurement value |
| Mocked payment volume | Sum of simulated amounts | technical telemetry only |
| Testnet payment volume | Sum of testnet amounts | integration telemetry only |
| Payment failures | Payment attempts ending in terminal/retryable failure | ambiguous `submitting` states reported separately |
| Duplicate payment attempts | Replayed/conflicting attempts blocked before duplicate settlement | attempts, not duplicate settled transfers |
| Duplicate settled payments | More than one confirmed settlement for one accepted proposal/idempotency contract | zero-tolerance metric |

The current API deliberately returns `paidTasks: null` until every confirmed
payment in scope has a verified, complete deal-evidence record. Once coverage
is complete:

- `paidTasks` counts all classified confirmed settlements;
- `paidExternalTasks` counts qualifying external customer-funded mainnet orders;
- `acceptedPaidExternalTasks` counts qualifying external orders whose delivery
  validator accepted fulfillment.

Technical settlement telemetry remains separate:
`confirmedLivePayments`, `mockedPaymentCount`, `unsupportedPaymentCount`,
`liveSettlementVolumeUsdc`, `mockedPaymentVolumeUsdc`, and
`unsupportedPaymentVolumeUsdc`.

## 5. Fulfillment and reliability metrics

| Metric | Definition | Formula |
|---|---|---|
| Successful fulfillment | Distinct paid proposals whose delivery validator accepted the contract | count accepted fulfillment IDs |
| Paid-order fulfillment rate | Paid proposals with accepted fulfillment / paid proposals | publish by transaction class |
| Median delivery time | Median elapsed seconds from payment confirmation to delivery verdict | use timestamps; do not substitute promised SLA |
| p95 delivery time | 95th percentile of the same elapsed duration | require sample count |
| Rejected deliveries | Fulfillments rejected by the contract validator | count and rate |
| End-to-end completion rate | Opted-in orders reaching confirmed payment and accepted delivery | completed / started eligible orders |
| Payment-to-delivery mismatch | Confirmed payments without a terminal delivery result by cutoff | count and age |

The API metric named `medianDeliverySeconds` measures elapsed time from payment
confirmation to an accepted delivery verdict when both timestamps are valid.
Offline mode keeps it in memory; the supported single-host live repository
persists its source events in SQLite. It is not full order-to-delivery duration.

## 6. Customer metrics

| Metric | Definition |
|---|---|
| Customer/problem interviews | Distinct external interviews with consented notes |
| Paying external customers | Distinct external customers with qualifying settlement |
| Repeat purchasers | Paying external customers with at least two qualifying paid orders |
| Repeat-purchase rate | Repeat purchasers / paying external customers |
| Customer rating | Mean/median consented rating with scale, count, and collection method |
| Repeat intent | Share of interviewed/delivered customers who explicitly said they intend another purchase; report separately from actual repeat purchase |
| Customer quote count | Quotes with exact text, context, and publication consent |

The current API identifies repeat buyers by buyer-agent URL over all confirmed
payments. Public business reporting must first filter to qualifying external
customer transactions and define the organization-level identity mapping.

## 7. Cost and margin metrics

Record variable costs per order where possible:

- Circle/payment/network fee;
- Gemini input/output/cached token cost;
- paid external-service cost;
- seller-agent variable compute;
- allocated variable infrastructure;
- refund/credit;
- other order-variable cost with description.

### Formulas

```text
net_revenue_usdc
= gross_external_revenue_usdc - refunds_usdc

variable_cogs_usdc
= circle_and_network_fees_usdc
+ gemini_cost_usdc
+ external_service_cost_usdc
+ seller_compute_cost_usdc
+ allocated_variable_infrastructure_usdc
+ other_variable_cost_usdc

gross_margin_usdc
= net_revenue_usdc - variable_cogs_usdc

gross_margin_percent
= gross_margin_usdc / net_revenue_usdc
```

If net revenue is zero, `grossMarginPercent` is `null`.

The current API returns `grossMarginUsdc: null` while any confirmed payment lacks
verified complete deal evidence. For complete qualifying external orders it
subtracts only the measured variable costs attributable to that qualifying
revenue cohort. Measured testnet, founder-sponsored, related-party, mocked, and
unsupported-network spend is reported separately as
`excludedPilotSpendUsdc`; it is not mixed into qualifying gross margin.
`grossMarginStatus` records whether the measurement/classification gate is
complete.

## 8. Autonomy metrics

| Metric | Definition |
|---|---|
| Autonomous order completion | Qualifying orders completed without a human approving the individual transaction |
| Autonomous completion rate | autonomous qualifying completions / qualifying completed orders |
| Checkout interruptions | Per-payment human approval prompts or manual transaction authorizations after policy setup |
| Policy setup events | Owner actions that create/change the standing envelope; not checkout interruptions |
| Emergency interventions | Human actions required after failure or ambiguity; report separately |

Do not claim “fully autonomous” from an unattended configuration flag. The
recorded run must show no per-payment approval and must preserve owner policy.

## 9. Required zero-tolerance metrics

Publish the count, including zero:

- payments above policy limit;
- arbitrary/unapproved destination-wallet settlements;
- duplicate settled payments;
- non-opted-in outbound contacts;
- secrets in public evidence;
- testnet/self/founder activity counted as customer revenue;
- seller outputs marked accepted without contract validation;
- public customer prompts without consent.

## 10. Current API field mapping

| API field | Safe interpretation |
|---|---|
| `registeredSellerAgents` | process-local registered sellers |
| `activatedSellerAgents` | process-local sellers with policy and SKU |
| `proposalsSent` | stored proposals in the current process |
| `proposalAcceptanceRate` | accepted-ID marks divided by proposals |
| `negotiatedPriceChangeUsdc` | sum of absolute revision deltas |
| `paidTasks` | null until verified evidence covers all confirmed payments; then all classified confirmed settlements |
| `paidExternalTasks` | verified qualifying external customer-funded mainnet orders |
| `acceptedPaidExternalTasks` | qualifying external orders with validator-accepted fulfillment |
| `confirmedLivePayments` | confirmed settlements on an explicit supported-mainnet allowlist; not automatically revenue |
| `mockedPaymentCount` | confirmed offline-mock/testnet technical payments |
| `unsupportedPaymentCount` | confirmed payments on unknown or unsupported networks; never revenue |
| `usdcRevenue` | net qualifying external revenue, or null while classification coverage is incomplete |
| `liveSettlementVolumeUsdc` | supported-mainnet confirmed volume; not automatically revenue |
| `mockedPaymentVolumeUsdc` | simulated/testnet-classified technical volume |
| `unsupportedPaymentVolumeUsdc` | confirmed unsupported-network technical volume |
| `successfulFulfillment` | accepted fulfillment receipts |
| `medianDeliverySeconds` | measured payment-confirmed to accepted-delivery elapsed time |
| `repeatPurchaseRate` | repeat verified paying customers / verified paying customers; null with no paying customers |
| `paymentFailures` | stored payment failure states |
| `policyDenials` | process-local denial counter |
| `duplicatePaymentCount` | blocked duplicate/conflict attempts |
| `grossMarginUsdc` | net qualifying revenue minus measured qualifying-order variable costs; null while coverage is incomplete |
| `excludedPilotSpendUsdc` | measured cost of excluded testnet/founder/related/mock/unsupported deals |
| `revenueClassification` | complete or explicitly unmeasured verified external-customer classification status |

Use the public revenue schema for submission metrics rather than copying the API
object without qualification.
