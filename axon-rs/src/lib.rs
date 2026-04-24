//! AXON runtime library — exposes the full AXON runtime: compiler
//! frontend (re-exported from `axon-frontend`), handlers, runtime
//! primitives, ESK, HTTP/WebSocket servers, persistence, OTS pipelines.
//!
//! Used by the `axon` binary and by integration tests.
//!
//! # Frontend vs runtime
//!
//! §Fase 12.a — the compiler frontend (lexer, parser, AST, type checker,
//! IR generator, top-level checker, and the closed catalogs used by the
//! type checker) lives in the sibling crate `axon-frontend`, which has
//! zero runtime dependencies. This crate re-exports those modules
//! transparently so every existing caller (76 call sites across 26
//! files) keeps compiling without changes. The crate `axon-lsp`
//! consumes `axon-frontend` directly, skipping the runtime surface.

// ── §Fase 12.a — frontend re-exports (transparent to callers) ───────
pub use axon_frontend::{
    ast,
    checker,
    epistemic,
    ir_generator,
    ir_nodes,
    legal_basis,
    lexer,
    parser,
    refinement,
    stream_effect,
    tokens,
    type_checker,
};

// `ots_catalog` is the compile-time slug catalog; the runtime `ots`
// module (below) re-exports these constants for backward compatibility.

// ── Runtime modules (stay in this crate) ────────────────────────────

pub mod anchor_checker;
pub mod api_keys;
pub mod audit_trail;
pub mod auth_middleware;
pub mod axon_server;
pub mod backend;
pub mod backend_error;
pub mod circuit_breaker;
pub mod compiler;
pub mod config_persistence;
pub mod conversation;
pub mod cors;
pub mod cost_estimator;
pub mod db_pool;
pub mod deployer;
pub mod emcp;
pub mod event_bus;
/// §λ-L-E Fase 2 — Handler layer (Free Monad + CPS). Port of `axon/runtime/handlers/`.
pub mod handlers;
/// §λ-L-E Fase 3 + 5 runtime primitives. Port of `axon/runtime/` (lease kernel,
/// reconcile loop, ensemble aggregator, immune kernels).
pub mod runtime;
/// §ESK Fase 6 — Epistemic Security Kernel. Port of `axon/runtime/esk/`.
pub mod esk;
/// CLI handlers for the ESK audit commands (dossier, sbom, audit, evidence-package).
pub mod audit_cli;
pub mod flow_inspect;
pub mod flow_version;
pub mod exec_context;
pub mod graceful_shutdown;
pub mod graph_export;
pub mod health_check;
pub mod hooks;
pub mod http_tool;
pub mod inspect;
pub mod lambda_data;
pub mod logging;
pub mod migrations;
pub mod output;
pub mod parallel;
pub mod plan_diff;
pub mod plan_export;
pub mod rate_limiter;
pub mod request_log;
pub mod request_middleware;
pub mod repl;
pub mod replay;
pub mod request_tracing;
pub mod resilient_backend;
pub mod retry_policy;
pub mod runner;
pub mod server_config;
pub mod server_metrics;
pub mod session_scope;
pub mod session_store;
pub mod step_deps;
pub mod storage;
pub mod storage_postgres;
pub mod stdlib;
pub mod tenant;
pub mod tenant_secrets;
// §Fase 10.e — JWT signature verification + JWKS client. Used by
// tenant::tenant_extractor_middleware when AXON_JWT_JWKS_URL is set.
pub mod jwt_verifier;
// §λ-L-E Fase 11.a runtime — `trust_verifiers` holds the runtime
// implementations that the compiler recognises; `stream_runtime` is
// the Stream<T> channel with policy dispatch. The compile-time
// `refinement` and `stream_effect` catalogs live in `axon-frontend`.
pub mod trust_verifiers;
pub mod stream_runtime;
// §λ-L-E Fase 11.b — Zero-Copy Multimodal Buffers.
// `buffer` defines ZeroCopyBuffer (Arc<[u8]>-backed) + BufferKind
// (open registry) + BufferPool (slab allocator with per-tenant
// soft-limit accounting). `ingest` hosts the network deposit paths
// (multipart/form-data streaming parser, WebSocket binary-frame
// accumulator) that populate buffers without intermediate copies.
pub mod buffer;
pub mod ingest;
// §λ-L-E Fase 11.c runtime — `replay_token` hosts ReplayToken canonical
// hashing + pluggable ReplayLog + ReplayExecutor for re-running from
// any token. The compile-time `legal_basis` catalog lives in
// `axon-frontend`.
pub mod replay_token;
// §λ-L-E Fase 11.d — Stateful PEM over WebSocket. `pem::state`
// defines CognitiveState with Q32.32 fixed-point float encoding
// so density-matrix round-trips are bit-identical across reconnects.
// `pem::continuity_token` is an HMAC-signed handshake that proves
// a reconnecting client is the original party. `pem::backend`
// exposes the PersistenceBackend async trait + in-memory impl;
// production uses axon_enterprise::cognitive_states (Postgres +
// envelope encryption).
pub mod pem;
// §λ-L-E Fase 11.e — Ontological Tool Synthesis binary pipelines.
// `ots::pipeline` hosts Transformer trait + TransformerRegistry +
// Dijkstra-based path search. `ots::native` seeds μ-law ↔ PCM16
// + resample (8k/16k/48k ladder). `ots::subprocess::ffmpeg` is
// the subprocess fallback with warm-pool + availability detection.
// The compile-time slug catalog lives in `axon-frontend::ots_catalog`.
pub mod ots;
pub mod tool_executor;
pub mod tool_registry;
pub mod tool_validator;
pub mod trace_export;
pub mod trace_store;
pub mod trace_stats;
pub mod tracer;
pub mod version_diff;
pub mod webhook_delivery;
pub mod webhooks;
