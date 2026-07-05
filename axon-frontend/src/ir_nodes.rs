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
    /// §Fase 71.a — temporal execution-window guards.
    pub windows: Vec<IRWindow>,
    pub daemons: Vec<IRDaemon>,
    pub ots_specs: Vec<IROts>,
    pub pix_specs: Vec<IRPix>,
    /// §Fase 62.0 — audit-chain (`ledger`) declarations. Distinct from
    /// `pix_specs` (the retrieval navigator); a ledger binds a hash-linked
    /// recorder to an audited surface.
    pub ledger_specs: Vec<IRLedger>,
    pub corpus_specs: Vec<IRCorpus>,
    pub psyche_specs: Vec<IRPsyche>,
    pub mandate_specs: Vec<IRMandate>,
    pub lambda_data_specs: Vec<IRLambdaData>,
    pub compute_specs: Vec<IRCompute>,
    pub axonstore_specs: Vec<IRAxonStore>,
    pub endpoints: Vec<IRAxonEndpoint>,
    /// §Fase 53 — closed-catalog extension declarations (compiled).
    /// `#[serde(skip)]` so the field is NOT emitted into the IR JSON —
    /// this keeps the static IR-JSON drift-gate fixtures green without
    /// regenerating them (same established pattern as `dataspace_specs`).
    /// The in-memory field feeds the §53.c type-checker + §53.d PCC (both
    /// read `&IRProgram`); soundness invariant #1 holds via SOURCE
    /// re-derivation — both the prover and the verifier read the
    /// source-derived IR, which carries the extensions. §53.x hardening
    /// (optional): un-skip + regenerate fixtures + bind extensions into
    /// the PCC `artifact_digest` (today the digest omits them; the
    /// witness still binds them by re-derivation). Deterministically
    /// sorted by `name` at the end of IR generation (§53.b founder
    /// refinement B) so multi-file declaration order can never perturb
    /// the proof-bundle hash.
    #[serde(skip)]
    pub extensions: Vec<IRExtension>,
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
    /// §λ-L-E Fase 13 — Mobile typed channels (compiled).
    pub channels: Vec<IRChannel>,
    /// §Fase 41.b — typed WebSocket transports (compiled). Each carries its
    /// referenced `session` protocol + the credit-window backpressure so
    /// axon-rs can realise the typed endpoint over a `tokio` WebSocket.
    pub sockets: Vec<IRSocket>,
    /// §Fase 51.c.2 — Pauli-sum observable declarations (compiled). Each carries
    /// its real-coefficient × Pauli-string terms so axon-rs can build the
    /// Hermitian measurement operator `M = Σ cₖ Pₖ` a `quant` block measures
    /// against. `#[serde(skip)]` (like `extensions` / `dataspace_specs`) so the
    /// static IR-JSON drift fixtures stay green; the in-memory field feeds the
    /// §51.c.2 checker + the §51.d/e runtime. The checker resolves
    /// `quant(observable: …)` against the AST symbol table, not this field.
    #[serde(skip)]
    pub observables: Vec<IRObservable>,
    /// §Fase 69.a — Advantage-Witness declarations. `skip_serializing_if = empty`
    /// keeps a witness-less program's IR JSON byte-identical (zero IR-SHA drift,
    /// the §52/§67 pattern); when present it rides the IR to the enterprise
    /// deploy/runtime evaluator (§69.b+).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub witnesses: Vec<IRWitness>,
    /// §Fase 80.b — outbound vendor connections (compiled). Each carries its
    /// axon-facing session binding (`protocol`/`role`), the per-tenant config
    /// keys (`resolve`/`secret`), the auth handshake, the total wire↔session
    /// projection (`map`) and the reconnect/overflow policies, so axon-rs can
    /// dial + transcode without vendor-specific code. `skip_serializing_if =
    /// empty` keeps an upstream-less program's IR JSON byte-identical (zero
    /// IR-SHA drift — the standing §76.d discipline).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub upstreams: Vec<IRUpstream>,
    /// §Fase 83.a — named, referenced browser-origin policies. `skip_serializing_if
    /// = empty` keeps a cors-less program's IR JSON byte-identical (zero IR-SHA
    /// drift — the standing §76.d discipline).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cors_policies: Vec<IRCors>,
    /// §Fase 85.b — named, referenced result-memoization policies. Same
    /// `skip_serializing_if = empty` IR-SHA discipline as `cors_policies`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub caches: Vec<IRCache>,
    /// §Fase 23 — algebraic effect declarations (compiled).
    /// Each declared effect persists into IR so axon-rs can build the
    /// per-effect operation table at startup. The CPS state graph for
    /// perform/handle sites lives inline within IRFlow.steps (each
    /// IRPerform / IRHandlerFrame carries its assigned state_id /
    /// frame_id).
    ///
    /// This Rust port mirrors the Python-side
    /// `IRProgram.effects: tuple[IREffectDeclaration, ...]` field so
    /// the byte-identical structural-parity gate stays green. The Rust
    /// frontend (axon-frontend) does not yet emit Fase 23 IR itself —
    /// the field exists to preserve serialization shape; the actual
    /// algebraic-effects compiler lives on the Python side, and the
    /// Rust runtime (axon-rs/src/effects/) consumes the JSON IR
    /// emitted by Python.
    pub effects: Vec<IREffectDeclaration>,
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
            windows: Vec::new(),
            daemons: Vec::new(),
            ots_specs: Vec::new(),
            pix_specs: Vec::new(),
            ledger_specs: Vec::new(),
            corpus_specs: Vec::new(),
            psyche_specs: Vec::new(),
            mandate_specs: Vec::new(),
            lambda_data_specs: Vec::new(),
            compute_specs: Vec::new(),
            axonstore_specs: Vec::new(),
            endpoints: Vec::new(),
            extensions: Vec::new(),
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
            channels: Vec::new(),
            sockets: Vec::new(),
            observables: Vec::new(),
            witnesses: Vec::new(),
            upstreams: Vec::new(),
            cors_policies: Vec::new(),
            caches: Vec::new(),
            effects: Vec::new(),
        }
    }
}

/// §Fase 51.d.2 — IR for the `yield <expr>` measurement point.
#[derive(Debug, Clone, Serialize)]
pub struct IRYield {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub value_expr: String,
    pub value_kind: String,
}

/// §Fase 51.c.2 — one term `cₖ · Pₖ` of a Pauli-sum observable (compiled).
#[derive(Debug, Clone, Serialize)]
pub struct IRPauliTerm {
    pub coefficient: f64,
    pub pauli: String,
}

/// §Fase 51.c.2 — IR for a Pauli-sum observable `M = Σ cₖ Pₖ`.
#[derive(Debug, Clone, Serialize)]
pub struct IRObservable {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub qubits: Option<i64>,
    pub terms: Vec<IRPauliTerm>,
}

/// §Fase 69.a — IR for an Advantage Witness. The deploy/runtime evaluator reads
/// `metric` + `threshold` + `baseline`, computes the metric over `data`, and
/// emits the verdict; a `holds == false` verdict is the honest fail-closed
/// signal (`axon-W007`/`W008`). `claim`/`data` are references resolved per domain.
#[derive(Debug, Clone, Serialize)]
pub struct IRWitness {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub claim: String,
    pub baseline: String,
    pub metric: String,
    pub threshold: f64,
    pub data: String,
}

// ── §Fase 23 — Algebraic effect declarations ─────────────────────────────────
//
// Mirror of Python's `IREffectDeclaration` and `IREffectOperation`
// dataclasses. The Rust frontend (axon-frontend) does not yet emit
// Fase 23 IR itself — these structs exist so the byte-identical
// structural-parity gate stays green when Python emits an empty
// `effects: []` field. The actual algebraic-effects compiler lives on
// the Python side; the Rust runtime (axon-rs/src/effects/) consumes
// the JSON IR via its own deserialize structs.

#[derive(Debug, Serialize, Default)]
pub struct IREffectDeclaration {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub operations: Vec<IREffectOperation>,
}

impl IREffectDeclaration {
    pub fn new() -> Self {
        Self {
            node_type: "effect_declaration",
            source_line: 0,
            source_column: 0,
            name: String::new(),
            operations: Vec::new(),
        }
    }
}

#[derive(Debug, Serialize, Default)]
pub struct IREffectOperation {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub type_parameters: Vec<String>,
    pub parameter_names: Vec<String>,
    pub parameter_types: Vec<String>,
    pub return_type: String,
}

impl IREffectOperation {
    pub fn new() -> Self {
        Self {
            node_type: "effect_operation",
            source_line: 0,
            source_column: 0,
            name: String::new(),
            type_parameters: Vec::new(),
            parameter_names: Vec::new(),
            parameter_types: Vec::new(),
            return_type: String::new(),
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

/// One operation in a compiled session protocol
/// (send / receive / loop / end / select / branch — §Fase 41.b adds the choices).
#[derive(Debug, Clone, Serialize)]
pub struct IRSessionStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub op: String,
    pub message_type: String,
    /// §Fase 41.b — labelled branches (only for `op == "select" | "branch"`;
    /// §Fase 79.b reuses them for `op == "interrupt"`: `body` + `handler` arms).
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub branches: Vec<IRSessionBranch>,
    /// §Fase 79.b — `op == "interrupt"` only: the handler's signal binder
    /// (`... as <sig> ...`). Skip-if-empty ⇒ zero IR-SHA drift for every
    /// non-interrupt step (the §76.d/§77.a additive-only discipline).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub binder: String,
    /// §Fase 79.b — `op == "interrupt"` only: the block declares a `resumable`
    /// handler. Skip-if-false ⇒ byte-identical IR for every other op.
    #[serde(skip_serializing_if = "std::ops::Not::not", default)]
    pub resumable: bool,
}

/// §Fase 41.b — one labelled arm of a compiled `select`/`branch` choice.
#[derive(Debug, Clone, Serialize)]
pub struct IRSessionBranch {
    pub node_type: &'static str,
    pub label: String,
    pub steps: Vec<IRSessionStep>,
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

/// §Fase 58.c — one typed parameter of a tool's input schema (the IR mirror of
/// the AST `Parameter`). `type_name` is the flattened BASE type string
/// (`String`, `List<String>`); optionality (`T?`) is carried in `optional`, so
/// `required` is derivable with no parallel bool (§58 D1, single source of
/// truth). Lossless round-trip is gated in §58.i.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct IRToolParam {
    pub name: String,
    pub type_name: String,
    pub optional: bool,
}

/// §Fase 58.c — one bound keyword argument of a `use Tool(k = v, …)` call (the
/// IR mirror of `UseArgs::Named`). `value` is an expression string (the
/// frontend has no structured `Expr`). The runtime (§58.e) assembles these into
/// the structured JSON request body.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct IRNamedArg {
    pub name: String,
    pub value: String,
    /// §Fase 60 — `"literal"` or `"reference"` (classified by `parse_let_atom`).
    /// A `"reference"` value (a bare identifier or `Step.output`) is resolved at
    /// runtime against the bindings (flow-param / `let` / step output), like a
    /// `let` reference — instead of being passed as the literal name (the pre-60
    /// bug). `"literal"` values keep `${…}` interpolation + typed coercion.
    pub value_kind: String,
}

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
    /// §Fase 58.c — the tool's typed INPUT SCHEMA (D1). Distinct from the §32
    /// `input_schema`/`output_schema` validation hints (those say HOW to
    /// validate raw output: JSON/number/…); these are the caller↔tool TYPE
    /// contract the type-checker enforces (§58.d) and the runtime binds
    /// structured args against (§58.e). Empty for a schema-less tool (D5).
    pub parameters: Vec<IRToolParam>,
    /// §Fase 58.c — the tool's declared OUTPUT type (D8), so `${Step.output}`
    /// is typed. `None` when undeclared. Single source of truth (lives here,
    /// not denormalised onto each call site).
    pub output_type: Option<String>,
    pub effect_row: Vec<String>,
    /// §Fase 84.b — Remote Hands. All three fields are `skip_serializing_if`
    /// so a program using none of them serialises **byte-identically** to the
    /// pre-§84 IR (the §76.d IR-SHA / additive-only gate — no drift for the
    /// entire existing corpus).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub risk: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub argv: Vec<String>,
    /// §Fase 85.b — the cache-policy reference (a declared `cache` name, or the
    /// `none` opt-out sentinel). Empty ⇒ module-default-governed. Elided when
    /// empty (IR-SHA stable for cache-less programs).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub cache: String,
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

#[derive(Debug, Clone, Serialize)]
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
    /// §Fase 68.b — the step's model-capability requirement (context window in
    /// tokens). `skip_serializing_if = Option::is_none` keeps every pre-§68 step's
    /// IR JSON byte-identical (no IR-SHA drift, D68.4); a legacy IR deserialises
    /// to `None` → the §68.c resolver picks the backend default exactly as today.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub requires_context: Option<u32>,
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

#[derive(Debug, Clone, Serialize)]
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
    pub ontology: String,             // T — ontological type
    pub certainty: f64,               // c ∈ [0,1]
    pub temporal_frame_start: String, // τ_start
    pub temporal_frame_end: String,   // τ_end
    pub provenance: String,           // ρ — EntityRef origin
    pub derivation: String,           // δ ∈ Δ
}

#[derive(Debug, Clone, Serialize)]
pub struct IRLambdaDataApply {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub lambda_data_name: String, // reference to declared ΛD
    pub target: String,           // expression being bound
    pub output_type: String,      // result type after binding
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
    /// Fase 19.e — exit the enclosing for-in body. Payload-free;
    /// the runner translates it into a sentinel that terminates the
    /// loop. Parser scope check guarantees this only appears inside
    /// a for-in body.
    Break(IRBreakStep),
    /// Fase 19.e — skip to the next iteration of the enclosing for-in
    /// body. Same shape as Break — payload-free, sentinel-driven at
    /// runtime.
    Continue(IRContinueStep),
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
    /// §λ-L-E Fase 13 — π-calc output prefix (Chan-Output / Chan-Mobility).
    Emit(IREmit),
    /// §λ-L-E Fase 13 — capability extrusion (Publish-Ext).
    Publish(IRPublish),
    /// §λ-L-E Fase 13 — dual of publish (typed handle import).
    Discover(IRDiscover),
    Persist(IRPersistStep),
    Retrieve(IRRetrieveStep),
    Mutate(IRMutateStep),
    Purge(IRPurgeStep),
    Transact(IRTransactBlock),
    /// §Fase 51.a — the `quant` cognitive block (Hilbert-space projection).
    Quant(IRQuant),
    /// §Fase 51.d.2 — the `yield` measurement point inside a `quant` block.
    Yield(IRYield),
    /// §Fase 52.c — `run <Flow>(args)` flow-step: invoke a declared flow from a
    /// body (a daemon listen handler). Reuses [`IRRun`] (the top-level run IR).
    Run(IRRun),
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
    /// §Fase 58.c — the bound keyword args of `use Tool(k = v, …)` (W1: the
    /// structured args survive to the IR, no longer collapsed to one opaque
    /// string). Empty for the legacy single-`on <arg>` form (`argument`
    /// carries that, D5).
    pub named_args: Vec<IRNamedArg>,
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

/// §Fase 70.a — the lowered form of a pure expression (`Expr`). Carried in the
/// IR for conditions the legacy `(condition, op, value)` triple cannot express.
/// Operators are canonical lowercase strings so the JSON is stable + readable;
/// the runtime evaluator (§70.f) matches on them. Externally-tagged by `kind`.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum IRExpr {
    /// A typed literal.
    Lit { lit: IRExprLit },
    /// A reference to a binding / dotted path.
    Ref { path: String },
    /// Unary op — `op ∈ {neg, not}`.
    Unary { op: String, operand: Box<IRExpr> },
    /// Binary op — `op ∈ {add,sub,mul,div,mod,eq,ne,lt,le,gt,ge,and,or}`.
    Binary {
        op: String,
        lhs: Box<IRExpr>,
        rhs: Box<IRExpr>,
    },
    /// §Fase 70.c — a closed-catalog builtin call. `args[0]` is the receiver.
    /// `builtin ∈ {length,count,is_empty,is_null,contains,starts_with,ends_with}`.
    Call {
        builtin: String,
        args: Vec<IRExpr>,
    },
    /// §Fase 70.d — field access on a non-reference base (the JSONB seam).
    Field {
        base: Box<IRExpr>,
        field: String,
    },
    /// §Fase 70.d — index access `base[index]`.
    Index {
        base: Box<IRExpr>,
        index: Box<IRExpr>,
    },
}

/// §Fase 70.a — a literal inside an [`IRExpr`].
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "ty", rename_all = "snake_case")]
pub enum IRExprLit {
    Int { value: i64 },
    Float { value: f64 },
    Bool { value: bool },
    Str { value: String },
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
    /// §Fase 70.a — the lowered expression form, present only for conditions
    /// the legacy triple cannot express. `skip_serializing_if` keeps the IR
    /// JSON (and its SHA) byte-identical for every pre-§70 program.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cond: Option<IRExpr>,
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
    /// Fase 17.a — preserves parser tokenization intent.
    /// One of "literal" | "reference" | "expression".
    pub value_kind: String,
    /// §Fase 70.f — the lowered expression form of the value, present only for
    /// `value_kind == "expression"`. The runtime evaluates it instead of
    /// treating the value string as an opaque literal. `skip_serializing_if`
    /// keeps the IR byte-identical for every literal / reference let.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value_ast: Option<IRExpr>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRReturnStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub value_expr: String,
}

/// Fase 19.e — `break` keyword IR node. Payload-free (the runner
/// raises a sentinel; no value is carried). Mirrors Python's
/// ``IRBreak`` (axon/compiler/ir_nodes.py).
#[derive(Debug, Clone, Serialize)]
pub struct IRBreakStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

/// Fase 19.e — `continue` keyword IR node. Same shape as
/// ``IRBreakStep``; the runner uses a different sentinel type to
/// distinguish loop-exit (break) from iteration-skip (continue).
#[derive(Debug, Clone, Serialize)]
pub struct IRContinueStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRParallelBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    /// §Fase 65 — the concurrent branches lowered from the AST `par { … }`.
    /// Each branch is a flow-IR body run concurrently by the dispatcher's
    /// `run_branches_concurrently`. `skip_serializing_if = "Vec::is_empty"` so a
    /// payload-free / empty `par` serializes byte-identically to the pre-§65
    /// shape (D5 back-compat); a `par` with real branches carries them.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub branches: Vec<Vec<IRFlowNode>>,
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

/// §Fase 86 — the compiled Directed Creative Synthesis block. This IS the
/// "structured IR metadata that the runtime executes as an orchestrated
/// pipeline" the README always claimed — pre-§86 it carried only a source
/// location. New fields are `skip_serializing_if`-elided so a program with no
/// `forge` stays IR-SHA stable.
#[derive(Debug, Clone, Serialize, Default)]
pub struct IRForgeBlock {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub name: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub seed: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub output_type: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub mode: String,
    #[serde(default, skip_serializing_if = "is_default_novelty")]
    pub novelty: f64,
    #[serde(default, skip_serializing_if = "is_one_i64")]
    pub depth: i64,
    #[serde(default, skip_serializing_if = "is_one_i64")]
    pub branches: i64,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub constraints_ref: String,
}

fn is_default_novelty(v: &f64) -> bool {
    (*v - 0.5).abs() < f64::EPSILON
}
fn is_one_i64(v: &i64) -> bool {
    *v == 1
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
    /// §Fase 63.B — MDN corpus-graph navigation: the seed document (`from:`).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub seed: String,
    /// §Fase 63.B — MDN navigation budget (`budget:` = max documents).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub budget: Option<i64>,
    /// §Fase 66 (Q2) — column-scope filter for a `corpus from axonstore`. A raw
    /// filter expr threaded to `read_all_store_rows` → `stream_retrieve` for
    /// BOTH the documents and edges stores, so the sourced MDN graph is scoped
    /// to a sub-tenant column (`where: "tenant_id == '${tenant_id}'"`). The
    /// §37.d filter compiler resolves `${name}` → `$N` bind params (injection-
    /// safe). Empty = no column filter (axon-tenant RLS scope only).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub where_expr: String,
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
    /// §λ-L-E Fase 13 D4 — true ⇒ `channel` is a declared
    /// `IRChannel` ref; false ⇒ legacy string topic.
    pub channel_is_ref: bool,
    pub event_alias: String,
    /// §Fase 52.a — the handler body's lowered flow-steps, executed per event /
    /// scheduled tick by the §52.c runtime. `skip_serializing_if` keeps a
    /// bodyless `listen`'s JSON byte-identical to the pre-§52.a shape (D8).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub body: Vec<IRFlowNode>,
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
    /// §Fase 35.o — declared `{ col: value }` field block (value
    /// expressions kept raw; interpolated at runtime). Empty ⇒ the
    /// runtime writes the flow's user bindings (v1.30.0 fallback).
    pub fields: Vec<(String, String)>,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRRetrieveStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
    pub where_expr: String,
    pub alias: String,
    /// §Fase 67.b — `order_by:` clause (raw `"col [asc|desc], …"`).
    /// `skip_serializing_if` empty so a store that doesn't order never
    /// perturbs the serialized IR bytes (the §52 brief-#33 /
    /// [[feedback-boot-hydrate-self-heal]] no-drift discipline).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub order_by: String,
    /// §Fase 67.b — `limit:` clause (raw `"100"` or `"${max}"`).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub limit_expr: String,
    /// §Fase 76.d — `aggregate:` clause (raw, closed catalog: `count` /
    /// `sum(col)` / `avg(col)` / `min(col)` / `max(col)`).
    /// `skip_serializing_if` empty so a non-aggregating retrieve never
    /// perturbs the serialized IR bytes (the same §67.b no-drift
    /// discipline — zero IR-SHA drift for existing programs).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub aggregate: String,
    /// §Fase 76.d — `group_by:` clause (raw `"col, col2"`).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub group_by: String,
    /// §Fase 85.b — `cache:` reference (a declared `cache` name). Empty ⇒
    /// uncached. Elided when empty (IR-SHA stable for cache-less retrieves).
    #[serde(skip_serializing_if = "String::is_empty", default)]
    pub cache: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IRMutateStep {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub store_name: String,
    pub where_expr: String,
    /// §Fase 35.p — declared `{ col: value }` SET assignments (value
    /// expressions kept raw; interpolated at runtime). Empty ⇒ the
    /// runtime writes the flow's user bindings (v1.31.0 fallback).
    pub fields: Vec<(String, String)>,
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

/// §Fase 51.a — IR for the `quant` cognitive block (Hilbert-space projection).
/// Mirrors `ast::QuantBlock`. Optional attributes serialize only when present
/// (`skip_serializing_if`) so a bare `quant {}` lowers to a minimal node and
/// the JSON stays diff-stable. The body lowers recursively, like `par` branches.
#[derive(Debug, Clone, Serialize)]
pub struct IRQuant {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    /// Encoding scheme surface spelling (`amplitude` | `angle`); `None` = default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub encoding: Option<String>,
    /// Referenced `Observable` (Pauli-sum) name; `None` if unspecified.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observable: Option<String>,
    /// Register width n; `None` = inferred.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub qubits: Option<i64>,
    /// Variational circuit depth L; `None` = backend default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub depth: Option<i64>,
    /// Projected-kernel bandwidth γ (D7); `None` = backend default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bandwidth: Option<f64>,
    /// §Fase 69.c — data re-uploading layers L (`None`/`1` = no re-uploading).
    /// `skip_serializing_if` keeps a non-re-uploading block's IR byte-identical.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reupload: Option<i64>,
    /// Algebraic-effect backend tag (`quant_sim` | `qpu_native`).
    pub effect: String,
    /// Nested flow-body IR (recursively lowered).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub body: Vec<IRFlowNode>,
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

/// §Fase 71.a — the lowered temporal execution-window guard. The runtime
/// (§71.b) evaluates `is_in_window(now, tz, allow)`; the daemon binding +
/// coalesced defer ledger are §71.c/d.
#[derive(Debug, Clone, Serialize)]
pub struct IRWindow {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub timezone: String,
    pub allow: Vec<IRWindowSpan>,
    /// §Fase 71.e — excluded dates (holidays): ISO `YYYY-MM-DD` literals. A tick
    /// whose local date is in this set is OUTSIDE regardless of the hour spans.
    /// `skip_serializing_if` keeps a holiday-less window's JSON byte-identical.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub exclude: Vec<String>,
    pub on_outside: String,
}

/// §Fase 71.a — one allowed day/hour span.
#[derive(Debug, Clone, Serialize)]
pub struct IRWindowSpan {
    pub day_start: String,
    pub day_end: String,
    pub hour_start: i64,
    pub hour_end: i64,
}

/// §Fase 72.a — the `budget { … }` linear-effect rate limit lowered to IR. Each
/// quota gates a declared tool's dispatch on a renewable token bucket (the §72.b
/// `RateLease`); `on_exhausted` is the exhaustion policy.
#[derive(Debug, Clone, Serialize)]
pub struct IRBudget {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub quotas: Vec<IRBudgetQuota>,
    /// `block` (fail-closed) | `defer` (reschedule via the §71 defer ledger) |
    /// `shed` (skip the call). An omitted policy lowers to `block` (the safe
    /// fail-closed default).
    pub on_exhausted: String,
}

/// §Fase 72.a — one quota: `<kind>: <limit> per <period> on Tool(<effect>)`.
#[derive(Debug, Clone, Serialize)]
pub struct IRBudgetQuota {
    /// `rate` (renewable bucket) | `max` (windowed hard cap, no intra-window refill).
    pub kind: String,
    /// Token allowance per period (> 0, validated by `axon-T831`).
    pub limit: i64,
    /// `second` | `minute` | `hour` | `day` (closed catalog, `axon-T832`).
    pub period: String,
    /// The declared tool this quota governs (`on Tool(X)`; resolved by `axon-T830`).
    pub effect: String,
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
    /// §Fase 77.a — egress signing algorithm (`hmac_sha256`; empty = the
    /// shield does not sign). Elided from JSON when empty so every pre-§77
    /// program's IR stays byte-identical (zero IR-SHA drift).
    #[serde(skip_serializing_if = "String::is_empty")]
    pub sign: String,
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

/// §Fase 62.0 — the audit-chain (`ledger`) IR node. Same shape as [`IRPix`]
/// but a DISTINCT node (`node_type: "ledger"`): a ledger binds a hash-linked
/// recorder to an audited surface (`source`), retaining `depth` rows under a
/// `branching`-factor Merkle tree, hashed with `model`. Kept separate from
/// `IRPix` so the navigator and the audit chain never alias on the wire.
#[derive(Debug, Clone, Serialize)]
pub struct IRLedger {
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
    /// §Fase 63.A — typed weighted edges. Non-empty ⇒ this corpus is an MDN
    /// graph `C = (D, R, τ, ω, σ)`; the runtime builds an `mdn::Corpus` from it.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub relations: Vec<IRCorpusRelation>,
    /// §Fase 63.C — `adaptive: true` enables the memory endofunctor on this
    /// corpus's navigations.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub adaptive: bool,
    pub mcp_server: String,
    pub mcp_resource_uri: String,
    /// §Fase 64.A — when present, this is a DYNAMIC store-sourced MDN graph: the
    /// documents and typed edges are rows in two declared `axonstore`s and the
    /// runtime builds the `mdn::Corpus` from the live rows at navigate-time
    /// (per-tenant, growing). Absent ⇒ the static §63 corpus (byte-identical IR).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub store_source: Option<IRCorpusStoreSource>,
}

/// §Fase 63.A — a lowered MDN corpus-graph edge `(from, to, τ, ω)`.
#[derive(Debug, Clone, Serialize)]
pub struct IRCorpusRelation {
    pub etype: String,
    pub from: String,
    pub to: String,
    pub weight: f64,
}

/// §Fase 64.A — the lowered store-mapping of a dynamic, `axonstore`-sourced MDN
/// corpus graph. `doc_store(doc_id, doc_title)` maps rows → nodes;
/// `edge_store(edge_from, edge_to, edge_type, edge_weight)` maps rows → typed
/// weighted edges. The runtime (§64.B) reads these stores tenant-scoped at
/// navigate-time to build the `mdn::Corpus`.
#[derive(Debug, Clone, Serialize)]
pub struct IRCorpusStoreSource {
    pub doc_store: String,
    pub doc_id: String,
    pub doc_title: String,
    pub edge_store: String,
    pub edge_from: String,
    pub edge_to: String,
    pub edge_type: String,
    pub edge_weight: String,
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
    /// §Fase 71.c — the `window:` temporal binding (a `window` primitive name).
    /// Empty ⇒ no temporal guard; `skip_serializing_if` keeps a windowless
    /// daemon's JSON byte-identical (D8 zero-drift).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub window_ref: String,
    /// §Fase 72.a — the `budget { … }` linear-effect rate limit. `None` ⇒ no
    /// budget; `skip_serializing_if` keeps a budgetless daemon's JSON
    /// byte-identical (D8 zero-drift).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub budget: Option<IRBudget>,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
    /// §Fase 52.a — the daemon's `listen` listeners (channel + alias + handler
    /// body). Pre-§52.a these were DROPPED at lowering (the IR daemon carried no
    /// listeners at all); now they survive so the §52.c runtime can mount + run
    /// them and the §52.d enterprise supervisor can extract them per-tenant.
    /// `skip_serializing_if` keeps a listenerless daemon's JSON unchanged (D8).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub listeners: Vec<IRListenStep>,
    /// §Fase 52.d — the capability scope the daemon's runs are confined to
    /// (`requires: [cap, …]`). The enterprise supervisor mints a per-run
    /// principal scoped to exactly these. `skip_serializing_if` keeps a
    /// requires-less daemon's JSON byte-identical (D8).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub requires_capabilities: Vec<String>,
}

// ── §Fase 53 — Closed-catalog extension mechanism ────────────────────────────

/// §Fase 53 — one compiled member of an `extension`. For `effects`
/// the `name` is a provenance base; `default_confidence` is a CEILING
/// (§53.d tainted-overriding). Metadata is elided from JSON when absent
/// so the serialised shape stays minimal once the `extensions` field is
/// un-skipped alongside the Python IR mirror.
#[derive(Debug, Clone, Serialize)]
pub struct IRExtensionMember {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub semantics: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_confidence: Option<f64>,
}

/// §Fase 53 — a compiled `extension` declaration. Rides in the IR (and,
/// once un-skipped, the proof bundle) so an independent PCC verifier
/// re-derives `is_known_base` against the artifact's own extensions
/// (soundness invariant #1). `category` ∈ {`effects`, `scan`} — the
/// type-checker (§53.c) enforces the closed category + no-shadowing +
/// provenance-class invariants before this IR is trusted.
#[derive(Debug, Clone, Serialize)]
pub struct IRExtension {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub category: String,
    pub members: Vec<IRExtensionMember>,
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
    /// §Fase 35.j (D11) — Pillar IV: the capability slug required to
    /// access this store (empty = no gate).
    pub capability: String,
    /// §Fase 38.b (D1) — the OPTIONAL column-schema declaration. Three
    /// closed forms (inline / manifest-ref / env-var). `None` means the
    /// 37.x runtime+deploy path applies verbatim (D5 absolute). The
    /// §38.d / §38.e type-checker proves every store reference against
    /// this when present.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub column_schema: Option<IRStoreColumnSchema>,
}

/// §Fase 38.b (D1) — IR mirror of [`crate::store_schema::StoreColumnSchema`].
/// Serializes as a tagged union: `{"form": "inline" | "manifest_ref" |
/// "env_var", …}`.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "form", rename_all = "snake_case")]
pub enum IRStoreColumnSchema {
    Inline { columns: Vec<IRStoreColumn> },
    ManifestRef { qualified_name: String },
    EnvVar { var_name: String },
}

/// §Fase 38.b (D1) — IR mirror of [`crate::store_schema::StoreColumn`].
/// The serialized `col_type` is the canonical PascalCase name (e.g.
/// `"Uuid"`, `"Int"`, `"Timestamptz"`).
#[derive(Debug, Clone, Serialize)]
pub struct IRStoreColumn {
    pub name: String,
    pub col_type: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub primary_key: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub auto_increment: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub not_null: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    pub unique: bool,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub default_value: String,
    /// §Fase 38.x.c (D2, D5) — `true` iff the column is declared with
    /// `GENERATED ALWAYS AS IDENTITY` or `GENERATED BY DEFAULT AS
    /// IDENTITY`. Distinct from `auto_increment` (legacy SERIAL via
    /// `nextval(...)` default). `skip_serializing_if` keeps IR JSON
    /// byte-identical to v1.38.2 for any column where `identity = false`.
    #[serde(default, skip_serializing_if = "is_false")]
    pub identity: bool,
    /// §Fase 73.f (D1) — `true` iff the column carries the `index`
    /// declaration. Surfaced into the IR so the deployment layer (the
    /// enterprise deploy gate) SEES the index as a declared capability and
    /// can materialize it (a GIN path index for a `Json`/`Jsonb` column, a
    /// b-tree otherwise) — never a silent out-of-band DBA action.
    /// `skip_serializing_if` keeps IR JSON byte-identical for any column
    /// where `indexed = false`.
    #[serde(default, skip_serializing_if = "is_false")]
    pub indexed: bool,
    /// §Fase 73.g (D1) — the OPTIONAL `Json<T>` shape-lens struct name on a
    /// `Json`/`Jsonb` column (`payload: Json<UserEvent>` → `Some("UserEvent")`).
    /// Surfaced into the IR so the PCC `JsonShapeSoundness` proof can
    /// RE-DERIVE, from the artifact alone, that every lens shape resolves
    /// to a declared struct `type` — the §73.a/§73.e lens well-formedness
    /// made an independently-verifiable proof object. `skip_serializing_if`
    /// keeps IR JSON byte-identical for any column with no shape lens.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub json_shape: Option<String>,
}

#[inline]
fn is_false(b: &bool) -> bool {
    !*b
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
    /// §Fase 37.y (D1) — Path parameter names extracted from the
    /// `path:` string. Mirrors `AxonEndpointDefinition.path_params`.
    /// **`skip_serializing_if = Vec::is_empty`** so a pre-v1.38.5 IR
    /// JSON snapshot (without the field) is byte-identical to a
    /// v1.38.5 IR JSON for the same endpoint — D5 backwards-compat
    /// absolute. The runtime + adopter tools that consume the IR
    /// JSON parse `path_params` as an absent key → empty Vec via
    /// serde's `default` semantics.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub path_params: Vec<String>,
    /// §Fase 37.y (D2) — Query parameters from the inline
    /// `query: { … }` block. Mirrors `AxonEndpointDefinition.query_params`
    /// using `IRTypeField` (shared with body type fields → uniform
    /// downstream tooling). **`skip_serializing_if = Vec::is_empty`**
    /// — same D5 IR-JSON byte-identity guarantee as `path_params`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub query_params: Vec<IRTypeField>,
    /// §Fase 51.x — capability scopes the request bearer must hold
    /// (the `requires: [scope.dotted]` declaration, §Fase 32.g). Mirror
    /// of `AxonEndpointDefinition.requires_capabilities`, lowered into
    /// the IR so the PCC CapabilityContainment property can prove that
    /// the stores this endpoint's flow reaches are all covered by the
    /// declared requires. **`skip_serializing_if = Vec::is_empty`** so a
    /// pre-§51.x IR-JSON snapshot (no `requires:`) stays byte-identical
    /// (D5 backwards-compat — empty key parses back to empty Vec).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub requires_capabilities: Vec<String>,
    /// §Fase 83.a — the `cors: <Name>` reference, or `""` when absent
    /// (D83.5: no CORS headers, ever). NEW field on an EXISTING struct —
    /// `skip_serializing_if` (not `shield_ref`'s bare/always-emitted
    /// historical shape) so a cors-less endpoint's IR stays byte-identical
    /// to pre-§83 (zero IR-SHA drift — the standing §76.d discipline).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub cors_ref: String,
}

// ── §λ-L-E Fase 13 — Mobile Typed Channels IR ───────────────────────────────

/// Compiled `channel Name { … }` declaration.
///
/// Direct port of `axon.compiler.ir_nodes.IRChannel`.  Lives in
/// `IRProgram.channels`; emit/publish/discover reductions embed in
/// their containing flow/listener (paper §3 + §4 — π-calc prefix
/// discipline preserved structurally, not lifted to top-level ops).
#[derive(Debug, Clone, Serialize)]
pub struct IRChannel {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub message: String, // surface spelling — Order | Channel<Order> | …
    pub qos: String,
    pub lifetime: String,
    pub persistence: String,
    pub shield_ref: String,
    /// §Fase 77.b — non-empty ⇒ some `publish <this> within <Shield>` site
    /// referenced a SIGNING shield: the channel is an EGRESS channel and
    /// its durable events are signed-deliverable to registered external
    /// subscribers under this algorithm (first publish site wins;
    /// deterministic — the catalog has one algorithm in v1). Elided from
    /// JSON when empty (zero IR-SHA drift for pre-§77 programs).
    #[serde(skip_serializing_if = "String::is_empty")]
    pub egress_sign: String,
}

/// §Fase 41.b — compiled typed WebSocket transport. `protocol` names the
/// `session` it carries; `backpressure_credit` is the typed-resource window
/// (`null` if unspecified). axon-rs realises the endpoint over a `tokio` WS,
/// crediting/decrementing the window per §4.2 of the paper.
#[derive(Debug, Clone, Serialize)]
pub struct IRSocket {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub protocol: String,
    pub backpressure_credit: Option<i64>,
    pub reconnect: bool,
    pub legal_basis: Option<String>,
}

/// §Fase 80.b — compiled outbound vendor connection (the client dual of
/// [`IRSocket`]). `protocol`/`role` bind the axon-facing session interface;
/// `resolve`/`secret` are per-tenant config keys (never literals — T850);
/// `map` is the compile-time-total wire↔session projection (T849). Optional
/// fields elide when absent so the IR shape is purely additive.
#[derive(Debug, Clone, Serialize)]
pub struct IRUpstream {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub transport: String,
    pub protocol: String,
    pub role: String,
    pub resolve: String,
    pub secret: String,
    pub auth_kind: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auth_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auth_prefix: Option<String>,
    pub map: Vec<IRUpstreamMapRule>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reconnect: Option<IRUpstreamReconnect>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub overflow: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backpressure_credit: Option<i64>,
    /// §80.f — the `Preset@vN` reference this declaration was expanded from
    /// (provenance for the compliance reviewer); absent for hand-written ones.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preset: Option<String>,
}

/// §Fase 80.b — one compiled `map:` projection rule.
#[derive(Debug, Clone, Serialize)]
pub struct IRUpstreamMapRule {
    pub node_type: &'static str,
    pub direction: String,
    pub message: String,
    pub framing: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tag: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub when_field: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub when_value: Option<String>,
}

/// §Fase 80.b — compiled reconnect policy (all three fields required by the
/// parser — a reconnection policy with a hole is not a policy).
#[derive(Debug, Clone, Serialize)]
pub struct IRUpstreamReconnect {
    pub backoff_ms: i64,
    pub max_attempts: i64,
    pub on_exhausted: String,
}

/// §Fase 83.a — a named, referenced browser-origin policy. Mirrors
/// `IRShield`'s field-for-field shape; consumed by `IRAxonEndpoint.cors_ref`.
/// Wildcard+credentials (T853), origin-glob shape (T854), and closed-method
/// (T855) violations are all rejected before this node is ever lowered — the
/// checker re-derives the same closed catalogs at deploy time (§83.c,
/// `CorsPolicyConsistency`), so an IR that reaches the runtime is already
/// proven consistent.
#[derive(Debug, Clone, Serialize)]
pub struct IRCors {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    pub allow_origins: Vec<String>,
    pub allow_methods: Vec<String>,
    pub allow_headers: Vec<String>,
    pub allow_credentials: bool,
    /// Duration literal (`"3600s"`) — same string-carries-the-unit
    /// convention as `axonendpoint.timeout`; the consumer (enterprise's
    /// dynamic CORS middleware) parses it into seconds at request time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_age: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub expose_headers: Vec<String>,
}

/// §Fase 85.b — compiled `cache` policy. The checker (§85.c) re-derives the
/// same laws at the deploy gate (`CacheSoundness`), so an IR that reaches the
/// runtime is already proven sound (one default max, non-pure ⇒ finite ttl,
/// references resolve). Every optional field is `skip_serializing_if` so a
/// bundle using `cache` only pays IR bytes for what it declares, and a bundle
/// with no `cache` never emits a `caches` key (IR-SHA stable, §76.d).
#[derive(Debug, Clone, Serialize)]
pub struct IRCache {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub name: String,
    /// `"redis"` | `"in_process"`; empty ⇒ runtime default (`in_process`).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub backend: String,
    /// Duration literal (`"10s"`) — same string-carries-the-unit convention as
    /// `cors.max_age`. `None` ⇒ cache-forever (sound only for a `pure` cache).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ttl: Option<String>,
    /// The parameter-name subset forming the key; empty ⇒ all bound params.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub key_params: Vec<String>,
    /// `true` ⇒ auto-covers every eligible tool (at most one per module).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub default_policy: bool,
    /// Effect classes this cache memoises; empty ⇒ `["pure"]`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub apply_to_effects: Vec<String>,
    /// Channel names whose `emit` flushes this cache's namespace.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub invalidate_on: Vec<String>,
}

/// Compiled emit step — `c⟨v⟩.P` (Chan-Output / Chan-Mobility).
///
/// `value_is_channel = true` ⇒ resolved at lowering time as a channel
/// handle (second-order mobility, paper §3.2); the runtime dispatches
/// on this flag without re-resolving symbols.
#[derive(Debug, Clone, Serialize)]
pub struct IREmit {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub channel_ref: String,
    pub value_ref: String,
    pub value_is_channel: bool,
}

/// Compiled publish step — capability extrusion (Publish-Ext, paper §4.3).
#[derive(Debug, Clone, Serialize)]
pub struct IRPublish {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub channel_ref: String,
    pub shield_ref: String,
    /// §Fase 77.b — the referenced shield's `sign:` algorithm, RESOLVED at
    /// lowering (order-independent pre-pass over every declared shield).
    /// Non-empty ⇒ this publish is an EGRESS declaration: the channel's
    /// events are signed-deliverable to registered external subscribers.
    /// Elided from JSON when empty (zero IR-SHA drift for pre-§77 programs).
    #[serde(skip_serializing_if = "String::is_empty")]
    pub sign: String,
}

/// Compiled discover step — dual of publish.
#[derive(Debug, Clone, Serialize)]
pub struct IRDiscover {
    pub node_type: &'static str,
    pub source_line: u32,
    pub source_column: u32,
    pub capability_ref: String,
    pub alias: String,
}
