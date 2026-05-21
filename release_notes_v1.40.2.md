# axon-lang v1.40.2 — Introspection error propagation + generic-aware body validation (Fase 37.x.j.11 + 38.x.f.9)

**Patch.** Closes two distinct gaps surfaced by adopter operational logs after the v1.40.0 + v1.40.1 cycle. Both are independent fixes shipped together for adopter convenience: Postgres backend now surfaces the **real** introspect error instead of masking it behind a cascade SQL failure, and D5 runtime body validation now parses `List<T>` / `Stream<T>` declarations instead of dead-ending on T9XX-typed flows whose body schemas reference generic surfaces.

## Symptom 1 — Introspection error masked behind cascade (Fase 37.x.j.11)

Adopter logs:

```
WARN axon::store: introspect failed for table 'tenants', falling back to bare table reference
ERROR axon::store: SQL error: relation "tenants" does not exist
```

The fall-through path in `query` / `insert` / `mutate` / `purge` was: when `introspect_conn(&mut tx, table).await` failed, the code logged a `tracing::warn!` and reused `(None, &empty_types)` to build SQL with the bare table name. That SQL then errored inside the same transaction (because the table genuinely lives in `tenant_<uuid>` schema, not `public`), and the **cascade** error was surfaced to the application — masking the **primary** schema-resolution failure.

**Adopters chasing the cascade error wasted hours debugging "missing table" when the real issue was an introspect privilege / search_path / SSL / pooler-mode upstream of SQL dispatch.**

## Fix 1 — ROLLBACK + propagate primary error directly

At 4 sites in [axon-rs/src/store/postgres_backend.rs](axon-rs/src/store/postgres_backend.rs) (`query`, `insert`, `mutate`, `purge`), the fall-through to bare-table SQL is removed. The new pattern:

```rust
let resolved = match introspect_conn(&mut tx, table).await {
    Ok(r) => r,
    Err(introspect_err) => {
        tracing::warn!(
            target: "axon::store",
            d_letter = "37.x.j.11",
            "introspection failed; rolling back transaction and propagating error"
        );
        let _ = tx.rollback().await;
        return Err(introspect_err);
    }
};
```

- Transaction is **rolled back** explicitly (rather than silently re-using a poisoned tx for the cascade SQL).
- Primary `introspect_err` is propagated directly to the caller — adopters see the schema-resolution failure as-is, no masking.
- `d_letter = "37.x.j.11"` tracing field anchors the log to this sub-fase for future grep.

The cache-write `self.cache_schema(table, resolved)` still happens on the success path (moved into the `Ok` arm so `resolved` is consumed once).

## Symptom 2 — T9XX↔D5 dead-end on generic body schemas (Fase 38.x.f.9)

Flows declared with body schemas referencing `List<TenantRecord>` or `Stream<ProgressEvent>` would compile cleanly (T9XX cardinality coverage from Fase 38.x.f passed) but error at **runtime** during D5 output body validation with:

```
error: type "List<TenantRecord>" is not known
```

Root cause: `validate_value` in [axon-rs/src/route_schema.rs](axon-rs/src/route_schema.rs) checked `type_name == "List"` at §3 — but the type_name string from the IR was `"List<TenantRecord>"` (the generic angle-brackets weren't stripped). Fall-through to §5 hit the "unknown type" branch.

**This is a T9XX↔D5 architectural seam.** Fase 38.x.f closed the compile-time gap for generic cardinality, but the runtime body validator was never updated to parse the generic surface form.

## Fix 2 — §0 generic-aware preamble in validate_value

New §0 preamble at the top of `validate_value` ([axon-rs/src/route_schema.rs](axon-rs/src/route_schema.rs)) handles `List<T>` and `Stream<T>` BEFORE §1 primitive matching:

```rust
fn validate_value(v: &Value, type_name: &str, generic_param: &str, ...) -> ... {
    // §0 — §Fase 38.x.f.9 generic-aware parsing
    if generic_param.is_empty() {
        if let Some(rest) = type_name.strip_prefix("List<") {
            if let Some(inner) = rest.strip_suffix('>') {
                return validate_value(v, "List", inner.trim(), field_path, table, body_type);
            }
        }
        if let Some(rest) = type_name.strip_prefix("Stream<") {
            if rest.ends_with('>') {
                return Ok(()); // SSE chunks validate at wire layer
            }
        }
    }
    // §1 primitives …  §2 enum …  §3 List<T> via validate_list …  §4 struct …  §5 unknown
}
```

- `List<T>` strips angle-brackets and recurses with `type_name="List"` + `generic_param="T"` → §3 path activates correctly. Nested forms (`List<List<T>>`) recurse naturally.
- `Stream<T>` is the SSE wire-layer responsibility (per Fase 33 architecture); the body validator returns Ok early because SSE chunks are validated downstream at the wire layer, not at request-body time.
- The `generic_param.is_empty()` guard means an inner recursion call won't re-enter §0 (idempotent).

6 new unit tests in `axon-rs/src/route_schema.rs::tests` anchor the fix:

- `fase38xf9_validate_body_accepts_list_of_primitive`
- `fase38xf9_validate_body_accepts_list_of_struct`
- `fase38xf9_validate_body_rejects_list_of_unknown_inner`
- `fase38xf9_validate_body_rejects_list_against_non_array`
- `fase38xf9_validate_body_accepts_nested_list_of_list`
- `fase38xf9_validate_body_stream_returns_ok_early`

## Test surface

- **2114/2114** axon-lang lib green (post-fix).
- **447/447** axon-frontend lib green (unchanged from v1.40.1).
- **12/12** Fase 37.x.j anchor green (unchanged from v1.40.1).
- **12/12** Fase 38.x.f anchor green (unchanged from v1.40.0).
- **6/6** new 38.x.f.9 generic-aware route_schema tests green.
- Zero regressions cross-stack.

## Migration

**No source-code changes for adopters.** v1.40.1 → v1.40.2 is a runtime-only patch.

- Adopters chasing cascade "relation X does not exist" errors when the real issue is upstream schema resolution → re-deploy with v1.40.2 and the **primary** introspect error surfaces directly.
- Adopters with `List<T>` / `Stream<T>` in body schemas of T9XX-typed flows → 400 schema-validation errors clear up; flows execute end-to-end.

## Plan vivos

- 37.x.j.11 sub-fase appended to [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md) with full diagnostic + fix narrative.
- 38.x.f.9 sub-fase appended to [docs/fase/fase_38xf_cardinality_coverage_complete.md](docs/fase/fase_38xf_cardinality_coverage_complete.md) with §0 preamble rationale + 6-test anchor.

## Trigger

Both gaps diagnosed 2026-05-21 from adopter operational reports. Both are architectural seams (introspect↔SQL dispatch composition + T9XX↔D5 runtime composition) that the v1.40.0 + v1.40.1 cycle didn't cover. v1.40.2 closes them in a single hotfix.

axon-frontend stays at 0.21.0 (frontend untouched; only `axon-rs/src/store/postgres_backend.rs` + `axon-rs/src/route_schema.rs` and their unit tests changed).
