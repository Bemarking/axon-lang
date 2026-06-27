//! AXON AST node definitions — direct port of axon/compiler/ast_nodes.py.
//!
//! Tier 1 constructs have fully typed structs.
//! Tier 2+ constructs use `GenericDeclaration` (structural fallback).

#![allow(dead_code)]

use crate::tokens::Trivia;

// ── Location helper ──────────────────────────────────────────────────────────

/// Source location shared by all AST nodes.
#[derive(Debug, Clone, Default)]
pub struct Loc {
    pub line: u32,
    pub column: u32,
}

// ── Trivia channel (Fase 14.a — Lossless lexing) ─────────────────────────────
//
// The Python AST attaches `leading_trivia` / `trailing_trivia` directly
// to each ASTNode (97+ subclasses inherit empty defaults). The Rust
// structs do not have inheritance, so adding two `Vec<Trivia>` fields
// to every node would require touching each of the 97 structs and
// every fixture test that constructs them — high mechanical churn for
// a use case (LSP / formatter / doc gen) that can be served just as
// well by indexing trivia by declaration position.
//
// `DeclarationTrivia` is a side-channel attached to `Program`. The
// parser populates it in lockstep with `declarations` so consumer code
// can do `program.declaration_trivia[i]` to get the leading/trailing
// trivia of `program.declarations[i]`. This preserves the AST shape
// (no breaking changes), keeps `IRProgram` JSON byte-identical with
// the Python reference (trivia is never serialised), and ships the
// adopter-reported feature end-to-end.
//
// If a future sub-phase wants per-node trivia inside the AST itself
// (mirror of the Python ASTNode shape), this side-channel is the seed:
// every `DeclarationTrivia` already carries the data; spreading it
// into the structs is a mechanical refactor at that point.

/// Comments attached to a single top-level declaration. Indexed
/// in parallel with `Program.declarations`.
#[derive(Debug, Clone, Default)]
pub struct DeclarationTrivia {
    /// Comment trivia that appeared before the declaration's first
    /// token (since the previous declaration or file start).
    pub leading: Vec<Trivia>,
    /// Comment trivia on the same line as the declaration's last
    /// effective token, before the next newline.
    pub trailing: Vec<Trivia>,
}

// ── Top-level ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct Program {
    pub declarations: Vec<Declaration>,
    /// Fase 14.a — comment trivia attached per declaration (parallel
    /// with `declarations`). Empty by default; populated by the parser
    /// when source carries comments. Defaults preserve every existing
    /// `Program { declarations, loc }` constructor — `..Default::default()`
    /// on a `Program` literal fills in the new field.
    pub declaration_trivia: Vec<DeclarationTrivia>,
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
    Ledger(LedgerDefinition),
    Psyche(PsycheDefinition),
    Corpus(CorpusDefinition),
    Dataspace(DataspaceDefinition),
    Ots(OtsDefinition),
    Mandate(MandateDefinition),
    Compute(ComputeDefinition),
    Daemon(DaemonDefinition),
    AxonStore(AxonStoreDefinition),
    AxonEndpoint(AxonEndpointDefinition),
    /// §Fase 53 — Closed-catalog extension mechanism. Declares
    /// adopter-specific PROVENANCE members for a closed catalog
    /// (`effects` bases or shield `scan` categories) so the
    /// type-checker + PCC treat them as first-class. Auditable +
    /// gateable; never extends the enforceable effect set (invariant
    /// #2 — provenance-class only).
    Extension(ExtensionDefinition),
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
    /// §Fase 41.b — typed WebSocket transport binding a `session` protocol
    /// (paper_websocket_cognitive_primitive.md).
    Socket(SocketDefinition),
    /// §Fase 51.c.2 — a Pauli-sum observable `M = Σ cₖ Pₖ` that a `quant`
    /// block measures against (paper §3.2; plan D5).
    Observable(ObservableDefinition),
    /// §Fase 69.a — an Advantage Witness: a machine-checkable proof obligation
    /// that a primitive's `claim` beats a cheaper `baseline` by a `metric` above
    /// a `threshold` on real `data` (doctrine `axon://logic/no_unwitnessed_advantage`).
    Witness(WitnessDefinition),
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
    pub kind: String, // postgres | redis | s3 | vpc | gpu | compute | file | custom
    pub endpoint: String, // connection URI
    pub capacity: Option<i64>, // pool size / instance count hint
    pub lifetime: String, // linear | affine | persistent (default: affine)
    pub certainty_floor: Option<f64>, // epistemic gate c ∈ [0.0, 1.0]
    pub shield_ref: String, // optional shield reference
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `fabric Name { provider, region, zones, ephemeral, shield }`
///
/// A tagged substrate — the topological container where resources are
/// provisioned. Maps to VPC / cluster / namespace.
#[derive(Debug, Default)]
pub struct FabricDefinition {
    pub name: String,
    pub provider: String, // aws | gcp | azure | kubernetes | bare_metal | custom
    pub region: String,   // provider-specific region id
    pub zones: Option<i64>, // number of availability zones
    pub ephemeral: Option<bool>, // true = destroy on program end
    pub shield_ref: String, // optional shield reference
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `manifest Name { resources, fabric, region, zones, compliance }`
///
/// A declarative specification of desired shape — not a "desired state" in
/// the Terraform sense, a *belief* about structure. Linear/affine resources
/// in `resources` must be disjoint (Separation Logic `*`).
#[derive(Debug, Default)]
pub struct ManifestDefinition {
    pub name: String,
    pub resources: Vec<String>, // references to ResourceDefinition names
    pub fabric_ref: String,     // reference to FabricDefinition name
    pub region: String,
    pub zones: Option<i64>,
    pub compliance: Vec<String>, // κ — regulatory class (Fase 6.1)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `observe Name from Manifest { sources, quorum, timeout, on_partition, certainty_floor }`
///
/// A quorum-gated observation of a manifest's real state. Each output
/// carries ΛD envelope E = ⟨c, τ, ρ, δ⟩; `τ` records observation lag.
/// `on_partition: fail` raises a CT-3 (Network Error) — partitions are ⊥ void.
#[derive(Debug, Default)]
pub struct ObserveDefinition {
    pub name: String,
    pub target: String, // name of ManifestDefinition being observed
    pub sources: Vec<String>,
    pub quorum: Option<i64>,  // Byzantine quorum threshold
    pub timeout: String,      // duration literal "5s", "100ms"
    pub on_partition: String, // fail (CT-3) | shield_quarantine
    pub certainty_floor: Option<f64>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub threshold: Option<f64>, // epistemic gate c ∈ [0.0, 1.0]
    pub tolerance: Option<f64>, // drift tolerance [0.0, 1.0]
    pub on_drift: String,       // provision | alert | refine (default: provision)
    pub shield_ref: String,
    pub mandate_ref: String,
    pub max_retries: i64, // default: 3
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub duration: String,  // "30s", "5m", "2h"
    pub acquire: String,   // on_start | on_demand (default: on_start)
    pub on_expire: String, // anchor_breach | release | extend (default: anchor_breach)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub aggregation: String, // majority | weighted | byzantine (default: majority)
    pub certainty_mode: String, // min | weighted | harmonic (default: min)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── §λ-L-E Fase 4 — Topology + π-calculus binary sessions ──────────────────

/// One step in a session protocol.
///
/// §Fase 4: `send T` | `receive T` | `loop` | `end`. §Fase 41.b adds **choice**:
/// `select { ℓ: [..], … }` (⊕ — this role chooses) and `branch { ℓ: [..], … }`
/// (& — this role offers); for those `op`s the labelled continuations live in
/// [`SessionStep::branches`] (a nested sub-protocol per label).
#[derive(Debug, Clone, Default)]
pub struct SessionStep {
    pub op: String,           // send | receive | loop | end | select | branch
    pub message_type: String, // only meaningful for send / receive
    /// §Fase 41.b — populated only for `op == "select" | "branch"`: the labelled
    /// branches, each a nested step sequence (its own sub-protocol).
    pub branches: Vec<SessionBranch>,
    pub loc: Loc,
}

/// §Fase 41.b — one labelled arm of a `select`/`branch` choice: `ℓ: [steps]`.
#[derive(Debug, Clone, Default)]
pub struct SessionBranch {
    pub label: String,
    pub steps: Vec<SessionStep>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `socket Name { protocol: SessionRef, backpressure: credit(n), reconnect:
/// cognitive_state, legal_basis: ... }`
///
/// §Fase 41.b — the typed WebSocket transport (paper_websocket_cognitive_primitive.md).
/// `socket` is NOT the protocol — the protocol is a `session` it references by
/// name (protocol and transport kept separate but composable). The type checker
/// resolves `protocol` to a declared `session` (whose two roles are already
/// duality-checked via the §41.a algebra), so the dialogue carried over the WS
/// connection is conformant + deadlock-free by construction.
#[derive(Debug, Default)]
pub struct SocketDefinition {
    pub name: String,
    /// The referenced `session` declaration's name — the protocol.
    pub protocol: String,
    /// The credit window of the typed-resource backpressure (`credit(n)`);
    /// `None` if unspecified. A `0` credit is rejected by the type checker.
    pub backpressure_credit: Option<i64>,
    /// `reconnect: cognitive_state` → `true` (resume mid-dialogue via a sealed
    /// §40.t snapshot); absent or `reconnect: none` → `false`.
    pub reconnect: bool,
    /// Optional `legal_basis:` annotation (enterprise audit/shield gate).
    pub legal_basis: Option<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub watch: Vec<String>,       // observe / ensemble / any declared ref
    pub sensitivity: Option<f64>, // [0.0, 1.0]
    pub baseline: String,         // "learned" (default) or name of a prior
    pub window: i64,              // samples used to estimate baseline (default: 100)
    pub scope: String,            // tenant | flow | global (MANDATORY, paper §8.2)
    pub tau: String,              // duration half-life
    pub decay: String,            // exponential (default) | linear | none
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `reflex Name { trigger, on_level, action, scope, sla }`
///
/// Deterministic, O(1) motor response. Contract invariants (paper §4.2):
/// never invokes an LLM; no long-running I/O; every activation emits a
/// signed_trace; idempotent on the same HealthReport.
#[derive(Debug, Default)]
pub struct ReflexDefinition {
    pub name: String,
    pub trigger: String,  // immune name (MANDATORY)
    pub on_level: String, // know | believe | speculate | doubt (default: doubt)
    pub action: String,   // drop | revoke | emit | redact | quarantine | terminate | alert
    pub scope: String,    // MANDATORY, paper §8.2
    pub sla: String,      // duration budget (e.g. "1ms")
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub source: String,     // immune name (MANDATORY)
    pub on_level: String,   // know | believe | speculate | doubt
    pub mode: String,       // audit_only | human_in_loop | adversarial
    pub scope: String,      // MANDATORY
    pub review_sla: String, // duration
    pub shield_ref: String, // optional shield gate (required for adversarial)
    pub max_patches: i64,   // bounded heal attempts (default: 3)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub render_hint: String, // card | list | form | chart | custom
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Tier 2+ structural fallback ──────────────────────────────────────────────

/// A declaration we recognize by keyword but parse only structurally.
/// Validates brace balance and captures keyword + name.
#[derive(Debug)]
pub struct GenericDeclaration {
    pub keyword: String,
    pub name: String,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Agent ────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AgentDefinition {
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String, // react | reflexion | plan_and_execute | custom
    pub on_stuck: String, // forge | hibernate | escalate | retry
    pub shield_ref: String,
    pub max_iterations: Option<i64>,
    pub max_tokens: Option<i64>,
    pub max_time: String,
    pub max_cost: Option<f64>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── §Fase 53 — Closed-catalog extension mechanism ────────────────────────────

/// One member of an `extension` declaration. For `category: effects`
/// the `name` is a provenance base (e.g. `"epistemic:believe"`) with
/// optional `semantics` + `default_confidence` (a CEILING, never a
/// floor — §53.d tainted-overriding). For `category: scan` the `name`
/// is a scan-category identifier and the metadata is typically absent.
#[derive(Debug, Clone)]
pub struct ExtensionMember {
    pub name: String,
    pub semantics: Option<String>,
    pub default_confidence: Option<f64>,
    pub loc: Loc,
}

/// `extension Name { category: effects|scan, members: [ "x" : { … }, … ] }`
///
/// §Fase 53. A first-class, auditable + gateable declaration that
/// expands a closed catalog with adopter-specific PROVENANCE members.
/// Soundness invariants (validated in §53.c/§53.d): members are
/// provenance-class only (never the enforceable effect set), must not
/// shadow a canonical base/category, and ride in the IR + proof bundle
/// so an independent PCC verifier re-derives against the same artifact.
#[derive(Debug)]
pub struct ExtensionDefinition {
    pub name: String,
    /// `effects` | `scan` — validated against the closed category set
    /// in §53.c (the type-checker), not the parser.
    pub category: String,
    pub members: Vec<ExtensionMember>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia. Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia. Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Shield ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ShieldDefinition {
    pub name: String,
    pub scan: Vec<String>,
    pub strategy: String, // pattern | classifier | dual_llm | canary | perplexity | ensemble
    pub on_breach: String, // halt | sanitize_and_retry | escalate | quarantine | deflect
    pub severity: String, // low | medium | high | critical
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Ledger ─────────────────────────────────────────────────────────────────
// §Fase 62.0 — the append-only, hash-linked audit chain. Took over the
// Provenance-Index role that `pix` historically (and only in the ℰMCP doc)
// occupied, so `pix` is freed for its true meaning: the PIX retrieval
// navigator (paper `paper_pix_formal_research.md`). A `ledger` binds a chain
// recorder to an audited surface (`axonstore://X`, `flow://X`, …); `depth`
// is chain retention, `branching` the Merkle factor, `model` the hash slug.

#[derive(Debug)]
pub struct LedgerDefinition {
    pub name: String,
    pub source: String,
    pub depth: Option<i64>,
    pub branching: Option<i64>,
    pub model: String,
    pub loc: Loc,
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub inference_mode: String, // active | passive
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Corpus ───────────────────────────────────────────────────────────────────

/// §Fase 63.A — a typed, weighted edge of an MDN corpus graph: `etype(from, to,
/// weight)`. `etype` is from the closed relation catalog (cite / elaborate /
/// corroborate / depend / implement / exemplify / contradict / supersede);
/// `from`/`to` name documents declared in the corpus; `weight ∈ (0, 1]`.
#[derive(Debug, Clone)]
pub struct CorpusRelation {
    pub etype: String,
    pub from: String,
    pub to: String,
    pub weight: f64,
    pub loc: Loc,
}

#[derive(Debug)]
pub struct CorpusDefinition {
    pub name: String,
    pub documents: Vec<String>, // simplified: list of pix refs
    /// §Fase 63.A — the typed weighted edges that make this corpus an MDN graph
    /// `C = (D, R, τ, ω, σ)`. Empty ⇒ the flat (edgeless) corpus.
    pub relations: Vec<CorpusRelation>,
    /// §Fase 63.C — `adaptive: true` enables the memory endofunctor: navigations
    /// over this corpus learn (semantic edge reinforcement + procedural bias),
    /// and subsequent navigations use the memory-modified EPR. Requires the
    /// graph to carry edges (static `relations:` OR a store-sourced edge store).
    pub adaptive: bool,
    pub mcp_server: String,
    pub mcp_resource_uri: String,
    /// §Fase 64.A — when `Some`, this is a DYNAMIC store-sourced MDN graph
    /// (`corpus N from axonstore { documents: DocStore(id, title)  relations:
    /// EdgeStore(from, to, etype, weight) }`): the documents and typed edges live
    /// as ROWS in two declared `axonstore`s and the graph is built from the live
    /// rows at navigate-time (per-tenant, growing). Mutually exclusive with the
    /// static §63 form — the `documents`/`relations`/`mcp_*` fields stay empty.
    /// `None` ⇒ the static compile-time corpus (back-compat byte-identical).
    pub store_source: Option<CorpusStoreSource>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 64.A — the dynamic, `axonstore`-sourced backing of an MDN corpus graph.
/// The graph's documents and typed edges are ROWS in two declared `axonstore`s,
/// so the graph grows at runtime (a new `persist` = a new node/edge) and is
/// per-tenant by inheritance from the store's §40 column-proof / RLS scope. The
/// runtime builds the `mdn::Corpus` from the live rows at navigate-time.
///
/// Surface:
/// ```text
/// corpus LtmGraph from axonstore {
///     documents: LtmSummaries( id, summary )                 // (id-col, title-col)
///     relations: LtmEdges( from_id, to_id, etype, weight )   // (from, to, etype, weight)
///     adaptive: true
/// }
/// ```
/// Documents and edges live in SEPARATE stores (an `axonstore` is one table with
/// one column schema). The type-checker (`check_corpus`) validates that both
/// stores are declared and — when they carry a §38 column schema — that the
/// mapped columns exist with compatible types (id present; title text-like;
/// from/to match the id type; etype text-like; weight numeric). The weight-range
/// invariant `ω ∈ (0, 1]` (G4) becomes a RUNTIME check here, since weights are
/// per-row dynamic (clamp on read + store CHECK), not a compile-time literal.
#[derive(Debug, Clone)]
pub struct CorpusStoreSource {
    pub doc_store: String,
    pub doc_id_col: String,
    pub doc_title_col: String,
    pub edge_store: String,
    pub edge_from_col: String,
    pub edge_to_col: String,
    pub edge_type_col: String,
    pub edge_weight_col: String,
    pub loc: Loc,
}

// ── Dataspace ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct DataspaceDefinition {
    pub name: String,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── OTS ──────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct OtsDefinition {
    pub name: String,
    pub teleology: String,
    pub homotopy_search: String, // shallow | deep | speculative
    pub loss_function: String,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    pub on_violation: String, // coerce | halt | retry
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Compute ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ComputeDefinition {
    pub name: String,
    pub shield_ref: String,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Daemon ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct DaemonDefinition {
    pub name: String,
    pub goal: String,
    pub tools: Vec<String>,
    pub memory_ref: String,
    pub strategy: String, // react | reflexion | plan_and_execute | custom
    pub on_stuck: String, // hibernate | escalate | retry | forge
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
    /// §Fase 52.d — the capability scope a daemon's runs are confined to
    /// (`requires: [cap, …]`, the same closed slug grammar as `axonendpoint
    /// requires:`). A scheduled (cron) daemon MUST declare this (it is a
    /// standing autonomous privilege); the enterprise supervisor mints a
    /// per-run principal scoped to EXACTLY these capabilities (least privilege,
    /// §52.d). Empty for event-only daemons / pre-§52 daemons.
    pub requires_capabilities: Vec<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── AxonStore ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AxonStoreDefinition {
    pub name: String,
    pub backend: String, // sqlite | postgresql | mysql
    pub connection: String,
    pub confidence_floor: Option<f64>,
    pub isolation: String, // read_committed | repeatable_read | serializable
    pub on_breach: String, // rollback | raise | log
    /// §Fase 35.j (D11) — Pillar IV: the capability slug required to
    /// access this store. Empty = no capability gate. Validated at
    /// parse time against the closed slug grammar (shared with the
    /// Fase 32.g `requires:` grammar).
    pub capability: String,
    /// §Fase 38.b (D1) — the OPTIONAL column-schema declaration. Three
    /// closed forms (inline / manifest-ref / env-var); `None` means the
    /// 37.x runtime+deploy path applies verbatim (D5 absolute). The
    /// §38.d / §38.e `StoreColumnProof` pass consumes this; the §38.h
    /// CLI exports it.
    pub column_schema: Option<crate::store_schema::StoreColumnSchema>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── AxonEndpoint ─────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct AxonEndpointDefinition {
    pub name: String,
    pub method: String, // GET | POST | PUT | DELETE
    pub path: String,
    pub body_type: String,
    pub execute_flow: String,
    pub output_type: String,
    pub shield_ref: String,
    pub retries: Option<i64>,
    pub timeout: String,
    /// §ESK Fase 6.1 — regulatory coverage on the boundary.
    pub compliance: Vec<String>,
    /// §Fase 30 — HTTP wire transport for the response. Closed enum
    /// per D2 ratified 2026-05-10: {"json" | "sse" | "ndjson"}.
    /// Default "json" (D1 — backwards-compat preserved). When set
    /// to "sse", the type-checker (30.c) verifies that
    /// `execute_flow` produces a Stream<T> (D3).
    pub transport: String,
    /// §Fase 30 — Keepalive comment interval for SSE transport (D6).
    /// Optional; default applied at runtime when transport == "sse"
    /// (default 15s). Closed enum at parse time:
    /// {"5s" | "15s" | "30s" | "60s"}. Empty string means
    /// "use runtime default".
    pub keepalive: String,
    /// §Fase 31.b — Type-Driven Wire Inference (D1, D7).
    /// `transport_explicit` is `true` if the source declared
    /// `transport:` explicitly (any of json/sse/ndjson). `false` if
    /// the field was omitted, in which case `transport` reflects the
    /// D1 default `"json"` but `implicit_transport` (computed by the
    /// `axon_frontend::type_checker::compute_implicit_transports`
    /// pass) carries the inferred value.
    pub transport_explicit: bool,
    /// §Fase 31.b — Inferred wire transport per D1:
    ///   implicit_transport(E) =
    ///     declared_transport(E)   if transport_explicit
    ///     "sse"                    if produces_stream(execute_flow) ∧ ¬explicit
    ///     "json"                   otherwise
    /// Empty string `""` before the type-checker runs. The Python
    /// reference implementation in `axon/compiler/type_checker.py`
    /// sets the field byte-identically (D7 cross-stack contract).
    pub implicit_transport: String,
    /// §Fase 32.g (D8) — Auth scope: capability slugs the request
    /// bearer must hold for the endpoint to dispatch. Empty vec
    /// means "no auth gate" (D9 backwards-compat). Slug grammar
    /// (closed): `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`. Examples:
    /// `admin`, `legal.read`, `hipaa.phi.read`. The runtime checks
    /// declared_requires ⊆ token_capabilities (AND semantics — every
    /// declared capability must be present in the bearer's claims).
    pub requires_capabilities: Vec<String>,
    /// §Fase 32.h — Replay-token binding (D9 plan-vivo).
    /// `replay_explicit` is `true` when the source declared `replay:`
    /// explicitly. `false` when the field was omitted, in which case
    /// `replay` reflects the method-default (POST/PUT → true, GET/
    /// DELETE → false) computed at deploy time. When the effective
    /// value resolves to `true`, every successful 2xx response is
    /// recorded in the runtime's axonendpoint replay log keyed by
    /// trace_id; auditors retrieve it via GET /v1/replay/<trace_id>.
    pub replay_explicit: bool,
    pub replay: bool,
    /// §Fase 33.z.k.b (v1.28.0) — Selected SSE wire-format dialect.
    ///
    /// Populated when the source uses the parametrized grammar
    /// `transport: sse(<dialect>)`. Closed catalog
    /// (`AXONENDPOINT_TRANSPORT_DIALECTS`): `{axon, openai, anthropic}`.
    /// Empty string `""` when:
    ///   - the source declared a non-SSE transport (`json`/`ndjson`), OR
    ///   - the source declared bare `transport: sse` without parens, OR
    ///   - the source omitted `transport:` entirely (D1 implicit path).
    ///
    /// When empty + the effective wire is SSE (per the runtime
    /// classifier `classify_dynamic_route_wire`), the runtime
    /// resolves the dialect via the Q1 algebraic-effect-driven
    /// default: openai for tool-streaming flows (algebraic predicate
    /// true), axon for type-annotation-only flows (algebraic predicate
    /// false). D3 explicit `transport: sse(<dialect>)` overrides the
    /// default.
    pub transport_dialect: String,
    /// §Fase 33.z.k.1 (v1.27.1) — Algebraic-effect override predicate.
    ///
    /// `true` when `execute_flow` references a tool that declares
    /// `effects: <stream:<policy>>` (Fase 30 algebraic-effect surface).
    /// Mirrors `type_checker::flow_uses_streaming_tool(execute_flow, program)`.
    ///
    /// Used by the runtime classifier
    /// (`axon_server::classify_dynamic_route_wire`) to OVERRIDE the
    /// v1.22.0 D6 backwards-compat gate: a tool with a declared stream
    /// effect is a LANGUAGE-LEVEL commitment to streaming, not a
    /// client preference. When this field is `true` AND
    /// `transport: json` is NOT explicitly declared (D3 opt-out remains
    /// sacred), the route wire is unconditionally `Sse` — no
    /// `Accept: text/event-stream` header required, no
    /// `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1` runtime flag required.
    ///
    /// Computed in lockstep with `implicit_transport` by the
    /// `compute_implicit_transports` pass. Default `false` before the
    /// pass runs (matches AST construction defaults; D9 backwards-
    /// compat preserved for older AST consumers).
    pub has_algebraic_stream_effect: bool,
    /// §Fase 36.d (D2) — the declared execution backend for the flow
    /// behind this endpoint. Empty string `""` means "not declared"
    /// (the endpoint resolves its backend down the Fase 36 D1
    /// precedence ladder — server default → environment-available
    /// `auto`). When non-empty the parser has validated it against the
    /// closed catalog [`crate::parser::AXONENDPOINT_BACKEND_VALUES`]
    /// and the type-checker rejects an unknown name as a compile
    /// error. A declared `backend:` is rung 2 of the resolution
    /// contract.
    pub backend: String,
    /// §Fase 37.y (D1) — Path parameter names extracted from the
    /// `path:` string at parse time. For `path: "/api/tenants/{tenant_id}/secrets/{secret_name}"`
    /// this is `["tenant_id", "secret_name"]`. Empty Vec when the
    /// path has no `{name}` placeholders (D5 backwards-compat — an
    /// endpoint without path params produces byte-identical IR to
    /// v1.38.4).
    ///
    /// Names are deduplicated + recorded in declaration order. A
    /// duplicate `{tenant_id}` in the same path is a parse error
    /// (HTTP route patterns reject duplicates structurally — `axum`
    /// would panic at registration). Type binding is always `Text`
    /// in v1.38.5 (HTTP path-segment convention); a future Fase 37.z
    /// may add per-placeholder type-override grammar `{tenant_id: Uuid}`.
    ///
    /// The Fase 37 D2 totality check (extended by 37.y D3) treats
    /// every name here as covering an equivalent flow parameter
    /// declared `Text`. Collision with a body field of the same name
    /// is a compile error (`axon-T901`, D4).
    pub path_params: Vec<String>,
    /// §Fase 37.y (D2) — Query parameters declared via the inline
    /// `query: { name: Type, name: Type? }` block on the endpoint.
    /// Empty Vec when the source omits the block (D5 backwards-compat).
    ///
    /// Closed type catalog (parser-enforced):
    /// `{Text, Int, Float, Bool, Uuid}`. The runtime receives every
    /// query value as a textual `String` and binds it to the same-named
    /// flow parameter; the closed catalog enables future per-type
    /// parsing/validation without breaking the manifest format.
    ///
    /// The optional flag (`?` suffix in the source) reuses
    /// `TypeExpr.optional`. An optional query param need not be
    /// covered by a flow parameter (D3 totality is over required
    /// params); a required query param missing from the flow signature
    /// is a `axon-T?nn` future arm. For v1.38.5 the totality check
    /// treats every query param as a binding-source candidate for any
    /// same-named flow param.
    ///
    /// Reusing `TypeField` (shared with body type declarations) keeps
    /// the D2 totality check uniform — the same `field.type_expr.name
    /// == param.type_expr.name` comparator works for body fields AND
    /// query params.
    pub query_params: Vec<TypeField>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Import ───────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ImportNode {
    pub module_path: Vec<String>,
    pub names: Vec<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// §Fase 58.a — the tool's typed INPUT SCHEMA (W2: the caller↔tool
    /// contract). Each entry is a named, typed parameter that the canonical
    /// `use Tool(k = v, …)` invocation binds against and the type-checker
    /// validates the caller's args against (CT-2 caller blame, pre-HTTP).
    /// Empty for a schema-less tool — the legacy single-`on <arg>` form still
    /// applies (§58 D5 back-compat). Reuses `Parameter` (same `TypeExpr`
    /// grammar as flow params).
    pub parameters: Vec<Parameter>,
    /// §Fase 58.a — the tool's declared OUTPUT type, so a tool-step's result
    /// is referenceable as `${Step.output}` with a real type (§58 D8). Flat
    /// string (mirrors step `output:`); `None` when undeclared.
    pub output_type: Option<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 19.e — `break` keyword. Payload-free; carries only its
    /// source location for error reporting.
    Break(BreakStatement),
    /// Fase 19.e — `continue` keyword. Payload-free; same shape as
    /// `Break`.
    Continue(ContinueStatement),
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
    /// §Fase 51.a — `quant { … }` cognitive block (Hilbert-space projection).
    /// Carries an optional attribute header + a real nested body of flow steps
    /// (so §51.b's Continuous Type Invariant can scan it). Lives inside a flow
    /// body like `par`; NOT a top-level declaration.
    Quant(QuantBlock),
    /// §Fase 51.d.2 — `yield <expr>` measurement point inside a `quant` block.
    /// Collapses the evolved amplitudes back to classical silicon; the effect
    /// operation whose resolution is a one-shot delimited continuation. Only
    /// well-formed inside a `quant` block (the checker rejects it elsewhere).
    Yield(YieldStatement),
    /// §Fase 52.c — `run <Flow>(args)` as a flow-step: invoke a declared flow
    /// from inside a body (notably a `daemon`'s `listen` handler — the Q3 ask).
    /// Reuses the top-level [`RunStatement`] shape (flow name + args + optional
    /// persona/context/anchors). Distinct from `Declaration::Run` only by
    /// position (a step inside a body vs. a program-root run).
    Run(RunStatement),
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
    /// §Fase 68.b — the step's declared MODEL CAPABILITY requirement: the
    /// context window (in tokens) the cognitive act needs. The §68.c resolver
    /// maps it to the smallest concrete model that satisfies it (per the
    /// resolved backend's §68.a catalog); `None` → the backend default
    /// (back-compat). Declare the NEED, not the vendor SKU (D68.1).
    pub requires_context: Option<u32>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

// ── Epistemic ────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct EpistemicBlock {
    pub mode: String,
    pub body: Vec<Declaration>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
    /// Fase 17.a — preserves the parser's tokenization intent so the
    /// runtime dispatcher can distinguish a quoted literal from a
    /// dotted-identifier reference. One of "literal", "reference",
    /// "expression". Defaults to "literal" so any pre-Fase-17 caller
    /// that constructs a LetStatement directly behaves as a literal.
    pub value_kind: String,
    /// §Fase 51.c.3 — optional type annotation `let x: <TypeExpr> = …`.
    /// `None` for the bare `let x = …` form (all pre-51.c.3 lets). Inside a
    /// `quant` block the Continuous Type Invariant inspects this to enforce the
    /// continuous-carrier discipline (`DensityMatrix[D]` D=2ⁿ; reject discrete
    /// conversational types). Carries the typed encoder-boundary contract.
    pub type_annotation: Option<TypeExpr>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

#[derive(Debug)]
pub struct ReturnStatement {
    pub value_expr: String,
    pub loc: Loc,
}

/// §Fase 51.d.2 — `yield <expr>` measurement point inside a `quant` block.
#[derive(Debug)]
pub struct YieldStatement {
    /// The measured expression (the structural hypothesis / density-matrix
    /// surrogate collapsed out of the Hilbert-space scope).
    pub value_expr: String,
    /// Tokenization intent (`literal` / `reference` / `expression`), mirroring
    /// `LetStatement.value_kind` so the runtime resolves the yielded value.
    pub value_kind: String,
    pub loc: Loc,
}

/// Fase 19.e — `break` keyword inside a for-in body. Carries no
/// payload; the runner translates it into a sentinel that
/// terminates the loop. Parser scope check (`loop_depth`)
/// guarantees this only appears inside a for-in body.
#[derive(Debug)]
pub struct BreakStatement {
    pub loc: Loc,
}

/// Fase 19.e — `continue` keyword inside a for-in body. Same
/// shape as ``BreakStatement``; the runner uses a different
/// sentinel type to distinguish loop-exit from iteration-skip.
#[derive(Debug)]
pub struct ContinueStatement {
    pub loc: Loc,
}

// ── Lambda Data (ΛD) — Epistemic State Vectors ─────────────────────────────

/// Top-level ΛD definition: ψ = ⟨T, V, E⟩ where E = ⟨c, τ, ρ, δ⟩.
#[derive(Debug)]
pub struct LambdaDataDefinition {
    pub name: String,
    pub ontology: String,             // T ∈ O — ontological type
    pub certainty: f64,               // c ∈ [0,1] — epistemic certainty scalar
    pub temporal_frame_start: String, // τ_start
    pub temporal_frame_end: String,   // τ_end
    pub provenance: String,           // ρ ∈ EntityRef — causal origin
    pub derivation: String, // δ ∈ Δ — see derivation catalogue (raw, derived, inferred, aggregated, transformed)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// In-flow ΛD application: binds epistemic state vector to a data target.
#[derive(Debug)]
pub struct LambdaDataApplyNode {
    pub lambda_data_name: String, // reference to LambdaDataDefinition
    pub target: String,           // expression to bind
    pub output_type: String,      // result type after epistemic binding
    pub loc: Loc,
}

// ── Tier 2 flow step nodes ──────────────────────────────────────────────────

#[derive(Debug)]
pub struct ProbeStep {
    pub target: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ReasonStep {
    pub strategy: String,
    pub target: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ValidateStep {
    pub target: String,
    pub rule: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct RefineStep {
    pub target: String,
    pub strategy: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct WeaveStep {
    pub sources: Vec<String>,
    pub target: String,
    pub format_type: String,
    pub priority: Vec<String>,
    pub style: String,
    pub loc: Loc,
}
/// §Fase 58.b — the closed catalog of `use <Tool>` argument forms. The
/// invocation surfaces are mutually exclusive, so a sum type models them
/// exactly (no ambiguous dual-empty state). NOTE: `apply: Tool given: <struct>`
/// (the splat form) is NOT here — it rides `StepNode.apply_ref` and is
/// validated against the tool schema in §58.d, not parsed as a `use`.
#[derive(Debug, Clone, PartialEq)]
pub enum UseArgs {
    /// `use Tool on "${arg}"` / `use Tool on query` — the §54.b single
    /// positional argument. D5 back-compat: behaves byte-identically to the
    /// pre-58 `argument: String` (empty string when no `on` clause).
    LegacyPositional(String),
    /// `use Tool(query = "${q}", max_results = 5)` — D2 canonical multi-field
    /// keyword args. Each entry is `(name, value, value_kind)`: `value` is the
    /// expression STRING (the frontend has no structured `Expr`; mirrors
    /// `argument` / `parse_argument_list`); `value_kind` is `"literal"` or
    /// `"reference"` — the §Fase 60 classification from `parse_let_atom`, so the
    /// runtime resolves a bare identifier / `Step.output` as a binding lookup
    /// (like `let`) instead of passing the name literally. The type-checker
    /// (§58.d + §60.c) validates each entry against the tool's declared input
    /// schema (W2 / CT-2 caller blame) and references against their source.
    Named(Vec<(String, String, String)>),
}

impl UseArgs {
    /// §58.b transitional — the legacy single-arg string for the IR `argument`
    /// field (still `String` until §58.c carries structured named args).
    /// `Named` projects an empty argument here; the type-checker validates
    /// named args from the AST, and §58.c/e wire their structured dispatch.
    pub fn legacy_argument(&self) -> String {
        match self {
            UseArgs::LegacyPositional(s) => s.clone(),
            UseArgs::Named(_) => String::new(),
        }
    }
}

#[derive(Debug)]
pub struct UseToolStep {
    pub tool_name: String,
    pub args: UseArgs,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct RememberStep {
    pub expression: String,
    pub memory_target: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct RecallStep {
    pub query: String,
    pub memory_source: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ParBlock {
    /// §Fase 65 — the concurrent branches. Each top-level statement inside
    /// `par { … }` is one branch (a single-statement body); they execute
    /// concurrently at runtime. Empty for a `par {}` with no statements
    /// (degenerate no-op). Before §65 this was payload-free (the branches were
    /// skipped at parse time), so `par` ran as a stub.
    pub branches: Vec<Vec<FlowStep>>,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct HibernateStep {
    pub event_name: String,
    pub timeout: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct DeliberateBlock {
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ConsensusBlock {
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ForgeBlock {
    pub loc: Loc,
}
#[derive(Debug)]
pub struct FocusStep {
    pub expression: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct AssociateStep {
    pub left: String,
    pub right: String,
    pub using_field: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct AggregateStep {
    pub target: String,
    pub group_by: Vec<String>,
    pub alias: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ExploreStepNode {
    pub target: String,
    pub limit: Option<i64>,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct IngestStep {
    pub source: String,
    pub target: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ShieldApplyStep {
    pub shield_name: String,
    pub target: String,
    pub output_type: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct StreamBlock {
    pub loc: Loc,
}
#[derive(Debug)]
pub struct NavigateStep {
    pub pix_name: String,
    pub corpus_name: String,
    pub query_expr: String,
    pub trail_enabled: bool,
    pub output_name: String,
    /// §Fase 63.B — for MDN corpus-graph navigation: the seed document `from:`
    /// to start the ε-informative traversal. Empty for PIX tree navigation.
    pub seed: String,
    /// §Fase 63.B — for MDN: the `budget:` (max documents). `None` = default.
    pub budget: Option<i64>,
    /// §Fase 66 (Q2) — optional column-scope filter (`where:`) for a
    /// `corpus from axonstore`. A raw filter expr (same shape as `retrieve …
    /// where`) pushed to the SELECT sourcing the corpus rows, so an adopter
    /// multiplexing sub-tenants in one axon-tenant via a column can scope the
    /// MDN graph to a single sub-tenant. Empty = no column filter (RLS-only).
    pub where_expr: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct DrillStep {
    pub pix_name: String,
    pub subtree_path: String,
    pub query_expr: String,
    pub output_name: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct TrailStep {
    pub navigate_ref: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct CorroborateStep {
    pub navigate_ref: String,
    pub output_name: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct OtsApplyStep {
    pub ots_name: String,
    pub target: String,
    pub output_type: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct MandateApplyStep {
    pub mandate_name: String,
    pub target: String,
    pub output_type: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct ComputeApplyStep {
    pub compute_name: String,
    pub arguments: Vec<String>,
    pub output_name: String,
    pub loc: Loc,
}
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
    /// §Fase 52.a — the handler body: real flow-steps executed on each event /
    /// scheduled tick. Pre-§52.a the `{ … }` block was `skip_braced_block`'d
    /// (the listener was inert); now it is parsed so a `daemon` can run logic
    /// (e.g. `run <Flow>(…)`) per trigger. Empty for a bodyless `listen`.
    pub body: Vec<FlowStep>,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct DaemonStepNode {
    pub daemon_ref: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct PersistStep {
    pub store_name: String,
    /// §Fase 35.o — the `{ col: value }` field block. Empty when the
    /// step is written without a block (`persist <store>`), in which
    /// case the runtime falls back to writing the flow's user
    /// bindings as a row (backward-compatible with v1.30.0).
    pub fields: Vec<(String, String)>,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct RetrieveStep {
    pub store_name: String,
    pub where_expr: String,
    pub alias: String,
    /// §Fase 67.b — optional `order_by:` clause: a closed
    /// comma-separated list of `column [asc|desc]` (same identifier
    /// discipline as `where:` columns — no injection). Empty = no
    /// ordering. Raw string, parsed + validated by the runtime
    /// (`filter::render_bounds`) and at `axon check` (§38.d `axon-T807`).
    pub order_by: String,
    /// §Fase 67.b — optional `limit:` clause: a `u32` literal OR a
    /// `${binding}` resolved to a `u32` at runtime. Empty = no limit.
    /// Raw string (`"100"` or `"${max}"`), validated at `axon check`
    /// (§38.d `axon-T808`).
    pub limit_expr: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct MutateStep {
    pub store_name: String,
    pub where_expr: String,
    /// §Fase 35.p — the `{ col: value }` SET assignments. Empty when
    /// the step declares no columns, in which case the runtime falls
    /// back to writing the flow's user bindings as the `SET` clause
    /// (backward-compatible with v1.31.0).
    pub fields: Vec<(String, String)>,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct PurgeStep {
    pub store_name: String,
    pub where_expr: String,
    pub loc: Loc,
}
#[derive(Debug)]
pub struct TransactBlock {
    pub loc: Loc,
}

/// §Fase 51.a — the `quant` cognitive primitive block surface
/// (`docs/papers/paper_primitiva_quant.md`; enterprise §Fase 51).
///
/// `quant` projects an MEK semantic tensor into a complex Hilbert space,
/// evolves it under a variational / kernel-feature map, and collapses back to
/// classical silicon. The attribute header is OPTIONAL — the bare `quant { … }`
/// form (the paper's example) leaves every attribute defaulted. The richer form
/// `quant(encoding: amplitude, observable: M, qubits: 10, depth: 4,
/// bandwidth: 0.5, backend: quant_sim) { … }` pins the encoding scheme (D2),
/// the Pauli-sum observable (D5), the register width / circuit depth, the
/// projected-kernel bandwidth γ (D7), and the algebraic-effect backend (D1/D9).
///
/// §51.a ships the SURFACE only. The Continuous Type Invariant over `body`
/// (§51.b), the typed continuous grammar incl. typed `let` + `Observable`
/// (§51.c), and the `quant_sim`/`qpu_native` effect injection + `yield`
/// measurement point (§51.d) land in subsequent sub-fases.
#[derive(Debug, Default)]
pub struct QuantBlock {
    /// `encoding:` — `amplitude` (default) or `angle` (shallow). `None` = the
    /// compiler default (amplitude). Carried as the surface spelling; §51.c
    /// validates against the closed scheme set.
    pub encoding: Option<String>,
    /// `observable:` — the name of a declared `Observable` (Pauli-sum, D5).
    /// `None` if unspecified (§51.c resolves + Hermiticity-checks it).
    pub observable: Option<String>,
    /// `qubits:` — the register width n (D = 2ⁿ). `None` = inferred from the
    /// encoded tensor dimensionality. The OSS reference backend caps n ≤ 10
    /// (D1); that bound is enforced at §51.e, not here.
    pub qubits: Option<i64>,
    /// `depth:` — the variational circuit depth L. `None` = backend default.
    pub depth: Option<i64>,
    /// `bandwidth:` — the projected-quantum-kernel bandwidth γ (D7). `None` =
    /// backend default.
    pub bandwidth: Option<f64>,
    /// The algebraic-effect backend tag: `quant_sim` (default) or `qpu_native`
    /// (D1/D9). Stored as the bare backend name; §51.d injects the full
    /// `ots:backend:<tag>` effect into the enclosing flow's effect row.
    pub effect: String,
    /// The nested flow-body statements (parsed like `par` branches, so §51.b
    /// can apply the Continuous Type Invariant to real AST). Empty for an
    /// empty `quant {}`.
    pub body: Vec<FlowStep>,
    pub loc: Loc,
}

/// §Fase 51.c.2 — one term `cₖ · Pₖ` of a Pauli-sum observable.
///
/// `coefficient` is a real scalar (parsed as `f64`); `pauli` is a Pauli string
/// over the closed alphabet `{I, X, Y, Z}` (one char per qubit), e.g. `"ZZ"` or
/// `"XI"`. A real linear combination of Pauli strings is **Hermitian by
/// construction** (each Pauli string is Hermitian; real-weighted sums preserve
/// Hermiticity), which is why the observable needs no separate Hermiticity check.
#[derive(Debug, Default, Clone)]
pub struct PauliTerm {
    pub coefficient: f64,
    pub pauli: String,
    pub loc: Loc,
}

/// §Fase 51.c.2 — the `observable <Name> { qubits, term: cₖ·Pₖ … }` declaration
/// (paper §3.2; plan D5). A typed Pauli-sum `M = Σ cₖ Pₖ` that a `quant` block
/// measures the evolved state against. The type-checker validates the closed
/// `{I,X,Y,Z}` alphabet + equal term lengths + non-empty sum; Hermiticity is
/// guaranteed by construction (real coefficients).
#[derive(Debug, Default)]
pub struct ObservableDefinition {
    pub name: String,
    /// `qubits: n` — the register width every Pauli string must span. `None`
    /// = inferred from the (equal) term lengths.
    pub qubits: Option<i64>,
    pub terms: Vec<PauliTerm>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 69.a — `witness <Name> { claim: <ref>  against: <baseline>
/// metric: <metric>  threshold: <ε>  data: <source> }`. The Advantage-Witness
/// proof obligation. The compiler proves it WELL-FORMED (§69.a, `axon-E0790`);
/// the advantage VALUE is computed on real `data` at deploy/runtime and carried
/// as a verdict (§69.b+). Fields are order-free `key: value` pairs.
#[derive(Debug)]
pub struct WitnessDefinition {
    pub name: String,
    /// The primitive instance whose advantage is claimed (e.g. an `observable` /
    /// `corpus` name, or a quant kernel reference).
    pub claim: String,
    /// The cheaper alternative the claim must beat (a closed-catalog baseline
    /// like `cosine` / `flat_retrieval` / `single_shot`, or a reference).
    pub baseline: String,
    /// How advantage is measured — a closed-catalog metric (`geometric_difference`,
    /// `kernel_target_alignment`, `ranking_lift`, `outcome_lift`).
    pub metric: String,
    /// The minimum advantage that justifies the cost (ε ≥ 0).
    pub threshold: f64,
    /// The real-data source the witness is evaluated on (a ref to an axonstore /
    /// corpus / labelled set). Required — advantage cannot be claimed in the abstract.
    pub data: String,
    pub loc: Loc,
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

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
    pub message: String,     // type name OR "Channel<T>" for second-order
    pub qos: String,         // at_most_once | at_least_once | exactly_once | broadcast | queue
    pub lifetime: String,    // linear | affine | persistent (D1 default: affine)
    pub persistence: String, // ephemeral | persistent_axonstore
    pub shield_ref: String,  // optional σ-shield gate for publish (D8)
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia attached to this declaration
    /// (comments preceding the declaration's first token, since the
    /// previous declaration or file start). Empty by default.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia (same line as the
    /// declaration's last effective token). Empty by default.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
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
