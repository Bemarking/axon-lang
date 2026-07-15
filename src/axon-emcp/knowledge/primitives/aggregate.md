---
name: aggregate
summary: "The dataspace verb (γ) over the first-party columnar engine (§108.d)."
category: data_plane
top_level: false
since: Fase 108.d (v2.63.0)
grammar: |
  aggregate <Dataspace> ...
---

# `aggregate`

`aggregate` is one of the four **relational query verbs** over a declared
`dataspace` (§108.d), executed by the first-party columnar engine — no
LLM in the loop, deterministic by construction.

## What the runtime actually does

γ: grouped aggregation over declared columns.

## Proof

`dataspace_engine::aggregate_query` — the §111 audit verdict: Real.

## See also

- `axon://primitives/dataspace` — the container + its typed schema.
- `axon://primitives/ingest` — how data (governedly) gets in.
