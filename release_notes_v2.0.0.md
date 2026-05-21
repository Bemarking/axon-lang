# axon-lang v2.0.0 — Pure Silicon Cognition

**MAJOR.** v2.0.0 is the architectural purification that the v1.x era
was building toward: **axon is now implemented entirely in Rust + C23**.
The Python compiler, runtime, server, and CLI that bootstrapped the
language are retired. The lexer, parser, type-checker, IR generator,
runtime, HTTP server, axonstore, and CLI are all native Rust + C23 —
one continuous gradient of metal from `.axon` source to silicon.

This release also delivers **`FlowEnvelope<T>`**, the canonical wire
contract that closes the T9XX↔D5 envelope seam adopters surfaced in
the v1.40.x cycle — the original gap that motivated the whole Fase 39
"Pure Silicon Cognition" cycle.

## Why a major bump

Two breaking changes:

1. **Mandatory `FlowEnvelope<T>` wire shape** for `transport: json`
   endpoints (D2 + D12 α). A bare `output: T` / `output: List<T>` /
   `output: Stream<T>` declaration no longer compiles — `axon-E039`
   surfaces at `axon check` with the canonical wrapping suggestion.

2. **Distribution model change**. The PyPI `axon-lang` package is now
   a thin native-binary launcher: `pip install axon-lang` fetches the
   precompiled Rust binary for your platform and `axon` execs it.
   There is no Python language code in the package.

## The ψ-vector wire contract — `FlowEnvelope<T>`

Every `transport: json` axonendpoint response is now the isomorphic
serialization of the epistemic vector `ψ = ⟨T, V, E⟩`:

```json
{
  "ontological_type": "List<TenantRecord>",
  "result": [{"id": 1, "name": "foo"}],
  "certainty": 0.97,
  "provenance_chain": ["flow:FetchTenants", "retrieve:tenants", "backend:stub"],
  "step_audit": { "step_names": [...], "step_results": [...], ... },
  "audit_chain_hash": "a3f5e1c8...",
  "blame_attribution": null,
  "execution_metrics": { "latency_ms": 142, "backend": "stub", ... },
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

- **Pillar I (epistemic)**: `ontological_type` (T), `result` (V),
  `certainty` bounded by **Theorem 5.1 in silicon** (`c ≤ 0.99` for
  derived states — enforced by the C23 kernel
  `axon-csys::envelope::validate_degradation`, structurally
  unbypassable from any Rust caller).
- **Pillar II (audit-chained)**: `provenance_chain` (semantic lineage
  taxonomy — `retrieve:`/`persist:`/`shield:`/`ots:`/…),
  `step_audit`, `audit_chain_hash` (SHA-256 tamper-evidence).
- **Pillar IV (capability)**: `blame_attribution` (closed-catalog
  `BlameKind`: anchor breach / shield rejection / store breach /
  backend soft-fail / type mismatch).

**Differential vs the industry**: gRPC `Status`, GraphQL
`{data, errors}`, and JSON-RPC carry typed payloads — but NONE carry
epistemic certainty bounded by a theorem, provenance HMAC-anchored,
and blame attribution as first-class wire fields. The cognitive-
language positioning is honored at the wire, not just at the source.

## Migration — adopters

See `docs/MIGRATION_v2.0.md` for the full guide. The mechanical change:

```axon
# v1.x — no longer compiles (axon-E039)
axonendpoint FetchTenants {
    method: GET
    path: /api/tenants
    execute: ListTenants
    output: List<TenantRecord>
}

# v2.0.0 — canonical
axonendpoint FetchTenants {
    method: GET
    path: /api/tenants
    execute: ListTenants
    output: FlowEnvelope<List<TenantRecord>>
}
```

Escape hatches: `output: Any` (universal accept, no D5 validation) or
`transport: sse(axon)` (streaming wire with its own event family —
bare `Stream<T>` valid there).

## What's gone (the purga)

426 files / 187,826 lines of Python deleted:
- `axon/compiler/` `runtime/` `server/` `cli/` `backends/` +
  `engine/` `enterprise/` `optimizer/` `stdlib/`
- The PyPI package's only Python is now a ~110-LOC binary launcher
  (`axon/_bootstrap.py`) + the version stub (`axon/__init__.py`).

## Distribution

- `pip install axon-lang` → fetches the native binary (Linux x86_64,
  macOS aarch64, Windows x86_64) from the GitHub Release
- `cargo install axon-lang` → native install, no Python
- GitHub Release binary tarballs
- axon-enterprise Docker image (Rust adopters)

## Cross-stack components

- **axon-lang v2.0.0** (Rust crate + PyPI launcher)
- **axon-frontend v1.0.0** (MAJOR — new `Cardinality::Wrapped` enum
  variant for FlowEnvelope; nested-generic parser support)
- **axon-csys** (C23 kernels — new `effects/envelope.{h,c}` for
  Theorem 5.1)
- **axon-enterprise v2.0.0** (catch-up — Docker image for Rust adopters)

## Fase 39 sub-fase summary

39.a FlowEnvelope type system · 39.b wire envelope runtime · 39.c
epistemic field producers (certainty C23 + provenance + blame) ·
39.d D5 canonical entry simplification · 39.e axon-E039 compile error ·
39.f Rust CLI binary parity (`parse` + `fmt`) · 39.g test migration
(Cat 3 → Rust binary; 164 Python tests quarantined+purged) ·
39.h purga (426 files) · 39.i atomic deploy.

## Test surface

2197 axon-rs lib + 468 axon-frontend lib (v1.0.0) + 13 axon-csys
envelope kernel + 12 fase39f CLI parity + 15 fase39b + 15 fase39c
integration + 16 Cat 3 Python (native-binary-driven) — green
cross-stack.

## Honest scope

`axon fmt` is the MVP token-level round-trip (canonical-form rewriting
deferred). `axon parse` runs single-threaded (`--jobs` accepted for
parity). Glob expansion in `parse` deferred. The blame_attribution
producers wire AnchorBreach end-to-end; the other 4 BlameKind
producers have ready functions + tests + priority but their runtime
surfacing deepens as observability hooks land.
