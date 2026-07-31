# Contest evidence

Public evidence belongs here only after redaction and owner consent.

## Required public artifacts

- `architecture.md`
- `demo-script.md`
- `metrics-definition.md`
- `customer-evidence.public.json`
- `transactions.public.json`
- `limitations.md`

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

Never count a wallet-to-self transfer, founder transfer, testnet transfer, or unpaid demo
as customer revenue.
