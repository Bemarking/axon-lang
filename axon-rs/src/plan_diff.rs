//! Plan Diff — compare two exported execution plans.
//!
//! Reads two plan JSON files (produced by `axon run --export-plan`) and
//! produces a structured diff showing what changed between them:
//!   - Added / removed / modified flows (units)
//!   - Added / removed / modified steps within matching flows
//!   - Changed prompts, step types, dependencies
//!   - Changed tool registry
//!   - Changed dependency graph (new parallel groups, unresolved refs)
//!
//! Usage:
//!   axon diff plan_a.json plan_b.json
//!   axon diff plan_a.json plan_b.json --json
//!
//! Exit codes:
//!   0 — plans are identical
//!   1 — plans differ
//!   2 — I/O or parse error

use std::collections::{HashMap, HashSet};
use std::io::IsTerminal;

// ── Diff result types ────────────────────────────────────────────────────

/// Top-level diff between two plans.
#[derive(Debug, Clone, serde::Serialize)]
pub struct PlanDiff {
    /// Whether the plans are identical.
    pub identical: bool,
    /// Summary of changes.
    pub summary: DiffSummary,
    /// Per-unit diffs (only for units that exist in at least one plan).
    pub units: Vec<UnitDiff>,
    /// Tool registry changes.
    pub tools: ToolsDiff,
    /// Dependency graph changes.
    pub dependencies: DepsDiff,
}

/// Aggregate change counts.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DiffSummary {
    pub units_added: usize,
    pub units_removed: usize,
    pub units_modified: usize,
    pub units_unchanged: usize,
    pub steps_added: usize,
    pub steps_removed: usize,
    pub steps_modified: usize,
    pub total_changes: usize,
}

/// Diff for a single execution unit (flow).
#[derive(Debug, Clone, serde::Serialize)]
pub struct UnitDiff {
    pub flow_name: String,
    pub status: ChangeStatus,
    /// Changed fields at unit level (persona, context, effort, anchors).
    pub field_changes: Vec<FieldChange>,
    /// Per-step diffs within this unit.
    pub steps: Vec<StepDiff>,
}

/// Diff for a single step.
#[derive(Debug, Clone, serde::Serialize)]
pub struct StepDiff {
    pub step_name: String,
    pub status: ChangeStatus,
    /// Changed fields (type, prompt, tool_argument, dependencies, etc.).
    pub field_changes: Vec<FieldChange>,
}

/// A single field-level change.
#[derive(Debug, Clone, serde::Serialize)]
pub struct FieldChange {
    pub field: String,
    pub old_value: String,
    pub new_value: String,
}

/// Tool registry diff.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ToolsDiff {
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub total_before: usize,
    pub total_after: usize,
}

/// Dependency graph diff.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DepsDiff {
    pub max_depth_before: usize,
    pub max_depth_after: usize,
    pub parallel_groups_before: usize,
    pub parallel_groups_after: usize,
    pub unresolved_before: usize,
    pub unresolved_after: usize,
}

/// Change classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ChangeStatus {
    Added,
    Removed,
    Modified,
    Unchanged,
}

// ── Core diff engine ─────────────────────────────────────────────────────

/// Compare two plan JSON values and produce a structured diff.
pub fn diff_plans(old: &serde_json::Value, new: &serde_json::Value) -> PlanDiff {
    let units = diff_units(old, new);
    let tools = diff_tools(old, new);
    let dependencies = diff_deps(old, new);

    let mut summary = DiffSummary {
        units_added: 0,
        units_removed: 0,
        units_modified: 0,
        units_unchanged: 0,
        steps_added: 0,
        steps_removed: 0,
        steps_modified: 0,
        total_changes: 0,
    };

    for u in &units {
        match u.status {
            ChangeStatus::Added => {
                summary.units_added += 1;
                summary.steps_added += u.steps.len();
            }
            ChangeStatus::Removed => {
                summary.units_removed += 1;
                summary.steps_removed += u.steps.len();
            }
            ChangeStatus::Modified => {
                summary.units_modified += 1;
                for s in &u.steps {
                    match s.status {
                        ChangeStatus::Added => summary.steps_added += 1,
                        ChangeStatus::Removed => summary.steps_removed += 1,
                        ChangeStatus::Modified => summary.steps_modified += 1,
                        ChangeStatus::Unchanged => {}
                    }
                }
            }
            ChangeStatus::Unchanged => summary.units_unchanged += 1,
        }
    }

    summary.total_changes = summary.units_added
        + summary.units_removed
        + summary.steps_added
        + summary.steps_removed
        + summary.steps_modified
        + summary.units_modified
        + tools.added.len()
        + tools.removed.len();

    let identical = summary.total_changes == 0;

    PlanDiff {
        identical,
        summary,
        units,
        tools,
        dependencies,
    }
}

/// Compare units (flows) between two plans.
fn diff_units(old: &serde_json::Value, new: &serde_json::Value) -> Vec<UnitDiff> {
    let old_units = extract_units(old);
    let new_units = extract_units(new);

    let old_names: HashSet<&str> = old_units.keys().copied().collect();
    let new_names: HashSet<&str> = new_units.keys().copied().collect();

    let mut diffs = Vec::new();

    // Removed units
    for &name in old_names.difference(&new_names) {
        let old_u = &old_units[name];
        let steps: Vec<StepDiff> = extract_step_names(old_u)
            .into_iter()
            .map(|s| StepDiff {
                step_name: s,
                status: ChangeStatus::Removed,
                field_changes: Vec::new(),
            })
            .collect();
        diffs.push(UnitDiff {
            flow_name: name.to_string(),
            status: ChangeStatus::Removed,
            field_changes: Vec::new(),
            steps,
        });
    }

    // Added units
    for &name in new_names.difference(&old_names) {
        let new_u = &new_units[name];
        let steps: Vec<StepDiff> = extract_step_names(new_u)
            .into_iter()
            .map(|s| StepDiff {
                step_name: s,
                status: ChangeStatus::Added,
                field_changes: Vec::new(),
            })
            .collect();
        diffs.push(UnitDiff {
            flow_name: name.to_string(),
            status: ChangeStatus::Added,
            field_changes: Vec::new(),
            steps,
        });
    }

    // Matching units — compare fields + steps
    for &name in old_names.intersection(&new_names) {
        let old_u = &old_units[name];
        let new_u = &new_units[name];

        let mut field_changes = Vec::new();
        compare_field(old_u, new_u, "persona_name", &mut field_changes);
        compare_field(old_u, new_u, "context_name", &mut field_changes);
        compare_field(old_u, new_u, "effort", &mut field_changes);
        compare_array_field(old_u, new_u, "anchors", &mut field_changes);

        let steps = diff_steps(old_u, new_u);

        let has_changes = !field_changes.is_empty()
            || steps.iter().any(|s| s.status != ChangeStatus::Unchanged);

        diffs.push(UnitDiff {
            flow_name: name.to_string(),
            status: if has_changes {
                ChangeStatus::Modified
            } else {
                ChangeStatus::Unchanged
            },
            field_changes,
            steps,
        });
    }

    diffs.sort_by(|a, b| a.flow_name.cmp(&b.flow_name));
    diffs
}

/// Compare steps within two matching units.
fn diff_steps(old_unit: &serde_json::Value, new_unit: &serde_json::Value) -> Vec<StepDiff> {
    let old_steps = extract_steps_map(old_unit);
    let new_steps = extract_steps_map(new_unit);

    let old_names: HashSet<&str> = old_steps.keys().copied().collect();
    let new_names: HashSet<&str> = new_steps.keys().copied().collect();

    let mut diffs = Vec::new();

    // Removed steps
    for &name in old_names.difference(&new_names) {
        diffs.push(StepDiff {
            step_name: name.to_string(),
            status: ChangeStatus::Removed,
            field_changes: Vec::new(),
        });
    }

    // Added steps
    for &name in new_names.difference(&old_names) {
        diffs.push(StepDiff {
            step_name: name.to_string(),
            status: ChangeStatus::Added,
            field_changes: Vec::new(),
        });
    }

    // Matching steps — compare fields
    for &name in old_names.intersection(&new_names) {
        let old_s = &old_steps[name];
        let new_s = &new_steps[name];

        let mut field_changes = Vec::new();
        compare_field(old_s, new_s, "step_type", &mut field_changes);
        compare_field(old_s, new_s, "prompt_preview", &mut field_changes);
        compare_field(old_s, new_s, "tool_argument", &mut field_changes);
        compare_field(old_s, new_s, "memory_expression", &mut field_changes);
        compare_array_field(old_s, new_s, "depends_on", &mut field_changes);

        let status = if field_changes.is_empty() {
            ChangeStatus::Unchanged
        } else {
            ChangeStatus::Modified
        };

        diffs.push(StepDiff {
            step_name: name.to_string(),
            status,
            field_changes,
        });
    }

    diffs.sort_by(|a, b| a.step_name.cmp(&b.step_name));
    diffs
}

/// Compare tool registries between two plans.
fn diff_tools(old: &serde_json::Value, new: &serde_json::Value) -> ToolsDiff {
    let old_names = extract_tool_names(old);
    let new_names = extract_tool_names(new);

    let old_set: HashSet<&str> = old_names.iter().map(|s| s.as_str()).collect();
    let new_set: HashSet<&str> = new_names.iter().map(|s| s.as_str()).collect();

    let added: Vec<String> = new_set.difference(&old_set).map(|s| s.to_string()).collect();
    let removed: Vec<String> = old_set.difference(&new_set).map(|s| s.to_string()).collect();

    let total_before = old["tools"]["total"].as_u64().unwrap_or(0) as usize;
    let total_after = new["tools"]["total"].as_u64().unwrap_or(0) as usize;

    ToolsDiff {
        added,
        removed,
        total_before,
        total_after,
    }
}

/// Compare dependency graphs between two plans.
fn diff_deps(old: &serde_json::Value, new: &serde_json::Value) -> DepsDiff {
    let od = &old["dependencies"];
    let nd = &new["dependencies"];

    DepsDiff {
        max_depth_before: od["max_depth"].as_u64().unwrap_or(0) as usize,
        max_depth_after: nd["max_depth"].as_u64().unwrap_or(0) as usize,
        parallel_groups_before: od["parallel_groups"]
            .as_array()
            .map(|a| a.len())
            .unwrap_or(0),
        parallel_groups_after: nd["parallel_groups"]
            .as_array()
            .map(|a| a.len())
            .unwrap_or(0),
        unresolved_before: od["unresolved_refs"]
            .as_array()
            .map(|a| a.len())
            .unwrap_or(0),
        unresolved_after: nd["unresolved_refs"]
            .as_array()
            .map(|a| a.len())
            .unwrap_or(0),
    }
}

// ── JSON extraction helpers ──────────────────────────────────────────────

fn extract_units(plan: &serde_json::Value) -> HashMap<&str, &serde_json::Value> {
    let mut map = HashMap::new();
    if let Some(units) = plan["units"].as_array() {
        for u in units {
            if let Some(name) = u["flow_name"].as_str() {
                map.insert(name, u);
            }
        }
    }
    map
}

fn extract_step_names(unit: &serde_json::Value) -> Vec<String> {
    unit["steps"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|s| s["name"].as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

fn extract_steps_map(unit: &serde_json::Value) -> HashMap<&str, &serde_json::Value> {
    let mut map = HashMap::new();
    if let Some(steps) = unit["steps"].as_array() {
        for s in steps {
            if let Some(name) = s["name"].as_str() {
                map.insert(name, s);
            }
        }
    }
    map
}

fn extract_tool_names(plan: &serde_json::Value) -> Vec<String> {
    plan["tools"]["registered"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|t| t["name"].as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

fn compare_field(
    old: &serde_json::Value,
    new: &serde_json::Value,
    field: &str,
    changes: &mut Vec<FieldChange>,
) {
    let old_val = json_str(&old[field]);
    let new_val = json_str(&new[field]);
    if old_val != new_val {
        changes.push(FieldChange {
            field: field.to_string(),
            old_value: old_val,
            new_value: new_val,
        });
    }
}

fn compare_array_field(
    old: &serde_json::Value,
    new: &serde_json::Value,
    field: &str,
    changes: &mut Vec<FieldChange>,
) {
    let old_val = old[field].to_string();
    let new_val = new[field].to_string();
    if old_val != new_val {
        changes.push(FieldChange {
            field: field.to_string(),
            old_value: old_val,
            new_value: new_val,
        });
    }
}

fn json_str(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Null => String::new(),
        other => other.to_string(),
    }
}

// ── CLI entry point ──────────────────────────────────────────────────────

/// Run the diff command. Returns exit code.
pub fn run_diff(file_a: &str, file_b: &str, json_output: bool) -> i32 {
    let use_color = !json_output && std::io::stdout().is_terminal();

    // Read files
    let content_a = match std::fs::read_to_string(file_a) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Cannot read '{}': {e}", file_a);
            return 2;
        }
    };
    let content_b = match std::fs::read_to_string(file_b) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Cannot read '{}': {e}", file_b);
            return 2;
        }
    };

    // Parse JSON
    let plan_a: serde_json::Value = match serde_json::from_str(&content_a) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("Invalid JSON in '{}': {e}", file_a);
            return 2;
        }
    };
    let plan_b: serde_json::Value = match serde_json::from_str(&content_b) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("Invalid JSON in '{}': {e}", file_b);
            return 2;
        }
    };

    let diff = diff_plans(&plan_a, &plan_b);

    if json_output {
        println!("{}", serde_json::to_string_pretty(&diff).unwrap());
    } else {
        print_diff(&diff, file_a, file_b, use_color);
    }

    if diff.identical { 0 } else { 1 }
}

// ── Human-readable output ────────────────────────────────────────────────

fn print_diff(diff: &PlanDiff, file_a: &str, file_b: &str, use_color: bool) {
    let red = |s: &str| if use_color { format!("\x1b[1;31m{s}\x1b[0m") } else { s.to_string() };
    let green = |s: &str| if use_color { format!("\x1b[1;32m{s}\x1b[0m") } else { s.to_string() };
    let yellow = |s: &str| if use_color { format!("\x1b[1;33m{s}\x1b[0m") } else { s.to_string() };
    let dim = |s: &str| if use_color { format!("\x1b[2m{s}\x1b[0m") } else { s.to_string() };
    let bold = |s: &str| if use_color { format!("\x1b[1m{s}\x1b[0m") } else { s.to_string() };

    println!(
        "{} {} → {}",
        bold("Plan Diff:"),
        dim(file_a),
        dim(file_b),
    );

    if diff.identical {
        println!("  {} Plans are identical.", green("✓"));
        return;
    }

    // Summary line
    let s = &diff.summary;
    println!(
        "  {} changes: {} unit(s) added, {} removed, {} modified; {} step(s) added, {} removed, {} modified",
        yellow(&format!("{}", s.total_changes)),
        s.units_added,
        s.units_removed,
        s.units_modified,
        s.steps_added,
        s.steps_removed,
        s.steps_modified,
    );

    // Unit diffs
    for u in &diff.units {
        match u.status {
            ChangeStatus::Added => {
                println!("\n  {} flow {}", green("+ "), bold(&u.flow_name));
                for step in &u.steps {
                    println!("    {} step {}", green("+"), step.step_name);
                }
            }
            ChangeStatus::Removed => {
                println!("\n  {} flow {}", red("- "), bold(&u.flow_name));
                for step in &u.steps {
                    println!("    {} step {}", red("-"), step.step_name);
                }
            }
            ChangeStatus::Modified => {
                println!("\n  {} flow {}", yellow("~ "), bold(&u.flow_name));
                for fc in &u.field_changes {
                    println!(
                        "    {} {}: {} → {}",
                        yellow("~"),
                        fc.field,
                        red(&fc.old_value),
                        green(&fc.new_value),
                    );
                }
                for step in &u.steps {
                    match step.status {
                        ChangeStatus::Added => {
                            println!("    {} step {}", green("+"), step.step_name);
                        }
                        ChangeStatus::Removed => {
                            println!("    {} step {}", red("-"), step.step_name);
                        }
                        ChangeStatus::Modified => {
                            println!("    {} step {}", yellow("~"), step.step_name);
                            for fc in &step.field_changes {
                                println!(
                                    "      {} {}: {} → {}",
                                    yellow("~"),
                                    fc.field,
                                    red(&fc.old_value),
                                    green(&fc.new_value),
                                );
                            }
                        }
                        ChangeStatus::Unchanged => {}
                    }
                }
            }
            ChangeStatus::Unchanged => {}
        }
    }

    // Tool changes
    if !diff.tools.added.is_empty() || !diff.tools.removed.is_empty() {
        println!("\n  {}", bold("Tools:"));
        for t in &diff.tools.added {
            println!("    {} {}", green("+"), t);
        }
        for t in &diff.tools.removed {
            println!("    {} {}", red("-"), t);
        }
    }

    // Dependency changes
    let d = &diff.dependencies;
    if d.max_depth_before != d.max_depth_after
        || d.parallel_groups_before != d.parallel_groups_after
        || d.unresolved_before != d.unresolved_after
    {
        println!("\n  {}", bold("Dependencies:"));
        if d.max_depth_before != d.max_depth_after {
            println!(
                "    max_depth: {} → {}",
                d.max_depth_before, d.max_depth_after,
            );
        }
        if d.parallel_groups_before != d.parallel_groups_after {
            println!(
                "    parallel_groups: {} → {}",
                d.parallel_groups_before, d.parallel_groups_after,
            );
        }
        if d.unresolved_before != d.unresolved_after {
            println!(
                "    unresolved_refs: {} → {}",
                d.unresolved_before, d.unresolved_after,
            );
        }
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn make_plan(units: serde_json::Value, tools: serde_json::Value, deps: serde_json::Value) -> serde_json::Value {
        json!({
            "_schema": { "type": "axon.plan", "version": "1.0.0" },
            "units": units,
            "tools": tools,
            "dependencies": deps,
        })
    }

    fn simple_plan() -> serde_json::Value {
        make_plan(
            json!([{
                "flow_name": "Flow1",
                "persona_name": "P1",
                "context_name": "default",
                "effort": "medium",
                "anchor_count": 1,
                "anchors": ["NoHallucination"],
                "steps": [
                    { "name": "S1", "step_type": "step", "prompt_preview": "do something", "depends_on": [], "is_root": true },
                    { "name": "S2", "step_type": "step", "prompt_preview": "use $S1", "depends_on": ["S1"], "is_root": false },
                ]
            }]),
            json!({ "total": 2, "builtin": ["Calculator"], "program": [], "registered": [
                { "name": "Calculator", "provider": "native", "source": "builtin" }
            ]}),
            json!({ "max_depth": 1, "parallel_groups": [["S1"]], "unresolved_refs": [] }),
        )
    }

    #[test]
    fn identical_plans() {
        let plan = simple_plan();
        let diff = diff_plans(&plan, &plan);
        assert!(diff.identical);
        assert_eq!(diff.summary.total_changes, 0);
        assert_eq!(diff.summary.units_unchanged, 1);
    }

    #[test]
    fn added_flow() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"].as_array_mut().unwrap().push(json!({
            "flow_name": "Flow2",
            "persona_name": "P2",
            "context_name": "default",
            "effort": "low",
            "anchor_count": 0,
            "anchors": [],
            "steps": [
                { "name": "A1", "step_type": "step", "prompt_preview": "new step", "depends_on": [], "is_root": true },
            ]
        }));

        let diff = diff_plans(&old, &new);
        assert!(!diff.identical);
        assert_eq!(diff.summary.units_added, 1);
        assert_eq!(diff.summary.steps_added, 1);

        let added = diff.units.iter().find(|u| u.flow_name == "Flow2").unwrap();
        assert_eq!(added.status, ChangeStatus::Added);
    }

    #[test]
    fn removed_flow() {
        let old = simple_plan();
        let new = make_plan(json!([]), json!({ "total": 0, "builtin": [], "program": [], "registered": [] }), json!({ "max_depth": 0, "parallel_groups": [], "unresolved_refs": [] }));

        let diff = diff_plans(&old, &new);
        assert!(!diff.identical);
        assert_eq!(diff.summary.units_removed, 1);
        assert_eq!(diff.summary.steps_removed, 2);
    }

    #[test]
    fn modified_step_prompt() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"][0]["steps"][0]["prompt_preview"] = json!("do something different");

        let diff = diff_plans(&old, &new);
        assert!(!diff.identical);
        assert_eq!(diff.summary.units_modified, 1);
        assert_eq!(diff.summary.steps_modified, 1);

        let flow1 = diff.units.iter().find(|u| u.flow_name == "Flow1").unwrap();
        assert_eq!(flow1.status, ChangeStatus::Modified);

        let s1 = flow1.steps.iter().find(|s| s.step_name == "S1").unwrap();
        assert_eq!(s1.status, ChangeStatus::Modified);
        assert_eq!(s1.field_changes[0].field, "prompt_preview");
    }

    #[test]
    fn added_step_in_existing_flow() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"][0]["steps"].as_array_mut().unwrap().push(json!({
            "name": "S3",
            "step_type": "use_tool",
            "prompt_preview": "new tool step",
            "depends_on": ["S2"],
            "is_root": false,
        }));

        let diff = diff_plans(&old, &new);
        assert!(!diff.identical);
        assert_eq!(diff.summary.steps_added, 1);

        let flow1 = diff.units.iter().find(|u| u.flow_name == "Flow1").unwrap();
        let s3 = flow1.steps.iter().find(|s| s.step_name == "S3").unwrap();
        assert_eq!(s3.status, ChangeStatus::Added);
    }

    #[test]
    fn changed_persona() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"][0]["persona_name"] = json!("P2");

        let diff = diff_plans(&old, &new);
        assert!(!diff.identical);

        let flow1 = diff.units.iter().find(|u| u.flow_name == "Flow1").unwrap();
        assert_eq!(flow1.status, ChangeStatus::Modified);
        assert!(flow1.field_changes.iter().any(|f| f.field == "persona_name"));
    }

    #[test]
    fn tool_registry_changes() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["tools"]["registered"].as_array_mut().unwrap().push(json!({
            "name": "WebSearch", "provider": "brave", "source": "program"
        }));
        new["tools"]["total"] = json!(3);

        let diff = diff_plans(&old, &new);
        assert_eq!(diff.tools.added, vec!["WebSearch"]);
        assert!(diff.tools.removed.is_empty());
        assert_eq!(diff.tools.total_before, 2);
        assert_eq!(diff.tools.total_after, 3);
    }

    #[test]
    fn dependency_changes() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["dependencies"]["max_depth"] = json!(3);
        new["dependencies"]["parallel_groups"] = json!([["S1", "S2"], ["S3"]]);

        let diff = diff_plans(&old, &new);
        assert_eq!(diff.dependencies.max_depth_before, 1);
        assert_eq!(diff.dependencies.max_depth_after, 3);
        assert_eq!(diff.dependencies.parallel_groups_before, 1);
        assert_eq!(diff.dependencies.parallel_groups_after, 2);
    }

    #[test]
    fn step_type_change() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"][0]["steps"][0]["step_type"] = json!("use_tool");

        let diff = diff_plans(&old, &new);
        let flow1 = diff.units.iter().find(|u| u.flow_name == "Flow1").unwrap();
        let s1 = flow1.steps.iter().find(|s| s.step_name == "S1").unwrap();
        assert_eq!(s1.status, ChangeStatus::Modified);
        assert!(s1.field_changes.iter().any(|f| f.field == "step_type"));
    }

    #[test]
    fn dependency_list_change() {
        let old = simple_plan();
        let mut new = simple_plan();
        new["units"][0]["steps"][1]["depends_on"] = json!(["S1", "S3"]);

        let diff = diff_plans(&old, &new);
        let flow1 = diff.units.iter().find(|u| u.flow_name == "Flow1").unwrap();
        let s2 = flow1.steps.iter().find(|s| s.step_name == "S2").unwrap();
        assert_eq!(s2.status, ChangeStatus::Modified);
        assert!(s2.field_changes.iter().any(|f| f.field == "depends_on"));
    }

    #[test]
    fn run_diff_file_not_found() {
        assert_eq!(run_diff("nonexistent_a.json", "nonexistent_b.json", false), 2);
    }

    #[test]
    fn run_diff_identical_files() {
        let tmp = std::env::temp_dir().join("axon_diff_test.json");
        let plan = simple_plan();
        std::fs::write(&tmp, serde_json::to_string(&plan).unwrap()).unwrap();

        let path = tmp.to_str().unwrap();
        assert_eq!(run_diff(path, path, true), 0);
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn run_diff_different_files() {
        let tmp_a = std::env::temp_dir().join("axon_diff_a.json");
        let tmp_b = std::env::temp_dir().join("axon_diff_b.json");

        let plan_a = simple_plan();
        let mut plan_b = simple_plan();
        plan_b["units"][0]["steps"][0]["prompt_preview"] = json!("changed");

        std::fs::write(&tmp_a, serde_json::to_string(&plan_a).unwrap()).unwrap();
        std::fs::write(&tmp_b, serde_json::to_string(&plan_b).unwrap()).unwrap();

        assert_eq!(run_diff(tmp_a.to_str().unwrap(), tmp_b.to_str().unwrap(), true), 1);

        let _ = std::fs::remove_file(tmp_a);
        let _ = std::fs::remove_file(tmp_b);
    }

    #[test]
    fn change_status_serializes() {
        assert_eq!(
            serde_json::to_string(&ChangeStatus::Added).unwrap(),
            "\"added\"",
        );
        assert_eq!(
            serde_json::to_string(&ChangeStatus::Modified).unwrap(),
            "\"modified\"",
        );
    }
}
