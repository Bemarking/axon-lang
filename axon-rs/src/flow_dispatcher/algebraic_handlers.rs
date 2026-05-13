//! §Fase 33.y.g — Algebraic-effect handler nodes.
//!
//! Six variants graduated in 33.y.g:
//!
//! - **`ShieldApply`** (Fase 20) — apply a registered shield to a
//!   target. Per-chunk scrubbing semantics when target is a stream
//!   (foundation for the enterprise PHI scrubber R&D track).
//! - **`OtsApply`** (Fase 14) — apply a One-True-Source transform.
//! - **`MandateApply`** (Fase 16-related) — apply a mandate (a
//!   compliance-bound transformation declared at the language level).
//! - **`ComputeApply`** (Fase 11.f) — invoke a compute capability
//!   with positional arguments; binds result under `output_name`.
//! - **`Listen`** (Fase 13 π-calc) — wait on a typed channel for
//!   an event; binds event payload under `event_alias`.
//! - **`DaemonStep`** (Fase 16 supervisor) — invoke a daemon by
//!   reference (the daemon's per-invocation execution is its own
//!   subsystem).
//!
//! # Architecture: OSS framework + enterprise hooks
//!
//! Per the OSS / ENTERPRISE / SPLIT charter, the actual shield /
//! OTS / mandate / compute capability *implementations* live in
//! `axon_enterprise.shield` (the scanner registry) + `axon_enterprise.
//! ots` (the OTS transformers) + `axon_enterprise.cognitive_states`
//! (the daemon supervisor + Fase 13 channel layer). 33.y.g ships the
//! OSS **framework** — the wire shape + the public `apply_*` helpers
//! that enterprise overrides via future hooks.
//!
//! The OSS-default `apply_*` helpers are **identity passthroughs**:
//! they bind the target verbatim under the output key. This is
//! semantically correct for the OSS reference implementation
//! (adopters with no shield registry see their data unmodified) and
//! provides the integration surface enterprise hooks supersede.
//!
//! # Wire shape
//!
//! Each handler emits:
//!   1. `axon.step_start { step_type: <slug>, ... }`
//!   2. `axon.step_complete { ... }`
//!
//! No StepToken events (these are pure capability-application
//! operations, not LLM dispatches). Output binds to
//! `ctx.let_bindings` under a variant-specific key + returns
//! `NodeOutcome::Completed { output, tokens_emitted: 0,
//! step_index: <reserved> }`.
//!
//! # D-letter anchors
//!
//! - **D1** — every variant has a NAMED async handler; exhaustive
//!   match in `dispatch_node`.
//! - **D3** — cancel checked at every `.await` boundary.
//! - **D7** — every error case routes through `DispatchError`; the
//!   `apply_*` helpers cannot fail in the OSS path (they're
//!   passthroughs); enterprise overrides will surface errors as
//!   `DispatchError::BackendError { name: "shield" / "ots" / ... }`.
//! - **D10** — sync-runner parity: shield/OTS/mandate/compute
//!   capabilities apply identically (identity in OSS); Listen
//!   binds a structured placeholder until the typed-channel layer
//!   wires into the dispatcher in a future sub-fase.

use crate::flow_dispatcher::{DispatchCtx, DispatchError, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use crate::ir_nodes::{
    IRComputeApplyStep, IRDaemonStepNode, IRListenStep, IRMandateApplyStep,
    IROtsApplyStep, IRShieldApplyStep,
};

// ────────────────────────────────────────────────────────────────────
//  Public apply_* helpers (enterprise hooks override these)
// ────────────────────────────────────────────────────────────────────

/// Apply a named shield to `target`. OSS default: identity
/// passthrough. Enterprise overrides (axon_enterprise.shield) hook
/// in via the future `DispatchCtx::shield_apply` field to route
/// through a registered scanner pipeline (HIPAA / legal / fintech).
///
/// # Streaming semantics
///
/// When `target` is the output of a streaming step (i.e. carries
/// per-chunk content), enterprise's per-chunk scrubber applies the
/// shield to each chunk as it arrives. The OSS path applies once
/// to the materialized string — semantically equivalent for the
/// adopter's wire output (the difference is the wire timing, which
/// matters only when shields can BLOCK chunks; OSS shields are
/// passthrough so they never block).
pub fn apply_shield_to_target(shield_name: &str, target: &str, _ctx: &DispatchCtx) -> String {
    // 33.y.g OSS default: identity. Enterprise overrides.
    let _ = shield_name;
    target.to_string()
}

/// Apply a named OTS (One-True-Source) transform to `target`. OSS
/// default: identity passthrough. Enterprise overrides
/// (axon_enterprise.ots) hook into a registered transformer
/// (audio resamplers / image rasterizers / document
/// canonicalisers).
pub fn apply_ots_to_target(ots_name: &str, target: &str, _ctx: &DispatchCtx) -> String {
    let _ = ots_name;
    target.to_string()
}

/// Apply a named mandate to `target`. OSS default: identity
/// passthrough. Enterprise overrides (axon_enterprise compliance
/// layer) hook into the registered mandate executor (GDPR
/// erasure / SOX retention / HIPAA minimum-necessary).
pub fn apply_mandate_to_target(mandate_name: &str, target: &str, _ctx: &DispatchCtx) -> String {
    let _ = mandate_name;
    target.to_string()
}

/// Invoke a compute capability with positional arguments. OSS
/// default: returns a canonical formatted string
/// `"compute:<name>(<arg1>, <arg2>, ...)"` so adopters observe
/// the invocation shape on the wire + can chain subsequent steps
/// against `output_name`. Enterprise overrides
/// (axon_enterprise.compute) hook into the real compute runtime.
pub fn invoke_compute_capability(
    compute_name: &str,
    arguments: &[String],
    ctx: &DispatchCtx,
) -> String {
    // Resolve each argument through let_bindings (symbolic
    // reference) or treat as literal.
    let resolved: Vec<String> = arguments
        .iter()
        .map(|arg| {
            ctx.let_bindings
                .get(arg)
                .cloned()
                .unwrap_or_else(|| arg.clone())
        })
        .collect();
    format!("compute:{compute_name}({})", resolved.join(", "))
}

/// Listen on a Fase 13 typed channel for an event. OSS default:
/// returns a canonical placeholder `"(awaiting <channel>)"` so
/// adopters observe the wait + bind under `event_alias` until
/// the typed-channel runtime layer wires in (axon_enterprise.
/// channels + future Fase 13 runtime). The placeholder is wire-
/// stable + adopter-diagnostic.
pub fn listen_on_channel(channel: &str, _channel_is_ref: bool, _ctx: &DispatchCtx) -> String {
    format!("(awaiting {channel})")
}

/// Invoke a daemon by reference. OSS default: returns canonical
/// `"daemon:<ref>"` placeholder. Enterprise overrides
/// (axon_enterprise.supervisor) dispatch to the registered daemon
/// supervisor's invocation surface.
pub fn invoke_daemon(daemon_ref: &str, _ctx: &DispatchCtx) -> String {
    format!("daemon:{daemon_ref}")
}

// ────────────────────────────────────────────────────────────────────
//  ShieldApply
// ────────────────────────────────────────────────────────────────────

/// Apply a shield to a target. Wire shape: `step_type: "shield_apply"`.
///
/// Resolution: `target` is resolved through `ctx.let_bindings`
/// (literal if missing). The shield is applied via
/// [`apply_shield_to_target`] (identity in OSS; enterprise
/// overrides). Output binds under `output_type` (when non-empty)
/// or under `<target>_shielded` (canonical fallback) in
/// `ctx.let_bindings`.
pub async fn run_shield_apply(
    node: &IRShieldApplyStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.shield_name.is_empty() {
        "ShieldApply".to_string()
    } else {
        node.shield_name.clone()
    };

    emit_step_start(ctx, &step_name, step_index, "shield_apply")?;

    let resolved_target = ctx
        .let_bindings
        .get(&node.target)
        .cloned()
        .unwrap_or_else(|| node.target.clone());
    let shielded = apply_shield_to_target(&node.shield_name, &resolved_target, ctx);

    let output_key = if !node.output_type.is_empty() {
        node.output_type.clone()
    } else if !node.target.is_empty() {
        format!("{}_shielded", node.target)
    } else {
        String::new()
    };
    if !output_key.is_empty() {
        ctx.let_bindings.insert(output_key, shielded.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &shielded, 0)?;

    Ok(NodeOutcome::Completed {
        output: shielded,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  OtsApply
// ────────────────────────────────────────────────────────────────────

/// Apply a One-True-Source transform. Wire shape:
/// `step_type: "ots_apply"`. Same resolution + output-binding
/// shape as [`run_shield_apply`].
pub async fn run_ots_apply(
    node: &IROtsApplyStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.ots_name.is_empty() {
        "OtsApply".to_string()
    } else {
        node.ots_name.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "ots_apply")?;

    let resolved_target = ctx
        .let_bindings
        .get(&node.target)
        .cloned()
        .unwrap_or_else(|| node.target.clone());
    let transformed = apply_ots_to_target(&node.ots_name, &resolved_target, ctx);

    let output_key = if !node.output_type.is_empty() {
        node.output_type.clone()
    } else if !node.target.is_empty() {
        format!("{}_ots", node.target)
    } else {
        String::new()
    };
    if !output_key.is_empty() {
        ctx.let_bindings.insert(output_key, transformed.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &transformed, 0)?;

    Ok(NodeOutcome::Completed {
        output: transformed,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  MandateApply
// ────────────────────────────────────────────────────────────────────

/// Apply a mandate. Wire shape: `step_type: "mandate_apply"`.
pub async fn run_mandate_apply(
    node: &IRMandateApplyStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.mandate_name.is_empty() {
        "MandateApply".to_string()
    } else {
        node.mandate_name.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "mandate_apply")?;

    let resolved_target = ctx
        .let_bindings
        .get(&node.target)
        .cloned()
        .unwrap_or_else(|| node.target.clone());
    let mandated = apply_mandate_to_target(&node.mandate_name, &resolved_target, ctx);

    let output_key = if !node.output_type.is_empty() {
        node.output_type.clone()
    } else if !node.target.is_empty() {
        format!("{}_mandated", node.target)
    } else {
        String::new()
    };
    if !output_key.is_empty() {
        ctx.let_bindings.insert(output_key, mandated.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &mandated, 0)?;

    Ok(NodeOutcome::Completed {
        output: mandated,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  ComputeApply
// ────────────────────────────────────────────────────────────────────

/// Invoke a compute capability. Wire shape:
/// `step_type: "compute_apply"`. Arguments are resolved through
/// `ctx.let_bindings`; the result binds under `output_name`.
pub async fn run_compute_apply(
    node: &IRComputeApplyStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.compute_name.is_empty() {
        "ComputeApply".to_string()
    } else {
        node.compute_name.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "compute_apply")?;

    let result = invoke_compute_capability(&node.compute_name, &node.arguments, ctx);

    if !node.output_name.is_empty() {
        ctx.let_bindings.insert(node.output_name.clone(), result.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &result, 0)?;

    Ok(NodeOutcome::Completed {
        output: result,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Listen
// ────────────────────────────────────────────────────────────────────

/// Listen on a typed channel. Wire shape: `step_type: "listen"`.
/// The placeholder `"(awaiting <channel>)"` binds under
/// `event_alias` until the Fase 13 typed-channel runtime wires
/// into the dispatcher in a future sub-fase.
pub async fn run_listen(
    node: &IRListenStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.event_alias.is_empty() {
        "Listen".to_string()
    } else {
        node.event_alias.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "listen")?;

    let placeholder = listen_on_channel(&node.channel, node.channel_is_ref, ctx);
    if !node.event_alias.is_empty() {
        ctx.let_bindings
            .insert(node.event_alias.clone(), placeholder.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &placeholder, 0)?;

    Ok(NodeOutcome::Completed {
        output: placeholder,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  DaemonStep
// ────────────────────────────────────────────────────────────────────

/// Invoke a daemon by reference. Wire shape:
/// `step_type: "daemon_step"`. The placeholder `"daemon:<ref>"`
/// binds under `<daemon_ref>_invoked` until the Fase 16
/// supervisor invocation surface wires into the dispatcher in a
/// future sub-fase.
pub async fn run_daemon_step(
    node: &IRDaemonStepNode,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.daemon_ref.is_empty() {
        "DaemonStep".to_string()
    } else {
        node.daemon_ref.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "daemon_step")?;

    let invoked = invoke_daemon(&node.daemon_ref, ctx);
    if !node.daemon_ref.is_empty() {
        ctx.let_bindings
            .insert(format!("{}_invoked", node.daemon_ref), invoked.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &invoked, 0)?;

    Ok(NodeOutcome::Completed {
        output: invoked,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Wire-event helpers (shared)
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

    // ── apply_* helpers (OSS identity passthrough) ───────────────────

    #[test]
    fn apply_shield_oss_default_is_identity() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(apply_shield_to_target("hipaa", "patient data", &ctx), "patient data");
    }

    #[test]
    fn apply_ots_oss_default_is_identity() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(apply_ots_to_target("audio_resampler", "raw bytes", &ctx), "raw bytes");
    }

    #[test]
    fn apply_mandate_oss_default_is_identity() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(apply_mandate_to_target("gdpr_erasure", "user record", &ctx), "user record");
    }

    #[test]
    fn invoke_compute_canonical_format_with_literal_args() {
        let (ctx, _rx) = fresh_ctx();
        let result = invoke_compute_capability(
            "sum",
            &["1".to_string(), "2".to_string(), "3".to_string()],
            &ctx,
        );
        assert_eq!(result, "compute:sum(1, 2, 3)");
    }

    #[test]
    fn invoke_compute_resolves_symbolic_args_through_let_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("a".into(), "10".into());
        ctx.let_bindings.insert("b".into(), "20".into());
        let result = invoke_compute_capability(
            "add",
            &["a".to_string(), "b".to_string()],
            &ctx,
        );
        assert_eq!(result, "compute:add(10, 20)");
    }

    #[test]
    fn listen_returns_canonical_awaiting_placeholder() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(listen_on_channel("event_bus", true, &ctx), "(awaiting event_bus)");
    }

    #[test]
    fn invoke_daemon_returns_canonical_invocation_placeholder() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(invoke_daemon("supervisor", &ctx), "daemon:supervisor");
    }

    // ── ShieldApply ──────────────────────────────────────────────────

    #[tokio::test]
    async fn run_shield_apply_binds_output_under_output_type() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("input_text".into(), "sensitive".into());
        let node = IRShieldApplyStep {
            node_type: "shield_apply",
            source_line: 0,
            source_column: 0,
            shield_name: "hipaa".into(),
            target: "input_text".into(),
            output_type: "scrubbed".into(),
        };
        let outcome = run_shield_apply(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, .. } => {
                assert_eq!(output, "sensitive");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("scrubbed").unwrap(), "sensitive");
        // Wire emits StepStart "shield_apply" + StepComplete.
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "shield_apply");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_shield_apply_canonical_fallback_output_key() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("doc".into(), "content".into());
        let node = IRShieldApplyStep {
            node_type: "shield_apply",
            source_line: 0,
            source_column: 0,
            shield_name: "hipaa".into(),
            target: "doc".into(),
            output_type: String::new(),
        };
        run_shield_apply(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("doc_shielded").unwrap(), "content");
    }

    // ── OtsApply ─────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_ots_apply_binds_output() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("raw_audio".into(), "samples".into());
        let node = IROtsApplyStep {
            node_type: "ots_apply",
            source_line: 0,
            source_column: 0,
            ots_name: "g711_mulaw".into(),
            target: "raw_audio".into(),
            output_type: "pcm".into(),
        };
        run_ots_apply(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("pcm").unwrap(), "samples");
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "ots_apply");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── MandateApply ─────────────────────────────────────────────────

    #[tokio::test]
    async fn run_mandate_apply_binds_output() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRMandateApplyStep {
            node_type: "mandate_apply",
            source_line: 0,
            source_column: 0,
            mandate_name: "gdpr_erasure".into(),
            target: "user_record".into(),
            output_type: "erased".into(),
        };
        run_mandate_apply(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("erased").unwrap(),
            "user_record"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "mandate_apply");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── ComputeApply ─────────────────────────────────────────────────

    #[tokio::test]
    async fn run_compute_apply_binds_result_under_output_name() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("x".into(), "5".into());
        ctx.let_bindings.insert("y".into(), "7".into());
        let node = IRComputeApplyStep {
            node_type: "compute_apply",
            source_line: 0,
            source_column: 0,
            compute_name: "add".into(),
            arguments: vec!["x".into(), "y".into()],
            output_name: "sum".into(),
        };
        run_compute_apply(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("sum").unwrap(), "compute:add(5, 7)");
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "compute_apply");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── Listen ───────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_listen_binds_placeholder_under_event_alias() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRListenStep {
            node_type: "listen",
            source_line: 0,
            source_column: 0,
            channel: "user_events".into(),
            channel_is_ref: true,
            event_alias: "evt".into(),
        };
        run_listen(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("evt").unwrap(),
            "(awaiting user_events)"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "listen");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── DaemonStep ───────────────────────────────────────────────────

    #[tokio::test]
    async fn run_daemon_step_binds_invocation_placeholder() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRDaemonStepNode {
            node_type: "daemon_step",
            source_line: 0,
            source_column: 0,
            daemon_ref: "audit_supervisor".into(),
        };
        run_daemon_step(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("audit_supervisor_invoked").unwrap(),
            "daemon:audit_supervisor"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "daemon_step");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── Cancel guards ────────────────────────────────────────────────

    #[tokio::test]
    async fn every_handler_short_circuits_on_cancel() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        assert!(matches!(
            run_shield_apply(
                &IRShieldApplyStep {
                    node_type: "shield_apply",
                    source_line: 0,
                    source_column: 0,
                    shield_name: "x".into(),
                    target: "y".into(),
                    output_type: "z".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_ots_apply(
                &IROtsApplyStep {
                    node_type: "ots_apply",
                    source_line: 0,
                    source_column: 0,
                    ots_name: "x".into(),
                    target: "y".into(),
                    output_type: "z".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_mandate_apply(
                &IRMandateApplyStep {
                    node_type: "mandate_apply",
                    source_line: 0,
                    source_column: 0,
                    mandate_name: "x".into(),
                    target: "y".into(),
                    output_type: "z".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_compute_apply(
                &IRComputeApplyStep {
                    node_type: "compute_apply",
                    source_line: 0,
                    source_column: 0,
                    compute_name: "x".into(),
                    arguments: vec![],
                    output_name: "y".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_listen(
                &IRListenStep {
                    node_type: "listen",
                    source_line: 0,
                    source_column: 0,
                    channel: "x".into(),
                    channel_is_ref: false,
                    event_alias: "y".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_daemon_step(
                &IRDaemonStepNode {
                    node_type: "daemon_step",
                    source_line: 0,
                    source_column: 0,
                    daemon_ref: "x".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));
    }
}
