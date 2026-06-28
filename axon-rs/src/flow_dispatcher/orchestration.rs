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
    // §Fase 70.a — a condition the legacy triple cannot express carries a
    // lowered pure expression; evaluate it with the expression evaluator.
    // Fail-closed on a type error (`None`) → the branch is not taken. The
    // legacy path below is byte-identical to pre-§70 (only reached when the
    // condition fit the legacy shape, i.e. `cond.cond == None`).
    if let Some(expr) = &cond.cond {
        return eval_expr(expr, ctx).map(|v| eval_truthy(&v)).unwrap_or(false);
    }

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
//  §Fase 70.a — the pure expression evaluator
// ────────────────────────────────────────────────────────────────────

/// A runtime expression value. The existing runtime is string-typed
/// (`let_bindings: HashMap<String,String>`); `EVal` recovers Int/Float/Bool
/// precision for arithmetic + numeric comparison while coercing to/from strings
/// at the boundary. Total + pure — no side effects, no I/O.
#[derive(Debug, Clone)]
enum EVal {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
}

/// Evaluate a lowered pure expression. Returns `None` on a type error / domain
/// error (non-numeric arithmetic, division-by-zero, integer overflow) so the
/// caller fail-closes. This evaluator runs ONLY for `cond = Some` (rich, post-§70
/// conditions), so it defines clean numeric-aware semantics with no obligation
/// to reproduce the legacy `eval_triple` string quirks.
fn eval_expr(e: &crate::ir_nodes::IRExpr, ctx: &DispatchCtx) -> Option<EVal> {
    use crate::ir_nodes::{IRExpr, IRExprLit};
    match e {
        IRExpr::Lit { lit } => Some(match lit {
            IRExprLit::Int { value } => EVal::Int(*value),
            IRExprLit::Float { value } => EVal::Float(*value),
            IRExprLit::Bool { value } => EVal::Bool(*value),
            IRExprLit::Str { value } => EVal::Str(value.clone()),
        }),
        IRExpr::Ref { path } => Some(eval_coerce_str(resolve_lhs(path, ctx))),
        IRExpr::Unary { op, operand } => {
            let v = eval_expr(operand, ctx)?;
            match op.as_str() {
                "not" => Some(EVal::Bool(!eval_truthy(&v))),
                "neg" => match v {
                    EVal::Int(i) => i.checked_neg().map(EVal::Int),
                    other => Some(EVal::Float(-eval_as_num(&other)?)),
                },
                _ => None,
            }
        }
        IRExpr::Binary { op, lhs, rhs } => match op.as_str() {
            // Short-circuit boolean operators.
            "and" => {
                let l = eval_expr(lhs, ctx)?;
                if !eval_truthy(&l) {
                    return Some(EVal::Bool(false));
                }
                Some(EVal::Bool(eval_truthy(&eval_expr(rhs, ctx)?)))
            }
            "or" => {
                let l = eval_expr(lhs, ctx)?;
                if eval_truthy(&l) {
                    return Some(EVal::Bool(true));
                }
                Some(EVal::Bool(eval_truthy(&eval_expr(rhs, ctx)?)))
            }
            _ => {
                let l = eval_expr(lhs, ctx)?;
                let r = eval_expr(rhs, ctx)?;
                eval_binop(op, &l, &r)
            }
        },
        // §Fase 70.c — closed-catalog builtin call.
        IRExpr::Call { builtin, args } => eval_builtin(builtin, args, ctx),
    }
}

/// §Fase 70.c — evaluate a pure builtin call. `args[0]` is the receiver.
fn eval_builtin(name: &str, args: &[crate::ir_nodes::IRExpr], ctx: &DispatchCtx) -> Option<EVal> {
    let recv = eval_to_str(&eval_expr(args.first()?, ctx)?);
    match name {
        "length" | "count" => Some(EVal::Int(builtin_length(&recv))),
        "is_empty" => Some(EVal::Bool(builtin_length(&recv) == 0)),
        "is_null" => {
            let t = recv.trim();
            Some(EVal::Bool(t.is_empty() || t == "null"))
        }
        "contains" => {
            let needle = eval_to_str(&eval_expr(args.get(1)?, ctx)?);
            Some(EVal::Bool(builtin_contains(&recv, &needle)))
        }
        "starts_with" => {
            let p = eval_to_str(&eval_expr(args.get(1)?, ctx)?);
            Some(EVal::Bool(recv.starts_with(&p)))
        }
        "ends_with" => {
            let s = eval_to_str(&eval_expr(args.get(1)?, ctx)?);
            Some(EVal::Bool(recv.ends_with(&s)))
        }
        _ => None,
    }
}

/// `.length` / `.count`: JSON array → element count; a retrieve envelope →
/// `rows` count; any other value → character count of the string.
fn builtin_length(s: &str) -> i64 {
    match serde_json::from_str::<serde_json::Value>(s) {
        Ok(serde_json::Value::Array(a)) => a.len() as i64,
        Ok(serde_json::Value::Object(m))
            if m.get("taint").map(|t| t.is_string()).unwrap_or(false) =>
        {
            match m.get("rows") {
                Some(serde_json::Value::Array(rows)) => rows.len() as i64,
                _ => 0,
            }
        }
        _ => s.chars().count() as i64,
    }
}

/// `.contains(x)`: JSON array → element membership (string-compared); any other
/// value → substring containment.
fn builtin_contains(recv: &str, needle: &str) -> bool {
    if let Ok(serde_json::Value::Array(a)) = serde_json::from_str::<serde_json::Value>(recv) {
        return a.iter().any(|e| match e {
            serde_json::Value::String(s) => s == needle,
            other => other.to_string() == needle,
        });
    }
    recv.contains(needle)
}

fn eval_binop(op: &str, l: &EVal, r: &EVal) -> Option<EVal> {
    match op {
        "add" | "sub" | "mul" | "div" | "mod" => {
            // Exact integer path when both sides are integers; else float.
            if let (Some(li), Some(ri)) = (eval_as_int(l), eval_as_int(r)) {
                let res = match op {
                    "add" => li.checked_add(ri)?,
                    "sub" => li.checked_sub(ri)?,
                    "mul" => li.checked_mul(ri)?,
                    "div" => li.checked_div(ri)?, // None on /0 or overflow
                    "mod" => li.checked_rem(ri)?,
                    _ => unreachable!(),
                };
                return Some(EVal::Int(res));
            }
            let (lf, rf) = (eval_as_num(l)?, eval_as_num(r)?);
            let res = match op {
                "add" => lf + rf,
                "sub" => lf - rf,
                "mul" => lf * rf,
                "div" => {
                    if rf == 0.0 {
                        return None;
                    }
                    lf / rf
                }
                "mod" => {
                    if rf == 0.0 {
                        return None;
                    }
                    lf % rf
                }
                _ => unreachable!(),
            };
            Some(EVal::Float(res))
        }
        "eq" => Some(EVal::Bool(eval_eq(l, r))),
        "ne" => Some(EVal::Bool(!eval_eq(l, r))),
        "lt" | "le" | "gt" | "ge" => {
            let ord = eval_cmp(l, r)?;
            use std::cmp::Ordering;
            Some(EVal::Bool(match op {
                "lt" => ord == Ordering::Less,
                "le" => ord != Ordering::Greater,
                "gt" => ord == Ordering::Greater,
                "ge" => ord != Ordering::Less,
                _ => unreachable!(),
            }))
        }
        _ => None,
    }
}

/// Coerce a resolved binding string to the most specific `EVal`.
fn eval_coerce_str(s: String) -> EVal {
    if let Ok(i) = s.parse::<i64>() {
        return EVal::Int(i);
    }
    if let Ok(f) = s.parse::<f64>() {
        return EVal::Float(f);
    }
    match s.as_str() {
        "true" => EVal::Bool(true),
        "false" => EVal::Bool(false),
        _ => EVal::Str(s),
    }
}

fn eval_as_int(v: &EVal) -> Option<i64> {
    match v {
        EVal::Int(i) => Some(*i),
        _ => None,
    }
}

fn eval_as_num(v: &EVal) -> Option<f64> {
    match v {
        EVal::Int(i) => Some(*i as f64),
        EVal::Float(f) => Some(*f),
        EVal::Str(s) => s.parse::<f64>().ok(),
        EVal::Bool(_) => None,
    }
}

fn eval_to_str(v: &EVal) -> String {
    match v {
        EVal::Int(i) => i.to_string(),
        EVal::Float(f) => f.to_string(),
        EVal::Bool(b) => b.to_string(),
        EVal::Str(s) => s.clone(),
    }
}

/// Equality: numeric when both coerce to numbers, boolean when both bools,
/// otherwise string equality.
fn eval_eq(l: &EVal, r: &EVal) -> bool {
    if let (Some(a), Some(b)) = (eval_as_num(l), eval_as_num(r)) {
        return a == b;
    }
    if let (EVal::Bool(a), EVal::Bool(b)) = (l, r) {
        return a == b;
    }
    eval_to_str(l) == eval_to_str(r)
}

/// Ordering: numeric when both coerce to numbers, otherwise lexical (mirrors
/// the legacy `numeric_cmp` fallback).
fn eval_cmp(l: &EVal, r: &EVal) -> Option<std::cmp::Ordering> {
    if let (Some(a), Some(b)) = (eval_as_num(l), eval_as_num(r)) {
        return a.partial_cmp(&b);
    }
    Some(eval_to_str(l).cmp(&eval_to_str(r)))
}

/// Truthiness: bool is itself; a number is truthy iff non-zero; a string is
/// truthy iff non-empty and not `"false"`/`"0"` (matching `eval_triple`'s bare
/// truthy check so a bare-ref condition is consistent across both paths).
fn eval_truthy(v: &EVal) -> bool {
    match v {
        EVal::Bool(b) => *b,
        EVal::Int(i) => *i != 0,
        EVal::Float(f) => *f != 0.0,
        EVal::Str(s) => !s.is_empty() && s != "false" && s != "0",
    }
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
    // §Fase 66.1 — resolve the iterable REFERENCE like every other value
    // position: `for e in ClassifyEdges.output` is the canonical form, and a
    // step binds its output under its bare NAME — so the `.output` suffix must
    // map to the step-name key. Pre-§66.1 this was a bare exact-key lookup, so
    // `ClassifyEdges.output` missed → fell back to the literal string
    // `"ClassifyEdges.output"`, which then comma-split into one bogus item and
    // made every `${e.field}` miss (the kivi brief #28 repro: `${e.to_id}`
    // reached Postgres verbatim).
    let raw = crate::exec_context::resolve_value_reference(iterable, &ctx.let_bindings);
    collection_elements_of(&raw)
}

/// §Fase 66/67.g — the canonical "what does this value iterate as" rule, shared
/// by `for … in` (above) and the §70.c collection builtins (`.length`,
/// `.count`, `.is_empty`, `.contains`) so a collection's size/membership is
/// exactly its iteration set. A JSON ARRAY → its elements; a retrieve EPISTEMIC
/// ENVELOPE (`{taint, …, rows:[…]}`) → its `rows`; anything else (a plain
/// string, a comma list) → the pre-§66 comma-split (byte-identical).
fn collection_elements_of(raw: &str) -> Vec<String> {
    if raw.trim().is_empty() {
        return Vec::new();
    }
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Array(elems)) => iterable_elements(elems),
        Ok(serde_json::Value::Object(map))
            if map.get("taint").map(|t| t.is_string()).unwrap_or(false) =>
        {
            match map.get("rows") {
                Some(serde_json::Value::Array(rows)) => iterable_elements(rows.clone()),
                _ => Vec::new(),
            }
        }
        _ => raw
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect(),
    }
}

/// Re-serialise each JSON element of an iterable into the per-loop-var string
/// binding: an object/array element to its compact JSON (so the §66 dotted
/// resolver can parse it back for `${var.field}`), a string element to its
/// inner text, a scalar to its compact form. Shared by the bare-array (step
/// `List<T>` output) and the retrieve-envelope `rows` (§67.g) paths so both
/// bind loop vars identically.
fn iterable_elements(elems: Vec<serde_json::Value>) -> Vec<String> {
    elems
        .into_iter()
        .map(|v| match v {
            serde_json::Value::String(s) => s,
            serde_json::Value::Object(_) | serde_json::Value::Array(_) => v.to_string(),
            other => other.to_string(),
        })
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
/// `value_expr` is resolved like every other value position (§66.1): `${X}` /
/// `${Step}` interpolation, a `Step.output` reference (the `.output` maps to the
/// step-name key), a bare `let`/param/step name, else the literal string.
///
/// §Fase 66.1 — pre-fix this did a bare exact-key lookup, so `return "${Summarize}"`
/// returned the LITERAL `${Summarize}` and `return Summarize.output` returned the
/// literal `Summarize.output` (the kivi brief #28 §C bug — interpolation worked in
/// a `persist` value via `store_row` but NOT in `return`). Now both resolve, so a
/// non-streaming flow returns the actual step output, matching the persist path.
pub async fn run_return(
    node: &IRReturnStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let value = crate::exec_context::resolve_value_reference(&node.value_expr, &ctx.let_bindings);
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

    // ── §Fase 70.a — the pure expression evaluator ───────────────────

    fn lit_int(v: i64) -> Box<IRExpr> {
        Box::new(IRExpr::Lit {
            lit: IRExprLit::Int { value: v },
        })
    }
    fn eref(p: &str) -> Box<IRExpr> {
        Box::new(IRExpr::Ref { path: p.into() })
    }
    fn bin(op: &str, l: Box<IRExpr>, r: Box<IRExpr>) -> IRExpr {
        IRExpr::Binary {
            op: op.into(),
            lhs: l,
            rhs: r,
        }
    }

    #[test]
    fn eval_expr_integer_arithmetic_is_exact() {
        let ctx = fresh_ctx_no_rx().0;
        // 2 + 3 * 4 = 14 (the parser builds the precedence tree; here we test eval)
        let e = bin("add", lit_int(2), Box::new(bin("mul", lit_int(3), lit_int(4))));
        assert!(matches!(eval_expr(&e, &ctx), Some(EVal::Int(14))));
    }

    #[test]
    fn eval_expr_division_by_zero_fails_closed() {
        let ctx = fresh_ctx_no_rx().0;
        let e = bin("div", lit_int(5), lit_int(0));
        assert!(eval_expr(&e, &ctx).is_none(), "div by zero → None (fail-closed)");
    }

    #[test]
    fn eval_expr_modulo() {
        let ctx = fresh_ctx_no_rx().0;
        let e = bin("mod", lit_int(17), lit_int(5));
        assert!(matches!(eval_expr(&e, &ctx), Some(EVal::Int(2))));
    }

    #[test]
    fn eval_expr_count_ge_limit_over_bindings() {
        // The headline: `recent >= limit` natively, no Tool needed.
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("recent".into(), "8".into());
        ctx.let_bindings.insert("limit".into(), "5".into());
        let e = bin("ge", eref("recent"), eref("limit"));
        assert!(eval_truthy(&eval_expr(&e, &ctx).unwrap()));
        // Below the limit → false.
        ctx.let_bindings.insert("recent".into(), "3".into());
        assert!(!eval_truthy(&eval_expr(&e, &ctx).unwrap()));
    }

    #[test]
    fn eval_expr_boolean_and_or_short_circuit() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("a".into(), "true".into());
        ctx.let_bindings.insert("b".into(), "false".into());
        let and = bin("and", eref("a"), eref("b"));
        assert!(!eval_truthy(&eval_expr(&and, &ctx).unwrap()));
        let or = bin("or", eref("a"), eref("b"));
        assert!(eval_truthy(&eval_expr(&or, &ctx).unwrap()));
    }

    #[test]
    fn eval_expr_not_negates_truthiness() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("ready".into(), "false".into());
        let e = IRExpr::Unary {
            op: "not".into(),
            operand: eref("ready"),
        };
        assert!(eval_truthy(&eval_expr(&e, &ctx).unwrap()));
    }

    #[test]
    fn evaluate_condition_routes_rich_cond_through_expr() {
        // An IRConditional with a `cond` expr is evaluated by the expr engine.
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("recent".into(), "9".into());
        ctx.let_bindings.insert("cap".into(), "10".into());
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
            cond: Some(bin("lt", eref("recent"), eref("cap"))),
        };
        assert!(evaluate_condition(&cond, &ctx), "9 < 10 → then branch");
    }

    // ── §Fase 70.c — collection / string builtins ────────────────────

    fn estr(s: &str) -> Box<IRExpr> {
        Box::new(IRExpr::Lit {
            lit: IRExprLit::Str { value: s.into() },
        })
    }
    fn call(name: &str, args: Vec<Box<IRExpr>>) -> IRExpr {
        IRExpr::Call {
            builtin: name.into(),
            args: args.into_iter().map(|b| *b).collect(),
        }
    }

    #[test]
    fn builtin_length_counts_json_array_elements() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("xs".into(), "[1,2,3]".into());
        let e = call("length", vec![eref("xs")]);
        assert!(matches!(eval_expr(&e, &ctx), Some(EVal::Int(3))));
    }

    #[test]
    fn builtin_length_of_a_string_is_char_count() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("s".into(), "hello".into());
        let e = call("length", vec![eref("s")]);
        assert!(matches!(eval_expr(&e, &ctx), Some(EVal::Int(5))));
    }

    #[test]
    fn builtin_length_unwraps_a_retrieve_envelope() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert(
            "rows".into(),
            r#"{"taint":"trusted","rows":[{"id":1},{"id":2}]}"#.into(),
        );
        let e = call("length", vec![eref("rows")]);
        assert!(matches!(eval_expr(&e, &ctx), Some(EVal::Int(2))));
    }

    #[test]
    fn builtin_contains_array_membership_and_substring() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("xs".into(), r#"["a","b","c"]"#.into());
        let in_arr = call("contains", vec![eref("xs"), estr("b")]);
        assert!(eval_truthy(&eval_expr(&in_arr, &ctx).unwrap()));
        ctx.let_bindings.insert("name".into(), "Dr. Smith".into());
        let sub = call("contains", vec![eref("name"), estr("Smith")]);
        assert!(eval_truthy(&eval_expr(&sub, &ctx).unwrap()));
    }

    #[test]
    fn builtin_starts_with_and_ends_with() {
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("n".into(), "Dr. House".into());
        assert!(eval_truthy(&eval_expr(&call("starts_with", vec![eref("n"), estr("Dr")]), &ctx).unwrap()));
        assert!(eval_truthy(&eval_expr(&call("ends_with", vec![eref("n"), estr("House")]), &ctx).unwrap()));
        assert!(!eval_truthy(&eval_expr(&call("starts_with", vec![eref("n"), estr("Mr")]), &ctx).unwrap()));
    }

    #[test]
    fn throttle_headline_recent_length_ge_limit() {
        // The adopter's throttle, end-to-end through evaluate_condition.
        let mut ctx = fresh_ctx_no_rx().0;
        ctx.let_bindings.insert("recent".into(), "[1,2,3,4,5,6,7,8]".into());
        ctx.let_bindings.insert("limit".into(), "5".into());
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
            cond: Some(bin("ge", Box::new(call("length", vec![eref("recent")])), eref("limit"))),
        };
        assert!(evaluate_condition(&cond, &ctx), "8 recent >= limit 5 → then");
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
            cond: None,
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
            cond: None,
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
            cond: None,
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

    // ── §Fase 66 (Q1) — structured iteration of a List<Record> ──────────

    #[test]
    fn resolve_iterable_iterates_json_array_elements_as_structured_records() {
        // `for e in ClassifyEdges.output` where the output is a List<Record>
        // JSON array: each element must bind to its OWN compact JSON object (so
        // `${e.field}` resolves it), NOT a comma-split fragment of the array.
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert(
            "edges".to_string(),
            r#"[{"to_id":"a","etype":"cite"},{"to_id":"b","etype":"elaborate"}]"#.to_string(),
        );
        let items = resolve_iterable("edges", &ctx);
        assert_eq!(items.len(), 2, "two array elements, not comma-split shards");
        // Each item is a parseable JSON object carrying the whole record.
        let first: serde_json::Value = serde_json::from_str(&items[0]).expect("element is JSON");
        assert_eq!(first["to_id"], "a");
        assert_eq!(first["etype"], "cite");
        // And it composes with the §66 dotted interpolation: bind `e` = element.
        ctx.let_bindings.insert("e".to_string(), items[1].clone());
        assert_eq!(
            crate::exec_context::interpolate_vars("${e.to_id}", &ctx.let_bindings),
            "b"
        );
    }

    #[test]
    fn resolve_iterable_unwraps_a_retrieve_envelope_into_its_rows() {
        // §Fase 67.g (kivi brief #35): `for s in to_hibernate` where
        // `to_hibernate` is a `retrieve … as: to_hibernate` binding. A retrieve
        // binds an EPISTEMIC ENVELOPE object (not a bare array), so pre-fix the
        // object failed the array check, fell to the comma-split, and shredded
        // the JSON → every `${s.col}` reached `persist`/`where:` verbatim. Now we
        // unwrap `rows` and iterate row objects exactly like a step's array
        // output, so `${s.<col>}` resolves identically (the #27/#28 fix, for
        // store rows whose shape comes from the axonstore schema, not a `type`).
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert(
            "to_hibernate".to_string(),
            r#"{"taint":"untrusted","confidence_floor":null,"trusted_rows":2,"below_floor_filtered":0,"rows":[{"tenant_id":"t-1","session_id_generic":"s-1","conversation_id":"c-1"},{"tenant_id":"t-2","session_id_generic":"s-2","conversation_id":"c-2"}]}"#.to_string(),
        );
        let items = resolve_iterable("to_hibernate", &ctx);
        assert_eq!(items.len(), 2, "two rows, not envelope comma-shards");
        // Each item is the row object — `${s.<col>}` resolves in EVERY position
        // (persist value, `where:`, mutate all route through interpolate_vars).
        ctx.let_bindings.insert("s".to_string(), items[0].clone());
        assert_eq!(
            crate::exec_context::interpolate_vars("${s.tenant_id}", &ctx.let_bindings),
            "t-1",
            "the brief #35 repro: `${{s.tenant_id}}` must resolve, not stay literal"
        );
        assert_eq!(
            crate::exec_context::interpolate_vars(
                "session_id == '${s.session_id_generic}'",
                &ctx.let_bindings
            ),
            "session_id == 's-1'",
            "and inside a sub-`where:` clause string too"
        );
    }

    #[test]
    fn resolve_iterable_empty_retrieve_envelope_yields_zero_iterations() {
        // A retrieve that matched 0 rows binds an envelope with an empty `rows`
        // array — the `for` must run ZERO times (not one comma-shard iteration
        // over the envelope scaffolding). The §C/Q3 honest-empty contract.
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert(
            "empty".to_string(),
            r#"{"taint":"untrusted","confidence_floor":null,"trusted_rows":0,"below_floor_filtered":0,"rows":[]}"#.to_string(),
        );
        assert!(resolve_iterable("empty", &ctx).is_empty());
    }

    #[test]
    fn resolve_iterable_non_json_falls_back_to_comma_split() {
        // Back-compat: a plain comma list iterates byte-identically to pre-§66.
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings
            .insert("xs".to_string(), "a, b, c".to_string());
        assert_eq!(resolve_iterable("xs", &ctx), vec!["a", "b", "c"]);
        // A JSON array of plain strings yields each string (not quoted).
        ctx.let_bindings
            .insert("ys".to_string(), r#"["x","y"]"#.to_string());
        assert_eq!(resolve_iterable("ys", &ctx), vec!["x", "y"]);
    }

    // ── §Fase 66.1 — the canonical `for e in Step.output` repro (kivi #28) ─

    #[test]
    fn resolve_iterable_resolves_a_step_output_reference_to_its_array() {
        // The CANONICAL form: `for e in ClassifyEdges.output`. The step binds its
        // output under the BARE NAME `ClassifyEdges`; pre-§66.1 `resolve_iterable`
        // did exact `get("ClassifyEdges.output")` → miss → literal → 1 bogus item.
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert(
            "ClassifyEdges".to_string(),
            r#"[{"to_id":"11111111-1111-1111-1111-111111111111","etype":"supersede"}]"#.to_string(),
        );
        let items = resolve_iterable("ClassifyEdges.output", &ctx);
        assert_eq!(items.len(), 1, "the step-output array iterates as ONE record");
        // And `${e.to_id}` resolves on the bound element (the #28 failure).
        ctx.let_bindings.insert("e".to_string(), items[0].clone());
        assert_eq!(
            crate::exec_context::interpolate_vars("${e.to_id}", &ctx.let_bindings),
            "11111111-1111-1111-1111-111111111111"
        );
    }

    #[tokio::test]
    async fn run_return_resolves_interpolation_and_step_output() {
        // kivi #28 §C: `return "${Summarize}"` and `return Summarize.output` must
        // return the step's OUTPUT, not the literal (interpolation worked in a
        // persist value but not in return pre-§66.1).
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings
            .insert("Summarize".to_string(), "the real summary".to_string());

        for expr in ["${Summarize}", "Summarize.output", "Summarize"] {
            let node = IRReturnStep {
                node_type: "return",
                source_line: 0,
                source_column: 0,
                value_expr: expr.to_string(),
            };
            match run_return(&node, &mut ctx).await.unwrap() {
                NodeOutcome::Return { value } => {
                    assert_eq!(value, "the real summary", "`return {expr}` must resolve")
                }
                other => panic!("expected Return, got {other:?}"),
            }
        }
    }
}
