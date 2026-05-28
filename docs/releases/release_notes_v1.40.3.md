# axon-lang v1.40.3 — Cross-stack parity hotfix (Fase 37.x.j.12 + 38.x.f.10)

**Patch.** Closes two parity gaps left open by v1.40.2: the 5th of 5 stores-crate introspect-masking sites (`row_stream.rs`, missed by 37.x.j.11) and the Python runtime side of the §0 generic-aware preamble (missed by 38.x.f.9 — Rust-only). Both fixes are structural: they restore the **single-runtime contract** (every introspect-in-tx site behaves identically across the store crate) and the **single-language contract** (`axon serve` Python ≡ `axon-rs` Rust on the same `.axon` source).

## Symptom 1 — Stream-cursor introspect masking (Fase 37.x.j.12)

v1.40.2 closed the masking class at 4 cache-MISS sites in [axon-rs/src/store/postgres_backend.rs](axon-rs/src/store/postgres_backend.rs) (`query` / `insert` / `mutate` / `purge`). The **5th site** — the Pillar III lazy cursor path in [axon-rs/src/store/row_stream.rs](axon-rs/src/store/row_stream.rs) line ~263 — was missed.

Adopters running `transport: sse` endpoints with a `retrieve` step against a real table observed the same cascade-error masking the 4 CRUD sites used to surface: `tracing::warn!(target: "axon::store", op = "introspect_in_tx_stream", ...)` fired on introspect failure, then the poisoned tx was re-used with bare-table SELECT, returning a misleading `relation X does not exist` instead of the primary schema-resolution failure.

## Fix 1 — Same shape as 37.x.j.11

The site is converted to the explicit ROLLBACK + propagate pattern:

```rust
let resolved = match introspect_conn(&mut tx, table).await {
    Ok(r) => r,
    Err(introspect_err) => {
        tracing::warn!(
            target: "axon::store",
            d_letter = "37.x.j.12",
            "store introspection failed inside the stream-cursor \
             transaction; rolling back and propagating the primary \
             error to the caller (no bare-table cascade)."
        );
        let _ = tx.rollback().await;
        return Err(introspect_err);
    }
};
```

`backend.cache_schema(table, resolved)` moves out of the `if let Ok(r) = resolved` conditional into a direct unconditional call (`resolved` is now `Ok(...)` by construction on the success path).

## Structural enforcement — new anchor test

New test file [axon-rs/tests/fase37xj_11_12_introspect_propagation.rs](axon-rs/tests/fase37xj_11_12_introspect_propagation.rs) with 4 §-assertions:

- `s_no_fall_through_to_bare_no_types_in_store_crate` — STATIC grep gate scanning PRODUCTION code (comments + `#[cfg(test)]` modules excluded) for the forbidden masking patterns `(None, &no_types)` and `Err(_) => (None,`. Any future PR that reintroduces the pattern turns the test RED before merge.
- `s_every_introspect_conn_site_rollbacks_on_error` — lower-bound count check: `tx.rollback().await` occurrences ≥ `introspect_conn(&mut tx, …)` calls in production code.
- `s_row_stream_site_carries_37xj12_d_letter` — the new site carries `d_letter = "37.x.j.12"` for adopter log correlation.
- `s_postgres_backend_carries_37xj11_d_letter` — the 4 CRUD sites preserve `d_letter = "37.x.j.11"` (regression guard against v1.40.2 rollback).

## Symptom 2 — Python runtime D5 dead-end on List<T> (Fase 38.x.f.10)

v1.40.2 closed the §0 generic-aware preamble on the Rust runtime (`axon-rs/src/route_schema.rs::validate_value`) and shipped 6 Rust unit tests. The symmetric site in `axon/runtime/route_schema.py::_validate_value` was missed — adopters running `axon serve` (Python-based runtime, default for adopters not on the Rust binary) still hit:

```
"axonendpoint declared an unknown body type `List<TenantRecord>` for field `<body>` —
 neither a built-in primitive nor a declared `type` in the deployed source."
```

The Python `_validate_value` jumped straight to §1 primitives without stripping `<Inner>` from `List<T>` / `Stream<T>`, so the raw `"List<TenantRecord>"` string fell through to §5 unknown_type — exactly as the pre-v1.40.2 Rust did.

**Founder principle violated** (memoria `feedback_axon_for_axon`): *"axon es un lenguaje, no varios, sino uno solo"*. A single `.axon` source MUST validate identically on both runtimes.

## Fix 2 — Python mirror of §0 preamble

Insert at the top of `_validate_value` in [axon/runtime/route_schema.py](axon/runtime/route_schema.py):

```python
if not generic_param:
    if type_name.startswith("List<") and type_name.endswith(">"):
        inner = type_name[len("List<"):-1].strip()
        return _validate_value(v, "List", inner, field_path, table, body_type)
    if type_name.startswith("Stream<") and type_name.endswith(">"):
        return None  # SSE chunks validate at the wire layer downstream
```

Recursive — `List<List<T>>` recurses naturally because the inner call lands here again with `type_name = "List<T>"` and strips ANOTHER layer.

## Cross-stack drift gate

12 new Python tests in [tests/test_fase32_body_schema.py](tests/test_fase32_body_schema.py) across two test classes:

1. **`TestFase38xf10GenericAwarePreamble`** — 6 tests byte-paritarios to the Rust v1.40.2 suite (`fase38xf9_validate_body_*` family).

2. **`TestFase38xf10CrossStackDrift`** — 6 cross-stack drift gate tests that lock Python ↔ Rust agreement on the validation tuple for the same `List<T>` / `Stream<T>` corpus. Any divergence breaks BOTH this gate AND its Rust twin, so drift fires on PRs to either stack.

## Test surface

- **2114/2114** axon-lang Rust lib green (unchanged from v1.40.2).
- **447/447** axon-frontend lib green (unchanged from v1.40.2).
- **4/4** new Fase 37.x.j.11+12 anchor §-assertions green.
- **12/12** Fase 37.x.j anchor green (unchanged).
- **12/12** Fase 38.x.f anchor green (unchanged).
- **6/6** Rust 38.x.f.9 route_schema tests green (unchanged from v1.40.2).
- **82/82** Python `test_fase32_body_schema.py` green (12 new 38.x.f.10 tests + 70 preserved).
- Zero regressions cross-stack.

## Migration

**No source-code changes for adopters.** v1.40.2 → v1.40.3 is a runtime-only patch on both stacks.

- Adopters running `axon serve` (Python) with `output: List<T>` / `Stream<T>` on T9XX-typed flows — re-deploy with v1.40.3 and the runtime D5 validation accepts the declared generic shape; no more `unknown body type` dead-ends.
- Adopters running `transport: sse` endpoints with a `retrieve` step against a real table — re-deploy with v1.40.3 and the **primary** introspect error surfaces directly instead of the cascade `relation X does not exist`.

## Plan vivos

- 37.x.j.12 sub-fase appended to [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md) — full diagnostic + structural enforcement narrative.
- 38.x.f.10 sub-fase appended to [docs/fase/fase_38xf_cardinality_coverage_complete.md](docs/fase/fase_38xf_cardinality_coverage_complete.md) — Python parity + drift gate rationale.

## Trigger

Both gaps diagnosed 2026-05-21 from the v1.40.2 hotfix review. The structural pattern in both cases: v1.40.2 closed each architectural seam on **one stack** but not its symmetric counterpart — v1.40.3 closes the symmetric sites, locks the contracts with grep gates + drift tests so the class cannot regress.

axon-frontend stays at 0.21.0 (frontend untouched; only `axon-rs/src/store/row_stream.rs`, `axon/runtime/route_schema.py`, and their test anchors changed).
