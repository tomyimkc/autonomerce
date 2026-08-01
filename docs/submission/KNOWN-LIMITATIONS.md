# Known limitations

`assessment snapshot: 2026-08-01`

This file describes the current repository state observed while preparing the
submission lane. Other implementation lanes are active, so re-audit immediately
before publishing.

## Contest-critical open gaps

1. **The deployed Gemini proof covers productization only.** It uses synthetic
   seller data and records no external customer, served-model metadata, token
   usage, or cost.
2. **The Circle proof is testnet-only and separate from the deployed Gemini
   order.** One 0.10 USDC Agent Wallet transfer is independently verified, but
   the Cloud Run workflow still uses offline payment.
3. **No deployed Gemini-to-Circle-to-fulfillment order is approved in public
   evidence.**
4. **No external customer, design-partner, revenue, repeat-purchase, customer
   quote, or measured margin record is approved here.**
5. **Final Circle sponsor eligibility remains incomplete** until the video and
   deployed commercial-order linkage requirements are satisfied and the
   official rules are rechecked. The sponsor page requires a “real,
   verifiable USDC transaction” but does not explicitly state that an Arc
   testnet transfer satisfies that phrase, so this repository does not assume
   that testnet proof alone clears eligibility.

These are blocking evidence gaps, not permission to imply that setup happened
privately.

## Integrated demo limitations

- The one-command demo is deterministic, credential-free, and uses fixtures.
- It makes zero network calls and moves zero real funds.
- Productization is attributed to the offline rules provider, not Gemini.
- Payment uses the offline Circle executor.
- The seller and buyer Agent Cards, need, artifact, wallets, timestamps, and
  commercial event sequence are synthetic.
- The demo proves code integration and idempotent offline replay only.
- The fixture fulfillment adapter does not prove an external seller-agent
  endpoint completed paid work.

## API composition limitations

- Offline mode intentionally uses process-local in-memory state.
- The supported live topology persists commerce and payment state in one SQLite
  database on one persistent host. It is not replicated, highly available, or
  safe for multiple API workers or horizontally scaled instances.
- Cloud Run is supported only for the private offline-payment API path. The
  current live payment topology is a single Compute Engine host with persistent
  disk.
- Optional integration adapters are discovered dynamically. Offline mode may
  use deterministic adapters; non-offline startup fails closed if the required
  payment or seller executor is unavailable.
- The API does not currently expose a dedicated public Agent Card endpoint.
- Seller creation stores a manifest, while full Agent Card parsing is exercised
  in the integrated demo/sales lane rather than the seller-create API route.
- x402 parsing exists in the payment package but is not demonstrated in the
  current end-to-end offline scenario.

## Gemini limitations

- The Gemini provider is optional and depends on owner-authenticated Google
  configuration.
- A deployed productization call records the requested model, Cloud Run revision,
  latency, structured result, and output hash. The served model identifier,
  token usage, and cost were not exposed and are not inferred.
- The default model string in code may not be the final pinned submission model.
- The public judging deployment explicitly selects `gemini-2.5-flash`; the
  credential-free local demo still reports the deterministic provider instead.
- Model output controls advisory display copy and relevance only. Price,
  latency, capacity, schemas, acceptance criteria, wallets, token, chain, and
  settlement remain deterministic. This deliberately limits model authority.

## Circle/payment limitations

- Offline payment receipts contain deterministic synthetic transaction hashes
  and no explorer URL.
- The testnet transfer used the Circle CLI Agent Wallet surface and publishes
  both wallet addresses, bounded application policy, transaction hash, and
  explorer URL. A final video still needs to show the product surface and
  uninterrupted order path.
- Live modes require owner wallet allowlists and durable SQLite state.
- The testnet runner pins the Circle CLI and Node interpreter by SHA-256 and
  independently verifies Arc receipts. The deployed Cloud Run API does not run
  this payment topology.
- Mainnet requires two explicit software opt-ins, but owner-side wallet policy,
  authentication, funding, and emergency-stop evidence remain operational tasks.
- Ambiguous CLI timeouts remain unresolved/submitting and require reconciliation.
- Normal live confirmation and reconciliation both fail closed unless real
  independent transaction evidence verifies the chain, canonical USDC contract,
  amount, payer, payee, and transaction hash.
- Acceptance binds the payer from the payment adapter's owner allowlist. A live
  deployment with multiple payer wallets must supply the intended allowlisted
  payer at acceptance; payment-time substitution remains rejected.
- Shared-SQLite crash recovery verifies the full settlement authorization,
  including canonical token/asset and both wallets, before importing a confirmed
  payment or advancing the proposal to paid.
- The current UI shows Arc Testnet fixture settlement. It is not customer revenue.

## Web limitations

- DEMO mode is a synthetic replay.
- LIVE mode uses a server-side backend-for-frontend, a signed short-lived owner
  session, a Cloud Run IAM identity token, and the private FastAPI bearer. The
  public deployment completed onboarding and one workflow against the private
  Gemini API with funds movement disabled.
- The named seller, buyer agents, orders, transaction hash, revenue amounts,
  conversion rate, trends, deltas, and autonomy report shown in DEMO mode are
  synthetic fixtures.
- “LIVE REPLAY” means an active local animation/replay, not live external data.
- LIVE owner authentication is a single-owner shared-secret session, not
  federated identity, buyer authentication, or multi-tenant authorization.
- Login/status limits are process-local to one web instance; a production edge
  or shared distributed rate limit is still required for fleet-wide
  enforcement. Each process now has bounded per-address state and a global
  budget, and ignores forwarding headers unless a trusted-proxy switch is
  explicitly enabled.
- Workflow retry is covered against the single-owner API and resumes one stable
  operation/payment key. It is not a distributed workflow engine.
- Proposal identity includes the exact buyer-need ID, and fulfillment resolves
  that need rather than selecting the first prospect sharing a buyer URL.
- The deployed trace proves Gemini productization only. Its payment and
  fulfillment adapters remain offline and do not prove Circle operation.
- Any presentation-only control must be removed or clearly labeled before final
  contest footage.

## Metrics limitations

- `paidTasks`, `usdcRevenue`, and `repeatPurchaseRate` are intentionally null
  until every confirmed payment in scope has verified, complete deal evidence.
- live settlement volume is reported separately and does not prove the payer is
  an external customer rather than founder/self/affiliate/reimbursed.
- `grossMarginUsdc` remains null until verified deal evidence explicitly closes
  the refund window and records measured per-order costs.
- `medianDeliverySeconds` measures payment confirmation to accepted delivery when
  timestamps are available; it is not full order-to-delivery duration.
- Offline counters are process-local. The supported single-host live repository
  persists operational metrics in SQLite, but no multi-host aggregation exists.
- the implementation can record network, infrastructure, fulfillment, other
  variable costs, and refunds per completed deal, but no approved external
  customer cost record exists in the public evidence as of August 1, 2026.

The public revenue schema and
[`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md) must govern submission numbers.

## Business-evidence limitations

- Interview and consent templates are ready, but templates are not interviews.
- A stated willingness to pay is not a customer or revenue event.
- A testnet transfer is not a sale.
- A founder payment is not market demand.
- A transaction hash alone does not prove customer relationship, delivered
  outcome, consent, or margin.
- The “every AI agent” tagline expresses the product vision, not measured
  universal compatibility or adoption.
- The first seller wedge is specified, but external demand remains to be shown.

## Security and operating limitations

- The product has not undergone an external security audit.
- The threat model and adversarial tests reduce known risks but do not guarantee
  the absence of vulnerabilities.
- Circle and Google account/session expiry can interrupt the live demo.
- Wallet policies and application policies are separate controls and must both
  be inspected.
- Public blockchain addresses and transactions are irreversible public data;
  redaction cannot remove them from the chain.
- Customer prompts and artifacts require separate consent from transaction
  publication.
- Offline publication uses a purpose-scoped `publication:` reference. Live
  publication remains disabled unless an injected verifier confirms a durable
  publication-specific consent record for the exact proposal and field set.
- Mainnet activity carries real financial risk and must remain tightly capped.

## Explicit non-goals for the contest build

- central marketplace;
- escrow or pooled custody;
- custom token;
- consumer wallet;
- investing, lending, credit, payroll, or autonomous treasury management;
- unsolicited mass outreach;
- unbounded dynamic pricing;
- model training;
- proof of broad production scale.
