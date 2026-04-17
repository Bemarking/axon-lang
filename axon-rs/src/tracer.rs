//! `axon trace` native implementation — pretty-print execution traces.
//!
//! Reads a `.trace.json` file (produced by `axon run --trace`) and renders
//! it as a human-readable timeline with ANSI colors.
//!
//! Supports both trace formats:
//!   - Python tracer: { _meta, events: [{type, data: {step_name, ...}}] }
//!   - Rust runner:   { _meta, events: [{event, unit, step, detail}] }
//!   - Span-based:    { _meta, spans: [{name, events, children}] }
//!
//! Exit codes:
//!   0 — success
//!   2 — file not found or invalid JSON

use std::io::{self, IsTerminal};
use std::path::Path;

use serde_json::Value;

// ── ANSI colors ─────────────────────────────────────────────────────────────

const RED: &str = "\x1b[31m";
const GREEN: &str = "\x1b[32m";
const YELLOW: &str = "\x1b[33m";
const CYAN: &str = "\x1b[36m";
const MAGENTA: &str = "\x1b[35m";
const BOLD: &str = "\x1b[1m";
const DIM: &str = "\x1b[2m";
const RESET: &str = "\x1b[0m";

fn event_color(event_type: &str) -> &'static str {
    match event_type {
        "step_start" | "step_end" | "confidence_check" => CYAN,
        "model_call" | "model_response" => MAGENTA,
        "anchor_check" => YELLOW,
        "anchor_pass" | "validation_pass" => GREEN,
        "anchor_breach" | "validation_fail" | "step_error" => RED,
        "retry_attempt" | "refine_start" => YELLOW,
        "memory_read" | "memory_write" => DIM,
        "unit_start" | "unit_complete" => CYAN,
        "step_stub" | "step_complete" => GREEN,
        _ => "",
    }
}

// ── Theme ───────────────────────────────────────────────────────────────────

struct Theme {
    rule: &'static str,
    span_open: &'static str,
    span_close: &'static str,
    event_prefix: &'static str,
}

const UNICODE_THEME: Theme = Theme {
    rule: "═",
    span_open: "┌─",
    span_close: "└─",
    event_prefix: "│",
};

const ASCII_THEME: Theme = Theme {
    rule: "=",
    span_open: "+-",
    span_close: "`-",
    event_prefix: "|",
};

// ── ANSI helper ─────────────────────────────────────────────────────────────

fn c(text: &str, code: &str, no_color: bool) -> String {
    if no_color {
        text.to_string()
    } else {
        format!("{code}{text}{RESET}")
    }
}

fn truncate(text: &str, limit: usize) -> String {
    if text.len() > limit {
        format!("{}...", &text[..limit.saturating_sub(3)])
    } else {
        text.to_string()
    }
}

// ── Rendering ───────────────────────────────────────────────────────────────

fn render_trace(data: &Value, no_color: bool) {
    let theme = if no_color { &ASCII_THEME } else { &UNICODE_THEME };
    let rule = theme.rule.repeat(60);

    println!();
    println!("{}", c(&rule, BOLD, no_color));
    println!("{}", c("  AXON Execution Trace", BOLD, no_color));
    println!("{}", c(&rule, BOLD, no_color));

    if let Value::Object(map) = data {
        // Render _meta
        if let Some(meta) = map.get("_meta").or(map.get("meta")) {
            render_meta(meta, no_color);
        }

        // Render spans (hierarchical)
        if let Some(Value::Array(spans)) = map.get("spans") {
            for span in spans {
                render_span(span, 1, no_color, theme);
            }
        }

        // Render events (flat)
        if let Some(Value::Array(events)) = map.get("events") {
            for event in events {
                render_event(event, 1, no_color, theme);
            }
        }

        // Fallback: render as flat key-value if no spans/events
        let has_spans = map.get("spans").and_then(|v| v.as_array()).map_or(false, |a| !a.is_empty());
        let has_events = map.get("events").and_then(|v| v.as_array()).map_or(false, |a| !a.is_empty());
        if !has_spans && !has_events {
            render_flat(data, 1, no_color);
        }
    } else if let Value::Array(items) = data {
        for item in items {
            render_event(item, 1, no_color, theme);
        }
    }

    println!();
    println!("{}", c(&rule, BOLD, no_color));
}

fn render_meta(meta: &Value, no_color: bool) {
    if let Value::Object(map) = meta {
        if let Some(source) = map.get("source").and_then(|v| v.as_str()) {
            println!("{}{}",
                c("  source: ", DIM, no_color),
                source
            );
        }
        if let Some(backend) = map.get("backend").and_then(|v| v.as_str()) {
            println!("{}{}",
                c("  backend: ", DIM, no_color),
                backend
            );
        }
        if let Some(version) = map.get("axon_version").and_then(|v| v.as_str()) {
            println!("{}{}",
                c("  version: ", DIM, no_color),
                version
            );
        }
        if let Some(mode) = map.get("mode").or(map.get("tool_mode")).and_then(|v| v.as_str()) {
            println!("{}{}",
                c("  mode: ", DIM, no_color),
                mode
            );
        }
        println!();
    }
}

fn render_span(span: &Value, indent: usize, no_color: bool, theme: &Theme) {
    let prefix = "  ".repeat(indent);
    let name = span.get("name").and_then(|v| v.as_str()).unwrap_or("unnamed");
    let duration = span.get("duration_ms");
    let dur_str = match duration {
        Some(Value::Number(n)) => format!(" ({}ms)", n),
        _ => String::new(),
    };

    println!(
        "{}{} {}{}",
        prefix,
        theme.span_open,
        c(name, &format!("{BOLD}{CYAN}"), no_color),
        dur_str
    );

    if let Some(Value::Array(events)) = span.get("events") {
        for event in events {
            render_event(event, indent + 1, no_color, theme);
        }
    }

    if let Some(Value::Array(children)) = span.get("children") {
        for child in children {
            render_span(child, indent + 1, no_color, theme);
        }
    }

    println!("{}{}", prefix, theme.span_close);
}

fn render_event(event: &Value, indent: usize, no_color: bool, theme: &Theme) {
    let prefix = "  ".repeat(indent);

    // Support both formats:
    // Python: {type: "step_start", data: {step_name: "Extract"}}
    // Rust:   {event: "unit_start", unit: "Flow", step: "Step", detail: "..."}
    let event_type = event.get("type")
        .or(event.get("event_type"))
        .or(event.get("event"))
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    let color = event_color(event_type);
    let badge = c(&format!("[{event_type}]"), &format!("{color}{BOLD}"), no_color);

    // Build summary from data dict or from flat fields
    let summary = if let Some(data) = event.get("data") {
        event_summary(data)
    } else {
        // Rust format: combine unit/step/detail
        let mut parts: Vec<String> = Vec::new();
        if let Some(unit) = event.get("unit").and_then(|v| v.as_str()) {
            if !unit.is_empty() { parts.push(unit.to_string()); }
        }
        if let Some(step) = event.get("step").and_then(|v| v.as_str()) {
            if !step.is_empty() { parts.push(step.to_string()); }
        }
        if let Some(detail) = event.get("detail").and_then(|v| v.as_str()) {
            if !detail.is_empty() { parts.push(detail.to_string()); }
        }
        if parts.is_empty() { String::new() } else { parts.join(" — ") }
    };

    let ts_str = event.get("timestamp")
        .and_then(|v| v.as_f64().map(|f| format!("[{f:.3}] ")).or(v.as_str().map(|s| format!("[{s}] "))))
        .unwrap_or_default();

    let summary_str = if summary.is_empty() { String::new() } else { format!("  {}", truncate(&summary, 80)) };

    println!("{}{} {}{}{}", prefix, theme.event_prefix, ts_str, badge, summary_str);

    // Expand details for breach/fail/retry events
    if matches!(event_type, "anchor_breach" | "validation_fail" | "retry_attempt" | "step_error") {
        if let Some(Value::Object(data)) = event.get("data") {
            for (key, val) in data {
                if matches!(key.as_str(), "step_name" | "name" | "message") { continue; }
                println!(
                    "{}{}   {}: {}",
                    prefix,
                    theme.event_prefix,
                    c(key, DIM, no_color),
                    truncate(&val.to_string().trim_matches('"').to_string(), 60)
                );
            }
        }
    }
}

fn event_summary(data: &Value) -> String {
    if let Value::Object(map) = data {
        for key in &["step_name", "name", "message", "content", "reason"] {
            if let Some(val) = map.get(*key).and_then(|v| v.as_str()) {
                return val.to_string();
            }
        }
    }
    String::new()
}

fn render_flat(data: &Value, indent: usize, no_color: bool) {
    let prefix = "  ".repeat(indent);
    if let Value::Object(map) = data {
        for (key, value) in map {
            if key.starts_with('_') { continue; }
            match value {
                Value::Object(_) => {
                    println!("{}{}", prefix, c(key, BOLD, no_color));
                    render_flat(value, indent + 1, no_color);
                }
                Value::Array(arr) => {
                    println!("{}{}: [{} items]", prefix, c(key, BOLD, no_color), arr.len());
                }
                _ => {
                    let val_str = match value {
                        Value::String(s) => s.clone(),
                        other => other.to_string(),
                    };
                    println!("{}{}: {}", prefix, c(key, DIM, no_color), val_str);
                }
            }
        }
    }
}

// ── Public entry point ───────────────────────────────────────────────────────

pub fn run_trace(file: &str, no_color: bool) -> i32 {
    let use_color = !no_color && io::stdout().is_terminal();
    let effective_no_color = !use_color;

    let path = Path::new(file);

    // Read file
    let content = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "{}",
                c(&format!("✗ File not found: {file}"), &format!("{BOLD}\x1b[31m"), effective_no_color)
            );
            return 2;
        }
    };

    // Parse JSON
    let data: Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(e) => {
            eprintln!(
                "{}",
                c(&format!("✗ Invalid JSON: {e}"), &format!("{BOLD}\x1b[31m"), effective_no_color)
            );
            return 2;
        }
    };

    render_trace(&data, effective_no_color);
    0
}
