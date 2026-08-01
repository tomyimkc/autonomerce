# Devpost final narrative candidate — Autonomerce / OfferRail

`owner review required` · `legal attestations and final submission remain owner-only`

Use this as the 500–1000 word narrative candidate for the live Devpost form.
Recheck the official rules, every public link, and the final video immediately
before submission. Do not remove the testnet, customer, revenue, or deployment
boundaries below unless stronger public evidence replaces them.

## Paste-ready narrative

### Inspiration and problem

AI agents can already perform valuable digital work, but most agent owners still
operate the commercial layer manually. They must decide what the agent can sell,
package the capability, find an interested buyer, negotiate safe terms, collect
payment, route the task, decide whether delivery passed, and preserve evidence.
That repeated integration work prevents a useful agent from becoming a
repeatable small business.

Autonomerce asks a practical entrepreneurship question: what if connecting an
agent to a sales department were as repeatable as connecting it to a tool?

### What Autonomerce does

Autonomerce is a policy-controlled commercial operating layer for callable AI
agents. Its portable component, OfferRail, converts a declared A2A, MCP,
OpenAPI, or custom capability into a machine-readable service SKU. An owner
defines the commercial and wallet envelope once. Inside that envelope,
Autonomerce can match an explicitly opted-in buyer need, create a proposal,
handle a bounded counteroffer, request USDC settlement, route paid work to the
seller agent, validate the returned artifact separately, and publish a redacted
receipt.

The core design rule is that adaptive reasoning is not financial authority.
The deployed proof uses Gemini for productization. The broader codebase exposes
advisory interfaces for relevance, proposal, negotiation, and delivery, but
those later Gemini stages are not evidenced in the deployed trace.
Deterministic code controls price, scope, capacity, buyer eligibility, token,
chain, payer, payee, amount, idempotency, payment confirmation, and delivery
acceptance. Payment never automatically means the work succeeded.

### How Gemini is operational

Gemini is the deployed adaptive productization layer, not decorative
copywriting. The broader sales-reasoning interfaces are implemented but are not
claimed as deployed evidence here. The private Cloud Run API uses
`gemini-2.5-flash` to transform a declared source-verification capability into a
structured SKU with an outcome, price, latency, capacity, and acceptance
criteria. The public evidence records the requested model, API revision,
timestamp, request latency, structured result, and resulting SKU. The owner
policy then clamps the output so the model cannot expand its authority.

Removing Gemini would remove adaptive productization from the deployed proof.
Removing the deterministic policy would make that adaptive layer unsafe for
commercial use; therefore both layers are necessary.

### How Circle is central

Circle is designed as the settlement rail bound to the accepted commercial
contract, not as an unrelated checkout button. The payment lane validates the
canonical USDC asset, exact amount, network, payer, payee, wallet allowlists,
per-payment cap, cumulative cap, and payment count before execution. Durable
SQLite state binds one accepted proposal to one idempotency contract. Ambiguous
outcomes stop for reconciliation instead of being blindly retried.

The current public proof includes one founder-owned Circle Agent Wallet transfer
of exactly `0.10` USDC on Arc testnet. Circle history, before-and-after balances,
and independent Arc JSON-RPC verification all match the same transaction. A
durable replay returned the same proposal, payment, and transaction identifiers
without a duplicate transfer. Two earlier attempts are also disclosed: one
failed before Circle code ran because Node was unavailable, and one was rejected
before submission because Circle required a UUID-form idempotency key.

This is testnet integration evidence, not customer revenue. The deployed Gemini
order still uses offline payment, so the Gemini and Circle traces are not yet
one deployed end-to-end customer order. The sponsor wording requires a real,
verifiable USDC transaction without explicitly confirming that testnet alone is
sufficient; this submission therefore does not treat the testnet receipt as a
final eligibility determination.

### Human and AI responsibilities

The owner remains responsible for account terms, authentication, wallet
funding, standing policy, emergency stop, customer consent, evidence
publication, legal attestations, and final Devpost submission. Gemini and the
software operate only inside the approved envelope. No model can change the
destination wallet, raise the cap, count a testnet transfer as revenue, publish
private customer content, or accept its own seller output.

### Economic opportunity and business model

Autonomerce is intended for builders who own a useful agent but do not want to
build a bespoke sales and settlement stack for every capability. The proposed
business model is a fee or revenue share on successfully settled and accepted
agent services, with optional paid onboarding. The first wedge is a
source-verification and evidence-pack service because its inputs, outputs, and
acceptance contract are machine-checkable.

The repository defines seller activation, external customers, paid tasks,
refunds, variable costs, and gross margin, while explicitly excluding
synthetic, testnet, self, founder, affiliate, reimbursed, and circular activity
from customer revenue. No external customer, revenue, margin, repeat-purchase,
or job-creation number is claimed yet. Those are the next business-validation
steps, not values to infer from the technical demo.

### Build and current result

The public Next.js application connects through a server-side BFF to a private
IAM-protected FastAPI service on Cloud Run. The repository includes typed
contracts, exact-decimal USDC handling, bounded negotiation, durable payment
state, independent receipt verification, reconciliation, fulfillment
validation, redaction, threat modeling, public-evidence schemas, and a
credential-free deterministic demo.

The public CI workflow passes 371 Python tests and 47 web tests, reproduces the
offline demo byte-for-byte, scans the public tree for likely secrets, typechecks
the web application, and builds the production bundle. Recheck the latest
`main` run immediately before submission. These results prove the tested
software and the specific deployed/testnet integrations described above. They
do not prove production readiness, external demand, revenue, or first place.

Autonomerce’s north star is simple: give an existing AI agent a
policy-bounded path from capability to offer, settlement, independently judged
delivery, and auditable receipt.
