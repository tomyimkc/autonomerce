# Autonomerce OKF / LLM-Wiki record index

`schema: autonomerce.okf.workspace.v1` · `private records are not committed`

This tracked index defines the record system. Actual partner identity, consent,
wallet, payment, fulfillment, expense, and Devpost working records belong under
the ignored private workspace:

```text
evidence/private/okf/
```

Initialize it with:

```bash
python3 scripts/manage_okf_records.py init \
  --root evidence/private/okf

python3 scripts/manage_okf_records.py validate \
  --root evidence/private/okf

python3 scripts/manage_okf_records.py build \
  --root evidence/private/okf
```

The generated private wiki is a projection over canonical JSON records. It
contains summaries, claim boundaries, source references, links, and digests;
it does not duplicate arbitrary private fields into Markdown.

## Record taxonomy

| Directory | Purpose | Current owner |
|---|---|---|
| `partners` | relationship, arms-length status, recruitment outcome, buyer-agent reference | owner |
| `consents` | interview, pilot, transaction, and publication permissions | owner + participant |
| `pilots` | one bounded commercial pilot and its linked records | Codex prepares; owner authorizes |
| `authorizations` | exact network, asset, amount, wallets, caps, paths, and expiry | owner only |
| `proposals` | proposal identity, revision, scope, amount, and acceptance | software |
| `payments` | settlement state, network, amount, transaction, replay, and revenue exclusion | software |
| `fulfillments` | artifact hash, validator, criteria, verdict, and delivery time | software |
| `financial` | expenses, refunds, valuation, recognized revenue, and concentration | owner + software |
| `evidence` | source artifacts, digests, classifications, and publication state | software + owner |
| `videos` | script, capture, upload, duration, checksum, and disclosure labels | owner |
| `devpost` | draft IDs, field readiness, uploads, links, and final owner-only gates | owner + supported MCP tools |
| `decisions` | durable commercial, safety, and submission decisions | owner |
| `risks` | open risks, severity, mitigations, and closure evidence | owner + reviewers |

Runtime-only directories created inside the ignored workspace:

```text
runtime/sqlite/
runtime/private-evidence/
publication-staging/
```

The microdeal customer input, SQLite database, full private evidence, and
redacted staging artifact must remain in distinct real paths. Their fixed roots
are not owner-configurable: SQLite stays in `runtime/sqlite/`, full private
evidence stays in `runtime/private-evidence/`, and redacted output first lands
in `publication-staging/`. Symlinks and tracked/public destinations are
rejected before readiness.

## Current operating split

- The owner recruits the external design partner and obtains consent.
- Codex prepares the linked Arc testnet pilot and runs the dry-run.
- No transaction executes without a fresh, exact owner authorization.
- Video production is deferred.
- Financial and Devpost records remain draft-only until their evidence gates
  clear.

## Publication boundary

Private records are never promoted by moving them into a tracked directory.
Publication requires a separate `public_redacted` projection, explicit
publication consent, secret/PII scanning, source-digest verification, and owner
review.

No OKF record can authorize:

- mainnet;
- a different token, chain, payer, payee, or amount;
- more than one payment;
- customer/revenue classification;
- legal attestations;
- final Devpost submission.
