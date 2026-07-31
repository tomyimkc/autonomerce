# Autonomerce Web

Standalone owner and revenue console for Autonomerce.

The polished local replay remains available as explicit **DEMO** mode. **LIVE**
mode calls only same-origin Next.js routes. Those server routes call the private
API with `AUTONOMERCE_API_BASE_URL` (falling back to the deployment-standard
`AUTONOMERCE_API_PRIVATE_ORIGIN`) and
`AUTONOMERCE_API_BEARER_TOKEN`; neither value is exposed to browser code or read
from `NEXT_PUBLIC_*`.

LIVE mutations additionally require an owner login. The browser submits the
dedicated `AUTONOMERCE_WEB_OWNER_TOKEN` once to a same-origin login route and
receives a signed 15-minute `HttpOnly`, `SameSite=Strict` cookie. Cookie signing
uses the separate server-only `AUTONOMERCE_WEB_SESSION_SECRET`. The owner token,
API bearer token, and session secret must all be different and must never use a
`NEXT_PUBLIC_*` name.

## Run locally

```bash
cd projects/autonomerce/apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

For LIVE mode:

```bash
export AUTONOMERCE_API_BASE_URL=http://127.0.0.1:8000
# Or use the existing deployment variable instead:
# export AUTONOMERCE_API_PRIVATE_ORIGIN=http://127.0.0.1:8000
export AUTONOMERCE_API_BEARER_TOKEN=replace-with-a-server-only-token
export AUTONOMERCE_WEB_OWNER_TOKEN="$(openssl rand -base64 32)"
export AUTONOMERCE_WEB_SESSION_SECRET="$(openssl rand -hex 32)"
# Only enable behind a trusted proxy that overwrites forwarding headers:
# export AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=true
```

If both API URL variables are set, their normalized values must match exactly;
the web server fails closed rather than choosing one. `AUTONOMERCE_API_BASE_URL`
therefore remains available for web-specific deployments while
`AUTONOMERCE_API_PRIVATE_ORIGIN` is the documented compatibility fallback.

The backend `/health` response must explicitly include `paymentMode` and
`movesFunds`. Missing fields produce a disconnected state. If `movesFunds=true`,
workflow execution is locked unless the deployment separately sets the
server-only `AUTONOMERCE_ALLOW_MOVES_FUNDS=true`. The onboarding and workflow
proxy routes reject requests without a valid owner session.
Owner-login failures receive per-address exponential backoff and a bounded
failure window. Forwarded client-address headers are ignored by default because
they are client-spoofable unless a trusted deployment proxy overwrites them.
Without the server-only `AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=true` opt-in, all
requests use the safe shared `unknown` limiter bucket. The owner-login and
public-status guards also apply process-global budgets and expiry-sweep bounded
per-address maps, so rotating addresses cannot create unbounded state or avoid
the global ceiling. The public status proxy remains separately cached and
coalesced so polling cannot consume the private API mutation budget.

Ordinary private API calls use the documented finite
`BACKEND_DEFAULT_TIMEOUT_MS` (12 seconds). Payment and fulfillment use the
endpoint-specific `BACKEND_PAY_TIMEOUT_MS` and
`BACKEND_FULFILL_TIMEOUT_MS` (150 seconds each), above the API's default
120-second Circle execution bound but below the hard
`BACKEND_MAX_TIMEOUT_MS` ceiling (180 seconds).

## Validate

```bash
npm run typecheck
npm test
npm run build

# Or run all three:
npm run check

# Real Next.js proxy against a real local FastAPI backend:
npm run test:integration:live
```

## Structure

- `app/` — Next.js App Router entry point and global visual system.
- `components/` — landing, onboarding, workflow, receipt, and revenue UI.
- `app/api/autonomerce/` — allowlisted auth, status, onboarding, and workflow
  server routes.
- `lib/backend-*.ts` — typed private API client and server-only configuration.
- `lib/demo-data.ts` — deterministic, public-safe DEMO replay fixture.
- `lib/money.ts` — exact USDC string and micro-unit helpers; no binary-float
  money arithmetic.
- `tests/` — focused tests for money handling and fixture identifiers.

## Integration notes

- DEMO mode makes no network requests and never falls through to LIVE success.
- LIVE requests use a fixed same-origin route surface, origin/body-size checks,
  owner-session checks on mutations, request timeouts, no redirects, and no
  browser-provided API authorization headers.
- Owner login/logout/status routes never return the owner token, API bearer, or
  session secret. Logout expires the signed session cookie immediately.
- LIVE prospect registration sends the explicit buyer contact-consent reference
  and buyer input. Receipt publication requires a separate publication
  authorization and consent reference; contact opt-in cannot be reused.
- A stable owner workflow UUID derives the payment idempotency key. Replaying a
  workflow resumes its existing proposal/payment/fulfillment instead of
  creating another settlement.
- Money enters the UI as canonical USDC strings and is aggregated with `bigint`
  micro-units.
- Payment confirmation and fulfillment acceptance are rendered as separate
  states, matching the project trust boundary.
- Demo receipts contain only public-safe identifiers and anonymized buyer data.
- LIVE receipt, payment, fulfillment, and metrics identifiers are rendered from
  backend responses; missing backend evidence is displayed as missing.
