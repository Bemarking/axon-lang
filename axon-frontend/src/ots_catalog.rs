//! §Fase 11.e — OTS (Ontological Tool Synthesis) compile-time slug catalogs.
//!
//! These constants are consumed by `type_checker` to validate that
//! `ots:transform:*` and `ots:backend:*` effect slugs carry only
//! qualifiers from the closed catalog. The runtime side of OTS —
//! pipeline execution, transformer registry, native transcoders,
//! ffmpeg subprocess fallback — lives in the `axon` runtime crate
//! at `axon_rs::ots` and re-exports these constants for backward
//! compatibility.
//!
//! Keeping the catalog here (not in the runtime) means any tool that
//! analyses AXON source (LSP, linters, analyzers) can validate OTS
//! usage without linking the full runtime.

/// Effect slug `ots:transform:<from>:<to>` declares a tool as
/// performing a kind conversion. The checker verifies a path exists.
pub const OTS_TRANSFORM_EFFECT_SLUG: &str = "ots:transform";

/// Effect slug `ots:backend:<kind>` declares HOW the conversion
/// happens. Closed qualifier set — new backends require a patch.
pub const OTS_BACKEND_EFFECT_SLUG: &str = "ots:backend";

/// Catalogue of valid `ots:backend:<qualifier>` qualifiers.
pub const OTS_BACKEND_CATALOG: &[&str] = &["native", "ffmpeg"];
