# Contest evidence

Public evidence belongs here only after redaction and owner consent.

## Current public artifacts

- [`public/build-identity.json`](public/build-identity.json)
- [`public/gemini-call.redacted.json`](public/gemini-call.redacted.json)
- [`public/transactions.public.json`](public/transactions.public.json)
- [`public/wallet-policy.redacted.json`](public/wallet-policy.redacted.json)
- [`public/circle-arc-testnet-transaction.public.json`](public/circle-arc-testnet-transaction.public.json)
- [`public/README.md`](public/README.md)

## Private, untracked artifacts

Keep under `evidence/private/`:

- customer identity and consent records;
- raw Circle CLI output;
- billing screenshots;
- raw product logs;
- unredacted order payloads;
- any credential-bearing diagnostic.

## Transaction public schema

```json
{
  "orderId": "anonymized",
  "proposalId": "proposal_...",
  "network": "BASE",
  "amountUsdc": "0.1",
  "transactionHash": "0x...",
  "explorerUrl": "https://...",
  "externalCustomer": true,
  "delivered": true,
  "customerConsentToPublish": true
}
```

Never count a wallet-to-self transfer, founder transfer, testnet transfer, or
unpaid demo as customer revenue. The deployed Gemini order used an offline mock
payment. The separate Arc testnet transfer moved test-value USDC between
founder-owned Agent Wallets and also reports zero qualifying revenue.
