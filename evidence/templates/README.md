# Public evidence templates

`examples: SYNTHETIC` · `not customer evidence` · `not revenue`

These schemas and examples define public-safe contest artifacts. The example
records exist only to exercise field structure. They do not describe users,
customers, live wallets, transactions, revenue, or results.

## Files

- `transaction.public.schema.json` — one public settlement linked to an order.
- `transaction.public.synthetic.example.json` — simulated example; no funds,
  customer, or revenue.
- `revenue.public.schema.json` — one measurement-window revenue snapshot.
- `revenue.public.synthetic.example.json` — zero-revenue snapshot that records
  one excluded simulated payment.

## Publication flow

1. collect raw records privately;
2. classify the relationship and network;
3. verify order/proposal/payment/fulfillment linkage;
4. apply customer consent;
5. redact private fields;
6. validate against the schema;
7. recompute metrics from transaction-level records;
8. run secret scanning;
9. obtain owner publication approval;
10. copy the approved artifact to the public evidence directory.

Never turn the synthetic examples into “live” evidence by changing only
`synthetic` to `false`. A live record must be regenerated from independently
verified source evidence.
