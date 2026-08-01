# Autonomerce OKF record profile

Autonomerce uses canonical JSON records plus deterministic Markdown OKF
projections. This avoids asking an LLM to parse private facts out of prose while
preserving a human-readable, linkable knowledge layer.

## Common JSON contract

Every non-template record requires:

```json
{
  "schemaVersion": "autonomerce.okf.record.v1",
  "recordId": "lowercase-slug",
  "recordKind": "partners",
  "status": "draft",
  "visibility": "private",
  "createdAt": "2026-08-01T00:00:00Z",
  "updatedAt": "2026-08-01T00:00:00Z",
  "title": "Short human title",
  "llmSummary": "Bounded summary for retrieval.",
  "claimBoundary": "What this record does not prove.",
  "sourceEvidence": [],
  "links": [],
  "nextAction": "One concrete next step."
}
```

Allowed statuses:

```text
draft
waiting_owner
authorized
ready
executed
verified
rejected
superseded
blocked
```

Allowed visibility:

```text
private
public_redacted
```

## Generated Markdown profile

The generated page uses existing Sophia-compatible flat frontmatter:

```yaml
---
id: pilot-example
pageType: memory
recordKind: pilots
status: ready
visibility: private
createdAt: "2026-08-01T00:00:00Z"
updatedAt: "2026-08-01T00:00:00Z"
sources: [consent-example]
links: [partner-example, authorization-example]
claimBoundary: "Testnet pilot; not revenue."
---
```

Do not add `domain: commerce`; the global Sophia OKF domain vocabulary does not
currently contain commerce. Do not use attribution/tradition fields for
operational records.

## Invariants

1. Record IDs are unique lowercase ASCII slugs.
2. Record kind must match its directory.
3. Links must resolve and cannot self-link.
4. `updatedAt` cannot precede `createdAt`.
5. Canonical records reject credential-bearing key names.
6. `public_redacted` records reject PII and credential-like text.
7. Generated pages include the canonical record SHA-256.
8. Generated pages copy only approved summary metadata, never arbitrary private
   fields.
9. `automaticSubmission` and automatic fund movement remain false.
10. Pilot readiness can produce a dry-run command but never execution approval.
11. One authorization is bound to exactly one active pilot and its exact
    `microdealId`.
12. Runtime SQLite and private evidence remain under the private workspace;
    redacted output first lands in workspace-owned publication staging.
13. Symlinked workspace directories and output targets are rejected.

## External pilot readiness

The pilot packet requires linked `partners`, `consents`, and `authorizations`
records. Readiness is limited to:

```text
ARC-TESTNET
canonical USDC
0.10 USDC
one payment
founder-sponsored testnet funding
external design partner
countedAsRevenue=false
payingCustomer=false
mainnetEnabled=false
```

Before readiness can pass:

- partner status is verified and recruitment is accepted;
- consent status is verified and all three permissions are granted;
- pilot status is ready;
- authorization status is authorized and bound to that pilot;
- `authorizedAt` is not in the future and `expiresAt` is still valid;
- the authorization is not shared by another active pilot;
- customer input passes the same bounded claim/source contract as the runner;
- all runtime and staging paths are real, non-symlinked, workspace-owned paths.

Even after all records validate, `readyForExecution` remains false until the
owner supplies fresh session-specific approval and the exact confirmation
required by `run_external_testnet_microdeal.py`.
