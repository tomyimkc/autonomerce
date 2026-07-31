# Autonomerce Code Review Follow-up

**Review date:** 2026-07-31
**Baseline:** `docs/reviews/CODE-REVIEW.md`
**Current-state refresh:** 2026-07-31; this documentation pass did not modify
application or test source

## Release recommendation

**NO-GO for an internet-exposed, fund-moving web deployment.**

The remediation closes the original silent-live-fallback, adapter-composition,
negotiation, schema-validation, x402, Docker-context, health-reporting, public-web
owner-session, web/backend contract, same-database crash-recovery, and URL-ingestion
defects. The remaining code-level blocker from the original review is that
deterministic Circle rejections still have no operator
reconciliation/resolution workflow.

The documented private single-host testnet shape is materially stronger, but this is
not approval for an internet-exposed or mainnet deployment. The store remains
single-host, consent is still an owner-supplied reference, model-driven SKU scope
remains advisory-sensitive, and no real Gemini/Circle/deployment integration was
verified by this review.

## Status summary

| Prior finding / requested check | Status | Evidence |
|---|---|---|
| **CR-01 — live config/env behavior** | **CLOSED** | `api/adapters.py:459-536,539-592,637-742` defines one composed runtime, bridges documented caps, rejects mode conflicts, and never substitutes a mock for requested live payment. `payments/api_adapter.py:270-387` consumes both canonical and documented aliases and requires live SQLite, wallet allowlists, network, and caps. `infra/runtime_preflight.py:168-249,251-321` fails closed before non-offline startup. Tests: `test_adapter_composition.py:201-235`; `test_payments.py:375-413`. |
| **CR-02 — auth and object authorization** | **CLOSED** | Private API mutation routes are bearer-protected and owner-scoped. LIVE web onboarding/workflow routes call `requireOwnerSession`; login issues a signed 15-minute `HttpOnly`, `SameSite=Strict` cookie using a distinct server-only session secret. Forged/expired sessions and secret reuse are covered by `apps/web/tests/owner-session.test.ts`. Cloud Run still adds IAM/IAP/service identity as an outer boundary. This closure is single-owner, not multi-role authorization. |
| **CR-03 — adapter composition / seller execution** | **CLOSED** | Live composition requires Gemini, a non-offline payment adapter, and an explicit seller executor (`api/adapters.py:637-742`), rejects caller-authored live artifacts (`api/adapters.py:306-341`), and does not silently downgrade. The API loads the persisted prospect input and passes it as `context.buyerInput` (`api/app.py:1667-1684`). Built-in and HTTPS seller executors consume that field (`sales/executors/__init__.py:402-455,746-827`). Tests: `test_adapter_composition.py:201-309`; `test_seller_executors.py`. |
| **Seller execution with buyerInput through the web** | **CLOSED** | The LIVE web workflow sends the buyer claim/source input in `inputPayload`, supplies the explicit consent reference, and the backend passes persisted `buyerInput` to the seller executor. This closes the prior empty-input integration mismatch; it does not validate the truth of caller-supplied sources. |
| **CR-04 — negotiation contract** | **CLOSED** | Proposal creation binds outcome, acceptance criteria, and delivery to the SKU (`api/app.py:1189-1245`). Counters may change price only; scope, criteria, and delivery mutations return 409 (`api/app.py:1283-1358`). Acceptance rechecks the SKU contract and policy (`api/app.py:1366-1415`). The final contract hash is checked before payment (`api/app.py:1507-1516`). Test: `test_api.py:412-443`. |
| **CR-05 — JSON Schema validation** | **CLOSED** | SKU schemas are validated before storage and after productization (`api/app.py:170-278,944-1042`). Fulfillment recursively enforces supported object, array, enum, length, numeric-bound, item, required, and additional-property constraints (`api/app.py:281-392`). Unsupported keywords fail closed. Test: `test_api.py:446-483`, plus the original missing-required-field test. |
| **CR-06 — durable commerce/payment state** | **CLOSED** | `SQLiteRepository` persists the complete commerce aggregate and payment state with transactional/uniqueness controls and restart recovery. `infra/runtime_preflight.py` now requires `AUTONOMERCE_COMMERCE_SQLITE_PATH` and `AUTONOMERCE_PAYMENT_SQLITE_PATH` to resolve to the same database file, on the marked persistent mount, with one worker. This closes the documented single-host crash-projection gap. No distributed/multi-instance store is claimed. |
| **CR-07 — Circle rejection handling** | **PARTIAL** | Ambiguous timeout/nonzero CLI outcomes now get a durable reconciliation marker and are not automatically retried (`payments/executors.py:153-186`; `payments/service.py:38-61`; `payments/store.py:597-674`). Test: `test_payments.py:457-502`. But every nonzero CLI exit is still classified as ambiguous, including a deterministic pre-submit rejection such as insufficient balance, and there is no authenticated reconciliation endpoint/job or transition that resolves or retries a proven-not-submitted payment. Such an order remains `SUBMITTING`. |
| **CR-08 — x402 binding** | **CLOSED** | `X402PaymentRequirement.to_intent` requires exact amount, chain, token, asset, payee, resource, identifier, scheme, and seller-host binding, then embeds the full requirement fingerprint in the payment intent (`payments/x402.py:315-415`). The intent fingerprint includes all security fields (`payments/models.py:279-303`). Tests: `test_payments.py:592-759`. |
| **CR-09 — web private proxy integration** | **CLOSED** | LIVE mode calls fixed same-origin Next.js routes with a server-only API bearer and valid owner session. The workflow sends consent and buyer input, publishes the receipt through the authenticated route before reading it, and accepts either `AUTONOMERCE_API_BASE_URL` or the deployment-standard `AUTONOMERCE_API_PRIVATE_ORIGIN`, failing closed if both differ. |
| **CR-10 — URL/SSRF controls** | **CLOSED** | API ingestion now requires public HTTPS for non-offline seller/buyer/capability URLs and permits only explicit loopback/reserved fixtures offline. Credentialized, private/link-local/metadata, malformed, fragmented, and non-default public destinations are rejected. The live executor retains exact allowlisting, DNS/IP pinning, redirect prohibition, and bounded I/O. |
| **CR-11 — `.dockerignore`** | **CLOSED** | Product-root `.dockerignore:1-20` excludes secrets, VCS data, `node_modules`, `.next`, Python caches, build output, private evidence, and review files. |
| **API health `paymentMode` / `movesFunds`** | **CLOSED** | Adapter diagnostics explicitly report effective runtime, payment mode, executor source, and `movesFunds` (`api/adapters.py:344-365,697-742`). `/health` exposes `paymentMode`, `movesFunds`, storage durability, authentication requirement, and integrations (`api/app.py:885-911`). Tests: `test_api.py:97-106`; `test_adapter_composition.py:290-309`. |

## Ranked remaining findings

### 1. Medium — Deterministic Circle CLI rejections still strand orders

**Location:** `apps/api/autonomerce/payments/executors.py:176-186`;
`apps/api/autonomerce/payments/service.py:38-61`.

**Failure scenario:** Circle exits nonzero with a structured or textual
pre-submission rejection such as insufficient balance or wallet-policy denial. The
processor records reconciliation-required state but leaves the payment `SUBMITTING`;
replay never calls Circle again, and the product exposes no reconciliation or
resolution action.

### 2. Closed — Cloud Run helper propagates the trusted-host value

**Location:** `infra/deploy_cloud_run_api.sh`;
`apps/api/autonomerce/api/app.py`.

The helper now requires and propagates `AUTONOMERCE_TRUSTED_HOSTS`, rejects
wildcard and URL values, and requires the configured private API origin host to
be included.

### 3. Boundary — Durable state is intentionally single-host

The same-database requirement closes the reviewed crash-projection gap for one
worker on one persistent host. It does not add replication, multi-instance
coordination, managed failover, or Cloud Run-compatible file locking. Any topology
change requires a shared transactional commerce/payment/reconciliation store and new
restart/load/failover tests.

## Verification performed

- The latest focused API/security/sales/persistence run in this worktree completed
  **58 passed** with the existing Starlette/TestClient deprecation warning.
- The latest full Python suite completed **193 passed** with one unrelated
  productizer-price assertion failure in untouched `tests/test_agents.py`.
- `npm test` in `apps/web` completed **18 passed**, including owner-session,
  backend-proxy, consent/input/publication workflow, and secret-isolation coverage.
- The current-state refresh inspected owner-session routes/tests, the LIVE
  consent/input/publication flow, same-database runtime preflight, `uv.lock`,
  digest-pinned `Dockerfile.api`, deployment scripts, and URL/security controls.

## Not reviewed or not verified in this follow-up

- No live Gemini/Vertex request, Circle testnet/mainnet transfer, Cloud Run
  deployment, IAM invocation, or real seller-agent network call was performed.
- The full web `npm run check` was not run; this refresh ran the 18-test web suite,
  not a fresh typecheck or production build.
- The offline CLI demo and Docker image build were not rerun in this follow-up.
- No distributed load, multi-node database, process-kill crash injection, browser
  end-to-end session test, accessibility audit, or visual review was performed.
- I did not re-review unrelated contest claims, legal/KYC requirements, or the full
  separate `APPSEC-REVIEW.md`.
