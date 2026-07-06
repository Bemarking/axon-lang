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
    /// §Fase 71.a — a temporal execution-window guard.
    Window(WindowDefinition),
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
    /// §Fase 80.b — the dual transport role of `socket`: a persistent,
    /// config-resolved OUTBOUND connection to a third-party vendor, typed by
    /// the same §41.a session algebra on the axon-facing side and transcoded
    /// to the vendor's wire frames by a declared total projection
    /// (docs/fase/fase_80_upstream_design.md).
    Upstream(UpstreamDefinition),
    /// §Fase 80.g — the voice-agent simplicity layer: macro-expands
    /// (inspectable via `axon desugar`, D80.6) to `ots` + carrier
    /// `session`/`socket` + `upstream` legs. The declaration stays in the
    /// AST for provenance + §80.c validation (T852); the IR carries only
    /// the expansion — sugar the compliance reviewer can always see through.
    Voice(VoiceDefinition),
    /// §Fase 83.a — a named, referenced browser-origin policy (mirrors
    /// `shield`'s shape exactly), resolved per `axonendpoint.cors:`
    /// reference (docs/fase/fase_83_cors_first_class_endpoint_property.md).
    Cors(CorsDefinition),
    /// §Fase 85.a — a named, referenced result-memoization policy (mirrors
    /// `cors`'s shape), resolved per `tool.cache:` / `retrieve.cache:`
    /// (docs/fase/fase_85_native_cache_primitive.md).
    Cache(CacheDefinition),
    /// §Fase 87.a — the long-horizon autonomous research primitive: a governed
    /// ORCHESTRATOR (not a monolith) that composes existing primitives
    /// (`memory`/`corpus`, `par`, `quant`, `forge`, `daemon`, the §72 budget,
    /// the §79 interruptible session, the §77 signed egress) into a
    /// budget-bounded, interruptible, fail-closed, provenance-witnessed
    /// research loop. Enterprise-exclusive at scale (charter split R1); the
    /// keyword + type discipline + ports live in OSS
    /// (docs/fase/fase_87_savant.md).
    Savant(SavantDefinition),
    /// §Fase 87.d — a dynamic tool-synthesis policy: the closed set of
    /// conditions (risk ceiling, source language, mandatory WASM zero-trust
    /// sandbox, Coder/Reviewer consensus) under which a `savant` may
    /// synthesise + execute a tool at runtime. The paper's "OTS = Ontological
    /// Tool Synthesis" grounded to a real keyword (`ots` already means
    /// one-shot media transform — paper §9.1). OSS declares + statically
    /// disciplines the policy and ships a DENY-BY-DEFAULT reference; the real
    /// Extism/WASM executor is enterprise (§87.j).
    Synth(SynthDefinition),
    /// §Fase 88.a — an authorization scope: the signed envelope (`targets`
    /// allowlist + `depth` ceiling + `approver`) a `warden` adversarial-analysis
    /// block MUST run `within`. The load-bearing safety construct that makes
    /// warden a governed auditor, not a weapon: no in-scope authorization ⇒ no
    /// analysis (fail-closed). Referenced by `warden(t) within <Scope>`
    /// (docs/fase/fase_88_warden.md).
    Scope(ScopeDefinition),
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
    pub op: String,           // send | receive | loop | end | select | branch | interrupt
    pub message_type: String, // send/receive: payload type · interrupt: the `on <Signal>` cause
    /// §Fase 41.b — populated only for `op == "select" | "branch"`: the labelled
    /// branches, each a nested step sequence (its own sub-protocol).
    ///
    /// §Fase 79.b — reused for `op == "interrupt"`: exactly two labelled arms,
    /// `body` (the interruptible region) and `handler` (runs on the signal). The
    /// handler may end in a `resume` step (back to `body`) or reach `end` (the
    /// abandon exit) — see the paper §3.5 two-exit construct.
    pub branches: Vec<SessionBranch>,
    /// §Fase 79.b — `op == "interrupt"` only: the handler's signal binder from
    /// `... as <sig> ...`. Empty for every other op. The handler references the
    /// received `CallInterruptCause` value under this name.
    pub binder: String,
    /// §Fase 79.b — `op == "interrupt"` only: `true` when the block declares a
    /// `resumable { … }` handler (the v1 surface always does). Default `false`
    /// keeps every non-interrupt step byte-identical in the IR (skip-if-false).
    pub resumable: bool,
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

/// `upstream Name { transport:, protocol:, role:, resolve:, secret:, auth:,
/// map: [...], reconnect: {...}, overflow:, backpressure: credit(n) }`
///
/// §Fase 80.b — the client dual of `socket`: axon dials OUT to a third-party
/// vendor (STT/TTS/realtime speech APIs). The axon-facing interface is a
/// declared `session` (referenced by `protocol:`, same field meaning as
/// `socket`) of which axon plays `role:`; the vendor side is realised by the
/// `map:` projection rules — a compile-time-total transcoding contract
/// (§80.c, axon-T849). `resolve:`/`secret:` name per-tenant config keys,
/// never URL/credential literals (axon-T850) — the same "config, not code"
/// property §58.g gave `tool`, extended to persistent duplex streams.
#[derive(Debug, Default)]
pub struct UpstreamDefinition {
    pub name: String,
    /// Wire transport axon dials. Closed catalog; v1 sole member `websocket`.
    pub transport: String,
    /// The referenced `session` declaration's name — the axon-facing protocol.
    pub protocol: String,
    /// Which of the session's two roles axon plays; the peer role is the
    /// vendor's, realised by the `map:` transcoding, never by axon code.
    pub role: String,
    /// Per-tenant config key holding the vendor URL (dot-separated,
    /// `SecretKeyPolicy`-shaped — never a URL literal).
    pub resolve: String,
    /// Per-tenant secret binding for the vendor credential (same charset).
    pub secret: String,
    /// Auth handshake kind: `header` | `query` | `signed_url`.
    pub auth_kind: String,
    /// Header/query-param name (`header("Authorization")` / `query("token")`).
    pub auth_name: Option<String>,
    /// Optional header value prefix (`header("Authorization", "Token ")`).
    pub auth_prefix: Option<String>,
    /// The wire↔session transcoding contract; totality checked at §80.c.
    pub map: Vec<UpstreamMapRule>,
    /// `reconnect: { backoff_ms:, max_attempts:, on_exhausted: }`.
    pub reconnect: Option<UpstreamReconnect>,
    /// Outbound-queue policy when the VENDOR is the slow side — a member of
    /// the existing `BackpressurePolicy` catalog. `None` ⇒ `fail` (honest
    /// default: no silently-lossy audio unless the adopter opts in).
    pub overflow: Option<String>,
    /// Axon-facing credit window, identical semantics to `socket`.
    pub backpressure_credit: Option<i64>,
    /// §Fase 80.f — set when declared via `upstream X from Preset@vN {…}`;
    /// carries the `Preset@vN` reference the desugar pass expanded.
    pub preset: Option<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// One `map:` projection rule: `send M as json [tag "X"]` /
/// `send M as binary` / `receive M as json [when "f" [= "v"]]` /
/// `receive M as binary`. Inbound `json` payloads land as §73 `Json` (total
/// navigation); the session message name is the routing + duality skeleton.
#[derive(Debug, Default)]
pub struct UpstreamMapRule {
    /// `send` (axon → vendor) or `receive` (vendor → axon).
    pub direction: String,
    /// The session message type this rule transcodes.
    pub message: String,
    /// `json` or `binary` (raw passthrough).
    pub framing: String,
    /// send-json only. Absent ⇒ the payload is sent VERBATIM (the vendor's
    /// exact wire shape, e.g. ElevenLabs `{"text": …}`); present ⇒ the tag
    /// is injected as `"type": "<tag>"` into the payload object (the
    /// Deepgram/OpenAI-Realtime envelope family).
    pub tag: Option<String>,
    /// receive-json only: discriminator field. Absent ⇒ the default
    /// equality discriminator `"type" = "<MessageName>"`.
    pub when_field: Option<String>,
    /// receive-json only. `Some(v)` ⇒ equality match on `when_field`;
    /// `None` with `when_field` present ⇒ field-PRESENCE match (vendors
    /// like Gemini Live mark frame kinds by which key exists). Equality
    /// rules dispatch before presence rules.
    pub when_value: Option<String>,
    pub loc: Loc,
}

/// `voice Name { stt:/tts: XOR realtime:, carrier:, interruptible:,
/// legal_basis:, persona:, context: }`
///
/// §Fase 80.g — the simplicity layer over §80's `upstream`: a blessed-
/// preset phone agent in under 20 lines. `stt:`+`tts:` (cascaded) XOR
/// `realtime:` (fused) — D80.1: one grammar, both architectures, never a
/// special-cased second path. Each leg is a `Preset@vN` reference or a
/// declared `upstream` name. Expansion is pure macro-lowering to existing
/// primitives; `axon desugar` prints it (D80.6).
#[derive(Debug, Default)]
pub struct VoiceDefinition {
    pub name: String,
    /// Cascaded STT leg (preset ref like `DeepgramSTT@v1` or upstream name).
    pub stt: Option<String>,
    /// Cascaded TTS leg.
    pub tts: Option<String>,
    /// Fused speech-to-speech leg (mutually exclusive with stt/tts — T852).
    pub realtime: Option<String>,
    /// Carrier codec: `mulaw8k` (default — PSTN; expansion emits the §ots
    /// μ-law↔PCM16 pair) or `pcm16` (browser/WebRTC-style, no transcode).
    pub carrier: String,
    /// `true` ⇒ the carrier session is a §79 interruptible region (barge-in
    /// capable) and the socket parks residuals — which REQUIRES
    /// `legal_basis:` (T852; the sugar must not generate a program
    /// `ParkedResidualSoundness` refutes).
    pub interruptible: bool,
    /// Rides onto the generated socket (the §79 data-at-rest obligation).
    pub legal_basis: Option<String>,
    /// Optional references wired for the flow layer (validated to exist).
    pub persona: Option<String>,
    pub context: Option<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `cors Name { allow_origins:, allow_methods:, allow_headers:,
/// allow_credentials:, max_age:, expose_headers: }`
///
/// §Fase 83.a — a named, referenced origin-policy declaration, mirroring
/// `shield`'s shape exactly: declared once, referenced from any number of
/// `axonendpoint`s via `cors: <Name>` (`AxonEndpointDefinition::cors_ref`).
/// Makes the browser-facing origin policy a property of the ENDPOINT,
/// resolved per the tenant's live deployed bundle — the shape a single
/// process-wide CORS knob (the market-standard pattern) cannot express for
/// a multi-tenant deploy where different bundles need different origins
/// for a path with the same name (D83.1/D83.3).
///
/// **Unknown fields are a hard parse error** (D83.7) — a CORS policy is
/// security-relevant, so `upstream`/`voice`'s stricter posture is followed
/// here, not `shield`'s lenient `axon-W010` record-and-skip.
#[derive(Debug, Default)]
pub struct CorsDefinition {
    pub name: String,
    /// `["https://app.example.com", "https://*.kivi.io"]` — exact origins
    /// or a single leading-wildcard host-label glob (D83.1/T854); no full
    /// regex, matching the closed/decidable spirit of the rest of the
    /// language. `["*"]` (any-origin) is legal UNLESS `allow_credentials`
    /// is also `true` — that combination is `axon-T853` (D83.2, the CORS
    /// spec's own rule, caught at compile time instead of a silent browser
    /// rejection).
    pub allow_origins: Vec<String>,
    /// Reuses the closed `axonendpoint` method catalog (GET/POST/PUT/
    /// PATCH/DELETE) — validated against the same list, not a free string
    /// (T855).
    pub allow_methods: Vec<String>,
    /// Request headers the preflight may allow (e.g. `["Content-Type",
    /// "Authorization"]`) — free-form header-name strings (hyphens are
    /// common in real header names, hence string literals, not bare
    /// identifiers).
    pub allow_headers: Vec<String>,
    /// `true` ⇒ `Access-Control-Allow-Credentials: true` is emitted.
    /// Forbidden together with an any-origin `allow_origins` (T853).
    pub allow_credentials: bool,
    /// `Access-Control-Max-Age` — a duration literal (`"3600s"`, `"1h"`),
    /// same lexer/token convention as `axonendpoint.timeout`. `None` ⇒ the
    /// header is omitted (browser default caching applies).
    pub max_age: Option<String>,
    /// `Access-Control-Expose-Headers` — response headers the browser's
    /// JS may read beyond the CORS-safelisted set. Free-form strings, same
    /// rationale as `allow_headers`.
    pub expose_headers: Vec<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `cache Name { backend:, ttl:, key:, default:, apply_to_effects:,
/// invalidate_on: }` — §Fase 85.a, a named, referenced result-memoization
/// policy resolved per `tool.cache:` / `retrieve.cache:` (mirrors
/// `CorsDefinition`'s named-and-referenced shape).
///
/// The load-bearing idea (D85.1): cacheability derives from the type system's
/// existing `effects: pure` proof — a `pure` tool is safe to cache by
/// construction. A `default: true` cache auto-covers every `pure` tool with
/// zero per-tool annotation; widening `apply_to_effects:` beyond `[pure]` is
/// allowed but the compiler names every non-pure tool it covers (W013) AND
/// forces a finite `ttl:` (T865 — you may cache a proven-deterministic result
/// forever, never a non-deterministic one).
///
/// **Unknown fields are a hard parse error** (the §83 D83.7 discipline) — a
/// cache governs correctness (serving a stale/foreign result is a real bug), so
/// a typo'd field can never silently mean "no policy."
#[derive(Debug, Default)]
pub struct CacheDefinition {
    pub name: String,
    /// `redis` (multi-replica, enterprise tier) or `in_process` (the OSS
    /// default single-replica tier). Empty ⇒ `in_process`. Validated against a
    /// closed catalog at check time.
    pub backend: String,
    /// Time-to-live as a duration literal (`"10s"`, `"5m"`, `"1h"`), same lexer
    /// convention as `cors.max_age`/`tool.timeout`. `None` ⇒ "cache forever" —
    /// sound ONLY for a provably-`pure` cache; a non-pure cache with no `ttl:`
    /// is `axon-T865` (D85.9).
    pub ttl: Option<String>,
    /// `key: [param, ...]` — the SUBSET of the covered tool's `parameters:`
    /// whose bound values form the cache key. Empty ⇒ ALL bound parameters
    /// (the automatic, zero-friction default). Used when one bound arg — e.g. a
    /// `request_id` — must NOT affect the key.
    pub key_params: Vec<String>,
    /// `default: true` ⇒ this cache auto-covers every eligible tool in the
    /// module without a per-tool `cache:` reference. At most one per module
    /// (`axon-T863`). Default `false`.
    pub default_policy: bool,
    /// `apply_to_effects: [pure, ...]` — the effect classes this cache is
    /// willing to memoise. Empty ⇒ `[pure]` (the only provably-safe default).
    /// Any member beyond `pure` is a WIDENING (W013 names each covered tool)
    /// and forces a finite `ttl:` (T865).
    pub apply_to_effects: Vec<String>,
    /// `invalidate_on: [Channel, ...]` — an `emit` on any listed channel
    /// flushes this cache's namespace. Each must resolve to a declared
    /// `channel` (`axon-T864`). Reuses the §13 pub/sub, not a second mechanism.
    pub invalidate_on: Vec<String>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 87.a — `savant <Name> { domain:, cognition{…}, memory{…}, budget{…},
/// mandate <M> {…} … }` — the long-horizon autonomous research primitive.
///
/// A `savant` is a declarative ORCHESTRATOR, not a new engine: it composes the
/// primitives Axon already ships (memory/corpus retention, `par` swarms, the
/// `quant` Hilbert substrate, `forge` novelty synthesis, the `daemon` host, the
/// §72 linear budget, the §79 interruptible session, the §77 signed egress)
/// into a single governed research loop. The paper's vision (docs/papers/
/// paper_primitiva_savant.md) grounded to real primitives in its §9.
///
/// §87.a parses the FULL block surface; the semantics land incrementally:
/// param-catalog + typed-output validation is §87.b (checker), memory-ref
/// resolution + §72 budget binding + §79 interruptibility is §87.c, and the
/// `SavantSoundness` PCC proof is §87.g. **Unknown fields are a hard parse
/// error** (the §83 D83.7 discipline, as `cache`/`cors`): a savant governs an
/// expensive, risk-bearing autonomous process, so a typo'd field can never
/// silently mean "no policy."
#[derive(Debug, Default)]
pub struct SavantDefinition {
    pub name: String,
    /// `domain: "…"` — the ontological scope of the generative boundary (the
    /// research topic the free-energy loop minimises surprise over). Required
    /// (§87.b `axon-T873`); empty until parsed.
    pub domain: String,
    /// `cognition { … }` — the epistemic parameters of the active-inference
    /// engine (depth / entropic threshold / divergence). `None` ⇒ engine
    /// defaults (§87.b supplies a catalog-checked default).
    pub cognition: Option<SavantCognition>,
    /// `memory { … }` — the retention layer. `backend` resolves to a declared
    /// `memory`/`corpus` primitive in §87.c (`axon-T875`); `None` ⇒ ephemeral.
    pub memory: Option<SavantMemory>,
    /// `budget { … }` — the compute ceiling. Bound to a §72 linear budget
    /// (`RateLease`) in §87.c so `max_iterations` is a TYPE-enforced ceiling,
    /// not a hope. `None` ⇒ §87.c rejects (a weeks-long autonomous loop with no
    /// budget is uninsurable).
    pub budget: Option<SavantBudget>,
    /// `mandate <Name> { objective:, output: }` — one or more epistemic
    /// mandates the savant autonomously decomposes into tasks. At least one
    /// required (§87.b `axon-T874`).
    pub mandates: Vec<SavantMandate>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 87.a — the `cognition { … }` sub-block of a [`SavantDefinition`]: the
/// active-inference engine's epistemic parameters (paper §3, §7.1).
#[derive(Debug, Default)]
pub struct SavantCognition {
    /// `depth: standard | deep | hyper` — the HRR dimensionality tier of the
    /// holographic memory codec. Closed catalog (§87.b `axon-T876`).
    pub depth: String,
    /// `entropic_threshold: <float>` — the Expected-Free-Energy convergence
    /// bound: the loop halts synthesis when no policy reduces EFE below this.
    /// Must be `> 0` (§87.b). `None` ⇒ engine default.
    pub entropic_threshold: Option<f64>,
    /// `divergence: low | med | high` — how aggressively the loop explores
    /// epistemic (β₂) voids vs. exploiting known structure. Closed catalog.
    pub divergence: String,
    pub loc: Loc,
}

/// §Fase 87.a — the `memory { … }` sub-block of a [`SavantDefinition`]: the
/// durable retention layer, composed from existing `memory`/`corpus` primitives.
#[derive(Debug, Default)]
pub struct SavantMemory {
    /// `backend: <Name>` — a reference to a declared `memory` or `corpus`
    /// primitive (resolved in §87.c `axon-T875`). Empty ⇒ ephemeral memory.
    pub backend: String,
    /// `corpus_graph: <bool>` — whether to iteratively index the ingested
    /// corpus as a simplicial-complex graph for the topological (β_n) reading.
    pub corpus_graph: bool,
    /// `isolation_level: strict | …` — per-tenant tensor partitioning. The
    /// enterprise engine enforces it; OSS records it. Empty ⇒ default.
    pub isolation_level: String,
    pub loc: Loc,
}

/// §Fase 87.a — the `budget { … }` sub-block of a [`SavantDefinition`]: the
/// compute ceiling, bound to a §72 linear budget in §87.c.
#[derive(Debug, Default)]
pub struct SavantBudget {
    /// `max_iterations: <int>` — the hard ceiling on FEP-loop iterations before
    /// the savant pauses (the paper's `compute_budget`). `> 0` (§87.b).
    pub max_iterations: Option<i64>,
    /// `max_tool_synth: <int>` — the hard ceiling on `synth` (§87.d) dynamic
    /// tool-creation events per mandate. `None` ⇒ 0 (no synthesis).
    pub max_tool_synth: Option<i64>,
    pub loc: Loc,
}

/// §Fase 87.a — a `mandate <Name> { objective:, output: }` sub-block of a
/// [`SavantDefinition`]: one epistemic research goal the savant pursues.
#[derive(Debug, Default)]
pub struct SavantMandate {
    pub name: String,
    /// `objective: "…"` — the natural-language research goal. Required
    /// (non-empty, §87.b `axon-T874`).
    pub objective: String,
    /// `output: <Type>` — the declared type the final report must inhabit
    /// (resolved to a declared `type` in §87.b). Required.
    pub output_type: String,
    pub loc: Loc,
}

/// §Fase 87.d — `synth <Name> { target:, risk:, language:, sandbox:, review:,
/// max_lines: }` — a dynamic tool-synthesis policy.
///
/// A `savant` that hits an epistemic gap it has no tool for can, under such a
/// policy, deduce + write a tool (a Coder sub-agent, a Reviewer sub-agent — a
/// `par` with an agreement condition), compile it to `wasm32-wasi`, and run it
/// in an Extism zero-trust sandbox, feeding stdout back as empirical evidence
/// (paper §6). The policy declares the SAFETY ENVELOPE; the runtime enforces it.
///
/// **Deny-by-default (D87.d):** OSS parses + statically disciplines this policy
/// but ships a `SynthBackend` reference that REFUSES to execute — running
/// untrusted synthesised code needs the enterprise Extism/gVisor isolation
/// (§87.j). The checker therefore requires `sandbox: wasm` (T882): a synth
/// policy that would run code outside a sandbox can never compile.
///
/// **Unknown fields are a hard parse error** (D83.7): a synth policy governs
/// arbitrary-code execution — the highest-stakes surface in the language.
#[derive(Debug, Default)]
pub struct SynthDefinition {
    pub name: String,
    /// `target: "…"` — what the synthesised tools are for (the capability scope).
    /// Required (§87.d `axon-T879`).
    pub target: String,
    /// `risk: low | medium | high | critical` — the ceiling risk class the
    /// policy admits; governs review + isolation strictness. Required
    /// (§87.d `axon-T880`).
    pub risk: String,
    /// `language: rust | c | python` — the allowed synthesis source language
    /// (all compiled to `wasm32-wasi`). Empty ⇒ any admitted language
    /// (§87.d `axon-T881` validates when present).
    pub language: String,
    /// `sandbox: wasm` — the isolation tier. MUST be `wasm` (§87.d `axon-T882`
    /// deny-by-default): synthesised code may only run in a zero-trust WASM
    /// sandbox. Empty ⇒ error (never a silent "no sandbox").
    pub sandbox: String,
    /// `review: required | none` — the Coder/Reviewer consensus requirement.
    /// Empty ⇒ `required` (the safe default). `none` is FORBIDDEN for
    /// `high`/`critical` risk (§87.d `axon-T883`).
    pub review: String,
    /// `max_lines: <int>` — an optional hard cap on synthesised source length
    /// (a smaller attack + review surface). `None` ⇒ engine default.
    pub max_lines: Option<i64>,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// `reconnect: { backoff_ms: 500, max_attempts: 5, on_exhausted: fail }` —
/// exponential backoff (doubling from `backoff_ms`, jittered at runtime), at
/// most `max_attempts` redials; `on_exhausted` is a closed catalog mirroring
/// `budget`'s style (v1 sole member `fail` — fail-closed, the flow sees the
/// exhaustion; `degrade`/`park` are named deferred scope).
#[derive(Debug, Default)]
pub struct UpstreamReconnect {
    pub backoff_ms: i64,
    pub max_attempts: i64,
    pub on_exhausted: String,
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

/// §Fase 71.a — a temporal execution-window guard. Where `shield` guards the
/// CONTENT of an emission and `anchor` guards its TRUTH, `window` guards its
/// TIMING: whether a scheduled (cron) tick runs, by timezone-aware day/hour
/// windows. The runtime decision (`is_in_window`) lands in §71.b; the daemon
/// binding + the defer ledger in §71.c/d.
#[derive(Debug)]
pub struct WindowDefinition {
    pub name: String,
    /// IANA timezone (`"America/Bogota"`). Format-checked at compile time
    /// (§71.a); full IANA membership validated by the runtime (§71.b, chrono-tz).
    pub timezone: String,
    /// The allowed day/hour spans (at least one). A tick inside ANY span runs.
    pub allow: Vec<WindowSpan>,
    /// §Fase 71.e — excluded dates (holidays): ISO `YYYY-MM-DD` date-string
    /// literals (`exclude: [ "2026-12-25", "2026-01-01" ]`). A tick whose local
    /// date (in `timezone`) is in this set is OUTSIDE the window regardless of the
    /// hour spans. The dates are LITERAL — part of the verified program, so the
    /// decision stays a pure, replayable function of `(now, the window, the tz-db
    /// version)` (the `time_is_an_explicit_input` doctrine). Empty ⇒ no holidays.
    pub exclude: Vec<String>,
    /// What to do when a tick falls OUTSIDE every allowed span:
    /// `skip` | `defer` | `warn` (closed catalog).
    pub on_outside: String,
    pub loc: Loc,
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 71.a — one allowed day/hour span, `{ days: Mon..Fri, hours: 9..18 }`.
/// `days` are inclusive weekday-name bounds; `hours` are inclusive 0–23 bounds.
#[derive(Debug)]
pub struct WindowSpan {
    pub day_start: String,
    pub day_end: String,
    pub hour_start: i64,
    pub hour_end: i64,
    pub loc: Loc,
}

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
    /// §Fase 77.a — egress signing algorithm (closed catalog: `hmac_sha256`,
    /// `axon-T846`). Empty = the shield does not sign. A shield with `sign:`
    /// is an EGRESS shield: `publish <Channel> within <Shield>` marks the
    /// channel for signed external delivery (§77.b).
    pub sign: String,
    /// §Fase 77.a (`axon-W010`) — block fields the parser did not recognize,
    /// with their source locations. Pre-77 the parser silently discarded
    /// these (`_ => skip_value()`), so a typo or an unsupported field passed
    /// `axon check` unremarked (Kivi brief #51 §B.3). The parser still skips
    /// the VALUE (leniency preserved — existing programs keep compiling) but
    /// records the NAME so the type checker can warn honestly.
    pub unknown_fields: Vec<(String, Loc)>,
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
    /// §Fase 71.c — the `window:` temporal binding (a `window` primitive name,
    /// §71.a). When set, the supervisor evaluates the bound window before
    /// claiming a scheduled tick: inside ⇒ fire; outside ⇒ `skip`/`warn`/`defer`
    /// per the window's `on_outside`. Empty for daemons with no temporal guard.
    pub window_ref: String,
    /// §Fase 72.a — the `budget { … }` linear-effect rate limit. When set, each
    /// `on Tool(X)` quota gates that tool's dispatch on a renewable token bucket
    /// (the §72.b `RateLease`): a call consumes a token, exhaustion applies
    /// `on_exhausted`. `None` for daemons with no effect budget.
    pub budget: Option<BudgetBlock>,
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

/// §Fase 72.a — a `budget { … }` block: a set of per-effect rate quotas plus the
/// exhaustion policy. Where `window` guards an effect's TIMING, `budget` guards
/// its RATE — a tool call consumes one token from a renewable bucket, and
/// over-emission is impossible by construction (the Logic pillar's linearity
/// made real for external effects).
#[derive(Debug)]
pub struct BudgetBlock {
    /// The per-effect quotas (`rate:`/`max:` lines). At least one.
    pub quotas: Vec<BudgetQuota>,
    /// What to do when a quota is exhausted: `block` (fail-closed, the default) |
    /// `defer` (reschedule via the §71 defer ledger) | `shed` (skip the call).
    pub on_exhausted: String,
    pub loc: Loc,
}

/// §Fase 72.a — one quota line of a [`BudgetBlock`]:
/// `<kind>: <limit> per <period> on Tool(<effect>)`.
#[derive(Debug)]
pub struct BudgetQuota {
    /// `rate` (a renewable bucket that refills `limit` tokens per `period`) or
    /// `max` (a windowed hard cap of `limit` per `period`, no intra-window refill).
    pub kind: String,
    /// The token allowance per period (> 0).
    pub limit: i64,
    /// The renewal/window period: `second` | `minute` | `hour` | `day`.
    pub period: String,
    /// The effect this quota governs — a declared `Tool` name (`on Tool(X)`).
    pub effect: String,
    pub loc: Loc,
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
    /// §Fase 83.a — the `cors: <Name>` reference, or `""` if absent
    /// (D83.5: absent ⇒ no CORS headers, ever — secure by default). Same
    /// empty-string sentinel convention as `shield_ref`, not `Option`.
    pub cors_ref: String,
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
    /// §Fase 84.b — Remote Hands. The `socket` this technician tool dispatches
    /// over: a program acting on a real machine dials `axon` as a `socket`
    /// client, and a `target:`-bound tool call sends its rendered argv down
    /// that connection. `None` ⇒ today's unchanged in-process / model-surface
    /// behaviour (zero regression; the whole §84 surface is inert unless
    /// `target:` is set). Resolved to a declared `socket` and duality-checked
    /// by `axon-T861`.
    pub target: Option<String>,
    /// §Fase 84.b — the operation's risk class, a v1-closed catalog of exactly
    /// `safe | destructive` (`technician::VALID_RISK_LEVELS`). `destructive`
    /// forces the bound session to carry a reachable `branch{approved/denied}`
    /// confirmation (`axon-T860`). `None` on a non-technician tool.
    pub risk: Option<String>,
    /// §Fase 84.b — the **argv template**: an ordered list of argv elements,
    /// each either a literal token (`"ping"`, `"-c"`) or a *whole-element*
    /// `${param}` placeholder (`"${host}"`). A placeholder binds to a declared
    /// `parameters:` entry and is substituted as ONE opaque argv argument at
    /// dispatch — never concatenated, never re-parsed by a shell (D84.1). This
    /// is the injection-safety keystone: the market's free `template:` STRING
    /// is deliberately NOT offered. Empty for a non-technician tool; required
    /// (`axon-T858`) when `target:` is set on a `provider: bash` tool.
    pub argv: Vec<String>,
    /// §Fase 85.b — the result-memoization policy for this tool. Names a
    /// declared `cache` (`axon-T864`), or the reserved sentinel `none` to opt
    /// OUT of an active `cache { default: true }` policy (the escape hatch for
    /// a rare mislabeled-`pure` tool). Empty ⇒ governed by the module default
    /// if one exists and this tool is eligible (`pure`, or covered by the
    /// default's `apply_to_effects`). Distinct from `memory` (D85.6).
    pub cache: String,
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
    /// §Fase 88.a — `warden(<target>) within <Scope> { … }` adversarial
    /// security-analysis block. A flow-body block (like `quant`): a target
    /// reference + a mandatory `within <Scope>` authorization clause + a nested
    /// body (`find_exploits()` → `list[Vulnerability]`, `fortify`). NOT a
    /// top-level declaration.
    Warden(WardenBlock),
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

// ── §Fase 70.a — the pure expression engine (`Expr`) ─────────────────────────

/// A pure, total expression in AXON's closed-catalog expression sublanguage
/// (§Fase 70). Evaluates to a value with no side effects, no I/O, no recursion
/// and no unbounded loops — so it is decidable and const-foldable. Mounted as
/// the condition of an `if` (and, in later sub-fases, `let` values + `where:`
/// predicates). Field/index access and the builtin catalog land in §70.c/d.
#[derive(Debug, Clone)]
pub enum Expr {
    /// A typed literal (`42`, `3.14`, `true`, `"hello"`).
    Lit(ExprLit),
    /// A reference to a binding or dotted path (`x`, `User.tier`).
    Ref(String),
    /// A unary operation (`-x`, `not x`).
    Unary(UnOp, Box<Expr>),
    /// A binary operation (`a + b`, `a >= b`, `a and b`).
    Binary(BinOp, Box<Expr>, Box<Expr>),
    /// §Fase 70.c — a closed-catalog builtin call. `args[0]` is the receiver
    /// (the value before the `.`); any further entries are the call arguments.
    /// E.g. `recent.length` → `Call(Length, [Ref("recent")])`,
    /// `name.starts_with("Dr")` → `Call(StartsWith, [Ref("name"), Lit(Str)])`.
    Call(Builtin, Vec<Expr>),
    /// §Fase 70.d — field access on a non-reference base (`items[0].name`,
    /// `(expr).field`). A plain dotted path stays a `Ref` (`a.b.c`) for
    /// back-compat; this node is the structured form the JSONB SQL lowering
    /// (deferred §73) consumes. The `String` is the field name.
    Field(Box<Expr>, String),
    /// §Fase 70.d — index access `base[index]` (array element / string char).
    Index(Box<Expr>, Box<Expr>),
}

/// The closed catalog of pure builtins (§Fase 70.c). All are total + pure.
/// Collection/string predicates only; the predicate-taking folds (`any`/`all`/
/// `none`) need lambdas and are deferred, as are `sum`/`min`/`max` and `in`/`??`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Builtin {
    /// `.length` — collection element count, or character count of a string.
    Length,
    /// `.count` — alias of `length`.
    Count,
    /// `.is_empty` — `length == 0`.
    IsEmpty,
    /// `.is_null` — the value is absent / empty / `null`.
    IsNull,
    /// `.contains(x)` — array membership, or string substring.
    Contains,
    /// `.starts_with(s)` — string prefix test.
    StartsWith,
    /// `.ends_with(s)` — string suffix test.
    EndsWith,
    /// §Fase 73.c — `.as_int` — honest coercion of a `Json` value to an
    /// integer. Fail-closed: a value that is not a JSON integer resolves
    /// to `null`, never a panic (doctrine `open_data_is_total`).
    AsInt,
    /// §Fase 73.c — `.as_float` — honest coercion to a float (an integer
    /// widens; anything else → `null`).
    AsFloat,
    /// §Fase 73.c — `.as_string` — honest coercion to a string (only a
    /// JSON string succeeds; a number / bool / null → `null`).
    AsString,
    /// §Fase 73.c — `.as_bool` — honest coercion to a boolean (only a
    /// JSON bool succeeds; anything else → `null`).
    AsBool,
}

impl Builtin {
    /// The number of arguments AFTER the receiver (`args[0]`).
    pub fn extra_arity(self) -> usize {
        match self {
            Builtin::Length
            | Builtin::Count
            | Builtin::IsEmpty
            | Builtin::IsNull
            | Builtin::AsInt
            | Builtin::AsFloat
            | Builtin::AsString
            | Builtin::AsBool => 0,
            Builtin::Contains | Builtin::StartsWith | Builtin::EndsWith => 1,
        }
    }

    /// The surface name (after the `.`).
    pub fn surface(self) -> &'static str {
        match self {
            Builtin::Length => "length",
            Builtin::Count => "count",
            Builtin::IsEmpty => "is_empty",
            Builtin::IsNull => "is_null",
            Builtin::Contains => "contains",
            Builtin::StartsWith => "starts_with",
            Builtin::EndsWith => "ends_with",
            Builtin::AsInt => "as_int",
            Builtin::AsFloat => "as_float",
            Builtin::AsString => "as_string",
            Builtin::AsBool => "as_bool",
        }
    }

    /// Resolve a name (after a `.`) to a builtin, or `None` if it is an ordinary
    /// field / path segment.
    pub fn from_name(name: &str) -> Option<Builtin> {
        Some(match name {
            "length" => Builtin::Length,
            "count" => Builtin::Count,
            "is_empty" => Builtin::IsEmpty,
            "is_null" => Builtin::IsNull,
            "contains" => Builtin::Contains,
            "starts_with" => Builtin::StartsWith,
            "ends_with" => Builtin::EndsWith,
            "as_int" => Builtin::AsInt,
            "as_float" => Builtin::AsFloat,
            "as_string" => Builtin::AsString,
            "as_bool" => Builtin::AsBool,
            _ => return None,
        })
    }
}

/// A literal value inside an [`Expr`]. The lexical form is preserved enough to
/// round-trip; the runtime evaluator (§70.f) coerces across these per the
/// existing string-runtime discipline.
#[derive(Debug, Clone)]
pub enum ExprLit {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
}

/// Unary operators (closed catalog).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnOp {
    /// Arithmetic negation `-`.
    Neg,
    /// Boolean negation `not`.
    Not,
}

/// Binary operators (closed catalog). Precedence is encoded in the Pratt parser.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
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
    /// §Fase 70.a — the parsed expression form of the condition. `None` when
    /// the condition fits the legacy `(condition, op, value)` + `or` shape
    /// (then the legacy fields drive evaluation, byte-identical to pre-§70);
    /// `Some` only for the richer forms the legacy triple cannot express
    /// (`and`, `not`, arithmetic, parentheses, nesting), which the runtime
    /// evaluates via the pure expression evaluator. Zero IR drift for existing
    /// programs.
    pub cond: Option<Expr>,
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
    /// §Fase 70.f — the parsed expression form of the value, present only when
    /// `value_kind == "expression"` (`let total = price * qty + tax`). The
    /// runtime evaluates it via the pure expression evaluator instead of the
    /// pre-§70 behaviour (which treated an expression as an opaque literal
    /// string). `None` for literal / reference / list values (byte-identical to
    /// pre-§70.f).
    pub value_ast: Option<Expr>,
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
/// §Fase 86 — `forge <Name>(seed: <string>) -> <Type> { mode:, novelty:,
/// depth:, branches:, constraints: }` — Directed Creative Synthesis. A
/// flow-body block that runs the Poincaré-Hadamard four-phase creative process
/// (Preparation → Incubation → Illumination → Verification) under a **measured,
/// fail-closed novelty guarantee** (D86.4/D86.6): the returned typed value must
/// clear a Normalized-Compression-Distance novelty floor against the obvious
/// baseline AND its `constraints:` anchor, or the forge fails structurally.
///
/// Before §86 this was a no-op stub (`{ loc }` only, body discarded). §86 makes
/// the README's long-standing claim true.
#[derive(Debug, Default)]
pub struct ForgeBlock {
    /// The synthesis name (`forge Artwork(...)` → `"Artwork"`).
    pub name: String,
    /// The creative seed — the conceptual starting point (`seed: "..."`).
    pub seed: String,
    /// The declared output type (`-> Visual` → `"Visual"`).
    pub output_type: String,
    /// Boden creativity mode (closed catalog: `combinatorial | exploratory |
    /// transformational`, `axon-T868`). Empty ⇒ defaults to `exploratory`.
    pub mode: String,
    /// Novelty target `[0.0, 1.0]` (`axon-T869`) — sets the fail-closed novelty
    /// floor and blends the incubation temperature. Default 0.5.
    pub novelty: f64,
    /// Incubation iterations (`depth ≥ 1`, `axon-T870`). Default 1.
    pub depth: i64,
    /// Illumination parallel branches (best-of-N, `branches ≥ 1`, `axon-T870`).
    /// Default 1.
    pub branches: i64,
    /// Optional `constraints:` reference to a declared `anchor` (`axon-T871`) —
    /// the verification predicate + coherence floor. Empty ⇒ novelty-floor-only
    /// verification.
    pub constraints_ref: String,
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
    /// §Fase 76.d — optional `aggregate:` clause: a member of the CLOSED
    /// catalog `count` | `sum(<col>)` | `avg(<col>)` | `min(<col>)` |
    /// `max(<col>)`. Empty = a plain `SELECT *` retrieve. Raw string,
    /// parsed + validated by the runtime (`filter::parse_aggregate_clause`)
    /// and at `axon check` (§76.d `axon-T843`/`T844`/`T845`).
    pub aggregate: String,
    /// §Fase 76.d — optional `group_by:` clause: a comma-separated list
    /// of column identifiers (same discipline as `order_by:` columns).
    /// Requires an `aggregate:`. Empty = no grouping.
    pub group_by: String,
    /// §Fase 85.b — optional `cache:` reference. A `retrieve` reads a store
    /// (a `storage` effect — never `pure`), so caching it is always a WIDENING
    /// that accepts staleness: the named `cache` MUST carry a finite `ttl:`
    /// (`axon-T865`) and typically an `invalidate_on:`. Names a declared
    /// `cache` (`axon-T864`); empty = uncached. Never governed by a
    /// `default: true` policy (defaults only auto-cover provably-`pure` tools).
    pub cache: String,
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

/// §Fase 88.a — `scope <Name> { targets:, depth:, approver: }` — the
/// authorization scope a `warden` block runs `within`. The load-bearing safety
/// construct (paper §5.2): it declares which resources may be analysed
/// (`targets` allowlist), how invasively (`depth` ceiling), and who authorised
/// it (`approver` capability). A `warden` with no resolvable in-scope
/// authorization does not compile (fail-closed). Named + referenced, like
/// `cache`/`cors`. **Unknown fields are a hard parse error** (D83.7): a scope
/// governs an offensive-capable analysis, so a typo can never silently widen it.
#[derive(Debug, Default)]
pub struct ScopeDefinition {
    pub name: String,
    /// `targets: [ "<resource>", … ]` — the allowlist of resources the operator
    /// owns/controls and authorises for analysis. Required + non-empty (§88.c
    /// `axon-T88x`); a target outside this list is a typed rejection.
    pub targets: Vec<String>,
    /// `depth: static_artifact | memory_dump | live_network` — the MOST invasive
    /// analysis depth this scope permits (the ceiling). Closed catalog, ordered
    /// least→most invasive; empty ⇒ the safest default `static_artifact` (§88.c).
    pub depth: String,
    /// `approver: [requires] "<capability>"` — the capability whose holder
    /// authorised this scope (segregation of duties, the `mandate` §21 model).
    /// Required (§88.c).
    pub approver: String,
    pub loc: Loc,
    /// Fase 14.b — leading comment trivia.
    pub leading_trivia: Vec<crate::tokens::Trivia>,
    /// Fase 14.b — trailing comment trivia.
    pub trailing_trivia: Vec<crate::tokens::Trivia>,
}

/// §Fase 88.a — the `warden(<target>) within <Scope> { … }` adversarial
/// security-analysis block. A flow-body block (like `quant`): it audits a
/// `target` under a paraconsistent adversarial framing, emitting attested
/// `Vulnerability` findings — but ONLY `within` a signed authorization `scope`.
/// §88.a ships the SURFACE only; scope resolution + the depth/witness discipline
/// is §88.c, and the real analysis engine is §88.d/f (enterprise).
#[derive(Debug, Default)]
pub struct WardenBlock {
    /// `warden(<target>)` — a reference to the resource under analysis (a
    /// let-bound value / declared target). §88.c checks it is within the scope's
    /// `targets` allowlist.
    pub target: String,
    /// `within <Scope>` — the MANDATORY authorization scope reference. Empty is a
    /// hard error (§88.c `axon-T88x`, fail-closed): no scope ⇒ no analysis.
    pub scope_ref: String,
    /// The nested flow-body statements (`find_exploits()`, `fortify`, `emit`),
    /// parsed like `par`/`quant` branches so §88.c can walk them.
    pub body: Vec<FlowStep>,
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
    /// §Fase 69.c — `reupload:` L, the number of DATA RE-UPLOADING layers. `None`
    /// or `1` = no re-uploading (the data enters once → a quadratic form, provably
    /// classical for amplitude+Pauli, §69.b). `L ≥ 2` interleaves the data
    /// encoding with entangling layers L times — the ONLY provable escape from the
    /// quadratic bound (Havlíček-style; canonical with `encoding: angle`). The
    /// resulting kernel must still pass an Advantage Witness to be deployed
    /// claiming advantage (§69.a/b).
    pub reupload: Option<i64>,
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
