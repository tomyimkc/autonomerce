# SKU authorization boundary

## Decision

Gemini is an advisory copy and relevance component. It is not an SKU contract
author, policy engine, validator selector, URL source, or payment authority.

`CapabilityProductizer` now separates the two planes:

| Plane | Authority |
|---|---|
| Display name, relevance flag, short rationale, summary | Gemini advice after deterministic text validation |
| Capability outcome and scope | Owner-approved `CapabilityDescriptor`; a legacy outcome paraphrase is accepted only when the deterministic scope guard proves that it adds no action or domain |
| Input/output schemas | Exact copies of the owner-approved capability |
| Price range | Owner-approved `CommercialPolicy` |
| Base price | Deterministic midpoint of the policy range, rounded to USDC precision |
| Latency | Deterministic capability-profile registry |
| Capacity | Minimum of the profile ceiling and owner policy limit |
| Acceptance criterion IDs | Deterministic validator registry and declared output schema |
| Source URL, instructions, payment terms, hidden terms | Never accepted from model output |

The productization prompt sends only untrusted display copy (`name`,
`description`, and `tags`) plus non-commercial authorization metadata. It does
not send source URLs, schemas, prices, latency, capacity, wallet/payment data, or
the owner policy.

## Deterministic registries

The capability-profile registry currently authorizes a 300-second latency and a
20-task/hour ceiling. Effective capacity is additionally capped by
`CommercialPolicy.maximum_tasks_per_hour`.

The validator registry can emit only:

- `non_empty_artifact`;
- `output_schema_valid` when an output schema exists;
- `required_field:<field>` for safe field names listed in
  `output_schema.required`.

Model-returned criterion IDs are never added to an SKU. Unknown IDs fail closed.
Two old test-adapter labels (`human_reviewed` and `provider_summary_present`) are
recognized as migration no-ops only; they are not stored and do not become
acceptance conditions.

## Response validation

The current structured response schema permits only:

```json
{
  "skus": [
    {
      "name": "Display copy",
      "relevant": true,
      "rationale": "Short relevance explanation"
    }
  ],
  "summary": "Copy-only summary",
  "reasonCodes": ["COPY_RELEVANT"]
}
```

The productizer rejects:

- unknown top-level or SKU fields;
- URLs, URI schemes, and Markdown links in generated text;
- prompt-control or tool/command instructions;
- payment-transfer instructions;
- hidden/fine-print terms, HTML comments, and hidden Unicode control text;
- unknown acceptance criterion IDs;
- outcome paraphrases that introduce an unapproved action or fail the
  deterministic relevance/scope check.

Older providers may still return the former price, latency, capacity, outcome,
and criteria keys during migration. Those keys are outside the Gemini schema.
They are parsed only to detect unsafe values and produce diagnostics; contract
terms are rebuilt from owner inputs and the registries.

## Agent Card handling

Agent Cards and capability manifests remain untrusted inputs. Before Gemini is
called, productization checks the copy-bearing capability name, description, and
tags for embedded URLs, prompt-control instructions, payment instructions,
hidden terms, and hidden control characters. The legitimate Agent Card
`source_url` remains metadata and is neither copied into the SKU outcome nor sent
to Gemini.

Owner approval should occur before persistence. The deterministic boundary does
not turn an unreviewed third-party capability into an owner-approved offer; it
ensures that model output cannot widen what the approved capability and policy
authorize.

## Security tests

`tests/test_productizer_security.py` includes:

- an adversarial Agent Card whose skill description attempts prompt injection;
- a capability with owner-approved schemas and policy;
- copy-only request-schema assertions;
- paired hostile price/latency/capacity responses proving identical SKU terms;
- unknown criterion rejection;
- unsupported URL, instruction, hidden-term, and scope-expansion rejection.
