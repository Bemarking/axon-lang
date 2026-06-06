# AXON v2.10.0 — Kwarg value binding: sound reference resolution (§Fase 60)

> **Released:** 2026-06-05
> **Type:** minor bump · bug fix + compile-time validation · **zero wire change** · back-compat (one documented bare-word note)
> **Theme:** §Fase 60 closes the gap where `use <Tool>(k = v)` resolved a kwarg
> VALUE only via `${…}` interpolation + literals — a bare flow-param or a
> `Step.output` was passed as the literal NAME, not its value. References now
> resolve (like `let`), and the type-checker validates them.

Carries `axon-frontend` **1.7.0 → 1.8.0** and `axon-lang` **2.9.0 → 2.10.0**.

---

## What's fixed

In `use <Tool>(k = v)`, the value `v` is now resolved at runtime by its kind:

- **Literal** — a quoted string, number, bool, list. Coerced to the declared
  parameter type; `${param}` / `${StepName}` interpolates inside strings.
- **Reference** — a bare identifier or a dotted step output, resolved against
  the live bindings (the same mechanism `let` already used):
  - a **flow parameter** — `company`;
  - a **prior step's output** — `ExtractUrl.output` (or the bare step name).
    This is the **extract → dispatch** pattern: each argument of a multi-arg
    tool comes from its own extraction step.

Before §60 these references were passed as the literal name (`"company"`,
`"ExtractUrl.output"`); now they resolve to the bound value. An unbound
reference resolves to the empty string — never a silent passthrough of the
name.

## Compile-time validation (caller-blame)

The type-checker validates a reference's **source type** (a flow-parameter's
type, or a `<Step>` / `<Step>.output` output type) against the tool's declared
parameter type — a mismatch is a compile error before any dispatch, e.g.
`url = ExtractCount.output` where the step outputs `Int` and `url` is `String`.
A reference the checker cannot resolve in scope (a `let`) is conservatively
skipped (no false positive). Literal validation (§58.d) is unchanged.

## Compatibility

- **Zero wire change**; both dispatch paths (sync + SSE) resolve identically.
- **One behavior note:** a bare unquoted word in value position is now a
  *reference*, not a literal string. Quote string literals — `mode = "production"`,
  not `mode = production`. This matches what the docs always showed; it only
  changes the previously-buggy bare-word-as-literal case.
- The legacy `use Tool on <arg>` single-arg form remains `${…}`-interpolation
  only; the canonical form for references is `use Tool(k = v)`.

## Doctrine

The canonical doctrine `axon://logic/dispatch_vs_cognition` (axon-emcp 0.6.0)
now documents the kwarg value forms + the extract→dispatch multi-arg pattern.
