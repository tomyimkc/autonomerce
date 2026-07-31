# Autonomerce Application Security Review

**Review date:** 2026-07-31
**Scope:** `/private/tmp/gemini-circle-agentic-payments/projects/autonomerce`
**Review type:** source-assisted threat model, targeted dynamic tests, SAST, dependency audit
**Change policy:** implementation files were not modified

> **Historical baseline, not current-state guidance.** This report records the tree
> reviewed at the time. See `APPSEC-REVIEW-FOLLOWUP.md` for the current status.
> Subsequent work added API authentication/owner scoping, durable commerce and
> payment SQLite state with a same-database live-mode requirement, credential-value
> and suffix detection, Agent Card/request limits, owner/IP rate and concurrency
> limits, public-HTTPS ingestion policy, non-offline docs/trusted-host hardening,
> web owner sessions, a hash-bearing `uv.lock`, and a digest-pinned API base image.
> The original evidence below is retained for audit history and must not be quoted
> as a description of the current tree.

## Executive summary

Autonomerce has several strong payment-lane controls: the bundled live adapter
requires payer/payee allowlists, the Circle subprocess uses `shell=False` and fixed
arguments, returned settlement fields are verified against the authorized intent,
mainnet requires explicit configuration, and the payment stores bind idempotency
keys, proposal IDs, x402 identifiers, and transaction hashes.

The product is **not safe to expose as a live, internet-reachable payment API in its
current form**. The FastAPI composition layer has no authentication or
authorization, yet exposes seller onboarding, policy replacement, self-asserted
buyer opt-in, proposal acceptance, payment initiation, fulfillment, and operational
data. In default offline mode this does not move funds. If the same API is deployed
with the bundled live Circle adapter, an unauthenticated caller can reach the payment
boundary and attempt transactions using owner-configured payer/payee allowlists and
spending caps. The allowlists prevent an arbitrary destination in the bundled
adapter, but they do not authorize *who* may initiate a payment.

The most important fixes are:

1. add mandatory identity, tenant ownership, and role/scope authorization before
   enabling any live adapter;
2. separate private operational data from public receipt projections;
3. make durable, shared idempotency storage an enforced live-mode invariant;
4. bind x402 amount and publication consent to immutable server-side records;
5. apply strict request/card size limits and integrate the existing consent,
   anti-spam, and SSRF controls into the API path.

## Severity and confidence

- **High:** practical compromise of confidentiality, integrity, or live payment
  authorization under realistic deployment conditions.
- **Medium:** exploitable integrity/availability/privacy weakness with narrower
  preconditions, or a live-payment safety invariant that can be misconfigured.
- **Low:** hardening or supply-chain weakness with no demonstrated remote exploit.
- **Defense-in-depth / unverified:** the unsafe condition is present, but the current
  product does not contain the network/tool sink needed to demonstrate exploitation.

“Confirmed” means the behavior was reproduced locally or is directly reachable in
the reviewed code. It does not mean a real Circle transaction or production
deployment was exercised.

## Prioritized confirmed findings

### A-01 — No authentication or object-level authorization on payment-capable API

**Severity:** High; potentially critical if exposed with live Circle credentials and
an attacker-controlled or compromised allowlisted payee
**Confidence:** Confirmed for missing authorization and payment-boundary reachability;
real-fund impact is conditional on live deployment and configured wallet policy
**STRIDE:** Spoofing, Tampering, Repudiation, Elevation of privilege

**Evidence**

- `apps/api/autonomerce/api/app.py:388-405` creates the application and shared locks
  without any authentication dependency or authorization middleware.
- `apps/api/autonomerce/api/app.py:425-451` lets any caller create a seller and choose
  its wallet address.
- `apps/api/autonomerce/api/app.py:519-549` lets any caller replace a seller's
  commercial policy.
- `apps/api/autonomerce/api/app.py:551-578` accepts a caller's own `optedIn: true`
  assertion.
- `apps/api/autonomerce/api/app.py:585-662` lets any caller create proposals.
- `apps/api/autonomerce/api/app.py:720-789` lets any caller accept, decline, or
  counter proposals.
- `apps/api/autonomerce/api/app.py:791-907` reaches the configured payment adapter.
- `apps/api/autonomerce/api/app.py:909-995` reaches fulfillment and returns artifacts.
- `infra/Dockerfile.api:17` binds Uvicorn to `0.0.0.0`.

**Reproduction**

A credential-free `TestClient` flow successfully created a seller, capability, SKU,
policy, prospect, proposal, acceptance, payment, and fulfillment. Statuses were:

```text
[201, 201, 200, 201, 201, 201, 200, 200, 200]
```

No request supplied an authentication header or session.

**Exploit scenario**

If an operator enables the live testnet/mainnet payment adapter behind this API, an
external caller can:

1. enumerate or create commercial objects;
2. replace a seller policy with permissive price, capacity, chain, and unattended
   settings;
3. self-assert an opted-in buyer;
4. create and accept a proposal;
5. call `/proposals/{id}/pay` with a known allowlisted payer address.

The bundled payment adapter still enforces its environment-configured payer/payee
allowlists and caps, so this review did **not** confirm a bypass to an arbitrary
destination. It did confirm that wallet policy is being used as a substitute for
caller authorization. An attacker could cause unwanted transfers to an allowlisted
seller, exhaust transaction/count/total limits, create reconciliation incidents, or
drain funds if an attacker-controlled destination is ever allowlisted.

**Exact remediation**

1. Fail startup for `testnet` or `mainnet` payment mode unless an authentication and
   authorization provider is configured.
2. Authenticate machine callers with short-lived OIDC/JWT credentials, mTLS, or
   signed service requests. Do not use an idempotency key or wallet address as
   authentication.
3. Add tenant ownership to every seller, capability, SKU, policy, prospect,
   proposal, payment, fulfillment, and receipt.
4. Enforce explicit scopes:
   - owner/admin: create sellers and bind payment/commercial policy;
   - buyer identity: counter/accept only proposals addressed to that buyer;
   - internal payment worker: call the live payment adapter;
   - seller worker: submit fulfillment only for its own paid proposal;
   - public: access only explicitly published receipt projections.
5. Move live payment execution to an internal queue/worker that is not directly
   internet-addressable.
6. Add immutable audit records containing authenticated subject, tenant, action,
   policy version, proposal version, request ID, and result.
7. Add regression tests proving unauthenticated and cross-tenant calls return
   `401/403` and never invoke the payment or fulfillment adapter.

---

### A-02 — Private buyer data and complete fulfillment artifacts are globally exposed

**Severity:** High when the API is reachable outside a trusted single-user process
**Confidence:** Confirmed
**STRIDE:** Information disclosure

**Evidence**

- `apps/api/autonomerce/api/app.py:225-235` includes buyer agent URL and desired
  outcome in prospect responses.
- `apps/api/autonomerce/api/app.py:238-253` includes buyer/seller URLs,
  `problemObserved`, offered outcome, and contract terms in proposal responses.
- `apps/api/autonomerce/api/app.py:580-583` lists every prospect without access
  control.
- `apps/api/autonomerce/api/app.py:664-673` lists every proposal without access
  control.
- `apps/api/autonomerce/api/app.py:265-281` can include the complete artifact.
- `apps/api/autonomerce/api/app.py:923-924` returns an existing fulfillment with
  `include_artifact=True`.
- `apps/api/autonomerce/api/app.py:995` returns a newly produced fulfillment with
  `include_artifact=True`.
- `apps/api/autonomerce/api/app.py:997-1042` exposes receipt data without checking a
  publication authorization record.

**Reproduction**

An unauthenticated caller listed all prospects and proposals, then received this
private artifact field from the fulfillment endpoint:

```json
{"sessionToken": "seller-secret"}
```

The public receipt projection omitted the artifact, but that does not protect the
separate operational endpoints.

**Exploit scenario**

An attacker enumerates proposal IDs from `/proposals`, calls
`/proposals/{proposal_id}/fulfill`, and receives an existing artifact. This can
expose customer inputs, generated deliverables, proprietary work, personal data, or
credentials accidentally returned by a seller agent.

**Exact remediation**

1. Apply the tenant/role controls from A-01 to all list, receipt, and fulfillment
   routes.
2. Never return a full artifact from a state-changing fulfillment endpoint. Return
   only an artifact ID, hash, media type, size, and acceptance result.
3. Store artifacts in a private object store using tenant-scoped encryption and
   short-lived, authenticated download grants.
4. Make `/receipts/{id}` return `404` unless the receipt has a durable,
   owner-authorized publication record.
5. Separate internal and public schemas at the type level; do not use an
   `include_artifact` boolean on a shared serializer.
6. Add tests proving tenant A cannot list, retrieve, fulfill, or publish tenant B's
   objects and that public receipt responses never contain prompts or artifacts.

---

### A-03 — Secret-field rejection is bypassed by common camelCase keys

**Severity:** Medium; combines with A-02 for high confidentiality impact
**Confidence:** Confirmed
**STRIDE:** Information disclosure

**Evidence**

- `apps/api/autonomerce/api/app.py:54-72` defines exact underscore-form secret keys.
- `apps/api/autonomerce/api/app.py:160-172` lowercases and replaces hyphens, but does
  not remove case boundaries or all non-alphanumeric separators. For example,
  `sessionToken` becomes `sessiontoken`, which is not in `_SECRET_KEYS`.
- `apps/api/autonomerce/api/app.py:426-440` stores seller manifests after this
  incomplete check.
- `apps/api/autonomerce/api/app.py:551-575` stores buyer payloads after the same
  incomplete check.
- `apps/api/autonomerce/api/app.py:953-983` stores seller artifacts without applying
  the stronger recursive redaction helpers.
- `security/controls.py:16-46`,
  `apps/api/autonomerce/payments/redaction.py:14-45`, and
  `packages/offerrail/receipts.py:87-137` contain stronger normalization/redaction
  logic, but the API path does not consistently use it.

**Reproduction**

The API accepted and stored:

```json
{"manifest": {"sessionToken": "seller-secret"}}
```

It also accepted and echoed:

```json
{"artifact": {"verdict": "ok", "sessionToken": "seller-secret"}}
```

Likewise, `accessToken` was accepted in a buyer `inputPayload`.

**Exploit scenario**

A seller agent, imported manifest, or customer payload includes `accessToken`,
`sessionToken`, `privateKey`, `clientSecret`, or another camelCase variant. The API
stores it as normal data and may return it through operational endpoints or include
it in later logs/debugging.

**Exact remediation**

1. Replace the API-local exact set with one central redaction/rejection function.
2. Normalize keys by retaining only lowercase alphanumeric characters, then match
   exact sensitive names and suffixes such as `accesstoken`, `sessiontoken`,
   `refreshtoken`, `privatekey`, and `clientsecret`.
3. Apply the control to:
   - inbound manifests, schemas, buyer payloads, and artifacts;
   - adapter output before storage;
   - exception/log fields;
   - every public and internal serializer.
4. Treat redaction as a backstop, not as authorization. Avoid accepting credentials
   in these payload classes at all.
5. Add parameterized regression tests for snake_case, kebab-case, camelCase,
   PascalCase, mixed separators, nested arrays/maps, bearer/basic authorization
   values, PEM private keys, and secret-bearing URLs.

---

### A-04 — The API bypasses the stricter contract-safe proposal/negotiation path

**Severity:** Medium
**Confidence:** Confirmed
**STRIDE:** Tampering

**Evidence**

- `apps/api/autonomerce/api/schemas.py:100-128` lets requesters supply
  `offeredOutcome`, delivery time, and acceptance criteria.
- `apps/api/autonomerce/api/app.py:623-657` authorizes price/host/capacity but then
  accepts caller-provided outcome, delivery time, and criteria.
- `apps/api/autonomerce/api/app.py:675-712` lets a counter replace
  `offered_outcome`, `delivery_seconds`, and `acceptance_criteria`.
- `apps/api/autonomerce/agents/proposals.py:143-154` is safer: it binds outcome,
  price, delivery time, and acceptance criteria to the published SKU.
- `apps/api/autonomerce/agents/negotiation.py:141-156` treats scope changes and
  unbounded terms as hard declines.

**Exploit scenario**

A buyer or unauthenticated caller changes a proposal's promised outcome, delivery
deadline, or acceptance contract while keeping the price within bounds. The payment
flow checks accepted state and price but does not require an immutable hash of the
seller-authorized SKU contract. This can produce a paid contract that neither party
actually authorized, poison fulfillment metrics, or force an impossible delivery.

**Exact remediation**

1. Route API proposal creation and counters through the same deterministic
   `ProposalWriter` and `NegotiationRecommender` invariants.
2. Make SKU outcome and acceptance criteria immutable for a proposal revision.
3. Permit buyer counters only for explicitly negotiable fields and bounded values.
4. Require a new proposal and fresh acceptance if scope or acceptance terms change.
5. Hash the final canonical contract and bind that hash into acceptance, payment
   intent, receipt, and fulfillment validation.
6. Add tests proving a counter cannot remove/add criteria, change scope, or set a
   delivery time below the seller-authorized minimum.

---

### A-05 — Live `PaymentAdapter` accepts a volatile in-memory idempotency store

**Severity:** Medium; high if used for mainnet or in a restart-prone/multi-replica
deployment
**Confidence:** Confirmed
**STRIDE:** Tampering, Repudiation

**Evidence**

- `apps/api/autonomerce/payments/api_adapter.py:76-85` checks only that a store was
  supplied for live mode; it does not verify durability.
- `apps/api/autonomerce/payments/api_adapter.py:86` accepts any `PaymentStore`,
  including `InMemoryPaymentStore`.
- `apps/api/autonomerce/payments/api_adapter.py:176-181` uses SQLite in the
  environment factory, but direct construction can bypass that safe default.
- `apps/api/autonomerce/payments/store.py:156-165` confirms that
  `InMemoryPaymentStore` is process-local.
- `apps/api/autonomerce/payments/store.py:291-299` describes SQLite as suitable for a
  single API deployment, not a distributed deployment.

**Reproduction**

The following live configuration was accepted:

```text
LIVE_MODE_ACCEPTS_VOLATILE_STORE testnet InMemoryPaymentStore
```

No payment was executed for this test.

**Exploit/failure scenario**

A caller constructs a live adapter with `InMemoryPaymentStore`, or deploys separate
SQLite files per container. After a process restart or on another replica, the
idempotency key, proposal binding, cumulative spend, x402 ID, and transaction-hash
reservations are absent. The same accepted proposal can be submitted again and the
Circle CLI has no transfer-idempotency argument to stop a second transfer.

**Exact remediation**

1. Add an explicit store capability such as
   `durability = PROCESS | SINGLE_NODE | DISTRIBUTED` and reject live mode unless it
   meets the deployment's required level.
2. Make the volatile store test-only and impossible to pass to a live adapter.
3. For internet/live deployment, use a shared transactional database with unique
   constraints on idempotency key, proposal ID, x402 requirement ID, payment ID, and
   transaction hash.
4. Reserve and transition within one authoritative database transaction and use
   row-level locking or serializable semantics.
5. Add restart and multi-worker regression tests demonstrating that the executor is
   called exactly once.
6. Add a reconciliation state/job for ambiguous `SUBMITTING` records; never solve
   ambiguity by automatic resubmission.

---

### A-06 — Parsed x402 amount is discarded when creating the payment intent

**Severity:** Medium
**Confidence:** Confirmed
**STRIDE:** Tampering

**Evidence**

- `apps/api/autonomerce/payments/x402.py:111-124` parses and validates the x402
  amount.
- `apps/api/autonomerce/payments/x402.py:174-206` includes the amount in the
  requirement object and fingerprint.
- `apps/api/autonomerce/payments/x402.py:208-227` calls
  `PaymentIntent.from_proposal(...)` without comparing or passing
  `self.amount_usdc`.
- `apps/api/autonomerce/payments/models.py:229-252` derives the intent amount only
  from the proposal price.

**Reproduction**

An x402 requirement for `0.1` USDC converted into an intent for a proposal priced at
`1` USDC:

```text
X402_AMOUNT_DROPPED 0.1 1
```

**Exploit scenario**

A resource advertises one x402 amount while the accepted proposal contains another.
The client can overpay relative to the resource requirement or underpay while
believing the x402 requirement was satisfied. The proposal cap and payee allowlist
still apply, so this is not an arbitrary over-cap transfer, but it breaks the
protocol/payment binding.

**Exact remediation**

1. Reject conversion unless `requirement.amount_usdc == proposal.price_usdc`.
2. Also require exact agreement for chain/network, token/asset, scheme, payee,
   resource, and the expected proposal/payment identifier.
3. Bind the complete x402 requirement fingerprint into `PaymentIntent.fingerprint`.
4. Reject conflicting identifier aliases rather than selecting the first of
   `paymentIdentifier`, `payment_id`, and `idempotencyKey`.
5. Require and replay-protect an x402 identifier in live x402 mode.
6. Add tests for amount mismatch, conflicting aliases, option selection, token/asset
   mismatch, and resource-host mismatch.

---

### A-07 — Receipt publication can be changed on an idempotent payment replay

**Severity:** Medium
**Confidence:** Confirmed in the reusable payment adapter; mitigated by the
process-local API repository during a same-process replay
**STRIDE:** Information disclosure, Tampering

**Evidence**

- `apps/api/autonomerce/payments/store.py:89-99` creates the stored receipt with the
  default `public=False`.
- `apps/api/autonomerce/payments/models.py:254-273` does not include publication
  consent in the payment fingerprint.
- `apps/api/autonomerce/payments/api_adapter.py:136-143` obtains the idempotent
  receipt and then replaces its `public` flag using the current caller's request.
- `apps/api/autonomerce/api/app.py:799-813` prevents this specific toggle for a
  same-process API replay by returning the repository copy first, but the adapter
  itself remains mutable and the repository is not durable.

**Reproduction**

The same payment intent and idempotency key were requested twice:

```text
PUBLIC_FLAG_MUTABLE_ON_IDEMPOTENT_REPLAY False True 1
```

The executor ran once, but the second response exposed a `public=True` receipt.

**Exploit scenario**

A private payment is replayed through the adapter with `public=True`. No second
payment occurs, but payer/payee wallet fields become eligible for the public
projection without a durable owner publication decision.

**Exact remediation**

1. Remove `public` from the payment execution call.
2. Keep payment records private and immutable.
3. Implement a separate authenticated publication action that stores who approved
   publication, when, which exact fields, and the consent/version reference.
4. Make public receipt lookup depend on that durable publication record.
5. Add tests proving payment retries cannot change privacy fields and publication
   requires the authorized owner/tenant.

---

### A-08 — Agent Card mappings and API payloads lack effective size/depth limits

**Severity:** Medium when internet reachable
**Confidence:** Confirmed
**STRIDE:** Denial of service

**Evidence**

- `apps/api/autonomerce/sales/agent_cards.py:17-18` defines a 256 KiB card limit.
- `apps/api/autonomerce/sales/agent_cards.py:228-240` applies the limit only to JSON
  strings/bytes; an already-decoded mapping returns before the size check.
- `apps/api/autonomerce/sales/agent_cards.py:25-41` and `157-225` do not cap string
  lengths, tags/examples counts, nested capability size, or depth.
- `apps/api/autonomerce/api/schemas.py:24-149` leaves manifest, schemas,
  descriptions, tags, buyer payloads, acceptance results, and artifacts largely
  unbounded.
- `apps/api/autonomerce/api/app.py:397-405` installs no request-size, concurrency, or
  rate-limit middleware.

**Reproduction**

An already-decoded Agent Card with a 262,145-character description was accepted,
while the equivalent serialized card was rejected:

```text
AGENT_CARD_MAPPING_BYPASSES_BYTE_LIMIT 262145 True
```

**Exploit scenario**

An unauthenticated caller sends very large or deeply nested manifests, schemas,
buyer payloads, artifacts, or repeated proposals. Parsing, deep copies, recursive
secret checks, JSON hashing, repository storage, and response serialization consume
CPU and memory until the process is unavailable.

**Exact remediation**

1. Enforce request-body limits at the load balancer/reverse proxy and again in ASGI
   middleware before JSON parsing.
2. Canonically serialize mapping inputs and enforce the same byte limit as raw JSON.
3. Add strict maximum lengths and counts to every string/list/map field.
4. Reject excessive JSON nesting and schema complexity.
5. Limit artifact bytes before copying, hashing, validation, or storage.
6. Add per-identity/IP concurrency and rate limits with smaller limits on expensive
   Gemini, payment, and fulfillment operations.
7. Add boundary tests for exact limit, limit + 1, deep nesting, list explosion, and
   decompression/proxy behavior.

## Defense-in-depth and unverified findings

### D-01 — Consent and anti-spam controls are not integrated into the API path

**Priority:** Medium before enabling outbound delivery
**Status:** Confirmed control gap; external spam exploit is unverified because the
reviewed API does not send proposals over the network

**Evidence**

- `apps/api/autonomerce/api/schemas.py:85-98` models consent as a caller-controlled
  boolean without a consent reference.
- `apps/api/autonomerce/api/app.py:551-578` treats `optedIn: true` as sufficient.
- `apps/api/autonomerce/sales/prospects.py:91-127` has a stronger registry requiring
  an auditable `consent_reference`, but the API repository does not use it.
- `apps/api/autonomerce/sales/pitching.py:59-78` and `199-236` implement duplicate,
  global, prospect, host, and cooldown limits, but `/proposals` does not use this
  workflow.
- The reproduced API accepted a self-asserted prospect on
  `https://169.254.169.254/...`.

**Risk**

Today this permits fake consent records, policy bypass, proposal/database spam, and
misleading opt-in metrics. If a network sender is later attached to proposal
creation, it becomes an autonomous unsolicited-contact mechanism.

**Recommended fix**

Require verifiable consent records with issuer, subject/agent identity, permitted
topics, issued/expiry/revocation times, and evidence reference. Use the same
`OptedInProspectRegistry` and `PitchWorkflow` in the API. Keep send rate state
durable and shared across replicas. Add an emergency global disable switch and
per-tenant budget.

---

### D-02 — SSRF protections exist but are not wired to Agent Card/API URLs

**Priority:** Medium before adding any URL fetcher
**Status:** Defense-in-depth; no current SSRF sink was found

**Evidence**

- `security/THREAT-MODEL.md:33` claims HTTPS, DNS/IP, private/link-local, and metadata
  protections.
- `apps/api/autonomerce/sales/agent_cards.py:44-57` permits HTTPS URLs whose host is
  `127.0.0.1`, link-local, private, or metadata.
- `apps/api/autonomerce/api/app.py:291-295` validates only scheme and hostname for
  buyer URLs.
- `apps/api/autonomerce/api/app.py:425-440` does not validate the seller URL before
  storing it.
- `security/controls.py:65-85` has a stricter literal-host helper, but it is not used
  by these paths and does not itself resolve DNS or prevent DNS rebinding.
- The parser accepted `https://127.0.0.1/private` even though the security helper
  classified it as non-public.

**Why this is not asserted as exploitable**

The Agent Card parser explicitly performs no network access, the pitching workflow
only creates local state, and no reviewed adapter fetched the stored URLs. Therefore
this review did not reproduce a request to metadata or an internal service.

**Recommended fix**

Before introducing fetches, create one centralized egress client that requires
HTTPS, rejects credentials/fragments and non-approved ports, resolves every A/AAAA
record, rejects private/loopback/link-local/reserved/multicast/metadata ranges, pins
the selected address for the request, revalidates every redirect, caps response
size/time, validates content type, and runs behind an outbound firewall. Prefer
owner allowlists over arbitrary remote URLs.

---

### D-03 — Prompt injection can poison model-generated SKU text and criteria

**Priority:** Medium defense-in-depth
**Status:** Dataflow confirmed; actual Gemini prompt-following behavior was not
tested and no direct tool/payment escalation was found

**Evidence**

- `apps/api/autonomerce/agents/providers.py:229-253` serializes the complete
  untrusted decision payload as model contents.
- `apps/api/autonomerce/agents/productizer.py:129-148` includes capability/Agent Card
  name, description, schemas, URL, and tags.
- `apps/api/autonomerce/agents/productizer.py:159-219` accepts model-generated SKU
  name, outcome, and arbitrary acceptance criteria. Price, latency, and capacity are
  clamped, and required deterministic criteria are appended.
- `apps/api/autonomerce/agents/proposals.py:143-154` correctly prevents proposal prose
  from changing a published SKU, but a poisoned productization result has already
  become the published SKU.
- Negotiation and delivery paths keep model advice out of payment authorization and
  deterministic acceptance, which materially limits impact.

**Risk**

A malicious Agent Card can instruct the model to create misleading scope, unsafe
display text, or impossible/adversarial criteria. This is primarily contract
poisoning and availability/reputation risk; the review found no model tool access,
shell execution, direct wallet authority, or ability to override deterministic
payment limits.

**Recommended fix**

Treat the model as a copy/relevance recommender only. Derive scope, schemas, and
criterion IDs from an owner-approved canonical manifest. Allow only registered
criterion IDs with deterministic validators. Label untrusted fields in the prompt,
use prompt-injection evaluation fixtures, reject outputs that introduce unsupported
instructions/URLs/criteria, and require owner review before publishing a materially
new SKU.

---

### D-04 — Circle subprocess is injection-resistant, but executable provenance and output handling can be hardened

**Priority:** Low
**Status:** Defense-in-depth; no command injection found

**Evidence**

- `apps/api/autonomerce/payments/executors.py:118-147` restricts the executable to one
  argv token and builds a fixed argument list.
- `apps/api/autonomerce/payments/executors.py:149-159` invokes the runner with
  `shell=False`, timeout, and captured output.
- `apps/api/autonomerce/payments/models.py:96-130` strictly validates wallet
  addresses and idempotency keys.
- `apps/api/autonomerce/payments/executors.py:191-227` verifies returned state, chain,
  payer, payee, amount, and transaction hash.
- The executable defaults to the PATH-resolved string `circle`; it is not pinned to
  an absolute path or verified by digest/signature.
- `apps/api/autonomerce/payments/redaction.py:20-29` redacts bearer tokens and several
  assignment forms but may miss arbitrary provider-specific or camelCase secret
  formats in CLI stderr.

**Recommended fix**

Use an owner-configured absolute executable path, a minimal sanitized environment,
known working directory, output byte cap, and version/digest allowlist. Do not retain
raw CLI output longer than verification requires. Expand log redaction and ensure
API responses never include CLI stderr. Consider a typed Circle API/client with
provider-supported idempotency if available.

---

### D-05 — Public web/API hardening headers and deployment boundaries are incomplete

**Priority:** Low now; higher when the web UI becomes dynamic
**Status:** Defense-in-depth

**Evidence**

- `apps/web/next.config.ts:3-6` configures no Content Security Policy,
  frame-ancestors/X-Frame-Options, Referrer-Policy, Permissions-Policy, or
  nosniff header.
- The reviewed web UI is a deterministic local fixture, makes no API/wallet calls,
  and no `dangerouslySetInnerHTML` sink was found.
- The API publishes OpenAPI documentation by default and binds externally in the
  container.
- No permissive CORS middleware was found. This is positive, but CORS is not
  authentication and does not stop direct non-browser clients.

**Recommended fix**

Place the API behind an authenticated gateway, disable or protect interactive API
docs in production, set strict security headers, define trusted hosts, terminate TLS
at a controlled proxy, and keep the static demo origin separate from the
payment-capable API origin. Reassess CSP/XSS/CSRF when the UI begins consuming live
data.

---

### D-06 — Python production dependencies and base image are not reproducibly pinned

**Priority:** Low
**Status:** Confirmed supply-chain/reproducibility weakness; no known advisory was
found in the resolved audit

**Evidence**

- `pyproject.toml:13-16` uses lower-bound-only optional dependency ranges.
- `infra/Dockerfile.api:1` uses a mutable image tag rather than an image digest.
- `infra/Dockerfile.api:13` resolves and installs floating dependency versions at
  build time.
- `apps/web/package-lock.json` exists and was auditable.

**Recommended fix**

Generate a reviewed production lock/constraints file with hashes, install from that
file, pin the base image by digest, produce an SBOM and provenance attestation, and
run dependency/secret/container scans in CI. Pin and verify the Circle CLI
distribution as part of the same supply-chain policy.

## Controls reviewed with no confirmed bypass

### Arbitrary wallet destination

No bypass was confirmed in the bundled live adapter:

- `apps/api/autonomerce/payments/api_adapter.py:76-85` requires non-empty payer and
  payee allowlists in live mode.
- `apps/api/autonomerce/payments/api_adapter.py:112-135` constructs payment policy
  from those owner-configured allowlists rather than caller-provided allowlists.
- `apps/api/autonomerce/payments/policy.py:95-112` denies non-allowlisted payer/payee
  and self-payment.
- `apps/api/autonomerce/payments/executors.py:220-227` checks the CLI-confirmed source,
  destination, and amount against the intent.
- `apps/api/autonomerce/api/app.py:866-900` binds the payee to the seller record and
  checks the returned receipt.

Remaining concern: the unauthenticated API controls which commercial action reaches
that destination, and `SellerCreate` accepts an arbitrary wallet before the live
adapter denies it. Keep the destination allowlist and add caller authorization; do
not replace one with the other.

### Mainnet opt-in

The reviewed software guard is present:

- `apps/api/autonomerce/payments/api_adapter.py:182-203` requires mainnet mode plus
  the exact confirmation value before constructing an enabled policy/executor.
- `apps/api/autonomerce/payments/executors.py:108-117` rechecks explicit mainnet
  enablement.
- `apps/api/autonomerce/payments/executors.py:127-133` rejects testnet/mainnet chain
  mismatch.

A targeted test confirmed that mainnet construction without opt-in fails. This does
not replace owner authentication, durable idempotency, wallet-side policy, low
operating balances, and deployment isolation.

### Idempotency and replay

Within one authoritative store, the controls are strong:

- payment intent fingerprint covers proposal, amount, chain, token/asset, payer,
  payee, scheme, x402 ID, and resource URL;
- stores reject conflicting idempotency keys, duplicate proposal IDs, replayed x402
  IDs, duplicate payment IDs, and reused transaction hashes;
- ambiguous execution remains `SUBMITTING` and is not automatically retried;
- SQLite uses parameterized values and transactional reservation.

No logical same-store duplicate-settlement bypass was found. A-05 is the material
gap: durability/shared-state is documented but not enforced for every live
construction/deployment.

### Circle CLI command injection

No command injection was reproduced. Wallets, amounts, chains, and tokens cannot
become shell syntax because the command uses `shell=False`, a fixed argv shape, and
strict value normalization. The Bandit subprocess alert was triaged as a false
positive for remote command injection, with the executable-provenance hardening in
D-04 still recommended.

### Public receipt projection

The receipt projection omits customer artifacts, buyer URL, buyer prompt, and
idempotency key, and only includes wallet addresses when the receipt is marked
public. The remaining issues are not a recursive-redaction bypass in that projection;
they are:

- unauthenticated access to private operational endpoints and minimal receipts
  (A-02);
- incomplete secret handling outside the receipt projection (A-03);
- mutable publication state on adapter replay (A-07).

## STRIDE trust-boundary summary

| Boundary | Primary STRIDE risks | Review result |
|---|---|---|
| Internet/client → FastAPI | Spoofing, tampering, repudiation, disclosure, DoS, elevation | **Failed:** no authentication, tenant ownership, role checks, body limits, or rate limits |
| Agent Card/buyer payload → Gemini | Tampering via prompt injection, disclosure | Model has no direct tool/payment authority, but productization text/criteria can be poisoned |
| API/model → commercial policy | Tampering, elevation | Price/host/capacity gates exist, but API can overwrite policy and bypass safer scope/criteria negotiation |
| API → payment adapter/store | Spoofing, replay, repudiation | Strong wallet/amount/replay controls; caller authorization and enforced durability are missing |
| Payment adapter → Circle CLI/session | Command injection, spoofed result, secret leakage | Fixed argv and strict result verification are strong; executable provenance/log handling need hardening |
| x402 header → payment intent | Tampering, replay, SSRF precursor | Strict parser basics; requirement amount is not bound to proposal amount |
| Seller output → fulfillment/storage | Injection, disclosure, DoS | No code execution found; artifacts are unbounded, insufficiently secret-filtered, and returned through unauthenticated API |
| Operational record → public receipt/web | Disclosure, tampering | Public projection is narrow; publication authorization and API isolation are incomplete |

## Tooling and test evidence

### Tests

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

Result:

```text
112 passed, 1 warning
```

The existing tests validate many intended controls, but they also explicitly assume
credential-free access to the complete API flow. Passing tests therefore do not
contradict A-01.

### Targeted dynamic checks

Confirmed:

- complete API mutation/payment/fulfillment flow with no credentials;
- self-asserted opt-in for a private/link-local-style URL;
- camelCase secret fields accepted and artifact secret echoed;
- public=false payment still has an unauthenticated minimal receipt containing a
  transaction hash;
- Agent Card mapping bypass of the serialized byte limit;
- private HTTPS Agent Card URL accepted;
- x402 amount dropped during intent conversion;
- payment publication flag changed on idempotent replay while executor call count
  remained one;
- live adapter accepted an in-memory store;
- mainnet executor rejected construction without explicit opt-in.

No real network request, Gemini call, Circle CLI call, or fund movement was
performed.

### Bandit

Bandit scanned 9,305 lines and reported 11 alerts:

- nine hardcoded-password alerts on the token symbol `USDC`: false positives;
- one subprocess-import alert: false positive for command injection because the
  reviewed call uses `shell=False`, fixed argv, and validated values;
- one SQL-string-construction alert: false positive because the interpolated
  placeholders are derived from a static enum set and all values are parameterized.

### Semgrep

Semgrep OSS ran 200 Python/security rules over 51 source files and reported zero
findings. It emitted four fixpoint-timeout warnings, so this is not complete proof
of absence.

### CodeQL

The CodeQL CLI/database was not available in this checkout. **ABSTAIN:** no CodeQL
result can be asserted without a configured database and query suite.

### Dependency and secret audits

- `npm audit` reviewed the lockfile graph (89 dependencies) and reported zero known
  vulnerabilities.
- `pip-audit` resolved the declared API/Gemini requirements and reported zero known
  vulnerabilities in the resolved set.
- The Python result is not a reproducible deployed-version guarantee because the
  project has no production lock and the Docker build resolves floating ranges.
- `scripts/scan_public_secrets.py` passed.

## Release recommendation

**Internet-facing offline demo:** Conditional. Keep it isolated from credentials and
wallet sessions, add body/rate limits, and clearly label all payments as simulated.

**Live testnet:** No-go until A-01, A-02, A-03, A-05, and A-08 are fixed and covered
by regression tests.

**Mainnet:** No-go. In addition to the live-testnet blockers, require a shared
durable store, authenticated internal payment worker, wallet-side destination and
spend policy, low operating balance, reconciliation procedure, deployment-level
egress controls, publication consent, and an independent review of the final
Circle/x402 integration.
