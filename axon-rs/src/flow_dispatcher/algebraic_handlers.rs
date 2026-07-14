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
/// passthrough. This helper is the **no-scanner fallback**: as of
/// §Fase 40.b, [`run_shield_apply`] first consults
/// [`crate::shield_registry`]; this function only runs when no scanner
/// is registered for the shield name. Enterprise vertical crates
/// register HIPAA / legal / fintech scanners via
/// [`crate::shield_registry::register_shield_scanner`].
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

// §Fase 111.f — `invoke_compute_capability` was DELETED here.
//
// It was the factory of the lie. It resolved the arguments and returned
// `format!("compute:{name}({args})")` — a STRING, which `run_compute_apply` bound
// under the step's output name and a downstream step then consumed as if it were
// a number. Its doc comment claimed "OSS default: returns a canonical formatted
// string … Enterprise overrides hook into the real compute runtime". No such hook
// existed, and no override could have helped: `IRCompute` carried no body to run.
//
// `run_compute_apply` now evaluates the declared §70 expression natively via
// `eval_expr`. There is nothing left for a placeholder to stand in for.

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

    // §Fase 40.b — consult the shield-scanner registry. A registered
    // scanner (enterprise HIPAA/legal/AML, etc.) returns a verdict:
    // `Pass` binds the (possibly redacted) content; `Reject` surfaces a
    // structured `DispatchError::BackendError` so the SSE/HTTP layer can
    // attribute blame. When NO scanner is registered for this name, the
    // OSS identity passthrough applies (backwards-compatible — adopters
    // with no enterprise layer see their data unmodified).
    let shielded = match crate::shield_registry::lookup_shield_scanner(&node.shield_name) {
        Some(scanner) => {
            let scan_ctx = crate::shield_registry::ShieldScanContext::new(node.shield_name.clone());
            match scanner.scan(&resolved_target, &scan_ctx) {
                crate::shield_registry::ShieldVerdict::Pass(content) => content,
                crate::shield_registry::ShieldVerdict::Reject { code, reason } => {
                    return Err(DispatchError::BackendError {
                        name: format!("shield:{}", node.shield_name),
                        message: format!("[{code}] {reason}"),
                    });
                }
            }
        }
        None => apply_shield_to_target(&node.shield_name, &resolved_target, ctx),
    };

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

/// **§Fase 111.f — `compute` MADE REAL.** Wire shape: `step_type: "compute_apply"`.
///
/// # What this used to be (§111 F10 — the loudest lie in the README)
///
/// `invoke_compute_capability` returned the **literal string**
/// `"compute:CalculatePremium(x_value, 1.2)"`. That string was bound under
/// `output_name`, and **a downstream step consumed it as if it were a number**.
///
/// It did not fall through to the LLM, so it was not *hallucinating* in the §108
/// sense — it was worse in one specific way: it was a **fabricated determinism
/// guarantee**. The README advertises `compute` as *"Deterministic muscle —
/// native Fast-Path execution **bypassing the LLM**"* and even asserts a
/// complexity class (*"compute steps: O(n) — linear in input size, native
/// execution"*). `IRCompute` carried only `name` and `shield_ref`: **no
/// parameters, no body**. There was nothing to execute, natively or otherwise.
/// The parser skipped the parameters token by token and the apply site hardcoded
/// `arguments: Vec::new()`.
///
/// # What it is now
///
/// A named **pure function over the §70 expression language** — the closed,
/// total, side-effect-free term algebra the runtime already evaluates natively
/// via `eval_expr` (the same evaluator behind `let`, `grad` and `conditional`).
///
/// ```text
/// compute Premium(base: Number, rate: Number) -> Number { base * rate * 1.2 }
/// …
/// compute Premium on amount, r -> premium      // premium is a NUMBER
/// ```
///
/// Linear in the term. **No model in the loop.** The advertised claim, made true
/// rather than made louder — and every failure is a refusal, never a string
/// wearing a number's clothes.
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

    // (1) Resolve the declared function.
    let spec = ctx
        .compute_specs
        .iter()
        .find(|c| c.name == node.compute_name)
        .cloned()
        .ok_or_else(|| DispatchError::BackendError {
            name: "compute".to_string(),
            message: format!(
                "`compute {}` does not resolve to a declared compute — nothing to execute",
                node.compute_name
            ),
        })?;

    // (2) A compute with no body cannot compute. REFUSE rather than bind a
    //     placeholder string that a downstream step will read as a number.
    let body = spec.body.clone().ok_or_else(|| DispatchError::BackendError {
        name: "compute".to_string(),
        message: format!(
            "`compute {}` declares no body — it cannot compute anything. Give it one: \
             `compute {}(x: Number) -> Number {{ x * 2 }}`. Binding a placeholder here is how \
             the pre-§111 runtime handed a downstream step the text \"compute:{}(…)\" where it \
             expected a number (§111 F10)",
            spec.name, spec.name, spec.name
        ),
    })?;

    // (3) Arity. A silent mismatch would evaluate the body against a stale or
    //     missing binding and still produce *a* number — the worst outcome.
    if node.arguments.len() != spec.parameters.len() {
        return Err(DispatchError::BackendError {
            name: "compute".to_string(),
            message: format!(
                "`compute {} on …` was applied to {} argument(s) but declares {} parameter(s) ({}). \
                 A silent arity mismatch would still yield a number — just the wrong one",
                spec.name,
                node.arguments.len(),
                spec.parameters.len(),
                spec.parameters
                    .iter()
                    .map(|p| p.name.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        });
    }

    // (4) Bind the arguments into the call frame: each declared parameter takes
    //     the value of its positional argument, resolved from the caller's
    //     bindings. Saved and restored, so a parameter name cannot leak out of
    //     the compute and shadow the caller's own binding.
    let mut saved: Vec<(String, Option<String>)> = Vec::new();
    for (param, arg) in spec.parameters.iter().zip(&node.arguments) {
        let value = crate::exec_context::resolve_value_reference(arg, &ctx.let_bindings);
        saved.push((param.name.clone(), ctx.let_bindings.get(&param.name).cloned()));
        ctx.let_bindings.insert(param.name.clone(), value);
    }

    // (5) Evaluate — natively, deterministically, with no model in the loop.
    let evaluated = crate::flow_dispatcher::orchestration::eval_expr(&body, ctx);

    // Restore the frame before doing anything else with the result.
    for (name, prior) in saved {
        match prior {
            Some(v) => {
                ctx.let_bindings.insert(name, v);
            }
            None => {
                ctx.let_bindings.remove(&name);
            }
        }
    }

    use crate::flow_dispatcher::orchestration::EVal;
    let result = match evaluated {
        Some(EVal::Int(i)) => i.to_string(),
        Some(EVal::Float(f)) => f.to_string(),
        Some(EVal::Bool(b)) => b.to_string(),
        Some(EVal::Str(s)) => s,
        // The §70 evaluator fails CLOSED on division by zero, an unresolvable
        // reference, a type mismatch — every one of which the old handler would
        // have papered over with a plausible-looking string.
        _ => {
            return Err(DispatchError::BackendError {
                name: "compute".to_string(),
                message: format!(
                    "`compute {}` did not evaluate — the expression could not be reduced to a \
                     value (an unresolvable reference, a type mismatch, or a division by zero). \
                     Refusing: a compute that cannot compute must not return something that LOOKS \
                     like a result",
                    spec.name
                ),
            })
        }
    };

    if !node.output_name.is_empty() {
        ctx.let_bindings
            .insert(node.output_name.clone(), result.clone());
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

/// §Fase 52.c — `run <Flow>(args)` flow-step: invoke a declared flow from a
/// body (a daemon `listen` handler — the brief #32 Q3). The LANGUAGE surface
/// (parse / type-check / IR / this dispatcher arm) lands here; the REAL
/// recursive flow dispatch — looking up `flow_name` in the program and
/// executing its steps under the daemon's identity — is wired by the §52.c
/// daemon executor (it needs the flow registry + the recursion guard, which
/// this leaf dispatcher does not own). Until then this binds the invocation
/// outcome under `output_to` (if any) so downstream steps resolve, mirroring
/// the surface-handler pattern §51 used for `quant`/`yield`.
pub async fn run_run(
    node: &axon_frontend::ir_nodes::IRRun,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, &node.flow_name, step_index, "run")?;
    let outcome = format!("(invoking flow {})", node.flow_name);
    if !node.output_to.is_empty() {
        ctx.let_bindings
            .insert(node.output_to.clone(), outcome.clone());
    }
    emit_step_complete(ctx, &node.flow_name, step_index, &outcome, 0)?;

    Ok(NodeOutcome::Completed {
        output: outcome,
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
                branch_path: ctx.branch_path_string(),
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
                branch_path: ctx.branch_path_string(),
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

    // ── ShieldApply × §Fase 40.b registry hook ───────────────────────
    // Unique shield names + cleanup so these don't collide with the
    // "hipaa" identity tests above under parallel execution.

    struct RedactScanner;
    impl crate::shield_registry::ShieldScanner for RedactScanner {
        fn scan(
            &self,
            _target: &str,
            _ctx: &crate::shield_registry::ShieldScanContext,
        ) -> crate::shield_registry::ShieldVerdict {
            crate::shield_registry::ShieldVerdict::pass("[REDACTED]")
        }
    }

    struct BlockScanner;
    impl crate::shield_registry::ShieldScanner for BlockScanner {
        fn scan(
            &self,
            _target: &str,
            _ctx: &crate::shield_registry::ShieldScanContext,
        ) -> crate::shield_registry::ShieldVerdict {
            crate::shield_registry::ShieldVerdict::reject("phi.unredacted", "PHI present")
        }
    }

    #[tokio::test]
    async fn run_shield_apply_routes_through_registered_scanner() {
        const NAME: &str = "t40b_redact";
        crate::shield_registry::register_shield_scanner(NAME, std::sync::Arc::new(RedactScanner));

        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("note".into(), "SSN 123-45-6789".into());
        let node = IRShieldApplyStep {
            node_type: "shield_apply",
            source_line: 0,
            source_column: 0,
            shield_name: NAME.into(),
            target: "note".into(),
            output_type: "scrubbed".into(),
        };
        let outcome = run_shield_apply(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => assert_eq!(output, "[REDACTED]"),
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("scrubbed").unwrap(), "[REDACTED]");

        crate::shield_registry::unregister_shield_scanner(NAME);
    }

    #[tokio::test]
    async fn run_shield_apply_rejecting_scanner_surfaces_backend_error() {
        const NAME: &str = "t40b_block";
        crate::shield_registry::register_shield_scanner(NAME, std::sync::Arc::new(BlockScanner));

        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("note".into(), "raw phi".into());
        let node = IRShieldApplyStep {
            node_type: "shield_apply",
            source_line: 0,
            source_column: 0,
            shield_name: NAME.into(),
            target: "note".into(),
            output_type: "scrubbed".into(),
        };
        let err = run_shield_apply(&node, &mut ctx).await.unwrap_err();
        match err {
            DispatchError::BackendError { name, message } => {
                assert_eq!(name, format!("shield:{NAME}"));
                assert!(message.contains("phi.unredacted"), "blame code in message");
                assert!(message.contains("PHI present"), "reason in message");
            }
            other => panic!("expected BackendError, got {other:?}"),
        }
        // A rejected shield must NOT bind output.
        assert!(ctx.let_bindings.get("scrubbed").is_none());

        crate::shield_registry::unregister_shield_scanner(NAME);
    }

    #[tokio::test]
    async fn run_shield_apply_unregistered_name_is_identity() {
        // No scanner registered under this unique name → OSS identity.
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("doc".into(), "untouched".into());
        let node = IRShieldApplyStep {
            node_type: "shield_apply",
            source_line: 0,
            source_column: 0,
            shield_name: "t40b_never_registered".into(),
            target: "doc".into(),
            output_type: "out".into(),
        };
        let outcome = run_shield_apply(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => assert_eq!(output, "untouched"),
            other => panic!("expected Completed, got {other:?}"),
        }
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

    /// §Fase 111.f — **this test used to BE the bug.**
    ///
    /// It asserted, in green, for years:
    ///
    /// ```text
    /// assert_eq!(ctx.let_bindings.get("sum").unwrap(), "compute:add(5, 7)");
    /// ```
    ///
    /// A test demanding that the sum of 5 and 7 be the **string**
    /// `"compute:add(5, 7)"` — and a downstream step would then consume that text
    /// where it expected a number, while the README promised "native Fast-Path
    /// execution bypassing the LLM" with an O(n) guarantee.
    ///
    /// The placeholder was not an oversight the tests missed. **The tests pinned
    /// it.** That is worth staring at: a suite can lock a lie in place as firmly
    /// as it locks a truth.
    ///
    /// It now asserts the opposite — an undeclared compute REFUSES rather than
    /// binding something that looks like a result.
    #[tokio::test]
    async fn run_compute_apply_refuses_an_undeclared_compute() {
        let (mut ctx, _rx) = fresh_ctx();
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
        let err = run_compute_apply(&node, &mut ctx)
            .await
            .expect_err("an undeclared compute must refuse, not bind a placeholder string");
        assert!(format!("{err:?}").contains("does not resolve to a declared compute"));
        assert!(
            ctx.let_bindings.get("sum").is_none(),
            "nothing may be bound for a compute that did not compute"
        );
    }

    /// …and a DECLARED compute really adds. `5 + 7 = 12`, a number, zero tokens.
    #[tokio::test]
    async fn run_compute_apply_evaluates_the_declared_expression_natively() {
        use crate::ir_nodes::{IRCompute, IRExpr, IRParameter};

        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("x".into(), "5".into());
        ctx.let_bindings.insert("y".into(), "7".into());

        let p = |n: &str| IRParameter {
            node_type: "parameter",
            source_line: 0,
            source_column: 0,
            name: n.into(),
            type_name: "Number".into(),
            generic_param: String::new(),
            optional: false,
        };
        ctx.compute_specs = std::sync::Arc::new(vec![IRCompute {
            node_type: "compute",
            source_line: 0,
            source_column: 0,
            name: "add".into(),
            shield_ref: String::new(),
            parameters: vec![p("a"), p("b")],
            return_type: "Number".into(),
            body: Some(IRExpr::Binary {
                op: "add".into(),
                lhs: Box::new(IRExpr::Ref { path: "a".into() }),
                rhs: Box::new(IRExpr::Ref { path: "b".into() }),
            }),
        }]);

        let node = IRComputeApplyStep {
            node_type: "compute_apply",
            source_line: 0,
            source_column: 0,
            compute_name: "add".into(),
            arguments: vec!["x".into(), "y".into()],
            output_name: "sum".into(),
        };
        let outcome = run_compute_apply(&node, &mut ctx).await.unwrap();

        assert_eq!(
            ctx.let_bindings.get("sum").unwrap(),
            "12",
            "5 + 7 = 12 — a NUMBER. This is the line the old test got wrong"
        );
        match outcome {
            NodeOutcome::Completed { tokens_emitted, .. } => assert_eq!(
                tokens_emitted, 0,
                "`compute` bypasses the LLM — that is the entire primitive"
            ),
            e => panic!("expected Completed, got {e:?}"),
        }

        match rx.try_recv().unwrap() {
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
            body: Vec::new(),
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
                    body: Vec::new(),
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
