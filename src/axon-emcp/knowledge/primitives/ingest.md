---
name: ingest
summary: "Governed ingestion into a dataspace — bounds-BEFORE-parse, sha256 provenance, born-Untrusted taint (§108.c; the pre-§108 placeholder hallucinated success)."
category: data_plane
top_level: false
since: "pre-§108; made real Fase 108.c (v2.63.0)"
grammar: |
  ingest <source> into <Dataspace>
---

# `ingest`

`ingest` loads external data into a declared `dataspace`.

## What the runtime actually does (§108.c)

- **Bounds BEFORE parse** — size/row ceilings are checked before any
  byte is interpreted (the §100 discipline).
- **sha256 provenance** — the artifact records what was ingested.
- **Born Untrusted** — ingested data carries the Untrusted taint
  (axon-T908); cognition must launder it through the declared gates.

The pre-§108 placeholder *hallucinated success* — it reported ingestion
that never happened. That finding is the mother of §111.

## Proof

`cognitive::run_ingest` (§108) + `fase108_dataspace_deploy.rs`.

## See also

- `axon://primitives/dataspace` — the destination.
- `axon://primitives/focus` · `associate` · `aggregate` · `explore`.
