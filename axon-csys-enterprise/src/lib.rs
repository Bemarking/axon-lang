//! axon-csys-enterprise — companion to OSS [`axon_csys`] adding
//! enterprise-only kernels (FIPS-validated crypto, tamper-evident
//! audit log mmap, byte-deterministic evidence packager, vertical
//! BPE tokenizer templates).
//!
//! § Fase 27 — Silicon + Cognition Enterprise (sesión 1). The
//! kernel infrastructure shipped in OSS axon-csys 0.1.x (BPE
//! engine, hash-table, FNV-1a, base64url, mmap helper, FIPS-friendly
//! SHA-256/HMAC) is reused; this crate adds the audit-posture
//! differentiators that matter for HIPAA / SOC2 / CC-EAL4+ / GDPR /
//! PCI DSS compliance.
//!
//! # License
//!
//! Business Source License v1.1 with 4-year delay → MIT (per
//! D2 ratified 2026-05-09 — HashiCorp / Sentry / MariaDB pattern).
//! Source-available; commercial use restricted during the active
//! lifecycle; auto-converts to MIT on the Change Date (2030-05-09
//! for v0.1.x). NOT publishable to crates.io — shipped to a
//! private/internal Cargo registry per the 27.k release plan.
//!
//! # Layout
//!
//! - `c-src/probe/`    — build-infra probe (27.b)  ✅ shipped
//! - `c-src/crypto/`   — FIPS-validated crypto link (27.c) — pending
//! - `c-src/audit/`    — audit log mmap + evidence packager (27.d, 27.f) — pending
//! - `c-src/tokens/`   — vertical BPE templates registration (27.e) — pending
//! - `c-src/shield/`   — PHI scrubber SIMD (27.g, optional) — pending
//!
//! # Default surface
//!
//! With no cargo feature enabled, this crate is a pass-through:
//! it re-exports the OSS [`axon_csys`] API surface verbatim. Adopters
//! running unlicensed deployments get the OSS pure-C path
//! transparently; the enterprise differentiators activate when the
//! adopter opts into a feature flag (`fips-boringssl`,
//! `fips-openssl`, `phi-scrubber-c`, `public-anchor`).
//!
//! # Wire-format byte-identity (D7 ratified)
//!
//! The FIPS-validated path produces byte-identical output to the
//! OSS pure-C path on every NIST CAVS reference vector + 100
//! deterministic-seeded fuzz iterations (drift gate runs in CI). A
//! ContinuityToken issued by an OSS deployment verifies on a
//! FIPS-validated deployment and vice versa. The differentiator is
//! the formal CMVP certification number embedded in the adopter's
//! compliance documentation, not the bytes on the wire.

#![doc(html_no_source)]

pub mod audit_log;
pub mod crypto;
pub mod probe;

// ──────────────────────────────────────────────────────────────────────
// Top-level convenience re-exports — the [`crypto`] module is the
// source of truth for which backend computes the bytes (FIPS-validated
// vs OSS pure-C); these aliases give adopters the same import shape
// they would use against OSS axon-csys directly.
//
// Crypto primitives are re-exported THROUGH the crypto module (so the
// feature-gated routing applies). Non-crypto primitives are re-exported
// directly from OSS axon-csys (no FIPS surface meaningful).
// ──────────────────────────────────────────────────────────────────────

pub use crate::crypto::{
    b64url_decode, b64url_encode, ct_eq, hex_decode, hex_encode, hmac_sha256, sha256,
    ContinuityWire, ContinuityWireError, HmacSha256, Sha256, SHA256_BLOCK_SIZE, SHA256_DIGEST_SIZE,
};

pub use axon_csys::{
    cl100k_base, count_tokens, estimate, mulaw_decode, mulaw_encode, o200k_base,
    resample_linear_pcm16, resample_linear_pcm16_output_len, utf8_boundary_floor, utf8_count_chars,
    BpeError, BufferPool, BufferPoolSnapshot, CountKind, PoolClass, ResampleError, Slab,
    TokenCount, Tokenizer,
};

// ──────────────────────────────────────────────────────────────────────
// Compile-time guards for feature-flag mutual exclusivity.
//
// `build.rs` rejects the `fips-boringssl` + `fips-openssl` combination
// at build time. The static_assertion below is a belt-and-braces
// check that catches the case where someone bypasses the build script
// (e.g. via a custom workspace setup that skips build.rs probing).
// ──────────────────────────────────────────────────────────────────────

#[cfg(all(feature = "fips-boringssl", feature = "fips-openssl"))]
compile_error!(
    "axon-csys-enterprise: features `fips-boringssl` and `fips-openssl` \
     are mutually exclusive. Pick one (per D3 ratified 2026-05-09)."
);

// ──────────────────────────────────────────────────────────────────────
// Feature-detection surface for downstream code.
//
// `axon_csys_enterprise::active_fips_backend()` returns a stable
// enum the audit log can record alongside every cryptographic
// operation. Useful for forensic replay: an adopter rotating from
// BoringSSL-FIPS to OpenSSL-FIPS sees the change reflected in the
// per-event audit-log signature.
// ──────────────────────────────────────────────────────────────────────

/// Which crypto backend was selected at compile time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FipsBackend {
    /// No FIPS-validated link — using the OSS pure-C axon-csys
    /// path. Output is byte-identical to FIPS-validated paths but
    /// lacks the CMVP certificate.
    None,
    /// BoringSSL-FIPS module linked statically.
    BoringSsl,
    /// OpenSSL-FIPS provider linked statically.
    OpenSsl,
}

impl FipsBackend {
    /// Compile-time-resolved backend. The build script populates the
    /// matching `cfg!(...)` flag based on the active cargo feature.
    pub const fn current() -> Self {
        if cfg!(axon_csys_enterprise_fips_boringssl) {
            Self::BoringSsl
        } else if cfg!(axon_csys_enterprise_fips_openssl) {
            Self::OpenSsl
        } else {
            Self::None
        }
    }

    /// Stable string label for audit-log emission. The label is
    /// fixed across releases so historical events stay parseable.
    pub const fn label(self) -> &'static str {
        match self {
            Self::None => "axon-csys-oss-pure-c",
            Self::BoringSsl => "boringssl-fips",
            Self::OpenSsl => "openssl-fips",
        }
    }
}
