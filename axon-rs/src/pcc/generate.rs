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

use crate::ir_nodes::{IRProgram, IRSessionStep};

use super::effects;
use super::proof_term::{
    AggregateSoundnessWitness, CallSoundnessCertificate, CapabilityContainmentWitness,
    AuthorizationCoverageWitness,
    CapabilityIsolationWitness,
    ChannelEgressSoundnessWitness,
    ChannelDeliverySoundnessWitness, ComplianceCoverageWitness, CorsPolicyConsistencyWitness,
    EffectBudgetedWitness,
    EffectRowSoundnessWitness, InterruptibleSessionSoundnessWitness, JsonShapeSoundnessWitness,
    ParkedResidualSoundnessWitness, ProofTerm, PropertyClass,
    CacheSoundnessWitness, ForgeSoundnessWitness, ResourceBoundsWitness, SavantSoundnessWitness,
    WardenSoundnessWitness,
    ShieldHaltGuaranteeWitness, TechnicianCommandSafetyWitness, ToolCallSoundnessWitness,
    UpstreamProjectionSoundnessWitness, Witness,
    CALL_INTERRUPT_CAUSES, MAX_RETRIES, VALID_BREACH_POLICIES, VALID_BUDGET_PERIODS,
    VALID_ON_EXHAUSTED,
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
pub fn generate_compliance_coverage_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ep in &ir.endpoints {
        if ep.compliance.is_empty() {
            continue;
        }
        let witness =
            derive_compliance_coverage_witness(&ep.name, &ep.compliance, &ep.shield_ref, ir);
        proofs.push(ProofTerm {
            property: PropertyClass::ComplianceCoverage,
            artifact_digest: digest.clone(),
            witness: Witness::ComplianceCoverage(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §89.c — derive an [`AuthorizationCoverageWitness`] for one endpoint. Pure +
/// total. Shared with the checker's re-derivation path (D51.2): both the prover
/// and the verifier compute coverage the SAME way, so the witnesses agree by
/// construction, and a forged `authorized: true` is caught by recomputation.
pub fn derive_authorization_coverage_witness(
    ep: &crate::ir_nodes::IRAxonEndpoint,
) -> AuthorizationCoverageWitness {
    let dispatches = !ep.execute_flow.is_empty();
    let has_requires = !ep.requires_capabilities.is_empty();
    let has_shield = !ep.shield_ref.is_empty();
    let has_compliance = !ep.compliance.is_empty();
    let public = ep.public;
    // The §89.b rule EXACTLY: covered by ≥1 discipline OR the explicit opt-out.
    let authorized = has_requires || has_shield || has_compliance || public;
    AuthorizationCoverageWitness {
        endpoint_name: ep.name.clone(),
        dispatches,
        has_requires,
        has_shield,
        has_compliance,
        public,
        authorized,
    }
}

/// §89.c — generate an AuthorizationCoverage proof for every DISPATCHING
/// `axonendpoint` (non-empty `execute:` — a real trust boundary). A
/// non-dispatching endpoint crosses no boundary → no proof (mirrors "no
/// compliance → no compliance proof"). The doctrine `every_boundary_is_guarded`
/// as an independently-verifiable, deploy-gated fact.
pub fn generate_authorization_coverage_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ep in &ir.endpoints {
        if ep.execute_flow.is_empty() {
            continue;
        }
        proofs.push(ProofTerm {
            property: PropertyClass::AuthorizationCoverage,
            artifact_digest: digest.clone(),
            witness: Witness::AuthorizationCoverage(derive_authorization_coverage_witness(ep)),
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
    // §Fase 53.d — the extension-declared PROVENANCE members the checker
    // honors, re-derived INDEPENDENTLY from the artifact's own
    // `extensions` by the caller (see `extension_effect_members`). Empty
    // for an artifact with no `extension` declarations (byte-identical
    // pre-§53 behavior).
    extension_effect_members: &std::collections::HashSet<String>,
) -> EffectRowSoundnessWitness {
    let declared_effects = canonical_classes(effect_row);

    let mut unknown_bases = Vec::new();
    let mut missing_qualifier = Vec::new();
    let mut invalid_stream_qualifier = Vec::new();
    let mut has_pure = false;
    let mut has_other = false;

    for entry in &declared_effects {
        // §Fase 53.d / §53.c.2 — a PROVENANCE member is accepted VERBATIM
        // (the full entry). Two sources: an `extension`-declared member,
        // or the built-in `epistemic:<level>` confidence axis. Both carry
        // no runtime capability (invariant #2), so neither is an unknown
        // base nor subject to qualifier enforcement; both count as "other"
        // for purity (a tool declaring `pure` + a provenance effect is
        // still a contradiction).
        if extension_effect_members.contains(entry) || effects::is_epistemic_provenance(entry) {
            has_other = true;
            continue;
        }
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

/// §Fase 53.d — the set of extension-declared PROVENANCE effect members
/// the PCC checker honors, re-derived INDEPENDENTLY from the artifact's
/// own `extensions` (soundness invariant #1 — the verifier never trusts
/// an external registry or the producer's compiler; D51.2). Invariant #2
/// is enforced here independently: a member whose base IS a canonical
/// enforceable base is NOT a provenance member (it is not "rescued" by
/// the extension), so it is excluded and falls through to the canonical
/// base/qualifier checks. Both the prover and the checker call this over
/// the SAME `ir`, so the re-derived witnesses agree by construction.
pub fn extension_effect_members(ir: &IRProgram) -> std::collections::HashSet<String> {
    let mut set = std::collections::HashSet::new();
    for ext in &ir.extensions {
        if ext.category != "effects" {
            continue;
        }
        for m in &ext.members {
            let (base, _) = effects::split_effect(&m.name);
            if !effects::is_known_base(base) {
                set.insert(m.name.clone());
            }
        }
    }
    set
}

/// §51.b — generate effect-row-soundness proofs for every tool in `ir`
/// that declares a non-empty `effects: <...>` row. Tools with no
/// declared effects produce no proof (nothing to certify).
pub fn generate_effect_row_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    // §Fase 53.d — provenance members declared by the artifact's own
    // extensions, re-derived once for the whole program.
    let ext_members = extension_effect_members(ir);
    let mut proofs = Vec::new();
    for tool in &ir.tools {
        if tool.effect_row.is_empty() {
            continue;
        }
        let witness =
            derive_effect_row_soundness_witness(&tool.name, &tool.effect_row, &ext_members);
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
    let malformed = !capability.is_empty() && !crate::parser::is_valid_capability_slug(capability);
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
pub fn generate_capability_isolation_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for store in &ir.axonstore_specs {
        if store.capability.is_empty() {
            continue;
        }
        let witness = derive_capability_isolation_witness(&store.name, &store.capability);
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
pub fn derive_endpoint_retry_witness(endpoint_name: &str, retries: i64) -> ResourceBoundsWitness {
    ResourceBoundsWitness::EndpointRetry {
        endpoint_name: endpoint_name.to_string(),
        retries,
        in_bounds: (0..=MAX_RETRIES).contains(&retries),
    }
}

/// §51.d — derive the credit-positivity witness for one socket's
/// DECLARED credit window. Pure + total. Shared with the checker.
pub fn derive_socket_credit_witness(socket_name: &str, credit: i64) -> ResourceBoundsWitness {
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
pub fn generate_resource_bounds_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
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

/// §51.e — derive a [`ShieldHaltGuaranteeWitness`] for one shield's
/// breach policy. Pure + total. Shared with the checker (D51.2).
///
/// §Fase 77.a (D77.6) — a shield whose enforcement is `sign:` (egress
/// signing) is NOT vacuous: the signature is what it enforces, so
/// `on_breach: halt` has a breach to react to (a delivery it refuses to
/// sign). `vacuous_halt` therefore requires BOTH `scan` and `sign` empty.
pub fn derive_shield_halt_witness(
    shield_name: &str,
    on_breach: &str,
    scan: &[String],
    sign: &str,
) -> ShieldHaltGuaranteeWitness {
    let known_policy = VALID_BREACH_POLICIES.contains(&on_breach);
    let scan_count = scan.len();
    let vacuous_halt = on_breach == "halt" && scan.is_empty() && sign.is_empty();
    ShieldHaltGuaranteeWitness {
        shield_name: shield_name.to_string(),
        on_breach: on_breach.to_string(),
        known_policy,
        scan_count,
        vacuous_halt,
    }
}

/// §51.e — generate shield-halt-guarantee proofs for every shield in
/// `ir` that declares a non-empty `on_breach` policy. Shields with no
/// breach policy declared produce no proof (no guarantee to certify).
pub fn generate_shield_halt_guarantee_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for shield in &ir.shields {
        if shield.on_breach.is_empty() {
            continue;
        }
        let witness = derive_shield_halt_witness(
            &shield.name,
            &shield.on_breach,
            &shield.scan,
            &shield.sign,
        );
        proofs.push(ProofTerm {
            property: PropertyClass::ShieldHaltGuarantee,
            artifact_digest: digest.clone(),
            witness: Witness::ShieldHaltGuarantee(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §51.x — recursively collect every store name a flow's steps reach
/// (Retrieve / Persist / Mutate / Purge), descending into BOTH
/// conditional branches + the for-in loop body. A SOUND
/// over-approximation: every statically-reachable store op is counted
/// (we do not know which branch fires at runtime, so both count), so a
/// containment proof never misses a reachable gate. Total + bounded.
///
/// ## §51.x.3 — no-silent-gap invariant (compiler-enforced)
///
/// The match below is **exhaustive — there is NO `_` wildcard arm**.
/// Every [`IRFlowNode`](crate::ir_nodes::IRFlowNode) variant is
/// classified deliberately into exactly one of three buckets:
///
/// - **store op** — names a capability-gated `axonstore_specs` entry
///   (the four CRUD verbs Retrieve/Persist/Mutate/Purge are, by
///   construction, the ONLY axonstore-touching nodes);
/// - **nesting** — carries a nested `Vec<IRFlowNode>` body to recurse
///   into (ONLY `Conditional` then/else + `ForIn` body);
/// - **leaf** — carries neither an axonstore reference nor a nested
///   body, so it contributes nothing to the reachable-gate set.
///
/// Because there is no wildcard, **adding a new `IRFlowNode` variant
/// breaks compilation here** until a maintainer classifies it — the
/// reachability walk can never silently miss a future node that adds a
/// store reference or a nested body. (A `cargo test` source gate also
/// pins the absence of a wildcard so a refactor cannot reintroduce one.)
///
/// Notes on the leaf classification:
/// - `Remember` / `Recall` reference the cognitive **memory** subsystem
///   (`memory_target` / `memory_source`), a DIFFERENT subsystem from the
///   capability-gated axonstore; if memory ever becomes capability-gated
///   that is a NEW property class, not this walk.
/// - `Par` / `Deliberate` / `Consensus` / `Forge` / `Stream` / `Transact`
///   are payload-free in the IR (no nested `IRFlowNode` body).
/// - If a flow-invocation node (cf. the top-level [`IRRun`](crate::ir_nodes::IRRun),
///   which today lives ONLY at program level and is unreachable from a
///   flow body) ever enters `IRFlowNode`, this is where transitive
///   cross-flow reachability must be REOPENED (§51.x.3).
fn collect_store_accesses(steps: &[crate::ir_nodes::IRFlowNode], out: &mut Vec<String>) {
    use crate::ir_nodes::IRFlowNode as N;
    for step in steps {
        match step {
            // ── store ops — the only axonstore-touching nodes ──
            N::Retrieve(s) => out.push(s.store_name.clone()),
            N::Persist(s) => out.push(s.store_name.clone()),
            N::Mutate(s) => out.push(s.store_name.clone()),
            N::Purge(s) => out.push(s.store_name.clone()),
            // ── nesting — the only nodes with a nested body ──
            N::Conditional(c) => {
                collect_store_accesses(&c.then_body, out);
                collect_store_accesses(&c.else_body, out);
            }
            N::ForIn(f) => collect_store_accesses(&f.body, out),
            // §Fase 51.a — `quant` carries a nested flow body; descend so any
            // store op reachable inside it is still soundness-checked.
            N::Quant(q) => collect_store_accesses(&q.body, out),
            // §Fase 88.a — `warden` carries a nested flow body; descend so any
            // store op reachable inside it is still soundness-checked.
            N::Warden(w) => collect_store_accesses(&w.body, out),
            // §Fase 51.d.2 — `yield` is a leaf (measurement value, no store op).
            N::Yield(_) => {}
            // §Fase 52.a — a `listen` handler body can contain store ops (a
            // daemon cleaner that `persist`s); descend so they're soundness-
            // checked, like the quant body above.
            N::Listen(l) => collect_store_accesses(&l.body, out),
            // §Fase 52.c — `run <Flow>` invokes a flow by NAME (no nested body),
            // so it touches no store DIRECTLY. Transitive store access through
            // the invoked flow is the cross-flow reachability this fn's header
            // flagged — deferred to the PCC DaemonSoundness follow-up; a leaf here.
            N::Run(_) => {}
            // ── leaves — no axonstore ref, no nested body. Listed
            // EXPLICITLY (no `_` wildcard) so a future variant forces a
            // deliberate classification at compile time (§51.x.3). ──
            N::Step(_)
            | N::Probe(_)
            | N::Reason(_)
            | N::Validate(_)
            | N::Refine(_)
            | N::Weave(_)
            | N::UseTool(_)
            | N::Remember(_)
            | N::Recall(_)
            | N::Let(_)
            | N::Return(_)
            | N::Break(_)
            | N::Continue(_)
            | N::LambdaDataApply(_)
            | N::Par(_)
            | N::Hibernate(_)
            | N::Deliberate(_)
            | N::Consensus(_)
            | N::Forge(_)
            | N::Focus(_)
            | N::Associate(_)
            | N::Aggregate(_)
            | N::Explore(_)
            | N::Ingest(_)
            | N::ShieldApply(_)
            | N::Stream(_)
            | N::Navigate(_)
            | N::Drill(_)
            | N::Trail(_)
            | N::Corroborate(_)
            | N::OtsApply(_)
            | N::MandateApply(_)
            | N::ComputeApply(_)
            | N::DaemonStep(_)
            | N::Emit(_)
            | N::Publish(_)
            | N::Discover(_)
            | N::Transact(_) => {}
        }
    }
}

/// §51.x — derive a [`CapabilityContainmentWitness`] for one endpoint
/// against the program IR. Pure + total. Shared with the checker
/// (D51.2). Resolves `execute_flow` in `ir.flows`, walks its reachable
/// store ops, resolves each store's capability gate, and computes the
/// uncovered set (`reached_gates \ declared_requires`).
pub fn derive_capability_containment_witness(
    endpoint_name: &str,
    execute_flow: &str,
    declared_requires_raw: &[String],
    ir: &IRProgram,
) -> CapabilityContainmentWitness {
    let declared_requires = canonical_classes(declared_requires_raw);

    let flow = ir.flows.iter().find(|f| f.name == execute_flow);
    let flow_resolved = flow.is_some();

    // Reachable store names (sound over-approximation).
    let mut reached_stores: Vec<String> = Vec::new();
    if let Some(f) = flow {
        collect_store_accesses(&f.steps, &mut reached_stores);
    }

    // Resolve each reached store to its capability gate (non-empty only).
    let mut reached_gates: Vec<String> = reached_stores
        .iter()
        .filter_map(|name| {
            ir.axonstore_specs
                .iter()
                .find(|s| &s.name == name)
                .map(|s| s.capability.clone())
        })
        .filter(|cap| !cap.is_empty())
        .collect();
    reached_gates.sort();
    reached_gates.dedup();

    // uncovered = reached_gates \ declared_requires (the gates the flow
    // reaches that the endpoint does not declare). Reuses the canonical
    // `covers` predicate (required \ provided).
    let mut uncovered_gates: Vec<String> =
        crate::esk::compliance::covers(declared_requires.iter(), reached_gates.iter())
            .into_iter()
            .collect();
    uncovered_gates.sort();

    CapabilityContainmentWitness {
        endpoint_name: endpoint_name.to_string(),
        execute_flow: execute_flow.to_string(),
        flow_resolved,
        declared_requires,
        reached_gates,
        uncovered_gates,
    }
}

/// §51.x — generate capability-containment proofs. One proof per
/// apx/axonendpoint where the property is non-trivial: the endpoint
/// declares `requires:` OR its flow reaches at least one gated store.
/// (An endpoint with no requires that reaches no gated store has
/// nothing to certify.) The "reaches a gated store with no requires"
/// case IS generated — that is the capability-leak finding.
pub fn generate_capability_containment_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ep in &ir.endpoints {
        let witness = derive_capability_containment_witness(
            &ep.name,
            &ep.execute_flow,
            &ep.requires_capabilities,
            ir,
        );
        // Skip trivial subjects: no declared requires AND no reached
        // gates (nothing to certify).
        if witness.declared_requires.is_empty() && witness.reached_gates.is_empty() {
            continue;
        }
        proofs.push(ProofTerm {
            property: PropertyClass::CapabilityContainment,
            artifact_digest: digest.clone(),
            witness: Witness::CapabilityContainment(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 58.i — ToolCallSoundness ───────────────────────────────────

/// §58.i — mirror of the §58.d `infer_arg_literal_type` (a type-checker
/// private fn). PCC re-states the spec INDEPENDENTLY (D51.2 — the
/// verifier never trusts the compiler): only an UNAMBIGUOUS literal is
/// typed. A bare identifier (`x` — the frontend stored the value as a
/// bare string, so the literal `"x"` and the reference `x` are
/// indistinguishable) and a `${…}` interpolation are runtime-resolved →
/// `None` (skipped, so no false positives). Cross-stack spec pin: a
/// drift gate keeps this in lockstep with the frontend rule.
fn infer_arg_literal_type(value: &str) -> Option<&'static str> {
    if value == "true" || value == "false" {
        return Some("Bool");
    }
    if value.contains('.') && value.parse::<f64>().is_ok() {
        return Some("Float");
    }
    let digits = value.strip_prefix('-').unwrap_or(value);
    if !digits.is_empty() && digits.chars().all(|c| c.is_ascii_digit()) {
        return Some("Int");
    }
    None
}

/// §58.i — mirror of the §58.d `tool_arg_types_align`. `Any` accepts
/// anything; an `Int` coerces into a `Float` parameter; otherwise the
/// declared base type (stripping the `?` optional marker + any
/// `<generic>`) must equal the inferred literal type.
fn tool_arg_types_align(value_ty: &str, decl_ty: &str) -> bool {
    let base = decl_ty.trim_end_matches('?').split('<').next().unwrap_or(decl_ty);
    base == "Any" || base == value_ty || (base == "Float" && value_ty == "Int")
}

/// §58.i — collect, in deterministic walk order, every NAMED-args
/// `use <Tool>(k = v, …)` call in a flow's steps, recursing into
/// conditional branches + for-in bodies (a `use` cannot nest in a step
/// body — §54.a — but the IR model permits it inside flow-level control
/// flow, so the walk descends there). The legacy `use <Tool> on <arg>`
/// form has empty `named_args` and is excluded (schema-less, D5).
///
/// Like [`collect_store_accesses`], the match is EXHAUSTIVE — no `_`
/// wildcard — so a future `IRFlowNode` variant carrying a nested body
/// breaks compilation here until a maintainer classifies it (a wildcard
/// could let a nested `use` call silently escape soundness checking). A
/// source gate pins the absence of a wildcard.
fn collect_named_use_tool_calls<'a>(
    steps: &'a [crate::ir_nodes::IRFlowNode],
    out: &mut Vec<&'a crate::ir_nodes::IRUseToolStep>,
) {
    use crate::ir_nodes::IRFlowNode as N;
    for step in steps {
        match step {
            // ── target — a structured (keyword-arg) tool dispatch ──
            N::UseTool(u) => {
                if !u.named_args.is_empty() {
                    out.push(u);
                }
            }
            // ── nesting — the only nodes with a nested IRFlowNode body ──
            N::Conditional(c) => {
                collect_named_use_tool_calls(&c.then_body, out);
                collect_named_use_tool_calls(&c.else_body, out);
            }
            N::ForIn(f) => collect_named_use_tool_calls(&f.body, out),
            // §Fase 51.a — `quant` carries a nested flow body; descend so a
            // structured `use` inside it cannot escape soundness checking.
            N::Quant(q) => collect_named_use_tool_calls(&q.body, out),
            // §Fase 88.a — `warden` carries a nested flow body; descend so a
            // structured `use` inside it cannot escape soundness checking.
            N::Warden(w) => collect_named_use_tool_calls(&w.body, out),
            // §Fase 51.d.2 — `yield` is a leaf (no nested body, no `use`).
            N::Yield(_) => {}
            // §Fase 52.a — a `listen` handler body can contain a `use <Tool>`;
            // descend so it is soundness-checked.
            N::Listen(l) => collect_named_use_tool_calls(&l.body, out),
            // §Fase 52.c — `run <Flow>` invokes a flow by name (no nested body).
            N::Run(_) => {}
            // ── leaves — no nested body. Listed EXPLICITLY (no `_`
            // wildcard) so a future nesting variant forces a deliberate
            // classification at compile time. ──
            N::Step(_)
            | N::Probe(_)
            | N::Reason(_)
            | N::Validate(_)
            | N::Refine(_)
            | N::Weave(_)
            | N::Remember(_)
            | N::Recall(_)
            | N::Let(_)
            | N::Return(_)
            | N::Break(_)
            | N::Continue(_)
            | N::LambdaDataApply(_)
            | N::Par(_)
            | N::Hibernate(_)
            | N::Deliberate(_)
            | N::Consensus(_)
            | N::Forge(_)
            | N::Focus(_)
            | N::Associate(_)
            | N::Aggregate(_)
            | N::Explore(_)
            | N::Ingest(_)
            | N::ShieldApply(_)
            | N::Stream(_)
            | N::Navigate(_)
            | N::Drill(_)
            | N::Trail(_)
            | N::Corroborate(_)
            | N::OtsApply(_)
            | N::MandateApply(_)
            | N::ComputeApply(_)
            | N::DaemonStep(_)
            | N::Emit(_)
            | N::Publish(_)
            | N::Discover(_)
            | N::Retrieve(_)
            | N::Persist(_)
            | N::Mutate(_)
            | N::Purge(_)
            | N::Transact(_) => {}
        }
    }
}

/// §58.i — sort + dedup a name list into the canonical witness form.
fn canonical_names(raw: &[String]) -> Vec<String> {
    let mut v = raw.to_vec();
    v.sort();
    v.dedup();
    v
}

/// §58.i — derive a [`ToolCallSoundnessWitness`] for the `use Tool(k=v)`
/// call at `call_index` (deterministic walk order) in flow `flow_name`.
/// Pure + total. Shared with the checker's re-derivation path (D51.2) —
/// the checker re-walks the SAME digest-bound IR, so producer + verifier
/// compute identically. `None` when the flow is absent or the index is
/// out of range (the checker renders that as a "call site not present"
/// refutation).
pub fn derive_tool_call_soundness_witness(
    flow_name: &str,
    call_index: usize,
    ir: &IRProgram,
) -> Option<ToolCallSoundnessWitness> {
    let flow = ir.flows.iter().find(|f| f.name == flow_name)?;
    let mut calls = Vec::new();
    collect_named_use_tool_calls(&flow.steps, &mut calls);
    let call = calls.get(call_index)?;

    let tool_name = call.tool_name.clone();
    let arg_pairs: Vec<(String, String)> = call
        .named_args
        .iter()
        .map(|a| (a.name.clone(), a.value.clone()))
        .collect();
    let arg_names: Vec<String> = arg_pairs.iter().map(|(n, _)| n.clone()).collect();

    // The called tool's declared schema (name, type, optional). Empty if
    // the tool is undeclared or schema-less.
    let params: Vec<(String, String, bool)> = ir
        .tools
        .iter()
        .find(|t| t.name == tool_name)
        .map(|t| {
            t.parameters
                .iter()
                .map(|p| (p.name.clone(), p.type_name.clone(), p.optional))
                .collect()
        })
        .unwrap_or_default();
    let schema_present = !params.is_empty();
    let declared_params = canonical_names(
        &params.iter().map(|(n, _, _)| n.clone()).collect::<Vec<_>>(),
    );

    // Duplicates: an arg name supplied more than once.
    let mut seen = std::collections::HashSet::new();
    let mut dup = std::collections::HashSet::new();
    for name in &arg_names {
        if !seen.insert(name.clone()) {
            dup.insert(name.clone());
        }
    }
    let duplicate_args = canonical_names(&dup.into_iter().collect::<Vec<_>>());

    // Unknown: an arg naming no declared parameter.
    let unknown_args = canonical_names(
        &arg_names
            .iter()
            .filter(|n| !params.iter().any(|(p, _, _)| &p == n))
            .cloned()
            .collect::<Vec<_>>(),
    );

    // Missing required: a non-optional param not supplied.
    let mut missing_required: Vec<String> = params
        .iter()
        .filter(|(p, _, optional)| !optional && !arg_names.iter().any(|n| n == p))
        .map(|(p, _, _)| p.clone())
        .collect();
    missing_required.sort();
    missing_required.dedup();

    // Literal type mismatches (conservative — decidable literals only).
    let mut type_mismatches: Vec<String> = Vec::new();
    for (name, value) in &arg_pairs {
        if let Some((_, decl_ty, _)) = params.iter().find(|(p, _, _)| p == name) {
            if let Some(val_ty) = infer_arg_literal_type(value) {
                if !tool_arg_types_align(val_ty, decl_ty) {
                    type_mismatches.push(format!("{name}:{decl_ty}:{val_ty}"));
                }
            }
        }
    }
    type_mismatches.sort();
    type_mismatches.dedup();

    Some(ToolCallSoundnessWitness {
        flow_name: flow_name.to_string(),
        call_index,
        tool_name,
        arg_names,
        declared_params,
        schema_present,
        unknown_args,
        duplicate_args,
        missing_required,
        type_mismatches,
    })
}

/// §58.i — generate tool-call-soundness proofs: one proof per structured
/// `use <Tool>(k = v, …)` call whose called tool declares a NON-EMPTY
/// `parameters:` schema. A call to a schema-less tool, an undeclared
/// tool, or the legacy `on <arg>` form carries no contract → no proof
/// (nothing to certify — mirrors "no effects → no effect-row proof").
pub fn generate_tool_call_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for flow in &ir.flows {
        let mut calls = Vec::new();
        collect_named_use_tool_calls(&flow.steps, &mut calls);
        for (call_index, _) in calls.iter().enumerate() {
            // Derive from (flow, index) so producer + checker share the
            // exact path. `None` is unreachable here (we just walked the
            // same flow), but stay total.
            let Some(witness) = derive_tool_call_soundness_witness(&flow.name, call_index, ir)
            else {
                continue;
            };
            // Nothing to certify for a schema-less / undeclared tool.
            if !witness.schema_present {
                continue;
            }
            proofs.push(ProofTerm {
                property: PropertyClass::ToolCallSoundness,
                artifact_digest: digest.clone(),
                witness: Witness::ToolCallSoundness(witness),
                axon_version: axon_version.to_string(),
            });
        }
    }
    proofs
}

// ── §Fase 72.f — EffectBudgeted ──────────────────────────────────────

/// §72.f — re-derive an [`EffectBudgetedWitness`] for the daemon named
/// `daemon_name`. `None` if no such daemon exists, or it has no `budget`
/// (nothing to certify). RE-DERIVES every fact from the artifact — the same
/// computation the checker runs — so producer + checker agree by construction.
pub fn derive_effect_budgeted_witness(
    daemon_name: &str,
    ir: &IRProgram,
) -> Option<EffectBudgetedWitness> {
    let daemon = ir.daemons.iter().find(|d| d.name == daemon_name)?;
    let budget = daemon.budget.as_ref()?;

    // The program's declared tools — the resolution surface.
    let declared_tools = canonical_names(&ir.tools.iter().map(|t| t.name.clone()).collect::<Vec<_>>());
    let declared: std::collections::HashSet<&str> =
        declared_tools.iter().map(String::as_str).collect();

    let mut unresolved_effects = Vec::new();
    let mut nonpositive_limits = Vec::new();
    let mut invalid_periods = Vec::new();
    for q in &budget.quotas {
        if !declared.contains(q.effect.as_str()) {
            unresolved_effects.push(q.effect.clone());
        }
        if q.limit <= 0 {
            nonpositive_limits.push(format!("{}:{}", q.effect, q.kind));
        }
        if !VALID_BUDGET_PERIODS.contains(&q.period.as_str()) {
            invalid_periods.push(format!("{}:{}", q.effect, q.period));
        }
    }

    Some(EffectBudgetedWitness {
        daemon_name: daemon_name.to_string(),
        quota_count: budget.quotas.len(),
        declared_tools,
        unresolved_effects: canonical_names(&unresolved_effects),
        nonpositive_limits: {
            let mut v = nonpositive_limits;
            v.sort();
            v
        },
        invalid_periods: {
            let mut v = invalid_periods;
            v.sort();
            v
        },
        on_exhausted: budget.on_exhausted.clone(),
        on_exhausted_valid: VALID_ON_EXHAUSTED.contains(&budget.on_exhausted.as_str()),
    })
}

/// §72.f — generate effect-budgeted proofs: one per daemon that declares a
/// `budget { … }`. A daemon with no budget carries no contract → no proof
/// (mirrors "no effects → no effect-row proof").
pub fn generate_effect_budgeted_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for daemon in &ir.daemons {
        if daemon.budget.is_none() {
            continue;
        }
        let Some(witness) = derive_effect_budgeted_witness(&daemon.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::EffectBudgeted,
            artifact_digest: digest.clone(),
            witness: Witness::EffectBudgeted(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 73.g — JsonShapeSoundness ──────────────────────────────────

/// §73.g — derive a [`JsonShapeSoundnessWitness`] for one store's column
/// shape lenses against the program IR. Pure + total. Shared with the
/// checker's re-derivation path so producer + verifier compute identically
/// (D51.2). `None` when the store is absent OR declares no inline
/// `Json<T>` lens column — no contract → no proof. (A `manifest_ref` /
/// `env_var` schema form carries no INLINE lens shape to certify; only the
/// inline form's declared shapes are in the artifact.)
pub fn derive_json_shape_soundness_witness(
    store_name: &str,
    ir: &IRProgram,
) -> Option<JsonShapeSoundnessWitness> {
    let store = ir.axonstore_specs.iter().find(|s| s.name == store_name)?;
    let columns = match store.column_schema.as_ref()? {
        crate::ir_nodes::IRStoreColumnSchema::Inline { columns } => columns,
        _ => return None,
    };
    // The lens sites: columns carrying a `Json<T>` shape, sorted by
    // (column, shape) for a canonical witness.
    let mut lens: Vec<(String, String)> = columns
        .iter()
        .filter_map(|c| c.json_shape.as_ref().map(|s| (c.name.clone(), s.clone())))
        .collect();
    if lens.is_empty() {
        return None;
    }
    lens.sort();

    let declared_types =
        canonical_names(&ir.types.iter().map(|t| t.name.clone()).collect::<Vec<_>>());
    let declared: std::collections::HashSet<&str> =
        declared_types.iter().map(String::as_str).collect();

    let lens_columns: Vec<String> = lens.iter().map(|(c, s)| format!("{c}:{s}")).collect();
    // `lens` is already sorted, so the filtered subset stays sorted.
    let unresolved_shapes: Vec<String> = lens
        .iter()
        .filter(|(_, s)| !declared.contains(s.as_str()))
        .map(|(c, s)| format!("{c}:{s}"))
        .collect();

    Some(JsonShapeSoundnessWitness {
        store_name: store_name.to_string(),
        declared_types,
        lens_columns,
        unresolved_shapes,
    })
}

/// §73.g — generate JsonShapeSoundness proofs: one per `axonstore` that
/// declares ≥1 inline `Json<T>` lens column. A store with no shape lens
/// carries no contract → no proof.
pub fn generate_json_shape_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for store in &ir.axonstore_specs {
        let Some(witness) = derive_json_shape_soundness_witness(&store.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::JsonShapeSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::JsonShapeSoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 74.g — ChannelDeliverySoundness ────────────────────────────

/// §74.g — every channel `emit`ted to (a PRODUCER) anywhere in the program:
/// walk all flow bodies + every daemon listener body, recursing into nested
/// `if` / `for` bodies. Shared by producer + checker (D51.2).
fn collect_emitted_channels(ir: &IRProgram) -> std::collections::HashSet<String> {
    fn walk(steps: &[crate::ir_nodes::IRFlowNode], out: &mut std::collections::HashSet<String>) {
        use crate::ir_nodes::IRFlowNode as N;
        for step in steps {
            match step {
                N::Emit(e) => {
                    out.insert(e.channel_ref.clone());
                }
                N::Conditional(c) => {
                    walk(&c.then_body, out);
                    walk(&c.else_body, out);
                }
                N::ForIn(f) => walk(&f.body, out),
                // A daemon listener body can itself `emit` (a relay).
                N::Listen(l) => walk(&l.body, out),
                _ => {}
            }
        }
    }
    let mut out = std::collections::HashSet::new();
    for flow in &ir.flows {
        walk(&flow.steps, &mut out);
    }
    for daemon in &ir.daemons {
        for listener in &daemon.listeners {
            walk(&listener.body, &mut out);
        }
    }
    out
}

/// §74.g — every channel a `daemon` `listen`s on (a non-cron event
/// listener — the consumers). Cron listeners are timer-driven, not channel
/// consumers.
fn collect_listened_channels(ir: &IRProgram) -> std::collections::HashSet<String> {
    let mut out = std::collections::HashSet::new();
    for daemon in &ir.daemons {
        for l in &daemon.listeners {
            if axon_frontend::cron::cron_expr(&l.channel).is_none() {
                out.insert(l.channel.clone());
            }
        }
    }
    out
}

/// §74.g — derive a [`ChannelDeliverySoundnessWitness`] for one channel.
/// Pure + total. `None` when the channel is absent OR has NO consumer (a
/// daemon `listen`er) — a channel with no listener carries no delivery
/// contract, so no proof is generated (mirrors "no effects → no
/// effect-row proof").
pub fn derive_channel_delivery_soundness_witness(
    channel_name: &str,
    ir: &IRProgram,
) -> Option<ChannelDeliverySoundnessWitness> {
    let ch = ir.channels.iter().find(|c| c.name == channel_name)?;
    let consumers = collect_listened_channels(ir);
    if !consumers.contains(channel_name) {
        return None;
    }
    let producers = collect_emitted_channels(ir);
    Some(ChannelDeliverySoundnessWitness {
        channel_name: channel_name.to_string(),
        persistence: ch.persistence.clone(),
        qos: ch.qos.clone(),
        has_producer: producers.contains(channel_name),
        has_consumer: true,
    })
}

/// §74.g — generate ChannelDeliverySoundness proofs: one per `channel`
/// that a daemon `listen`s on.
pub fn generate_channel_delivery_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ch in &ir.channels {
        let Some(witness) = derive_channel_delivery_soundness_witness(&ch.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::ChannelDeliverySoundness,
            artifact_digest: digest.clone(),
            witness: Witness::ChannelDeliverySoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 76.e — AggregateSoundness ──────────────────────────────────

/// §76.e — every aggregate-`retrieve` site in the program: walk all flow
/// bodies + every daemon listener body, recursing into nested `if` /
/// `for` bodies. A site is any retrieve with a non-empty `aggregate:` OR
/// `group_by:` (the latter alone is a T845 violation the witness records).
/// Shared by producer + checker (D51.2). Sorted + deduped so the
/// derivation is canonical.
pub fn derive_aggregate_soundness_witnesses(
    ir: &IRProgram,
) -> Vec<AggregateSoundnessWitness> {
    fn witness_for(
        flow_name: &str,
        s: &crate::ir_nodes::IRRetrieveStep,
    ) -> Option<AggregateSoundnessWitness> {
        if s.aggregate.trim().is_empty() && s.group_by.trim().is_empty() {
            return None;
        }
        let mut w = AggregateSoundnessWitness {
            flow_name: flow_name.to_string(),
            store_name: s.store_name.clone(),
            aggregate: s.aggregate.clone(),
            group_by: s.group_by.clone(),
            order_by: s.order_by.clone(),
            limit_expr: s.limit_expr.clone(),
            function: String::new(),
            column: String::new(),
            group_columns: Vec::new(),
            violations: Vec::new(),
        };
        // The SAME closed-catalog parser the engines run (D51.2 — the
        // checker re-derives through it too, so the proof certifies the
        // exact runtime semantics, not a reimplementation).
        match crate::store::filter::parse_aggregate_clause(
            &s.aggregate,
            &s.group_by,
            &s.order_by,
            &s.limit_expr,
        ) {
            Ok(Some((spec, groups))) => {
                w.function = spec.func.label().to_string();
                w.column = spec.column.unwrap_or_default();
                w.group_columns = groups;
            }
            // Unreachable for a selected site (empty-both is filtered
            // above) — kept total.
            Ok(None) => {}
            Err(e) => w.violations.push(e.to_string()),
        }
        Some(w)
    }
    fn walk(
        flow_name: &str,
        steps: &[crate::ir_nodes::IRFlowNode],
        out: &mut Vec<AggregateSoundnessWitness>,
    ) {
        use crate::ir_nodes::IRFlowNode as N;
        for step in steps {
            match step {
                N::Retrieve(s) => {
                    if let Some(w) = witness_for(flow_name, s) {
                        out.push(w);
                    }
                }
                N::Conditional(c) => {
                    walk(flow_name, &c.then_body, out);
                    walk(flow_name, &c.else_body, out);
                }
                N::ForIn(f) => walk(flow_name, &f.body, out),
                N::Listen(l) => walk(flow_name, &l.body, out),
                _ => {}
            }
        }
    }
    let mut out = Vec::new();
    for flow in &ir.flows {
        walk(&flow.name, &flow.steps, &mut out);
    }
    for daemon in &ir.daemons {
        let subject = format!("daemon:{}", daemon.name);
        for listener in &daemon.listeners {
            walk(&subject, &listener.body, &mut out);
        }
    }
    out.sort_by(|a, b| {
        (&a.flow_name, &a.store_name, &a.aggregate, &a.group_by)
            .cmp(&(&b.flow_name, &b.store_name, &b.aggregate, &b.group_by))
    });
    out.dedup();
    out
}

/// §76.e — generate AggregateSoundness proofs: one per aggregate-retrieve
/// site. A malformed site still generates its (refutable) proof — the
/// §52 deploy gate then rejects the bundle, fail-closed.
pub fn generate_aggregate_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    derive_aggregate_soundness_witnesses(ir)
        .into_iter()
        .map(|witness| ProofTerm {
            property: PropertyClass::AggregateSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::AggregateSoundness(witness),
            axon_version: axon_version.to_string(),
        })
        .collect()
}

// ── §Fase 77.b — ChannelEgressSoundness ──────────────────────────────

/// §77.b — the first publish site (flows in declaration order, then daemon
/// listeners) targeting `channel_name` whose shield declares `sign:`.
/// Returns `(sign, shield_ref)`. The derivation NEVER trusts the IR's
/// pre-resolved `IRPublish.sign` stamp — it re-resolves the named shield
/// against the artifact's shield list (D51.2: a forged stamp is caught
/// because the checker recomputes). Mirrors the walk order of the
/// frontend's `mark_egress_channels` (first site wins) so producer and
/// lowering agree.
fn derive_first_signing_publish(
    channel_name: &str,
    ir: &IRProgram,
) -> Option<(String, String)> {
    fn walk(
        steps: &[crate::ir_nodes::IRFlowNode],
        channel_name: &str,
        ir: &IRProgram,
        found: &mut Option<(String, String)>,
    ) {
        use crate::ir_nodes::IRFlowNode as N;
        for step in steps {
            if found.is_some() {
                return;
            }
            match step {
                N::Publish(p) if p.channel_ref == channel_name => {
                    let sign = ir
                        .shields
                        .iter()
                        .find(|s| s.name == p.shield_ref)
                        .map(|s| s.sign.clone())
                        .unwrap_or_default();
                    if !sign.is_empty() {
                        *found = Some((sign, p.shield_ref.clone()));
                    }
                }
                N::Conditional(c) => {
                    walk(&c.then_body, channel_name, ir, found);
                    walk(&c.else_body, channel_name, ir, found);
                }
                N::ForIn(f) => walk(&f.body, channel_name, ir, found),
                N::Par(p) => {
                    for branch in &p.branches {
                        walk(branch, channel_name, ir, found);
                    }
                }
                N::Listen(l) => walk(&l.body, channel_name, ir, found),
                N::Quant(q) => walk(&q.body, channel_name, ir, found),
                _ => {}
            }
        }
    }
    let mut found = None;
    for flow in &ir.flows {
        walk(&flow.steps, channel_name, ir, &mut found);
        if found.is_some() {
            return found;
        }
    }
    for daemon in &ir.daemons {
        for listener in &daemon.listeners {
            walk(&listener.body, channel_name, ir, &mut found);
            if found.is_some() {
                return found;
            }
        }
    }
    found
}

/// §77.b — derive a [`ChannelEgressSoundnessWitness`] for one channel.
/// Pure + total. `None` when the channel carries NO egress contract:
/// neither a declared `egress_sign` on its handle nor a derivable signing
/// publish site (mirrors "no effects → no effect-row proof").
pub fn derive_channel_egress_witness(
    channel_name: &str,
    ir: &IRProgram,
) -> Option<ChannelEgressSoundnessWitness> {
    let ch = ir.channels.iter().find(|c| c.name == channel_name)?;
    let (derived_sign, shield_ref) =
        derive_first_signing_publish(channel_name, ir).unwrap_or_default();
    if ch.egress_sign.is_empty() && derived_sign.is_empty() {
        return None;
    }
    Some(ChannelEgressSoundnessWitness {
        channel_name: channel_name.to_string(),
        declared_egress_sign: ch.egress_sign.clone(),
        derived_sign,
        shield_ref,
        persistence: ch.persistence.clone(),
        durable: ch.persistence == "persistent_axonstore",
    })
}

/// §77.b — generate ChannelEgressSoundness proofs: one per channel with an
/// egress contract (declared or derivable). An unsound site still generates
/// its (refutable) proof — the §52 deploy gate then rejects the bundle,
/// fail-closed.
pub fn generate_channel_egress_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for ch in &ir.channels {
        let Some(witness) = derive_channel_egress_witness(&ch.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::ChannelEgressSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::ChannelEgressSoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 79.c — InterruptibleSessionSoundness ───────────────────────────────

/// §79.c — does an IR handler step-sequence reach a two-exit terminal (`resume`
/// or `end`) on every path (D79.11a)? The checker's own re-derivation of the
/// §79.c type-checker's `handler_reaches_exit` (D51.2 — PCC states the spec
/// independently). A terminal choice is well-formed iff every arm reaches one.
fn ir_handler_reaches_exit(steps: &[IRSessionStep]) -> bool {
    match steps.last() {
        Some(s) if s.op == "resume" || s.op == "end" => true,
        Some(s) if s.op == "select" || s.op == "branch" => {
            !s.branches.is_empty() && s.branches.iter().all(|b| ir_handler_reaches_exit(&b.steps))
        }
        _ => false,
    }
}

/// §79.c — the first `interrupt` step (by pre-order walk) in `steps` whose
/// `on <Signal>` matches `signal`. Descends into nested arms (v1 forbids nested
/// interrupts, but the walk is total either way).
fn find_interrupt_step<'a>(steps: &'a [IRSessionStep], signal: &str) -> Option<&'a IRSessionStep> {
    for s in steps {
        if s.op == "interrupt" && s.message_type == signal {
            return Some(s);
        }
        for b in &s.branches {
            if let Some(found) = find_interrupt_step(&b.steps, signal) {
                return Some(found);
            }
        }
    }
    None
}

/// §79.c — every distinct interrupt signal declared in `steps` (canonical:
/// sorted + deduped), so one region ↦ one proof even if the same cause recurs.
fn interrupt_signals(steps: &[IRSessionStep]) -> Vec<String> {
    let mut out = Vec::new();
    fn walk(steps: &[IRSessionStep], out: &mut Vec<String>) {
        for s in steps {
            if s.op == "interrupt" {
                out.push(s.message_type.clone());
            }
            for b in &s.branches {
                walk(&b.steps, out);
            }
        }
    }
    walk(steps, &mut out);
    out.sort();
    out.dedup();
    out
}

/// §79.c — re-derive the InterruptibleSessionSoundness witness for the interrupt
/// region located by `(session, role, signal)`. `None` if no such region exists
/// in the artifact (a forged / stale proof then refutes).
pub fn derive_interruptible_session_witness(
    session_name: &str,
    role_name: &str,
    signal: &str,
    ir: &IRProgram,
) -> Option<InterruptibleSessionSoundnessWitness> {
    let session = ir.sessions.iter().find(|s| s.name == session_name)?;
    let role = session.roles.iter().find(|r| r.name == role_name)?;
    let step = find_interrupt_step(&role.steps, signal)?;
    let has_body = step.branches.iter().any(|b| b.label == "body");
    let handler = step.branches.iter().find(|b| b.label == "handler");
    Some(InterruptibleSessionSoundnessWitness {
        session_name: session_name.to_string(),
        role_name: role_name.to_string(),
        signal: step.message_type.clone(),
        signal_in_catalog: CALL_INTERRUPT_CAUSES.contains(&step.message_type.as_str()),
        has_body,
        has_handler: handler.is_some(),
        handler_reaches_exit: handler
            .map(|h| ir_handler_reaches_exit(&h.steps))
            .unwrap_or(false),
    })
}

/// §79.c — generate InterruptibleSessionSoundness proofs: one per interrupt
/// region declared in any session role. An unsound region (bogus signal,
/// missing arm, handler with no exit) still gets its refutable proof — the §52
/// deploy gate then rejects the bundle fail-closed.
pub fn generate_interruptible_session_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for session in &ir.sessions {
        for role in &session.roles {
            for signal in interrupt_signals(&role.steps) {
                let Some(witness) =
                    derive_interruptible_session_witness(&session.name, &role.name, &signal, ir)
                else {
                    continue;
                };
                proofs.push(ProofTerm {
                    property: PropertyClass::InterruptibleSessionSoundness,
                    artifact_digest: digest.clone(),
                    witness: Witness::InterruptibleSessionSoundness(witness),
                    axon_version: axon_version.to_string(),
                });
            }
        }
    }
    proofs
}

// ── §Fase 79.f — ParkedResidualSoundness + CallSoundnessCertificate ──────────

/// §79.f — re-derive the ParkedResidualSoundness witness for `socket_name`.
/// `None` if the socket does not carry an interruptible session (no residual is
/// ever parked at rest → no obligation → no proof).
pub fn derive_parked_residual_witness(
    socket_name: &str,
    ir: &IRProgram,
) -> Option<ParkedResidualSoundnessWitness> {
    let socket = ir.sockets.iter().find(|s| s.name == socket_name)?;
    let session = ir.sessions.iter().find(|s| s.name == socket.protocol);
    let session_has_interrupt = session
        .map(|s| {
            s.roles
                .iter()
                .any(|r| !interrupt_signals(&r.steps).is_empty())
        })
        .unwrap_or(false);
    if !session_has_interrupt {
        return None;
    }
    Some(ParkedResidualSoundnessWitness {
        socket_name: socket_name.to_string(),
        session_name: socket.protocol.clone(),
        session_has_interrupt,
        reconnect_cognitive_state: socket.reconnect,
        legal_basis_declared: socket
            .legal_basis
            .as_ref()
            .map(|b| !b.is_empty())
            .unwrap_or(false),
    })
}

/// §79.f — one ParkedResidualSoundness proof per socket carrying an
/// interruptible session. A socket that parks a residual without `reconnect:
/// cognitive_state` or without a `legal_basis` still gets its refutable proof.
pub fn generate_parked_residual_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for socket in &ir.sockets {
        let Some(witness) = derive_parked_residual_witness(&socket.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::ParkedResidualSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::ParkedResidualSoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §80 — collect the distinct message types a compiled session role
/// sends/receives, walking select/branch arms and §79 interrupt body+handler
/// (a message only exchanged inside a handler still crosses the wire).
/// Order-preserving first-occurrence dedup — the checker compares these
/// vectors verbatim, so derivation order must be deterministic.
fn collect_ir_role_messages(
    steps: &[axon_frontend::ir_nodes::IRSessionStep],
    sends: &mut Vec<String>,
    receives: &mut Vec<String>,
) {
    for step in steps {
        match step.op.as_str() {
            "send" => {
                if !sends.contains(&step.message_type) {
                    sends.push(step.message_type.clone());
                }
            }
            "receive" => {
                if !receives.contains(&step.message_type) {
                    receives.push(step.message_type.clone());
                }
            }
            "select" | "branch" | "interrupt" => {
                for b in &step.branches {
                    collect_ir_role_messages(&b.steps, sends, receives);
                }
            }
            _ => {}
        }
    }
}

/// §80 — the T850 charset law, re-derived: a config key is lowercase
/// `[a-z0-9][a-z0-9_.-]*` (the compile-time mirror of the enterprise
/// `SecretKeyPolicy`). A URL (`:`/`/`) or a typical credential literal
/// (uppercase) cannot satisfy it.
fn is_policy_shaped_config_key(key: &str) -> bool {
    let mut chars = key.chars();
    let head_ok = chars.next().is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit());
    head_ok && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '_' | '.' | '-'))
}

/// §80 — derive the [`UpstreamProjectionSoundnessWitness`] for one upstream
/// from the IR alone (pure; shared by the generator and, by re-derivation,
/// the checker — D51.2). `None` if the upstream does not exist.
pub fn derive_upstream_projection_witness(
    upstream_name: &str,
    ir: &IRProgram,
) -> Option<UpstreamProjectionSoundnessWitness> {
    let up = ir.upstreams.iter().find(|u| u.name == upstream_name)?;

    // Required sets — from the bound role (empty if the binding is broken;
    // a broken binding also fails totality below, so the proof refutes).
    let mut required_sends = Vec::new();
    let mut required_receives = Vec::new();
    let bound_role = ir
        .sessions
        .iter()
        .find(|s| s.name == up.protocol)
        .and_then(|s| s.roles.iter().find(|r| r.name == up.role));
    if let Some(role) = bound_role {
        collect_ir_role_messages(&role.steps, &mut required_sends, &mut required_receives);
    }

    // Covered sets — from the map rules (dedup, source order).
    let mut covered_sends = Vec::new();
    let mut covered_receives = Vec::new();
    for r in &up.map {
        let bucket = if r.direction == "send" { &mut covered_sends } else { &mut covered_receives };
        if !bucket.contains(&r.message) {
            bucket.push(r.message.clone());
        }
    }

    // Totality + unambiguity — the T849 law re-derived from the artifact.
    let mut total = bound_role.is_some();
    for (dir, required) in [("send", &required_sends), ("receive", &required_receives)] {
        for msg in required.iter() {
            let n = up.map.iter().filter(|r| r.direction == dir && &r.message == msg).count();
            if n != 1 {
                total = false;
            }
        }
    }
    for r in &up.map {
        let known = if r.direction == "send" {
            required_sends.contains(&r.message)
        } else {
            required_receives.contains(&r.message)
        };
        if !known {
            total = false;
        }
    }
    // Discriminator keys mirror the §80.c checker exactly: no `when` ⇒
    // equality ("type", Some(<MessageName>)); `when "f" = "v"` ⇒ equality
    // (f, Some(v)); `when "f"` ⇒ PRESENCE (f, None). Equality dispatches
    // before presence at runtime, so only identical keys are ambiguous.
    let receive_json: Vec<(String, Option<String>)> = up
        .map
        .iter()
        .filter(|r| r.direction == "receive" && r.framing == "json")
        .map(|r| match (&r.when_field, &r.when_value) {
            (None, _) => ("type".to_string(), Some(r.message.clone())),
            (Some(f), Some(v)) => (f.clone(), Some(v.clone())),
            (Some(f), None) => (f.clone(), None),
        })
        .collect();
    for (i, a) in receive_json.iter().enumerate() {
        if receive_json.iter().skip(i + 1).any(|b| a == b) {
            total = false;
        }
    }
    if up.map.iter().filter(|r| r.direction == "receive" && r.framing == "binary").count() > 1 {
        total = false;
    }

    Some(UpstreamProjectionSoundnessWitness {
        upstream_name: up.name.clone(),
        session_name: up.protocol.clone(),
        role_name: up.role.clone(),
        required_sends,
        required_receives,
        covered_sends,
        covered_receives,
        projection_total: total,
        config_keys_valid: is_policy_shaped_config_key(&up.resolve) && is_policy_shaped_config_key(&up.secret),
    })
}

/// §80 — one UpstreamProjectionSoundness proof per `upstream`. An upstream
/// with a partial projection or literal-shaped config still gets its
/// refutable proof — the checker refutes it, the deploy gate blocks it.
pub fn generate_upstream_projection_soundness_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for up in &ir.upstreams {
        let Some(witness) = derive_upstream_projection_witness(&up.name, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::UpstreamProjectionSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::UpstreamProjectionSoundness(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

/// §79.f — the unified **`CallSoundnessCertificate`**: for one socket bundle,
/// compose the interruptible-session soundness of its session, the parked-
/// residual soundness of the socket, and the socket's resource (credit) bound
/// into ONE deploy-time artifact — the "can this call ever misbehave" question
/// asked once, before a single call happens. Composition is NOT a mere
/// conjunction (D79.8): `ParkedResidualSoundness` is the genuinely-new member
/// interruption introduces (the data-at-rest surface, paper §7).
///
/// The enterprise serving layer (§79.f ENT) extends the bundle with the
/// flow-scoped shield + budget proofs it can resolve; this OSS core composes
/// the socket-derivable members. `None` if the socket does not exist.
pub fn generate_call_soundness_certificate(
    socket_name: &str,
    ir: &IRProgram,
    axon_version: &str,
) -> Option<CallSoundnessCertificate> {
    let socket = ir.sockets.iter().find(|s| s.name == socket_name)?;
    let session_name = socket.protocol.clone();
    let mut proofs = Vec::new();

    // (1) InterruptibleSessionSoundness — the socket's session.
    proofs.extend(
        generate_interruptible_session_soundness_proofs(ir, axon_version)
            .into_iter()
            .filter(|p| {
                matches!(&p.witness,
                    Witness::InterruptibleSessionSoundness(w) if w.session_name == session_name)
            }),
    );
    // (2) ParkedResidualSoundness — the socket's data-at-rest surface (new).
    proofs.extend(
        generate_parked_residual_soundness_proofs(ir, axon_version)
            .into_iter()
            .filter(|p| {
                matches!(&p.witness,
                    Witness::ParkedResidualSoundness(w) if w.socket_name == socket_name)
            }),
    );
    // (3) ResourceBounds — the socket's credit-window bound.
    proofs.extend(
        generate_resource_bounds_proofs(ir, axon_version)
            .into_iter()
            .filter(|p| p.witness.subject_name() == socket_name),
    );

    Some(CallSoundnessCertificate {
        socket_name: socket_name.to_string(),
        session_name,
        artifact_digest: artifact_digest(ir),
        axon_version: axon_version.to_string(),
        proofs,
    })
}

// ── §Fase 83.c — CorsPolicyConsistency ───────────────────────────────────────

/// §83.c — re-derive the whole-program CORS witness from `ir.cors_policies`
/// + `ir.endpoints`. "No contract → no proof" (the standing convention): a
/// program with no `cors` declarations AND no `cors_ref` anywhere returns
/// `None` — there is nothing to certify.
pub fn derive_cors_policy_consistency_witness(ir: &IRProgram) -> Option<CorsPolicyConsistencyWitness> {
    if ir.cors_policies.is_empty() && ir.endpoints.iter().all(|e| e.cors_ref.is_empty()) {
        return None;
    }
    let declared_cors_names: Vec<String> =
        ir.cors_policies.iter().map(|c| c.name.clone()).collect();
    let endpoint_cors_refs: Vec<(String, String)> = ir
        .endpoints
        .iter()
        .filter(|e| !e.cors_ref.is_empty())
        .map(|e| (e.name.clone(), e.cors_ref.clone()))
        .collect();
    let all_references_resolve = endpoint_cors_refs
        .iter()
        .all(|(_, r)| declared_cors_names.contains(r));
    let wildcard_credential_violations: Vec<String> = ir
        .cors_policies
        .iter()
        .filter(|c| c.allow_credentials && c.allow_origins.iter().any(|o| o == "*"))
        .map(|c| c.name.clone())
        .collect();
    // Cross-method path consistency: same shape as the §83.c type-checker
    // pass (axon-T857), re-derived from the compiled IR instead of the AST.
    let mut by_path: std::collections::HashMap<&str, (&str, &str)> = std::collections::HashMap::new();
    let mut cross_method_conflicts: Vec<(String, String)> = Vec::new();
    for ep in &ir.endpoints {
        if ep.path.is_empty() {
            continue;
        }
        match by_path.get(ep.path.as_str()) {
            None => {
                by_path.insert(ep.path.as_str(), (ep.name.as_str(), ep.cors_ref.as_str()));
            }
            Some((first_name, first_ref)) => {
                if *first_ref != ep.cors_ref {
                    cross_method_conflicts.push((first_name.to_string(), ep.name.clone()));
                }
            }
        }
    }
    Some(CorsPolicyConsistencyWitness {
        declared_cors_names,
        endpoint_cors_refs,
        all_references_resolve,
        wildcard_credential_violations,
        cross_method_conflicts,
    })
}

/// §83.c — generate the (at most one) CorsPolicyConsistency proof for `ir`.
/// Program-wide, so this is a Vec of length 0 or 1, unlike most generators.
pub fn generate_cors_policy_consistency_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    match derive_cors_policy_consistency_witness(ir) {
        Some(witness) => vec![ProofTerm {
            property: PropertyClass::CorsPolicyConsistency,
            artifact_digest: artifact_digest(ir),
            witness: Witness::CorsPolicyConsistency(witness),
            axon_version: axon_version.to_string(),
        }],
        None => Vec::new(),
    }
}

// ── §Fase 84.c — TechnicianCommandSafety ─────────────────────────────────────

/// §84.c — does this IR session-step sequence contain a reachable
/// `branch{ approved / denied }`? Mirror of the frontend
/// `type_checker::session_has_confirm_branch`, re-derived on the compiled IR.
fn ir_session_has_confirm_branch(steps: &[axon_frontend::ir_nodes::IRSessionStep]) -> bool {
    for step in steps {
        if step.op == "branch" {
            let has_approved = step
                .branches
                .iter()
                .any(|b| b.label == axon_frontend::technician::CONFIRM_APPROVED_LABEL);
            let has_denied = step
                .branches
                .iter()
                .any(|b| b.label == axon_frontend::technician::CONFIRM_DENIED_LABEL);
            if has_approved && has_denied {
                return true;
            }
        }
        for b in &step.branches {
            if ir_session_has_confirm_branch(&b.steps) {
                return true;
            }
        }
    }
    false
}

/// §84.c — re-derive the technician-safety witness for one `target:`-bound
/// tool. `None` for a tool that is not a technician tool (no `target:`) — "no
/// contract → no proof" (the standing convention).
pub fn derive_technician_command_safety_witness(
    tool: &axon_frontend::ir_nodes::IRToolSpec,
    ir: &IRProgram,
) -> Option<TechnicianCommandSafetyWitness> {
    let target_socket = tool.target.clone()?;
    let session_name = ir
        .sockets
        .iter()
        .find(|s| s.name == target_socket)
        .map(|s| s.protocol.clone())
        .unwrap_or_default();
    let risk = tool.risk.clone().unwrap_or_default();

    let param_names: std::collections::HashSet<&str> =
        tool.parameters.iter().map(|p| p.name.as_str()).collect();
    let mut unbound_placeholders = Vec::new();
    let mut partial_tokens = Vec::new();
    for tok in &tool.argv {
        match axon_frontend::technician::classify_argv_token(tok) {
            axon_frontend::technician::ArgvToken::Placeholder(name) => {
                if !param_names.contains(name.as_str()) {
                    unbound_placeholders.push(name);
                }
            }
            axon_frontend::technician::ArgvToken::Partial(t) => partial_tokens.push(t),
            axon_frontend::technician::ArgvToken::Literal(_) => {}
        }
    }

    // T858 is scoped to `provider: bash`; a non-bash target tool is not
    // required to carry an argv template, so `argv_present` is vacuously true.
    let argv_present = tool.provider != "bash" || !tool.argv.is_empty();

    let confirm_branch_reachable =
        if risk == axon_frontend::technician::RISK_DESTRUCTIVE {
            ir.sessions
                .iter()
                .find(|s| s.name == session_name)
                .map(|s| s.roles.iter().any(|r| ir_session_has_confirm_branch(&r.steps)))
                .unwrap_or(false)
        } else {
            true
        };

    Some(TechnicianCommandSafetyWitness {
        tool_name: tool.name.clone(),
        target_socket,
        session_name,
        risk,
        argv: tool.argv.clone(),
        argv_present,
        unbound_placeholders,
        partial_tokens,
        confirm_branch_reachable,
    })
}

/// §84.c — one TechnicianCommandSafety proof per `target:`-bound tool.
pub fn generate_technician_command_safety_proofs(
    ir: &IRProgram,
    axon_version: &str,
) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut proofs = Vec::new();
    for tool in &ir.tools {
        let Some(witness) = derive_technician_command_safety_witness(tool, ir) else {
            continue;
        };
        proofs.push(ProofTerm {
            property: PropertyClass::TechnicianCommandSafety,
            artifact_digest: digest.clone(),
            witness: Witness::TechnicianCommandSafety(witness),
            axon_version: axon_version.to_string(),
        });
    }
    proofs
}

// ── §Fase 85.c — CacheSoundness ──────────────────────────────────────────────

/// §85.c — re-derive the whole-program cache witness from `ir.caches` +
/// `ir.tools` + `ir.channels`. "No contract → no proof": a program with no
/// `cache` declaration and no `tool.cache:` reference returns `None`.
pub fn derive_cache_soundness_witness(ir: &IRProgram) -> Option<CacheSoundnessWitness> {
    let uses_cache = !ir.caches.is_empty()
        || ir
            .tools
            .iter()
            .any(|t| !t.cache.is_empty() && t.cache != "none");
    if !uses_cache {
        return None;
    }

    let cache_names: Vec<String> = ir.caches.iter().map(|c| c.name.clone()).collect();
    let default_count = ir.caches.iter().filter(|c| c.default_policy).count();

    let base = |e: &str| e.split_once(':').map(|(b, _)| b).unwrap_or(e).to_string();
    let widened_without_ttl: Vec<String> = ir
        .caches
        .iter()
        .filter(|c| {
            let pure_only = c.apply_to_effects.iter().all(|e| base(e) == "pure");
            !pure_only && c.ttl.is_none()
        })
        .map(|c| c.name.clone())
        .collect();

    let channel_names: std::collections::HashSet<&str> =
        ir.channels.iter().map(|c| c.name.as_str()).collect();
    let cache_name_set: std::collections::HashSet<&str> =
        cache_names.iter().map(|s| s.as_str()).collect();
    let mut unresolved_refs = Vec::new();
    for c in &ir.caches {
        for ch in &c.invalidate_on {
            if !channel_names.contains(ch.as_str()) {
                unresolved_refs.push(format!("cache '{}' invalidate_on '{}'", c.name, ch));
            }
        }
    }
    for t in &ir.tools {
        if !t.cache.is_empty() && t.cache != "none" && !cache_name_set.contains(t.cache.as_str()) {
            unresolved_refs.push(format!("tool '{}' cache '{}'", t.name, t.cache));
        }
    }

    Some(CacheSoundnessWitness {
        cache_names,
        default_count,
        widened_without_ttl,
        unresolved_refs,
    })
}

/// §85.c — generate the (at most one) CacheSoundness proof for `ir`.
pub fn generate_cache_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    match derive_cache_soundness_witness(ir) {
        Some(witness) => vec![ProofTerm {
            property: PropertyClass::CacheSoundness,
            artifact_digest: artifact_digest(ir),
            witness: Witness::CacheSoundness(witness),
            axon_version: axon_version.to_string(),
        }],
        None => Vec::new(),
    }
}

// ── §Fase 86.c — ForgeSoundness ──────────────────────────────────────────────

const FORGE_MODES: &[&str] = &["combinatorial", "exploratory", "transformational"];

/// Recursively collect `(flow_name, &IRForgeBlock)` from a flow's step tree
/// (forge blocks can nest inside `if` / `for` bodies).
fn collect_forge_blocks<'a>(
    steps: &'a [axon_frontend::ir_nodes::IRFlowNode],
    flow_name: &str,
    out: &mut Vec<(String, &'a axon_frontend::ir_nodes::IRForgeBlock)>,
) {
    use axon_frontend::ir_nodes::IRFlowNode;
    for step in steps {
        match step {
            IRFlowNode::Forge(f) => out.push((flow_name.to_string(), f)),
            IRFlowNode::Conditional(c) => {
                collect_forge_blocks(&c.then_body, flow_name, out);
                collect_forge_blocks(&c.else_body, flow_name, out);
            }
            IRFlowNode::ForIn(f) => collect_forge_blocks(&f.body, flow_name, out),
            _ => {}
        }
    }
}

/// §86.c — collect `&IRForgeBlock` from a step tree (checker helper; recurses
/// into `if`/`for` bodies).
pub(crate) fn __collect_forge_for_check<'a>(
    steps: &'a [axon_frontend::ir_nodes::IRFlowNode],
    out: &mut Vec<&'a axon_frontend::ir_nodes::IRForgeBlock>,
) {
    use axon_frontend::ir_nodes::IRFlowNode;
    for step in steps {
        match step {
            IRFlowNode::Forge(f) => out.push(f),
            IRFlowNode::Conditional(c) => {
                __collect_forge_for_check(&c.then_body, out);
                __collect_forge_for_check(&c.else_body, out);
            }
            IRFlowNode::ForIn(f) => __collect_forge_for_check(&f.body, out),
            _ => {}
        }
    }
}

/// §86.c — re-derive one forge block's soundness witness against the IR anchors.
pub fn derive_forge_soundness_witness(
    flow_name: &str,
    forge: &axon_frontend::ir_nodes::IRForgeBlock,
    ir: &IRProgram,
) -> ForgeSoundnessWitness {
    let mode_ok = forge.mode.is_empty() || FORGE_MODES.contains(&forge.mode.as_str());
    let novelty_in_range = forge.novelty >= 0.0 && forge.novelty <= 1.0;
    let bounds_ok = forge.depth >= 1 && forge.branches >= 1;
    let seed_and_type_present =
        !forge.seed.trim().is_empty() && !forge.output_type.trim().is_empty();
    let constraints_ok = forge.constraints_ref.is_empty()
        || ir
            .anchors
            .iter()
            .any(|a| a.name == forge.constraints_ref && a.confidence_floor.is_some());
    ForgeSoundnessWitness {
        forge_name: forge.name.clone(),
        flow_name: flow_name.to_string(),
        mode: forge.mode.clone(),
        novelty_milli: (forge.novelty * 1000.0).round() as i64,
        depth: forge.depth,
        branches: forge.branches,
        constraints_ref: forge.constraints_ref.clone(),
        mode_ok,
        novelty_in_range,
        bounds_ok,
        seed_and_type_present,
        constraints_ok,
    }
}

/// §86.c — one ForgeSoundness proof per `forge` block in the program.
pub fn generate_forge_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut forges = Vec::new();
    for flow in &ir.flows {
        collect_forge_blocks(&flow.steps, &flow.name, &mut forges);
    }
    forges
        .into_iter()
        .map(|(flow_name, forge)| ProofTerm {
            property: PropertyClass::ForgeSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::ForgeSoundness(derive_forge_soundness_witness(&flow_name, forge, ir)),
            axon_version: axon_version.to_string(),
        })
        .collect()
}

/// §87.g — the checker's own statement of the `savant` cognition catalogs
/// (mirror of the private `axon_frontend::type_checker::VALID_SAVANT_*`).
const SAVANT_DEPTHS: &[&str] = &["standard", "deep", "hyper"];
const SAVANT_DIVERGENCES: &[&str] = &["low", "med", "high"];

/// §87.g — re-derive one savant's governance-soundness witness against the IR.
/// The single source of truth reused by both the prover and the verifier
/// (`check_savant_soundness`), so a forged/stale proof is caught by
/// re-derivation, exactly as ForgeSoundness/CacheSoundness.
pub fn derive_savant_soundness_witness(
    savant: &axon_frontend::ir_nodes::IRSavant,
    ir: &IRProgram,
) -> SavantSoundnessWitness {
    let domain_present = !savant.domain.trim().is_empty();

    let mandate_ok = !savant.mandates.is_empty()
        && savant
            .mandates
            .iter()
            .all(|m| !m.objective.trim().is_empty() && !m.output_type.trim().is_empty());

    let max_iterations = savant
        .budget
        .as_ref()
        .and_then(|b| b.max_iterations)
        .unwrap_or(0);
    let budget_bounded = max_iterations > 0;

    let cognition_ok = savant.cognition.as_ref().is_none_or(|c| {
        let depth_ok = c.depth.is_empty() || SAVANT_DEPTHS.contains(&c.depth.as_str());
        let div_ok = c.divergence.is_empty() || SAVANT_DIVERGENCES.contains(&c.divergence.as_str());
        let thr_ok = c.entropic_threshold.is_none_or(|t| t > 0.0);
        depth_ok && div_ok && thr_ok
    });

    let memory_ref_ok = savant.memory.as_ref().is_none_or(|m| {
        m.backend.is_empty()
            || ir.memories.iter().any(|x| x.name == m.backend)
            || ir.corpus_specs.iter().any(|x| x.name == m.backend)
    });

    SavantSoundnessWitness {
        savant_name: savant.name.clone(),
        mandate_count: savant.mandates.len() as i64,
        max_iterations,
        domain_present,
        mandate_ok,
        budget_bounded,
        cognition_ok,
        memory_ref_ok,
    }
}

/// §87.g — one SavantSoundness proof per `savant` in the program. `savant` is a
/// top-level declaration, so this iterates `ir.savants` directly (no flow-step
/// walk like forge).
pub fn generate_savant_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    ir.savants
        .iter()
        .map(|savant| ProofTerm {
            property: PropertyClass::SavantSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::SavantSoundness(derive_savant_soundness_witness(savant, ir)),
            axon_version: axon_version.to_string(),
        })
        .collect()
}

// ── §Fase 88.e — WardenSoundness ─────────────────────────────────────────────

const SCOPE_DEPTHS: &[&str] = &["static_artifact", "memory_dump", "live_network"];

/// Recursively collect `(flow_name, &IRWarden)` from a flow's step tree (warden
/// blocks can nest inside `if`/`for`/`quant` and other warden bodies).
fn collect_warden_blocks<'a>(
    steps: &'a [axon_frontend::ir_nodes::IRFlowNode],
    flow_name: &str,
    out: &mut Vec<(String, &'a axon_frontend::ir_nodes::IRWarden)>,
) {
    use axon_frontend::ir_nodes::IRFlowNode;
    for step in steps {
        match step {
            IRFlowNode::Warden(w) => {
                out.push((flow_name.to_string(), w));
                collect_warden_blocks(&w.body, flow_name, out);
            }
            IRFlowNode::Conditional(c) => {
                collect_warden_blocks(&c.then_body, flow_name, out);
                collect_warden_blocks(&c.else_body, flow_name, out);
            }
            IRFlowNode::ForIn(f) => collect_warden_blocks(&f.body, flow_name, out),
            IRFlowNode::Quant(q) => collect_warden_blocks(&q.body, flow_name, out),
            _ => {}
        }
    }
}

/// §88.e — collect `&IRWarden` from a step tree (checker helper; recurses into
/// `if`/`for`/`quant`/warden bodies).
pub(crate) fn __collect_warden_for_check<'a>(
    steps: &'a [axon_frontend::ir_nodes::IRFlowNode],
    out: &mut Vec<&'a axon_frontend::ir_nodes::IRWarden>,
) {
    use axon_frontend::ir_nodes::IRFlowNode;
    for step in steps {
        match step {
            IRFlowNode::Warden(w) => {
                out.push(w);
                __collect_warden_for_check(&w.body, out);
            }
            IRFlowNode::Conditional(c) => {
                __collect_warden_for_check(&c.then_body, out);
                __collect_warden_for_check(&c.else_body, out);
            }
            IRFlowNode::ForIn(f) => __collect_warden_for_check(&f.body, out),
            IRFlowNode::Quant(q) => __collect_warden_for_check(&q.body, out),
            _ => {}
        }
    }
}

/// §88.e — re-derive one warden block's authorization-soundness witness against
/// the IR (`scopes`). The single source of truth reused by the prover + the
/// verifier (`check_warden_soundness`), so a forged/stale proof is caught by
/// re-derivation.
pub fn derive_warden_soundness_witness(
    flow_name: &str,
    warden: &axon_frontend::ir_nodes::IRWarden,
    ir: &IRProgram,
) -> WardenSoundnessWitness {
    let scope = ir.scopes.iter().find(|s| s.name == warden.scope_ref);
    WardenSoundnessWitness {
        warden_target: warden.target.clone(),
        flow_name: flow_name.to_string(),
        scope_ref: warden.scope_ref.clone(),
        scope_resolves: scope.is_some(),
        targets_nonempty: scope.is_some_and(|s| !s.targets.is_empty()),
        depth_ok: scope
            .is_some_and(|s| s.depth.is_empty() || SCOPE_DEPTHS.contains(&s.depth.as_str())),
        approver_present: scope.is_some_and(|s| !s.approver.trim().is_empty()),
    }
}

/// §88.e — one WardenSoundness proof per `warden` block in the program.
pub fn generate_warden_soundness_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let digest = artifact_digest(ir);
    let mut wardens = Vec::new();
    for flow in &ir.flows {
        collect_warden_blocks(&flow.steps, &flow.name, &mut wardens);
    }
    wardens
        .into_iter()
        .map(|(flow_name, warden)| ProofTerm {
            property: PropertyClass::WardenSoundness,
            artifact_digest: digest.clone(),
            witness: Witness::WardenSoundness(derive_warden_soundness_witness(
                &flow_name, warden, ir,
            )),
            axon_version: axon_version.to_string(),
        })
        .collect()
}

/// §51.f — generate proofs across ALL property classes for `ir`. The
/// `axon pcc prove` entry point. Concatenates every per-class
/// generator (compliance / effects / capability-gate / resources /
/// shields / capability-containment / tool-call-soundness /
/// effect-budgeted) — one bundle covering every certifiable property an
/// apx program declares.
pub fn generate_all_proofs(ir: &IRProgram, axon_version: &str) -> Vec<ProofTerm> {
    let mut proofs = Vec::new();
    proofs.extend(generate_compliance_coverage_proofs(ir, axon_version));
    proofs.extend(generate_effect_row_soundness_proofs(ir, axon_version));
    proofs.extend(generate_capability_isolation_proofs(ir, axon_version));
    proofs.extend(generate_resource_bounds_proofs(ir, axon_version));
    proofs.extend(generate_shield_halt_guarantee_proofs(ir, axon_version));
    proofs.extend(generate_capability_containment_proofs(ir, axon_version));
    proofs.extend(generate_tool_call_soundness_proofs(ir, axon_version));
    proofs.extend(generate_effect_budgeted_proofs(ir, axon_version));
    proofs.extend(generate_json_shape_soundness_proofs(ir, axon_version));
    proofs.extend(generate_channel_delivery_soundness_proofs(ir, axon_version));
    proofs.extend(generate_aggregate_soundness_proofs(ir, axon_version));
    proofs.extend(generate_channel_egress_soundness_proofs(ir, axon_version));
    proofs.extend(generate_interruptible_session_soundness_proofs(ir, axon_version));
    proofs.extend(generate_parked_residual_soundness_proofs(ir, axon_version));
    proofs.extend(generate_upstream_projection_soundness_proofs(ir, axon_version));
    proofs.extend(generate_cors_policy_consistency_proofs(ir, axon_version));
    proofs.extend(generate_technician_command_safety_proofs(ir, axon_version));
    proofs.extend(generate_cache_soundness_proofs(ir, axon_version));
    proofs.extend(generate_forge_soundness_proofs(ir, axon_version));
    proofs.extend(generate_savant_soundness_proofs(ir, axon_version));
    proofs.extend(generate_warden_soundness_proofs(ir, axon_version));
    proofs.extend(generate_authorization_coverage_proofs(ir, axon_version));
    proofs
}
