# Autonomerce / OfferRail — judge quickstart

`submission draft: 2026-07-31` · `candidateOnly: true` · `current demo: synthetic/offline`

> **Evidence boundary:** the repository contains an integrated, credential-free
> OfferRail workflow and live-adapter code, but the approved public evidence does
> **not** yet contain a real Gemini call, Circle Agent Wallet transaction,
> external customer, revenue, public deployment, or production result.

## If you have 30 seconds

**Problem:** useful AI agents can perform work, but their owners still have to
manually package the capability, find opted-in demand, negotiate terms, collect
payment, check delivery, and prove what happened.

**Product:** Autonomerce adds that commercial operating layer. Its portable
protocol, **OfferRail**, links:

```text
declared agent capability
-> Gemini-assisted productization and sales decisions
-> deterministic owner policy
-> opted-in buyer need
-> bounded proposal and negotiation
-> Circle USDC settlement
-> seller-agent fulfillment
-> independent delivery validation
-> redacted receipt
```

**Why it is different:** Gemini can recommend adaptive commercial decisions, but
cannot widen price, scope, capacity, wallet, token, chain, settlement, or
acceptance authority. Payment confirmation and delivery acceptance are separate,
and one accepted proposal is bound to at most one settlement.

**What can be verified now:** a reproducible offline workflow, typed contracts,
policy denials, idempotent payment replay, fulfillment validation, redaction,
and evidence schemas. The offline provider and simulated Circle executor make
zero network calls and move zero real funds.

**What still needs real proof:** `[LIVE_GEMINI_ORDER]`,
`[CIRCLE_AGENT_WALLET]`, `[VERIFIABLE_USDC_TRANSACTION]`,
`[PUBLIC_DEPLOYMENT]`, and `[EXTERNAL_CUSTOMER_AND_UNIT_ECONOMICS]`.

Start here:

1. [`EVIDENCE-INDEX.md`](EVIDENCE-INDEX.md) — claim-to-proof map.
2. [`DEVPOST-DRAFT.md`](DEVPOST-DRAFT.md) — submission copy with replacement
   gates.
3. [`KNOWN-LIMITATIONS.md`](KNOWN-LIMITATIONS.md) — contest-critical gaps.

## The three-minute judge story

The final video must be under three minutes after upload/transcoding. Until live
proof exists, the same sequence may be used only as a rehearsal with a
persistent `SYNTHETIC / OFFLINE / NO FUNDS MOVED` label.

| Time | Judge question | Story and visual | Proof that must be visible |
|---:|---|---|---|
| 0:00–0:12 | What problem is this solving? | A capable agent has no repeatable way to package, sell, settle, and prove its work. | Product name, tagline, one concrete seller capability |
| 0:12–0:30 | What is the product? | Connect the capability; Autonomerce creates a policy-bounded commercial lane from SKU to receipt. | The complete OfferRail lifecycle in one frame |
| 0:30–0:50 | Is Gemini operational or decorative? | A live Gemini decision converts the declared capability into a structured SKU or materially shapes the shown proposal. Code visibly clamps unauthorized terms. | Requested model, UTC timestamp, operation, structured output, resulting SKU/proposal ID, clamp result |
| 0:50–1:10 | Who remains in control? | The owner sets price, capacity, buyer, token, chain, wallet, and unattended limits once. The model cannot alter them. | Policy ID/version, caps, allowlists, configured wallet |
| 1:10–1:32 | How does selling happen? | An explicitly opted-in buyer need is matched; a machine-readable proposal is generated; a bounded counter is accepted, countered, or declined. | Consent reference, need ID, proposal revision diff, deterministic reason code |
| 1:32–1:58 | Is Circle central and autonomous? | The accepted proposal triggers the required Circle Agent Wallet USDC path without a per-payment approval prompt. | Network, wallet, exact amount, transaction hash, explorer confirmation, no approval interruption |
| 1:58–2:20 | Does payment equal success? | No. The seller agent fulfills after settlement, and a separate deterministic validator checks the accepted contract. | Payment status and delivery verdict shown as distinct events; artifact hash and acceptance results |
| 2:20–2:38 | Can a judge audit it? | A redacted receipt binds the order, proposal, settlement, fulfillment, and evidence classification without exposing prompts, artifacts, or secrets. | Linked IDs, receipt hash, publication consent reference |
| 2:38–2:52 | Is there business evidence? | Report only approved external measurements for a fixed UTC window. If all values are zero, show zero. | `[CUSTOMERS]`, `[DELIVERED_PAID_TASKS]`, `[EXTERNAL_MAINNET_USDC]`, `[VARIABLE_COSTS]`, `[GROSS_MARGIN]`, exclusions |
| 2:52–2:59 | Why does it matter? | “Autonomerce gives an existing agent a policy-bounded path to become a seller.” | Public app, repository, evidence index |

### The first 30-second narration

> Useful AI agents can do work, but their owners still have to package the
> service, find opted-in demand, negotiate, collect payment, check delivery, and
> keep the evidence. Autonomerce adds that commercial operating layer. OfferRail
> links Gemini-assisted sales decisions to deterministic owner policy, Circle
> USDC settlement, independent fulfillment validation, and a redacted receipt.
> This recording will show one order end to end and label every synthetic,
> testnet, or live step explicitly.

Do not say “this recording will show” the live steps unless the final recording
actually contains them. For the current offline rehearsal, replace the last
sentence with:

> This is a deterministic offline rehearsal: no Gemini service is called, no
> Circle Agent Wallet is used, and no funds move.

## What a judge can reproduce now

From `projects/autonomerce`:

```bash
uv sync --frozen --extra api --extra gemini --extra test

PYTHONPATH=apps/api:packages/offerrail:. \
  python3 examples/run_offline_demo.py \
  --output /tmp/autonomerce-offline-demo.json
```

Inspect these narrow diagnostics:

```text
diagnostics.offline = true
diagnostics.networkCalls = 0
diagnostics.credentialsUsed = false
diagnostics.realFundsMoved = false
diagnostics.idempotentPaymentReplay = true
diagnostics.paymentExecutorCalls = 1
diagnostics.ledgerEntries = 4
diagnostics.ledgerVerified = true
```

The generated amount, wallets, transaction hash, buyer, seller, delivery, and
receipt are fixtures. A passing run supports only the claim that the integrated
offline software path executed with the listed properties.

Repository verification:

```bash
PYTHONPATH=apps/api:packages/offerrail:. \
  python3 -m pytest -q tests

python3 scripts/scan_public_secrets.py

# When running inside the Sophia repository:
python3 ../../tools/lint_claims.py
```

Record a public CI/run URL before stating that the submission revision passed
these gates: `[PUBLIC_CI_RUN_URL]`.

## Rubric route

| Target | Judge-first case | Current repository evidence | Evidence still required |
|---|---|---|---|
| Build — Business Viability | Converts an existing callable agent into a metered seller with a fee/revenue-share path and defined unit economics. | business model, portable adapter architecture, pricing/cost definitions, evidence schemas, and strict revenue exclusions | `[REAL_USERS]`, `[ARMS_LENGTH_REVENUE]`, `[DELIVERED_PAID_ORDERS]`, `[ALL_EXPENSES]`, `[MARKETING_SPEND]`, and `[MARGIN_SNAPSHOT]` |
| Build — AI-Native Operations | Gemini is intended to make structured productization, fit, proposal, negotiation, or delivery-summary decisions inside deterministic authority. | Gemini provider and typed decision services; tests for structured output and policy non-expansion | `[DEPLOYED_GEMINI_CALL]` materially used by the recorded order plus production execution evidence |
| Build — Category Impact | Gives owners of useful agents a reusable path to activate a seller in Entrepreneurship & Job Creation rather than build a bespoke sales stack. | onboarding and OfferRail lifecycle implemented; seller activation metric defined | `[EXTERNAL_INTERVIEWS]`, `[EXTERNAL_SELLER_ACTIVATION]`, `[PAYING_CUSTOMERS]`, `[CUSTOMER_FEEDBACK]`, and no unsupported job-count claim |
| Circle — Creativeness & Innovation | Binds an agent-native commercial contract to settlement and delivery evidence, rather than adding a generic checkout button. | proposal/payment/fulfillment contracts and receipts | working public comparison/demo and `[REAL_TRANSACTION_PROOF]` |
| Circle — Centrality to Business | The commercial loop cannot complete without settlement bound to the accepted proposal. | strict payment authorization, receipt verification hooks, and separate delivery state | `[CIRCLE_AGENT_WALLET]` plus one order-linked USDC settlement |
| Circle — Technical Depth & Autonomy | Standing owner policy, exact authorization, durable idempotency, fail-closed verification, and no per-payment approval design. | guarded Circle adapter, x402 parser, SQLite store, reconciliation, adversarial tests | recorded live run showing wallet policy, no approval interruption, explorer proof, and idempotent replay |
| Circle — Customer Experience | Seller sees one understandable workflow from capability to auditable receipt. | Next.js replay and owner-authenticated LIVE path code | deployed connected flow, reliable completion, and `[EXTERNAL_CUSTOMER_FEEDBACK]` |

The three main-campaign criteria are equally weighted. The Circle page does not
publish weights for its four criteria.

See the artifact-level mapping in
[`EVIDENCE-INDEX.md`](EVIDENCE-INDEX.md).

## Five invariants worth inspecting

1. **Model advice is not authorization.** Deterministic code owns money, scope,
   wallets, chain/token, idempotency, and delivery acceptance.
2. **Opt-in is mandatory.** Non-opted-in buyer needs are rejected.
3. **One proposal, at most one settlement.** Replays return the prior result;
   conflicting reuse fails closed.
4. **Payment is not delivery.** Fulfillment has its own contract validator and
   verdict.
5. **Public does not mean private data.** Receipts expose approved identifiers,
   hashes, and verdicts, not credentials, customer prompts, or private artifacts.

## Claim vocabulary

| Label | Meaning |
|---|---|
| `synthetic` | invented fixture or replay; proves only that a demo/schema exists |
| `offline_verified` | credential-free code path was executed; no external service or funds |
| `testnet_verified` | independently inspectable test-network evidence; never revenue |
| `live_verified` | timestamped evidence supports the specific external integration shown |
| `external_measured` | arms-length customer, transaction, delivery, consent, and cost records support the stated metric |
| `planned` | specified but not yet evidenced |

Never collapse these states into “real,” “live,” “customer,” “revenue,” or
“validated.”

## Blocking placeholders before final submission

- `[PUBLIC_REPOSITORY_URL]`
- `[PUBLIC_APP_URL]`
- `[UNDER_3_MINUTE_VIDEO_URL]`
- `[PUBLIC_EVIDENCE_INDEX_URL]`
- `[DEPLOYED_REVISION_AND_COMMIT]`
- `[LIVE_GEMINI_CALL_EVIDENCE_URL]`
- `[CIRCLE_AGENT_WALLET_ADDRESS]`
- `[WALLET_POLICY_EVIDENCE_URL]`
- `[VERIFIED_TRANSACTION_EXPLORER_URL]`
- `[REDACTED_ORDER_TRANSACTION_DELIVERY_RECORD_URL]`
- `[EXTERNAL_CUSTOMER_CONSENT_EVIDENCE_URL]`
- `[REVENUE_AND_UNIT_ECONOMICS_SNAPSHOT_URL]`
- `[PUBLIC_CI_RUN_URL]`

If a blocking artifact is absent, leave the corresponding public claim absent
or state the gap explicitly.
