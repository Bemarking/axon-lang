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
    /// Tier 3+ declarations parsed structurally (balanced braces, no detailed AST).
    Generic(GenericDeclaration),
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
#[derive(Debug)]
pub struct ListenStep { pub channel: String, pub event_alias: String, pub loc: Loc }
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
