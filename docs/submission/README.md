# Autonomerce submission and evidence lane

`snapshot: 2026-07-31` · `candidateOnly: true` · `canClaimAGI: false`

This directory prepares the Build with Gemini and Circle Agentic Economy
submission without converting fixtures, testnet activity, founder activity, or
plans into business evidence.

## Read order

1. [`JUDGE-QUICKSTART.md`](JUDGE-QUICKSTART.md)
2. [`EVIDENCE-INDEX.md`](EVIDENCE-INDEX.md)
3. [`DEVPOST-DRAFT.md`](DEVPOST-DRAFT.md)
4. [`VIDEO-STORYBOARD.md`](VIDEO-STORYBOARD.md)
5. [`DEMO-RUNBOOK.md`](DEMO-RUNBOOK.md)
6. [`SETUP-PROOF-CHECKLIST.md`](SETUP-PROOF-CHECKLIST.md)
7. [`METRICS-DEFINITIONS.md`](METRICS-DEFINITIONS.md)
8. [`JUDGE-CHECKLIST.md`](JUDGE-CHECKLIST.md)
9. [`KNOWN-LIMITATIONS.md`](KNOWN-LIMITATIONS.md)
10. [`CUSTOMER-INTERVIEW-TEMPLATE.md`](CUSTOMER-INTERVIEW-TEMPLATE.md)
11. [`CUSTOMER-CONSENT-TEMPLATE.md`](CUSTOMER-CONSENT-TEMPLATE.md)

Machine-readable public evidence templates are under
[`../../evidence/templates/`](../../evidence/templates/).

## Evidence-state vocabulary

Use these labels consistently in copy, screenshots, receipts, and dashboards.

| State | Meaning | May support a public claim? |
|---|---|---|
| `synthetic` | Invented fixture or example created only to exercise a schema or UI | Only the claim that a demo/schema exists |
| `offline_verified` | Credential-free code path executed and checked locally; no external service or funds | Only the tested software behavior |
| `testnet_verified` | A real testnet service or transaction has independently inspectable evidence | Technical integration, never revenue or customer demand |
| `live_verified` | A deployed external integration has timestamped logs or receipts | The specific integration behavior shown |
| `external_measured` | Arms-length customer, transaction, delivery, and consent records support the number | The measured business claim, within the stated period and exclusions |
| `planned` | Specified but not yet evidenced | No completed-capability claim |

Never use `live`, `real`, `customer`, `revenue`, `profit`, `margin`, or `validated`
as synonyms for `synthetic`, `offline_verified`, or `testnet_verified`.

## Current build snapshot

The following is a repository assessment, not a final contest verdict.

| Surface | Current evidence | Safe wording |
|---|---|---|
| Domain and OfferRail core | Typed contracts, deterministic money/policy/state logic, idempotency, and public receipt code with tests | “Implemented and tested offline” |
| Integrated demo | `python -m autonomerce.demo` connects Agent Cards, productization, opted-in matching, bounded negotiation, mock payment, fulfillment validation, and a synthetic public receipt | “Credential-free integrated offline demo; no funds move” |
| Gemini | Structured `GeminiDecisionProvider` plus productization, fit, proposal, negotiation, and delivery-decision boundaries; the current integrated demo uses the offline provider | “Gemini adapter implemented; live judged-call proof pending” |
| Circle | Guarded Circle CLI executor, payment policy, durable SQLite payment store option, x402 parser, verification hooks, and an API payment adapter; offline is the default | “Circle payment lane implemented; Agent Wallet and real transaction proof pending” |
| API | FastAPI workflow from seller onboarding through metrics, with injectable adapters | “Runnable credential-free API” |
| Web | Polished Next.js local replay using deterministic fixture data and no live API calls | “Synthetic local replay UI” |
| Deployment | Docker/Cloud Run instructions and preflight scripts | “Deployment path documented; public deployment proof pending” |
| Customers and revenue | No approved public records in this lane | “Not yet evidenced” |

## Sources of truth

When documents conflict, use this order:

1. live official contest and sponsor rules at submission time;
2. `docs/research/contests/gemini-circle-agentic-payments/FINAL-SPEC.md`;
3. `projects/autonomerce/PROJECT-CONTRACT.md`;
4. executable code and tests;
5. these submission drafts;
6. synthetic UI/demo fixtures.

The contest criteria and eligibility facts are volatile. Reverify the official
Build with Gemini Devpost rules and Circle Agentic Economy page before recording
the final video and again before final submission.

## Absolute claim boundaries

- A simulated or testnet payment is **not** customer revenue.
- A founder, affiliate, reimbursed, circular, or wallet-to-self transfer is
  **not** arms-length demand.
- A payment confirmation is **not** proof of successful delivery.
- A delivery is accepted only when the declared contract validator accepts it.
- A screenshot is supporting context, not a substitute for a public transaction
  hash, explorer record, redacted order record, or customer consent.
- UI fixture names, buyers, orders, conversion rates, and revenue are
  **synthetic** unless replaced by approved public evidence.
- Do not publish a customer prompt, identity, quote, artifact, or transaction
  linkage without the corresponding permission in the consent record.
