# Devpost draft — Autonomerce

`drafted: 2026-07-31` · `NOT READY TO SUBMIT UNCHANGED`

This is truthful against the current repository snapshot. Bracketed fields may
be replaced only with evidence that passes
[`SETUP-PROOF-CHECKLIST.md`](SETUP-PROOF-CHECKLIST.md) and
[`JUDGE-CHECKLIST.md`](JUDGE-CHECKLIST.md).

Criteria were rechecked on 2026-07-31 against the live official Build with
Gemini Devpost rules and Circle Agentic Economy page. Recheck both immediately
before submission:

- `https://xprize.devpost.com/rules`
- `https://www.geminixprize.com/agentic-payments/`

## Submission metadata

- **Project:** Autonomerce
- **Component/protocol:** OfferRail
- **Tagline:** Give every AI agent a sales department
- **Main category:** Entrepreneurship & Job Creation
- **Sponsor target:** Circle Agentic Economy Prize
- **Entrant:** individual owner
- **Repository:** `[PUBLIC_REPOSITORY_URL — REQUIRED FOR CIRCLE]`
- **Live application:** `[PUBLIC_CLOUD_RUN_OR_WEB_URL]`
- **Video:** `[UNDER_3_MINUTE_VIDEO_URL]`
- **Public wallet:** `[CIRCLE_AGENT_WALLET_ADDRESS]`
- **Explorer proof:** `[VERIFIED_TRANSACTION_EXPLORER_URL]`
- **Evidence index:** `[PUBLIC_EVIDENCE_URL]`

## One-line summary

Autonomerce turns an existing AI agent into a policy-bounded seller that can
package capabilities with Gemini, negotiate machine-readable offers, receive
USDC through Circle, validate delivery, and issue an auditable receipt.

## Short description

Most useful agents can do work but cannot reliably sell it. Autonomerce adds the
commercial operating layer: capability productization, opted-in demand matching,
bounded negotiation, autonomous USDC settlement, fulfillment validation, and
public-safe receipts. Gemini recommends product and sales decisions; deterministic
code controls price, scope, capacity, token, chain, wallets, idempotency, and
delivery acceptance.

## Full project description

### Inspiration

AI agents are becoming capable workers, but an owner still has to turn each
capability into an offer, find demand, negotiate, collect payment, route the job,
check the result, and maintain records. That manual gap prevents small builders
from operating agent-native businesses.

Autonomerce asks a practical entrepreneurship question:

> What if connecting an agent to a sales department were as repeatable as
> connecting it to a tool?

### What it does

Autonomerce accepts an A2A Agent Card, MCP/OpenAPI description, or manual
capability manifest and converts it into a machine-readable service catalog.
The owner binds a commercial policy once. The system can then:

1. productize capabilities into priced service SKUs;
2. consider only explicitly opted-in buyer needs;
3. draft a relevant proposal;
4. accept, counter, or decline inside deterministic bounds;
5. receive policy-authorized USDC;
6. route paid work to the seller agent;
7. validate the returned artifact against the accepted contract;
8. issue a redacted payment and delivery receipt;
9. update metrics without counting simulated, testnet, self, or founder
   transfers as customer revenue.

### How Gemini is central

The Gemini boundary is operational rather than decorative. Structured Gemini
decisions can:

- extract and productize declared capabilities;
- recommend sellable outcomes and acceptance criteria;
- score fit between an opted-in buyer need and a published SKU;
- draft proposal relevance without inventing price or scope;
- recommend negotiation actions from a code-authorized action set;
- summarize deterministic delivery results without accepting its own output.

Removing the model removes the adaptive productization and sales-reasoning layer.
It does **not** remove the controls: code remains authoritative for policy,
payments, and acceptance.

**Current evidence boundary:** the repository contains the structured Gemini
provider and typed decision services. The checked-in integrated demo deliberately
uses a deterministic offline provider. Replace this paragraph only after the
deployed judged path records a real Gemini request, model identity, timestamp,
and output used by the demonstrated order.

### How Circle is central

Autonomerce is designed around autonomous USDC settlement, not a checkout button.
The payment lane binds one accepted proposal to one idempotency key, validates
token, chain, amount, payer, payee, and limits, executes through a guarded Circle
adapter, verifies the returned receipt, and keeps payment confirmation separate
from delivery acceptance.

The repository includes:

- a strict payment-policy gate;
- replay-safe in-memory and SQLite payment stores;
- guarded testnet/mainnet Circle CLI execution;
- x402 `PAYMENT-REQUIRED` parsing;
- fail-closed receipt verification hooks;
- redacted public payment receipts;
- two explicit mainnet enablement controls.

**Current evidence boundary:** offline mode is the default and moves no funds.
Do not claim Circle Agent Wallet eligibility, a real transaction, or customer
revenue until the public wallet, wallet policy, transaction hash, explorer link,
order linkage, and consent record are present.

### Autonomy and safety

The owner approves commercial and wallet policy, not each transaction. Inside
that envelope, the judged path is intended to operate without a per-payment
approval prompt. Gemini cannot change price limits, expand scope, select an
arbitrary destination wallet, mark a payment confirmed, accept its own output,
or expose secrets.

Key invariants include:

- one accepted proposal maps to at most one settlement;
- repeated idempotent requests do not execute a second payment;
- non-opted-in prospects are rejected;
- unsupported chain, token, wallet, amount, or scope changes fail closed;
- mainnet execution requires explicit owner enablement and durable state;
- payment and delivery are independently checked;
- public receipts omit prompts, artifacts, credentials, and private identity.

### Entrepreneurship & Job Creation impact

Autonomerce is infrastructure for creating small agent-native businesses. A
builder who already owns a useful agent can add a catalog, policy, settlement,
delivery, and evidence layer instead of building a bespoke sales operation.
The immediate wedge is a source-verification/evidence-pack seller, while the
portable contract supports other digital-service agents.

The category claim is a path-to-impact claim until external activation and
payment evidence exists. Final copy should report only measured seller activation,
external customers, delivered paid tasks, and repeat purchase from the public
evidence snapshot.

### Business viability

The commercial model is a fee or revenue share on successfully settled and
delivered agent services, with optional paid seller onboarding. Unit economics
must be reported per order:

```text
gross margin
= external customer revenue
- refunds
- Circle/network/payment fees
- Gemini variable cost
- paid external-service cost
- allocated variable infrastructure cost
```

**Verified metrics for final insertion:**

- External customer interviews: `[COUNT]`
- External design partners: `[COUNT]`
- External paying customers: `[COUNT]`
- Delivered paid external tasks: `[COUNT]`
- Mainnet external USDC revenue: `[AMOUNT]`
- Variable costs: `[AMOUNT + BREAKDOWN]`
- Gross margin: `[AMOUNT AND PERCENT]`
- Repeat-purchase rate: `[RATE WITH DENOMINATOR]`
- Measurement window: `[UTC START]` to `[UTC END]`

If any value remains zero, report zero and explain the miss. Never replace it
with demo fixture volume, testnet activity, a founder transfer, or a projection.

### What is implemented today

- shared typed contracts and canonical USDC handling;
- OfferRail catalog, policy, proposal, negotiation, idempotency, and receipt core;
- Gemini and deterministic structured-decision providers;
- opted-in prospect registry, matching, pitch, negotiation, and fulfillment;
- Circle mock and guarded CLI execution, x402 parsing, policy, persistence, and
  receipt verification;
- a FastAPI composition layer;
- a one-command credential-free integrated demo;
- a polished Next.js synthetic replay;
- adversarial and integration tests;
- deployment, secret-scan, and platform preflight scripts.

### Current limitations

The current public evidence is an offline integrated build. A final Circle
submission still requires owner-authenticated Agent Wallet setup, a real
verifiable USDC transaction shown in the video, a public wallet and explorer
link, and a public repository. The main Build submission still needs a deployed
Gemini-in-the-loop order plus honest external customer and unit-economics
evidence. See [`KNOWN-LIMITATIONS.md`](KNOWN-LIMITATIONS.md).

### Challenges

- separating model recommendations from financial authorization;
- preserving autonomy without giving the model an unbounded wallet;
- making retries safe when network outcomes may be ambiguous;
- proving delivery separately from proving payment;
- making demo and evidence surfaces useful without leaking customer data;
- distinguishing technical fixture volume from arms-length business traction.

### Accomplishments we are proud of

- a complete credential-free sale can run across the real repository lanes;
- every commercial step produces typed, inspectable state;
- model output cannot widen the accepted commercial contract;
- idempotent retries do not duplicate offline settlement;
- public receipts expose hashes and verdicts rather than private artifacts;
- simulated and testnet activity are excluded from customer revenue by policy.

These are software accomplishments, not claims of external customers, revenue,
or live platform qualification.

### What we learned

Autonomous payments are primarily a boundary-design problem. The model should be
powerful where adaptation creates value and powerless where a wrong action can
change limits, recipients, settlement state, or acceptance. The strongest
business evidence is not a dashboard screenshot; it is a chain from consent to
proposal to payment to delivered contract to measured cost.

### What is next

1. run a deployed Gemini-backed productization and proposal flow;
2. connect an owner-policy-bound Circle Agent Wallet;
3. complete testnet and then tightly capped mainnet proof;
4. onboard external design partners;
5. publish consented, redacted transaction and delivery evidence;
6. replace synthetic UI metrics with the measured public snapshot;
7. record the final sub-three-minute demo.

## Built with

Gemini API / Google Gen AI SDK, Google Cloud / Cloud Run, Circle Agent Stack and
Agent Wallets, USDC, x402, A2A, FastAPI, Pydantic, Python, Next.js, React,
TypeScript, SQLite, Docker, and pytest.

Only retain a technology in the final Devpost list if the submitted public build
actually uses it.

## Rubric alignment matrix

| Criterion | Current draft evidence | Required upgrade before final claim |
|---|---|---|
| Build: Business Viability | product wedge, pricing, measurement definitions, interview/consent process | external interviews, customers, paid delivered orders, costs, margin |
| Build: AI-Native Operations | typed Gemini decision boundary and adapter | deployed Gemini call materially used in the recorded order |
| Build: Category Impact | portable seller operating layer and entrepreneurship thesis | measured seller activation or credible external adoption evidence |
| Circle: Creativeness & Innovation | agent-to-seller rail with proof-linked settlement | clear comparison and working public demo |
| Circle: Centrality to Business | payment is bound to proposal and delivery lifecycle | real Agent Wallet transaction central to the shown order |
| Circle: Technical Depth & Autonomy | policy, idempotency, x402, verification, no per-payment approval design | live autonomous run with wallet policy and no approval interruption |
| Circle: Customer Experience | owner console and auditable workflow | live connected flow plus external user feedback |

## Final-copy replacement rules

- Replace `[COUNT]`, `[AMOUNT]`, `[RATE]`, and URLs only from approved evidence.
- State the network every time a transaction is shown.
- Use `testnet`, `simulated`, `external mainnet`, `founder`, and `self` as explicit
  classifications; never collapse them into “transactions.”
- If Gemini or Circle fails during recording, do not narrate the intended
  behavior over fixture footage as if the live action occurred.
- Recheck the live official rules immediately before submission.
