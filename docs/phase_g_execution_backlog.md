# Backlog de Ejecución — Fase G

Este archivo lista las sesiones planeadas y ejecutadas para la Fase G (Persistencia y Evolución) del programa AXON.

## Objetivo de Fase

Completar las primitivas cognitivas pendientes de implementación runtime (AxonStore, Dataspace), evolucionar el lenguaje, y validar end-to-end con backends reales. La Fase D entregó la plataforma (192 rutas), la Fase E conectó backends y MCP (7 métodos JSON-RPC), la Fase F endureció para producción (10-stage pipeline, 621 tests). La Fase G cierra el gap entre primitivas declaradas y runtime operativo.

## Estado heredado de Fase F

| Métrica | Valor |
|---------|-------|
| Módulos fuente | 61 archivos `.rs` |
| Líneas fuente | 48,999 |
| Tests de integración | 621 |
| Rutas API (HTTP) | 192 |
| Métodos MCP (JSON-RPC) | 7 (initialize, tools/list, tools/call, resources/list, resources/read, prompts/list, prompts/get) |
| Structs públicos (server) | 132 |
| Backends soportados | 7 (anthropic, openai, gemini, kimi, glm, openrouter, ollama) |
| Primitivas cognitivas | 47 (20 declarations + 4 epistemic + 14 execution + 9 navigation) |
| Backend registry | 22 campos por entry, 10-stage pipeline |
| Optimizer | 4 estrategias (cheapest, fastest, most_reliable, balanced) |
| Rate limiting | RPM/TPM por backend con ventana 60s |
| Protocolo MCP | 100% (tools + resources + prompts + streaming) |
| Formal alignment | ΛD, blame CT-2/CT-3, CSP §5.3, effect rows, Theorem 5.1, 47 primitivas codificadas |

## Backlog Inicial

1. AxonStore persistence — conectar la primitiva `axonstore` a almacenamiento durable (file/SQLite).
2. Dataspace runtime — implementar la primitiva `dataspace` con `ingest`, `focus`, `associate`, `aggregate`, `explore`.
3. End-to-end validation — test harness para validación con backends LLM reales y cost caps.
4. Language evolution — nuevas primitivas, pattern matching, módulos.
5. Client SDKs — clientes TypeScript/Python para el servidor ℰMCP.
6. Horizontal scaling — coordinación multi-instancia, estado compartido.

## Sesiones

**Handoff G1:**
- **A:** AxonStore persistence — wire `axonstore`/`persist`/`retrieve`/`mutate`/`purge`/`transact` primitives to file-based durable storage. 
- **B:** Dataspace runtime — implement `dataspace` declaration with `ingest`/`focus`/`associate`/`aggregate`/`explore` step primitives.
- **C:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **D:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **E:** Backend usage dashboard — `GET /v1/backends/dashboard` aggregate view: calls, cost, limits, circuit state, ranking per backend.

---

### G1 — Backend Usage Dashboard (Option E)

**Scope:** `GET /v1/backends/dashboard` — single-endpoint aggregate view of the entire backend fleet.

**Delivered:**

1. **`backends_dashboard_handler`** (`axon_server.rs`):
   - Per-backend summary: name, enabled, status, circuit state (closed/half-open/open), consecutive failures, calls, errors, error rate, tokens I/O, avg latency, cost USD, last call timestamp, rate limits (with remaining capacity), fallback chain.
   - Fleet-wide aggregates: total backends, enabled count, circuit-open count, degraded count, total calls/errors/tokens/cost, fleet error rate, fleet avg latency.
   - Balanced optimizer ranking: reuses `compute_backend_scores("balanced")` to include scoring and recommended backend.

2. **Circuit state classification:**
   - `"open"` — `circuit_open_until > 0 && now < circuit_open_until`
   - `"half-open"` — `consecutive_failures > 0` but circuit not open
   - `"closed"` — no failures, circuit closed

3. **Rate limit remaining:** Computes RPM/TPM remaining within 60s window; resets to full capacity when window expires.

4. **Route registered:** `GET /v1/backends/dashboard` → 193 total routes.

**Tests added (3):**
- `test_backend_dashboard_fleet_aggregation` — validates fleet-wide sums across 2 backends (calls, errors, cost, tokens, avg latency, error rate)
- `test_backend_dashboard_circuit_state_classification` — validates closed/open/half-open classification and fleet counts (enabled, circuit-open, degraded)
- `test_backend_dashboard_rate_limit_remaining` — validates RPM/TPM remaining within active window and after window expiry reset

**Evidence:**
- `cargo test` → 624 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 192 | 193 |
| Tests | 621 | 624 |
| Source lines | ~48,999 | ~49,130 |

---

**Handoff G2:**
- **A:** AxonStore persistence — wire `axonstore`/`persist`/`retrieve`/`mutate`/`purge`/`transact` primitives to file-based durable storage.
- **B:** Dataspace runtime — implement `dataspace` declaration with `ingest`/`focus`/`associate`/`aggregate`/`explore` step primitives.
- **C:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **D:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **E:** Backend health probing — automated periodic `POST /v1/backends/{name}/check` with configurable intervals and status history tracking.

---

### G2 — AxonStore Cognitive Persistence (Option A)

**Scope:** Wire the `axonstore` cognitive primitive (#18 of 47) to runtime with ΛD-compliant epistemic envelopes on every entry.

**Delivered:**

1. **Structs (3 new pub structs → 135 total):**
   - `AxonStoreEntry` — key/value + `EpistemicEnvelope` + version tracking + timestamps
   - `AxonStoreInstance` — named store with ontology type hint, entry map, ops counter
   - `AxonStoreTransactOp` — operation descriptor for batch transactions

2. **Handlers (8 new, 7 route registrations → 201 total):**
   - `POST /v1/axonstore` — create named store with ontology
   - `GET /v1/axonstore` — list all stores with metadata
   - `GET /v1/axonstore/{name}` — introspect store (all entries with envelopes)
   - `DELETE /v1/axonstore/{name}` — delete store and all entries
   - `POST /v1/axonstore/{name}/persist` — store entry (c=1.0, δ=raw)
   - `GET /v1/axonstore/{name}/retrieve/{key}` — retrieve entry with full ΛD envelope
   - `POST /v1/axonstore/{name}/mutate` — update entry (c≤0.99, δ=derived per Theorem 5.1)
   - `POST /v1/axonstore/{name}/purge` — delete entry
   - `POST /v1/axonstore/{name}/transact` — atomic batch (all-or-nothing validation)

3. **ΛD Formal Alignment:**
   - `persist` → `EpistemicEnvelope::raw_config()` → c=1.0, δ=raw
   - `mutate` → `EpistemicEnvelope::derived()` → c=0.99 (clamped), δ=derived
   - Theorem 5.1 enforced: only raw writes carry c=1.0; mutations always degrade
   - Each entry carries full ψ = ⟨T, V, E⟩ where E = ⟨c, τ, ρ, δ⟩
   - `transact`: all-or-nothing validation prevents partial state corruption

4. **ServerState extended:** `axon_stores: HashMap<String, AxonStoreInstance>` field added

**Tests added (3):**
- `test_axonstore_persist_retrieve_with_epistemic_envelope` — persist raw entry (c=1.0, δ=raw), retrieve, validate ΛD envelope
- `test_axonstore_mutate_degrades_certainty_theorem_5_1` — mutate degrades c to 0.99, δ to derived; validates Theorem 5.1 violation detection (c=1.0 + derived → error)
- `test_axonstore_transact_batch_and_purge` — batch persist 3 entries, mutate one, purge another, validate all-or-nothing semantics

**Evidence:**
- `cargo test` → 627 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 193 | 201 |
| Tests | 624 | 627 |
| Pub structs | 132 | 135 |
| Source lines | ~49,130 | ~49,530 |

---

**Handoff G3:**
- **A:** Dataspace runtime — implement `dataspace` declaration with `ingest`/`focus`/`associate`/`aggregate`/`explore` step primitives and ΛD envelopes.
- **B:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **C:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **D:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **E:** AxonStore file persistence — flush AxonStore instances to disk (JSON) and restore on server restart.

---

### G3 — Dataspace Cognitive Navigation (Option A)

**Scope:** Wire the `dataspace` declaration (primitive #13) and its 5 navigation step-primitives (`ingest`/`focus`/`associate`/`aggregate`/`explore`, primitives #44-47 + `ingest`) to runtime with ΛD-compliant epistemic envelopes.

**Delivered:**

1. **Structs (3 new pub structs → 138 total):**
   - `DataspaceEntry` — id, ontology, data (JSON), `EpistemicEnvelope`, tags, ingested_at
   - `DataspaceAssociation` — from/to entry IDs, relation name, certainty (clamped ≤0.99), created_at
   - `DataspaceInstance` — named container with entries map, associations vec, ontology, ops counter, auto-id

2. **Handlers (8 new, 7 route registrations → 208 total):**
   - `POST /v1/dataspace` — create named dataspace with ontology
   - `GET /v1/dataspace` — list all dataspaces with metadata
   - `DELETE /v1/dataspace/{name}` — delete dataspace and all entries/associations
   - `POST /v1/dataspace/{name}/ingest` — add entry (c=1.0, δ=raw)
   - `POST /v1/dataspace/{name}/focus` — filter by ontology/tags with limit (result c≤0.99, δ=derived)
   - `POST /v1/dataspace/{name}/associate` — link two entries by relation (c clamped ≤0.99)
   - `POST /v1/dataspace/{name}/aggregate` — reduce: count/sum/avg/min/max over numeric field path (result c≤0.99, δ=aggregated)
   - `GET /v1/dataspace/{name}/explore` — structural discovery: ontology distribution, tag frequency, relation types, epistemic summary

3. **ΛD Formal Alignment:**
   - `ingest` → `EpistemicEnvelope::raw_config()` → c=1.0, δ=raw (direct data ingestion)
   - `focus` → result envelope c=0.99, δ=derived (Theorem 5.1: filtering is derived computation)
   - `associate` → certainty clamped [0, 0.99] (associations are derived knowledge)
   - `aggregate` → result envelope c=0.99, δ=aggregated (reduction over raw data)
   - `explore` → result envelope c=0.99, δ=derived (introspection is derived)

4. **ServerState extended:** `dataspaces: HashMap<String, DataspaceInstance>` field added

**Tests added (3):**
- `test_dataspace_ingest_focus_with_epistemic_envelopes` — ingest 3 entries (2 observations + 1 hypothesis), focus by ontology and tags, validate all raw entries carry c=1.0
- `test_dataspace_associate_and_explore` — ingest concepts, create associations with clamped certainty, explore ontology distribution and relation types
- `test_dataspace_aggregate_operations` — ingest 5 scored entries, validate count/sum/avg/min/max, confirm aggregation results are derived (c≤0.99)

**Evidence:**
- `cargo test` → 630 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 201 | 208 |
| Tests | 627 | 630 |
| Pub structs | 135 | 138 |
| Source lines | ~49,530 | ~49,870 |

**Primitives wired to runtime (cumulative):**
- `axonstore` (#18): persist/retrieve/mutate/purge/transact — G2
- `dataspace` (#13): ingest/focus/associate/aggregate/explore — G3
- Total: 2 declaration primitives + 10 step operations connected to live HTTP API

---

**Handoff G4:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore/Dataspace file persistence — flush stores to disk (JSON) and restore on server restart.
- **E:** Dataspace EMCP exposition — expose dataspaces as EMCP resources (resources/list, resources/read) with ΛD envelopes.

---

### G4 — Dataspace/AxonStore ℰMCP Exposition (Option E)

**Scope:** Expose dataspaces and axonstores as MCP resources via `resources/list` and `resources/read`, with full ΛD epistemic envelopes and CT-2 blame on errors.

**Delivered:**

1. **MCP `resources/list` — 4 new resource categories:**
   - `axon://dataspaces` — registry of all cognitive dataspaces
   - `axon://dataspaces/{name}` — individual dataspace (entries + associations + ontology)
   - `axon://axonstores` — registry of all cognitive persistence stores
   - `axon://axonstores/{name}` — individual axonstore (entries + versions + envelopes)
   - Dynamic: each dataspace/axonstore instance appears as a separate MCP resource with metadata in description

2. **MCP `resources/read` — 4 new URI handlers:**
   - `axon://dataspaces` → all dataspaces with entry/association counts + `_epistemic` (c=1.0, δ=raw)
   - `axon://dataspaces/{name}` → full dump: entries with per-entry ΛD envelope, associations with certainty
   - `axon://axonstores` → all stores with entry counts + `_epistemic`
   - `axon://axonstores/{name}` → full dump: entries with key/value/version + per-entry ΛD envelope

3. **Formal Alignment:**
   - Every resource read carries `_epistemic` block with ontology, certainty, derivation, provenance
   - Registry reads: c=1.0, δ=raw (authoritative server state)
   - Per-entry reads: propagate the entry's actual ΛD envelope (raw or derived depending on history)
   - Error responses carry `_axon_blame: { blame: "caller", reason: "CT-2" }` per Findler-Felleisen

4. **No new routes** — all changes within existing `POST /v1/mcp` JSON-RPC handler

**Tests added (3):**
- `test_emcp_dataspace_resource_serialization` — validate resources/list format and resources/read entry with ΛD _epistemic block (c=1.0, δ=raw)
- `test_emcp_axonstore_resource_serialization` — validate raw vs derived entries in MCP read, confirm Theorem 5.1 (raw=1.0, derived=0.99)
- `test_emcp_resource_blame_on_missing_dataspace` — validate CT-2 (caller) blame on non-existent resource URIs for both dataspace and axonstore

**Evidence:**
- `cargo test` → 633 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 208 | 208 (no new routes, MCP handler extended) |
| Tests | 630 | 633 |
| MCP resource types | 4 (traces/recent, metrics, backends, flows) | 8 (+dataspaces, +dataspaces/{n}, +axonstores, +axonstores/{n}) |

---

**Handoff G5:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore/Dataspace file persistence — flush stores to disk (JSON) and restore on server restart.
- **E:** Dataspace ℰMCP tools — expose `ingest`/`focus`/`aggregate` as MCP tools (tools/list, tools/call) with CSP §5.3 schemas.

---

### G5 — Dataspace ℰMCP Tools (Option E)

**Scope:** Expose dataspace operations as MCP tools via `tools/list` and `tools/call`, with CSP §5.3 typed schemas, ΛD envelopes, and blame calculus on errors.

**Delivered:**

1. **MCP `tools/list` — 3 tool types per dataspace:**
   - `axon_ds_{name}_ingest` — ingest data with CSP schema: `required: ["data"]`, effect `<io, epistemic:know>`, taint `Raw`
   - `axon_ds_{name}_focus` — filter entries with CSP schema: constraints `result ⊆ dataspace`, effect `<io, epistemic:speculate>`, taint `Uncertainty`
   - `axon_ds_{name}_aggregate` — reduce with CSP schema: `op ∈ {count,sum,avg,min,max}`, effect `<io, epistemic:speculate>`, taint `Uncertainty`
   - Each tool carries `_axon_csp` block with constraints, effect_row, output_taint per §5.3

2. **MCP `tools/call` — dataspace dispatch:**
   - Tool name parsing: `axon_ds_{name}_{op}` → `rfind('_')` splits name from op
   - `ingest`: creates entry with ΛD raw envelope (c=1.0), lattice "know", effect `[io, epistemic:know]`
   - `focus`: filters and returns JSON results, ΛD derived (c=0.99), lattice "speculate"
   - `aggregate`: computes count/sum/avg/min/max, ΛD derived (c=0.99), δ=aggregated
   - All responses include `_axon` metadata: epistemic_envelope, lattice_position, effect_row, blame
   - Errors carry CT-2 blame (caller) per Findler-Felleisen

3. **Formal Alignment:**
   - CSP §5.3: each tool has typed `inputSchema` with `_axon_csp` constraints block
   - ΛD: ingest=raw (c=1.0), focus/aggregate=derived (c≤0.99, Theorem 5.1)
   - Epistemic lattice: ingest→know, focus→speculate, aggregate→speculate
   - Effect rows: computed from operation type
   - Blame: CT-2 on bad dataspace name or unknown op

**Tests added (3):**
- `test_emcp_dataspace_tool_name_parsing` — validates `axon_ds_{name}_{op}` parsing with rfind for multi-word dataspace names
- `test_emcp_dataspace_tool_csp_schemas` — validates CSP §5.3 schema structure: _axon_csp constraints, effect_row, output_taint for all 3 ops
- `test_emcp_dataspace_tool_call_epistemic_envelopes` — validates ΛD envelopes per op (raw/derived), lattice positions, effect rows, Theorem 5.1 enforcement

**Evidence:**
- `cargo test` → 636 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 208 | 208 (MCP handler extended, no new routes) |
| Tests | 633 | 636 |
| MCP tool types | flow-only | flow + 3 per dataspace (ingest/focus/aggregate) |
| MCP resource types | 8 | 8 |

---

**Handoff G6:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore/Dataspace file persistence — flush stores to disk (JSON) and restore on server restart.
- **E:** AxonStore ℰMCP tools — expose `persist`/`retrieve`/`mutate`/`purge` as MCP tools with CSP §5.3 schemas and Theorem 5.1 enforcement.

---

### G6 — AxonStore/Dataspace File Persistence (Option D)

**Scope:** Wire AxonStore and Dataspace instances into the existing `ServerBackup` serialization pipeline so they survive server restarts via `persist`/`recover` and `backup`/`restore`.

**Delivered:**

1. **`ServerBackup` struct extended:**
   - Added `axon_stores: HashMap<String, AxonStoreInstance>` with `#[serde(default)]`
   - Added `dataspaces: HashMap<String, DataspaceInstance>` with `#[serde(default)]`
   - Backward compatible: old backups without these fields deserialize cleanly (empty maps)

2. **3 handlers updated to include stores:**
   - `server_backup_handler` (POST /v1/server/backup) — serializes stores to JSON response
   - `server_persist_handler` (POST /v1/server/persist) — writes stores to disk, section count 7→9
   - `build_server_backup()` helper — includes stores in auto-persist path

3. **2 handlers updated to restore stores:**
   - `server_restore_handler` (POST /v1/server/restore) — merges stores from JSON backup (no overwrite)
   - `server_recover_handler` (POST /v1/server/recover) — merges stores from disk file (no overwrite)
   - Both report `axon_stores_restored` and `dataspaces_restored` counts

4. **ΛD provenance:** Per-section epistemic envelopes added for `axon_stores` and `dataspaces` sections

5. **Merge semantics:** Restore/recover never overwrites existing in-memory stores (merge-only), preserving runtime state

**Tests added (3):**
- `test_server_backup_includes_axon_stores_and_dataspaces` — backup with populated store+dataspace, round-trip serialization, verify entries/values/next_id preserved
- `test_server_backup_backward_compatible_without_stores` — deserialize old-format backup (no store fields), verify `#[serde(default)]` produces empty maps
- `test_server_backup_epistemic_envelopes_preserved_on_roundtrip` — raw entry (c=1.0, δ=raw) and derived entry (c=0.95, δ=derived) survive serialization with ΛD invariants intact

**Evidence:**
- `cargo test` → 639 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 208 | 208 (existing handlers extended) |
| Tests | 636 | 639 |
| Backup sections | 7 | 9 (+axon_stores, +dataspaces) |

---

**Handoff G7:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore ℰMCP tools — expose `persist`/`retrieve`/`mutate`/`purge` as MCP tools with CSP §5.3 schemas and Theorem 5.1 enforcement.
- **E:** Cognitive primitive inventory endpoint — `GET /v1/primitives` with per-primitive runtime status (wired/pending), ΛD alignment, and coverage metrics.

---

### G7 — Cognitive Primitive Inventory (Option E)

**Scope:** `GET /v1/primitives` �� single endpoint reporting all 47 AXON cognitive primitives with per-primitive runtime wiring status, coverage metrics, and ΛD formal alignment metadata.

**Delivered:**

1. **`primitives_handler`** (`axon_server.rs`):
   - Enumerates all 47 primitives across 4 categories (20 declarations + 14 step + 4 epistemic + 9 navigation)
   - Per-primitive: name, status (`wired`/`pending`), endpoint/mechanism, phase wired in
   - Fleet metrics: total, wired count, pending count, coverage percentage
   - ΛD alignment block: EpistemicEnvelope formula, Theorem 5.1, epistemic lattice, blame calculus taxonomy, CSP §5.3, effect rows

2. **Wiring status (29 wired / 18 pending = 61.7% coverage):**
   - **Wired declarations (12/20):** flow, persona, context, anchor, tool, memory, type, agent, daemon, axonstore, dataspace, lambda
   - **Wired step (7/14):** step, reason, validate, use, remember, recall, par
   - **Wired epistemic (4/4):** know, believe, speculate, doubt — 100% coverage
   - **Wired navigation (6/9):** stream, focus, associate, aggregate, explore, navigate
   - **Pending (18):** shield, pix, psyche, corpus, ots, mandate, compute, axonendpoint, refine, weave, probe, hibernate, deliberate, consensus, forge, drill, trail, corroborate

3. **Route registered:** `GET /v1/primitives` → 209 total routes

**Tests added (3):**
- `test_primitive_inventory_covers_all_47` — validates AXON_COGNITIVE_PRIMITIVES has exactly 47 entries, category distribution (20+14+4+9=47), each primitive in exactly one category
- `test_primitive_wiring_status_classification` — validates 29 wired + 18 pending = 47, coverage > 60%, no overlap between wired/pending
- `test_primitive_lambda_d_alignment_metadata` — validates ΛD structures: raw c=1.0, derived c≤0.99, Theorem 5.1, epistemic lattice ordering, blame taxonomy (CT-2/CT-3)

**Evidence:**
- `cargo test` → 642 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 208 | 209 |
| Tests | 639 | 642 |
| Primitive coverage | unmeasured | 29/47 = 61.7% |

---

**Handoff G8:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore ℰMCP tools — expose `persist`/`retrieve`/`mutate`/`purge` as MCP tools with CSP §5.3 schemas and Theorem 5.1 enforcement.
- **E:** Shield primitive runtime — implement input/output guardrails with pattern matching, toxicity filters, and PII detection.

---

### G8 — AxonStore ℰMCP Tools (Option D)

**Scope:** Expose AxonStore persistence operations as MCP tools via `tools/list` and `tools/call`, completing the cognitive persistence bridge through the standard ℰMCP protocol with CSP §5.3 schemas and Theorem 5.1 enforcement.

**Delivered:**

1. **MCP `tools/list` extension (4 tools per AxonStore instance):**
   - `axon_as_{name}_persist` — raw write, c=1.0, δ=raw, effect: `<io, epistemic:know>`, taint: Raw
   - `axon_as_{name}_retrieve` — envelope-preserving read, effect: `<io, epistemic:believe>`, taint: Preserved
   - `axon_as_{name}_mutate` — Theorem 5.1 degradation, c≤0.99, δ=derived, effect: `<io, epistemic:speculate>`, taint: Uncertainty
   - `axon_as_{name}_purge` — irreversible deletion, effect: `<io, epistemic:know>`, taint: Void
   - Each tool carries full CSP §5.3 `_axon_csp` schema (constraints, effect_row, output_taint)

2. **MCP `tools/call` dispatch (`axon_as_{name}_{op}` pattern):**
   - Name parsing via `rfind('_')` — supports multi-word store names (e.g., `axon_as_user_prefs_mutate`)
   - **persist**: creates `AxonStoreEntry` with `EpistemicEnvelope::raw_config()` (c=1.0, δ=raw)
   - **retrieve**: returns entry with full ΛD envelope; missing key → c=0.0, lattice=doubt
   - **mutate**: `EpistemicEnvelope::derived()` enforcement (Theorem 5.1: c clamped ≤0.99), version increment
   - **purge**: destructive removal with `total_ops` tracking
   - All responses include `_axon` block with epistemic envelope, lattice position, effect row, and blame attribution

3. **Blame calculus (Findler-Felleisen):**
   - CT-2 (caller blame) on: missing key parameter, non-existent store, unknown op, mutate/purge absent key
   - Consistent with existing dataspace tool dispatch blame semantics

4. **Primitives handler updated:**
   - `axonstore` wiring: `/v1/axonstore/* + MCP tools/call (persist/retrieve/mutate/purge/transact)` — phase G2+G8

**Tests added (3):**
- `test_emcp_axonstore_tool_name_parsing` — validates `axon_as_{name}_{op}` rfind parsing for all 4 operations including multi-word store names
- `test_emcp_axonstore_tool_csp_schemas` — validates CSP §5.3 schema structure: constraints, effect_row, output_taint per tool type with Theorem 5.1 references
- `test_emcp_axonstore_tool_call_epistemic_envelopes` — validates ΛD envelopes: persist=raw(c=1.0), retrieve=preserved, mutate=derived(c≤0.99), purge=void; Theorem 5.1 violation detection; absent key → doubt(c=0.0)

**Evidence:**
- `cargo test` → 645 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 209 | 209 (no new routes — tools exposed via existing MCP endpoint) |
| Tests | 642 | 645 |
| MCP tools per AxonStore | 0 | 4 (persist/retrieve/mutate/purge) |
| AxonStore protocol coverage | HTTP only | HTTP + ℰMCP |

---

**Handoff G9:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** Shield primitive runtime — implement input/output guardrails with pattern matching, toxicity filters, and PII detection.
- **E:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.

---

### G9 — Shield Primitive Runtime (Option D)

**Scope:** Wire the `shield` cognitive primitive (#9 of 47) to runtime — input/output guardrails with deny lists, pattern matching, PII detection, and length limits. Each shield carries ΛD epistemic alignment: evaluation is derived (c≤0.99, δ=derived) because pattern matching is speculative.

**Delivered:**

1. **Structs (3 new pub structs → 142 total):**
   - `ShieldRule` — per-rule guardrail: kind (deny_list/pattern/pii/length), value, action (block/warn/redact), enabled flag
   - `ShieldResult` — evaluation outcome: blocked, warnings, redactions, processed content, rules evaluated/triggered
   - `ShieldInstance` — named collection of ordered rules with mode (input/output/both), evaluation stats, `evaluate()` method

2. **`ShieldInstance::evaluate()` engine (4 rule kinds):**
   - `deny_list` — case-insensitive substring match → block/warn/redact (with `█` masking)
   - `pattern` — simple wildcard matching with `*` → block/warn/redact
   - `pii` — heuristic detection: email (`@` + `.`), phone (≥10 digits), SSN (3-2-4 digit pattern)
   - `length` — max character limit enforcement

3. **Handlers (6 new):**
   - `shield_create_handler` — POST /v1/shields (name, mode, rules)
   - `shield_list_handler` — GET /v1/shields (summary per shield)
   - `shield_get_handler` — GET /v1/shields/{name} (full rules + stats)
   - `shield_delete_handler` — DELETE /v1/shields/{name} (admin-only)
   - `shield_evaluate_handler` — POST /v1/shields/{name}/evaluate (content + direction → ShieldResult with ΛD envelope)
   - `shield_add_rule_handler` — POST /v1/shields/{name}/rules (add rule with duplicate detection)

4. **Routes (4 new → 213 total):**
   - `/v1/shields` (GET+POST), `/v1/shields/{name}` (GET+DELETE), `/v1/shields/{name}/evaluate` (POST), `/v1/shields/{name}/rules` (POST)

5. **ServerState + ServerBackup extended:**
   - `shields: HashMap<String, ShieldInstance>` added to ServerState
   - `shields` field added to ServerBackup with `#[serde(default)]` for backward compatibility
   - Restore/recover handlers include shield merge semantics (no overwrite)

6. **Primitives handler updated:**
   - `shield` → wired: `/v1/shields/* (create/evaluate/rules with deny_list/pattern/pii/length)` — phase G9
   - Primitive coverage: 30/47 = 63.8% (was 29/47 = 61.7%)

7. **ΛD Epistemic alignment:**
   - No triggers → c=0.95, lattice=speculate (high confidence content is safe, but speculative)
   - Triggered → c=0.85, lattice=doubt (lower confidence due to pattern match uncertainty)
   - All evaluations δ=derived per Theorem 5.1 (pattern matching is approximate)

**Tests added (3):**
- `test_shield_evaluate_deny_list_and_redact` — validates block/redact/warn actions, disabled rule skipping, `█` masking, clean content pass-through
- `test_shield_pii_detection_and_length_rules` — validates email PII detection with `[EMAIL REDACTED]`, phone number warning, length limit blocking, mode="both" compatibility
- `test_shield_epistemic_alignment` — validates Theorem 5.1 (c<1.0 for all evaluations), certainty gradient (clean=0.95 > triggered=0.85), lattice positions, effect rows, mode validation

**Evidence:**
- `cargo test` → 648 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 209 | 213 |
| Tests | 645 | 648 |
| Pub structs | ~139 | ~142 |
| Primitive coverage | 29/47 (61.7%) | 30/47 (63.8%) |

---

**Handoff G10:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Backend health probing — automated periodic health checks with configurable intervals and status history tracking.
- **D:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **E:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.

---

### G10 — Backend Health Probing (Option C)

**Scope:** Configurable health probe infrastructure per backend with check history tracking, transition detection, uptime analysis, and fleet-wide health summary. Extends the existing `POST /v1/backends/{name}/check` to record history and update probe counters.

**Delivered:**

1. **Structs (2 new pub structs → 144 total):**
   - `BackendHealthProbe` — per-backend probe config: interval_secs, unhealthy/healthy thresholds, timeout_ms, enabled, consecutive_ok/fail counters. Default: 300s interval, 3-fail/2-ok thresholds, 10s timeout, disabled.
   - `HealthCheckRecord` — individual check entry: timestamp, status, latency_ms, error, previous_status (for transition detection).

2. **ServerState extended:**
   - `backend_health_probes: HashMap<String, BackendHealthProbe>` — per-backend probe configuration
   - `backend_health_history: HashMap<String, Vec<HealthCheckRecord>>` — per-backend check history (capped at 100 entries)

3. **Existing `backends_check_handler` enhanced:**
   - Now records `HealthCheckRecord` to history on every check
   - Updates probe consecutive counters (ok/fail) based on check result
   - Returns `transition: bool` indicating status change
   - History auto-caps at 100 entries per backend (FIFO)

4. **Handlers (4 new):**
   - `backends_health_handler` — GET /v1/backends/{name}/health: full history with transition count, uptime %, avg latency, probe config
   - `backends_probe_put_handler` — PUT /v1/backends/{name}/probe: configure probe settings (interval, thresholds, timeout, enabled)
   - `backends_probe_get_handler` — GET /v1/backends/{name}/probe: read probe configuration + consecutive counters
   - `backends_fleet_health_handler` — GET /v1/backends/health: fleet-wide summary (healthy/degraded/unreachable/unknown counts, per-backend uptime, probe status)

5. **Routes (3 new → 216 total):**
   - `/v1/backends/health` (GET), `/v1/backends/{name}/health` (GET), `/v1/backends/{name}/probe` (GET+PUT)

**Tests added (3):**
- `test_backend_health_probe_configuration` — validates default values, custom config, serialization/deserialization round-trip
- `test_health_check_record_tracking` — validates history recording, transition detection (healthy→degraded→healthy = 2 transitions), uptime calculation (75%), history cap at 100 entries
- `test_health_probe_consecutive_counter_logic` — validates consecutive counter behavior: healthy threshold (2), unhealthy threshold (3), counter reset on status change, disabled probe flag

**Evidence:**
- `cargo test` → 651 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 213 | 216 |
| Tests | 648 | 651 |
| Pub structs | ~142 | ~144 |
| Backend observability | dashboard only | dashboard + health history + probes + fleet health |

---

**Handoff G11:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Corpus primitive runtime — wire `corpus` cognitive primitive for document corpus management with ingest/search/cite operations.

---

### G11 — Corpus Primitive Runtime (Option E)

**Scope:** Wire the `corpus` cognitive primitive (#14 of 47) to runtime — document corpus management with ingest, keyword search (TF-based relevance scoring), and citation extraction with excerpt generation. All operations carry ΛD epistemic envelopes per Theorem 5.1.

**Delivered:**

1. **Structs (3 new pub structs → 147 total):**
   - `CorpusDocument` — id, title, content, tags, source provenance, ΛD envelope, word_count
   - `CorpusCitation` — document_id, title, excerpt, relevance score, ΛD envelope (δ=derived)
   - `CorpusInstance` — named corpus with ontology, document map, auto-incrementing IDs, op counter

2. **Handlers (6 new):**
   - `corpus_create_handler` — POST /v1/corpus (name, ontology)
   - `corpus_list_handler` — GET /v1/corpus (summary per corpus)
   - `corpus_delete_handler` — DELETE /v1/corpus/{name} (admin-only)
   - `corpus_ingest_handler` — POST /v1/corpus/{name}/ingest (title, content, tags, source → ΛD raw c=1.0)
   - `corpus_search_handler` — POST /v1/corpus/{name}/search (query, tags filter, limit → TF-based relevance with title 3x boost → ΛD derived c=0.99)
   - `corpus_cite_handler` — POST /v1/corpus/{name}/cite (query, max_citations, excerpt_length → passage extraction with relevance → ΛD derived c=0.99)

3. **Search engine:**
   - Term frequency scoring: count query term hits in content + title (title weighted 3x)
   - Relevance normalization: hits / total_words, capped at 1.0
   - Tag filtering: all specified tags must match (AND logic)
   - Results sorted by relevance descending with configurable limit

4. **Citation engine:**
   - Exact match: finds query position, extracts surrounding excerpt (configurable length)
   - Partial match: falls back to individual term matching with proportional relevance
   - Excerpt extraction with safe UTF-8 boundary handling
   - Sorted by relevance, capped at max_citations

5. **Routes (4 new → 220 total):**
   - `/v1/corpus` (GET+POST), `/v1/corpus/{name}` (DELETE), `/v1/corpus/{name}/ingest` (POST), `/v1/corpus/{name}/search` (POST), `/v1/corpus/{name}/cite` (POST)

6. **ΛD Epistemic alignment:**
   - Ingest: c=1.0, δ=raw (document is ground truth)
   - Search: c=0.99, δ=derived (relevance scoring is approximate), lattice=speculate
   - Cite: c=0.99, δ=derived (excerpt extraction is interpretive), lattice=speculate

7. **Primitives handler updated:**
   - `corpus` → wired: `/v1/corpus/* (ingest/search/cite with ΛD envelopes)` — phase G11
   - Coverage: 31/47 = 66.0% (was 30/47 = 63.8%)

**Tests added (3):**
- `test_corpus_document_ingest_and_epistemic_envelope` — validates document storage, word_count, tags, source provenance, ΛD raw envelope (c=1.0), multi-document corpus management
- `test_corpus_search_relevance_scoring` — validates TF-based scoring with title boost, correct ranking (title match > body match), no false positives (database doc excluded), Theorem 5.1 search derivation
- `test_corpus_citation_extraction_with_theorem_5_1` — validates excerpt extraction around query match, ΛD derived envelope (c=0.99), Theorem 5.1 violation detection (derived+c=1.0 rejected), relevance score bounds

**Evidence:**
- `cargo test` → 654 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 216 | 220 |
| Tests | 651 | 654 |
| Pub structs | ~144 | ~147 |
| Primitive coverage | 30/47 (63.8%) | 31/47 (66.0%) |

---

**Handoff G12:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Compute primitive runtime — wire `compute` cognitive primitive for numeric/symbolic computation with expression evaluation.

---

### G12 — Compute Primitive Runtime (Option E)

**Scope:** Wire the `compute` cognitive primitive (#17 of 47) to runtime — full expression evaluator with arithmetic, functions, constants, variables, and ΛD epistemic exactness tracking. Exact integer arithmetic carries c=1.0 (raw), while floating-point/transcendental operations carry c=0.99 (derived) per Theorem 5.1.

**Delivered:**

1. **Expression evaluator engine (`compute_evaluate`):**
   - **Tokenizer** (`compute_tokenize`): numbers, operators (+−×÷%^), parentheses, identifiers (variables/functions/constants), unary minus
   - **Shunting-yard evaluator** (`compute_eval_tokens`): correct operator precedence, associativity (^ right-associative), parentheses grouping
   - **Operators (6):** `+`, `-`, `*`, `/`, `%`, `^` (power)
   - **Functions (9):** sqrt, abs, sin, cos, log (natural), exp, ceil, floor, round
   - **Constants (3):** pi (π), e (Euler's), tau (2π)
   - **Variables:** arbitrary named variables via `HashMap<String, f64>`
   - **Error handling:** division by zero, modulo by zero, sqrt of negative, log of non-positive, unknown variables

2. **Structs (1 new pub struct → 148 total):**
   - `ComputeResult` — value, expression, exact flag, variables used, certainty, derivation

3. **Handlers (3 new):**
   - `compute_evaluate_handler` — POST /v1/compute/evaluate (expression + variables → result with ΛD envelope)
   - `compute_batch_handler` — POST /v1/compute/batch (multiple expressions in one call, aggregate exactness)
   - `compute_functions_handler` — GET /v1/compute/functions (available operators, functions, constants, epistemic rules)

4. **Routes (3 new → 223 total):**
   - `/v1/compute/evaluate` (POST), `/v1/compute/batch` (POST), `/v1/compute/functions` (GET)

5. **ΛD Epistemic alignment (exactness-based):**
   - Exact integer arithmetic: c=1.0, δ=raw, lattice=know (ground truth)
   - Floating point / transcendentals / division: c=0.99, δ=derived, lattice=speculate
   - Batch: all_exact only if every expression is exact
   - Effect rows: `<compute, epistemic:know>` (exact) or `<compute, epistemic:speculate>` (approximate)

6. **Primitives handler updated:**
   - `compute` → wired: `/v1/compute/* (evaluate/batch/functions with ΛD exactness tracking)` — phase G12
   - Coverage: 32/47 = 68.1% (was 31/47 = 66.0%)

**Tests added (3):**
- `test_compute_arithmetic_and_operator_precedence` — validates basic ops, precedence (* before +), parentheses, power, modulo, nested expressions, unary minus, division exactness (derived), division by zero error
- `test_compute_variables_and_functions` — validates variable substitution (x+y), sqrt/abs/floor/ceil/round functions, pi/e constants, composed expressions (sqrt(x²+y²)), unknown variable error
- `test_compute_epistemic_alignment_theorem_5_1` — validates exact→c=1.0/raw, approximate→c=0.99/derived, lattice positions (know vs speculate), EpistemicEnvelope validation, Theorem 5.1 violation detection, effect rows

**Evidence:**
- `cargo test` → 657 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 220 | 223 |
| Tests | 654 | 657 |
| Pub structs | ~147 | ~148 |
| Primitive coverage | 31/47 (66.0%) | 32/47 (68.1%) |

---

**Handoff G13:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Mandate primitive runtime — wire `mandate` cognitive primitive for authorization/permission management with role-based access policies.

---

### G13 — Mandate Primitive Runtime (Option E)

**Scope:** Wire the `mandate` cognitive primitive (#16 of 47) to runtime — authorization/permission management with priority-ordered, first-match-wins policy evaluation. Supports subject/action/resource pattern matching (exact, prefix `*`, wildcard `*`). ΛD alignment: explicit rule match → c=1.0/raw (deterministic), default deny → c=0.99/derived (inferential, Theorem 5.1).

**Delivered:**

1. **Structs (3 new pub structs → 151 total):**
   - `MandateRule` — id, subject/action/resource patterns, effect (allow/deny), priority, enabled
   - `MandateEvaluation` — allowed, matched_rule, effect, rules_evaluated, certainty, derivation
   - `MandatePolicy` — named policy with rules, `evaluate()` method, stats tracking

2. **Policy evaluation engine (`MandatePolicy::evaluate`):**
   - Rules sorted by priority (descending) at evaluation time
   - First-match-wins: first rule matching (subject, action, resource) determines outcome
   - Subject matching: exact string or `*` wildcard
   - Action matching: exact string or `*` wildcard
   - Resource matching: exact string, prefix with trailing `*`, or `*` wildcard
   - Default deny when no rule matches
   - Disabled rules skipped

3. **Handlers (6 new):**
   - `mandate_create_handler` — POST /v1/mandates (name, description, rules; admin-only)
   - `mandate_list_handler` — GET /v1/mandates (summary per policy)
   - `mandate_get_handler` — GET /v1/mandates/{name} (full rules + stats)
   - `mandate_delete_handler` — DELETE /v1/mandates/{name} (admin-only)
   - `mandate_evaluate_handler` — POST /v1/mandates/{name}/evaluate (subject+action+resource → decision with ΛD)
   - `mandate_add_rule_handler` — POST /v1/mandates/{name}/rules (add rule with duplicate detection; admin-only)

4. **Routes (4 new → 227 total):**
   - `/v1/mandates` (GET+POST), `/v1/mandates/{name}` (GET+DELETE), `/v1/mandates/{name}/evaluate` (POST), `/v1/mandates/{name}/rules` (POST)

5. **ΛD Epistemic alignment:**
   - Explicit rule match: c=1.0, δ=raw, lattice=know (deterministic decision)
   - Default deny: c=0.99, δ=derived, lattice=speculate (inferential, no rule matched)
   - Effect rows: `<io, epistemic:know>` (explicit) or `<io, epistemic:speculate>` (default)

6. **Primitives handler updated:**
   - `mandate` → wired: `/v1/mandates/* (policy CRUD, evaluate with priority-ordered first-match)` — phase G13
   - Coverage: 33/47 = 70.2% (was 32/47 = 68.1%)

**Tests added (3):**
- `test_mandate_policy_evaluation_first_match_wins` — validates priority ordering, admin wildcard, operator prefix match, deny overrides, default deny, disabled rule skipping, rule count
- `test_mandate_resource_pattern_matching` — validates exact match, prefix match with trailing *, wildcard * match, non-matching paths, prefix vs exact distinction
- `test_mandate_epistemic_alignment_theorem_5_1` — validates explicit match c=1.0/raw, default deny c=0.99/derived, lattice positions, EpistemicEnvelope validation, Theorem 5.1 violation detection

**Evidence:**
- `cargo test` → 660 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 223 | 227 |
| Tests | 657 | 660 |
| Pub structs | ~148 | ~151 |
| Primitive coverage | 32/47 (68.1%) | 33/47 (70.2%) |

---

**Handoff G14:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Refine primitive runtime — wire `refine` cognitive primitive for iterative output improvement with convergence tracking.

---

### G14 — Refine Primitive Runtime (Option E)

**Scope:** Wire the `refine` cognitive primitive (#19 of 47) to runtime — iterative output improvement with convergence tracking. Sessions progress through iterations guided by feedback, converging when quality reaches a target or delta falls below a threshold. ΛD: all refinements are derived (c≤0.99, δ=derived per Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 153 total):**
   - `RefineIteration` — iteration number, content, quality score, delta, timestamp, feedback
   - `RefineSession` — session with target_quality, convergence_threshold, max_iterations, iteration history, convergence detection

2. **`RefineSession` engine:**
   - `add_iteration()` — adds iteration, computes delta from previous quality, checks convergence
   - `check_convergence()` — true when quality ≥ target OR |delta| < threshold (after ≥2 iterations)
   - `current_quality()` — last iteration's quality
   - Guards: rejects iterations after convergence or when max reached

3. **Handlers (4 new):**
   - `refine_start_handler` — POST /v1/refine (name, initial_content, initial_quality, target, max)
   - `refine_iterate_handler` — POST /v1/refine/{id}/iterate (content, quality, feedback → convergence check)
   - `refine_status_handler` — GET /v1/refine/{id} (full history, quality/delta trends)
   - `refine_list_handler` — GET /v1/refine (all sessions summary)

4. **Routes (3 new → 230 total):**
   - `/v1/refine` (GET+POST), `/v1/refine/{id}` (GET), `/v1/refine/{id}/iterate` (POST)

5. **ΛD Epistemic alignment:**
   - All iterations: c = 0.5 + quality × 0.49, capped at 0.99 (derived, Theorem 5.1)
   - Converged session: lattice=believe (high confidence in final output)
   - Iterating session: lattice=speculate (still improving)
   - Effect row: `<io, epistemic:speculate>`

6. **Primitives handler updated:**
   - `refine` → wired: `/v1/refine/* (start/iterate/status with convergence tracking)` — phase G14
   - Coverage: 34/47 = 72.3% (was 33/47 = 70.2%)

**Tests added (3):**
- `test_refine_session_iteration_and_convergence` — validates iteration progression, delta computation, convergence on target quality, post-convergence rejection
- `test_refine_convergence_by_delta_and_max_iterations` — validates delta-threshold convergence (|delta| < 0.02), max iterations enforcement, error messages
- `test_refine_epistemic_alignment_theorem_5_1` — validates certainty formula (0.5 + q×0.49 ≤ 0.99), quality-certainty correlation, max cap at 0.99, Theorem 5.1 violation detection, lattice positions, quality trend tracking

**Evidence:**
- `cargo test` → 663 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 227 | 230 |
| Tests | 660 | 663 |
| Pub structs | ~151 | ~153 |
| Primitive coverage | 33/47 (70.2%) | 34/47 (72.3%) |

---

**Handoff G15:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Trail primitive runtime — wire `trail` cognitive primitive for execution path recording with step-by-step trace capture.

---

### G15 — Trail Primitive Runtime (Option E)

**Scope:** Wire the `trail` cognitive primitive (#37 of 47) to runtime — execution path recording with step-by-step trace capture, outcome tracking, and duration aggregation. Trails are immutable once completed, ensuring audit integrity. ΛD: trail recording is raw observation (c=1.0 completed, c=0.95 in-progress).

**Delivered:**

1. **Structs (2 new pub structs → 155 total):**
   - `TrailStep` — step number, operation, input/output, duration_ms, outcome (success/failure/skipped), metadata map, timestamp
   - `TrailRecord` — id, name, target, steps, completed flag, outcome, total_duration_ms, `add_step()`, `complete()`, success/failure counts

2. **`TrailRecord` engine:**
   - `add_step()` — appends step with auto-incrementing number, accumulates duration, rejects after completion
   - `complete()` — marks trail as done with final outcome, sets completed_at timestamp, guards against double-completion
   - `step_count()`, `success_count()`, `failure_count()` — introspection helpers

3. **Handlers (5 new):**
   - `trail_start_handler` — POST /v1/trails (name, target → new trail record)
   - `trail_step_handler` — POST /v1/trails/{id}/step (operation, input, output, duration_ms, outcome, metadata)
   - `trail_complete_handler` — POST /v1/trails/{id}/complete (outcome → immutable seal)
   - `trail_get_handler` — GET /v1/trails/{id} (full step history with ΛD envelope)
   - `trail_list_handler` — GET /v1/trails (all trails summary)

4. **Routes (4 new → 234 total):**
   - `/v1/trails` (GET+POST), `/v1/trails/{id}` (GET), `/v1/trails/{id}/step` (POST), `/v1/trails/{id}/complete` (POST)

5. **ΛD Epistemic alignment:**
   - Trail steps: c=1.0, δ=raw (recording what actually happened)
   - Completed trail: c=1.0, δ=raw, lattice=know (ground truth)
   - In-progress trail: c=0.95, δ=raw, lattice=believe (provisional)
   - Consistent with Theorem 5.1: raw observations may carry c=1.0

6. **Primitives handler updated:**
   - `trail` → wired: `/v1/trails/* (start/step/complete with step-by-step trace)` — phase G15
   - Coverage: 35/47 = 74.5% (was 34/47 = 72.3%)

**Tests added (3):**
- `test_trail_step_recording_and_completion` — validates step recording, auto-numbering, duration accumulation, metadata, completion sealing, post-completion rejection
- `test_trail_success_failure_counts` — validates success/failure/skipped counting across 5 steps, total_duration_ms, partial outcome completion
- `test_trail_epistemic_alignment` — validates c=0.95 in-progress vs c=1.0 completed, raw observation envelopes, Theorem 5.1 consistency (raw CAN be c=1.0), lattice positions, serialization

**Evidence:**
- `cargo test` → 666 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 230 | 234 |
| Tests | 663 | 666 |
| Pub structs | ~153 | ~155 |
| Primitive coverage | 34/47 (72.3%) | 35/47 (74.5%) |

---

**Handoff G16:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Shield ℰMCP tools — expose shield create/evaluate as MCP tools with CSP §5.3 schemas for AI-agent self-regulation.
- **E:** Probe primitive runtime — wire `probe` cognitive primitive for exploratory information gathering with multi-source queries.

---

### G16 — Probe Primitive Runtime (Option E)

**Scope:** Wire the `probe` cognitive primitive (#21 of 47) to runtime — exploratory information gathering with multi-source queries, relevance-weighted findings, aggregate certainty, and per-source distribution. Probing is inherently speculative: all findings are derived (c≤0.99, δ=derived per Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 157 total):**
   - `ProbeFinding` — source, query, content, relevance, certainty (= relevance × 0.99, capped at 0.99), timestamp
   - `ProbeSession` — id, name, question, sources, findings, completed, total_queries, `add_finding()`, `top_findings()`, `aggregate_certainty()`, `findings_per_source()`

2. **`ProbeSession` engine:**
   - `add_finding()` — appends finding with auto-computed certainty (relevance × 0.99)
   - `top_findings(limit)` — returns top N findings sorted by relevance descending
   - `aggregate_certainty()` — average certainty across all findings
   - `findings_per_source()` — HashMap of source → finding count

3. **Handlers (5 new):**
   - `probe_create_handler` — POST /v1/probes (name, question, sources)
   - `probe_query_handler` — POST /v1/probes/{id}/query (source, query, results → findings)
   - `probe_complete_handler` — POST /v1/probes/{id}/complete (seal + top findings + summary)
   - `probe_get_handler` — GET /v1/probes/{id} (full findings + distribution)
   - `probe_list_handler` — GET /v1/probes (all probes summary)

4. **Routes (4 new → 238 total):**
   - `/v1/probes` (GET+POST), `/v1/probes/{id}` (GET), `/v1/probes/{id}/query` (POST), `/v1/probes/{id}/complete` (POST)

5. **ΛD Epistemic alignment:**
   - All findings: c = relevance × 0.99, capped at 0.99 (derived, Theorem 5.1)
   - Aggregate certainty: average of all finding certainties
   - Lattice: aggregate > 0.8 → believe; else → speculate (never know)
   - Effect row: `<io, epistemic:speculate>`

6. **Primitives handler updated:**
   - `probe` → wired: `/v1/probes/* (create/query/complete with multi-source findings)` — phase G16
   - Coverage: 36/47 = 76.6% (was 35/47 = 74.5%)

**Tests added (3):**
- `test_probe_session_findings_and_aggregation` — validates multi-source findings, certainty cap (relevance×0.99≤0.99), top_findings sorting, findings_per_source distribution, aggregate certainty
- `test_probe_completion_and_top_findings` — validates 8 varied-relevance findings, top-3 ordering, completion, aggregate certainty ≤0.99, lattice position, top_findings with limit > total
- `test_probe_epistemic_alignment_theorem_5_1` — validates certainty cap even at relevance=1.0, relevance-certainty correlation, Theorem 5.1 violation detection, aggregate ≤0.99, lattice never "know"

**Evidence:**
- `cargo test` → 669 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 234 | 238 |
| Tests | 666 | 669 |
| Pub structs | ~155 | ~157 |
| Primitive coverage | 35/47 (74.5%) | 36/47 (76.6%) |

---

**Handoff G17:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Weave primitive runtime — wire `weave` cognitive primitive for multi-source content synthesis with attribution tracking.
- **E:** Drill primitive runtime — wire `drill` cognitive primitive for deep recursive exploration with depth-limited search.

---

### G17 — Weave Primitive Runtime (Option D)

**Scope:** Wire the `weave` cognitive primitive (#20 of 47) to runtime — multi-source content synthesis with weighted strands, source attribution, and certainty aggregation. Synthesis is always derived per Theorem 5.1 (c≤0.99), with certainty computed as weighted average of strand source certainties.

**Delivered:**

1. **Structs (2 new pub structs → 159 total):**
   - `WeaveStrand` — id, source attribution, content, weight (0.0–1.0), source_certainty, timestamp
   - `WeaveSession` — id, name, goal, strands, synthesis output, `add_strand()`, `synthesize()`, `synthesis_certainty()`, `attributions()`

2. **`WeaveSession` engine:**
   - `add_strand()` — appends strand with auto-ID, clamped weight/certainty to [0.0, 1.0]
   - `synthesize()` — combines strands (weight-ordered) with `[source] content` attribution markers; immutable once done
   - `synthesis_certainty()` — weighted average of strand certainties: Σ(certainty×weight)/Σ(weight)
   - `attributions()` — list of (source, weight) pairs for provenance tracking

3. **Handlers (5 new):**
   - `weave_create_handler` — POST /v1/weaves (name, goal)
   - `weave_strand_handler` — POST /v1/weaves/{id}/strand (source, content, weight, source_certainty)
   - `weave_synthesize_handler` — POST /v1/weaves/{id}/synthesize (seal + attribution + ΛD envelope)
   - `weave_get_handler` — GET /v1/weaves/{id} (strands + synthesis + attributions)
   - `weave_list_handler` — GET /v1/weaves (all weaves summary)

4. **Routes (4 new → 242 total):**
   - `/v1/weaves` (GET+POST), `/v1/weaves/{id}` (GET), `/v1/weaves/{id}/strand` (POST), `/v1/weaves/{id}/synthesize` (POST)

5. **ΛD Epistemic alignment:**
   - Synthesis certainty: weighted average of strand source certainties, capped at 0.99 in handler
   - All synthesis is derived (Theorem 5.1: combining sources is transformation, not raw observation)
   - Lattice: certainty > 0.8 → believe; else → speculate
   - Effect row: `<io, epistemic:speculate>`

6. **Primitives handler updated:**
   - `weave` → wired: `/v1/weaves/* (strand/synthesize with attribution and weighted certainty)` — phase G17
   - Coverage: 37/47 = 78.7% (was 36/47 = 76.6%)

**Tests added (3):**
- `test_weave_strand_collection_and_synthesis` — validates multi-source strand collection, attribution markers in synthesis, weight-ordered output, post-synthesis immutability
- `test_weave_synthesis_certainty_weighted` — validates weighted certainty formula (0.9 for skewed weights, 0.7 for equal), empty weave returns 0.0, empty synthesize fails
- `test_weave_epistemic_alignment_theorem_5_1` — validates handler cap at 0.99 even with all-raw sources, Theorem 5.1 violation detection, lattice positions, weight clamping (negative→0.0, >1→1.0), attribution in synthesis

**Evidence:**
- `cargo test` → 672 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 238 | 242 |
| Tests | 669 | 672 |
| Pub structs | ~157 | ~159 |
| Primitive coverage | 36/47 (76.6%) | 37/47 (78.7%) |

---

**Handoff G18:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Drill primitive runtime — wire `drill` cognitive primitive for deep recursive exploration with depth-limited search.
- **E:** Corroborate primitive runtime — wire `corroborate` cognitive primitive for cross-source verification with agreement scoring.

---

### G18 — Corroborate Primitive Runtime (Option E)

**Scope:** Wire the `corroborate` cognitive primitive (#38 of 47) to runtime — cross-source claim verification with evidence collection, stance tracking (supports/contradicts/neutral), confidence-weighted agreement scoring, and tri-state verdicts. ΛD: verification is always derived (c≤0.99, Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 161 total):**
   - `CorroborateEvidence` — id, source, content, stance (supports/contradicts/neutral), confidence (clamped 0.0–1.0), timestamp
   - `CorroborateSession` — id, name, claim, evidence, verdict, `add_evidence()`, `compute_agreement()`, `verify()`, `stance_counts()`

2. **Agreement scoring engine:**
   - Agreement ratio: (Σsupporting_confidence − Σcontradicting_confidence) / Σtotal_confidence → [-1, 1]
   - Certainty: |agreement| × 0.99, capped at 0.99
   - Verdicts: agreement > 0.5 → "corroborated", < -0.5 → "disputed", else → "inconclusive"
   - Stance validation: only "supports", "contradicts", "neutral" accepted

3. **Handlers (5 new):**
   - `corroborate_create_handler` — POST /v1/corroborate (name, claim)
   - `corroborate_evidence_handler` — POST /v1/corroborate/{id}/evidence (source, content, stance, confidence → live agreement preview)
   - `corroborate_verify_handler` — POST /v1/corroborate/{id}/verify (seal + verdict + ΛD envelope)
   - `corroborate_get_handler` — GET /v1/corroborate/{id} (full evidence + agreement + stance counts)
   - `corroborate_list_handler` — GET /v1/corroborate (all sessions summary)

4. **Routes (4 new → 246 total):**
   - `/v1/corroborate` (GET+POST), `/v1/corroborate/{id}` (GET), `/v1/corroborate/{id}/evidence` (POST), `/v1/corroborate/{id}/verify` (POST)

5. **ΛD Epistemic alignment:**
   - Certainty: |agreement| × 0.99, always ≤ 0.99 (derived)
   - Lattice: corroborated → believe, disputed → doubt, inconclusive → speculate
   - Effect row: `<io, epistemic:{lattice}>`
   - Theorem 5.1: cross-source verification is inferential, never raw

6. **Primitives handler updated:**
   - `corroborate` → wired: `/v1/corroborate/* (evidence/verify with agreement scoring)` — phase G18
   - Coverage: 38/47 = 80.9% (was 37/47 = 78.7%)

**Tests added (3):**
- `test_corroborate_evidence_and_agreement_scoring` — validates multi-stance evidence, stance counts, agreement formula (net support/total), inconclusive verdict for mixed evidence, invalid stance rejection
- `test_corroborate_verify_verdicts` — validates "corroborated" (strong support), "disputed" (strong contradiction), post-verification immutability, empty session rejection
- `test_corroborate_epistemic_alignment_theorem_5_1` — validates certainty cap at 0.99 even with all-support, Theorem 5.1 violation detection, lattice positions per verdict, confidence clamping (>1→1.0, <0→0.0)

**Evidence:**
- `cargo test` → 675 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 242 | 246 |
| Tests | 672 | 675 |
| Pub structs | ~159 | ~161 |
| Primitive coverage | 37/47 (78.7%) | **38/47 (80.9%)** |

---

**Handoff G19:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Drill primitive runtime — wire `drill` cognitive primitive for deep recursive exploration with depth-limited search.
- **E:** Forge primitive runtime — wire `forge` cognitive primitive for artifact generation with template-based output construction.

---

### G19 — Drill Primitive Runtime (Option D)

**Scope:** Wire the `drill` cognitive primitive (#36 of 47) to runtime — depth-limited recursive exploration with tree-structured question-answer chains. Certainty degrades with depth: surface findings are more reliable than deep speculation. ΛD: all drill findings are derived (c≤0.99, Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 163 total):**
   - `DrillNode` — id (path-based: "root.0.1"), question, answer, depth, children, is_leaf, certainty (depth-derived)
   - `DrillSession` — id, name, root_question, max_depth, nodes HashMap, `add_root()`, `expand()`, depth/leaf/certainty introspection

2. **Drill engine:**
   - `certainty_at_depth(d)` — (1.0 − d×0.05).max(0.5).min(0.99): depth-0=0.99, depth-5=0.75, depth-10+=0.5
   - `add_root()` — creates root node, guards against duplicates
   - `expand(parent_id, question, answer)` — adds child with path-based ID, enforces max_depth, marks leaves
   - `node_count()`, `max_depth_reached()`, `leaf_count()`, `avg_certainty()` — introspection helpers

3. **Handlers (5 new):**
   - `drill_create_handler` — POST /v1/drills (name, root_question, root_answer, max_depth)
   - `drill_expand_handler` — POST /v1/drills/{id}/expand (parent_id, question, answer → depth + certainty)
   - `drill_complete_handler` — POST /v1/drills/{id}/complete (seal + tree summary)
   - `drill_get_handler` — GET /v1/drills/{id} (full tree with all nodes)
   - `drill_list_handler` — GET /v1/drills (all drills summary)

4. **Routes (4 new → 250 total):**
   - `/v1/drills` (GET+POST), `/v1/drills/{id}` (GET), `/v1/drills/{id}/expand` (POST), `/v1/drills/{id}/complete` (POST)

5. **ΛD Epistemic alignment (depth-degrading):**
   - Certainty formula: (1.0 − depth × 0.05), clamped to [0.5, 0.99]
   - Root (depth 0): c=0.99 (near-certain, but still derived)
   - Mid-depth (5): c=0.75 (speculative)
   - Max-depth (10+): c=0.5 (highly speculative)
   - Lattice: c > 0.8 → believe; c ≤ 0.8 → speculate
   - All nodes derived per Theorem 5.1

6. **Primitives handler updated:**
   - `drill` → wired: `/v1/drills/* (expand/complete with depth-limited exploration tree)` — phase G19
   - Coverage: 39/47 = 83.0% (was 38/47 = 80.9%)

**Tests added (3):**
- `test_drill_tree_expansion_and_depth_limit` — validates root creation, path-based child IDs, multi-branch expansion, max_depth enforcement, non-existent parent rejection, leaf/node counts
- `test_drill_certainty_degradation_with_depth` — validates certainty formula at depths 0/1/2/5/10/20, node certainty verification, average certainty, all certainties in [0.5, 0.99]
- `test_drill_epistemic_alignment_theorem_5_1` — validates root capped at 0.99, Theorem 5.1 violation detection, lattice positions (shallow=believe, deep=speculate), completion immutability, serialization

**Evidence:**
- `cargo test` → 678 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 246 | 250 |
| Tests | 675 | 678 |
| Pub structs | ~161 | ~163 |
| Primitive coverage | 38/47 (80.9%) | 39/47 (83.0%) |

---

**Handoff G20:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Forge primitive runtime — wire `forge` cognitive primitive for artifact generation with template-based output construction.
- **E:** Deliberate primitive runtime — wire `deliberate` cognitive primitive for extended reasoning with backtrack and option evaluation.

---

### G20 — Forge Primitive Runtime (Option D)

**Scope:** Wire the `forge` cognitive primitive (#35 of 47) to runtime — artifact generation with template registration, `{{variable}}` placeholder extraction, and variable substitution rendering. ΛD: template rendering is deterministic but derived (c=0.99, δ=derived per Theorem 5.1).

**Delivered:**

1. **Structs (3 new pub structs → 166 total):**
   - `ForgeTemplate` — name, content with `{{placeholder}}` markers, extracted variable list, format hint
   - `ForgeArtifact` — id, template_name, rendered content, variables_used, format, certainty (0.99)
   - `ForgeSession` — id, name, templates map, artifacts list, `extract_variables()`, `add_template()`, `render()`

2. **Forge engine:**
   - `extract_variables()` — scans content for `{{var}}` patterns, deduplicates
   - `add_template()` — registers template with auto-extracted variables, rejects duplicates
   - `render()` — validates all required variables present, substitutes `{{var}}` → value, produces `ForgeArtifact`
   - Multiple renders per template, unique artifact IDs

3. **Handlers (5 new):**
   - `forge_create_handler` — POST /v1/forges (name)
   - `forge_template_handler` — POST /v1/forges/{id}/template (name, content, format → extracted variables)
   - `forge_render_handler` — POST /v1/forges/{id}/render (template, variables → artifact with ΛD envelope)
   - `forge_get_handler` — GET /v1/forges/{id} (templates + artifacts)
   - `forge_list_handler` — GET /v1/forges (all forges summary)

4. **Routes (4 new → 254 total):**
   - `/v1/forges` (GET+POST), `/v1/forges/{id}` (GET), `/v1/forges/{id}/template` (POST), `/v1/forges/{id}/render` (POST)

5. **ΛD Epistemic alignment:**
   - All artifacts: c=0.99, δ=derived (template instantiation is transformation)
   - Lattice: believe (deterministic but derived)
   - Effect row: `<io, epistemic:believe>`
   - Blame: CT-2 on missing variables or unknown template

6. **Primitives handler updated:**
   - `forge` → wired: `/v1/forges/* (template/render with {{variable}} substitution)` — phase G20
   - Coverage: 40/47 = 85.1% (was 39/47 = 83.0%)

**Tests added (3):**
- `test_forge_template_variable_extraction_and_rendering` — validates `{{var}}` extraction, deduplication, template registration, rendering with substitution, format propagation, certainty=0.99
- `test_forge_render_errors_and_multiple_artifacts` — validates missing variable error, non-existent template error, multiple renders with unique IDs, variable override between renders
- `test_forge_epistemic_alignment_theorem_5_1` — validates c=0.99 for all artifacts, Theorem 5.1 violation detection, lattice=believe, effect rows, all artifacts carry 0.99

**Evidence:**
- `cargo test` → 681 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 250 | 254 |
| Tests | 678 | 681 |
| Pub structs | ~163 | ~166 |
| Primitive coverage | 39/47 (83.0%) | **40/47 (85.1%)** |

---

**Handoff G21:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Deliberate primitive runtime — wire `deliberate` cognitive primitive for extended reasoning with backtrack and option evaluation.
- **E:** Consensus primitive runtime — wire `consensus` cognitive primitive for multi-agent agreement with voting and quorum.

---

### G21 — Deliberate Primitive Runtime (Option D)

**Scope:** Wire the `deliberate` cognitive primitive (#33 of 47) to runtime — structured decision-making with option evaluation, pros/cons scoring, backtracking (elimination), and margin-based certainty. ΛD: deliberation is inferential reasoning — all outcomes derived (c≤0.99, Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 168 total):**
   - `DeliberateOption` — id, label, description, pros/cons lists, composite score, eliminated flag, elimination reason
   - `DeliberateSession` — id, name, question, options, `add_option()`, `evaluate()`, `eliminate()`, `decide()`, `viable_count()`

2. **Deliberation engine:**
   - `add_option()` — adds option with neutral score (0.5), rejects after decision
   - `evaluate()` — adds pro/con, recomputes score: pros/(pros+cons), rejects eliminated options
   - `eliminate()` — backtrack: marks option eliminated, sets score to 0.0
   - `decide()` — selects highest-scoring viable option; certainty = margin × 0.99 (margin = best − second-best)
   - Clear winner (large margin) → high certainty; close contest → near-zero certainty

3. **Handlers (7 new):**
   - `deliberate_create_handler` — POST /v1/deliberate (name, question)
   - `deliberate_option_handler` — POST /v1/deliberate/{id}/option (label, description)
   - `deliberate_evaluate_handler` — POST /v1/deliberate/{id}/evaluate (option_id, pro, con → score)
   - `deliberate_eliminate_handler` — POST /v1/deliberate/{id}/eliminate (option_id, reason → backtrack)
   - `deliberate_decide_handler` — POST /v1/deliberate/{id}/decide (→ chosen + certainty)
   - `deliberate_get_handler` — GET /v1/deliberate/{id} (all options + decision)
   - `deliberate_list_handler` — GET /v1/deliberate (all sessions summary)

4. **Routes (6 new → 260 total):**
   - `/v1/deliberate` (GET+POST), `/v1/deliberate/{id}` (GET), `/v1/deliberate/{id}/option` (POST), `/v1/deliberate/{id}/evaluate` (POST), `/v1/deliberate/{id}/eliminate` (POST), `/v1/deliberate/{id}/decide` (POST)

5. **ΛD Epistemic alignment (margin-based):**
   - Certainty = (best_score − second_best_score) × 0.99, capped at 0.99
   - Clear winner: high margin → high certainty (believe)
   - Close contest: low margin → low certainty (speculate)
   - All decisions derived per Theorem 5.1

6. **Primitives handler updated:**
   - `deliberate` → wired: `/v1/deliberate/* (option/evaluate/eliminate/decide with scoring)` — phase G21
   - Coverage: 41/47 = 87.2% (was 40/47 = 85.1%)

**Tests added (3):**
- `test_deliberate_option_evaluation_and_scoring` — validates option addition, pros/cons scoring (3/4=0.75, 1/3=0.33), neutral initial score, viable count
- `test_deliberate_backtrack_and_decide` — validates elimination (backtrack), post-elimination rejection, decide selects highest score, post-decision immutability, no viable options error
- `test_deliberate_epistemic_alignment_theorem_5_1` — validates margin-based certainty (clear=0.99, close≈0.0), Theorem 5.1 violation detection, lattice positions, certainty ≤0.99

**Evidence:**
- `cargo test` → 684 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 254 | 260 |
| Tests | 681 | 684 |
| Pub structs | ~166 | ~168 |
| Primitive coverage | 40/47 (85.1%) | 41/47 (87.2%) |

---

**Handoff G22:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Consensus primitive runtime — wire `consensus` cognitive primitive for multi-agent agreement with voting and quorum.
- **E:** Hibernate primitive runtime — wire `hibernate` cognitive primitive for long-running suspension with checkpoint/resume.

---

### G22 — Consensus Primitive Runtime (Option D)

**Scope:** Wire the `consensus` cognitive primitive (#34 of 47) to runtime — multi-agent agreement through confidence-weighted voting with quorum thresholds and agreement-based certainty. ΛD: consensus is aggregated opinion — always derived (c≤0.99, Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 170 total):**
   - `ConsensusVote` — voter, choice, confidence (0.0–1.0), rationale, timestamp
   - `ConsensusSession` — id, name, proposal, choices, quorum, votes, `vote()`, `tally()`, `resolve()`, `has_quorum()`

2. **Consensus engine:**
   - `vote()` — casts vote with confidence weighting, one-vote-per-voter, validates choice against allowed set
   - `tally()` — confidence-weighted scores per choice, sorted descending
   - `has_quorum()` — vote_count ≥ quorum threshold
   - `resolve()` — selects winner (highest weighted score), computes agreement (winner_score/total_score), certainty = agreement × 0.99

3. **Handlers (5 new):**
   - `consensus_create_handler` — POST /v1/consensus (name, proposal, choices, quorum)
   - `consensus_vote_handler` — POST /v1/consensus/{id}/vote (voter, choice, confidence, rationale → live tally)
   - `consensus_resolve_handler` — POST /v1/consensus/{id}/resolve (→ winner + agreement + ΛD)
   - `consensus_get_handler` — GET /v1/consensus/{id} (votes + tally)
   - `consensus_list_handler` — GET /v1/consensus (all sessions summary)

4. **Routes (4 new → 264 total):**
   - `/v1/consensus` (GET+POST), `/v1/consensus/{id}` (GET), `/v1/consensus/{id}/vote` (POST), `/v1/consensus/{id}/resolve` (POST)

5. **ΛD Epistemic alignment (agreement-based):**
   - Certainty = agreement × 0.99, capped at 0.99
   - Unanimous → agreement=1.0, certainty=0.99 (believe)
   - Majority → agreement>0.5, certainty moderate (speculate)
   - Split → agreement=0.5, certainty low (doubt)
   - All outcomes derived per Theorem 5.1

6. **Primitives handler updated:**
   - `consensus` → wired: `/v1/consensus/* (vote/resolve with quorum and agreement scoring)` — phase G22
   - Coverage: 42/47 = 89.4% (was 41/47 = 87.2%)

**Tests added (3):**
- `test_consensus_voting_and_tally` — validates voting, confidence-weighted tally (claude=1.7 vs gpt4=0.7), duplicate voter rejection, invalid choice rejection
- `test_consensus_quorum_and_resolve` — validates quorum enforcement (2/3 → fail, 3/3 → pass), resolve winner (approve), agreement ratio (0.74), unanimous agreement (1.0), post-resolution immutability
- `test_consensus_epistemic_alignment_theorem_5_1` — validates certainty ≤0.99 even unanimous, Theorem 5.1 violation detection, lattice positions (believe/speculate/doubt), split vote → doubt, confidence clamping

**Evidence:**
- `cargo test` → 687 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 260 | 264 |
| Tests | 684 | 687 |
| Pub structs | ~168 | ~170 |
| Primitive coverage | 41/47 (87.2%) | **42/47 (89.4%)** |

---

**Handoff G23:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** Hibernate primitive runtime — wire `hibernate` cognitive primitive for long-running suspension with checkpoint/resume.
- **E:** OTS primitive runtime — wire `ots` cognitive primitive for one-time-secret generation with ephemeral tokens.

---

### G23 — Hibernate Primitive Runtime (Option D)

**Scope:** Wire the `hibernate` cognitive primitive (#32 of 47) to runtime — long-running suspension with checkpoint/resume lifecycle. Checkpoints capture exact state snapshots (c=1.0, δ=raw); resumed execution is derived (c=0.99, δ=derived per Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 172 total):**
   - `HibernateCheckpoint` — id, label, serialized state (JSON), phase, timestamp
   - `HibernateSession` — id, name, operation, status lifecycle, checkpoints, `suspend()`, `checkpoint()`, `resume()`, `complete()`

2. **Hibernate engine:**
   - `checkpoint()` — saves immutable state snapshot, rejects after completion
   - `suspend()` — transitions active→suspended, guards against double-suspend and completed sessions
   - `resume(checkpoint_id)` — transitions suspended→resumed, validates checkpoint exists, stores resumed_from
   - `complete()` — transitions to completed, guards against double-completion
   - Status lifecycle: active → suspended → resumed → completed

3. **Handlers (6 new):**
   - `hibernate_create_handler` — POST /v1/hibernate (name, operation)
   - `hibernate_checkpoint_handler` — POST /v1/hibernate/{id}/checkpoint (label, state, phase)
   - `hibernate_suspend_handler` — POST /v1/hibernate/{id}/suspend
   - `hibernate_resume_handler` — POST /v1/hibernate/{id}/resume (checkpoint_id → restored state)
   - `hibernate_get_handler` — GET /v1/hibernate/{id} (status + checkpoints)
   - `hibernate_list_handler` — GET /v1/hibernate (all sessions)

4. **Routes (5 new → 269 total):**
   - `/v1/hibernate` (GET+POST), `/v1/hibernate/{id}` (GET), `/v1/hibernate/{id}/checkpoint` (POST), `/v1/hibernate/{id}/suspend` (POST), `/v1/hibernate/{id}/resume` (POST)

5. **ΛD Epistemic alignment:**
   - Checkpoint: c=1.0, δ=raw, lattice=know (exact state capture)
   - Resume: c=0.99, δ=derived, lattice=believe (reconstruction from checkpoint)
   - Theorem 5.1: raw checkpoints CAN carry c=1.0; resumed (derived) cannot

6. **Primitives handler updated:**
   - `hibernate` → wired: `/v1/hibernate/* (checkpoint/suspend/resume with state preservation)` — phase G23
   - Coverage: 43/47 = 91.5% (was 42/47 = 89.4%)

**Tests added (3):**
- `test_hibernate_checkpoint_and_suspend` — validates checkpoint creation, state JSON preservation, suspend lifecycle, double-suspend rejection, checkpoint-while-suspended allowed
- `test_hibernate_resume_and_complete` — validates resume from specific checkpoint, state restoration, non-existent checkpoint rejection, complete lifecycle, post-completion guards
- `test_hibernate_epistemic_alignment` — validates checkpoint raw (c=1.0), resume derived (c=0.99), Theorem 5.1 (raw OK, derived+c=1.0 rejected), full lifecycle (active→suspended→resumed→completed)

**Evidence:**
- `cargo test` → 690 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 264 | 269 |
| Tests | 687 | 690 |
| Pub structs | ~170 | ~172 |
| Primitive coverage | 42/47 (89.4%) | **43/47 (91.5%)** |

---

**Handoff G24:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** AxonStore transact ℰMCP tool — expose atomic `transact` as MCP tool with all-or-nothing batch semantics and per-op ΛD envelopes.
- **D:** OTS primitive runtime — wire `ots` cognitive primitive for one-time-secret generation with ephemeral tokens.
- **E:** Psyche primitive runtime — wire `psyche` cognitive primitive for metacognitive self-reflection with introspection reports.

---

### G24 — OTS Primitive Runtime (Option D)

**Scope:** Wire the `ots` cognitive primitive (#15 of 47) to runtime — one-time-secret generation with ephemeral tokens, TTL-based expiry, and single-use consumption. Values are cleared from memory after retrieval. ΛD: created/retrieved secrets are raw (c=1.0); consumed/expired are void (c=0.0).

**Delivered:**

1. **Struct (1 new pub struct → 173 total):**
   - `OtsSecret` — token, value (cleared on consume), consumed flag, TTL, creator, label, `is_expired()`, `consume()`

2. **OTS engine:**
   - `consume()` — returns value and permanently clears it from struct, rejects if already consumed or expired
   - `is_expired()` — checks if now > created_at + ttl_secs (ttl_secs=0 means no expiry)
   - `generate_ots_token()` — unique token generation with nanosecond-based hex suffix
   - Security: value is zeroed after single retrieval, list endpoint never exposes values

3. **Handlers (3 new):**
   - `ots_create_handler` — POST /v1/ots (value, ttl_secs, label → token)
   - `ots_retrieve_handler` — GET /v1/ots/{token} (→ value + destroy, one-time only)
   - `ots_list_handler` — GET /v1/ots (metadata only, never values)

4. **Routes (2 new → 271 total):**
   - `/v1/ots` (GET+POST), `/v1/ots/{token}` (GET)

5. **ΛD Epistemic alignment:**
   - Created secret: c=1.0, δ=raw (the secret IS the ground truth)
   - Retrieved secret: c=1.0, δ=raw (exact value, then destroyed)
   - Consumed/expired: c=0.0, δ=void (no longer exists)
   - Lattice: available → know, consumed → ⊥ (bottom)
   - One of few primitives where raw c=1.0 is correct (consistent with Theorem 5.1)

6. **Primitives handler updated:**
   - `ots` → wired: `/v1/ots/* (create/retrieve-once with TTL and ephemeral destruction)` — phase G24
   - Coverage: 44/47 = 93.6% (was 43/47 = 91.5%)

**Tests added (3):**
- `test_ots_create_and_consume_once` — validates single-use consume, value clearing, double-consume rejection
- `test_ots_expiry_and_ttl` — validates TTL boundary (within/expired), expired consume rejection, no-TTL (ttl=0) never expires
- `test_ots_epistemic_alignment` — validates raw envelopes (c=1.0), void after consume (c=0.0), Theorem 5.1 consistency, value zeroing, token generation

**Evidence:**
- `cargo test` → 693 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 269 | 271 |
| Tests | 690 | 693 |
| Pub structs | ~172 | ~173 |
| Primitive coverage | 43/47 (91.5%) | **44/47 (93.6%)** |

---

**Handoff G25:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Psyche primitive runtime — wire `psyche` cognitive primitive for metacognitive self-reflection with introspection reports.
- **D:** Pix primitive runtime — wire `pix` cognitive primitive for visual reasoning with image metadata and annotation.
- **E:** AxonEndpoint primitive runtime — wire `axonendpoint` cognitive primitive for external API endpoint binding.

---

### G25 — Psyche Primitive Runtime (Option C)

**Scope:** Wire the `psyche` cognitive primitive (#13 of 47) to runtime — metacognitive self-reflection with categorized insights (knowledge_gap/uncertainty/bias/strength/recommendation), severity levels, and a self-awareness scoring algorithm. ΛD: self-reflection is always derived (c≤0.99, Theorem 5.1).

**Delivered:**

1. **Structs (2 new pub structs → 175 total):**
   - `PsycheInsight` — id, category (5 types), content, confidence, severity (info/warning/critical), timestamp
   - `PsycheSession` — id, name, context, insights, `add_insight()`, `report()` (introspection report generator)

2. **Psyche engine:**
   - `add_insight()` — validates category (5 types) and severity (3 levels), clamps confidence, rejects after completion
   - `report()` — generates introspection report:
     - Category distribution (gaps, uncertainties, biases, strengths, recommendations)
     - Severity summary (critical/warning/info)
     - Average confidence
     - **Self-awareness score**: diversity×0.7 + avg_confidence×0.3 − critical_penalty (diversity = categories_used/5)

3. **Handlers (5 new):**
   - `psyche_create_handler` — POST /v1/psyche (name, context)
   - `psyche_insight_handler` — POST /v1/psyche/{id}/insight (category, content, confidence, severity)
   - `psyche_complete_handler` — POST /v1/psyche/{id}/complete (→ report + awareness score + ΛD)
   - `psyche_get_handler` — GET /v1/psyche/{id} (insights + report)
   - `psyche_list_handler` — GET /v1/psyche (all sessions)

4. **Routes (4 new → 275 total):**
   - `/v1/psyche` (GET+POST), `/v1/psyche/{id}` (GET), `/v1/psyche/{id}/insight` (POST), `/v1/psyche/{id}/complete` (POST)

5. **ΛD Epistemic alignment:**
   - Certainty = awareness_score × 0.99, capped at 0.99
   - Lattice: awareness > 0.7 → believe; else → speculate
   - Self-reflection is inherently derived (meta-reasoning about reasoning)
   - All insights carry c=0.99, δ=derived per Theorem 5.1

6. **Primitives handler updated:**
   - `psyche` → wired: `/v1/psyche/* (insight/complete with self-awareness scoring)` — phase G25
   - Coverage: 45/47 = 95.7% (was 44/47 = 93.6%)

**Tests added (3):**
- `test_psyche_insight_categories_and_validation` — validates all 5 categories, invalid category/severity rejection, confidence clamping, insight counting
- `test_psyche_introspection_report` — validates category distribution, severity summary, average confidence (0.64), self-awareness score (~0.79), diversity penalty for narrow insights, post-completion rejection
- `test_psyche_epistemic_alignment_theorem_5_1` — validates derived c≤0.99, Theorem 5.1 violation detection, awareness-scaled certainty, lattice positions, empty session zero awareness

**Evidence:**
- `cargo test` → 696 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 271 | 275 |
| Tests | 693 | 696 |
| Pub structs | ~173 | ~175 |
| Primitive coverage | 44/47 (93.6%) | **45/47 (95.7%)** |

---

**Handoff G26:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Pix primitive runtime — wire `pix` cognitive primitive for visual reasoning with image metadata and annotation.
- **D:** AxonEndpoint primitive runtime — wire `axonendpoint` cognitive primitive for external API endpoint binding.
- **E:** Phase G exit review — comprehensive audit of all 47 primitives, cumulative metrics, and Phase H readiness assessment.

---

### G26 — AxonEndpoint Primitive Runtime (Option D)

**Scope:** Wire the `axonendpoint` cognitive primitive (#19 of 47) to runtime — external API endpoint binding with URL templates (`{param}` placeholders), method/auth/header configuration, intent-based call recording, and call history. ΛD: external API results are derived (c=0.99, δ=derived) with network effect row.

**Delivered:**

1. **Structs (2 new pub structs → 177 total):**
   - `EndpointBinding` — name, method (GET/POST/PUT/DELETE), url_template, headers, auth_type/auth_ref, timeout, enabled, call/error counts
   - `EndpointCallRecord` — id, binding, resolved_url, method, body, params, timestamp

2. **Endpoint engine:**
   - URL template resolution: `{param}` placeholders substituted from params map
   - Intent-based calling: records call intent without actual HTTP (delegated to external orchestration/MCP clients)
   - Call history capped at 500 entries (FIFO)
   - Method validation (GET/POST/PUT/DELETE), enabled flag check

3. **Handlers (5 new):**
   - `endpoint_create_handler` — POST /v1/endpoints (name, method, url_template, auth, headers)
   - `endpoint_call_handler` — POST /v1/endpoints/{name}/call (params, body → resolved URL + call record)
   - `endpoint_get_handler` — GET /v1/endpoints/{name} (binding details + stats)
   - `endpoint_delete_handler` — DELETE /v1/endpoints/{name} (admin-only)
   - `endpoint_list_handler` — GET /v1/endpoints (all bindings summary)

4. **Routes (3 new → 278 total):**
   - `/v1/endpoints` (GET+POST), `/v1/endpoints/{name}` (GET+DELETE), `/v1/endpoints/{name}/call` (POST)

5. **ΛD Epistemic alignment:**
   - Call results: c=0.99, δ=derived (external data crosses trust boundary)
   - Effect row: `<io, network, epistemic:speculate>` — includes network effect
   - Lattice: speculate (external sources are inherently uncertain)
   - Binding configuration itself: raw (c=1.0) — but call results are derived

6. **Primitives handler updated:**
   - `axonendpoint` → wired: `/v1/endpoints/* (bind/call with URL templates and auth config)` — phase G26
   - Coverage: 46/47 = 97.9% (was 45/47 = 95.7%)

**Tests added (3):**
- `test_axonendpoint_binding_and_url_resolution` — validates URL template resolution with multi-param substitution, headers, auth config, serialization
- `test_axonendpoint_call_record_and_history` — validates call recording, URL resolution, total_calls increment, disabled binding check, valid methods
- `test_axonendpoint_epistemic_alignment` — validates derived c=0.99 for call results, Theorem 5.1 violation detection, network effect row, lattice=speculate, binding config raw vs result derived, serialization round-trip

**Evidence:**
- `cargo test` → 699 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 275 | 278 |
| Tests | 696 | 699 |
| Pub structs | ~175 | ~177 |
| Primitive coverage | 45/47 (95.7%) | **46/47 (97.9%)** |

---

**Handoff G27:**
- **A:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps and auto-rollback.
- **B:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server with type-safe tool invocation.
- **C:** Pix primitive runtime — wire `pix` cognitive primitive for visual reasoning with image metadata and annotation (final primitive → 47/47 = 100%).
- **D:** Phase G exit review — comprehensive audit of all 47 primitives, cumulative metrics, and Phase H readiness assessment.
- **E:** ℰMCP tool surface expansion — expose remaining primitives (psyche/forge/drill/etc.) as MCP tools with CSP §5.3 schemas.

---

### G27 — Pix Primitive Runtime (Option C) — FINAL PRIMITIVE

**Scope:** Wire the `pix` cognitive primitive (#12 of 47) — the **final primitive** — to runtime. Visual reasoning with image registration, bounding-box annotation, and visual classification. ΛD: image metadata is raw (c=1.0); annotations are derived (c=0.99, Theorem 5.1). **This session achieves 47/47 = 100% cognitive primitive coverage.**

**Delivered:**

1. **Structs (3 new pub structs → 180 total):**
   - `PixAnnotation` — id, label, bbox [x,y,w,h] in normalized coords (0.0–1.0), confidence, category (object/text/region/feature), description
   - `PixImage` — id, source, width/height, format, annotations, ΛD envelope, auto-incrementing annotation IDs
   - `PixSession` — id, name, images map, `register_image()`, `annotate()`, `image_count()`, `total_annotations()`

2. **Pix engine:**
   - `register_image()` — registers image with raw envelope (c=1.0, metadata is ground truth)
   - `annotate()` — adds annotation with bbox validation ([0.0,1.0]), category validation, confidence clamping; transitions image envelope to derived (c=0.99)
   - Bbox validation: all 4 values must be in [0.0, 1.0]
   - Category validation: object/text/region/feature

3. **Handlers (5 new):**
   - `pix_create_handler` — POST /v1/pix (name)
   - `pix_image_handler` — POST /v1/pix/{id}/image (source, width, height, format)
   - `pix_annotate_handler` — POST /v1/pix/{id}/annotate (image_id, label, bbox, confidence, category, description)
   - `pix_get_handler` — GET /v1/pix/{id} (images + annotations)
   - `pix_list_handler` — GET /v1/pix (all sessions)

4. **Routes (4 new → 282 total):**
   - `/v1/pix` (GET+POST), `/v1/pix/{id}` (GET), `/v1/pix/{id}/image` (POST), `/v1/pix/{id}/annotate` (POST)

5. **ΛD Epistemic alignment:**
   - Image registration: c=1.0, δ=raw, lattice=know (metadata is ground truth)
   - Annotation: c=0.99, δ=derived, lattice=speculate (visual interpretation)
   - Theorem 5.1: raw metadata CAN carry c=1.0; annotations (derived) cannot

6. **Primitives handler updated:**
   - `pix` → wired: `/v1/pix/* (image/annotate with bbox and visual classification)` — phase G27
   - **Coverage: 47/47 = 100.0%** (was 46/47 = 97.9%)

**Tests added (3):**
- `test_pix_image_registration_and_metadata` — validates image registration, metadata (width/height/format/source), raw envelope (c=1.0), multi-image session
- `test_pix_annotation_and_bbox_validation` — validates annotation creation, bbox validation (out-of-range rejected), invalid category rejection, confidence clamping, envelope transition (raw→derived)
- `test_pix_epistemic_alignment_theorem_5_1_final_primitive` — validates raw→derived transition on annotation, Theorem 5.1 compliance, lattice positions, **asserts 20+4+14+9=47 total primitives**

**Evidence:**
- `cargo test` → 702 passed, 0 failed
- `cargo build --release` → clean (warnings only)

| Metric | Before | After |
|--------|--------|-------|
| Routes | 278 | 282 |
| Tests | 699 | 702 |
| Pub structs | ~177 | ~180 |
| Primitive coverage | 46/47 (97.9%) | **47/47 (100.0%)** |

---

## Phase G Milestone: 100% Cognitive Primitive Coverage

All 47 AXON cognitive primitives are now wired to runtime:

| Category | Count | Primitives |
|----------|-------|------------|
| Declarations (20) | 20/20 | persona, context, flow, anchor, tool, memory, type, agent, shield, pix, psyche, corpus, dataspace, ots, mandate, compute, daemon, axonstore, axonendpoint, lambda |
| Epistemic (4) | 4/4 | know, believe, speculate, doubt |
| Execution (14) | 14/14 | step, reason, validate, refine, weave, probe, use, remember, recall, par, hibernate, deliberate, consensus, forge |
| Navigation (9) | 9/9 | stream, navigate, drill, trail, corroborate, focus, associate, aggregate, explore |

**Phase G cumulative (G1–G27):**
- Sessions: 27
- Routes: 192 → 282 (+90)
- Tests: 621 → 702 (+81)
- Pub structs: 132 → ~180 (+48)
- Primitives wired: 29/47 → 47/47 (100%)

---

**Handoff G28:**
- **A:** Phase G exit review — comprehensive audit document with cumulative metrics and Phase H readiness assessment.
- **B:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps.
- **C:** Client SDK scaffolding — TypeScript MCP client package for ℰMCP server.
- **D:** ℰMCP tool surface expansion — expose new primitives as MCP tools with CSP §5.3 schemas.
- **E:** Performance profiling — benchmark the 282-route server under load with latency/throughput analysis.

---

### G28 — Phase G Exit Review (Option A) — PHASE CLOSEOUT

**Scope:** Comprehensive phase closeout document with cumulative metrics, complete primitive inventory, formal alignment summary, and Phase H readiness assessment.

**Delivered:**

1. **`docs/phase_g_exit_review.md`** — full exit review document:
   - Quantitative summary: 57,421 source lines, 24,939 test lines, 282 routes, 179 pub structs, 702 tests
   - Complete 47/47 primitive inventory with endpoint, phase, and ΛD alignment per primitive
   - Session log (G1–G28): routes/tests added per session
   - Formal alignment summary: ΛD, Theorem 5.1, CSP §5.3, blame calculus, epistemic lattice
   - Exit criteria checklist: all 8 criteria met
   - Cumulative project status (Phases A–G): ~227 sessions total
   - Phase H readiness assessment with 6 candidates

**Evidence:**
- No code changes (documentation-only session)
- All prior evidence maintained: 702 tests pass, release build clean

| Metric | Value |
|--------|-------|
| Routes | 282 |
| Tests | 702 |
| Pub structs | 179 |
| Source lines | 57,421 |
| Test lines | 24,939 |
| Total lines | 82,360 |
| Primitive coverage | **47/47 (100.0%)** |
| Phase G sessions | 28 |

---

## PHASE G — COMPLETE

*Phase G closed: 2026-04-14*
*Objective achieved: all 47 cognitive primitives wired to runtime*
*See `docs/phase_g_exit_review.md` for full closeout document*
