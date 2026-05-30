//! §Fase 51.a — Proof generation (the producer / compiler side).
//!
//! Walks an [`IRProgram`] and emits one [`ProofTerm`] per apx /
//! axonendpoint that declares a `compliance:` set. Generation records
//! the DERIVATION (the witness) for every compliance-bearing endpoint;
//! it does NOT decide the verdict — that is the independent checker's
//! job ([`crate::pcc::checker::check_proof`]). This split is deliberate:
//! the producer hands the consumer a derivation, the consumer
//! re-checks it (D51.2). A defective endpoint (phantom class / no
//! shield) still gets a proof term; the checker renders `Refuted` so
//! the defect is surfaced, not hidden.

use crate::ir_nodes::IRProgram;

use super::proof_term::{
    ComplianceCoverageWitness, ProofTerm, PropertyClass, Witness,
};

/// Canonical SHA-256 hex digest of the IR artifact. Reuses the
/// `esk::provenance` canonicalizer so the producer + the independent
/// checker compute byte-identical digests. A serialization failure
/// (practically unreachable for the derive-`Serialize` IR) degrades to
/// a fixed sentinel — still consistent between generate + check, so
/// the digest binding stays sound even in the degenerate case.
pub fn artifact_digest(ir: &IRProgram) -> String {
    match serde_json::to_value(ir) {
        Ok(v) => crate::esk::provenance::content_hash(&v),
        Err(_) => "<ir-unserializable>".to_string(),
    }
}

/// Sort + dedup a class list into the canonical form the witness
/// carries (so the checker's re-derivation compares equal).
fn canonical_classes(raw: &[String]) -> Vec<String> {
    let mut v: Vec<String> = raw.to_vec();
    v.sort();
    v.dedup();
    v
}

/// §51.a — derive a [`ComplianceCoverageWitness`] for one endpoint
/// against the program IR. Pure + total. Shared with the checker's
/// re-derivation path so producer + verifier compute identically (the
/// checker calls this to recompute, then compares against the proof's
/// witness — D51.2).
pub fn derive_compliance_coverage_witness(
    endpoint_name: &str,
    declared_compliance: &[String],
    shield_ref: &str,
    ir: &IRProgram,
) -> ComplianceCoverageWitness {
    let required_classes = canonical_classes(declared_compliance);

    // Resolve the shield once; reuse for presence + provided coverage.
    let resolved_shield = if shield_ref.is_empty() {
        None
    } else {
        ir.shields.iter().find(|s| s.name == shield_ref)
    };
    let shield_present = resolved_shield.is_some();
    let provided_classes = resolved_shield
        .map(|s| canonical_classes(&s.compliance))
        .unwrap_or_default();

    let unknown_classes: Vec<String> = required_classes
        .iter()
        .filter(|c| !crate::esk::compliance::is_known(c))
        .cloned()
        .collect();

    // The coverage gap: required classes the shield does NOT provide.
    // Reuses the canonical `compliance::covers` predicate (the producer
    // + the independent checker share this exact derivation).
    let mut uncovered_classes: Vec<String> =
        crate::esk::compliance::covers(provided_classes.iter(), required_classes.iter())
            .into_iter()
            .collect();
    uncovered_classes.sort();

    ComplianceCoverageWitness {
        endpoint_name: endpoint_name.to_string(),
        required_classes,
        shield_ref: shield_ref.to_string(),
        shield_present,
        provided_classes,
        unknown_classes,
        uncovered_classes,
    }
}

/// §51.a — generate compliance-coverage proofs for every apx /
/// axonendpoint in `ir` that declares a non-empty `compliance:` set.
///
/// D51.5 — apx (`axpoint`) and `axonendpoint` share the IR
/// `endpoints` node family, so this one walk covers both. Endpoints
/// with no compliance declaration produce no proof (nothing to
/// certify).
pub fn generate_compliance_coverage_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ep in &ir.endpoints {
        if ep.compliance.is_empty() {
            continue;
        }
        let witness = derive_compliance_coverage_witness(
            &ep.name,
            &ep.compliance,
            &ep.shield_ref,
            ir,
        );
        proofs.push(ProofTerm {
            property: PropertyClass::ComplianceCoverage,
            artifact_digest: digest.clone(),
            witness: Witness::ComplianceCoverage(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}
