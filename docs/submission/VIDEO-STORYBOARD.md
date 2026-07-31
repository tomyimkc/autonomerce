# Under-three-minute video storyboard and script

`target runtime: 2:35` · `hard maximum: 2:59` · `final evidence not yet present`

The final judged cut must show a real deployed Gemini-in-the-loop workflow and,
for the Circle prize, a real verifiable USDC transaction using the required
Circle wallet surface. The current local UI and offline demo are useful for
rehearsal only and must be labeled **SYNTHETIC / NO FUNDS MOVED**.

## Recording rules

- Record one coherent order. Do not splice unrelated transactions into one story.
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

## Final judged cut — 155 seconds

| Time | Visual | Narration | On-screen proof |
|---:|---|---|---|
| 0–8s | Fast montage: capable agent, empty storefront, then Autonomerce rail | “AI agents can do valuable work, but most still cannot package, sell, settle, and prove that work without a human operator.” | Product name and tagline |
| 8–20s | Seller onboarding with one real capability manifest | “Autonomerce gives an existing agent a sales department. I connect a capability; the owner sets the boundaries once.” | Agent URL/manifest type; no secrets |
| 20–38s | Live Gemini productization response becomes an SKU | “Gemini turns the declared capability into a sellable outcome and acceptance contract. The model recommends; code clamps price, capacity, and scope to policy.” | Requested model ID, timestamp, SKU, `provider=google`; redact prompt content if needed |
| 38–55s | Policy editor: price floor/ceiling, allowed buyer, chain, token, capacity, unattended switch | “The owner authorizes a commercial and wallet envelope—not each checkout. Gemini cannot raise these limits or choose a new destination wallet.” | Policy ID, wallet policy screenshot, caps |
| 55–72s | Opted-in buyer need appears; proposal is generated | “An opted-in buyer publishes a need. Autonomerce matches it to the SKU and creates a machine-readable proposal.” | Consent reference, buyer pseudonym, proposal ID |
| 72–89s | Buyer counter; deterministic gate accepts/counters/declines | “The buyer counters. Gemini recommends an action from the safe action set; deterministic code enforces discount, scope, expiry, buyer, and capacity bounds.” | Revision diff and policy decision code |
| 89–112s | Accepted proposal triggers Circle payment; no approval dialog; explorer opens | “Inside policy, the transaction proceeds without a per-payment human prompt. Circle settles exactly the accepted amount to the bound seller wallet.” | Agent Wallet address, network, amount, tx hash, explorer confirmation |
| 112–132s | Seller agent fulfills; contract validator evaluates artifact | “Payment does not mean success. The seller agent delivers the work, and a separate validator checks the accepted schema and criteria.” | Artifact hash, validator name, PASS/FAIL criteria |
| 132–145s | Public redacted receipt links proposal, payment, and delivery | “The public receipt links one proposal, one settlement, and one delivery verdict without exposing the customer prompt or private artifact.” | Order ID, proposal ID, payment ID, fulfillment ID |
| 145–152s | Public evidence snapshot | “In this measurement window: [VERIFIED CUSTOMERS], [VERIFIED DELIVERED PAID TASKS], [VERIFIED MAINNET USDC REVENUE], and [VERIFIED GROSS MARGIN].” | Evidence JSON with UTC window and exclusions |
| 152–155s | Logo and public links | “Autonomerce: give every AI agent a sales department.” | App, repo, evidence links |

## Narration script

> AI agents can do valuable work, but most still cannot package, sell, settle,
> and prove that work without a human operator.
>
> Autonomerce gives an existing agent a sales department. I connect a
> capability; the owner sets the boundaries once.
>
> Gemini turns the declared capability into a sellable outcome and acceptance
> contract. The model recommends; code clamps price, capacity, and scope to
> policy.
>
> The owner authorizes a commercial and wallet envelope—not each checkout.
> Gemini cannot raise these limits or choose a new destination wallet.
>
> An opted-in buyer publishes a need. Autonomerce matches it to the SKU and
> creates a machine-readable proposal.
>
> The buyer counters. Gemini recommends an action from the safe action set;
> deterministic code enforces discount, scope, expiry, buyer, and capacity
> bounds.
>
> Inside policy, the transaction proceeds without a per-payment human prompt.
> Circle settles exactly the accepted amount to the bound seller wallet.
>
> Payment does not mean success. The seller agent delivers the work, and a
> separate validator checks the accepted schema and criteria.
>
> The public receipt links one proposal, one settlement, and one delivery
> verdict without exposing the customer prompt or private artifact.
>
> In this measurement window: [VERIFIED CUSTOMERS], [VERIFIED DELIVERED PAID
> TASKS], [VERIFIED MAINNET USDC REVENUE], and [VERIFIED GROSS MARGIN].
>
> Autonomerce: give every AI agent a sales department.

At a calm 125–135 words per minute, the script leaves room for natural pauses
and visual proof. Time the actual narration; do not trust the table alone.

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
