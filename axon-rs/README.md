# AXON Rust Native Runtime (v1.0.0)

The compiled Rust implementation of the AXON cognitive language with **282 HTTP routes**, **47/47 cognitive primitives**, and production-grade systems:

- **Observability**: Structured JSON logging with request tracing (Phase K)
- **Resilience**: Circuit breakers, exponential backoff, fallback chains (Phase K)
- **Persistence**: PostgreSQL backend with 12 domain tables and embedded migrations (Phase K)

## Directory Structure

```
axon-rs/
├── Cargo.toml              # Rust dependencies & metadata
├── src/
│   ├── main.rs             # Server entry point (AxonServer)
│   ├── lib.rs              # Public module exports (11 Phase K modules)
│   ├── axon_server.rs      # HTTP server & route handlers (282 routes)
│   ├── backend.rs          # LLM backend calls (7 providers)
│   ├── compiler/           # IR compilation to backend prompts
│   ├── executor/           # Flow execution engine
│   ├── logging.rs          # Tracing subscriber configuration (K1)
│   ├── request_tracing.rs  # Tower middleware for request ID correlation (K1)
│   ├── backend_error.rs    # Error classification & retry logic (K2)
│   ├── retry_policy.rs     # Exponential backoff with jitter (K2)
│   ├── circuit_breaker.rs  # Per-provider state machine (K2)
│   ├── resilient_backend.rs # Composition layer (K2)
│   ├── storage.rs          # StorageBackend trait & dispatcher (K3)
│   ├── storage_postgres.rs # PostgreSQL implementation (K4)
│   ├── db_pool.rs          # Connection pool management (K4)
│   └── migrations.rs       # Embedded migration runner (K4)
├── migrations/
│   ├── 001_initial_schema.sql     # 12 tables (traces, sessions, daemons, etc.)
│   └── 002_indexes.sql            # 15 performance indexes
├── tests/
│   └── integration.rs      # End-to-end tests (753 total)
└── README.md               # This file
```

## Build

### Release Build

```bash
cd axon-rs
cargo build --release
```

Binary: `target/release/axon` (or `axon.exe` on Windows)

### Development Build

```bash
cargo build
```

Binary: `target/debug/axon`

## Run

### In-Memory Storage (Development)

```bash
cargo run --release -- --port 3000
```

Logs to stdout, no persistence.

### With PostgreSQL (Production)

```bash
# Create database
createdb axon

# Run with persistence & structured logging
DATABASE_URL="postgresql://user:pass@localhost/axon" \
cargo run --release -- \
  --port 3000 \
  --log-format json \
  --log-file ./logs \
  --database-url "$DATABASE_URL"
```

Options:
- `--port` — HTTP server port (default: 3000)
- `--log-format` — `json` or `pretty` (default: pretty)
- `--log-file` — Directory for daily-rotated logs
- `--database-url` — PostgreSQL connection string; if unset, uses in-memory storage

## Quick Test

```bash
# Health check
curl http://localhost:3000/v1/health

# Deploy a flow
curl -X POST http://localhost:3000/v1/deploy \
  -H "Content-Type: application/json" \
  -d '{"source": "flow test { step reason { prompt: \"hello\" } }", "backend": "stub"}'

# Execute
curl -X POST http://localhost:3000/v1/execute/test
```

## Tests

```bash
# Full test suite (1,466 tests)
cargo test

# Specific test groups
cargo test test_k5_          # Phase K tests only (15 tests)
cargo test --lib            # Unit tests (713 tests)
cargo test --test integration # Integration tests (753 tests)

# With output
cargo test -- --nocapture
```

All tests pass with zero failures. Tests work with in-memory storage (no DB required).

## Phase K Features

### K1: Observability
- **tracing subscriber**: JSON or pretty formatting to stdout
- **Request tracing**: UUID `request_id` per request, propagated in `x-request-id` header
- **Log rotation**: Daily files via `tracing-appender`
- **Configurable levels**: Via `AXON_LOG` env or `--log-level` CLI

### K2: Resilience
- **Exponential backoff**: 500ms base, 2.0x multiplier, 30s max, deterministic jitter
- **Circuit breaker**: Per-provider state machine (5 failures → Open, 30s cooldown, 2 successes → Closed)
- **Fallback chains**: e.g., `anthropic → openrouter → ollama`
- **Error classification**: Determines if errors are retryable or terminal
- **Supports 7 backends**: Anthropic, OpenAI, Gemini, Kimi, GLM, OpenRouter, Ollama

### K3-K4: Persistence
- **PostgreSQL backend**: Full ACID semantics with embedded migrations
- **12 domain tables**: traces, sessions, daemons, audit_log, axon_stores, dataspaces, hibernations, event_history, execution_cache, cost_tracking, schedules, backend_registry
- **15 indexes**: Query optimization
- **UPSERT semantics**: Idempotent writes
- **JSONB storage**: Nested structures without extra joins
- **In-memory fallback**: Graceful degradation when DB unavailable

## Troubleshooting

### Database connection fails
Without `DATABASE_URL` set, the server automatically falls back to in-memory storage. Check logs for details:

```bash
RUST_LOG=debug cargo run --release -- --port 3000
```

### Compilation error: "could not compile"
Ensure you have Rust 1.70+:

```bash
rustup update
cargo clean
cargo build --release
```

### Performance: slow requests
Check database pool status via `/v1/health`. If pool is exhausted, increase `max_connections` in db_pool.rs or reduce concurrent requests.

## Dependencies (Phase K)

- `tokio` — async runtime
- `axum` — HTTP framework
- `sqlx` — runtime SQL queries (no compile-time macros needed)
- `tracing`, `tracing-subscriber`, `tracing-appender` — structured logging
- `uuid` — request IDs
- `chrono` — timestamps
- And 30+ others (see Cargo.toml)

## For Complete Documentation

See the main [`README.md`](../README.md) at the project root for:
- Language specification
- Paradigm shifts (epistemic directives, forge, agent, shield, etc.)
- Design principles and comparison
- Full roadmap (Phases 0–K)
