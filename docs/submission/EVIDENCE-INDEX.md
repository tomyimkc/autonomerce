# Autonomerce / OfferRail — evidence index

`draft snapshot: 2026-07-31` · `candidateOnly: true` · `canClaimAGI: false`

This index maps each judge-facing statement to the narrowest public artifact
that can support it. A file path proves that implementation or a reproducible
verification route exists; it does not prove that the final submission revision
passed, that an external service was used, or that a business result occurred.

## Current verdict

| Area | Current approved state | Safe public wording |
|---|---|---|
| OfferRail lifecycle | implemented; reproducible offline demo available | “Integrated credential-free offline workflow; fixtures only.” |
| Gemini | deployed Vertex AI productization call recorded on the private Cloud Run API | “One deployed `gemini-2.5-flash` call productized the synthetic source-verification seller; payment remained offline.” |
| Circle | one bounded Circle Agent Wallet Arc testnet transfer independently verified; deployed Gemini order still uses offline payment | “0.10 USDC Arc testnet integration and idempotent replay verified; not revenue or a deployed end-to-end order.” |
| Web/API | public Cloud Run LIVE BFF connected to a private IAM-protected API | “Public application is deployed; funds movement is disabled.” |
| Customers and revenue | no approved public evidence | “Not yet evidenced.” |
| Circle prize eligibility | wallet and transaction proof available; testnet sufficiency is not assumed; final video and deployed order linkage incomplete | “Targeting the prize with testnet evidence; final eligibility proof is still pending.” |

The credential-free offline demo remains synthetic. Separately, the public
Cloud Run trace establishes deployed Gemini productization and the private API
boundary. Its buyer, seller, payment, and fulfillment evidence is synthetic.
The separate Circle trace establishes one testnet settlement only. Neither
trace establishes a customer, revenue, accepted external delivery, mainnet, or
production claim.

## Evidence status key

| Status | Requirement |
|---|---|
| `AVAILABLE` | public repository artifact exists and directly supports the narrow implementation/documentation claim |
| `REPRODUCIBLE` | a judge can run the documented credential-free verification route; attach a public run receipt before claiming the submission revision passed |
| `PLACEHOLDER` | real evidence is required and no approved public artifact is present |
| `BLOCKING` | the absent artifact blocks the associated eligibility or outcome claim |

Evidence classifications remain separate:
`synthetic`, `offline_verified`, `testnet_verified`, `live_verified`,
`external_measured`, and `planned`.

## Judge entry points

| ID | Purpose | Artifact | Status |
|---|---|---|---|
| J-01 | 30-second product and evidence orientation | [`JUDGE-QUICKSTART.md`](JUDGE-QUICKSTART.md) | `AVAILABLE` |
| J-02 | Full submission source library and replacement rules | [`DEVPOST-DRAFT.md`](DEVPOST-DRAFT.md) | `AVAILABLE` |
| J-02A | Paste-ready 500–1000 word narrative candidate | [`DEVPOST-FINAL-CANDIDATE.md`](DEVPOST-FINAL-CANDIDATE.md) | `AVAILABLE`; owner review required |
| J-03 | Final live/offline operating sequence | [`DEMO-RUNBOOK.md`](DEMO-RUNBOOK.md) | `AVAILABLE` |
| J-04 | Detailed three-minute shot plan | [`VIDEO-STORYBOARD.md`](VIDEO-STORYBOARD.md) | `AVAILABLE` |
| J-05 | Current gaps and non-goals | [`KNOWN-LIMITATIONS.md`](KNOWN-LIMITATIONS.md) | `AVAILABLE` |
| J-06 | Final judge audit | [`JUDGE-CHECKLIST.md`](JUDGE-CHECKLIST.md) | `AVAILABLE` |
| J-07 | Owner setup and publication gates | [`SETUP-PROOF-CHECKLIST.md`](SETUP-PROOF-CHECKLIST.md) | `AVAILABLE` |
| J-08 | Metric definitions and exclusions | [`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md) | `AVAILABLE` |

## Proof chain for the recorded order

The final judged order should use one stable `orderId` and link every artifact
below. Do not assemble one apparent order from unrelated runs.

| Step | Required public fields | Current artifact | Final evidence placeholder |
|---|---|---|---|
| Build identity | repository commit, deployed revision, UTC timestamp, public app URL | [`../../evidence/public/build-identity.json`](../../evidence/public/build-identity.json) | available |
| Seller capability | manifest/card type, capability ID, safe public fields | [`../../examples/fixtures/seller-agent-card.json`](../../examples/fixtures/seller-agent-card.json) is synthetic | `[REDACTED_REAL_SELLER_CAPABILITY_URL]` |
| Gemini decision | operation, requested model, served model if available, config version, UTC time, latency, token/cost record, structured output hash, resulting SKU/proposal ID | [`../../evidence/public/gemini-call.redacted.json`](../../evidence/public/gemini-call.redacted.json); served model and token/cost fields remain unavailable | available with stated gaps |
| Owner policy | policy ID/version, price/capacity bounds, network/token, wallet/recipient constraints, unattended setting | policy implementation listed in O-03 and C-02 | `[PUBLIC_COMMERCIAL_AND_WALLET_POLICY_URL]` |
| Buyer opt-in | anonymized buyer/need ID, active consent reference, scope, UTC time | synthetic fixture and enforcement code listed in S-01 through S-03 | `[PUBLIC_OPT_IN_EVIDENCE_URL]` |
| Proposal/negotiation | proposal ID, revisions, exact amount/scope, expiry, deterministic reason code | OfferRail and sales artifacts listed below | `[PUBLIC_PROPOSAL_EVIDENCE_URL]` |
| Circle settlement | Agent Wallet address, network, canonical USDC, exact amount, payer/payee, transaction hash, explorer URL, confirmation time, idempotency result | [`../../evidence/public/circle-arc-testnet-transaction.public.json`](../../evidence/public/circle-arc-testnet-transaction.public.json) and [`../../evidence/public/wallet-policy.redacted.json`](../../evidence/public/wallet-policy.redacted.json) | testnet settlement available; deployed-order linkage pending |
| Fulfillment | seller endpoint class, payment ID, artifact hash, validator, per-criterion results, delivery time | implementation and tests listed in F-01 through F-04 | `[PUBLIC_FULFILLMENT_EVIDENCE_URL]` |
| Receipt publication | order/proposal/payment/fulfillment IDs, evidence classification, redacted fields, publication consent reference | implementation listed in R-01 through R-05 | `[PUBLIC_REDACTED_RECEIPT_URL]` |
| Business snapshot | fixed UTC window, external-customer classification, exclusions, refunds, costs, revenue, margin, repeat denominator | templates and definitions listed in B-01 through B-05 | `[PUBLIC_REVENUE_AND_UNIT_ECONOMICS_URL]` |

## Rubric-to-proof map

### Build with Gemini — Business Viability

| Claim or judge question | Current proof | Classification | Missing proof |
|---|---|---|---|
| Is there a workable business model? | fee/revenue-share model and order-level cost formula in [`DEVPOST-DRAFT.md`](DEVPOST-DRAFT.md) and [`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md) | `planned` economics | `[MEASURED_ORDER_LEVEL_COSTS_URL]` |
| Are customers and revenue real? | schemas deliberately exclude synthetic/testnet/self/founder/affiliate/reimbursed/circular activity | no approved business result | `[QUALIFYING_EXTERNAL_CUSTOMER_RECORDS_URL]` and `[EXTERNAL_MAINNET_TRANSACTION_INDEX_URL]` |
| Was paid work delivered? | separate fulfillment contract and receipt code | offline fixtures only | `[ORDER_LINKED_ACCEPTED_DELIVERY_URL]` |
| Is margin measured? | reproducible formula and zero/null rules | no measured variable costs | `[PUBLIC_MARGIN_SNAPSHOT_URL]` |
| Are all expenses and customer-acquisition costs disclosed? | metric definitions and zero/null rules exist | no approved expense statement | `[PUBLIC_P_AND_L_URL]` with hosting, Gemini, Circle/network, external service, contractor, marketing, and acquisition spend |
| Is the model sustainable? | adapter boundaries, deployment docs, SQLite single-host topology, fail-closed preflight, and explicit limitations | feasibility documentation | public deployment, measured reliability, repeat behavior, design-partner evidence, and an honest scale plan beyond the single-host topology |

### Build with Gemini — AI-Native Operations

| Claim or judge question | Current proof | Classification | Missing proof |
|---|---|---|---|
| Is Gemini part of operational logic? | deployed productization call plus `GeminiDecisionProvider`, productizer, fit, proposal, negotiation, and delivery decision boundaries | `live_verified` for productization only | broader deployed-order evidence for other decision stages |
| Is the output structured? | typed request/response models and provider tests | code/test target | `[REDACTED_LIVE_STRUCTURED_OUTPUT_URL]` |
| Is Gemini materially used? | the deployed call produced the SKU used by the recorded synthetic order | productization is live; settlement remains offline | external-customer proof and broader decision-stage evidence |
| Can the model authorize money or broaden scope? | deterministic clamps and security tests | reproducible offline | `[PUBLIC_CI_RUN_URL]` for final revision |
| Is model identity known? | provider supports configured model metadata | no approved live receipt | requested/served model, timestamp, latency, config, usage, and cost record |

### Build with Gemini — Category Impact: Entrepreneurship & Job Creation

| Claim or judge question | Current proof | Classification | Missing proof |
|---|---|---|---|
| Is the customer problem concrete? | first seller wedge and commercial lifecycle in [`../../README.md`](../../README.md); interview method in [`CUSTOMER-INTERVIEW-TEMPLATE.md`](CUSTOMER-INTERVIEW-TEMPLATE.md) | `planned` for external demand | `[CONSENTED_EXTERNAL_INTERVIEW_INDEX_URL]` |
| Can an existing agent become a seller? | A2A/manifest ingestion, SKU, policy, proposal, payment, fulfillment, and receipt path | offline implementation | `[EXTERNAL_SELLER_ONBOARDING_URL]` |
| Is seller activation measurable? | definition in [`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md) | metric defined, not measured externally | `[SELLER_ACTIVATION_SNAPSHOT_URL]` |
| Is the impact broader than one fixture? | portable OfferRail contracts and adapter boundaries | architectural portability only | `[EXTERNAL_DESIGN_PARTNER_URLS]` and proportionate adoption statement |
| Does this create economic opportunity? | product thesis and fee/revenue-share model | path-to-impact claim only | external seller/customer/orders and measured economics; do not substitute projected or unsupported job counts |
| Is the experience useful to a non-developer? | synthetic Next.js replay and owner workflow code | synthetic/offline only | deployed connected flow and `[EXTERNAL_USER_FEEDBACK_URL]` |

### Circle Agentic Economy Prize

Circle eligibility and judging claims require the final live artifacts in this
section. Implementation alone is not a substitute.

| Criterion | Current proof | Blocking live proof |
|---|---|---|
| Required Gemini usage | provider and decision integration code | `[LIVE_GEMINI_CALL_EVIDENCE_URL]` |
| Required Circle Agent Stack / Agent Wallet usage | guarded lane plus redacted wallet/policy evidence | final video/product-surface confirmation |
| Agent autonomously makes or receives real USDC | operator-triggered bounded runner completed one testnet transfer with no Circle approval prompt | final uninterrupted recorded order and official eligibility recheck |
| Public repository | project export tooling and disclosure documents exist | `[PUBLIC_REPOSITORY_URL]` |
| Creativeness & Innovation | OfferRail binds proposal, settlement, delivery, and receipt | working public flow and accurately scoped comparison |
| Centrality to Business | settlement authorization is bound to the accepted proposal | one demonstrated commercial order whose loop depends on the Circle settlement |
| Technical Depth & Autonomy | policy, durable idempotency, verification, reconciliation, x402 parser, separate delivery state | live wallet policy, confirmed transaction, idempotent replay, and failure behavior |
| Customer Experience | owner workflow and synthetic Next.js replay exist | deployed connected flow, reliable completion, and external customer feedback |

The three main-campaign criteria are equally weighted. The Circle page lists the
four bonus-prize criteria above without published weights.

## Repository artifact registry

### O — OfferRail commercial core

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| O-01 | Capabilities can be converted to deterministic SKU contracts. | [`../../packages/offerrail/catalog.py`](../../packages/offerrail/catalog.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |
| O-02 | Proposals have stable identifiers and controlled state transitions. | [`../../packages/offerrail/proposals.py`](../../packages/offerrail/proposals.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |
| O-03 | Commercial limits are deterministic and fail closed. | [`../../packages/offerrail/policy.py`](../../packages/offerrail/policy.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |
| O-04 | Negotiation is bounded by the authorized action set. | [`../../packages/offerrail/negotiation.py`](../../packages/offerrail/negotiation.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |
| O-05 | Idempotency replays identical work and rejects conflicts/failure retries. | [`../../packages/offerrail/idempotency.py`](../../packages/offerrail/idempotency.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |
| O-06 | Commercial receipts are redacted, append-only, and hash chained. | [`../../packages/offerrail/receipts.py`](../../packages/offerrail/receipts.py) | `tests/test_offerrail_core.py` | `REPRODUCIBLE` |

### G — Gemini decision boundary

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| G-01 | A Gemini structured-decision provider is implemented. | [`../../apps/api/autonomerce/agents/providers.py`](../../apps/api/autonomerce/agents/providers.py) | `tests/test_agents.py` | `AVAILABLE`; live use `PLACEHOLDER` |
| G-02 | Productization cannot widen owner-declared authority. | [`../../apps/api/autonomerce/agents/productizer.py`](../../apps/api/autonomerce/agents/productizer.py) | `tests/test_productizer_security.py`, `tests/test_agents.py` | `REPRODUCIBLE` |
| G-03 | Buyer fit requires opt-in and policy compatibility. | [`../../apps/api/autonomerce/agents/prospects.py`](../../apps/api/autonomerce/agents/prospects.py) | `tests/test_agents.py` | `REPRODUCIBLE` |
| G-04 | Proposal and negotiation recommendations remain advisory. | [`../../apps/api/autonomerce/agents/proposals.py`](../../apps/api/autonomerce/agents/proposals.py), [`../../apps/api/autonomerce/agents/negotiation.py`](../../apps/api/autonomerce/agents/negotiation.py) | `tests/test_agents.py` | `REPRODUCIBLE` |
| G-05 | Delivery summaries cannot self-approve an artifact. | [`../../apps/api/autonomerce/agents/delivery.py`](../../apps/api/autonomerce/agents/delivery.py) | `tests/test_agents.py` | `REPRODUCIBLE` |
| G-LIVE | A deployed Gemini call productized the SKU used by the recorded synthetic order. | [`../../evidence/public/gemini-call.redacted.json`](../../evidence/public/gemini-call.redacted.json) | Cloud Run revision, request latency, output hash, and SKU/order linkage inspection | `AVAILABLE`; productization only |

### S — Opted-in sales workflow

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| S-01 | Agent Cards/capabilities can be parsed for the seller workflow. | [`../../apps/api/autonomerce/sales/agent_cards.py`](../../apps/api/autonomerce/sales/agent_cards.py) | `tests/test_sales.py` | `REPRODUCIBLE` |
| S-02 | A prospect requires explicit opt-in and a consent reference. | [`../../apps/api/autonomerce/sales/prospects.py`](../../apps/api/autonomerce/sales/prospects.py) | `tests/test_sales.py`, `tests/test_api.py` | `REPRODUCIBLE` |
| S-03 | Matching and pitching reject ineligible demand. | [`../../apps/api/autonomerce/sales/matching.py`](../../apps/api/autonomerce/sales/matching.py), [`../../apps/api/autonomerce/sales/pitching.py`](../../apps/api/autonomerce/sales/pitching.py) | `tests/test_sales.py` | `REPRODUCIBLE` |
| S-04 | Negotiation remains tied to proposal/policy state. | [`../../apps/api/autonomerce/sales/negotiation.py`](../../apps/api/autonomerce/sales/negotiation.py) | `tests/test_sales.py` | `REPRODUCIBLE` |

### C — Circle/payment lane

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| C-01 | Payment execution has offline and guarded live executor boundaries. | [`../../apps/api/autonomerce/payments/executors.py`](../../apps/api/autonomerce/payments/executors.py) | `tests/test_payments.py` | `REPRODUCIBLE`; Arc testnet execution `AVAILABLE` |
| C-02 | Chain, token, asset, amount, payer, payee, and limits are policy checked. | [`../../apps/api/autonomerce/payments/policy.py`](../../apps/api/autonomerce/payments/policy.py) | `tests/test_payments.py` | `REPRODUCIBLE` |
| C-03 | One payment is bound to one accepted proposal/idempotency contract. | [`../../apps/api/autonomerce/payments/service.py`](../../apps/api/autonomerce/payments/service.py) | `tests/test_payments.py` | `REPRODUCIBLE` |
| C-04 | Durable SQLite payment state is available for the supported live topology. | [`../../apps/api/autonomerce/payments/store.py`](../../apps/api/autonomerce/payments/store.py) | `tests/test_payments.py`, `tests/test_repository_persistence.py` | `REPRODUCIBLE` |
| C-05 | Ambiguous outcomes require reconciliation rather than blind retry. | [`../../apps/api/autonomerce/payments/reconciliation.py`](../../apps/api/autonomerce/payments/reconciliation.py) | `tests/test_payment_reconciliation.py`, `tests/test_reconciliation_routes.py` | `REPRODUCIBLE` |
| C-06 | Independent receipt verification is fail closed. | [`../../apps/api/autonomerce/payments/verification.py`](../../apps/api/autonomerce/payments/verification.py) | `tests/test_payments.py` | `REPRODUCIBLE` |
| C-07 | Public payment fields are recursively redacted. | [`../../apps/api/autonomerce/payments/redaction.py`](../../apps/api/autonomerce/payments/redaction.py) | `tests/test_payments.py` | `REPRODUCIBLE` |
| C-08 | x402 `PAYMENT-REQUIRED` parsing exists. | [`../../apps/api/autonomerce/payments/x402.py`](../../apps/api/autonomerce/payments/x402.py) | `tests/test_payments.py` | `REPRODUCIBLE`; end-to-end x402 demo pending |
| C-09 | API composition can inject the payment adapter and preserves contract checks. | [`../../apps/api/autonomerce/payments/api_adapter.py`](../../apps/api/autonomerce/payments/api_adapter.py), [`../../apps/api/autonomerce/api/adapters.py`](../../apps/api/autonomerce/api/adapters.py) | `tests/test_adapter_composition.py`, `tests/test_api.py` | `REPRODUCIBLE` |
| C-LIVE | A bounded Circle Agent Wallet runner transferred 0.10 USDC on Arc testnet and replayed without duplication. | [`../../evidence/public/circle-arc-testnet-transaction.public.json`](../../evidence/public/circle-arc-testnet-transaction.public.json), [`../../evidence/public/wallet-policy.redacted.json`](../../evidence/public/wallet-policy.redacted.json) | explorer, Circle history, balance delta, independent Arc RPC | `AVAILABLE`; final deployed-order/video eligibility remains `BLOCKING` |

### F — Fulfillment and delivery validation

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| F-01 | Fulfillment requires a confirmed matching payment. | [`../../apps/api/autonomerce/sales/fulfillment.py`](../../apps/api/autonomerce/sales/fulfillment.py) | `tests/test_sales.py` | `REPRODUCIBLE` |
| F-02 | Seller output is hashed and validated as data. | [`../../apps/api/autonomerce/sales/fulfillment.py`](../../apps/api/autonomerce/sales/fulfillment.py) | `tests/test_sales.py` | `REPRODUCIBLE` |
| F-03 | Contract failure produces a rejected delivery rather than a success claim. | [`../../apps/api/autonomerce/agents/delivery.py`](../../apps/api/autonomerce/agents/delivery.py) | `tests/test_agents.py`, `tests/test_api.py` | `REPRODUCIBLE` |
| F-04 | The API binds fulfillment to the exact accepted buyer need/proposal. | [`../../apps/api/autonomerce/api/app.py`](../../apps/api/autonomerce/api/app.py) | `tests/test_api.py` | `REPRODUCIBLE` |

### R — API, receipts, security, and reproducibility

| ID | Narrow claim | Artifact | Verification | Status |
|---|---|---|---|---|
| R-01 | A credential-free end-to-end fixture can run across all product lanes. | [`../../examples/run_offline_demo.py`](../../examples/run_offline_demo.py) | run command in `JUDGE-QUICKSTART.md` | `REPRODUCIBLE`; classification `synthetic/offline_verified` only |
| R-02 | The API composes onboarding through receipt and metrics. | [`../../apps/api/autonomerce/api/app.py`](../../apps/api/autonomerce/api/app.py) | `tests/test_api.py`, `tests/test_e2e_offline.py` | `REPRODUCIBLE` |
| R-03 | Public receipt publication is separate and consent scoped. | [`../../apps/api/autonomerce/api/app.py`](../../apps/api/autonomerce/api/app.py), [`../../apps/api/autonomerce/api/repository.py`](../../apps/api/autonomerce/api/repository.py) | `tests/test_api.py`, `tests/test_runtime_preflight.py` | `REPRODUCIBLE` |
| R-04 | Threats and controls are documented. | [`../../security/THREAT-MODEL.md`](../../security/THREAT-MODEL.md), [`../../security/README.md`](../../security/README.md) | `tests/security/test_controls.py` | `AVAILABLE` / `REPRODUCIBLE` |
| R-05 | Public files can be scanned for likely secrets. | [`../../scripts/scan_public_secrets.py`](../../scripts/scan_public_secrets.py) | [`../../evidence/public/ci-and-security.json`](../../evidence/public/ci-and-security.json) | `AVAILABLE`; exact public release CI passed |
| R-06 | Deployment modes and fail-closed settings are documented. | [`../../infra/README.md`](../../infra/README.md), [`../../docs/DEPLOYMENT-SECURITY.md`](../../docs/DEPLOYMENT-SECURITY.md) | `tests/test_runtime_preflight.py`, [`../../evidence/public/build-identity.json`](../../evidence/public/build-identity.json) | `AVAILABLE`; public LIVE BFF and private offline-payment API verified |
| R-07 | Pre-existing work is disclosed. | [`../../PREEXISTING-ASSET-DISCLOSURE.md`](../../PREEXISTING-ASSET-DISCLOSURE.md) | manual review against final public history | `AVAILABLE`; final revision review pending |

### B — Business and public-evidence definitions

| ID | Narrow claim | Artifact | Status |
|---|---|---|---|
| B-01 | Synthetic/testnet/related-party activity cannot count as customer revenue. | [`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md) | `AVAILABLE` |
| B-02 | Public transaction fields and classifications are schema constrained. | [`../../evidence/templates/transaction.public.schema.json`](../../evidence/templates/transaction.public.schema.json) | `AVAILABLE` |
| B-03 | Revenue, costs, margin, and exclusions are schema constrained. | [`../../evidence/templates/revenue.public.schema.json`](../../evidence/templates/revenue.public.schema.json) | `AVAILABLE` |
| B-04 | Example records are visibly synthetic and zero-revenue. | [`../../evidence/templates/transaction.public.synthetic.example.json`](../../evidence/templates/transaction.public.synthetic.example.json), [`../../evidence/templates/revenue.public.synthetic.example.json`](../../evidence/templates/revenue.public.synthetic.example.json) | `AVAILABLE`; not business evidence |
| B-05 | Customer publication permissions are separated by field/use. | [`CUSTOMER-CONSENT-TEMPLATE.md`](CUSTOMER-CONSENT-TEMPLATE.md) | template `AVAILABLE`; signed records `PLACEHOLDER` |

## Required live evidence register

These placeholders must be replaced with public, judge-openable artifacts or the
associated claim must be removed.

| ID | Artifact | Minimum contents | Claim unlocked | Status |
|---|---|---|---|---|
| L-01 | `https://github.com/tomyimkc/autonomerce` | final tagged commit, license, disclosure, setup, security, limitations | public-source eligibility and reproducibility | `AVAILABLE`; final contest tag pending |
| L-02 | `https://autonomerce-web-6dnob6ekdq-uc.a.run.app` | clean-session access, HTTPS, health/status, matching deployed revision | deployed-demo claim | `AVAILABLE` |
| L-03 | [`../../evidence/public/gemini-call.redacted.json`](../../evidence/public/gemini-call.redacted.json) | model/config/time/latency, structured output hash, resulting SKU/order linkage | Gemini used operationally for productization | `AVAILABLE`; served-model and usage/cost fields unavailable |
| L-04 | [`../../evidence/public/wallet-policy.redacted.json`](../../evidence/public/wallet-policy.redacted.json) | public addresses, network, wallet surface, safe caps/allowlists | Circle Agent Wallet testnet surface used | `AVAILABLE`; video pending |
| L-05 | [`../../evidence/public/circle-arc-testnet-transaction.public.json`](../../evidence/public/circle-arc-testnet-transaction.public.json) | independently inspectable exact USDC transfer | Arc testnet transaction exists | `AVAILABLE` |
| L-06 | `[REDACTED_ORDER_TRANSACTION_DELIVERY_RECORD_URL]` | one deployed-order linkage across Gemini, proposal, payment, fulfillment, and verdict | Circle is central to the full commercial loop | `BLOCKING`; settlement-only proof is available |
| L-07 | `[NO_PER_PAYMENT_APPROVAL_VIDEO_TIMESTAMP]` | policy configured before checkout; uninterrupted autonomous settlement | autonomy within standing policy | `BLOCKING` |
| L-08 | `[CUSTOMER_CONSENT_AND_CLASSIFICATION_URL]` | anonymized external relationship, selected publication permissions | customer/quote/transaction publication | `BLOCKING` for customer claims |
| L-09 | `[REVENUE_AND_UNIT_ECONOMICS_SNAPSHOT_URL]` | UTC window, qualifying transactions, exclusions, refunds, all variable costs, margin | measured revenue/margin | `BLOCKING` for business results |
| L-10 | [`../../evidence/public/ci-and-security.json`](../../evidence/public/ci-and-security.json) | final commit, tests, secret scan, typecheck, production build, lock checks, and deterministic demo hash | final-revision verification claim | `AVAILABLE` |
| L-11 | `[UNDER_3_MINUTE_VIDEO_URL]` | complete linked story with readable evidence and accurate labels | submitted demonstration | `BLOCKING` |

## Final artifact naming suggestion

The actual public paths may differ, but the evidence should remain one artifact
per purpose:

```text
evidence/public/build-identity.json
evidence/public/gemini-call.redacted.json
evidence/public/wallet-policy.redacted.json
evidence/public/transactions.public.json
evidence/public/orders.public.json
evidence/public/revenue.public.json
evidence/public/customer-evidence.public.json
evidence/public/ci-and-security.json
evidence/public/video-checksum.txt
```

Do not create a “live” artifact by editing the synthetic examples. Generate it
from independently verified source records, validate it, scan it, and obtain
publication approval.

## Verification and publication checklist

For every final artifact:

1. record the exact repository commit and deployed revision;
2. use UTC timestamps;
3. identify `synthetic`, `testnet`, `self/founder/affiliate`, or
   `external mainnet` explicitly;
4. verify order/proposal/payment/fulfillment linkage;
5. verify network, canonical USDC, exact amount, payer, payee, and transaction
   hash independently;
6. retain consent for each public customer field;
7. redact prompts, artifacts, identity, credentials, headers, sessions, and
   recovery material;
8. validate against the public schema;
9. recompute metrics from transaction-level records;
10. run tests, secret scanning, and claim linting against the final commit;
11. open every link while logged out;
12. remove any claim whose proof chain is incomplete.
