---
name: stream
summary: "Algebraic-effects stream block — the body is parsed, lowered and EXECUTED over the Free-Monad CPS handler runtime (§111.e; it used to be discarded at parse time)."
category: operators
top_level: false
since: "pre-§111; body executed since Fase 111.e"
grammar: |
  stream {
      <handler-steps>
  }
---

# `stream`

`stream` is the **algebraic-effects block**: its body declares handlers
over the Free-Monad CPS runtime.

## What the runtime actually does (§111.e)

The body is parsed, lowered into the IR, and **executed** — before
§111.e it went through `parse_block_step`, whose entire job was
`skip_braced_block()`: the contents were thrown away at parse time and
the block "completed" with an empty string while the README sold
"Algebraic Effects and Free Monads".

## Proof

`axon-rs/tests/fase111_e_stream_runs.rs` — the body RUNS;
`axon-frontend/tests/fase111_e_stream_body.rs` — the body lowers.

## See also

- `axon://primitives/step` — what the body is made of.
