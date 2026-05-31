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

use super::effects;
use super::proof_term::{
    CapabilityIsolationWitness, ComplianceCoverageWitness,
    EffectRowSoundnessWitness, ProofTerm, PropertyClass, ResourceBoundsWitness,
    Witness, MAX_RETRIES,
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

/// §51.b — derive an [`EffectRowSoundnessWitness`] for one tool's
/// declared effect row. Pure + total. Shared with the checker's
/// re-derivation path (D51.2).
pub fn derive_effect_row_soundness_witness(
    tool_name: &str,
    effect_row: &[String],
) -> EffectRowSoundnessWitness {
    let declared_effects = canonical_classes(effect_row);

    let mut unknown_bases = Vec::new();
    let mut missing_qualifier = Vec::new();
    let mut invalid_stream_qualifier = Vec::new();
    let mut has_pure = false;
    let mut has_other = false;

    for entry in &declared_effects {
        let (base, qualifier) = effects::split_effect(entry);
        if !effects::is_known_base(base) {
            unknown_bases.push(entry.clone());
            // An unknown base is also "other" for purity purposes —
            // a tool with `pure` + a phantom effect is still a
            // contradiction. (has_other set below covers it.)
            has_other = true;
            continue;
        }
        if base == "pure" {
            has_pure = true;
        } else {
            has_other = true;
        }
        if effects::requires_qualifier(base) && qualifier.is_none() {
            missing_qualifier.push(entry.clone());
        }
        if base == "stream" {
            if let Some(q) = qualifier {
                if !effects::is_valid_stream_qualifier(q) {
                    invalid_stream_qualifier.push(entry.clone());
                }
            }
        }
    }

    let purity_violation = has_pure && has_other;

    EffectRowSoundnessWitness {
        tool_name: tool_name.to_string(),
        declared_effects,
        unknown_bases,
        missing_qualifier,
        invalid_stream_qualifier,
        purity_violation,
    }
}

/// §51.b — generate effect-row-soundness proofs for every tool in `ir`
/// that declares a non-empty `effects: <...>` row. Tools with no
/// declared effects produce no proof (nothing to certify).
pub fn generate_effect_row_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for tool in &ir.tools {
        if tool.effect_row.is_empty() {
            continue;
        }
        let witness =
            derive_effect_row_soundness_witness(&tool.name, &tool.effect_row);
        proofs.push(ProofTerm {
            property: PropertyClass::EffectRowSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::EffectRowSoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §51.c — derive a [`CapabilityIsolationWitness`] for one store's
/// capability gate. Pure + total. Shared with the checker's
/// re-derivation path (D51.2). Grammar validity delegates to the OSS
/// single-source-of-truth `axon_frontend::parser::is_valid_capability_slug`
/// (re-exported as `crate::parser`) — the checker re-derives the FACT
/// (this store's gate slug) and re-runs the canonical validator; it
/// does not trust the witness.
pub fn derive_capability_isolation_witness(
    store_name: &str,
    capability: &str,
) -> CapabilityIsolationWitness {
    let malformed =
        !capability.is_empty() && !crate::parser::is_valid_capability_slug(capability);
    CapabilityIsolationWitness {
        store_name: store_name.to_string(),
        capability: capability.to_string(),
        malformed,
    }
}

/// §51.c — generate capability-isolation proofs for every `axonstore`
/// in `ir` that declares a non-empty `capability` gate. Stores with no
/// gate produce no proof (nothing to certify — an ungated store is out
/// of scope for the gate-integrity property).
pub fn generate_capability_isolation_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for store in &ir.axonstore_specs {
        if store.capability.is_empty() {
            continue;
        }
        let witness =
            derive_capability_isolation_witness(&store.name, &store.capability);
        proofs.push(ProofTerm {
            property: PropertyClass::CapabilityIsolation,
            artifact_digest: digest.clone(),
            witness: Witness::CapabilityIsolation(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §51.d — derive the retry-bound witness for one endpoint. Pure +
/// total. Shared with the checker (D51.2).
pub fn derive_endpoint_retry_witness(
    endpoint_name: &str,
    retries: i64,
) -> ResourceBoundsWitness {
    ResourceBoundsWitness::EndpointRetry {
        endpoint_name: endpoint_name.to_string(),
        retries,
        in_bounds: (0..=MAX_RETRIES).contains(&retries),
    }
}

/// §51.d — derive the credit-positivity witness for one socket's
/// DECLARED credit window. Pure + total. Shared with the checker.
pub fn derive_socket_credit_witness(
    socket_name: &str,
    credit: i64,
) -> ResourceBoundsWitness {
    ResourceBoundsWitness::SocketCredit {
        socket_name: socket_name.to_string(),
        credit,
        positive: credit >= 1,
    }
}

/// §51.d — generate resource-bound proofs: one retry-bound proof per
/// apx/axonendpoint, plus one credit-positivity proof per socket that
/// DECLARES a `backpressure: credit(k)` window. Sockets with an
/// unspecified credit produce no proof (unspecified is a legitimate
/// type state, not a bound to certify). `timeout` is out of scope by
/// design (closed duration enum, bounded at parse).
pub fn generate_resource_bounds_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ep in &ir.endpoints {
        let witness = derive_endpoint_retry_witness(&ep.name, ep.retries);
        proofs.push(ProofTerm {
            property: PropertyClass::ResourceBounds,
            artifact_digest: digest.clone(),
            witness: Witness::ResourceBounds(witness),
            axon_version: axon_version.to_string(),
        });
    }
    for socket in &ir.sockets {
        if let Some(credit) = socket.backpressure_credit {
            let witness = derive_socket_credit_witness(&socket.name, credit);
            proofs.push(ProofTerm {
                property: PropertyClass::ResourceBounds,
                artifact_digest: digest.clone(),
                witness: Witness::ResourceBounds(witness),
                axon_version: axon_version.to_string(),
            });
        }
    }
    proofs
}
