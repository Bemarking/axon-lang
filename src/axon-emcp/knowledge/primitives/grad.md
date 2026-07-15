---
name: grad
summary: "The proof-carrying derivative — SYMBOLIC differentiation over the §70 expression language at compile time; the gradient IS IR (PCC GradientSoundness) and the runtime only evaluates."
category: operators
top_level: false
since: Fase 109 (v2.65.0)
grammar: |
  let g = grad(<expr>, <wrt-binding>)
---

# `grad`

`grad` is the **proof-carrying derivative**: symbolic differentiation
over the §70 expression language, at COMPILE time.

## What the runtime actually does (§109)

The gradient **is IR**: differentiation happens in the frontend, the
derivative expression ships inside the artifact under the PCC
`GradientSoundness` witness, and the runtime only **evaluates** it —
zero tokens, no model in the loop, no numeric approximation.

## Proof

`axon-rs/tests/fase109_grad_runtime.rs` +
`axon-frontend/tests/fase109_grad_grammar.rs`.

## See also

- `axon://primitives/compute` — the sibling: named pure functions over
  the same expression language.
