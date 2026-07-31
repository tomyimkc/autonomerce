# Autonomerce Final Code Review

**Review date:** 2026-07-31
**Scope:** current Autonomerce implementation, tests, packaging, and deployment
preflight
**Release-blocking result:** **0 Critical / 0 High / 0 Medium / 0 Low remaining
in the requested remediation scope**

## Recommendation

- **Credential-free offline contest demo:** GO.
- **Private single-host testnet:** conditional code-readiness; real integration
  and operator evidence are still required.
- **Mainnet or multi-instance production:** NO-GO.

This recommendation is narrower than a production approval. It reflects local
code/test evidence and a synthetic startup preflight, not live Gemini/Circle,
customer, revenue, deployment, or funds-movement proof.

## Final reviewer blockers and closure

### 1. High — seller change bypassed operation replay protection

**Prior failure:** proposal replay discovery was scoped to the newly supplied
seller. Reusing operation ID `X` with seller B could miss seller A's existing
proposal, create a second proposal, and derive a second payment idempotency key.

**Fix:**

- initial replay lookup now uses owner-authenticated `GET /proposals` without a
  caller-controlled seller filter;
- the stored operation marker is compared against the complete immutable
  fingerprint before any candidate is accepted or a new proposal is created;
- the owner-wide backend list remains tenant-scoped by the API principal.

**Regression:**

```text
resumed workflow rejects a changed seller before creating or paying: PASS
```

**Independent rereproduction after the fix:**

```text
proposal creations: 1
payments: 1
changed-seller replay: 409 workflow_operation_conflict
second proposal/payment: none
```

**Status:** CLOSED.

### 2. High — canonical live environment could not pass preflight

**Prior failure:** the deployment contract required
`AUTONOMERCE_MODE=live` and `AUTONOMERCE_PAYMENT_MODE=testnet`, while the
payment factory interpreted `live` as requiring the legacy
`AUTONOMERCE_CIRCLE_NETWORK`. Preflight rejected that legacy variable, so no
configuration could satisfy both.

**Fix:**

- `AUTONOMERCE_MODE=live` is treated as the composition selector;
- `AUTONOMERCE_PAYMENT_MODE=testnet|mainnet` is the canonical settlement mode;
- legacy network inference remains compatibility-only outside deployment
  preflight;
- canonical allowed chains continue to bind the actual settlement policy.

**Regressions and reproduction:**

```text
test_canonical_live_environment_uses_explicit_payment_mode: PASS
fresh-process private-single-host-testnet runtime_preflight: PASS
legacy AUTONOMERCE_CIRCLE_NETWORK in passing environment: absent
```

**Status:** CLOSED.

## Additional final hardening

### Bounded same-operation queue

The web lock already bounded distinct operation IDs and removed completed
entries. It now also caps each operation at 32 outstanding requests. Excess
requests receive typed `429 workflow_operation_queue_full` responses rather
than consuming unbounded same-key promise chains.

Regression:

```text
same workflow operation has a bounded waiter queue: PASS
```

### Explicit live publication mode

Live preflight now requires
`AUTONOMERCE_RECEIPT_PUBLICATION_MODE=disabled|verified`.

- `disabled` rejects contradictory verifier configuration.
- `verified` imports the configured `module:function`, calls the factory, and
  requires a callable verifier before startup.
- The endpoint still independently requires exact proposal/need/field consent
  and returns fail-closed errors when verification is absent or negative.

Four focused runtime-preflight tests pass.

### Canonical Circle preflight helper

The read-only Circle helper now consumes canonical
`AUTONOMERCE_PAYMENT_ALLOWED_CHAINS` and
`AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS` settings instead of legacy
network/wallet aliases. It retains absolute binary path and SHA-256 checks and
does not submit a payment.

## Correctness/integrity summary

| Area | Result |
|---|---|
| Exact decimal USDC | Exact decimal parsing/aggregation; no binary-float financial decisions |
| Buyer need | Proposal and fulfillment bind the exact `buyerNeedId` and private input |
| Proposal identity | Proposal IDs/hashes include exact need, problem, price, delivery, scope, and expiry |
| State projection | Explicit legal transition graph; stale replay safe; conflicting same-revision content rejected |
| Acceptance | Immutable settlement authorization frozen at acceptance |
| Payer | Selected only from owner-configured live allowlist |
| Payee | Bound to accepted seller configuration and immutable authorization |
| Asset | Canonical USDC contract required for each supported chain |
| Payment replay | Intent and receipt fields must match; transaction-hash reuse rejected |
| Reconciliation | Durable retryable/confirm/cancel operator actions; no automatic resubmission |
| Crash recovery | Shared SQLite reconstruction requires complete matching authorization/evidence |
| Fulfillment | Payment/proposal relationship enforced; seller output validated against accepted contract |
| Publication | Separate owner action with separate purpose-scoped consent |
| Gemini | Advisory only for copy/relevance; deterministic code owns financial and acceptance decisions |
| Async API | Blocking productizer/payment/fulfillment adapters execute through `asyncio.to_thread` |
| BFF timeouts | Ordinary 12 s; payment/fulfillment 150 s; hard maximum 180 s |
| Rate/queue state | Bounded/expiry-swept address maps; bounded distinct and same-operation workflow queues |

## Final local gate results

```text
Python: 223 passed, 1 warning
Web: TypeScript PASS; 33 tests passed; production build PASS
Authenticated offline-backend web integration: 1 passed
Source demo: two byte-identical runs
Installed-wheel demo: two byte-identical runs
Container health: offline/offline/movesFunds=false
In-container demo: two byte-identical runs
```

The Next.js-generated `next-env.d.ts` file is ignored, as recommended by the
installed Next 16 documentation. `npm run typecheck` runs `next typegen` before
`tsc --noEmit`, so a clean checkout generates route types before type checking
without committing dev/build-specific generated paths.

Policy/integrity gates are rerun after this document is written and are recorded
in the landing PR. A passing local gate is not a claim of live external service
behavior.

## Residual engineering boundaries

1. **Single-host only.** SQLite and process-local rate/concurrency controls do
   not support multi-instance active-active deployment.
2. **External integrations unproven.** No real Gemini, Circle CLI, transaction
   lookup, consent verifier, or seller-agent network integration was exercised.
3. **Mainnet operations unproven.** No funding, emergency stop, incident
   response, key rotation, legal review, or production monitoring receipt
   exists.
4. **Supply-chain attestation incomplete.** No final SBOM, signed provenance,
   registry signature, CodeQL receipt, or container advisory report is claimed.
5. **Contest outcomes unproven.** There is no external customer, revenue,
   deployment, Devpost submission, finalist, or prize result.

## Final conclusion

The final code review gate is **GO at 0 Critical / 0 High** for the deterministic
offline contest build and for continued owner-controlled testnet integration.
It is **not** approval to enable mainnet, claim production readiness, or publish
customer/revenue claims.
