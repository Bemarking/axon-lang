# axon-enterprise v1.31.3 — catch-up to axon-lang 1.40.3 (cross-stack parity hotfix, Fase 37.x.j.12 + 38.x.f.10)

**Patch catch-up.** Lifts the enterprise stack to axon-lang 1.40.3, inheriting two parity closures that v1.40.2 left open: the 5th of 5 stores-crate introspect-masking sites (`row_stream.rs`, missed by 37.x.j.11) and the Python runtime side of the §0 generic-aware preamble (missed by 38.x.f.9 — Rust-only).

## What enterprise tenants get

Two structural-parity fixes inherited via the axon-lang 1.40.3 dep pin bump:

### 1. Stream-cursor introspect propagation (Fase 37.x.j.12)

v1.40.2 closed the masking class at 4 cache-MISS sites in `axon-rs/src/store/postgres_backend.rs` (`query` / `insert` / `mutate` / `purge`). The **5th site** — the Pillar III lazy cursor in `axon-rs/src/store/row_stream.rs` line ~263 — was missed.

Enterprise tenants running `transport: sse` endpoints with a `retrieve` step against a real table observed the same cascade-error masking that v1.40.2 closed for the 4 CRUD sites: introspect failure → `tracing::warn!` → poisoned tx re-used with bare-table SELECT → misleading `relation X does not exist` returned to the application layer instead of the primary schema-resolution failure.

v1.40.3 closes the gap with the same ROLLBACK + propagate pattern; new `d_letter = "37.x.j.12"` tracing field anchors the site for log correlation.

### 2. Python runtime D5 generic-aware (Fase 38.x.f.10)

v1.40.2 closed the §0 generic-aware preamble on the Rust runtime only. The Python runtime `axon/runtime/route_schema.py::_validate_value` was missed.

Enterprise tenants running `axon serve` (Python-based runtime, default for adopters not on the Rust binary) STILL hit `unknown body type List<TenantRecord>` after v1.40.2 — because the Python validator never stripped `<T>` and fell through to §5 unknown_type.

**Founder principle**: *"axon es un lenguaje, no varios, sino uno solo"* — cross-runtime parity is mandatory.

v1.40.3 mirrors the §0 preamble in Python + adds 12 new tests (6 byte-paritarios + 6 cross-stack drift gate locking Python ↔ Rust agreement on the validation tuple for `List<T>` / `Stream<T>` corpus).

## Structural enforcement

New test file `axon-rs/tests/fase37xj_11_12_introspect_propagation.rs` ships 4 §-assertions including a STATIC grep gate scanning PRODUCTION code under `axon-rs/src/store/` for the forbidden masking patterns `(None, &no_types)` and `Err(_) => (None,`. Any future PR that reintroduces a 6th store-introspect site without the explicit ROLLBACK + propagate pattern turns the test RED before merge.

12 new Python tests in `tests/test_fase32_body_schema.py` (`TestFase38xf10GenericAwarePreamble` + `TestFase38xf10CrossStackDrift`) lock the Python ↔ Rust parity contract for the §0 preamble. Drift fires on PRs to either stack.

## Vertical impact

Both gaps affected all regulated-vertical enterprise tenants:

- **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** — `transport: sse` clinical-reasoning flows hitting Pillar III lazy cursors against PHI tables + `axon serve` Python deployments with `output: List<PhiRecord>` on T9XX-typed clinical-decision flows.
- **FRE 502 + Upjohn / Hickman** — streaming privilege-review flows over legal document corpora + Python deployments with `output: List<DocumentReview>` body schemas.
- **BSA / OFAC / MiFID II AML** — streaming investigative flows against fintech transaction stores + Python deployments with `output: List<Transaction>` body schemas.
- **FedRAMP AU-2** — streaming decision-support flows over government record stores + Python deployments with `output: List<BenefitsClaim>` body schemas.

v1.31.3 closes both gaps structurally via the upstream axon-lang 1.40.3 fixes. Re-deploy the Docker image; no source-code changes required for `.axon` flows.

## Catch-up surface

- `pyproject.toml`: version 1.31.2 → 1.31.3, dep pin `axon-lang>=1.40.2` → `>=1.40.3`.
- `axon_enterprise/__init__.py`: `__version__` 1.31.2 → 1.31.3.

axon-frontend Rust crate dep stays at **0.21.0** (frontend untouched; only `axon-rs/src/store/row_stream.rs`, `axon/runtime/route_schema.py`, and their anchor tests changed in axon-lang 1.40.3).

## Migration

**No source-code changes required.** v1.31.2 → v1.31.3 is a runtime-only Docker image update.

Per standing rule (every axon-lang release ships an axon-enterprise catch-up): v1.31.3 closes the cycle in lockstep with axon-lang v1.40.3.

## Plan vivos

- Fase 37.x.j REOPENED 2026-05-21 for sub-fase 37.x.j.12 (row_stream introspect propagation) — see [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md) §10.
- Fase 38.x.f REOPENED 2026-05-21 for sub-fase 38.x.f.10 (Python parity of §0 generic-aware preamble) — see [docs/fase/fase_38xf_cardinality_coverage_complete.md](docs/fase/fase_38xf_cardinality_coverage_complete.md) §10.
