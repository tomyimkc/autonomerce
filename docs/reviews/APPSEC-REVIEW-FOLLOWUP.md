# Autonomerce Application Security Follow-up

**Review date:** 2026-07-31
**Prior review:** `docs/reviews/APPSEC-REVIEW.md`
**Scope:** current tree at `/private/tmp/gemini-circle-agentic-payments/projects/autonomerce`
**Current-state refresh:** 2026-07-31; this documentation pass did not modify
application or test source

## Executive result

The remediation materially improves the product. Authentication and single-owner
object scoping now protect private API routes; artifacts are reduced to hashes and
metadata; proposal scope and acceptance terms are server-bound; live payment and
commerce state must be durable; x402 requirements are fully bound; publication is a
separate durable owner action; and live seller execution fails closed behind an
explicit executor.

The prior live-payment authorization path is no longer reproducible. However, the
review is **not fully closed**:

- consent remains a self-asserted reference rather than a verified consent record;
- model-driven SKU productization remains prompt-injection-sensitive;
- Circle executable provenance/output handling remains incomplete; and
- SBOM/provenance and fresh dependency/container advisory evidence remain absent.

**Status count:** 10 CLOSED, 3 PARTIAL, 1 OPEN.

## Prior findings status

| ID | Severity | Status | Current conclusion |
|---|---:|---|---|
| A-01 | High | **CLOSED** | Private routes require bearer authentication when configured, objects carry an owner, cross-owner access is rejected, and non-offline startup requires authentication plus durable storage. |
| A-02 | High | **CLOSED** | Private operational routes are authenticated/owner-scoped; fulfillment responses and durable records contain artifact hash/metadata, not the artifact; public receipt lookup requires a durable publication record. |
| A-03 | Medium | **CLOSED** | Central input/output credential detection covers normalized suffix variants plus bearer/basic/PEM values and credentialized URLs; focused regression tests cover the previously accepted names. |
| A-04 | Medium | **CLOSED** | Proposal scope, criteria, and delivery are bound to the SKU; counters may change price only; a canonical contract hash is checked before payment. |
| A-05 | Medium | **CLOSED** | Live `PaymentAdapter` rejects process-local stores; deployment preflight restricts live mode to one worker and marked persistent single-host SQLite storage. |
| A-06 | Medium | **CLOSED** | x402 amount, chain, token, asset, payee, resource, identifier, scheme, and full requirement fingerprint are bound into the payment intent. |
| A-07 | Medium | **CLOSED** | Payment replay cannot change `public`; publication is a separate authenticated, owner-scoped, immutable repository action. |
| A-08 | Medium | **CLOSED** | Mapping and serialized Agent Cards share byte/depth/node/string/list limits; middleware enforces owner/IP rate and concurrency budgets with stricter Gemini, payment, and fulfillment classes and deterministic `429` responses. |
| D-01 | Medium | **PARTIAL** | `consentReference` and open-proposal/capacity controls are now required, but the API still accepts an owner-supplied opaque consent reference and does not use durable per-prospect/host cooldown state. |
| D-02 | Medium defense-in-depth | **CLOSED** | Seller/buyer/capability URL ingestion requires public HTTPS in non-offline mode and permits only explicit loopback/reserved fixtures offline; credentials, private/link-local/metadata targets, fragments, and malformed hosts are rejected. |
| D-03 | Medium defense-in-depth | **OPEN** | Untrusted capability/Card text still reaches Gemini productization and model-generated SKU text/criteria can still become the stored SKU. |
| D-04 | Low | **PARTIAL** | Fixed argv, `shell=False`, and exact response verification remain strong; executable digest/absolute-path enforcement, sanitized environment, and hard subprocess output caps remain absent. |
| D-05 | Low | **CLOSED** | Non-offline FastAPI disables OpenAPI/Swagger/ReDoc, requires explicit non-wildcard trusted hosts, and emits API security headers; the web retains its own header boundary. |
| D-06 | Low | **PARTIAL** | The API base is digest-pinned and `uv.lock` is installed with `uv sync --frozen`; SBOM/provenance, fresh advisory scans, hash-pinned bootstrap tooling, and Circle CLI pinning remain outside this closure. |

## Prioritized unresolved findings

### 1. A-03 — Credential-field and credential-value rejection

**Severity:** Medium
**Status:** **CLOSED**
**STRIDE:** Information disclosure

**Evidence**

- `apps/api/autonomerce/api/app.py` applies one normalized credential detector to
  parsed JSON request bodies and relevant adapter outputs.
- Exact names and suffix variants cover `accessToken`, `oauthAccessToken`,
  `mySessionToken`, `privateKeyPem`, `*token`, `*secret`, and `*privateKeyPem`.
- String values are rejected when they contain bearer credentials, decodable Basic
  credentials, PEM blocks, or credentialized URLs.
- Legitimate blockchain `token` and policy `allowedToken` fields are allowed only at
  their expected top-level route positions rather than globally exempted.
- `tests/test_api_residual_security.py` covers the previously accepted names,
  credential-bearing values, and non-reflection of the supplied credential.

This closure is syntactic input/output prevention. It is not a claim that payload
scanning replaces Secret Manager, log redaction, least-privilege credentials, or
provider-side key rotation.

---

### 2. A-08 — Request, Agent Card, rate, and concurrency limits

**Severity:** Medium
**Status:** **CLOSED**
**STRIDE:** Denial of service

**Evidence**

- Request middleware rejects compressed bodies, oversized declared/actual bodies,
  non-finite JSON, parser recursion, excessive depth, and excessive node count.
- `apps/api/autonomerce/sales/agent_cards.py` applies the same serialized-byte,
  depth, node, string, list, and mapping limits to decoded mappings and JSON
  string/byte fixtures. Canonical size is counted incrementally rather than building
  a second oversized byte string.
- `apps/api/autonomerce/api/rate_limit.py` maintains separate owner and direct-peer
  sliding-window/request and in-flight concurrency budgets.
- Gemini/SKU preview, payment, and fulfillment routes have stricter budgets than
  standard routes. Limit and concurrency failures return deterministic `429`
  details and `Retry-After`.
- `tests/test_api_residual_security.py` covers exact byte/byte-plus-one Agent Cards,
  shape limits, repeated requests, independent owner/IP budgets, all expensive route
  classes, and an actual in-flight concurrency collision.

The limiter is process-local. That is aligned with the documented one-worker live
SQLite topology, but a future multi-worker/multi-instance deployment still requires
gateway and shared-store enforcement.

---

### 3. D-01 — Consent and anti-spam integration is incomplete

**Severity:** Medium before outbound autonomous operation
**Status:** **PARTIAL**
**STRIDE:** Spoofing, Repudiation, Denial of service

**Evidence**

- `apps/api/autonomerce/api/schemas.py:108-135` adds `consentReference`.
- `apps/api/autonomerce/api/app.py:1083-1123` requires opt-in plus a non-empty
  reference and stores it with owner scope.
- `apps/api/autonomerce/api/app.py:638-680` enforces policy price, buyer-host,
  discount, and maximum-open-proposal limits.
- The API record does not validate consent issuer, subject, topic scope,
  issue/expiry/revocation timestamps, or evidence.
- The stronger registry/cooldown workflow in
  `apps/api/autonomerce/sales/prospects.py` and
  `apps/api/autonomerce/sales/pitching.py` is still not the API persistence path.

**Required remediation**

Persist a verified consent object rather than an opaque caller assertion. Bind it to
owner, buyer identity, allowed topics, issuer, issue/expiry/revocation state, and
evidence. Persist global/prospect/host rate events in the durable repository and
enforce them in `/proposals`.

---

### 4. D-02 — Network URL ingestion policy

**Severity:** Medium defense-in-depth
**Status:** **CLOSED**
**STRIDE:** Server-side request forgery

**Evidence**

- `apps/api/autonomerce/api/schemas.py` defines the ingestion policy used by seller,
  buyer/prospect, proposal, and capability-source routes.
- Non-offline mode requires credential-free public HTTPS on the default port and
  rejects private, loopback, link-local, reserved, metadata, local/internal,
  malformed, fixture, userinfo, and fragment targets.
- Offline mode additionally permits explicit loopback and reserved
  `.example`/`.test`/`.invalid` fixtures; it does not permit arbitrary private
  networks.
- Agent Card parsing applies compatible host/port/credential rules.
- The live HTTPS executor retains the stronger egress controls: exact owner
  allowlist, DNS/IP validation and pinning, no redirects, bounded payloads, and
  media-type enforcement.
- `tests/test_api_residual_security.py` covers offline fixtures, private-network
  rejection, and non-offline public-HTTPS enforcement.

The ingestion check is intentionally lookup-free. DNS resolution and pinning remain
an egress responsibility, so this closure does not authorize new fetch sinks that
bypass the guarded executor.

---

### 5. D-03 — Model-driven SKU productization remains prompt-injection-sensitive

**Severity:** Medium defense-in-depth
**Status:** **OPEN**
**STRIDE:** Tampering

**Evidence**

- `apps/api/autonomerce/agents/providers.py:229-269` sends decision payloads to
  Gemini and accepts structured model output.
- `apps/api/autonomerce/agents/productizer.py:129-148` includes untrusted capability
  description, schemas, URL, and tags.
- `apps/api/autonomerce/agents/productizer.py:159-219` still permits model-generated
  SKU name, outcome, and criteria to become a `ServiceSKU`.
- `apps/api/autonomerce/api/app.py:1013-1042` validates returned types, schemas, and
  secret fields but does not restrict outcome/criteria to an owner-approved
  vocabulary.

Downstream proposal immutability prevents a buyer from changing the resulting SKU,
but it does not prove that the SKU itself was safely authorized.

**Required remediation**

Make the model advisory for copy/relevance only. Derive scope and criterion IDs from
an owner-approved manifest and deterministic validator registry. Add adversarial
Agent Card fixtures proving unsupported instructions, URLs, and criteria are
rejected before SKU persistence.

---

### 6. D-04 — Circle subprocess provenance/output hardening remains incomplete

**Severity:** Low
**Status:** **PARTIAL**
**STRIDE:** Tampering, Information disclosure

**Evidence**

- `apps/api/autonomerce/payments/executors.py:131-163` uses a fixed argv and
  `shell=False`.
- `apps/api/autonomerce/payments/executors.py:206-265` verifies state, chain, source,
  destination, amount, and transaction hash.
- `infra/runtime_preflight.py:217-221` verifies only that the configured executable
  is one token and resolvable with `shutil.which`.
- `apps/api/autonomerce/payments/executors.py:156-163` inherits the ambient process
  environment and captures unbounded subprocess output before parsing/truncating
  error display.

**Required remediation**

Require an owner-configured absolute binary path plus reviewed version/digest,
execute with a minimal environment and fixed working directory, and impose hard
stdout/stderr byte limits.

---

### 7. D-05 — Web and API deployment hardening

**Severity:** Low
**Status:** **CLOSED**
**STRIDE:** Information disclosure, Clickjacking

**Evidence**

- `apps/web/next.config.ts:3-57` now defines CSP, frame, content-type, referrer,
  permissions, opener/resource policy, origin isolation, and HSTS headers.
- `infra/runtime_preflight.py:283-309` requires an authenticated private deployment
  mode and separate public web/private API origins.
- `apps/api/autonomerce/api/app.py` disables OpenAPI, Swagger UI, and ReDoc in
  non-offline mode.
- Non-offline startup requires explicit trusted hosts and rejects a wildcard.
- The API emits CSP, frame, content-type, referrer, permissions, cross-origin,
  cache-control, and HSTS headers as applicable.
- `tests/test_api_residual_security.py` covers disabled/protected docs, trusted-host
  rejection, and response headers.

The Cloud Run helper now requires and propagates `AUTONOMERCE_TRUSTED_HOSTS`,
rejects wildcard and URL values, and requires the configured private API origin
host to be included.

---

### 8. D-06 — Reproducible dependency and base-image inputs

**Severity:** Low
**Status:** **PARTIAL**
**STRIDE:** Tampering

**Evidence**

- `infra/Dockerfile.api` pins `python:3.12-slim` by digest.
- The image copies the committed `uv.lock`, pins the `uv` bootstrap version, and
  installs with `uv sync --frozen`.
- `uv.lock` records resolved artifacts and hashes.
- `infra/deploy_cloud_run_api.sh` requires the final application image by digest.

**Remaining boundary**

The `uv` bootstrap download is exact-version but not hash-locked by this Dockerfile,
and no SBOM/provenance attestation or fresh dependency/container advisory result is
recorded. The single-host live preflight now requires a reviewed Circle CLI path
and SHA-256 and the executor rechecks that digest before each transfer; this local
integrity check is not a distribution provenance attestation. Do not describe the
current image as bit-for-bit reproducible or vulnerability-free.

## Closed finding evidence

### A-01 — Authentication and owner scoping

- `apps/api/autonomerce/api/auth.py:20-61` implements constant-time bearer-token
  verification and returns only the configured owner identity.
- `apps/api/autonomerce/api/app.py:780-800` refuses non-offline startup without
  bearer authentication, durable commerce storage, and a non-offline payment
  adapter.
- `apps/api/autonomerce/api/app.py:816-825` authenticates every non-public route.
- `apps/api/autonomerce/api/app.py:683-690` enforces object owner equality.
- Seller, prospect, proposal, payment, fulfillment, publication, list, and metrics
  paths apply the principal/owner checks.
- `tests/test_api.py:352-409` passed unauthenticated, invalid-token, cross-owner, and
  non-offline startup regression cases.

This closure is for the documented **single-owner** deployment. It is not a claim
that the API implements multi-role buyer/seller/workforce authorization.

### A-02 — Artifact and operational-data privacy

- `apps/api/autonomerce/api/app.py:538-552` exposes only fulfillment evidence and
  artifact metadata.
- `apps/api/autonomerce/api/app.py:1693-1735` hashes and validates the artifact but
  persists only metadata in the fulfillment receipt.
- `apps/api/autonomerce/api/app.py:1796-1840` returns `404` before publication and
  never includes buyer input or artifact content in the public projection.
- `tests/test_api.py:109-214` and `446-482` passed artifact omission, publication,
  and durable-record privacy assertions.

### A-04 — Contract immutability

- `apps/api/autonomerce/api/app.py:1189-1215` rejects create-time scope, acceptance,
  and delivery changes and derives those fields from the SKU.
- `apps/api/autonomerce/api/app.py:1283-1358` rejects those mutations during a
  counter and permits only bounded price revision.
- `apps/api/autonomerce/api/app.py:563-576` computes the canonical contract hash.
- `apps/api/autonomerce/api/app.py:1507-1516` refuses payment if the stored hash is
  missing or stale.
- `tests/test_api.py:412-443` passed scope/criteria/delivery mutation cases.

The hash is not embedded in `PaymentReceipt`; that is residual defense-in-depth, but
no current untrusted API path can alter the accepted contract without detection
before payment.

### A-05 — Durable live stores

- `apps/api/autonomerce/payments/api_adapter.py:177-200` rejects missing or
  process-local live stores.
- `apps/api/autonomerce/payments/store.py:382-396` requires a durable SQLite file
  path for the supported single-node store.
- `apps/api/autonomerce/api/app.py:784-793` separately requires a durable commerce
  repository.
- `infra/runtime_preflight.py` requires a marked writable persistent mount, the
  commerce and payment paths to be the same database file, one API worker, and
  rejects live Cloud Run use.
- `tests/test_payments.py:352-394` and
  `tests/test_repository_persistence.py:161-291` passed process-store rejection,
  restart persistence, atomic projection, and multi-worker rejection tests.

### A-06 — x402 amount and requirement binding

- `apps/api/autonomerce/payments/x402.py:315-413` requires exact amount, chain,
  token, asset, payee, resource, identifier, and scheme agreement and copies the
  complete fingerprint into `PaymentIntent`.
- `apps/api/autonomerce/payments/models.py:280-303` includes those values in the
  payment fingerprint.
- `tests/test_payments.py:592-759` passed amount mismatch, complete binding,
  conflicting alias, and fingerprint-change cases.

### A-07 — Publication replay

- `apps/api/autonomerce/payments/api_adapter.py:260-263` ignores the compatibility
  `public` execution argument and always creates private payment records.
- `apps/api/autonomerce/api/app.py:1495-1499` rejects publication through payment.
- `apps/api/autonomerce/api/app.py:1750-1794` implements a separate authenticated
  publication action.
- `apps/api/autonomerce/api/repository.py:381-408` and the SQLite implementation
  reject conflicting publication replay.
- `tests/test_payments.py:416-438` passed private-to-public payment replay, with one
  executor call and both receipts remaining private.

## Seller executor and live fail-closed verification

The live seller path is materially safer:

- live composition requires an explicit seller executor
  (`apps/api/autonomerce/api/adapters.py:595-634`, `712-740`);
- caller-authored live artifacts are rejected
  (`apps/api/autonomerce/api/adapters.py:306-341`);
- the built-in verification executor binds supported SKUs, bounds claims/sources,
  scopes non-abstain decisions to cited supplied evidence, and marks external truth
  unverified;
- the HTTPS executor uses exact URL allowlisting, public DNS/IP validation, pinned
  TLS, no redirects, bounded request/response sizes, JSON media enforcement, and
  credential rejection.

`tests/test_seller_executors.py` passed all executor, SSRF, credential, redirect,
factory, and evidence-scope tests. `tests/test_adapter_composition.py` passed live
mode no-fallback, explicit-executor, and caller-artifact rejection tests.

Runtime preflight checks produced:

```text
AUTONOMERCE RUNTIME PREFLIGHT: PASS
(deployment=local-offline, runtime=offline, auth=local-only, payment=offline)

BLOCKED: AUTONOMERCE_API_BEARER_TOKEN must be set explicitly
LIVE_WITHOUT_TOKEN_EXIT=2

BLOCKED: Cloud Run must use an explicit cloud-run-private-* deployment mode
CLOUD_LIVE_EXIT=2
```

## Targeted test and tooling record

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPYCACHEPREFIX=/private/tmp/autonomerce-appsec-pycache \
python3 -m pytest -p no:cacheprovider -q \
  tests/test_api_residual_security.py \
  tests/test_api.py \
  tests/test_sales.py \
  tests/test_repository_persistence.py
```

Result:

```text
58 passed, 1 warning
```

The warning was the existing FastAPI/Starlette `TestClient` deprecation warning.
The latest full Python run completed 193 passing tests with one unrelated
productizer-price assertion failure in untouched `tests/test_agents.py`.
`npm test` in `apps/web` completed 18 passing tests, including owner-session,
backend-proxy, workflow-contract, and secret-isolation cases.

Fresh Bandit, Semgrep, CodeQL, and `pip-audit` results cannot be asserted: those
tools were unavailable in the current environment. **ABSTAIN** on a current SAST or
Python advisory clean bill until those tools are run against this remediated tree.
The prior review's tool results do not prove the changed tree clean.

## STRIDE trust-boundary summary

| Boundary | Main risks | Follow-up result |
|---|---|---|
| Client → FastAPI | Spoofing, elevation, disclosure, DoS | Authentication, owner scoping, credential rejection, input limits, and process-local rate/concurrency controls present |
| Agent Card/buyer data → Gemini | Tampering, disclosure | Credential filtering and URL/shape limits closed; productization prompt injection open |
| API → commerce repository | Tampering, repudiation | Owner records, contract hashes, atomic durable SQLite, and publication records present |
| API → payment adapter/store | Replay, tampering, repudiation | Durable-store enforcement, exact receipt validation, and replay binding closed |
| x402 → payment intent | Tampering, replay | Complete exact binding closed |
| Payment adapter → Circle CLI | Injection, spoofed result, leakage | Injection/result controls strong; executable provenance/output caps partial |
| API → seller executor/network | SSRF, disclosure, tampering | Explicit fail-closed executor, exact allowlist, DNS/IP pinning, and limits present |
| Seller artifact → storage/public receipt | Disclosure, DoS | Artifact content not persisted or publicly returned; publication is explicit and durable |
| Deployment → internet | Spoofing, disclosure, misconfiguration | App docs/headers/trusted hosts closed; Cloud Run helper still must propagate the trusted-host value |

## Release recommendation

- **Local/offline demo:** acceptable with the documented local-only boundary.
- **Private single-host testnet pilot:** conditional for trusted operators only;
  preserve one worker/one database, explicit trusted hosts, low caps, and external
  authentication.
- **Internet-facing live testnet:** **NO-GO** while D-01 lacks verified consent and
  durable anti-spam state, D-03 remains model-authority-sensitive, Circle executable
  hardening is partial, and no final deployed integration review exists.
- **Mainnet:** **NO-GO** pending the unresolved items, reproducible supply chain,
  fresh SAST/dependency scans, and an independent review of the final deployed
  Circle credentials, binary, wallet policy, storage mount, and gateway controls.
