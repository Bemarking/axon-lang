//! Trace Export — export analytics as Prometheus exposition format or CSV.
//!
//! Converts `TraceAnalytics` into standard formats for external consumption:
//!   - Prometheus: text exposition format (text/plain; version=0.0.4)
//!   - CSV: comma-separated values for spreadsheet/BI tools
//!
//! Prometheus metrics follow naming conventions:
//!   axon_trace_*  — trace-level metrics
//!   axon_latency_* — latency percentiles
//!   axon_tokens_*  — token usage
//!   axon_anchors_* — anchor pass/breach rates
//!   axon_errors_*  — error/retry rates

use crate::trace_stats::TraceAnalytics;

// ── Prometheus exposition format ────────────────────────────────────────

/// Export analytics as Prometheus exposition format text.
pub fn to_prometheus(analytics: &TraceAnalytics) -> String {
    let mut out = String::new();

    // Trace count
    out.push_str("# HELP axon_traces_total Total number of traces analyzed.\n");
    out.push_str("# TYPE axon_traces_total gauge\n");
    out.push_str(&format!("axon_traces_total {}\n", analytics.trace_count));
    out.push('\n');

    // Units
    out.push_str("# HELP axon_units_total Total execution units across all traces.\n");
    out.push_str("# TYPE axon_units_total gauge\n");
    out.push_str(&format!("axon_units_total {}\n", analytics.latency.unit_count));
    out.push('\n');

    // Steps
    out.push_str("# HELP axon_steps_total Total steps executed across all traces.\n");
    out.push_str("# TYPE axon_steps_total gauge\n");
    out.push_str(&format!("axon_steps_total {}\n", analytics.errors.total_steps));
    out.push('\n');

    // Latency percentiles
    out.push_str("# HELP axon_latency_ms Latency percentiles in milliseconds.\n");
    out.push_str("# TYPE axon_latency_ms gauge\n");
    out.push_str(&format!("axon_latency_ms{{quantile=\"0.5\"}} {}\n", analytics.latency.p50_ms));
    out.push_str(&format!("axon_latency_ms{{quantile=\"0.95\"}} {}\n", analytics.latency.p95_ms));
    out.push_str(&format!("axon_latency_ms{{quantile=\"0.99\"}} {}\n", analytics.latency.p99_ms));
    out.push_str(&format!("axon_latency_mean_ms {}\n", analytics.latency.mean_ms));
    out.push_str(&format!("axon_latency_min_ms {}\n", analytics.latency.min_ms));
    out.push_str(&format!("axon_latency_max_ms {}\n", analytics.latency.max_ms));
    out.push('\n');

    // Tokens
    out.push_str("# HELP axon_tokens_total Total tokens used.\n");
    out.push_str("# TYPE axon_tokens_total gauge\n");
    out.push_str(&format!("axon_tokens_total{{type=\"input\"}} {}\n", analytics.tokens.total_input));
    out.push_str(&format!("axon_tokens_total{{type=\"output\"}} {}\n", analytics.tokens.total_output));
    out.push_str(&format!("axon_tokens_total{{type=\"combined\"}} {}\n", analytics.tokens.total));
    out.push_str(&format!("axon_tokens_mean_per_unit{{type=\"input\"}} {}\n", analytics.tokens.mean_input_per_unit));
    out.push_str(&format!("axon_tokens_mean_per_unit{{type=\"output\"}} {}\n", analytics.tokens.mean_output_per_unit));
    out.push('\n');

    // Anchors
    out.push_str("# HELP axon_anchor_checks_total Total anchor checks performed.\n");
    out.push_str("# TYPE axon_anchor_checks_total gauge\n");
    out.push_str(&format!("axon_anchor_checks_total {}\n", analytics.anchors.total_checks));
    out.push_str(&format!("axon_anchor_passes_total {}\n", analytics.anchors.total_passes));
    out.push_str(&format!("axon_anchor_breaches_total {}\n", analytics.anchors.total_breaches));
    out.push_str(&format!("axon_anchor_pass_rate {:.4}\n", analytics.anchors.pass_rate));
    out.push_str(&format!("axon_anchor_breach_rate {:.4}\n", analytics.anchors.breach_rate));
    out.push('\n');

    // Top breaches as labeled metrics
    if !analytics.anchors.top_breaches.is_empty() {
        out.push_str("# HELP axon_anchor_breach_count Breach count per anchor name.\n");
        out.push_str("# TYPE axon_anchor_breach_count gauge\n");
        for b in &analytics.anchors.top_breaches {
            out.push_str(&format!(
                "axon_anchor_breach_count{{anchor=\"{}\"}} {}\n",
                b.anchor_name, b.breach_count
            ));
        }
        out.push('\n');
    }

    // Errors
    out.push_str("# HELP axon_errors_total Total step errors.\n");
    out.push_str("# TYPE axon_errors_total gauge\n");
    out.push_str(&format!("axon_errors_total {}\n", analytics.errors.total_errors));
    out.push_str(&format!("axon_retries_total {}\n", analytics.errors.total_retries));
    out.push_str(&format!("axon_error_rate {:.4}\n", analytics.errors.error_rate));
    out.push_str(&format!("axon_retry_rate {:.4}\n", analytics.errors.retry_rate));
    out.push('\n');

    // Unique steps
    out.push_str("# HELP axon_unique_steps Total unique step names.\n");
    out.push_str("# TYPE axon_unique_steps gauge\n");
    out.push_str(&format!("axon_unique_steps {}\n", analytics.steps.unique_steps));
    out.push('\n');

    // Top steps as labeled metrics
    if !analytics.steps.top_steps.is_empty() {
        out.push_str("# HELP axon_step_frequency Execution count per step name.\n");
        out.push_str("# TYPE axon_step_frequency gauge\n");
        for s in &analytics.steps.top_steps {
            out.push_str(&format!(
                "axon_step_frequency{{step=\"{}\"}} {}\n",
                s.step_name, s.count
            ));
        }
        out.push('\n');
    }

    out
}

// ── CSV export ──────────────────────────────────────────────────────────

/// Export analytics as CSV rows (metric,value format).
pub fn to_csv(analytics: &TraceAnalytics) -> String {
    let mut out = String::new();
    out.push_str("metric,value\n");

    out.push_str(&format!("traces_total,{}\n", analytics.trace_count));
    out.push_str(&format!("units_total,{}\n", analytics.latency.unit_count));
    out.push_str(&format!("steps_total,{}\n", analytics.errors.total_steps));

    // Latency
    out.push_str(&format!("latency_p50_ms,{}\n", analytics.latency.p50_ms));
    out.push_str(&format!("latency_p95_ms,{}\n", analytics.latency.p95_ms));
    out.push_str(&format!("latency_p99_ms,{}\n", analytics.latency.p99_ms));
    out.push_str(&format!("latency_mean_ms,{}\n", analytics.latency.mean_ms));
    out.push_str(&format!("latency_min_ms,{}\n", analytics.latency.min_ms));
    out.push_str(&format!("latency_max_ms,{}\n", analytics.latency.max_ms));

    // Tokens
    out.push_str(&format!("tokens_input,{}\n", analytics.tokens.total_input));
    out.push_str(&format!("tokens_output,{}\n", analytics.tokens.total_output));
    out.push_str(&format!("tokens_total,{}\n", analytics.tokens.total));
    out.push_str(&format!("tokens_mean_input_per_unit,{}\n", analytics.tokens.mean_input_per_unit));
    out.push_str(&format!("tokens_mean_output_per_unit,{}\n", analytics.tokens.mean_output_per_unit));

    // Anchors
    out.push_str(&format!("anchor_checks,{}\n", analytics.anchors.total_checks));
    out.push_str(&format!("anchor_passes,{}\n", analytics.anchors.total_passes));
    out.push_str(&format!("anchor_breaches,{}\n", analytics.anchors.total_breaches));
    out.push_str(&format!("anchor_pass_rate,{:.4}\n", analytics.anchors.pass_rate));
    out.push_str(&format!("anchor_breach_rate,{:.4}\n", analytics.anchors.breach_rate));

    // Top breaches
    for b in &analytics.anchors.top_breaches {
        out.push_str(&format!("anchor_breach:{},{}\n", b.anchor_name, b.breach_count));
    }

    // Errors
    out.push_str(&format!("errors_total,{}\n", analytics.errors.total_errors));
    out.push_str(&format!("retries_total,{}\n", analytics.errors.total_retries));
    out.push_str(&format!("error_rate,{:.4}\n", analytics.errors.error_rate));
    out.push_str(&format!("retry_rate,{:.4}\n", analytics.errors.retry_rate));

    // Steps
    out.push_str(&format!("unique_steps,{}\n", analytics.steps.unique_steps));
    for s in &analytics.steps.top_steps {
        out.push_str(&format!("step_freq:{},{}\n", s.step_name, s.count));
    }

    out
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::trace_stats::*;

    fn sample_analytics() -> TraceAnalytics {
        TraceAnalytics {
            trace_count: 3,
            latency: LatencyStats {
                unit_count: 5,
                p50_ms: 100,
                p95_ms: 250,
                p99_ms: 400,
                mean_ms: 150,
                min_ms: 50,
                max_ms: 500,
            },
            tokens: TokenStats {
                total_input: 1000,
                total_output: 500,
                total: 1500,
                mean_input_per_unit: 200,
                mean_output_per_unit: 100,
                mean_total_per_unit: 300,
                unit_count: 5,
            },
            anchors: AnchorStats {
                total_checks: 20,
                total_passes: 17,
                total_breaches: 3,
                pass_rate: 0.85,
                breach_rate: 0.15,
                top_breaches: vec![
                    AnchorBreachEntry { anchor_name: "NoHallucination".into(), breach_count: 2 },
                    AnchorBreachEntry { anchor_name: "FactualOnly".into(), breach_count: 1 },
                ],
            },
            errors: ErrorStats {
                total_steps: 15,
                total_errors: 2,
                total_retries: 1,
                error_rate: 0.1333,
                retry_rate: 0.0667,
            },
            steps: StepFrequency {
                unique_steps: 4,
                top_steps: vec![
                    StepFreqEntry { step_name: "Analyze".into(), count: 6 },
                    StepFreqEntry { step_name: "Summarize".into(), count: 4 },
                    StepFreqEntry { step_name: "Generate".into(), count: 3 },
                    StepFreqEntry { step_name: "Review".into(), count: 2 },
                ],
            },
        }
    }

    #[test]
    fn prometheus_contains_trace_count() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_traces_total 3"));
    }

    #[test]
    fn prometheus_contains_latency_quantiles() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_latency_ms{quantile=\"0.5\"} 100"));
        assert!(prom.contains("axon_latency_ms{quantile=\"0.95\"} 250"));
        assert!(prom.contains("axon_latency_ms{quantile=\"0.99\"} 400"));
        assert!(prom.contains("axon_latency_mean_ms 150"));
        assert!(prom.contains("axon_latency_min_ms 50"));
        assert!(prom.contains("axon_latency_max_ms 500"));
    }

    #[test]
    fn prometheus_contains_tokens() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_tokens_total{type=\"input\"} 1000"));
        assert!(prom.contains("axon_tokens_total{type=\"output\"} 500"));
        assert!(prom.contains("axon_tokens_total{type=\"combined\"} 1500"));
    }

    #[test]
    fn prometheus_contains_anchors() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_anchor_checks_total 20"));
        assert!(prom.contains("axon_anchor_pass_rate 0.8500"));
        assert!(prom.contains("axon_anchor_breach_rate 0.1500"));
        assert!(prom.contains("axon_anchor_breach_count{anchor=\"NoHallucination\"} 2"));
        assert!(prom.contains("axon_anchor_breach_count{anchor=\"FactualOnly\"} 1"));
    }

    #[test]
    fn prometheus_contains_errors() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_errors_total 2"));
        assert!(prom.contains("axon_retries_total 1"));
        assert!(prom.contains("axon_error_rate 0.1333"));
    }

    #[test]
    fn prometheus_contains_step_frequency() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("axon_step_frequency{step=\"Analyze\"} 6"));
        assert!(prom.contains("axon_step_frequency{step=\"Summarize\"} 4"));
        assert!(prom.contains("axon_unique_steps 4"));
    }

    #[test]
    fn prometheus_has_help_and_type_lines() {
        let prom = to_prometheus(&sample_analytics());
        assert!(prom.contains("# HELP axon_traces_total"));
        assert!(prom.contains("# TYPE axon_traces_total gauge"));
        assert!(prom.contains("# HELP axon_latency_ms"));
        assert!(prom.contains("# HELP axon_tokens_total"));
    }

    #[test]
    fn prometheus_empty_analytics() {
        let a = TraceAnalytics {
            trace_count: 0,
            latency: LatencyStats { unit_count: 0, p50_ms: 0, p95_ms: 0, p99_ms: 0, mean_ms: 0, min_ms: 0, max_ms: 0 },
            tokens: TokenStats { total_input: 0, total_output: 0, total: 0, mean_input_per_unit: 0, mean_output_per_unit: 0, mean_total_per_unit: 0, unit_count: 0 },
            anchors: AnchorStats { total_checks: 0, total_passes: 0, total_breaches: 0, pass_rate: 1.0, breach_rate: 0.0, top_breaches: vec![] },
            errors: ErrorStats { total_steps: 0, total_errors: 0, total_retries: 0, error_rate: 0.0, retry_rate: 0.0 },
            steps: StepFrequency { unique_steps: 0, top_steps: vec![] },
        };
        let prom = to_prometheus(&a);
        assert!(prom.contains("axon_traces_total 0"));
        // No breach_count or step_frequency sections for empty data
        assert!(!prom.contains("axon_anchor_breach_count"));
        assert!(!prom.contains("axon_step_frequency"));
    }

    #[test]
    fn csv_header_present() {
        let csv = to_csv(&sample_analytics());
        assert!(csv.starts_with("metric,value\n"));
    }

    #[test]
    fn csv_contains_metrics() {
        let csv = to_csv(&sample_analytics());
        assert!(csv.contains("traces_total,3"));
        assert!(csv.contains("latency_p50_ms,100"));
        assert!(csv.contains("latency_p95_ms,250"));
        assert!(csv.contains("tokens_input,1000"));
        assert!(csv.contains("tokens_output,500"));
        assert!(csv.contains("anchor_checks,20"));
        assert!(csv.contains("anchor_pass_rate,0.8500"));
        assert!(csv.contains("errors_total,2"));
        assert!(csv.contains("unique_steps,4"));
    }

    #[test]
    fn csv_contains_breach_labels() {
        let csv = to_csv(&sample_analytics());
        assert!(csv.contains("anchor_breach:NoHallucination,2"));
        assert!(csv.contains("anchor_breach:FactualOnly,1"));
    }

    #[test]
    fn csv_contains_step_freq_labels() {
        let csv = to_csv(&sample_analytics());
        assert!(csv.contains("step_freq:Analyze,6"));
        assert!(csv.contains("step_freq:Summarize,4"));
    }

    #[test]
    fn csv_parseable_line_count() {
        let csv = to_csv(&sample_analytics());
        let lines: Vec<&str> = csv.lines().collect();
        // header + base metrics + breaches + step freqs
        // 1 header + 3 counts + 6 latency + 5 tokens + 5 anchors + 2 breaches + 4 errors + 1 unique + 4 steps = 31
        assert!(lines.len() > 25);
        // Each line (except header) should have exactly one comma
        for line in &lines[1..] {
            assert_eq!(line.matches(',').count(), 1, "Line has wrong number of commas: {}", line);
        }
    }
}
