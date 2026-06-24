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

/// Variable names the runner manages internally. They are excluded from
/// the "user binding" view (see [`ExecContext::user_bindings`]) so that
/// a `persist`/`mutate` into a SQL-backed `axonstore` writes only the
/// flow's own data as a row — never runner bookkeeping.
const BUILTIN_VARS: &[&str] = &[
    "flow_name",
    "persona_name",
    "unit_index",
    "result",
    "step_name",
    "step_type",
    "step_index",
];

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

    /// §Fase 37.d (D3) — the full variable map, for resolving `${name}`
    /// placeholders in a store `where:` clause against the flow context
    /// (the Request Binding Contract on the synchronous filter path).
    pub fn vars(&self) -> &HashMap<String, String> {
        &self.vars
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
    /// Unknown variables are left as-is. Delegates to the free
    /// [`interpolate_vars`] so the streaming dispatcher interpolates
    /// `persist` field values with byte-identical semantics (D5).
    pub fn interpolate(&self, text: &str) -> String {
        interpolate_vars(text, &self.vars)
    }

    /// §Fase 60 — resolve a `use Tool(k = v)` keyword-arg value by its
    /// `value_kind` (reference → binding lookup; literal → interpolation).
    /// Delegates to the free [`resolve_named_arg_value`] so the sync runner and
    /// the streaming dispatcher resolve kwargs byte-identically (D5).
    pub fn resolve_named_arg(&self, value: &str, value_kind: &str) -> String {
        resolve_named_arg_value(value, value_kind, &self.vars)
    }

    /// Number of variables currently set.
    pub fn var_count(&self) -> usize {
        self.vars.len()
    }

    /// The user-meaningful bindings — every variable that is not a
    /// runner built-in ([`BUILTIN_VARS`]): `let` bindings and step
    /// results keyed by step name. These are the columns a `persist` /
    /// `mutate` into a postgresql-backed `axonstore` writes as a row
    /// (Fase 35.e). Sorted by name for deterministic SQL.
    pub fn user_bindings(&self) -> Vec<(String, String)> {
        let mut out: Vec<(String, String)> = self
            .vars
            .iter()
            .filter(|(k, _)| !BUILTIN_VARS.contains(&k.as_str()))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }
}

/// §Fase 35.o — Interpolate `${name}` / `$name` references in `text`
/// against an arbitrary variable map. Extracted from
/// [`ExecContext::interpolate`] so both execution paths — the sync
/// runner (`ExecContext.vars`) and the streaming dispatcher
/// (`DispatchCtx.let_bindings`) — interpolate `persist` field values
/// with byte-identical semantics (D5: the two paths never diverge).
/// Unknown variables are left literal.
/// §Fase 66 (Q1) — resolve a `${...}` variable reference, supporting dotted
/// FIELD-ACCESS on a binding whose value is a JSON object (`${e.to_id}` where
/// `e` is a `for e in List<Record>` loop element).
///
/// Resolution order (back-compatible — the dotted path only fires on a miss):
/// 1. EXACT key lookup (`vars.get("e.to_id")`) — preserves any literal dotted
///    key a flow might have bound, and is the only path for plain `${name}`.
/// 2. If the key contains `.` and the BASE segment (before the first `.`)
///    resolves to a JSON object, walk the remaining `.field` path into it and
///    render the leaf (a JSON string yields its inner text; any other JSON
///    value yields its compact form). A non-JSON base, a missing field, or a
///    non-object intermediate falls through to `None` (the caller keeps the
///    `${…}` literal, exactly as for an unknown plain variable).
fn resolve_dotted_var(vars: &HashMap<String, String>, key: &str) -> Option<String> {
    if let Some(val) = vars.get(key) {
        return Some(val.clone());
    }
    let (base, rest) = key.split_once('.')?;
    let base_val = vars.get(base)?;
    let mut cur: serde_json::Value = serde_json::from_str(base_val).ok()?;
    for field in rest.split('.') {
        cur = match cur {
            serde_json::Value::Object(mut m) => m.remove(field)?,
            _ => return None,
        };
    }
    Some(match cur {
        serde_json::Value::String(s) => s,
        other => other.to_string(),
    })
}

pub fn interpolate_vars(text: &str, vars: &HashMap<String, String>) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;

    while i < bytes.len() {
        if bytes[i] == b'$' && i + 1 < bytes.len() {
            if bytes[i + 1] == b'{' {
                // ${name} form — incl. §66 dotted field-access (${e.field}).
                if let Some(close) = text[i + 2..].find('}') {
                    let var_name = &text[i + 2..i + 2 + close];
                    if let Some(val) = resolve_dotted_var(vars, var_name) {
                        out.push_str(&val);
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
                if let Some(val) = vars.get(var_name) {
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

/// §Fase 60 — resolve a `use Tool(k = v)` keyword-argument VALUE against the
/// runtime bindings, by its frontend-classified `value_kind`:
///
/// - `"reference"` — a bare identifier (`company`), a `let` name, or a
///   `Step.output` — resolved by binding lookup, mirroring the `let` reference
///   handler ([`crate::flow_dispatcher::orchestration`]). Steps bind their output
///   under their bare name, so a trailing `.output` maps to the step-name key.
///   An unbound reference yields the empty string (the type-checker §60.c rejects
///   unknown references at compile time, so a type-checked program never hits
///   this) — never a silent passthrough of the literal name (the pre-60 bug).
/// - anything else (`"literal"`) — `${…}` / `$name` interpolation, as before.
///
/// Shared by both dispatch paths (sync runner + streaming dispatcher) so kwarg
/// value resolution is byte-identical (D5).
pub fn resolve_named_arg_value(
    value: &str,
    value_kind: &str,
    vars: &HashMap<String, String>,
) -> String {
    if value_kind == "reference" {
        vars.get(value)
            .or_else(|| value.strip_suffix(".output").and_then(|step| vars.get(step)))
            .cloned()
            .unwrap_or_default()
    } else {
        interpolate_vars(value, vars)
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── §Fase 60 — resolve_named_arg_value ──────────────────────────────────

    fn bindings() -> HashMap<String, String> {
        let mut m = HashMap::new();
        m.insert("user_input".to_string(), "analiza https://acme.com".to_string());
        m.insert("company".to_string(), "Acme".to_string());
        // A step's output is bound under its (bare) step name in both paths.
        m.insert("ExtractUrl".to_string(), "https://acme.com".to_string());
        m
    }

    #[test]
    fn reference_resolves_bare_flow_param() {
        // The pre-60 bug: a bare identifier was passed literally. Now it resolves.
        assert_eq!(
            resolve_named_arg_value("company", "reference", &bindings()),
            "Acme"
        );
    }

    #[test]
    fn reference_resolves_step_output_dotted_to_step_name_key() {
        // `ExtractUrl.output` → strip `.output` → the step-name binding.
        assert_eq!(
            resolve_named_arg_value("ExtractUrl.output", "reference", &bindings()),
            "https://acme.com"
        );
    }

    #[test]
    fn reference_resolves_bare_step_name() {
        assert_eq!(
            resolve_named_arg_value("ExtractUrl", "reference", &bindings()),
            "https://acme.com"
        );
    }

    #[test]
    fn reference_unbound_is_empty_not_literal_name() {
        // D6 — honest empty, never the literal name passthrough (the old bug).
        assert_eq!(resolve_named_arg_value("nope", "reference", &bindings()), "");
    }

    #[test]
    fn literal_keeps_interpolation_and_verbatim() {
        // A `"literal"` value keeps `${…}` interpolation (back-compat, D5).
        assert_eq!(
            resolve_named_arg_value("${company}", "literal", &bindings()),
            "Acme"
        );
        // A bare literal string is verbatim (NOT a binding lookup).
        assert_eq!(
            resolve_named_arg_value("Acme", "literal", &bindings()),
            "Acme"
        );
    }

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

    #[test]
    fn user_bindings_excludes_builtins() {
        let mut ctx = ExecContext::new("F", "P", 0);
        ctx.set_step("Gather", "step", 0);
        ctx.set_result("Gather", "data");
        ctx.set("tenant_id", "acme");
        // Built-ins (flow_name, persona_name, unit_index, result,
        // step_name, step_type, step_index) are excluded; only the
        // `let`/result bindings remain, sorted by name.
        let bindings = ctx.user_bindings();
        assert_eq!(
            bindings,
            vec![
                ("Gather".to_string(), "data".to_string()),
                ("tenant_id".to_string(), "acme".to_string()),
            ]
        );
    }

    #[test]
    fn user_bindings_empty_for_fresh_context() {
        let ctx = ExecContext::new("F", "P", 0);
        assert!(ctx.user_bindings().is_empty());
    }

    // ── §Fase 66 (Q1) — dotted field-access interpolation ───────────────

    #[test]
    fn interpolate_resolves_dotted_field_of_a_json_object_binding() {
        // The `for e in List<Record>` element: `e` binds to a JSON object;
        // `${e.to_id}` must resolve to the field's inner string value (not the
        // literal `${e.to_id}`, the pre-§66 behavior the kivi brief #27 hit).
        let mut vars = HashMap::new();
        vars.insert(
            "e".to_string(),
            r#"{"to_id":"abc-123","etype":"cite","weight":0.9}"#.to_string(),
        );
        assert_eq!(
            interpolate_vars("${e.to_id}", &vars),
            "abc-123",
            "dotted field-access must resolve the JSON object's field"
        );
        assert_eq!(interpolate_vars("${e.etype}", &vars), "cite");
        // A numeric leaf renders as its compact JSON form.
        assert_eq!(interpolate_vars("${e.weight}", &vars), "0.9");
        // Mixed with a literal + a plain var.
        vars.insert("tid".to_string(), "T1".to_string());
        assert_eq!(
            interpolate_vars("row ${tid}/${e.to_id}", &vars),
            "row T1/abc-123"
        );
    }

    #[test]
    fn interpolate_dotted_misses_stay_literal_and_exact_keys_win() {
        let mut vars = HashMap::new();
        // Base is not JSON → keep the literal (never panics, never half-resolves).
        vars.insert("e".to_string(), "not json".to_string());
        assert_eq!(interpolate_vars("${e.to_id}", &vars), "${e.to_id}");
        // Unknown base → literal.
        assert_eq!(interpolate_vars("${missing.x}", &vars), "${missing.x}");
        // Missing field on a valid object → literal.
        vars.insert("o".to_string(), r#"{"a":"1"}"#.to_string());
        assert_eq!(interpolate_vars("${o.b}", &vars), "${o.b}");
        // Back-compat: an EXACT dotted key (a literal binding) still wins over
        // the JSON walk.
        vars.insert("o.b".to_string(), "exact".to_string());
        assert_eq!(interpolate_vars("${o.b}", &vars), "exact");
        // A plain (non-dotted) var is unchanged.
        assert_eq!(interpolate_vars("${o}", &vars), r#"{"a":"1"}"#);
    }
}
