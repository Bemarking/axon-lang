//! §Fase 33.y.d — Orchestration variant handlers.
//!
//! Six variants graduated in 33.y.d: `Let` / `Conditional` / `ForIn`
//! / `Break` / `Continue` / `Return`. Unlike the pure-shape variants
//! (Fase 33.y.c) these handlers DO NOT call `Backend::stream()`
//! directly; they compose child handlers via recursive
//! [`crate::flow_dispatcher::dispatch_node`] calls and surface
//! sentinel outcomes that propagate through the orchestration tree.
//!
//! # Handler responsibilities
//!
//! - [`run_let`] — Resolve the RHS (literal / reference into
//!   `ctx.let_bindings`) + bind into the scope. Does NOT emit wire
//!   events (Let is not a step from the adopter wire's perspective);
//!   does NOT advance `ctx.step_counter`. Returns
//!   `NodeOutcome::Completed { output: <resolved>, tokens_emitted: 0,
//!   step_index: <current> }`.
//!
//! - [`run_conditional`] — Evaluate the predicate (resolving LHS
//!   from `ctx.let_bindings`, comparing against `comparison_value`
//!   per `comparison_op`, joining multi-part conditions per
//!   `conjunctor`). Dispatch the chosen branch's body via
//!   recursive `dispatch_node` calls; thread sentinels (Break /
//!   LoopContinue / Return) up unchanged. `branch_path` segment:
//!   `"conditional.then"` or `"conditional.else"`.
//!
//! - [`run_for_in`] — Iterate over the `iterable` field (resolved
//!   from `ctx.let_bindings`, comma-split for the OSS scalar-list
//!   interpretation; collection-typed iteration ships in a future
//!   sub-fase). For each element: bind `variable` in
//!   `ctx.let_bindings`, push branch_path `"for_in[<index>]"`,
//!   dispatch body. Break sentinel → terminate loop early;
//!   LoopContinue → skip to next iter; Return → propagate up.
//!
//! - [`run_break`] — Returns `NodeOutcome::Break` immediately. The
//!   enclosing ForIn observes this + terminates. Parser scope check
//!   in `axon-frontend::parser::parse_break` guarantees this only
//!   appears inside a ForIn body, so the dispatcher does not need
//!   to validate scope at runtime.
//!
//! - [`run_continue`] — Same shape as `run_break`; returns
//!   `NodeOutcome::LoopContinue`.
//!
//! - [`run_return`] — Returns `NodeOutcome::Return { value }` where
//!   `value` is the IRReturnStep's `value_expr` field (resolved
//!   from `ctx.let_bindings` if it matches a binding name; literal
//!   otherwise).
//!
//! # Cancellation
//!
//! Every handler checks `ctx.cancel.is_cancelled()` at entry +
//! recursive dispatch_node calls propagate the cancel via their
//! own entry checks. ForIn additionally checks the cancel between
//! iterations so a cancel fired mid-loop terminates promptly.
//!
//! # D-letter anchors
//!
//! - **D1** — each orchestration variant has a NAMED async handler;
//!   the dispatcher arm delegates exhaustively (no `_ =>` fallback).
//! - **D3** — cancel propagation: entry checks + per-iter checks in
//!   ForIn surface `DispatchError::UpstreamCancelled` within ≤
//!   one dispatch-tick of the cancel firing.
//! - **D6** — `branch_path` segments thread orchestration shape:
//!   `"conditional.then"`, `"conditional.else"`, `"for_in[N]"`.
//!   Future Fase 33.y sub-fases that extend `StepAuditRecord` with
//!   `branch_path` will consume this directly.
//! - **D10** — semantic parity with the sync runner: Let bindings
//!   resolve identically; Conditional selects the same branch given
//!   the same input; ForIn iterates the same count; Break/Continue/
//!   Return produce byte-identical sentinel semantics.

use crate::flow_dispatcher::{dispatch_node, DispatchCtx, DispatchError, NodeOutcome};
use crate::ir_nodes::{
    IRBreakStep, IRConditional, IRContinueStep, IRForIn, IRLetBinding, IRReturnStep,
};

// ────────────────────────────────────────────────────────────────────
//  Let
// ────────────────────────────────────────────────────────────────────

/// Resolve the RHS + insert into `ctx.let_bindings`. Three
/// `value_kind` cases (closed catalog inherited from
/// `axon_frontend::parser::parse_let`):
///
/// - `"literal"` — the value is the literal string verbatim.
/// - `"reference"` — the value is a binding name; resolve from
///   `ctx.let_bindings` (returns empty string when unbound — same
///   posture as the sync runner's missing-reference behavior).
/// - `"expression"` — the value is a compound expression. 33.y.d's
///   pragmatic interpretation: treat as literal. Full expression
///   evaluation requires the AST-level expression evaluator that
///   ships in a future sub-fase.
pub async fn run_let(
    binding: &IRLetBinding,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let resolved = match binding.value_kind.as_str() {
        "reference" => ctx
            .let_bindings
            .get(&binding.value)
            .cloned()
            .unwrap_or_default(),
        // "literal", "expression", and any future value_kind fall
        // through to the literal path. value_kind is a closed
        // catalog in axon-frontend; a 4th variant would require
        // updating this match + the test surface in lockstep.
        _ => binding.value.clone(),
    };

    ctx.let_bindings.insert(binding.target.clone(), resolved.clone());

    Ok(NodeOutcome::Completed {
        output: resolved,
        tokens_emitted: 0,
        step_index: ctx.step_counter,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Conditional
// ────────────────────────────────────────────────────────────────────

/// Evaluate the predicate + dispatch the chosen branch.
///
/// # Predicate semantics
///
/// 1. Resolve LHS: if `cond.condition` is a key in
///    `ctx.let_bindings`, use its value; else treat the string
///    itself as the literal value.
/// 2. Compare against `comparison_value` per `comparison_op`:
///    - `"=="`, `"="` — equality
///    - `"!="` — inequality
///    - `">"`, `">="`, `"<"`, `"<="` — numeric comparison
///      (when both sides parse as f64; falls back to string
///      lexicographic comparison otherwise — matches sync runner
///      pragmatic posture for unconstrained `if x > y` semantics)
///    - empty string — treats LHS as a boolean (truthy iff non-empty
///      and not "false"/"0")
/// 3. Multi-part `conditions` joined by `conjunctor`:
///    - `"or"` — short-circuit disjunction (LHS clause OR each
///      subsequent (lhs, op, rhs) triple).
///    - other / empty — only the primary clause evaluated.
///
/// # Branch dispatch
///
/// Push `"conditional.then"` or `"conditional.else"` onto
/// `branch_path`. Iterate the chosen body via recursive
/// `dispatch_node`. Aggregate `tokens_emitted` across children.
/// Sentinels (Break / LoopContinue / Return) propagate up
/// unchanged. Pop `branch_path` on every exit path.
pub async fn run_conditional(
    cond: &IRConditional,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let branch_taken = evaluate_condition(cond, ctx);
    let body = if branch_taken {
        &cond.then_body
    } else {
        &cond.else_body
    };
    let branch_tag = if branch_taken {
        "conditional.then"
    } else {
        "conditional.else"
    };

    ctx.branch_path.push(branch_tag.to_string());
    let result = dispatch_body(body, ctx).await;
    ctx.branch_path.pop();
    result
}

/// Evaluate the closed-catalog predicate over `(condition,
/// comparison_op, comparison_value, conditions, conjunctor)`.
fn evaluate_condition(cond: &IRConditional, ctx: &DispatchCtx) -> bool {
    let primary = eval_triple(
        &cond.condition,
        &cond.comparison_op,
        &cond.comparison_value,
        ctx,
    );

    match cond.conjunctor.as_str() {
        "or" => {
            if primary {
                return true;
            }
            for (lhs, op, rhs) in &cond.conditions {
                if eval_triple(lhs, op, rhs, ctx) {
                    return true;
                }
            }
            false
        }
        // empty conjunctor or any future variant: primary only.
        _ => primary,
    }
}

fn eval_triple(lhs_raw: &str, op: &str, rhs: &str, ctx: &DispatchCtx) -> bool {
    let lhs = resolve_lhs(lhs_raw, ctx);
    match op {
        "==" | "=" => lhs == rhs,
        "!=" => lhs != rhs,
        ">" => numeric_cmp(&lhs, rhs).map_or(lhs.as_str() > rhs, |c| c.is_gt()),
        ">=" => numeric_cmp(&lhs, rhs).map_or(lhs.as_str() >= rhs, |c| c != std::cmp::Ordering::Less),
        "<" => numeric_cmp(&lhs, rhs).map_or(lhs.as_str() < rhs, |c| c.is_lt()),
        "<=" => numeric_cmp(&lhs, rhs).map_or(lhs.as_str() <= rhs, |c| c != std::cmp::Ordering::Greater),
        // Empty op: bare truthy check on LHS. Non-empty + not
        // "false"/"0" → true.
        "" => !lhs.is_empty() && lhs != "false" && lhs != "0",
        // Unknown operator — false by default. Closed-catalog the
        // parser shouldn't emit unknown operators; this is defensive
        // for the IR-construction-from-tests path.
        _ => false,
    }
}

fn resolve_lhs(name: &str, ctx: &DispatchCtx) -> String {
    ctx.let_bindings
        .get(name)
        .cloned()
        .unwrap_or_else(|| name.to_string())
}

fn numeric_cmp(a: &str, b: &str) -> Option<std::cmp::Ordering> {
    let a = a.parse::<f64>().ok()?;
    let b = b.parse::<f64>().ok()?;
    a.partial_cmp(&b)
}

// ────────────────────────────────────────────────────────────────────
//  ForIn
// ────────────────────────────────────────────────────────────────────

/// Iterate over the resolved iterable + dispatch the body per
/// element.
///
/// # Iterable resolution
///
/// `cond.iterable` is treated as a scalar-list reference: if it
/// names a binding in `ctx.let_bindings`, split its value on `,`
/// and trim each item; if no binding, split `iterable` itself on
/// `,`. Empty string → zero iterations.
///
/// # Variable binding
///
/// For each element, `ctx.let_bindings[variable] = element`.
/// Bindings persist between iterations — the same key is
/// overwritten — matching the sync runner's flow-scoped iter-var
/// semantics. After the loop, the binding holds the LAST iterated
/// value (or remains unset if zero iterations).
///
/// # Sentinel handling
///
/// - `NodeOutcome::Break` — exit the loop immediately. Returns
///   `Completed` with the aggregate output up to the break point.
/// - `NodeOutcome::LoopContinue` — skip to next iteration.
/// - `NodeOutcome::Return { value }` — propagate up unchanged.
///   Flow loop terminates.
///
/// # Branch path
///
/// Per-iter `"for_in[<index>]"` push/pop. Children inside the body
/// can read the current iteration index from this path.
pub async fn run_for_in(
    for_in: &IRForIn,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let items = resolve_iterable(&for_in.iterable, ctx);
    let mut aggregate_output = String::new();
    let mut aggregate_tokens: u64 = 0;
    let entry_step_index = ctx.step_counter;

    for (idx, item) in items.iter().enumerate() {
        if ctx.cancel.is_cancelled() {
            return Err(DispatchError::UpstreamCancelled);
        }

        ctx.let_bindings.insert(for_in.variable.clone(), item.clone());
        ctx.branch_path.push(format!("for_in[{idx}]"));

        let iter_outcome = dispatch_body(&for_in.body, ctx).await;

        ctx.branch_path.pop();

        match iter_outcome {
            Ok(NodeOutcome::Completed {
                output,
                tokens_emitted,
                ..
            }) => {
                if !output.is_empty() {
                    if !aggregate_output.is_empty() {
                        aggregate_output.push('\n');
                    }
                    aggregate_output.push_str(&output);
                }
                aggregate_tokens += tokens_emitted;
            }
            Ok(NodeOutcome::Break) => break,
            Ok(NodeOutcome::LoopContinue) => continue,
            Ok(NodeOutcome::Return { value }) => {
                return Ok(NodeOutcome::Return { value });
            }
            Ok(other) => {
                // LegacyShimHandled — sub-graduate. Treat as "iter
                // completed without producing output"; the
                // production wire surface keeps working because the
                // shimmed variant's wire emission (if any) already
                // fired through its dispatch path.
                let _ = other;
            }
            Err(e) => return Err(e),
        }
    }

    Ok(NodeOutcome::Completed {
        output: aggregate_output,
        tokens_emitted: aggregate_tokens,
        step_index: entry_step_index,
    })
}

fn resolve_iterable(iterable: &str, ctx: &DispatchCtx) -> Vec<String> {
    let raw = ctx
        .let_bindings
        .get(iterable)
        .cloned()
        .unwrap_or_else(|| iterable.to_string());
    if raw.trim().is_empty() {
        return Vec::new();
    }
    raw.split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

// ────────────────────────────────────────────────────────────────────
//  Break / Continue / Return — sentinel emitters
// ────────────────────────────────────────────────────────────────────

/// Emit the Break sentinel. Cancel-check guard for D3.
pub async fn run_break(
    _node: &IRBreakStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    Ok(NodeOutcome::Break)
}

/// Emit the LoopContinue sentinel. Cancel-check guard for D3.
pub async fn run_continue(
    _node: &IRContinueStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    Ok(NodeOutcome::LoopContinue)
}

/// Emit the Return sentinel with the resolved value.
///
/// `value_expr` is resolved through `ctx.let_bindings` first (so
/// `return foo` looks up `foo`'s bound value); falls back to the
/// literal string otherwise (so `return "literal"` works).
pub async fn run_return(
    node: &IRReturnStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let value = ctx
        .let_bindings
        .get(&node.value_expr)
        .cloned()
        .unwrap_or_else(|| node.value_expr.clone());
    Ok(NodeOutcome::Return { value })
}

// ────────────────────────────────────────────────────────────────────
//  Shared body dispatcher
// ────────────────────────────────────────────────────────────────────

/// Walk a body vector + dispatch each node, threading sentinels
/// up through the orchestration tree. Used by `run_conditional`
/// (for then/else bodies) + `run_for_in` (for each iter body).
///
/// `Box::pin` is used because `dispatch_node` may itself recurse
/// back into this dispatcher (orchestration nested inside
/// orchestration). The pinned boxed future breaks the otherwise-
/// infinite type recursion the compiler would otherwise reject.
async fn dispatch_body(
    body: &[crate::ir_nodes::IRFlowNode],
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let mut last_output = String::new();
    let mut total_tokens: u64 = 0;
    let entry_step_index = ctx.step_counter;

    for (i, child) in body.iter().enumerate() {
        if ctx.cancel.is_cancelled() {
            return Err(DispatchError::UpstreamCancelled);
        }

        ctx.branch_path.push(format!("step[{i}]"));
        let outcome = Box::pin(dispatch_node(child, ctx)).await;
        ctx.branch_path.pop();

        match outcome? {
            NodeOutcome::Completed {
                output,
                tokens_emitted,
                ..
            } => {
                if !output.is_empty() {
                    last_output = output;
                }
                total_tokens += tokens_emitted;
            }
            NodeOutcome::Break => return Ok(NodeOutcome::Break),
            NodeOutcome::LoopContinue => return Ok(NodeOutcome::LoopContinue),
            NodeOutcome::Return { value } => return Ok(NodeOutcome::Return { value }),
            NodeOutcome::LegacyShimHandled { .. } => {
                // Non-graduated child — no output captured. Future
                // sub-fases retire the shim per variant.
            }
        }
    }

    Ok(NodeOutcome::Completed {
        output: last_output,
        tokens_emitted: total_tokens,
        step_index: entry_step_index,
    })
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
        mpsc::UnboundedReceiver<crate::flow_execution_event::FlowExecutionEvent>,
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

    // ── Let ──────────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_let_literal_binds_value() {
        let (mut ctx, _rx) = fresh_ctx();
        let binding = IRLetBinding {
            node_type: "let",
            source_line: 0,
            source_column: 0,
            target: "region".into(),
            value: "us-east-1".into(),
            value_kind: "literal".into(),
        };
        let outcome = run_let(&binding, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed {
                output,
                tokens_emitted,
                ..
            } => {
                assert_eq!(output, "us-east-1");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("region").unwrap(), "us-east-1");
    }

    #[tokio::test]
    async fn run_let_reference_resolves_from_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("upstream".into(), "value-A".into());

        let binding = IRLetBinding {
            node_type: "let",
            source_line: 0,
            source_column: 0,
            target: "downstream".into(),
            value: "upstream".into(),
            value_kind: "reference".into(),
        };
        let outcome = run_let(&binding, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => {
                assert_eq!(output, "value-A");
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("downstream").unwrap(), "value-A");
    }

    #[tokio::test]
    async fn run_let_reference_missing_binding_yields_empty_string() {
        let (mut ctx, _rx) = fresh_ctx();
        let binding = IRLetBinding {
            node_type: "let",
            source_line: 0,
            source_column: 0,
            target: "x".into(),
            value: "nonexistent".into(),
            value_kind: "reference".into(),
        };
        let outcome = run_let(&binding, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => assert_eq!(output, ""),
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("x").unwrap(), "");
    }

    #[tokio::test]
    async fn run_let_does_not_advance_step_counter() {
        let (mut ctx, _rx) = fresh_ctx();
        assert_eq!(ctx.step_counter, 0);
        let binding = IRLetBinding {
            node_type: "let",
            source_line: 0,
            source_column: 0,
            target: "k".into(),
            value: "v".into(),
            value_kind: "literal".into(),
        };
        run_let(&binding, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.step_counter, 0,
            "Let MUST NOT advance the step counter (not a step from \
             the wire's perspective)"
        );
    }

    // ── Condition evaluator ───────────────────────────────────────────

    #[test]
    fn eval_triple_string_equality() {
        let ctx = fresh_ctx_no_rx().0;
        assert!(eval_triple("us", "==", "us", &ctx));
        assert!(!eval_triple("us", "==", "eu", &ctx));
        assert!(eval_triple("us", "!=", "eu", &ctx));
    }

    #[test]
    fn eval_triple_numeric_comparison() {
        let ctx = fresh_ctx_no_rx().0;
        assert!(eval_triple("5", ">", "3", &ctx));
        assert!(eval_triple("5", ">=", "5", &ctx));
        assert!(eval_triple("3", "<", "5", &ctx));
        assert!(eval_triple("5", "<=", "5", &ctx));
        assert!(!eval_triple("3", ">", "5", &ctx));
    }

    #[test]
    fn eval_triple_resolves_lhs_through_bindings() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("region".into(), "us".into());
        assert!(eval_triple("region", "==", "us", &ctx));
        assert!(!eval_triple("region", "==", "eu", &ctx));
    }

    #[test]
    fn eval_triple_truthy_empty_op() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("flag".into(), "yes".into());
        assert!(eval_triple("flag", "", "", &ctx));

        ctx.let_bindings.insert("falsy".into(), "false".into());
        assert!(!eval_triple("falsy", "", "", &ctx));

        ctx.let_bindings.insert("zero".into(), "0".into());
        assert!(!eval_triple("zero", "", "", &ctx));

        ctx.let_bindings.insert("empty".into(), "".into());
        assert!(!eval_triple("empty", "", "", &ctx));
    }

    fn fresh_ctx_no_rx() -> (DispatchCtx, mpsc::UnboundedReceiver<crate::flow_execution_event::FlowExecutionEvent>) {
        let (tx, rx) = mpsc::unbounded_channel();
        let ctx = DispatchCtx::new("F", "stub", "", CancellationFlag::new(), tx);
        (ctx, rx)
    }

    // ── Iterable resolver ─────────────────────────────────────────────

    #[test]
    fn resolve_iterable_splits_comma_list_from_binding() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("regions".into(), "us,eu,asia".into());
        let items = resolve_iterable("regions", &ctx);
        assert_eq!(items, vec!["us", "eu", "asia"]);
    }

    #[test]
    fn resolve_iterable_trims_whitespace() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("xs".into(), " a , b , c ".into());
        assert_eq!(resolve_iterable("xs", &ctx), vec!["a", "b", "c"]);
    }

    #[test]
    fn resolve_iterable_falls_back_to_literal_string() {
        let ctx = fresh_ctx_no_rx().0;
        assert_eq!(resolve_iterable("a,b", &ctx), vec!["a", "b"]);
    }

    #[test]
    fn resolve_iterable_empty_yields_zero_items() {
        let ctx = fresh_ctx_no_rx().0;
        assert!(resolve_iterable("", &ctx).is_empty());
    }

    // ── Break / Continue / Return ─────────────────────────────────────

    #[tokio::test]
    async fn run_break_returns_break_sentinel() {
        let (mut ctx, _rx) = fresh_ctx();
        let outcome = run_break(
            &IRBreakStep {
                node_type: "break",
                source_line: 0,
                source_column: 0,
            },
            &mut ctx,
        )
        .await
        .unwrap();
        assert!(matches!(outcome, NodeOutcome::Break));
    }

    #[tokio::test]
    async fn run_continue_returns_loop_continue_sentinel() {
        let (mut ctx, _rx) = fresh_ctx();
        let outcome = run_continue(
            &IRContinueStep {
                node_type: "continue",
                source_line: 0,
                source_column: 0,
            },
            &mut ctx,
        )
        .await
        .unwrap();
        assert!(matches!(outcome, NodeOutcome::LoopContinue));
    }

    #[tokio::test]
    async fn run_return_with_literal_value() {
        let (mut ctx, _rx) = fresh_ctx();
        let outcome = run_return(
            &IRReturnStep {
                node_type: "return",
                source_line: 0,
                source_column: 0,
                value_expr: "ok".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        match outcome {
            NodeOutcome::Return { value } => assert_eq!(value, "ok"),
            other => panic!("expected Return, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_return_resolves_through_let_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("result".into(), "computed".into());
        let outcome = run_return(
            &IRReturnStep {
                node_type: "return",
                source_line: 0,
                source_column: 0,
                value_expr: "result".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        match outcome {
            NodeOutcome::Return { value } => assert_eq!(value, "computed"),
            other => panic!("expected Return, got {other:?}"),
        }
    }

    // ── Cancel guards ────────────────────────────────────────────────

    #[tokio::test]
    async fn every_orchestration_handler_short_circuits_on_cancel() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        let binding = IRLetBinding {
            node_type: "let",
            source_line: 0,
            source_column: 0,
            target: "x".into(),
            value: "y".into(),
            value_kind: "literal".into(),
        };
        assert!(matches!(
            run_let(&binding, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        let cond = IRConditional {
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
        };
        assert!(matches!(
            run_conditional(&cond, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        let for_in = IRForIn {
            node_type: "for_in",
            source_line: 0,
            source_column: 0,
            variable: "i".into(),
            iterable: String::new(),
            body: Vec::new(),
        };
        assert!(matches!(
            run_for_in(&for_in, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_break(
                &IRBreakStep {
                    node_type: "break",
                    source_line: 0,
                    source_column: 0,
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_continue(
                &IRContinueStep {
                    node_type: "continue",
                    source_line: 0,
                    source_column: 0,
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        assert!(matches!(
            run_return(
                &IRReturnStep {
                    node_type: "return",
                    source_line: 0,
                    source_column: 0,
                    value_expr: String::new(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));
    }

    // ── Conditional + body composition ────────────────────────────────

    #[tokio::test]
    async fn conditional_then_branch_dispatched_when_eq() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("region".into(), "us".into());
        let cond = IRConditional {
            node_type: "conditional",
            source_line: 0,
            source_column: 0,
            condition: "region".into(),
            comparison_op: "==".into(),
            comparison_value: "us".into(),
            then_body: vec![IRFlowNode::Let(IRLetBinding {
                node_type: "let",
                source_line: 0,
                source_column: 0,
                target: "took".into(),
                value: "then-branch".into(),
                value_kind: "literal".into(),
            })],
            else_body: Vec::new(),
            conditions: Vec::new(),
            conjunctor: String::new(),
        };
        run_conditional(&cond, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("took").unwrap(), "then-branch");
    }

    #[tokio::test]
    async fn conditional_else_branch_dispatched_when_ne() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("region".into(), "us".into());
        let cond = IRConditional {
            node_type: "conditional",
            source_line: 0,
            source_column: 0,
            condition: "region".into(),
            comparison_op: "==".into(),
            comparison_value: "eu".into(),
            then_body: Vec::new(),
            else_body: vec![IRFlowNode::Let(IRLetBinding {
                node_type: "let",
                source_line: 0,
                source_column: 0,
                target: "took".into(),
                value: "else-branch".into(),
                value_kind: "literal".into(),
            })],
            conditions: Vec::new(),
            conjunctor: String::new(),
        };
        run_conditional(&cond, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("took").unwrap(), "else-branch");
    }

    // ── ForIn composition ─────────────────────────────────────────────

    #[tokio::test]
    async fn for_in_iterates_each_element() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("xs".into(), "a,b,c".into());

        let for_in = IRForIn {
            node_type: "for_in",
            source_line: 0,
            source_column: 0,
            variable: "x".into(),
            iterable: "xs".into(),
            body: vec![IRFlowNode::Let(IRLetBinding {
                node_type: "let",
                source_line: 0,
                source_column: 0,
                target: "last".into(),
                value: "x".into(),
                value_kind: "reference".into(),
            })],
        };
        run_for_in(&for_in, &mut ctx).await.unwrap();
        // After 3 iters, "last" should hold the final value "c".
        assert_eq!(ctx.let_bindings.get("last").unwrap(), "c");
        // Iteration variable is left bound to last item.
        assert_eq!(ctx.let_bindings.get("x").unwrap(), "c");
    }

    #[tokio::test]
    async fn for_in_break_terminates_loop() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("xs".into(), "a,b,c".into());
        let for_in = IRForIn {
            node_type: "for_in",
            source_line: 0,
            source_column: 0,
            variable: "x".into(),
            iterable: "xs".into(),
            body: vec![IRFlowNode::Break(IRBreakStep {
                node_type: "break",
                source_line: 0,
                source_column: 0,
            })],
        };
        run_for_in(&for_in, &mut ctx).await.unwrap();
        // Only 1 iteration before break — variable bound to first.
        assert_eq!(ctx.let_bindings.get("x").unwrap(), "a");
    }

    #[tokio::test]
    async fn for_in_zero_iterations_when_iterable_empty() {
        let (mut ctx, _rx) = fresh_ctx();
        let for_in = IRForIn {
            node_type: "for_in",
            source_line: 0,
            source_column: 0,
            variable: "x".into(),
            iterable: "".into(),
            body: vec![IRFlowNode::Let(IRLetBinding {
                node_type: "let",
                source_line: 0,
                source_column: 0,
                target: "marker".into(),
                value: "ran".into(),
                value_kind: "literal".into(),
            })],
        };
        run_for_in(&for_in, &mut ctx).await.unwrap();
        assert!(ctx.let_bindings.get("marker").is_none());
    }

    #[tokio::test]
    async fn for_in_return_propagates_through_loop() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("xs".into(), "a,b,c".into());
        let for_in = IRForIn {
            node_type: "for_in",
            source_line: 0,
            source_column: 0,
            variable: "x".into(),
            iterable: "xs".into(),
            body: vec![IRFlowNode::Return(IRReturnStep {
                node_type: "return",
                source_line: 0,
                source_column: 0,
                value_expr: "early".into(),
            })],
        };
        let outcome = run_for_in(&for_in, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Return { value } => assert_eq!(value, "early"),
            other => panic!("expected Return propagation, got {other:?}"),
        }
    }
}
