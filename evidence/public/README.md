# Public contest evidence

These files contain redacted, judge-openable evidence for the deployed
Autonomerce contest build. They are deliberately narrower than the private raw
logs.

## Current evidence

- [`build-identity.json`](build-identity.json) binds the merged Sophia revision,
  immutable container images, Cloud Run revisions, public web URL, and private
  API IAM boundary.
- [`gemini-call.redacted.json`](gemini-call.redacted.json) records one deployed
  Vertex AI Gemini productization call and the resulting structured SKU fields.
- [`transactions.public.json`](transactions.public.json) records the linked
  synthetic/offline settlement and delivery result. It explicitly says that no
  funds moved and that the amount is not revenue.
- [`wallet-policy.redacted.json`](wallet-policy.redacted.json) records the
  bounded Circle Agent Wallet testnet policy and the two fail-safe pre-submission
  attempts that preceded the confirmed transfer.
- [`circle-arc-testnet-transaction.public.json`](circle-arc-testnet-transaction.public.json)
  records one independently verified 0.10 USDC Arc testnet transfer and its
  idempotent replay. It is founder-owned testnet activity and is not revenue.

## Classification boundary

The Gemini productization call is `live_verified`: the deployed private API
executed the request on Vertex AI and returned a structured result. Separately,
the Circle settlement runner has `testnet_verified` evidence for one
founder-owned Agent Wallet transfer. These are not yet one deployed
Gemini-to-Circle-to-fulfillment order. No file here proves an external customer,
revenue, mainnet settlement, accepted delivery, or production readiness.

Raw owner-session cookies, Secret Manager values, authorization headers,
unredacted Cloud Run logs, and private workflow payloads are excluded.
