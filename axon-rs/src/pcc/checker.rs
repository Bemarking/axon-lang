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
    artifact_digest, derive_aggregate_soundness_witnesses,
    derive_capability_containment_witness, derive_capability_isolation_witness,
    derive_channel_egress_witness, derive_compliance_coverage_witness,
    derive_channel_delivery_soundness_witness,
    derive_effect_budgeted_witness, derive_effect_row_soundness_witness,
    derive_endpoint_retry_witness, derive_interruptible_session_witness,
    derive_json_shape_soundness_witness, derive_parked_residual_witness,
    derive_shield_halt_witness, derive_socket_credit_witness, derive_tool_call_soundness_witness,
    derive_upstream_projection_witness,
};
use super::proof_term::{
    CallSoundnessCertificate, ProofTerm, PropertyClass, ResourceBoundsWitness, Witness,
    CALL_INTERRUPT_CAUSES, VALID_SIGN_ALGORITHMS,
};

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
        (PropertyClass::ToolCallSoundness, Witness::ToolCallSoundness(w)) => {
            check_tool_call_soundness(w, ir)
        }
        (PropertyClass::EffectBudgeted, Witness::EffectBudgeted(w)) => {
            check_effect_budgeted(w, ir)
        }
        (PropertyClass::JsonShapeSoundness, Witness::JsonShapeSoundness(w)) => {
            check_json_shape_soundness(w, ir)
        }
        (PropertyClass::ChannelDeliverySoundness, Witness::ChannelDeliverySoundness(w)) => {
            check_channel_delivery_soundness(w, ir)
        }
        (PropertyClass::AggregateSoundness, Witness::AggregateSoundness(w)) => {
            check_aggregate_soundness(w, ir)
        }
        (PropertyClass::ChannelEgressSoundness, Witness::ChannelEgressSoundness(w)) => {
            check_channel_egress_soundness(w, ir)
        }
        (
            PropertyClass::InterruptibleSessionSoundness,
            Witness::InterruptibleSessionSoundness(w),
        ) => check_interruptible_session_soundness(w, ir),
        (PropertyClass::ParkedResidualSoundness, Witness::ParkedResidualSoundness(w)) => {
            check_parked_residual_soundness(w, ir)
        }
        (PropertyClass::UpstreamProjectionSoundness, Witness::UpstreamProjectionSoundness(w)) => {
            check_upstream_projection_soundness(w, ir)
        }
        (PropertyClass::CorsPolicyConsistency, Witness::CorsPolicyConsistency(w)) => {
            check_cors_policy_consistency(w, ir)
        }
        (PropertyClass::TechnicianCommandSafety, Witness::TechnicianCommandSafety(w)) => {
            check_technician_command_safety(w, ir)
        }
        (PropertyClass::CacheSoundness, Witness::CacheSoundness(w)) => {
            check_cache_soundness(w, ir)
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

    // Re-derive independently — do NOT trust the witness. §Fase 53.d:
    // the extension provenance members are re-derived from the SAME
    // artifact (`ir`), so an extension-declared base verifies, while a
    // base no extension declares still refutes. Soundness invariant #1:
    // the verifier reads the artifact's own `extensions`, never an
    // external registry.
    let ext_members = super::generate::extension_effect_members(ir);
    let actual =
        derive_effect_row_soundness_witness(&tool.name, &tool.effect_row, &ext_members);

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

    // Re-derive independently — do NOT trust the witness. §77.a: `sign`
    // participates (a sign-only egress shield is a non-vacuous halt, D77.6).
    let actual = derive_shield_halt_witness(
        &shield.name,
        &shield.on_breach,
        &shield.scan,
        &shield.sign,
    );

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
                "shield '{}' declares `on_breach: halt` but neither `scan:` nor `sign:` — the halt can never fire (nothing enforced ⟹ no breach ⟹ no halt): a vacuous guarantee",
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

/// §58.i — re-derive the tool-call-soundness witness from the named flow
/// + call site and verify it against the proof, then render the verdict.
/// Independent of the producer (D51.2): the checker re-walks the SAME
/// digest-bound IR, locates the call at `call_index`, re-reads the called
/// tool's `parameters:` schema, and recomputes every fact; a forged
/// witness (e.g. hiding an unknown argument or a type mismatch) is
/// rejected because the recomputation disagrees.
fn check_tool_call_soundness(
    claimed: &super::proof_term::ToolCallSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    // Re-derive independently — do NOT trust the witness. `None` ⟹ the
    // flow or the call site named by the witness is absent from this
    // artifact (forged / stale proof).
    let actual = match derive_tool_call_soundness_witness(
        &claimed.flow_name,
        claimed.call_index,
        ir,
    ) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "flow '{}' has no structured `use` call at index {} in this artifact",
                    claimed.flow_name, claimed.call_index
                ),
            }
        }
    };

    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }

    // Verdict on the re-derived (trusted) facts.
    if !actual.schema_present {
        // A schema-less / undeclared tool carries no arg contract — there
        // is nothing to certify, so a proof for it is vacuously verified
        // (generation never emits one; this stays total for a hand-built
        // witness).
        return CheckOutcome::Verified;
    }
    if !actual.unknown_args.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "call to tool '{}' in flow '{}' passes argument(s) {:?} the tool does not declare (declared parameters: {:?})",
                actual.tool_name, actual.flow_name, actual.unknown_args, actual.declared_params
            ),
        };
    }
    if !actual.duplicate_args.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "call to tool '{}' in flow '{}' supplies duplicate argument(s) {:?}",
                actual.tool_name, actual.flow_name, actual.duplicate_args
            ),
        };
    }
    if !actual.missing_required.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "call to tool '{}' in flow '{}' omits required argument(s) {:?}",
                actual.tool_name, actual.flow_name, actual.missing_required
            ),
        };
    }
    if !actual.type_mismatches.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "call to tool '{}' in flow '{}' has literal-argument type mismatch(es) {:?} (each `arg:expected:got`)",
                actual.tool_name, actual.flow_name, actual.type_mismatches
            ),
        };
    }
    CheckOutcome::Verified
}

/// §72.f — check an [`EffectBudgetedWitness`]. Re-derive the budget facts
/// independently from the artifact; refute on disagreement (forgery) or on any
/// budget defect (an unresolved effect, a non-positive limit, an invalid period,
/// or an out-of-catalog `on_exhausted`).
fn check_effect_budgeted(
    claimed: &super::proof_term::EffectBudgetedWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    // Re-derive — do NOT trust the witness. `None` ⟹ the daemon named by the
    // witness is absent, or it carries no budget (forged / stale proof).
    let actual = match derive_effect_budgeted_witness(&claimed.daemon_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "daemon '{}' has no `budget {{ }}` in this artifact",
                    claimed.daemon_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict on the re-derived (trusted) facts.
    if !actual.unresolved_effects.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "daemon '{}' budget targets undefined tool(s) {:?} — no matching `tool` declaration",
                actual.daemon_name, actual.unresolved_effects
            ),
        };
    }
    if !actual.nonpositive_limits.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "daemon '{}' budget has non-positive quota limit(s) {:?} (each `effect:kind`)",
                actual.daemon_name, actual.nonpositive_limits
            ),
        };
    }
    if !actual.invalid_periods.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "daemon '{}' budget has out-of-catalog period(s) {:?} (each `effect:period`; valid: {:?})",
                actual.daemon_name, actual.invalid_periods, super::proof_term::VALID_BUDGET_PERIODS
            ),
        };
    }
    if !actual.on_exhausted_valid {
        return CheckOutcome::Refuted {
            reason: format!(
                "daemon '{}' budget has an out-of-catalog `on_exhausted` policy '{}' (valid: {:?})",
                actual.daemon_name, actual.on_exhausted, super::proof_term::VALID_ON_EXHAUSTED
            ),
        };
    }
    CheckOutcome::Verified
}

/// §73.g — check a [`JsonShapeSoundnessWitness`]. Re-derive the store's
/// lens shapes independently from the artifact; refute on disagreement
/// (forgery) or on any shape that does not resolve to a declared struct
/// `type` (the `axon-T840` invariant, now independently verified).
fn check_json_shape_soundness(
    claimed: &super::proof_term::JsonShapeSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    // Re-derive — do NOT trust the witness. `None` ⟹ the store named by the
    // witness is absent, or carries no inline `Json<T>` lens column (a
    // forged / stale proof).
    let actual = match derive_json_shape_soundness_witness(&claimed.store_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "axonstore '{}' declares no inline `Json<T>` lens column in this artifact",
                    claimed.store_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict on the re-derived (trusted) facts: every lens shape must
    // resolve to a declared struct `type`.
    if !actual.unresolved_shapes.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axonstore '{}' declares `Json<T>` lens column(s) {:?} (each `column:Shape`) \
                 whose shape is not a declared `type` — the lens cannot be field-checked, so \
                 navigation soundness is unprovable. Declare the struct, or use open `Json`.",
                actual.store_name, actual.unresolved_shapes
            ),
        };
    }
    CheckOutcome::Verified
}

/// §74.g — check a [`ChannelDeliverySoundnessWitness`]. Re-derive the
/// channel's producer/consumer facts from the artifact; refute on
/// disagreement (forgery) or when a consumed channel has NO producer (a
/// `listen`er that can never fire — nothing `emit`s to it).
fn check_channel_delivery_soundness(
    claimed: &super::proof_term::ChannelDeliverySoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match derive_channel_delivery_soundness_witness(&claimed.channel_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "channel '{}' has no `daemon` `listen`er in this artifact (no delivery \
                     contract to certify)",
                    claimed.channel_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict: a consumed channel with no producer never fires.
    if !actual.has_producer {
        return CheckOutcome::Refuted {
            reason: format!(
                "channel '{}' has a `daemon` `listen`er but NO producer — nothing `emit`s to \
                 it, so the listener can never fire. Add an `emit {}(…)` in a flow, or remove \
                 the listener (the Kivi brief #39 defect, now machine-checked).",
                actual.channel_name, actual.channel_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §76.e — check an [`AggregateSoundnessWitness`]. Re-derive ALL aggregate
/// sites from the artifact (through the SAME runtime clause parser the
/// engines execute) and require the claimed witness to be one of them —
/// a witness about a site the artifact does not contain is a forgery.
/// Then the verdict: any recorded violation refutes (the rendered SQL
/// would not aggregate exactly the declared columns through the closed
/// catalog).
fn check_aggregate_soundness(
    claimed: &super::proof_term::AggregateSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let derived = derive_aggregate_soundness_witnesses(ir);
    if !derived.iter().any(|w| w == claimed) {
        return CheckOutcome::Refuted {
            reason: format!(
                "no aggregate-retrieve site in this artifact matches the witness \
                 (flow '{}', store '{}', aggregate '{}') — forged or stale proof",
                claimed.flow_name, claimed.store_name, claimed.aggregate
            ),
        };
    }
    if !claimed.violations.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "aggregate-retrieve on store '{}' in flow '{}' is UNSOUND: {}",
                claimed.store_name,
                claimed.flow_name,
                claimed.violations.join("; ")
            ),
        };
    }
    CheckOutcome::Verified
}

/// §77.b — check a [`ChannelEgressSoundnessWitness`]. Re-derive the
/// channel's egress facts from the artifact (publish sites resolved
/// against the DECLARED shields — never the IR's pre-resolved stamps);
/// refute on disagreement (a forged `egress_sign` handle), an algorithm
/// outside the closed signing catalog, or a non-durable egress channel
/// (D77.6 — a webhook promise backed by an ephemeral buffer dies
/// unwitnessed with the process).
fn check_channel_egress_soundness(
    claimed: &super::proof_term::ChannelEgressSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match derive_channel_egress_witness(&claimed.channel_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "channel '{}' carries no egress contract in this artifact (no declared \
                     `egress_sign`, no signing publish site) — forged or stale proof",
                    claimed.channel_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict 1: the handle's marking must be exactly what the program
    // derives — a stamp with no deriving publish site (or a site the
    // stamp hides) is a forged egress surface.
    if actual.declared_egress_sign != actual.derived_sign {
        return CheckOutcome::Refuted {
            reason: format!(
                "channel '{}' egress marking '{}' disagrees with the program's publish \
                 sites (derived '{}') — the egress surface is not derivable from the \
                 source (forged handle or stale lowering)",
                actual.channel_name, actual.declared_egress_sign, actual.derived_sign
            ),
        };
    }
    // Verdict 2: closed signing catalog.
    if !VALID_SIGN_ALGORITHMS.contains(&actual.derived_sign.as_str()) {
        return CheckOutcome::Refuted {
            reason: format!(
                "channel '{}' declares egress signing '{}' — not in the closed signing \
                 catalog {:?}",
                actual.channel_name, actual.derived_sign, VALID_SIGN_ALGORITHMS
            ),
        };
    }
    // Verdict 3: durable egress (D77.6) — signed external delivery must
    // inherit the §74 outbox's at-least-once.
    if !actual.durable {
        return CheckOutcome::Refuted {
            reason: format!(
                "channel '{}' is egress-published under shield '{}' (`sign: {}`) but its \
                 persistence is '{}' — signed egress requires `persistence: \
                 persistent_axonstore` (axon-T848)",
                actual.channel_name, actual.shield_ref, actual.derived_sign, actual.persistence
            ),
        };
    }
    CheckOutcome::Verified
}

/// §83.c — independent checker for [`PropertyClass::CorsPolicyConsistency`].
/// Re-derives the whole-program witness and rejects on ANY of: a forged/
/// stale witness, an unresolved `cors:` reference (T856), a wildcard+
/// credentials violation (T853), or a cross-method path conflict (T857).
fn check_cors_policy_consistency(
    claimed: &super::proof_term::CorsPolicyConsistencyWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match super::generate::derive_cors_policy_consistency_witness(ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: "no cors contract exists in this artifact (no `cors` declarations, \
                         no `cors:` references) — forged or stale proof"
                    .to_string(),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    if !actual.all_references_resolve {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T856 an `axonendpoint.cors:` reference does not resolve to a declared \
                 `cors` — declared: {:?}, referenced: {:?}",
                actual.declared_cors_names, actual.endpoint_cors_refs
            ),
        };
    }
    if !actual.wildcard_credential_violations.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T853 cors declaration(s) combine an any-origin `allow_origins` with \
                 `allow_credentials: true` (CORS spec violation): {:?}",
                actual.wildcard_credential_violations
            ),
        };
    }
    if !actual.cross_method_conflicts.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T857 axonendpoints sharing a path disagree on `cors:` \
                 (endpoint_a, endpoint_b) pairs: {:?}",
                actual.cross_method_conflicts
            ),
        };
    }
    CheckOutcome::Verified
}

/// §84.c — independent checker for [`PropertyClass::TechnicianCommandSafety`].
/// Re-derives the per-tool witness and rejects on ANY of: a forged/stale
/// witness, a missing argv template on a bash tool (T858), an unbound or
/// partial argv placeholder (T859), or a destructive command with no reachable
/// confirm/deny branch (T860). This proof travels with the artifact to the
/// deploy gate — the last line before an IR reaches a real machine.
fn check_technician_command_safety(
    claimed: &super::proof_term::TechnicianCommandSafetyWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let tool = match ir.tools.iter().find(|t| t.name == claimed.tool_name) {
        Some(t) => t,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "no technician tool '{}' exists in this artifact — forged or stale proof",
                    claimed.tool_name
                ),
            }
        }
    };
    let actual = match super::generate::derive_technician_command_safety_witness(tool, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "tool '{}' is not a technician tool (no `target:`) — forged or stale proof",
                    claimed.tool_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    if !actual.argv_present {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T858 technician tool '{}' binds `target:` on `provider: bash` but declares \
                 no `argv:` template",
                actual.tool_name
            ),
        };
    }
    if !actual.unbound_placeholders.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T859 technician tool '{}' has argv placeholder(s) not bound to a declared \
                 parameter: {:?}",
                actual.tool_name, actual.unbound_placeholders
            ),
        };
    }
    if !actual.partial_tokens.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T859 technician tool '{}' has partial/fused argv token(s) (a `${{param}}` \
                 must be a whole argv element): {:?}",
                actual.tool_name, actual.partial_tokens
            ),
        };
    }
    if !actual.confirm_branch_reachable {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T860 technician tool '{}' is `risk: destructive` but its bound session '{}' \
                 offers no reachable `branch{{ approved / denied }}` confirmation",
                actual.tool_name, actual.session_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §85.c — independent checker for [`PropertyClass::CacheSoundness`]. Re-derives
/// the whole-program cache witness and rejects on ANY of: a forged/stale
/// witness, more than one `default: true` (T863), a widened cache without a
/// finite ttl (T865), or an unresolved reference (T864).
fn check_cache_soundness(
    claimed: &super::proof_term::CacheSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match super::generate::derive_cache_soundness_witness(ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: "no cache contract exists in this artifact (no `cache` declarations, no \
                         `tool.cache:` references) — forged or stale proof"
                    .to_string(),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    if actual.default_count > 1 {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T863 {} caches declare `default: true` (must be ≤ 1)",
                actual.default_count
            ),
        };
    }
    if !actual.widened_without_ttl.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T865 cache(s) widen `apply_to_effects:` beyond [pure] with no `ttl:`: {:?}",
                actual.widened_without_ttl
            ),
        };
    }
    if !actual.unresolved_refs.is_empty() {
        return CheckOutcome::Refuted {
            reason: format!(
                "axon-T864 unresolved cache/channel reference(s): {:?}",
                actual.unresolved_refs
            ),
        };
    }
    CheckOutcome::Verified
}

/// §79.c — verify an [`InterruptibleSessionSoundnessWitness`]. The checker
/// re-derives every fact from the IR session steps (D51.2) and then applies the
/// four soundness verdicts of the 79.a paper §6.2: closed-catalog signal, both
/// arms present, and a two-exit handler.
fn check_interruptible_session_soundness(
    claimed: &super::proof_term::InterruptibleSessionSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match derive_interruptible_session_witness(
        &claimed.session_name,
        &claimed.role_name,
        &claimed.signal,
        ir,
    ) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "no interrupt region with signal '{}' in session '{}' role '{}' — \
                     forged or stale proof",
                    claimed.signal, claimed.session_name, claimed.role_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict 1: closed CallInterruptCause catalog (D79.2).
    if !actual.signal_in_catalog {
        return CheckOutcome::Refuted {
            reason: format!(
                "interrupt signal '{}' is not a CallInterruptCause {:?}",
                actual.signal, CALL_INTERRUPT_CAUSES
            ),
        };
    }
    // Verdict 2: both a body and a resumable handler.
    if !actual.has_body || !actual.has_handler {
        return CheckOutcome::Refuted {
            reason: format!(
                "interrupt region in session '{}' role '{}' is missing its {} arm",
                actual.session_name,
                actual.role_name,
                if !actual.has_body { "body" } else { "resumable handler" }
            ),
        };
    }
    // Verdict 3: two-exit handler (D79.11a).
    if !actual.handler_reaches_exit {
        return CheckOutcome::Refuted {
            reason: format!(
                "interrupt handler in session '{}' role '{}' does not reach a two-exit \
                 terminal (`resume` or `end`, D79.11a)",
                actual.session_name, actual.role_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §79.f — verify a [`ParkedResidualSoundnessWitness`]: the socket's parked κ is
/// AAD-bound + recoverable (`reconnect: cognitive_state`) and its at-rest
/// retention is governed (`legal_basis`). Re-derived from the IR (D51.2).
fn check_parked_residual_soundness(
    claimed: &super::proof_term::ParkedResidualSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match derive_parked_residual_witness(&claimed.socket_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "socket '{}' carries no interruptible session in this artifact (no parked-\
                     residual obligation) — forged or stale proof",
                    claimed.socket_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict 1: the park must be AAD-bound + recoverable (§41.g).
    if !actual.reconnect_cognitive_state {
        return CheckOutcome::Refuted {
            reason: format!(
                "socket '{}' parks an interruptible residual but does not declare `reconnect: \
                 cognitive_state` — the at-rest κ would be an unsealed second store (paper §7)",
                actual.socket_name
            ),
        };
    }
    // Verdict 2: the at-rest retention must be governed.
    if !actual.legal_basis_declared {
        return CheckOutcome::Refuted {
            reason: format!(
                "socket '{}' parks a possibly-PII-bearing residual but declares no `legal_basis` \
                 — the at-rest retention TTL has no legal ceiling (paper §7)",
                actual.socket_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §80 — verify an [`UpstreamProjectionSoundnessWitness`]: the upstream's
/// `map:` projection is a total, unambiguous cover of the bound role's
/// message set (T849 re-derived) and its `resolve:`/`secret:` values are
/// policy-shaped config keys (T850 re-derived). Everything is recomputed
/// from the IR (D51.2); a forged `projection_total: true` cannot survive.
fn check_upstream_projection_soundness(
    claimed: &super::proof_term::UpstreamProjectionSoundnessWitness,
    ir: &IRProgram,
) -> CheckOutcome {
    let actual = match derive_upstream_projection_witness(&claimed.upstream_name, ir) {
        Some(w) => w,
        None => {
            return CheckOutcome::Refuted {
                reason: format!(
                    "upstream '{}' does not exist in this artifact — forged or stale proof",
                    claimed.upstream_name
                ),
            }
        }
    };
    if actual != *claimed {
        return CheckOutcome::Refuted {
            reason: "witness disagrees with artifact re-derivation (forged or stale proof)"
                .to_string(),
        };
    }
    // Verdict 1: no message may fall through untranscoded (§80's core claim).
    if !actual.projection_total {
        return CheckOutcome::Refuted {
            reason: format!(
                "upstream '{}': the `map:` projection is not a total, unambiguous cover of \
                 session '{}' role '{}' — a message would cross the boundary untranscoded (T849)",
                actual.upstream_name, actual.session_name, actual.role_name
            ),
        };
    }
    // Verdict 2: no vendor coordinate may live in source (config, not code).
    if !actual.config_keys_valid {
        return CheckOutcome::Refuted {
            reason: format!(
                "upstream '{}': `resolve:`/`secret:` are not policy-shaped config keys — an \
                 endpoint or credential literal is in the artifact (T850)",
                actual.upstream_name
            ),
        };
    }
    CheckOutcome::Verified
}

/// §79.f — the overall verdict for a [`CallSoundnessCertificate`]: EVERY
/// composed member must independently verify against `ir`. Returns the first
/// non-`Verified` member's outcome (so the caller sees *why* a call is not
/// certified sound), or `Verified` when all hold. An empty certificate (a
/// socket with no interruptible session) is vacuously `Verified` — there is no
/// call-soundness obligation to discharge.
pub fn check_call_soundness_certificate(
    cert: &CallSoundnessCertificate,
    ir: &IRProgram,
) -> CheckOutcome {
    for proof in &cert.proofs {
        let outcome = check_proof(proof, ir);
        if outcome != CheckOutcome::Verified {
            return outcome;
        }
    }
    CheckOutcome::Verified
}
