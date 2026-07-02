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
    AggregateSoundnessWitness, CapabilityContainmentWitness, CapabilityIsolationWitness,
    ChannelEgressSoundnessWitness,
    ChannelDeliverySoundnessWitness, ComplianceCoverageWitness, EffectBudgetedWitness,
    EffectRowSoundnessWitness, JsonShapeSoundnessWitness, ProofTerm, PropertyClass,
    ResourceBoundsWitness, ShieldHaltGuaranteeWitness, ToolCallSoundnessWitness, Witness,
    MAX_RETRIES, VALID_BREACH_POLICIES, VALID_BUDGET_PERIODS, VALID_ON_EXHAUSTED,
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
    proofs
}
