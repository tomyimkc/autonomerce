# Autonomerce Code Review

**Review date:** 2026-07-31
**Scope:** contracts, OfferRail, Gemini agents, sales, payments/x402, FastAPI,
offline E2E/demo, web, security controls, deployment, and tests
**Implementation changes made by this review:** none

> **Historical baseline, not current-state guidance.** See
> `CODE-REVIEW-FOLLOWUP.md` for the refreshed status. Subsequent work implemented
> fail-closed live composition, private API owner checks, signed web owner sessions,
> backend-compatible LIVE consent/input/publication flow, durable commerce and
> payment SQLite state with a same-database preflight requirement, hardened URL
> ingestion, and frozen API image inputs. The findings below remain the original
> review record rather than current deployment facts.

## Release recommendation

**NO-GO for an internet-exposed or real-funds deployment.**

**GO only for the explicitly credential-free offline CLI demo.** The offline
scenario is deterministic, exercises the isolated implementation lanes, and clearly
labels the settlement as simulated. The composed FastAPI/web/deployment path does
not yet provide the same end-to-end guarantees.

The highest-risk gaps are:

1. the documented "live" deployment still selects offline/mock payment behavior and
   ignores the documented 1/10 USDC limits;
2. the deployment is explicitly unauthenticated while exposing policy mutation and
   payment-triggering endpoints;
3. the FastAPI composition path does not wire the Gemini or live seller-agent lanes,
   and it can issue a fulfillment receipt from an artifact supplied by the API caller;
4. API negotiation and validation are materially weaker than the OfferRail/agent
   implementations they are supposed to compose.

The target tree changed concurrently during this review (`pyproject.toml`, API
metrics, and tests). I refreshed the isolated review copy and reran the affected
suite against the current tree before writing this report.

## Prioritized findings

### CR-01 — Critical — The documented live configuration silently runs offline/mock payments and ignores the documented safety caps

**Evidence**

- `infra/README.md:24-30` deploys with `AUTONOMERCE_MODE=live`.
- `.env.example:2,14-17` documents `AUTONOMERCE_MODE`,
  `AUTONOMERCE_CIRCLE_NETWORK`, `AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC=1`, and
  `AUTONOMERCE_CIRCLE_MAX_DAILY_USDC=10`.
- `apps/api/autonomerce/payments/api_adapter.py:149-180` reads a different set of
  variables: `AUTONOMERCE_PAYMENT_MODE`,
  `AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC`,
  `AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC`, and
  `AUTONOMERCE_PAYMENT_SQLITE_PATH`. Its defaults are offline mode, 1,000 USDC per
  payment, and 10,000 USDC total.
- `apps/api/autonomerce/api/adapters.py:213-232,243-270` catches adapter factory
  errors and substitutes the mock adapter rather than failing startup.
- `apps/api/autonomerce/api/app.py:414-423` always reports
  `credentialsRequired: false`; the integration label does not expose whether the
  selected payment executor moves funds.

**Verified failure scenarios**

- With the exact documented `AUTONOMERCE_MODE=live`, the current application loaded:
  `OfflineProductizer`, `PaymentAdapter(mode=OFFLINE)`, and
  `OfflineFulfillmentAdapter`. Health labeled payment as `"optional"`, not offline.
- With `AUTONOMERCE_PAYMENT_MODE=testnet` but the required SQLite path/allowlists
  omitted, application startup succeeded with `MockPaymentAdapter`; the configuration
  error was reduced to an item in `optionalImportErrors`.
- With the documented Circle limits set to 1/10 USDC and a valid testnet adapter
  configuration, the adapter still used 1,000/10,000 USDC because those variable
  names are not read.

**Impact**

A contest deploy following the provided runbook can display a confirmed-looking
payment that never contacted Circle. If an operator later enables live mode but
relies on the documented cap variables, the independent payment gate is up to
1,000 times more permissive than intended. A malformed live configuration fails
open to a mock rather than refusing to start.

**Action**

1. Define one canonical runtime mode and one documented payment configuration schema.
2. In testnet/mainnet mode, fail application startup if any required adapter,
   durable store, wallet allowlist, credential source, or cap is missing.
3. Never substitute `MockPaymentAdapter` when a non-offline mode was requested.
4. Make `/health` report `paymentMode`, executor class, `movesFunds`, effective caps,
   store type/durability, and whether every required live lane loaded.
5. Add deployment tests that construct the app from `.env.example` and the Cloud Run
   command and assert the exact effective configuration.

---

### CR-02 — Critical — The documented public deployment exposes every state-changing and payment-triggering API without authentication or object authorization

**Evidence**

- `infra/README.md:25-29` deploys the API with `--allow-unauthenticated`.
- `apps/api/autonomerce/api/app.py:425-907` exposes seller creation, capability
  creation, policy replacement, prospect creation, proposal creation/counter/
  acceptance, and payment execution as ordinary routes with no authentication
  dependency.
- `apps/api/autonomerce/api/app.py:909-995` similarly exposes fulfillment.
- `apps/api/autonomerce/api/schemas.py:139-144` lets the caller select the payer
  wallet supplied to the payment adapter.
- Route introspection confirmed zero FastAPI dependencies on every application route.

**Failure scenario**

When the documented unauthenticated service is connected to a live Circle session,
an internet caller can create or replace a seller policy, register its own opted-in
buyer, create and accept a proposal, and call `/pay`. If the caller supplies a known
allowlisted payer address and constructs the seller with an allowlisted destination,
the server-side Circle session can spend the owner-controlled wallet without proving
that the caller owns the buyer, seller, policy, or wallet.

The same missing authorization globally exposes buyer needs and complete fulfillment
artifacts through `/prospects`, `/fulfill`, and repeated fulfillment responses.

**Action**

1. Keep payment/mutation routes private until tenant authentication and object-level
   authorization exist.
2. Require an authenticated owner principal to onboard sellers and bind policies.
3. Require a cryptographically authenticated buyer/agent principal for need,
   negotiation, acceptance, and payment actions.
4. Derive payer/seller ownership server-side; do not authorize it from a request
   wallet string.
5. Leave only explicitly public, redacted receipt endpoints unauthenticated.
6. Add cross-tenant and unauthenticated negative tests for every mutation route.

---

### CR-03 — High — The FastAPI path does not compose the Gemini/OfferRail/live seller lanes and can accept caller-authored fulfillment as seller output

**Evidence**

- `PROJECT-CONTRACT.md:7-20` requires the judged path to include Gemini
  productization, OfferRail-bounded negotiation, Circle payment, seller-agent
  fulfillment, validation, and receipt/revenue update.
- `apps/api/autonomerce/api/adapters.py:243-255` looks for
  `autonomerce.agents.api_adapter` and `autonomerce.sales.api_adapter`; neither
  module exists in the current tree.
- `apps/api/autonomerce/api/adapters.py:257-270` suppresses missing optional lanes
  and substitutes `OfflineProductizer` and `OfflineFulfillmentAdapter`.
- `apps/api/autonomerce/api/schemas.py:147-150` accepts an artifact directly from the
  API caller.
- `apps/api/autonomerce/api/app.py:936-947` forwards that artifact to the selected
  fulfillment adapter.
- `apps/api/autonomerce/api/adapters.py:165-195` returns the supplied artifact in the
  fallback fulfillment adapter; it does not contact the seller agent.
- `apps/api/autonomerce/demo/scenario.py:168-211,245-319,321-400` is a separate
  composition path that explicitly imports and wires the real offline lanes.

**Verified failure scenario**

The production container built and started successfully, but reported:

```text
productizer = OfflineProductizer
payment     = PaymentAdapter(OFFLINE)
fulfillment = OfflineFulfillmentAdapter
```

After a mocked payment, an API caller could submit its own artifact to `/fulfill`;
the API issued a seller fulfillment receipt without invoking a seller agent.

**Impact**

The CLI demo and the FastAPI product are two different systems. The CLI demonstrates
the lane implementations, while the deployable API does not call Gemini, does not
use the OfferRail core for proposal/negotiation/receipts, and does not perform live
seller-agent fulfillment. A judge using the API or web cannot verify the contract's
claimed end-to-end path.

**Action**

1. Implement explicit Gemini productizer and seller-fulfillment API adapters.
2. Make OfferRail the authoritative proposal, policy, transition, idempotency, and
   commercial-receipt implementation used by FastAPI.
3. In non-offline mode, reject caller-supplied seller artifacts and require the
   authenticated seller adapter response.
4. Fail startup when a requested live lane is missing.
5. Add one E2E test that boots the production app configuration and asserts the
   concrete implementation class used at every contract step.

---

### CR-04 — High — API proposal creation and countering permit unbounded scope, SLA, and acceptance-contract changes

**Evidence**

- `apps/api/autonomerce/api/schemas.py:100-128` exposes `offeredOutcome`,
  `deliverySeconds`, and `acceptanceCriteria` on proposal and counter requests.
- `apps/api/autonomerce/api/app.py:343-385` authorizes price, buyer host, opt-in, and
  open-proposal count, but does not authorize outcome, delivery time, or acceptance
  criteria.
- `apps/api/autonomerce/api/app.py:631-657` accepts caller-selected initial terms.
- `apps/api/autonomerce/api/app.py:675-718` replaces outcome, delivery time, and
  acceptance criteria and returns `counter_within_policy`.
- The safer implementations already exist:
  `packages/offerrail/negotiation.py:119-166` preserves scope and required criteria,
  and `apps/api/autonomerce/agents/negotiation.py:141-170` treats scope/term changes
  as hard declines.

**Verified failure scenario**

For a SKU with a 60-second SLA and generated acceptance criteria, the API accepted
this counter:

```text
offeredOutcome     = "Also transfer unrelated customer data"
deliverySeconds    = 999999
acceptanceCriteria = []
```

It returned HTTP 200 and `counter_within_policy`; the proposal could then be accepted
and paid.

**Impact**

A buyer or unauthenticated caller can convert a seller-approved SKU into a paid
contract for unrelated work, remove the evidence required for acceptance, or set an
unbounded delivery obligation. Payment is bound only to the resulting proposal price,
not to an immutable seller-authorized contract.

**Action**

1. Route API proposal creation/counters through the OfferRail/agent invariant code.
2. Make SKU scope and required acceptance criteria immutable within a proposal.
3. Bound delivery changes to explicit seller-authorized limits.
4. Require a new proposal and fresh acceptance for any scope/contract change.
5. Bind a canonical final-contract hash into acceptance, payment intent, fulfillment,
   and receipts.
6. Add adversarial tests for removed criteria, added terms, changed scope, and
   oversized delivery times.

---

### CR-05 — High — The API's shallow schema checker marks invalid paid deliverables as accepted

**Evidence**

- `apps/api/autonomerce/api/app.py:114-157` checks only top-level type, required
  property presence, and immediate property type.
- It ignores common contract constraints including `minLength`, `maxLength`, `enum`,
  `minimum`, `maximum`, nested schemas, array items, and `additionalProperties`.
- `apps/api/autonomerce/api/app.py:959-994` uses this result to set the fulfillment
  receipt's `accepted` flag and the proposal's terminal `DELIVERED`/`FAILED` state.
- `tests/test_api.py:252-284` tests only a missing required field; it does not exercise
  any ignored schema constraint.

**Verified failure scenario**

For this advertised output contract:

```json
{
  "type": "object",
  "required": ["result"],
  "properties": {"result": {"type": "string", "minLength": 5}},
  "additionalProperties": false
}
```

the API accepted:

```json
{"result": "", "extra": "not allowed by schema"}
```

It returned `accepted: true`, `output_schema_valid: true`, and marked the proposal
delivered.

**Impact**

A buyer can pay for a contract, receive an invalid artifact, and still get an
accepted delivery receipt and successful-fulfillment metric. This is a direct
transaction-integrity failure.

**Action**

1. Use one authoritative, standards-compliant JSON Schema validator for SKU creation
   and fulfillment.
2. Validate the SKU schema itself before publishing it.
3. Fail closed on unsupported schema keywords rather than silently ignoring them.
4. Keep natural-language criteria separate and require named deterministic validators
   for each.
5. Add negative tests for nested objects/arrays, enum, lengths, numeric bounds,
   additional properties, malformed schemas, and unknown criteria.

---

### CR-06 — High — Order, proposal, receipt, and metric state is process-local and is not transactionally coordinated with payment state

**Evidence**

- `apps/api/autonomerce/api/app.py:395-405` defaults to a new
  `InMemoryRepository` and process-local asyncio locks.
- `apps/api/autonomerce/api/repository.py:34-56` stores all sellers, policies,
  prospects, proposals, API payment receipts, fulfillments, and metrics in memory.
- `apps/api/autonomerce/api/app.py:414-423` explicitly reports `storage: memory`.
- `apps/api/autonomerce/payments/store.py:291-299` describes the SQLite store as
  suitable for a single API deployment; it is separate from the FastAPI repository.
- `infra/README.md:24-30` configures neither a shared application database nor a
  payment database.

**Failure scenarios**

- A process restart after onboarding loses the seller, policy, SKU, prospect, and
  proposal; the demo cannot continue.
- A process exits after Circle confirms but before `repository.save_payment(...)`.
  The financial store may know about the transfer, but the API has lost or never
  recorded the order state needed for fulfillment and public receipt lookup.
- Two processes/containers have different repositories and locks, so proposal caps,
  duplicate checks, receipt lookup, and metrics can disagree.

**Action**

1. Persist the full commerce aggregate in one shared transactional database.
2. Store seller/policy/SKU/prospect/proposal/payment/fulfillment state and unique
   idempotency constraints together, or coordinate them with an outbox/saga.
3. Add explicit reconciliation for `SUBMITTING` and externally confirmed payments.
4. Add restart, crash-after-transfer, and multi-worker tests.
5. Do not enable live payment until the API can recover an accepted order after a
   process/container loss.

---

### CR-07 — High — Any nonzero Circle CLI response permanently strands the payment, even when the CLI proves no transfer was submitted

**Evidence**

- `apps/api/autonomerce/payments/executors.py:167-176` marks every nonzero Circle CLI
  exit as `terminal=False`.
- `apps/api/autonomerce/payments/service.py:38-53` leaves every such failure in
  `SUBMITTING`.
- `apps/api/autonomerce/payments/service.py:40-42` returns an existing reservation
  without executing again.
- `apps/api/autonomerce/payments/store.py:32-46` permits no recovery transition from
  the terminal/retry states, and there is no reconciliation API/job in the product.

**Verified failure scenario**

A fake Circle CLI returned exit 2 with:

```text
insufficient balance; no transfer submitted
```

The record remained `SUBMITTING`. A retry returned the same `SUBMITTING` receipt and
the executor call count stayed at one.

**Impact**

A routine testnet problem—insufficient funds, wallet policy rejection, invalid CLI
configuration, or a deterministic command error—can permanently block that proposal
and consume policy capacity. The operator cannot safely retry or resolve the order
through the product.

**Action**

1. Parse structured Circle error codes and distinguish proven pre-submit terminal
   rejection from ambiguous post-submit failure.
2. Keep ambiguous results blocked, but add an authenticated reconciliation workflow
   that queries Circle by provider reference/transaction evidence.
3. Permit a safe transition from proven-not-submitted failures back to an authorized
   retry state.
4. Add tests for timeout, malformed output, insufficient funds, policy denial,
   confirmed-but-local-write-failed, and reconciliation outcomes.

---

### CR-08 — Medium — x402 requirement amounts are parsed but discarded when constructing the payment intent

**Evidence**

- `apps/api/autonomerce/payments/x402.py:111-124` parses and validates the x402
  amount.
- `apps/api/autonomerce/payments/x402.py:174-206` stores it in the requirement and
  includes it in the requirement fingerprint.
- `apps/api/autonomerce/payments/x402.py:208-227` calls
  `PaymentIntent.from_proposal(...)` without checking or supplying
  `self.amount_usdc`.
- `apps/api/autonomerce/payments/models.py:229-252` takes the intent amount only from
  the proposal price.

**Verified failure scenario**

An x402 requirement for `0.1` USDC converted to a payment intent for `1` USDC because
the accepted proposal price was `1`.

**Impact**

The client can overpay or underpay relative to the x402 requirement while the local
policy believes the proposal price was correctly paid. This breaks the protocol-to-
payment binding even though the wallet and global caps still apply.

**Action**

1. Reject conversion unless requirement amount exactly equals accepted proposal
   amount.
2. Also bind and compare chain/network, token/asset, scheme, payee, resource URL, and
   requirement identifier.
3. Include the complete requirement fingerprint in the payment intent fingerprint.
4. Add amount-mismatch and conflicting-requirement tests.

---

### CR-09 — High for the contest demo — The web product is a static fixture, not a client of the API or offline demo

**Evidence**

- `apps/web/README.md:5-9,41-48` explicitly says the UI is a local replay, makes no
  network requests, and shows an empty state when demo mode is disabled.
- `apps/web/components/autonomerce-app.tsx:3-24` imports static demo objects and only
  toggles local state.
- `apps/web/components/autonomerce-app.tsx:205-220,238-244` confirms that no live API
  request is made.
- `apps/web/components/onboarding.tsx:17-24,66-294` advances a local step counter;
  submitted seller/policy form values are never sent or retained.
- `apps/web/lib/demo-data.ts:31-255` hard-codes the seller, transaction, six settled
  orders, and revenue chart.
- `apps/web/tests/money.test.ts:18-50` tests money helpers and fixture identifier
  shapes only; there is no API/client/browser workflow test.

**Failure scenario**

A judge changes the agent URL, product, price, or policy in onboarding and clicks
Activate. The UI advances to "Ready to sell" but creates no seller, calls no Gemini
provider, binds no policy, and cannot replay the actual CLI receipt. The displayed
payment/revenue remains the hard-coded fixture.

**Action**

1. Add a typed API client and connect onboarding, order workflow, receipts, and
   metrics to the backend.
2. For a credential-free contest demo, invoke/replay the actual offline demo output
   rather than maintaining a second hand-authored dataset.
3. Display the effective backend mode and `movesFunds` status prominently.
4. Add browser E2E tests that submit onboarding, execute an offline order, and assert
   the rendered IDs/amounts equal backend receipts.

---

### CR-10 — Medium — SSRF/security URL controls are not wired into API ingress

**Evidence**

- `security/controls.py:65-85` defines a public-HTTPS check that rejects literal
  loopback/private/link-local targets.
- `apps/api/autonomerce/api/schemas.py:24-47,85-97` applies only string length/basic
  field constraints to seller and buyer URLs.
- `apps/api/autonomerce/api/app.py:291-295` permits both HTTP and HTTPS buyer URLs and
  checks only that a hostname exists.
- The FastAPI package does not import or call `security.controls`.

**Failure scenario**

The current fallback adapters perform no URL fetch, so there is not yet a complete
SSRF exploit path. Once the missing live Agent Card or seller fulfillment adapter is
added, already-stored URLs such as metadata, loopback, private-network, or
attacker-controlled DNS targets can reach the outbound call boundary unless every
adapter independently revalidates them.

**Action**

1. Validate public HTTPS URLs at API ingress and immediately before each outbound
   request.
2. Resolve every A/AAAA result and reject private, loopback, link-local, reserved,
   multicast, and metadata destinations.
3. Pin the validated destination for the connection and revalidate every redirect to
   prevent DNS rebinding/redirect bypass.
4. Add integration tests at the actual HTTP client boundary, not only unit tests for
   the helper.

---

### CR-11 — Medium — The product has no `.dockerignore`; the normal build context is hundreds of megabytes

**Evidence**

- No product-root `.dockerignore` exists.
- `infra/Dockerfile.api:9-13` needs only the Python metadata, API source, and packages,
  but `docker build ... .` still transfers the whole context before applying `COPY`.
- A build from the complete current-style product tree transferred **432.6 MB**,
  primarily the web `node_modules`/`.next` trees. A lean context containing only
  relevant source was **676.9 kB**.

**Failure scenario**

The contest build spends most of its time uploading irrelevant local artifacts and
can send developer-only files to a remote build service even though they are not
copied into the final image. This increases deployment latency and the chance of
missing a contest-demo window.

**Action**

Add a product-root `.dockerignore` covering at least:

```text
.env
.env.*
.git
.next
node_modules
build
dist
*.egg-info
__pycache__
.pytest_cache
evidence/private
docs/reviews
```

Then add a CI assertion that the build context remains below a reasonable size.

## What passed

All commands were run in isolated copies unless noted so runtime caches/build outputs
would not modify the target implementation.

| Check | Result |
|---|---|
| `./scripts/test_offline.sh` | **112 passed**, 1 FastAPI/Starlette deprecation warning |
| `npm run check` | TypeScript passed; **5 tests passed**; production Next.js build passed |
| `python3 examples/run_offline_demo.py --compact` | Passed; all four lanes available; delivered; simulated; no credentials/network/funds |
| `python3 scripts/scan_public_secrets.py` | Passed |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities reported |
| `python3 tools/lint_claims.py` from repo root | Passed; 92 files scanned |
| `docker build -f infra/Dockerfile.api .` | Passed |
| Built-container `/health` smoke | Passed, but exposed the offline fallback configuration described in CR-01/CR-03 |
| Google/Circle preflight scripts | Correctly blocked with exit 2 because `gcloud`, Circle CLI, project, and owner authentication were unavailable |

## Test coverage gaps that allowed the findings

- No test boots the app with the documented Cloud Run environment and asserts the
  effective adapter modes/caps.
- No authentication, object-authorization, or cross-tenant tests exist.
- API negotiation tests cover a valid price counter only; they do not attack scope,
  SLA, or acceptance criteria.
- API fulfillment tests cover a missing required field only; they do not test the
  rest of the advertised JSON Schema contract.
- No restart/crash/multi-worker idempotency test coordinates the API repository and
  payment store.
- No Circle nonzero-exit or reconciliation test exists.
- No x402 amount-versus-proposal binding test exists.
- Web tests do not exercise onboarding, API integration, or rendered backend receipts.
- The strong OfferRail/agents/sales unit tests do not prove that FastAPI actually uses
  those implementations.

## What I did not review or could not verify

- No live Gemini/Vertex request was made; model authentication, quota, latency, and
  live structured-output compatibility were not exercised.
- No Circle testnet/mainnet transfer was submitted; Circle CLI was unavailable and no
  owner-authenticated wallet session was used.
- No real Cloud Run deployment, IAM policy, autoscaling behavior, revision rollback,
  or managed-database integration was exercised.
- I did not perform a full browser visual/accessibility/performance audit; I reviewed
  the source and ran typecheck/tests/production build.
- I did not run a distributed load test, chaos test, or crash injection against a
  real external payment.
- I did not independently rerun every Bandit/Semgrep/CodeQL item documented in the
  separate `docs/reviews/APPSEC-REVIEW.md`; security findings included here were
  independently checked against source or focused probes.
- I did not review contest legal attestations, KYC, customer-consent validity, or
  whether synthetic evidence is acceptable to the contest.
