# Autonomerce

**Give every AI agent a sales department.**

Autonomerce is a portable A2A revenue operator. It turns an existing A2A, MCP,
OpenAPI, or custom agent into an autonomous seller that can:

1. productize capabilities into machine-readable offers;
2. discover opted-in prospective buyers;
3. pitch and negotiate within owner policy;
4. receive USDC through Circle;
5. route paid work to the seller agent;
6. validate and deliver the result;
7. produce auditable commercial receipts.

`candidateOnly: true` · `canClaimAGI: false`

**Judges and reviewers:** start with the
[`30-second quickstart`](docs/submission/JUDGE-QUICKSTART.md), then inspect the
[`claim-to-proof evidence index`](docs/submission/EVIDENCE-INDEX.md). The public
Cloud Run application now uses live Vertex AI Gemini productization behind a
private IAM-protected API. Separately, the guarded Circle lane has one
independently verified 0.10 USDC Arc testnet Agent Wallet transfer with durable
idempotent replay. It is not customer revenue and is not yet linked to the
deployed Gemini order or fulfillment.

**Public application:**
`https://autonomerce-web-6dnob6ekdq-uc.a.run.app`

## Why it exists

Useful agents do not automatically have a business. Their owners still need to
define an offer, find interested buyers, negotiate safe terms, collect payment,
route work, judge delivery, and prove what happened.

Autonomerce composes those steps into one policy-controlled commercial loop:

```text
seller Agent Card / MCP / OpenAPI capability
-> Gemini-assisted service productization
-> owner commercial policy
-> opted-in buyer need
-> machine-readable proposal
-> bounded negotiation
-> Circle USDC settlement
-> seller fulfillment
-> deterministic validation
-> delivery and revenue receipt
```

The first demonstrated seller is a source-verification/evidence-pack agent. The
architecture is intended to support other callable agents without giving a
model authority over wallets or acceptance.

## Contest target

- Build with Gemini XPRIZE
- Circle Agentic Economy Prize
- Category: Entrepreneurship & Job Creation
- Deadline: 2026-08-17 13:00 PDT / 2026-08-18 04:00 HKT

## What is implemented

- exact-money domain contracts and deterministic identifiers;
- OfferRail catalog, proposal, policy, negotiation, idempotency, and
  hash-chained receipt primitives;
- structured Gemini provider plus a credential-free deterministic provider;
- model-authority boundary: Gemini may recommend copy/relevance but cannot set
  price, wallet, token, chain, capacity, latency, or acceptance criteria;
- A2A Agent Card parsing, opted-in prospect registration, matching, and
  rate-limited pitching;
- Circle/x402 payment adapter with policy caps, durable idempotency, ambiguous
  execution handling, and reconciliation primitives;
- built-in verification seller and constrained HTTPS seller executor;
- durable SQLite commerce and payment state for the supported single-host live
  topology;
- owner-authenticated FastAPI and Next.js LIVE flow;
- explicit receipt publication and private-artifact hashing;
- exact buyer-need/proposal binding so fulfillment uses the accepted order input;
- immutable live payer selection from the owner-configured payment allowlist;
- asset-preserving shared-SQLite crash recovery before a proposal becomes paid;
- deterministic offline demo, adversarial tests, threat model, and deployment
  preflight.

## Quickstart: credential-free offline demo

Prerequisites:

- Python 3.11 or newer;
- `uv`;
- Node.js 20.9 or newer for the web application.

From this standalone repository:

```bash
uv sync --frozen --extra api --extra gemini --extra test

PYTHONPATH=apps/api:packages/offerrail:. \
  python3 examples/run_offline_demo.py
```

From the parent Sophia repository:

```bash
cd projects/autonomerce
uv sync --frozen --extra api --extra gemini --extra test

PYTHONPATH=apps/api:packages/offerrail:. \
  python3 examples/run_offline_demo.py
```

Expected properties of the offline output:

- `diagnostics.offline` is `true`;
- `diagnostics.networkCalls` is `0`;
- `diagnostics.credentialsUsed` is `false`;
- `diagnostics.realFundsMoved` is `false`;
- one simulated payment executor call serves an idempotent replay;
- four receipt-ledger entries verify as one hash chain.

The fixture transaction hash and revenue amount are synthetic. They are not
Circle transaction proof or customer revenue.

## Run the API locally

```bash
export AUTONOMERCE_DEPLOYMENT_MODE=local-offline
export AUTONOMERCE_MODE=offline
export AUTONOMERCE_API_AUTH_MODE=local-only
export AUTONOMERCE_API_OWNER_ID=autonomerce-owner
export AUTONOMERCE_WEB_PUBLIC_ORIGIN=http://localhost:3000
export AUTONOMERCE_API_PRIVATE_ORIGIN=http://127.0.0.1:8000
export AUTONOMERCE_PAYMENT_MODE=offline
export AUTONOMERCE_PAYMENT_STORE_DURABILITY=memory-offline
export PORT=8000

./infra/start_api.sh
```

`local-only` is for loopback or an otherwise isolated development machine. Do
not publish it through a tunnel.

## Run the web application

```bash
cd apps/web
npm ci
npm run dev
```

DEMO mode is the default and is deliberately synthetic. LIVE mode uses
server-side proxy routes, a signed short-lived owner session, and a private API
bearer that is never returned to browser code. See
[`apps/web/README.md`](apps/web/README.md).

## Test and verify

```bash
./scripts/release_preflight.sh
```

Or run the component checks:

```bash
PYTHONPATH=apps/api:packages/offerrail:. \
  python3 -m pytest -q tests

cd apps/web
npm run check
cd ../..

python3 scripts/scan_public_secrets.py

python3 scripts/build_xprize_product_evidence.py \
  --output /tmp/autonomerce-xprize-product-evidence.zip

python3 scripts/build_xprize_product_evidence.py \
  --verify /tmp/autonomerce-xprize-product-evidence.zip
```

When this project is developed inside Sophia, also run:

```bash
python3 ../../tools/lint_claims.py
```

## Trust boundaries

### Gemini may

- interpret capability copy;
- recommend display names and relevance;
- assist buyer-fit, proposal, and bounded-negotiation decisions;
- summarize delivery evidence.

### Deterministic code must

- authorize price, discount, expiry, buyer, capacity, token, chain, wallets,
  payment amount, idempotency, and public disclosure;
- independently confirm settlement;
- validate seller output against the accepted contract;
- keep payment confirmation distinct from delivery acceptance.

### Circle executes

- an owner-policy-constrained USDC settlement through the configured Agent
  Wallet path.

The repository never accepts OTPs, wallet recovery material, or unrestricted
credentials through its API.

## Runtime modes

| Mode | Gemini | Payment | Intended use |
|---|---|---|---|
| Offline | deterministic provider | simulated | reproducible development and judging fallback |
| Testnet | configured live provider | Circle testnet | integration proof, not revenue |
| Mainnet | configured live provider | tightly capped Circle mainnet | owner-approved external paid pilot |

Live payment modes require one owner, one API worker, strict wallet allowlists
and caps, an explicit seller executor, and a single persistent SQLite database
shared by commerce and payment state. Cloud Run is currently documented for the
offline-payment API path; the supported live topology is a single Compute
Engine host with persistent disk.

## Repository map

```text
apps/api/autonomerce/agents/     Gemini and deterministic decisions
apps/api/autonomerce/api/        authenticated FastAPI composition
apps/api/autonomerce/payments/   Circle/x402, policy, storage, reconciliation
apps/api/autonomerce/sales/      Agent Cards, prospects, proposals, fulfillment
apps/web/                        Next.js product and LIVE backend-for-frontend
packages/offerrail/              portable commercial protocol primitives
examples/                        deterministic fixtures and offline demo
security/                        controls and threat-model support
tests/                           unit, integration, adversarial, persistence
docs/submission/                 Devpost, video, evidence, and judge checklists
Product_Evidence/                deterministic XPRIZE evidence package sources
wiki/                            tracked OKF record profile and index
evidence/templates/okf/          private-workspace record templates
infra/                           container, preflight, Cloud Run, Compute Engine
```

The XPRIZE package reports zero qualifying revenue and zero verified external
users because no approved public business evidence supports a positive value.
Its actual expense and net profit/loss fields remain unknown rather than
inferring missing billing records as zero. See
[`Product_Evidence/README.md`](Product_Evidence/README.md).

## Private OKF record workspace

Autonomerce keeps customer identity, consent, wallet bindings, pilot
authorization, payment, fulfillment, financial, video, and Devpost working
records in an ignored local workspace:

```bash
python3 scripts/manage_okf_records.py init \
  --root evidence/private/okf

python3 scripts/manage_okf_records.py validate \
  --root evidence/private/okf

python3 scripts/manage_okf_records.py build \
  --root evidence/private/okf
```

The workspace uses canonical JSON records and deterministic Markdown
OKF/LLM-Wiki projections. Generated pages contain summaries, provenance links,
claim boundaries, and content digests without copying arbitrary private fields.

See [`wiki/INDEX.md`](wiki/INDEX.md) and
[`wiki/schema/autonomerce-record-profile.md`](wiki/schema/autonomerce-record-profile.md).

The external design-partner pilot can be checked without execution:

```bash
python3 scripts/manage_okf_records.py pilot-readiness \
  --root evidence/private/okf \
  --pilot-id pilot-example
```

Readiness emits a dry-run command only. It never moves funds and always leaves
execution blocked pending fresh, exact owner approval.

## Deployment

Start with [`infra/README.md`](infra/README.md) and
[`docs/DEPLOYMENT-SECURITY.md`](docs/DEPLOYMENT-SECURITY.md).

The judging deployment is split into a public owner-session-protected Next.js
BFF and a private Cloud Run IAM API. Its redacted build identity and one deployed
Gemini productization receipt are in [`evidence/public/`](evidence/public/).
The same directory also contains a separately executed Circle Agent Wallet Arc
testnet transaction and redacted policy evidence.

The repository intentionally fails closed when required live settings are
missing or contradictory. Do not weaken trusted hosts, durability checks,
wallet allowlists, amount caps, or owner authentication to make a deployment
start.

## Evidence and claim boundary

Active contest build. Credential-free offline mode and deterministic tests remain
the reproducible fallback. A deployed Cloud Run order has now verified the
Gemini productization lane with a private API, synthetic buyer/seller data, mock
payment, and deterministic offline fulfillment.

At this repository snapshot:

- one redacted deployed Gemini productization receipt is committed;
- the public web deployment is connected to the private IAM-protected API;
- one founder-owned Circle Agent Wallet transfer of 0.10 testnet USDC is
  independently verified and committed;
- the deployed Cloud Run order still uses offline payment, and the testnet
  transfer is not yet linked to deployed Gemini productization or fulfillment;
- no external customer, revenue, margin, or production-availability claim is
  approved.

Read [`docs/submission/KNOWN-LIMITATIONS.md`](docs/submission/KNOWN-LIMITATIONS.md)
before using public copy or footage.

## Contributing

Read [`PROJECT-CONTRACT.md`](PROJECT-CONTRACT.md) before changing code.

Every change must preserve:

- exact decimal money;
- deterministic authorization;
- idempotent settlement;
- opt-in outreach;
- private artifact handling;
- explicit testnet/mainnet labeling;
- the no-overclaim boundary.

## License

Apache-2.0. See [`LICENSE`](LICENSE), [`NOTICE`](NOTICE), and
[`PREEXISTING-ASSET-DISCLOSURE.md`](PREEXISTING-ASSET-DISCLOSURE.md).
