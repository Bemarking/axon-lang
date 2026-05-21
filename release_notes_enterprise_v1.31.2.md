# axon-enterprise v1.31.2 — catch-up to axon-lang 1.40.2 (introspection error propagation + generic-aware body validation, Fase 37.x.j.11 + 38.x.f.9)

**Patch catch-up.** Lifts the enterprise stack to axon-lang 1.40.2, inheriting two distinct gap closures shipped together for adopter convenience: Postgres backend now surfaces the **real** introspect error instead of masking it behind a cascade SQL failure, and D5 runtime body validation now parses `List<T>` / `Stream<T>` declarations instead of dead-ending on T9XX-typed flows whose body schemas reference generic surfaces.

## What enterprise tenants get

Two independent fixes inherited via the axon-lang 1.40.2 dep pin bump:

### 1. Introspection error propagation (Fase 37.x.j.11)

Pre-v1.40.2 (i.e. v1.31.1 and prior): when `introspect_conn` failed in the Postgres backend, the runtime logged a `tracing::warn!` and fell through to bare-table SQL inside the same transaction. The bare-table SQL cascaded with `relation X does not exist` — masking the **real** upstream schema-resolution failure (privilege / search_path / SSL / pooler-mode). Adopters chasing the cascade error wasted hours debugging the wrong layer.

v1.40.2 closes the gap at 4 sites in `axon-rs/src/store/postgres_backend.rs` (`query`, `insert`, `mutate`, `purge`): introspect failure now (1) emits a warn with `d_letter="37.x.j.11"` tracing field, (2) rolls back the transaction explicitly via `tx.rollback().await`, (3) returns the primary `introspect_err` directly. Adopters see the **real** error verbatim.

### 2. Generic-aware D5 body validation (Fase 38.x.f.9)

Pre-v1.40.2: flows declared with body schemas referencing `List<TenantRecord>` or `Stream<ProgressEvent>` would compile cleanly (T9XX cardinality coverage from Fase 38.x.f passed) but error at **runtime** during D5 output body validation with `type "List<TenantRecord>" is not known`. Root cause: `validate_value` in `axon-rs/src/route_schema.rs` checked `type_name == "List"` at §3 — but the IR string was `"List<TenantRecord>"` (generics unstripped). Architectural seam between Fase 38.x.f (compile-time) and Fase 32.d (runtime D5 body validation).

v1.40.2 closes the seam with a §0 generic-aware preamble at the top of `validate_value` that strips angle-brackets for `List<T>` and recurses with `type_name="List"` + `generic_param="T"` → §3 path activates correctly. Nested `List<List<T>>` recurses naturally. `Stream<T>` returns Ok early (SSE wire layer validates downstream).

## Vertical impact

Both gaps affected all regulated-vertical enterprise tenants:

- **HIPAA Safe Harbor + 21 CFR Part 11** clinical records — introspect masking on PHI table schema-resolution failures + generic body schemas on `List<PhiRecord>` clinical-reasoning flows
- **FRE 502 + Upjohn / Hickman** legal document stores — introspect masking on privilege-log schema-resolution + generic body schemas on `List<DocumentReview>` review flows
- **BSA / OFAC / MiFID II AML** fintech transaction stores — introspect masking on aml_events schema-resolution + generic body schemas on `List<Transaction>` investigative flows
- **FedRAMP AU-2** government record stores — introspect masking on record-store schema-resolution + generic body schemas on `List<BenefitsClaim>` decision flows

v1.31.2 closes both hazards structurally via the upstream axon-lang 1.40.2 fixes. Re-deploy the Docker image; no source-code changes required for `.axon` flows.

## Fix architecture (inherited)

Two landing pieces:

1. **`axon-rs/src/store/postgres_backend.rs`** — 4 sites converted to the explicit `match introspect_conn(...).await` + `tx.rollback().await` + `return Err(introspect_err)` pattern. Cache-write `self.cache_schema(table, resolved)` moved into the `Ok` arm (single-consumption invariant).

2. **`axon-rs/src/route_schema.rs`** — new §0 preamble at the top of `validate_value`:

   ```rust
   if generic_param.is_empty() {
       if let Some(rest) = type_name.strip_prefix("List<") {
           if let Some(inner) = rest.strip_suffix('>') {
               return validate_value(v, "List", inner.trim(), field_path, table, body_type);
           }
       }
       if let Some(rest) = type_name.strip_prefix("Stream<") {
           if rest.ends_with('>') {
               return Ok(());
           }
       }
   }
   ```

   Plus 6 new unit tests anchoring the fix.

## Catch-up surface

- `pyproject.toml`: version 1.31.1 → 1.31.2, dep pin `axon-lang>=1.40.1` → `>=1.40.2`.
- `axon_enterprise/__init__.py`: `__version__` 1.31.1 → 1.31.2.

axon-frontend Rust crate dep stays at **0.21.0** (frontend untouched; only `axon-rs/src/store/postgres_backend.rs` + `axon-rs/src/route_schema.rs` + their unit tests changed in axon-lang 1.40.2).

## Migration

**No source-code changes required.** v1.31.1 → v1.31.2 is a runtime-only Docker image update.

- Adopters chasing cascade `relation X does not exist` errors when the real issue is upstream schema resolution → re-deploy with v1.31.2 and the **primary** introspect error surfaces directly.
- Adopters with `List<T>` / `Stream<T>` in body schemas of T9XX-typed flows → 400 schema-validation errors clear up; flows execute end-to-end.

Per standing rule (every axon-lang release ships an axon-enterprise catch-up): v1.31.2 closes the cycle in lockstep with axon-lang v1.40.2.

## Plan vivos

- Fase 37.x.j REOPENED 2026-05-21 for sub-fase 37.x.j.11 (introspect error propagation) — see [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md) §37.x.j.11.
- Fase 38.x.f REOPENED 2026-05-21 for sub-fase 38.x.f.9 (generic-aware D5 body validation) — see [docs/fase/fase_38xf_cardinality_coverage_complete.md](docs/fase/fase_38xf_cardinality_coverage_complete.md) §38.x.f.9.
