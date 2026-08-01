# Automation connection plan

## Current state — August 1, 2026

- Google Cloud authentication is complete for project
  `gen-lang-client-0791755511`.
- Circle testnet login is complete.
- The official Devpost MCP endpoint is configured, but the current Codex process
  has no `DEVPOST_MCP_TOKEN` environment variable and exposes no Devpost tools.

The product can still be built and tested offline. Devpost mutations remain
blocked until a fresh bearer token is injected into a newly started Codex
process.

Repository-side automation is already present for the private API, web owner
session, and deployment preflight. The browser owner session is separate from
Google, Circle, GitHub, and Devpost authentication: it authorizes LIVE mutations in
the Autonomerce web proxy but does not complete any external provider login.

## Devpost

Official MCP endpoint:

```text
https://devpost.com/mcp
```

Advertised bearer scopes:

```text
mcp:tools
mcp:read
mcp:write
```

The bearer token previously pasted into chat must be revoked. Create a fresh
token and inject it without placing it in chat or the repository:

```zsh
read -s "DEVPOST_MCP_TOKEN?Fresh Devpost MCP token: "
echo
export DEVPOST_MCP_TOKEN

codex mcp remove devpost
codex mcp add devpost \
  --url https://devpost.com/mcp \
  --bearer-token-env-var DEVPOST_MCP_TOKEN

codex mcp list
codex
```

The Codex process must start from the same shell so it inherits the token. After
the session ends:

```zsh
unset DEVPOST_MCP_TOKEN
```

Target draft:

```text
project ID: 1368519
slug: autonomerce
```

Old draft IDs requested for deletion:

```text
1367683
1367682
1363845
```

After authentication, enumerate the MCP tool list before mutation. Use only
tools exposed by the official server and restrict all edits to project
`1368519`. Draft deletion, binary uploads, or legal submission may remain
unsupported and require the UI.

The owner must still review residence/eligibility, legal attestations, and
perform the final submit action.

## Google Cloud and Gemini

Preferred authentication:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

The product uses Application Default Credentials with Vertex AI.

Optional automation:

- Google Cloud MCP server with scoped IAM;
- Google Cloud CLI authenticated as the owner;
- a least-privilege service account stored in Secret Manager.

Official resources:

- `https://docs.cloud.google.com/mcp/overview`
- `https://cloud.google.com/docs/authentication/provide-credentials-adc`
- `https://cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart`

Do not provide an unrestricted owner service-account key if ADC or workload identity is
available.

## Circle

Preferred authentication:

```bash
circle wallet login OWNER_EMAIL
```

The owner enters the email OTP. The agent uses the resulting CLI session.

Optional automation:

- Circle CLI adapter;
- Circle MCP server for Circle SDK/tool code generation;
- Circle Agent Stack starter-kit MCP server;
- direct Agent Wallet API through a least-privilege server credential.

Official resources:

- `https://developers.circle.com/agent-stack/agent-wallets/quickstart`
- `https://developers.circle.com/agent-stack/agent-wallets/wallet-operations/custom-policies`
- `https://github.com/circlefin/circle-mcp-server`
- `https://developers.circle.com/agent-stack/mcp-server`

The owner must set wallet policies before mainnet funding. Do not provide OTPs, recovery
material, or Circle session tokens in chat.

The official Circle MCP server is an integration/code-generation aid; it does
not replace the owner's wallet login, OTP, wallet policy, or the application's
independent settlement verification.

For the supported private single-host payment topology, automation must preserve
these storage invariants:

- one persistent, operator-provisioned mount;
- one API worker;
- `AUTONOMERCE_PAYMENT_SQLITE_PATH` and
  `AUTONOMERCE_COMMERCE_SQLITE_PATH` set to the same SQLite file; and
- the durable-volume marker required by `infra/runtime_preflight.py`.

Both commerce and payment state are durable in that database. This is not a
distributed store and must not be described as safe for multiple instances or
Cloud Run live payment.

Every testnet/mainnet deployment must also configure:

- `AUTONOMERCE_CIRCLE_CLI_SHA256` for the reviewed absolute CLI binary; and
- `AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY` as `module:function`.
- `AUTONOMERCE_RECEIPT_PUBLICATION_MODE` as either `disabled` or `verified`.
- `AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY` as `module:function`
  whenever publication mode is `verified`.

The lookup factory returns a callable receiving a transaction hash. Its evidence
must independently report `confirmed`, `chain`, `amountUsdc`, `payerWallet`,
`payeeWallet`, `transactionHash`, `token`, and canonical USDC `asset`. Normal
live payment confirmation fails closed without this lookup; CLI output alone is
not sufficient.

The publication-consent factory returns a callable that receives keyword
arguments `proposal`, `prospect`, `consent_reference`, and `fields`. It must
return exactly `True` only after verifying a durable consent record whose
purpose is receipt publication and whose subject/scope covers that order and
field set. Without the verifier, non-offline receipt publication returns `503`.
Offline fixtures still require a separate `publication:` reference and cannot
reuse or alias the buyer-contact reference.

## GitHub

Preferred:

```bash
gh auth login
gh auth status
```

The agent can then create the public repository, push the subtree branch, open a PR, and
monitor CI. The owner should review repository visibility and contest evidence before launch.

## Other service APIs

Preferred order:

1. purpose-built MCP connector;
2. authenticated CLI session;
3. workload identity or OAuth;
4. Secret Manager;
5. untracked local environment variable as a temporary fallback.

Never:

- paste a secret into chat;
- commit `.env`;
- put a key in browser JavaScript;
- use one unrestricted key across development and production;
- give a worker agent access to unrelated accounts.

## Repository automation entrypoints

The shell entrypoints are committed executable and should be invoked directly:

```bash
./infra/start_api.sh
./infra/deploy_cloud_run_api.sh
./scripts/preflight_google.sh
./scripts/preflight_circle.sh
./scripts/test_offline.sh
./scripts/export_public_repo.sh
```

The API container uses the committed, hash-bearing `uv.lock`, installs with
`uv sync --frozen`, and starts from a digest-pinned Python base. The Cloud Run helper
also requires the final application image by digest. These facts do not prove a
current vulnerability-free image or an SBOM/provenance attestation. The supported
single-host live path separately requires a reviewed Circle CLI SHA-256 and an
independent transaction-lookup factory.

The current Cloud Run helper remains offline-payment-only. It requires and
propagates `AUTONOMERCE_TRUSTED_HOSTS`, rejects wildcard and URL values, and
requires the configured private API origin host to be included. Do not use `*`
as a production workaround.

The public web ignores `X-Forwarded-For`, `X-Real-IP`, Cloudflare, and Vercel
forwarding headers by default. Set
`AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=true` only when the directly attached
trusted edge strips or overwrites client-supplied forwarding headers. The web
process also applies bounded per-address and process-global login/status
budgets; horizontally scaled deployments still require an edge or shared
distributed rate limiter.

## Owner-only actions

- accept terms;
- complete OTP/KYC/account verification;
- link billing;
- fund mainnet;
- approve wallet policy;
- approve publication of transaction evidence;
- final Devpost legal attestation and submit.

Everything else can be automated after the authenticated sessions are available.

For the Autonomerce web proxy specifically, the owner login route issues a signed
15-minute `HttpOnly`, `SameSite=Strict` session cookie. Its
`AUTONOMERCE_WEB_OWNER_TOKEN` and `AUTONOMERCE_WEB_SESSION_SECRET` remain
server-only and distinct from the private API bearer token. This is a single-owner
control, not federated or multi-tenant identity.
