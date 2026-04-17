//! Execution context — runtime variables accessible between steps.
//!
//! Provides `$variable` interpolation in user prompts and system prompts.
//! Variables are populated automatically by the runner as steps execute.
//!
//! Built-in variables:
//!   $result       — output of the most recent step
//!   $step_name    — name of the current step
//!   $step_type    — type of the current step
//!   $flow_name    — name of the current flow
//!   $persona_name — name of the current persona
//!   $unit_index   — 1-based index of the current execution unit
//!   $step_index   — 1-based index of the current step within the unit
//!   ${StepName}   — result of a specific named step (e.g., ${Analyze})
//!
//! Variable syntax: `$name` or `${name}` (braces for disambiguation).

use std::collections::HashMap;

/// Execution context — holds runtime variables for a single execution unit.
#[derive(Debug, Clone)]
pub struct ExecContext {
    vars: HashMap<String, String>,
}

impl ExecContext {
    /// Create a new context with unit-level variables pre-set.
    pub fn new(flow_name: &str, persona_name: &str, unit_index: usize) -> Self {
        let mut vars = HashMap::new();
        vars.insert("flow_name".to_string(), flow_name.to_string());
        vars.insert("persona_name".to_string(), persona_name.to_string());
        vars.insert("unit_index".to_string(), format!("{}", unit_index + 1));
        vars.insert("result".to_string(), String::new());
        ExecContext { vars }
    }

    /// Set a variable.
    pub fn set(&mut self, key: &str, value: &str) {
        self.vars.insert(key.to_string(), value.to_string());
    }

    /// Get a variable value.
    pub fn get(&self, key: &str) -> Option<&str> {
        self.vars.get(key).map(|s| s.as_str())
    }

    /// Set the current step context variables.
    pub fn set_step(&mut self, step_name: &str, step_type: &str, step_index: usize) {
        self.vars.insert("step_name".to_string(), step_name.to_string());
        self.vars.insert("step_type".to_string(), step_type.to_string());
        self.vars.insert("step_index".to_string(), format!("{}", step_index + 1));
    }

    /// Record the result of a step (updates $result and ${StepName}).
    pub fn set_result(&mut self, step_name: &str, result: &str) {
        self.vars.insert("result".to_string(), result.to_string());
        self.vars.insert(step_name.to_string(), result.to_string());
    }

    /// Interpolate variables in a string.
    ///
    /// Replaces `${name}` and `$name` with their values from the context.
    /// Unknown variables are left as-is.
    pub fn interpolate(&self, text: &str) -> String {
        let bytes = text.as_bytes();
        let mut out = String::with_capacity(text.len());
        let mut i = 0;

        while i < bytes.len() {
            if bytes[i] == b'$' && i + 1 < bytes.len() {
                if bytes[i + 1] == b'{' {
                    // ${name} form
                    if let Some(close) = text[i + 2..].find('}') {
                        let var_name = &text[i + 2..i + 2 + close];
                        if let Some(val) = self.vars.get(var_name) {
                            out.push_str(val);
                        } else {
                            // Unknown variable — keep literal
                            out.push_str(&text[i..i + 3 + close]);
                        }
                        i += 3 + close;
                        continue;
                    }
                } else if bytes[i + 1].is_ascii_alphabetic() || bytes[i + 1] == b'_' {
                    // $name form — consume alphanumeric + underscore
                    let start = i + 1;
                    let mut end = start;
                    while end < bytes.len()
                        && (bytes[end].is_ascii_alphanumeric() || bytes[end] == b'_')
                    {
                        end += 1;
                    }
                    let var_name = &text[start..end];
                    if let Some(val) = self.vars.get(var_name) {
                        out.push_str(val);
                    } else {
                        out.push_str(&text[i..end]);
                    }
                    i = end;
                    continue;
                }
            }
            out.push(bytes[i] as char);
            i += 1;
        }

        out
    }

    /// Number of variables currently set.
    pub fn var_count(&self) -> usize {
        self.vars.len()
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_context_has_unit_vars() {
        let ctx = ExecContext::new("Analyze", "Expert", 0);
        assert_eq!(ctx.get("flow_name"), Some("Analyze"));
        assert_eq!(ctx.get("persona_name"), Some("Expert"));
        assert_eq!(ctx.get("unit_index"), Some("1"));
        assert_eq!(ctx.get("result"), Some(""));
    }

    #[test]
    fn set_step_updates_vars() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set_step("Gather", "step", 0);
        assert_eq!(ctx.get("step_name"), Some("Gather"));
        assert_eq!(ctx.get("step_type"), Some("step"));
        assert_eq!(ctx.get("step_index"), Some("1"));
    }

    #[test]
    fn set_result_updates_both() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set_result("Analyze", "The answer is 42");
        assert_eq!(ctx.get("result"), Some("The answer is 42"));
        assert_eq!(ctx.get("Analyze"), Some("The answer is 42"));
    }

    #[test]
    fn interpolate_dollar_name() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set_result("Analyze", "42");
        let out = ctx.interpolate("The result is $result from step $step_name");
        // $step_name not set yet — left as-is
        assert!(out.contains("The result is 42"));
    }

    #[test]
    fn interpolate_braced() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set_result("Analyze", "42");
        let out = ctx.interpolate("Previous: ${Analyze}, flow: ${flow_name}");
        assert_eq!(out, "Previous: 42, flow: F");
    }

    #[test]
    fn interpolate_unknown_kept_literal() {
        let ctx = ExecContext::new("F", "P", 0);
        let out = ctx.interpolate("Value: $unknown and ${also_unknown}");
        assert_eq!(out, "Value: $unknown and ${also_unknown}");
    }

    #[test]
    fn interpolate_no_vars() {
        let ctx = ExecContext::new("F", "P", 0);
        let out = ctx.interpolate("No variables here.");
        assert_eq!(out, "No variables here.");
    }

    #[test]
    fn interpolate_adjacent_vars() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("a", "hello");
        ctx.set("b", "world");
        let out = ctx.interpolate("$a$b");
        assert_eq!(out, "helloworld");
    }

    #[test]
    fn interpolate_dollar_at_end() {
        let ctx = ExecContext::new("F", "P", 0);
        let out = ctx.interpolate("price is $");
        assert_eq!(out, "price is $");
    }

    #[test]
    fn interpolate_dollar_number() {
        let ctx = ExecContext::new("F", "P", 0);
        let out = ctx.interpolate("cost: $100");
        assert_eq!(out, "cost: $100");
    }

    #[test]
    fn set_and_get_custom() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set("custom_key", "custom_value");
        assert_eq!(ctx.get("custom_key"), Some("custom_value"));
    }

    #[test]
    fn var_count() {
        let ctx = ExecContext::new("F", "P", 0);
        // flow_name, persona_name, unit_index, result = 4
        assert_eq!(ctx.var_count(), 4);
    }
}
