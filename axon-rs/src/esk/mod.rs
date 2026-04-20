//! AXON Runtime — Epistemic Security Kernel (§ESK Fase 6).
//!
//! Direct port of `axon/runtime/esk/`. The ESK sits at the sealed boundary
//! of the runtime and gives every artefact a cryptographic, regulatory,
//! and epistemic identity that external audits (SOC 2 / ISO 27001 / FIPS /
//! CC EAL 4+) can verify without access to Axon internals.
//!
//! Sub-modules:
//!   * `compliance` — canonical κ registry (§Fase 6.1).
//!   * `provenance` — HMAC / Merkle-chained signed envelopes (§Fase 6.2).
//!   * `attestation` — SBOM + ComplianceDossier + in-toto Statement (§Fase 6.6).
//!   * `audit_engine` — gap analysis, risk register, evidence packager.

pub mod attestation;
pub mod audit_engine;
pub mod compliance;
pub mod provenance;
