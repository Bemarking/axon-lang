//! Trace Analytics — aggregate statistics across multiple execution traces.
//!
//! Loads one or more `.trace.json` files and computes:
//!   - Latency percentiles (p50, p95, p99, mean, min, max)
//!   - Token usage (total, mean, per-unit, per-step)
//!   - Anchor breach rate and top breached anchors
//!   - Error rate and retry rate
//!   - Step frequency distribution
//!
//! Usage:
//!   axon stats trace1.json trace2.json ...   — aggregate stats
//!   axon stats *.trace.json --json           — structured JSON output
//!
//! Exit codes:
//!   0 — stats computed successfully
//!   2 — I/O or parse error

use std::collections::HashMap;
use std::io::IsTerminal;

use crate::replay;

// ── Analytics structures ────────────────────────────────────────────────

/// Aggregate analytics across one or more traces.
#[derive(Debug, Clone, serde::Serialize)]
pub struct TraceAnalytics {
    pub trace_count: usize,
    pub latency: LatencyStats,
    pub tokens: TokenStats,
    pub anchors: AnchorStats,
    pub errors: ErrorStats,
    pub steps: StepFrequency,
}

/// Latency statistics with percentiles.
#[derive(Debug, Clone, serde::Serialize)]
pub struct LatencyStats {
    pub unit_count: usize,
    pub p50_ms: u64,
    pub p95_ms: u64,
    pub p99_ms: u64,
    pub mean_ms: u64,
    pub min_ms: u64,
    pub max_ms: u64,
}

/// Token usage statistics.
#[derive(Debug, Clone, serde::Serialize)]
pub struct TokenStats {
    pub total_input: u64,
    pub total_output: u64,
    pub total: u64,
    pub mean_input_per_unit: u64,
    pub mean_output_per_unit: u64,
    pub mean_total_per_unit: u64,
    pub unit_count: usize,
}

/// Anchor pass/breach statistics.
#[derive(Debug, Clone, serde::Serialize)]
pub struct AnchorStats {
    pub total_checks: usize,
    pub total_passes: usize,
    pub total_breaches: usize,
    pub pass_rate: f64,
    pub breach_rate: f64,
    pub top_breaches: Vec<AnchorBreachEntry>,
}

/// A single anchor breach frequency entry.
#[derive(Debug, Clone, serde::Serialize)]
pub struct AnchorBreachEntry {
    pub anchor_name: String,
    pub breach_count: usize,
}

/// Error and retry statistics.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ErrorStats {
    pub total_steps: usize,
    pub total_errors: usize,
    pub total_retries: usize,
    pub error_rate: f64,
    pub retry_rate: f64,
}

/// Step name frequency distribution.
#[derive(Debug, Clone, serde::Serialize)]
pub struct StepFrequency {
    pub unique_steps: usize,
    pub top_steps: Vec<StepFreqEntry>,
}

/// A single step frequency entry.
#[derive(Debug, Clone, serde::Serialize)]
pub struct StepFreqEntry {
    pub step_name: String,
    pub count: usize,
}

// ── Computation ─────────────────────────────────────────────────────────

/// Compute aggregate analytics from a set of parsed traces.
pub fn compute_analytics(traces: &[replay::ReplayTrace]) -> TraceAnalytics {
    let mut durations: Vec<u64> = Vec::new();
    let mut total_input: u64 = 0;
    let mut total_output: u64 = 0;
    let mut total_passes: usize = 0;
    let mut total_breaches: usize = 0;
    let mut total_steps: usize = 0;
    let mut total_errors: usize = 0;
    let mut total_retries: usize = 0;
    let mut breach_counts: HashMap<String, usize> = HashMap::new();
    let mut step_counts: HashMap<String, usize> = HashMap::new();

    for trace in traces {
        for unit in &trace.units {
            durations.push(unit.duration_ms);
            total_input += unit.total_input_tokens;
            total_output += unit.total_output_tokens;

            for step in &unit.steps {
                total_steps += 1;
                *step_counts.entry(step.name.clone()).or_insert(0) += 1;

                if !step.success {
                    total_errors += 1;
                }
                if step.was_retried {
                    total_retries += 1;
                }

                for anchor in &step.anchor_results {
                    if anchor.passed {
                        total_passes += 1;
                    } else {
                        total_breaches += 1;
                        *breach_counts.entry(anchor.anchor_name.clone()).or_insert(0) += 1;
                    }
                }
            }
        }
    }

    let latency = compute_latency(&durations);
    let unit_count = durations.len();

    let tokens = TokenStats {
        total_input,
        total_output,
        total: total_input + total_output,
        mean_input_per_unit: if unit_count > 0 { total_input / unit_count as u64 } else { 0 },
        mean_output_per_unit: if unit_count > 0 { total_output / unit_count as u64 } else { 0 },
        mean_total_per_unit: if unit_count > 0 { (total_input + total_output) / unit_count as u64 } else { 0 },
        unit_count,
    };

    let total_checks = total_passes + total_breaches;
    let anchors = AnchorStats {
        total_checks,
        total_passes,
        total_breaches,
        pass_rate: if total_checks > 0 { total_passes as f64 / total_checks as f64 } else { 1.0 },
        breach_rate: if total_checks > 0 { total_breaches as f64 / total_checks as f64 } else { 0.0 },
        top_breaches: top_breaches(&breach_counts, 10),
    };

    let errors = ErrorStats {
        total_steps,
        total_errors,
        total_retries,
        error_rate: if total_steps > 0 { total_errors as f64 / total_steps as f64 } else { 0.0 },
        retry_rate: if total_steps > 0 { total_retries as f64 / total_steps as f64 } else { 0.0 },
    };

    let steps = compute_step_frequency(&step_counts, 10);

    TraceAnalytics {
        trace_count: traces.len(),
        latency,
        tokens,
        anchors,
        errors,
        steps,
    }
}

fn compute_latency(durations: &[u64]) -> LatencyStats {
    if durations.is_empty() {
        return LatencyStats {
            unit_count: 0,
            p50_ms: 0,
            p95_ms: 0,
            p99_ms: 0,
            mean_ms: 0,
            min_ms: 0,
            max_ms: 0,
        };
    }

    let mut sorted = durations.to_vec();
    sorted.sort();
    let n = sorted.len();

    LatencyStats {
        unit_count: n,
        p50_ms: percentile(&sorted, 50.0),
        p95_ms: percentile(&sorted, 95.0),
        p99_ms: percentile(&sorted, 99.0),
        mean_ms: sorted.iter().sum::<u64>() / n as u64,
        min_ms: sorted[0],
        max_ms: sorted[n - 1],
    }
}

/// Compute a percentile from a sorted slice using nearest-rank method.
fn percentile(sorted: &[u64], pct: f64) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let rank = (pct / 100.0 * sorted.len() as f64).ceil() as usize;
    let idx = rank.min(sorted.len()).saturating_sub(1);
    sorted[idx]
}

fn top_breaches(counts: &HashMap<String, usize>, limit: usize) -> Vec<AnchorBreachEntry> {
    let mut entries: Vec<AnchorBreachEntry> = counts
        .iter()
        .map(|(name, &count)| AnchorBreachEntry {
            anchor_name: name.clone(),
            breach_count: count,
        })
        .collect();
    entries.sort_by(|a, b| b.breach_count.cmp(&a.breach_count));
    entries.truncate(limit);
    entries
}

fn compute_step_frequency(counts: &HashMap<String, usize>, limit: usize) -> StepFrequency {
    let mut entries: Vec<StepFreqEntry> = counts
        .iter()
        .map(|(name, &count)| StepFreqEntry {
            step_name: name.clone(),
            count,
        })
        .collect();
    entries.sort_by(|a, b| b.count.cmp(&a.count));
    let unique_steps = entries.len();
    entries.truncate(limit);

    StepFrequency {
        unique_steps,
        top_steps: entries,
    }
}

// ── CLI entry point ─────────────────────────────────────────────────────

/// Load trace files and compute aggregate analytics.
/// Format: "text" (default), "json", "prometheus", "csv".
/// Returns exit code: 0 = success, 2 = error.
pub fn run_stats(files: &[String], format: &str) -> i32 {
    if files.is_empty() {
        eprintln!("error: no trace files provided");
        return 2;
    }

    let mut traces: Vec<replay::ReplayTrace> = Vec::new();
    let mut errors = 0;

    for path in files {
        match std::fs::read_to_string(path) {
            Ok(content) => {
                match serde_json::from_str::<serde_json::Value>(&content) {
                    Ok(data) => {
                        traces.push(replay::parse_trace(&data));
                    }
                    Err(e) => {
                        eprintln!("error: failed to parse {}: {}", path, e);
                        errors += 1;
                    }
                }
            }
            Err(e) => {
                eprintln!("error: failed to read {}: {}", path, e);
                errors += 1;
            }
        }
    }

    if traces.is_empty() {
        eprintln!("error: no valid traces loaded ({} errors)", errors);
        return 2;
    }

    let analytics = compute_analytics(&traces);

    match format {
        "json" => println!("{}", serde_json::to_string_pretty(&analytics).unwrap()),
        "prometheus" => print!("{}", crate::trace_export::to_prometheus(&analytics)),
        "csv" => print!("{}", crate::trace_export::to_csv(&analytics)),
        _ => print_analytics(&analytics, errors),
    }

    0
}

// ── Human-readable output ───────────────────────────────────────────────

fn print_analytics(a: &TraceAnalytics, load_errors: usize) {
    let use_color = std::io::stdout().is_terminal();

    let bold = if use_color { "\x1b[1m" } else { "" };
    let cyan = if use_color { "\x1b[36m" } else { "" };
    let yellow = if use_color { "\x1b[33m" } else { "" };
    let red = if use_color { "\x1b[31m" } else { "" };
    let green = if use_color { "\x1b[32m" } else { "" };
    let reset = if use_color { "\x1b[0m" } else { "" };

    println!("{}═══ AXON Trace Analytics ═══{}", bold, reset);
    println!();

    // Overview
    println!("{}Traces:{} {}", cyan, reset, a.trace_count);
    if load_errors > 0 {
        println!("{}Load errors:{} {}", red, reset, load_errors);
    }
    println!("{}Units:{} {}", cyan, reset, a.latency.unit_count);
    println!("{}Steps:{} {}", cyan, reset, a.errors.total_steps);
    println!();

    // Latency
    println!("{}── Latency ──{}", bold, reset);
    if a.latency.unit_count > 0 {
        println!("  p50:  {} ms", a.latency.p50_ms);
        println!("  p95:  {} ms", a.latency.p95_ms);
        println!("  p99:  {} ms", a.latency.p99_ms);
        println!("  mean: {} ms", a.latency.mean_ms);
        println!("  min:  {} ms", a.latency.min_ms);
        println!("  max:  {} ms", a.latency.max_ms);
    } else {
        println!("  (no latency data)");
    }
    println!();

    // Tokens
    println!("{}── Tokens ──{}", bold, reset);
    println!("  total input:    {}", a.tokens.total_input);
    println!("  total output:   {}", a.tokens.total_output);
    println!("  total:          {}", a.tokens.total);
    if a.tokens.unit_count > 0 {
        println!("  mean/unit:      {} in + {} out", a.tokens.mean_input_per_unit, a.tokens.mean_output_per_unit);
    }
    println!();

    // Anchors
    println!("{}── Anchors ──{}", bold, reset);
    if a.anchors.total_checks > 0 {
        println!("  checks:    {}", a.anchors.total_checks);
        println!("  {}passes:    {}{} ({:.1}%)", green, a.anchors.total_passes, reset, a.anchors.pass_rate * 100.0);
        println!("  {}breaches:  {}{} ({:.1}%)", red, a.anchors.total_breaches, reset, a.anchors.breach_rate * 100.0);
        if !a.anchors.top_breaches.is_empty() {
            println!("  top breaches:");
            for b in &a.anchors.top_breaches {
                println!("    {}× {}{}{}", b.breach_count, yellow, b.anchor_name, reset);
            }
        }
    } else {
        println!("  (no anchor data)");
    }
    println!();

    // Errors
    println!("{}── Errors ──{}", bold, reset);
    println!("  errors:  {} / {} steps ({:.1}%)", a.errors.total_errors, a.errors.total_steps, a.errors.error_rate * 100.0);
    println!("  retries: {} ({:.1}%)", a.errors.total_retries, a.errors.retry_rate * 100.0);
    println!();

    // Step frequency
    println!("{}── Step Frequency ──{}", bold, reset);
    println!("  unique steps: {}", a.steps.unique_steps);
    if !a.steps.top_steps.is_empty() {
        for s in &a.steps.top_steps {
            println!("    {}× {}", s.count, s.step_name);
        }
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::replay::{ReplayTrace, TraceMeta, ReplayUnit, ReplayStep, AnchorEvent, ReplaySummary};

    fn make_meta() -> TraceMeta {
        TraceMeta {
            source: "test.axon".into(),
            backend: "anthropic".into(),
            tool_mode: "stub".into(),
            axon_version: "0.30.6".into(),
            mode: "stub".into(),
        }
    }

    fn make_step(name: &str, success: bool, retried: bool, anchors: Vec<AnchorEvent>) -> ReplayStep {
        ReplayStep {
            name: name.into(),
            event_type: "step_complete".into(),
            output: format!("{} output", name),
            success,
            anchor_results: anchors,
            was_retried: retried,
        }
    }

    fn make_unit(flow: &str, duration_ms: u64, input_tokens: u64, output_tokens: u64, steps: Vec<ReplayStep>) -> ReplayUnit {
        ReplayUnit {
            flow_name: flow.into(),
            steps,
            duration_ms,
            total_input_tokens: input_tokens,
            total_output_tokens: output_tokens,
            anchor_breaches: 0,
        }
    }

    fn make_trace(units: Vec<ReplayUnit>) -> ReplayTrace {
        let total_steps = units.iter().map(|u| u.steps.len()).sum();
        let total_input: u64 = units.iter().map(|u| u.total_input_tokens).sum();
        let total_output: u64 = units.iter().map(|u| u.total_output_tokens).sum();
        ReplayTrace {
            meta: make_meta(),
            units,
            summary: ReplaySummary {
                total_units: 0,
                total_steps,
                total_anchor_passes: 0,
                total_anchor_breaches: 0,
                total_retries: 0,
                total_errors: 0,
                total_input_tokens: total_input,
                total_output_tokens: total_output,
            },
        }
    }

    fn anchor(name: &str, passed: bool) -> AnchorEvent {
        AnchorEvent { anchor_name: name.into(), passed, detail: String::new() }
    }

    #[test]
    fn percentile_basic() {
        // 10 values: 10,20,30,...,100
        let data: Vec<u64> = (1..=10).map(|x| x * 10).collect();
        assert_eq!(percentile(&data, 50.0), 50);
        assert_eq!(percentile(&data, 95.0), 100);
        assert_eq!(percentile(&data, 99.0), 100);
        assert_eq!(percentile(&data, 0.0), 10); // ceil(0) = 0, saturating_sub → 0 → first element
    }

    #[test]
    fn percentile_single_value() {
        assert_eq!(percentile(&[42], 50.0), 42);
        assert_eq!(percentile(&[42], 99.0), 42);
    }

    #[test]
    fn percentile_empty() {
        assert_eq!(percentile(&[], 50.0), 0);
    }

    #[test]
    fn latency_stats_computed() {
        let t1 = make_trace(vec![
            make_unit("F", 100, 0, 0, vec![make_step("S1", true, false, vec![])]),
            make_unit("F", 200, 0, 0, vec![make_step("S2", true, false, vec![])]),
        ]);
        let t2 = make_trace(vec![
            make_unit("F", 150, 0, 0, vec![make_step("S1", true, false, vec![])]),
        ]);

        let a = compute_analytics(&[t1, t2]);
        assert_eq!(a.latency.unit_count, 3);
        assert_eq!(a.latency.min_ms, 100);
        assert_eq!(a.latency.max_ms, 200);
        assert_eq!(a.latency.mean_ms, 150); // (100+200+150)/3
    }

    #[test]
    fn token_stats_aggregated() {
        let t = make_trace(vec![
            make_unit("F1", 0, 100, 50, vec![make_step("S", true, false, vec![])]),
            make_unit("F2", 0, 200, 80, vec![make_step("S", true, false, vec![])]),
        ]);

        let a = compute_analytics(&[t]);
        assert_eq!(a.tokens.total_input, 300);
        assert_eq!(a.tokens.total_output, 130);
        assert_eq!(a.tokens.total, 430);
        assert_eq!(a.tokens.mean_input_per_unit, 150);
        assert_eq!(a.tokens.mean_output_per_unit, 65);
        assert_eq!(a.tokens.unit_count, 2);
    }

    #[test]
    fn anchor_stats_computed() {
        let t = make_trace(vec![
            make_unit("F", 0, 0, 0, vec![
                make_step("S1", true, false, vec![
                    anchor("SafeOutput", true),
                    anchor("NoHallucination", false),
                ]),
                make_step("S2", true, false, vec![
                    anchor("SafeOutput", true),
                    anchor("NoHallucination", false),
                    anchor("FactualOnly", false),
                ]),
            ]),
        ]);

        let a = compute_analytics(&[t]);
        assert_eq!(a.anchors.total_checks, 5);
        assert_eq!(a.anchors.total_passes, 2);
        assert_eq!(a.anchors.total_breaches, 3);
        assert!((a.anchors.pass_rate - 0.4).abs() < 0.01);
        assert!((a.anchors.breach_rate - 0.6).abs() < 0.01);

        // Top breaches sorted by count
        assert_eq!(a.anchors.top_breaches.len(), 2);
        assert_eq!(a.anchors.top_breaches[0].anchor_name, "NoHallucination");
        assert_eq!(a.anchors.top_breaches[0].breach_count, 2);
        assert_eq!(a.anchors.top_breaches[1].anchor_name, "FactualOnly");
        assert_eq!(a.anchors.top_breaches[1].breach_count, 1);
    }

    #[test]
    fn error_and_retry_stats() {
        let t = make_trace(vec![
            make_unit("F", 0, 0, 0, vec![
                make_step("S1", true, false, vec![]),
                make_step("S2", false, true, vec![]),  // error + retried
                make_step("S3", true, true, vec![]),   // success but was retried
                make_step("S4", false, false, vec![]), // error, no retry
            ]),
        ]);

        let a = compute_analytics(&[t]);
        assert_eq!(a.errors.total_steps, 4);
        assert_eq!(a.errors.total_errors, 2);
        assert_eq!(a.errors.total_retries, 2);
        assert!((a.errors.error_rate - 0.5).abs() < 0.01);
        assert!((a.errors.retry_rate - 0.5).abs() < 0.01);
    }

    #[test]
    fn step_frequency_distribution() {
        let t = make_trace(vec![
            make_unit("F1", 0, 0, 0, vec![
                make_step("Analyze", true, false, vec![]),
                make_step("Summarize", true, false, vec![]),
            ]),
            make_unit("F2", 0, 0, 0, vec![
                make_step("Analyze", true, false, vec![]),
                make_step("Generate", true, false, vec![]),
                make_step("Analyze", true, false, vec![]),
            ]),
        ]);

        let a = compute_analytics(&[t]);
        assert_eq!(a.steps.unique_steps, 3);
        assert_eq!(a.steps.top_steps[0].step_name, "Analyze");
        assert_eq!(a.steps.top_steps[0].count, 3);
    }

    #[test]
    fn empty_traces() {
        let a = compute_analytics(&[]);
        assert_eq!(a.trace_count, 0);
        assert_eq!(a.latency.unit_count, 0);
        assert_eq!(a.latency.p50_ms, 0);
        assert_eq!(a.tokens.total, 0);
        assert!((a.anchors.pass_rate - 1.0).abs() < 0.01); // No checks → 100% pass
        assert!((a.anchors.breach_rate - 0.0).abs() < 0.01);
    }

    #[test]
    fn multiple_traces_aggregate() {
        let t1 = make_trace(vec![
            make_unit("F", 100, 50, 20, vec![make_step("A", true, false, vec![])]),
        ]);
        let t2 = make_trace(vec![
            make_unit("F", 200, 70, 30, vec![make_step("B", true, false, vec![])]),
        ]);

        let a = compute_analytics(&[t1, t2]);
        assert_eq!(a.trace_count, 2);
        assert_eq!(a.latency.unit_count, 2);
        assert_eq!(a.tokens.total_input, 120);
        assert_eq!(a.tokens.total_output, 50);
        assert_eq!(a.errors.total_steps, 2);
        assert_eq!(a.steps.unique_steps, 2);
    }

    #[test]
    fn no_anchor_data_defaults() {
        let t = make_trace(vec![
            make_unit("F", 100, 0, 0, vec![make_step("S", true, false, vec![])]),
        ]);

        let a = compute_analytics(&[t]);
        assert_eq!(a.anchors.total_checks, 0);
        assert!((a.anchors.pass_rate - 1.0).abs() < 0.01);
        assert!(a.anchors.top_breaches.is_empty());
    }

    #[test]
    fn analytics_serializes_to_json() {
        let t = make_trace(vec![
            make_unit("F", 100, 50, 20, vec![
                make_step("S", true, false, vec![anchor("Safe", true)]),
            ]),
        ]);

        let a = compute_analytics(&[t]);
        let json = serde_json::to_value(&a).unwrap();
        assert_eq!(json["trace_count"], 1);
        assert!(json["latency"]["p50_ms"].is_number());
        assert!(json["tokens"]["total"].is_number());
        assert!(json["anchors"]["pass_rate"].is_number());
        assert!(json["errors"]["error_rate"].is_number());
        assert!(json["steps"]["unique_steps"].is_number());
    }

    #[test]
    fn run_stats_no_files_returns_error() {
        assert_eq!(run_stats(&[], "text"), 2);
    }

    #[test]
    fn run_stats_missing_file_returns_error() {
        let files = vec!["nonexistent_trace_file.json".to_string()];
        assert_eq!(run_stats(&files, "text"), 2);
    }

    #[test]
    fn run_stats_valid_trace_json() {
        let tmp = std::env::temp_dir().join("axon_stats_test.trace.json");
        let data = serde_json::json!({
            "_meta": { "source": "t.axon", "backend": "anthropic", "tool_mode": "stub", "axon_version": "0.30.6", "mode": "stub" },
            "events": [
                { "event": "unit_start", "unit": "F", "step": "", "detail": "" },
                { "event": "step_complete", "unit": "F", "step": "S", "detail": "ok" },
                { "event": "unit_complete", "unit": "F", "step": "", "detail": "" },
            ]
        });
        std::fs::write(&tmp, serde_json::to_string(&data).unwrap()).unwrap();

        let files = vec![tmp.to_str().unwrap().to_string()];
        assert_eq!(run_stats(&files, "json"), 0);

        let _ = std::fs::remove_file(tmp);
    }
}
