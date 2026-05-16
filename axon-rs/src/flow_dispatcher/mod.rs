//! §Fase 33.y.b — Per-IRFlowNode async dispatcher skeleton.
//!
//! This module ships the **structural foundation** of the Fase 33.y
//! universal-algebraic-streaming cycle: a closed-catalog, compiler-
//! enforced exhaustive dispatch table over the 45-variant
//! [`crate::ir_nodes::IRFlowNode`] enum. Each arm in
//! [`dispatch_node`]'s match is named explicitly; adding a 46th
//! IRFlowNode variant fails the Rust build at this match until the
//! corresponding dispatcher arm is added (D1 totality invariant).
//!
//! # What 33.y.b ships
//!
//! - [`DispatchCtx`] — the shared per-flow context every per-variant
//!   handler reads + writes. Carries the FlowExecutionEvent producer,
//!   the cancellation flag, the side-channels for enforcement summary
//!   / step audit / runtime warnings, the orchestration `branch_path`
//!   (for D6 per-step replay binding under Par/ForIn/Conditional
//!   nesting), and the per-step counter.
//! - [`NodeOutcome`] — closed catalog of dispatcher outcomes. In
//!   33.y.b only the transitional [`NodeOutcome::LegacyShimHandled`]
//!   variant exists; subsequent sub-fases 33.y.c–j add real outcomes
//!   (`Completed`, `Break`, `LoopContinue`, `Return`, etc.) and
//!   33.y.l removes `LegacyShimHandled` once every variant has its
//!   real handler.
//! - [`DispatchError`] — closed catalog of dispatch errors. Five
//!   variants today: BackendError / UpstreamCancelled /
//!   LegacyShimFailed / MissingDependency / ChannelClosed.
//! - [`ShimReason`] — per-IRFlowNode-variant tag for the 33.y.b
//!   transitional shim. The drift gate
//!   [`tests::shim_reason_covers_full_ir_flow_node_catalog`]
//!   asserts the ShimReason set has 1-to-1 cardinality with the
//!   IRFlowNode set.
//! - [`dispatch_node`] — the dispatcher entry point. Exhaustive
//!   match over 45 arms; each arm delegates to [`legacy_shim`] which
//!   returns `Ok(NodeOutcome::LegacyShimHandled)`. **No node is
//!   actually executed in 33.y.b.** The module is standalone — not
//!   wired into `server_execute_streaming` — so production behavior
//!   is byte-identical with v1.25.0 (D4).
//!
//! # What 33.y.b does NOT ship
//!
//! - Real per-variant async logic (lands per sub-fase 33.y.c–j).
//! - Integration with `server_execute_streaming` (lands incrementally
//!   per sub-fase as each variant comes online).
//! - Wire-format extensions (per-step `wire_status`, `branch_path`
//!   field on `StepAuditRecord`, `axon-W003 partial-streaming-
//!   activation` warning — all land in 33.y.c–l).
//!
//! # D-letter anchors
//!
//! - **D1** — Per-IRFlowNode async dispatch is total. The exhaustive
//!   match below is the compiler-enforced totality witness.
//! - **D4** — Wire byte-compat preserved. No production code path
//!   calls `dispatch_node` in 33.y.b; the module exists to lock the
//!   shape that subsequent sub-fases extend.
//! - **D7** — Production-grade per-variant handler discipline. The
//!   shim is INTENTIONALLY a no-op transition — not an
//!   `unimplemented!()` panic, not a `todo!()`, not a `_ =>` catch-all.
//!   Each arm is named; each shim invocation tags its IR variant
//!   precisely. The shim is structural plumbing, not a stub.

use crate::cancel_token::CancellationFlag;
use crate::flow_execution_event::FlowExecutionEvent;
use crate::ir_nodes::IRFlowNode;
use crate::stream_effect::BackpressurePolicy;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};

/// §Fase 33.y.c — Pure-shape variant handlers (Step / Probe / Reason /
/// Validate / Refine / Weave). All 6 variants reduce to "produce a
/// single LLM response from a prompt + cognitive framing"; the module
/// houses the shared async core (`run_pure_shape`) + 6 thin
/// per-variant entry points that build the variant's framing.
pub mod pure_shape;

/// §Fase 33.y.d — Orchestration variant handlers (Let / Conditional /
/// ForIn / Break / Continue / Return). 6 variants — control-flow
/// constructs that compose child handlers via recursive
/// `dispatch_node` calls + sentinel-driven loop semantics +
/// `branch_path` segments threading the orchestration tree.
pub mod orchestration;

/// §Fase 33.y.e — Parallel variant handler (`Par`) + public helper
/// [`parallel::run_branches_concurrently`] for concurrent dispatch
/// via `futures::future::join_all` with per-branch DispatchCtx
/// clones + post-join step_counter merge + Return-sentinel
/// propagation. `IRParallelBlock` is payload-free in v1.25.0; the
/// handler emits the `step_type: "par"` wire shape with zero
/// token events. Future IR extensions wire branches into the
/// public helper.
pub mod parallel;

/// §Fase 33.y.e — Stream variant handler (`Stream`) + public bridge
/// [`effects_bridge::bridge_effect_stream_yield`] integrating the
/// Fase 23 algebraic-effects runtime: scans the instruction block
/// for `perform Stream.Yield x` (statically + via trace), runs the
/// `EffectRuntime`, and emits one `axon.token` per Yield with the
/// resolved value. `IRStreamBlock` is payload-free in v1.25.0; the
/// handler emits the `step_type: "stream"` wire shape with zero
/// token events. Future IR extensions wire instruction blocks into
/// the public bridge.
pub mod effects_bridge;

/// §Fase 33.y.f — Cognitive primitives (Fase 11 neuro-symbolic).
/// 10 variants: `Remember` / `Recall` are PEM-bound (write-through
/// + read-back via the optional [`DispatchCtx::pem_backend`]);
/// `Forge` is payload-free wire shape (canonical
/// `step_type: "forge"`); `Focus` / `Associate` / `Aggregate` /
/// `Explore` / `Ingest` / `Navigate` / `Corroborate` reuse the
/// pure-shape async core ([`pure_shape::run_pure_shape`]) with
/// each variant's cognitive framing addendum reflected in the
/// system prompt.
pub mod cognitive;

/// §Fase 33.y.g — Algebraic-effect handler nodes.
/// 6 variants: `ShieldApply` / `OtsApply` / `MandateApply` — apply
/// a named capability to a target with structured output binding;
/// `ComputeApply` — invoke a compute capability with positional
/// arguments; `Listen` — wait on a Fase 13 typed channel for an
/// event; `DaemonStep` — invoke a Fase 16 daemon supervisor by
/// reference. Each handler emits wire shape with the canonical
/// `step_type` slug + public `apply_*` helpers that enterprise
/// integrations override (per the OSS/ENTERPRISE/SPLIT charter
/// — the shield/OTS/mandate scanner registries live in
/// `axon_enterprise.shield`).
pub mod algebraic_handlers;

/// §Fase 33.y.h — Wire-integration handler nodes (π-calc +
/// persistence + multi-agent deliberation). 10 variants:
/// **Emit / Publish / Discover** (Fase 13 typed channels — π-calc
/// output prefix + capability extrusion + dual discovery);
/// **Persist / Retrieve / Mutate / Purge / Transact** (persistence
/// primitives — snapshot / load / update / delete / transactional
/// block); **Deliberate / Consensus** (multi-agent payload-free
/// blocks). Each ships wire shape + public helper that enterprise
/// integrations (Postgres / Redis / MQ / typed-channel runtime)
/// override.
pub mod wire_integrations;

/// §Fase 33.y.i — PIX variants (paper §6 hidden-state primitives).
/// 3 variants: **Hibernate** (CPS-style event-await with timeout
/// — Fase 11.e + Fase 16 supervisor); **Drill** (PIX subtree
/// navigation); **Trail** (breadcrumb walk over a prior
/// navigation). OSS reference impl uses `__pix_*` /
/// `__hibernating_*` namespaced let_bindings keys; enterprise R&D
/// (axon_enterprise.cognitive_states + .supervisor) wires real
/// continuation-passing semantics + PIX state machines.
pub mod pix;

/// §Fase 33.y.j — Lambda + UseTool (the final 2 variants).
/// **LambdaDataApply** — Fase 15 ΛD apply (the sync runner walks
/// a CPS dispatcher mapping lambda data structures to expressions;
/// 33.y.j ships the OSS wire shape + helper). **UseTool** —
/// mid-step tool invocation (Fase 22 backend tools; the
/// `ChatRequest.tools` cross-cutting plumb-through lands in
/// 33.y.k D8). Completes the 45-variant total coverage.
pub mod lambda_tools;

/// §Fase 34.g — Unified stream handler (4-disjunction convergence).
/// Pre-34.g the four streaming-effect disjunctions (LLM-side
/// `output: Stream<T>`, `apply: <stream-tool>`, `use_tool` syntax,
/// `perform Stream.Yield`) had divergent drain paths — disjunct (a)
/// enforced `BackpressurePolicy` at chunk granularity while (b)/(d)
/// only captured the policy slug in audit without enforcement. This
/// module ships [`unified_stream::unified_stream_handler`] — the
/// single drain loop that ALL `Stream<ToolChunk>`-producing
/// disjunctions route through; the handler integrates a
/// [`crate::stream_runtime::Stream<ToolChunk>`] policy primitive +
/// returns a [`unified_stream::ToolStreamSummary`] with real
/// `chunks_dropped`/`chunks_degraded` counters. Also ships the
/// [`unified_stream::chat_chunk_to_tool_chunk`] type-bridge for
/// disjunct (a) symmetry tests + [`unified_stream::unified_stream_from_chunks`]
/// adapter for disjunct (d)'s static-scan output.
pub mod unified_stream;

// ────────────────────────────────────────────────────────────────────
//  DispatchCtx — shared per-flow async surface
// ────────────────────────────────────────────────────────────────────

/// Per-flow dispatcher context. Carries the producer-side wire
/// surface (`tx` for FlowExecutionEvent), cancel-in-body propagation
/// (`cancel`), the audit/enforcement/warning side-channels (read by
/// the SSE handler at `axon.complete` time), and the orchestration
/// `branch_path` for D6 per-step replay binding.
///
/// # `branch_path` semantics
///
/// Empty at flow root. Parent handlers push a segment when descending
/// into a child:
/// - `par[0]`, `par[1]`, `par[2]` for the n-th branch of a Par block.
/// - `for_in[0]`, `for_in[1]` for the n-th iteration of a ForIn loop.
/// - `conditional.then`, `conditional.else` for the chosen branch
///   of an `if`.
/// - Children inside a branch concat: `par[0].step[0]` for the first
///   child step of the first Par branch.
///
/// The path is observable in `StepAuditRecord.branch_path` (extended
/// in 33.y.f when the audit row writer gains the field) so regulators
/// replaying a flow on appeal see the full execution tree, not just a
/// flattened step sequence.
///
/// # `step_counter`
///
/// Monotonic per-flow counter. Each Step (or pure-shape variant
/// promoted to Step) increments. Surface fed into `step_audit` so
/// the row index is correct under nested orchestration.
#[derive(Clone)]
pub struct DispatchCtx {
    pub flow_name: String,
    pub backend_name: String,
    pub system_prompt: String,
    pub cancel: CancellationFlag,
    pub tx: mpsc::UnboundedSender<FlowExecutionEvent>,
    pub enforcement_summaries: Arc<
        Mutex<HashMap<String, crate::axon_server::EnforcementSummaryWire>>,
    >,
    pub step_audit_records: Arc<
        Mutex<Vec<crate::axonendpoint_replay::StepAuditRecord>>,
    >,
    pub runtime_warnings: Arc<
        Mutex<Vec<crate::runtime_warnings::RuntimeWarning>>,
    >,
    pub branch_path: Vec<String>,
    pub step_counter: usize,
    /// §Fase 33.y.f — Optional PEM async surface for cognitive
    /// primitives (Remember / Recall etc.). When `Some(backend)`,
    /// `run_remember` write-through persists to PEM and `run_recall`
    /// restores from PEM as a write-back cache layered over
    /// `let_bindings`. When `None`, both handlers degrade to
    /// `let_bindings`-only (in-memory) — the canonical adopter
    /// path for tests + adopters that don't opt into persistent
    /// cognitive state. Arc-cloned per branch for concurrent
    /// dispatch (Fase 33.y.e parity).
    pub pem_backend: Option<std::sync::Arc<dyn crate::pem::PersistenceBackend>>,
    /// §Fase 33.y.f — Session anchor for PEM persistence. Defaults
    /// to `flow_name` in [`DispatchCtx::new`]; adopters override
    /// for multi-session flows.
    pub session_id: String,
    /// §Fase 33.y.f — Tenant routing tag for PEM persistence.
    /// Defaults to empty in [`DispatchCtx::new`]; multi-tenant
    /// adopters set this before dispatch.
    pub tenant_id: String,
    /// §Fase 33.y.d — Let-binding scope. Map from binding name to its
    /// resolved value. `run_let` inserts; `run_conditional` reads to
    /// evaluate the condition; `run_for_in` inserts the iteration
    /// variable per iter. Bindings persist through the flow's
    /// lifetime — sub-scoping is NOT introduced in 33.y.d (the
    /// sync runner's let semantics are flow-scoped + monotonic,
    /// matching this discipline for D10 parity). The `HashMap` is
    /// cheap to clone for branch isolation when sub-fases 33.y.e
    /// introduce parallel branches with private scopes (Par block).
    pub let_bindings: std::collections::HashMap<String, String>,
    /// §Fase 33.y.c — Per-node declared `<stream:<policy>>` resolved
    /// by the caller BEFORE invoking `dispatch_node`. The pure-shape
    /// handlers read + consume this field (set back to `None` on
    /// entry) so each handler observes the policy intended for ITS
    /// node, never the previous node's residue. When `None`, the
    /// handler skips `StreamPolicyEnforcer` wrapping + emits chunks
    /// directly to the wire.
    ///
    /// Subsequent sub-fases 33.y.d-l adopt the same pattern for
    /// orchestration handlers (`Par` / `ForIn`) when child nodes
    /// declare effects.
    pub pending_effect_policy: Option<BackpressurePolicy>,
    /// §Fase 34.d (v1.29.0) — Tool registry surface for the
    /// streaming-tool dispatcher branch. When `Some(registry)`,
    /// `pure_shape::run_step` resolves `step.apply_ref` against
    /// the registry; if the entry's `is_streaming` flag is true,
    /// the step bypasses `Backend::stream()` entirely + invokes
    /// `tool.stream(args, ctx)` via the
    /// [`crate::tool_dispatch_bridge::resolve_streaming_tool`]
    /// factory. When `None` (D9 backwards-compat), the legacy
    /// LLM-side path is taken regardless of source-declared
    /// `effects: <stream:<policy>>` — adopters who haven't wired
    /// the registry yet see no behavior change. Arc-shared for
    /// concurrent dispatch (Fase 33.y.e parity).
    pub tool_registry: Option<std::sync::Arc<crate::tool_registry::ToolRegistry>>,
    /// §Fase 35.f (v1.30.0) — axonstore registry for SQL-vs-KV
    /// dispatch. When `Some(registry)`, `run_persist` / `run_retrieve`
    /// / `run_mutate` / `run_purge` resolve `store_name` against it: a
    /// `postgresql`-backed store routes through `PostgresStoreBackend`,
    /// every other (and every undeclared) store takes the byte-
    /// identical key-value path. When `None` (the `DispatchCtx::new`
    /// default), every store op is key-value — the pre-35 behavior,
    /// unchanged (D3). Arc-shared so concurrent branches share one
    /// per-DSN pool cache.
    pub store_registry: Option<std::sync::Arc<crate::store::registry::StoreRegistry>>,
    /// §Fase 35.j (v1.30.0) — Pillar IV: the capability slugs the
    /// current request carries (the JWT bearer's `capabilities`
    /// claim). When `Some`, the store handlers re-check a
    /// capability-gated store against this set before any access —
    /// defense-in-depth behind the type-checker's compile-time
    /// guarantee. When `None` (the `DispatchCtx::new` default), there
    /// is no capability context at this layer and the runtime
    /// re-check is a no-op: the compile-time check + the endpoint's
    /// Fase 32.g `requires:` gate stand.
    pub held_capabilities: Option<Vec<String>>,
}

impl DispatchCtx {
    /// Construct a fresh context for a new flow. Subsequent sub-fases
    /// extend this with builder methods as the surface grows (PEM /
    /// ReplayToken / CognitiveState plumbing in 33.y.f, tool registry
    /// in 33.y.k, etc.).
    pub fn new(
        flow_name: impl Into<String>,
        backend_name: impl Into<String>,
        system_prompt: impl Into<String>,
        cancel: CancellationFlag,
        tx: mpsc::UnboundedSender<FlowExecutionEvent>,
    ) -> Self {
        let flow_name = flow_name.into();
        let session_id = flow_name.clone();
        Self {
            flow_name,
            backend_name: backend_name.into(),
            system_prompt: system_prompt.into(),
            cancel,
            tx,
            enforcement_summaries: Arc::new(Mutex::new(HashMap::new())),
            step_audit_records: Arc::new(Mutex::new(Vec::new())),
            runtime_warnings: Arc::new(Mutex::new(Vec::new())),
            branch_path: Vec::new(),
            step_counter: 0,
            pem_backend: None,
            session_id,
            tenant_id: String::new(),
            let_bindings: std::collections::HashMap::new(),
            pending_effect_policy: None,
            tool_registry: None,
            store_registry: None,
            held_capabilities: None,
        }
    }

    /// §Fase 35.f — Builder: attach the `axonstore` registry so the
    /// wire-integration store handlers route postgresql-backed stores
    /// to SQL. Without it, every store op stays key-value (D3).
    /// Returns `self` so builders chain.
    pub fn with_store_registry(
        mut self,
        registry: std::sync::Arc<crate::store::registry::StoreRegistry>,
    ) -> Self {
        self.store_registry = Some(registry);
        self
    }

    /// §Fase 35.j — Builder: attach the request's held capability
    /// slugs so the store handlers re-check capability-gated stores
    /// (Pillar IV). Returns `self` so builders chain.
    pub fn with_held_capabilities(mut self, capabilities: Vec<String>) -> Self {
        self.held_capabilities = Some(capabilities);
        self
    }

    /// §Fase 34.d — Builder: attach a tool registry so the
    /// dispatcher's streaming-tool branch can resolve `apply_ref`
    /// against it. Returns `self` so builders chain.
    pub fn with_tool_registry(
        mut self,
        registry: std::sync::Arc<crate::tool_registry::ToolRegistry>,
    ) -> Self {
        self.tool_registry = Some(registry);
        self
    }

    /// Builder: attach a PEM persistence backend. Returns `self` so
    /// callers can chain `DispatchCtx::new(...).with_pem(backend)`.
    pub fn with_pem(
        mut self,
        backend: std::sync::Arc<dyn crate::pem::PersistenceBackend>,
    ) -> Self {
        self.pem_backend = Some(backend);
        self
    }

    /// Builder: set the session id (defaults to flow_name).
    pub fn with_session_id(mut self, session_id: impl Into<String>) -> Self {
        self.session_id = session_id.into();
        self
    }

    /// Builder: set the tenant id (defaults to empty).
    pub fn with_tenant_id(mut self, tenant_id: impl Into<String>) -> Self {
        self.tenant_id = tenant_id.into();
        self
    }

    /// Builder-style setter for the pending effect policy. Returns
    /// `self` so callers can chain `ctx.with_effect_policy(policy)`
    /// before invoking `dispatch_node`. Handlers read + clear the
    /// field via [`Self::take_pending_effect_policy`].
    pub fn with_effect_policy(mut self, policy: BackpressurePolicy) -> Self {
        self.pending_effect_policy = Some(policy);
        self
    }

    /// §Fase 33.z.c — Builder: inject external Arc-backed side-channels
    /// so the dispatcher's per-variant handlers populate the SAME
    /// Mutexes that `server_execute_streaming` reads from for the SSE
    /// wire's `enforcement_summary`, `step_audit`, and `runtime_warnings`
    /// fields.
    ///
    /// Without this builder, `DispatchCtx::new` creates FRESH Arcs that
    /// the dispatcher populates but the production hot path can't read.
    /// That gap broke `axon.complete.enforcement_summary` wire emission
    /// on the canonical Step shape when the dispatcher graft (33.z.b)
    /// activated — the 33.x.d production-path tests detected the
    /// regression at the `assert_eq!(generate_summary["chunks_pushed"], 1)`
    /// line because the side-channel the wire reads from stayed empty
    /// while the dispatcher's fresh Arc carried the counters.
    ///
    /// Used exclusively by `streaming_via_dispatcher::run_streaming_via_dispatcher`
    /// to thread the side-channels the SSE handler constructs into the
    /// dispatcher. Downstream-crate consumers driving `dispatch_node`
    /// directly continue to use `DispatchCtx::new` + the fresh internal
    /// Arcs.
    pub fn with_external_side_channels(
        mut self,
        enforcement_summaries: std::sync::Arc<
            tokio::sync::Mutex<
                std::collections::HashMap<String, crate::axon_server::EnforcementSummaryWire>,
            >,
        >,
        step_audit_records: std::sync::Arc<
            tokio::sync::Mutex<Vec<crate::axonendpoint_replay::StepAuditRecord>>,
        >,
        runtime_warnings: std::sync::Arc<
            tokio::sync::Mutex<Vec<crate::runtime_warnings::RuntimeWarning>>,
        >,
    ) -> Self {
        self.enforcement_summaries = enforcement_summaries;
        self.step_audit_records = step_audit_records;
        self.runtime_warnings = runtime_warnings;
        self
    }

    /// Read + clear the pending effect policy. Returns `None` when no
    /// policy was set by the caller. The take-semantics (vs. peek)
    /// prevents a stale policy from a previous node leaking into the
    /// next handler's invocation if the caller forgets to clear.
    pub fn take_pending_effect_policy(&mut self) -> Option<BackpressurePolicy> {
        self.pending_effect_policy.take()
    }

    /// Render the current `branch_path` as a wire-stable string. Empty
    /// path returns `""` (flow root); single segment `"par[0]"`; multi
    /// `"par[0].step[1]"`. The format is byte-stable across calls.
    pub fn branch_path_string(&self) -> String {
        self.branch_path.join(".")
    }
}

// ────────────────────────────────────────────────────────────────────
//  NodeOutcome — closed catalog of dispatcher outcomes
// ────────────────────────────────────────────────────────────────────

/// Closed catalog of dispatcher outcomes. 33.y.b ships only the
/// transitional [`LegacyShimHandled`] variant; subsequent sub-fases
/// 33.y.c–j add real outcomes:
///
/// - `Completed { output, tokens_emitted }` — handler ran to
///   completion; output captured + tokens forwarded on the wire.
/// - `Break` — sentinel from an in-loop `break`. The For-In handler
///   short-circuits remaining iterations + propagates up.
/// - `LoopContinue` — sentinel from `continue`. Skips to next
///   iteration.
/// - `Return { value }` — sentinel from `return`. Flow loop
///   terminates.
///
/// 33.y.l removes [`LegacyShimHandled`] once every variant has its
/// real handler.
///
/// # Why a closed catalog vs `Result<String, _>`
///
/// Sentinel values (Break / LoopContinue / Return) need to flow up
/// through nested handler stacks WITHOUT being mistaken for content.
/// A `Result<String, _>` would force the caller to encode sentinels
/// in-band, which is unsound under serde + adopter-observable output.
/// The closed enum is the only sound algebraic representation.
#[derive(Debug, Clone)]
#[non_exhaustive]
pub enum NodeOutcome {
    /// §Fase 33.y.c+ — Handler ran to completion. `output` is the
    /// concatenated chunk content captured during streaming;
    /// `tokens_emitted` is the count of non-empty `StepToken` events
    /// fanned to the wire (post-policy enforcement for steps with a
    /// declared `<stream:<policy>>`). The `step_index` is the value
    /// of `ctx.step_counter` at the moment the handler started (i.e.
    /// the index the handler reserved for itself before
    /// incrementing); orchestration handlers in 33.y.d–e use this
    /// to surface per-branch index trails on `branch_path`.
    Completed {
        output: String,
        tokens_emitted: u64,
        step_index: usize,
    },
    /// §Fase 33.y.d sentinel — emitted by the `Break` handler. The
    /// enclosing `ForIn` handler observes this outcome from its
    /// child dispatch + terminates the loop (skips remaining
    /// iterations). Parser scope check guarantees `Break` only
    /// appears inside a `ForIn` body, so non-loop ancestors that
    /// observe this outcome MUST propagate it upward unchanged.
    Break,
    /// §Fase 33.y.d sentinel — emitted by the `Continue` handler.
    /// The enclosing `ForIn` handler observes this + skips to the
    /// next iteration. Same propagation discipline as
    /// [`NodeOutcome::Break`].
    LoopContinue,
    /// §Fase 33.y.d sentinel — emitted by the `Return` handler.
    /// Terminates the flow loop with the carried `value` as the
    /// final flow output. Parents propagate unchanged until the
    /// flow-loop level observes it.
    Return { value: String },
}

// ────────────────────────────────────────────────────────────────────
//  DispatchError — closed catalog of dispatcher errors
// ────────────────────────────────────────────────────────────────────

/// Closed catalog of dispatcher errors. Adopter-reachable error
/// surfaces are NAMED (D7 mandate: zero `unwrap()` / zero
/// `unimplemented!()` / zero `_ =>` catch-all). Each variant carries
/// adopter-actionable structured data.
#[derive(Debug, Clone)]
#[non_exhaustive]
pub enum DispatchError {
    /// `Backend::stream()` failed on a per-variant handler that
    /// invoked it. Carries the backend name + the upstream error
    /// message so the SSE handler can surface a structured
    /// `axon.error` event.
    BackendError { name: String, message: String },

    /// Cancellation flag fired mid-dispatch (client disconnected or
    /// upstream `tokio::select!` raced the cancel branch). Caller
    /// MUST treat this as a clean exit (no `axon.error` event
    /// surfaced — the consumer is already gone).
    UpstreamCancelled,

    /// A per-variant handler needed a dependency that wasn't
    /// available on the DispatchCtx (e.g., PEM async surface for a
    /// `Remember`/`Recall` handler before 33.y.f wires it in). The
    /// `name` field tags which dependency.
    MissingDependency { name: &'static str },

    /// The mpsc sender returned `Err(_)` — consumer dropped. Caller
    /// MUST treat this as a clean exit (same posture as
    /// `UpstreamCancelled`).
    ChannelClosed,
}

impl std::fmt::Display for DispatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BackendError { name, message } => {
                write!(f, "backend '{name}' stream() failed: {message}")
            }
            Self::UpstreamCancelled => write!(f, "upstream cancelled mid-dispatch"),
            Self::MissingDependency { name } => {
                write!(f, "dispatcher missing dependency: {name}")
            }
            Self::ChannelClosed => write!(f, "channel closed (consumer dropped)"),
        }
    }
}

impl std::error::Error for DispatchError {}

// ────────────────────────────────────────────────────────────────────
//  §Fase 33.y.l — ShimReason enum + legacy_shim function retired
// ────────────────────────────────────────────────────────────────────
//
// After 33.y.j reached 45/45 IRFlowNode graduation, the
// transitional `ShimReason` enum + `legacy_shim` function + the
// `NodeOutcome::LegacyShimHandled` variant became structurally
// unreachable from `dispatch_node`'s exhaustive match. 33.y.l
// retires the entire shim infrastructure in this lockstep cleanup:
//
//   - ShimReason enum                   — DELETED
//   - ShimReason::ALL constant          — DELETED
//   - ShimReason::slug() method         — DELETED
//   - legacy_shim() async helper        — DELETED
//   - NodeOutcome::LegacyShimHandled    — DELETED variant
//
// Drift-gate slug catalog now uses `flow_plan::ir_flow_node_kind`
// directly (the same byte-stable surface that was duplicated in
// ShimReason::slug — single source of truth).
//
// The dispatcher's 45-arm exhaustive match is unchanged: every IR
// variant routes to its real async handler module (pure_shape /
// orchestration / parallel / effects_bridge / cognitive /
// algebraic_handlers / wire_integrations / pix / lambda_tools).
//
// Search the codebase: `grep -E "unimplemented|todo!|legacy_shim"
// axon-rs/src/flow_dispatcher/*.rs` returns ZERO matches post-33.y.l
// (verified by the `fase33y_l_parity_gate.rs::d7_no_legacy_markers`
// drift-gate test).
//
// Build-time guarantee: `legacy_shim` is gone → compiler enforces
// that NO future arm in dispatch_node can fall back to a stub. The
// catalog totality contract D1 is sealed.
// ────────────────────────────────────────────────────────────────────
//  dispatch_node — the exhaustive entry point
// ────────────────────────────────────────────────────────────────────

/// Dispatch a single IRFlowNode through the per-variant async
/// handler stack. Total over the 45-variant closed catalog
/// (compiler-enforced exhaustive match).
///
/// # 45/45 graduation FINAL (33.y.j)
///
/// As of Fase 33.y.j, every IRFlowNode variant has a NAMED async
/// handler. There are NO `_ =>` catch-all arms, NO `legacy_shim`
/// calls, NO `unimplemented!()` markers. Adding a 46th IRFlowNode
/// variant fails the Rust build here until a real per-variant
/// async handler is wired in.
///
/// Each arm's handler module:
///
/// - **pure_shape** (33.y.c) — Step / Probe / Reason / Validate /
///   Refine / Weave
/// - **orchestration** (33.y.d) — Let / Conditional / ForIn /
///   Break / Continue / Return
/// - **parallel** (33.y.e) — Par
/// - **effects_bridge** (33.y.e + D9) — Stream
/// - **cognitive** (33.y.f) — Remember / Recall / Forge / Focus /
///   Associate / Aggregate / Explore / Ingest / Navigate /
///   Corroborate
/// - **algebraic_handlers** (33.y.g) — ShieldApply / OtsApply /
///   MandateApply / ComputeApply / Listen / DaemonStep
/// - **wire_integrations** (33.y.h) — Emit / Publish / Discover /
///   Persist / Retrieve / Mutate / Purge / Transact / Deliberate /
///   Consensus
/// - **pix** (33.y.i) — Hibernate / Drill / Trail
/// - **lambda_tools** (33.y.j) — LambdaDataApply / UseTool
///
/// # Cancellation
///
/// Every per-variant handler checks `ctx.cancel.is_cancelled()`
/// at entry and at every `.await` boundary per the Fase 33.x.e
/// `cancel_aware` discipline. Cancel propagation is uniform
/// across the entire 45-variant catalog.
pub async fn dispatch_node(
    node: &IRFlowNode,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    // Exhaustive match — compiler enforces every variant has a
    // named arm. Adding a 46th IRFlowNode variant fails the build
    // here until the new arm is added. ZERO `_ =>` catch-all.
    match node {
        // §Fase 33.y.c — pure-shape variants graduated to real
        // async handlers. Each delegates to its labeled
        // `pure_shape::run_*` entry which wraps the shared
        // `pure_shape::run_pure_shape` async core. The shim is
        // retired for these 6 variants; subsequent sub-fases retire
        // it for the remaining 39 variants per the topological
        // schedule in `docs/fase_33y_algebraic_streaming_dispatcher.md`.
        IRFlowNode::Step(step) => pure_shape::run_step(step, ctx).await,
        IRFlowNode::Probe(probe) => pure_shape::run_probe(probe, ctx).await,
        IRFlowNode::Reason(reason) => pure_shape::run_reason(reason, ctx).await,
        IRFlowNode::Validate(validate) => pure_shape::run_validate(validate, ctx).await,
        IRFlowNode::Refine(refine) => pure_shape::run_refine(refine, ctx).await,
        IRFlowNode::Weave(weave) => pure_shape::run_weave(weave, ctx).await,
        // §Fase 33.y.j — UseTool graduated.
        IRFlowNode::UseTool(node) => lambda_tools::run_use_tool(node, ctx).await,
        // §Fase 33.y.f — cognitive primitives PEM-bound.
        IRFlowNode::Remember(node) => cognitive::run_remember(node, ctx).await,
        IRFlowNode::Recall(node) => cognitive::run_recall(node, ctx).await,
        // §Fase 33.y.d — orchestration variants graduated to real
        // async handlers. Each composes child handlers via recursive
        // `dispatch_node` calls + threads sentinel outcomes (Break /
        // LoopContinue / Return) up through orchestration parents.
        IRFlowNode::Conditional(cond) => orchestration::run_conditional(cond, ctx).await,
        IRFlowNode::ForIn(for_in) => orchestration::run_for_in(for_in, ctx).await,
        IRFlowNode::Let(let_bind) => orchestration::run_let(let_bind, ctx).await,
        IRFlowNode::Return(ret) => orchestration::run_return(ret, ctx).await,
        IRFlowNode::Break(brk) => orchestration::run_break(brk, ctx).await,
        IRFlowNode::Continue(cont) => orchestration::run_continue(cont, ctx).await,
        // §Fase 33.y.j — LambdaDataApply graduated.
        IRFlowNode::LambdaDataApply(node) => lambda_tools::run_lambda_data_apply(node, ctx).await,
        // §Fase 33.y.e — Par graduated to real async handler. The
        // payload-free `IRParallelBlock` emits the canonical
        // `step_type: "par"` wire shape; future IR extensions
        // delegate to `parallel::run_branches_concurrently`.
        IRFlowNode::Par(par) => parallel::run_par(par, ctx).await,
        // §Fase 33.y.i — PIX variants graduated.
        IRFlowNode::Hibernate(node) => pix::run_hibernate(node, ctx).await,
        // §Fase 33.y.h — multi-agent deliberation blocks.
        IRFlowNode::Deliberate(node) => wire_integrations::run_deliberate(node, ctx).await,
        IRFlowNode::Consensus(node) => wire_integrations::run_consensus(node, ctx).await,
        // §Fase 33.y.f — Forge payload-free wire shape.
        IRFlowNode::Forge(node) => cognitive::run_forge(node, ctx).await,
        // §Fase 33.y.f — cognitive framing handlers reuse pure_shape.
        IRFlowNode::Focus(node) => cognitive::run_focus(node, ctx).await,
        IRFlowNode::Associate(node) => cognitive::run_associate(node, ctx).await,
        IRFlowNode::Aggregate(node) => cognitive::run_aggregate(node, ctx).await,
        IRFlowNode::Explore(node) => cognitive::run_explore(node, ctx).await,
        IRFlowNode::Ingest(node) => cognitive::run_ingest(node, ctx).await,
        // §Fase 33.y.g — algebraic-effect handler nodes graduated.
        IRFlowNode::ShieldApply(node) => algebraic_handlers::run_shield_apply(node, ctx).await,
        // §Fase 33.y.e — Stream graduated to real async handler.
        // The payload-free `IRStreamBlock` emits the canonical
        // `step_type: "stream"` wire shape; future IR extensions
        // delegate to `effects_bridge::bridge_effect_stream_yield`.
        IRFlowNode::Stream(stream) => effects_bridge::run_stream(stream, ctx).await,
        IRFlowNode::Navigate(node) => cognitive::run_navigate(node, ctx).await,
        IRFlowNode::Drill(node) => pix::run_drill(node, ctx).await,
        IRFlowNode::Trail(node) => pix::run_trail(node, ctx).await,
        IRFlowNode::Corroborate(node) => cognitive::run_corroborate(node, ctx).await,
        IRFlowNode::OtsApply(node) => algebraic_handlers::run_ots_apply(node, ctx).await,
        IRFlowNode::MandateApply(node) => algebraic_handlers::run_mandate_apply(node, ctx).await,
        IRFlowNode::ComputeApply(node) => algebraic_handlers::run_compute_apply(node, ctx).await,
        IRFlowNode::Listen(node) => algebraic_handlers::run_listen(node, ctx).await,
        IRFlowNode::DaemonStep(node) => algebraic_handlers::run_daemon_step(node, ctx).await,
        // §Fase 33.y.h — π-calc typed channels (Fase 13).
        IRFlowNode::Emit(node) => wire_integrations::run_emit(node, ctx).await,
        IRFlowNode::Publish(node) => wire_integrations::run_publish(node, ctx).await,
        IRFlowNode::Discover(node) => wire_integrations::run_discover(node, ctx).await,
        // §Fase 33.y.h — persistence primitives.
        IRFlowNode::Persist(node) => wire_integrations::run_persist(node, ctx).await,
        IRFlowNode::Retrieve(node) => wire_integrations::run_retrieve(node, ctx).await,
        IRFlowNode::Mutate(node) => wire_integrations::run_mutate(node, ctx).await,
        IRFlowNode::Purge(node) => wire_integrations::run_purge(node, ctx).await,
        IRFlowNode::Transact(node) => wire_integrations::run_transact(node, ctx).await,
    }
}

// ────────────────────────────────────────────────────────────────────
//  Unit tests — drift gate + smoke
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cancel_token::CancellationFlag;

    /// §Fase 33.y.l drift-gate update — the historical
    /// `shim_reason_cardinality_45_variants` /
    /// `shim_reason_slugs_are_unique` /
    /// `shim_reason_slugs_are_well_formed` /
    /// `legacy_shim_returns_handled_on_happy_path` /
    /// `legacy_shim_returns_cancel_when_flag_set` /
    /// `shim_reason_slug_matches_ir_flow_node_kind` tests are
    /// RETIRED here. The replacement coverage lives in:
    ///
    ///   - `tests/fase33y_b_dispatcher_skeleton.rs` — IR-variant
    ///     catalog cardinality + slug uniqueness via
    ///     `flow_plan::ir_flow_node_kind` directly (single source
    ///     of truth, no more `ShimReason::slug` duplication).
    ///   - `tests/fase33y_l_parity_gate.rs` — D7 build-time grep
    ///     invariant: zero `unimplemented!` / `todo!` / `legacy_shim`
    ///     symbols in `flow_dispatcher/*.rs`.

    /// 33.y.b branch_path: empty at flow root.
    #[test]
    fn dispatch_ctx_branch_path_empty_at_root() {
        let (tx, _rx) = mpsc::unbounded_channel();
        let ctx = DispatchCtx::new(
            "F",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        );
        assert!(ctx.branch_path.is_empty());
        assert_eq!(ctx.branch_path_string(), "");
        assert_eq!(ctx.step_counter, 0);
    }

    /// 33.y.b branch_path: multi-segment join is wire-stable.
    #[test]
    fn dispatch_ctx_branch_path_joins_segments() {
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new(
            "F",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        );
        ctx.branch_path.push("par[0]".to_string());
        ctx.branch_path.push("step[1]".to_string());
        assert_eq!(ctx.branch_path_string(), "par[0].step[1]");
    }

    /// 33.y.b DispatchError Display surface produces actionable
    /// messages for every variant.
    #[test]
    fn dispatch_error_display_surface() {
        let cases: Vec<(DispatchError, &str)> = vec![
            (
                DispatchError::BackendError {
                    name: "anthropic".to_string(),
                    message: "rate limited".to_string(),
                },
                "backend 'anthropic' stream() failed: rate limited",
            ),
            (DispatchError::UpstreamCancelled, "upstream cancelled mid-dispatch"),
            (
                DispatchError::MissingDependency { name: "pem_async" },
                "dispatcher missing dependency: pem_async",
            ),
            (DispatchError::ChannelClosed, "channel closed (consumer dropped)"),
        ];
        for (err, expected) in cases {
            assert_eq!(format!("{err}"), expected);
        }
    }

    /// 33.y.c smoke: dispatch_node dispatches Step through the
    /// graduated pure-shape handler (not the shim) and returns
    /// `NodeOutcome::Completed` with the stub backend's canonical
    /// "(stub)" 1-token output.
    #[tokio::test]
    async fn dispatch_node_step_routes_to_pure_shape_handler() {
        use crate::ir_nodes::*;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "Generate".to_string(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".to_string(),
            use_tool: None,
            probe: None,
            reason: None,
            weave: None,
            output_type: String::new(),
            confidence_floor: None,
            navigate_ref: String::new(),
            apply_ref: String::new(),
            body: Vec::new(),
        };
        let node = IRFlowNode::Step(step);

        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new(
            "F",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        );

        let outcome = dispatch_node(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed {
                output,
                tokens_emitted,
                step_index,
            } => {
                assert_eq!(output, "(stub)");
                assert_eq!(tokens_emitted, 1);
                assert_eq!(step_index, 0);
            }
            other => panic!("post-33.y.c: Step routes to pure_shape handler returning Completed; got {other:?}"),
        }
    }
}
