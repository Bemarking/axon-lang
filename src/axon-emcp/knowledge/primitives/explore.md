---
name: explore
summary: "The dataspace profiling verb — zone-map statistics over declared columns (§108.d)."
category: data_plane
top_level: false
since: Fase 108.d (v2.63.0)
grammar: |
  explore <Dataspace> ...
---

# `explore`

`explore` is one of the four **relational query verbs** over a declared
`dataspace` (§108.d), executed by the first-party columnar engine — no
LLM in the loop, deterministic by construction.

## What the runtime actually does

zone-map statistics: profiling: per-column stats from the columnar engine's zone maps.

## Proof

`dataspace_engine::explore_profile` — the §111 audit verdict: Real.

## See also

- `axon://primitives/dataspace` — the container + its typed schema.
- `axon://primitives/ingest` — how data (governedly) gets in.
