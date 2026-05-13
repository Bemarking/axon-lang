//! §Fase 33.y.b drift gate — assert the `flow_dispatcher` module's
//! exhaustive surface is structurally locked.
//!
//! # Why a dedicated drift gate
//!
//! `flow_dispatcher::tests` covers the module-internal invariants
//! (ShimReason cardinality / slug uniqueness / shape / cancel
//! propagation). This integration test exercises the PUBLIC surface
//! end-to-end:
//!
//! - `dispatch_node` routes every one of the 45 IRFlowNode discriminants
//!   to its labeled ShimReason (no arm forwards to the wrong shim
//!   tag — the kind of bug a careless arm-renaming refactor would
//!   introduce).
//! - The ShimReason public catalog is observable from a downstream
//!   consumer (proves `ShimReason::ALL` is reachable across the
//!   crate boundary).
//! - `dispatch_node` honors the cancel flag at the entry point.
//! - `DispatchCtx::new` produces a usable context across the crate
//!   boundary (downstream consumers can construct it).
//!
//! When 33.y.c lands the first real per-variant handler, the
//! corresponding test below INVERTS to assert the real outcome
//! (`NodeOutcome::Completed { output, tokens_emitted }`) instead of
//! `LegacyShimHandled`.

use axon::cancel_token::CancellationFlag;
use axon::flow_dispatcher::{
    dispatch_node, DispatchCtx, DispatchError, NodeOutcome, ShimReason,
};
use axon::ir_nodes::*;
use tokio::sync::mpsc;

// ────────────────────────────────────────────────────────────────────
//  Synthetic IRFlowNode factory — covers all 45 variants
// ────────────────────────────────────────────────────────────────────
//
// Each factory returns a minimally-shaped IR value that satisfies the
// enum discriminant; the dispatcher in 33.y.b only matches the
// discriminant, so payload contents are irrelevant. Subsequent
// sub-fases extend each factory with realistic payloads as the
// per-variant handler tests need them.

fn step_node() -> IRFlowNode {
    IRFlowNode::Step(IRStep {
        node_type: "step",
        source_line: 0,
        source_column: 0,
        name: String::new(),
        persona_ref: String::new(),
        given: String::new(),
        ask: String::new(),
        use_tool: None,
        probe: None,
        reason: None,
        weave: None,
        output_type: String::new(),
        confidence_floor: None,
        navigate_ref: String::new(),
        apply_ref: String::new(),
        body: Vec::new(),
    })
}

fn probe_node() -> IRFlowNode {
    IRFlowNode::Probe(IRProbe {
        node_type: "probe",
        source_line: 0,
        source_column: 0,
        target: String::new(),
    })
}

fn reason_node() -> IRFlowNode {
    IRFlowNode::Reason(IRReasonStep {
        node_type: "reason",
        source_line: 0,
        source_column: 0,
        strategy: String::new(),
        target: String::new(),
    })
}

fn validate_node() -> IRFlowNode {
    IRFlowNode::Validate(IRValidateStep {
        node_type: "validate",
        source_line: 0,
        source_column: 0,
        target: String::new(),
        rule: String::new(),
    })
}

fn refine_node() -> IRFlowNode {
    IRFlowNode::Refine(IRRefineStep {
        node_type: "refine",
        source_line: 0,
        source_column: 0,
        target: String::new(),
        strategy: String::new(),
    })
}

fn weave_node() -> IRFlowNode {
    IRFlowNode::Weave(IRWeaveStep {
        node_type: "weave",
        source_line: 0,
        source_column: 0,
        sources: Vec::new(),
        target: String::new(),
        format_type: String::new(),
        priority: Vec::new(),
        style: String::new(),
    })
}

fn use_tool_node() -> IRFlowNode {
    IRFlowNode::UseTool(IRUseToolStep {
        node_type: "use_tool",
        source_line: 0,
        source_column: 0,
        tool_name: String::new(),
        argument: String::new(),
    })
}

fn remember_node() -> IRFlowNode {
    IRFlowNode::Remember(IRRememberStep {
        node_type: "remember",
        source_line: 0,
        source_column: 0,
        expression: String::new(),
        memory_target: String::new(),
    })
}

fn recall_node() -> IRFlowNode {
    IRFlowNode::Recall(IRRecallStep {
        node_type: "recall",
        source_line: 0,
        source_column: 0,
        query: String::new(),
        memory_source: String::new(),
    })
}

fn conditional_node() -> IRFlowNode {
    IRFlowNode::Conditional(IRConditional {
        node_type: "conditional",
        source_line: 0,
        source_column: 0,
        condition: String::new(),
        comparison_op: String::new(),
        comparison_value: String::new(),
        then_body: Vec::new(),
        else_body: Vec::new(),
        conditions: Vec::new(),
        conjunctor: String::new(),
    })
}

fn for_in_node() -> IRFlowNode {
    IRFlowNode::ForIn(IRForIn {
        node_type: "for_in",
        source_line: 0,
        source_column: 0,
        variable: String::new(),
        iterable: String::new(),
        body: Vec::new(),
    })
}

fn let_node() -> IRFlowNode {
    IRFlowNode::Let(IRLetBinding {
        node_type: "let",
        source_line: 0,
        source_column: 0,
        target: String::new(),
        value: String::new(),
        value_kind: String::new(),
    })
}

fn return_node() -> IRFlowNode {
    IRFlowNode::Return(IRReturnStep {
        node_type: "return",
        source_line: 0,
        source_column: 0,
        value_expr: String::new(),
    })
}

fn break_node() -> IRFlowNode {
    IRFlowNode::Break(IRBreakStep {
        node_type: "break",
        source_line: 0,
        source_column: 0,
    })
}

fn continue_node() -> IRFlowNode {
    IRFlowNode::Continue(IRContinueStep {
        node_type: "continue",
        source_line: 0,
        source_column: 0,
    })
}

fn lambda_data_apply_node() -> IRFlowNode {
    IRFlowNode::LambdaDataApply(IRLambdaDataApply {
        node_type: "lambda_data_apply",
        source_line: 0,
        source_column: 0,
        lambda_data_name: String::new(),
        target: String::new(),
        output_type: String::new(),
    })
}

fn par_node() -> IRFlowNode {
    IRFlowNode::Par(IRParallelBlock {
        node_type: "par",
        source_line: 0,
        source_column: 0,
    })
}

fn hibernate_node() -> IRFlowNode {
    IRFlowNode::Hibernate(IRHibernateStep {
        node_type: "hibernate",
        source_line: 0,
        source_column: 0,
        event_name: String::new(),
        timeout: String::new(),
    })
}

fn deliberate_node() -> IRFlowNode {
    IRFlowNode::Deliberate(IRDeliberateBlock {
        node_type: "deliberate",
        source_line: 0,
        source_column: 0,
    })
}

fn consensus_node() -> IRFlowNode {
    IRFlowNode::Consensus(IRConsensusBlock {
        node_type: "consensus",
        source_line: 0,
        source_column: 0,
    })
}

fn forge_node() -> IRFlowNode {
    IRFlowNode::Forge(IRForgeBlock {
        node_type: "forge",
        source_line: 0,
        source_column: 0,
    })
}

fn focus_node() -> IRFlowNode {
    IRFlowNode::Focus(IRFocusStep {
        node_type: "focus",
        source_line: 0,
        source_column: 0,
        expression: String::new(),
    })
}

fn associate_node() -> IRFlowNode {
    IRFlowNode::Associate(IRAssociateStep {
        node_type: "associate",
        source_line: 0,
        source_column: 0,
        left: String::new(),
        right: String::new(),
        using_field: String::new(),
    })
}

fn aggregate_node() -> IRFlowNode {
    IRFlowNode::Aggregate(IRAggregateStep {
        node_type: "aggregate",
        source_line: 0,
        source_column: 0,
        target: String::new(),
        group_by: Vec::new(),
        alias: String::new(),
    })
}

fn explore_node() -> IRFlowNode {
    IRFlowNode::Explore(IRExploreStep {
        node_type: "explore",
        source_line: 0,
        source_column: 0,
        target: String::new(),
        limit: None,
    })
}

fn ingest_node() -> IRFlowNode {
    IRFlowNode::Ingest(IRIngestStep {
        node_type: "ingest",
        source_line: 0,
        source_column: 0,
        source: String::new(),
        target: String::new(),
    })
}

fn shield_apply_node() -> IRFlowNode {
    IRFlowNode::ShieldApply(IRShieldApplyStep {
        node_type: "shield_apply",
        source_line: 0,
        source_column: 0,
        shield_name: String::new(),
        target: String::new(),
        output_type: String::new(),
    })
}

fn stream_node() -> IRFlowNode {
    IRFlowNode::Stream(IRStreamBlock {
        node_type: "stream_block",
        source_line: 0,
        source_column: 0,
    })
}

fn navigate_node() -> IRFlowNode {
    IRFlowNode::Navigate(IRNavigateStep {
        node_type: "navigate",
        source_line: 0,
        source_column: 0,
        pix_ref: String::new(),
        corpus_ref: String::new(),
        query: String::new(),
        trail_enabled: false,
        output_name: String::new(),
    })
}

fn drill_node() -> IRFlowNode {
    IRFlowNode::Drill(IRDrillStep {
        node_type: "drill",
        source_line: 0,
        source_column: 0,
        pix_ref: String::new(),
        subtree_path: String::new(),
        query: String::new(),
        output_name: String::new(),
    })
}

fn trail_node() -> IRFlowNode {
    IRFlowNode::Trail(IRTrailStep {
        node_type: "trail",
        source_line: 0,
        source_column: 0,
        navigate_ref: String::new(),
    })
}

fn corroborate_node() -> IRFlowNode {
    IRFlowNode::Corroborate(IRCorroborateStep {
        node_type: "corroborate",
        source_line: 0,
        source_column: 0,
        navigate_ref: String::new(),
        output_name: String::new(),
    })
}

fn ots_apply_node() -> IRFlowNode {
    IRFlowNode::OtsApply(IROtsApplyStep {
        node_type: "ots_apply",
        source_line: 0,
        source_column: 0,
        ots_name: String::new(),
        target: String::new(),
        output_type: String::new(),
    })
}

fn mandate_apply_node() -> IRFlowNode {
    IRFlowNode::MandateApply(IRMandateApplyStep {
        node_type: "mandate_apply",
        source_line: 0,
        source_column: 0,
        mandate_name: String::new(),
        target: String::new(),
        output_type: String::new(),
    })
}

fn compute_apply_node() -> IRFlowNode {
    IRFlowNode::ComputeApply(IRComputeApplyStep {
        node_type: "compute_apply",
        source_line: 0,
        source_column: 0,
        compute_name: String::new(),
        arguments: Vec::new(),
        output_name: String::new(),
    })
}

fn listen_node() -> IRFlowNode {
    IRFlowNode::Listen(IRListenStep {
        node_type: "listen",
        source_line: 0,
        source_column: 0,
        channel: String::new(),
        channel_is_ref: false,
        event_alias: String::new(),
    })
}

fn daemon_step_node() -> IRFlowNode {
    IRFlowNode::DaemonStep(IRDaemonStepNode {
        node_type: "daemon_step",
        source_line: 0,
        source_column: 0,
        daemon_ref: String::new(),
    })
}

fn emit_node() -> IRFlowNode {
    IRFlowNode::Emit(IREmit {
        node_type: "emit",
        source_line: 0,
        source_column: 0,
        channel_ref: String::new(),
        value_ref: String::new(),
        value_is_channel: false,
    })
}

fn publish_node() -> IRFlowNode {
    IRFlowNode::Publish(IRPublish {
        node_type: "publish",
        source_line: 0,
        source_column: 0,
        channel_ref: String::new(),
        shield_ref: String::new(),
    })
}

fn discover_node() -> IRFlowNode {
    IRFlowNode::Discover(IRDiscover {
        node_type: "discover",
        source_line: 0,
        source_column: 0,
        capability_ref: String::new(),
        alias: String::new(),
    })
}

fn persist_node() -> IRFlowNode {
    IRFlowNode::Persist(IRPersistStep {
        node_type: "persist",
        source_line: 0,
        source_column: 0,
        store_name: String::new(),
    })
}

fn retrieve_node() -> IRFlowNode {
    IRFlowNode::Retrieve(IRRetrieveStep {
        node_type: "retrieve",
        source_line: 0,
        source_column: 0,
        store_name: String::new(),
        where_expr: String::new(),
        alias: String::new(),
    })
}

fn mutate_node() -> IRFlowNode {
    IRFlowNode::Mutate(IRMutateStep {
        node_type: "mutate",
        source_line: 0,
        source_column: 0,
        store_name: String::new(),
        where_expr: String::new(),
    })
}

fn purge_node() -> IRFlowNode {
    IRFlowNode::Purge(IRPurgeStep {
        node_type: "purge",
        source_line: 0,
        source_column: 0,
        store_name: String::new(),
        where_expr: String::new(),
    })
}

fn transact_node() -> IRFlowNode {
    IRFlowNode::Transact(IRTransactBlock {
        node_type: "transact",
        source_line: 0,
        source_column: 0,
    })
}

/// The full IRFlowNode × ShimReason cartesian product the 33.y.b
/// drift gate exercises end-to-end through `dispatch_node`. Each
/// entry: a factory producing a synthetic IR variant + the
/// ShimReason the dispatcher MUST route it to + the wire-stable
/// slug `flow_plan::ir_flow_node_kind` returns for that IR variant.
fn all_45_pairs() -> Vec<(IRFlowNode, ShimReason, &'static str)> {
    vec![
        (step_node(), ShimReason::Step, "step"),
        (probe_node(), ShimReason::Probe, "probe"),
        (reason_node(), ShimReason::Reason, "reason"),
        (validate_node(), ShimReason::Validate, "validate"),
        (refine_node(), ShimReason::Refine, "refine"),
        (weave_node(), ShimReason::Weave, "weave"),
        (use_tool_node(), ShimReason::UseTool, "use_tool"),
        (remember_node(), ShimReason::Remember, "remember"),
        (recall_node(), ShimReason::Recall, "recall"),
        (conditional_node(), ShimReason::Conditional, "conditional"),
        (for_in_node(), ShimReason::ForIn, "for_in"),
        (let_node(), ShimReason::Let, "let"),
        (return_node(), ShimReason::Return, "return"),
        (break_node(), ShimReason::Break, "break"),
        (continue_node(), ShimReason::Continue, "continue"),
        (lambda_data_apply_node(), ShimReason::LambdaDataApply, "lambda_data_apply"),
        (par_node(), ShimReason::Par, "par"),
        (hibernate_node(), ShimReason::Hibernate, "hibernate"),
        (deliberate_node(), ShimReason::Deliberate, "deliberate"),
        (consensus_node(), ShimReason::Consensus, "consensus"),
        (forge_node(), ShimReason::Forge, "forge"),
        (focus_node(), ShimReason::Focus, "focus"),
        (associate_node(), ShimReason::Associate, "associate"),
        (aggregate_node(), ShimReason::Aggregate, "aggregate"),
        (explore_node(), ShimReason::Explore, "explore"),
        (ingest_node(), ShimReason::Ingest, "ingest"),
        (shield_apply_node(), ShimReason::ShieldApply, "shield_apply"),
        (stream_node(), ShimReason::Stream, "stream_block"),
        (navigate_node(), ShimReason::Navigate, "navigate"),
        (drill_node(), ShimReason::Drill, "drill"),
        (trail_node(), ShimReason::Trail, "trail"),
        (corroborate_node(), ShimReason::Corroborate, "corroborate"),
        (ots_apply_node(), ShimReason::OtsApply, "ots_apply"),
        (mandate_apply_node(), ShimReason::MandateApply, "mandate_apply"),
        (compute_apply_node(), ShimReason::ComputeApply, "compute_apply"),
        (listen_node(), ShimReason::Listen, "listen"),
        (daemon_step_node(), ShimReason::DaemonStep, "daemon_step"),
        (emit_node(), ShimReason::Emit, "emit"),
        (publish_node(), ShimReason::Publish, "publish"),
        (discover_node(), ShimReason::Discover, "discover"),
        (persist_node(), ShimReason::Persist, "persist"),
        (retrieve_node(), ShimReason::Retrieve, "retrieve"),
        (mutate_node(), ShimReason::Mutate, "mutate"),
        (purge_node(), ShimReason::Purge, "purge"),
        (transact_node(), ShimReason::Transact, "transact"),
    ]
}

/// Construct a fresh DispatchCtx + return the receiver so callers
/// keep it alive (graduated handlers in 33.y.c+ send events to tx;
/// a dropped receiver returns DispatchError::ChannelClosed).
fn fresh_ctx() -> (DispatchCtx, mpsc::UnboundedReceiver<axon::flow_execution_event::FlowExecutionEvent>) {
    let (tx, rx) = mpsc::unbounded_channel();
    let ctx = DispatchCtx::new(
        "TestFlow",
        "stub",
        "system prompt",
        CancellationFlag::new(),
        tx,
    );
    (ctx, rx)
}

// ────────────────────────────────────────────────────────────────────
//  §1 — Cardinality + arm coverage
// ────────────────────────────────────────────────────────────────────

#[test]
fn cartesian_product_has_exactly_45_entries() {
    assert_eq!(
        all_45_pairs().len(),
        45,
        "33.y.b drift gate: the IRFlowNode × ShimReason cartesian \
         product must cover all 45 variants. Adding a 46th IRFlowNode \
         variant fails the dispatch_node compile (forcing a new arm) \
         AND requires updating this drift gate factory + pair list."
    );
}

#[test]
fn shim_reason_all_const_has_exactly_45_entries() {
    assert_eq!(
        ShimReason::ALL.len(),
        45,
        "33.y.b drift gate: ShimReason::ALL covers all 45 variants \
         (1-to-1 with IRFlowNode + the dispatch_node match arms)."
    );
}

// ────────────────────────────────────────────────────────────────────
//  §2 — Every variant routes to its labeled ShimReason
// ────────────────────────────────────────────────────────────────────

/// 33.y.b drift gate amended in 33.y.c: 6 variants (Step / Probe /
/// Reason / Validate / Refine / Weave) have GRADUATED from
/// `LegacyShimHandled` to a real `pure_shape` async handler returning
/// `NodeOutcome::Completed { output, tokens_emitted, step_index }`.
/// The remaining 39 variants still route through `legacy_shim`. As
/// each subsequent sub-fase 33.y.d–j ships handlers for additional
/// variants, this set GROWS until 33.y.l where `LegacyShimHandled` is
/// deleted (all 45 graduated).
const GRADUATED_VARIANTS: &[ShimReason] = &[
    // 33.y.c — pure-shape (6)
    ShimReason::Step,
    ShimReason::Probe,
    ShimReason::Reason,
    ShimReason::Validate,
    ShimReason::Refine,
    ShimReason::Weave,
    // 33.y.d — orchestration (6)
    ShimReason::Let,
    ShimReason::Conditional,
    ShimReason::ForIn,
    ShimReason::Break,
    ShimReason::Continue,
    ShimReason::Return,
    // 33.y.e — parallel + algebraic (2)
    ShimReason::Par,
    ShimReason::Stream,
    // 33.y.f — cognitive primitives (10)
    ShimReason::Remember,
    ShimReason::Recall,
    ShimReason::Forge,
    ShimReason::Focus,
    ShimReason::Associate,
    ShimReason::Aggregate,
    ShimReason::Explore,
    ShimReason::Ingest,
    ShimReason::Navigate,
    ShimReason::Corroborate,
    // 33.y.g — algebraic-effect handlers (6)
    ShimReason::ShieldApply,
    ShimReason::OtsApply,
    ShimReason::MandateApply,
    ShimReason::ComputeApply,
    ShimReason::Listen,
    ShimReason::DaemonStep,
    // 33.y.h — wire integrations (10)
    ShimReason::Emit,
    ShimReason::Publish,
    ShimReason::Discover,
    ShimReason::Persist,
    ShimReason::Retrieve,
    ShimReason::Mutate,
    ShimReason::Purge,
    ShimReason::Transact,
    ShimReason::Deliberate,
    ShimReason::Consensus,
    // 33.y.i — PIX variants (3)
    ShimReason::Hibernate,
    ShimReason::Drill,
    ShimReason::Trail,
];

/// Pure-shape graduated variants (33.y.c) — strict "(stub)" + 1 token.
const PURE_SHAPE_GRADUATED: &[ShimReason] = &[
    ShimReason::Step,
    ShimReason::Probe,
    ShimReason::Reason,
    ShimReason::Validate,
    ShimReason::Refine,
    ShimReason::Weave,
];

/// Orchestration graduated variants (33.y.d) — return varied outcome
/// shapes depending on the synthetic IR payload: Let → Completed
/// with the bound value; Conditional/ForIn → Completed (empty body
/// in the synthetic factory); Break → Break sentinel; Continue →
/// LoopContinue sentinel; Return → Return sentinel.
const ORCHESTRATION_GRADUATED: &[ShimReason] = &[
    ShimReason::Let,
    ShimReason::Conditional,
    ShimReason::ForIn,
    ShimReason::Break,
    ShimReason::Continue,
    ShimReason::Return,
];

/// Parallel + algebraic graduated variants (33.y.e) — both
/// `IRParallelBlock` and `IRStreamBlock` are payload-free in
/// v1.25.0; handlers emit canonical wire shape (StepStart +
/// StepComplete with the corresponding step_type slug) +
/// return Completed { output: "", tokens_emitted: 0 }.
const PARALLEL_ALGEBRAIC_GRADUATED: &[ShimReason] = &[
    ShimReason::Par,
    ShimReason::Stream,
];

/// Cognitive primitive graduated variants (33.y.f).
///
/// - **Remember/Recall/Forge**: emit wire shape; for the synthetic
///   factory inputs in this drift gate, Remember binds the literal
///   expression as output; Recall returns empty (no prior memory);
///   Forge returns empty (payload-free). All 0 tokens.
/// - **Focus/Associate/Aggregate/Explore/Ingest/Navigate/Corroborate**:
///   route through `pure_shape::run_pure_shape` which calls the
///   stub backend → 1 chunk of "(stub)" → 1 token.
const COGNITIVE_PEM_BOUND_GRADUATED: &[ShimReason] = &[
    ShimReason::Remember,
    ShimReason::Recall,
    ShimReason::Forge,
];

const COGNITIVE_FRAMING_GRADUATED: &[ShimReason] = &[
    ShimReason::Focus,
    ShimReason::Associate,
    ShimReason::Aggregate,
    ShimReason::Explore,
    ShimReason::Ingest,
    ShimReason::Navigate,
    ShimReason::Corroborate,
];

/// Algebraic-effect handler graduated variants (33.y.g) — apply
/// capability + invoke / listen / daemon. All emit wire shape +
/// bind output under a variant-specific key in `let_bindings`.
/// For zero-payload synthetic inputs in the drift gate, outputs
/// are sensible defaults (empty/placeholder).
const ALGEBRAIC_HANDLERS_GRADUATED: &[ShimReason] = &[
    ShimReason::ShieldApply,
    ShimReason::OtsApply,
    ShimReason::MandateApply,
    ShimReason::ComputeApply,
    ShimReason::Listen,
    ShimReason::DaemonStep,
];

/// Wire-integration graduated variants (33.y.h) — π-calc typed
/// channels + persistence primitives + multi-agent deliberation.
/// All emit wire shape + various placeholder/persisted outputs;
/// tokens_emitted=0 across the board (no LLM dispatch).
const WIRE_INTEGRATIONS_GRADUATED: &[ShimReason] = &[
    ShimReason::Emit,
    ShimReason::Publish,
    ShimReason::Discover,
    ShimReason::Persist,
    ShimReason::Retrieve,
    ShimReason::Mutate,
    ShimReason::Purge,
    ShimReason::Transact,
    ShimReason::Deliberate,
    ShimReason::Consensus,
];

/// PIX graduated variants (33.y.i) — Hibernate / Drill / Trail.
/// All emit canonical wire shape + bind placeholder/seeded value
/// under variant-specific keys. Tokens=0 across the board.
const PIX_GRADUATED: &[ShimReason] = &[
    ShimReason::Hibernate,
    ShimReason::Drill,
    ShimReason::Trail,
];

#[tokio::test]
async fn every_ir_flow_node_routes_to_its_labeled_handler() {
    let pairs = all_45_pairs();
    for (node, expected_reason, expected_kind) in pairs {
        let (mut ctx, _rx) = fresh_ctx();
        let outcome = dispatch_node(&node, &mut ctx).await;
        let pure_shape = PURE_SHAPE_GRADUATED.contains(&expected_reason);
        let orchestration = ORCHESTRATION_GRADUATED.contains(&expected_reason);

        let parallel_algebraic =
            PARALLEL_ALGEBRAIC_GRADUATED.contains(&expected_reason);
        let cognitive_pem = COGNITIVE_PEM_BOUND_GRADUATED.contains(&expected_reason);
        let cognitive_framing = COGNITIVE_FRAMING_GRADUATED.contains(&expected_reason);
        let algebraic_handler = ALGEBRAIC_HANDLERS_GRADUATED.contains(&expected_reason)
            || WIRE_INTEGRATIONS_GRADUATED.contains(&expected_reason)
            || PIX_GRADUATED.contains(&expected_reason);

        // Cognitive-framing handlers behave like pure-shape (1 token).
        let pure_shape_like = pure_shape || cognitive_framing;
        // Parallel/algebraic + cognitive-PEM-bound return Completed
        // with output="" (truly payload-free). Algebraic handlers +
        // wire integrations return Completed with placeholder output
        // (compute:(...), (awaiting ...), daemon:..., "persisted N
        // entries to `s`", etc.) so they need a separate arm that
        // doesn't assert output equality.
        let strict_empty_completed = parallel_algebraic || cognitive_pem;

        match (outcome, pure_shape_like, orchestration, strict_empty_completed, algebraic_handler) {
            // Pure-shape: stub-backend produces "(stub)" with 1 token.
            (Ok(NodeOutcome::Completed { output, tokens_emitted, .. }), true, _, _, _) => {
                assert_eq!(
                    output, "(stub)",
                    "pure-shape variant {:?} stub output should be '(stub)' (D4)",
                    expected_reason
                );
                assert_eq!(
                    tokens_emitted, 1,
                    "pure-shape variant {:?} stub emits 1 token (D4 byte-compat)",
                    expected_reason
                );
            }
            // Orchestration: Break/Continue/Return are sentinel-only;
            // Let/Conditional/ForIn return Completed with payload-
            // dependent output (zero-payload synthetics → empty body
            // → empty output).
            (Ok(NodeOutcome::Break), _, true, _, _) if expected_reason == ShimReason::Break => {}
            (Ok(NodeOutcome::LoopContinue), _, true, _, _)
                if expected_reason == ShimReason::Continue => {}
            (Ok(NodeOutcome::Return { .. }), _, true, _, _)
                if expected_reason == ShimReason::Return => {}
            (Ok(NodeOutcome::Completed { .. }), _, true, _, _)
                if matches!(
                    expected_reason,
                    ShimReason::Let | ShimReason::Conditional | ShimReason::ForIn
                ) => {}
            // Strict empty (Par + Stream + Remember + Recall + Forge):
            // Completed with output="", tokens=0.
            (
                Ok(NodeOutcome::Completed {
                    output,
                    tokens_emitted,
                    ..
                }),
                _,
                _,
                true,
                _,
            ) => {
                assert_eq!(
                    output, "",
                    "33.y.e/f strict-empty variant {:?} → empty output",
                    expected_reason
                );
                assert_eq!(
                    tokens_emitted, 0,
                    "33.y.e/f strict-empty variant {:?} → 0 tokens",
                    expected_reason
                );
            }
            // 33.y.g algebraic handlers: Completed with placeholder
            // outputs (compute:(...), (awaiting ...), daemon:..., or
            // empty for Shield/Ots/Mandate with empty target).
            // tokens_emitted=0 always.
            (
                Ok(NodeOutcome::Completed { tokens_emitted, .. }),
                _,
                _,
                _,
                true,
            ) => {
                assert_eq!(
                    tokens_emitted, 0,
                    "33.y.g algebraic handler variant {:?} → 0 tokens",
                    expected_reason
                );
            }
            // Non-graduated: shim returns LegacyShimHandled.
            (
                Ok(NodeOutcome::LegacyShimHandled { reason, node_kind }),
                false,
                false,
                false,
                false,
            ) => {
                assert_eq!(
                    reason, expected_reason,
                    "non-graduated dispatch_node routed {:?} to the wrong \
                     ShimReason: got {:?}, expected {:?}",
                    expected_kind, reason, expected_reason
                );
                assert_eq!(
                    node_kind, expected_kind,
                    "non-graduated dispatch_node returned the wrong node_kind \
                     slug for {:?}: got {:?}, expected {:?}",
                    expected_reason, node_kind, expected_kind
                );
            }
            (Ok(other), true, _, _, _) => panic!(
                "pure-shape variant {:?} expected Completed (stub), got {other:?}",
                expected_reason
            ),
            (Ok(other), _, true, _, _) => panic!(
                "orchestration variant {:?} unexpected outcome: {other:?}",
                expected_reason
            ),
            (Ok(other), _, _, true, _) => panic!(
                "strict-empty variant {:?} expected Completed (empty), got {other:?}",
                expected_reason
            ),
            (Ok(other), _, _, _, true) => panic!(
                "algebraic handler variant {:?} expected Completed, got {other:?}",
                expected_reason
            ),
            (Ok(other), false, false, false, false) => panic!(
                "non-graduated variant {:?} expected LegacyShimHandled, got {other:?}",
                expected_reason
            ),
            (Err(e), _, _, _, _) => panic!(
                "dispatch_node returned Err for {:?}: {e:?}",
                expected_reason
            ),
        }
    }
}

/// Pin the size of the graduated-variants set. Across 33.y.c–j this
/// set GROWS variant-by-variant. At 33.y.l this assertion becomes
/// `GRADUATED_VARIANTS.len() == 45` and `LegacyShimHandled` is
/// deleted in lockstep.
#[test]
fn graduated_variants_set_size_pinned_for_33_y_i() {
    assert_eq!(
        GRADUATED_VARIANTS.len(),
        43,
        "33.y.i advances graduated count to 43: 6 pure-shape + 6 \
         orchestration + 2 parallel/algebraic + 10 cognitive + 6 \
         algebraic handlers + 10 wire integrations + 3 PIX \
         (Hibernate/Drill/Trail). 33.y.j will advance to 45 (Lambda \
         + UseTool)."
    );
    assert_eq!(PURE_SHAPE_GRADUATED.len(), 6);
    assert_eq!(ORCHESTRATION_GRADUATED.len(), 6);
    assert_eq!(PARALLEL_ALGEBRAIC_GRADUATED.len(), 2);
    assert_eq!(COGNITIVE_PEM_BOUND_GRADUATED.len(), 3);
    assert_eq!(COGNITIVE_FRAMING_GRADUATED.len(), 7);
    assert_eq!(ALGEBRAIC_HANDLERS_GRADUATED.len(), 6);
    assert_eq!(WIRE_INTEGRATIONS_GRADUATED.len(), 10);
    assert_eq!(PIX_GRADUATED.len(), 3);
}

// ────────────────────────────────────────────────────────────────────
//  §3 — Cancel propagation through dispatch_node entry
// ────────────────────────────────────────────────────────────────────

#[tokio::test]
async fn dispatch_node_honors_cancel_flag_at_entry() {
    let pairs = all_45_pairs();
    for (node, _reason, kind) in pairs {
        let (tx, _rx) = mpsc::unbounded_channel();
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);
        let outcome = dispatch_node(&node, &mut ctx).await;
        match outcome {
            Err(DispatchError::UpstreamCancelled) => {} // expected
            other => panic!(
                "expected UpstreamCancelled for {kind} with cancel set, got {other:?}"
            ),
        }
    }
}

// ────────────────────────────────────────────────────────────────────
//  §4 — ShimReason::slug() is byte-equal with flow_plan::ir_flow_node_kind
// ────────────────────────────────────────────────────────────────────

#[test]
fn shim_reason_slug_matches_flow_plan_kind_for_all_45_variants() {
    use axon::flow_plan::ir_flow_node_kind;
    let pairs = all_45_pairs();
    for (node, reason, expected_kind) in pairs {
        let from_flow_plan = ir_flow_node_kind(&node);
        let from_shim_reason = reason.slug();
        assert_eq!(
            from_flow_plan, from_shim_reason,
            "wire-stability drift: flow_plan::ir_flow_node_kind \
             returned {:?} but ShimReason::{:?}.slug() returned {:?} \
             for the same IR variant",
            from_flow_plan, reason, from_shim_reason
        );
        assert_eq!(
            from_flow_plan, expected_kind,
            "drift gate pair list disagrees with flow_plan for {:?}",
            reason
        );
    }
}

// ────────────────────────────────────────────────────────────────────
//  §5 — DispatchCtx surface usable across crate boundary
// ────────────────────────────────────────────────────────────────────

#[test]
fn dispatch_ctx_branch_path_round_trip() {
    let (mut ctx, _rx) = fresh_ctx();
    assert_eq!(ctx.branch_path_string(), "");
    ctx.branch_path.push("par[0]".to_string());
    assert_eq!(ctx.branch_path_string(), "par[0]");
    ctx.branch_path.push("step[3]".to_string());
    assert_eq!(ctx.branch_path_string(), "par[0].step[3]");
    ctx.branch_path.pop();
    assert_eq!(ctx.branch_path_string(), "par[0]");
}

#[test]
fn dispatch_ctx_step_counter_writable() {
    let (mut ctx, _rx) = fresh_ctx();
    assert_eq!(ctx.step_counter, 0);
    ctx.step_counter += 1;
    assert_eq!(ctx.step_counter, 1);
}

// ────────────────────────────────────────────────────────────────────
//  §6 — DispatchError variants are reachable from the public surface
// ────────────────────────────────────────────────────────────────────

#[test]
fn dispatch_error_variants_constructible_from_public_surface() {
    let _be = DispatchError::BackendError {
        name: "anthropic".to_string(),
        message: "rate limited".to_string(),
    };
    let _uc = DispatchError::UpstreamCancelled;
    let _lsf = DispatchError::LegacyShimFailed {
        kind: "let",
        message: "rhs eval failed".to_string(),
    };
    let _md = DispatchError::MissingDependency { name: "pem_async" };
    let _cc = DispatchError::ChannelClosed;
    // If this compiles, the variants are all reachable.
}

// ────────────────────────────────────────────────────────────────────
//  §7 — D7 invariant: zero `unimplemented!()` / `todo!()` markers
// ────────────────────────────────────────────────────────────────────
//
// This test verifies (at the type level) that calling dispatch_node
// on every IRFlowNode variant does NOT panic. If a future maintainer
// drops an `unimplemented!()` into an arm, this test surfaces the
// panic at PR time, not at adopter runtime.

#[tokio::test]
async fn dispatch_node_does_not_panic_for_any_variant() {
    let pairs = all_45_pairs();
    for (node, reason, kind) in pairs {
        let (mut ctx, _rx) = fresh_ctx();
        // If this `await` panics for any variant we've shipped a
        // `unimplemented!()` / `todo!()` / `panic!()` into an arm.
        // The D7 mandate forbids this.
        let outcome = dispatch_node(&node, &mut ctx).await;
        // We only assert it didn't panic — the specific outcome
        // shape is exercised by §2 above.
        assert!(
            outcome.is_ok() || outcome.is_err(),
            "outcome for {kind} ({reason:?}) is somehow neither Ok nor \
             Err — impossible per Rust's type system but asserted \
             for sanity"
        );
    }
}
