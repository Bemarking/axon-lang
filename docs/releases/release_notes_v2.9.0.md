# AXON v2.9.0 — The `use`/`apply:` law + the honest compiler (§Fase 59)

> **Released:** 2026-06-05
> **Type:** minor bump · compile-time diagnostic + canonical doctrine · **zero runtime/wire change** · fully back-compat
> **Theme:** §Fase 59 draws the line AXON always had but never enforced: a
> deterministic tool **dispatch** (`use <Tool>(k=v)`) and a **cognitive
> delegation** of a tool to the model (`apply: <Tool>`) are two distinct
> epistemic operations. The compiler now indicates the path honestly — it
> never fakes determinism — and the law is canon in the EMCP.

Carries `axon-frontend` **1.6.0 → 1.7.0** and `axon-lang` **2.8.0 → 2.9.0**.

---

## What's new

### `axon-W004` — the honest-compiler guidance (§59.a)

`apply: <Tool>` runs a tool as a **cognitive step backend**: the step
executes as an LLM reasoning call and the model decides, stochastically,
whether to invoke the tool. It is **not** a deterministic dispatch.
`use <Tool>(k = v, …)` is the one deterministic, schema-validated,
real-dispatch surface.

When you write `apply: <Tool>` on a tool that declares a `parameters:`
schema, `axon check` now emits **`axon-W004`** — naming the cognitive
nature and redirecting you to `use <Tool>(k = v, …)` (listing the schema's
parameters so the conversion is paste-actionable). The compiler never
silently makes `apply:` deterministic.

This **supersedes the §58.d.2 splat type-check**: its hard errors
(`missing required` / `type mismatch` on `apply: given:`) validated a
deterministic contract the runtime never honored — the "illusion of
control." Those phantom errors are gone; the real CT-2 caller-blame
validation stays exactly where it executes: on `use <Tool>(k = v, …)`
(§58.d, untouched).

### Canonical doctrine in the EMCP (§59.b)

The law is now first-class knowledge: **`axon://logic/dispatch_vs_cognition`**
— the four-pillar account of `use` vs `apply:`, the provider contract
(`http`/`mcp` for real dispatch), the `axon-W004` connection, and the
before/after migration. Any agent/adopter consuming the ℰMCP server gets
the doctrine, not just one adopter.

## Why this matters (the principle)

AXON does not pretend the LLM is deterministic. It contains the model's
stochasticity and *surfaces* it (the epistemic lattice, the envelope). The
adopter chooses `use` where they need determinism and `apply:` where they
genuinely want the model to reason with a tool available — and the
compiler tells them which one they wrote. The fence stays put; the adopter
adapts to the language's nature.

## Compatibility

- **Zero runtime/wire change.** §59 changes only a compile-time diagnostic
  + docs. No bytes of the runtime, the dispatch, or the wire change.
- **A relaxation, not a tightening:** programs that previously *errored* on
  a `apply: given:` mismatch now compile (with the `axon-W004` guidance).
  Nothing that compiled before stops compiling.
- The deterministic surface `use <Tool>(k = v, …)` keeps its full CT-2
  validation (§58.d).
