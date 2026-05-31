//! §Fase 51.b — the PCC checker's independent effect specification.
//!
//! Proof-Carrying Code requires the consumer's checker to embed the
//! PROPERTY SPECIFICATION it verifies — it cannot delegate to the
//! producer's (compiler's) internal logic, or it would not be
//! independent (D51.2). This module is the checker's own statement of
//! "what a well-formed effect row is": the closed base-effect catalog
//! + the qualifier discipline.
//!
//! **Source of truth + drift:** this catalog mirrors
//! `axon_frontend::type_checker::VALID_EFFECTS` (private const) +
//! the §λ-L-E Fase 11.a qualifier rules. axon-frontend's catalog is
//! the canonical compiler-side spec; this is the checker-side spec.
//! They MUST agree. §51.f (which exposes `VALID_EFFECTS` as `pub` for
//! the `axon pcc verify` CLI) adds the cross-crate drift gate asserting
//! equality. Until then the equality is maintained by review + the
//! `EFFECT_BASES` doc-comment pin. The stream-qualifier catalog
//! ([`crate::stream_effect::BACKPRESSURE_CATALOG`]) IS public and is
//! referenced directly (no duplication needed there).

/// The closed catalog of valid base effects. Mirror of
/// `axon_frontend::type_checker::VALID_EFFECTS` (v2.4.0). A tool's
/// effect-row entry `base` or `base:qualifier` is well-formed only if
/// `base` is in this set.
pub const EFFECT_BASES: &[&str] = &[
    "io", "network", "pure", "random", "storage", "stream", "trust",
    "sensitive", "legal", "ots",
];

/// Effects that REQUIRE a `:qualifier` to be sound. `stream` needs a
/// backpressure policy (else the runtime cannot enforce backpressure);
/// `trust` needs a proof kind (else the trust claim is unverifiable).
/// A bare `stream` / `trust` is an unsound effect declaration.
pub const QUALIFIER_REQUIRED_BASES: &[&str] = &["stream", "trust"];

/// Split an effect-row entry into `(base, Option<qualifier>)`.
/// `"network"` → `("network", None)`; `"stream:drop_oldest"` →
/// `("stream", Some("drop_oldest"))`. Total.
pub fn split_effect(entry: &str) -> (&str, Option<&str>) {
    match entry.split_once(':') {
        Some((b, q)) => (b, Some(q)),
        None => (entry, None),
    }
}

/// Whether `base` is in the closed catalog.
pub fn is_known_base(base: &str) -> bool {
    EFFECT_BASES.contains(&base)
}

/// Whether `base` requires a qualifier to be sound.
pub fn requires_qualifier(base: &str) -> bool {
    QUALIFIER_REQUIRED_BASES.contains(&base)
}

/// Whether a `stream:<q>` qualifier is a valid backpressure policy.
/// Delegates to the PUBLIC `BACKPRESSURE_CATALOG` (no duplication).
pub fn is_valid_stream_qualifier(qualifier: &str) -> bool {
    crate::stream_effect::BACKPRESSURE_CATALOG.contains(&qualifier)
}
