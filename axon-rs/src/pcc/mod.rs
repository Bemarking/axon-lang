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
pub mod effects;
pub mod generate;
pub mod proof_term;

pub use checker::{check_proof, CheckOutcome};
pub use generate::{
    artifact_digest, derive_capability_isolation_witness,
    derive_compliance_coverage_witness, derive_effect_row_soundness_witness,
    derive_endpoint_retry_witness, derive_socket_credit_witness,
    generate_capability_isolation_proofs, generate_compliance_coverage_proofs,
    generate_effect_row_soundness_proofs, generate_resource_bounds_proofs,
};
pub use proof_term::{
    CapabilityIsolationWitness, ComplianceCoverageWitness,
    EffectRowSoundnessWitness, ProofTerm, PropertyClass, ResourceBoundsWitness,
    Witness, MAX_RETRIES,
};

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir_nodes::{IRAxonEndpoint, IRProgram, IRShield, IRToolSpec};

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
        assert_eq!(PropertyClass::EffectRowSoundness.slug(), "effect_row_soundness");
        assert_eq!(PropertyClass::CapabilityIsolation.slug(), "capability_isolation");
        assert_eq!(PropertyClass::ResourceBounds.slug(), "resource_bounds");
    }

    // ── §Fase 51.b — EffectRowSoundness ──────────────────────────────

    /// Tool declaring the given effect-row entries.
    fn tool(name: &str, effects: &[&str]) -> IRToolSpec {
        IRToolSpec {
            node_type: "tool",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            provider: "native".to_string(),
            max_results: None,
            filter_expr: String::new(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            input_schema: Vec::new(),
            output_schema: String::new(),
            effect_row: effects.iter().map(|s| s.to_string()).collect(),
        }
    }

    /// Happy path: a tool with well-formed effects verifies.
    #[test]
    fn well_formed_effect_row_verifies() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Fetch", &["network", "storage"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 1);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// A tool with no declared effects produces no proof.
    #[test]
    fn no_effects_no_proof() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Plain", &[]));
        assert!(generate_effect_row_soundness_proofs(&ir, VERSION).is_empty());
    }

    /// Phantom base effect (typo'd `netwrok`) → Refuted.
    #[test]
    fn phantom_effect_base_refuted() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Typo", &["netwrok"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("unknown base"), "got: {reason}");
                assert!(reason.contains("netwrok"), "got: {reason}");
            }
            other => panic!("expected phantom-effect Refuted, got {other:?}"),
        }
    }

    /// Bare `stream` without a backpressure qualifier → Refuted
    /// (unenforceable).
    #[test]
    fn bare_stream_missing_qualifier_refuted() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Streamer", &["stream"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("without a qualifier"), "got: {reason}");
            }
            other => panic!("expected missing-qualifier Refuted, got {other:?}"),
        }
    }

    /// `stream:<valid policy>` verifies (qualifier from the backpressure
    /// catalog).
    #[test]
    fn valid_stream_qualifier_verifies() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Streamer", &["stream:drop_oldest"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// `stream:<bogus>` (qualifier not in the backpressure catalog) →
    /// Refuted.
    #[test]
    fn invalid_stream_qualifier_refuted() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Streamer", &["stream:explode"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("invalid backpressure policy"), "got: {reason}");
            }
            other => panic!("expected invalid-qualifier Refuted, got {other:?}"),
        }
    }

    /// `pure` alongside another effect → purity contradiction → Refuted.
    #[test]
    fn purity_violation_refuted() {
        let mut ir = empty_ir();
        ir.tools.push(tool("FakePure", &["pure", "network"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("pure"), "got: {reason}");
                assert!(reason.contains("cannot be effectful"), "got: {reason}");
            }
            other => panic!("expected purity Refuted, got {other:?}"),
        }
    }

    /// `pure` alone verifies.
    #[test]
    fn pure_alone_verifies() {
        let mut ir = empty_ir();
        ir.tools.push(tool("TrulyPure", &["pure"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// ADVERSARIAL (D51.2): a forged witness hiding a phantom base
    /// (clearing `unknown_bases`) is rejected — the checker recomputes.
    #[test]
    fn forged_hidden_unknown_base_rejected() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Sneaky", &["netwrok"]));
        let mut proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        if let Witness::EffectRowSoundness(ref mut w) = proofs[0].witness {
            w.unknown_bases.clear(); // the lie
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("disagrees with artifact"), "got: {reason}");
            }
            other => panic!("expected forged Refuted, got {other:?}"),
        }
    }

    /// ADVERSARIAL: a proof whose `property` and `witness` variants
    /// disagree (ComplianceCoverage property carrying an
    /// EffectRowSoundness witness) is UnknownProperty — neither
    /// property is actually witnessed, so no silent accept.
    #[test]
    fn mismatched_property_witness_is_unknown_property() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Fetch", &["network"]));
        let digest = artifact_digest(&ir);
        let bogus = ProofTerm {
            property: PropertyClass::ComplianceCoverage, // mismatch
            artifact_digest: digest,
            witness: Witness::EffectRowSoundness(
                derive_effect_row_soundness_witness("Fetch", &["network".to_string()]),
            ),
            axon_version: VERSION.to_string(),
        };
        assert_eq!(check_proof(&bogus, &ir), CheckOutcome::UnknownProperty);
    }

    /// Effect-row proof round-trips through JSON and still verifies.
    #[test]
    fn effect_proof_json_round_trips_and_verifies() {
        let mut ir = empty_ir();
        ir.tools.push(tool("Fetch", &["network", "storage"]));
        let proofs = generate_effect_row_soundness_proofs(&ir, VERSION);
        let json = serde_json::to_string(&proofs[0]).expect("serialize");
        let restored: ProofTerm = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(restored, proofs[0]);
        assert_eq!(check_proof(&restored, &ir), CheckOutcome::Verified);
    }

    /// Digest binding holds for effect-row proofs too.
    #[test]
    fn effect_proof_digest_mismatch_rejected() {
        let mut ir_a = empty_ir();
        ir_a.tools.push(tool("Fetch", &["network"]));
        let proofs = generate_effect_row_soundness_proofs(&ir_a, VERSION);

        let mut ir_b = empty_ir();
        ir_b.tools.push(tool("Fetch", &["network"]));
        ir_b.tools.push(tool("Other", &["storage"])); // changes digest

        assert_eq!(check_proof(&proofs[0], &ir_b), CheckOutcome::DigestMismatch);
    }

    // ── §Fase 51.c — CapabilityIsolation ─────────────────────────────

    /// `axonstore` with the given Pillar IV capability gate slug.
    fn store(name: &str, capability: &str) -> crate::ir_nodes::IRAxonStore {
        crate::ir_nodes::IRAxonStore {
            node_type: "axonstore",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            backend: "postgresql".to_string(),
            connection: String::new(),
            confidence_floor: None,
            isolation: String::new(),
            on_breach: String::new(),
            capability: capability.to_string(),
            column_schema: None,
        }
    }

    /// Happy path: a well-formed §32.g gate slug verifies.
    #[test]
    fn well_formed_gate_verifies() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Ledger", "legal.read"));
        let proofs = generate_capability_isolation_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 1);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// A store with no capability gate produces no proof.
    #[test]
    fn no_gate_no_proof() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Open", ""));
        assert!(generate_capability_isolation_proofs(&ir, VERSION).is_empty());
    }

    /// A malformed gate slug (uppercase violates the §32.g grammar) →
    /// Refuted.
    #[test]
    fn malformed_gate_refuted() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Broken", "Legal.Read")); // uppercase
        let proofs = generate_capability_isolation_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("malformed capability gate"), "got: {reason}");
                assert!(reason.contains("Legal.Read"), "got: {reason}");
            }
            other => panic!("expected malformed-gate Refuted, got {other:?}"),
        }
    }

    /// Dotted multi-segment scope (`hipaa.phi.read`) is well-formed.
    #[test]
    fn deep_dotted_gate_verifies() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Phi", "hipaa.phi.read"));
        let proofs = generate_capability_isolation_proofs(&ir, VERSION);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// ADVERSARIAL (D51.2): a forged witness claiming `malformed:
    /// false` for a broken gate is rejected — the checker re-runs the
    /// grammar validator and finds the witness lies.
    #[test]
    fn forged_malformed_flag_rejected() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Sneaky", "Bad..Slug"));
        let mut proofs = generate_capability_isolation_proofs(&ir, VERSION);
        if let Witness::CapabilityIsolation(ref mut w) = proofs[0].witness {
            w.malformed = false; // the lie
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("disagrees with artifact"), "got: {reason}");
            }
            other => panic!("expected forged Refuted, got {other:?}"),
        }
    }

    /// Digest binding holds for capability proofs.
    #[test]
    fn capability_proof_digest_mismatch_rejected() {
        let mut ir_a = empty_ir();
        ir_a.axonstore_specs.push(store("Ledger", "legal.read"));
        let proofs = generate_capability_isolation_proofs(&ir_a, VERSION);

        let mut ir_b = empty_ir();
        ir_b.axonstore_specs.push(store("Ledger", "legal.read"));
        ir_b.axonstore_specs.push(store("Extra", "fin.read")); // changes digest

        assert_eq!(check_proof(&proofs[0], &ir_b), CheckOutcome::DigestMismatch);
    }

    /// Capability proof round-trips through JSON and still verifies.
    #[test]
    fn capability_proof_json_round_trips_and_verifies() {
        let mut ir = empty_ir();
        ir.axonstore_specs.push(store("Ledger", "legal.read"));
        let proofs = generate_capability_isolation_proofs(&ir, VERSION);
        let json = serde_json::to_string(&proofs[0]).expect("serialize");
        let restored: ProofTerm = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(restored, proofs[0]);
        assert_eq!(check_proof(&restored, &ir), CheckOutcome::Verified);
    }

    // ── §Fase 51.d — ResourceBounds ──────────────────────────────────

    /// An endpoint with the given `retries` (reuses the base builder).
    fn endpoint_retries(name: &str, retries: i64) -> IRAxonEndpoint {
        let mut e = endpoint(name, &[], "");
        e.retries = retries;
        e
    }

    /// A socket with the given (optional) backpressure credit window.
    fn socket(name: &str, credit: Option<i64>) -> crate::ir_nodes::IRSocket {
        crate::ir_nodes::IRSocket {
            node_type: "socket",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            protocol: "ChatProtocol".to_string(),
            backpressure_credit: credit,
            reconnect: false,
            legal_basis: None,
        }
    }

    /// Retry counts within `[0, MAX_RETRIES]` verify — including both
    /// boundaries (0 and the ceiling).
    #[test]
    fn retry_in_bounds_verifies() {
        let mut ir = empty_ir();
        ir.endpoints.push(endpoint_retries("Mid", 3));
        ir.endpoints.push(endpoint_retries("Zero", 0));
        ir.endpoints.push(endpoint_retries("Ceiling", MAX_RETRIES));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 3);
        for p in &proofs {
            assert_eq!(check_proof(p, &ir), CheckOutcome::Verified);
        }
    }

    /// Negative retries → Refuted (nonsensical).
    #[test]
    fn retry_negative_refuted() {
        let mut ir = empty_ir();
        ir.endpoints.push(endpoint_retries("Neg", -1));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("retries=-1"), "got: {reason}");
                assert!(reason.contains("outside the bound"), "got: {reason}");
            }
            other => panic!("expected negative-retry Refuted, got {other:?}"),
        }
    }

    /// Retry count above the ceiling → Refuted (retry storm).
    #[test]
    fn retry_storm_refuted() {
        let mut ir = empty_ir();
        ir.endpoints.push(endpoint_retries("Storm", MAX_RETRIES + 1));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("retry storm"), "got: {reason}");
            }
            other => panic!("expected retry-storm Refuted, got {other:?}"),
        }
    }

    /// A socket with a positive declared credit verifies.
    #[test]
    fn socket_positive_credit_verifies() {
        let mut ir = empty_ir();
        ir.sockets.push(socket("Chat", Some(8)));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        assert_eq!(proofs.len(), 1);
        assert_eq!(check_proof(&proofs[0], &ir), CheckOutcome::Verified);
    }

    /// A socket declaring credit(0) → Refuted (deadlock per §41.b).
    #[test]
    fn socket_zero_credit_refuted() {
        let mut ir = empty_ir();
        ir.sockets.push(socket("Dead", Some(0)));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("deadlock"), "got: {reason}");
            }
            other => panic!("expected zero-credit Refuted, got {other:?}"),
        }
    }

    /// A socket with UNSPECIFIED credit produces no proof (legitimate
    /// type state, not a bound to certify).
    #[test]
    fn socket_unspecified_credit_no_proof() {
        let mut ir = empty_ir();
        ir.sockets.push(socket("Unspecified", None));
        // No endpoints either, so the whole proof set is empty.
        assert!(generate_resource_bounds_proofs(&ir, VERSION).is_empty());
    }

    /// ADVERSARIAL (D51.2): a forged retry witness claiming
    /// `in_bounds: true` for a negative retry count is rejected — the
    /// checker recomputes the bound.
    #[test]
    fn forged_retry_in_bounds_rejected() {
        let mut ir = empty_ir();
        ir.endpoints.push(endpoint_retries("Liar", -5));
        let mut proofs = generate_resource_bounds_proofs(&ir, VERSION);
        if let Witness::ResourceBounds(ResourceBoundsWitness::EndpointRetry {
            ref mut in_bounds,
            ..
        }) = proofs[0].witness
        {
            *in_bounds = true; // the lie
        }
        match check_proof(&proofs[0], &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("disagrees with artifact"), "got: {reason}");
            }
            other => panic!("expected forged Refuted, got {other:?}"),
        }
    }

    /// ADVERSARIAL: a SocketCredit witness for a socket that has NO
    /// declared credit in the artifact is rejected (forged / stale).
    #[test]
    fn forged_socket_credit_for_unspecified_rejected() {
        let mut ir = empty_ir();
        ir.sockets.push(socket("Ghost", None)); // unspecified in artifact
        let digest = artifact_digest(&ir);
        let bogus = ProofTerm {
            property: PropertyClass::ResourceBounds,
            artifact_digest: digest,
            witness: Witness::ResourceBounds(derive_socket_credit_witness("Ghost", 8)),
            axon_version: VERSION.to_string(),
        };
        match check_proof(&bogus, &ir) {
            CheckOutcome::Refuted { reason } => {
                assert!(reason.contains("no declared backpressure credit"), "got: {reason}");
            }
            other => panic!("expected forged-socket Refuted, got {other:?}"),
        }
    }

    /// Digest binding holds for resource-bound proofs.
    #[test]
    fn resource_proof_digest_mismatch_rejected() {
        let mut ir_a = empty_ir();
        ir_a.endpoints.push(endpoint_retries("E", 2));
        let proofs = generate_resource_bounds_proofs(&ir_a, VERSION);

        let mut ir_b = empty_ir();
        ir_b.endpoints.push(endpoint_retries("E", 2));
        ir_b.endpoints.push(endpoint_retries("Extra", 1)); // changes digest

        assert_eq!(check_proof(&proofs[0], &ir_b), CheckOutcome::DigestMismatch);
    }

    /// Resource-bound proof round-trips through JSON and still verifies.
    #[test]
    fn resource_proof_json_round_trips_and_verifies() {
        let mut ir = empty_ir();
        ir.sockets.push(socket("Chat", Some(16)));
        let proofs = generate_resource_bounds_proofs(&ir, VERSION);
        let json = serde_json::to_string(&proofs[0]).expect("serialize");
        let restored: ProofTerm = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(restored, proofs[0]);
        assert_eq!(check_proof(&restored, &ir), CheckOutcome::Verified);
    }
}
