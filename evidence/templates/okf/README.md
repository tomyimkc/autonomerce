# Autonomerce private OKF workspace templates

These templates are copied into an ignored workspace by:

```bash
python3 scripts/manage_okf_records.py init \
  --root evidence/private/okf
```

Template files are not evidence and are skipped by validation. Copy a template
to `<record-id>.json`, replace every placeholder, and run `validate`.

The existing microdeal runner also requires a separate private customer input:

```text
external-customer-record.template.json
```

Copy that file into the ignored private workspace, replace its IDs, buyer-agent
URL, claims, and sources, and reference the resulting path from the linked
authorization record. It is operational input, not a public OKF record.

The eventual redacted execution record must match:

```text
external-testnet-microdeal.public.schema.json
```

The schema fixes the evidence to Arc testnet, canonical USDC, 0.10 USDC,
founder-sponsored funding, `countedAsRevenue=false`, `payingCustomer=false`,
redacted wallets, independent lookup, and idempotent replay.

`init` creates private workspace-owned runtime boundaries:

```text
runtime/sqlite/
runtime/private-evidence/
publication-staging/
```

Authorization records must point the SQLite database and evidence outputs into
those directories. Readiness rejects symlinks, directories used as files,
tracked/public project destinations, and one authorization shared by multiple
active pilots.

Never commit the initialized private workspace. The project `.gitignore`
excludes `evidence/private/`.
