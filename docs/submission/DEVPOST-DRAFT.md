# Devpost draft — Autonomerce / OfferRail

`drafted: 2026-07-31` · `NOT READY TO SUBMIT UNCHANGED`

This copy is bounded by the approved public repository evidence. Bracketed
fields may be replaced only with artifacts that pass
[`SETUP-PROOF-CHECKLIST.md`](SETUP-PROOF-CHECKLIST.md) and map cleanly through
[`EVIDENCE-INDEX.md`](EVIDENCE-INDEX.md).

The Devpost overview requests a **500–1000 word written narrative**. This file is
the source library, not the paste-ready final narrative. Before submission,
assemble one 500–1000 word version, record its word count, and retain the
human-versus-AI operations, economic-opportunity, build-story, revenue,
expense, customer, and evidence statements required by the live form.

**Current evidence boundary:** the integrated demo is deterministic and
offline. It calls no external service, uses no credentials, and moves no real
funds. There is not yet approved public proof of a live Gemini order, Circle
Agent Wallet transaction, external customer, revenue, public deployment, or
production result.

Official criteria were reviewed on 2026-07-31. Recheck immediately before
recording and again before submission:

- `https://xprize.devpost.com/rules`
- `https://www.geminixprize.com/agentic-payments/`

## Submission metadata

- **Project:** Autonomerce
- **Protocol/component:** OfferRail
- **Tagline:** Give every AI agent a sales department
- **Main category:** Entrepreneurship & Job Creation
- **Sponsor target:** Circle Agentic Economy Prize
- **Entrant:** individual owner
- **Repository:** `[PUBLIC_REPOSITORY_URL — REQUIRED FOR CIRCLE]`
- **Application:** `[PUBLIC_APP_URL]`
- **Video:** `[UNDER_3_MINUTE_VIDEO_URL]`
- **Evidence:** `[PUBLIC_EVIDENCE_INDEX_URL]`
- **Circle Agent Wallet:** `[PUBLIC_WALLET_ADDRESS]`
- **Transaction:** `[VERIFIED_TRANSACTION_EXPLORER_URL]`
- **Submission commit/deployment:** `[COMMIT]` / `[DEPLOYED_REVISION]`
- **Final narrative word count:** `[500_TO_1000]`

## Judge-first 30-second read

### The problem

Useful AI agents can perform work, but their owners still have to package the
capability, find opted-in demand, negotiate safe terms, collect payment, route
the job, check delivery, and maintain evidence. That manual commercial layer is
a barrier between an agent that can do a task and a small business that can
sell one.

### The product

Autonomerce is a policy-controlled commercial operating layer for callable
agents. Its portable protocol, OfferRail, connects:

```text
agent capability
-> Gemini-assisted productization and sales decisions
-> deterministic owner policy
-> opted-in buyer need
-> machine-readable proposal and bounded negotiation
-> Circle USDC settlement
-> seller-agent fulfillment
-> independent delivery validation
-> redacted receipt and measured economics
```

### The key design choice

Gemini recommends where adaptation creates value. Deterministic code authorizes
price, scope, capacity, buyer, token, chain, wallets, settlement, idempotency,
and delivery acceptance. Circle is intended to execute the accepted USDC
settlement inside a standing owner policy, not as a disconnected checkout
button. Payment confirmation never marks delivery successful.

### What the repository proves today

The repository contains a credential-free integrated offline workflow, typed
contracts, model-authority boundaries, opt-in enforcement, bounded negotiation,
simulated idempotent payment, fulfillment validation, redaction, persistence and
reconciliation primitives, public-evidence schemas, and adversarial test targets.

It does **not** yet prove live Gemini use, Circle Agent Wallet eligibility, a
real transaction, a customer, revenue, deployment, or production readiness.

## One-line summary

Autonomerce gives an existing AI agent a policy-bounded path from declared
capability to offer, settlement, validated delivery, and auditable receipt.

## Three-minute video story

The final cut should tell one linked order story. If live proof is unavailable,
the footage must remain labeled `SYNTHETIC / OFFLINE / NO FUNDS MOVED` and the
missing eligibility claims must be removed.

| Time | Story beat | Visible evidence |
|---:|---|---|
| 0:00–0:12 | “Agents can work; most cannot operate the commercial loop.” | concrete seller capability and product name |
| 0:12–0:30 | “Autonomerce adds OfferRail from capability to receipt.” | full lifecycle diagram and owner value |
| 0:30–0:50 | Gemini materially productizes the capability or shapes the shown proposal. | model/config/time, structured output, resulting SKU/proposal, deterministic clamp |
| 0:50–1:10 | The owner sets the commercial and wallet envelope once. | policy version, price/capacity limits, token/network, wallet allowlists |
| 1:10–1:32 | An opted-in buyer need becomes a proposal; a bounded counter is resolved. | consent reference, need/proposal IDs, revision diff, reason code |
| 1:32–1:58 | The accepted proposal triggers the required Circle Agent Wallet USDC path without a per-payment approval interruption. | wallet, network, exact amount, transaction hash, explorer confirmation |
| 1:58–2:20 | The seller fulfills; a separate validator accepts or rejects the contract. | payment and delivery as distinct states, artifact hash, acceptance results |
| 2:20–2:38 | A redacted receipt links proposal, settlement, delivery, and evidence class. | linked IDs, receipt hash, consent-scoped public fields |
| 2:38–2:52 | Only approved external measurements are reported. | fixed UTC window, customers/orders/revenue/costs/margin, exclusions |
| 2:52–2:59 | “Autonomerce gives an existing agent a path to become a seller.” | public app, repository, evidence links |

The first 30 seconds should use:

> Useful AI agents can do work, but their owners still have to package the
> service, find opted-in demand, negotiate, collect payment, check delivery, and
> keep the evidence. Autonomerce adds that commercial operating layer. OfferRail
> links Gemini-assisted sales decisions to deterministic owner policy, Circle
> USDC settlement, independent fulfillment validation, and a redacted receipt.

For an offline rehearsal, immediately add:

> This is a deterministic rehearsal: no Gemini service is called, no Circle
> Agent Wallet is used, and no funds move.

## Inspiration

The owner of a useful agent should not need to build a bespoke sales stack for
every capability. Autonomerce asks a practical entrepreneurship question:

> What if connecting an agent to a sales department were as repeatable as
> connecting it to a tool?

The first seller wedge is a source-verification/evidence-pack agent: a concrete
digital service with structured inputs, a machine-checkable output contract,
and a clear reason to separate payment from delivery acceptance.

## What it does

Autonomerce accepts an A2A Agent Card, MCP/OpenAPI description, or manual
capability manifest and converts the declared capability into a service catalog.
The owner binds commercial and wallet policy. Inside that envelope, the
submitted design can:

1. productize declared capabilities into service SKUs;
2. consider only explicitly opted-in buyer needs;
3. draft a relevant machine-readable proposal;
4. accept, counter, or decline within deterministic bounds;
5. request USDC settlement for the exact accepted contract;
6. route confirmed paid work to the seller agent;
7. validate the returned artifact separately from payment;
8. publish a consent-scoped, redacted receipt;
9. compute business metrics without counting synthetic, testnet, self, founder,
   affiliate, reimbursed, or circular activity as customer revenue.

## How Gemini is central

Gemini is intended to supply the adaptive productization and sales-reasoning
layer. Structured decisions can:

- extract and productize declared capabilities;
- recommend a sellable outcome and display framing;
- score fit between an opted-in need and an existing SKU;
- draft proposal relevance without inventing authorized price or scope;
- recommend a negotiation action from a code-authorized action set;
- summarize deterministic delivery results without accepting the model’s own
  output.

Removing the model removes adaptive productization and sales reasoning. It does
not remove the controls: deterministic code remains authoritative for price,
scope, capacity, buyer eligibility, token, chain, wallets, payment, idempotency,
and delivery acceptance.

**Current Gemini evidence:** `GeminiDecisionProvider` and typed decision services
are implemented. The integrated offline demo deliberately uses a deterministic
provider. Final copy may state that Gemini was used by the judged order only
after `[LIVE_GEMINI_CALL_EVIDENCE_URL]` records the model/config, UTC timestamp,
structured output or hash, resulting order object, and deployed revision.

## How Circle is central

Autonomerce is designed around autonomous USDC settlement bound to the accepted
commercial contract, not around a generic payment button. The payment lane:

- creates one immutable authorization for the accepted proposal revision;
- checks canonical token/asset, network, amount, payer, payee, limits, expiry,
  policy version, and seller configuration;
- uses a stable idempotency contract;
- treats ambiguous outcomes as reconciliation work rather than blindly retrying;
- independently verifies the returned receipt;
- keeps payment confirmation separate from delivery acceptance;
- emits redacted public payment fields.

The repository includes a payment-policy gate, in-memory and SQLite stores,
guarded Circle CLI execution, an API payment adapter, x402
`PAYMENT-REQUIRED` parsing, receipt verification hooks, and explicit mainnet
enablement controls.

**Current Circle evidence:** offline mode is the default and moves no funds.
Do not claim that a Circle Agent Wallet was used, a real transaction occurred,
the prize eligibility bar was met, or customer revenue exists until the public
wallet, wallet product/policy evidence, transaction hash, explorer link, order
linkage, no-per-payment-approval footage, and publication consent are present.

## Autonomy and safety

The owner approves a standing commercial and wallet envelope, not each
individual transaction. Inside that envelope, the judged design is intended to
operate without a checkout-time approval prompt.

Gemini cannot:

- raise price or discount limits;
- expand the accepted scope or output contract;
- choose an arbitrary payer or destination wallet;
- change the network, token, or canonical USDC asset;
- mark a payment confirmed;
- bypass idempotency or reconciliation;
- accept its own seller output;
- publish private customer content or credentials.

Key invariants:

- one accepted proposal maps to at most one settlement;
- an identical idempotent request returns the prior result;
- conflicting reuse and ambiguous failures fail closed;
- non-opted-in prospects are rejected;
- unsupported price, scope, capacity, network, token, wallet, or amount changes
  are rejected;
- mainnet requires explicit software opt-ins and durable state;
- payment and delivery have independent verdicts;
- public receipts omit prompts, private artifacts, credentials, and direct
  customer identity unless separately authorized.

## Entrepreneurship & Job Creation

Autonomerce targets the gap between owning a useful agent and operating an
agent-native service business. A builder can add a catalog, owner policy,
settlement, fulfillment, and evidence layer instead of assembling a bespoke
sales operation.

The impact claim remains a **path-to-impact** claim until external activation is
measured. Final copy should distinguish:

- registered sellers;
- activated sellers with a SKU and policy;
- externally activated sellers;
- external design partners;
- paying external customers;
- accepted paid external deliveries;
- repeat purchasers.

Do not present the tagline “Give every AI agent a sales department” as achieved
compatibility, universal access, adoption, or job creation.

## Business model and viability

The proposed business model is a fee or revenue share on successfully settled
and delivered agent services, with optional paid seller onboarding. The final
submission should report unit economics at order level:

```text
net external revenue
= qualifying external mainnet USDC
- refunds and credits

variable cost of goods
= Circle/network/payment fees
+ Gemini variable cost
+ paid external-service cost
+ seller-agent variable compute
+ allocated variable infrastructure
+ other order-variable cost

gross margin
= net external revenue
- variable cost of goods
```

### Verified metrics for final insertion

- Measurement window: `[UTC_START]` to `[UTC_END]`
- External problem interviews: `[COUNT + EVIDENCE_URL]`
- External design partners: `[COUNT + EVIDENCE_URL]`
- Activated external sellers: `[COUNT + EVIDENCE_URL]`
- Paying external customers: `[COUNT + EVIDENCE_URL]`
- Delivered paid external tasks: `[COUNT + EVIDENCE_URL]`
- Gross external mainnet USDC: `[AMOUNT + TRANSACTION_INDEX_URL]`
- Refunds/credits: `[AMOUNT + METHOD]`
- Variable costs: `[AMOUNT + BREAKDOWN_URL]`
- Gross margin: `[AMOUNT_AND_PERCENT + SNAPSHOT_URL]`
- Repeat purchasers/rate: `[COUNT/RATE + DENOMINATOR]`

If a value is zero or unavailable, report zero or `not measured` as defined by
the public schema. Never substitute demo fixture volume, testnet activity,
founder/self transfers, wallet-to-wallet movement, willingness to pay, or a
projection.

## What is implemented in the repository

- shared typed contracts and exact decimal USDC handling;
- OfferRail catalog, policy, proposal, negotiation, idempotency, and
  hash-chained receipt primitives;
- Gemini and deterministic structured-decision providers;
- opted-in prospect registration, matching, pitching, negotiation, and
  fulfillment;
- Circle mock and guarded CLI execution, payment policy, durable SQLite state,
  x402 parsing, verification, and reconciliation;
- FastAPI composition from seller onboarding through metrics and publication;
- owner-authenticated Next.js LIVE-path code plus a clearly synthetic replay;
- one-command credential-free integrated offline demo;
- adversarial, integration, persistence, security, and preflight test targets;
- deployment, public-export, evidence-schema, and secret-scan support.

These are implementation statements. The final submission revision should link
`[PUBLIC_CI_RUN_URL]` before stating that all tests or gates passed.

## Current limitations

The approved public evidence does not yet contain:

1. a deployed Gemini-in-the-loop judged order;
2. Circle Agent Wallet product/policy proof;
3. a real, independently verifiable USDC transaction;
4. footage proving no per-payment approval inside standing policy;
5. a public deployment receipt and stable public URL;
6. an external customer, paid delivery, customer quote, revenue, repeat
   purchase, measured variable costs, or margin;
7. an external security audit or broad production-scale proof.

See [`KNOWN-LIMITATIONS.md`](KNOWN-LIMITATIONS.md). These are blocking evidence
gaps, not implied private accomplishments.

## Challenges

- separating model recommendations from financial authorization;
- preserving useful autonomy without giving a model an unbounded wallet;
- making retries safe when a network outcome may be ambiguous;
- independently verifying settlement rather than trusting an executor response;
- proving delivery separately from proving payment;
- keeping public evidence useful without leaking customer data;
- distinguishing fixture volume from arms-length business traction;
- making one workflow legible to both technical and entrepreneurship judges.

## Accomplishments we are proud of

- a complete credential-free sale can execute across the repository’s real
  internal lanes;
- every commercial step produces typed, inspectable state;
- model output cannot widen the authorized commercial contract;
- identical offline payment retries reuse one simulated execution;
- failed/ambiguous idempotency states are not blindly replayed;
- delivery is accepted or rejected against the declared contract;
- public receipts expose approved hashes and verdicts rather than private
  artifacts;
- metric definitions exclude simulated, testnet, related-party, reimbursed, and
  circular activity from customer revenue.

These are software and methodology accomplishments, not claims of external
customers, live integrations, revenue, or prize qualification.

## What we learned

Agentic payments are primarily a boundary-design and evidence-design problem.
The model should be powerful where adaptation creates value and powerless where
a wrong action can change limits, recipients, settlement state, or delivery
acceptance. A transaction hash alone is not a business result. The strongest
evidence is a consented chain from need to proposal to policy-authorized payment
to validated delivery to measured cost.

## What is next

1. deploy the reviewed revision and record build identity;
2. run a Gemini-backed productization/proposal decision used by the recorded
   order;
3. connect an owner-policy-bound Circle Agent Wallet;
4. complete testnet proof, then a tightly capped real USDC proof if approved;
5. onboard external design partners and one arms-length buyer;
6. publish consented, redacted order/transaction/delivery evidence;
7. measure all variable costs and generate the public revenue snapshot;
8. record the final sub-three-minute video;
9. run final tests, secret scan, claim lint, schema validation, and logged-out
   link checks;
10. remove every unreplaced placeholder and unsupported claim.

## Built with

Gemini API / Google Gen AI SDK, Google Cloud, Circle Agent Stack and Agent
Wallets, USDC, x402, A2A, FastAPI, Pydantic, Python, Next.js, React, TypeScript,
SQLite, Docker, and pytest.

Retain a technology in the submitted list only if the public submission build
actually uses it. For the current repository snapshot, live Gemini, Google Cloud,
Circle Agent Wallet, and real USDC usage remain pending evidence.

## Judging-criteria map

| Criterion | Judge-facing thesis | Current evidence | Required final proof |
|---|---|---|---|
| Build — Business Viability | repeatable commercial layer and fee/revenue-share path for agent services | business model, adapter boundaries, metric/cost definitions, and strict revenue exclusions | real users, arms-length revenue, delivered paid orders, actual expenses, marketing spend, margin, and sustainability evidence |
| Build — AI-Native Operations | Gemini materially adapts productization and selling while deterministic code owns authority | provider, typed decisions, clamps, and tests | deployed Gemini call materially used by the recorded order plus production execution evidence |
| Build — Category Impact | lowers the barrier for owners of useful agents to activate policy-bounded sellers in Entrepreneurship & Job Creation | concrete wedge, activation/customer/delivery definitions, portable onboarding architecture | external seller/design-partner activation, customers, feedback, measured economics, and no unsupported job-count claim |
| Circle — Creativeness & Innovation | proposal-to-settlement-to-delivery proof rail, not generic checkout | OfferRail/payment/receipt implementation | public working comparison and real transaction |
| Circle — Centrality to Business | settlement is bound to the accepted commercial contract | immutable authorization and separate delivery state | one order whose commercial loop depends on Circle settlement |
| Circle — Technical Depth & Autonomy | policy, exact authorization, durable idempotency, fail-closed verification, reconciliation, no per-payment approval design | payment code and adversarial test targets | live Agent Wallet policy, explorer proof, no approval interruption, replay evidence |
| Circle — Customer Experience | understandable seller workflow from capability to receipt | synthetic replay and connected-path code | deployed live flow, external customer feedback, reliable completion, and consented evidence |

The three main-campaign criteria are equally weighted. The Circle page lists
four independent bonus-prize criteria but does not publish weights. See the
official-source matrix in the Sophia development repository before finalizing
the submission.

## Final replacement rules

- Replace placeholders only from the matching public evidence artifact.
- Show the network every time a wallet, payment, or transaction appears.
- Use `synthetic`, `offline`, `testnet`, `external mainnet`, `self/founder`,
  `affiliate`, and `reimbursed/circular` as explicit classifications.
- Do not call an executor response “verified” without independent evidence.
- Do not call a payment “revenue” without external-customer classification.
- Do not call a paid order “delivered” unless the declared validator accepted
  it.
- Do not publish customer identity, prompts, artifacts, quotes, or transaction
  linkage beyond the recorded consent.
- If Gemini or Circle fails during recording, stop or label the fallback; never
  narrate intended behavior over fixture footage as if it occurred.
- Recheck official rules on the submission date.
