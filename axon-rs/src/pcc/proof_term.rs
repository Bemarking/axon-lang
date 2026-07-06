//! §Fase 51.a — Proof-Carrying Code: the portable proof object.
//!
//! A [`ProofTerm`] is the serializable artifact a producer (the axon
//! compiler) emits alongside compiled code, certifying that a declared
//! property holds. A consumer runs the INDEPENDENT checker
//! ([`crate::pcc::checker`]) to verify it — WITHOUT trusting the
//! producer (D51.2). The term travels as JSON, the same delivery
//! surface as the SBOM / in-toto statements in [`crate::esk::attestation`],
//! but unlike those it is a *proof* the consumer re-checks, not an
//! attestation the consumer trusts.
//!
//! ## D51.1 — representation
//!
//! - [`PropertyClass`] — closed enum of property kinds. §51.a ships
//!   exactly [`PropertyClass::ComplianceCoverage`]; §51.b-e extend it.
//! - `artifact_digest` — SHA-256 hex of the canonical IR JSON the proof
//!   is ABOUT. Binds the proof to a specific artifact: a proof for
//!   program A cannot be replayed against program B (the checker
//!   recomputes the digest and rejects a mismatch).
//! - [`Witness`] — the property-specific derivation the checker
//!   re-verifies against the artifact.
//! - `axon_version` — producer version. Diagnostic only: the checker
//!   does NOT trust it (it re-derives the property regardless).

use serde::{Deserialize, Serialize};

/// The closed catalog of properties a [`ProofTerm`] can certify.
///
/// §Fase 51.a ships [`Self::ComplianceCoverage`]. The §51.b-e classes
/// (`EffectRowSoundness`, `CapabilityIsolation`, `ResourceBounds`,
/// `ShieldHaltGuarantee`) land as the proof-term language generalizes
/// (D51.4 — "universal" is the architecture, shipped one class at a
/// time). Adding a variant here requires a matching witness variant +
/// checker arm — the §51.a drift gate pins this lockstep.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PropertyClass {
    /// Every regulatory class an apx/axonendpoint declares in
    /// `compliance:` is (a) a known class in the closed
    /// [`crate::esk::compliance`] registry and (b) backed by a present,
    /// resolvable shield (`shield_ref` non-empty AND that shield exists
    /// in the program IR). Catches phantom compliance classes (a
    /// typo'd `HIPPA`) and compliance-claimed-without-enforcement
    /// (declaring GDPR with no attached shield).
    ComplianceCoverage,
    /// §51.b — every entry in a tool's `effects: <...>` row is
    /// well-formed: its base is in the closed effect catalog
    /// ([`crate::pcc::effects::EFFECT_BASES`]); `stream` / `trust`
    /// carry a qualifier (`stream`'s in the backpressure catalog); and
    /// `pure` is exclusive (a tool cannot be both `pure` and
    /// effectful). Catches phantom effects (typo'd `network`), bare
    /// `stream` without a backpressure policy, and pure/impure
    /// contradictions.
    EffectRowSoundness,
    /// §51.c — every capability gate an `axonstore` declares (its
    /// Pillar IV `capability` slug, §Fase 35.j) is a well-formed §32.g
    /// capability scope (matches the closed grammar
    /// `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`, via the OSS
    /// `axon_frontend::parser::is_valid_capability_slug`). A malformed
    /// gate is a Pillar IV defect: it can never match a properly-formed
    /// bearer capability, so the store is either locked out or — worse,
    /// if a consumer treats "unparseable gate" as "no gate" — silently
    /// bypassed.
    ///
    /// **Scope (honest):** this is the gate-integrity half. The
    /// containment half — an apx's reachable store gates ⊆ its declared
    /// `requires:` set — needs the endpoint `requires_capabilities`
    /// (AST / enterprise deploy metadata, NOT lowered to the frontend
    /// IR) + flow→store reachability, and is deferred to §51.x
    /// (enterprise PCC consumption, where `requires` lives).
    CapabilityIsolation,
    /// §51.d — declared resource bounds are within sane limits:
    /// an apx/axonendpoint's `retries` is in `[0, MAX_RETRIES]`
    /// (negative is nonsensical; above the ceiling is a retry storm),
    /// and a `socket` carrying a DECLARED `backpressure: credit(k)`
    /// has `k >= 1` (a credit window of 0 deadlocks the §Fase 41.b
    /// typed-resource gate). Unspecified socket credit is a legitimate
    /// type state and is NOT refuted. `timeout` is out of scope by
    /// design — it is a closed duration enum (`{5s,15s,30s,60s}`)
    /// already bounded at parse time, not an unbounded-resource risk.
    ResourceBounds,
    /// §51.e — a shield's breach policy provides a real guarantee:
    /// `on_breach` is a recognized policy (closed catalog — catches a
    /// typo'd `hault`, which the parser does NOT reject since it reads
    /// `on_breach` as a bare identifier), and a shield declaring
    /// `on_breach: halt` actually scans something (a halt shield with
    /// an empty `scan: []` can never detect a breach, so the halt never
    /// fires — a vacuous guarantee / security theater).
    ShieldHaltGuarantee,
    /// §51.x — the CONTAINMENT half of capability isolation (the
    /// deferral §51.c flagged): every capability gate on a store the
    /// apx's `execute_flow` REACHES is covered by the endpoint's
    /// declared `requires:` scopes. Otherwise the flow touches a store
    /// gated by capability `G` the endpoint does not declare requiring
    /// — a request satisfying the endpoint's declared requires could
    /// still reach a store it is not authorized for (capability leak /
    /// privilege escalation). Reachability is a SOUND
    /// over-approximation: every statically-reachable store op (both
    /// conditional branches + the loop body) is counted. An
    /// unresolvable `execute_flow` is REFUTED (cannot certify
    /// containment for a flow the artifact does not contain).
    CapabilityContainment,
    /// §58.i — every structured `use <Tool>(k = v, …)` call satisfies the
    /// called tool's declared `parameters:` input schema: no argument
    /// names a parameter the tool does not declare; no argument is
    /// supplied twice; every required (non-optional) parameter is
    /// supplied; and every UNAMBIGUOUS-LITERAL argument's type aligns
    /// with the declared type. This makes the §58.d CT-2 caller-blame
    /// check an INDEPENDENTLY-VERIFIABLE proof — the tool schema rides
    /// the bundle and the verifier re-derives the call's soundness from
    /// the artifact, never trusting the compiler that ran the type-check
    /// (D1). Literal-type alignment is CONSERVATIVE (only Int/Float/Bool
    /// literals; bare identifiers + `${…}` interpolations are
    /// runtime-resolved and skipped — zero false positives), so the
    /// structural facts (unknown / duplicate / missing) are always
    /// certified and the literal-type facts are certified where decidable
    /// statically. A schema-less tool (no `parameters:`) and the legacy
    /// `use <Tool> on <arg>` form carry no contract → no proof (D5).
    ToolCallSoundness,
    /// §72.f — every `budget { rate/max … on Tool(X) }` a daemon declares is
    /// well-formed + ENFORCEABLE: each quota's `on Tool(X)` resolves to a
    /// declared tool in the program; each `limit` is positive; each `period` is
    /// in the closed catalog (`second|minute|hour|day`); and `on_exhausted` is in
    /// the closed catalog (`block|defer|shed`). This makes a budgeted effect's
    /// linearity (the `effects_are_linear` doctrine) an INDEPENDENTLY-VERIFIABLE
    /// fact: the verifier re-derives, from the artifact alone, that every quota is
    /// a sound contract the dispatch gate can enforce — never trusting the
    /// compiler that ran the §72.a type-check (`axon-T830`–`T834`). A daemon with
    /// no `budget` carries no contract → no proof (mirrors "no effects → no
    /// effect-row proof").
    EffectBudgeted,
    /// §73.g — every `Json<T>` shape LENS an `axonstore` column declares is
    /// SOUND: its `T` resolves to a declared struct `type` in the program.
    /// This makes the §73.a/§73.e lens well-formedness (the `axon-T840`
    /// invariant — "the shape is a declared struct") an INDEPENDENTLY-
    /// VERIFIABLE fact: the verifier re-derives, from the artifact alone,
    /// that every column lens shape names a real struct whose fields are a
    /// closed, finite catalog — so navigation over the lens is DECIDABLE by
    /// construction (a finite fold over the struct's fields, the
    /// `open_data_is_total` guarantee). It never trusts the compiler that
    /// ran the §73.a type-check. A store with no `Json<T>` lens column
    /// carries no contract → no proof (mirrors "no effects → no effect-row
    /// proof"); an open `Json` column (no shape) is unconstrained and is
    /// not a lens site.
    JsonShapeSoundness,
    /// §74.g — every typed `channel` a `daemon` `listen`s on has a PRODUCER:
    /// some flow (or daemon-listener body) `emit`s to it. A `listen`er on a
    /// channel that NOTHING emits to NEVER fires — the original Kivi brief
    /// #39 defect (a daemon waiting on an event no producer raises). §74
    /// wired flow→daemon delivery (the listener fires when an event arrives),
    /// so the remaining delivery defect is the unproduced channel — and this
    /// proof makes it INDEPENDENTLY VERIFIABLE: the verifier re-derives, from
    /// the artifact alone, that every consumed channel has a matching `emit`,
    /// so the declared `qos`/`persistence` delivery is actually reachable
    /// (`delivery_is_a_kept_promise`). The compile-time mirror is `axon-W009`
    /// (§52.g, reworked in §74.g). A channel with no listener carries no
    /// delivery contract → no proof.
    ChannelDeliverySoundness,
    /// §76.e — every `retrieve … { aggregate: / group_by: }` in the program
    /// is SOUND: the aggregate resolves against the CLOSED function catalog
    /// (`count` / `sum(col)` / `avg(col)` / `min(col)` / `max(col)`), every
    /// referenced column satisfies the identifier discipline, the cross-rules
    /// hold (no `group_by:` without an aggregate; no `aggregate:` with
    /// `order_by:`/`limit:`; the aggregate column is not a group key) — so
    /// the SQL the engines render aggregates EXACTLY the declared columns
    /// through the closed catalog, nothing more. The verifier re-derives the
    /// parse from the artifact alone via the SAME runtime clause parser
    /// (`store::filter::parse_aggregate_clause`) — never trusting the
    /// compiler that ran the §76.d type-check (`axon-T843`–`T845`). A
    /// retrieve with no aggregate surface carries no contract → no proof.
    AggregateSoundness,
    /// §77.b — every EGRESS-marked `channel` in the artifact is derivable
    /// from the program and sound: the channel handle's `egress_sign` equals
    /// what re-walking the publish sites derives (a `publish C within S`
    /// where shield S declares `sign:`), the algorithm is in the closed
    /// signing catalog, and the channel is DURABLE
    /// (`persistence: persistent_axonstore`) so signed external delivery
    /// inherits the §74 outbox's at-least-once (`egress_is_a_kept_promise`).
    /// A forged handle (egress marking with no deriving publish site), a
    /// bogus algorithm, or an ephemeral egress channel refutes — and the
    /// §52 deploy gate rejects the bundle fail-closed. The compile-time
    /// mirror is `axon-T846`/`T848`. A channel with neither a declared nor
    /// a derivable egress marking carries no contract → no proof.
    ChannelEgressSoundness,
    /// §Fase 79.c — an **interruptible session region** (`interrupt … on
    /// <Signal> as <sig> resumable …`) is sound: the signal is in the closed
    /// `CallInterruptCause` catalog (D79.2), the region declares both a body and
    /// a resumable handler, and the handler reaches a **two-exit** terminal
    /// (`resume` or `end`, D79.11a). Re-derived from the IR session steps; a
    /// forged witness (e.g. `signal_in_catalog: true` for a bogus cause) is
    /// caught by recomputation. Compile-time mirror: the §79.c type-checker's
    /// interrupt validation.
    InterruptibleSessionSoundness,
    /// §Fase 79.f — `ParkedResidualSoundness`: the data-at-rest surface that
    /// interruption opens. A socket whose protocol contains an interrupt region
    /// parks the body's residual (a possibly PII-bearing κ) into the §41.g
    /// `cognitive_state` snapshot for the TTL window — a surface the §77 shield
    /// (which reasons about *channel egress*, not snapshot-at-rest) never sees.
    /// The obligation (paper §7): the socket must declare `reconnect:
    /// cognitive_state` (so the park is AAD-bound + recoverable) AND a
    /// `legal_basis` (so the at-rest retention is governed). This is the
    /// genuinely-new fourth member of the `CallSoundnessCertificate` — not an
    /// emergent conjunction of the other three (D79.8).
    ParkedResidualSoundness,
    /// §Fase 80 — `UpstreamProjectionSoundness`: an `upstream`'s declared
    /// wire↔session projection (`map:`) is a TOTAL, unambiguous cover of the
    /// bound role's message set, and its `resolve:`/`secret:` values are
    /// config KEYS (never endpoint/credential literals). This is §80's core
    /// claim — "no message falls through untranscoded, no vendor coordinate
    /// in source" — as a machine-checkable obligation re-derived from the IR
    /// alone (the `no_unwitnessed_advantage` discipline applied to the trust
    /// boundary D80.4 stops at: everything up to the wire is proved, the
    /// vendor's side is defended + witnessed, never claimed). Compile-time
    /// mirror: the §80.c type-checker (T849/T850/T851).
    UpstreamProjectionSoundness,
    /// §Fase 83 — `CorsPolicyConsistency`: for every `axonendpoint.cors:`
    /// reference in the program, the referenced `cors` declaration exists;
    /// no `cors` declaration combines an any-origin `allow_origins` with
    /// `allow_credentials: true` (the CORS spec's own forbidden pairing);
    /// and no two `axonendpoint`s sharing a `path:` reference different (or
    /// inconsistently unset/set) `cors:` declarations. Re-derives the same
    /// closed checks the §83.c type-checker already ran (T853/T856/T857) —
    /// belt-and-suspenders against a stored IR whose compile-time proof has
    /// gone stale (a hand-edited or version-drifted deployment).
    CorsPolicyConsistency,
    /// §84.c — for each `target:`-bound technician `tool`, re-derives the
    /// Remote Hands safety facts the §84.c type-checker already proved
    /// (T858/T859/T860): a `provider: bash` tool has a non-empty `argv:`
    /// template; every `${param}` in that argv is a WHOLE argv element bound
    /// to a declared parameter (no unbound, no partial/fused token — the
    /// injection-safety keystone, D84.1); and a `risk: destructive` tool's
    /// bound session offers a reachable `branch{ approved / denied }`
    /// confirmation (D84.2). Belt-and-suspenders against a stored IR whose
    /// compile-time proof has gone stale (a hand-edited or version-drifted
    /// deployment reaching a real machine — the highest-stakes surface, so it
    /// gets a deploy-time re-derivation like everything else).
    TechnicianCommandSafety,
    /// §85.c — re-derives the program-wide cache laws the §85.c type-checker
    /// proved: at most one `cache { default: true }` (T863); every cache that
    /// widens `apply_to_effects:` beyond `[pure]` carries a finite `ttl:`
    /// (T865, the "never cache a non-deterministic result forever" invariant);
    /// and every `invalidate_on:` / `tool.cache:` reference resolves (T864).
    /// Belt-and-suspenders against a stored IR whose compile-time proof has
    /// gone stale — a mis-cached result is a correctness bug (serving a foreign
    /// or stale value), so it gets a deploy-time re-derivation.
    CacheSoundness,
    /// §86.c — for each `forge` block, re-derives the Directed Creative
    /// Synthesis well-formedness the §86.c type-checker proved (T868–T872): the
    /// creativity `mode` is in the Boden catalog; `novelty` ∈ [0,1]; `depth`
    /// and `branches` ≥ 1; a `seed` is present; and a non-empty `constraints:`
    /// resolves to a declared `anchor` carrying a `confidence_floor`. This
    /// certifies the pipeline is well-formed and WILL run its fail-closed
    /// verification gate — the measured-novelty *outcome* is data-dependent and
    /// enforced at runtime (D86.6).
    ForgeSoundness,
    /// §87.g — for each `savant` (the long-horizon autonomous research
    /// primitive), re-derives the governance invariants the §87.b/c type-checker
    /// proved: a bounded ontological `domain` (T873); at least one well-formed
    /// `mandate` (T874); a mandatory, positive compute `budget.max_iterations`
    /// (T877 — the §72 linear-budget discipline, the load-bearing
    /// "budget-bounded" half of the doctrine `autonomy_is_a_governed_
    /// orchestration_not_a_loop`); and valid `cognition` catalogs (T876). This
    /// certifies a stored/deployed savant is STILL governed — an autonomous loop
    /// that runs for weeks with a stale proof that dropped its budget would be
    /// fail-open, so it gets a deploy-time re-derivation. (Interruptibility +
    /// provenance are enforced by the enterprise host, §87.k.)
    SavantSoundness,
}

/// §72.f — the closed period catalog for `budget` quotas. The checker's own
/// statement of the spec (D51.2) — mirror of
/// `axon_frontend::type_checker::VALID_BUDGET_PERIODS`.
pub const VALID_BUDGET_PERIODS: &[&str] = &["second", "minute", "hour", "day"];

/// §72.f — the closed exhaustion-policy catalog for `budget`. Mirror of
/// `axon_frontend::type_checker::VALID_ON_EXHAUSTED`.
pub const VALID_ON_EXHAUSTED: &[&str] = &["block", "defer", "shed"];

/// §51.e — the closed breach-policy catalog. Mirror of
/// `axon_frontend::type_checker::VALID_ON_BREACH_POLICIES` (private
/// const). The checker's own statement of the spec (D51.2). Cross-crate
/// drift gate deferred to §51.f alongside the effect catalog.
pub const VALID_BREACH_POLICIES: &[&str] =
    &["deflect", "escalate", "halt", "quarantine", "sanitize_and_retry"];

/// §51.d — the retry-storm ceiling. A declared `retries` above this is
/// almost certainly a defect (an unbounded-ish retry storm), not a
/// legitimate config. Generous on purpose so legitimate high-retry
/// configs are not false-positived; the negative-retries case is the
/// unambiguous defect this bound primarily guards.
pub const MAX_RETRIES: i64 = 100;

impl PropertyClass {
    /// Stable wire slug for the property class.
    pub fn slug(&self) -> &'static str {
        match self {
            PropertyClass::ComplianceCoverage => "compliance_coverage",
            PropertyClass::EffectRowSoundness => "effect_row_soundness",
            PropertyClass::CapabilityIsolation => "capability_isolation",
            PropertyClass::ResourceBounds => "resource_bounds",
            PropertyClass::ShieldHaltGuarantee => "shield_halt_guarantee",
            PropertyClass::CapabilityContainment => "capability_containment",
            PropertyClass::ToolCallSoundness => "tool_call_soundness",
            PropertyClass::EffectBudgeted => "effect_budgeted",
            PropertyClass::JsonShapeSoundness => "json_shape_soundness",
            PropertyClass::ChannelDeliverySoundness => "channel_delivery_soundness",
            PropertyClass::AggregateSoundness => "aggregate_soundness",
            PropertyClass::ChannelEgressSoundness => "channel_egress_soundness",
            PropertyClass::InterruptibleSessionSoundness => "interruptible_session_soundness",
            PropertyClass::ParkedResidualSoundness => "parked_residual_soundness",
            PropertyClass::UpstreamProjectionSoundness => "upstream_projection_soundness",
            PropertyClass::CorsPolicyConsistency => "cors_policy_consistency",
            PropertyClass::TechnicianCommandSafety => "technician_command_safety",
            PropertyClass::CacheSoundness => "cache_soundness",
            PropertyClass::ForgeSoundness => "forge_soundness",
            PropertyClass::SavantSoundness => "savant_soundness",
        }
    }
}

/// §79.c — the closed `CallInterruptCause` catalog. The checker's own statement
/// of the spec (D51.2) — mirror of
/// `axon_frontend::type_checker::CALL_INTERRUPT_CAUSES`. Cross-crate drift is
/// gated the same way the other mirrored catalogs are.
pub const CALL_INTERRUPT_CAUSES: &[&str] =
    &["CallerSpeech", "Dtmf", "SilenceTimeout", "AgentFault"];

/// §51.a — witness for [`PropertyClass::ComplianceCoverage`].
///
/// The derivation the producer recorded. The checker RE-DERIVES every
/// field from the artifact and rejects the proof if the witness
/// disagrees (D51.2 — a forged witness is caught because the checker
/// recomputes, it does not believe the claim).
///
/// The property certified: the shield attached to a compliance-bearing
/// apx **actually covers** every regulatory class the apx declares —
/// `covers(provided, required) == ∅` (the existing
/// [`crate::esk::compliance::covers`] predicate), with no phantom
/// classes and a present, resolvable shield.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComplianceCoverageWitness {
    /// The apx / axonendpoint this proof is about.
    pub endpoint_name: String,
    /// The regulatory classes the endpoint declared, sorted + deduped
    /// (canonical so the checker's re-derivation compares equal).
    pub required_classes: Vec<String>,
    /// The endpoint's `shield_ref` (empty string = no shield declared).
    pub shield_ref: String,
    /// Whether `shield_ref` is non-empty AND resolves to a shield
    /// present in the program IR.
    pub shield_present: bool,
    /// The regulatory classes the resolved shield PROVIDES (its
    /// `compliance:` set), sorted + deduped. Empty when no shield
    /// resolves.
    pub provided_classes: Vec<String>,
    /// The subset of `required_classes` that are NOT in the closed
    /// regulatory registry (phantom compliance claims). Empty for a
    /// verifying proof.
    pub unknown_classes: Vec<String>,
    /// The subset of `required_classes` the shield does NOT provide
    /// (`required \ provided` — the coverage gap), sorted. Empty for a
    /// verifying proof.
    pub uncovered_classes: Vec<String>,
}

/// §51.b — witness for [`PropertyClass::EffectRowSoundness`].
///
/// The derivation for one tool's declared effect row. The checker
/// re-derives every field from the tool's IR and rejects a disagreement
/// as forgery (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EffectRowSoundnessWitness {
    /// The tool this proof is about.
    pub tool_name: String,
    /// The tool's declared effect-row entries, sorted + deduped
    /// (canonical so the checker's re-derivation compares equal). Each
    /// entry is `base` or `base:qualifier`.
    pub declared_effects: Vec<String>,
    /// Entries whose base effect is NOT in the closed catalog (phantom
    /// effects). Empty for a verifying proof.
    pub unknown_bases: Vec<String>,
    /// Qualifier-required bases (`stream` / `trust`) declared WITHOUT a
    /// qualifier (bare `stream` / `trust`). Empty for a verifying proof.
    pub missing_qualifier: Vec<String>,
    /// `stream:<q>` entries whose qualifier is not a valid backpressure
    /// policy. Empty for a verifying proof.
    pub invalid_stream_qualifier: Vec<String>,
    /// True when `pure` appears alongside any other effect (a tool
    /// cannot be both pure and effectful). False for a verifying proof.
    pub purity_violation: bool,
}

/// §51.c — witness for [`PropertyClass::CapabilityIsolation`].
///
/// The derivation for one `axonstore`'s capability gate. The checker
/// re-reads the store's `capability` from the IR and re-runs the §32.g
/// grammar validator; a forged witness is rejected because the
/// recomputation disagrees (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityIsolationWitness {
    /// The `axonstore` this proof is about.
    pub store_name: String,
    /// The store's declared Pillar IV capability gate slug.
    pub capability: String,
    /// True when `capability` is non-empty AND does NOT match the
    /// §32.g capability-scope grammar. False for a verifying proof.
    pub malformed: bool,
}

/// §51.d — witness for [`PropertyClass::ResourceBounds`]. One subject
/// per proof: an endpoint's retry bound OR a socket's credit window.
/// Tagged by `subject` so the JSON is self-describing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "subject")]
pub enum ResourceBoundsWitness {
    /// An apx/axonendpoint's declared `retries`.
    EndpointRetry {
        endpoint_name: String,
        retries: i64,
        /// True when `retries` is in `[0, MAX_RETRIES]`.
        in_bounds: bool,
    },
    /// A socket's DECLARED `backpressure: credit(k)` window. Generated
    /// only when the socket declares a credit (unspecified is not
    /// witnessed — it is a legitimate type state, not a bound to
    /// certify).
    SocketCredit {
        socket_name: String,
        credit: i64,
        /// True when `credit >= 1` (a 0 window deadlocks per §41.b).
        positive: bool,
    },
}

/// §51.e — witness for [`PropertyClass::ShieldHaltGuarantee`].
///
/// The derivation for one shield's breach policy. The checker re-reads
/// the shield's `on_breach` + `scan` from the IR and recomputes both
/// facts; a forged witness is rejected because the recomputation
/// disagrees (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShieldHaltGuaranteeWitness {
    /// The shield this proof is about.
    pub shield_name: String,
    /// The shield's declared `on_breach` policy.
    pub on_breach: String,
    /// True when `on_breach` is in the closed breach-policy catalog.
    pub known_policy: bool,
    /// Count of declared `scan` categories (for the vacuous-halt check).
    pub scan_count: usize,
    /// True when `on_breach == "halt"` AND `scan` is empty — the halt
    /// can never fire (no scan ⟹ no breach ⟹ no halt). False for a
    /// verifying proof.
    pub vacuous_halt: bool,
}

/// §51.x — witness for [`PropertyClass::CapabilityContainment`].
///
/// The derivation for one endpoint's reachable-store-gate containment.
/// The checker re-resolves the `execute_flow`, re-walks its reachable
/// store ops, re-resolves each store's capability gate, and recomputes
/// the uncovered set; a forged witness is rejected because the
/// recomputation disagrees (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityContainmentWitness {
    /// The apx / axonendpoint this proof is about.
    pub endpoint_name: String,
    /// The flow the endpoint executes.
    pub execute_flow: String,
    /// Whether `execute_flow` resolves to a flow present in the IR.
    pub flow_resolved: bool,
    /// The capability scopes the endpoint declares (`requires:`),
    /// sorted + deduped.
    pub declared_requires: Vec<String>,
    /// The capability gates of the stores the flow REACHES (each
    /// reached store's non-empty `capability`), sorted + deduped.
    pub reached_gates: Vec<String>,
    /// `reached_gates \ declared_requires` — gates the flow reaches but
    /// the endpoint does not declare requiring. Empty for a verifying
    /// proof.
    pub uncovered_gates: Vec<String>,
}

/// §58.i — witness for [`PropertyClass::ToolCallSoundness`].
///
/// The derivation for ONE structured `use <Tool>(k = v, …)` call site.
/// The checker re-walks the named flow, locates the call at `call_index`
/// (deterministic walk order over the same digest-bound IR), re-reads
/// the called tool's `parameters:` schema, and recomputes every fact; a
/// forged witness (e.g. hiding an unknown argument) is rejected because
/// the recomputation disagrees (D51.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolCallSoundnessWitness {
    /// The flow containing the call.
    pub flow_name: String,
    /// Ordinal of this call among ALL named-arg `use` calls in the flow,
    /// in deterministic walk order (recursing into conditional branches +
    /// for-in bodies). Locates the exact call site so the checker
    /// re-derives the SAME one (two calls to the same tool in one flow
    /// are distinguished).
    pub call_index: usize,
    /// The tool the call invokes.
    pub tool_name: String,
    /// The argument names supplied at the call, in SOURCE ORDER (so a
    /// duplicate is visible). Re-derived from the IR call.
    pub arg_names: Vec<String>,
    /// The called tool's declared parameter names, sorted + deduped
    /// (context + forgery surface). Empty if the tool is undeclared.
    pub declared_params: Vec<String>,
    /// Whether the called tool is declared with a NON-EMPTY `parameters:`
    /// schema. A generated proof always has this `true` (a schema-less /
    /// undeclared tool carries no contract → no proof).
    pub schema_present: bool,
    /// Args naming a parameter the tool does not declare, sorted +
    /// deduped. Empty for a verifying proof.
    pub unknown_args: Vec<String>,
    /// Argument names supplied more than once, sorted + deduped. Empty
    /// for a verifying proof.
    pub duplicate_args: Vec<String>,
    /// Required (non-optional) parameters not supplied, sorted. Empty for
    /// a verifying proof.
    pub missing_required: Vec<String>,
    /// Unambiguous-literal args whose type does not align with the
    /// declared type, each `name:expected:got`, sorted. Empty for a
    /// verifying proof. (Bare identifiers / `${…}` interpolations are
    /// runtime-resolved → not inferred → never listed.)
    pub type_mismatches: Vec<String>,
}

/// §72.f — witness for [`PropertyClass::EffectBudgeted`].
///
/// The property certified: every quota in a daemon's `budget { … }` is a sound,
/// enforceable contract — its `on Tool(X)` resolves to a declared tool, its limit
/// is positive, its period is in the closed catalog, and the budget's
/// `on_exhausted` is in the closed catalog. The checker RE-DERIVES every field
/// from the artifact (the daemon's IR budget + the program's tools) and rejects
/// the proof if the witness disagrees (D51.2 — a forged witness is caught because
/// the checker recomputes). A verifying proof has all four defect lists empty +
/// `on_exhausted_valid == true`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EffectBudgetedWitness {
    /// The daemon carrying the budget.
    pub daemon_name: String,
    /// The number of quotas in the budget (context + forgery surface).
    pub quota_count: usize,
    /// The program's declared tool names, sorted + deduped (the resolution
    /// surface the checker re-derives `unresolved_effects` against).
    pub declared_tools: Vec<String>,
    /// Quota effects (`on Tool(X)`) that do NOT resolve to a declared tool,
    /// sorted + deduped. Empty for a verifying proof.
    pub unresolved_effects: Vec<String>,
    /// Quotas whose limit is ≤ 0, each `effect:kind`, sorted. Empty for verifying.
    pub nonpositive_limits: Vec<String>,
    /// Quotas whose period is not in the closed catalog, each `effect:period`,
    /// sorted. Empty for a verifying proof.
    pub invalid_periods: Vec<String>,
    /// The budget's exhaustion policy (context).
    pub on_exhausted: String,
    /// Whether `on_exhausted` is in the closed catalog. `false` ⇒ refuted.
    pub on_exhausted_valid: bool,
}

/// §73.g — witness for [`PropertyClass::JsonShapeSoundness`].
///
/// The property certified: every `Json<T>` shape lens an `axonstore`
/// declares (a column typed `Json<T>` / `Jsonb<T>`) has `T` resolving to a
/// declared struct `type` in the program. The checker RE-DERIVES every
/// field from the artifact (the store's IR columns + the program's
/// `type` declarations) and rejects the proof if the witness disagrees
/// (D51.2 — a forged witness is caught because the checker recomputes). A
/// verifying proof has `unresolved_shapes` empty.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct JsonShapeSoundnessWitness {
    /// The `axonstore` this proof is about.
    pub store_name: String,
    /// The program's declared struct `type` names, sorted + deduped (the
    /// resolution surface the checker re-derives `unresolved_shapes`
    /// against).
    pub declared_types: Vec<String>,
    /// Each lens column as `column:Shape`, sorted (context + the forgery
    /// surface — the set of lens sites the proof is about).
    pub lens_columns: Vec<String>,
    /// Lens columns whose shape `T` does NOT resolve to a declared struct
    /// `type`, each `column:Shape`, sorted + deduped. Empty for a
    /// verifying proof.
    pub unresolved_shapes: Vec<String>,
}

/// §74.g — witness for [`PropertyClass::ChannelDeliverySoundness`].
///
/// The property certified: a typed `channel` a `daemon` `listen`s on has a
/// PRODUCER (some flow / daemon-listener body `emit`s to it), so the
/// listener can actually fire. The checker RE-DERIVES every field from the
/// artifact (the program's `emit` sites + daemon `listen` sites) and
/// rejects the proof if the witness disagrees (D51.2). A verifying proof
/// has `has_consumer && has_producer` (or no consumer at all → no proof is
/// generated).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChannelDeliverySoundnessWitness {
    /// The `channel` this proof is about.
    pub channel_name: String,
    /// The channel's declared `persistence` (`ephemeral` / `persistent_axonstore`).
    pub persistence: String,
    /// The channel's declared `qos`.
    pub qos: String,
    /// Whether some flow (or daemon-listener body) `emit`s to this channel.
    pub has_producer: bool,
    /// Whether some `daemon` `listen`s on this channel (a non-cron listener).
    pub has_consumer: bool,
}

/// §76.e — witness for [`PropertyClass::AggregateSoundness`].
///
/// One aggregate-`retrieve` site. The checker RE-DERIVES every field from
/// the artifact (re-walking the flows / daemon-listener bodies and
/// re-parsing the clause through the SAME runtime parser) and rejects the
/// proof if the witness disagrees (D51.2). A verifying proof has empty
/// `violations`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AggregateSoundnessWitness {
    /// The flow (or `daemon:<name>` listener body) containing the site.
    pub flow_name: String,
    /// The `axonstore` the retrieve targets.
    pub store_name: String,
    /// The raw `aggregate:` clause as declared.
    pub aggregate: String,
    /// The raw `group_by:` clause as declared.
    pub group_by: String,
    /// The raw `order_by:` clause (participates in the T845 combo rule).
    pub order_by: String,
    /// The raw `limit:` clause (participates in the T845 combo rule).
    pub limit_expr: String,
    /// The parsed closed-catalog function label (`count`/`sum`/`avg`/
    /// `min`/`max`); empty when the clause failed to parse.
    pub function: String,
    /// The aggregate's column argument; empty for `count` or a
    /// failed parse.
    pub column: String,
    /// The parsed, validated group columns (declaration order).
    pub group_columns: Vec<String>,
    /// The typed parse/cross-rule violations, empty for a verifying
    /// proof (rendered from the runtime `FilterError`).
    pub violations: Vec<String>,
}

/// §77.b — the closed egress-signing catalog. The checker's own statement
/// of the spec (D51.2) — mirror of
/// `axon_frontend::type_checker::VALID_SIGN_ALGORITHMS`.
pub const VALID_SIGN_ALGORITHMS: &[&str] = &["hmac_sha256"];

/// §77.b — witness for [`PropertyClass::ChannelEgressSoundness`].
///
/// One egress-marked channel. The checker RE-DERIVES every field from the
/// artifact (re-walking the publish sites against the declared shields —
/// never trusting the IR's pre-resolved `sign` stamps) and rejects the
/// proof if the witness disagrees (D51.2). A verifying proof has
/// `declared_egress_sign == derived_sign`, a catalog algorithm, and
/// `durable == true`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChannelEgressSoundnessWitness {
    /// The `channel` this proof is about.
    pub channel_name: String,
    /// The `egress_sign` the artifact's channel handle CLAIMS (what the
    /// enterprise egress worker would read).
    pub declared_egress_sign: String,
    /// The algorithm RE-DERIVED from the program: the first publish site
    /// (flows in order, then daemon listeners) whose shield declares
    /// `sign:`. Empty when no signing publish site exists.
    pub derived_sign: String,
    /// The shield the deriving publish site named (empty when none).
    pub shield_ref: String,
    /// The channel's declared `persistence`.
    pub persistence: String,
    /// `persistence == "persistent_axonstore"` — the §77 durable-egress
    /// requirement (D77.6).
    pub durable: bool,
}

/// §79.c — witness for [`PropertyClass::InterruptibleSessionSoundness`].
///
/// One interruptible region, located by `(session_name, role_name, signal)`.
/// The checker RE-DERIVES every field from the IR session steps and rejects the
/// proof if the witness disagrees (D51.2). A verifying proof has
/// `signal_in_catalog && has_body && has_handler && handler_reaches_exit`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterruptibleSessionSoundnessWitness {
    /// The `session` this region lives in.
    pub session_name: String,
    /// The role whose protocol contains the interrupt region.
    pub role_name: String,
    /// The `on <Signal>` cause, verbatim from the IR step.
    pub signal: String,
    /// `signal ∈ CallInterruptCause` — a pure function of `signal`, so a forged
    /// `true` here is caught (the checker recomputes it from `signal`).
    pub signal_in_catalog: bool,
    /// The region declares a `body` arm.
    pub has_body: bool,
    /// The region declares a resumable `handler` arm.
    pub has_handler: bool,
    /// The handler reaches a two-exit terminal (`resume` or `end`) on every
    /// path (D79.11a — a handler that falls off the end would leak a linear
    /// continuation capability).
    pub handler_reaches_exit: bool,
}

/// §79.f — witness for [`PropertyClass::ParkedResidualSoundness`].
///
/// One socket that carries an interruptible session (so its body residual may
/// be parked at rest). The checker re-derives every field from the IR and
/// rejects a disagreement (D51.2). A verifying proof has `session_has_interrupt
/// → (reconnect_cognitive_state && legal_basis_declared)`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParkedResidualSoundnessWitness {
    /// The socket binding the interruptible session.
    pub socket_name: String,
    /// The session the socket's `protocol` references.
    pub session_name: String,
    /// The referenced session contains at least one `interrupt` region (so a
    /// residual can be parked at rest).
    pub session_has_interrupt: bool,
    /// The socket declares `reconnect: cognitive_state` — the park is AAD-bound
    /// and recoverable (§41.g), not a second, unsealed store.
    pub reconnect_cognitive_state: bool,
    /// The socket declares a `legal_basis` — the at-rest retention of the
    /// parked κ is governed (its TTL has a legal ceiling).
    pub legal_basis_declared: bool,
}

/// §80 — witness for [`PropertyClass::UpstreamProjectionSoundness`].
///
/// One `upstream`, located by name. The checker RE-DERIVES the required
/// message sets from the referenced session's bound role, the covered sets
/// from the `map:` rules, and the key-shape verdicts from the strings
/// themselves — a forged `projection_total: true` is caught by
/// recomputation (D51.2). A verifying proof has `projection_total &&
/// config_keys_valid`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UpstreamProjectionSoundnessWitness {
    /// The `upstream` this proof is about.
    pub upstream_name: String,
    /// The session its `protocol:` references.
    pub session_name: String,
    /// The role axon plays (`role:`).
    pub role_name: String,
    /// Messages the bound role SENDS (dedup, source order) — re-derived
    /// from the IR session steps, through select/branch/interrupt arms.
    pub required_sends: Vec<String>,
    /// Messages the bound role RECEIVES — same derivation.
    pub required_receives: Vec<String>,
    /// Messages with a `send` map rule (dedup, source order).
    pub covered_sends: Vec<String>,
    /// Messages with a `receive` map rule.
    pub covered_receives: Vec<String>,
    /// The projection is total + unambiguous: every required message covered
    /// exactly once in its direction, no rule for a message the role never
    /// exchanges, distinct inbound-json discriminators, ≤ 1 inbound-binary
    /// rule (the T849 law, re-derived).
    pub projection_total: bool,
    /// `resolve:`/`secret:` are policy-shaped config keys (the T850 law:
    /// lowercase `[a-z0-9][a-z0-9_.-]*` — a URL or credential literal
    /// cannot satisfy this).
    pub config_keys_valid: bool,
}

/// §83.c — witness for [`PropertyClass::CorsPolicyConsistency`].
///
/// Unlike most witnesses (one channel / socket / upstream), this property is
/// inherently PROGRAM-WIDE: "every reference resolves" and "no two endpoints
/// on one path disagree" are statements about the whole declaration set, not
/// one declaration. The checker RE-DERIVES every field from the IR's
/// `cors_policies` + `endpoints` and rejects the proof if the witness
/// disagrees (D51.2). A verifying proof has `all_references_resolve == true`
/// and both violation lists empty.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CorsPolicyConsistencyWitness {
    /// Every `cors` declaration's name, source order.
    pub declared_cors_names: Vec<String>,
    /// `(endpoint_name, cors_ref)` for every endpoint with a non-empty
    /// `cors_ref`, source order.
    pub endpoint_cors_refs: Vec<(String, String)>,
    /// Every `endpoint_cors_refs` entry's `cors_ref` is in
    /// `declared_cors_names` (`axon-T856`, re-derived).
    pub all_references_resolve: bool,
    /// Names of `cors` declarations combining an any-origin `allow_origins`
    /// with `allow_credentials: true` — the CORS spec's forbidden pairing
    /// (`axon-T853`, re-derived). Empty for a verifying proof.
    pub wildcard_credential_violations: Vec<String>,
    /// `(first_endpoint_name, conflicting_endpoint_name)` pairs sharing a
    /// `path` but disagreeing on `cors_ref` (`axon-T857`, re-derived). Empty
    /// for a verifying proof.
    pub cross_method_conflicts: Vec<(String, String)>,
}

/// §84.c — witness for [`PropertyClass::TechnicianCommandSafety`], one per
/// `target:`-bound technician `tool`. The checker RE-DERIVES every field from
/// the IR (`tools` + `sockets` + `sessions`) and rejects the proof if the
/// witness disagrees (D51.2). A verifying proof has `argv_present == true`,
/// both violation lists empty, and (`risk != "destructive"` OR
/// `confirm_branch_reachable == true`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TechnicianCommandSafetyWitness {
    /// The tool this witness certifies.
    pub tool_name: String,
    /// The `socket` the tool dispatches over (`target:`).
    pub target_socket: String,
    /// The session bound by that socket (its `protocol:`).
    pub session_name: String,
    /// The declared `risk:` class (`safe | destructive`).
    pub risk: String,
    /// The argv template, verbatim (each element literal or `${param}`).
    pub argv: Vec<String>,
    /// A `provider: bash` tool has a non-empty argv template (`axon-T858`).
    /// `true` for a verifying proof.
    pub argv_present: bool,
    /// argv placeholders that are NOT declared `parameters:` entries
    /// (`axon-T859`). Empty for a verifying proof.
    pub unbound_placeholders: Vec<String>,
    /// argv elements that mention `${` but are not a whole-element placeholder
    /// (the fused/partial tokens `axon-T859` forbids — `"${x}.txt"`). Empty for
    /// a verifying proof.
    pub partial_tokens: Vec<String>,
    /// For `risk: destructive`, the bound session offers a reachable
    /// `branch{ approved / denied }` (`axon-T860`). Always `true` for a
    /// non-destructive tool (vacuous).
    pub confirm_branch_reachable: bool,
}

/// §85.c — witness for [`PropertyClass::CacheSoundness`], one per program (the
/// laws are inherently whole-module). The checker RE-DERIVES every field from
/// `ir.caches` + `ir.tools` + `ir.channels` and rejects on disagreement. A
/// verifying proof has `default_count <= 1` and both violation lists empty.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CacheSoundnessWitness {
    /// Every declared `cache` name, source order.
    pub cache_names: Vec<String>,
    /// How many caches declare `default: true` (`axon-T863`: must be ≤ 1).
    pub default_count: usize,
    /// Caches that widen `apply_to_effects:` beyond `[pure]` yet declare no
    /// `ttl:` (`axon-T865`). Empty for a verifying proof.
    pub widened_without_ttl: Vec<String>,
    /// Unresolved references: an `invalidate_on:` channel or a `tool.cache:`
    /// that names no declared symbol (`axon-T864`). Empty for a verifying proof.
    pub unresolved_refs: Vec<String>,
}

/// §86.c — witness for [`PropertyClass::ForgeSoundness`], one per `forge`
/// block. The checker RE-DERIVES every field from the IR (`flows` + `anchors`)
/// and rejects on disagreement. A verifying proof has every `*_ok` flag true.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ForgeSoundnessWitness {
    pub forge_name: String,
    pub flow_name: String,
    pub mode: String,
    /// novelty × 1000, integer-encoded (Eq-friendly; the checker compares the
    /// same rounding).
    pub novelty_milli: i64,
    pub depth: i64,
    pub branches: i64,
    pub constraints_ref: String,
    /// `mode` is empty (⇒ exploratory default) or in the Boden catalog (T868).
    pub mode_ok: bool,
    /// novelty ∈ [0,1] (T869).
    pub novelty_in_range: bool,
    /// depth ≥ 1 AND branches ≥ 1 (T870).
    pub bounds_ok: bool,
    /// seed non-empty AND output_type present (T872).
    pub seed_and_type_present: bool,
    /// `constraints:` empty, OR resolves to a declared anchor with a
    /// `confidence_floor` (T871).
    pub constraints_ok: bool,
}

/// §87.g — witness for [`PropertyClass::SavantSoundness`], one per `savant`. The
/// checker RE-DERIVES every field from `ir.savants` (+ `ir.memories`/
/// `ir.corpus_specs` for the memory binding) and rejects on disagreement. A
/// verifying proof has every `*_ok` flag true.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SavantSoundnessWitness {
    pub savant_name: String,
    /// The number of mandates (T874: ≥ 1).
    pub mandate_count: i64,
    /// The declared FEP-loop ceiling (0 if none — then `budget_bounded` is false).
    pub max_iterations: i64,
    /// A non-empty ontological `domain:` (T873).
    pub domain_present: bool,
    /// At least one mandate, each with a non-empty objective + output type (T874).
    pub mandate_ok: bool,
    /// A mandatory, positive `budget.max_iterations` (T877 — the §72 discipline;
    /// the load-bearing "budget-bounded" invariant).
    pub budget_bounded: bool,
    /// `cognition` absent, OR its `depth`/`divergence` are in catalog and
    /// `entropic_threshold` (if set) is > 0 (T876).
    pub cognition_ok: bool,
    /// `memory.backend` empty, OR resolves to a declared `memory`/`corpus` (T875).
    pub memory_ref_ok: bool,
}

/// The property-specific witness. Tagged so the JSON is self-describing
/// + a future class adds a variant without ambiguity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Witness {
    ComplianceCoverage(ComplianceCoverageWitness),
    EffectRowSoundness(EffectRowSoundnessWitness),
    EffectBudgeted(EffectBudgetedWitness),
    CapabilityIsolation(CapabilityIsolationWitness),
    ResourceBounds(ResourceBoundsWitness),
    ShieldHaltGuarantee(ShieldHaltGuaranteeWitness),
    CapabilityContainment(CapabilityContainmentWitness),
    ToolCallSoundness(ToolCallSoundnessWitness),
    JsonShapeSoundness(JsonShapeSoundnessWitness),
    ChannelDeliverySoundness(ChannelDeliverySoundnessWitness),
    AggregateSoundness(AggregateSoundnessWitness),
    ChannelEgressSoundness(ChannelEgressSoundnessWitness),
    InterruptibleSessionSoundness(InterruptibleSessionSoundnessWitness),
    ParkedResidualSoundness(ParkedResidualSoundnessWitness),
    UpstreamProjectionSoundness(UpstreamProjectionSoundnessWitness),
    CorsPolicyConsistency(CorsPolicyConsistencyWitness),
    TechnicianCommandSafety(TechnicianCommandSafetyWitness),
    CacheSoundness(CacheSoundnessWitness),
    ForgeSoundness(ForgeSoundnessWitness),
    SavantSoundness(SavantSoundnessWitness),
}

impl Witness {
    /// §51.f — the subject (endpoint / tool / store / socket / shield)
    /// the witness is about, for human-readable CLI output. Total.
    pub fn subject_name(&self) -> &str {
        match self {
            Witness::ComplianceCoverage(w) => &w.endpoint_name,
            Witness::EffectRowSoundness(w) => &w.tool_name,
            Witness::EffectBudgeted(w) => &w.daemon_name,
            Witness::CapabilityIsolation(w) => &w.store_name,
            Witness::ResourceBounds(ResourceBoundsWitness::EndpointRetry {
                endpoint_name,
                ..
            }) => endpoint_name,
            Witness::ResourceBounds(ResourceBoundsWitness::SocketCredit {
                socket_name,
                ..
            }) => socket_name,
            Witness::ShieldHaltGuarantee(w) => &w.shield_name,
            Witness::CapabilityContainment(w) => &w.endpoint_name,
            Witness::ToolCallSoundness(w) => &w.tool_name,
            Witness::JsonShapeSoundness(w) => &w.store_name,
            Witness::ChannelDeliverySoundness(w) => &w.channel_name,
            Witness::AggregateSoundness(w) => &w.store_name,
            Witness::ChannelEgressSoundness(w) => &w.channel_name,
            Witness::InterruptibleSessionSoundness(w) => &w.session_name,
            Witness::ParkedResidualSoundness(w) => &w.socket_name,
            Witness::UpstreamProjectionSoundness(w) => &w.upstream_name,
            // §83.c — program-wide property, no single named subject.
            Witness::CorsPolicyConsistency(_) => "<program>",
            Witness::TechnicianCommandSafety(w) => &w.tool_name,
            // §85.c — program-wide property, no single named subject.
            Witness::CacheSoundness(_) => "<program>",
            Witness::ForgeSoundness(w) => &w.forge_name,
            Witness::SavantSoundness(w) => &w.savant_name,
        }
    }
}

/// The portable proof object (D51.1). Serializes to JSON; travels with
/// the artifact; the independent checker verifies it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofTerm {
    /// The property class this term certifies.
    pub property: PropertyClass,
    /// SHA-256 hex of the canonical IR JSON the proof is about (binds
    /// the proof to a specific artifact).
    pub artifact_digest: String,
    /// The derivation the checker re-verifies.
    pub witness: Witness,
    /// Producer version (diagnostic; NOT trusted by the checker).
    pub axon_version: String,
}

/// §51.f — the portable proof bundle the `axon pcc prove` CLI emits +
/// `axon pcc verify` consumes. Carries every proof generated for an
/// artifact plus the artifact digest they all bind to (a quick
/// sanity field — the per-proof `artifact_digest` is the authoritative
/// binding the checker re-verifies).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofBundle {
    /// Producer version that generated the bundle.
    pub axon_version: String,
    /// SHA-256 hex digest of the artifact all proofs bind to.
    pub artifact_digest: String,
    /// Every generated proof (across all property classes).
    pub proofs: Vec<ProofTerm>,
}

/// §79.f — the unified **`CallSoundnessCertificate`** for one socket bundle:
/// the composed proofs (interruptible-session soundness of the session +
/// parked-residual soundness of the socket + the socket's resource bound) plus
/// the bundle identity. Served by the enterprise `GET
/// /admin/calls/certificate/{bundle_id}` (§79.f ENT). The overall verdict —
/// "can this call ever misbehave" — is computed by the independent checker
/// ([`crate::pcc::checker::check_call_soundness_certificate`]): EVERY member
/// must verify, and the composition adds the genuinely-new parked-residual
/// obligation, not a mere conjunction of pre-existing classes (D79.8).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallSoundnessCertificate {
    /// The socket that binds the interruptible session (the bundle id).
    pub socket_name: String,
    /// The session the socket's `protocol` references.
    pub session_name: String,
    /// SHA-256 hex digest of the artifact the composed proofs bind to.
    pub artifact_digest: String,
    /// Producer version.
    pub axon_version: String,
    /// The composed member proofs.
    pub proofs: Vec<ProofTerm>,
}
