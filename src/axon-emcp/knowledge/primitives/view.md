---
name: view
summary: "A UI view declaration — referential integrity is checked; route dispatch and session-typed reactivity are deferred (§111)."
category: wire
top_level: true
since: λ-L-E Fase 9
grammar: |
  view <Name> {
      # UI view declaration; references are integrity-checked
  }
---

# `view`

`view` declares a **UI view**.

## What the runtime actually does — and does not (§111, honest scope)

- **Enforced**: referential integrity — the names a view references
  must resolve to declared entities.
- **Deferred**: no `route` check, no session-typed-reactivity check,
  and it **renders nothing** (no renderer exists in the runtime).

The §111 classification is **Partial**. A view is today a checked
declaration awaiting its runtime — declared scope, not a hidden gap.

## See also

- `axon://primitives/component` — the sibling declaration.
- `axon://primitives/axonendpoint` — the wire surface that IS real.
