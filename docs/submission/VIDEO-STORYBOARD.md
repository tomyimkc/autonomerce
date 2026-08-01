# Under-three-minute video storyboard and script

`target runtime: 2:35` · `hard maximum: 2:59` · `final evidence not yet present`

The judged cut must show the strongest public evidence without editing separate
runs into one apparent order. The current evidence supports a deployed
Gemini-productization trace and a separate founder-owned Arc testnet Agent
Wallet transfer. The deployed workflow still uses mocked payment. Every
synthetic, offline, founder-owned, and testnet segment must remain visibly
labeled.

## Recording rules

- Never splice unrelated traces into one apparent order. Until a linked order
  exists, show the Gemini and Circle evidence as explicitly separate runs.
- Keep the network label visible whenever a wallet or transaction appears.
- Blur secrets, customer identity, prompts, browser account details, and private
  wallet/session material before publication.
- Show a transaction hash and explorer link long enough to pause and inspect.
- Show that the transaction did not require a per-payment approval prompt after
  the owner policy was configured.
- Show payment confirmation and delivery acceptance as separate events.
- Show only metrics backed by the public evidence files.
- If a required live proof is unavailable, say so plainly; do not substitute
  synthetic numbers.

## Current evidence-safe judged cut — 155 seconds

| Time | Visual | Narration | On-screen proof |
|---:|---|---|---|
| 0–8s | Fast montage: capable agent, empty storefront, then Autonomerce rail | “AI agents can do valuable work, but most still cannot package, sell, settle, and prove that work without a human operator.” | Product name and tagline |
| 8–23s | Public app and status response | “Autonomerce gives an existing agent a policy-controlled commercial layer. This public app is live, while funds movement remains disabled.” | Public URL; `mode=offline`; `movesFunds=false`; private-API boundary |
| 23–48s | Owner-authenticated deployed Gemini productization of the synthetic source-verification seller | “In the deployed trace, Gemini turns a declared capability into a structured SKU. The model proposes product framing; deterministic policy clamps price, capacity, scope, and acceptance criteria.” | `gemini-2.5-flash`, Cloud Run revision, UTC timestamp, latency, SKU ID, `provider=google`; persistent `SYNTHETIC SELLER` label |
| 48–65s | Commercial authority and wallet policy evidence | “Adaptive reasoning is not financial authority. Code controls the allowed action set, token, network, payer, payee, exact amount, caps, and idempotency.” | Authority fields from Gemini evidence; redacted wallet policy; no credentials |
| 65–92s | Separate Circle Agent Wallet history and Arc explorer trace | “Separately, a founder-owned Agent Wallet transferred exactly 0.10 USDC on Arc testnet under standing application policy. Circle history, balance delta, replay, and independent RPC verification agree. This is testnet integration evidence, not customer revenue and not the deployed Gemini order.” | Persistent `SEPARATE ARC TESTNET TRACE — FOUNDER-OWNED — NOT REVENUE`; network, amount, tx hash, explorer, replay IDs |
| 92–116s | Deployed synthetic workflow reaches mocked payment and deterministic acceptance | “Back in the deployed workflow, mocked payment and deterministic fulfillment exercise the commercial state machine. Payment confirmation and delivery acceptance remain separate, and receipt publication remains off.” | Persistent `MOCKED PAYMENT / SYNTHETIC WORKFLOW`; proposal, mocked payment, accepted fulfillment, `published=false` |
| 116–140s | Side-by-side proof matrix: Gemini trace, Circle trace, and missing linkage | “These two traces prove different boundaries. They do not prove one Gemini-to-Circle-to-fulfillment customer order. The missing linked order, customer consent, and video proof remain explicit blockers.” | Product Evidence pages 1–2 and 5–8; `linked order: BLOCKING`; `external customer: BLOCKING` |
| 140–150s | Current business-evidence snapshot | “No external customer, delivered paid task, mainnet revenue, or gross-margin result is currently evidenced.” | Evidence window, exclusions, and `not evidenced` labels |
| 150–155s | Logo and public links | “Autonomerce: give every AI agent a sales department.” | App, repo, Product Evidence PDF |

## Narration script

> AI agents can do valuable work, but most still cannot package, sell, settle,
> and prove that work without a human operator.
>
> Autonomerce gives an existing agent a policy-controlled commercial layer.
> This public app is live, while funds movement remains disabled.
>
> In the deployed trace, Gemini turns a declared capability into a structured
> SKU. The model proposes product framing; deterministic policy clamps price,
> capacity, scope, and acceptance criteria.
>
> Adaptive reasoning is not financial authority. Code controls the allowed
> action set, token, network, payer, payee, exact amount, caps, and idempotency.
>
> Separately, a founder-owned Agent Wallet transferred exactly zero point one
> USDC on Arc testnet under standing application policy. Circle history, balance
> delta, replay, and independent RPC verification agree.
>
> This is testnet integration evidence, not customer revenue and not the
> deployed Gemini order.
>
> Back in the deployed workflow, mocked payment and deterministic fulfillment
> exercise the commercial state machine.
>
> Payment confirmation and delivery acceptance remain separate, and receipt
> publication remains off.
>
> These two traces prove different boundaries. They do not prove one
> Gemini-to-Circle-to-fulfillment customer order.
>
> The missing linked order, customer consent, and final video proof remain
> explicit blockers. No external customer, delivered paid task, mainnet
> revenue, or gross-margin result is currently evidenced.
>
> Autonomerce: give every AI agent a sales department.

At a calm pace, the script leaves room for readable identifiers and evidence
labels. Time the actual narration; do not trust the table alone.

## Upgrade rule after a linked external pilot

Replace the evidence-safe cut only after one public record links the Gemini SKU,
proposal, Circle settlement, accepted fulfillment, and publication consent.
Never reuse the current founder-owned testnet transfer as if it were that
external order. Recompute the business sentence from the approved financial
evidence instead of manually inserting optimistic counts.

## Current offline rehearsal cut

Until the live gates clear, add a persistent banner:

> `OFFLINE SYNTHETIC REHEARSAL — DETERMINISTIC FIXTURES — NO FUNDS MOVED`

Use:

```bash
cd projects/autonomerce
PYTHONPATH=apps/api:packages python3 -m autonomerce.demo \
  --output /tmp/autonomerce-offline-demo.json
```

Safe rehearsal narration:

> “This credential-free rehearsal exercises the repository’s integrated
> contracts with a deterministic provider and simulated Circle executor. It
> proves the offline workflow and idempotency behavior only. It is not a
> customer, revenue, Gemini-live, Agent Wallet, or real-transaction claim.”

Do not submit the offline cut as proof of Circle prize eligibility.

## Shot checklist

- [ ] Runtime is below 2:59 after upload/transcoding.
- [ ] Product name and category are understandable in the first 15 seconds.
- [ ] Gemini model identity and actual operational output are visible.
- [ ] Owner policy and deterministic boundary are visible.
- [ ] Buyer opt-in/consent is visible without exposing identity.
- [ ] No per-transaction approval interruption occurs.
- [ ] Circle wallet, network, exact amount, transaction hash, and explorer proof
      are visible.
- [ ] Payment and fulfillment verdicts appear separately.
- [ ] Metrics match the public evidence snapshot exactly.
- [ ] Synthetic/testnet footage is labeled throughout.
- [ ] Captions are accurate and large enough for mobile playback.
- [ ] A backup local video file and checksum are retained.

## Failure handling during recording

| Failure | Required response |
|---|---|
| Gemini call fails or falls back offline | Stop. Do not describe the SKU as Gemini-generated. |
| Payment response is mocked | Label it simulated and remove Circle eligibility claims. |
| Transaction is testnet | Label it testnet and report zero customer revenue from it. |
| Explorer does not independently confirm | Do not call the payment verified. Reconcile before recording. |
| Per-payment approval prompt appears | The autonomy requirement is not demonstrated; fix policy/session and rerun. |
| Delivery validator rejects | Show the rejection honestly or rerun with a corrected seller output; never edit the verdict. |
| Metrics disagree with evidence JSON | Use the evidence JSON and correct the UI/narration before publishing. |
