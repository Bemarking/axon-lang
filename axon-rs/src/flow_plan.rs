//! §Fase 33.x.b — Streaming execution plan extraction.
//!
//! Builds a streaming-shaped execution plan from `.axon` source for
//! the production async SSE path. Pre-resolves per-step
//! [`BackpressurePolicy`] via
//! [`crate::stream_effect_dispatcher::resolve_stream_effect_for_step`]
//! so the hot per-chunk loop in
//! `crate::axon_server::server_execute_streaming_async` does NOT
//! re-walk the AST per chunk.
//!
//! # Scope boundary (33.x.b)
//!
//! 33.x.b ships the SIMPLEST step shape (single `ask`, no anchors,
//! no `apply: lambda`, no `let` bindings, no mid-stream `use_tool`).
//! This is exactly the canonical Kivi/Stream-effect adopter shape
//! the diagnostic anchor pins. Flows that use the omitted features
//! still execute correctly on the legacy synchronous path; the
//! streaming path falls back via [`PlanFallback::LegacyOrchestration`]
//! and the SSE handler routes through `server_execute_full` (the
//! pre-33.x.b path). NO silent degradation — the fallback is
//! observable in plan output so adopter diagnostics can flag it.
//!
//! # Lift target (33.x.c)
//!
//! `runner::build_execution_plan` (private, sync) stays unchanged in
//! 33.x.b. 33.x.c unifies the two builders. Until then, this module
//! is the SOLE source of truth for streaming-path plan extraction;
//! `runner.rs` is the sole source of truth for sync-path execution.
//!
//! # D-letter anchors
//!
//! - **D1** — every streaming-path flow resolves a [`StreamingExecutionPlan`]
//!   here before dispatching to `Backend::stream()`. The plan's
//!   `backend_name` is the resolved provider name; `steps[].effect_policy`
//!   pre-resolves the declared `<stream:<policy>>` for the
//!   `StreamPolicyEnforcer` wrap in 33.x.d.
//! - **D4** — the plan structure carries NO new wire-shape fields;
//!   it is internal scaffolding that produces the same
//!   FlowExecutionEvent sequence as the pre-33.x.b path for the
//!   adopter shapes 33.x.b supports.
//! - **D5** — fallback to legacy orchestration is observable via
//!   [`PlanFallback`] so 33.x.g can hook `axon-W002`-style warnings.

use crate::ir_nodes::IRProgram;
use crate::stream_effect::BackpressurePolicy;
use crate::stream_effect_dispatcher::resolve_stream_effect_for_step;

// ────────────────────────────────────────────────────────────────────
//  Plan types
// ────────────────────────────────────────────────────────────────────

/// One step in a streaming execution plan.
///
/// Pre-resolves every field the hot loop needs — system prompt,
/// user prompt, declared effect policy. The per-chunk loop in
/// `server_execute_streaming_async` reads these fields without
/// touching the IR or AST.
#[derive(Debug, Clone, PartialEq)]
pub struct StreamingStep {
    /// Canonical step name (matches `IRStep.name`). Surfaces in
    /// `axon.token.step` + `axon.complete.step_names`.
    pub step_name: String,
    /// User prompt this step asks the LLM. Built from `step.ask` +
    /// optional `apply: tool` argument expansion.
    pub user_prompt: String,
    /// Optional max-tokens cap from `context.max_tokens` or
    /// step-level `max_tokens:` declaration.
    pub max_tokens: Option<u32>,
    /// Optional temperature from `context.temperature` (overridden
    /// by locked-param dispatch in the Backend impl).
    pub temperature: Option<f64>,
    /// Pre-resolved backpressure policy from the step's tool's
    /// `effects: <stream:<policy>>` declaration. `None` when the
    /// step doesn't `apply:` a tool with a stream effect.
    /// Activated by 33.x.d's `StreamPolicyEnforcer` wrap; recorded
    /// today in `axon.complete.stream_policies` for audit
    /// correlation (Fase 33.e).
    pub effect_policy: Option<BackpressurePolicy>,
}

/// Streaming execution plan — one per flow invocation.
#[derive(Debug, Clone, PartialEq)]
pub struct StreamingExecutionPlan {
    /// Flow name from `run` declaration.
    pub flow_name: String,
    /// Backend name as the adopter resolved it (after `auto`
    /// resolution upstream of plan construction).
    pub backend_name: String,
    /// Composed system prompt — persona + context + anchor
    /// instructions (Fase 11 stack). Same shape as the sync
    /// `runner::build_system_prompt` output.
    pub system_prompt: String,
    /// Ordered step list. Empty plan == empty flow (rare but valid
    /// per IR grammar; the streaming path emits FlowStart +
    /// FlowComplete with `steps_executed: 0` per Fase 33.b).
    pub steps: Vec<StreamingStep>,
}

/// Reason a flow could not be planned for the streaming path.
///
/// Each variant is a closed-catalog signal the SSE handler routes
/// to either an `axon.error` wire event (hard error) or a fallback
/// to the legacy synchronous path (soft fall-through).
#[derive(Debug, Clone, PartialEq)]
pub enum PlanError {
    /// Source did not parse. Mirrors `Parser::parse` error message.
    Parse(String),
    /// Type checker rejected the source.
    TypeCheck(Vec<String>),
    /// IR generation failed (rare — usually means the type-check
    /// pass missed an invariant).
    IrGeneration(String),
    /// The requested flow_name was not found in the IR's flow list.
    FlowNotFound { flow_name: String, available: Vec<String> },
    /// The flow uses features the 33.x.b streaming path does not
    /// yet support. The handler falls back to the legacy sync path.
    /// 33.x.b ships the simplest shape (single `ask:` per step,
    /// optional `apply: tool`). Anchors, lambda apply, let bindings
    /// and mid-stream tool calls live on the legacy path until
    /// their respective follow-ups.
    LegacyOrchestrationRequired { reason: PlanFallback, flow_name: String },
}

/// Closed catalog of reasons the streaming path falls back to the
/// legacy synchronous orchestration. Each variant maps to a
/// specific adopter source shape the 33.x.b scope explicitly
/// defers.
#[derive(Debug, Clone, PartialEq)]
pub enum PlanFallback {
    /// Flow uses `anchor: <name>` constraints. Anchor enforcement
    /// fires on FINAL flow output, which is incompatible with
    /// per-token streaming until per-chunk anchor checking lands.
    AnchorConstraintsPresent,
    /// Flow uses `apply: <lambda>` (Fase 15 lambda data apply).
    /// Lambda apply runs after the step's LLM response; per-chunk
    /// lambda application is a future fase.
    LambdaApplyPresent,
    /// Flow uses `let X = ...` SSA bindings (Fase 17). Binding
    /// resolution runs between steps; streaming path doesn't yet
    /// thread the binding context through the per-chunk loop.
    LetBindingPresent,
    /// Flow uses `use_tool` mid-step (function calling). Mid-stream
    /// tool calls are explicit Fase 33-followon-2 scope.
    UseToolPresent,
    /// Flow contains a `Hibernate` step (Fase 19 CPS). Hibernation
    /// requires the synchronous CPS handler stack.
    HibernatePresent,
    /// Flow contains a `Drill` or `Trail` step (Fase 19 PIX). PIX
    /// trace state is captured on the synchronous path.
    PixPresent,
    /// Flow contains an `IRFlowNode` variant that 33.x.b does not
    /// yet model (Conditional / ForIn / Par / Probe / Reason /
    /// ShieldApply / etc.). 33.x.b ships the canonical
    /// `step S { ask: "..." [apply: tool] }` shape only; subsequent
    /// 33.x followups extend coverage per founder-sequenced
    /// sub-fases. The legacy synchronous path keeps working for
    /// these flows — there is no functional regression.
    UnsupportedNode {
        /// Stable kind discriminant — e.g. `"conditional"`,
        /// `"for_in"`, `"reason"`. Surfaces in audit row + future
        /// 33.x.g warning emission.
        kind: &'static str,
    },
}

impl PlanFallback {
    /// Stable slug for diagnostic emission. Used by audit row +
    /// future 33.x.g warning surface.
    pub fn slug(&self) -> &'static str {
        match self {
            Self::AnchorConstraintsPresent => "anchor_constraints",
            Self::LambdaApplyPresent => "lambda_apply",
            Self::LetBindingPresent => "let_binding",
            Self::UseToolPresent => "use_tool",
            Self::HibernatePresent => "hibernate",
            Self::PixPresent => "pix",
            Self::UnsupportedNode { .. } => "unsupported_node",
        }
    }
}

// ────────────────────────────────────────────────────────────────────
//  Plan builder
// ────────────────────────────────────────────────────────────────────

/// Build a streaming execution plan from `.axon` source.
///
/// Pipeline: lex → parse → type-check → IR generation → walk the
/// IR's runs for `flow_name` → emit one [`StreamingStep`] per step.
///
/// Returns [`PlanError::LegacyOrchestrationRequired`] when the flow
/// uses any feature 33.x.b's scope explicitly defers. The SSE
/// handler treats this as a SOFT fallback — it routes the request
/// to `server_execute_full` (the pre-33.x.b path) so adopters with
/// these flow shapes continue working unchanged.
pub fn build_streaming_plan(
    source: &str,
    source_file: &str,
    flow_name: &str,
    backend_name: &str,
) -> Result<StreamingExecutionPlan, PlanError> {
    // 1. Lex
    let tokens = crate::lexer::Lexer::new(source, source_file)
        .tokenize()
        .map_err(|e| PlanError::Parse(format!("lex error: {e:?}")))?;

    // 2. Parse
    let mut parser = crate::parser::Parser::new(tokens);
    let program = parser.parse().map_err(|e| PlanError::Parse(e.message))?;

    // 3. Type-check
    let mut checker = crate::type_checker::TypeChecker::new(&program);
    let errors = checker.check();
    if !errors.is_empty() {
        return Err(PlanError::TypeCheck(
            errors.into_iter().map(|e| e.message).collect(),
        ));
    }

    // 4. IR generation
    let ir = crate::ir_generator::IRGenerator::new().generate(&program);

    build_plan_from_ir(&ir, &program, flow_name, backend_name)
}

/// Build a plan from an already-typed IR. Useful for tests that
/// drive the planner with hand-constructed IR (no source parse).
pub fn build_plan_from_ir(
    ir: &IRProgram,
    program: &crate::ast::Program,
    flow_name: &str,
    backend_name: &str,
) -> Result<StreamingExecutionPlan, PlanError> {
    // 5. Locate the flow in the IR (for orchestration metadata).
    let flow = ir
        .flows
        .iter()
        .find(|f| f.name == flow_name)
        .ok_or_else(|| PlanError::FlowNotFound {
            flow_name: flow_name.to_string(),
            available: ir.flows.iter().map(|f| f.name.clone()).collect(),
        })?;

    // 5b. Locate the same flow on the AST side (for effect-row
    //     resolution via `resolve_stream_effect_for_step`, which
    //     takes `&FlowDefinition`).
    let ast_flow = program
        .declarations
        .iter()
        .find_map(|d| match d {
            crate::ast::Declaration::Flow(f) if f.name == flow_name => Some(f),
            _ => None,
        })
        .ok_or_else(|| PlanError::FlowNotFound {
            flow_name: flow_name.to_string(),
            available: ir.flows.iter().map(|f| f.name.clone()).collect(),
        })?;

    // 6. Reject unsupported features up front (closed catalog).
    if let Some(reason) = unsupported_feature_reason(flow, ir) {
        return Err(PlanError::LegacyOrchestrationRequired {
            reason,
            flow_name: flow_name.to_string(),
        });
    }

    // 7. System prompt — best-effort composition mirroring the sync
    //    path's `build_system_prompt` output. Only persona/context
    //    fields that exist in the IR get included.
    let system_prompt = compose_system_prompt(flow, ir);

    // 8. Per-step plan. Only `IRFlowNode::Step` variants are
    //    streaming-eligible; every other variant has been rejected
    //    upstream by `unsupported_feature_reason`.
    let mut steps = Vec::new();
    for node in &flow.steps {
        if let crate::ir_nodes::IRFlowNode::Step(ir_step) = node {
            let max_tokens = ir
                .contexts
                .first()
                .and_then(|c| c.max_tokens)
                .map(|n| n as u32);
            let temperature = ir.contexts.first().and_then(|c| c.temperature);
            let effect_policy =
                resolve_stream_effect_for_step(&ir_step.name, ast_flow, program);

            steps.push(StreamingStep {
                step_name: ir_step.name.clone(),
                user_prompt: ir_step.ask.clone(),
                max_tokens,
                temperature,
                effect_policy,
            });
        }
    }

    Ok(StreamingExecutionPlan {
        flow_name: flow_name.to_string(),
        backend_name: backend_name.to_string(),
        system_prompt,
        steps,
    })
}

/// Walk a flow's steps + IR and return `Some(PlanFallback)` iff any
/// step uses a feature 33.x.b defers. Closed-catalog — adding a new
/// reason requires updating this function + the `PlanFallback`
/// enum (compiler enforces exhaustiveness in the slug match).
fn unsupported_feature_reason(
    flow: &crate::ir_nodes::IRFlow,
    ir: &IRProgram,
) -> Option<PlanFallback> {
    use crate::ir_nodes::IRFlowNode;

    // Anchors on the flow's `run` declaration — IR-level signal.
    if ir.runs.iter().any(|r| {
        r.flow_name == flow.name && !r.resolved_anchors.is_empty()
    }) {
        return Some(PlanFallback::AnchorConstraintsPresent);
    }

    for node in &flow.steps {
        match node {
            IRFlowNode::Step(_) => {
                // The streaming-eligible node — `step S { ask:
                // "..." }` (with or without `apply: tool`).
            }
            IRFlowNode::LambdaDataApply(_) => {
                return Some(PlanFallback::LambdaApplyPresent);
            }
            IRFlowNode::Let(_) => {
                return Some(PlanFallback::LetBindingPresent);
            }
            IRFlowNode::UseTool(_) => {
                return Some(PlanFallback::UseToolPresent);
            }
            IRFlowNode::Hibernate(_) => {
                return Some(PlanFallback::HibernatePresent);
            }
            IRFlowNode::Drill(_) | IRFlowNode::Trail(_) => {
                return Some(PlanFallback::PixPresent);
            }
            // Every other IRFlowNode variant (Probe, Reason,
            // Validate, Refine, Weave, Remember, Recall,
            // Conditional, ForIn, Return, Break, Continue, Par,
            // Deliberate, Consensus, Forge, Focus, Associate,
            // Aggregate, Explore, Ingest, ShieldApply, Stream,
            // Navigate, Corroborate, OtsApply, MandateApply,
            // ComputeApply, Listen, DaemonStep, Emit, Publish,
            // Discover, Persist, Retrieve, Mutate, Purge,
            // Transact) is currently rejected as
            // `LegacyOrchestrationRequired::UnsupportedNode` — the
            // streaming path ships canonical
            // `step S { ask: "..." [apply: tool] }` first.
            // Subsequent 33.x followups extend coverage per
            // founder-sequenced sub-fases. Default-deny is the
            // safe posture: legacy synchronous path keeps working
            // for these flows.
            other => {
                return Some(PlanFallback::UnsupportedNode {
                    kind: ir_flow_node_kind(other),
                });
            }
        }
    }

    None
}

/// Stable kind discriminant for an `IRFlowNode`. Closed catalog
/// extracted as a separate function so adding a new IRFlowNode
/// variant on the frontend forces an explicit match update here
/// (compiler enforces exhaustiveness via the unreachable arm).
fn ir_flow_node_kind(node: &crate::ir_nodes::IRFlowNode) -> &'static str {
    use crate::ir_nodes::IRFlowNode;
    match node {
        IRFlowNode::Step(_) => "step",
        IRFlowNode::Probe(_) => "probe",
        IRFlowNode::Reason(_) => "reason",
        IRFlowNode::Validate(_) => "validate",
        IRFlowNode::Refine(_) => "refine",
        IRFlowNode::Weave(_) => "weave",
        IRFlowNode::UseTool(_) => "use_tool",
        IRFlowNode::Remember(_) => "remember",
        IRFlowNode::Recall(_) => "recall",
        IRFlowNode::Conditional(_) => "conditional",
        IRFlowNode::ForIn(_) => "for_in",
        IRFlowNode::Let(_) => "let",
        IRFlowNode::Return(_) => "return",
        IRFlowNode::Break(_) => "break",
        IRFlowNode::Continue(_) => "continue",
        IRFlowNode::LambdaDataApply(_) => "lambda_data_apply",
        IRFlowNode::Par(_) => "par",
        IRFlowNode::Hibernate(_) => "hibernate",
        IRFlowNode::Deliberate(_) => "deliberate",
        IRFlowNode::Consensus(_) => "consensus",
        IRFlowNode::Forge(_) => "forge",
        IRFlowNode::Focus(_) => "focus",
        IRFlowNode::Associate(_) => "associate",
        IRFlowNode::Aggregate(_) => "aggregate",
        IRFlowNode::Explore(_) => "explore",
        IRFlowNode::Ingest(_) => "ingest",
        IRFlowNode::ShieldApply(_) => "shield_apply",
        IRFlowNode::Stream(_) => "stream_block",
        IRFlowNode::Navigate(_) => "navigate",
        IRFlowNode::Drill(_) => "drill",
        IRFlowNode::Trail(_) => "trail",
        IRFlowNode::Corroborate(_) => "corroborate",
        IRFlowNode::OtsApply(_) => "ots_apply",
        IRFlowNode::MandateApply(_) => "mandate_apply",
        IRFlowNode::ComputeApply(_) => "compute_apply",
        IRFlowNode::Listen(_) => "listen",
        IRFlowNode::DaemonStep(_) => "daemon_step",
        IRFlowNode::Emit(_) => "emit",
        IRFlowNode::Publish(_) => "publish",
        IRFlowNode::Discover(_) => "discover",
        IRFlowNode::Persist(_) => "persist",
        IRFlowNode::Retrieve(_) => "retrieve",
        IRFlowNode::Mutate(_) => "mutate",
        IRFlowNode::Purge(_) => "purge",
        IRFlowNode::Transact(_) => "transact",
    }
}

/// Compose a streaming-path system prompt from the IR. Mirrors the
/// sync `runner::build_system_prompt` shape closely enough that the
/// LLM responds equivalently; not byte-identical because 33.x.b's
/// scope skips fields the streaming path doesn't honor (anchor
/// instructions — those flows fall back to legacy).
fn compose_system_prompt(
    flow: &crate::ir_nodes::IRFlow,
    ir: &IRProgram,
) -> String {
    let mut parts: Vec<String> = Vec::new();

    if let Some(persona) = ir.personas.first() {
        parts.push(format!("# Persona: {}", persona.name));
        if !persona.domain.is_empty() {
            parts.push(format!("Domain expertise: {}", persona.domain.join(", ")));
        }
        if !persona.tone.is_empty() {
            parts.push(format!("Communication tone: {}", persona.tone));
        }
        if !persona.language.is_empty() {
            parts.push(format!("Language: {}", persona.language));
        }
    }

    if let Some(ctx) = ir.contexts.first() {
        parts.push(format!("\n# Context: {}", ctx.name));
        if !ctx.depth.is_empty() {
            parts.push(format!("Analysis depth: {}", ctx.depth));
        }
        if !ctx.memory_scope.is_empty() {
            parts.push(format!("Memory scope: {}", ctx.memory_scope));
        }
    }

    parts.push(format!("\n# Flow: {}", flow.name));
    parts.join("\n")
}

// ────────────────────────────────────────────────────────────────────
//  Tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_simple_stream_source() -> &'static str {
        // Canonical Kivi-shape: single step, output Stream<Token>,
        // explicit transport: sse. No anchors, no apply, no let.
        "flow Chat() -> Unit {\n\
            step Generate { ask: \"hi\" output: Stream<Token> }\n\
         }\n\
         axonendpoint ChatEndpoint { method: POST path: \"/chat\" execute: Chat transport: sse }"
    }

    fn parse_stream_with_effect_source() -> &'static str {
        // Disjunct (b): tool with stream effect, step apply.
        "tool chat_token_stream { description: \"stream\" effects: <stream:drop_oldest> }\n\
         flow Chat() -> Unit {\n\
            step Generate { ask: \"hi\" apply: chat_token_stream }\n\
         }\n\
         axonendpoint ChatEndpoint { method: POST path: \"/chat\" execute: Chat transport: sse }"
    }

    #[test]
    fn build_plan_for_simple_stream_flow_returns_one_step() {
        let plan = build_streaming_plan(
            parse_simple_stream_source(),
            "test.axon",
            "Chat",
            "stub",
        )
        .expect("simple stream flow plans cleanly");

        assert_eq!(plan.flow_name, "Chat");
        assert_eq!(plan.backend_name, "stub");
        assert_eq!(plan.steps.len(), 1);
        assert_eq!(plan.steps[0].step_name, "Generate");
        assert_eq!(plan.steps[0].user_prompt, "hi");
        assert_eq!(plan.steps[0].effect_policy, None, "no tool effect → no policy");
    }

    #[test]
    fn build_plan_with_drop_oldest_effect_pre_resolves_policy() {
        let plan = build_streaming_plan(
            parse_stream_with_effect_source(),
            "test.axon",
            "Chat",
            "stub",
        )
        .expect("stream-effect flow plans cleanly");

        assert_eq!(plan.steps.len(), 1);
        assert_eq!(plan.steps[0].effect_policy, Some(BackpressurePolicy::DropOldest));
    }

    #[test]
    fn build_plan_unknown_flow_returns_flow_not_found() {
        let err = build_streaming_plan(
            parse_simple_stream_source(),
            "test.axon",
            "NonexistentFlow",
            "stub",
        )
        .expect_err("unknown flow rejected");

        match err {
            PlanError::FlowNotFound { flow_name, available } => {
                assert_eq!(flow_name, "NonexistentFlow");
                assert_eq!(available, vec!["Chat".to_string()]);
            }
            other => panic!("expected FlowNotFound, got {other:?}"),
        }
    }

    #[test]
    fn build_plan_unparseable_source_returns_parse_error() {
        let err = build_streaming_plan(
            "not a valid axon source",
            "test.axon",
            "Chat",
            "stub",
        )
        .expect_err("garbage rejected");

        assert!(matches!(err, PlanError::Parse(_)));
    }

    #[test]
    fn build_plan_multi_step_flow_preserves_order() {
        let src = "flow MultiStep() -> Unit {\n\
                     step First { ask: \"one\" }\n\
                     step Second { ask: \"two\" }\n\
                     step Third { ask: \"three\" }\n\
                   }\n\
                   axonendpoint E { method: POST path: \"/m\" execute: MultiStep transport: sse }";
        let plan = build_streaming_plan(src, "test.axon", "MultiStep", "stub").unwrap();
        assert_eq!(plan.steps.len(), 3);
        assert_eq!(plan.steps[0].step_name, "First");
        assert_eq!(plan.steps[1].step_name, "Second");
        assert_eq!(plan.steps[2].step_name, "Third");
        assert_eq!(plan.steps[0].user_prompt, "one");
        assert_eq!(plan.steps[1].user_prompt, "two");
        assert_eq!(plan.steps[2].user_prompt, "three");
    }

    #[test]
    fn plan_fallback_slugs_are_stable_strings() {
        // Each variant has a documented slug. Drift in this match
        // surfaces in 33.x.g warning emission.
        assert_eq!(PlanFallback::AnchorConstraintsPresent.slug(), "anchor_constraints");
        assert_eq!(PlanFallback::LambdaApplyPresent.slug(), "lambda_apply");
        assert_eq!(PlanFallback::LetBindingPresent.slug(), "let_binding");
        assert_eq!(PlanFallback::UseToolPresent.slug(), "use_tool");
        assert_eq!(PlanFallback::HibernatePresent.slug(), "hibernate");
        assert_eq!(PlanFallback::PixPresent.slug(), "pix");
    }

    #[test]
    fn plan_is_deterministic_for_same_source() {
        let plan1 = build_streaming_plan(
            parse_simple_stream_source(),
            "test.axon",
            "Chat",
            "stub",
        )
        .unwrap();
        let plan2 = build_streaming_plan(
            parse_simple_stream_source(),
            "test.axon",
            "Chat",
            "stub",
        )
        .unwrap();
        assert_eq!(plan1, plan2, "plan builder is pure + deterministic");
    }

    #[test]
    fn streaming_step_eq_is_field_wise() {
        let a = StreamingStep {
            step_name: "X".into(),
            user_prompt: "y".into(),
            max_tokens: Some(100),
            temperature: Some(0.7),
            effect_policy: Some(BackpressurePolicy::DropOldest),
        };
        let b = a.clone();
        assert_eq!(a, b);
    }

    #[test]
    fn streaming_plan_includes_backend_name() {
        let plan = build_streaming_plan(
            parse_simple_stream_source(),
            "test.axon",
            "Chat",
            "anthropic",
        )
        .unwrap();
        assert_eq!(plan.backend_name, "anthropic");
    }

    #[test]
    fn empty_flow_body_produces_empty_step_list() {
        // Pathological but parseable case: empty flow body.
        let src = "flow Empty() -> Unit {\n\
                   }\n\
                   axonendpoint E { method: POST path: \"/e\" execute: Empty transport: sse }";
        let plan = build_streaming_plan(src, "test.axon", "Empty", "stub").unwrap();
        assert!(plan.steps.is_empty());
        assert_eq!(plan.flow_name, "Empty");
    }
}
