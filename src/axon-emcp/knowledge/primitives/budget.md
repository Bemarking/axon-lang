---
name: budget
summary: "A declared spend ceiling over cognition and tool use — enforced on the canonical `use Tool(...)` path (§114.a); attachable to a daemon or declared top-level."
category: operators
top_level: true
since: "Fase 72 (daemon-attached); top-level Fase 114.a (v2.69.0)"
grammar: |
  # Top-level (Fase 114.a) — governs every flow that calls the named tools:
  budget <Name> {
      rate: <n> per <second|minute|hour> on Tool(<ToolName>)
  }
  # Daemon-attached (Fase 72) — governs that daemon's ticks:
  daemon <Name> { budget { rate: <n> per <minute> on Tool(<ToolName>) } }
---

# `budget`

`budget` is a **linear-effect rate ceiling**: it bounds how often the
named tools may be invoked, per declared window.

## What the runtime actually does (§114.a)

The ceiling binds on the **canonical `use Tool(...)` dispatch path** —
the same seam every entry point (sync, SSE, daemon) runs through. A
call over quota is **refused**, not queued: spend ceilings fail closed.

This was §114.a's live bug: before it, `budget` was *discussed* in the
README seventeen times, badged zero, tracked in no table — and the
runtime never read it on the canonical path. The §114.z gate widening
exists because of this primitive.

## Proof

`axon-rs/tests/fase114_a_budget_governs_the_canonical_path.rs` (9/9) —
the ceiling really binds, on the path production takes.

## See also

- `axon://primitives/tool` — what the quota names.
- `axon://primitives/daemon` — the attached form's host.
- `axon://primitives/window` — the temporal (when), vs budget's how-much.
