# Fase 8.2.h — Rust↔Python IR parity: closure report

**Last synced:** 2026-04-20
**Fixture:** [axon-rs/tests/parity/fase1_through_5_plus_compliance.axon](../axon-rs/tests/parity/fase1_through_5_plus_compliance.axon)
**Python golden:** [axon-rs/tests/parity/fase1_through_5_plus_compliance.python.ir.json](../axon-rs/tests/parity/fase1_through_5_plus_compliance.python.ir.json)
**Rust tests:**
- `cargo test --test integration parity_fase1_5_byte_identical` — **byte-identical** gate (§8.2.h final).
- `cargo test --test integration parity_fase1_5_structural` — structural gate (§8.2.h initial).
- `cargo test --test integration parity_fase1_5_emit` — emits Rust IR next to the Python golden for local diffing.

## Status: byte-identical parity achieved ✓

All originally-catalogued divergences are resolved or strictly scoped:

| ID | Description | Status |
|---|---|---|
| **D1** | Rust `IRProgram.dataspace_specs` emitted where Python omits the field | **Fixed** via `#[serde(skip)]` (§8.2.h.1) |
| **D2** | `intention_tree` root missing in Rust | **Fixed** — `IRIntentionTree` + `IRIntentionOperation::{Manifest, Observe}` untagged-enum; populated during `visit_declaration` (§8.2.h.2) |
| **D3** | `Option<T>` on Shield (`max_retries / confidence_threshold / sandbox`) and Endpoint (`retries`) serialised as `null`; Python emits concrete `0 / 0.0 / false / 0` | **Fixed** — AST keeps `Option<T>` (parser still distinguishes "not set"); IR lowering collapses via `.unwrap_or(default)` (§8.2.h.3) |
| **D4** | CLI `_meta` envelope (source path, backend, axon_version) | Intentionally out-of-scope for core IR parity; stripped in the parity test. Will be reproduced when the Rust CLI ships in §8.6 |

Three additional fixes landed during §8.2.h closure:

- **IRAxonEndpoint** `node_type` changed from `"axonendpoint"` to `"endpoint"` to match Python.
- **IRShield** default `strategy` set to `"pattern"` at lowering time (matches Python dataclass default).
- **IRShield** `taint` field skipped from JSON output (Python's IRShield doesn't carry it; it lives on `ShieldDefinition` AST only).
- **IRSessionStep / IRSessionRole / IRTopologyEdge** now carry `source_line` + `source_column`, matching Python's `IRNode` base class.

## How the byte-identical gate works

The Rust test re-serialises both sides (Python golden + freshly-generated Rust IR) through the **same** `serde_json::to_string_pretty` writer, then diffs line-by-line. This normalises:

- Line endings (Python's `Path.write_text` writes `CRLF` on Windows; `serde_json` always writes `LF`).
- Optional trailing-newline differences.
- `null` vs absent fields (serde writes `null` exactly as Python does).

The test strips the CLI-only `_meta` envelope before comparing — that envelope is a CLI wrapper, not part of IR semantics.

## How to regenerate the Python golden

```
python -m axon.cli compile \
  axon-rs/tests/parity/fase1_through_5_plus_compliance.axon \
  -o axon-rs/tests/parity/fase1_through_5_plus_compliance.python.ir.json
```

## CI integration

`.github/workflows/rust_parity.yml` runs both jobs on every push/PR:

1. `structural-parity` — fast Rust-only check that bucket counts + named-identifier ordering + compliance arrays stay aligned. Protects against shallow regressions.
2. `byte-identical-parity` — regenerates Python golden and runs the byte-identical Rust test. Protects against any IR drift.

## Remaining work (out of scope for §8.2.h)

- **§8.2.h.4** — CLI `_meta` envelope reproduction when the Rust CLI ships (§8.6). Not blocking §8.2 closure.
- Fixtures covering Tier-2 declarations beyond the current fixture (agents, pix, psyche, corpus, mandate, compute, axonstore, lambda_data). Each can be added as `tests/parity/<name>.axon` with a regenerated Python golden; the existing harness applies unchanged.
