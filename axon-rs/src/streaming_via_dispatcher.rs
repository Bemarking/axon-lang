//! §Fase 33.z.b — Streaming-via-dispatcher graft skeleton.
//!
//! This module ships the alternative production-path producer that
//! routes adopter traffic through `flow_dispatcher::dispatch_node`
//! end-to-end. It is the v1.27.0 lift of the 33.y structurally-
//! complete dispatcher (45/45 IRFlowNode variants with compiler-
//! enforced exhaustive match) from the test surface to the
//! production SSE wire.
//!
//! # Why a new module, not a `server_execute_streaming` rewrite?
//!
//! The 33.z.b sub-fase ships the producer behind a feature flag
//! (`AXON_STREAMING_VIA_DISPATCHER`, default OFF) so v1.27.0-alpha
//! adopters who DON'T opt in see byte-identical v1.26.0 wire
//! behavior (D4 safety net during the migration). When the flag is
//! ON, `server_execute_streaming` invokes
//! [`run_streaming_via_dispatcher`] instead of the v1.26.0 paths
//! (`run_streaming_async_path` for canonical Step + `run_streaming_legacy_path`
//! for everything else). Sub-fase 33.z.c flips the flag default
//! from OFF to ON for v1.27.0 stable; sub-fase 33.z.e deletes the
//! flag + the legacy path entirely.
//!
//! Mirrors the proven Fase 33.x.h opt-in BPE chunking pattern —
//! land a new hot path behind a flag, validate with adopters,
//! flip default, then retire the legacy path.
//!
//! # Architecture
//!
//! The producer:
//!
//! 1. Emits `FlowExecutionEvent::FlowStart` on the same mpsc channel
//!    the SSE consumer reads from (path-agnostic — the consumer
//!    doesn't know whether events came from the legacy producer or
//!    this one).
//! 2. Compiles `source` → AST → IR via the unified pipeline
//!    (`crate::flow_plan::compile_source_to_ir`). Parse / type-check
//!    / IR-generation errors emit `FlowExecutionEvent::FlowError`
//!    and the producer exits cleanly.
//! 3. Resolves the requested `flow_name` from the IR's flow list.
//!    Missing flow → structured `FlowError` + clean exit.
//! 4. Constructs a [`DispatchCtx`] with the inbound `tx` so every
//!    `dispatch_node` call emits events on the SSE consumer's
//!    channel directly — no intermediate buffering.
//! 5. Walks `flow.body` in order. For each top-level `IRFlowNode`,
//!    calls `flow_dispatcher::dispatch_node(&node, &mut ctx).await`.
//!    The dispatcher's per-variant handler emits StepStart /
//!    StepToken / StepComplete / ToolCall events on `ctx.tx`.
//! 6. Honors sentinel outcomes from the dispatcher: `Return { value }`
//!    breaks the loop (a `return foo` statement short-circuits the
//!    flow); `Break` and `LoopContinue` are loop-only sentinels and
//!    are ignored at the top level (they only propagate inside
//!    `ForIn` bodies, which the dispatcher's orchestration handlers
//!    handle internally).
//! 7. Emits `FlowExecutionEvent::FlowComplete` with the final
//!    success flag + accumulated token counts + audit summary.
//!
//! # Cancel discipline (D3)
//!
//! The producer threads the same `CancellationFlag` from
//! `server_execute_streaming` into the `DispatchCtx`. Every
//! per-variant handler checks the flag at its entry (33.y D3
//! invariant enforced by the drift gate). A client disconnect
//! during a deeply-nested orchestration shape (e.g.,
//! `for x in xs { par { step A {...} step B {...} } }`) aborts
//! ALL concurrent branches within p95 ≤100ms wall-clock budget
//! preserved from 33.x.e.
//!
//! # Wire byte-compat (D4)
//!
//! Canonical `step S { ask: "..." output: Stream<Token> }` + stub
//! backend continues to emit exactly 1 axon.token "(stub)" + 1
//! axon.complete — identical to the v1.26.0 `run_streaming_async_path`
//! wire body. This is enforced by the 33.z.b integration test pack:
//! every shape that worked in v1.26.0 keeps working byte-equal
//! with the flag ON.
//!
//! # What this module does NOT do
//!
//! - Per-step replay binding extension (D6 branch_path) — that's
//!   33.z.c scope; the dispatcher's `StepAuditRecord` shape with
//!   `branch_path` already exists from 33.y, but the SSE handler
//!   side of the replay row capture is in 33.z.c.
//! - `axon.tool_call` SSE event wire emission — also 33.z.c; this
//!   module emits `FlowExecutionEvent::ToolCall` (33.y.k) but the
//!   SSE consumer still silently consumes (the 33.y.k baseline).
//! - 50-flow sync↔async parity corpus — 33.z.d.
//! - Legacy path retirement — 33.z.e.

use crate::cancel_token::CancellationFlag;
use crate::flow_dispatcher::{dispatch_node, DispatchCtx, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use tokio::sync::mpsc::UnboundedSender;

/// §Fase 33.z.b — Drive a flow's execution through the
/// `flow_dispatcher::dispatch_node` hot path end-to-end, emitting
/// FlowExecutionEvents on the inbound mpsc channel.
///
/// Signature mirrors [`run_streaming_legacy_path`] for drop-in
/// replacement under the `AXON_STREAMING_VIA_DISPATCHER` flag.
///
/// # Arguments
///
/// - `source` — the `.axon` source text (deploy-time captured).
/// - `source_file` — for diagnostic locality in error messages.
/// - `flow_name` — the flow to dispatch (resolved from IR).
/// - `backend` — the LLM backend name (passed through to DispatchCtx).
/// - `cancel` — the cancellation flag shared with the SSE handler.
/// - `tx` — the FlowExecutionEvent mpsc channel the SSE consumer
///   reads from.
///
/// # Cancel safety
///
/// Every send wraps a `cancel.is_cancelled()` check + a tx-closed
/// check (matches the 33.x.f cancel-safety helper pattern in the
/// legacy path). On cancel OR consumer-drop, the producer exits
/// early without emitting further events. The dispatcher's per-
/// variant handlers carry the same discipline internally.
pub async fn run_streaming_via_dispatcher(
    source: String,
    source_file: String,
    flow_name: String,
    backend: String,
    cancel: CancellationFlag,
    tx: UnboundedSender<FlowExecutionEvent>,
    // §Fase 33.z.c — External side-channels threaded from
    // `server_execute_streaming` so the dispatcher's per-variant
    // handlers populate the SAME Mutexes the SSE wire's
    // `enforcement_summary`, `step_audit`, and `runtime_warnings`
    // fields read from. Without these, the dispatcher's fresh internal
    // Arcs (created by `DispatchCtx::new`) would carry the counters
    // but never reach the wire — adopter loses D4 byte-compat with
    // the v1.25.0 33.x.d/f production-path surface.
    enforcement_summaries: std::sync::Arc<
        tokio::sync::Mutex<
            std::collections::HashMap<
                String,
                crate::axon_server::EnforcementSummaryWire,
            >,
        >,
    >,
    step_audit_records: std::sync::Arc<
        tokio::sync::Mutex<Vec<crate::axonendpoint_replay::StepAuditRecord>>,
    >,
    runtime_warnings: std::sync::Arc<
        tokio::sync::Mutex<Vec<crate::runtime_warnings::RuntimeWarning>>,
    >,
    // §Fase 35.j (Pillar IV) — the capability slugs the request
    // carries (the JWT bearer's `capabilities` claim). `Some` activates
    // the store handlers' runtime capability re-check; `None` defers to
    // the type-checker's compile-time guarantee.
    held_capabilities: Option<Vec<String>>,
) {
    // Cancel-safety helper — mirrors the legacy path's `emit` closure.
    // Returns `Err(())` when the producer should exit early (cancel
    // fired OR consumer dropped the receiver).
    let emit = |event: FlowExecutionEvent| -> Result<(), ()> {
        if cancel.is_cancelled() {
            return Err(());
        }
        tx.send(event).map_err(|_| ())
    };

    let exec_start = std::time::Instant::now();

    // §1 — FlowStart fires BEFORE we attempt compilation so any
    // consumer can bind side-effect state (audit row, observability
    // span) immediately.
    if emit(FlowExecutionEvent::FlowStart {
        flow_name: flow_name.clone(),
        backend: backend.clone(),
        timestamp_ms: now_ms(),
    })
    .is_err()
    {
        return;
    }

    // §2 — Compile source → IR via the unified pipeline. Parse /
    // type-check / IR-generation errors emit FlowError + exit.
    let (ast_program, ir) = match crate::flow_plan::compile_source_to_ir(&source, &source_file) {
        Ok(pair) => pair,
        Err(plan_error) => {
            let _ = emit(FlowExecutionEvent::FlowError {
                flow_name: flow_name.clone(),
                error: format!("compilation failed: {plan_error:?}"),
                timestamp_ms: now_ms(),
            });
            let _ = emit(FlowExecutionEvent::FlowComplete {
                flow_name,
                backend,
                success: false,
                steps_executed: 0,
                tokens_input: 0,
                tokens_output: 0,
                latency_ms: exec_start.elapsed().as_millis() as u64,
                timestamp_ms: now_ms(),
            });
            return;
        }
    };

    // §2.5 — Build the axonstore registry (Fase 35.f). The D2 closed-
    // catalog gate runs here: an unknown `backend:` fails fast with a
    // named FlowError before any node dispatches.
    let store_registry = match crate::store::registry::StoreRegistry::build(
        &ir.axonstore_specs,
    ) {
        Ok(r) => std::sync::Arc::new(r),
        Err(reg_error) => {
            let _ = emit(FlowExecutionEvent::FlowError {
                flow_name: flow_name.clone(),
                error: format!("axonstore registry: {reg_error}"),
                timestamp_ms: now_ms(),
            });
            let _ = emit(FlowExecutionEvent::FlowComplete {
                flow_name,
                backend,
                success: false,
                steps_executed: 0,
                tokens_input: 0,
                tokens_output: 0,
                latency_ms: exec_start.elapsed().as_millis() as u64,
                timestamp_ms: now_ms(),
            });
            return;
        }
    };

    // §3 — Resolve the requested flow from the IR's flow list.
    // The frontend's IR generator preserves source declaration order
    // so a multi-flow program can dispatch any of them by name.
    let flow = match ir.flows.iter().find(|f| f.name == flow_name) {
        Some(f) => f.clone(),
        None => {
            let available: Vec<String> = ir.flows.iter().map(|f| f.name.clone()).collect();
            let _ = emit(FlowExecutionEvent::FlowError {
                flow_name: flow_name.clone(),
                error: format!(
                    "flow '{}' not found in compiled IR; available: {:?}",
                    flow_name, available
                ),
                timestamp_ms: now_ms(),
            });
            let _ = emit(FlowExecutionEvent::FlowComplete {
                flow_name,
                backend,
                success: false,
                steps_executed: 0,
                tokens_input: 0,
                tokens_output: 0,
                latency_ms: exec_start.elapsed().as_millis() as u64,
                timestamp_ms: now_ms(),
            });
            return;
        }
    };

    // §4 — System prompt composition. Mirror of the v1.25.0 33.x.b
    // discipline: persona + context + anchor instructions via the
    // public composer; `backend_tag: None` because the wire's
    // `axon.complete.backend` field already carries the backend name.
    let system_prompt = crate::flow_plan::compose_system_prompt_public(&flow, &ir, None);

    // §Fase 36.i (D4) — Build the tool registry from the compiled
    // IR's tool declarations. Pre-36.i `DispatchCtx::with_tool_registry`
    // had ZERO production callers: `run_streaming_via_dispatcher`
    // attached only the store registry + side-channels, so
    // `ctx.tool_registry` stayed `None` and the dispatcher's
    // streaming-tool branch in `run_step` (`pure_shape.rs`) — gated on
    // `ctx.tool_registry == Some` — could never fire. A
    // `step S { apply: <tool> }` whose `tool` declared
    // `provider: <p>, effects: <stream:<policy>>` silently fell
    // through to the plain-LLM path: the declared provider AND the
    // declared stream effect were ignored at execution.
    //
    // Wiring the registry here makes the dead builder LIVE: a step
    // applying a tool the registry flags `is_streaming` now reaches
    // `run_step_streaming_tool` and executes against the TOOL's
    // declared `provider:` (the per-step backend, overriding the
    // flow-level backend for that step) with the `<stream:<policy>>`
    // effect honored end-to-end. `register_from_ir` auto-derives the
    // `is_streaming` flag from each tool's `effect_row` (Fase 34.c).
    let tool_registry = {
        let mut reg = crate::tool_registry::ToolRegistry::new();
        reg.register_from_ir(&ir.tools);
        std::sync::Arc::new(reg)
    };

    // §5 — Construct DispatchCtx. The mpsc tx is the SAME channel
    // the SSE consumer reads from; the dispatcher's events flow
    // directly to the wire with no intermediate buffering.
    let mut ctx = DispatchCtx::new(
        flow_name.clone(),
        backend.clone(),
        system_prompt,
        cancel.clone(),
        tx.clone(),
    )
    .with_external_side_channels(
        enforcement_summaries,
        step_audit_records,
        runtime_warnings,
    )
    .with_store_registry(store_registry)
    // §Fase 36.i (D4) — the tool registry, now LIVE on the production
    // SSE path. Activates the dispatcher's streaming-tool branch.
    .with_tool_registry(tool_registry);
    // §Fase 35.j — thread the request's held capabilities into the
    // dispatcher so the store handlers can re-check gated stores.
    ctx.held_capabilities = held_capabilities;

    // §6 — Walk the flow body. For each top-level IRFlowNode, call
    // dispatch_node and honor the outcome semantics:
    //
    //   Completed { .. }      → continue to the next node
    //   Break                 → ignored at top level (loop sentinel
    //                           only propagates inside ForIn bodies)
    //   LoopContinue          → ignored at top level (same)
    //   Return { value }      → short-circuit the flow loop (a `return`
    //                           statement explicitly terminates execution)
    //   Err(UpstreamCancelled)→ exit cleanly (cancel was observed
    //                           inside a handler at its entry guard)
    //   Err(other)            → emit FlowError + exit
    //
    // Sentinels Break / LoopContinue are scoped to orchestration
    // bodies (ForIn / Conditional) — they're handled INTERNALLY by
    // those handlers and don't surface here. If they DO surface at
    // top level it's a structural bug; we treat them as no-ops so
    // the flow continues (defensive — never panic on the production
    // hot path per D7).
    let mut total_tokens_output: u64 = 0;
    let mut steps_executed: usize = 0;
    let mut flow_success = true;

    // §Fase 33.z.c — Look up the AST flow that corresponds to the
    // IR flow. The AST is needed by `resolve_stream_effect_for_step`
    // to walk the tool-effects table. For canonical Step shapes
    // declaring `<stream:<policy>>` effects on a tool referenced via
    // `apply: tool_name`, this is the same resolution the v1.25.0
    // 33.x.d production path does in `build_streaming_plan`.
    //
    // Resolution happens at the TOP LEVEL only. Nested-step policies
    // (steps inside Conditional / ForIn / Par bodies) inherit `None`
    // — a deeper resolution that walks AST through orchestration is
    // 33.z.d scope (50-flow parity corpus). For the canonical Step
    // shape that the d2_post_33_x_d test exercises, top-level
    // resolution is sufficient.
    let ast_flow = ast_program
        .declarations
        .iter()
        .find_map(|d| match d {
            crate::ast::Declaration::Flow(f) if f.name == flow_name => Some(f),
            _ => None,
        });

    for node in &flow.steps {
        if cancel.is_cancelled() {
            break;
        }
        // §Fase 33.z.c — Per-step effect-policy resolution. Set
        // `ctx.pending_effect_policy` before dispatch; the pure_shape
        // handler reads + clears via `take_pending_effect_policy()` +
        // wraps the chunk stream with `StreamPolicyEnforcer`.
        if let (Some(ast_f), crate::ir_nodes::IRFlowNode::Step(ir_step)) = (ast_flow, node) {
            if !ir_step.name.is_empty() {
                ctx.pending_effect_policy =
                    crate::stream_effect_dispatcher::resolve_stream_effect_for_step(
                        &ir_step.name,
                        ast_f,
                        &ast_program,
                    );
            }
        }
        let outcome = dispatch_node(node, &mut ctx).await;
        match outcome {
            Ok(NodeOutcome::Completed {
                tokens_emitted, ..
            }) => {
                total_tokens_output += tokens_emitted;
                // step_index from the handler reflects the node's
                // position in the FLOW (not the body — orchestration
                // handlers internally manage their own counters).
                steps_executed += 1;
            }
            Ok(NodeOutcome::Break) | Ok(NodeOutcome::LoopContinue) => {
                // Defensive: shouldn't reach top level. Treat as no-op.
            }
            Ok(NodeOutcome::Return { .. }) => {
                // Explicit `return` in flow body — short-circuit.
                steps_executed += 1;
                break;
            }
            Err(crate::flow_dispatcher::DispatchError::UpstreamCancelled) => {
                // Cancel fired during dispatch; exit cleanly without
                // emitting FlowError (cancel is a graceful shutdown,
                // not a flow failure per D3 contract from 33.x.e).
                break;
            }
            Err(e) => {
                flow_success = false;
                let _ = emit(FlowExecutionEvent::FlowError {
                    flow_name: flow_name.clone(),
                    error: format!("dispatcher error: {e:?}"),
                    timestamp_ms: now_ms(),
                });
                break;
            }
        }
    }

    // §7 — FlowComplete with accumulated counters. tokens_input is
    // 0 because the dispatcher doesn't currently track input tokens
    // separately (the per-step audit records do, but the FlowComplete
    // input field stays 0 until 33.z.c extends the surface).
    let _ = emit(FlowExecutionEvent::FlowComplete {
        flow_name,
        backend,
        success: flow_success,
        steps_executed,
        tokens_input: 0,
        tokens_output: total_tokens_output,
        latency_ms: exec_start.elapsed().as_millis() as u64,
        timestamp_ms: now_ms(),
    });

    // Drop ctx (and its tx clone) so the consumer's `recv().await`
    // returns None when this producer task completes — the original
    // tx in the caller is dropped separately by the spawn site.
    drop(ctx);
}

// ────────────────────────────────────────────────────────────────────
//  Tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cancel_token::CancellationFlag;
    use tokio::sync::mpsc;

    /// Canonical Step + stub backend → 1 axon.token "(stub)" + 1
    /// axon.complete. Wire byte-compat with v1.26.0 `run_streaming_async_path`.
    #[tokio::test]
    async fn canonical_step_emits_single_stub_token() {
        let src = "flow Chat() -> Unit {\n\
                       step Generate { ask: \"hi\" output: Stream<Token> }\n\
                   }\n\
                   axonendpoint E { method: POST path: \"/c\" execute: Chat transport: sse }";
        let (tx, mut rx) = mpsc::unbounded_channel();
        let cancel = CancellationFlag::new();
        let enforcement = std::sync::Arc::new(tokio::sync::Mutex::new(
            std::collections::HashMap::new(),
        ));
        let audit = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        let warnings = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        run_streaming_via_dispatcher(
            src.to_string(),
            "test.axon".to_string(),
            "Chat".to_string(),
            "stub".to_string(),
            cancel,
            tx,
            enforcement,
            audit,
            warnings,
            None,
        )
        .await;

        let mut events = Vec::new();
        while let Some(ev) = rx.recv().await {
            events.push(ev);
        }

        let token_count = events
            .iter()
            .filter(|e| matches!(e, FlowExecutionEvent::StepToken { .. }))
            .count();
        let complete_count = events
            .iter()
            .filter(|e| matches!(e, FlowExecutionEvent::FlowComplete { .. }))
            .count();
        let flow_start_count = events
            .iter()
            .filter(|e| matches!(e, FlowExecutionEvent::FlowStart { .. }))
            .count();
        assert_eq!(flow_start_count, 1, "exactly 1 FlowStart");
        assert_eq!(token_count, 1, "stub backend emits exactly 1 token");
        assert_eq!(complete_count, 1, "exactly 1 FlowComplete");
    }

    /// Compilation error → FlowError + FlowComplete{success=false}
    /// + no StepToken events.
    #[tokio::test]
    async fn compilation_error_emits_flow_error_and_completes() {
        let src = "not valid axon source ::: <<< broken";
        let (tx, mut rx) = mpsc::unbounded_channel();
        let cancel = CancellationFlag::new();
        let enforcement = std::sync::Arc::new(tokio::sync::Mutex::new(
            std::collections::HashMap::new(),
        ));
        let audit = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        let warnings = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        run_streaming_via_dispatcher(
            src.to_string(),
            "broken.axon".to_string(),
            "Whatever".to_string(),
            "stub".to_string(),
            cancel,
            tx,
            enforcement,
            audit,
            warnings,
            None,
        )
        .await;

        let mut events = Vec::new();
        while let Some(ev) = rx.recv().await {
            events.push(ev);
        }

        let error_count = events
            .iter()
            .filter(|e| matches!(e, FlowExecutionEvent::FlowError { .. }))
            .count();
        let token_count = events
            .iter()
            .filter(|e| matches!(e, FlowExecutionEvent::StepToken { .. }))
            .count();
        let complete_success: Vec<bool> = events
            .iter()
            .filter_map(|e| match e {
                FlowExecutionEvent::FlowComplete { success, .. } => Some(*success),
                _ => None,
            })
            .collect();
        assert!(error_count >= 1, "compilation error emits FlowError");
        assert_eq!(token_count, 0, "no tokens on compilation failure");
        assert_eq!(complete_success, vec![false], "FlowComplete success=false");
    }

    /// Missing flow name → FlowError + FlowComplete{success=false}.
    #[tokio::test]
    async fn missing_flow_name_emits_flow_error() {
        let src = "flow Chat() -> Unit {\n\
                       step Generate { ask: \"hi\" output: Stream<Token> }\n\
                   }\n\
                   axonendpoint E { method: POST path: \"/c\" execute: Chat transport: sse }";
        let (tx, mut rx) = mpsc::unbounded_channel();
        let cancel = CancellationFlag::new();
        let enforcement = std::sync::Arc::new(tokio::sync::Mutex::new(
            std::collections::HashMap::new(),
        ));
        let audit = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        let warnings = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        run_streaming_via_dispatcher(
            src.to_string(),
            "test.axon".to_string(),
            "NonExistent".to_string(),
            "stub".to_string(),
            cancel,
            tx,
            enforcement,
            audit,
            warnings,
            None,
        )
        .await;

        let mut events = Vec::new();
        while let Some(ev) = rx.recv().await {
            events.push(ev);
        }

        let error_found = events.iter().any(|e| {
            matches!(e, FlowExecutionEvent::FlowError { error, .. } if error.contains("not found"))
        });
        assert!(error_found, "missing flow surfaces structured 'not found' error");
    }

    /// Pre-cancel → producer exits cleanly without StepToken / FlowComplete.
    #[tokio::test]
    async fn pre_cancel_short_circuits() {
        let src = "flow Chat() -> Unit {\n\
                       step Generate { ask: \"hi\" output: Stream<Token> }\n\
                   }\n\
                   axonendpoint E { method: POST path: \"/c\" execute: Chat transport: sse }";
        let (tx, mut rx) = mpsc::unbounded_channel();
        let cancel = CancellationFlag::new();
        cancel.cancel(); // pre-cancel
        let enforcement = std::sync::Arc::new(tokio::sync::Mutex::new(
            std::collections::HashMap::new(),
        ));
        let audit = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        let warnings = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        run_streaming_via_dispatcher(
            src.to_string(),
            "test.axon".to_string(),
            "Chat".to_string(),
            "stub".to_string(),
            cancel,
            tx,
            enforcement,
            audit,
            warnings,
            None,
        )
        .await;

        let mut events = Vec::new();
        while let Some(ev) = rx.recv().await {
            events.push(ev);
        }
        // Cancel fired before FlowStart could be emitted → channel
        // close drains zero events. The producer's `emit` helper
        // checks `cancel.is_cancelled()` first → returns Err(()) →
        // producer exits without emitting.
        assert_eq!(events.len(), 0, "pre-cancel → zero events emitted");
    }
}
