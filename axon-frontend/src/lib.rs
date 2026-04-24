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

pub mod tokens;
pub mod lexer;
pub mod ast;
pub mod parser;
pub mod epistemic;
pub mod type_checker;
pub mod ir_nodes;
pub mod ir_generator;
pub mod checker;

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
