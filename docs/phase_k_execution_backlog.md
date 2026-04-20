# Backlog de Ejecucion — Fase K

Este archivo lista las sesiones planeadas y ejecutadas para la Fase K (Launch — Production Hardening) del programa AXON.

## Objetivo de Fase

Cerrar las 3 brechas criticas de produccion para que Axon v1.0.0 pueda sostener adoptores empresariales de produccion sin compromisos. Politica: cero "por ahora", cero "lo minimo" — todo production-complete.

**Las 3 brechas:**
1. Persistencia (PostgreSQL full) — los datos no pueden perderse al reiniciar
2. Observabilidad (logging completo) — depurar a las 3 AM debe ser posible
3. Resiliencia LLM (retry + circuit breaker + fallback) — nada tumba un flujo

## Estado heredado de Fase J

| Metrica | Valor |
|---------|-------|
| Modulos fuente | 61 archivos `.rs` |
| Lineas fuente | 58,389 |
| Tests de integracion | 738 |
| Rutas API (HTTP) | 282 |
| Primitivas cognitivas | 47/47 = 100% |

## Sesiones

### K1 — Observabilidad

**Scope:** Logging estructurado production-grade para AxonServer y backends LLM.

**Delivered:**

1. **`src/logging.rs`** — Subscriber `tracing` con:
   - JSON o pretty output a stdout
   - Rotacion diaria de archivos via `tracing-appender`
   - Nivel configurable via `AXON_LOG` env o `--log-level` CLI
   - Filtro via `EnvFilter`

2. **`src/request_tracing.rs`** — Middleware Tower:
   - UUID `request_id` por request (via `uuid` crate)
   - Span con method, path, client_ip
   - Status + latency_ms al completar
   - Header `x-request-id` en response

3. **Instrumentacion `backend.rs`**:
   - 4 funciones call/call_stream/call_multi/call_multi_stream instrumentadas
   - Cada llamada LLM registra: backend, model, latency_ms, tokens_in, tokens_out, stop_reason
   - Errores HTTP loggeados con url + status

4. **Instrumentacion `axon_server.rs`**:
   - `run_serve()` inicializa logging como primera accion
   - Todos los `eprintln!` reemplazados con `tracing::info!/warn!/error!`
   - CLI args nuevos: `--log-format`, `--log-file`, `--database-url`

**Dependencies added:** tracing 0.1, tracing-subscriber 0.3, tracing-appender 0.2, uuid 1

**Tests:** 2 unit tests (LogFormat) + 1 integration test (cli_serve verifica structured logs)

---

### K2 — Resiliencia

**Scope:** LLM call hardening con retry, circuit breaker, timeout, y fallback.

**Delivered:**

1. **`src/backend_error.rs`** — `BackendErrorKind` enum:
   - 10 variantes: Timeout, RateLimit, ServerError, AuthError, NetworkError, StreamDropped, InvalidResponse, ProviderUnavailable, CircuitOpen, Unknown
   - `is_retryable()` para decisiones de retry
   - `from_status()` para clasificar HTTP status codes
   - `from_reqwest_error()` para clasificar errores de red

2. **`src/retry_policy.rs`** — `RetryPolicy`:
   - Backoff exponencial: base_delay=500ms, multiplier=2.0, max_delay=30s
   - Jitter deterministico para evitar thundering herd
   - Respeta `Retry-After` de providers (rate limit hints)
   - `should_retry()` valida attempts + error kind

3. **`src/circuit_breaker.rs`** — `CircuitBreaker`:
   - State machine: Closed → Open (5 failures) → HalfOpen (30s cooldown) → Closed (2 successes)
   - Per-provider isolation
   - Logging de transiciones via tracing
   - Reset manual para admin endpoints

4. **`src/resilient_backend.rs`** — `ResilientBackend`:
   - Composicion: circuit_breaker → retry_with_backoff → actual_call → fallback_chain
   - Cadenas de fallback configurables (ej: anthropic → openrouter → ollama)
   - Clasificacion de errores via message parsing
   - All 7 providers inicializados con circuit breakers

**Tests:** 33 unit tests (5 error, 8 retry, 10 circuit breaker, 10 resilient backend)

---

### K3 — Persistencia: Schema y Trait

**Scope:** Abstraccion de storage y schema PostgreSQL.

**Delivered:**

1. **`src/storage.rs`** — `StorageBackend` trait:
   - 12 dominios: traces, sessions, daemons, audit, axon_stores, dataspaces, hibernations, events, cache, costs, schedules, health
   - 33 metodos async
   - `InMemoryBackend` (no-op) para desarrollo/testing
   - `StorageDispatcher` enum para dispatch concreto sin `dyn` (evita dyn-compatibility)
   - `StorageError` enum: ConnectionError, QueryError, SerializationError, NotFound
   - 11 row types portables (TraceRow, SessionRow, DaemonRow, etc.)

2. **`src/storage_postgres.rs`** — `PostgresBackend`:
   - Implementacion completa de 33 metodos via sqlx runtime queries
   - UPSERT (ON CONFLICT DO UPDATE) para saves idempotentes
   - JSONB para estructuras anidadas
   - No requiere DB al compilar (runtime queries, no macros)

3. **`src/db_pool.rs`** — Pool management:
   - PgPoolOptions: max=10, min=2, acquire_timeout=5s, idle_timeout=300s
   - Health check via SELECT 1
   - URL masking para logging seguro

4. **`src/migrations.rs`** — Migration runner embebido

5. **SQL migrations:**
   - `001_initial_schema.sql`: 12 tablas (traces, sessions, daemons, audit_log, axon_stores, dataspaces, hibernations, event_history, execution_cache, cost_tracking, schedules, backend_registry)
   - `002_indexes.sql`: 15 indices para performance

**Dependencies added:** sqlx 0.8 (postgres, json, chrono, migrate), chrono 0.4

**Tests:** 14 unit tests (InMemoryBackend contract + error display + db_pool masking)

---

### K4 — Persistencia: Integracion Server

**Scope:** Integrar storage y resilient backend en ServerState.

**Delivered:**

1. **`ServerState` ampliado:**
   - `storage: Arc<StorageDispatcher>` — backend persistente
   - `resilient_backend: Arc<ResilientBackend>` — backend LLM resiliente

2. **`ServerConfig` ampliado:**
   - `log_format: String` — "json" o "pretty"
   - `log_file: Option<String>` — directorio para logs rotativos
   - `database_url: Option<String>` — URL PostgreSQL

3. **Inicializacion asincrona en `run_serve()`:**
   - Si DATABASE_URL esta configurado: crea pool, ejecuta migraciones, reemplaza storage
   - Si falla: log error y continua con InMemoryBackend (fallback graceful)
   - Todo dentro del bloque `rt.block_on(async { ... })`

4. **CLI args:**
   - `--log-format` (json/pretty)
   - `--log-file` (directorio)
   - `--database-url` (tambien lee `DATABASE_URL` env)

---

### K5 — Integration Testing y Hardening

**Scope:** Tests end-to-end para los 3 sistemas nuevos.

**Delivered (15 tests):**

1. `test_k5_log_format_variants` — validacion de formatos de logging
2. `test_k5_circuit_breaker_full_lifecycle` — Closed → Open → HalfOpen → Closed
3. `test_k5_circuit_breaker_half_open_failure_reopens` — HalfOpen failure → Open
4. `test_k5_retry_policy_backoff_escalation` — backoff 100→200→400→800ms
5. `test_k5_retry_policy_respects_rate_limit_hint` — Retry-After provider hint
6. `test_k5_error_classification_comprehensive` — 10+ status codes + retryable logic
7. `test_k5_resilient_backend_all_providers_initialized` — 7 providers en Closed
8. `test_k5_resilient_backend_circuit_reset` — reset manual
9. `test_k5_storage_dispatcher_in_memory` — save/load round-trip
10. `test_k5_hibernation_lifecycle_agent` — create → checkpoint → suspend → resume
11. `test_k5_server_config_new_fields` — log_format, log_file, database_url
12. `test_k5_server_state_has_storage_and_resilient_backend` — fields present in state
13. `test_k5_health_endpoint_with_tracing_middleware` — /v1/health funciona con tracing layer
14. `test_k5_db_url_masking` — password masking en URLs
15. `test_k5_storage_error_types` — all error variants format correctly

---

## Evidencia Final

- `cargo test` → **713 lib + 753 integration = 1,466 tests passed, 0 failed**
- `cargo build --release` → clean (warnings only)

| Metrica | Antes (J) | Despues (K) | Delta |
|---------|-----------|-------------|-------|
| Modulos fuente | 61 | 72 | +11 |
| Tests lib | 666 | 713 | +47 |
| Tests integracion | 738 | 753 | +15 |
| Tests total | 1,404 | 1,466 | +62 |
| Dependencies | 8 | 14 | +6 |
| SQL tables | 0 | 12 | +12 |
| SQL indexes | 0 | 15 | +15 |

## Archivos Nuevos (Phase K)

| Archivo | Proposito |
|---------|-----------|
| `src/logging.rs` | Structured logging (tracing subscriber) |
| `src/request_tracing.rs` | Tower middleware (request_id + spans) |
| `src/backend_error.rs` | Error classification (retryable/non-retryable) |
| `src/retry_policy.rs` | Exponential backoff with jitter |
| `src/circuit_breaker.rs` | Per-provider state machine |
| `src/resilient_backend.rs` | Composition: retry + circuit_breaker + fallback |
| `src/storage.rs` | StorageBackend trait + InMemoryBackend + StorageDispatcher |
| `src/storage_postgres.rs` | PostgreSQL implementation (33 methods) |
| `src/db_pool.rs` | Connection pool management |
| `src/migrations.rs` | Embedded migration runner |
| `migrations/001_initial_schema.sql` | 12 tables |
| `migrations/002_indexes.sql` | 15 indexes |
