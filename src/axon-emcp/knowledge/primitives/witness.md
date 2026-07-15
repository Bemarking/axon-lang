---
name: witness
summary: "The advantage-witness declaration (§69) — INTERNAL: benchmark and advantage claims wait for the Sandbox (§101), so this is deliberately NOT part of the advertised surface."
category: operators
top_level: true
since: Fase 69.a
grammar: |
  witness <Name> {
      # advantage-witness declaration (§69) — INTERNAL surface
  }
---

# `witness`

`witness` declares an **advantage witness** (§69) — a structured record
of a measured advantage claim.

## Deliberately NOT advertised

This primitive is `is_advertised: false` in the registry, by doctrine:
**benchmark and advantage claims wait for the Sandbox** (§101 D101.19).
Until adopters can reproduce a claim in the Sandbox, the language does
not advertise the primitive that would carry it. The grammar exists and
is gated (`fase69_a_witness_grammar.rs` / `fase69_a_witness_metric_parity.rs`);
the public promise is deferred on purpose.

## See also

- `axon://primitives/observable` — measurement of a different kind.
