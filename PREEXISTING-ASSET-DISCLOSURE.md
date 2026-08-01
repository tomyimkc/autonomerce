# Pre-existing asset disclosure

Autonomerce is a new contest-period product created on 2026-07-31.

Sophia-AGI predates Autonomerce. The following generic infrastructure concepts or source
files may inform the new product and must be disclosed if copied or adapted into the public
repository.

## May 19 eligibility-cutoff distinction

The available repository history begins on June 18, 2026, after the
`2026-05-19T17:00:00Z` eligibility cutoff. Current Git history identifies no
tracked source resource verified as existing before that cutoff. The Sophia
resources below are still pre-existing relative to Autonomerce because they
were tracked before the product was introduced on July 31.

See
[`Product_Evidence/PRE-MAY-19-RESOURCES.md`](Product_Evidence/PRE-MAY-19-RESOURCES.md)
for commit/date details and the explicit boundary for private or external
resources that are not visible in repository history.

| Sophia source | Generic value | Contest-period Autonomerce work |
|---|---|---|
| `agent/execution_budget.py` | bounded resource reservations | payment/commercial policies and Circle binding are new |
| `agent/receipt_protocol.py` | deterministic JSON and redaction | proposal/payment/fulfillment schemas are new |
| `agent/evidence_ledger.py` | append-only evidence records | commercial receipt and delivery lifecycle are new |
| `agent/audit_chain.py` | hash-chained audit records | product-specific revenue events are new |
| `agent/task_receipts.py` | workflow lifecycle receipts | seller/proposal/payment states are new |
| `agent/gemini_llm.py` | Google GenAI client pattern | ADK sales/productization agents are new |
| provenance/source-discipline modules | initial verification service concept | A2A commercialization, Circle settlement, and customer product are new |

## Rules

- Do not copy files without preserving Apache-2.0 notices.
- Record the original path and commit for every copied/adapted file.
- Do not represent historical Sophia usage, benchmarks, or revenue as Autonomerce evidence.
- Autonomerce customer growth and revenue start during the contest period.
- The standalone public repository must contain this disclosure.
