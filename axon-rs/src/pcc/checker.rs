//! §Fase 51.a — the INDEPENDENT proof checker (the consumer side).
//!
//! This is the trust boundary of Proof-Carrying Code. A consumer who
//! does NOT trust the axon compiler runs [`check_proof`] against the
//! artifact + the proof term and gets an unforgeable verdict. The
//! checker is small, total, and never-panics on arbitrary proof input
//! — it is the only piece a verifier must audit.
//!
//! ## D51.2 — independence (the soundness contract)
//!
//! The checker RE-DERIVES the property from the artifact and verifies
//! the witness against that re-derivation. It NEVER accepts a witness
//! field on faith. A forged witness — one claiming `shield_present:
//! true` for an endpoint whose `shield_ref` is empty, or omitting a
//! phantom class from `unknown_classes` — is rejected because the
//! checker recomputes those facts from the IR and compares. The
//! adversarial tests (`forged_*_rejected`) are first-class gates.
//!
//! ## D51.1 — digest binding
//!
//! Before checking any property the checker recomputes the artifact
//! digest and rejects a mismatch ([`CheckOutcome::DigestMismatch`]).
//! A proof minted for program A cannot be replayed against program B.

use crate::ir_nodes::IRProgram;

use super::generate::{artifact_digest, derive_compliance_coverage_witness};
use super::proof_term::{ProofTerm, PropertyClass, Witness};

/// The closed verdict catalog. Total over every proof shape — no
/// default / panic path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckOutcome {
    /// The property holds for this artifact and the witness matches the
    /// checker's independent re-derivation.
    Verified,
    /// The witness matches the artifact but the property does NOT hold
    /// (an honest defect — e.g. compliance declared with no resolvable
    /// shield, or a phantom regulatory class), OR the witness DISAGREES
    /// with the artifact (a forged proof). `reason` distinguishes.
    Refuted { reason: String },
    /// The proof's `artifact_digest` does not match the supplied
    /// artifact — the proof is about a different program.
    DigestMismatch,
    /// The proof's property/witness pairing is not one this checker
    /// version understands (forward-compat for §51.b-e classes).
    UnknownProperty,
}

/// §51.a — verify a [`ProofTerm`] against the artifact it claims to be
/// about. Independent of the producer (D51.2). Total + never-panics.
pub fn check_proof(proof: &ProofTerm, ir: &IRProgram) -> CheckOutcome {
    // (1) D51.1 — digest binding. Recompute; reject a mismatch before
    // looking at the witness at all.
    if proof.artifact_digest != artifact_digest(ir) {
        return CheckOutcome::DigestMismatch;
    }
    // (2) dispatch on the (property, witness) pairing.
    match (&proof.property, &proof.witness) {
        (PropertyClass::ComplianceCoverage, Witness::ComplianceCoverage(w)) => {
            check_compliance_coverage(w, ir)
        }
    }
}

/// §51.a — re-derive the compliance-coverage witness from the artifact
/// and verify it against the proof's witness, then render the verdict.
///
/// The order matters for soundness: we recompute the witness FIRST
/// (independent of the proof's claims), reject any disagreement as a
/// forgery, and only THEN decide Verified vs Refuted on the
/// re-derived facts.
fn check_compliance_coverage(
    claimed: &super::proof_term::ComplianceCoverageWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    // Locate the endpoint named in the witness. Absent ⟹ the proof is
    // about an endpoint not in this artifact (forged / stale).
    let ep = match ir.endpoints.iter().find(|e| e.name == claimed.endpoint_name) {
        Some(e) => e,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "endpoint '{}' not present in artifact",
                    claimed.endpoint_name
                ),
            }
        }
    };

    // Re-derive independently — do NOT trust the witness (D51.2).
    let actual = derive_compliance_coverage_witness(
        &ep.name,
        &ep.compliance,
        &ep.shield_ref,
        ir,
    );

    // Forgery detection: every witness field must equal the checker's
    // re-derivation. Any disagreement ⟹ the proof lies about the
    // artifact.
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    // Verdict on the re-derived (trusted) facts.
    if !actual.shield_present {
        return CheckOutcome::Refuted {
            reason: format!(
                "endpoint '{}' declares compliance {:?} but has no resolvable shield (shield_ref={:?})",
                actual.endpoint_name, actual.required_classes, actual.shield_ref
            ),
        };
    }
    if !actual.unknown_classes.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "endpoint '{}' declares unknown regulatory class(es) {:?} (not in the closed registry)",
                actual.endpoint_name, actual.unknown_classes
            ),
        };
    }
    if !actual.uncovered_classes.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "endpoint '{}' requires regulatory class(es) {:?} that its shield '{}' does not provide (shield provides {:?})",
                actual.endpoint_name,
                actual.uncovered_classes,
                actual.shield_ref,
                actual.provided_classes
            ),
        };
    }
    CheckOutcome::Verified
}
