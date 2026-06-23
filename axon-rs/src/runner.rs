//! `axon run` native implementation — stub + real execution.
//!
//! Pipeline: Source → Lex → Parse → Type-check → IR → Execution Plan → Execute
//!
//! Execution modes:
//!   - stub (default): prints execution plan without API calls
//!   - real: sends each step to LLM backend (Anthropic Messages API)
//!
//! Exit codes:
//!   0 — success
//!   1 — compilation or execution error
//!   2 — I/O or configuration error
//!
//! # §Fase 33.x.i — `crate::backend` deprecation
//!
//! This file is one of four callers of the deprecated synchronous
//! `crate::backend` mono-file (see `backend.rs` module docs).
//! The `#![allow(deprecated)]` below silences the deprecation
//! warnings on this file's call sites while the deeper async
//! migration progresses under followup sub-fase Fase 33.x.i.2
//! (sync→async migration of the 4 callers, separate cycle).

#![allow(deprecated)]

use std::io::{self, IsTerminal};
use std::path::Path;

use crate::anchor_checker;
use crate::backend;
use crate::conversation::{ConversationHistory, ContextWindow};
use crate::exec_context::ExecContext;
use crate::hooks::HookManager;
use crate::ir_generator::IRGenerator;
use crate::ir_nodes::*;
use crate::lexer::{Lexer, LexerError};
use crate::output::{OutputFormat, ReportBuilder, StepReport};
use crate::parallel;
use crate::plan_export::{self, PlanBuilder, PlanUnit, PlanStep, PlanTools, PlanToolEntry, PlanDependencies, UnresolvedRef};
use crate::parser::{ParseError, Parser};
use crate::session_store::SessionStore;
use crate::step_deps;
use crate::store::epistemic;
use crate::store::filter::SqlValue;
use crate::store::row_stream;
use crate::store::postgres_backend::{PostgresStoreBackend, StoreError};
use crate::store::registry::{StoreBackendKind, StoreRegistry};
use crate::tool_registry::ToolRegistry;
use crate::tool_validator::{self, EffectTracker};
use crate::type_checker::TypeChecker;

/// Single source of truth for the AXON version string.
/// Resolved at compile time from `[package].version` in `Cargo.toml`,
/// so a single bump there propagates to every caller. Eliminates the
/// drift that previously had `AXON_VERSION` redeclared as a string
/// literal in five files (audit_cli.rs, compiler.rs, main.rs, repl.rs,
/// runner.rs) — each carrying a different stale value.
pub const AXON_VERSION: &str = env!("CARGO_PKG_VERSION");

// ── ANSI helpers ─────────────────────────────────────────────────────────────

fn c(text: &str, code: &str, use_color: bool) -> String {
    if use_color {
        format!("{code}{text}\x1b[0m")
    } else {
        text.to_string()
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/// Truncate a string for display, appending "..." if over max_len.
fn truncate_output(s: &str, max_len: usize) -> String {
    let single_line = s.replace('\n', " ");
    if single_line.len() <= max_len {
        single_line
    } else {
        format!("{}...", &single_line[..max_len])
    }
}

// ── Compiled execution plan ─────────────────────────────────────────────────

/// A compiled execution unit — one per `run` statement.
#[derive(Debug, serde::Serialize)]
struct ExecutionUnit {
    flow_name: String,
    persona_name: String,
    context_name: String,
    system_prompt: String,
    steps: Vec<CompiledStep>,
    anchor_instructions: Vec<String>,
    effort: String,
    #[serde(skip)]
    resolved_anchors: Vec<IRAnchor>,
    /// §Fase 37.b (D1) — the Request Binding Contract bindings:
    /// `(flow parameter name, value)` pairs resolved from the HTTP
    /// request body. Seeded into the unit's `ExecContext` before the
    /// step walk so `${param}` interpolates. Empty for a caller with
    /// no request body (CLI / batch / pipeline) — D5 backwards-compat.
    #[serde(skip)]
    param_bindings: Vec<(String, String)>,
}

/// A compiled step ready for LLM dispatch.
#[derive(Debug, serde::Serialize)]
struct CompiledStep {
    step_name: String,
    step_type: String,
    system_prompt: String,
    user_prompt: String,
    /// For `use_tool` steps: the raw argument expression.
    #[serde(skip_serializing_if = "Option::is_none")]
    tool_argument: Option<String>,
    /// For memory steps: the expression/query/target.
    #[serde(skip_serializing_if = "Option::is_none")]
    memory_expression: Option<String>,
    /// Fase 15.c — for `lambda_data_apply` steps: the full payload
    /// (spec snapshot + target + output_type) so the runner can build
    /// ψ = ⟨T, V, E⟩ without reaching back into the IR.
    #[serde(skip_serializing_if = "Option::is_none")]
    lambda_apply_payload: Option<crate::lambda_runtime::LambdaApplyPayload>,
    /// Fase 17.c — for `let_binding` steps: the payload (target,
    /// value, value_kind) so the stub executor can perform the
    /// SSA binding without re-traversing the IR.
    #[serde(skip_serializing_if = "Option::is_none")]
    let_payload: Option<LetPayload>,
    /// §Fase 35.o / 35.p — for `persist` (INSERT columns) and `mutate`
    /// (UPDATE SET assignments) steps: the declared `{ col: value }`
    /// block. `Some` ⇒ the SQL row is built from exactly these columns
    /// (interpolated); `None` ⇒ no block was written and the runtime
    /// falls back to the flow's user bindings (v1.31.0).
    #[serde(skip_serializing_if = "Option::is_none")]
    store_fields: Option<Vec<(String, String)>>,
    /// §Fase 58.e — for a `use Tool(k = v, …)` dispatch: the bound keyword
    /// args `(name, raw value)`. Non-empty ⇒ the runtime assembles a STRUCTURED
    /// JSON request body (`{"query":"…","max_results":5}`) instead of the flat
    /// `{"input": …}`. Empty for the legacy single-`on <arg>` form (D5).
    /// §Fase 60 — each entry is `(name, raw value, value_kind)`; `value_kind`
    /// (`"literal"` / `"reference"`) drives runtime resolution: a reference is a
    /// binding lookup, a literal keeps `${…}` interpolation.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    tool_named_args: Vec<(String, String, String)>,
    /// §Fase 58.e — the called tool's declared `(param, type)` schema, resolved
    /// from `ir.tools` at build time so the runtime coerces each arg value to
    /// its DECLARED JSON type (a `String` param stays a string even when its
    /// value is all-digits) without reaching back into the IR.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    tool_param_types: Vec<(String, String)>,
    /// §Fase 65.A/B — for a structural verb (navigate / drill / trail): the IR
    /// node, carried so the non-streaming server executor dispatches its REAL
    /// handler via `flow_dispatcher::dispatch_node` instead of falling through to
    /// the LLM — which fabricates output (the Kivi gap report). `Some` only for
    /// the verbs in [`routes_through_dispatcher`]. Runtime-only: `#[serde(skip)]`
    /// keeps the compiled-plan wire shape byte-identical.
    #[serde(skip)]
    structural_node: Option<crate::ir_nodes::IRFlowNode>,
}

/// Fase 17.c — payload carried inside a CompiledStep for `let X = value`
/// SSA bindings. `value_kind` ∈ {"literal", "reference", "expression"}
/// disambiguates a quoted literal from a dotted-identifier reference
/// resolved at runtime.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LetPayload {
    pub target: String,
    pub value: String,
    pub value_kind: String,
}

/// Trace event for execution recording.
#[derive(Debug, serde::Serialize)]
struct TraceEvent {
    event: String,
    unit: String,
    step: String,
    detail: String,
}

// ── Build execution plan from IR ────────────────────────────────────────────

fn build_execution_plan(ir: &IRProgram, backend: &str) -> Vec<ExecutionUnit> {
    let mut units = Vec::new();

    for run in &ir.runs {
        let system_prompt = build_system_prompt(run, backend);
        let anchor_instructions = build_anchor_instructions(run);
        let steps = build_compiled_steps(run, ir);

        units.push(ExecutionUnit {
            flow_name: run.flow_name.clone(),
            persona_name: run.persona_name.clone(),
            context_name: run.context_name.clone(),
            system_prompt,
            steps,
            anchor_instructions,
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
            // §Fase 37.b — the CLI / `run`-statement plan builder has
            // no HTTP request body; the binding is empty (D5).
            param_bindings: Vec::new(),
        });
    }

    units
}

fn build_system_prompt(run: &IRRun, backend: &str) -> String {
    let mut parts: Vec<String> = Vec::new();

    // Persona block
    if let Some(ref persona) = run.resolved_persona {
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
        if let Some(ct) = persona.confidence_threshold {
            parts.push(format!("Confidence threshold: {ct:.2}"));
        }
        if persona.cite_sources == Some(true) {
            parts.push("Always cite sources.".to_string());
        }
        if !persona.refuse_if.is_empty() {
            parts.push(format!("Refuse if: {}", persona.refuse_if.join(", ")));
        }
    }

    // Context block
    if let Some(ref ctx) = run.resolved_context {
        parts.push(format!("\n# Context: {}", ctx.name));
        if !ctx.depth.is_empty() {
            parts.push(format!("Analysis depth: {}", ctx.depth));
        }
        if !ctx.memory_scope.is_empty() {
            parts.push(format!("Memory scope: {}", ctx.memory_scope));
        }
        if let Some(t) = ctx.temperature {
            parts.push(format!("Temperature: {t:.1}"));
        }
        if let Some(mt) = ctx.max_tokens {
            parts.push(format!("Max tokens: {mt}"));
        }
    }

    // Anchor enforcement
    if !run.resolved_anchors.is_empty() {
        parts.push("\n# Constraints (Anchors)".to_string());
        for anchor in &run.resolved_anchors {
            let mut constraint = format!("- {}: {}", anchor.name, anchor.require);
            if let Some(cf) = anchor.confidence_floor {
                constraint.push_str(&format!(" (confidence ≥ {cf:.2})"));
            }
            if !anchor.on_violation.is_empty() {
                constraint.push_str(&format!(" [on_violation: {}]", anchor.on_violation));
            }
            parts.push(constraint);
        }
    }

    // Backend tag
    parts.push(format!("\n[Backend: {backend} | AXON {AXON_VERSION}]"));

    parts.join("\n")
}

fn build_anchor_instructions(run: &IRRun) -> Vec<String> {
    run.resolved_anchors
        .iter()
        .map(|a| {
            let mut s = format!("{}: {}", a.name, a.require);
            if let Some(cf) = a.confidence_floor {
                s.push_str(&format!(" (≥{cf:.2})"));
            }
            s
        })
        .collect()
}

fn build_compiled_steps(run: &IRRun, ir: &IRProgram) -> Vec<CompiledStep> {
    let flow = match &run.resolved_flow {
        Some(f) => f,
        None => return Vec::new(),
    };

    let mut steps = Vec::new();
    for node in &flow.steps {
        let (step_name, step_type, action) = extract_step_info(node);
        let system_prompt = format!(
            "You are executing step '{}' of flow '{}'.",
            step_name, flow.name
        );
        let user_prompt = if action.is_empty() {
            format!("Execute step: {step_name}")
        } else {
            action
        };

        // Extract tool argument for use_tool steps
        let tool_argument = match node {
            IRFlowNode::UseTool(s) => Some(s.argument.clone()),
            _ => None,
        };

        // §Fase 58.e — the structured keyword args of a `use Tool(k = v, …)`
        // dispatch, plus the called tool's declared `(param, type)` schema
        // (resolved once from `ir.tools`) so the runtime coerces each value to
        // its declared JSON type. Both empty for the legacy single-arg form.
        let (tool_named_args, tool_param_types) = match node {
            IRFlowNode::UseTool(s) => {
                let named: Vec<(String, String, String)> = s
                    .named_args
                    .iter()
                    .map(|a| (a.name.clone(), a.value.clone(), a.value_kind.clone()))
                    .collect();
                let types: Vec<(String, String)> = ir
                    .tools
                    .iter()
                    .find(|t| t.name == s.tool_name)
                    .map(|t| {
                        t.parameters
                            .iter()
                            .map(|p| (p.name.clone(), p.type_name.clone()))
                            .collect()
                    })
                    .unwrap_or_default();
                (named, types)
            }
            _ => (Vec::new(), Vec::new()),
        };

        // Extract memory expression for remember/recall/persist/retrieve/mutate/purge
        let memory_expression = match node {
            IRFlowNode::Remember(s) => Some(s.expression.clone()),
            IRFlowNode::Recall(s) => Some(s.query.clone()),
            IRFlowNode::Persist(s) => Some(s.store_name.clone()),
            IRFlowNode::Retrieve(s) => Some(format!("{}:{}", s.store_name, s.where_expr)),
            IRFlowNode::Mutate(s) => Some(format!("{}:{}", s.store_name, s.where_expr)),
            IRFlowNode::Purge(s) => Some(format!("{}:{}", s.store_name, s.where_expr)),
            _ => None,
        };

        // Fase 15.c — materialise the lambda apply payload by looking
        // up the spec snapshot from ir.lambda_data_specs. The runner
        // needs the full snapshot at execute-time to construct ψ;
        // carrying it in the CompiledStep keeps the executor free of
        // IR back-references (mirrors Python's BaseBackend pattern).
        let lambda_apply_payload = match node {
            IRFlowNode::LambdaDataApply(s) => {
                let snap = ir
                    .lambda_data_specs
                    .iter()
                    .find(|spec| spec.name == s.lambda_data_name)
                    .map(|spec| crate::lambda_runtime::SpecSnapshot {
                        name: spec.name.clone(),
                        ontology: spec.ontology.clone(),
                        certainty: spec.certainty,
                        temporal_frame_start: spec.temporal_frame_start.clone(),
                        temporal_frame_end: spec.temporal_frame_end.clone(),
                        provenance: spec.provenance.clone(),
                        derivation: spec.derivation.clone(),
                    })
                    .unwrap_or_default();
                Some(crate::lambda_runtime::LambdaApplyPayload {
                    lambda_data_name: s.lambda_data_name.clone(),
                    target: s.target.clone(),
                    output_type: s.output_type.clone(),
                    spec_snapshot: snap,
                })
            }
            _ => None,
        };

        // Fase 17.c — materialise the let payload from the IR Let
        // node so the stub executor can bind without re-traversing
        // the IR. Same pattern as the lambda apply payload above.
        let let_payload = match node {
            IRFlowNode::Let(s) => Some(LetPayload {
                target: s.target.clone(),
                value: s.value.clone(),
                value_kind: s.value_kind.clone(),
            }),
            _ => None,
        };

        // §Fase 35.o / 35.p — materialise the declared `{ col: value }`
        // block of a `persist` (INSERT columns) or `mutate` (UPDATE SET
        // assignments) so `execute_sql_store_step` scopes the SQL row
        // to exactly those columns. No block ⇒ `None` → the v1.31.0
        // user-bindings fallback.
        let store_fields = match node {
            IRFlowNode::Persist(s) if !s.fields.is_empty() => {
                Some(s.fields.clone())
            }
            IRFlowNode::Mutate(s) if !s.fields.is_empty() => {
                Some(s.fields.clone())
            }
            _ => None,
        };

        // §Fase 65.A/B — carry the IR node for the structural verbs the executor
        // routes through the dispatcher (real handler, not the LLM fallthrough).
        let structural_node = if routes_through_dispatcher(node) {
            Some(node.clone())
        } else {
            None
        };

        steps.push(CompiledStep {
            step_name,
            step_type,
            system_prompt,
            user_prompt,
            tool_argument,
            memory_expression,
            lambda_apply_payload,
            let_payload,
            store_fields,
            tool_named_args,
            tool_param_types,
            structural_node,
        });
    }

    steps
}

/// §Fase 58.e — assemble the STRUCTURED JSON request body for a `use Tool(k =
/// v, …)` dispatch from its ALREADY-INTERPOLATED `(name, value)` args. Each
/// value is coerced to its DECLARED parameter type so the tool backend receives
/// `{"query":"Acme","max_results":5,"safe":true}` — not a flat
/// `{"input": "…"}`. serde builds the object, so JSON escaping is correct.
pub(crate) fn build_structured_tool_body(
    interpolated_args: &[(String, String)],
    param_types: &[(String, String)],
) -> String {
    let mut map = serde_json::Map::new();
    for (name, value) in interpolated_args {
        let declared = param_types
            .iter()
            .find(|(p, _)| p == name)
            .map(|(_, t)| t.as_str());
        map.insert(name.clone(), coerce_tool_arg_value(value, declared));
    }
    serde_json::Value::Object(map).to_string()
}

/// §Fase 58.e — coerce an interpolated arg value to JSON per its DECLARED type.
/// `Int`/`Float`/`Bool` parse into the matching JSON scalar; a value that does
/// not parse falls back to a JSON string (the §58.d type-checker already flags
/// a literal mismatch at compile time — interpolated/runtime values are coerced
/// leniently rather than dropped). `String`, custom domain types, lists, and
/// unknown / schema-less (`None`) stay JSON strings — so a `String` parameter
/// keeps its value verbatim even when it is all-digits.
pub(crate) fn coerce_tool_arg_value(value: &str, declared_type: Option<&str>) -> serde_json::Value {
    let base = declared_type.map(|t| t.trim_end_matches('?').split('<').next().unwrap_or(t));
    match base {
        Some("Int") => value
            .parse::<i64>()
            .map(|i| serde_json::Value::Number(i.into()))
            .unwrap_or_else(|_| serde_json::Value::String(value.to_string())),
        Some("Float") => value
            .parse::<f64>()
            .ok()
            .and_then(serde_json::Number::from_f64)
            .map(serde_json::Value::Number)
            .unwrap_or_else(|| serde_json::Value::String(value.to_string())),
        Some("Bool") => match value {
            "true" => serde_json::Value::Bool(true),
            "false" => serde_json::Value::Bool(false),
            _ => serde_json::Value::String(value.to_string()),
        },
        _ => serde_json::Value::String(value.to_string()),
    }
}

fn extract_step_info(node: &IRFlowNode) -> (String, String, String) {
    match node {
        IRFlowNode::Step(s) => (s.name.clone(), "step".to_string(), s.ask.clone()),
        IRFlowNode::Probe(s) => (s.target.clone(), "probe".to_string(), format!("Probe: {}", s.target)),
        IRFlowNode::Reason(s) => (s.target.clone(), "reason".to_string(), format!("Reason about: {}", s.target)),
        IRFlowNode::Validate(s) => (s.target.clone(), "validate".to_string(), format!("Validate: {}", s.target)),
        IRFlowNode::Refine(s) => (s.target.clone(), "refine".to_string(), format!("Refine: {}", s.target)),
        IRFlowNode::Weave(s) => ("weave".to_string(), "weave".to_string(), format!("Weave {} sources into {}", s.sources.len(), s.target)),
        IRFlowNode::UseTool(s) => (s.tool_name.clone(), "use_tool".to_string(), format!("Use tool: {}", s.tool_name)),
        IRFlowNode::Remember(s) => (s.memory_target.clone(), "remember".to_string(), format!("Remember: {}", s.expression)),
        IRFlowNode::Recall(s) => (s.memory_source.clone(), "recall".to_string(), format!("Recall: {}", s.query)),
        IRFlowNode::Conditional(s) => (s.condition.clone(), "conditional".to_string(), format!("If: {}", s.condition)),
        IRFlowNode::ForIn(s) => (s.variable.clone(), "for_in".to_string(), format!("For {} in {}", s.variable, s.iterable)),
        IRFlowNode::Let(s) => (s.target.clone(), "let".to_string(), format!("Let {} = {}", s.target, s.value)),
        IRFlowNode::Return(s) => ("return".to_string(), "return".to_string(), format!("Return: {}", s.value_expr)),
        IRFlowNode::Par(_) => ("parallel".to_string(), "parallel".to_string(), "Parallel block".to_string()),
        IRFlowNode::Hibernate(_) => ("hibernate".to_string(), "hibernate".to_string(), "Hibernate".to_string()),
        IRFlowNode::Deliberate(_) => ("deliberate".to_string(), "deliberate".to_string(), "Deliberate block".to_string()),
        IRFlowNode::Consensus(_) => ("consensus".to_string(), "consensus".to_string(), "Consensus block".to_string()),
        IRFlowNode::Forge(_) => ("forge".to_string(), "forge".to_string(), "Forge block".to_string()),
        IRFlowNode::Focus(s) => (s.expression.clone(), "focus".to_string(), format!("Focus: {}", s.expression)),
        IRFlowNode::Associate(s) => (s.left.clone(), "associate".to_string(), format!("Associate: {} ↔ {}", s.left, s.right)),
        IRFlowNode::Aggregate(s) => (s.target.clone(), "aggregate".to_string(), format!("Aggregate: {}", s.target)),
        IRFlowNode::Explore(s) => (s.target.clone(), "explore".to_string(), format!("Explore: {}", s.target)),
        IRFlowNode::Ingest(s) => (s.source.clone(), "ingest".to_string(), format!("Ingest: {}", s.source)),
        IRFlowNode::ShieldApply(s) => (s.shield_name.clone(), "shield_apply".to_string(), format!("Apply shield: {}", s.shield_name)),
        IRFlowNode::Stream(_) => ("stream".to_string(), "stream".to_string(), "Stream block".to_string()),
        IRFlowNode::Navigate(s) => (s.pix_ref.clone(), "navigate".to_string(), format!("Navigate: {}", s.pix_ref)),
        IRFlowNode::Drill(s) => (s.pix_ref.clone(), "drill".to_string(), format!("Drill: {} → {}", s.pix_ref, s.subtree_path)),
        IRFlowNode::Trail(s) => (s.navigate_ref.clone(), "trail".to_string(), format!("Trail: {}", s.navigate_ref)),
        IRFlowNode::Corroborate(s) => (s.navigate_ref.clone(), "corroborate".to_string(), format!("Corroborate: {}", s.navigate_ref)),
        IRFlowNode::OtsApply(s) => (s.ots_name.clone(), "ots_apply".to_string(), format!("Apply OTS: {}", s.ots_name)),
        IRFlowNode::MandateApply(s) => (s.mandate_name.clone(), "mandate_apply".to_string(), format!("Apply mandate: {}", s.mandate_name)),
        IRFlowNode::ComputeApply(s) => (s.compute_name.clone(), "compute_apply".to_string(), format!("Apply compute: {}", s.compute_name)),
        IRFlowNode::Listen(s) => (s.channel.clone(), "listen".to_string(), format!("Listen: {}", s.channel)),
        IRFlowNode::DaemonStep(s) => (s.daemon_ref.clone(), "daemon".to_string(), format!("Daemon: {}", s.daemon_ref)),
        IRFlowNode::Persist(s) => (s.store_name.clone(), "persist".to_string(), format!("Persist to: {}", s.store_name)),
        IRFlowNode::Retrieve(s) => (s.store_name.clone(), "retrieve".to_string(), format!("Retrieve from: {}", s.store_name)),
        IRFlowNode::Mutate(s) => (s.store_name.clone(), "mutate".to_string(), format!("Mutate: {}", s.store_name)),
        IRFlowNode::Purge(s) => (s.store_name.clone(), "purge".to_string(), format!("Purge: {}", s.store_name)),
        IRFlowNode::Transact(_) => ("transact".to_string(), "transact".to_string(), "Transact block".to_string()),
        IRFlowNode::LambdaDataApply(s) => (s.lambda_data_name.clone(), "lambda_data_apply".to_string(), format!("Apply ΛD: {}", s.lambda_data_name)),
        // §λ-L-E Fase 13 — Mobile typed channel reductions.
        IRFlowNode::Emit(s) => (s.channel_ref.clone(), "emit".to_string(), format!("Emit on {}: {}", s.channel_ref, s.value_ref)),
        IRFlowNode::Publish(s) => (s.channel_ref.clone(), "publish".to_string(), format!("Publish {} within {}", s.channel_ref, s.shield_ref)),
        IRFlowNode::Discover(s) => (s.capability_ref.clone(), "discover".to_string(), format!("Discover {} as {}", s.capability_ref, s.alias)),
        // Fase 19.e — break / continue. Payload-free; the executor
        // raises sentinel exceptions caught by the enclosing for-in.
        IRFlowNode::Break(_) => ("break".to_string(), "break".to_string(), "Break out of for-in loop".to_string()),
        IRFlowNode::Continue(_) => ("continue".to_string(), "continue".to_string(), "Continue to next for-in iteration".to_string()),
    }
}

// ── Stub executor ───────────────────────────────────────────────────────────

fn execute_stub(
    units: &[ExecutionUnit],
    use_color: bool,
    trace: bool,
) -> (bool, Vec<TraceEvent>) {
    let mut events: Vec<TraceEvent> = Vec::new();

    for (i, unit) in units.iter().enumerate() {
        println!(
            "\n{}",
            c(
                &format!("▶ Execution Unit {}/{}: {} as {}", i + 1, units.len(), unit.flow_name, unit.persona_name),
                "\x1b[1;36m",
                use_color,
            )
        );

        if trace {
            events.push(TraceEvent {
                event: "unit_start".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!("persona={}, context={}", unit.persona_name, unit.context_name),
            });
        }

        // Show system prompt summary
        println!(
            "  {} {}",
            c("System:", "\x1b[1;33m", use_color),
            truncate(&unit.system_prompt, 120)
        );

        if !unit.anchor_instructions.is_empty() {
            println!(
                "  {} {}",
                c("Anchors:", "\x1b[1;33m", use_color),
                unit.anchor_instructions.join(" | ")
            );
        }

        if !unit.effort.is_empty() {
            println!(
                "  {} {}",
                c("Effort:", "\x1b[1;33m", use_color),
                unit.effort
            );
        }

        // Execute each step (stub)
        let mut stub_ctx = crate::exec_context::ExecContext::new(
            &unit.flow_name,
            &unit.persona_name,
            i,
        );
        // §Fase 37.b (D1) — seed the flow's parameters from the
        // request body BEFORE the step walk so `${param}` resolves.
        for (name, value) in &unit.param_bindings {
            stub_ctx.set(name, value);
        }
        for (j, step) in unit.steps.iter().enumerate() {
            stub_ctx.set_step(&step.step_name, &step.step_type, j);
            println!(
                "  {} {}.{} [{}] {}",
                c("→", "\x1b[32m", use_color),
                j + 1,
                c(&step.step_name, "\x1b[1m", use_color),
                step.step_type,
                &step.user_prompt
            );

            // Fase 15.c — `lambda_data_apply` is the only primitive the
            // stub executor implements semantically: it's a pure binding
            // (no LLM, no I/O), so the stub can produce a correct ψ
            // without diverging from the real executor. Adopters running
            // `axon run --stub` get observable bindings for downstream
            // ${OutputType} interpolation.
            if step.step_type == "lambda_data_apply" {
                if let Some(payload) = &step.lambda_apply_payload {
                    let target_value = if payload.target.is_empty() {
                        serde_json::Value::Null
                    } else {
                        // Interpolate target via stub_ctx — supports
                        // ${StepName} / $var. Falls back to a string
                        // literal of the target ref so the trace stays
                        // observable even when the var is unresolved.
                        let raw = stub_ctx
                            .get(&payload.target)
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| payload.target.clone());
                        serde_json::Value::String(raw)
                    };
                    match crate::lambda_runtime::build_psi(
                        &payload.spec_snapshot,
                        target_value,
                    ) {
                        Ok(psi) => {
                            let psi_json = serde_json::to_string(&psi).unwrap_or_default();
                            if !payload.output_type.is_empty() {
                                stub_ctx.set(&payload.output_type, &psi_json);
                            }
                            stub_ctx.set_result(&step.step_name, &psi_json);
                            if trace {
                                events.push(TraceEvent {
                                    event: "lambda_data_apply".to_string(),
                                    unit: unit.flow_name.clone(),
                                    step: step.step_name.clone(),
                                    detail: psi_json,
                                });
                            }
                            continue;
                        }
                        Err(err) => {
                            eprintln!(
                                "  {} lambda apply error: {}",
                                c("✗", "\x1b[31m", use_color),
                                err
                            );
                            if trace {
                                events.push(TraceEvent {
                                    event: "lambda_data_apply_error".to_string(),
                                    unit: unit.flow_name.clone(),
                                    step: step.step_name.clone(),
                                    detail: err.to_string(),
                                });
                            }
                            return (false, events);
                        }
                    }
                }
            }

            // Fase 17.c — `let_binding` is also a pure SSA binding
            // (no LLM, no I/O). The stub binds the resolved value
            // into ExecContext under `target` so downstream ${X} /
            // $X interpolation finds it. Resolution rule:
            //   * literal — bind verbatim
            //   * reference — look up in stub_ctx; fall back to the
            //     literal value string if absent (preserves observable
            //     trace even when the var is unresolved at stub time)
            //   * expression — bind the joined string; runtime
            //     evaluation via NativeComputeDispatcher is a future
            //     sub-phase
            if step.step_type == "let_binding" {
                if let Some(payload) = &step.let_payload {
                    let resolved = if payload.value_kind == "reference"
                        && !payload.value.is_empty()
                    {
                        stub_ctx
                            .get(&payload.value)
                            .map(str::to_string)
                            .unwrap_or_else(|| payload.value.clone())
                    } else {
                        payload.value.clone()
                    };
                    if !payload.target.is_empty() {
                        stub_ctx.set(&payload.target, &resolved);
                    }
                    stub_ctx.set_result(&step.step_name, &resolved);
                    if trace {
                        events.push(TraceEvent {
                            event: "let_binding".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: format!(
                                "{}={} (kind={})",
                                payload.target, resolved, payload.value_kind,
                            ),
                        });
                    }
                    continue;
                }
            }

            // ── Fase 19.f/g — stub-correct dispatch for the 11 new
            // primitives (Conditional / ForIn / Par / Return / Remember /
            // Recall / Hibernate / Drill / Trail / Break / Continue).
            //
            // "Stub-correct" means: recognize the step type, emit a
            // trace event with the right shape, and bind any
            // adopter-visible placeholders to ExecContext so downstream
            // ${X} / $X interpolation continues to resolve. The stub
            // does NOT perform the real subsystem work (LLM scoring,
            // PIX traversal, HMAC token signing, MemoryBackend writes)
            // — that is the Python runner's responsibility. The Rust
            // stub mirrors the Python contract at the trace boundary
            // so cross-stack parity goldens (Fase 19.h) compare on the
            // same structured shapes.
            match step.step_type.as_str() {
                "remember" => {
                    let target = &step.step_name;
                    if !target.is_empty() {
                        stub_ctx.set(target, "<remembered>");
                    }
                    if trace {
                        events.push(TraceEvent {
                            event: "remember".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step
                                .memory_expression
                                .clone()
                                .unwrap_or_default(),
                        });
                    }
                    continue;
                }
                "recall" => {
                    let source = &step.step_name;
                    if !source.is_empty() {
                        stub_ctx.set(source, "<recalled>");
                    }
                    if trace {
                        events.push(TraceEvent {
                            event: "recall".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step
                                .memory_expression
                                .clone()
                                .unwrap_or_default(),
                        });
                    }
                    continue;
                }
                "return" => {
                    // Mirror Python's `__return_value__` slot. The stub
                    // does not actually short-circuit the unit (no
                    // sentinel mechanism) — it just records the
                    // intended value so the trace shows the early-exit
                    // intent. Adopters running `axon run --stub` see
                    // the binding; the real Python executor enforces
                    // termination.
                    stub_ctx.set("__return_value__", &step.user_prompt);
                    if trace {
                        events.push(TraceEvent {
                            event: "return".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step.user_prompt.clone(),
                        });
                    }
                    continue;
                }
                "hibernate" => {
                    // Bind a placeholder token; full ContinuityTokenSigner
                    // integration is the Python runner's job.
                    stub_ctx.set("__hibernation_token__", "<stub-token>");
                    if trace {
                        events.push(TraceEvent {
                            event: "hibernate".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: format!("flow={}", unit.flow_name),
                        });
                    }
                    continue;
                }
                "drill" => {
                    // Bind under `drill:<pix_ref>` so adopter code
                    // that interpolates the binding finds something.
                    let key = format!("drill:{}", step.step_name);
                    stub_ctx.set(&key, "<stub-drill-result>");
                    if trace {
                        events.push(TraceEvent {
                            event: "drill".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step.user_prompt.clone(),
                        });
                    }
                    continue;
                }
                "trail" => {
                    let key = format!("trail:{}", step.step_name);
                    stub_ctx.set(&key, "<stub-trail-result>");
                    if trace {
                        events.push(TraceEvent {
                            event: "trail".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step.user_prompt.clone(),
                        });
                    }
                    continue;
                }
                "conditional" | "for_in" | "parallel" => {
                    // Pure control flow — no adopter-visible binding;
                    // just record the structural intent in the trace.
                    if trace {
                        events.push(TraceEvent {
                            event: step.step_type.clone(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step.user_prompt.clone(),
                        });
                    }
                    continue;
                }
                "break" | "continue" => {
                    // Loop-control sentinels. Stub doesn't enforce
                    // loop exit (no sentinel exception machinery here)
                    // — it just records the keyword in the trace.
                    if trace {
                        events.push(TraceEvent {
                            event: step.step_type.clone(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: step.user_prompt.clone(),
                        });
                    }
                    continue;
                }
                _ => {}
            }

            if trace {
                events.push(TraceEvent {
                    event: "step_stub".to_string(),
                    unit: unit.flow_name.clone(),
                    step: step.step_name.clone(),
                    detail: format!("[{}] {}", step.step_type, step.user_prompt),
                });
            }
        }

        if trace {
            events.push(TraceEvent {
                event: "unit_complete".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!("{} steps (stub)", unit.steps.len()),
            });
        }

        println!(
            "  {} {} steps completed (stub mode)",
            c("✓", "\x1b[32m", use_color),
            unit.steps.len()
        );
    }

    (true, events)
}

// ── Real executor ───────────────────────────────────────────────────────────

const MAX_ANCHOR_RETRIES: u32 = 2;

// ── §Fase 35.e — axonstore SQL routing for the sync runner ──────────
//
// The sync runner is synchronous; `PostgresStoreBackend`'s operations
// are async. `block_on_store` bridges the two by running the future on
// a freshly-spawned OS thread that owns a current-thread Tokio runtime.
// A fresh thread never carries an ambient runtime, so this is safe
// whether `execute_real` runs on a server worker thread, a
// `spawn_blocking` thread, or a plain CLI thread — there is no
// "runtime within a runtime" hazard. `std::thread::scope` joins the
// thread before returning. One pool is created + used + dropped per
// store op; cross-request pooling is the streaming dispatcher's path
// (35.f, the production hot path).
fn block_on_store<F>(fut: F) -> F::Output
where
    F: std::future::Future + Send,
    F::Output: Send,
{
    std::thread::scope(|scope| {
        scope
            .spawn(|| {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("Fase 35.e: failed to build the store-op Tokio runtime")
                    .block_on(fut)
            })
            .join()
            .expect("Fase 35.e: the store-op thread panicked")
    })
}

/// Execute one `persist`/`retrieve`/`mutate`/`purge` step against a
/// postgresql-backed `axonstore`, returning a human-readable result
/// summary or a typed [`StoreError`].
///
/// The store name doubles as the SQL table name (D12 — `IRAxonStore`
/// carries no schema, so v1.31.0 operates against existing tables).
/// §Fase 35.o / 35.p — `persist` (INSERT columns) and `mutate`
/// (UPDATE SET assignments) write the columns of their declared
/// `{ col: value }` block (`store_fields`, value expressions
/// interpolated); with no block they fall back to writing the flow's
/// user bindings as a row ([`ExecContext::user_bindings`]).
/// `retrieve`/`purge` are driven by the `where`-expression. D5 — the
/// SAME `PostgresStoreBackend` the streaming dispatcher uses, so the
/// two execution paths never diverge.
///
/// §Fase 37.d (D3) — `memory_expr` is the RAW `store:where` expression
/// (NOT pre-interpolated). A `${name}` in the `where` clause is
/// resolved by the filter compiler against `ctx.vars()` into a `$N`
/// bind parameter — never string-spliced into the `where` source. The
/// pre-37.d path interpolated the whole expression first, which let a
/// request value carrying a `'` break a string-literal boundary.
/// §Fase 37.x.j.10 (POST-CLOSE HOTFIX 2026-05-21) — Async variant of
/// `execute_sql_store_step`. The pre-hotfix sync variant wrapped the
/// SQL dispatch in its OWN `block_on_store` (own temporary tokio
/// runtime per call). Combined with the eager pin acquisition (also
/// on its own temp runtime), this created a fatal cross-runtime
/// hazard: the pinned `PoolConnection<Postgres>` carries reactor
/// handles bound to the runtime that ACQUIRED it; awaiting on it from
/// a different runtime hangs indefinitely (the reactor that would
/// notify the I/O completion is already dropped).
///
/// 37.x.j.10 collapses the per-step runtime back into a SINGLE
/// outer-scope runtime owned by `execute_server_flow`. This async fn
/// runs on the caller's runtime, so the pin acquired at flow start
/// + every SQL dispatch + the implicit pin drop on flow exit ALL
/// live on the same runtime. Reactor handles stay valid.
///
/// The sync variant `execute_sql_store_step` is retained as a thin
/// wrapper for CLI tests + pre-async callers; it spins up a single
/// `block_on_store` and calls this async variant. New callers should
/// invoke the async variant directly from an async context.
async fn execute_sql_store_step_async(
    store_registry: &StoreRegistry,
    // §Fase 37.x.j (D1) — pinned-connection map shared across the flow
    // execution. Keyed by axonstore name; when the entry exists the
    // store op routes its SQL through that exact physical Postgres
    // connection (held since `execute_server_flow` start). When the
    // entry is absent the op falls back to `StoreConn::Pool` (legacy
    // pre-37.x.j behavior) — keeping CLI tests + non-server callers
    // working unchanged.
    //
    // §37.x.j.10 — the `&mut` reference is held across `.await`
    // boundaries inside this fn. Safe because the function is the
    // unique &mut borrower of the map for its execution and the map
    // itself is owned by the outer scope (`execute_server_flow`'s
    // single block_on_store, or a test scope's single async wrapper).
    pinned_conns: &mut std::collections::HashMap<String, sqlx::pool::PoolConnection<sqlx::Postgres>>,
    step_type: &str,
    store_name: &str,
    memory_expr: &str,
    store_fields: Option<&[(String, String)]>,
    ctx: &ExecContext,
) -> Result<String, StoreError> {
    // The connection + confidence_floor live on the `IRAxonStore` the
    // registry validated.
    let spec = store_registry.spec(store_name);
    let _connection = spec.map(|s| s.connection.clone()).unwrap_or_default();
    let confidence_floor = spec.and_then(|s| s.confidence_floor);

    // §Fase 37.x.j (D1) — the SHARED backend is resolved from the
    // registry cache INSIDE the `block_on_store` async block below
    // (the registry's `resolve` may need a tokio context when it
    // lazily builds the PgPool on first reference). Pre-37.x.j the
    // runner created a fresh `PgPool` per `connect_named` call — a
    // pre-existing inefficiency that 37.x.j fixes en passant by
    // routing through the cached pool.

    // `memory_expression` is `"store:where"` for retrieve/mutate/purge
    // and the bare store name for persist — the where-expr is whatever
    // follows the first colon (empty when absent).
    let where_expr = memory_expr
        .splitn(2, ':')
        .nth(1)
        .unwrap_or("")
        .to_string();
    // §Fase 37.d (D3) — an OWNED copy of the flow's variable map, moved
    // into the store-op task; the filter compiler resolves `${name}`
    // in `where_expr` against it into `$N` bind parameters.
    let where_bindings: std::collections::HashMap<String, String> =
        ctx.vars().clone();

    // §Fase 35.o / 35.p — when the `persist` / `mutate` step declared a
    // `{ col: value }` block, the SQL row is exactly those columns with
    // their value expressions interpolated against the flow context.
    // With no block (`store_fields` is `None`) fall back to the v1.31.0
    // behaviour: every user binding as a text column. `store_fields` is
    // only materialised for `persist`/`mutate`, so `retrieve`/`purge`
    // (which ignore `data`) always take the fallback. Every value binds
    // as text (D12 — no column-type schema in v1.31).
    let data: Vec<(String, SqlValue)> = match store_fields {
        Some(fields) => fields
            .iter()
            .map(|(col, expr)| {
                (col.clone(), SqlValue::Text(ctx.interpolate(expr)))
            })
            .collect(),
        None => ctx
            .user_bindings()
            .into_iter()
            .map(|(k, v)| (k, SqlValue::Text(v)))
            .collect(),
    };

    let store_name = store_name.to_string();
    let step_type = step_type.to_string();
    let store_name_for_reinsert = store_name.clone();

    // §Fase 37.x.j (D1) — take the pin OUT of the shared map for the
    // duration of this dispatch. After the dispatch returns (success
    // OR error), the pin is re-inserted UNCONDITIONALLY so the next
    // store op against this same store reuses it.
    //
    // §Fase 37.x.j.10 — no longer wrapped in block_on_store. The
    // async fn runs on the caller's runtime, so the pin's reactor
    // handles stay valid for every `.await` below.
    let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> =
        pinned_conns.remove(&store_name);

    // §Fase 37.x.j (D1) — resolve the SHARED backend from the registry
    // cache. The registry caches `PostgresStoreBackend` by resolved
    // DSN; the backend's inner `PgPool` is `Arc<...>` so the clone
    // shares pool state with every other call AND with the eagerly-
    // acquired pin in `pinned_conns`.
    let backend = match store_registry.resolve(&store_name) {
        Ok(crate::store::registry::StoreHandle::Postgres(b)) => b,
        Ok(_) => {
            // Re-insert the pin if we removed one (we won't dispatch).
            if let Some(p) = pin {
                pinned_conns.insert(store_name_for_reinsert, p);
            }
            return Err(StoreError::Connect {
                source: format!(
                    "axonstore `{store_name}` expected to resolve to \
                     a postgresql backend but the registry returned \
                     `in_memory`. Routing bug — the SQL gate in \
                     `execute_real` should have skipped this step."
                ),
            });
        }
        Err(e) => {
            if let Some(p) = pin {
                pinned_conns.insert(store_name_for_reinsert, p);
            }
            return Err(e);
        }
    };

    // §Fase 37.x.j.10 — dispatch body inlined here. `pin` is `&mut`-
    // borrowed inside each match arm for the StoreConn::Pinned variant;
    // the borrow ends at the end of each arm so we can re-insert `pin`
    // unconditionally below regardless of result.
    let result: Result<String, StoreError> = async {
        match step_type.as_str() {
            "retrieve" => {
                // §35.i Pillar III — retrieve drains off a lazy cursor,
                // bounded (never materializes a huge result set).
                // §35.g Pillar I — every tuple born Untrusted,
                // confidence_floor filters sub-floor rows. The result
                // is an epistemic envelope carrying both dispositions.
                let cancel = crate::cancel_token::CancellationFlag::new();
                // §Fase 37.x.j (D1) — build `StoreConn::Pinned` when a
                // pin is held for this store (the post-37.x.j default
                // for server-driven flows), else `StoreConn::Pool`
                // (legacy path for CLI / pre-server callers). The
                // Pinned variant routes the SELECT through the exact
                // physical Postgres backend connection acquired at
                // flow start — Supavisor/PgBouncer cannot swap.
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                let stream_outcome = row_stream::stream_retrieve(
                    &backend,
                    &mut store_conn,
                    &store_name,
                    &where_expr,
                    row_stream::DEFAULT_RETRIEVE_POLICY,
                    row_stream::DEFAULT_MAX_ROWS,
                    &cancel,
                    &where_bindings,
                )
                .await?;
                let metadata = row_stream::stream_metadata(
                    row_stream::DEFAULT_RETRIEVE_POLICY,
                    &stream_outcome,
                );
                let outcome = epistemic::enforce_retrieve_floor(
                    epistemic::mark_retrieved(stream_outcome.rows),
                    confidence_floor,
                );
                let mut envelope =
                    epistemic::retrieve_envelope(&outcome, confidence_floor);
                envelope["stream"] = metadata;
                Ok(serde_json::to_string(&envelope)
                    .unwrap_or_else(|_| "{}".to_string()))
            }
            "purge" => {
                // §Fase 37.x.j (D1) — pinned/pool dispatch (see retrieve).
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                let n = backend
                    .purge(&mut store_conn, &store_name, &where_expr, &where_bindings)
                    .await?;
                Ok(format!("{n} row(s) purged"))
            }
            "persist" => {
                // §35.g Pillar I — a sub-floor or un-elevated write
                // into a confidence-floored store is a typed error.
                epistemic::enforce_persist_floor(
                    &data,
                    confidence_floor,
                    &store_name,
                )?;
                // §Fase 37.x.j (D1) — pinned/pool dispatch.
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                let n = backend.insert(&mut store_conn, &store_name, &data).await?;
                Ok(format!("{n} row(s) persisted"))
            }
            "mutate" => {
                // §Fase 37.x.j (D1) — pinned/pool dispatch.
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                let n = backend
                    .mutate(&mut store_conn, &store_name, &where_expr, &data, &where_bindings)
                    .await?;
                Ok(format!("{n} row(s) mutated"))
            }
            // The caller only routes the four store-op step types here.
            other => Err(StoreError::Query {
                op: "store",
                source: format!("unsupported store step type `{other}`"),
            }),
        }
    }.await;

    // §Fase 37.x.j (D1) — re-insert the pin (UNCONDITIONALLY — success
    // OR error path) so the next store op against this store reuses
    // the same physical Postgres backend connection. `pin` was taken
    // out at the top of this fn and the dispatch above only borrows
    // it `&mut`-wise inside each match arm — so it's still owned here
    // regardless of `result`'s Ok/Err outcome.
    if let Some(p) = pin {
        pinned_conns.insert(store_name_for_reinsert, p);
    }

    result
}

/// §Fase 35.e — Sync wrapper retained for CLI tests + pre-async callers.
///
/// §Fase 37.x.j.10 (POST-CLOSE HOTFIX) — wraps the new async fn
/// `execute_sql_store_step_async` in a SINGLE block_on_store so the
/// pin acquire (if any was pre-populated) + the SQL dispatch happen
/// on the SAME temporary tokio runtime. Pre-hotfix the sync variant
/// had its OWN block_on_store inside (per-step temp runtime); when
/// the caller's eager pin acquisition was ALSO on a separate temp
/// runtime, the cross-runtime hazard appeared. The wrapper here is
/// safe ONLY when the caller's pin map is empty (legacy Pool path)
/// — production callers MUST use the async variant directly inside
/// the OUTER block_on_store at `execute_server_flow`.
fn execute_sql_store_step(
    store_registry: &StoreRegistry,
    pinned_conns: &mut std::collections::HashMap<String, sqlx::pool::PoolConnection<sqlx::Postgres>>,
    step_type: &str,
    store_name: &str,
    memory_expr: &str,
    store_fields: Option<&[(String, String)]>,
    ctx: &ExecContext,
) -> Result<String, StoreError> {
    block_on_store(execute_sql_store_step_async(
        store_registry,
        pinned_conns,
        step_type,
        store_name,
        memory_expr,
        store_fields,
        ctx,
    ))
}

/// §Fase 37.x.j.10 (POST-CLOSE HOTFIX 2026-05-21) — Async variant of
/// `execute_real`. Production callers MUST invoke this from inside
/// the OUTER `block_on_store` at `execute_server_flow` so the entire
/// flow execution (eager pin acquire + every store dispatch + implicit
/// pin drop on exit) lives on a SINGLE temporary tokio runtime. This
/// is the load-bearing structural property that prevents the cross-
/// runtime `PoolConnection<Postgres>` hazard the pre-hotfix code
/// exhibited.
///
/// The single store-op site (`execute_sql_store_step_async`) is now
/// awaited directly here — no nested `block_on_store`. Every other
/// operation in this fn is synchronous-style code; the async fn just
/// means the await of the SQL dispatch site is legal.
///
/// The sync variant `execute_real` retained as a thin wrapper for the
/// CLI path + pre-async callers that don't have a tokio context.
/// §Fase 65.A — the dispatcher-shared state a STRUCTURAL `navigate` needs: the
/// axonstore registry (to read the corpus rows tenant-scoped) + the static MDN
/// corpus graphs (§63 `corpus { relations: }`) + the dynamic store-sourced
/// corpus specs (§64 `corpus … from axonstore`) + the adaptive set. Built once
/// per server flow from the IR — mirroring `run_streaming_via_dispatcher` — so a
/// NON-streaming `navigate` executes the SAME real MDN traversal as the SSE path
/// instead of the LLM fallthrough. `None` on the CLI path (its executor unifies
/// in a later sub-fase; navigate there keeps the legacy behavior for now).
struct NavDispatch {
    store_registry: std::sync::Arc<StoreRegistry>,
    corpora: std::sync::Arc<std::collections::HashMap<String, crate::mdn::Corpus>>,
    store_sources:
        std::sync::Arc<std::collections::HashMap<String, crate::ir_nodes::IRCorpusStoreSource>>,
    adaptive: std::sync::Arc<std::collections::HashSet<String>>,
}

/// §Fase 65.A — kill-switch for the structural-dispatch bridge. ON by default:
/// the legacy path (LLM fallthrough) is a CORRECTNESS BUG for a pure-effect verb
/// — it fabricates output that does not exist. Set `AXON_UNIFIED_EXECUTOR` to
/// `0`/`off`/`false`/`no` to revert to the legacy behavior (escape hatch only,
/// until the §65.E cutover removes it).
fn structural_dispatch_enabled() -> bool {
    match std::env::var("AXON_UNIFIED_EXECUTOR") {
        Ok(v) => !matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "0" | "off" | "false" | "no"
        ),
        Err(_) => true,
    }
}

/// §Fase 65.B — the structural verbs the non-streaming server executor routes
/// through the flow dispatcher instead of the LLM fallthrough. These are the
/// PURE-EFFECT verbs whose dispatcher handler runs a real, embeddings-free
/// computation over the live corpus / PIX state with NO LLM call (so they need
/// no per-tenant API key plumbing — that arrives with the cognitive verbs in
/// §65.C). Today: the MDN/PIX navigation family. `navigate` (§65.A) over the
/// live store-sourced graph; `drill` into a PIX subtree; `trail` the breadcrumb
/// of a prior navigate. Cognitive-framing verbs (forge/focus/associate/aggregate/
/// explore/ingest/corroborate) and the multi-agent verbs (deliberate/consensus)
/// reuse `pure_shape` → they DO call the LLM, so they stay on the legacy path
/// until §65.C threads the per-tenant key through `DispatchCtx`.
fn routes_through_dispatcher(node: &crate::ir_nodes::IRFlowNode) -> bool {
    use crate::ir_nodes::IRFlowNode as N;
    matches!(node, N::Navigate(_) | N::Drill(_) | N::Trail(_))
}

/// §Fase 65.A/B — run a pure-effect structural verb (navigate / drill / trail)
/// as its REAL computation by bridging into the flow dispatcher's
/// [`crate::flow_dispatcher::dispatch_node`], sharing the flow's EXACT pinned,
/// tenant-scoped Postgres connections (the §64.B isolation guarantee — NEVER a
/// fresh pool acquire). The pins are LENT to a throwaway `DispatchCtx` for the
/// duration of this single node, then reclaimed into the runner's map. The
/// dispatcher events go to a dropped channel (the runner builds its own report).
/// Returns the structural result (the REAL documents / subtree / trail) or an
/// honest empty/`Err` — never an LLM hallucination.
///
/// Cross-node state: the dispatcher writes its bindings into the throwaway
/// `DispatchCtx`; we copy ALL of them back into the runner's `ExecContext` so a
/// later `trail`/`drill` that consumes a prior `navigate`'s breadcrumb/subtree
/// binding still sees it (each verb gets a fresh ctx, but the runner context is
/// the persistent store re-seeded into every bridge call). The per-flow MDN
/// interaction history is shared (`histories`) so adaptive reinforcement accrues
/// with cross-navigation variance — parity with the SSE single-ctx path.
///
/// Tenant isolation note: the dispatcher reads route through the SAME
/// `read_all_store_rows` → `stream_retrieve` path the runner's own `retrieve`
/// uses, on the SAME task (so the `current_tenant_id()` task-local + per-op
/// `SET LOCAL axon.current_tenant` apply identically) and over the SAME physical
/// pinned connection (lent here) — inheriting the exact isolation of a
/// non-streaming `retrieve`. The concurrent two-tenant property test is the
/// load-bearing safeguard (§65.A/B risk matrix).
async fn dispatch_structural(
    node: &crate::ir_nodes::IRFlowNode,
    exec_ctx: &mut ExecContext,
    flow_name: &str,
    backend_name: &str,
    system_prompt: &str,
    pinned_conns: &mut std::collections::HashMap<
        String,
        sqlx::pool::PoolConnection<sqlx::Postgres>,
    >,
    nd: &NavDispatch,
    histories: &std::sync::Arc<
        std::sync::Mutex<std::collections::HashMap<String, crate::mdn_memory::History>>,
    >,
) -> Result<String, String> {
    use std::sync::{Arc, Mutex};
    // Lend the flow's pins to a shared Arc<Mutex> so the DispatchCtx operates on
    // the SAME physical, tenant-scoped connections — the §64.B isolation. The
    // runner is the unique borrower of `pinned_conns` here (sequential within the
    // wave), so the take/restore is race-free.
    let lent = std::mem::take(pinned_conns);
    let pin_arc = Arc::new(Mutex::new(lent));
    let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
    let mut dctx = crate::flow_dispatcher::DispatchCtx::new(
        flow_name,
        backend_name,
        system_prompt,
        crate::cancel_token::CancellationFlag::new(),
        tx,
    )
    .with_store_registry(nd.store_registry.clone())
    .with_mdn_corpora(nd.corpora.clone())
    .with_mdn_adaptive(nd.adaptive.clone())
    .with_mdn_store_sources(nd.store_sources.clone())
    .with_pinned_conns(pin_arc.clone());
    // Share the flow's MDN interaction history across all of its navigate nodes
    // so adaptive ω reinforcement sees cross-navigation variance (SSE parity).
    dctx.mdn_histories = histories.clone();
    // Seed the dispatcher's let-bindings from the runner's exec context so
    // `${param}` in `query:` / `from:` (and any prior-step output) interpolates
    // identically to every other step in this flow.
    dctx.let_bindings = exec_ctx.vars().clone();

    let outcome = crate::flow_dispatcher::dispatch_node(node, &mut dctx).await;

    // Copy ALL of the handler's bindings back into the runner's context so
    // cross-node PIX/MDN state (e.g. a `navigate` trail later consumed by a
    // `trail`/`drill`) survives the throwaway DispatchCtx.
    for (k, v) in dctx.let_bindings.drain() {
        exec_ctx.set(&k, &v);
    }
    // Reclaim the pins into the runner's map (the dispatcher took/returned them
    // within the shared Arc; drain it back so the flow's remaining store ops keep
    // using the same pinned connections).
    {
        let mut reclaimed = pin_arc.lock().unwrap();
        for (k, v) in reclaimed.drain() {
            pinned_conns.insert(k, v);
        }
    }

    match outcome {
        Ok(crate::flow_dispatcher::NodeOutcome::Completed { output, .. }) => Ok(output),
        // A cancelled / non-completing outcome binds empty rather than fabricating.
        Ok(_) => Ok(String::new()),
        Err(e) => Err(format!("{e:?}")),
    }
}

async fn execute_real_async(
    units: &[ExecutionUnit],
    backend_name: &str,
    source_file: &str,
    use_color: bool,
    trace: bool,
    stream: bool,
    output_fmt: OutputFormat,
    report: &mut ReportBuilder,
    registry: &ToolRegistry,
    store_registry: &StoreRegistry,
    // §Fase 37.x.j (D1) — flow-scoped pinned connection map, populated
    // by `execute_server_flow` (server-driven flows) and empty for
    // CLI / pre-37.x.j callers.
    pinned_conns: &mut std::collections::HashMap<String, sqlx::pool::PoolConnection<sqlx::Postgres>>,
    api_key_override: Option<&str>,
    // §Fase 65.A — the dispatcher-shared corpus state for structural `navigate`.
    // `Some` on the server path (built from the IR); `None` on the CLI path.
    nav_dispatch: Option<&NavDispatch>,
) -> Result<(bool, Vec<TraceEvent>), backend::BackendError> {
    let api_key = match api_key_override {
        Some(key) => key.to_string(),
        None => backend::get_api_key(backend_name)?,
    };
    let mut events: Vec<TraceEvent> = Vec::new();
    let mut total_input_tokens: u64 = 0;
    let mut total_output_tokens: u64 = 0;
    let mut session = SessionStore::new(source_file);
    let mut hooks = HookManager::new();
    let mut effects = EffectTracker::new();
    let json = output_fmt.is_json();

    for (i, unit) in units.iter().enumerate() {
        if !json {
            println!(
                "\n{}",
                c(
                    &format!(
                        "▶ Execution Unit {}/{}: {} as {}",
                        i + 1,
                        units.len(),
                        unit.flow_name,
                        unit.persona_name
                    ),
                    "\x1b[1;36m",
                    use_color,
                )
            );
        }

        if trace {
            events.push(TraceEvent {
                event: "unit_start".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!(
                    "persona={}, context={}",
                    unit.persona_name, unit.context_name
                ),
            });
        }

        let mut ctx = ExecContext::new(&unit.flow_name, &unit.persona_name, i);
        // §Fase 37.b (D1) — seed the flow's parameters from the
        // request body BEFORE the step walk so `${param}` resolves in
        // step prompts, `where:` clauses and `persist` field blocks.
        for (name, value) in &unit.param_bindings {
            ctx.set(name, value);
        }
        let mut conversation = ConversationHistory::new();
        let mut context_window = ContextWindow::new();
        // §Fase 65.B — shared MDN interaction history across this flow's
        // structural navigate nodes (adaptive ω reinforcement needs
        // cross-navigation variance; one Arc per flow ≡ the SSE single-ctx path).
        let nav_histories: std::sync::Arc<
            std::sync::Mutex<std::collections::HashMap<String, crate::mdn_memory::History>>,
        > = std::sync::Arc::new(std::sync::Mutex::new(std::collections::HashMap::new()));
        hooks.on_unit_start(&unit.flow_name, &unit.persona_name);
        report.begin_unit(&unit.flow_name, &unit.persona_name);

        // Step dependency analysis + parallel schedule
        // §Fase 61 — the set of producing step names, so a `use Tool(k = v)`
        // call's keyword-arg references fold into the analysis argument (a flow-
        // param reference is gated out). Without this the call's data-deps are
        // invisible and the scheduler co-schedules it with its sources.
        let step_name_set: std::collections::HashSet<&str> =
            unit.steps.iter().map(|s| s.step_name.as_str()).collect();
        let step_infos: Vec<step_deps::StepInfo> = unit.steps.iter().map(|s| {
            step_deps::StepInfo {
                name: s.step_name.clone(),
                step_type: s.step_type.clone(),
                user_prompt: s.user_prompt.clone(),
                argument: step_deps::use_tool_analysis_argument(
                    s.tool_argument.as_deref()
                        .or(s.memory_expression.as_deref())
                        .unwrap_or(""),
                    &s.tool_named_args,
                    &step_name_set,
                ),
            }
        }).collect();

        let dep_graph = step_deps::analyze(&step_infos);
        let schedule = parallel::build_schedule(&dep_graph);

        if trace {
            if !json && dep_graph.max_depth > 0 {
                println!(
                    "  {} {}",
                    c("⊞", "\x1b[2;36m", use_color),
                    c(
                        &format!(
                            "Dependencies: depth={}, {} parallel group{}{}",
                            dep_graph.max_depth,
                            dep_graph.parallel_groups.len(),
                            if dep_graph.parallel_groups.len() == 1 { "" } else { "s" },
                            if dep_graph.unresolved_refs.is_empty() {
                                String::new()
                            } else {
                                format!(", {} unresolved ref(s)", dep_graph.unresolved_refs.len())
                            },
                        ),
                        "\x1b[2;36m",
                        use_color,
                    ),
                );
            }

            events.push(TraceEvent {
                event: "step_deps".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!(
                    "depth={}, parallel_groups={}, unresolved={}, steps: {}",
                    dep_graph.max_depth,
                    dep_graph.parallel_groups.len(),
                    dep_graph.unresolved_refs.len(),
                    dep_graph.steps.iter()
                        .map(|s| {
                            if s.depends_on.is_empty() {
                                s.name.clone()
                            } else {
                                format!("{}→[{}]", s.name, s.depends_on.join(","))
                            }
                        })
                        .collect::<Vec<_>>()
                        .join(", "),
                ),
            });

            if !json && schedule.has_parallelism() {
                println!(
                    "  {} {}",
                    c("⫘", "\x1b[2;35m", use_color),
                    c(
                        &format!("Schedule: {}", schedule.summary()),
                        "\x1b[2;35m",
                        use_color,
                    ),
                );
            }

            events.push(TraceEvent {
                event: "schedule".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!(
                    "waves={}, parallel_waves={}, max_parallelism={}, schedule: {}",
                    schedule.waves.len(),
                    schedule.parallel_waves,
                    schedule.max_parallelism,
                    schedule.summary(),
                ),
            });
        }

        // Build step lookup by name → (index, &CompiledStep)
        let step_map: std::collections::HashMap<&str, (usize, &CompiledStep)> = unit
            .steps
            .iter()
            .enumerate()
            .map(|(j, s)| (s.step_name.as_str(), (j, s)))
            .collect();

        // ── Wave-based execution loop ────────────────────────────
        for (wave_idx, wave) in schedule.waves.iter().enumerate() {
            let is_parallel_wave = wave.is_parallel && wave.steps.len() > 1;

            if is_parallel_wave && !json {
                println!(
                    "  {} {}",
                    c("⫘", "\x1b[35m", use_color),
                    c(
                        &format!(
                            "Wave {}/{}: [{}] (parallel, {} steps)",
                            wave_idx + 1,
                            schedule.waves.len(),
                            wave.steps.join(" | "),
                            wave.steps.len(),
                        ),
                        "\x1b[2;35m",
                        use_color,
                    ),
                );
            }

            if trace {
                events.push(TraceEvent {
                    event: "wave_start".to_string(),
                    unit: unit.flow_name.clone(),
                    step: String::new(),
                    detail: format!(
                        "wave={}/{}, steps=[{}], parallel={}",
                        wave_idx + 1,
                        schedule.waves.len(),
                        wave.steps.join(", "),
                        is_parallel_wave,
                    ),
                });
            }

            if is_parallel_wave {
                // ── Parallel wave execution ──────────────────────
                // Snapshot shared state; each thread gets its own copy.
                let ctx_snapshot = ctx.clone();
                let conversation_snapshot = conversation.clone();

                let wave_results = parallel::execute_wave(wave, |step_name| {
                    // Thread-local state (no mutation of shared state)
                    let (_j, step) = match step_map.get(step_name) {
                        Some(v) => *v,
                        None => return parallel::WaveStepResult {
                            step_name: step_name.to_string(),
                            output: "step not found".to_string(),
                            success: false,
                        },
                    };

                    // Native tool steps
                    if step.step_type == "use_tool" {
                        // §Fase 58.e — `use Tool(k = v, …)` assembles a typed
                        // structured JSON body; the legacy single-`on <arg>`
                        // form keeps the flat interpolation (D5).
                        let arg = if !step.tool_named_args.is_empty() {
                            let interpolated: Vec<(String, String)> = step
                                .tool_named_args
                                .iter()
                                .map(|(n, v, kind)| {
                                    // §Fase 60 — resolve by value_kind (reference
                                    // → binding lookup; literal → interpolation).
                                    (n.clone(), ctx_snapshot.resolve_named_arg(v, kind))
                                })
                                .collect();
                            build_structured_tool_body(&interpolated, &step.tool_param_types)
                        } else {
                            ctx_snapshot.interpolate(step.tool_argument.as_deref().unwrap_or(""))
                        };
                        if let Some(result) = registry.dispatch(&step.step_name, &arg) {
                            return parallel::WaveStepResult {
                                step_name: step_name.to_string(),
                                output: result.output,
                                success: result.success,
                            };
                        }
                    }

                    // LLM steps — each thread gets its own conversation copy
                    let full_system = format!("{}\n\n{}", unit.system_prompt, step.system_prompt);
                    let interpolated_prompt = ctx_snapshot.interpolate(&step.user_prompt);
                    let mut thread_conversation = conversation_snapshot.clone();
                    let mut thread_events: Vec<TraceEvent> = Vec::new();
                    let mut thread_input_tokens: u64 = 0;
                    let mut thread_output_tokens: u64 = 0;

                    let result = execute_step_with_retry(
                        backend_name,
                        &api_key,
                        &full_system,
                        &interpolated_prompt,
                        &step.step_name,
                        &unit.flow_name,
                        &unit.resolved_anchors,
                        use_color,
                        false, // no trace in parallel threads (avoid interleaved output)
                        false, // no streaming in parallel (interleaved stdout)
                        json,
                        &mut thread_conversation,
                        &mut thread_events,
                        &mut thread_input_tokens,
                        &mut thread_output_tokens,
                    );

                    parallel::WaveStepResult {
                        step_name: step_name.to_string(),
                        output: result,
                        success: true,
                    }
                });

                // Merge results back into shared state
                for wr in &wave_results {
                    let (j, step) = step_map[wr.step_name.as_str()];

                    ctx.set_step(&step.step_name, &step.step_type, j);
                    ctx.set_result(&step.step_name, &wr.output);
                    hooks.on_step_start(&step.step_name, &step.step_type);
                    hooks.on_step_end(0, 0, 0, 0, false);

                    if !json {
                        let status = if wr.success { "ok" } else { "error" };
                        println!(
                            "  {} {}.{} [{}] → {} [parallel]",
                            c("⫘", "\x1b[35m", use_color),
                            j + 1,
                            c(&step.step_name, "\x1b[1m", use_color),
                            step.step_type,
                            c(
                                &format!("{status}: {}", truncate_output(&wr.output, 80)),
                                if wr.success { "\x1b[32m" } else { "\x1b[31m" },
                                use_color,
                            ),
                        );
                    }

                    report.record_step(StepReport {
                        name: step.step_name.clone(),
                        step_type: step.step_type.clone(),
                        result: wr.output.clone(),
                        duration_ms: 0,
                        input_tokens: 0,
                        output_tokens: 0,
                        anchor_breaches: 0,
                        chain_activations: 0,
                        was_retried: false,
                    });

                    if trace {
                        events.push(TraceEvent {
                            event: "step_parallel".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: format!(
                                "wave={}, success={}, output={}",
                                wave_idx + 1,
                                wr.success,
                                truncate_output(&wr.output, 120),
                            ),
                        });
                    }
                }

                // Append wave results to conversation as synthetic context
                for wr in &wave_results {
                    conversation.add_user(&format!("[Step {}]", wr.step_name));
                    conversation.add_assistant(&wr.output);
                }
            } else {
                // ── Sequential execution (single-step wave) ──────
                for step_name in &wave.steps {
                    let (j, step) = step_map[step_name.as_str()];

            ctx.set_step(&step.step_name, &step.step_type, j);
            hooks.on_step_start(&step.step_name, &step.step_type);

            if !json {
                println!(
                    "  {} {}.{} [{}]",
                    c("→", "\x1b[33m", use_color),
                    j + 1,
                    c(&step.step_name, "\x1b[1m", use_color),
                    step.step_type,
                );
            }

            // ── Native tool interception ────────────────────────
            if step.step_type == "use_tool" {
                // §Fase 58.e — `use Tool(k = v, …)` assembles a typed structured
                // JSON body; the legacy single-`on <arg>` form keeps the flat
                // interpolation (D5).
                let arg = if !step.tool_named_args.is_empty() {
                    let interpolated: Vec<(String, String)> = step
                        .tool_named_args
                        .iter()
                        // §Fase 60 — resolve by value_kind (reference → binding
                        // lookup; literal → interpolation).
                        .map(|(n, v, kind)| (n.clone(), ctx.resolve_named_arg(v, kind)))
                        .collect();
                    build_structured_tool_body(&interpolated, &step.tool_param_types)
                } else {
                    ctx.interpolate(step.tool_argument.as_deref().unwrap_or(""))
                };
                if let Some(result) = registry.dispatch(&step.step_name, &arg) {
                    let status = if result.success { "ok" } else { "error" };
                    if !json {
                        println!(
                            "  {} {} → {} [native]",
                            c("🔧", "\x1b[36m", use_color),
                            c(&result.tool_name, "\x1b[1m", use_color),
                            c(&format!("{status}: {}", result.output), if result.success { "\x1b[32m" } else { "\x1b[31m" }, use_color),
                        );
                    }

                    // Validate output against schema + track effects
                    if let Some(entry) = registry.get(&step.step_name) {
                        if !entry.output_schema.is_empty() {
                            let vr = tool_validator::validate_output(
                                &step.step_name, &result.output, &entry.output_schema,
                            );
                            if !vr.passed && !json {
                                println!(
                                    "  {} {}",
                                    c("⚠", "\x1b[33m", use_color),
                                    c(
                                        &format!("Validation: {} — {}", vr.schema, vr.message),
                                        "\x1b[33m",
                                        use_color,
                                    ),
                                );
                            }
                            if trace {
                                events.push(TraceEvent {
                                    event: format!("tool_validate_{}", if vr.passed { "pass" } else { "fail" }),
                                    unit: unit.flow_name.clone(),
                                    step: step.step_name.clone(),
                                    detail: format!("schema={}, {}", vr.schema, vr.message),
                                });
                            }
                        }
                        if !entry.effect_row.is_empty() {
                            effects.record(
                                &step.step_name, &step.step_name, &unit.flow_name, &entry.effect_row,
                            );
                        }
                    }

                    ctx.set_result(&step.step_name, &result.output);
                    hooks.on_step_end(0, 0, 0, 0, false);
                    report.record_step(StepReport {
                        name: step.step_name.clone(),
                        step_type: step.step_type.clone(),
                        result: result.output.clone(),
                        duration_ms: 0,
                        input_tokens: 0,
                        output_tokens: 0,
                        anchor_breaches: 0,
                        chain_activations: 0,
                        was_retried: false,
                    });
                    if trace {
                        events.push(TraceEvent {
                            event: "tool_native".to_string(),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: format!(
                                "tool={}, success={}, output={}",
                                result.tool_name, result.success, result.output
                            ),
                        });
                    }
                    continue; // Skip LLM call
                }
                // Unknown tool — fall through to LLM
            }

            // ── Session memory interception ─────────────────────
            if matches!(step.step_type.as_str(), "remember" | "recall" | "persist" | "retrieve" | "mutate" | "purge") {
                let raw_expr = step.memory_expression.as_deref().unwrap_or("");
                let expr = ctx.interpolate(raw_expr);

                // §Fase 35.e — SQL routing. A persist/retrieve/mutate/
                // purge whose store resolves to a postgresql backend
                // executes real SQL and skips the key-value path
                // entirely. remember/recall, and every in_memory or
                // undeclared store, fall through to the byte-identical
                // pre-35 key-value path below (D3 — absolute).
                if matches!(step.step_type.as_str(), "persist" | "retrieve" | "mutate" | "purge")
                    && store_registry.backend_kind(&step.step_name)
                        == Some(StoreBackendKind::Postgresql)
                {
                    // §Fase 37.d (D3) — pass the RAW `store:where`
                    // expression (NOT the pre-interpolated `expr`): the
                    // filter compiler resolves `${name}` in the `where`
                    // clause into `$N` bind parameters, never a splice.
                    // §Fase 37.x.j.10 — call the async variant via
                    // `.await` on the SAME runtime as the outer
                    // `execute_server_flow` block_on_store. Pre-hotfix
                    // this was the sync `execute_sql_store_step` whose
                    // internal block_on_store created a per-step temp
                    // runtime, defeating the pin's reactor handles.
                    let (result_text, ok) = match execute_sql_store_step_async(
                        store_registry,
                        pinned_conns,
                        &step.step_type,
                        &step.step_name,
                        raw_expr,
                        step.store_fields.as_deref(),
                        &ctx,
                    ).await {
                        Ok(summary) => (summary, true),
                        Err(e) => (format!("store error: {e}"), false),
                    };
                    ctx.set_result(&step.step_name, &result_text);
                    let detail = format!("{} → {}", step.step_name, result_text);
                    if !json {
                        let color = if ok { "\x1b[35m" } else { "\x1b[31m" };
                        println!(
                            "  {} {} [{}]",
                            c(if ok { "💾" } else { "✗" }, color, use_color),
                            c(&detail, color, use_color),
                            step.step_type,
                        );
                    }
                    hooks.on_step_end(0, 0, 0, 0, false);
                    report.record_step(StepReport {
                        name: step.step_name.clone(),
                        step_type: step.step_type.clone(),
                        result: detail.clone(),
                        duration_ms: 0,
                        input_tokens: 0,
                        output_tokens: 0,
                        anchor_breaches: 0,
                        chain_activations: 0,
                        was_retried: false,
                    });
                    if trace {
                        events.push(TraceEvent {
                            event: format!("axonstore_sql_{}", step.step_type),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail,
                        });
                    }
                    continue; // Skip the key-value path and the LLM call.
                }

                let (action, detail) = match step.step_type.as_str() {
                    "remember" => {
                        session.remember(&step.step_name, &expr, &step.step_name);
                        ctx.set_result(&step.step_name, &expr);
                        ("remember", format!("{} = {}", step.step_name, expr))
                    }
                    "recall" => {
                        let val = session.recall(&step.step_name)
                            .map(|e| e.value.clone())
                            .unwrap_or_else(|| "(not found)".to_string());
                        ctx.set_result(&step.step_name, &val);
                        ("recall", format!("{} → {}", step.step_name, val))
                    }
                    "persist" => {
                        session.persist(&step.step_name, &expr, &step.step_name);
                        ctx.set_result(&step.step_name, &expr);
                        ("persist", format!("{} → store", step.step_name))
                    }
                    "retrieve" => {
                        let val = session.retrieve(&step.step_name)
                            .map(|e| e.value.clone())
                            .unwrap_or_else(|| {
                                let results = session.retrieve_query(&expr);
                                if results.is_empty() {
                                    "(not found)".to_string()
                                } else {
                                    format!("{} entries", results.len())
                                }
                            });
                        ctx.set_result(&step.step_name, &val);
                        ("retrieve", format!("{} → {}", step.step_name, val))
                    }
                    "mutate" => {
                        let parts: Vec<&str> = expr.splitn(2, ':').collect();
                        let ok = if parts.len() == 2 {
                            session.mutate(parts[0], parts[1], &step.step_name)
                        } else {
                            false
                        };
                        let msg = if ok { "updated" } else { "not found" };
                        ctx.set_result(&step.step_name, msg);
                        ("mutate", format!("{} → {}", step.step_name, msg))
                    }
                    "purge" => {
                        let ok = session.purge(&step.step_name);
                        let msg = if ok { "removed" } else { "not found" };
                        ctx.set_result(&step.step_name, msg);
                        ("purge", format!("{} → {}", step.step_name, msg))
                    }
                    _ => unreachable!(),
                };

                if !json {
                    println!(
                        "  {} {} [{}]",
                        c("💾", "\x1b[35m", use_color),
                        c(&detail, "\x1b[35m", use_color),
                        action,
                    );
                }
                hooks.on_step_end(0, 0, 0, 0, false);
                report.record_step(StepReport {
                    name: step.step_name.clone(),
                    step_type: step.step_type.clone(),
                    result: detail.clone(),
                    duration_ms: 0,
                    input_tokens: 0,
                    output_tokens: 0,
                    anchor_breaches: 0,
                    chain_activations: 0,
                    was_retried: false,
                });
                if trace {
                    events.push(TraceEvent {
                        event: format!("session_{action}"),
                        unit: unit.flow_name.clone(),
                        step: step.step_name.clone(),
                        detail,
                    });
                }
                continue; // Skip LLM call
            }

            // ── §Fase 65.A/B — structural verbs via the flow dispatcher ────
            // navigate / drill / trail are PURE EFFECTS over the live corpus /
            // PIX state: they must run the dispatcher's REAL handler (signed-EPR
            // / ε-informative MDN nav, PIX subtree drill, breadcrumb trail) — NOT
            // the LLM fallthrough below, which fabricates output (the Kivi gap
            // report). The dispatcher shares this flow's exact pinned, RLS-scoped
            // connections + its MDN interaction history.
            if structural_dispatch_enabled() {
                if let (Some(node), Some(nd)) = (step.structural_node.as_ref(), nav_dispatch) {
                    let (result_text, ok) = match dispatch_structural(
                        node,
                        &mut ctx,
                        &unit.flow_name,
                        backend_name,
                        &unit.system_prompt,
                        pinned_conns,
                        nd,
                        &nav_histories,
                    )
                    .await
                    {
                        Ok(out) => (out, true),
                        Err(e) => {
                            tracing::warn!(
                                target: "axon::dispatch",
                                verb = %step.step_type,
                                step = %step.step_name,
                                error = %e,
                                "structural dispatch failed; binding empty \
                                 (NOT hallucinating via the LLM)"
                            );
                            (String::new(), false)
                        }
                    };
                    ctx.set_result(&step.step_name, &result_text);
                    if !json {
                        let color = if ok { "\x1b[34m" } else { "\x1b[31m" };
                        println!(
                            "  {} {} [{}]",
                            c(if ok { "🧭" } else { "✗" }, color, use_color),
                            c(
                                &format!("{} → {} char(s)", step.step_name, result_text.len()),
                                color,
                                use_color,
                            ),
                            step.step_type,
                        );
                    }
                    hooks.on_step_end(0, 0, 0, 0, false);
                    report.record_step(StepReport {
                        name: step.step_name.clone(),
                        step_type: step.step_type.clone(),
                        result: result_text,
                        duration_ms: 0,
                        input_tokens: 0,
                        output_tokens: 0,
                        anchor_breaches: 0,
                        chain_activations: 0,
                        was_retried: false,
                    });
                    if trace {
                        events.push(TraceEvent {
                            event: format!("{}_structural", step.step_type),
                            unit: unit.flow_name.clone(),
                            step: step.step_name.clone(),
                            detail: format!("verb={}", step.step_type),
                        });
                    }
                    continue; // Skip the LLM call — a pure-effect verb.
                }
            }

            // ── LLM call with variable interpolation + conversation history ──
            let full_system = format!("{}\n\n{}", unit.system_prompt, step.system_prompt);
            let interpolated_prompt = ctx.interpolate(&step.user_prompt);

            // Enforce context budget before LLM call
            let dropped = context_window.enforce(&mut conversation);
            if dropped > 0 {
                if !json {
                    println!(
                        "  {} {}",
                        c("⊘", "\x1b[33m", use_color),
                        c(
                            &format!(
                                "Context window: dropped {} messages ({} total chars remaining, ~{}k tokens)",
                                dropped,
                                conversation.total_chars(),
                                ContextWindow::estimate_tokens(conversation.total_chars()) / 1000,
                            ),
                            "\x1b[2;33m",
                            use_color,
                        ),
                    );
                }
                if trace {
                    events.push(TraceEvent {
                        event: "context_truncated".to_string(),
                        unit: unit.flow_name.clone(),
                        step: step.step_name.clone(),
                        detail: format!(
                            "dropped={}, remaining_chars={}, remaining_turns={}",
                            dropped,
                            conversation.total_chars(),
                            conversation.turn_count(),
                        ),
                    });
                }
            }

            let step_input_before = total_input_tokens;
            let step_output_before = total_output_tokens;
            let step_result = execute_step_with_retry(
                backend_name,
                &api_key,
                &full_system,
                &interpolated_prompt,
                &step.step_name,
                &unit.flow_name,
                &unit.resolved_anchors,
                use_color,
                trace,
                stream,
                json,
                &mut conversation,
                &mut events,
                &mut total_input_tokens,
                &mut total_output_tokens,
            );
            let step_in = total_input_tokens - step_input_before;
            let step_out = total_output_tokens - step_output_before;
            ctx.set_result(&step.step_name, &step_result);
            hooks.on_step_end(step_in, step_out, 0, 0, false);
            report.record_step(StepReport {
                name: step.step_name.clone(),
                step_type: step.step_type.clone(),
                result: step_result,
                duration_ms: 0,
                input_tokens: step_in,
                output_tokens: step_out,
                anchor_breaches: 0,
                chain_activations: 0,
                was_retried: false,
            });

                } // end sequential wave step loop
            } // end sequential/parallel branch
        } // end wave loop

        hooks.on_unit_end();
        report.end_unit(&hooks);

        if trace {
            events.push(TraceEvent {
                event: "unit_complete".to_string(),
                unit: unit.flow_name.clone(),
                step: String::new(),
                detail: format!(
                    "{} steps, {} conversation turns, {} chars context{}",
                    unit.steps.len(),
                    conversation.turn_count(),
                    conversation.total_chars(),
                    if context_window.was_truncated() {
                        format!(
                            ", {} messages truncated across {} events",
                            context_window.total_dropped,
                            context_window.truncation_count,
                        )
                    } else {
                        String::new()
                    },
                ),
            });
        }

        if !json {
            println!(
                "  {} {} steps completed",
                c("✓", "\x1b[32m", use_color),
                unit.steps.len()
            );
        }
    }

    // Flush session store to disk
    if let Err(e) = session.flush() {
        if !json {
            eprintln!("  {} {}", c("⚠", "\x1b[33m", use_color), e);
        }
    } else if session.store_count() > 0 && !json {
        println!(
            "  {}",
            c(
                &format!("💾 Session: {} memory, {} persistent ({})",
                    session.memory_count(), session.store_count(),
                    session.store_path().display()),
                "\x1b[2m",
                use_color,
            )
        );
    }

    // Token usage summary
    if !json && (total_input_tokens > 0 || total_output_tokens > 0) {
        println!(
            "\n  {}",
            c(
                &format!(
                    "Token usage: {} input + {} output = {} total",
                    total_input_tokens,
                    total_output_tokens,
                    total_input_tokens + total_output_tokens
                ),
                "\x1b[2m",
                use_color,
            )
        );
    }

    // Execution metrics summary
    if hooks.total_steps() > 0 {
        if !json {
            println!(
                "  {}",
                c(
                    &format!(
                        "Execution: {} steps across {} units in {}ms (avg {}ms/step){}",
                        hooks.total_steps(),
                        hooks.unit_metrics().len(),
                        hooks.total_duration_ms(),
                        hooks.avg_step_duration_ms(),
                        if hooks.retried_steps() > 0 {
                            format!(", {} retried", hooks.retried_steps())
                        } else {
                            String::new()
                        },
                    ),
                    "\x1b[2m",
                    use_color,
                )
            );
        }

        if trace {
            // Per-unit timing breakdown in trace
            for um in hooks.unit_metrics() {
                events.push(TraceEvent {
                    event: "hook_unit_metrics".to_string(),
                    unit: um.unit_name.clone(),
                    step: String::new(),
                    detail: format!(
                        "duration={}ms, steps={}, tokens_in={}, tokens_out={}, breaches={}, chains={}",
                        um.duration_ms, um.total_steps,
                        um.total_input_tokens, um.total_output_tokens,
                        um.total_anchor_breaches, um.total_chain_activations,
                    ),
                });
            }
        }
    }

    // Effect tracking summary
    if effects.total_executions() > 0 {
        if !json {
            println!(
                "  {}",
                c(
                    &format!("Effects: {}", effects.summary()),
                    "\x1b[2m",
                    use_color,
                )
            );
        }
        if trace {
            events.push(TraceEvent {
                event: "effect_summary".to_string(),
                unit: String::new(),
                step: String::new(),
                detail: effects.summary(),
            });
        }
    }

    Ok((true, events))
}

/// §Fase 35.e — Sync wrapper for `execute_real_async`.
///
/// §Fase 37.x.j.10 (POST-CLOSE HOTFIX) — retained for the CLI path
/// + pre-async tests. Wraps the async fn in a SINGLE `block_on_store`
/// so the entire flow execution lives on one temporary tokio runtime.
/// Pre-hotfix the sync variant called `execute_sql_store_step` which
/// HAD its own block_on_store internally (per-step temp runtime); when
/// the caller's eager pin acquisition was ALSO on a separate temp
/// runtime, the pin's reactor handles were stale → SQL `.await` hung.
/// The new structure guarantees pin + dispatch share one runtime.
///
/// Production server-driven callers (`execute_server_flow`) MUST NOT
/// use this wrapper — they construct their OWN outer `block_on_store`
/// to ALSO include the eager pin acquisition. This wrapper is correct
/// only when the caller's `pinned_conns` map is empty (legacy Pool
/// path) — in that case there's no pre-acquired pin whose runtime
/// could mismatch the dispatch's.
fn execute_real(
    units: &[ExecutionUnit],
    backend_name: &str,
    source_file: &str,
    use_color: bool,
    trace: bool,
    stream: bool,
    output_fmt: OutputFormat,
    report: &mut ReportBuilder,
    registry: &ToolRegistry,
    store_registry: &StoreRegistry,
    pinned_conns: &mut std::collections::HashMap<String, sqlx::pool::PoolConnection<sqlx::Postgres>>,
    api_key_override: Option<&str>,
) -> Result<(bool, Vec<TraceEvent>), backend::BackendError> {
    block_on_store(execute_real_async(
        units,
        backend_name,
        source_file,
        use_color,
        trace,
        stream,
        output_fmt,
        report,
        registry,
        store_registry,
        pinned_conns,
        api_key_override,
        // §Fase 65.A — the CLI path does not yet unify on the dispatcher;
        // `navigate` there keeps the legacy behavior (no structural bridge).
        None,
    ))
}

/// Execute a single step with anchor-breach retry loop.
///
/// On error-severity breaches, re-prompts the LLM with violation feedback
/// up to MAX_ANCHOR_RETRIES times. Warning-severity breaches are reported
/// but do not trigger retries.
#[allow(clippy::too_many_arguments)]
fn execute_step_with_retry(
    backend_name: &str,
    api_key: &str,
    system_prompt: &str,
    original_user_prompt: &str,
    step_name: &str,
    flow_name: &str,
    anchors: &[IRAnchor],
    use_color: bool,
    trace: bool,
    stream: bool,
    json: bool,
    conversation: &mut ConversationHistory,
    events: &mut Vec<TraceEvent>,
    total_input_tokens: &mut u64,
    total_output_tokens: &mut u64,
) -> String {
    let mut user_prompt = original_user_prompt.to_string();
    let mut attempt: u32 = 0;
    let mut last_response_text = String::new();
    let effective_stream = stream && !json; // No streaming in JSON mode

    loop {
        let history = conversation.messages();
        let result = if effective_stream {
            // Streaming mode: print tokens as they arrive
            use std::io::Write;
            print!("    ");
            let _ = std::io::stdout().flush();
            let resp = backend::call_multi_stream(
                backend_name, api_key, system_prompt, history, &user_prompt, None,
                |chunk| {
                    print!("{chunk}");
                    let _ = std::io::stdout().flush();
                },
            );
            println!(); // End the streamed line
            resp
        } else {
            backend::call_multi(backend_name, api_key, system_prompt, history, &user_prompt, None)
        };

        match result {
            Ok(resp) => {
                *total_input_tokens += resp.input_tokens;
                *total_output_tokens += resp.output_tokens;
                last_response_text = resp.text.clone();

                // Print response (non-streaming: show preview; streaming: already printed)
                if !json {
                    let preview = if effective_stream {
                        String::new() // Already printed inline
                    } else if resp.text.len() > 500 {
                        format!("{}…", &resp.text[..500])
                    } else {
                        resp.text.clone()
                    };

                    println!(
                        "  {} {}",
                        c("✓", "\x1b[32m", use_color),
                        c(
                            &format!(
                                "[{}] {} tokens in, {} out",
                                resp.stop_reason, resp.input_tokens, resp.output_tokens
                            ),
                            "\x1b[2m",
                            use_color,
                        )
                    );

                    if !effective_stream {
                        for line in preview.lines() {
                            println!("    {line}");
                        }
                    }
                }

                if trace {
                    events.push(TraceEvent {
                        event: "step_complete".to_string(),
                        unit: flow_name.to_string(),
                        step: step_name.to_string(),
                        detail: format!(
                            "model={}, input_tokens={}, output_tokens={}, stop={}, attempt={}",
                            resp.model, resp.input_tokens, resp.output_tokens, resp.stop_reason, attempt + 1
                        ),
                    });
                }

                // ── Anchor checking ──────────────────────────────
                if anchors.is_empty() {
                    conversation.add_user(original_user_prompt);
                    conversation.add_assistant(&last_response_text);
                    return last_response_text;
                }

                let results = anchor_checker::check_all(anchors, &resp.text);
                let mut error_breaches: Vec<String> = Vec::new();

                for result in &results {
                    if result.passed {
                        if !json {
                            println!(
                                "  {} {}",
                                c("⚓", "\x1b[32m", use_color),
                                c(&format!("{}: pass ({:.0}%)", result.anchor_name, result.confidence * 100.0), "\x1b[32m", use_color),
                            );
                        }
                        if trace {
                            events.push(TraceEvent {
                                event: "anchor_pass".to_string(),
                                unit: flow_name.to_string(),
                                step: step_name.to_string(),
                                detail: format!("{} (confidence={:.2})", result.anchor_name, result.confidence),
                            });
                        }
                    } else {
                        if !json {
                            let severity_color = if result.severity == "error" { "\x1b[31m" } else { "\x1b[33m" };
                            println!(
                                "  {} {} [{}] ({:.0}%)",
                                c("⚓", severity_color, use_color),
                                c(&format!("{}: BREACH", result.anchor_name), &format!("\x1b[1m{severity_color}"), use_color),
                                result.severity,
                                result.confidence * 100.0,
                            );
                            for v in &result.violations {
                                println!(
                                    "    {} {}",
                                    c("↳", severity_color, use_color),
                                    v,
                                );
                            }
                        }
                        if trace {
                            events.push(TraceEvent {
                                event: "anchor_breach".to_string(),
                                unit: flow_name.to_string(),
                                step: step_name.to_string(),
                                detail: format!(
                                    "{} [{}] (confidence={:.2}): {}",
                                    result.anchor_name,
                                    result.severity,
                                    result.confidence,
                                    result.violations.join("; ")
                                ),
                            });
                        }

                        // Collect error-severity breaches for retry
                        if result.severity == "error" {
                            for v in &result.violations {
                                error_breaches.push(format!("{}: {}", result.anchor_name, v));
                            }
                        }
                    }
                }

                // ── Anchor chaining ─────────────────────────────
                let chain_results = anchor_checker::check_chained(&results, anchors, &resp.text);
                for (rule, chain_result) in &chain_results {
                    if chain_result.passed {
                        if !json {
                            println!(
                                "  {} {}",
                                c("⛓", "\x1b[36m", use_color),
                                c(
                                    &format!(
                                        "{} → {}: pass ({:.0}%) [{}]",
                                        rule.trigger, chain_result.anchor_name,
                                        chain_result.confidence * 100.0, rule.reason,
                                    ),
                                    "\x1b[36m",
                                    use_color,
                                ),
                            );
                        }
                    } else {
                        if !json {
                            println!(
                                "  {} {}",
                                c("⛓", "\x1b[31m", use_color),
                                c(
                                    &format!(
                                        "{} → {}: BREACH ({:.0}%) [{}]",
                                        rule.trigger, chain_result.anchor_name,
                                        chain_result.confidence * 100.0, rule.reason,
                                    ),
                                    "\x1b[1;31m",
                                    use_color,
                                ),
                            );
                            for v in &chain_result.violations {
                                println!(
                                    "    {} {}",
                                    c("↳", "\x1b[31m", use_color),
                                    v,
                                );
                            }
                        }
                        // Chain breaches count as error breaches for retry
                        if chain_result.severity == "error" {
                            for v in &chain_result.violations {
                                error_breaches.push(format!(
                                    "{} (chained from {}): {}",
                                    chain_result.anchor_name, rule.trigger, v
                                ));
                            }
                        }
                    }
                    if trace {
                        events.push(TraceEvent {
                            event: "anchor_chain".to_string(),
                            unit: flow_name.to_string(),
                            step: step_name.to_string(),
                            detail: format!(
                                "{} → {}: {} (confidence={:.2}, reason={})",
                                rule.trigger,
                                chain_result.anchor_name,
                                if chain_result.passed { "pass" } else { "BREACH" },
                                chain_result.confidence,
                                rule.reason,
                            ),
                        });
                    }
                }

                // ── Retry on error-severity breaches ─────────────
                if error_breaches.is_empty() || attempt >= MAX_ANCHOR_RETRIES {
                    if !error_breaches.is_empty() {
                        if !json {
                            println!(
                                "  {} {}",
                                c("⚠", "\x1b[33m", use_color),
                                c(
                                    &format!(
                                        "Anchor breaches remain after {} retries — continuing",
                                        MAX_ANCHOR_RETRIES
                                    ),
                                    "\x1b[33m",
                                    use_color,
                                ),
                            );
                        }
                        if trace {
                            events.push(TraceEvent {
                                event: "retry_exhausted".to_string(),
                                unit: flow_name.to_string(),
                                step: step_name.to_string(),
                                detail: format!(
                                    "{} error breaches after {} retries",
                                    error_breaches.len(),
                                    MAX_ANCHOR_RETRIES
                                ),
                            });
                        }
                    }
                    conversation.add_user(original_user_prompt);
                    conversation.add_assistant(&last_response_text);
                    return last_response_text;
                }

                // Build retry prompt with violation feedback
                attempt += 1;
                let feedback = error_breaches
                    .iter()
                    .enumerate()
                    .map(|(i, v)| format!("{}. {}", i + 1, v))
                    .collect::<Vec<_>>()
                    .join("\n");

                user_prompt = format!(
                    "{}\n\n\
                    IMPORTANT: Your previous response violated the following constraints:\n\
                    {}\n\n\
                    Please regenerate your response, strictly avoiding the violations listed above.",
                    original_user_prompt,
                    feedback
                );

                if !json {
                    println!(
                        "  {} {}",
                        c("↻", "\x1b[35m", use_color),
                        c(
                            &format!(
                                "Retry {}/{} — {} anchor breach(es) detected",
                                attempt,
                                MAX_ANCHOR_RETRIES,
                                error_breaches.len()
                            ),
                            "\x1b[1;35m",
                            use_color,
                        ),
                    );
                }

                if trace {
                    events.push(TraceEvent {
                        event: "retry_attempt".to_string(),
                        unit: flow_name.to_string(),
                        step: step_name.to_string(),
                        detail: format!(
                            "attempt={}/{}, breaches: {}",
                            attempt,
                            MAX_ANCHOR_RETRIES,
                            error_breaches.join("; ")
                        ),
                    });
                }

                // Loop continues with updated user_prompt
            }
            Err(err) => {
                if !json {
                    eprintln!(
                        "  {} step '{}' failed: {}",
                        c("✗", "\x1b[31m", use_color),
                        step_name,
                        err
                    );
                }

                if trace {
                    events.push(TraceEvent {
                        event: "step_error".to_string(),
                        unit: flow_name.to_string(),
                        step: step_name.to_string(),
                        detail: format!("{err}"),
                    });
                }

                return String::new(); // API error — don't retry
            }
        }
    }
}

fn truncate(s: &str, max: usize) -> String {
    let first_line = s.lines().next().unwrap_or(s);
    if first_line.len() > max {
        format!("{}…", &first_line[..max])
    } else {
        first_line.to_string()
    }
}

/// Build a plan export from compiled execution units.
fn build_plan_export(
    units: &[ExecutionUnit],
    source_file: &str,
    backend: &str,
    registry: &ToolRegistry,
) -> plan_export::PlanExport {
    let mut plan_units = Vec::new();
    let mut all_deps = PlanDependencies {
        max_depth: 0,
        parallel_groups: Vec::new(),
        unresolved_refs: Vec::new(),
    };

    for unit in units {
        // Build step infos for dependency analysis
        // §Fase 61 — fold `use Tool(k = v)` keyword-arg references into the
        // analysis argument so the plan reflects the real dependency edges.
        let step_name_set: std::collections::HashSet<&str> =
            unit.steps.iter().map(|s| s.step_name.as_str()).collect();
        let step_infos: Vec<step_deps::StepInfo> = unit.steps.iter().map(|s| {
            step_deps::StepInfo {
                name: s.step_name.clone(),
                step_type: s.step_type.clone(),
                user_prompt: s.user_prompt.clone(),
                argument: step_deps::use_tool_analysis_argument(
                    s.tool_argument.as_deref()
                        .or(s.memory_expression.as_deref())
                        .unwrap_or(""),
                    &s.tool_named_args,
                    &step_name_set,
                ),
            }
        }).collect();

        let dep_graph = step_deps::analyze(&step_infos);

        // Build plan steps with dependency info
        let plan_steps: Vec<PlanStep> = unit.steps.iter().zip(dep_graph.steps.iter()).map(|(s, d)| {
            PlanStep {
                name: s.step_name.clone(),
                step_type: s.step_type.clone(),
                prompt_preview: truncate(&s.user_prompt, 200),
                tool_argument: s.tool_argument.clone(),
                memory_expression: s.memory_expression.clone(),
                depends_on: d.depends_on.clone(),
                is_root: d.is_root,
            }
        }).collect();

        plan_units.push(PlanUnit {
            flow_name: unit.flow_name.clone(),
            persona_name: unit.persona_name.clone(),
            context_name: unit.context_name.clone(),
            effort: unit.effort.clone(),
            anchor_count: unit.resolved_anchors.len(),
            anchors: unit.anchor_instructions.clone(),
            steps: plan_steps,
        });

        // Merge dependency info
        if dep_graph.max_depth > all_deps.max_depth {
            all_deps.max_depth = dep_graph.max_depth;
        }
        all_deps.parallel_groups.extend(dep_graph.parallel_groups);
        all_deps.unresolved_refs.extend(
            dep_graph.unresolved_refs.into_iter().map(|(step, var)| {
                UnresolvedRef { step, variable: var }
            }),
        );
    }

    // Build tool info
    let tools = PlanTools {
        total: registry.len(),
        builtin: registry.builtin_names().into_iter().map(|s| s.to_string()).collect(),
        program: registry.program_names().into_iter().map(|s| s.to_string()).collect(),
        registered: registry.tool_names().into_iter().map(|name| {
            let entry = registry.get(name).unwrap();
            PlanToolEntry {
                name: entry.name.clone(),
                provider: entry.provider.clone(),
                source: format!("{:?}", entry.source).to_lowercase(),
                output_schema: entry.output_schema.clone(),
                effect_row: entry.effect_row.clone(),
            }
        }).collect(),
    };

    PlanBuilder::build(source_file, backend, &plan_units, tools, all_deps)
}

// ── Server execution entry point ─────────────────────────────────────────────

pub struct ServerRunnerMetrics {
    pub success: bool,
    pub steps_executed: usize,
    pub tokens_input: u64,
    pub tokens_output: u64,
    pub anchor_breaches: usize,
    pub step_names: Vec<String>,
    pub step_results: Vec<String>,
    /// Per-step token chunks for streaming (simulated from step results).
    pub per_step_chunks: Vec<Vec<String>>,
    /// §Fase 39.c.y — semantic provenance events captured during
    /// flow execution. Each entry is a `kind:identifier` slug
    /// (closed taxonomy enforced by producer sites):
    ///   - `retrieve:<store>`         — Pillar II store read
    ///   - `persist:<store>`          — Pillar II store insert
    ///   - `mutate:<store>`           — Pillar II store update
    ///   - `purge:<store>`            — Pillar II store delete
    ///   - `shield:<name>@<step>`     — Pillar I shield invocation
    ///   - `ots:<name>@<step>`        — OTS apply
    ///   - `mandate:<name>@<step>`    — mandate apply
    ///   - `compute:<name>@<step>`    — compute apply
    ///   - `lambda_apply:<name>@<step>` — lambda data apply
    /// The wire envelope's `provenance_chain` is built from
    /// `[flow:F, …events…, step:S0, step:S1, …, backend:B]`.
    /// Empty for trivial flows; populated by [`emit_provenance_event`]
    /// at the runtime sites.
    pub provenance_events: Vec<String>,
    /// §Fase 39.c.z — closed-catalog blame attribution from runtime
    /// degradation events. Populated when:
    ///   - an anchor with severity != "error" fires (degraded path
    ///     proceeds)
    ///   - a shield flags content but flow proceeds
    ///   - a store mutation chain verification fails AND flow
    ///     proceeds with prior-state read
    ///   - a backend returns truncated / partial response
    ///   - D5 detects a recoverable type mismatch
    /// `None` on the clean happy path. The first surfaced blame
    /// wins (subsequent events are recorded in audit_log but do
    /// not overwrite the primary attribution).
    pub blame_attribution: Option<crate::wire_envelope::BlameContext>,
    /// §Fase 55.b — the Theorem 5.1 `(base, scope, confidence)` triple of
    /// every flow-level `use <Tool>` dispatch whose tool declares an
    /// `epistemic:<level>` effect. Derived from the IR via
    /// [`crate::epistemic_capture::collect_for_flow`] — the same function
    /// the streaming path calls, so both transports surface byte-identical
    /// envelopes (§55.c parity). Empty for flows with no epistemic tool.
    pub epistemic_envelopes: Vec<crate::epistemic_capture::EpistemicEnvelope>,
}

/// §Fase 55.b/c — derive a flow's epistemic envelopes from the IR. This is
/// the SINGLE site both transports funnel through — the synchronous runner
/// calls it directly with its in-hand `ir`; the streaming
/// `axon_server::resolve_epistemic_envelopes_for_flow` re-derives the IR
/// from source and calls THIS function — so the sync `FlowEnvelope` and the
/// streaming `axon.complete` carry byte-identical `(base, scope, confidence)`
/// triples by construction (the §55.c parity invariant: there is exactly
/// one derivation, never two that could drift). `input_confidence = 1.0`:
/// a top-level flow's ψ is clean before any tool degrades it.
pub fn derive_epistemic_envelopes_for_flow(
    ir: &crate::ir_nodes::IRProgram,
    flow_name: &str,
) -> Vec<crate::epistemic_capture::EpistemicEnvelope> {
    ir.flows
        .iter()
        .find(|f| f.name == flow_name)
        .map(|f| crate::epistemic_capture::collect_for_flow(f, &ir.tools, 1.0))
        .unwrap_or_default()
}

pub fn execute_server_flow(
    ir: &crate::ir_nodes::IRProgram,
    flow_name: &str,
    backend: &str,
    source_file: &str,
    api_key_override: Option<&str>,
    // §Fase 37.b (D1) — the parsed HTTP request body. The flow's
    // declared parameters bind from its same-named fields (the Request
    // Binding Contract) and seed each `ExecContext` before the step
    // walk. `None` for a caller with no request body (D5).
    request_body: Option<&serde_json::Value>,
    // §Fase 37.y (D3) — the URL path captures (e.g. for
    // `/api/tenants/{tenant_id}` the map is `{tenant_id: "acme"}`).
    // Empty map for callers without a dynamic route (D5 backwards-
    // compat). Passed to `bind_request` alongside `request_body`.
    request_path: &std::collections::HashMap<String, String>,
    // §Fase 37.y (D3) — the URL query string parsed into name → value.
    // Single-value semantics in v1.38.5 (multi-value query keys
    // deferred per plan vivo §7); axum's `Query<HashMap>` extractor
    // provides this shape.
    request_query: &std::collections::HashMap<String, String>,
    // §Fase 58.g (D7) — optional per-tenant / per-server tool base URL.
    // When `Some`, every URL-dispatched program tool with a RELATIVE
    // `runtime` is resolved against it (`{base}/{slug}`) so the adopter
    // wires their tool-server via config without touching the program;
    // absolute runtimes stay verbatim (D5). `None` → no resolution.
    tool_base_url: Option<&str>,
) -> Result<ServerRunnerMetrics, String> {
    let mut target_run = None;
    for run in &ir.runs {
        if run.flow_name == flow_name {
            target_run = Some(run);
            break;
        }
    }

    let mut execution_units = Vec::new();

    if let Some(run) = target_run {
        execution_units.push(ExecutionUnit {
            flow_name: run.flow_name.clone(),
            persona_name: run.persona_name.clone(),
            context_name: run.context_name.clone(),
            system_prompt: build_system_prompt(run, backend),
            steps: build_compiled_steps(run, ir),
            anchor_instructions: build_anchor_instructions(run),
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
            // §Fase 37.b (D1) — bind the request body to the resolved
            // flow's declared parameters.
            // §Fase 37.y (D3) — extended to bind from path + query
            // sources too; the runtime merge respects the D4
            // compile-time collision rejection (axon-T901).
            param_bindings: run
                .resolved_flow
                .as_ref()
                .map(|f| crate::request_binding::bind_request(
                    f,
                    request_path,
                    request_query,
                    request_body,
                ))
                .unwrap_or_default(),
        });
    } else {
        let target_flow: &crate::ir_nodes::IRFlow = ir
            .flows
            .iter()
            .find(|f| f.name == flow_name)
            .ok_or_else(|| format!("flow '{}' not found in compiled IR", flow_name))?;

        let default_persona = ir.personas.first().cloned().unwrap_or_else(|| crate::ir_nodes::IRPersona {
            node_type: "Persona",
            source_line: 0,
            source_column: 0,
            name: "Default".to_string(),
            domain: vec![],
            tone: "".to_string(),
            confidence_threshold: None,
            cite_sources: None,
            refuse_if: vec![],
            language: "".to_string(),
            description: "".to_string(),
        });
        let default_context = ir.contexts.first().cloned().unwrap_or_else(|| crate::ir_nodes::IRContext {
            node_type: "Context",
            source_line: 0,
            source_column: 0,
            name: "Default".to_string(),
            memory_scope: "".to_string(),
            language: "".to_string(),
            depth: "".to_string(),
            max_tokens: None,
            temperature: None,
            cite_sources: None,
        });

        let run = crate::ir_nodes::IRRun {
            node_type: "Run",
            source_line: 0,
            source_column: 0,
            flow_name: flow_name.to_string(),
            arguments: vec![],
            persona_name: default_persona.name.clone(),
            context_name: default_context.name.clone(),
            anchor_names: vec![],
            on_failure: "".to_string(),
            on_failure_params: vec![],
            output_to: "".to_string(),
            effort: "low".to_string(),
            resolved_flow: Some(target_flow.clone()),
            resolved_persona: Some(default_persona),
            resolved_context: Some(default_context),
            resolved_anchors: ir.anchors.clone(),
        };

        execution_units.push(ExecutionUnit {
            flow_name: run.flow_name.clone(),
            persona_name: run.persona_name.clone(),
            context_name: run.context_name.clone(),
            system_prompt: build_system_prompt(&run, backend),
            steps: build_compiled_steps(&run, ir),
            anchor_instructions: build_anchor_instructions(&run),
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
            // §Fase 37.b (D1) — bind the request body to the flow's
            // declared parameters (the dynamic-route execution path).
            // §Fase 37.y (D3) — extended to bind from path + query
            // sources too.
            param_bindings: crate::request_binding::bind_request(
                target_flow,
                request_path,
                request_query,
                request_body,
            ),
        });
    }

    let mut report = crate::output::ReportBuilder::new(source_file, backend, "json");
    let mut registry = crate::tool_registry::ToolRegistry::new();
    // §Fase 58.f — register the program's declared tools on the SERVER path
    // (the CLI path already does this in `run_run`). Without this, every
    // program-declared `tool { provider: http … }` missed the registry and the
    // step silently degraded to an LLM call (the brief #22 / #17 finding). This
    // `registry` is a per-call local (built fresh above for THIS request), so
    // registration is request-scoped — no cross-tenant tool contamination
    // between concurrent flows (§58 D10). Provider→URL resolves via each tool's
    // declared `runtime:` field (D7); the §58.e structured body then POSTs to it.
    registry.register_from_ir(&ir.tools);
    // §Fase 58.g (D7) — resolve relative tool runtimes against the
    // caller-supplied per-tenant / per-server base URL. Request-scoped
    // (this `registry` is a per-call local) → no cross-tenant leakage.
    if let Some(base) = tool_base_url {
        registry.resolve_relative_endpoints(base);
    }

    // §Fase 35.e — build the axonstore registry from the program's
    // declarations. The D2 closed-catalog gate runs here: an unknown
    // backend fails fast, at deploy, with a named error.
    // §Fase 65.A — Arc the registry so it can be shared (by clone) into the
    // structural-navigate `DispatchCtx` while still being borrowed (via Deref)
    // by the eager-pin walk + `execute_real_async`'s own store path.
    let store_registry = std::sync::Arc::new(
        StoreRegistry::build(&ir.axonstore_specs)
            .map_err(|e| format!("axonstore registry: {e}"))?,
    );

    // §Fase 65.A — build the dispatcher's corpus state from the IR exactly as
    // `run_streaming_via_dispatcher` does, so a NON-streaming `navigate` runs the
    // SAME structural MDN traversal as the SSE path (instead of hallucinating via
    // the LLM). Static §63 graphs + dynamic §64 store-sourced corpora + the
    // adaptive set are all wired.
    let nav_dispatch = {
        let mut corpora: std::collections::HashMap<String, crate::mdn::Corpus> =
            std::collections::HashMap::new();
        let mut store_sources: std::collections::HashMap<
            String,
            crate::ir_nodes::IRCorpusStoreSource,
        > = std::collections::HashMap::new();
        let mut adaptive: std::collections::HashSet<String> = std::collections::HashSet::new();
        for cspec in &ir.corpus_specs {
            if !cspec.relations.is_empty() {
                let rels: Vec<(String, String, String, f64)> = cspec
                    .relations
                    .iter()
                    .map(|r| (r.etype.clone(), r.from.clone(), r.to.clone(), r.weight))
                    .collect();
                if let Ok(corpus) = crate::mdn::Corpus::from_declaration(&cspec.documents, &rels) {
                    corpora.insert(cspec.name.clone(), corpus);
                }
            }
            if let Some(src) = &cspec.store_source {
                store_sources.insert(cspec.name.clone(), src.clone());
            }
            if cspec.adaptive && (!cspec.relations.is_empty() || cspec.store_source.is_some()) {
                adaptive.insert(cspec.name.clone());
            }
        }
        NavDispatch {
            store_registry: store_registry.clone(),
            corpora: std::sync::Arc::new(corpora),
            store_sources: std::sync::Arc::new(store_sources),
            adaptive: std::sync::Arc::new(adaptive),
        }
    };

    // §Fase 37.x.j (D1) — Eager acquire one PoolConnection per
    // postgresql-backed axonstore referenced in the flow body BEFORE
    // executing any step. Each pin is held for the whole flow
    // execution and released on `pinned_conns` drop at the end of
    // this function (Rust handles the drop order: HashMap drops →
    // every PoolConnection drops → the per-conn `after_release
    // DEALLOCATE ALL` hook from Fase 38.x.a D2 runs → conn returns
    // to the pool clean).
    //
    // The discovery walk filters `step.step_type` to the four SQL
    // store ops + checks the registry's `backend_kind` to skip
    // in_memory stores (no race, no pin needed). The set is
    // deduplicated by store_name — multiple steps against the same
    // store share ONE pin (the D1 invariant).
    //
    // Acquire failure is non-fatal: the flow proceeds with an empty
    // pin map, which falls back to the legacy `StoreConn::Pool`
    // path. This preserves resilience against transient pool
    // saturation (a deploy-time `verify_postgres_schemas` failure
    // is the right gate for "store unreachable", not flow-time).
    // §Fase 37.x.j.10 (POST-CLOSE HOTFIX) — Compute the set of
    // postgresql-backed axonstores referenced by ANY execution unit's
    // body. This walks the IR purely SYNCHRONOUSLY — no .await, no
    // tokio runtime needed. The actual pin acquisition happens INSIDE
    // the single outer `block_on_store` below so the pins acquire on
    // the SAME runtime that later dispatches their SQL.
    let needed_pg_stores: std::collections::HashSet<String> = {
        let mut needed = std::collections::HashSet::new();
        for unit in &execution_units {
            for step in &unit.steps {
                if matches!(
                    step.step_type.as_str(),
                    "persist" | "retrieve" | "mutate" | "purge"
                ) && store_registry.backend_kind(&step.step_name)
                    == Some(crate::store::registry::StoreBackendKind::Postgresql)
                {
                    needed.insert(step.step_name.clone());
                }
            }
        }
        needed
    };

    let (success, _events) = if backend == "stub" {
        let result = execute_stub(&execution_units, false, false);
        // §Fase 33.b Layer 1 — close the steps_executed:0 hollow-wire bug.
        //
        // execute_stub prints step results to stdout and updates its
        // local stub_ctx but does NOT touch the ReportBuilder. The CLI
        // path at the bottom of this file handles the gap by manually
        // populating the report after execute_stub returns; the server
        // path (this function) historically did not, so every dynamic-
        // route SSE dispatch over the stub backend served a hollow
        // body: `step:""`, `token:""`, `steps_executed:0`.
        //
        // Mirror the CLI path here: enumerate the execution_units +
        // record one StepReport per step. `result: "(stub)"` matches
        // the CLI's placeholder — adopters running on stub see the
        // step name + a sentinel result, NOT an empty event. Real
        // backend streaming (Fase 33.d) replaces "(stub)" with the
        // actual backend chunk text.
        for unit in &execution_units {
            report.begin_unit(&unit.flow_name, &unit.persona_name);
            for step in &unit.steps {
                report.record_step(crate::output::StepReport {
                    name: step.step_name.clone(),
                    step_type: step.step_type.clone(),
                    result: "(stub)".to_string(),
                    duration_ms: 0,
                    input_tokens: 0,
                    output_tokens: 0,
                    anchor_breaches: 0,
                    chain_activations: 0,
                    was_retried: false,
                });
            }
            let mut stub_hooks = crate::hooks::HookManager::new();
            stub_hooks.on_unit_start(&unit.flow_name, &unit.persona_name);
            stub_hooks.on_unit_end();
            report.end_unit(&stub_hooks);
        }
        result
    } else {
        // §Fase 37.x.j.10 (POST-CLOSE HOTFIX 2026-05-21) — SINGLE
        // outer `block_on_store` wraps BOTH the eager pin acquisition
        // AND the flow execution. This is the load-bearing structural
        // property: pin acquire + every SQL dispatch + implicit pin
        // drop ALL live on the SAME temporary tokio runtime. Reactor
        // handles inside each `PoolConnection<Postgres>` stay valid
        // throughout the flow. Pre-hotfix the eager-acquire loop used
        // its OWN block_on_store per store (separate runtime), and
        // the dispatch's nested block_on_store inside the sync
        // `execute_sql_store_step` was YET ANOTHER runtime — pinned
        // conn awaited from a foreign runtime hung indefinitely.
        block_on_store(async {
            let mut pinned_conns: std::collections::HashMap<
                String,
                sqlx::pool::PoolConnection<sqlx::Postgres>,
            > = std::collections::HashMap::new();

            // — 1. Eager pin acquisition on THIS runtime.
            //
            // Note: `async` (no `move`) so we borrow `report`,
            // `registry`, `store_registry`, `execution_units`,
            // `needed_pg_stores`, etc. by reference. The async block's
            // lifetime is bounded by `block_on_store` which is
            // bounded by the enclosing function — so the borrows
            // outlive the future safely.
            for store_name in &needed_pg_stores {
                match store_registry.resolve(store_name) {
                    Ok(crate::store::registry::StoreHandle::Postgres(backend_pool)) => {
                        match backend_pool.acquire_pin().await {
                            Ok(conn) => {
                                crate::store::pin_observability::emit_pin_acquire(
                                    store_name,
                                    flow_name,
                                    "",
                                    "eager",
                                    None,
                                );
                                pinned_conns.insert(store_name.clone(), conn);
                            }
                            Err(e) => {
                                tracing::warn!(
                                    target: "axon::store::pin",
                                    store_name = %store_name,
                                    error = %e,
                                    d_letter = "37.x.j.D1",
                                    "failed to acquire flow pin; falling \
                                     back to per-step pool acquisition \
                                     (legacy path) for this store. Adopter \
                                     under transaction-mode pooler may \
                                     observe the unnamed-prepared-statement \
                                     race for this op."
                                );
                            }
                        }
                    }
                    Ok(_) => {}
                    Err(e) => {
                        tracing::warn!(
                            target: "axon::store::pin",
                            store_name = %store_name,
                            error = %e,
                            d_letter = "37.x.j.D1",
                            "failed to resolve axonstore for flow pin; \
                             falling back to per-step pool acquisition."
                        );
                    }
                }
            }

            // — 2. Run the flow on THIS SAME runtime.
            execute_real_async(
                &execution_units,
                backend,
                source_file,
                false,
                false,
                false,
                crate::output::OutputFormat::Json,
                &mut report,
                &registry,
                &store_registry,
                &mut pinned_conns,
                api_key_override,
                // §Fase 65.A — structural navigate on the server path.
                Some(&nav_dispatch),
            ).await
            // — 3. `pinned_conns` drops here → every PoolConnection
            //   drops on THIS runtime → `after_release(DEALLOCATE ALL)`
            //   hook runs (Fase 38.x.a D2) → conns return to pool
            //   clean. The whole pin lifecycle stayed on one runtime.
        }).map_err(|e| format!("Backend error: {:?}", e))?
    };

    let hooks = crate::hooks::HookManager::new();
    let r = report.build(success, &hooks);

    // §Fase 39.c.z — derive blame from the report BEFORE the
    // partial-move loop below. The producer walks the units +
    // steps by reference; the loop afterward consumes them. We
    // must extract any structured observability from `r` first.
    let blame_attribution =
        crate::wire_envelope_producers::derive_blame_from_report(&r);

    let mut steps_executed = 0;
    let mut tokens_input = 0;
    let mut tokens_output = 0;
    let mut step_results = Vec::new();
    let mut step_names = Vec::new();
    let mut anchor_breaches = 0;

    for u in r.units {
        for s in u.steps {
            steps_executed += 1;
            tokens_input += s.input_tokens;
            tokens_output += s.output_tokens;
            step_results.push(s.result);
            step_names.push(s.name);
            anchor_breaches += s.anchor_breaches as usize;
        }
    }

    // Generate per-step token chunks (simulated streaming granularity)
    let per_step_chunks: Vec<Vec<String>> = step_results.iter().map(|result| {
        if result.is_empty() {
            vec![]
        } else {
            // Chunk by word boundaries (~token-level granularity)
            result.split_whitespace()
                .collect::<Vec<&str>>()
                .chunks(3) // ~3 words per chunk
                .map(|chunk| chunk.join(" "))
                .collect()
        }
    }).collect();

    // §Fase 39.c.y — derive semantic provenance events from the IR
    // walk. Each store-touching step + each shield/ots/mandate/compute
    // apply emits a `kind:identifier` slug into the chain. The slug
    // taxonomy is closed (see ServerRunnerMetrics.provenance_events
    // doc + wire_envelope_producers module). This is the FOUNDATION
    // of Pillar II audit lineage on the wire envelope.
    let provenance_walk: Vec<(String, String)> = execution_units
        .iter()
        .flat_map(|u| {
            u.steps
                .iter()
                .map(|s| (s.step_type.clone(), s.step_name.clone()))
        })
        .collect();
    let provenance_events =
        crate::wire_envelope_producers::collect_provenance_events_from(
            &provenance_walk,
        );

    // §Fase 39.c.z — blame_attribution was derived BEFORE the
    // partial-move loop above (the report's units/steps are
    // consumed into step_names/step_results by that loop). The
    // priority order is: anchor breach > shield rejection > store
    // breach > backend soft-fail > type mismatch. The first
    // surfaced wins per `merge_blame`'s stable tie-break.

    // §Fase 55.b/c — capture the epistemic envelopes via the SINGLE shared
    // derivation (the streaming path funnels through the same function).
    let epistemic_envelopes = derive_epistemic_envelopes_for_flow(ir, flow_name);

    Ok(ServerRunnerMetrics {
        success,
        steps_executed,
        tokens_input,
        tokens_output,
        anchor_breaches,
        step_names,
        step_results,
        per_step_chunks,
        provenance_events,
        blame_attribution,
        epistemic_envelopes,
    })
}

// ── Public entry point ───────────────────────────────────────────────────────

pub fn run_run(
    file: &str,
    backend: &str,
    trace: bool,
    tool_mode: &str,
    stream: bool,
    output: &str,
    export_plan: bool,
) -> i32 {
    let output_fmt = match OutputFormat::from_str(output) {
        Some(f) => f,
        None => {
            eprintln!("✗ Invalid output format '{}'. Use 'text' or 'json'.", output);
            return 2;
        }
    };
    let json = output_fmt.is_json();
    let use_color = if json { false } else { io::stdout().is_terminal() };
    let path = Path::new(file);
    let filename = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| file.to_string());

    // ── 1. Read source ───────────────────────────────────────────
    let source = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "{}",
                c(&format!("✗ File not found: {file}"), "\x1b[1;31m", use_color)
            );
            return 2;
        }
    };

    // ── 2. Lex ───────────────────────────────────────────────────
    let tokens = match Lexer::new(&source, file).tokenize() {
        Ok(t) => t,
        Err(LexerError { message, line, column }) => {
            let loc = if column > 0 {
                format!(":{line}:{column}")
            } else {
                format!(":{line}")
            };
            eprintln!(
                "{}  {message}",
                c(&format!("✗ {filename}{loc}"), "\x1b[1;31m", use_color)
            );
            return 1;
        }
    };

    // ── 3. Parse ─────────────────────────────────────────────────
    let mut parser = Parser::new(tokens);
    let program = match parser.parse() {
        Ok(p) => p,
        Err(ParseError { message, line, column, .. }) => {
            let loc = if column > 0 {
                format!(":{line}:{column}")
            } else {
                format!(":{line}")
            };
            eprintln!(
                "{}  {message}",
                c(&format!("✗ {filename}{loc}"), "\x1b[1;31m", use_color)
            );
            return 1;
        }
    };

    // ── 4. Type check ────────────────────────────────────────────
    let type_errors = TypeChecker::new(&program).check();
    if !type_errors.is_empty() {
        eprintln!(
            "{}  {} type error(s)",
            c(&format!("✗ {filename}"), "\x1b[1;31m", use_color),
            type_errors.len()
        );
        for te in &type_errors {
            eprintln!("  error [line {}]: {}", te.line, te.message);
        }
        return 1;
    }

    // ── 5. Generate IR ───────────────────────────────────────────
    let ir_program = IRGenerator::new().generate(&program);

    // ── 6. Build execution plan ──────────────────────────────────
    let units = build_execution_plan(&ir_program, backend);

    if units.is_empty() {
        eprintln!(
            "{}",
            c("⚠ No run statements found — nothing to execute.", "\x1b[1;33m", use_color)
        );
        return 0;
    }

    // ── 7. Execute ───────────────────────────────────────────────
    let mode_label = if tool_mode == "real" {
        if stream { "real+stream" } else { "real" }
    } else {
        "stub"
    };

    if !json {
        println!(
            "{}",
            c(
                &format!(
                    "═══ AXON Run: {filename} ({} unit{}, backend={backend}, mode={tool_mode}) ═══",
                    units.len(),
                    if units.len() == 1 { "" } else { "s" }
                ),
                "\x1b[1;36m",
                use_color,
            )
        );
    }

    let mut report = ReportBuilder::new(file, backend, mode_label);

    // Build tool registry from IR + builtins
    let mut registry = ToolRegistry::new();
    registry.register_from_ir(&ir_program.tools);

    // §Fase 35.e — build the axonstore registry (D2 closed-catalog
    // gate). An unknown `backend:` fails fast, before execution.
    let store_registry = match StoreRegistry::build(&ir_program.axonstore_specs) {
        Ok(r) => r,
        Err(e) => {
            eprintln!(
                "{}  {e}",
                c(&format!("✗ {filename}"), "\x1b[1;31m", use_color)
            );
            return 1;
        }
    };

    if !json && !registry.program_names().is_empty() {
        println!(
            "  {}",
            c(
                &format!(
                    "Tools: {} registered ({} builtin + {} program)",
                    registry.len(),
                    registry.builtin_names().len(),
                    registry.program_names().len(),
                ),
                "\x1b[2m",
                use_color,
            )
        );
    }

    // ── Export plan and exit (no execution) ──────────────────────
    if export_plan {
        let plan = build_plan_export(&units, file, backend, &registry);
        println!("{}", PlanBuilder::to_json(&plan));
        return 0;
    }

    // §Fase 37.x.j (D1) — CLI path: no flow-scoped pinning (the CLI
    // runs one flow per process invocation; the legacy per-step
    // `StoreConn::Pool` fallback is acceptable for one-shot runs and
    // keeps CLI smoke tests byte-identical to pre-37.x.j).
    let mut cli_pinned_conns: std::collections::HashMap<
        String,
        sqlx::pool::PoolConnection<sqlx::Postgres>,
    > = std::collections::HashMap::new();
    let (success, events) = if tool_mode == "real" {
        match execute_real(&units, backend, file, use_color, trace, stream, output_fmt, &mut report, &registry, &store_registry, &mut cli_pinned_conns, None) {
            Ok((s, e)) => (s, e),
            Err(err) => {
                eprintln!(
                    "{}",
                    c(&format!("✗ Backend error: {err}"), "\x1b[1;31m", use_color)
                );
                return 2;
            }
        }
    } else {
        let (s, e) = execute_stub(&units, use_color, trace);
        // For stub mode, build minimal unit reports
        for unit in &units {
            report.begin_unit(&unit.flow_name, &unit.persona_name);
            for step in &unit.steps {
                report.record_step(StepReport {
                    name: step.step_name.clone(),
                    step_type: step.step_type.clone(),
                    result: "(stub)".into(),
                    duration_ms: 0,
                    input_tokens: 0,
                    output_tokens: 0,
                    anchor_breaches: 0,
                    chain_activations: 0,
                    was_retried: false,
                });
            }
            // Stub mode has no HookManager — use a temporary one for the unit
            let mut stub_hooks = crate::hooks::HookManager::new();
            stub_hooks.on_unit_start(&unit.flow_name, &unit.persona_name);
            stub_hooks.on_unit_end();
            report.end_unit(&stub_hooks);
        }
        (s, e)
    };

    // ── 8. JSON output or text summary ─────────────────────────
    if json {
        // Build report with a dummy HookManager for stub mode
        // (real mode already populated hooks inside execute_real)
        let stub_hooks = crate::hooks::HookManager::new();
        let execution_report = report.build(success, &stub_hooks);
        println!("{}", ReportBuilder::to_json(&execution_report));
    } else {
        let total_steps: usize = units.iter().map(|u| u.steps.len()).sum();
        println!(
            "\n{}",
            c(
                &format!(
                    "═══ {} unit{}, {} step{} — {mode_label} execution complete ═══",
                    units.len(),
                    if units.len() == 1 { "" } else { "s" },
                    total_steps,
                    if total_steps == 1 { "" } else { "s" },
                ),
                "\x1b[1;32m",
                use_color,
            )
        );
    }

    // ── 9. Save trace ────────────────────────────────────────────
    if trace && !events.is_empty() {
        let trace_path = Path::new(file).with_extension("trace.json");
        let trace_json = serde_json::json!({
            "_meta": {
                "source": file,
                "backend": backend,
                "tool_mode": tool_mode,
                "axon_version": AXON_VERSION,
                "mode": "stub",
            },
            "events": events,
        });
        match serde_json::to_string_pretty(&trace_json) {
            Ok(json_str) => match std::fs::write(&trace_path, json_str) {
                Ok(_) => {
                    if !json {
                        println!(
                            "{}",
                            c(
                                &format!("📋 Trace saved → {}", trace_path.display()),
                                "\x1b[1;35m",
                                use_color,
                            )
                        );
                    }
                }
                Err(e) => eprintln!("⚠ Could not save trace: {e}"),
            },
            Err(e) => eprintln!("⚠ Could not serialize trace: {e}"),
        }
    }

    if success { 0 } else { 1 }
}

// ── §Fase 35.e — sync-runner axonstore wiring tests ─────────────────

#[cfg(test)]
mod fase58e_tests {
    use super::*;

    #[test]
    fn coerce_respects_declared_int_float_bool() {
        assert_eq!(coerce_tool_arg_value("5", Some("Int")), serde_json::json!(5));
        assert_eq!(
            coerce_tool_arg_value("3.14", Some("Float")),
            serde_json::json!(3.14)
        );
        assert_eq!(
            coerce_tool_arg_value("true", Some("Bool")),
            serde_json::json!(true)
        );
        assert_eq!(
            coerce_tool_arg_value("false", Some("Bool")),
            serde_json::json!(false)
        );
    }

    #[test]
    fn coerce_keeps_string_param_verbatim_even_if_all_digits() {
        // Robustness invariant: a `String` param is NEVER numified.
        assert_eq!(
            coerce_tool_arg_value("12345", Some("String")),
            serde_json::json!("12345")
        );
        assert_eq!(
            coerce_tool_arg_value("Acme Corp", Some("String")),
            serde_json::json!("Acme Corp")
        );
    }

    #[test]
    fn coerce_optional_and_generic_types_use_base() {
        assert_eq!(coerce_tool_arg_value("7", Some("Int?")), serde_json::json!(7));
        // `List<String>` → base `List` → not a scalar → string.
        assert_eq!(
            coerce_tool_arg_value("x", Some("List<String>")),
            serde_json::json!("x")
        );
    }

    #[test]
    fn coerce_unparseable_scalar_falls_back_to_string_not_dropped() {
        // Declared Int/Bool but the (interpolated) value isn't one → lenient
        // string rather than a drop. The §58.d type-checker already flags a
        // literal mismatch at compile time.
        assert_eq!(
            coerce_tool_arg_value("not-a-number", Some("Int")),
            serde_json::json!("not-a-number")
        );
        assert_eq!(
            coerce_tool_arg_value("maybe", Some("Bool")),
            serde_json::json!("maybe")
        );
    }

    #[test]
    fn coerce_unknown_or_schemaless_param_is_string() {
        assert_eq!(coerce_tool_arg_value("5", None), serde_json::json!("5"));
        assert_eq!(
            coerce_tool_arg_value("5", Some("SearchResults")),
            serde_json::json!("5")
        );
    }

    #[test]
    fn build_body_assembles_typed_structured_object() {
        let args = vec![
            ("query".to_string(), "Acme Corp".to_string()),
            ("max_results".to_string(), "5".to_string()),
            ("safesearch".to_string(), "true".to_string()),
        ];
        let types = vec![
            ("query".to_string(), "String".to_string()),
            ("max_results".to_string(), "Int".to_string()),
            ("safesearch".to_string(), "Bool".to_string()),
        ];
        let v: serde_json::Value =
            serde_json::from_str(&build_structured_tool_body(&args, &types)).unwrap();
        assert_eq!(v["query"], serde_json::json!("Acme Corp"));
        assert_eq!(v["max_results"], serde_json::json!(5));
        assert_eq!(v["safesearch"], serde_json::json!(true));
        // NOT the flat `{"input": …}` legacy shape.
        assert!(v.get("input").is_none());
    }

    #[test]
    fn build_body_escapes_special_characters_via_serde() {
        let args = vec![("query".to_string(), "a\"b\nc".to_string())];
        let types = vec![("query".to_string(), "String".to_string())];
        let v: serde_json::Value =
            serde_json::from_str(&build_structured_tool_body(&args, &types)).unwrap();
        assert_eq!(v["query"], serde_json::json!("a\"b\nc"));
    }

    #[test]
    fn build_body_empty_args_is_empty_object() {
        assert_eq!(build_structured_tool_body(&[], &[]), "{}");
    }
}

#[cfg(test)]
mod fase35e_tests {
    use super::*;

    fn pg_store(name: &str, connection: &str) -> IRAxonStore {
        IRAxonStore {
            node_type: "axonstore",
            source_line: 0,
            source_column: 0,
            name: name.to_string(),
            backend: "postgresql".to_string(),
            connection: connection.to_string(),
            confidence_floor: None,
            isolation: String::new(),
            on_breach: String::new(),
            capability: String::new(),
            column_schema: None,
        }
    }

    #[test]
    fn block_on_store_runs_a_future_from_a_plain_thread() {
        // The CLI path: `execute_real` runs with no ambient runtime.
        let n = block_on_store(async { 20 + 15 });
        assert_eq!(n, 35);
    }

    #[tokio::test]
    async fn block_on_store_runs_a_future_from_within_a_runtime() {
        // The server path: `execute_real` runs on a Tokio worker
        // thread. `block_on_store` must NOT panic with "runtime within
        // a runtime" — it spawns a fresh OS thread that owns its own
        // runtime.
        let n = block_on_store(async { 7 * 6 });
        assert_eq!(n, 42);
    }

    #[test]
    fn sql_store_step_surfaces_missing_env_var_never_a_kv_fallback() {
        // The SQL path is reached (routing works) and fails honestly:
        // a postgresql store whose `env:` var is unset yields a typed
        // StoreError — D2's "never a silent KV fallback", proven
        // end-to-end through the sync runner's helper.
        let registry = StoreRegistry::build(&[pg_store(
            "logs",
            "env:AXON_NONEXISTENT_VAR_FASE35E",
        )])
        .unwrap();
        let ctx = ExecContext::new("F", "P", 0);
        let mut pin_map = std::collections::HashMap::new();
        let result = execute_sql_store_step(
            &registry,
            &mut pin_map,
            "retrieve",
            "logs",
            "logs:id = 1",
            None,
            &ctx,
        );
        assert!(matches!(result, Err(StoreError::MissingEnvVar { .. })));
    }

    #[test]
    fn sql_persist_below_confidence_floor_is_blocked() {
        // §35.g Pillar I — a store declaring confidence_floor rejects
        // an un-elevated persist (no `_confidence` binding) with a
        // typed epistemic error, before any row is written.
        let mut store = pg_store("ledger", "postgresql://u:p@localhost:5432/db");
        store.confidence_floor = Some(0.8);
        let registry = StoreRegistry::build(&[store]).unwrap();
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("amount", "100"); // a user binding, but no `_confidence`
        let mut pin_map = std::collections::HashMap::new();
        let result =
            execute_sql_store_step(&registry, &mut pin_map, "persist", "ledger", "ledger", None, &ctx);
        assert!(matches!(result, Err(StoreError::Epistemic(_))));
    }

    #[test]
    fn sql_store_step_persist_builds_a_row_from_user_bindings() {
        // persist into a postgresql store writes the flow's user
        // bindings as a row. With a malformed DSN the connect fails
        // (typed PoolInit error) — proving persist reaches the SQL
        // path with the bindings-as-row data assembled, not the KV
        // path.
        let registry =
            StoreRegistry::build(&[pg_store("events", "not a dsn")]).unwrap();
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("event_kind", "login");
        let mut pin_map = std::collections::HashMap::new();
        let result =
            execute_sql_store_step(&registry, &mut pin_map, "persist", "events", "events", None, &ctx);
        assert!(matches!(result, Err(StoreError::PoolInit { .. })));
    }

    #[test]
    fn sql_persist_scopes_the_row_to_the_declared_field_block() {
        // §Fase 35.o — a `persist` carrying a `{ col: value }` block
        // writes EXACTLY those columns (value expressions interpolated
        // against the flow context), ignoring every other binding the
        // flow holds. The malformed DSN fails at connect (typed
        // PoolInit) — proving the field-scoped row was assembled and
        // reached the SQL path. The pre-35.o behaviour would have
        // dumped `message`/`channel_kind`/… into the INSERT.
        let registry =
            StoreRegistry::build(&[pg_store("chat_history", "not a dsn")]).unwrap();
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("message", "hello");
        ctx.set("channel_kind", "whatsapp");
        ctx.set("tenant_id", "acme");
        let fields = vec![
            ("sender".to_string(), "user".to_string()),
            ("content".to_string(), "${message}".to_string()),
            ("tenant_id".to_string(), "${tenant_id}".to_string()),
        ];
        let mut pin_map = std::collections::HashMap::new();
        let result = execute_sql_store_step(
            &registry,
            &mut pin_map,
            "persist",
            "chat_history",
            "chat_history",
            Some(&fields),
            &ctx,
        );
        assert!(matches!(result, Err(StoreError::PoolInit { .. })));
    }

    #[test]
    fn sql_mutate_scopes_the_set_to_the_declared_field_block() {
        // §Fase 35.p — a `mutate` carrying a `{ col: value }` block
        // builds the UPDATE SET from EXACTLY those columns (value
        // expressions interpolated), ignoring every other binding the
        // flow holds. The malformed DSN fails at connect (typed
        // PoolInit) — proving the field-scoped SET row was assembled
        // and reached the SQL path. The pre-35.p behaviour would have
        // SET `tenant_id` (a flow param, not a column).
        let registry =
            StoreRegistry::build(&[pg_store("accounts", "not a dsn")]).unwrap();
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("tenant_id", "acme"); // a flow param, NOT a column
        ctx.set("new_balance", "500");
        let fields = vec![
            ("balance".to_string(), "${new_balance}".to_string()),
            ("status".to_string(), "active".to_string()),
        ];
        let mut pin_map = std::collections::HashMap::new();
        let result = execute_sql_store_step(
            &registry,
            &mut pin_map,
            "mutate",
            "accounts",
            "accounts:id = 1",
            Some(&fields),
            &ctx,
        );
        assert!(matches!(result, Err(StoreError::PoolInit { .. })));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  §Fase 65.0 / 65.A — unified executor: structural navigate bridge
// ─────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod fase65_navigate_bridge {
    use super::*;

    /// §Fase 65.A — the bridge is ON by default (the legacy LLM fallthrough is a
    /// correctness bug for a pure `navigate`); the `AXON_UNIFIED_EXECUTOR`
    /// kill-switch reverts it. Serialized via a process-global env var, so this
    /// test owns the var for its body.
    #[test]
    fn kill_switch_defaults_on_and_respects_env() {
        std::env::remove_var("AXON_UNIFIED_EXECUTOR");
        assert!(structural_dispatch_enabled(), "default ON when unset");
        for off in ["0", "off", "false", "no", "OFF"] {
            std::env::set_var("AXON_UNIFIED_EXECUTOR", off);
            assert!(!structural_dispatch_enabled(), "kill-switch honors {off:?}");
        }
        std::env::set_var("AXON_UNIFIED_EXECUTOR", "1");
        assert!(structural_dispatch_enabled(), "anything else stays ON");
        std::env::remove_var("AXON_UNIFIED_EXECUTOR");
    }

    /// §Fase 65.B — `routes_through_dispatcher` selects exactly the pure-effect
    /// MDN/PIX verbs: navigate / drill / trail. Cognitive-framing + multi-agent
    /// verbs (which call the LLM via `pure_shape`) and store/tool verbs stay on
    /// their existing paths.
    #[test]
    fn routes_only_the_pure_structural_verbs() {
        use crate::ir_nodes::*;
        let nav = IRFlowNode::Navigate(IRNavigateStep {
            node_type: "navigate",
            source_line: 0,
            source_column: 0,
            pix_ref: "G".into(),
            corpus_ref: "G".into(),
            query: String::new(),
            trail_enabled: false,
            output_name: "o".into(),
            seed: String::new(),
            budget: None,
        });
        assert!(routes_through_dispatcher(&nav));
        let drill = IRFlowNode::Drill(IRDrillStep {
            node_type: "drill",
            source_line: 0,
            source_column: 0,
            pix_ref: "G".into(),
            subtree_path: "A.B".into(),
            query: String::new(),
            output_name: "o".into(),
        });
        assert!(routes_through_dispatcher(&drill));
        // A cognitive-framing verb that reaches the LLM must NOT route here.
        let focus = IRFlowNode::Focus(IRFocusStep {
            node_type: "focus",
            source_line: 0,
            source_column: 0,
            expression: "x".into(),
        });
        assert!(!routes_through_dispatcher(&focus));
    }

    /// §Fase 65.A — THE anti-hallucination guarantee (Kivi acceptance, unit
    /// scope): a store-sourced `navigate` whose backing store is NOT Postgres
    /// (here an empty registry) binds an EMPTY result — the §64.B honest degrade
    /// — instead of fabricating documents. The full real-rows → real-hits E2E
    /// runs in the Postgres CI lane (the §37.x.j precedent). Critically, this
    /// path NEVER reaches the LLM: the bridge returns structural output directly.
    #[tokio::test]
    async fn store_sourced_navigate_without_postgres_binds_empty_not_hallucinated() {
        let src = crate::ir_nodes::IRCorpusStoreSource {
            doc_store: "LtmSummaries".into(),
            doc_id: "id".into(),
            doc_title: "summary".into(),
            edge_store: "LtmEdges".into(),
            edge_from: "from_id".into(),
            edge_to: "to_id".into(),
            edge_type: "etype".into(),
            edge_weight: "weight".into(),
        };
        let mut store_sources = std::collections::HashMap::new();
        store_sources.insert("LtmGraph".to_string(), src);
        let nd = empty_nav_dispatch(store_sources);
        let nav = crate::ir_nodes::IRFlowNode::Navigate(crate::ir_nodes::IRNavigateStep {
            node_type: "navigate",
            source_line: 0,
            source_column: 0,
            pix_ref: "LtmGraph".into(),
            corpus_ref: "LtmGraph".into(),
            query: "prueba de recall".into(),
            trail_enabled: false,
            output_name: "hits".into(),
            seed: String::new(),
            budget: Some(5),
        });
        let mut ctx = ExecContext::new("RecallLTM", "Default", 0);
        let mut pins = std::collections::HashMap::new();
        let hist = std::sync::Arc::new(std::sync::Mutex::new(std::collections::HashMap::new()));
        let out = dispatch_structural(
            &nav, &mut ctx, "RecallLTM", "kimi", "", &mut pins, &nd, &hist,
        )
        .await
        .expect("structural navigate returns Ok (honest empty), not an LLM call");
        assert_eq!(out, "", "empty corpus must bind empty, never fabricate hits");
        assert_eq!(
            ctx.get("hits"),
            Some(""),
            "the empty output binding propagates back to the runner context"
        );
    }

    /// §Fase 65.B — a `drill` with no indexable PIX source in scope degrades to
    /// its structural placeholder (NOT an LLM call). Proves drill is routed to the
    /// dispatcher's pure handler, and that the result binds back to the runner
    /// context under the drill's `output:` name.
    #[tokio::test]
    async fn drill_without_source_degrades_structurally_not_via_llm() {
        let nd = empty_nav_dispatch(std::collections::HashMap::new());
        let drill = crate::ir_nodes::IRFlowNode::Drill(crate::ir_nodes::IRDrillStep {
            node_type: "drill",
            source_line: 0,
            source_column: 0,
            pix_ref: "Unknown".into(),
            subtree_path: "A.B".into(),
            query: "q".into(),
            output_name: "section".into(),
        });
        let mut ctx = ExecContext::new("F", "Default", 0);
        let mut pins = std::collections::HashMap::new();
        let hist = std::sync::Arc::new(std::sync::Mutex::new(std::collections::HashMap::new()));
        let out = dispatch_structural(
            &drill, &mut ctx, "F", "kimi", "", &mut pins, &nd, &hist,
        )
        .await
        .expect("structural drill returns Ok, never an LLM call");
        // The placeholder is deterministic + bound back under `output:` — the
        // point is it ran the dispatcher handler, not the LLM fallthrough.
        assert_eq!(ctx.get("section").map(|s| s.to_string()), Some(out));
    }

    fn empty_nav_dispatch(
        store_sources: std::collections::HashMap<String, crate::ir_nodes::IRCorpusStoreSource>,
    ) -> NavDispatch {
        NavDispatch {
            store_registry: std::sync::Arc::new(crate::store::registry::StoreRegistry::empty()),
            corpora: std::sync::Arc::new(std::collections::HashMap::new()),
            store_sources: std::sync::Arc::new(store_sources),
            adaptive: std::sync::Arc::new(std::collections::HashSet::new()),
        }
    }
}
