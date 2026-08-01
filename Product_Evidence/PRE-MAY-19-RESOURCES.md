# Pre-May 19 resource disclosure

`eligibility cutoff: 2026-05-19T17:00:00Z`

## Repository-tracked finding

The available Sophia repository history begins with commit
`772193e68a10eedac31abb8ce5c3e90798ff6325` on
`2026-06-18T10:13:00+08:00`, after the eligibility cutoff. Current Git history
therefore identifies **no tracked source resource verified as existing before
May 19, 2026**.

This is a statement about the available repository history only. It does not
certify that no private, local, third-party, unpublished, or externally hosted
resource existed before the cutoff.

## Post-cutoff resources that still predate Autonomerce

Autonomerce was introduced on July 31, 2026. The following disclosed Sophia
resources were added after the contest cutoff but before Autonomerce and remain
pre-existing relative to the product:

| Resource | First tracked commit | First tracked date |
|---|---|---|
| `agent/gemini_llm.py` | `4a154dae9f69866d031664fcab94241d7083d908` | `2026-06-18T19:20:44+08:00` |
| `agent/audit_chain.py` | `e88932cef42e49888ad974ea45c2add68856eb27` | `2026-06-28T15:06:07+08:00` |
| `agent/execution_budget.py` | `55115f306425c7e080588baf2b37e9363b27592e` | `2026-07-25T16:55:44+08:00` |
| `agent/receipt_protocol.py` | `55115f306425c7e080588baf2b37e9363b27592e` | `2026-07-25T16:55:44+08:00` |
| `agent/evidence_ledger.py` | `55115f306425c7e080588baf2b37e9363b27592e` | `2026-07-25T16:55:44+08:00` |
| `agent/task_receipts.py` | `55115f306425c7e080588baf2b37e9363b27592e` | `2026-07-25T16:55:44+08:00` |

Their generic concepts and the contest-period Autonomerce work are described in
the included `PREEXISTING-ASSET-DISCLOSURE.md`.

## Submission boundary

- Historical Sophia usage, benchmarks, users, revenue, or adoption are not
  Autonomerce contest evidence.
- The listed commits do not prove that any code was copied unchanged; final
  attribution and license review remains required.
- The owner must separately disclose any relevant pre-cutoff resource that is
  absent from the available repository history.
