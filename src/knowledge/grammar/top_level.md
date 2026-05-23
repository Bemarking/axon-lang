---
name: top_level
title: Top-level vs. nested primitives
summary: Closed table of every AXON primitive's surface — what stands alone at the program root, what only appears nested inside another construct.
---

# Top-level vs. nested primitives

Every AXON primitive is either **top-level** (it stands alone at the
program root) or **nested** (it only appears inside another
construct). The compiler enforces this at parse time: a `step`
declaration outside any `flow` is a syntax error; a `flow` declaration
*inside* another `flow` is too.

This page is the authoritative table. When an agent is unsure where a
primitive belongs, it should consult this resource — every decision
follows from one row.

## How to read this table

- **Surface** — the AXON keyword as it appears in source.
- **Top-level** — `✓` if the keyword starts a top-level declaration;
  `✗` if it only appears nested.
- **Lives inside** — for nested primitives, the parent construct(s)
  that may contain it.
- **Category** — the family the primitive belongs to (drives the
  `axon.primitives(filter)` facet).
- **Since** — the cycle that introduced it.

## Cognition

| Surface | Top-level | Lives inside | Since |
|---|:---:|---|---|
| `persona`  | ✓ | — (referenced by `run … as` and `step … use`) | v0.1.0 |
| `context`  | ✓ | — (referenced by `run … within`)              | v0.1.0 |
| `flow`     | ✓ | —                                              | v0.1.0 |
| `anchor`   | ✓ | — (referenced by `run … constrained_by [...]`) | v0.1.0 |
| `tool`     | ✓ | — (referenced implicitly by the tool surface)  | v0.1.0 |
| `intent`   | ✓ | —                                              | v0.1.0 |
| `memory`   | ✓ | —                                              | v0.1.0 |
| `agent`    | ✓ | —                                              | v0.1.0 |
| `step`     | ✗ | `flow`                                         | v0.1.0 |
| `reason`   | ✗ | `flow` (sibling of `step`) — also `step` body  | v0.1.0 |
| `probe`    | ✗ | `flow`, `step` body                            | v0.1.0 |
| `validate` | ✗ | `flow`                                         | v0.1.0 |
| `refine`   | ✗ | `flow`                                         | v0.1.0 |
| `weave`    | ✗ | `flow`                                         | v0.1.0 |
| `use`      | ✗ | `flow`, `step` header                          | v0.1.0 |

## Cognitive I/O

| Surface | Top-level | Lives inside | Since |
|---|:---:|---|---|
| `resource`  | ✓ | — | Fase 6 |
| `fabric`    | ✓ | — | Fase 6 |
| `manifest`  | ✓ | — | Fase 6 |
| `observe`   | ✓ | — | Fase 6 |
| `reconcile` | ✓ | — | Fase 6 |
| `lease`     | ✓ | — | Fase 6 |
| `ensemble`  | ✓ | — | Fase 6 |
| `session`   | ✓ | — (referenced by `socket protocol:`) | Fase 41.a |

## Data plane

| Surface | Top-level | Lives inside | Since |
|---|:---:|---|---|
| `axonstore` | ✓ | — | Fase 36 |
| `dataspace` | ✓ | — | Fase 36 |
| `corpus`    | ✓ | — | Fase 36 |
| `pix`       | ✓ | — | Fase 19 |
| `type`      | ✓ | — | v0.1.0  |

## Session types & wire

| Surface | Top-level | Lives inside | Since |
|---|:---:|---|---|
| `session`        | ✓ | — | Fase 41.a |
| `socket`         | ✓ | — | Fase 41.b |
| `axonendpoint`   | ✓ | — | Fase 32 |
| `axpoint`        | ✓ | — | Fase 32 |
| `daemon`         | ✓ | — | Fase 16 |
| `mcp`            | ✓ | — | Fase 33+ |
| `listen`         | ✗ | `flow`, `daemon` body | Fase 16 |

> The `taint` keyword is a reserved word in the lexer but has no
> parser production today (it appears in the epistemic-uncertainty
> lattice in `axon-frontend::epistemic`, not as a top-level
> declaration). If a future Fase introduces a `taint <Name> { … }`
> declaration the registry + this table grow together.

## Operators

| Surface | Top-level | Lives inside | Since |
|---|:---:|---|---|
| `shield`   | ✓ | — | Fase 20 |
| `mandate`  | ✓ | — | Fase 21 |
| `compute`  | ✓ | — | Fase 17 |
| `lambda`   | ✓ | — | Fase 15 |
| `forge`    | ✗ | `flow` | Fase 18 |
| `ots`      | ✓ | — | Fase 11 |
| `psyche`   | ✓ | — | Fase 14 |
| `agent`    | ✓ | — | Fase 18 |
| `logic`    | ✓ | — | Fase 23 |

## Statements (not primitives, but parsed at flow body)

These are statements an agent treats as the body of a `flow`. They
are NEVER top-level.

| Surface | Lives inside | What it does |
|---|---|---|
| `if … else`   | `flow` body | Conditional branch |
| `for x in …`  | `flow` body | Bounded iteration |
| `let x = …`   | `flow` body | Local binding |
| `return …`    | `flow` body | Early/explicit return |
| `break`       | inside `for` | Loop early-exit |
| `continue`    | inside `for` | Next iteration |
| `run …`       | top-level — but it is a *binding*, not a declaration | Binds a flow to a persona+context+anchors |
| `apply`       | `step` body field | Invoke another flow |

## Composition discipline

- **Flows compose by `apply`, not by nesting.** A `flow` declaration
  cannot appear inside another `flow`. Sub-flows are *referenced*
  from a `step` body via `apply: <FlowName>`.
- **Anchors and shields bind through `run`, not the flow header.** A
  flow does not list its constraints; the `run` statement that
  executes it does, via `constrained_by [...]`.
- **Personas, contexts, and tools are referenced, not redeclared.** A
  flow that uses a persona references it (`as <Persona>` on the
  `run`, or `use <Persona>` per step). It does not embed a fresh
  declaration.

For the *why* behind these rules, read
`axon://logic/flow_composition`.
