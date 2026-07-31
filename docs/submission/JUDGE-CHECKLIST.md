# Judge-facing checklist

Use this as the final evidence-index outline. A checked box means a judge can
open the cited public artifact without private access and verify the narrow
claim.

## 1. Submission basics

- [ ] Devpost profile and participant application complete.
- [ ] Project created during the eligible contest period.
- [ ] Main category is **Entrepreneurship & Job Creation**.
- [ ] Public project summary matches the submitted build.
- [ ] Video is shorter than three minutes.
- [ ] Public app URL works in a clean browser session.
- [ ] Public repository URL works and contains a license, setup instructions,
      architecture, safe demo, and limitations.
- [ ] Pre-existing asset disclosure is present.
- [ ] Evidence index uses UTC timestamps and immutable commit/revision IDs.

## 2. Build with Gemini rubric

### Business Viability

- [ ] Problem is described from external interviews, not founder intuition only.
- [ ] Interview count links to consented records.
- [ ] Design-partner count excludes uncommitted prospects.
- [ ] Paying-customer count excludes founder, affiliate, self, reimbursed,
      circular, testnet, and synthetic activity.
- [ ] Each published revenue transaction links to an order and settlement.
- [ ] At least one delivered order links payment to acceptance evidence.
- [ ] Revenue window and exclusions are explicit.
- [ ] Gemini, external-service, network/payment, and infrastructure costs are
      measured.
- [ ] Gross margin is calculated from actual costs.
- [ ] Customer quote is exact, contextualized, and consented.
- [ ] Known misses are reported rather than hidden.

Public links:

- Interviews: `[URL]`
- Customer evidence: `[URL]`
- Transactions: `[URL]`
- Revenue snapshot: `[URL]`
- Unit economics: `[URL]`

### AI-Native Operations

- [ ] Gemini is called in the deployed application.
- [ ] The recorded order shows a Gemini decision used operationally.
- [ ] Requested model ID is visible; served model ID is recorded if available.
- [ ] Prompt/config version, latency, and token usage are retained.
- [ ] Gemini output is structured and does not contain private chain-of-thought.
- [ ] Removing Gemini would materially remove adaptive productization/sales
      behavior, not just copywriting.
- [ ] Deterministic code remains authoritative for price, wallet, payment,
      idempotency, and delivery acceptance.
- [ ] Any non-Gemini provider in the submitted path is disclosed.

Public links:

- Gemini architecture: `[URL]`
- Live call evidence: `[URL]`
- Model/config record: `[URL]`

### Category Impact — Entrepreneurship & Job Creation

- [ ] Submission explains how an existing agent owner can become a seller.
- [ ] First customer wedge and seller SKU are concrete.
- [ ] Seller activation metric is defined and reported.
- [ ] External seller/design-partner evidence is separated from first-party demo.
- [ ] Impact claim is proportional to measured adoption.
- [ ] No “every agent” scale claim is presented as achieved adoption.

Public links:

- Seller onboarding demo: `[URL]`
- Activation metrics: `[URL]`
- Design-partner evidence: `[URL]`

## 3. Circle hard eligibility and proof

- [ ] Public GitHub repository.
- [ ] Gemini API used.
- [ ] Circle Agent Stack used.
- [ ] Circle Agent Wallet used.
- [ ] Agent autonomously makes and/or receives real USDC.
- [ ] No human approves the individual payment in the recorded path.
- [ ] Video includes real, verifiable transaction proof.
- [ ] Public wallet address is disclosed.
- [ ] Explorer link is disclosed.
- [ ] Testnet/mainnet is labeled accurately.
- [ ] Wallet policy and spending/recipient limits are shown.
- [ ] Transaction is bound to the accepted proposal.
- [ ] Idempotent retry does not create a duplicate settlement.

Public links:

- Wallet: `[URL OR ADDRESS]`
- Wallet policy evidence: `[URL]`
- Explorer: `[URL]`
- Redacted transaction record: `[URL]`

If any required Circle item remains unchecked, remove Circle eligibility wording
from public copy rather than implying completion.

## 4. Circle judging dimensions

### Creativeness & Innovation

- [ ] Demonstrate agent-to-seller conversion, not a generic payment button.
- [ ] Show the proposal-payment-delivery proof chain.
- [ ] Explain the OfferRail contract and differentiation in one sentence.
- [ ] Avoid novelty claims that are not supported by a comparison.

### Centrality to Business

- [ ] The demonstrated service cannot complete its commercial loop without the
      Circle settlement rail.
- [ ] USDC amount and transaction map to the actual order.
- [ ] Payment is part of the business workflow, not an isolated transfer demo.

### Technical Depth & Autonomy

- [ ] Policy, chain/token, wallet, capacity, amount, and idempotency gates are
      visible or directly linked.
- [ ] x402 use is shown if claimed.
- [ ] Ambiguous failures do not auto-retry.
- [ ] Mainnet requires durable idempotency state and explicit opt-ins.
- [ ] Payment confirmation and fulfillment acceptance are separate.
- [ ] Adversarial tests pass.

### Customer Experience

- [ ] Seller onboarding is understandable.
- [ ] Buyer need and consent are clear.
- [ ] Proposal changes are inspectable.
- [ ] Payment status is understandable without exposing secrets.
- [ ] Delivery verdict and receipt are useful to a non-developer.
- [ ] External user feedback is linked and accurately quoted.

## 5. Security and integrity

- [ ] No secret in source, fixtures, logs, screenshots, video, receipts, or git
      history.
- [ ] No OTP, recovery material, Circle session token, Google credential, or
      authorization header is public.
- [ ] Customer prompt/artifact publication follows explicit consent.
- [ ] Public receipt redaction is tested.
- [ ] Network, token, payer, payee, amount, and transaction hash are independently
      verified.
- [ ] Buyer opt-in is active and scoped.
- [ ] Emergency stop and rollback are documented.
- [ ] Mainnet wallet contains only the approved contest operating budget.
- [ ] Threat model is public.

## 6. Reproducibility

- [ ] Offline demo runs without credentials.
- [ ] Offline demo is permanently labeled synthetic/no-funds.
- [ ] Test commands and expected outputs are documented.
- [ ] Web build/typecheck/tests pass.
- [ ] Python tests pass.
- [ ] Claim linter passes.
- [ ] Public-secret scanner passes.
- [ ] JSON schemas validate public evidence.
- [ ] Deployed revision matches the public repository commit.

## 7. Final claim audit

Search the entire submission, captions, screenshots, and video for:

- `user`, `customer`, `design partner`;
- `transaction`, `payment`, `settled`;
- `revenue`, `margin`, `profit`;
- `live`, `real`, `production`;
- `autonomous`, `no human`;
- `Gemini`, `Circle`, `Agent Wallet`, `x402`;
- `validated`, `verified`, `proven`;
- percentages, counts, currency amounts, and time savings.

For every occurrence, identify:

1. the exact public evidence;
2. the classification and measurement window;
3. exclusions;
4. consent;
5. whether the wording is narrower than the evidence.

Delete or weaken any claim without a complete chain.
