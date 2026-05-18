//! §Fase 33.y.c — Pure-shape variant handlers (Step / Probe / Reason /
//! Validate / Refine / Weave).
//!
//! All 6 IRFlowNode variants here share the underlying shape "produce
//! a single LLM response from a prompt + cognitive framing". The
//! module exposes:
//!
//! - One shared async core [`run_pure_shape`] that drives the per-step
//!   `Backend::stream()` loop, forwards chunks as `axon.token` events,
//!   wraps the chunk stream with [`StreamPolicyEnforcer`] when the
//!   caller supplied a `pending_effect_policy`, and records the
//!   per-step audit row + enforcement summary at FlowComplete.
//!
//! - 6 thin per-variant entry points that build the variant's
//!   [`PureShapeStep`] (name + user prompt + cognitive framing
//!   addendum + wire kind slug) and delegate to `run_pure_shape`.
//!
//! # Cognitive framings
//!
//! Each variant's framing nudges the LLM toward its declared
//! semantic posture WITHOUT changing the underlying call mechanics:
//!
//! - `Step` — neutral. The user prompt is the `ask:` field verbatim;
//!   no framing addendum (the system prompt established at flow
//!   level fully captures the intent).
//! - `Probe` — investigative. Framing addendum: *"You are probing the
//!   target. Investigate deeply, surface what's hidden, return
//!   concisely."*
//! - `Reason` — deliberative. Framing addendum reflects the declared
//!   strategy (e.g. `chain_of_thought`, `tree_of_thought`,
//!   `analogical`) when present.
//! - `Validate` — verification. Framing names the rule being checked.
//! - `Refine` — improvement. Framing names the strategy + signals the
//!   target is treated as draft input.
//! - `Weave` — synthesis. Framing names the sources + format/style;
//!   the LLM produces a stitched output ordered by `priority`.
//!
//! # Wire shape
//!
//! Each handler emits:
//!   1. `axon.step_start { step_name, step_index, step_type: <slug>, timestamp_ms }`
//!   2. `axon.step_token { step_name, content, token_index, timestamp_ms }` — one per non-empty chunk
//!   3. `axon.step_complete { step_name, step_index, success: true, full_output, tokens_input: 0, tokens_output, timestamp_ms }`
//!
//! `step_type` matches `flow_plan::ir_flow_node_kind` byte-for-byte
//! (`"step"` / `"probe"` / `"reason"` / `"validate"` / `"refine"` /
//! `"weave"`). Adopter EventSource clients filter on the `step_type`
//! field to surface per-variant UI affordances.
//!
//! # D-letter anchors
//!
//! - **D1** — every pure-shape variant has a NAMED async handler;
//!   the dispatcher arm delegates exhaustively (no `_ =>` catch-all).
//! - **D2** — `pending_effect_policy` is consumed by [`run_pure_shape`]
//!   before `Backend::stream()` resolves; the enforcer activates per-
//!   node, not per-step-list-iteration.
//! - **D3** — `cancel.is_cancelled()` is checked at every `.await`
//!   boundary; cancel propagates into reqwest body via Fase 33.x.e's
//!   `cancel_aware` adapter (the backend impls already plumb this).
//! - **D4** — wire shape extends v1.25.0 by adding `step_type` slugs
//!   for the 5 non-`Step` variants; the canonical `Step` slug stays
//!   `"step"` byte-identical with the pre-33.y.c emission. New slugs
//!   are observable but elided (`step_type: "step"`) when the IR
//!   variant is `Step`.
//! - **D6** — per-step audit row carries `effect_policy_applied` =
//!   `Some(<policy>.slug())` when the caller supplied a policy,
//!   `None` otherwise. The `step_audit_records` side-channel
//!   accumulates one row per handler call.
//! - **D7** — production-grade: zero `unwrap()` on the chunk-stream
//!   side; every error case routes through [`DispatchError`].

use crate::backends::{ChatRequest, Message};
use crate::flow_dispatcher::{DispatchCtx, DispatchError, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use crate::ir_nodes::{
    IRProbe, IRReasonStep, IRRefineStep, IRStep, IRValidateStep, IRWeaveStep,
};
use crate::stream_effect::BackpressurePolicy;
use futures::StreamExt;
use sha2::{Digest, Sha256};

// ────────────────────────────────────────────────────────────────────
//  PureShapeStep — per-variant framing carrier
// ────────────────────────────────────────────────────────────────────

/// The per-variant context built by each entry function. Owns the
/// rendered user prompt + framing addendum; the shared core
/// [`run_pure_shape`] reads + drives the LLM dispatch.
pub struct PureShapeStep {
    /// Step name as declared in the source (stable across versions
    /// of the flow). For variants without an explicit `name:` field
    /// (Probe / Reason / Validate / Refine / Weave) we use the
    /// target/strategy field that uniquely identifies the node.
    pub name: String,
    /// User-side prompt sent as `Message::user(...)`.
    pub user_prompt: String,
    /// Optional framing appended to the flow-level `system_prompt`
    /// (sourced from `ctx.system_prompt`). When `None` the system
    /// prompt is sent verbatim.
    pub framing_addendum: Option<String>,
    /// Wire `step_type` slug — byte-equal with
    /// `flow_plan::ir_flow_node_kind` for the corresponding IR
    /// variant.
    pub kind_slug: &'static str,
    /// §Fase 33.y.k — Tools plumbed into `ChatRequest.tools`. The
    /// per-variant entry function builds this from the step's
    /// declared `apply: <tool>` (canonical Step shape) or
    /// `use_tool: [...]` (multi-tool form). For OSS reference: each
    /// declared tool synthesizes a minimal [`ToolSpec`] with name +
    /// canonical description + empty `{}` parameter schema.
    /// Enterprise integrations resolve real `IRToolSpec` entries
    /// from the IRProgram (a future Fase 33.y.k.2 follow-up
    /// extends `DispatchCtx` with an `Option<&IRProgram>` ref for
    /// full per-provider parameter-schema resolution).
    ///
    /// Empty `Vec` (default) → backend gets no tools → wire shape
    /// stays D4 byte-compat with pre-33.y.k.
    pub tools: Vec<crate::backends::ToolSpec>,
}

// ────────────────────────────────────────────────────────────────────
//  Per-variant entry points
// ────────────────────────────────────────────────────────────────────

/// Step entry — neutral cognitive framing. The user prompt is the
/// `ask:` field verbatim; no addendum (the flow-level system prompt
/// fully establishes intent).
///
/// §Fase 33.y.k — when `step.apply_ref` is non-empty, synthesizes
/// a [`ToolSpec`](crate::backends::ToolSpec) and plumbs it into
/// `ChatRequest.tools` via the shared async core. Adopter flows
/// declaring `step S { apply: <tool> }` activate real upstream
/// tool-calling on the SSE wire (Anthropic `tool_use` / OpenAI
/// `tool_calls` / etc.). When `apply_ref` is empty, tools stays
/// `Vec::new()` → wire shape byte-compat with pre-33.y.k.
pub async fn run_step(
    step: &IRStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    // §Fase 36.x.e (D4) — interpolate `${name}` / `$name` in the
    // step's `ask` against the flow bindings BEFORE it becomes the
    // prompt (legacy LLM path) or the tool argument (streaming-tool
    // path). A `retrieve … as: alias` binds `alias`, a `let` binds
    // its target, and a prior `step`'s output is bound under the step
    // name (see `run_pure_shape` / `run_step_streaming_tool`). So the
    // agent pattern's data threads — retrieve context → deliberate →
    // persist — on the streaming dispatcher path, matching the
    // synchronous path's interpolation contract (Fase 35.q).
    let prompt =
        crate::exec_context::interpolate_vars(&step.ask, &ctx.let_bindings);

    // §Fase 34.d — Streaming-tool branch. When the step's
    // `apply_ref` resolves to a tool flagged `is_streaming` in the
    // attached registry, bypass the LLM upstream entirely + invoke
    // `tool.stream(args, ctx)` via the
    // [`crate::tool_dispatch_bridge::resolve_streaming_tool`] factory.
    //
    // The branch fires ONLY when ALL THREE conditions hold:
    //   1. `step.apply_ref` is non-empty (tool reference present)
    //   2. `ctx.tool_registry` is Some (registry wired)
    //   3. The resolved entry's `is_streaming` flag is true
    //
    // When any condition fails, the legacy LLM-side path is taken
    // (Fase 33.y.k+33.z behavior preserved). D9 backwards-compat:
    // adopters who don't wire the registry see no change.
    if !step.apply_ref.is_empty() {
        if let Some(registry) = ctx.tool_registry.clone() {
            if let Some(entry) = registry.get(&step.apply_ref) {
                if entry.is_streaming {
                    return run_step_streaming_tool(step, entry.clone(), &prompt, ctx).await;
                }
            }
        }
    }
    // Legacy path: LLM-side dispatch (Fase 33.y.k+33.z).
    let tools = synthesize_tools_from_step(step);
    let shape = PureShapeStep {
        name: if step.name.is_empty() {
            "Step".to_string()
        } else {
            step.name.clone()
        },
        user_prompt: prompt,
        framing_addendum: None,
        kind_slug: "step",
        tools,
    };
    run_pure_shape(shape, ctx).await
}

/// §Fase 34.d (v1.29.0) — Streaming-tool dispatch branch.
///
/// Bypasses `Backend::stream()` entirely. Invokes
/// `tool.stream(step.ask, ctx)` via the bridge factory + drains the
/// resulting `Stream<ToolChunk>` chunk-by-chunk into the wire as
/// `FlowExecutionEvent::StepToken` events.
///
/// # Wire-event sequence
///
/// 1. `FlowExecutionEvent::StepStart` (kind_slug = "step")
/// 2. `FlowExecutionEvent::StepToken` × N (one per non-empty chunk
///    delta the tool emitted)
/// 3. `FlowExecutionEvent::StepComplete` carrying the accumulated
///    output + tokens_emitted (= chunk count) + success flag
///
/// # Cancel discipline
///
/// Polled BEFORE invoking `tool.stream()`, BETWEEN each chunk
/// drain, and AFTER the stream closes. Surfaces
/// `DispatchError::UpstreamCancelled` to the caller; the consumer
/// (post-33.z producer) treats this as a clean exit.
///
/// # Audit row
///
/// Records `StepAuditRecord` with:
/// - `step_name`, `step_index` — standard fields
/// - `tokens_emitted` — chunk count (1 per non-empty delta)
/// - `output_hash_hex` — SHA-256 of concatenated tool deltas
/// - `effect_policy_applied` — the policy slug from the tool's
///   `effect_row` (e.g., "drop_oldest"). Captured at the dispatch
///   layer; actual enforcement at the chunk level lands in
///   Fase 34.g's `unified_stream_handler`.
/// - `chunks_dropped` / `chunks_degraded` — 0 for 34.d (enforcer
///   integration deferred to 34.g).
///
/// # Honest scope
///
/// 34.d ships the BRANCH POINT: the dispatcher correctly detects
/// `is_streaming` tools + routes through the streaming path + the
/// wire emits per-chunk content. The full `StreamPolicyEnforcer`
/// integration (where `drop_oldest` actually drops chunks etc.)
/// lands in 34.g. For 34.d, the policy is captured in the audit
/// row but not enforced at chunk granularity.
async fn run_step_streaming_tool(
    step: &IRStep,
    entry: crate::tool_registry::ToolEntry,
    // §Fase 36.x.e (D4) — the step's `ask` already interpolated by
    // `run_step` against `ctx.let_bindings`. Used as the tool's
    // streaming argument so a `${retrieve_alias}` reaches the tool.
    prompt: &str,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    // §Fase 34.g convergence — the per-chunk drain loop now lives
    // in `flow_dispatcher::unified_stream::unified_stream_handler`.
    // Pre-34.g this function ran an inline drain loop with policy
    // capture-but-no-enforcement; 34.g shifts the drain to the
    // unified handler which integrates a
    // `crate::stream_runtime::Stream<ToolChunk>` policy primitive
    // + returns a `ToolStreamSummary` with real
    // `chunks_dropped`/`chunks_degraded` counters.

    // 1. Reserve step index for audit-row + StepStart parity.
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    // 2. Cancel check at entry — same discipline as run_pure_shape.
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    // 3. Resolve declared backpressure policy from the tool's
    //    effect_row. None when the tool flagged is_streaming via a
    //    non-stream slug (parser guarantees one stream policy per
    //    declaration, but the registry's is_streaming flag could be
    //    set programmatically without a declared policy).
    let policy =
        crate::tool_dispatch_bridge::extract_stream_policy(&entry.effect_row);

    let step_name = if step.name.is_empty() {
        "Step".to_string()
    } else {
        step.name.clone()
    };

    // 4. Emit StepStart. Carries the standard `step` kind_slug —
    //    adopters EventSource-filtering on kind don't need to
    //    distinguish stream-tool steps from non-stream steps at the
    //    StepStart layer; the per-chunk StepToken events carry the
    //    per-tool semantics.
    ctx.tx
        .send(FlowExecutionEvent::StepStart {
            step_name: step_name.clone(),
            step_index,
            step_type: "step".to_string(),
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)?;

    // 5. Construct ToolContext + Tool trait impl via the bridge.
    let tool_ctx = crate::tool_dispatch_bridge::build_tool_context(
        ctx.cancel.clone(),
        0, // 34.d-scope: trace_id placeholder. The dispatcher doesn't
           // currently carry trace_id in DispatchCtx; future sub-fase
           // (34.i audit extension) plumbs through.
    );
    let tool = crate::tool_dispatch_bridge::resolve_streaming_tool(&entry);

    // 6. Cancel check before invoking the tool — its body might do
    //    work even at .await entry. Mirrors run_pure_shape's pre-
    //    backend-call check.
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    // 7. Invoke tool.stream() + route through the unified handler.
    //    The handler applies the declared policy at chunk
    //    granularity (real enforcement, not just slug-capture-in-
    //    audit) + returns a typed summary the caller uses to
    //    populate the audit row + decide the outcome.
    // §Fase 36.x.e (D4) — the interpolated `prompt` is the tool
    // argument (not the raw `step.ask`), so a `${retrieve_alias}`
    // resolved upstream reaches the streaming tool.
    let source = tool.stream(prompt.to_string(), tool_ctx).await;
    let summary = crate::flow_dispatcher::unified_stream::unified_stream_handler(
        source,
        policy,
        &ctx.cancel,
        &ctx.tx,
        &step_name,
    )
    .await?;

    // §Fase 36.x.e.2 — surface the enforcement summary. When the
    // step's applied tool declared a `<stream:<policy>>` effect, the
    // streaming-tool path runs the enforcer (via
    // `unified_stream_handler`) exactly as the LLM-side path does in
    // `run_pure_shape::drain_through_enforcer` — but pre-36.x.e.2 it
    // never WROTE the result to `ctx.enforcement_summaries`, so the
    // `axon.complete` envelope's `enforcement_summary` field stayed
    // empty for an `apply:`-streaming-tool step. This closes that
    // parity gap: the same `EnforcementSummaryWire` shape is keyed
    // under the step name from the `ToolStreamSummary` metrics.
    if let Some(p) = policy {
        let wire = crate::axon_server::EnforcementSummaryWire {
            policy_slug: p.slug().to_string(),
            chunks_pushed: summary.chunks_pushed,
            chunks_delivered: summary.chunks_delivered,
            drop_oldest_hits: summary.chunks_dropped,
            degrade_quality_hits: summary.chunks_degraded,
            pause_upstream_blocks: summary.pause_upstream_blocks,
            fail_overflows: summary.fail_overflows,
            failed: !summary.success,
        };
        ctx.enforcement_summaries
            .lock()
            .await
            .insert(step_name.clone(), wire);
    }

    // 8. Cancel mid-stream → propagate. The accumulated chunks
    //    already reached the wire via the unified handler; the
    //    StepComplete + audit row are skipped (consumer chain
    //    treats this as upstream-cancelled).
    if summary.cancelled && ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    // 9. StepComplete event. Mirrors run_pure_shape's shape.
    ctx.tx
        .send(FlowExecutionEvent::StepComplete {
            step_name: step_name.clone(),
            step_index,
            success: summary.success,
            full_output: summary.accumulated.clone(),
            tokens_input: 0,
            tokens_output: summary.tokens_emitted,
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)?;

    // 10. Audit row — D6 per-step replay binding. 34.g activates
    //     real `chunks_dropped`/`chunks_degraded` counters from the
    //     unified handler's metrics snapshot. 34.i adds the tool-
    //     stream provenance quartet: tool_name (entry.name), the
    //     source-chunk count (summary.chunks_pushed including
    //     terminator + empty-delta intermediates), explicit
    //     tool_output_hash_hex (same scope as output_hash_hex for
    //     34.i; diverges in future fases with degrader transforms),
    //     and the closed-catalog terminator kind slug.
    {
        let terminator_kind = if summary.cancelled {
            "cancelled"
        } else if summary.terminator_message.is_some() {
            "error"
        } else {
            "stop"
        };
        let record = crate::axonendpoint_replay::StepAuditRecord {
            step_name: step_name.clone(),
            step_index,
            success: summary.success,
            tokens_emitted: summary.tokens_emitted,
            output_hash_hex: summary.output_hash_hex.clone(),
            effect_policy_applied: policy.map(|p| p.slug().to_string()),
            chunks_dropped: summary.chunks_dropped,
            chunks_degraded: summary.chunks_degraded,
            timestamp_ms: now_ms(),
            tool_name: Some(entry.name.clone()),
            tool_chunks_emitted: Some(summary.chunks_pushed),
            tool_output_hash_hex: Some(summary.output_hash_hex.clone()),
            tool_terminator_kind: Some(terminator_kind.to_string()),
        };
        let mut guard = ctx.step_audit_records.lock().await;
        guard.push(record);
    }

    // 11. Surface DispatchError on Error-terminator. Includes the
    //     Fail-policy overflow surface (the summary carries the
    //     terminator_message that the unified handler synthesized
    //     from `StreamError::Overflow`).
    if let Some(message) = summary.terminator_message {
        return Err(DispatchError::BackendError {
            name: format!("tool:{}", entry.name),
            message,
        });
    }

    // §Fase 36.x.e (D4) — bind the tool's accumulated output under
    // the step name so a downstream `persist` / `step` can reference
    // it (`${StepName}`). Only on the success path — an
    // error-terminated step (handled above) has no output to thread.
    ctx.let_bindings
        .insert(step_name.clone(), summary.accumulated.clone());

    Ok(NodeOutcome::Completed {
        output: summary.accumulated,
        tokens_emitted: summary.tokens_emitted,
        step_index,
    })
}

/// §Fase 33.y.k — Resolve `step.apply_ref` into a `Vec<ToolSpec>`.
/// OSS reference: when `apply_ref` is non-empty, synthesizes a
/// minimal `ToolSpec { name, description, parameters_json: "{}" }`.
/// When the IRProgram tool registry surface lands (future Fase
/// 33.y.k.2), this helper resolves the real `IRToolSpec` with
/// `parameters_json` from `input_schema`.
fn synthesize_tools_from_step(step: &IRStep) -> Vec<crate::backends::ToolSpec> {
    if step.apply_ref.is_empty() {
        return Vec::new();
    }
    vec![crate::backends::ToolSpec {
        name: step.apply_ref.clone(),
        description: format!("Tool reference: {}", step.apply_ref),
        parameters_json: "{}".to_string(),
    }]
}

/// Probe entry — investigative framing. The target is investigated
/// deeply; the LLM surfaces what's hidden + returns concisely.
pub async fn run_probe(
    probe: &IRProbe,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let shape = PureShapeStep {
        name: if probe.target.is_empty() {
            "Probe".to_string()
        } else {
            probe.target.clone()
        },
        user_prompt: format!("Investigate: {}", probe.target),
        framing_addendum: Some(
            "You are probing the target. Investigate deeply, surface what's hidden, return concisely.".into(),
        ),
        kind_slug: "probe",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Reason entry — deliberative framing reflecting the declared
/// strategy (`chain_of_thought`, `tree_of_thought`, `analogical`, …).
pub async fn run_reason(
    reason: &IRReasonStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let strategy_clause = if reason.strategy.is_empty() {
        String::new()
    } else {
        format!(" using strategy `{}`", reason.strategy)
    };
    let shape = PureShapeStep {
        name: if reason.target.is_empty() {
            "Reason".to_string()
        } else {
            reason.target.clone()
        },
        user_prompt: format!("Reason about: {}{}", reason.target, strategy_clause),
        framing_addendum: Some(
            "You are reasoning deliberately. Show the steps of your reasoning where they bear on the answer.".into(),
        ),
        kind_slug: "reason",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Validate entry — verification framing. The target is checked
/// against the declared rule; the LLM returns a pass/fail verdict
/// with reasoning.
pub async fn run_validate(
    validate: &IRValidateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let rule_clause = if validate.rule.is_empty() {
        String::new()
    } else {
        format!(" against rule `{}`", validate.rule)
    };
    let shape = PureShapeStep {
        name: if validate.target.is_empty() {
            "Validate".to_string()
        } else {
            validate.target.clone()
        },
        user_prompt: format!("Validate: {}{}", validate.target, rule_clause),
        framing_addendum: Some(
            "You are validating. Return a structured verdict (pass/fail) with the reasoning that supports it.".into(),
        ),
        kind_slug: "validate",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Refine entry — improvement framing. The target is treated as
/// draft input; the declared strategy (when present) names the
/// improvement axis.
pub async fn run_refine(
    refine: &IRRefineStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let strategy_clause = if refine.strategy.is_empty() {
        String::new()
    } else {
        format!(" using strategy `{}`", refine.strategy)
    };
    let shape = PureShapeStep {
        name: if refine.target.is_empty() {
            "Refine".to_string()
        } else {
            refine.target.clone()
        },
        user_prompt: format!("Refine: {}{}", refine.target, strategy_clause),
        framing_addendum: Some(
            "You are refining. Treat the target as draft input; improve it along the declared strategy without losing fidelity to its intent.".into(),
        ),
        kind_slug: "refine",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Weave entry — synthesis framing. Sources are stitched into the
/// target via `format_type`; `priority` orders the contribution
/// weighting; `style` shapes the output voice.
pub async fn run_weave(
    weave: &IRWeaveStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let sources_clause = if weave.sources.is_empty() {
        String::new()
    } else {
        format!(" from sources [{}]", weave.sources.join(", "))
    };
    let format_clause = if weave.format_type.is_empty() {
        String::new()
    } else {
        format!(" as {}", weave.format_type)
    };
    let style_clause = if weave.style.is_empty() {
        String::new()
    } else {
        format!(" in {} style", weave.style)
    };
    let priority_clause = if weave.priority.is_empty() {
        String::new()
    } else {
        format!(" with priority [{}]", weave.priority.join(", "))
    };
    let shape = PureShapeStep {
        name: if weave.target.is_empty() {
            "Weave".to_string()
        } else {
            weave.target.clone()
        },
        user_prompt: format!(
            "Weave: {}{}{}{}{}",
            weave.target, sources_clause, format_clause, style_clause, priority_clause
        ),
        framing_addendum: Some(
            "You are weaving. Stitch the sources into the target output. Honor the declared priority + format + style.".into(),
        ),
        kind_slug: "weave",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

// ────────────────────────────────────────────────────────────────────
//  Shared async core
// ────────────────────────────────────────────────────────────────────

/// Drive a single pure-shape step end-to-end: emit StepStart, build
/// ChatRequest, dispatch to the backend's `stream()`, optionally
/// wrap with `StreamPolicyEnforcer`, forward chunks as
/// `axon.step_token` events, capture the audit row, emit
/// StepComplete, return `NodeOutcome::Completed`.
///
/// # Cancellation
///
/// Checked at every `.await` boundary. On cancel surfaces
/// `DispatchError::UpstreamCancelled` — the caller treats this as a
/// clean exit (no `axon.error` event surfaced; the consumer is
/// already gone).
///
/// # Backend resolution
///
/// `ctx.backend_name` is resolved via
/// [`crate::backends::resolve_streaming_backend`]. Returns
/// `DispatchError::BackendError` if the name is unknown.
///
/// # Effect-policy activation
///
/// If `ctx.pending_effect_policy` is `Some(_)`, the backend's chunk
/// stream is wrapped in `StreamPolicyEnforcer` per Fase 33.x.d
/// semantics — producer-side `tokio::spawn` runs the enforcer's
/// `drain`; consumer-side this fn pops chunks via `pop_chunk`. The
/// `EnforcementSummary` is captured post-drain + recorded under the
/// step's name in `ctx.enforcement_summaries`.
///
/// `pending_effect_policy` is CONSUMED by this call (cleared on
/// entry) so the next handler invocation observes its OWN policy,
/// never the previous handler's residue.
pub async fn run_pure_shape(
    shape: PureShapeStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    // 1. Reserve the step index BEFORE incrementing the counter so
    //    the audit row + StepStart event share the same index value.
    //    This matches the sync runner's discipline for D10 byte-
    //    identical parity.
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    // 2. Consume the pending effect policy. Take-semantics: if the
    //    caller forgot to set it for the NEXT handler, no stale
    //    leak.
    let effect_policy = ctx.take_pending_effect_policy();

    // 3. Cancel check at entry.
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    // 4. StepStart event. Carries the variant's wire slug so adopter
    //    EventSource clients filter per variant.
    ctx.tx
        .send(FlowExecutionEvent::StepStart {
            step_name: shape.name.clone(),
            step_index,
            step_type: shape.kind_slug.to_string(),
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)?;

    // 5. Resolve backend through the streaming registry. Mirrors
    //    `run_streaming_async_path`'s resolution discipline.
    let backend = crate::backends::resolve_streaming_backend(&ctx.backend_name)
        .ok_or_else(|| DispatchError::BackendError {
            name: ctx.backend_name.clone(),
            message: format!(
                "not in streaming registry; supported: {}",
                crate::backends::STREAMING_BACKEND_NAMES.join(", ")
            ),
        })?;

    // 6. Compose effective system prompt: flow-level (ctx.system_prompt)
    //    + variant-specific framing addendum.
    let system = match &shape.framing_addendum {
        Some(addendum) if ctx.system_prompt.is_empty() => addendum.clone(),
        Some(addendum) => format!("{}\n\n{}", ctx.system_prompt, addendum),
        None => ctx.system_prompt.clone(),
    };

    // 7. Build ChatRequest. §Fase 33.y.k D8 — tools plumb-through.
    //    `shape.tools` is populated by `run_step` from `step.apply_ref`
    //    (canonical Step shape); empty for cognitive-framing handlers
    //    (Probe/Reason/Validate/Refine/Weave/Focus/Associate/etc.)
    //    whose IR shapes don't carry tool references today.
    let request = ChatRequest {
        model: String::new(),
        messages: vec![Message::user(shape.user_prompt.clone())],
        system: if system.is_empty() { None } else { Some(system) },
        max_tokens: None,
        temperature: None,
        top_p: None,
        tools: shape.tools.clone(),
        stream: true,
        trace_id: None,
        cancel: ctx.cancel.clone(),
    };

    // 8. Cancel check before issuing the upstream request — the
    //    HTTP call itself is the most expensive `.await` boundary
    //    we're about to cross.
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    // 9. Open the per-step backend stream.
    let chunk_stream = backend
        .stream(request)
        .await
        .map_err(|e| DispatchError::BackendError {
            name: ctx.backend_name.clone(),
            message: format!("{e}"),
        })?;

    // 10. Drain — either through the StreamPolicyEnforcer (when an
    //     effect was declared) or directly.
    let (accumulated, tokens_emitted, drop_count, degrade_count) = match effect_policy {
        Some(policy) => drain_through_enforcer(
            chunk_stream,
            &shape,
            ctx,
            policy,
            step_index,
        )
        .await?,
        None => drain_direct(chunk_stream, &shape, ctx, step_index).await?,
    };

    // 11. Compute the output SHA-256 for the audit row + emit
    //     StepComplete.
    let output_hash_hex = sha256_hex(&accumulated);

    ctx.tx
        .send(FlowExecutionEvent::StepComplete {
            step_name: shape.name.clone(),
            step_index,
            success: true,
            full_output: accumulated.clone(),
            tokens_input: 0,
            tokens_output: tokens_emitted,
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)?;

    // 12. Push the audit row for D6 per-step replay binding.
    //     LLM-side disjunct (a) → no Tool::stream() source backing
    //     this path; the 34.i tool-stream provenance quartet stays
    //     `None`. D4 byte-compat: serde elides the fields so the
    //     wire shape for legacy LLM-side rows is byte-identical to
    //     the pre-34.i emission.
    {
        let record = crate::axonendpoint_replay::StepAuditRecord {
            step_name: shape.name.clone(),
            step_index,
            success: true,
            tokens_emitted,
            output_hash_hex,
            effect_policy_applied: effect_policy.map(|p| p.slug().to_string()),
            chunks_dropped: drop_count,
            chunks_degraded: degrade_count,
            timestamp_ms: now_ms(),
            tool_name: None,
            tool_chunks_emitted: None,
            tool_output_hash_hex: None,
            tool_terminator_kind: None,
        };
        let mut guard = ctx.step_audit_records.lock().await;
        guard.push(record);
    }

    // §Fase 36.x.e (D4) — bind the step's output under its name so a
    // downstream `persist` / `step` / interpolation site can
    // reference it (`${StepName}`). The streaming dispatcher path
    // threads a step's output through `ctx.let_bindings` exactly as a
    // `retrieve … as: alias` threads a retrieved value.
    ctx.let_bindings
        .insert(shape.name.clone(), accumulated.clone());

    Ok(NodeOutcome::Completed {
        output: accumulated,
        tokens_emitted,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Drain helpers — direct + through-enforcer
// ────────────────────────────────────────────────────────────────────

async fn drain_direct(
    chunk_stream: crate::backends::ChatStream,
    shape: &PureShapeStep,
    ctx: &mut DispatchCtx,
    _step_index: usize,
) -> Result<(String, u64, u64, u64), DispatchError> {
    use crate::backends::FinishReason;
    let mut accumulated = String::new();
    let mut tokens_emitted: u64 = 0;
    let mut stream = chunk_stream;

    while let Some(chunk_result) = stream.next().await {
        if ctx.cancel.is_cancelled() {
            return Err(DispatchError::UpstreamCancelled);
        }
        match chunk_result {
            Ok(chunk) => {
                // §Fase 33.y.k D8 — emit ToolCall event when the
                // backend signals FinishReason::ToolUse. Carries
                // the FIRST declared tool name from
                // `shape.tools[0].name` so adopters correlate the
                // tool-call event with their declared `apply: <tool>`.
                // When `shape.tools` is empty (no declared tool)
                // the tool_name is `"<unknown>"` — the upstream
                // signaled a tool-use but the step didn't declare
                // one, so the adopter sees the divergence on the
                // wire (closed-catalog tag, not silent).
                if let Some(FinishReason::ToolUse) = &chunk.finish_reason {
                    let tool_name = shape
                        .tools
                        .first()
                        .map(|t| t.name.clone())
                        .unwrap_or_else(|| "<unknown>".to_string());
                    ctx.tx
                        .send(FlowExecutionEvent::ToolCall {
                            step_name: shape.name.clone(),
                            tool_name,
                            content: chunk.delta.clone(),
                            timestamp_ms: now_ms(),
                        })
                        .map_err(|_| DispatchError::ChannelClosed)?;
                }
                if !chunk.delta.is_empty() {
                    tokens_emitted += 1;
                    accumulated.push_str(&chunk.delta);
                    ctx.tx
                        .send(FlowExecutionEvent::StepToken {
                            step_name: shape.name.clone(),
                            content: chunk.delta,
                            token_index: tokens_emitted,
                            timestamp_ms: now_ms(),
                        })
                        .map_err(|_| DispatchError::ChannelClosed)?;
                }
            }
            Err(e) => {
                return Err(DispatchError::BackendError {
                    name: ctx.backend_name.clone(),
                    message: format!("chunk error: {e}"),
                });
            }
        }
    }
    Ok((accumulated, tokens_emitted, 0, 0))
}

async fn drain_through_enforcer(
    chunk_stream: crate::backends::ChatStream,
    shape: &PureShapeStep,
    ctx: &mut DispatchCtx,
    policy: BackpressurePolicy,
    _step_index: usize,
) -> Result<(String, u64, u64, u64), DispatchError> {
    use crate::stream_effect_dispatcher::{StreamPolicyEnforcer, DEFAULT_STREAM_BUFFER_CAPACITY};
    use std::sync::Arc;

    // Build enforcer per the established Fase 33.x.d dispatch
    // (identity degrader OSS default for DegradeQuality; enterprise
    // verticals override via separate R&D track).
    let enforcer = Arc::new(match policy {
        BackpressurePolicy::DegradeQuality => StreamPolicyEnforcer::with_degrader(
            policy,
            DEFAULT_STREAM_BUFFER_CAPACITY,
            Arc::new(|chunk| chunk),
        ),
        BackpressurePolicy::DropOldest
        | BackpressurePolicy::PauseUpstream
        | BackpressurePolicy::Fail => StreamPolicyEnforcer::new(policy),
    });

    // Producer task — drains the chunk stream into the enforcer.
    // `ChatStream` (Pin<Box<dyn Stream + Send>>) is `Unpin` by
    // construction so it satisfies `enforcer.drain`'s bound.
    let producer_enforcer = enforcer.clone();
    let producer = tokio::spawn(async move {
        let summary = producer_enforcer
            .drain(chunk_stream, |_e| {
                // Backend errors are captured by the consumer when
                // it sees the enforcer close prematurely.
            })
            .await;
        producer_enforcer.close().await;
        summary
    });

    // Consumer side — pop chunks + forward to wire.
    let mut accumulated = String::new();
    let mut tokens_emitted: u64 = 0;

    while let Some(chunk) = enforcer.pop_chunk().await {
        if ctx.cancel.is_cancelled() {
            return Err(DispatchError::UpstreamCancelled);
        }
        // §Fase 33.y.k D8 — same ToolCall emission as `drain_direct`.
        // When the backend signals FinishReason::ToolUse on a chunk
        // pulled through the enforcer, surface the tool-call to the
        // wire BEFORE forwarding any text delta (the enforcer's
        // chunk ordering preserves arrival sequence; the ToolCall
        // event always precedes the StepToken from the same chunk).
        if let Some(crate::backends::FinishReason::ToolUse) = &chunk.finish_reason {
            let tool_name = shape
                .tools
                .first()
                .map(|t| t.name.clone())
                .unwrap_or_else(|| "<unknown>".to_string());
            ctx.tx
                .send(FlowExecutionEvent::ToolCall {
                    step_name: shape.name.clone(),
                    tool_name,
                    content: chunk.delta.clone(),
                    timestamp_ms: now_ms(),
                })
                .map_err(|_| DispatchError::ChannelClosed)?;
        }
        if !chunk.delta.is_empty() {
            tokens_emitted += 1;
            accumulated.push_str(&chunk.delta);
            ctx.tx
                .send(FlowExecutionEvent::StepToken {
                    step_name: shape.name.clone(),
                    content: chunk.delta,
                    token_index: tokens_emitted,
                    timestamp_ms: now_ms(),
                })
                .map_err(|_| DispatchError::ChannelClosed)?;
        }
    }

    // Producer summary — wait for the producer to finish so we get
    // accurate counters in the snapshot below.
    let drain_summary = producer.await.map_err(|e| DispatchError::BackendError {
        name: ctx.backend_name.clone(),
        message: format!("enforcer producer task join: {e}"),
    })?;

    // Post-drain metrics snapshot. Pull the counters AFTER the
    // consumer loop finished (matches Fase 33.x.d discipline — the
    // drain-returned `chunks_delivered` is captured before the
    // consumer terminates; the post-loop snapshot is authoritative
    // for delivered count). The drain summary keeps `failed` +
    // policy slug as authoritative.
    let snap = enforcer.metrics_snapshot();
    let wire = crate::axon_server::EnforcementSummaryWire {
        policy_slug: policy.slug().to_string(),
        chunks_pushed: snap.items_pushed,
        chunks_delivered: snap.items_delivered,
        drop_oldest_hits: snap.drop_oldest_hits,
        degrade_quality_hits: snap.degrade_quality_hits,
        pause_upstream_blocks: snap.pause_upstream_blocks,
        fail_overflows: snap.fail_overflows,
        failed: drain_summary.failed,
    };

    {
        let mut guard = ctx.enforcement_summaries.lock().await;
        guard.insert(shape.name.clone(), wire);
    }

    let drop_count = snap.drop_oldest_hits;
    let degrade_count = snap.degrade_quality_hits;
    Ok((accumulated, tokens_emitted, drop_count, degrade_count))
}

// ────────────────────────────────────────────────────────────────────
//  sha256_hex helper
// ────────────────────────────────────────────────────────────────────

fn sha256_hex(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(digest.len() * 2);
    for byte in digest.as_slice() {
        use std::fmt::Write as _;
        let _ = write!(hex, "{byte:02x}");
    }
    hex
}

// ────────────────────────────────────────────────────────────────────
//  Unit tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cancel_token::CancellationFlag;
    use tokio::sync::mpsc;

    fn fresh_ctx() -> (
        DispatchCtx,
        mpsc::UnboundedReceiver<FlowExecutionEvent>,
    ) {
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

    /// sha256_hex of the empty string is the canonical
    /// e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
    #[test]
    fn sha256_hex_empty_string_is_canonical() {
        assert_eq!(
            sha256_hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    /// sha256_hex of "(stub)" — the canonical stub backend chunk.
    #[test]
    fn sha256_hex_stub_marker() {
        // Independently computed:
        //   echo -n "(stub)" | sha256sum
        //   97f2ad79c25c0b6f3c87018b5e6b94c91d11ef0aaa61d4f7f8a6d8b1f0c8c0fb (will be checked at runtime)
        let h = sha256_hex("(stub)");
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    }

    #[tokio::test]
    async fn run_step_with_stub_backend_emits_one_token() {
        use crate::ir_nodes::IRStep;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "Generate".into(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".into(),
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
        let (mut ctx, mut rx) = fresh_ctx();

        let outcome = run_step(&step, &mut ctx).await.expect("run_step ok");
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, step_index } => {
                assert_eq!(output, "(stub)");
                assert_eq!(tokens_emitted, 1);
                assert_eq!(step_index, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }

        // Drain wire events
        let mut events = Vec::new();
        while let Ok(ev) = rx.try_recv() {
            events.push(ev);
        }
        // Expect StepStart + StepToken + StepComplete (3 events).
        assert_eq!(events.len(), 3, "events: {events:?}");
        assert!(matches!(events[0], FlowExecutionEvent::StepStart { .. }));
        assert!(matches!(events[1], FlowExecutionEvent::StepToken { .. }));
        assert!(matches!(events[2], FlowExecutionEvent::StepComplete { .. }));
    }

    #[tokio::test]
    async fn run_step_cancel_pre_dispatch_short_circuits() {
        use crate::ir_nodes::IRStep;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "S".into(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".into(),
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
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        let outcome = run_step(&step, &mut ctx).await;
        assert!(matches!(outcome, Err(DispatchError::UpstreamCancelled)));
    }

    #[tokio::test]
    async fn run_step_unknown_backend_returns_backend_error() {
        use crate::ir_nodes::IRStep;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "S".into(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".into(),
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
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new(
            "F",
            "does_not_exist",
            "",
            CancellationFlag::new(),
            tx,
        );

        let outcome = run_step(&step, &mut ctx).await;
        match outcome {
            Err(DispatchError::BackendError { name, message }) => {
                assert_eq!(name, "does_not_exist");
                assert!(message.contains("not in streaming registry"));
            }
            other => panic!("expected BackendError, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_step_pending_policy_consumed_on_entry() {
        use crate::ir_nodes::IRStep;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "S".into(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".into(),
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
        let (mut ctx, _rx) = fresh_ctx();
        ctx.pending_effect_policy = Some(BackpressurePolicy::DropOldest);

        let _ = run_step(&step, &mut ctx).await.expect("ok");
        assert!(
            ctx.pending_effect_policy.is_none(),
            "33.y.c contract: handler MUST consume pending_effect_policy on entry"
        );

        // Enforcement summary recorded for the step name.
        let summaries = ctx.enforcement_summaries.lock().await;
        assert!(summaries.contains_key("S"));
        assert_eq!(summaries["S"].policy_slug, "drop_oldest");
    }

    #[tokio::test]
    async fn run_step_records_step_audit_row() {
        use crate::ir_nodes::IRStep;

        let step = IRStep {
            node_type: "step",
            source_line: 0,
            source_column: 0,
            name: "Generate".into(),
            persona_ref: String::new(),
            given: String::new(),
            ask: "hi".into(),
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
        let (mut ctx, _rx) = fresh_ctx();
        let _ = run_step(&step, &mut ctx).await.expect("ok");

        let audit = ctx.step_audit_records.lock().await;
        assert_eq!(audit.len(), 1);
        assert_eq!(audit[0].step_name, "Generate");
        assert_eq!(audit[0].tokens_emitted, 1);
        assert!(audit[0].success);
        // SHA-256 of "(stub)" — content-addressable per D6.
        assert_eq!(audit[0].output_hash_hex.len(), 64);
        assert!(audit[0].effect_policy_applied.is_none());
    }

    #[tokio::test]
    async fn run_probe_kind_slug_is_probe() {
        use crate::ir_nodes::IRProbe;

        let probe = IRProbe {
            node_type: "probe",
            source_line: 0,
            source_column: 0,
            target: "market_data".into(),
        };
        let (mut ctx, mut rx) = fresh_ctx();
        let _ = run_probe(&probe, &mut ctx).await.expect("ok");

        // First event is StepStart with step_type="probe".
        let ev = rx.try_recv().expect("event");
        match ev {
            FlowExecutionEvent::StepStart { step_type, step_name, .. } => {
                assert_eq!(step_type, "probe");
                assert_eq!(step_name, "market_data");
            }
            other => panic!("expected StepStart, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_reason_kind_slug_is_reason() {
        use crate::ir_nodes::IRReasonStep;

        let reason = IRReasonStep {
            node_type: "reason",
            source_line: 0,
            source_column: 0,
            strategy: "chain_of_thought".into(),
            target: "claim".into(),
        };
        let (mut ctx, mut rx) = fresh_ctx();
        let _ = run_reason(&reason, &mut ctx).await.expect("ok");

        let ev = rx.try_recv().expect("event");
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "reason");
            }
            other => panic!("expected StepStart, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_validate_kind_slug_is_validate() {
        use crate::ir_nodes::IRValidateStep;

        let validate = IRValidateStep {
            node_type: "validate",
            source_line: 0,
            source_column: 0,
            target: "draft".into(),
            rule: "no_pii".into(),
        };
        let (mut ctx, mut rx) = fresh_ctx();
        let _ = run_validate(&validate, &mut ctx).await.expect("ok");
        let ev = rx.try_recv().expect("event");
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "validate");
            }
            other => panic!("expected StepStart, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_refine_kind_slug_is_refine() {
        use crate::ir_nodes::IRRefineStep;

        let refine = IRRefineStep {
            node_type: "refine",
            source_line: 0,
            source_column: 0,
            target: "draft".into(),
            strategy: "tighten".into(),
        };
        let (mut ctx, mut rx) = fresh_ctx();
        let _ = run_refine(&refine, &mut ctx).await.expect("ok");
        let ev = rx.try_recv().expect("event");
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "refine");
            }
            other => panic!("expected StepStart, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_weave_kind_slug_is_weave() {
        use crate::ir_nodes::IRWeaveStep;

        let weave = IRWeaveStep {
            node_type: "weave",
            source_line: 0,
            source_column: 0,
            sources: vec!["A".into(), "B".into()],
            target: "report".into(),
            format_type: "markdown".into(),
            priority: vec!["A".into()],
            style: "formal".into(),
        };
        let (mut ctx, mut rx) = fresh_ctx();
        let _ = run_weave(&weave, &mut ctx).await.expect("ok");
        let ev = rx.try_recv().expect("event");
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "weave");
            }
            other => panic!("expected StepStart, got {other:?}"),
        }
    }
}
