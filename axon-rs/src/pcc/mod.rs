//! §Fase 51 — Proof-Carrying Code (PCC).
//!
//! From **attestation** to **machine-checkable proof**. The
//! [`crate::esk::attestation`] surface (SBOM, in-toto/SLSA provenance,
//! ComplianceDossier) emits builder-signed CLAIMS a consumer trusts.
//! PCC emits a portable [`ProofTerm`] a consumer INDEPENDENTLY verifies
//! ([`check_proof`]) — without trusting the axon compiler that produced
//! it (Necula 1997: ship code + proof; the consumer runs a small,
//! trusted, producer-independent checker).
//!
//! §Fase 51.a ships the kernel + the first property class
//! ([`PropertyClass::ComplianceCoverage`]): every regulatory class an
//! apx / axonendpoint declares is known + backed by a resolvable
//! shield. §51.b-e generalize to effect-row soundness, capability
//! isolation, resource bounds, and shield-halt guarantees — the
//! proof-term language + checker dispatch are designed to extend
//! (D51.4 — "universal" is the architecture, shipped one class at a
//! time).
//!
//! ## The loop
//!
//! ```text
//!   producer:  generate_compliance_coverage_proofs(ir, version)  ->  [ProofTerm]
//!                  (records the derivation; does NOT decide the verdict)
//!   consumer:  check_proof(&proof, ir)  ->  CheckOutcome
//!                  (re-derives from the artifact; renders Verified / Refuted;
//!                   rejects a forged witness or a digest mismatch)
//! ```
//!
//! The split is the point: the producer hands over a derivation, the
//! consumer re-checks it. Trust lives in the (small, auditable)
//! checker, not the (large, complex) compiler.

pub mod checker;
pub mod generate;
pub mod proof_term;

pub use checker::{check_proof, CheckOutcome};
pub use generate::{
    artifact_digest, derive_compliance_coverage_witness,
    generate_compliance_coverage_proofs,
};
pub use proof_term::{
    ComplianceCoverageWitness, ProofTerm, PropertyClass, Witness,
};

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir_nodes::{IRAxonEndpoint, IRProgram, IRShield};

    const VERSION: &str = "2.4.0-test";

    fn empty_ir() -> IRProgram {
        IRProgram::new()
    }

    fn endpoint(name: &str, compliance: &[&str], shield_ref: &str) -> IRAxonEndpoint {
        IRAxonEndpoint {
            node_type: "endpoint",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            method: "POST".to_string(),
            path: format!("/{name}"),
            body_type: String::new(),
            execute_flow: "F".to_string(),
            output_type: String::new(),
            shield_ref: shield_ref.to_string(),
            retries: 0,
            timeout: String::new(),
            compliance: compliance.iter().map(|s| s.to_string()).collect(),
            path_params: Vec::new(),
            query_params: Vec::new(),
        }
    }

    /// Shield providing the given regulatory classes (its `compliance:`
    /// set — the §ESK Fase 6.1 covered-classes field).
    fn shield(name: &str, provides: &[&str]) -> IRShield {
        IRShield {
            node_type: "shield",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            scan: vec!["pii_leak".to_string()],
            strategy: String::new(),
            on_breach: "halt".to_string(),
            severity: "high".to_string(),
            quarantine: String::new(),
            max_retries: 0,
            confidence_threshold: 0.0,
            allow_tools: Vec::new(),
            deny_tools: Vec::new(),
            sandbox: false,
            redact: Vec::new(),
            log: String::new(),
            deflect_message: String::new(),
            taint: String::new(),
            compliance: provides.iter().map(|s| s.to_string()).collect(),
        }
    }

    /// Happy path: an apx declaring known classes + a present shield
    /// generates a proof the independent checker VERIFIES.
    #[test]
    fn covered_endpoint_proof_verifies() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA", "GDPR"]));
        ir.endpoints
            .push(endpoint("ChatEndpoint", &["HIPAA", "GDPR"], "PhiGate"));

        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 1, "one compliance-bearing endpoint => one proof");
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// Endpoints with no compliance declaration produce no proof
    /// (nothing to certify).
    #[test]
    fn no_compliance_no_proof() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA"]));
        ir.endpoints.push(endpoint("Plain", &[], "PhiGate"));
        assert!(generate_compliance_coverage_proofs(&ir, VERSION).is_empty());
    }

    /// Honest defect: the shield resolves but does NOT provide every
    /// required class (endpoint requires HIPAA+GDPR, shield covers only
    /// HIPAA) → Refuted naming the uncovered gap. This is the core
    /// `covers()` semantic the proof certifies.
    #[test]
    fn shield_missing_required_class_is_refuted() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PartialGate", &["HIPAA"]));
        ir.endpoints
            .push(endpoint("Gap", &["HIPAA", "GDPR"], "PartialGate"));
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("does not provide"), "got: {reason}");
                assert!(reason.contains("GDPR"), "got: {reason}");
            }
            other => panic!("expected coverage-gap Refuted, got {other:?}"),
        }
    }

    /// Honest defect: compliance declared but no shield attached →
    /// the checker REFUTES (you cannot claim regulatory coverage with
    /// zero enforcement).
    #[test]
    fn compliance_without_shield_is_refuted() {
        let mut ir = empty_ir();
        ir.endpoints
            .push(endpoint("NoGuard", &["HIPAA"], "")); // empty shield_ref
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 1);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("no resolvable shield"), "got: {reason}");
            }
            other => panic!("expected Refuted, got {other:?}"),
        }
    }

    /// Honest defect: shield_ref names a shield that isn't in the IR →
    /// dangling reference → Refuted.
    #[test]
    fn dangling_shield_ref_is_refuted() {
        let mut ir = empty_ir();
        ir.endpoints
            .push(endpoint("Dangling", &["HIPAA"], "GhostShield"));
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("no resolvable shield"), "got: {reason}");
            }
            other => panic!("expected Refuted, got {other:?}"),
        }
    }

    /// Honest defect: phantom regulatory class (typo'd `HIPPA`) →
    /// Refuted naming the unknown class.
    #[test]
    fn phantom_regulatory_class_is_refuted() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA"]));
        ir.endpoints
            .push(endpoint("Typo", &["HIPPA"], "PhiGate")); // HIPPA, not HIPAA
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("unknown regulatory class"), "got: {reason}");
                assert!(reason.contains("HIPPA"), "got: {reason}");
            }
            other => panic!("expected Refuted, got {other:?}"),
        }
    }

    /// ADVERSARIAL (D51.2): a forged witness claiming `shield_present:
    /// true` for an endpoint whose shield_ref is empty is REJECTED —
    /// the checker recomputes shield_present from the artifact and
    /// finds the witness lies.
    #[test]
    fn forged_shield_present_rejected() {
        let mut ir = empty_ir();
        ir.endpoints.push(endpoint("Forge", &["HIPAA"], ""));
        let mut proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        // Tamper: flip shield_present to true (the lie).
        if let Witness::ComplianceCoverage(ref mut w) = proofs[0].witness {
            w.shield_present = true;
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("disagrees with artifact"), "got: {reason}");
            }
            other => panic!("expected forged-witness Refuted, got {other:?}"),
        }
    }

    /// ADVERSARIAL (D51.2): a forged witness hiding a phantom class
    /// (omitting it from `unknown_classes`) is REJECTED — the checker
    /// recomputes the unknown set.
    #[test]
    fn forged_hidden_unknown_class_rejected() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA"]));
        ir.endpoints.push(endpoint("Hide", &["NOTACLASS"], "PhiGate"));
        let mut proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        // Tamper: pretend there are no unknown classes.
        if let Witness::ComplianceCoverage(ref mut w) = proofs[0].witness {
            w.unknown_classes.clear();
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("disagrees with artifact"), "got: {reason}");
            }
            other => panic!("expected forged-witness Refuted, got {other:?}"),
        }
    }

    /// ADVERSARIAL (D51.1): a proof minted for program A checked
    /// against program B (different digest) is REJECTED.
    #[test]
    fn digest_mismatch_rejected() {
        let mut ir_a = empty_ir();
        ir_a.shields.push(shield("PhiGate", &["HIPAA"]));
        ir_a.endpoints
            .push(endpoint("ChatEndpoint", &["HIPAA"], "PhiGate"));
        let proofs = generate_compliance_coverage_proofs(&ir_a, VERSION);

        // Program B: same endpoint + shield, but an extra endpoint
        // changes the IR digest. Built fresh (IRProgram is not Clone).
        let mut ir_b = empty_ir();
        ir_b.shields.push(shield("PhiGate", &["HIPAA"]));
        ir_b.endpoints
            .push(endpoint("ChatEndpoint", &["HIPAA"], "PhiGate"));
        ir_b.endpoints.push(endpoint("Extra", &["GDPR"], "PhiGate"));

        assert_eq!(
            check_proof(&proofs[0], &ir_b),
            CheckOutcome::DigestMismatch,
            "a proof for program A must not verify against program B"
        );
    }

    /// ADVERSARIAL: a proof whose witness names an endpoint absent from
    /// the artifact is Refuted (not a panic). Exercises the
    /// never-panic guarantee on a stale/forged endpoint reference.
    #[test]
    fn proof_for_absent_endpoint_refuted_not_panic() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA"]));
        ir.endpoints
            .push(endpoint("Real", &["HIPAA"], "PhiGate"));
        let mut proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        // Tamper the endpoint name to one not in the IR, and re-stamp
        // the digest so we get past the digest gate to the endpoint
        // lookup (isolates the absent-endpoint path).
        if let Witness::ComplianceCoverage(ref mut w) = proofs[0].witness {
            w.endpoint_name = "Ghost".to_string();
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("not present in artifact"), "got: {reason}");
            }
            other => panic!("expected absent-endpoint Refuted, got {other:?}"),
        }
    }

    /// The proof term round-trips through JSON (it travels as JSON
    /// alongside the artifact). A round-tripped proof still verifies.
    #[test]
    fn proof_term_json_round_trips_and_verifies() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA"]));
        ir.endpoints
            .push(endpoint("ChatEndpoint", &["HIPAA"], "PhiGate"));
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        let json = serde_json::to_string(&proofs[0]).expect("serialize");
        let restored: ProofTerm = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(restored, proofs[0]);
        assert_eq!(check_proof(&restored, &ir), CheckOutcome::Verified);
    }

    /// Witness canonicalization: declared classes in any order +
    /// duplicates produce the same (sorted, deduped) witness, so the
    /// checker's re-derivation compares equal regardless of source
    /// ordering.
    #[test]
    fn class_ordering_and_dupes_canonicalized() {
        let mut ir = empty_ir();
        ir.shields.push(shield("PhiGate", &["HIPAA", "GDPR"]));
        ir.endpoints.push(endpoint(
            "Multi",
            &["GDPR", "HIPAA", "GDPR"], // unsorted + duplicate
            "PhiGate",
        ));
        let proofs = generate_compliance_coverage_proofs(&ir, VERSION);
        if let Witness::ComplianceCoverage(ref w) = proofs[0].witness {
            assert_eq!(w.required_classes, vec!["GDPR".to_string(), "HIPAA".to_string()]);
        } else {
            panic!("expected ComplianceCoverage witness");
        }
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// §51.a property-class slug is stable (wire contract).
    #[test]
    fn property_class_slug_stable() {
        assert_eq!(PropertyClass::ComplianceCoverage.slug(), "compliance_coverage");
    }
}
