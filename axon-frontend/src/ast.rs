//! AXON AST node definitions — direct port of axon/compiler/ast_nodes.py.
//!
//! Tier 1 constructs have fully typed structs.
//! Tier 2+ constructs use `GenericDeclaration` (structural fallback).

#![allow(dead_code)]

// ── Location helper ──────────────────────────────────────────────────────────

/// Source location shared by all AST nodes.
#[derive(Debug, Clone, Default)]
pub struct Loc {
    pub line: u32,
    pub column: u32,
}

// ── Top-level ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct Program {
    pub declarations: Vec<Declaration>,
    pub loc: Loc,
}

/// A single top-level declaration in an AXON program.
#[derive(Debug)]
pub enum Declaration {
    Import(ImportNode),
    Persona(PersonaDefinition),
    Context(ContextDefinition),
    Anchor(AnchorConstraint),
    Memory(MemoryDefinition),
    Tool(ToolDefinition),
    Type(TypeDefinition),
    Flow(FlowDefinition),
    Intent(IntentNode),
    Run(RunStatement),
    Epistemic(EpistemicBlock),
    Let(LetStatement),
    /// Lambda Data (ΛD) — Epistemic State Vector definition.
    LambdaData(LambdaDataDefinition),
    // ── Tier 2 declarations (full AST) ──
    Agent(AgentDefinition),
    Shield(ShieldDefinition),
    Pix(PixDefinition),
    Psyche(PsycheDefinition),
    Corpus(CorpusDefinition),
    Dataspace(DataspaceDefinition),
    Ots(OtsDefinition),
    Mandate(MandateDefinition),
    Compute(ComputeDefinition),
    Daemon(DaemonDefinition),
    AxonStore(AxonStoreDefinition),
    AxonEndpoint(AxonEndpointDefinition),
    /// §λ-L-E Fase 1 — I/O cognitivo primitives.
    Resource(ResourceDefinition),
    Fabric(FabricDefinition),
    Manifest(ManifestDefinition),
    Observe(ObserveDefinition),
    /// §λ-L-E Fase 3 — Control cognitivo primitives.
    Reconcile(ReconcileDefinition),
    Lease(LeaseDefinition),
    Ensemble(EnsembleDefinition),
    /// §λ-L-E Fase 4 — Topology + π-calculus binary sessions.
    Session(SessionDefinition),
    Topology(TopologyDefinition),
    /// §λ-L-E Fase 5 — Cognitive immune system (per docs/paper_immune_v2.md).
    Immune(ImmuneDefinition),
    Reflex(ReflexDefinition),
    Heal(HealDefinition),
    /// §λ-L-E Fase 9 — UI cognitiva declarativa.
    Component(ComponentDefinition),
    View(ViewDefinition),
    /// §λ-L-E Fase 13 — Mobile typed channels (paper_mobile_channels.md).
    Channel(ChannelDefinition),
    /// Tier 3+ declarations parsed structurally (balanced braces, no detailed AST).
    Generic(GenericDeclaration),
}

// ── §λ-L-E Fase 1 — Resource primitive ───────────────────────────────────────

/// `resource Name { kind, endpoint, capacity, lifetime, certainty_floor, shield }`
///
/// An infrastructure resource declared as a linear, affine, or persistent
/// token. Linear/affine resources cannot be aliased across manifests
/// (Separation Logic `*` disjointness).
#[derive(Debug, Default)]
pub struct ResourceDefinition {
    pub name: String,
    pub kind: String,                 // postgres | redis | s3 | vpc | gpu | compute | file | custom
    pub endpoint: String,             // connection URI
    pub capacity: Option<i64>,        // pool size / instance count hint
    pub lifetime: String,             // linear | affine | persistent (default: affine)
    pub certainty_floor: Option<f64>, // epistemic gate c ∈ [0.0, 1.0]
    pub shield_ref: String,           // optional shield reference
    pub loc: Loc,
}

/// `fabric Name { provider, region, zones, ephemeral, shield }`
///
/// A tagged substrate — the topological container where resources are
/// provisioned. Maps to VPC / cluster / namespace.
#[derive(Debug, Default)]
pub struct FabricDefinition {
    pub name: String,
    pub provider: String,            // aws | gcp | azure | kubernetes | bare_metal | custom
    pub region: String,              // provider-specific region id
    pub zones: Option<i64>,          // number of availability zones
    pub ephemeral: Option<bool>,     // true = destroy on program end
    pub shield_ref: String,          // optional shield reference
    pub loc: Loc,
}

/// `manifest Name { resources, fabric, region, zones, compliance }`
///
/// A declarative specification of desired shape — not a "desired state" in
/// the Terraform sense, a *belief* about structure. Linear/affine resources
/// in `resources` must be disjoint (Separation Logic `*`).
#[derive(Debug, Default)]
pub struct ManifestDefinition {
    pub name: String,
    pub resources: Vec<String>,      // references to ResourceDefinition names
    pub fabric_ref: String,          // reference to FabricDefinition name
    pub region: String,
    pub zones: Option<i64>,
    pub compliance: Vec<String>,     // κ — regulatory class (Fase 6.1)
    pub loc: Loc,
}

/// `observe Name from Manifest { sources, quorum, timeout, on_partition, certainty_floor }`
///
/// A quorum-gated observation of a manifest's real state. Each output
/// carries ΛD envelope E = ⟨c, τ, ρ, δ⟩; `τ` records observation lag.
/// `on_partition: fail` raises a CT-3 (Network Error) — partitions are ⊥ void.
#[derive(Debug, Default)]
pub struct ObserveDefinition {
    pub name: String,
    pub target: String,              // name of ManifestDefinition being observed
    pub sources: Vec<String>,
    pub quorum: Option<i64>,         // Byzantine quorum threshold
    pub timeout: String,             // duration literal "5s", "100ms"
    pub on_partition: String,        // fail (CT-3) | shield_quarantine
    pub certainty_floor: Option<f64>,
    pub loc: Loc,
}

// ── §λ-L-E Fase 3 — Control cognitivo primitives ─────────────────────────────

/// `reconcile Name { observe, threshold, tolerance, on_drift, shield, mandate, max_retries }`
///
/// A cognitive control loop that minimises variational free energy
/// `F = D_KL(q(s) || p(s, o))` between a manifest belief and an observe
/// evidence. Acting on the environment (`on_drift: provision`) is one of
/// the two classical routes to reducing F (the other is belief revision).
#[derive(Debug, Default)]
pub struct ReconcileDefinition {
    pub name: String,
    pub observe_ref: String,
    pub threshold: Option<f64>,       // epistemic gate c ∈ [0.0, 1.0]
    pub tolerance: Option<f64>,       // drift tolerance [0.0, 1.0]
    pub on_drift: String,             // provision | alert | refine (default: provision)
    pub shield_ref: String,
    pub mandate_ref: String,
    pub max_retries: i64,             // default: 3
    pub loc: Loc,
}

/// `lease Name { resource, duration, acquire, on_expire }`
///
/// Affine/linear lease on a resource, with explicit Δt encoded in the `τ`
/// of the ΛD envelope. Runtime materializes each lease as a revocable
/// token; use post-expiry raises `LeaseExpiredError` (CT-2) per D2.
#[derive(Debug, Default)]
pub struct LeaseDefinition {
    pub name: String,
    pub resource_ref: String,
    pub duration: String,             // "30s", "5m", "2h"
    pub acquire: String,              // on_start | on_demand (default: on_start)
    pub on_expire: String,            // anchor_breach | release | extend (default: anchor_breach)
    pub loc: Loc,
}

/// `ensemble Name { observations, quorum, aggregation, certainty_mode }`
///
/// Byzantine quorum aggregator over ≥2 independent observations. Yields
/// common knowledge `Cφ` (Fagin-Halpern) when at least `quorum` observers
/// agree. Failed observations are excluded; below quorum raises CT-3.
#[derive(Debug, Default)]
pub struct EnsembleDefinition {
    pub name: String,
    pub observations: Vec<String>,
    pub quorum: Option<i64>,
    pub aggregation: String,          // majority | weighted | byzantine (default: majority)
    pub certainty_mode: String,       // min | weighted | harmonic (default: min)
    pub loc: Loc,
}

// ── §λ-L-E Fase 4 — Topology + π-calculus binary sessions ──────────────────

/// One step in a session protocol: `send T` | `receive T` | `loop` | `end`.
#[derive(Debug, Clone, Default)]
pub struct SessionStep {
    pub op: String,             // send | receive | loop | end
    pub message_type: String,   // only meaningful for send / receive
    pub loc: Loc,
}

/// One role in a binary session — name + ordered list of steps.
#[derive(Debug, Default)]
pub struct SessionRole {
    pub name: String,
    pub steps: Vec<SessionStep>,
    pub loc: Loc,
}

/// `session Name { role1: [step, …]  role2: [step, …] }`
///
/// A binary session type — exactly two roles whose protocols MUST be
/// pairwise Honda-Vasconcelos dual. Duality is verified by the type
/// checker; non-dual programs are rejected at compile time.
#[derive(Debug, Default)]
pub struct SessionDefinition {
    pub name: String,
    pub roles: Vec<SessionRole>,
    pub loc: Loc,
}

/// `source -> target : Session` — one directed edge of a topology.
///
/// Convention: the source plays the FIRST role of the session; the target
/// plays the SECOND role. Fixed so assignment is unambiguous.
#[derive(Debug, Default)]
pub struct TopologyEdge {
    pub source: String,
    pub target: String,
    pub session_ref: String,
    pub loc: Loc,
}

/// `topology Name { nodes: […]  edges: [A -> B : Session, …] }`
///
/// A typed directed graph over Axon entities. Edges carry session references
/// whose duality the type checker enforces; the graph is statically analysed
/// for Honda-liveness (deadlock-prone cycles).
#[derive(Debug, Default)]
pub struct TopologyDefinition {
    pub name: String,
    pub nodes: Vec<String>,
    pub edges: Vec<TopologyEdge>,
    pub loc: Loc,
}

// ── §λ-L-E Fase 5 — Cognitive immune system (per paper_immune_v2.md) ────────

/// `immune Name { watch, sensitivity, baseline, window, scope, tau, decay }`
///
/// A continuous anomaly sensor over a declared observation vector.
/// Computes D_KL(q_baseline || p_observed) (paper §3.2) and emits a
/// HealthReport at an epistemic level derived from the KL magnitude.
///
/// Pure sensor — `immune` takes NO action. Actions belong to `reflex`
/// and `heal`, which consume its HealthReport.
#[derive(Debug, Default)]
pub struct ImmuneDefinition {
    pub name: String,
    pub watch: Vec<String>,          // observe / ensemble / any declared ref
    pub sensitivity: Option<f64>,    // [0.0, 1.0]
    pub baseline: String,            // "learned" (default) or name of a prior
    pub window: i64,                 // samples used to estimate baseline (default: 100)
    pub scope: String,               // tenant | flow | global (MANDATORY, paper §8.2)
    pub tau: String,                 // duration half-life
    pub decay: String,               // exponential (default) | linear | none
    pub loc: Loc,
}

/// `reflex Name { trigger, on_level, action, scope, sla }`
///
/// Deterministic, O(1) motor response. Contract invariants (paper §4.2):
/// never invokes an LLM; no long-running I/O; every activation emits a
/// signed_trace; idempotent on the same HealthReport.
#[derive(Debug, Default)]
pub struct ReflexDefinition {
    pub name: String,
    pub trigger: String,             // immune name (MANDATORY)
    pub on_level: String,            // know | believe | speculate | doubt (default: doubt)
    pub action: String,              // drop | revoke | emit | redact | quarantine | terminate | alert
    pub scope: String,               // MANDATORY, paper §8.2
    pub sla: String,                 // duration budget (e.g. "1ms")
    pub loc: Loc,
}

/// `heal Name { source, on_level, mode, scope, review_sla, shield, max_patches }`
///
/// Linear-Logic one-shot patch synthesis. Patch type:
/// `!Synthesized ⊸ Applied ⊸ Collapsed` (paper §6) — each transition
/// consumes its predecessor, guaranteeing single application + forced collapse.
///
/// Mode ∈ {audit_only | human_in_loop | adversarial} controls automation
/// (paper §7); `adversarial` REQUIRES a shield gate (paper §7.3).
#[derive(Debug, Default)]
pub struct HealDefinition {
    pub name: String,
    pub source: String,              // immune name (MANDATORY)
    pub on_level: String,            // know | believe | speculate | doubt
    pub mode: String,                // audit_only | human_in_loop | adversarial
    pub scope: String,               // MANDATORY
    pub review_sla: String,          // duration
    pub shield_ref: String,          // optional shield gate (required for adversarial)
    pub max_patches: i64,            // bounded heal attempts (default: 3)
    pub loc: Loc,
}

// ── §λ-L-E Fase 9 — UI cognitiva (component / view) ─────────────────────────

/// `component Name { renders, via_shield, on_interact, render_hint }`.
///
/// A reusable UI fragment. `renders` is the data type the component
/// visualizes; if that type has κ, `via_shield` is mandatory and its
/// compliance set MUST cover the type's κ (compile-time enforcement).
#[derive(Debug, Default)]
pub struct ComponentDefinition {
    pub name: String,
    pub renders: String,
    pub via_shield: String,
    pub on_interact: String,
    pub render_hint: String,   // card | list | form | chart | custom
    pub loc: Loc,
}

/// `view Name { title, components: [...], route }`.
///
/// A top-level screen. `components` is an ordered list of declared
/// `component` names composed in the view's primary layout.
#[derive(Debug, Default)]
pub struct ViewDefinition {
    pub name: String,
    pub title: String,
    pub components: Vec<String>,
    pub route: String,
    pub loc: Loc,
}

// ── Tier 2+ structural fallback ──────────────────────────────────────────────

/// A declaration we recognize by keyword but parse only structurally.
/// Validates brace balance and captures keyword + name.
#[derive(Debug)]
pub struct GenericDeclaration {
    pub keyword: String,
    pub name: String,
    pub loc: Loc,
}

// ── Agent ────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AgentDefinition {
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String,          // react | reflexion | plan_and_execute | custom
    pub on_stuck: String,          // forge | hibernate | escalate | retry
    pub shield_ref: String,
    pub max_iterations: Option<i64>,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
    pub loc: Loc,
}

// ── Shield ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ShieldDefinition {
    pub name: String,
    pub scan: Vec<String>,
    pub strategy: String,          // pattern | classifier | dual_llm | canary | perplexity | ensemble
    pub on_breach: String,         // halt | sanitize_and_retry | escalate | quarantine | deflect
    pub severity: String,          // low | medium | high | critical
    pub quarantine: String,
    pub max_retries: Option<i64>,
    pub confidence_threshold: Option<f64>,
    pub allow_tools: Vec<String>,
    pub deny_tools: Vec<String>,
    pub sandbox: Option<bool>,
    pub redact: Vec<String>,
    pub log: String,
    pub deflect_message: String,
    pub taint: String,
    /// §ESK Fase 6.1 — regulatory coverage (HIPAA, PCI_DSS, GDPR, …).
    pub compliance: Vec<String>,
    pub loc: Loc,
}

// ── Pix ──────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct PixDefinition {
    pub name: String,
    pub source: String,
    pub depth: Option<i64>,
    pub branching: Option<i64>,
    pub model: String,
    pub loc: Loc,
}

// ── Psyche ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct PsycheDefinition {
    pub name: String,
    pub dimensions: Vec<String>,
    pub manifold_noise: Option<f64>,
    pub manifold_momentum: Option<f64>,
    pub safety_constraints: Vec<String>,
    pub quantum_enabled: Option<bool>,
    pub inference_mode: String,    // active | passive
    pub loc: Loc,
}

// ── Corpus ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct CorpusDefinition {
    pub name: String,
    pub documents: Vec<String>,    // simplified: list of pix refs
    pub mcp_server: String,
    pub mcp_resource_uri: String,
    pub loc: Loc,
}

// ── Dataspace ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct DataspaceDefinition {
    pub name: String,
    pub loc: Loc,
}

// ── OTS ──────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct OtsDefinition {
    pub name: String,
    pub teleology: String,
    pub homotopy_search: String,   // shallow | deep | speculative
    pub loss_function: String,
    pub loc: Loc,
}

// ── Mandate ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct MandateDefinition {
    pub name: String,
    pub constraint: String,
    pub kp: Option<f64>,
    pub ki: Option<f64>,
    pub kd: Option<f64>,
    pub tolerance: Option<f64>,
    pub max_steps: Option<i64>,
    pub on_violation: String,      // coerce | halt | retry
    pub loc: Loc,
}

// ── Compute ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ComputeDefinition {
    pub name: String,
    pub shield_ref: String,
    pub loc: Loc,
}

// ── Daemon ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct DaemonDefinition {
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String,          // react | reflexion | plan_and_execute | custom
    pub on_stuck: String,          // hibernate | escalate | retry | forge
    pub shield_ref: String,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
    /// §λ-L-E Fase 13 D4 — listen blocks captured for type-checker
    /// validation (typed-channel ref + dual-mode deprecation warning).
    /// Pre-Fase 13 the parser discarded these structurally; we now
    /// retain them so 13.b/13.f can validate emit/publish/discover
    /// inside listener bodies and surface D4 string-topic warnings.
    pub listeners: Vec<ListenStep>,
    pub loc: Loc,
}

// ── AxonStore ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AxonStoreDefinition {
    pub name: String,
    pub backend: String,           // sqlite | postgresql | mysql
    pub connection: String,
    pub confidence_floor: Option<f64>,
    pub isolation: String,         // read_committed | repeatable_read | serializable
    pub on_breach: String,         // rollback | raise | log
    pub loc: Loc,
}

// ── AxonEndpoint ─────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AxonEndpointDefinition {
    pub name: String,
    pub method: String,            // GET | POST | PUT | DELETE
    pub path: String,
    pub body_type: String,
    pub execute_flow: String,
    pub output_type: String,
    pub shield_ref: String,
    pub retries: Option<i64>,
    pub timeout: String,
    /// §ESK Fase 6.1 — regulatory coverage on the boundary.
    pub compliance: Vec<String>,
    pub loc: Loc,
}

// ── Import ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ImportNode {
    pub module_path: Vec<String>,
    pub names: Vec<String>,
    pub loc: Loc,
}

// ── Persona ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct PersonaDefinition {
    pub name: String,
    pub domain: Vec<String>,
    pub tone: String,
    pub confidence_threshold: Option<f64>,
    pub cite_sources: Option<bool>,
    pub refuse_if: Vec<String>,
    pub language: String,
    pub description: String,
    pub loc: Loc,
}

// ── Context ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ContextDefinition {
    pub name: String,
    pub memory_scope: String,
    pub language: String,
    pub depth: String,
    pub max_tokens: Option<i64>,
    pub temperature: Option<f64>,
    pub cite_sources: Option<bool>,
    pub loc: Loc,
}

// ── Anchor ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AnchorConstraint {
    pub name: String,
    pub require: String,
    pub reject: Vec<String>,
    pub enforce: String,
    pub description: String,
    pub confidence_floor: Option<f64>,
    pub unknown_response: String,
    pub on_violation: String,
    pub on_violation_target: String,
    pub loc: Loc,
}

// ── Memory ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct MemoryDefinition {
    pub name: String,
    pub store: String,
    pub backend: String,
    pub retrieval: String,
    pub decay: String,
    pub loc: Loc,
}

// ── Tool ─────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ToolDefinition {
    pub name: String,
    pub provider: String,
    pub max_results: Option<i64>,
    pub filter_expr: String,
    pub timeout: String,
    pub runtime: String,
    pub sandbox: Option<bool>,
    pub effects: Option<EffectRow>,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct EffectRow {
    pub effects: Vec<String>,
    pub epistemic_level: String,
    pub loc: Loc,
}

// ── Type ─────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct TypeDefinition {
    pub name: String,
    pub fields: Vec<TypeField>,
    pub range_constraint: Option<RangeConstraint>,
    pub where_clause: Option<WhereClause>,
    /// §ESK Fase 6.1 — κ regulatory class attached to a type.
    pub compliance: Vec<String>,
    pub loc: Loc,
}

#[derive(Debug, Clone)]
pub struct TypeExpr {
    pub name: String,
    pub generic_param: String,
    pub optional: bool,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct TypeField {
    pub name: String,
    pub type_expr: TypeExpr,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct RangeConstraint {
    pub min_value: f64,
    pub max_value: f64,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct WhereClause {
    pub expression: String,
    pub loc: Loc,
}

// ── Flow ─────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct FlowDefinition {
    pub name: String,
    pub parameters: Vec<Parameter>,
    pub return_type: Option<TypeExpr>,
    pub body: Vec<FlowStep>,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct Parameter {
    pub name: String,
    pub type_expr: TypeExpr,
    pub loc: Loc,
}

/// Statements that can appear inside a flow body.
#[derive(Debug)]
pub enum FlowStep {
    Step(StepNode),
    If(ConditionalNode),
    ForIn(ForInStatement),
    Let(LetStatement),
    Return(ReturnStatement),
    /// Lambda Data application in a flow step.
    LambdaDataApply(LambdaDataApplyNode),
    // ── Tier 2 flow steps ──
    Probe(ProbeStep),
    Reason(ReasonStep),
    Validate(ValidateStep),
    Refine(RefineStep),
    Weave(WeaveStep),
    UseTool(UseToolStep),
    Remember(RememberStep),
    Recall(RecallStep),
    Par(ParBlock),
    Hibernate(HibernateStep),
    Deliberate(DeliberateBlock),
    Consensus(ConsensusBlock),
    Forge(ForgeBlock),
    Focus(FocusStep),
    Associate(AssociateStep),
    Aggregate(AggregateStep),
    ExploreStep(ExploreStepNode),
    Ingest(IngestStep),
    ShieldApply(ShieldApplyStep),
    Stream(StreamBlock),
    Navigate(NavigateStep),
    Drill(DrillStep),
    Trail(TrailStep),
    Corroborate(CorroborateStep),
    OtsApply(OtsApplyStep),
    MandateApply(MandateApplyStep),
    ComputeApply(ComputeApplyStep),
    Listen(ListenStep),
    DaemonStep(DaemonStepNode),
    /// §λ-L-E Fase 13 — π-calculus output prefix `c⟨v⟩.P` (Chan-Output / Chan-Mobility).
    Emit(EmitStatement),
    /// §λ-L-E Fase 13 — capability extrusion (Publish-Ext, paper §4.3).
    Publish(PublishStatement),
    /// §λ-L-E Fase 13 — dual of publish (dynamic typed handle import).
    Discover(DiscoverStatement),
    Persist(PersistStep),
    Retrieve(RetrieveStep),
    Mutate(MutateStep),
    Purge(PurgeStep),
    Transact(TransactBlock),
    /// Flow-level statements we recognize but parse structurally.
    GenericStep(GenericFlowStep),
}

/// A flow step we recognize by keyword but parse only structurally.
#[derive(Debug)]
pub struct GenericFlowStep {
    pub keyword: String,
    pub loc: Loc,
}

// ── Step ─────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct StepNode {
    pub name: String,
    pub persona_ref: String,
    pub given: String,
    pub ask: String,
    pub output_type: String,
    pub confidence_floor: Option<f64>,
    pub navigate_ref: String,
    pub apply_ref: String,
    pub loc: Loc,
}

// ── Intent ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct IntentNode {
    pub name: String,
    pub given: String,
    pub ask: String,
    pub output_type: Option<TypeExpr>,
    pub confidence_floor: Option<f64>,
    pub loc: Loc,
}

// ── Run ──────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct RunStatement {
    pub flow_name: String,
    pub arguments: Vec<String>,
    pub persona: String,
    pub context: String,
    pub anchors: Vec<String>,
    pub on_failure: String,
    pub on_failure_params: Vec<(String, String)>,
    pub output_to: String,
    pub effort: String,
    pub loc: Loc,
}

// ── Epistemic ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct EpistemicBlock {
    pub mode: String,
    pub body: Vec<Declaration>,
    pub loc: Loc,
}

// ── Control flow ─────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ConditionalNode {
    pub condition: String,
    pub comparison_op: String,
    pub comparison_value: String,
    pub then_body: Vec<FlowStep>,
    pub else_body: Vec<FlowStep>,
    pub conditions: Vec<(String, String, String)>,
    pub conjunctor: String,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct ForInStatement {
    pub variable: String,
    pub iterable: String,
    pub body: Vec<FlowStep>,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct LetStatement {
    pub identifier: String,
    pub value_expr: String,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct ReturnStatement {
    pub value_expr: String,
    pub loc: Loc,
}

// ── Lambda Data (ΛD) — Epistemic State Vectors ─────────────────────────────

/// Top-level ΛD definition: ψ = ⟨T, V, E⟩ where E = ⟨c, τ, ρ, δ⟩.
#[derive(Debug)]
pub struct LambdaDataDefinition {
    pub name: String,
    pub ontology: String,                  // T ∈ O — ontological type
    pub certainty: f64,                    // c ∈ [0,1] — epistemic certainty scalar
    pub temporal_frame_start: String,      // τ_start
    pub temporal_frame_end: String,        // τ_end
    pub provenance: String,               // ρ ∈ EntityRef — causal origin
    pub derivation: String,               // δ ∈ Δ = {raw, derived, inferred, aggregated, transformed}
    pub loc: Loc,
}

/// In-flow ΛD application: binds epistemic state vector to a data target.
#[derive(Debug)]
pub struct LambdaDataApplyNode {
    pub lambda_data_name: String,          // reference to LambdaDataDefinition
    pub target: String,                    // expression to bind
    pub output_type: String,              // result type after epistemic binding
    pub loc: Loc,
}

// ── Tier 2 flow step nodes ──────────────────────────────────────────────────

#[derive(Debug)]
pub struct ProbeStep { pub target: String, pub loc: Loc }
#[derive(Debug)]
pub struct ReasonStep { pub strategy: String, pub target: String, pub loc: Loc }
#[derive(Debug)]
pub struct ValidateStep { pub target: String, pub rule: String, pub loc: Loc }
#[derive(Debug)]
pub struct RefineStep { pub target: String, pub strategy: String, pub loc: Loc }
#[derive(Debug)]
pub struct WeaveStep {
    pub sources: Vec<String>, pub target: String, pub format_type: String,
    pub priority: Vec<String>, pub style: String, pub loc: Loc,
}
#[derive(Debug)]
pub struct UseToolStep { pub tool_name: String, pub argument: String, pub loc: Loc }
#[derive(Debug)]
pub struct RememberStep { pub expression: String, pub memory_target: String, pub loc: Loc }
#[derive(Debug)]
pub struct RecallStep { pub query: String, pub memory_source: String, pub loc: Loc }
#[derive(Debug)]
pub struct ParBlock { pub loc: Loc }
#[derive(Debug)]
pub struct HibernateStep { pub event_name: String, pub timeout: String, pub loc: Loc }
#[derive(Debug)]
pub struct DeliberateBlock { pub loc: Loc }
#[derive(Debug)]
pub struct ConsensusBlock { pub loc: Loc }
#[derive(Debug)]
pub struct ForgeBlock { pub loc: Loc }
#[derive(Debug)]
pub struct FocusStep { pub expression: String, pub loc: Loc }
#[derive(Debug)]
pub struct AssociateStep { pub left: String, pub right: String, pub using_field: String, pub loc: Loc }
#[derive(Debug)]
pub struct AggregateStep { pub target: String, pub group_by: Vec<String>, pub alias: String, pub loc: Loc }
#[derive(Debug)]
pub struct ExploreStepNode { pub target: String, pub limit: Option<i64>, pub loc: Loc }
#[derive(Debug)]
pub struct IngestStep { pub source: String, pub target: String, pub loc: Loc }
#[derive(Debug)]
pub struct ShieldApplyStep { pub shield_name: String, pub target: String, pub output_type: String, pub loc: Loc }
#[derive(Debug)]
pub struct StreamBlock { pub loc: Loc }
#[derive(Debug)]
pub struct NavigateStep {
    pub pix_name: String, pub corpus_name: String, pub query_expr: String,
    pub trail_enabled: bool, pub output_name: String, pub loc: Loc,
}
#[derive(Debug)]
pub struct DrillStep { pub pix_name: String, pub subtree_path: String, pub query_expr: String, pub output_name: String, pub loc: Loc }
#[derive(Debug)]
pub struct TrailStep { pub navigate_ref: String, pub loc: Loc }
#[derive(Debug)]
pub struct CorroborateStep { pub navigate_ref: String, pub output_name: String, pub loc: Loc }
#[derive(Debug)]
pub struct OtsApplyStep { pub ots_name: String, pub target: String, pub output_type: String, pub loc: Loc }
#[derive(Debug)]
pub struct MandateApplyStep { pub mandate_name: String, pub target: String, pub output_type: String, pub loc: Loc }
#[derive(Debug)]
pub struct ComputeApplyStep { pub compute_name: String, pub arguments: Vec<String>, pub output_name: String, pub loc: Loc }
/// §λ-L-E Fase 13 D4 — dual-mode listen.
///
/// `channel_is_ref = true` ⇒ `channel` is the name of a declared
/// `ChannelDefinition` (canonical Fase 13 form).  `false` ⇒ legacy
/// string topic (deprecated; type checker emits a warning).
#[derive(Debug)]
pub struct ListenStep {
    pub channel: String,
    pub channel_is_ref: bool,
    pub event_alias: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct DaemonStepNode { pub daemon_ref: String, pub loc: Loc }
#[derive(Debug)]
pub struct PersistStep { pub store_name: String, pub loc: Loc }
#[derive(Debug)]
pub struct RetrieveStep { pub store_name: String, pub where_expr: String, pub alias: String, pub loc: Loc }
#[derive(Debug)]
pub struct MutateStep { pub store_name: String, pub where_expr: String, pub loc: Loc }
#[derive(Debug)]
pub struct PurgeStep { pub store_name: String, pub where_expr: String, pub loc: Loc }
#[derive(Debug)]
pub struct TransactBlock { pub loc: Loc }

// ── §λ-L-E Fase 13 — Mobile Typed Channels ──────────────────────────────────

/// `channel Name { message: T, qos: X, lifetime: ℓ, persistence: π, shield: σ }`.
///
/// First-class affine resource carrying a typed message.  Direct port
/// of `axon.compiler.ast_nodes.ChannelDefinition`.  `message` retains
/// the surface spelling (e.g. `"Order"` or `"Channel<Order>"`) so the
/// type checker can resolve nested mobility (paper §3.3).
#[derive(Debug)]
pub struct ChannelDefinition {
    pub name: String,
    pub message: String,        // type name OR "Channel<T>" for second-order
    pub qos: String,            // at_most_once | at_least_once | exactly_once | broadcast | queue
    pub lifetime: String,       // linear | affine | persistent (D1 default: affine)
    pub persistence: String,    // ephemeral | persistent_axonstore
    pub shield_ref: String,     // optional σ-shield gate for publish (D8)
    pub loc: Loc,
}

/// `emit ChannelName(value_ref)` — π-calculus output prefix `c⟨v⟩.P`.
///
/// Direct port of `axon.compiler.ast_nodes.EmitStatement`.  Handles
/// both Chan-Output (scalar payload) and Chan-Mobility (channel-as-
/// value); the type checker dispatches based on whether `value_ref`
/// resolves to a `ChannelDefinition`.
#[derive(Debug)]
pub struct EmitStatement {
    pub channel_ref: String,
    pub value_ref: String,
    pub loc: Loc,
}

/// `publish ChannelName within ShieldName` — capability extrusion.
///
/// Paper §4.3 (Publish-Ext) materialized as a flow step.  The `within
/// <Shield>` clause is mandatory (D8) — the parser rejects bare
/// `publish C`, the type checker rejects publishes whose shield does
/// not cover κ(message_type) (Fase 6.1 + paper §3.4).
#[derive(Debug)]
pub struct PublishStatement {
    pub channel_ref: String,
    pub shield_ref: String,
    pub loc: Loc,
}

/// `discover ChannelName as alias` — dual of publish.
///
/// Imports a previously-published handle into a fresh affine local
/// binding.  The `as <alias>` is mandatory; the type checker rejects
/// discovery of channels that were never declared with `shield_ref`.
#[derive(Debug)]
pub struct DiscoverStatement {
    pub capability_ref: String,
    pub alias: String,
    pub loc: Loc,
}
