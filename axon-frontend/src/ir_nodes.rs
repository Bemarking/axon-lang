//! AXON IR node definitions — direct port of axon/compiler/ir_nodes.py.
//!
//! All nodes serialize to JSON matching the Python IR output format exactly.

#![allow(dead_code)]

use serde::Serialize;

// ── Program root ─────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRProgram {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub personas: Vec<IRPersona>,
    pub contexts: Vec<IRContext>,
    pub anchors: Vec<IRAnchor>,
    pub tools: Vec<IRToolSpec>,
    pub memories: Vec<IRMemory>,
    pub types: Vec<IRType>,
    pub flows: Vec<IRFlow>,
    pub runs: Vec<IRRun>,
    pub imports: Vec<IRImport>,
    pub agents: Vec<IRAgent>,
    pub shields: Vec<IRShield>,
    pub daemons: Vec<IRDaemon>,
    pub ots_specs: Vec<IROts>,
    pub pix_specs: Vec<IRPix>,
    pub corpus_specs: Vec<IRCorpus>,
    pub psyche_specs: Vec<IRPsyche>,
    pub mandate_specs: Vec<IRMandate>,
    pub lambda_data_specs: Vec<IRLambdaData>,
    pub compute_specs: Vec<IRCompute>,
    pub axonstore_specs: Vec<IRAxonStore>,
    pub endpoints: Vec<IRAxonEndpoint>,
    /// Local-only: IRDataspace specs are computed during IR generation so
    /// the cost estimator and inspectors can reach them, but Python's
    /// reference IRProgram does not serialise this field. Hidden from JSON
    /// output for byte-identical parity (§8.2.h.1).
    #[serde(skip)]
    pub dataspace_specs: Vec<IRDataspace>,
    /// §λ-L-E Fase 1 — I/O cognitivo primitives (compiled).
    pub resources: Vec<IRResource>,
    pub fabrics: Vec<IRFabric>,
    pub manifests: Vec<IRManifest>,
    pub observations: Vec<IRObserve>,
    /// §λ-L-E Fase 1 (Free Monad root) — populated when the program
    /// declares manifests/observes. `None` ⇒ serialises as `null`
    /// (matches Python when the field is `None`).
    pub intention_tree: Option<IRIntentionTree>,
    /// §λ-L-E Fase 3 — Control cognitivo primitives (compiled).
    pub reconciles: Vec<IRReconcile>,
    pub leases: Vec<IRLease>,
    pub ensembles: Vec<IREnsemble>,
    /// §λ-L-E Fase 4 — Topology + Session (compiled).
    pub sessions: Vec<IRSession>,
    pub topologies: Vec<IRTopology>,
    /// §λ-L-E Fase 5 — Immune system (compiled).
    pub immunes: Vec<IRImmune>,
    pub reflexes: Vec<IRReflex>,
    pub heals: Vec<IRHeal>,
    /// §λ-L-E Fase 9 — UI cognitiva declarativa (compiled).
    pub components: Vec<IRComponent>,
    pub views: Vec<IRView>,
}

impl IRProgram {
    pub fn new() -> Self {
        IRProgram {
            node_type: "program",
            source_line: 1,
            source_column: 1,
            personas: Vec::new(),
            contexts: Vec::new(),
            anchors: Vec::new(),
            tools: Vec::new(),
            memories: Vec::new(),
            types: Vec::new(),
            flows: Vec::new(),
            runs: Vec::new(),
            imports: Vec::new(),
            agents: Vec::new(),
            shields: Vec::new(),
            daemons: Vec::new(),
            ots_specs: Vec::new(),
            pix_specs: Vec::new(),
            corpus_specs: Vec::new(),
            psyche_specs: Vec::new(),
            mandate_specs: Vec::new(),
            lambda_data_specs: Vec::new(),
            compute_specs: Vec::new(),
            axonstore_specs: Vec::new(),
            endpoints: Vec::new(),
            dataspace_specs: Vec::new(),
            resources: Vec::new(),
            fabrics: Vec::new(),
            manifests: Vec::new(),
            observations: Vec::new(),
            intention_tree: None,
            reconciles: Vec::new(),
            leases: Vec::new(),
            ensembles: Vec::new(),
            sessions: Vec::new(),
            topologies: Vec::new(),
            immunes: Vec::new(),
            reflexes: Vec::new(),
            heals: Vec::new(),
            components: Vec::new(),
            views: Vec::new(),
        }
    }
}

// ── §λ-L-E Fase 1 — IRResource ──────────────────────────────────────────────

/// Compiled resource declaration — linear/affine infrastructure token.
///
/// Python counterpart: `axon.compiler.ir_nodes.IRResource`.
#[derive(Debug, Clone, Serialize)]
pub struct IRResource {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub kind: String,
    pub endpoint: String,
    pub capacity: Option<i64>,
    pub lifetime: String,             // linear | affine | persistent
    pub certainty_floor: Option<f64>, // c ∈ [0.0, 1.0]
    pub shield_ref: String,
}

impl IRResource {
    pub fn new(name: String, line: u32, column: u32) -> Self {
        IRResource {
            node_type: "resource",
            source_line: line,
            source_column: column,
            name,
            kind: String::new(),
            endpoint: String::new(),
            capacity: None,
            lifetime: "affine".to_string(),
            certainty_floor: None,
            shield_ref: String::new(),
        }
    }
}

// ── §λ-L-E Fase 1 — IRFabric ────────────────────────────────────────────────

/// Compiled fabric declaration — topological substrate for resources.
#[derive(Debug, Clone, Serialize)]
pub struct IRFabric {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub provider: String,
    pub region: String,
    pub zones: Option<i64>,
    pub ephemeral: Option<bool>,
    pub shield_ref: String,
}

// ── §λ-L-E Fase 1 — IRManifest ──────────────────────────────────────────────

/// Compiled manifest declaration — declarative belief about desired shape.
#[derive(Debug, Clone, Serialize)]
pub struct IRManifest {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub resources: Vec<String>,
    pub fabric_ref: String,
    pub region: String,
    pub zones: Option<i64>,
    pub compliance: Vec<String>,
}

// ── §λ-L-E Fase 1 — IRObserve ───────────────────────────────────────────────

// ── §λ-L-E Fase 1 — IRIntentionTree (Free Monad root) ──────────────────────

/// A single operation node in the intention tree.
///
/// Operations are heterogeneous IR nodes (manifests, observes) that the
/// Handler layer (Fase 2) interprets via CPS. The enum is `#[serde(untagged)]`
/// so JSON output is just the inner struct — matching Python's `asdict`
/// behaviour on a polymorphic `tuple[IRNode, ...]`.
#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum IRIntentionOperation {
    Manifest(IRManifest),
    Observe(IRObserve),
}

/// The Free Monad F_Σ(X) — a pure description of I/O intentions. Flat in
/// Fase 1; nested continuations arrive with handlers + reconcile loops.
#[derive(Debug, Clone, Serialize)]
pub struct IRIntentionTree {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub operations: Vec<IRIntentionOperation>,
}

/// Compiled observe declaration — quorum-gated observation with lag τ.
#[derive(Debug, Clone, Serialize)]
pub struct IRObserve {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub target: String,
    pub sources: Vec<String>,
    pub quorum: Option<i64>,
    pub timeout: String,
    pub on_partition: String,
    pub certainty_floor: Option<f64>,
}

// ── §λ-L-E Fase 3 — IRReconcile / IRLease / IREnsemble ──────────────────────

/// Compiled reconcile declaration — free-energy minimizing control loop.
#[derive(Debug, Clone, Serialize)]
pub struct IRReconcile {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub observe_ref: String,
    pub threshold: Option<f64>,
    pub tolerance: Option<f64>,
    pub on_drift: String,
    pub shield_ref: String,
    pub mandate_ref: String,
    pub max_retries: i64,
}

/// Compiled lease declaration — τ-decaying affine resource token.
#[derive(Debug, Clone, Serialize)]
pub struct IRLease {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub resource_ref: String,
    pub duration: String,
    pub acquire: String,
    pub on_expire: String,
}

/// Compiled ensemble declaration — Byzantine quorum aggregator.
#[derive(Debug, Clone, Serialize)]
pub struct IREnsemble {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub observations: Vec<String>,
    pub quorum: Option<i64>,
    pub aggregation: String,
    pub certainty_mode: String,
}

// ── §λ-L-E Fase 4 — IRSession / IRTopology ──────────────────────────────────

/// One operation in a compiled session protocol (send / receive / loop / end).
#[derive(Debug, Clone, Serialize)]
pub struct IRSessionStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub op: String,
    pub message_type: String,
}

/// A role's name and its ordered protocol steps.
#[derive(Debug, Clone, Serialize)]
pub struct IRSessionRole {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub steps: Vec<IRSessionStep>,
}

/// Compiled binary session — exactly two dual roles (verified at type-check).
#[derive(Debug, Clone, Serialize)]
pub struct IRSession {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub roles: Vec<IRSessionRole>,
}

/// Directed, session-typed edge between two topology nodes.
#[derive(Debug, Clone, Serialize)]
pub struct IRTopologyEdge {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub source: String,
    pub target: String,
    pub session_ref: String,
}

/// Compiled topology — typed graph over Axon entities.
#[derive(Debug, Clone, Serialize)]
pub struct IRTopology {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub nodes: Vec<String>,
    pub edges: Vec<IRTopologyEdge>,
}

// ── §λ-L-E Fase 5 — IRImmune / IRReflex / IRHeal ────────────────────────────

/// Compiled immune sensor — KL+FEP anomaly detector descriptor.
#[derive(Debug, Clone, Serialize)]
pub struct IRImmune {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub watch: Vec<String>,
    pub sensitivity: Option<f64>,
    pub baseline: String,
    pub window: i64,
    pub scope: String,
    pub tau: String,
    pub decay: String,
}

/// Compiled reflex — deterministic O(1) motor response descriptor.
#[derive(Debug, Clone, Serialize)]
pub struct IRReflex {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub trigger: String,
    pub on_level: String,
    pub action: String,
    pub scope: String,
    pub sla: String,
}

/// Compiled heal — Linear-Logic one-shot patch kernel descriptor.
#[derive(Debug, Clone, Serialize)]
pub struct IRHeal {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub source: String,
    pub on_level: String,
    pub mode: String,
    pub scope: String,
    pub review_sla: String,
    pub shield_ref: String,
    pub max_patches: i64,
}

// ── §λ-L-E Fase 9 — IRComponent / IRView ────────────────────────────────────

/// Compiled UI component — reusable fragment over a typed data source.
#[derive(Debug, Clone, Serialize)]
pub struct IRComponent {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub renders: String,
    pub via_shield: String,
    pub on_interact: String,
    pub render_hint: String,
}

/// Compiled UI view — top-level screen composing declared components.
#[derive(Debug, Clone, Serialize)]
pub struct IRView {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub title: String,
    pub components: Vec<String>,
    pub route: String,
}

// ── Import ───────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRImport {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub module_path: Vec<String>,
    pub names: Vec<String>,
}

// ── Persona ──────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRPersona {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub domain: Vec<String>,
    pub tone: String,
    pub confidence_threshold: Option<f64>,
    pub cite_sources: Option<bool>,
    pub refuse_if: Vec<String>,
    pub language: String,
    pub description: String,
}

// ── Context ──────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRContext {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub memory_scope: String,
    pub language: String,
    pub depth: String,
    pub max_tokens: Option<i64>,
    pub temperature: Option<f64>,
    pub cite_sources: Option<bool>,
}

// ── Anchor ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRAnchor {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub description: String,
    pub require: String,
    pub reject: Vec<String>,
    pub enforce: String,
    pub confidence_floor: Option<f64>,
    pub unknown_response: String,
    pub on_violation: String,
    pub on_violation_target: String,
}

// ── Tool ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRToolSpec {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub provider: String,
    pub max_results: Option<i64>,
    pub filter_expr: String,
    pub timeout: String,
    pub runtime: String,
    pub sandbox: Option<bool>,
    pub input_schema: Vec<String>,
    pub output_schema: String,
    pub effect_row: Vec<String>,
}

// ── Memory ───────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRMemory {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub store: String,
    pub backend: String,
    pub retrieval: String,
    pub decay: String,
}

// ── Type ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRTypeField {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub type_name: String,
    pub generic_param: String,
    pub optional: bool,
}

#[derive(Debug, Serialize)]
pub struct IRType {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub fields: Vec<IRTypeField>,
    pub range_min: Option<f64>,
    pub range_max: Option<f64>,
    pub where_expression: String,
    /// §ESK Fase 6.1 — κ regulatory class.
    pub compliance: Vec<String>,
}

// ── Flow ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRParameter {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub type_name: String,
    pub generic_param: String,
    pub optional: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDataEdge {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub source_step: String,
    pub target_step: String,
    pub type_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub persona_ref: String,
    pub given: String,
    pub ask: String,
    pub use_tool: Option<serde_json::Value>,
    pub probe: Option<serde_json::Value>,
    pub reason: Option<serde_json::Value>,
    pub weave: Option<serde_json::Value>,
    pub output_type: String,
    pub confidence_floor: Option<f64>,
    pub navigate_ref: String,
    pub apply_ref: String,
    pub body: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRFlow {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub parameters: Vec<IRParameter>,
    pub return_type_name: String,
    pub return_type_generic: String,
    pub return_type_optional: bool,
    pub steps: Vec<IRFlowNode>,
    pub edges: Vec<IRDataEdge>,
    pub execution_levels: Vec<Vec<String>>,
}

// ── Run ──────────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct IRRun {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub flow_name: String,
    pub arguments: Vec<String>,
    pub persona_name: String,
    pub context_name: String,
    pub anchor_names: Vec<String>,
    pub on_failure: String,
    pub on_failure_params: Vec<Vec<String>>,
    pub output_to: String,
    pub effort: String,
    pub resolved_flow: Option<IRFlow>,
    pub resolved_persona: Option<IRPersona>,
    pub resolved_context: Option<IRContext>,
    pub resolved_anchors: Vec<IRAnchor>,
}

// ── Lambda Data (ΛD) — Epistemic State Vectors ─────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRLambdaData {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub ontology: String,                  // T — ontological type
    pub certainty: f64,                    // c ∈ [0,1]
    pub temporal_frame_start: String,      // τ_start
    pub temporal_frame_end: String,        // τ_end
    pub provenance: String,               // ρ — EntityRef origin
    pub derivation: String,               // δ ∈ Δ
}

#[derive(Debug, Clone, Serialize)]
pub struct IRLambdaDataApply {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub lambda_data_name: String,          // reference to declared ΛD
    pub target: String,                    // expression being bound
    pub output_type: String,              // result type after binding
}

// ── Flow step IR nodes ──────────────────────────────────────────────────────

/// Polymorphic flow body node — serializes via #[serde(untagged)] so each
/// variant emits its inner struct's JSON (with its own `node_type` field).
#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum IRFlowNode {
    Step(IRStep),
    Probe(IRProbe),
    Reason(IRReasonStep),
    Validate(IRValidateStep),
    Refine(IRRefineStep),
    Weave(IRWeaveStep),
    UseTool(IRUseToolStep),
    Remember(IRRememberStep),
    Recall(IRRecallStep),
    Conditional(IRConditional),
    ForIn(IRForIn),
    Let(IRLetBinding),
    Return(IRReturnStep),
    LambdaDataApply(IRLambdaDataApply),
    Par(IRParallelBlock),
    Hibernate(IRHibernateStep),
    Deliberate(IRDeliberateBlock),
    Consensus(IRConsensusBlock),
    Forge(IRForgeBlock),
    Focus(IRFocusStep),
    Associate(IRAssociateStep),
    Aggregate(IRAggregateStep),
    Explore(IRExploreStep),
    Ingest(IRIngestStep),
    ShieldApply(IRShieldApplyStep),
    Stream(IRStreamBlock),
    Navigate(IRNavigateStep),
    Drill(IRDrillStep),
    Trail(IRTrailStep),
    Corroborate(IRCorroborateStep),
    OtsApply(IROtsApplyStep),
    MandateApply(IRMandateApplyStep),
    ComputeApply(IRComputeApplyStep),
    Listen(IRListenStep),
    DaemonStep(IRDaemonStepNode),
    Persist(IRPersistStep),
    Retrieve(IRRetrieveStep),
    Mutate(IRMutateStep),
    Purge(IRPurgeStep),
    Transact(IRTransactBlock),
}

#[derive(Debug, Clone, Serialize)]
pub struct IRProbe {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRReasonStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub strategy: String,
    pub target: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRValidateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
    pub rule: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRRefineStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
    pub strategy: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRWeaveStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub sources: Vec<String>,
    pub target: String,
    pub format_type: String,
    pub priority: Vec<String>,
    pub style: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRUseToolStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub tool_name: String,
    pub argument: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRRememberStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub expression: String,
    pub memory_target: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRRecallStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub query: String,
    pub memory_source: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRConditional {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub condition: String,
    pub comparison_op: String,
    pub comparison_value: String,
    pub then_body: Vec<IRFlowNode>,
    pub else_body: Vec<IRFlowNode>,
    pub conditions: Vec<(String, String, String)>,
    pub conjunctor: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRForIn {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub variable: String,
    pub iterable: String,
    pub body: Vec<IRFlowNode>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRLetBinding {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRReturnStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub value_expr: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRParallelBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRHibernateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub event_name: String,
    pub timeout: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDeliberateBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRConsensusBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRForgeBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRFocusStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub expression: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRAssociateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub left: String,
    pub right: String,
    pub using_field: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRAggregateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
    pub group_by: Vec<String>,
    pub alias: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRExploreStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub target: String,
    pub limit: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRIngestStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub source: String,
    pub target: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRShieldApplyStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub shield_name: String,
    pub target: String,
    pub output_type: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRStreamBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRNavigateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub pix_ref: String,
    pub corpus_ref: String,
    pub query: String,
    pub trail_enabled: bool,
    pub output_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDrillStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub pix_ref: String,
    pub subtree_path: String,
    pub query: String,
    pub output_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRTrailStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub navigate_ref: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRCorroborateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub navigate_ref: String,
    pub output_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IROtsApplyStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub ots_name: String,
    pub target: String,
    pub output_type: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRMandateApplyStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub mandate_name: String,
    pub target: String,
    pub output_type: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRComputeApplyStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub compute_name: String,
    pub arguments: Vec<String>,
    pub output_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRListenStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub channel: String,
    pub event_alias: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDaemonStepNode {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub daemon_ref: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRPersistStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRRetrieveStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
    pub where_expr: String,
    pub alias: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRMutateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
    pub where_expr: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRPurgeStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
    pub where_expr: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRTransactBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

// ── Tier 2 IR nodes ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct IRAgent {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String,
    pub on_stuck: String,
    pub shield_ref: String,
    pub max_iterations: Option<i64>,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRShield {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub scan: Vec<String>,
    pub strategy: String,
    pub on_breach: String,
    pub severity: String,
    pub quarantine: String,
    /// §8.2.h.3 — Python emits concrete 0, not null. AST keeps `Option<i64>`
    /// so the parser can distinguish "not set"; IR lowering collapses.
    pub max_retries: i64,
    pub confidence_threshold: f64,
    pub allow_tools: Vec<String>,
    pub deny_tools: Vec<String>,
    pub sandbox: bool,
    pub redact: Vec<String>,
    pub log: String,
    pub deflect_message: String,
    // `taint` exists on `ShieldDefinition` (AST) but Python's reference
    // IRShield doesn't emit it. Hidden from JSON output for §8.2.h parity.
    #[serde(skip)]
    pub taint: String,
    /// §ESK Fase 6.1 — covered regulatory classes for this shield.
    pub compliance: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRPix {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub source: String,
    pub depth: Option<i64>,
    pub branching: Option<i64>,
    pub model: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRPsyche {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub dimensions: Vec<String>,
    pub manifold_noise: Option<f64>,
    pub manifold_momentum: Option<f64>,
    pub safety_constraints: Vec<String>,
    pub quantum_enabled: Option<bool>,
    pub inference_mode: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRCorpus {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub documents: Vec<String>,
    pub mcp_server: String,
    pub mcp_resource_uri: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDataspace {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IROts {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub teleology: String,
    pub homotopy_search: String,
    pub loss_function: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRMandate {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub constraint: String,
    pub kp: Option<f64>,
    pub ki: Option<f64>,
    pub kd: Option<f64>,
    pub tolerance: Option<f64>,
    pub max_steps: Option<i64>,
    pub on_violation: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRCompute {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub shield_ref: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRDaemon {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String,
    pub on_stuck: String,
    pub shield_ref: String,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRAxonStore {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub backend: String,
    pub connection: String,
    pub confidence_floor: Option<f64>,
    pub isolation: String,
    pub on_breach: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRAxonEndpoint {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub method: String,
    pub path: String,
    pub body_type: String,
    pub execute_flow: String,
    pub output_type: String,
    pub shield_ref: String,
    /// §8.2.h.3 — Python emits concrete `0`; AST stays `Option<i64>`.
    pub retries: i64,
    pub timeout: String,
    /// §ESK Fase 6.1 — κ regulatory class on the boundary.
    pub compliance: Vec<String>,
}
