# Threat model

## Assets

- seller Circle wallet and policy;
- buyer and seller wallet addresses;
- accepted proposal and price;
- payment idempotency state;
- Gemini/Google credentials;
- Circle CLI session;
- customer inputs and delivered artifacts;
- public transaction evidence;
- measured revenue.

## Trust boundaries

1. Agent Card and MCP/OpenAPI manifests are untrusted.
2. Buyer needs and counteroffers are untrusted.
3. Gemini output is advisory and untrusted until schema/policy validation.
4. Paid seller output is untrusted until contract validation.
5. Circle transaction confirmation proves settlement, not fulfillment quality.
6. Public evidence is a redacted projection, not the operational record.

## Primary threats

| Threat | Control |
|---|---|
| Prompt injection in Agent Card | treat text as data; typed extraction; no direct tool authority |
| Model raises price discount/limit | deterministic CommercialPolicy |
| Arbitrary payee wallet | proposal-bound allowlist and address validation |
| Duplicate payment | stable idempotency key and confirmed-payment store |
| Replay of transaction proof | one transaction hash binds to one proposal/payment |
| SSRF through Agent Card URL | HTTPS-only, DNS/IP checks, no private/link-local/metadata |
| Autonomous spam | opt-in registry, per-host rate limit, daily proposal cap |
| Seller result injects commands | never execute result; validate artifact as data |
| Secret leakage in receipts | recursive key/value redaction |
| Testnet represented as revenue | public receipt includes chain/network; revenue gate requires mainnet |
| Wallet-to-self counted as customer | payer and payee identity check |
| Payment counted as delivery | separate payment and fulfillment states |

## Contest-safe operating limits

- start on Arc testnet;
- mainnet Base wallet is separately authenticated;
- per-transaction cap should start at 1 USDC or lower;
- monthly operating wallet should not exceed the owner-approved contest budget;
- no automatic outreach to a non-opted-in prospect;
- no mainnet payment test until policy verification is captured.
