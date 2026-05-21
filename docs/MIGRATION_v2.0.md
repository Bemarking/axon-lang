# Migrating to axon v2.0.0 — Pure Silicon Cognition

v2.0.0 is a MAJOR release with two breaking changes. This guide walks
adopters through both. Most `.axon` sources need a small mechanical
edit; the runtime + CLI behavior is otherwise at parity with v1.40.x.

## Breaking change 1 — `FlowEnvelope<T>` mandatory wire shape

### What changed

For `transport: json` endpoints (the default), the response wire shape
is now the canonical `FlowEnvelope<T>` envelope (the ψ-vector
serialization). A bare `output: T` declaration no longer compiles —
`axon check` raises **`axon-E039`** with the canonical fix.

### Why

In the v1.x era the wire was a flat envelope object, but the
`output:` declaration could be any type — leading to the T9XX↔D5 seam
where the compile-time hint suggested `output: List<T>` while the
runtime D5 gate rejected it (the wire was an object, not an array).
v2.0.0 closes this structurally: the wire IS `FlowEnvelope<T>`, and
the declaration must name it.

### How to migrate

For every `axonendpoint` with `transport: json` (or no `transport:`
declared) that has a non-`Any`, non-`Unit` `output:`:

```axon
# BEFORE (v1.x)
axonendpoint GetTenant {
    method: GET
    path: /api/tenants/{id}
    execute: FetchTenant
    output: TenantRecord          # ← axon-E039 in v2.0.0
}

# AFTER (v2.0.0)
axonendpoint GetTenant {
    method: GET
    path: /api/tenants/{id}
    execute: FetchTenant
    output: FlowEnvelope<TenantRecord>
}
```

The same applies to plural + stream shapes:

| v1.x declaration | v2.0.0 declaration |
|------------------|--------------------|
| `output: TenantRecord` | `output: FlowEnvelope<TenantRecord>` |
| `output: List<TenantRecord>` | `output: FlowEnvelope<List<TenantRecord>>` |
| `output: Stream<Token>` (json) | `output: FlowEnvelope<Stream<Token>>` OR `transport: sse(axon)` + `output: Stream<Token>` |

### Escape hatches (no source change to FlowEnvelope)

- `output: Any` — universal accept, **no D5 validation** (degraded
  surface; use when you intentionally don't want wire-shape checking).
- `output: Unit` — endpoint produces no body.
- `transport: sse(axon)` — switch to the streaming wire (its own
  `axon.token` / `axon.complete` event family); bare `Stream<T>` is
  valid there.
- Omit `output:` entirely — D9 backwards-compat skip (no gate).

### Client-side migration

Your HTTP clients now parse a `FlowEnvelope<T>` JSON object on every
`transport: json` 2xx response:

```jsonc
{
  "ontological_type": "TenantRecord",
  "result": { /* your typed payload — extract THIS */ },
  "certainty": 0.97,
  "provenance_chain": [...],
  "step_audit": {...},
  "audit_chain_hash": "...",
  "blame_attribution": null,
  "execution_metrics": {...},
  "trace_id": "..."
}
```

- Extract `result` for the typed data your code consumed before.
- Read `certainty` if you want the epistemic confidence (bounded
  ≤ 0.99 for derived states per Theorem 5.1).
- Read `provenance_chain` + `audit_chain_hash` for audit / compliance
  (HMAC-anchored tamper-evidence).
- Read `blame_attribution` to detect degraded-posture responses
  (anchor breach / shield rejection / store breach / backend
  soft-fail / type mismatch).

The envelope is a SINGLE stable shape across all endpoints —
codegen-friendly for typed clients.

## Breaking change 2 — distribution model

### What changed

The PyPI `axon-lang` package no longer contains the Python language.
`pip install axon-lang` now installs a thin launcher that fetches the
precompiled native Rust binary for your platform and execs it.

### Impact

- **CLI users**: no change in behavior. `pip install axon-lang &&
  axon check x.axon` works exactly as before — it's the native binary
  under the hood now.
- **Library importers** (`import axon; axon.compiler...`): the Python
  compiler/runtime modules are GONE. There is no Python API. Use:
  - the native CLI (`axon check` / `compile` / `serve` / …)
  - the `axon-lang` Rust crate (`cargo add axon-lang`) for embedding
  - the `axon-frontend` Rust crate for lexer/parser/type-checker

### Install options

```bash
pip install axon-lang        # native binary launcher (Python ecosystem)
cargo install axon-lang      # native install (no Python)
# OR download a binary tarball from the GitHub Release
```

## Behavior parity (NOT changed)

- The `axon` CLI surface: `check`, `compile`, `run`, `trace`,
  `parse`, `fmt`, `serve`, `store`, `version`, `inspect`, `repl`,
  `deploy`, `dossier`, `sbom`, `audit`, `evidence-package`, `ld`,
  `diff`, `replay`, `stats`, `graph`, `estimate` — all native, all at
  parity.
- The HTTP server wire (other than the FlowEnvelope wrap): SSE event
  family, idempotency, replay tokens, auth scopes — unchanged.
- The axonstore four pillars, the algebraic effects runtime, the
  shield runtime — unchanged.

## Diagnostic differences (cosmetic)

The native binary's error messages differ cosmetically from the v1.x
Python CLI in two places:

- Invalid-JSON errors use `serde_json` phrasing ("expected value at
  line 1 column 1") vs Python's `json` ("Expecting value: line 1
  column 1 (char 0)").
- On Windows `cmd.exe`, the `✗` glyph may render as `X` (ASCII
  fallback). Exit codes + error classes are identical.
