# Autonomerce Product Evidence

`snapshot: 2026-08-01` · `candidateOnly: true` · `canClaimAGI: false`

This directory is the tracked source for the Build with Gemini
`Product_Evidence/` submission package. It contains only claim-bounded,
public-reviewable text artifacts. The deterministic builder also copies the
approved Gemini, Circle, Cloud, CI, financial-method, disclosure, and
limitations records into a self-contained ZIP.

## Current evidence boundary

- A deployed Vertex AI Gemini productization call is recorded for one synthetic
  seller capability.
- A public Cloud Run web service is connected to a private IAM-protected API;
  payment in that deployed trace is offline and synthetic.
- One founder-owned Circle Agent Wallet transfer of `0.10` testnet USDC on Arc
  testnet is independently recorded and explicitly excluded from revenue.
- No approved public evidence establishes an external customer, paying user,
  qualifying revenue, complete contest expense ledger, actual profit/loss, or
  production readiness.
- Screenshot files are not fabricated. The package contains an explicit
  owner-only capture and redaction checklist instead.

## Financial interpretation

[`financial/may-august-breakdown.json`](financial/may-august-breakdown.json)
uses zero for the amount/count currently supported by approved public evidence:
qualifying recognized revenue, verified expense records, and verified external
users. It does **not** infer that actual expenses or actual net profit/loss are
zero. Those fields remain `null` while the expense ledger is incomplete.

The July testnet transfer is listed only as excluded technical evidence:

```text
testnet settlement volume: 0.10 USDC
qualifying recognized revenue: USD 0
counted as customer revenue: false
```

## Build and verify

From the Autonomerce project root:

```bash
python3 scripts/build_xprize_product_evidence.py \
  --output /tmp/autonomerce-xprize-product-evidence.zip

python3 scripts/build_xprize_product_evidence.py \
  --verify /tmp/autonomerce-xprize-product-evidence.zip
```

The builder:

1. reads an explicit allowlist from
   [`archive-files.json`](archive-files.json);
2. rejects traversal, absolute paths, private/generated paths, symlinks,
   non-files, binary content, likely secrets, email addresses, and local home
   paths;
3. fixes ZIP timestamps and file modes;
4. emits `Product_Evidence/MANIFEST.json` with SHA-256 and size for every
   payload;
5. reopens the ZIP and verifies all manifest hashes before reporting success.

The generated archive belongs under ignored `dist/` or another temporary
location. Do not commit the ZIP as a substitute for reviewing its source
artifacts.

## Read order

1. [`EVIDENCE-INDEX.md`](EVIDENCE-INDEX.md)
2. [`financial/P_AND_L.md`](financial/P_AND_L.md)
3. [`financial/may-august-breakdown.json`](financial/may-august-breakdown.json)
4. [`PRE-MAY-19-RESOURCES.md`](PRE-MAY-19-RESOURCES.md)
5. [`screenshots/README.md`](screenshots/README.md)
6. generated `MANIFEST.json` inside the archive

Archive determinism and manifest integrity establish reproducible packaging,
not owner approval, contest eligibility, evidence completeness, or a business
result.
