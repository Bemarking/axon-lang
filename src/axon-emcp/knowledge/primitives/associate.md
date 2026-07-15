---
name: associate
summary: "The dataspace join verb (⋈) over the first-party columnar engine (§108.d)."
category: data_plane
top_level: false
since: Fase 108.d (v2.63.0)
grammar: |
  associate <Dataspace> ...
---

# `associate`

`associate` is one of the four **relational query verbs** over a declared
`dataspace` (§108.d), executed by the first-party columnar engine — no
LLM in the loop, deterministic by construction.

## What the runtime actually does

⋈: a hash equi-join over two dataspaces — and it REFUSES a keyless join (a cross product nobody declared is a defect).

## Proof

`dataspace_engine::associate_query` — the §111 audit verdict: Real.

## See also

- `axon://primitives/dataspace` — the container + its typed schema.
- `axon://primitives/ingest` — how data (governedly) gets in.
