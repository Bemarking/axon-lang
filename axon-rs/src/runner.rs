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
        let steps = build_compiled_steps(run);

        units.push(ExecutionUnit {
            flow_name: run.flow_name.clone(),
            persona_name: run.persona_name.clone(),
            context_name: run.context_name.clone(),
            system_prompt,
            steps,
            anchor_instructions,
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
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

fn build_compiled_steps(run: &IRRun) -> Vec<CompiledStep> {
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

        steps.push(CompiledStep {
            step_name,
            step_type,
            system_prompt,
            user_prompt,
            tool_argument,
            memory_expression,
        });
    }

    steps
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
        for (j, step) in unit.steps.iter().enumerate() {
            println!(
                "  {} {}.{} [{}] {}",
                c("→", "\x1b[32m", use_color),
                j + 1,
                c(&step.step_name, "\x1b[1m", use_color),
                step.step_type,
                &step.user_prompt
            );

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
    api_key_override: Option<&str>,
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
        let mut conversation = ConversationHistory::new();
        let mut context_window = ContextWindow::new();
        hooks.on_unit_start(&unit.flow_name, &unit.persona_name);
        report.begin_unit(&unit.flow_name, &unit.persona_name);

        // Step dependency analysis + parallel schedule
        let step_infos: Vec<step_deps::StepInfo> = unit.steps.iter().map(|s| {
            step_deps::StepInfo {
                name: s.step_name.clone(),
                step_type: s.step_type.clone(),
                user_prompt: s.user_prompt.clone(),
                argument: s.tool_argument.as_deref()
                    .or(s.memory_expression.as_deref())
                    .unwrap_or("")
                    .to_string(),
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
                        let raw_arg = step.tool_argument.as_deref().unwrap_or("");
                        let arg = ctx_snapshot.interpolate(raw_arg);
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
                let raw_arg = step.tool_argument.as_deref().unwrap_or("");
                let arg = ctx.interpolate(raw_arg);
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
        let step_infos: Vec<step_deps::StepInfo> = unit.steps.iter().map(|s| {
            step_deps::StepInfo {
                name: s.step_name.clone(),
                step_type: s.step_type.clone(),
                user_prompt: s.user_prompt.clone(),
                argument: s.tool_argument.as_deref()
                    .or(s.memory_expression.as_deref())
                    .unwrap_or("")
                    .to_string(),
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
}

pub fn execute_server_flow(
    ir: &crate::ir_nodes::IRProgram,
    flow_name: &str,
    backend: &str,
    source_file: &str,
    api_key_override: Option<&str>,
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
            steps: build_compiled_steps(run),
            anchor_instructions: build_anchor_instructions(run),
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
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
            steps: build_compiled_steps(&run),
            anchor_instructions: build_anchor_instructions(&run),
            effort: run.effort.clone(),
            resolved_anchors: run.resolved_anchors.clone(),
        });
    }

    let mut report = crate::output::ReportBuilder::new(source_file, backend, "json");
    let mut registry = crate::tool_registry::ToolRegistry::new();

    let (success, _events) = if backend == "stub" {
        execute_stub(&execution_units, false, false)
    } else {
        execute_real(
            &execution_units,
            backend,
            source_file,
            false,
            false,
            false,
            crate::output::OutputFormat::Json,
            &mut report,
            &registry,
            api_key_override,
        ).map_err(|e| format!("Backend error: {:?}", e))?
    };

    let hooks = crate::hooks::HookManager::new();
    let r = report.build(success, &hooks);
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

    Ok(ServerRunnerMetrics {
        success,
        steps_executed,
        tokens_input,
        tokens_output,
        anchor_breaches,
        step_names,
        step_results,
        per_step_chunks,
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
        Err(ParseError { message, line, column }) => {
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

    let (success, events) = if tool_mode == "real" {
        match execute_real(&units, backend, file, use_color, trace, stream, output_fmt, &mut report, &registry, None) {
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
