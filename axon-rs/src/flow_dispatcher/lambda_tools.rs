//! §Fase 33.y.j — Lambda + UseTool. The final 2 variants needed
//! to reach 45/45 IRFlowNode graduation.
//!
//! Two variants graduated in 33.y.j:
//!
//! - **`LambdaDataApply`** (Fase 15 ΛD apply) — apply a named
//!   lambda data structure to a target expression. Sync runner
//!   walks a CPS dispatcher mapping lambda data structures to
//!   their result expressions. OSS reference impl uses the public
//!   helper [`apply_lambda_data`] which returns a canonical
//!   `"lambda:<name>(<target>)"` placeholder; enterprise R&D
//!   (axon_enterprise lambda runtime) wires the real CPS
//!   dispatcher.
//!
//! - **`UseTool`** (Fase 22 mid-step tool dispatch) — invoke a
//!   named tool with an argument. The full
//!   `ChatRequest.tools` cross-cutting plumb-through (D8) lands
//!   in 33.y.k as a cross-cutting fix that extends the
//!   `pure_shape` core. 33.y.j ships the OSS reference impl via
//!   the public helper [`invoke_tool`] which returns a canonical
//!   `"tool:<name>(<argument>)"` placeholder; enterprise R&D
//!   wires the real Fase 22 tool registry + dispatch.
//!
//! After 33.y.j: 45/45 IRFlowNode variants graduated. The legacy
//! `shim` becomes structurally unreachable from `dispatch_node`;
//! 33.y.l explicitly retires it.
//!
//! # D-letter anchors
//!
//! - **D1** — both variants have NAMED async handlers; the
//!   exhaustive match in `dispatch_node` reaches 45/45 graduation.
//! - **D3** — cancel checked at every `.await` boundary.
//! - **D7** — every error case routes through `DispatchError`;
//!   OSS helpers cannot fail (placeholder semantics); enterprise
//!   overrides surface `BackendError` for real lambda/tool
//!   runtime errors.
//! - **D8 (preview)** — UseTool is the 33.y.k cross-cutting
//!   anchor. 33.y.j ships the wire shape + helper surface; 33.y.k
//!   plumbs `ChatRequest.tools` through every `pure_shape`-routed
//!   handler so adopters declaring `apply: <tool>` see real
//!   tool-call events on the wire.
//! - **D10** — sync-runner parity: lambda apply + tool invocation
//!   produce deterministic placeholders for OSS path; enterprise
//!   integration preserves the SAME wire envelope (only inner
//!   content differs).

use crate::flow_dispatcher::{DispatchCtx, DispatchError, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use crate::ir_nodes::{IRLambdaDataApply, IRUseToolStep};

// ────────────────────────────────────────────────────────────────────
//  Public helpers (enterprise hooks override these)
// ────────────────────────────────────────────────────────────────────

/// Apply a named ΛD (lambda data structure) to a target. OSS
/// default: resolves `target` through `ctx.let_bindings` (literal
/// if missing) + returns canonical `"lambda:<name>(<resolved_target>)"`.
/// Enterprise overrides hook the Fase 15 CPS dispatcher (real
/// lambda evaluation against the IR).
pub fn apply_lambda_data(
    lambda_name: &str,
    target: &str,
    ctx: &DispatchCtx,
) -> String {
    let resolved_target = ctx
        .let_bindings
        .get(target)
        .cloned()
        .unwrap_or_else(|| target.to_string());
    format!("lambda:{lambda_name}({resolved_target})")
}

/// Invoke a tool with an argument. OSS default: resolves
/// `argument` through `ctx.let_bindings` (literal if missing) +
/// returns canonical `"tool:<name>(<resolved_argument>)"`.
/// Enterprise overrides hook the Fase 22 tool registry +
/// per-provider dispatch (Anthropic / OpenAI / etc.). The D8
/// cross-cutting fix (33.y.k) extends `pure_shape::run_pure_shape`
/// to plumb `ChatRequest.tools` so `apply: <tool>` on a Step
/// activates real upstream tool-calling on the wire.
pub fn invoke_tool(tool_name: &str, argument: &str, ctx: &DispatchCtx) -> String {
    let resolved_argument = ctx
        .let_bindings
        .get(argument)
        .cloned()
        .unwrap_or_else(|| argument.to_string());
    format!("tool:{tool_name}({resolved_argument})")
}

// ────────────────────────────────────────────────────────────────────
//  LambdaDataApply (Fase 15 ΛD apply)
// ────────────────────────────────────────────────────────────────────

/// LambdaDataApply handler. Wire shape:
/// `step_type: "lambda_data_apply"`. Resolves the lambda via
/// [`apply_lambda_data`] + binds result under `output_type` (or
/// `<target>_lambda_applied` canonical fallback) in
/// `ctx.let_bindings`.
pub async fn run_lambda_data_apply(
    node: &IRLambdaDataApply,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.lambda_data_name.is_empty() {
        "LambdaApply".to_string()
    } else {
        node.lambda_data_name.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "lambda_data_apply")?;

    let result = apply_lambda_data(&node.lambda_data_name, &node.target, ctx);

    let output_key = if !node.output_type.is_empty() {
        node.output_type.clone()
    } else if !node.target.is_empty() {
        format!("{}_lambda_applied", node.target)
    } else {
        String::new()
    };
    if !output_key.is_empty() {
        ctx.let_bindings.insert(output_key, result.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &result, 0)?;

    Ok(NodeOutcome::Completed {
        output: result,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  UseTool (Fase 22 mid-step tool dispatch)
// ────────────────────────────────────────────────────────────────────

/// UseTool handler. Wire shape: `step_type: "use_tool"`. Resolves
/// the tool invocation via [`invoke_tool`] + binds result under
/// `<tool_name>_result` canonical key in `ctx.let_bindings`.
///
/// # 33.y.k integration note
///
/// The full D8 cross-cutting fix that plumbs `ChatRequest.tools`
/// through every `pure_shape`-routed handler so `apply: <tool>` on
/// a Step activates real upstream tool-calling on the SSE wire
/// lands in **Fase 33.y.k**. 33.y.j ships the structural wire
/// shape for the explicit `use_tool: <name>` IR variant.
pub async fn run_use_tool(
    node: &IRUseToolStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.tool_name.is_empty() {
        "UseTool".to_string()
    } else {
        node.tool_name.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "use_tool")?;

    let result = invoke_tool(&node.tool_name, &node.argument, ctx);

    if !node.tool_name.is_empty() {
        ctx.let_bindings
            .insert(format!("{}_result", node.tool_name), result.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &result, 0)?;

    Ok(NodeOutcome::Completed {
        output: result,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Wire-event helpers
// ────────────────────────────────────────────────────────────────────

fn emit_step_start(
    ctx: &mut DispatchCtx,
    step_name: &str,
    step_index: usize,
    step_type: &str,
) -> Result<(), DispatchError> {
    ctx.tx
        .send(FlowExecutionEvent::StepStart {
            step_name: step_name.to_string(),
            step_index,
            step_type: step_type.to_string(),
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)
}

fn emit_step_complete(
    ctx: &mut DispatchCtx,
    step_name: &str,
    step_index: usize,
    full_output: &str,
    tokens_output: u64,
) -> Result<(), DispatchError> {
    ctx.tx
        .send(FlowExecutionEvent::StepComplete {
            step_name: step_name.to_string(),
            step_index,
            success: true,
            full_output: full_output.to_string(),
            tokens_input: 0,
            tokens_output,
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)
}

// ────────────────────────────────────────────────────────────────────
//  Unit tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cancel_token::CancellationFlag;
    use crate::ir_nodes::*;
    use tokio::sync::mpsc;

    fn fresh_ctx() -> (
        DispatchCtx,
        mpsc::UnboundedReceiver<FlowExecutionEvent>,
    ) {
        let (tx, rx) = mpsc::unbounded_channel();
        let ctx = DispatchCtx::new(
            "TestFlow",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        );
        (ctx, rx)
    }

    // ── apply_lambda_data ────────────────────────────────────────────

    #[test]
    fn apply_lambda_data_literal_target() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(
            apply_lambda_data("inc", "5", &ctx),
            "lambda:inc(5)"
        );
    }

    #[test]
    fn apply_lambda_data_resolves_target_through_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("x".into(), "42".into());
        assert_eq!(
            apply_lambda_data("square", "x", &ctx),
            "lambda:square(42)"
        );
    }

    // ── invoke_tool ──────────────────────────────────────────────────

    #[test]
    fn invoke_tool_literal_argument() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(
            invoke_tool("calculator", "2+2", &ctx),
            "tool:calculator(2+2)"
        );
    }

    #[test]
    fn invoke_tool_resolves_argument_through_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("query".into(), "weather today".into());
        assert_eq!(
            invoke_tool("web_search", "query", &ctx),
            "tool:web_search(weather today)"
        );
    }

    // ── LambdaDataApply ──────────────────────────────────────────────

    #[tokio::test]
    async fn run_lambda_data_apply_binds_under_output_type() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("input_data".into(), "raw".into());
        let node = IRLambdaDataApply {
            node_type: "lambda_data_apply",
            source_line: 0,
            source_column: 0,
            lambda_data_name: "transform".into(),
            target: "input_data".into(),
            output_type: "transformed".into(),
        };
        let outcome = run_lambda_data_apply(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, .. } => {
                assert_eq!(output, "lambda:transform(raw)");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(
            ctx.let_bindings.get("transformed").unwrap(),
            "lambda:transform(raw)"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "lambda_data_apply");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_lambda_data_apply_canonical_fallback() {
        let (mut ctx, _rx) = fresh_ctx();
        let node = IRLambdaDataApply {
            node_type: "lambda_data_apply",
            source_line: 0,
            source_column: 0,
            lambda_data_name: "norm".into(),
            target: "doc".into(),
            output_type: String::new(),
        };
        run_lambda_data_apply(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("doc_lambda_applied").unwrap(),
            "lambda:norm(doc)"
        );
    }

    // ── UseTool ──────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_use_tool_binds_under_canonical_result_key() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("input".into(), "5+3".into());
        let node = IRUseToolStep {
            node_type: "use_tool",
            source_line: 0,
            source_column: 0,
            tool_name: "calculator".into(),
            argument: "input".into(),
        };
        let outcome = run_use_tool(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, .. } => {
                assert_eq!(output, "tool:calculator(5+3)");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(
            ctx.let_bindings.get("calculator_result").unwrap(),
            "tool:calculator(5+3)"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "use_tool");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── Cancel guards ────────────────────────────────────────────────

    #[tokio::test]
    async fn lambda_and_use_tool_short_circuit_on_cancel() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        let lambda = IRLambdaDataApply {
            node_type: "lambda_data_apply",
            source_line: 0,
            source_column: 0,
            lambda_data_name: "x".into(),
            target: "y".into(),
            output_type: "z".into(),
        };
        assert!(matches!(
            run_lambda_data_apply(&lambda, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        let ut = IRUseToolStep {
            node_type: "use_tool",
            source_line: 0,
            source_column: 0,
            tool_name: "x".into(),
            argument: "y".into(),
        };
        assert!(matches!(
            run_use_tool(&ut, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));
    }
}
