---
name: focus
summary: "The dataspace verb (σ∘π) over the first-party columnar engine (§108.d)."
category: data_plane
top_level: false
since: Fase 108.d (v2.63.0)
grammar: |
  focus <Dataspace> ...
---

# `focus`

`focus` is one of the four **relational query verbs** over a declared
`dataspace` (§108.d), executed by the first-party columnar engine — no
LLM in the loop, deterministic by construction.

## What the runtime actually does

σ∘π: selection + projection: filter rows, keep named columns.

## Proof

`dataspace_engine::focus_query` — the §111 audit verdict: Real.

## See also

- `axon://primitives/dataspace` — the container + its typed schema.
- `axon://primitives/ingest` — how data (governedly) gets in.
