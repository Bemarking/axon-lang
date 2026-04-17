//! Execution Replay — reconstruct and analyze recorded traces.
//!
//! Reads `.trace.json` files (produced by `axon run --trace`) and provides:
//!   - Structured timeline reconstruction
//!   - Per-step result extraction
//!   - Anchor pass/breach summary
//!   - Regression comparison between two traces
//!
//! Usage:
//!   axon replay trace.json                   — replay a single trace
//!   axon replay trace.json --json            — structured JSON output
//!   axon replay old.trace.json new.trace.json — regression comparison
//!
//! Exit codes:
//!   0 — replay successful (or traces match for regression)
//!   1 — regression differences detected
//!   2 — I/O or parse error

use std::collections::HashMap;
use std::io::IsTerminal;

// ── Replay structures ────────────────────────────────────────────────────

/// A reconstructed execution from a trace file.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplayTrace {
    pub meta: TraceMeta,
    pub units: Vec<ReplayUnit>,
    pub summary: ReplaySummary,
}

/// Trace metadata from the _meta header.
#[derive(Debug, Clone, serde::Serialize)]
pub struct TraceMeta {
    pub source: String,
    pub backend: String,
    pub tool_mode: String,
    pub axon_version: String,
    pub mode: String,
}

/// A reconstructed execution unit.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplayUnit {
    pub flow_name: String,
    pub steps: Vec<ReplayStep>,
    pub duration_ms: u64,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub anchor_breaches: u32,
}

/// A reconstructed step from trace events.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplayStep {
    pub name: String,
    pub event_type: String,
    pub output: String,
    pub success: bool,
    pub anchor_results: Vec<AnchorEvent>,
    pub was_retried: bool,
}

/// Anchor pass/breach event.
#[derive(Debug, Clone, serde::Serialize)]
pub struct AnchorEvent {
    pub anchor_name: String,
    pub passed: bool,
    pub detail: String,
}

/// Summary of a replayed trace.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplaySummary {
    pub total_units: usize,
    pub total_steps: usize,
    pub total_anchor_passes: usize,
    pub total_anchor_breaches: usize,
    pub total_retries: usize,
    pub total_errors: usize,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
}

/// Regression diff between two replayed traces.
#[derive(Debug, Clone, serde::Serialize)]
pub struct RegressionDiff {
    pub identical: bool,
    pub step_diffs: Vec<StepRegression>,
    pub summary: RegressionSummary,
}

/// Regression diff for a single step.
#[derive(Debug, Clone, serde::Serialize)]
pub struct StepRegression {
    pub unit: String,
    pub step: String,
    pub status: RegressionStatus,
    pub old_output: String,
    pub new_output: String,
}

/// Regression status for a step.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RegressionStatus {
    /// Output matches.
    Match,
    /// Output differs.
    Changed,
    /// Step only in old trace.
    Removed,
    /// Step only in new trace.
    Added,
}

/// Summary of regression comparison.
#[derive(Debug, Clone, serde::Serialize)]
pub struct RegressionSummary {
    pub total_steps: usize,
    pub matched: usize,
    pub changed: usize,
    pub added: usize,
    pub removed: usize,
}

// ── Trace parsing ────────────────────────────────────────────────────────

/// Parse a trace JSON value into a structured ReplayTrace.
pub fn parse_trace(data: &serde_json::Value) -> ReplayTrace {
    let meta = parse_meta(data);
    let events = data["events"]
        .as_array()
        .cloned()
        .unwrap_or_default();

    let units = reconstruct_units(&events);

    let mut summary = ReplaySummary {
        total_units: units.len(),
        total_steps: 0,
        total_anchor_passes: 0,
        total_anchor_breaches: 0,
        total_retries: 0,
        total_errors: 0,
        total_input_tokens: 0,
        total_output_tokens: 0,
    };

    for u in &units {
        summary.total_steps += u.steps.len();
        summary.total_input_tokens += u.total_input_tokens;
        summary.total_output_tokens += u.total_output_tokens;
        summary.total_anchor_breaches += u.anchor_breaches as usize;
        for s in &u.steps {
            summary.total_anchor_passes += s.anchor_results.iter().filter(|a| a.passed).count();
            summary.total_anchor_breaches += s.anchor_results.iter().filter(|a| !a.passed).count();
            if s.was_retried {
                summary.total_retries += 1;
            }
            if !s.success {
                summary.total_errors += 1;
            }
        }
    }

    ReplayTrace {
        meta,
        units,
        summary,
    }
}

fn parse_meta(data: &serde_json::Value) -> TraceMeta {
    let meta = &data["_meta"];
    TraceMeta {
        source: meta["source"].as_str().unwrap_or("").to_string(),
        backend: meta["backend"].as_str().unwrap_or("").to_string(),
        tool_mode: meta["tool_mode"].as_str().unwrap_or("").to_string(),
        axon_version: meta["axon_version"].as_str().unwrap_or("").to_string(),
        mode: meta["mode"].as_str().unwrap_or("").to_string(),
    }
}

fn reconstruct_units(events: &[serde_json::Value]) -> Vec<ReplayUnit> {
    let mut units: Vec<ReplayUnit> = Vec::new();
    let mut current_unit: Option<ReplayUnit> = None;
    let mut current_step_anchors: Vec<AnchorEvent> = Vec::new();
    let mut current_step_retried = false;

    for event in events {
        let etype = event["event"]
            .as_str()
            .or_else(|| event["type"].as_str())
            .unwrap_or("");
        let unit_name = event["unit"].as_str().unwrap_or("");
        let step_name = event["step"].as_str().unwrap_or("");
        let detail = event["detail"].as_str().unwrap_or("");

        match etype {
            "unit_start" => {
                if let Some(u) = current_unit.take() {
                    units.push(u);
                }
                current_unit = Some(ReplayUnit {
                    flow_name: unit_name.to_string(),
                    steps: Vec::new(),
                    duration_ms: 0,
                    total_input_tokens: 0,
                    total_output_tokens: 0,
                    anchor_breaches: 0,
                });
                current_step_anchors.clear();
                current_step_retried = false;
            }
            "unit_complete" => {
                if let Some(u) = current_unit.take() {
                    units.push(u);
                }
            }
            "step_complete" | "step_stub" | "tool_native" | "step_parallel" => {
                if let Some(ref mut u) = current_unit {
                    let success = etype != "step_error";
                    u.steps.push(ReplayStep {
                        name: step_name.to_string(),
                        event_type: etype.to_string(),
                        output: detail.to_string(),
                        success,
                        anchor_results: std::mem::take(&mut current_step_anchors),
                        was_retried: current_step_retried,
                    });
                    current_step_retried = false;
                }
            }
            "step_error" => {
                if let Some(ref mut u) = current_unit {
                    u.steps.push(ReplayStep {
                        name: step_name.to_string(),
                        event_type: etype.to_string(),
                        output: detail.to_string(),
                        success: false,
                        anchor_results: std::mem::take(&mut current_step_anchors),
                        was_retried: current_step_retried,
                    });
                    current_step_retried = false;
                }
            }
            "anchor_pass" => {
                current_step_anchors.push(AnchorEvent {
                    anchor_name: extract_anchor_name(detail),
                    passed: true,
                    detail: detail.to_string(),
                });
            }
            "anchor_breach" => {
                current_step_anchors.push(AnchorEvent {
                    anchor_name: extract_anchor_name(detail),
                    passed: false,
                    detail: detail.to_string(),
                });
                if let Some(ref mut u) = current_unit {
                    u.anchor_breaches += 1;
                }
            }
            "retry_attempt" => {
                current_step_retried = true;
            }
            "hook_unit_metrics" => {
                if let Some(ref mut u) = current_unit.as_mut().or_else(|| units.last_mut()) {
                    // Parse: "duration=123ms, steps=2, tokens_in=500, tokens_out=200, ..."
                    for part in detail.split(", ") {
                        if let Some(val) = part.strip_prefix("duration=").and_then(|s| s.strip_suffix("ms")) {
                            u.duration_ms = val.parse().unwrap_or(0);
                        } else if let Some(val) = part.strip_prefix("tokens_in=") {
                            u.total_input_tokens = val.parse().unwrap_or(0);
                        } else if let Some(val) = part.strip_prefix("tokens_out=") {
                            u.total_output_tokens = val.parse().unwrap_or(0);
                        }
                    }
                }
            }
            // Session events create synthetic steps
            e if e.starts_with("session_") => {
                if let Some(ref mut u) = current_unit {
                    u.steps.push(ReplayStep {
                        name: step_name.to_string(),
                        event_type: etype.to_string(),
                        output: detail.to_string(),
                        success: true,
                        anchor_results: Vec::new(),
                        was_retried: false,
                    });
                }
            }
            _ => {} // wave_start, step_deps, schedule, etc. — metadata only
        }
    }

    // Push final unit if still open
    if let Some(u) = current_unit {
        units.push(u);
    }

    units
}

fn extract_anchor_name(detail: &str) -> String {
    // Format: "AnchorName: 0.95" or "AnchorName: 0.50, reason=..."
    detail.split(':').next().unwrap_or("").trim().to_string()
}

// ── Regression comparison ────────────────────────────────────────────────

/// Compare two replayed traces for regression testing.
pub fn compare_traces(old: &ReplayTrace, new: &ReplayTrace) -> RegressionDiff {
    let mut step_diffs = Vec::new();

    // Build step output maps: (unit, step) → output
    let old_map = build_step_map(old);
    let new_map = build_step_map(new);

    let mut all_keys: Vec<(String, String)> = old_map
        .keys()
        .chain(new_map.keys())
        .cloned()
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();
    all_keys.sort();

    for key in &all_keys {
        let old_val = old_map.get(key);
        let new_val = new_map.get(key);

        let (status, old_output, new_output) = match (old_val, new_val) {
            (Some(o), Some(n)) => {
                if o == n {
                    (RegressionStatus::Match, o.clone(), n.clone())
                } else {
                    (RegressionStatus::Changed, o.clone(), n.clone())
                }
            }
            (Some(o), None) => (RegressionStatus::Removed, o.clone(), String::new()),
            (None, Some(n)) => (RegressionStatus::Added, String::new(), n.clone()),
            (None, None) => continue,
        };

        step_diffs.push(StepRegression {
            unit: key.0.clone(),
            step: key.1.clone(),
            status,
            old_output,
            new_output,
        });
    }

    let matched = step_diffs.iter().filter(|d| d.status == RegressionStatus::Match).count();
    let changed = step_diffs.iter().filter(|d| d.status == RegressionStatus::Changed).count();
    let added = step_diffs.iter().filter(|d| d.status == RegressionStatus::Added).count();
    let removed = step_diffs.iter().filter(|d| d.status == RegressionStatus::Removed).count();
    let identical = changed == 0 && added == 0 && removed == 0;
    let total_steps = step_diffs.len();

    RegressionDiff {
        identical,
        step_diffs,
        summary: RegressionSummary {
            total_steps,
            matched,
            changed,
            added,
            removed,
        },
    }
}

fn build_step_map(trace: &ReplayTrace) -> HashMap<(String, String), String> {
    let mut map = HashMap::new();
    for u in &trace.units {
        for s in &u.steps {
            map.insert(
                (u.flow_name.clone(), s.name.clone()),
                s.output.clone(),
            );
        }
    }
    map
}

// ── CLI entry point ──────────────────────────────────────────────────────

/// Run the replay command. Returns exit code.
pub fn run_replay(file: &str, compare_file: Option<&str>, json_output: bool) -> i32 {
    let use_color = !json_output && std::io::stdout().is_terminal();

    // Read primary trace
    let content = match std::fs::read_to_string(file) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Cannot read '{}': {e}", file);
            return 2;
        }
    };
    let data: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("Invalid JSON in '{}': {e}", file);
            return 2;
        }
    };

    let trace = parse_trace(&data);

    // If comparison file provided, do regression
    if let Some(cmp_file) = compare_file {
        let cmp_content = match std::fs::read_to_string(cmp_file) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("Cannot read '{}': {e}", cmp_file);
                return 2;
            }
        };
        let cmp_data: serde_json::Value = match serde_json::from_str(&cmp_content) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("Invalid JSON in '{}': {e}", cmp_file);
                return 2;
            }
        };

        let cmp_trace = parse_trace(&cmp_data);
        let regression = compare_traces(&trace, &cmp_trace);

        if json_output {
            println!("{}", serde_json::to_string_pretty(&regression).unwrap());
        } else {
            print_regression(&regression, file, cmp_file, use_color);
        }

        return if regression.identical { 0 } else { 1 };
    }

    // Single trace replay
    if json_output {
        println!("{}", serde_json::to_string_pretty(&trace).unwrap());
    } else {
        print_replay(&trace, file, use_color);
    }

    0
}

// ── Human-readable output ────────────────────────────────────────────────

fn print_replay(trace: &ReplayTrace, file: &str, use_color: bool) {
    let bold = |s: &str| if use_color { format!("\x1b[1m{s}\x1b[0m") } else { s.to_string() };
    let dim = |s: &str| if use_color { format!("\x1b[2m{s}\x1b[0m") } else { s.to_string() };
    let green = |s: &str| if use_color { format!("\x1b[32m{s}\x1b[0m") } else { s.to_string() };
    let red = |s: &str| if use_color { format!("\x1b[31m{s}\x1b[0m") } else { s.to_string() };
    let cyan = |s: &str| if use_color { format!("\x1b[36m{s}\x1b[0m") } else { s.to_string() };
    let yellow = |s: &str| if use_color { format!("\x1b[33m{s}\x1b[0m") } else { s.to_string() };

    println!("{} {}", bold("Replay:"), dim(file));
    println!(
        "  {} source={}, backend={}, mode={}",
        dim("meta:"),
        trace.meta.source,
        trace.meta.backend,
        trace.meta.mode,
    );

    for u in &trace.units {
        println!(
            "\n  {} {} ({} steps, {}ms)",
            cyan("▶"),
            bold(&u.flow_name),
            u.steps.len(),
            u.duration_ms,
        );

        for (i, s) in u.steps.iter().enumerate() {
            let icon = if s.success { green("✓") } else { red("✗") };
            let truncated = truncate_line(&s.output, 80);
            println!(
                "    {} {}.{} [{}] → {}",
                icon,
                i + 1,
                bold(&s.name),
                s.event_type,
                truncated,
            );

            for a in &s.anchor_results {
                let a_icon = if a.passed { green("⚓") } else { red("⚓") };
                println!("      {} {}", a_icon, a.detail);
            }

            if s.was_retried {
                println!("      {} retried", yellow("↻"));
            }
        }
    }

    // Summary
    let s = &trace.summary;
    println!(
        "\n  {} {} units, {} steps, {} passes, {} breaches, {} retries, {} errors",
        bold("Summary:"),
        s.total_units,
        s.total_steps,
        s.total_anchor_passes,
        s.total_anchor_breaches,
        s.total_retries,
        s.total_errors,
    );
    if s.total_input_tokens > 0 || s.total_output_tokens > 0 {
        println!(
            "  {} {} input + {} output tokens",
            dim("Tokens:"),
            s.total_input_tokens,
            s.total_output_tokens,
        );
    }
}

fn print_regression(diff: &RegressionDiff, file_a: &str, file_b: &str, use_color: bool) {
    let bold = |s: &str| if use_color { format!("\x1b[1m{s}\x1b[0m") } else { s.to_string() };
    let dim = |s: &str| if use_color { format!("\x1b[2m{s}\x1b[0m") } else { s.to_string() };
    let green = |s: &str| if use_color { format!("\x1b[1;32m{s}\x1b[0m") } else { s.to_string() };
    let red = |s: &str| if use_color { format!("\x1b[1;31m{s}\x1b[0m") } else { s.to_string() };
    let yellow = |s: &str| if use_color { format!("\x1b[1;33m{s}\x1b[0m") } else { s.to_string() };

    println!(
        "{} {} → {}",
        bold("Regression:"),
        dim(file_a),
        dim(file_b),
    );

    if diff.identical {
        println!("  {} Traces match — no regressions.", green("✓"));
        return;
    }

    let s = &diff.summary;
    println!(
        "  {} {}/{} steps match, {} changed, {} added, {} removed",
        yellow("!"),
        s.matched,
        s.total_steps,
        s.changed,
        s.added,
        s.removed,
    );

    for d in &diff.step_diffs {
        match d.status {
            RegressionStatus::Match => {} // skip
            RegressionStatus::Changed => {
                println!(
                    "\n  {} {}.{} — output changed",
                    yellow("~"),
                    d.unit,
                    bold(&d.step),
                );
                println!("    {} {}", red("-"), truncate_line(&d.old_output, 80));
                println!("    {} {}", green("+"), truncate_line(&d.new_output, 80));
            }
            RegressionStatus::Added => {
                println!(
                    "  {} {}.{} — new step",
                    green("+"),
                    d.unit,
                    bold(&d.step),
                );
            }
            RegressionStatus::Removed => {
                println!(
                    "  {} {}.{} — step removed",
                    red("-"),
                    d.unit,
                    bold(&d.step),
                );
            }
        }
    }
}

fn truncate_line(s: &str, max: usize) -> String {
    let line = s.lines().next().unwrap_or(s);
    if line.len() > max {
        format!("{}...", &line[..max])
    } else {
        line.to_string()
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_trace() -> serde_json::Value {
        json!({
            "_meta": {
                "source": "test.axon",
                "backend": "anthropic",
                "tool_mode": "stub",
                "axon_version": "1.0.0",
                "mode": "stub",
            },
            "events": [
                { "event": "unit_start", "unit": "Flow1", "step": "", "detail": "persona=P1, context=default" },
                { "event": "anchor_pass", "unit": "Flow1", "step": "S1", "detail": "NoHallucination: 0.95" },
                { "event": "step_complete", "unit": "Flow1", "step": "S1", "detail": "result of S1" },
                { "event": "anchor_breach", "unit": "Flow1", "step": "S2", "detail": "FactualOnly: 0.30, reason=opinion detected" },
                { "event": "step_complete", "unit": "Flow1", "step": "S2", "detail": "result of S2" },
                { "event": "unit_complete", "unit": "Flow1", "step": "", "detail": "2 steps, 4 conversation turns" },
            ]
        })
    }

    #[test]
    fn parse_meta() {
        let data = sample_trace();
        let trace = parse_trace(&data);
        assert_eq!(trace.meta.source, "test.axon");
        assert_eq!(trace.meta.backend, "anthropic");
        assert_eq!(trace.meta.mode, "stub");
    }

    #[test]
    fn parse_units_and_steps() {
        let data = sample_trace();
        let trace = parse_trace(&data);
        assert_eq!(trace.units.len(), 1);
        assert_eq!(trace.units[0].flow_name, "Flow1");
        assert_eq!(trace.units[0].steps.len(), 2);
        assert_eq!(trace.units[0].steps[0].name, "S1");
        assert_eq!(trace.units[0].steps[0].output, "result of S1");
        assert!(trace.units[0].steps[0].success);
        assert_eq!(trace.units[0].steps[1].name, "S2");
    }

    #[test]
    fn parse_anchor_events() {
        let data = sample_trace();
        let trace = parse_trace(&data);

        // S1 has an anchor pass
        assert_eq!(trace.units[0].steps[0].anchor_results.len(), 1);
        assert!(trace.units[0].steps[0].anchor_results[0].passed);
        assert_eq!(trace.units[0].steps[0].anchor_results[0].anchor_name, "NoHallucination");

        // S2 has an anchor breach
        assert_eq!(trace.units[0].steps[1].anchor_results.len(), 1);
        assert!(!trace.units[0].steps[1].anchor_results[0].passed);
        assert_eq!(trace.units[0].steps[1].anchor_results[0].anchor_name, "FactualOnly");
    }

    #[test]
    fn parse_summary() {
        let data = sample_trace();
        let trace = parse_trace(&data);
        assert_eq!(trace.summary.total_units, 1);
        assert_eq!(trace.summary.total_steps, 2);
        assert_eq!(trace.summary.total_anchor_passes, 1);
        // Breaches counted from both unit level and step level
        assert!(trace.summary.total_anchor_breaches >= 1);
    }

    #[test]
    fn parse_tool_events() {
        let data = json!({
            "_meta": { "source": "t.axon", "backend": "anthropic", "tool_mode": "stub", "axon_version": "1.0.0", "mode": "stub" },
            "events": [
                { "event": "unit_start", "unit": "F", "step": "", "detail": "" },
                { "event": "tool_native", "unit": "F", "step": "CalcStep", "detail": "tool=Calculator, success=true, output=42" },
                { "event": "unit_complete", "unit": "F", "step": "", "detail": "" },
            ]
        });

        let trace = parse_trace(&data);
        assert_eq!(trace.units[0].steps.len(), 1);
        assert_eq!(trace.units[0].steps[0].name, "CalcStep");
        assert_eq!(trace.units[0].steps[0].event_type, "tool_native");
        assert!(trace.units[0].steps[0].success);
    }

    #[test]
    fn parse_retry_events() {
        let data = json!({
            "_meta": { "source": "t.axon", "backend": "anthropic", "tool_mode": "real", "axon_version": "1.0.0", "mode": "real" },
            "events": [
                { "event": "unit_start", "unit": "F", "step": "", "detail": "" },
                { "event": "retry_attempt", "unit": "F", "step": "S1", "detail": "attempt=1/2" },
                { "event": "step_complete", "unit": "F", "step": "S1", "detail": "retry succeeded" },
                { "event": "unit_complete", "unit": "F", "step": "", "detail": "" },
            ]
        });

        let trace = parse_trace(&data);
        assert!(trace.units[0].steps[0].was_retried);
        assert_eq!(trace.summary.total_retries, 1);
    }

    #[test]
    fn parse_error_step() {
        let data = json!({
            "_meta": { "source": "t.axon", "backend": "anthropic", "tool_mode": "real", "axon_version": "1.0.0", "mode": "real" },
            "events": [
                { "event": "unit_start", "unit": "F", "step": "", "detail": "" },
                { "event": "step_error", "unit": "F", "step": "Bad", "detail": "connection failed" },
                { "event": "unit_complete", "unit": "F", "step": "", "detail": "" },
            ]
        });

        let trace = parse_trace(&data);
        assert!(!trace.units[0].steps[0].success);
        assert_eq!(trace.summary.total_errors, 1);
    }

    #[test]
    fn parse_hook_metrics() {
        let data = json!({
            "_meta": { "source": "t.axon", "backend": "anthropic", "tool_mode": "real", "axon_version": "1.0.0", "mode": "real" },
            "events": [
                { "event": "unit_start", "unit": "F", "step": "", "detail": "" },
                { "event": "step_complete", "unit": "F", "step": "S", "detail": "ok" },
                { "event": "unit_complete", "unit": "F", "step": "", "detail": "" },
                { "event": "hook_unit_metrics", "unit": "F", "step": "", "detail": "duration=250ms, steps=1, tokens_in=100, tokens_out=50, breaches=0, chains=0" },
            ]
        });

        let trace = parse_trace(&data);
        assert_eq!(trace.units[0].duration_ms, 250);
        assert_eq!(trace.units[0].total_input_tokens, 100);
        assert_eq!(trace.units[0].total_output_tokens, 50);
    }

    #[test]
    fn regression_identical() {
        let data = sample_trace();
        let trace = parse_trace(&data);
        let diff = compare_traces(&trace, &trace);
        assert!(diff.identical);
        assert_eq!(diff.summary.matched, 2);
        assert_eq!(diff.summary.changed, 0);
    }

    #[test]
    fn regression_changed_output() {
        let data_old = sample_trace();
        let mut data_new = sample_trace();
        // events[2] is step_complete for S1
        data_new["events"][2]["detail"] = json!("different result");

        let old = parse_trace(&data_old);
        let new = parse_trace(&data_new);
        let diff = compare_traces(&old, &new);

        assert!(!diff.identical);
        assert_eq!(diff.summary.changed, 1);
        assert_eq!(diff.summary.matched, 1);
    }

    #[test]
    fn regression_added_step() {
        let data_old = sample_trace();
        let mut data_new = sample_trace();
        // Add a new step
        data_new["events"].as_array_mut().unwrap().insert(3, json!(
            { "event": "step_complete", "unit": "Flow1", "step": "S3", "detail": "new step" }
        ));

        let old = parse_trace(&data_old);
        let new = parse_trace(&data_new);
        let diff = compare_traces(&old, &new);

        assert!(!diff.identical);
        assert_eq!(diff.summary.added, 1);
    }

    #[test]
    fn run_replay_file_not_found() {
        assert_eq!(run_replay("nonexistent.trace.json", None, false), 2);
    }

    #[test]
    fn run_replay_single_trace() {
        let tmp = std::env::temp_dir().join("axon_replay_test.trace.json");
        let data = sample_trace();
        std::fs::write(&tmp, serde_json::to_string(&data).unwrap()).unwrap();

        assert_eq!(run_replay(tmp.to_str().unwrap(), None, true), 0);
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn run_replay_regression_identical() {
        let tmp = std::env::temp_dir().join("axon_replay_reg.trace.json");
        let data = sample_trace();
        std::fs::write(&tmp, serde_json::to_string(&data).unwrap()).unwrap();

        let path = tmp.to_str().unwrap();
        assert_eq!(run_replay(path, Some(path), true), 0);
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn run_replay_regression_different() {
        let tmp_a = std::env::temp_dir().join("axon_replay_a.trace.json");
        let tmp_b = std::env::temp_dir().join("axon_replay_b.trace.json");

        let data_a = sample_trace();
        let mut data_b = sample_trace();
        // events[2] is step_complete for S1
        data_b["events"][2]["detail"] = json!("changed output");

        std::fs::write(&tmp_a, serde_json::to_string(&data_a).unwrap()).unwrap();
        std::fs::write(&tmp_b, serde_json::to_string(&data_b).unwrap()).unwrap();

        assert_eq!(
            run_replay(tmp_a.to_str().unwrap(), Some(tmp_b.to_str().unwrap()), true),
            1,
        );

        let _ = std::fs::remove_file(tmp_a);
        let _ = std::fs::remove_file(tmp_b);
    }

    #[test]
    fn regression_status_serializes() {
        assert_eq!(serde_json::to_string(&RegressionStatus::Match).unwrap(), "\"match\"");
        assert_eq!(serde_json::to_string(&RegressionStatus::Changed).unwrap(), "\"changed\"");
        assert_eq!(serde_json::to_string(&RegressionStatus::Added).unwrap(), "\"added\"");
    }

    #[test]
    fn empty_trace() {
        let data = json!({ "_meta": {}, "events": [] });
        let trace = parse_trace(&data);
        assert_eq!(trace.units.len(), 0);
        assert_eq!(trace.summary.total_steps, 0);
    }
}
