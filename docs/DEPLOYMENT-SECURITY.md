# Deployment security boundary

**Status:** hardened configuration for offline deployment and a private,
single-host live-payment pilot; not approval for internet-exposed live payment or
mainnet production.

## 1. Required origin separation

Autonomerce has two different trust zones:

| Origin | Exposure | Allowed contents |
|---|---|---|
| `AUTONOMERCE_WEB_PUBLIC_ORIGIN` | Public | DEMO assets plus owner-session-protected LIVE backend-for-frontend routes |
| `AUTONOMERCE_API_PRIVATE_ORIGIN` | Private | FastAPI operational, mutation, fulfillment, and payment-capable routes |

The origins must not be equal. The browser must not receive the private API origin
or bearer token. LIVE mode uses fixed same-origin Next.js routes as a
backend-for-frontend; those routes require a signed owner session and call the
private API server-side. Do not add a direct browser rewrite for `/pay`, private
receipts, fulfillment artifacts, OpenAPI, or arbitrary API paths.

## 2. Explicit deployment modes

`infra/runtime_preflight.py` accepts only these mode pairs:

| `AUTONOMERCE_DEPLOYMENT_MODE` | Required runtime mode | Required payment mode | Boundary |
|---|---|---|---|
| `local-offline` | `offline` | `offline` | Loopback/isolated developer machine only |
| `cloud-run-private-offline` | `offline` | `offline` | Cloud Run IAM, IAP, or service-to-service |
| `private-single-host-testnet` | `live` | `testnet` | Supported private pilot shape on one persistent Compute Engine host |
| `private-single-host-mainnet` | `live` | `mainnet` | Configuration shape only; release no-go |

Cloud Run testnet/mainnet is blocked at startup. The current live adapter only has
SQLite. Cloud Run local storage does not survive instance replacement, and Cloud Run
NFS volumes do not provide the file locking SQLite requires. A shared managed
commerce/payment/reconciliation store must be implemented in application code
before a live-payment Cloud Run mode can be added.

The single-host live mode now persists the complete commerce aggregate and payment
state in SQLite. Runtime preflight requires both configured paths to resolve to the
same database file so restart recovery can reconcile externally confirmed payments
with proposal state. This is durable for the documented one-worker persistent-host
topology only; it is not distributed durability or high availability.

## 3. Layered authentication

The application now has a single-owner bearer authenticator and owner scoping for
private routes. This is a useful fail-closed application boundary for non-offline
mode, but it is still a static, single-tenant credential rather than federated
OIDC/IAP identity or role-based multi-tenant authorization. Therefore:

1. Never use `--allow-unauthenticated`.
2. Keep the API behind exactly one declared external control:
   - `cloud-run-iam`;
   - `iap`;
   - `service-to-service`; or
   - `external-auth-proxy` for a non-Cloud-Run single host.
3. Grant `roles/run.invoker` only to named users, groups, or service accounts.
4. Reject `allUsers` and `allAuthenticatedUsers`.
5. For machine callers, use short-lived audience-bound ID tokens from the caller's
   service account at the Cloud Run boundary.
6. For non-offline application mode, inject `AUTONOMERCE_API_BEARER_TOKEN` from an
   approved secret store and set `AUTONOMERCE_API_OWNER_ID`; never commit the token.
7. Treat the application bearer and Cloud Run IAM/IAP as layered coarse controls.
   They do not provide separate buyer/seller identities or role-scoped multi-tenant
   authorization.

The public web proxy additionally implements a dedicated owner login. Successful
login issues a signed 15-minute `HttpOnly`, `SameSite=Strict` cookie. LIVE
onboarding and workflow routes reject missing, forged, or expired owner sessions.
`AUTONOMERCE_WEB_OWNER_TOKEN`, `AUTONOMERCE_WEB_SESSION_SECRET`, and
`AUTONOMERCE_API_BEARER_TOKEN` must be distinct server-only values. This closes the
unauthenticated web-deputy condition, but it does not create federated identity,
multi-role authorization, or verified buyer consent.

Forwarding headers are ignored unless
`AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=true`. Enable that switch only behind a
trusted edge that strips or overwrites client-supplied forwarding headers. Login
and public-status limits include both bounded per-address state and a
process-global budget. A multi-instance deployment still needs an edge or shared
distributed limiter.

The provided deployment script supports only the private offline Cloud Run mode and
checks the resulting invoker policy. Live payment on Cloud Run remains blocked by
the unsupported storage topology. The helper requires and propagates
`AUTONOMERCE_TRUSTED_HOSTS`, rejects wildcard and URL values, and requires the
configured private API origin host to be included.

## 4. Runtime preflight

The API container starts through `infra/start_api.sh`, which runs
`infra/runtime_preflight.py` before Uvicorn. Startup fails closed when:

- a legacy Circle network/wallet/cap alias is present instead of the canonical
  payment-adapter names;
- deployment mode, `AUTONOMERCE_MODE`, and `AUTONOMERCE_PAYMENT_MODE` disagree;
- a private mode lacks an accepted external authentication mode;
- a non-offline mode lacks the application owner ID or bearer token;
- Cloud Run lacks the expected `K_SERVICE` runtime marker;
- the public web and private API origins are equal, malformed, or non-HTTPS;
- a live single-host mode lacks wallet/chain allowlists or bounded payment caps;
- the Circle CLI executable is missing;
- either SQLite path is outside the declared persistent mount;
- the commerce and payment SQLite paths are not the same database file;
- the persistent mount lacks the operator-provisioned marker; or
- the real payment adapter or durable commerce repository cannot be constructed
  exactly as configured.

Live deployments must explicitly set
`AUTONOMERCE_RECEIPT_PUBLICATION_MODE=disabled` or `verified`. Verified
publication additionally requires
`AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY=module:function` to construct a
callable that verifies the publication-specific consent record for the exact
proposal and requested public field set. Preflight imports the factory and
requires it to return a callable before starting the live service.

The FastAPI factory separately rejects non-offline startup without an explicit
trusted-host configuration.

For a non-Cloud-Run persistent single-host volume, provision this marker before
startup:

```bash
printf '%s\n' AUTONOMERCE_DURABLE_STORE_V1 \
  > /persistent/autonomerce/.autonomerce-durable-volume
```

Then set:

```bash
AUTONOMERCE_PAYMENT_STORE_DURABILITY=single-host-persistent-volume
AUTONOMERCE_PAYMENT_DURABLE_MOUNT_PATH=/persistent/autonomerce
AUTONOMERCE_PAYMENT_SQLITE_PATH=/persistent/autonomerce/autonomerce.sqlite3
AUTONOMERCE_COMMERCE_SQLITE_PATH=/persistent/autonomerce/autonomerce.sqlite3
AUTONOMERCE_TRUSTED_HOSTS=private-api.example.com
```

The marker proves deliberate provisioning, not replication or availability. SQLite
is only documented for one process on one persistent host. Do not place it on Cloud
Run NFS, Cloud Storage FUSE, an ephemeral container path, or a multi-instance shared
filesystem.

## 5. Web security headers

`apps/web/next.config.ts` applies the following to every route:

- enforced Content Security Policy;
- `frame-ancestors 'none'` plus `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- restrictive `Permissions-Policy`;
- same-origin opener/resource policies;
- HSTS for HTTPS deployments; and
- removal of the `X-Powered-By` header.

The CSP has no remote script, style, frame, API, wallet, analytics, or font origin.
It retains `'unsafe-inline'` for scripts and styles because the current static Next
App Router output includes inline hydration data and generated styles. It does not
allow `'unsafe-eval'`. Revisit the policy if the web application adds third-party
content, API calls, wallet SDKs, analytics, or user-authored HTML.

The web build is pinned to Next's `standalone` output so these headers are emitted by
the deployed server. If the UI is exported to a CDN later, reproduce and test the
same headers at the CDN because static files cannot emit HTTP response headers.

The FastAPI service separately emits API security headers and uses trusted-host
middleware. In non-offline mode, OpenAPI, Swagger UI, and ReDoc routes are disabled.
Offline mode retains the documentation routes for local development.

## 6. Secrets and payment credentials

- Use the Cloud Run runtime service account and Application Default Credentials for
  Google APIs. Do not mount a service-account JSON key.
- Do not put Circle OTPs, recovery material, private keys, wallet session state, or
  bearer tokens in committed `.env` files. Inject the application bearer token from
  an approved secret store when non-offline mode is eventually enabled.
- The reference Dockerfile does not install or authenticate the Circle CLI. The
  supported single-host live path installs it separately, requires
  `AUTONOMERCE_CIRCLE_CLI_SHA256`, verifies that digest at startup and immediately
  before every transfer, and still requires a reviewed authentication mechanism.
- Wallet addresses and allowlists are not secret, but changes to them are
  security-sensitive configuration and require review.
- Keep operating balances and per-payment/total/count caps low even in testnet.

## 7. Mainnet release gate

Mainnet is not approved by these configuration changes. Before enabling it, require:

- separate authenticated buyer/seller subjects and role-scoped tenant ownership
  beyond the current single-owner bearer model;
- an internal payment worker that is not a general public route;
- a shared managed durable idempotency and reconciliation store;
- immutable audit records and ambiguous-transfer recovery;
- wallet-side destination and spend policy;
- reviewed publication consent and private receipt handling;
- load/restart/crash tests against the final topology;
- an independently verified Circle integration; and
- an operator-approved rollback and incident procedure.

Do not interpret a passing infra preflight as proof that those controls exist.

## 8. Supply-chain boundary

The prior floating Python/base-image statements are stale:

1. `infra/Dockerfile.api` pins the Python base by digest.
2. The image copies the committed `uv.lock` and installs with `uv sync --frozen`.
3. The lock contains resolved artifact hashes.
4. The deploy helper requires the final application image by digest.

These controls make the declared Python resolution and base-image input
reproducible within the repository build. They do not establish bit-for-bit build
reproducibility, an SBOM, provenance attestation, a fresh dependency/container
advisory scan, or a digest-pinned Circle CLI. Those remain production release work.
