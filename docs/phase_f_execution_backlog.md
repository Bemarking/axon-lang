# Backlog de Ejecución — Fase F

Este archivo lista las sesiones planeadas y ejecutadas para la Fase F (Producción y Endurecimiento) del programa AXON.

## Objetivo de Fase

Llevar AXON de plataforma funcional a sistema listo para producción real. La Fase D entregó la infraestructura (189 rutas, 576 tests), la Fase E la conectó con backends LLM reales y protocolo MCP (606 tests). La Fase F endurece, valida end-to-end, y prepara para consumo externo.

## Estado heredado de Fase E

| Métrica | Valor |
|---------|-------|
| Módulos fuente | 61 archivos `.rs` |
| Líneas fuente | 48,668 |
| Tests de integración | 606 |
| Rutas API (HTTP) | 189 |
| Métodos MCP (JSON-RPC) | 7 (initialize, tools/list, tools/call, resources/list, resources/read, prompts/list, prompts/get) |
| Structs públicos (server) | 131 |
| Backends soportados | 7 (anthropic, openai, gemini, kimi, glm, openrouter, ollama) |
| Primitivas cognitivas | 47 (20 declarations + 4 epistemic + 14 execution + 9 navigation) |
| Protocolo MCP | 100% (tools + resources + prompts + streaming) |
| Backend stack | Registry → Keys → Metrics → Fallback → Circuit Breaker |
| Formal alignment | ΛD envelopes, blame CT-2/CT-3, CSP §5.3, effect rows, Theorem 5.1 |

## Backlog Inicial

1. Wire remaining 16 handlers — resolver keys, registrar métricas, usar fallback y circuit breaker en todos los handlers de ejecución, no solo `execute_handler`.
2. Backend rate limiting — throttling por proveedor respetando límites de API.
3. Backend cost tracking — costo por backend usando `CostPricing` integrado al registry.
4. End-to-end validation — tests con backends reales (stub→anthropic/openai).
5. AxonStore persistence — persistencia durable de estado de ejecución entre restarts.
6. Production TLS — HTTPS nativo para el servidor.

## Sesiones

**Handoff F1:**
- **A:** Wire remaining 16 execution handlers — propagate resolve_backend_key + record_backend_metrics + fallback + circuit breaker to all server_execute call sites.
- **B:** Backend rate limiting — per-backend request throttling with configurable RPM/TPM limits.
- **C:** Backend cost tracking — compute per-backend USD cost from CostPricing and accumulate in registry.
- **D:** AxonStore persistence — wire `axonstore` primitive to durable storage backend (file/SQLite).
- **E:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps.

### Sesión F1: Wire All Execution Handlers — full backend stack propagation

**Objetivo de sesión:**
Eliminar la deuda técnica de E2-E5: los 16 handlers de ejecución secundarios usaban `server_execute(..., None)` — sin resolver keys del registry, sin registrar métricas, sin fallback chain, sin circuit breaker. Solo `execute_handler` (el handler primario) tenía el stack completo.

**Alcance cerrado:**
- Nueva función `server_execute_full(state, source, source_file, flow_name, backend)`:
  - Encapsula el pipeline completo: `resolve_backend_key` → `execute_with_fallback` → `record_backend_metrics`.
  - Retorna `(Result<ServerExecutionResult, String>, String)` — resultado + backend real usado.
  - Registra métricas tanto en éxito como en fallo (circuit breaker se alimenta correctamente).
- 16 call sites actualizados de `server_execute(..., None)` a `server_execute_full(&state, ...)`:
  - `daemon_run_handler` — ejecución de daemons.
  - `execute_dequeue_handler` — ejecución desde cola.
  - `schedules_tick_handler` — ejecución programada (todos los schedules due).
  - `traces_replay_handler` — re-ejecución de traces.
  - `execute_drain_handler` — drain de cola.
  - `execute_sandbox_handler` — ejecución sandboxed.
  - `execute_process_handler` — ejecución con middleware.
  - `execute_dry_run_handler` — dry-run.
  - `execute_pipeline_handler` — pipeline multi-stage (cada stage).
  - `execute_cached_handler` — ejecución con cache-through.
  - `execute_batch_handler` — batch (cada item).
  - `execute_batch_cached_handler` — batch cached (cada item).
  - `flows_group_execute_handler` — ejecución grupal por tag (cada flow).
  - `execute_pinned_handler` — ejecución de versión fijada.
  - `execute_ab_test_handler` — A/B test.
  - `execute_cache_replay_handler` — replay desde cache.
- Excluido: `execute_warm_handler` mantiene `server_execute(..., "stub", None)` — intencional, warming no requiere backend real.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `server_execute_full()`: nueva función wrapper (resolve + fallback + metrics).
  - 16 call sites: `server_execute(..., None)` → `server_execute_full(&state, ...)`.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (609 total):
  - `server_execute_full_resolves_key_and_records_metrics` — pipeline 3-step: key → fallback → metrics.
  - `all_execution_handlers_use_full_stack` — inventario de 16+ handlers, warm handler excluido.
  - `server_execute_full_records_metrics_on_failure` — fallas registran métricas y alimentan circuit breaker.

**Verificación:**
- `cargo test`: 609 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff F2:**
- **A:** Backend rate limiting — per-backend request throttling with configurable RPM/TPM limits.
- **B:** Backend cost tracking — compute per-backend USD cost from CostPricing and accumulate in registry.
- **C:** AxonStore persistence — wire `axonstore` primitive to durable storage backend (file/SQLite).
- **D:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps.
- **E:** Backend selection optimizer — auto-select cheapest/fastest backend based on accumulated metrics.

### Sesión F2: Backend Cost Tracking — per-backend USD cost from CostPricing

**Objetivo de sesión:**
Integrar el cálculo de costo por llamada a backend usando `CostPricing` (input_per_million/output_per_million por proveedor) y acumular el total USD en cada `BackendRegistryEntry`. Esto conecta el sistema de costos de Phase D con el backend registry de Phase E.

**Alcance cerrado:**
- `BackendRegistryEntry` + `total_cost_usd: f64` (`#[serde(default)]`).
- En `record_backend_metrics()`:
  - Extrae pricing de `state.cost_pricing` **antes** del borrow mutable a `backend_registry` (evita conflicto de borrows).
  - Computa: `cost = (tokens_input / 1M) × input_price + (tokens_output / 1M) × output_price`.
  - Acumula con 4 decimales de precisión.
  - Backends desconocidos en CostPricing → precio 0 (stub es gratis).
- `backends_metrics_handler` (`GET /v1/backends/{name}/metrics`): incluye `total_cost_usd` en respuesta.
- No entra: cost budgets per-backend (usar flow-level budgets existentes), cost alerts.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendRegistryEntry`: +1 campo `total_cost_usd`.
  - `record_backend_metrics()`: pricing extraction + cost computation + accumulation.
  - `backends_metrics_handler`: `total_cost_usd` en ambas ramas (Some/None).
  - Todos los constructors: actualizados.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (612 total):
  - `backend_cost_tracking_field_serde` — serialización, default 0.0.
  - `backend_cost_computation_from_pricing` — cálculo correcto: $3/M input + $15/M output, unknown = $0.
  - `backend_cost_accumulation_across_calls` — acumulación over 3 calls, stub gratis.

**Verificación:**
- `cargo test`: 612 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff F3:**
- **A:** Backend rate limiting — per-backend request throttling with configurable RPM/TPM limits.
- **B:** AxonStore persistence — wire `axonstore` primitive to durable storage backend (file/SQLite).
- **C:** End-to-end smoke test infrastructure — test harness for live backend validation with cost caps.
- **D:** Backend selection optimizer — auto-select cheapest/fastest backend based on accumulated metrics and cost.
- **E:** Backend cost budget — per-backend spending limit with alert on threshold.

### Sesión F3: Backend Selection Optimizer — auto-select optimal backend by strategy

**Objetivo de sesión:**
Implementar selección automática de backend basada en métricas acumuladas. Dado que ahora rastreamos calls, errors, latency, y costo por backend (E3+F2), el optimizer analiza estos datos en tiempo real y recomienda el mejor backend según la estrategia elegida.

**Alcance cerrado:**
- `BackendScore` struct: name, enabled, circuit_open, total_calls, error_rate, avg_latency_ms, cost_per_call_usd, total_cost_usd, score (composite).
- `compute_backend_scores(state, strategy)` — core optimizer:
  - **cheapest**: `score = 100 - cost_per_call × 1000` (lower cost → higher score).
  - **fastest**: `score = 100 - avg_latency / 50` (lower latency → higher score).
  - **most_reliable**: `score = (1 - error_rate) × 100` (lower errors → higher score).
  - **balanced** (default): `40% reliability + 30% speed + 30% cost` (Pareto-inspired, §7).
  - Circuit-open backends → score 0 (never selected).
  - Backends sin métricas → score 100 (benefit of the doubt).
  - Sorted descending by score.
- `GET /v1/backends/ranking?strategy=X` — ranked list de todos los backends con scores.
- `POST /v1/backends/select` — retorna el backend óptimo + alternatives top-3.
- Routes: 189→191.

**Conexión con §7 (Pareto):** La estrategia `balanced` implementa un compromiso multi-objetivo entre fiabilidad, velocidad y costo — principio Pareto del documento de investigación.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendScore` struct.
  - `compute_backend_scores()`: optimizer con 4 estrategias.
  - `backends_ranking_handler`, `backends_select_handler`: 2 handlers.
  - +2 rutas.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (615 total):
  - `backend_score_struct_serializes` — struct con score, error_rate, cost fields.
  - `backend_selection_strategies` — 3 backends con perfiles distintos, cada estrategia selecciona correctamente.
  - `backend_selection_circuit_open_excluded` — circuit-open siempre score 0, empty registry → error.

**Verificación:**
- `cargo test`: 615 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff F4:**
- **A:** Backend rate limiting — per-backend RPM/TPM throttling with configurable limits.
- **B:** AxonStore persistence — wire `axonstore` primitive to durable storage backend.
- **C:** End-to-end smoke test infrastructure — test harness for live backend validation.
- **D:** Backend cost budget — per-backend spending limit with alert and auto-disable.
- **E:** Auto-backend in execute — use optimizer to auto-select backend when "auto" is specified.

### Sesión F4: Auto-Backend in Execute — optimizer-driven backend selection via "auto"

**Objetivo de sesión:**
Conectar el optimizer (F3) directamente al path de ejecución: cuando un usuario especifica `backend: "auto"`, el sistema auto-selecciona el backend óptimo usando la estrategia `balanced` (40% reliability + 30% speed + 30% cost). Esto funciona en todos los 16+ handlers vía `server_execute_full` y en el handler primario `execute_handler`.

**Alcance cerrado:**
- En `server_execute_full()`:
  - Si `backend == "auto"` → `compute_backend_scores(state, "balanced")` → usa `scores[0].name`.
  - Si registry vacío → fallback a `"stub"`.
  - El `effective_backend` se pasa a `resolve_backend_key`, `execute_with_fallback`, y `record_backend_metrics`.
  - Todos los 16 handlers que usan `server_execute_full` soportan "auto" automáticamente.
- En `execute_handler` (handler primario con `execute_with_fallback` directo):
  - Mismo patrón: resuelve "auto" dentro del lock scope antes de ejecutar.
- Cadena completa: `"auto"` → optimizer → `effective_backend` → key resolution → fallback chain → circuit breaker → metrics → cost.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `server_execute_full()`: auto-backend resolution al inicio.
  - `execute_handler`: auto-backend resolution en lock scope.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (618 total):
  - `auto_backend_resolves_to_best` — balanced scoring: openai gana sobre anthropic con perfiles simulados.
  - `auto_backend_fallback_to_stub_when_empty` — registry vacío → "stub".
  - `auto_backend_propagates_through_all_handlers` — "auto" nunca llega a downstream, siempre resuelto.

**Verificación:**
- `cargo test`: 618 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff F5:**
- **A:** Backend rate limiting — per-backend RPM/TPM throttling with configurable limits.
- **B:** AxonStore persistence — wire `axonstore` primitive to durable storage backend.
- **C:** End-to-end smoke test infrastructure — test harness for live backend validation.
- **D:** Backend cost budget — per-backend spending limit with alert and auto-disable on breach.
- **E:** Phase F closeout — feature inventory, backend stack audit, production readiness review.

### Sesión F5: Backend Rate Limiting — per-backend RPM/TPM throttling

**Objetivo de sesión:**
Implementar throttling por proveedor LLM con límites configurables de requests per minute (RPM) y tokens per minute (TPM). Previene exceder cuotas de API de proveedores y protege contra uso excesivo.

**Alcance cerrado:**
- `BackendRegistryEntry` +5 campos:
  - `max_rpm: u32` (0=unlimited), `max_tpm: u64` (0=unlimited).
  - `rpm_window_start: u64` (unix seconds), `rpm_count: u32`, `tpm_count: u64`.
- `check_backend_rate_limit(state, backend)`:
  - Reset automático de ventana tras 60 segundos.
  - Check RPM: si `max_rpm > 0 && rpm_count >= max_rpm` → error con tiempo restante.
  - Check TPM: si `max_tpm > 0 && tpm_count >= max_tpm` → error con tiempo restante.
  - Incrementa `rpm_count` pre-ejecución.
  - TPM incrementado post-ejecución en `record_backend_metrics` (tokens reales).
- Wired into `server_execute_full()`: check antes de resolve_backend_key. Todos los 16+ handlers lo heredan.
- Endpoints:
  - `PUT /v1/backends/{name}/limits` — configurar max_rpm/max_tpm. Audit-logged.
  - `GET /v1/backends/{name}/limits` — ver límites y uso actual (current_rpm, current_tpm, window_remaining, rpm_limited, tpm_limited).
- Routes: 191→192.

**Archivos modificados:**
- `axon-rs/src/axon_server.rs`:
  - `BackendRegistryEntry`: +5 campos rate limiting.
  - `check_backend_rate_limit()`: check + window reset + RPM increment.
  - `record_backend_metrics()`: TPM increment post-ejecución.
  - `server_execute_full()`: rate limit check antes de ejecución.
  - `backends_limits_put_handler`, `backends_limits_get_handler`: 2 handlers.
  - +1 ruta.
- `axon-rs/tests/integration.rs` — 3 tests nuevos (621 total):
  - `backend_rate_limit_fields_serde` — serialización, defaults (0=unlimited).
  - `backend_rate_limit_check_logic` — RPM/TPM at limit → blocked, unlimited → never blocked.
  - `backend_rate_limit_window_reset` — 60s window reset, within window → no reset.

**Verificación:**
- `cargo test`: 621 passed, 0 failed. **✓ All green.**
- `cargo build --release`: limpio (warnings only). **✓**
- CHECK: 5/5

---

**Handoff F6:**
- **A:** AxonStore persistence — wire `axonstore` primitive to durable storage backend.
- **B:** End-to-end smoke test infrastructure — test harness for live backend validation.
- **C:** Backend cost budget — per-backend spending limit with alert and auto-disable on breach.
- **D:** Phase F closeout — feature inventory, backend stack audit, production readiness review.
- **E:** Backend usage dashboard — aggregate view of all backends: calls, cost, limits, circuit state.

### Sesión F6: Phase F Comprehensive Closeout — production readiness review

**Alcance:** Full Phase F exit review. Audited 192 routes + 7 MCP methods, 132 public structs, 61 modules (48,999 lines), 621 tests (20,258 lines). Key deliverable: 10-stage `server_execute_full()` pipeline wired to all 16+ handlers. Backend registry expanded to 22 fields per entry. 4 optimizer strategies. RPM/TPM rate limiting. Created `docs/phase_f_exit_review.md`.
**Evidencia:** 621 tests pass. Release build limpio. Exit review document complete.
**CHECK: 5/5**

---

## Phase F: COMPLETE

**Sessions:** F1–F6 (6 sessions)
**Final test count:** 621
**Final source:** 48,999 lines across 61 modules
**Exit review:** `docs/phase_f_exit_review.md`

**Phase G candidates:**
1. AxonStore persistence — wire `axonstore` primitive to durable storage (file/SQLite)
2. End-to-end testing — test harness for live backend validation with cost caps
3. Language evolution — new AXON primitives, pattern matching, modules
4. Client SDKs — TypeScript/Python MCP clients for ℰMCP
5. Horizontal scaling — multi-instance coordination, shared state
