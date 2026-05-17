# Migration to axon-lang v1.33.0

v1.33.0 unifies one thing that had quietly diverged between axon's two
runtimes: **variable interpolation**. It is additive and
**backward-compatible** — no program breaks — but it is the release
that makes a single `.axon` interpolate *identically* whether it runs
on the Rust runtime or the Python runtime.

> **TL;DR** — axon has **one** interpolation syntax: `${name}` /
> `$name`. The Rust runtime always used it; as of v1.33.0 the Python
> runtime accepts it too. `{{name}}` is a **legacy Python-runtime-only
> dialect** — still works on the Python runtime, never worked on the
> Rust runtime, and is not part of the language. Convert your flows to
> `${name}`.

---

## The interpolation contract

This is a **language contract**, not a per-runtime detail:

- A variable reference is **`${name}`** or **`$name`**.
  - `${name}` — the braced form; `name` is everything up to the first
    `}`. Use it when the reference is adjacent to identifier
    characters: `${id}_suffix`.
  - `$name` — the bare form; `name` is `[A-Za-z_][A-Za-z0-9_]*` and
    ends at the first non-identifier character.
- A name **in scope** is replaced by its value. A name **not in
  scope** is left **literal** — `${missing}` stays `${missing}`, so a
  mistyped reference is visible, never silently blanked.
- Interpolation is a **single pass** — a substituted value is never
  re-scanned.
- A bare `$` that is not followed by `{` or an identifier character is
  literal (`price: $5` — the `$` stays).

It applies uniformly everywhere a flow carries a value expression:
step prompts (`ask:`), `retrieve` / `mutate` `where:` clauses, and the
`persist` / `mutate` `{ col: value }` blocks.

The contract is pinned by a shared corpus
(`tests/fixtures/interpolation_contract.json`) that **both** runtimes'
test suites assert against — if either runtime ever drifts, CI fails.

---

## Scenario 1 — flows written for the Python server use `{{name}}`

The Python runtime historically interpolated **`{{name}}`**. The Rust
runtime never did — it only ever interpolated `${name}` / `$name`. So a
flow authored against the Python server, deployed unchanged to the Rust
server, left every `{{...}}` **literal** at runtime:

```
retrieve tenants { where: "id == '{{tenant_id}}'" }
  → SELECT * FROM tenants WHERE id == '{{tenant_id}}'   → 0 rows
persist chat_history { content: "{{message}}" }
  → the literal string "{{message}}" persisted
step Reply { ask: "...{{message}}..." }
  → the LLM receives "{{message}}" literally
```

**v1.33.0** makes the Python runtime accept `${name}` too (additive —
`{{name}}` keeps working there for now). So you can:

1. Convert your flows `{{x}}` → `${x}` **while still in production on
   the Python server** — the converted flows run correctly on the
   Python runtime immediately, because it now speaks `${name}`.
2. Cut over to the Rust server whenever you choose — the same
   `${name}` flows run byte-identical there.

The conversion is **decoupled from the cutover**. You are never forced
to do a big-bang rewrite-and-switch.

**Action:** convert `{{name}}` → `${name}` across your `.axon` flows.
A mechanical find-and-replace of `{{` → `${` and `}}` → `}` is
correct for the common case (single-name references).

---

## Scenario 2 — a flow already using `${name}`

Nothing to do. `${name}` / `$name` was always the Rust runtime's
syntax and is now also the Python runtime's. Such a flow already runs
identically on both. v1.33.0 changes nothing for it.

---

## `{{name}}` — status

`{{name}}` is **not part of the language**. It is a legacy dialect of
the Python runtime only, kept working **transitionally** so flows
written against the Python server keep running until they are
converted. It will not be added to the Rust runtime, and it ends when
the Python runtime is retired (the project's Rust + C direction).
Treat every `{{...}}` in your flows as scheduled work — convert it.

---

## Backward compatibility

- A `${name}` flow: unchanged on both runtimes.
- A `{{name}}` flow: unchanged on the Python runtime (still
  interpolates); still literal on the Rust runtime (never supported).
- An unknown `${missing}` reference is left literal — it cannot blank
  a value or throw.
- No `axonstore`, `flow`, or step syntax changed.
