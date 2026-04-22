//! AXON compiler library — exposes lexer, parser, type checker, IR generator.
//!
//! Used by the `axon` binary and by integration tests.

pub mod anchor_checker;
pub mod api_keys;
pub mod ast;
pub mod audit_trail;
pub mod auth_middleware;
pub mod axon_server;
pub mod backend;
pub mod backend_error;
pub mod checker;
pub mod circuit_breaker;
pub mod compiler;
pub mod config_persistence;
pub mod conversation;
pub mod cors;
pub mod cost_estimator;
pub mod db_pool;
pub mod deployer;
pub mod emcp;
pub mod epistemic;
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
pub mod ir_generator;
pub mod ir_nodes;
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
pub mod lexer;
pub mod parser;
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
// §λ-L-E Fase 11.a — Temporal Algebraic Effects + Trust Types.
// `refinement` defines the closed Trust Catalog (Trusted<T> /
// Untrusted<T>); `stream_effect` defines the closed backpressure
// policy catalog (Stream<T>); `trust_verifiers` holds the runtime
// implementations that the compiler recognises; `stream_runtime`
// is the Stream<T> channel with policy dispatch.
pub mod refinement;
pub mod stream_effect;
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
// §λ-L-E Fase 11.c — Deterministic Replay + Legal-Basis Typed
// Effects. `legal_basis` is the closed catalogue of regulatory
// authorisations (GDPR/CCPA/SOX/HIPAA/GLBA/PCI-DSS). `replay_token`
// hosts ReplayToken canonical hashing + pluggable ReplayLog +
// ReplayExecutor for re-running from any token. Distinct from the
// existing `replay` module, which reconstructs trace files for
// debugging — `replay_token` is for regulatory-grade audit replay.
pub mod legal_basis;
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
pub mod tokens;
pub mod tool_executor;
pub mod tool_registry;
pub mod tool_validator;
pub mod trace_export;
pub mod trace_store;
pub mod trace_stats;
pub mod tracer;
pub mod type_checker;
pub mod version_diff;
pub mod webhook_delivery;
pub mod webhooks;
