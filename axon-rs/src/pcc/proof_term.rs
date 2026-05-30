//! §Fase 51.a — Proof-Carrying Code: the portable proof object.
//!
//! A [`ProofTerm`] is the serializable artifact a producer (the axon
//! compiler) emits alongside compiled code, certifying that a declared
//! property holds. A consumer runs the INDEPENDENT checker
//! ([`crate::pcc::checker`]) to verify it — WITHOUT trusting the
//! producer (D51.2). The term travels as JSON, the same delivery
//! surface as the SBOM / in-toto statements in [`crate::esk::attestation`],
//! but unlike those it is a *proof* the consumer re-checks, not an
//! attestation the consumer trusts.
//!
//! ## D51.1 — representation
//!
//! - [`PropertyClass`] — closed enum of property kinds. §51.a ships
//!   exactly [`PropertyClass::ComplianceCoverage`]; §51.b-e extend it.
//! - `artifact_digest` — SHA-256 hex of the canonical IR JSON the proof
//!   is ABOUT. Binds the proof to a specific artifact: a proof for
//!   program A cannot be replayed against program B (the checker
//!   recomputes the digest and rejects a mismatch).
//! - [`Witness`] — the property-specific derivation the checker
//!   re-verifies against the artifact.
//! - `axon_version` — producer version. Diagnostic only: the checker
//!   does NOT trust it (it re-derives the property regardless).

use serde::{Deserialize, Serialize};

/// The closed catalog of properties a [`ProofTerm`] can certify.
///
/// §Fase 51.a ships [`Self::ComplianceCoverage`]. The §51.b-e classes
/// (`EffectRowSoundness`, `CapabilityIsolation`, `ResourceBounds`,
/// `ShieldHaltGuarantee`) land as the proof-term language generalizes
/// (D51.4 — "universal" is the architecture, shipped one class at a
/// time). Adding a variant here requires a matching witness variant +
/// checker arm — the §51.a drift gate pins this lockstep.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PropertyClass {
    /// Every regulatory class an apx/axonendpoint declares in
    /// `compliance:` is (a) a known class in the closed
    /// [`crate::esk::compliance`] registry and (b) backed by a present,
    /// resolvable shield (`shield_ref` non-empty AND that shield exists
    /// in the program IR). Catches phantom compliance classes (a
    /// typo'd `HIPPA`) and compliance-claimed-without-enforcement
    /// (declaring GDPR with no attached shield).
    ComplianceCoverage,
}

impl PropertyClass {
    /// Stable wire slug for the property class.
    pub fn slug(&self) -> &'static str {
        match self {
            PropertyClass::ComplianceCoverage => "compliance_coverage",
        }
    }
}

/// §51.a — witness for [`PropertyClass::ComplianceCoverage`].
///
/// The derivation the producer recorded. The checker RE-DERIVES every
/// field from the artifact and rejects the proof if the witness
/// disagrees (D51.2 — a forged witness is caught because the checker
/// recomputes, it does not believe the claim).
///
/// The property certified: the shield attached to a compliance-bearing
/// apx **actually covers** every regulatory class the apx declares —
/// `covers(provided, required) == ∅` (the existing
/// [`crate::esk::compliance::covers`] predicate), with no phantom
/// classes and a present, resolvable shield.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComplianceCoverageWitness {
    /// The apx / axonendpoint this proof is about.
    pub endpoint_name: String,
    /// The regulatory classes the endpoint declared, sorted + deduped
    /// (canonical so the checker's re-derivation compares equal).
    pub required_classes: Vec<String>,
    /// The endpoint's `shield_ref` (empty string = no shield declared).
    pub shield_ref: String,
    /// Whether `shield_ref` is non-empty AND resolves to a shield
    /// present in the program IR.
    pub shield_present: bool,
    /// The regulatory classes the resolved shield PROVIDES (its
    /// `compliance:` set), sorted + deduped. Empty when no shield
    /// resolves.
    pub provided_classes: Vec<String>,
    /// The subset of `required_classes` that are NOT in the closed
    /// regulatory registry (phantom compliance claims). Empty for a
    /// verifying proof.
    pub unknown_classes: Vec<String>,
    /// The subset of `required_classes` the shield does NOT provide
    /// (`required \ provided` — the coverage gap), sorted. Empty for a
    /// verifying proof.
    pub uncovered_classes: Vec<String>,
}

/// The property-specific witness. Tagged so the JSON is self-describing
/// + a future class adds a variant without ambiguity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Witness {
    ComplianceCoverage(ComplianceCoverageWitness),
}

/// The portable proof object (D51.1). Serializes to JSON; travels with
/// the artifact; the independent checker verifies it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofTerm {
    /// The property class this term certifies.
    pub property: PropertyClass,
    /// SHA-256 hex of the canonical IR JSON the proof is about (binds
    /// the proof to a specific artifact).
    pub artifact_digest: String,
    /// The derivation the checker re-verifies.
    pub witness: Witness,
    /// Producer version (diagnostic; NOT trusted by the checker).
    pub axon_version: String,
}
