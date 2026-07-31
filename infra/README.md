# Deployment

The deployable boundary is intentionally split:

- **Public web origin:** the Next.js UI supports explicit DEMO mode and a LIVE
  backend-for-frontend flow. LIVE mutations require a signed, short-lived owner
  session; the API bearer token remains server-only. The web app is built as a
  standalone server so `next.config.ts` emits the enforced security headers.
- **Private API origin:** the FastAPI service is not a public browser API. Put it
  behind Cloud Run IAM, IAP, or service-to-service authentication.

The origins must be different. Do not expose the payment-capable routes through a
public rewrite from the web origin.

See `docs/DEPLOYMENT-SECURITY.md` for the complete boundary and current no-go items.

## Local offline API

```bash
cd projects/autonomerce
uv sync --frozen --extra api --extra gemini --extra test
. .venv/bin/activate

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

Local-only means loopback or an otherwise isolated development machine. Do not
publish this mode through a tunnel or public load balancer.

## Private Cloud Run API

The provided Cloud Run path is deliberately **offline-payment only**. The current
application implements durable SQLite commerce and payment stores, including
restart recovery when both stores use the same database file. Cloud Run's writable
container filesystem is disposable, while its NFS volume support does not provide
the file locking required by the supported SQLite topology. Therefore this
repository does not claim a safe durable live-payment configuration on Cloud Run.

Build and push the API image in CI, resolve the pushed image to an immutable digest,
then configure:

```bash
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export GOOGLE_CLOUD_REGION=us-central1
export AUTONOMERCE_API_IMAGE='us-central1-docker.pkg.dev/PROJECT/REPO/autonomerce-api@sha256:...'
export AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF='autonomerce-api-bearer:1'
export AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT='autonomerce-api@PROJECT.iam.gserviceaccount.com'
export AUTONOMERCE_ALLOWED_INVOKER='serviceAccount:trusted-caller@PROJECT.iam.gserviceaccount.com'
export AUTONOMERCE_API_AUTH_MODE=service-to-service
export AUTONOMERCE_WEB_PUBLIC_ORIGIN='https://app.example.com'
export AUTONOMERCE_API_PRIVATE_ORIGIN='https://autonomerce-api-HASH-uc.a.run.app'
export AUTONOMERCE_TRUSTED_HOSTS='autonomerce-api-HASH-uc.a.run.app'

./infra/deploy_cloud_run_api.sh
```

`infra/deploy_cloud_run_api.sh`:

- accepts only an image digest, never a mutable tag;
- injects the application bearer only from an explicit numeric Secret Manager
  version and rejects a direct token value;
- pins `AUTONOMERCE_PAYMENT_MODE=offline`;
- deploys with `--no-allow-unauthenticated`;
- selects ingress from the declared auth mode;
- pins one container request at a time and one maximum instance;
- grants `roles/run.invoker` only to the named principal;
- rejects `allUsers` and `allAuthenticatedUsers` after deployment.

The FastAPI host boundary also reads `AUTONOMERCE_TRUSTED_HOSTS`. The Cloud Run
helper requires and propagates an explicit host list, rejects wildcards and URLs,
and requires the private API origin host to be included. Do not weaken the
application to a wildcard host as a workaround.

### Private Gemini productization mode

The same private API helper can run real Vertex AI Gemini productization while
keeping payment and fulfillment offline:

```bash
export AUTONOMERCE_DEPLOYMENT_MODE=cloud-run-private-gemini
export AUTONOMERCE_GEMINI_MODEL=gemini-2.5-flash
export GOOGLE_CLOUD_LOCATION=global

./infra/deploy_cloud_run_api.sh
```

This mode sets `AUTONOMERCE_MODE=gemini`,
`AUTONOMERCE_PRODUCTIZER_MODE=gemini`, and
`GOOGLE_GENAI_USE_VERTEXAI=true`. It rejects payment, seller-executor,
fulfillment, and transaction-lookup factories. The runtime service account needs
only the Google permissions required for the chosen Vertex AI model plus Secret
Manager access to the application bearer. A successful deployment proves neither
Circle settlement nor seller fulfillment.

Choose one auth mode:

| Mode | Intended caller | Ingress |
|---|---|---|
| `cloud-run-iam` | explicitly authorized user/service identity with an ID token | `all`, but IAM-authenticated |
| `iap` | authenticated human access through Cloud Run IAP | `all`, with IAP enabled |
| `service-to-service` | internal workload using its service-account ID token | `internal` |

IAP and service-to-service still require a least-privilege
`AUTONOMERCE_ALLOWED_INVOKER`. Never use a wallet address, API idempotency key, or
browser CORS policy as caller authentication.

## Public Cloud Run web

`infra/Dockerfile.web` builds the standalone Next.js server with a digest-pinned
Node base and a non-root runtime. Build the application image in CI, resolve the
pushed image digest, then select one explicit deployment mode.

Safe public judging fallback:

```bash
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export GOOGLE_CLOUD_REGION=us-central1
export AUTONOMERCE_WEB_IMAGE='us-central1-docker.pkg.dev/PROJECT/REPO/autonomerce-web@sha256:...'
export AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT='autonomerce-web@PROJECT.iam.gserviceaccount.com'
export AUTONOMERCE_WEB_PUBLIC_ORIGIN='https://autonomerce-web-HASH-uc.a.run.app'
export AUTONOMERCE_WEB_MODE=DEMO

./infra/deploy_cloud_run_web.sh
```

DEMO rejects all private-backend and secret configuration, clears revision
secrets, labels the experience synthetic-only, and cannot enable funds movement.

LIVE is an owner-session-protected backend-for-frontend. It requires:

- a distinct private API origin;
- an explicit `AUTONOMERCE_API_IAM_AUTH=true|false` choice;
- for the recommended Cloud Run-to-Cloud Run path, an IAM audience exactly
  equal to the private API origin; the web runtime acquires a short-lived ID
  token from the metadata server and sends it in
  `X-Serverless-Authorization`, leaving `Authorization` available for the
  application bearer;
- the API bearer, owner token, and session signing secret as three distinct,
  numerically version-pinned Secret Manager references;
- the web service account as an authorized private API caller;
- concurrency one and one maximum instance; and
- an exact, explicit `AUTONOMERCE_ALLOW_MOVES_FUNDS=true` before the web can
  expose a payment mutation.

Example secret boundary:

```bash
export AUTONOMERCE_WEB_MODE=LIVE
export AUTONOMERCE_API_PRIVATE_ORIGIN='https://autonomerce-api-HASH-uc.a.run.app'
export AUTONOMERCE_API_IAM_AUTH=true
export AUTONOMERCE_API_IAM_AUDIENCE="$AUTONOMERCE_API_PRIVATE_ORIGIN"
export AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF='autonomerce-api-bearer:1'
export AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF='autonomerce-web-owner-token:1'
export AUTONOMERCE_WEB_SESSION_SECRET_REF='autonomerce-web-session-secret:1'
export AUTONOMERCE_ALLOW_MOVES_FUNDS=false

./infra/deploy_cloud_run_web.sh
```

Keep funds movement false for the Gemini-only judging deployment. A later
testnet proof must use the documented private single-host topology rather than
turning the Cloud Run API into a payment worker.

For this topology, deploy the API with
`AUTONOMERCE_API_AUTH_MODE=cloud-run-iam` and grant
`roles/run.invoker` to the web runtime service account. The API remains
unauthenticated-public **disabled** even though its ingress is reachable for IAM
validation. Do not set `AUTONOMERCE_API_IAM_AUTH=false` merely to make a failed
private call appear connected.

## Live payment modes

`AUTONOMERCE_PAYMENT_MODE=testnet` and `mainnet` use these real adapter names:

- `AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC`
- `AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC`
- `AUTONOMERCE_PAYMENT_MAX_COUNT`
- `AUTONOMERCE_PAYMENT_ALLOWED_CHAINS`
- `AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS`
- `AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS`
- `AUTONOMERCE_PAYMENT_SQLITE_PATH`
- `AUTONOMERCE_CIRCLE_CLI_BINARY`
- `AUTONOMERCE_CIRCLE_CLI_SHA256`
- `AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY`
- `AUTONOMERCE_RECEIPT_PUBLICATION_MODE` set explicitly to `disabled` or
  `verified`
- `AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY` when live receipt
  publication mode is `verified`
- `AUTONOMERCE_ENABLE_MAINNET_PAYMENTS`

`AUTONOMERCE_MODE` is the API-composition selector and must be `offline` for the
offline modes or `live` for a real payment mode. The legacy
`AUTONOMERCE_CIRCLE_*` network/wallet/cap aliases are not used by this deployment
configuration and are rejected by the runtime preflight; use the canonical
`AUTONOMERCE_PAYMENT_*` names above.

The single-host testnet/mainnet configuration requires:

- the application's single-owner bearer token;
- an external authenticated proxy;
- an explicit `AUTONOMERCE_TRUSTED_HOSTS` value for the private API host;
- one API worker;
- a deliberately provisioned persistent volume;
- both `AUTONOMERCE_PAYMENT_SQLITE_PATH` and
  `AUTONOMERCE_COMMERCE_SQLITE_PATH` set to the **same database file** inside that
  volume;
- an explicit Gemini model;
- an explicit seller-agent executor factory;
- strict payer/payee/chain and USDC caps;
- a pinned Circle CLI SHA-256 checked before startup and immediately before
  every transfer;
- an independent transaction-lookup factory that verifies confirmation,
  chain, canonical USDC contract, amount, payer, payee, and transaction hash.

This mode is suitable for a single Google Compute Engine VM with a persistent disk,
not Cloud Run. The runtime preflight constructs both durable repositories and fails
before startup if the paths differ or the configuration is incomplete. Sharing one
SQLite database is the supported crash-reconciliation boundary; it is not a claim
of multi-host availability or distributed durability. Mainnet still requires the
exact explicit mainnet confirmation value and an owner-reviewed low-value wallet
policy.

## Owner web session

The public web proxy is no longer an unauthenticated bearer-token deputy. LIVE
onboarding and workflow routes require:

- `AUTONOMERCE_WEB_OWNER_TOKEN`, submitted only to the same-origin login route;
- `AUTONOMERCE_WEB_SESSION_SECRET`, a distinct server-only signing secret of at
  least 32 characters; and
- `AUTONOMERCE_API_BEARER_TOKEN`, used only by the server-side private API client.

The owner token, session secret, and API bearer token must all be different. The
login route issues a signed 15-minute `HttpOnly`, `SameSite=Strict` cookie; it is not
federated identity, multi-tenant authorization, or proof of buyer consent.

## Reproducible API image inputs

The API image now uses a digest-pinned Python base, copies the committed `uv.lock`,
and installs with `uv sync --frozen`. The lock records resolved artifact hashes, and
the Cloud Run helper separately requires the final application image by digest.
These controls close the prior floating Python/base-image statements. They do not
provide an SBOM, build provenance attestation, current vulnerability scan, or a
digest-pinned Circle CLI.

## Rollback

Cloud Run preserves revisions. Route traffic to a previously verified private
revision instead of deleting the service. Re-run the IAM-policy check after every
rollback or traffic change; a safe image revision does not compensate for a public
invoker binding.
