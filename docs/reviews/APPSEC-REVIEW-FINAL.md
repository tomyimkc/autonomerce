# Autonomerce Final Application Security Review

**Review date:** 2026-07-31
**Scope:** the uncommitted Autonomerce contest snapshot under
`projects/autonomerce/`
**Review boundary:** code, tests, deterministic offline execution, synthetic
single-host preflight, installed wheel, and local container smoke

## Executive verdict

The final release-blocking review scope contains:

| Severity | Open count |
|---|---:|
| Critical | **0** |
| High | **0** |
| Medium | **0 within the remediation scope** |
| Low | **0 within the remediation scope** |

An independent code reviewer reproduced the previously reported changed-seller
workflow replay, reviewed the remediation, and then reported **0 Critical / 0
High** in that scope. The changed-seller replay now returns
`409 workflow_operation_conflict` before a second proposal or payment can be
created.

An independent reality-check rerun then reported **0 Critical / 0 High / 0
Medium / 0 Low remaining in the requested remediation scope**. Operational
non-proof and supply-chain evidence boundaries remain documented below; they are
not represented as discovered code vulnerabilities.

The credential-free offline path is **GO** for local judging and development.
The private, one-worker, one-persistent-host testnet shape has **conditional
code-readiness only**: a canonical synthetic configuration passes startup
preflight, but no live Gemini request, Circle transaction, external transaction
lookup, publication-consent verifier, or deployed host was exercised. Mainnet is
**NO-GO**.

## Final closure table

| Boundary | Final result | Evidence |
|---|---|---|
| Workflow operation replay | **CLOSED** | Replay lookup spans the authenticated owner's proposal namespace. Changing seller, SKU, policy, buyer, consent, price, expiry, problem, or delivery changes the stored fingerprint and fails before proposal creation/payment. |
| Exact buyer need | **CLOSED** | Proposals require `buyerNeedId`; identifiers bind the exact buyer input and consent; fulfillment reloads the accepted need rather than choosing by buyer URL. |
| Acceptance and settlement authorization | **CLOSED** | Acceptance freezes exact proposal revision/hash, amount, payer, payee, chain, token, canonical asset, policy/config versions, and expiry. Payment consumes only that snapshot. |
| Payer/payee control | **CLOSED** | Live payer selection comes from the configured allowlist; empty allowlists fail; multiple payer wallets require explicit selection; payment-time substitution is rejected. |
| Canonical USDC asset | **CLOSED** | Supported networks bind canonical USDC contract addresses. A different asset descriptor, even if labeled `USDC`, is rejected. |
| Circle command integrity | **CLOSED internally** | Live execution requires an absolute binary path and reviewed SHA-256, rehashes immediately before transfer, uses fixed argv with no shell, a constrained environment/working directory, and bounded output. Distribution provenance is not claimed. |
| Independent settlement verification | **CLOSED internally** | Live confirmation requires an explicitly marked independent transaction lookup that matches hash, chain, amount, payer, payee, token, and asset. No real provider implementation was exercised. |
| Idempotency and reconciliation | **CLOSED for supported topology** | Durable payment intent/replay checks, transaction-hash uniqueness, operator reconciliation routes, independent evidence, and projection repair are implemented. No automatic resubmission occurs after ambiguous execution. |
| Crash recovery | **CLOSED for shared single-host SQLite** | Recovery requires complete settlement authorization, preserves token/asset/payer/payee/amount/hash, and refuses incomplete or conflicting evidence before advancing commerce state. |
| Proposal state projection | **CLOSED** | An explicit transition graph rejects illegal terminal exits and same-revision conflicts while permitting valid accepted-to-paid revision advancement and stale lower-state replay. |
| Repository parity | **CLOSED** | In-memory and SQLite repositories enforce settlement/fulfillment relationships and transaction-hash uniqueness rather than leaving security checks only in one implementation. |
| Owner authentication | **CLOSED for single-owner scope** | Private API routes use bearer authentication and owner scoping. The web BFF uses a separate signed, short-lived, strict `HttpOnly` owner session and never exposes the API bearer to browser code. |
| Request/resource exhaustion | **CLOSED for one process** | API and web address maps are bounded and expiry-swept. Global budgets resist address rotation. Workflow IDs are capped at 1,024 and each operation is capped at 32 outstanding requests with typed `429` rejection. |
| Publication authorization | **CLOSED as a fail-closed boundary** | Publication is separate from payment, requires purpose-scoped consent, and rejects contact-consent reuse. Live preflight now requires explicit `disabled` or `verified` publication mode; verified mode imports a factory and requires a callable verifier before startup. |
| Live configuration contract | **CLOSED** | `AUTONOMERCE_MODE=live` composes the live system while `AUTONOMERCE_PAYMENT_MODE=testnet|mainnet` selects settlement. Canonical `AUTONOMERCE_PAYMENT_*` settings no longer require a legacy variable that deployment preflight rejects. |
| SSRF and untrusted seller execution | **CLOSED for current sinks** | Non-offline URL ingestion requires public HTTPS. The HTTPS executor applies exact allowlists, DNS/IP validation and pinning, no redirects, bounded payloads, media-type checks, and credential rejection. |
| Gemini authority | **CLOSED for financial/acceptance authority** | Gemini can suggest copy and relevance only. Deterministic manifests, policy, validators, and exact-money code control criteria, price, wallet, chain, token, amount, capacity, latency, and acceptance. |

## Remaining evidence boundaries

### External publication-consent evidence is not supplied

The code and preflight fail closed, but this repository does not contain a
contest-owner production consent provider or a real verifier receipt. A live
operator must configure `AUTONOMERCE_RECEIPT_PUBLICATION_MODE=verified` and a
factory that checks an independently stored, unexpired, unrevoked consent record
for the exact proposal and public field set. Until that integration is exercised,
live public-receipt publication is not proven.

### No fresh third-party SBOM/advisory attestation

The Python lock, pinned base-image digest, pinned `uv` version, wheel, container
build, public secret scan, and source tests are local evidence. They are not an
SBOM, SLSA provenance record, signed image, CodeQL result, container advisory
scan, or guarantee of no vulnerable dependency.

## Verification receipts

### Python

```text
223 passed, 1 warning in 3.98s
```

The warning is the existing Starlette/TestClient deprecation warning.

### Web

```text
TypeScript: PASS
Node tests: 33 passed, 0 failed
Next.js production build: PASS
Authenticated offline-backend integration: 1 passed, 0 failed
```

The integration test starts an authenticated **offline** FastAPI backend. The
word `LIVE` in the test name describes the real BFF/backend path, not a live
Gemini or Circle transaction.

### Canonical private testnet startup preflight

A fresh process used:

```text
AUTONOMERCE_DEPLOYMENT_MODE=private-single-host-testnet
AUTONOMERCE_MODE=live
AUTONOMERCE_PAYMENT_MODE=testnet
AUTONOMERCE_PAYMENT_ALLOWED_CHAINS=ARC-TESTNET
AUTONOMERCE_RECEIPT_PUBLICATION_MODE=disabled
```

plus synthetic owner auth, wallet allowlists, caps, independent-lookup factory,
pinned executable, trusted host, one worker, and a marked persistent directory.
No legacy `AUTONOMERCE_CIRCLE_NETWORK` variable was set.

Result:

```text
AUTONOMERCE RUNTIME PREFLIGHT: PASS
(deployment=private-single-host-testnet, runtime=live,
 auth=external-auth-proxy, payment=testnet)
```

This proves configuration compatibility only. The executable and lookup used in
this receipt were synthetic and moved no funds.

### Deterministic demo

Two source-tree runs were byte-identical:

```json
{
  "offline": true,
  "networkCalls": 0,
  "credentialsUsed": false,
  "realFundsMoved": false,
  "paymentExecutorCalls": 1,
  "idempotentPaymentReplay": true,
  "ledgerEntries": 4,
  "ledgerVerified": true
}
```

### Installed wheel

```text
Wheel: /tmp/autonomerce-dist.6iFOlx/autonomerce-0.1.0-py3-none-any.whl
SHA-256: e947129b0c81983fbc57e81f7e679a67154ffb6e89811f302566ddfd0e48e159
Installed-package demo: two byte-identical runs
```

The temporary path is a local review receipt, not a published artifact URL.

### Container

```text
Image: autonomerce:final-review
Image ID: sha256:f59bba4056bd6074b1f7738a862870abf9a42023998ea7dc72d6354883a6225c
/health: status=ok, runtimeMode=offline, paymentMode=offline, movesFunds=false
In-container installed demo: two byte-identical runs
```

The image build and smoke were local. No registry push or hosted deployment is
claimed.

## Operating-mode recommendation

| Mode | Verdict | Required interpretation |
|---|---|---|
| Credential-free offline | **GO** | Deterministic judging/development path only; transaction and revenue values are synthetic. |
| Private one-worker persistent single-host testnet | **CONDITIONAL CODE-READINESS** | Canonical startup configuration passes locally. Owner must still authenticate, supply real factories, fund/allowlist wallets, deploy the host, and collect external evidence. |
| Internet-exposed multi-instance live service | **NO-GO** | Current storage/limiter design intentionally supports one process on one persistent host, not distributed coordination. |
| Mainnet | **NO-GO** | No real transaction, deployment, incident controls, legal review, or production operations evidence exists. |

## Explicit non-proof boundary

This final review does **not** prove:

- a Gemini request, model identity, latency, output quality, or cost;
- compatibility with an installed/current Circle Agent Wallet CLI;
- a Circle testnet or mainnet transfer;
- a real explorer, RPC, facilitator, or transaction-lookup integration;
- a real publication-consent verifier or consent record;
- credentials, OTP/KYC, billing, wallet session, balance, funding, or limits;
- a Compute Engine, Cloud Run, or other hosted deployment;
- customer opt-in, customer identity, demand, revenue, margin, or job creation;
- multi-worker, multi-host, failover, or production availability;
- legal, tax, sanctions, KYC, privacy, or money-transmission compliance; or
- mainnet or production security.
