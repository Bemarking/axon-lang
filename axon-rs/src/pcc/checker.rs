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

use super::generate::{
    artifact_digest, derive_capability_containment_witness,
    derive_capability_isolation_witness, derive_compliance_coverage_witness,
    derive_effect_row_soundness_witness, derive_endpoint_retry_witness,
    derive_shield_halt_witness, derive_socket_credit_witness,
};
use super::proof_term::{ProofTerm, PropertyClass, ResourceBoundsWitness, Witness};

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
    // (2) dispatch on the (property, witness) pairing. A mismatched
    // pairing (e.g. property says ComplianceCoverage but the witness is
    // an EffectRowSoundness witness) is a malformed proof — neither
    // property is actually witnessed — so it is UnknownProperty, not a
    // silent accept.
    match (&proof.property, &proof.witness) {
        (PropertyClass::ComplianceCoverage, Witness::ComplianceCoverage(w)) => {
            check_compliance_coverage(w, ir)
        }
        (PropertyClass::EffectRowSoundness, Witness::EffectRowSoundness(w)) => {
            check_effect_row_soundness(w, ir)
        }
        (PropertyClass::CapabilityIsolation, Witness::CapabilityIsolation(w)) => {
            check_capability_isolation(w, ir)
        }
        (PropertyClass::ResourceBounds, Witness::ResourceBounds(w)) => {
            check_resource_bounds(w, ir)
        }
        (PropertyClass::ShieldHaltGuarantee, Witness::ShieldHaltGuarantee(w)) => {
            check_shield_halt_guarantee(w, ir)
        }
        (PropertyClass::CapabilityContainment, Witness::CapabilityContainment(w)) => {
            check_capability_containment(w, ir)
        }
        _ => CheckOutcome::UnknownProperty,
    }
}

/// §52.a — the result of checking one proof inside a bundle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProofCheck {
    /// Position of the proof in `ProofBundle::proofs`.
    pub index: usize,
    /// The property class the proof claims.
    pub property: PropertyClass,
    /// The witness subject (endpoint / tool / store / shield name).
    pub subject: String,
    /// The independent checker's verdict.
    pub outcome: CheckOutcome,
}

/// §52.a — the deployability report for a whole [`ProofBundle`].
///
/// Aggregates the per-proof [`check_proof`] outcomes so a consumer (the
/// enterprise deploy gate, the `axon pcc verify` CLI) has ONE trusted
/// predicate for "is this bundle deployable." The policy — what counts
/// as deployable — lives HERE, on the checker side, never in consumer
/// glue (D52.1): a bundle is deployable iff every proof `Verified`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleReport {
    /// One entry per proof, in bundle order.
    pub results: Vec<ProofCheck>,
}

impl BundleReport {
    /// True iff EVERY proof verified. Fail-closed: an empty bundle is
    /// vacuously verified (nothing to refute), and any non-`Verified`
    /// outcome (`Refuted` / `DigestMismatch` / `UnknownProperty`) makes
    /// the whole bundle non-deployable (D52.2).
    pub fn all_verified(&self) -> bool {
        self.results
            .iter()
            .all(|r| r.outcome == CheckOutcome::Verified)
    }

    /// Every check that did NOT verify — the reasons a deploy gate
    /// surfaces when it rejects.
    pub fn refutations(&self) -> Vec<&ProofCheck> {
        self.results
            .iter()
            .filter(|r| r.outcome != CheckOutcome::Verified)
            .collect()
    }
}

/// §52.a — check every proof in a bundle against the artifact,
/// independently (each proof re-derived via [`check_proof`]). The
/// bundle's own `artifact_digest` is advisory only — the authoritative
/// binding is the per-proof digest [`check_proof`] re-verifies, so a
/// bundle whose proofs are about a different artifact reports
/// `DigestMismatch` per proof (not a silent pass).
pub fn check_bundle(bundle: &super::proof_term::ProofBundle, ir: &IRProgram) -> BundleReport {
    let results = bundle
        .proofs
        .iter()
        .enumerate()
        .map(|(index, proof)| ProofCheck {
            index,
            property: proof.property.clone(),
            subject: proof.witness.subject_name().to_string(),
            outcome: check_proof(proof, ir),
        })
        .collect();
    BundleReport { results }
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

/// §51.b — re-derive the effect-row witness from the named tool and
/// verify it against the proof, then render the verdict. Independent
/// of the producer (D51.2): the checker re-reads `tool.effect_row` from
/// the artifact and recomputes every fact; a forged witness is rejected
/// because the recomputation disagrees.
fn check_effect_row_soundness(
    claimed: &super::proof_term::EffectRowSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let tool = match ir.tools.iter().find(|t| t.name == claimed.tool_name) {
        Some(t) => t,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "tool '{}' not present in artifact",
                    claimed.tool_name
                ),
            }
        }
    };

    // Re-derive independently — do NOT trust the witness.
    let actual = derive_effect_row_soundness_witness(&tool.name, &tool.effect_row);

    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    // Verdict on the re-derived facts.
    if !actual.unknown_bases.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "tool '{}' declares effect entr(ies) with unknown base(s) {:?} (not in the closed effect catalog)",
                actual.tool_name, actual.unknown_bases
            ),
        };
    }
    if !actual.missing_qualifier.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "tool '{}' declares qualifier-requiring effect(s) {:?} without a qualifier (bare stream/trust is unenforceable)",
                actual.tool_name, actual.missing_qualifier
            ),
        };
    }
    if !actual.invalid_stream_qualifier.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "tool '{}' declares stream effect(s) {:?} with an invalid backpressure policy qualifier",
                actual.tool_name, actual.invalid_stream_qualifier
            ),
        };
    }
    if actual.purity_violation {
        return CheckOutcome::Refuted {
            reason: format!(
                "tool '{}' declares `pure` alongside other effects {:?} — a pure tool cannot be effectful",
                actual.tool_name, actual.declared_effects
            ),
        };
    }
    CheckOutcome::Verified
}

/// §51.c — re-derive the capability-gate witness from the named store
/// and verify it against the proof, then render the verdict.
/// Independent of the producer (D51.2): the checker re-reads
/// `store.capability` from the artifact and re-runs the §32.g grammar
/// validator; a forged witness (claiming `malformed: false` for a
/// broken gate) is rejected because the recomputation disagrees.
fn check_capability_isolation(
    claimed: &super::proof_term::CapabilityIsolationWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let store = match ir
        .axonstore_specs
        .iter()
        .find(|s| s.name == claimed.store_name)
    {
        Some(s) => s,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "axonstore '{}' not present in artifact",
                    claimed.store_name
                ),
            }
        }
    };

    // Re-derive independently — do NOT trust the witness.
    let actual = derive_capability_isolation_witness(&store.name, &store.capability);

    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    if actual.malformed {
        return CheckOutcome::Refuted {
            reason: format!(
                "axonstore '{}' declares a malformed capability gate {:?} (not a valid §32.g scope: ^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$)",
                actual.store_name, actual.capability
            ),
        };
    }
    CheckOutcome::Verified
}

/// §51.d — re-derive the resource-bound witness from the named subject
/// (endpoint or socket) and verify it against the proof, then render
/// the verdict. Independent of the producer (D51.2): the checker
/// re-reads `retries` / `backpressure_credit` from the artifact and
/// recomputes the bound; a forged witness is rejected because the
/// recomputation disagrees.
fn check_resource_bounds(
    claimed: &ResourceBoundsWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    match claimed {
        ResourceBoundsWitness::EndpointRetry { endpoint_name, .. } => {
            let ep = match ir.endpoints.iter().find(|e| e.name == *endpoint_name) {
                Some(e) => e,
                None => {
                    return CheckOutcome::Refuted {
                        reason: format!(
                            "endpoint '{}' not present in artifact",
                            endpoint_name
                        ),
                    }
                }
            };
            let actual = derive_endpoint_retry_witness(&ep.name, ep.retries);
            if actual != *claimed {
                return CheckOutcome::Refuted {
                    reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                        .to_string(),
                };
            }
            if let ResourceBoundsWitness::EndpointRetry { retries, in_bounds, .. } = &actual {
                if !in_bounds {
                    return CheckOutcome::Refuted {
                        reason: format!(
                            "endpoint '{}' declares retries={} outside the bound [0, {}] (negative is nonsensical; above the ceiling is a retry storm)",
                            ep.name,
                            retries,
                            super::proof_term::MAX_RETRIES
                        ),
                    };
                }
            }
            CheckOutcome::Verified
        }
        ResourceBoundsWitness::SocketCredit { socket_name, .. } => {
            let socket = match ir.sockets.iter().find(|s| s.name == *socket_name) {
                Some(s) => s,
                None => {
                    return CheckOutcome::Refuted {
                        reason: format!(
                            "socket '{}' not present in artifact",
                            socket_name
                        ),
                    }
                }
            };
            // The witness claims a DECLARED credit. If the artifact's
            // socket has no declared credit, the witness disagrees
            // (forged / stale).
            let credit = match socket.backpressure_credit {
                Some(k) => k,
                None => {
                    return CheckOutcome::Refuted {
                        reason: format!(
                            "socket '{}' has no declared backpressure credit in the artifact, but the witness claims one (forged or stale proof)",
                            socket_name
                        ),
                    }
                }
            };
            let actual = derive_socket_credit_witness(&socket.name, credit);
            if actual != *claimed {
                return CheckOutcome::Refuted {
                    reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                        .to_string(),
                };
            }
            if let ResourceBoundsWitness::SocketCredit { credit, positive, .. } = &actual {
                if !positive {
                    return CheckOutcome::Refuted {
                        reason: format!(
                            "socket '{}' declares backpressure credit({}) — a window < 1 deadlocks the §Fase 41.b typed-resource gate",
                            socket.name, credit
                        ),
                    };
                }
            }
            CheckOutcome::Verified
        }
    }
}

/// §51.e — re-derive the shield breach-policy witness from the named
/// shield and verify it against the proof, then render the verdict.
/// Independent of the producer (D51.2): the checker re-reads
/// `on_breach` + `scan` from the artifact and recomputes both facts; a
/// forged witness (claiming `vacuous_halt: false` for a halt shield
/// that scans nothing) is rejected because the recomputation disagrees.
fn check_shield_halt_guarantee(
    claimed: &super::proof_term::ShieldHaltGuaranteeWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let shield = match ir.shields.iter().find(|s| s.name == claimed.shield_name) {
        Some(s) => s,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "shield '{}' not present in artifact",
                    claimed.shield_name
                ),
            }
        }
    };

    // Re-derive independently — do NOT trust the witness.
    let actual =
        derive_shield_halt_witness(&shield.name, &shield.on_breach, &shield.scan);

    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    if !actual.known_policy {
        return CheckOutcome::Refuted {
            reason: format!(
                "shield '{}' declares an unknown on_breach policy {:?} (not in the closed breach-policy catalog)",
                actual.shield_name, actual.on_breach
            ),
        };
    }
    if actual.vacuous_halt {
        return CheckOutcome::Refuted {
            reason: format!(
                "shield '{}' declares `on_breach: halt` but an empty `scan: []` — the halt can never fire (no scan ⟹ no breach ⟹ no halt): a vacuous guarantee",
                actual.shield_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §51.x — re-derive the capability-containment witness from the named
/// endpoint and verify it against the proof, then render the verdict.
/// Independent of the producer (D51.2): the checker re-resolves the
/// `execute_flow`, re-walks its reachable store ops, re-resolves each
/// gate, and recomputes the uncovered set; a forged witness (e.g.
/// hiding an uncovered gate) is rejected because the recomputation
/// disagrees.
fn check_capability_containment(
    claimed: &super::proof_term::CapabilityContainmentWitness,
    ir: &IRProgram,
) -> CheckOutcome {
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

    // Re-derive independently — do NOT trust the witness.
    let actual = derive_capability_containment_witness(
        &ep.name,
        &ep.execute_flow,
        &ep.requires_capabilities,
        ir,
    );

    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    // Verdict. An unresolvable execute_flow cannot be analyzed for
    // store reachability — refuse to certify containment (sound: a
    // missing flow could reach gated stores we cannot see).
    if !actual.flow_resolved {
        return CheckOutcome::Refuted {
            reason: format!(
                "endpoint '{}' executes flow '{}' which is not present in the artifact — cannot certify capability containment",
                actual.endpoint_name, actual.execute_flow
            ),
        };
    }
    if !actual.uncovered_gates.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "endpoint '{}' reaches store(s) gated by capabilit(ies) {:?} that its declared `requires:` {:?} does not cover — a capability leak (a request satisfying the declared requires could reach a store it is not authorized for)",
                actual.endpoint_name, actual.uncovered_gates, actual.declared_requires
            ),
        };
    }
    CheckOutcome::Verified
}
