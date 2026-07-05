//! AXON compiler frontend.
//!
//! Pure frontend of the AXON language: lexer, parser, AST, epistemic
//! type primitives, type checker, IR generator, and the top-level
//! compile-time checker that glues them together.
//!
//! # Design contract
//!
//! This crate has **zero runtime dependencies**. The only allowed
//! external dep is `serde` (plus its proc-macro chain). Any addition
//! of a runtime dep (tokio, axum, sqlx, reqwest, aws-*, jsonwebtoken,
//! …) is rejected at CI time.
//!
//! # Consumers
//!
//! - `axon` crate (the AXON runtime in `../axon-rs/`) re-exports these
//!   modules so existing callers keep working.
//! - `axon-lsp` (Language Server, separate repo) consumes the frontend
//!   directly without dragging runtime deps.
//!
//! # Byte-identical parity
//!
//! Outputs must match the Python reference implementation
//! (`../axon/`) on the golden-file test corpus. Divergences are
//! release blockers.

pub mod ast;
pub mod checker;
pub mod cron;
pub mod epistemic;
pub mod ir_generator;
pub mod ir_nodes;
pub mod lexer;
pub mod parser;
pub mod smart_suggest;
pub mod store_column_proof;
pub mod store_introspect;
pub mod store_schema;
pub mod store_schema_manifest;
pub mod tokens;
pub mod type_checker;

// §Fase 11.a — compile-time catalogs used by the type checker.
// `refinement` declares the closed Trust<T> catalog; `stream_effect`
// declares the closed backpressure policy catalog. Both are pure
// enum-like definitions with `std::fmt` only — no runtime deps.
// The matching runtime implementations (`trust_verifiers`,
// `stream_runtime`) live in the `axon` runtime crate.
pub mod refinement;
pub mod stream_effect;

// §Fase 11.c — closed catalogue of regulatory authorisations
// (GDPR/CCPA/SOX/HIPAA/GLBA/PCI-DSS) used by the type checker to
// enforce `@legal_basis` annotations. Pure catalog, no runtime deps.
pub mod legal_basis;

// §Fase 11.e — OTS (Ontological Tool Synthesis) compile-time slug
// catalogs. Runtime pipeline execution lives in `axon::ots` and
// re-exports these for backward compatibility.
pub mod ots_catalog;

// §Fase 13.g — LSP-facing analysis primitives for typed channels.
// Pure AST helpers consumed by `axon-lsp` (sibling repo) to implement
// hover, completion, go-to-definition and find-references. Zero
// runtime deps — stays inside the Fase 12.c contract.
pub mod channel_analysis;

// §Fase 41.a — session types: the pure algebra of typed bidirectional
// dialogue (WebSocket as a cognitive primitive). The session-type
// grammar + the duality involution `(·)⊥` + regular-coinductive
// equality for `μ`-types + the connection law (`peer ≡ self⊥`).
// Grounded in Caires–Pfenning (session types = intuitionistic linear
// propositions). Pure — no runtime deps; the `socket` surface (41.b),
// credit-refined backpressure (41.c) and the typed-WS runtime (41.d,
// in the `axon` crate) build on this. See
// docs/paper_websocket_cognitive_primitive.md.
pub mod session;
// §Fase 41.h — multiparty session types (Honda–Yoshida–Carbone). A
// `GlobalType` declares an n-party protocol; projection `G⌐r` extracts
// each role's binary `SessionType` (the §41.a algebra). The safe-
// realizability gate is `project_all`: a `Result::Ok` is the structural
// certificate that independent per-role runtimes faithfully realise `G`.
pub mod multiparty;

// §Fase 6.a — the closed registry of every primitive AXON exposes as
// a named language construct. Single source of truth for the ℰMCP
// coverage gate + scaffold CLI + future LSP completions / docs-site
// generators. Pure const data, no runtime deps. See the module-level
// docs for the discipline (registry + corpus = atomic addition).
pub mod primitive_registry;
pub use primitive_registry::{
    by_category, coverage_summary, find as find_primitive, with_status, CoverageSummary,
    DocStatus, PrimitiveInfo, PRIMITIVE_REGISTRY,
};

// §Fase 80.f — the blessed upstream preset catalog (versioned, forkable,
// ordinary `.axon` source per D80.5) + the `from Preset@vN` expansion the
// parser runs before type-check. Pure const data + a pure AST pass.
pub mod upstream_presets;

// §Fase 80.g — `voice` macro-expansion to source text (the `axon desugar`
// payload). Pure AST pass run by the parser before preset expansion.
pub mod voice_desugar;

// §Fase 84 — Remote Hands: the pure, shared argv-template classifier + risk
// catalog used by BOTH the type-checker and the runtime dispatcher (D84.1).
pub mod technician;
