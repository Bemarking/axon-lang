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
    derive_compliance_coverage_witness, derive_channel_delivery_soundness_witness,
    derive_effect_budgeted_witness, derive_effect_row_soundness_witness,
    derive_endpoint_retry_witness, derive_json_shape_soundness_witness,
    derive_shield_halt_witness, derive_socket_credit_witness, derive_tool_call_soundness_witness,
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
