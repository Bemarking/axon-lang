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
    /// §51.b — every entry in a tool's `effects: <...>` row is
    /// well-formed: its base is in the closed effect catalog
    /// ([`crate::pcc::effects::EFFECT_BASES`]); `stream` / `trust`
    /// carry a qualifier (`stream`'s in the backpressure catalog); and
    /// `pure` is exclusive (a tool cannot be both `pure` and
    /// effectful). Catches phantom effects (typo'd `network`), bare
    /// `stream` without a backpressure policy, and pure/impure
    /// contradictions.
    EffectRowSoundness,
    /// §51.c — every capability gate an `axonstore` declares (its
    /// Pillar IV `capability` slug, §Fase 35.j) is a well-formed §32.g
    /// capability scope (matches the closed grammar
    /// `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`, via the OSS
    /// `axon_frontend::parser::is_valid_capability_slug`). A malformed
    /// gate is a Pillar IV defect: it can never match a properly-formed
    /// bearer capability, so the store is either locked out or — worse,
    /// if a consumer treats "unparseable gate" as "no gate" — silently
    /// bypassed.
    ///
    /// **Scope (honest):** this is the gate-integrity half. The
    /// containment half — an apx's reachable store gates ⊆ its declared
    /// `requires:` set — needs the endpoint `requires_capabilities`
    /// (AST / enterprise deploy metadata, NOT lowered to the frontend
    /// IR) + flow→store reachability, and is deferred to §51.x
    /// (enterprise PCC consumption, where `requires` lives).
    CapabilityIsolation,
}

impl PropertyClass {
    /// Stable wire slug for the property class.
    pub fn slug(&self) -> &'static str {
        match self {
            PropertyClass::ComplianceCoverage => "compliance_coverage",
            PropertyClass::EffectRowSoundness => "effect_row_soundness",
            PropertyClass::CapabilityIsolation => "capability_isolation",
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

/// §51.b — witness for [`PropertyClass::EffectRowSoundness`].
///
/// The derivation for one tool's declared effect row. The checker
/// re-derives every field from the tool's IR and rejects a disagreement
/// as forgery (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EffectRowSoundnessWitness {
    /// The tool this proof is about.
    pub tool_name: String,
    /// The tool's declared effect-row entries, sorted + deduped
    /// (canonical so the checker's re-derivation compares equal). Each
    /// entry is `base` or `base:qualifier`.
    pub declared_effects: Vec<String>,
    /// Entries whose base effect is NOT in the closed catalog (phantom
    /// effects). Empty for a verifying proof.
    pub unknown_bases: Vec<String>,
    /// Qualifier-required bases (`stream` / `trust`) declared WITHOUT a
    /// qualifier (bare `stream` / `trust`). Empty for a verifying proof.
    pub missing_qualifier: Vec<String>,
    /// `stream:<q>` entries whose qualifier is not a valid backpressure
    /// policy. Empty for a verifying proof.
    pub invalid_stream_qualifier: Vec<String>,
    /// True when `pure` appears alongside any other effect (a tool
    /// cannot be both pure and effectful). False for a verifying proof.
    pub purity_violation: bool,
}

/// §51.c — witness for [`PropertyClass::CapabilityIsolation`].
///
/// The derivation for one `axonstore`'s capability gate. The checker
/// re-reads the store's `capability` from the IR and re-runs the §32.g
/// grammar validator; a forged witness is rejected because the
/// recomputation disagrees (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityIsolationWitness {
    /// The `axonstore` this proof is about.
    pub store_name: String,
    /// The store's declared Pillar IV capability gate slug.
    pub capability: String,
    /// True when `capability` is non-empty AND does NOT match the
    /// §32.g capability-scope grammar. False for a verifying proof.
    pub malformed: bool,
}

/// The property-specific witness. Tagged so the JSON is self-describing
/// + a future class adds a variant without ambiguity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Witness {
    ComplianceCoverage(ComplianceCoverageWitness),
    EffectRowSoundness(EffectRowSoundnessWitness),
    CapabilityIsolation(CapabilityIsolationWitness),
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
