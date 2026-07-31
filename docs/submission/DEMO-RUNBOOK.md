# Autonomerce demo runbook

This runbook has two distinct modes:

1. **offline rehearsal**, executable now with deterministic fixtures and no funds;
2. **live judged run**, permitted only after the setup proof gates pass.

Never allow an offline or testnet run to inherit the visual or verbal label
“customer revenue.”

## 1. Operator roles

| Role | Responsibility |
|---|---|
| Owner | account terms, authentication/OTP, billing, wallet funding, policy approval, publication consent, final submit |
| Demo operator | starts services, checks evidence state, runs the order, captures proof, stops on ambiguity |
| Evidence reviewer | verifies redaction, transaction/order linkage, consent, metric formulas, and claim wording |
| Customer/buyer | provides arms-length need, consent, payment, and delivery feedback; may use a pseudonym publicly |

The owner may also be the operator, but an owner/founder transfer still cannot
be counted as external customer revenue.

## 2. Offline integrated rehearsal

### Preconditions

- Python 3.11 or newer.
- No credentials are required.
- Run from the product root.
- Treat every output as synthetic.

### One-command scenario

```bash
cd projects/autonomerce
PYTHONPATH=apps/api:packages python3 -m autonomerce.demo \
  --output /tmp/autonomerce-offline-demo.json
```

Expected evidence:

```json
{
  "offline": true,
  "networkCalls": 0,
  "credentialsUsed": false,
  "realFundsMoved": false,
  "idempotentPaymentReplay": true,
  "ledgerVerified": true
}
```

The output also identifies the concrete lane implementations used. The generated
receipt is a simulated fixture and must not be copied into a live transaction
file without the `synthetic` classification.

### API rehearsal

Terminal A:

```bash
cd projects/autonomerce
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[api,gemini,test]"
PYTHONPATH=apps/api:packages \
  uvicorn autonomerce.api.app:create_app --factory --port 8000
```

Confirm:

```bash
curl -sS http://127.0.0.1:8000/health | python3 -m json.tool
```

For a safe offline run, the productizer must report `offline`; the payment
integration may report `mock` or an optional adapter whose configured mode is
offline. Any returned payment must contain `"mocked": true`.

Use the interactive OpenAPI page at `http://127.0.0.1:8000/docs` or call these
routes in order:

1. `POST /sellers`
2. `POST /sellers/{sellerId}/capabilities`
3. `POST /sellers/{sellerId}/skus/preview`
4. `POST /sellers/{sellerId}/policies`
5. `POST /prospects` with `"optedIn": true`
6. `POST /proposals`
7. `POST /proposals/{proposalId}/counter`
8. `POST /proposals/{proposalId}/accept`
9. `POST /proposals/{proposalId}/pay`
10. repeat step 9 with the same idempotency key and confirm no second execution;
11. `POST /proposals/{proposalId}/fulfill`
12. `GET /receipts/{proposalId}`
13. `GET /metrics`

Recommended synthetic fixture terms:

- seller wallet: `0x1111111111111111111111111111111111111111`;
- payer wallet: `0x2222222222222222222222222222222222222222`;
- network: `ARC-TESTNET`;
- price: `0.10` USDC;
- buyer host: `buyer.example`;
- idempotency key: `synthetic-demo-order-001`;
- artifact verdict: `abstain`, with an empty source list.

These values are documentation fixtures, not users, wallets, transactions, or
results.

### Web rehearsal

```bash
cd projects/autonomerce/apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

The page is a static local replay. It makes no API or wallet calls. Keep the
“Demo data” control visible and add a recording overlay that says:

> `SYNTHETIC UI FIXTURE — NO CUSTOMER OR REVENUE EVIDENCE`

The UI’s named seller, buyers, orders, amounts, conversion, and revenue chart are
not public business metrics.

## 3. Live judged run — preflight

Do not begin until every blocking item is checked.

### Google/Gemini

- [ ] Google Cloud project and billing are active.
- [ ] deployed service uses a Google Cloud product;
- [ ] Application Default Credentials or workload identity is active;
- [ ] a pinned Gemini model is configured;
- [ ] the application records requested model, served model if available,
      operation, UTC timestamp, prompt/config version, latency, and token usage
      without storing secrets or private reasoning;
- [ ] `GET /health` or equivalent reports a live Gemini productizer, not
      `offline`;
- [ ] no non-Gemini fallback silently handles the judged order.

### Circle

- [ ] owner is authenticated to the correct Circle environment;
- [ ] required Circle Agent Wallet exists;
- [ ] wallet policy has a low per-transaction and total cap;
- [ ] payer and payee wallets are allowlisted;
- [ ] mainnet wallet contains only the approved contest operating budget;
- [ ] durable idempotency storage is configured;
- [ ] the operator has a tested emergency stop;
- [ ] testnet proof passed before mainnet;
- [ ] live mode cannot start without the explicit mainnet confirmations;
- [ ] public wallet address and explorer URL are approved for publication.

### Customer/order

- [ ] customer is external and relationship is recorded;
- [ ] buyer need is explicitly opted in;
- [ ] price, scope, artifact publication, quote, and transaction-publication
      permissions are separately recorded;
- [ ] no customer prompt or identity appears in the public screen capture unless
      specifically permitted;
- [ ] the order is not founder-funded, reimbursed, circular, affiliate-only, or
      wallet-to-self if it will be counted as external revenue.

### Evidence

- [ ] destination directory is private and untracked during capture;
- [ ] clock is synchronized and UTC timestamps are available;
- [ ] repository commit and deployed revision are recorded;
- [ ] secret scanner passes before and after redaction;
- [ ] public transaction and revenue files validate against the schemas under
      `evidence/templates/`.

## 4. Live judged run — execution

### A. Start and identify the build

Capture:

- repository commit;
- deployed revision;
- application URL;
- health output;
- Gemini model/config version;
- Circle network and public wallet;
- policy ID and caps.

Stop if the deployed revision does not match the reviewed commit.

### B. Onboard the seller

1. load one real seller Agent Card or capability manifest;
2. show only public capability fields;
3. verify the destination seller wallet is owner-configured, not model-provided;
4. record the seller ID and capability ID.

### C. Productize with Gemini

1. invoke the live Gemini-backed productizer;
2. capture the structured response metadata;
3. show the resulting SKU;
4. show any price/capacity clamp performed by deterministic code;
5. record the SKU ID and acceptance contract.

Stop if the provider is offline, the response lacks model identity, or the
model widens the owner policy.

### D. Discover opted-in demand and propose

1. register the buyer need with active consent;
2. show fit/match reasoning codes;
3. generate the proposal;
4. record proposal ID, revision, amount, scope, expiry, and acceptance criteria.

Stop if the buyer is not opted in or the proposal exceeds budget or policy.

### E. Negotiate

1. submit a bounded counteroffer;
2. show Gemini’s recommended action;
3. show the deterministic authorized action set and final decision;
4. confirm scope and acceptance criteria did not silently expand;
5. accept the final proposal.

### F. Settle with Circle

1. show the already-approved wallet policy;
2. trigger payment from the accepted proposal;
3. do not interact with a per-payment approval prompt;
4. wait for an unambiguous confirmed receipt;
5. independently open the explorer record;
6. verify chain, token, exact amount, payer, payee, and transaction hash;
7. retry the same idempotency key and confirm no second transfer;
8. record the payment ID and classification.

Stop on timeout, ambiguous settlement, mismatched receipt fields, missing
explorer proof, or any duplicate transfer. Reconcile manually; never auto-retry
an ambiguous live payment.

### G. Fulfill and validate

1. route the paid task to the seller agent;
2. capture private artifact and logs outside the public repository;
3. run deterministic contract validation;
4. show every acceptance result;
5. record artifact hash and fulfillment ID;
6. publish only the redacted receipt fields permitted by consent.

If validation fails, do not describe the order as delivered. A failed delivery
may still be valuable evidence if reported honestly.

### H. Publish evidence and metrics

1. create one transaction record per settlement;
2. link order, proposal, payment, and fulfillment IDs;
3. classify synthetic, testnet, founder/self, affiliate, or external mainnet;
4. count revenue only under the definitions in `METRICS-DEFINITIONS.md`;
5. add actual variable costs before calculating gross margin;
6. validate JSON;
7. run redaction and secret scans;
8. obtain final owner/customer publication approval.

## 5. Demo success criteria

The live judged run is successful only if:

- Gemini materially generated or recommended an operational decision used by
  the order;
- deterministic code authorized all commercial and payment terms;
- the buyer was opted in;
- no human approved the individual payment;
- Circle independently confirms the exact USDC settlement;
- one payment is bound to one accepted proposal;
- fulfillment ran after confirmation;
- delivery acceptance was decided separately;
- the public receipt is redacted and linked;
- metrics preserve every exclusion.

## 6. Recovery table

| Symptom | Action |
|---|---|
| Gemini unavailable | Fail closed or explicitly switch to rehearsal mode. Do not record a judged cut. |
| Circle CLI/session expired | Stop, let the owner reauthenticate, verify network and policy again, then create a new order/idempotency key. |
| Ambiguous payment timeout | Do not retry. Query transaction state and reconcile the reserved payment. |
| Wrong chain/token/wallet | Treat as a hard failure and investigate; do not edit the receipt. |
| Duplicate key bound to another proposal | Reject with conflict; create no payment. |
| Fulfillment rejected | Preserve the rejected receipt; correct the seller output under the order’s allowed retry policy or issue a new order. |
| Public file leaks private data | Remove the public artifact immediately where possible, rotate any exposed secret, and regenerate from the private source. |
| Metrics are inconsistent | Freeze publication, reconcile transaction-level records, and regenerate the snapshot. |
