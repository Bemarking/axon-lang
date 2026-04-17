//! Tool result validation and effect tracking.
//!
//! After a tool executes, validates the output against its declared
//! `output_schema` and records which effects were activated from the
//! tool's `effect_row`.
//!
//! Validation rules (by output_schema value):
//!   "JSON" / "json"       — output must be valid JSON
//!   "number" / "numeric"  — output must parse as f64
//!   "boolean" / "bool"    — output must be "true" or "false"
//!   "nonempty"            — output must not be empty or whitespace-only
//!   ""                    — no validation (always passes)
//!   other                 — treated as a type name, validated as non-empty
//!
//! Effect categories:
//!   read     — reads data from external source
//!   write    — writes/persists data externally
//!   network  — makes network calls
//!   compute  — performs significant computation
//!   side     — general side effect
//!
//! The `EffectTracker` accumulates effect records during execution
//! for inclusion in the execution report.

use std::collections::HashMap;

// ── Validation ─────────────────────────────────────────────────────────────

/// Result of validating a tool output.
#[derive(Debug, Clone)]
pub struct ValidationResult {
    pub tool_name: String,
    pub schema: String,
    pub passed: bool,
    pub message: String,
}

/// Validate a tool's output against its declared output_schema.
pub fn validate_output(tool_name: &str, output: &str, schema: &str) -> ValidationResult {
    let schema_lower = schema.trim().to_lowercase();

    let (passed, message) = match schema_lower.as_str() {
        // No schema declared — always passes
        "" => (true, "no schema declared".to_string()),

        // JSON validation
        "json" => {
            match serde_json::from_str::<serde_json::Value>(output) {
                Ok(_) => (true, "valid JSON".to_string()),
                Err(e) => (false, format!("invalid JSON: {e}")),
            }
        }

        // Numeric validation
        "number" | "numeric" | "integer" | "float" => {
            match output.trim().parse::<f64>() {
                Ok(_) => (true, "valid number".to_string()),
                Err(_) => (false, format!("expected number, got: '{}'", truncate(output, 50))),
            }
        }

        // Boolean validation
        "boolean" | "bool" => {
            let lower = output.trim().to_lowercase();
            if lower == "true" || lower == "false" {
                (true, "valid boolean".to_string())
            } else {
                (false, format!("expected boolean, got: '{}'", truncate(output, 50)))
            }
        }

        // Non-empty validation
        "nonempty" | "non_empty" | "required" => {
            if output.trim().is_empty() {
                (false, "output is empty".to_string())
            } else {
                (true, "non-empty output".to_string())
            }
        }

        // Named type — treated as non-empty check
        _ => {
            if output.trim().is_empty() {
                (false, format!("expected {schema} output, got empty"))
            } else {
                (true, format!("output present (schema: {schema})"))
            }
        }
    };

    ValidationResult {
        tool_name: tool_name.to_string(),
        schema: schema.to_string(),
        passed,
        message,
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() > max {
        format!("{}…", &s[..max])
    } else {
        s.to_string()
    }
}

// ── Effect tracking ────────────────────────────────────────────────────────

/// A recorded tool effect event.
#[derive(Debug, Clone)]
pub struct EffectRecord {
    pub tool_name: String,
    pub step_name: String,
    pub unit_name: String,
    pub effects: Vec<String>,
}

/// Tracks tool effects during execution.
#[derive(Debug)]
pub struct EffectTracker {
    records: Vec<EffectRecord>,
    effect_counts: HashMap<String, usize>,
}

impl EffectTracker {
    pub fn new() -> Self {
        EffectTracker {
            records: Vec::new(),
            effect_counts: HashMap::new(),
        }
    }

    /// Record a tool execution with its declared effects.
    pub fn record(
        &mut self,
        tool_name: &str,
        step_name: &str,
        unit_name: &str,
        effects: &[String],
    ) {
        for effect in effects {
            *self.effect_counts.entry(effect.clone()).or_insert(0) += 1;
        }
        self.records.push(EffectRecord {
            tool_name: tool_name.to_string(),
            step_name: step_name.to_string(),
            unit_name: unit_name.to_string(),
            effects: effects.to_vec(),
        });
    }

    /// All recorded effect events.
    pub fn records(&self) -> &[EffectRecord] {
        &self.records
    }

    /// Total number of tool executions tracked.
    pub fn total_executions(&self) -> usize {
        self.records.len()
    }

    /// Count of a specific effect type across all executions.
    pub fn effect_count(&self, effect: &str) -> usize {
        self.effect_counts.get(effect).copied().unwrap_or(0)
    }

    /// All distinct effect types observed.
    pub fn distinct_effects(&self) -> Vec<&str> {
        let mut effects: Vec<&str> = self.effect_counts.keys().map(|k| k.as_str()).collect();
        effects.sort();
        effects
    }

    /// Whether any network effects have been recorded.
    pub fn has_network_effects(&self) -> bool {
        self.effect_count("network") > 0
    }

    /// Whether any write effects have been recorded.
    pub fn has_write_effects(&self) -> bool {
        self.effect_count("write") > 0
    }

    /// Summary string for display.
    pub fn summary(&self) -> String {
        if self.records.is_empty() {
            return "no tool effects".to_string();
        }
        let parts: Vec<String> = self
            .effect_counts
            .iter()
            .map(|(k, v)| format!("{k}:{v}"))
            .collect();
        format!(
            "{} tool executions, effects: {}",
            self.records.len(),
            parts.join(", ")
        )
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── Validation tests ───────────────────────────────────────────

    #[test]
    fn validate_no_schema() {
        let r = validate_output("Tool", "anything", "");
        assert!(r.passed);
    }

    #[test]
    fn validate_json_valid() {
        let r = validate_output("Tool", r#"{"key": "value"}"#, "JSON");
        assert!(r.passed);
    }

    #[test]
    fn validate_json_array() {
        let r = validate_output("Tool", "[1, 2, 3]", "json");
        assert!(r.passed);
    }

    #[test]
    fn validate_json_invalid() {
        let r = validate_output("Tool", "not json at all", "JSON");
        assert!(!r.passed);
        assert!(r.message.contains("invalid JSON"));
    }

    #[test]
    fn validate_number_valid() {
        let r = validate_output("Calc", "42", "number");
        assert!(r.passed);
        let r2 = validate_output("Calc", "3.14", "numeric");
        assert!(r2.passed);
        let r3 = validate_output("Calc", "-100", "integer");
        assert!(r3.passed);
    }

    #[test]
    fn validate_number_invalid() {
        let r = validate_output("Calc", "not a number", "number");
        assert!(!r.passed);
    }

    #[test]
    fn validate_boolean_valid() {
        assert!(validate_output("T", "true", "boolean").passed);
        assert!(validate_output("T", "false", "bool").passed);
        assert!(validate_output("T", "TRUE", "boolean").passed);
    }

    #[test]
    fn validate_boolean_invalid() {
        let r = validate_output("T", "maybe", "boolean");
        assert!(!r.passed);
    }

    #[test]
    fn validate_nonempty_valid() {
        let r = validate_output("T", "has content", "nonempty");
        assert!(r.passed);
    }

    #[test]
    fn validate_nonempty_invalid() {
        let r = validate_output("T", "  ", "nonempty");
        assert!(!r.passed);
    }

    #[test]
    fn validate_named_type_present() {
        let r = validate_output("T", "some data", "EntityMap");
        assert!(r.passed);
        assert!(r.message.contains("EntityMap"));
    }

    #[test]
    fn validate_named_type_empty() {
        let r = validate_output("T", "", "RiskAnalysis");
        assert!(!r.passed);
    }

    // ── Effect tracker tests ───────────────────────────────────────

    #[test]
    fn tracker_empty() {
        let tracker = EffectTracker::new();
        assert_eq!(tracker.total_executions(), 0);
        assert!(tracker.distinct_effects().is_empty());
        assert!(!tracker.has_network_effects());
        assert!(!tracker.has_write_effects());
        assert_eq!(tracker.summary(), "no tool effects");
    }

    #[test]
    fn tracker_record_effects() {
        let mut tracker = EffectTracker::new();
        tracker.record(
            "WebSearch",
            "Search",
            "Flow1",
            &["network".to_string(), "read".to_string()],
        );

        assert_eq!(tracker.total_executions(), 1);
        assert!(tracker.has_network_effects());
        assert!(!tracker.has_write_effects());
        assert_eq!(tracker.effect_count("network"), 1);
        assert_eq!(tracker.effect_count("read"), 1);
    }

    #[test]
    fn tracker_multiple_records() {
        let mut tracker = EffectTracker::new();
        tracker.record("WebSearch", "S1", "F1", &["network".to_string()]);
        tracker.record("DBWrite", "S2", "F1", &["write".to_string(), "network".to_string()]);
        tracker.record("Calculator", "S3", "F1", &["compute".to_string()]);

        assert_eq!(tracker.total_executions(), 3);
        assert_eq!(tracker.effect_count("network"), 2);
        assert_eq!(tracker.effect_count("write"), 1);
        assert_eq!(tracker.effect_count("compute"), 1);
        assert!(tracker.has_network_effects());
        assert!(tracker.has_write_effects());
    }

    #[test]
    fn tracker_distinct_effects_sorted() {
        let mut tracker = EffectTracker::new();
        tracker.record("T1", "S", "F", &["write".to_string(), "compute".to_string()]);
        tracker.record("T2", "S", "F", &["network".to_string(), "read".to_string()]);

        let effects = tracker.distinct_effects();
        assert_eq!(effects, vec!["compute", "network", "read", "write"]);
    }

    #[test]
    fn tracker_records_accessible() {
        let mut tracker = EffectTracker::new();
        tracker.record("WebSearch", "Search", "Flow1", &["network".to_string()]);

        let records = tracker.records();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].tool_name, "WebSearch");
        assert_eq!(records[0].step_name, "Search");
        assert_eq!(records[0].unit_name, "Flow1");
        assert_eq!(records[0].effects, vec!["network"]);
    }

    #[test]
    fn tracker_summary_format() {
        let mut tracker = EffectTracker::new();
        tracker.record("T1", "S", "F", &["network".to_string()]);
        tracker.record("T2", "S", "F", &["network".to_string()]);

        let summary = tracker.summary();
        assert!(summary.contains("2 tool executions"));
        assert!(summary.contains("network:2"));
    }
}
