# Autonomerce implementation contract

This is the integration contract for parallel implementation lanes.

## Non-negotiable product behavior

The judged path must demonstrate:

```text
seller Agent Card or manifest
-> Gemini capability productization
-> commercial-policy binding
-> opted-in buyer discovery
-> machine-readable offer
-> bounded negotiation
-> autonomous Circle USDC payment
-> seller-agent fulfillment
-> contract validation
-> delivery receipt and revenue update
```

No human approves an individual payment inside an already-approved policy.

## Shared Python package

Import shared domain types from:

```python
from autonomerce.contracts import ...
```

Do not redefine the shared enums or dataclasses in lane-local modules.

## Stable identifiers

IDs use a semantic prefix plus a deterministic SHA-256 suffix:

```text
sku_<24 hex>
need_<24 hex>
proposal_<24 hex>
payment_<24 hex>
fulfillment_<24 hex>
```

## Money

- Use `decimal.Decimal`, never binary float.
- Canonical USDC strings have six or fewer decimal places.
- Negative money is invalid.
- Policy checks are deterministic and fail closed.

## Trust boundaries

- Gemini recommends commercial actions.
- Deterministic policy code authorizes them.
- Circle executes payment.
- Proposal acceptance creates an immutable settlement authorization binding the
  exact revision, amount, payer, payee, chain, token, canonical USDC contract,
  policy version, seller configuration version, and expiry.
- Normal live confirmation requires an independent transaction lookup; Circle
  CLI output alone is not settlement proof.
- Seller outputs are untrusted until validated.
- Payment confirmation does not imply delivery success.
- Delivery success does not imply a factual truth claim beyond the service contract.

## Credentials

- No secrets in source, fixtures, logs, or receipts.
- Offline mode must run with zero credentials.
- Live adapters read credentials from authenticated CLI sessions, Application
  Default Credentials, Secret Manager, or explicitly named environment variables.
- Never accept OTPs or recovery material through application APIs.

## Public evidence

Public receipts may contain:

- public wallet address;
- network;
- amount;
- transaction hash;
- proposal ID;
- anonymized order ID;
- timestamps;
- acceptance verdict.

Public receipts must not contain:

- API keys;
- authorization headers;
- Circle session tokens;
- Google credentials;
- customer prompts unless explicitly consented;
- private buyer identity.

## Lane ownership

| Lane | Write scope |
|---|---|
| OfferRail core | `packages/offerrail/**` |
| Gemini agents | `apps/api/autonomerce/agents/**` |
| Circle/x402 | `apps/api/autonomerce/payments/**` |
| A2A sales | `apps/api/autonomerce/sales/**` |
| API composition | `apps/api/autonomerce/api/**` |
| Web UI | `apps/web/**` |
| Security | `security/**`, `tests/security/**` |
| Deployment | `infra/**`, product-local workflow/scripts |
| Submission/docs | `docs/**`, `evidence/README.md` |

Shared files require main-agent ownership.

## Quality gates

- `python3 -m pytest -q projects/autonomerce/tests`
- product-local type/import smoke
- zero payment-policy violations in adversarial fixtures
- zero duplicate payment settlement for one idempotency key
- zero secrets in committed fixtures
- `python3 tools/lint_claims.py`
