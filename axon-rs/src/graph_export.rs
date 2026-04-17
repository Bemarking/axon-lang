//! Graph Export — render dependency graphs as DOT (Graphviz) or Mermaid.
//!
//! Takes a compiled AXON program's step dependency graph and produces
//! visual diagram source in standard formats:
//!   - DOT: for Graphviz (svg, png, pdf via `dot` command)
//!   - Mermaid: for GitHub markdown, Mermaid Live, documentation
//!
//! Nodes are colored by wave depth (parallel execution tier).
//! Parallel groups are highlighted with subgraph clusters.
//!
//! Usage:
//!   axon graph program.axon                 — DOT output (default)
//!   axon graph program.axon --format mermaid — Mermaid output

use std::collections::HashMap;

use crate::step_deps::{self, DependencyGraph, StepInfo};

// ── Graph from IR ───────────────────────────────────────────────────────

/// Build step dependency graph from IR program.
pub fn graph_from_ir(ir: &crate::ir_nodes::IRProgram) -> Vec<(String, DependencyGraph)> {
    let mut results = Vec::new();

    for flow in &ir.flows {
        let steps: Vec<StepInfo> = flow.steps.iter().filter_map(|node| {
            extract_step_info(node)
        }).collect();

        if !steps.is_empty() {
            let graph = step_deps::analyze(&steps);
            results.push((flow.name.clone(), graph));
        }
    }

    results
}

/// Extract StepInfo from an IRFlowNode.
fn extract_step_info(node: &crate::ir_nodes::IRFlowNode) -> Option<StepInfo> {
    use crate::ir_nodes::IRFlowNode;
    match node {
        IRFlowNode::Step(s) => Some(StepInfo {
            name: s.name.clone(),
            step_type: "step".into(),
            user_prompt: s.ask.clone(),
            argument: s.given.clone(),
        }),
        IRFlowNode::UseTool(s) => Some(StepInfo {
            name: s.tool_name.clone(),
            step_type: "use_tool".into(),
            user_prompt: String::new(),
            argument: s.argument.clone(),
        }),
        IRFlowNode::Probe(s) => Some(StepInfo {
            name: format!("probe_{}", s.target),
            step_type: "probe".into(),
            user_prompt: s.target.clone(),
            argument: String::new(),
        }),
        IRFlowNode::Reason(s) => Some(StepInfo {
            name: format!("reason_{}", s.target),
            step_type: "reason".into(),
            user_prompt: s.target.clone(),
            argument: String::new(),
        }),
        IRFlowNode::Validate(s) => Some(StepInfo {
            name: format!("validate_{}", s.target),
            step_type: "validate".into(),
            user_prompt: s.target.clone(),
            argument: s.rule.clone(),
        }),
        IRFlowNode::Refine(s) => Some(StepInfo {
            name: format!("refine_{}", s.target),
            step_type: "refine".into(),
            user_prompt: s.target.clone(),
            argument: String::new(),
        }),
        IRFlowNode::Remember(s) => Some(StepInfo {
            name: format!("remember_{}", s.memory_target),
            step_type: "remember".into(),
            user_prompt: String::new(),
            argument: s.expression.clone(),
        }),
        IRFlowNode::Recall(s) => Some(StepInfo {
            name: format!("recall_{}", s.memory_source),
            step_type: "recall".into(),
            user_prompt: String::new(),
            argument: s.query.clone(),
        }),
        _ => None, // Control flow nodes don't participate in dep analysis
    }
}

// ── DOT export ──────────────────────────────────────────────────────────

/// Wave colors for depth-based coloring (pastel palette).
const WAVE_COLORS: &[&str] = &[
    "#A8D8EA", // wave 0 — light blue
    "#AA96DA", // wave 1 — light purple
    "#FCBAD3", // wave 2 — light pink
    "#FFD3B6", // wave 3 — light orange
    "#DCEDC1", // wave 4 — light green
    "#F6E6CB", // wave 5 — light yellow
];

fn wave_color(depth: usize) -> &'static str {
    WAVE_COLORS[depth % WAVE_COLORS.len()]
}

/// Export a dependency graph as DOT (Graphviz) format.
pub fn to_dot(flow_name: &str, graph: &DependencyGraph) -> String {
    let mut out = String::new();
    let depths = compute_depths(graph);

    out.push_str(&format!("digraph \"{}\" {{\n", flow_name));
    out.push_str("  rankdir=TB;\n");
    out.push_str("  node [shape=box, style=\"rounded,filled\", fontname=\"Helvetica\"];\n");
    out.push_str("  edge [color=\"#666666\"];\n");
    out.push('\n');

    // Nodes with wave coloring
    for step in &graph.steps {
        let depth = depths.get(&step.name).copied().unwrap_or(0);
        let color = wave_color(depth);
        let label = format!("{}", step.name);
        let tooltip = format!("{} (wave {}, {})", step.name, depth, step.step_type);
        out.push_str(&format!(
            "  \"{}\" [label=\"{}\", fillcolor=\"{}\", tooltip=\"{}\"];\n",
            step.name, label, color, tooltip
        ));
    }
    out.push('\n');

    // Edges
    for step in &graph.steps {
        for dep in &step.depends_on {
            out.push_str(&format!("  \"{}\" -> \"{}\";\n", dep, step.name));
        }
    }

    // Parallel group clusters
    for (i, group) in graph.parallel_groups.iter().enumerate() {
        out.push('\n');
        out.push_str(&format!("  subgraph cluster_parallel_{} {{\n", i));
        out.push_str("    style=dashed;\n");
        out.push_str("    color=\"#999999\";\n");
        out.push_str(&format!("    label=\"parallel wave {}\";\n", i));
        for name in group {
            out.push_str(&format!("    \"{}\";\n", name));
        }
        out.push_str("  }\n");
    }

    out.push_str("}\n");
    out
}

/// Export multiple flow graphs as a single DOT file.
pub fn to_dot_multi(graphs: &[(String, DependencyGraph)]) -> String {
    let mut out = String::new();
    out.push_str("digraph AXON {\n");
    out.push_str("  rankdir=TB;\n");
    out.push_str("  compound=true;\n");
    out.push_str("  node [shape=box, style=\"rounded,filled\", fontname=\"Helvetica\"];\n");
    out.push_str("  edge [color=\"#666666\"];\n");
    out.push('\n');

    for (flow_name, graph) in graphs {
        let depths = compute_depths(graph);
        let prefix = flow_name.replace(' ', "_");

        out.push_str(&format!("  subgraph cluster_{} {{\n", prefix));
        out.push_str(&format!("    label=\"{}\";\n", flow_name));
        out.push_str("    style=solid;\n");
        out.push_str("    color=\"#333333\";\n");
        out.push('\n');

        for step in &graph.steps {
            let depth = depths.get(&step.name).copied().unwrap_or(0);
            let color = wave_color(depth);
            let node_id = format!("{}_{}", prefix, step.name);
            out.push_str(&format!(
                "    \"{}\" [label=\"{}\", fillcolor=\"{}\"];\n",
                node_id, step.name, color
            ));
        }

        for step in &graph.steps {
            for dep in &step.depends_on {
                out.push_str(&format!(
                    "    \"{}_{}\"->\"{}_{}\";\n",
                    prefix, dep, prefix, step.name
                ));
            }
        }

        out.push_str("  }\n\n");
    }

    out.push_str("}\n");
    out
}

// ── Mermaid export ──────────────────────────────────────────────────────

/// Export a dependency graph as Mermaid diagram syntax.
pub fn to_mermaid(flow_name: &str, graph: &DependencyGraph) -> String {
    let mut out = String::new();
    let depths = compute_depths(graph);

    out.push_str(&format!("---\ntitle: {}\n---\n", flow_name));
    out.push_str("graph TD\n");

    // Nodes
    for step in &graph.steps {
        let depth = depths.get(&step.name).copied().unwrap_or(0);
        let shape = match step.step_type.as_str() {
            "use_tool" => format!("{{{{{}}}}} ", step.name), // diamond for tools
            _ => format!("[{}]", step.name),
        };
        out.push_str(&format!("  {}{}:::wave{}\n", step.name, shape, depth % 6));
    }
    out.push('\n');

    // Edges
    for step in &graph.steps {
        for dep in &step.depends_on {
            out.push_str(&format!("  {} --> {}\n", dep, step.name));
        }
    }

    // Parallel annotations
    if !graph.parallel_groups.is_empty() {
        out.push('\n');
        for (i, group) in graph.parallel_groups.iter().enumerate() {
            let names = group.join(" & ");
            out.push_str(&format!("  %% parallel wave {}: {}\n", i, names));
        }
    }

    // Style classes for wave colors
    out.push('\n');
    let mermaid_colors = ["#A8D8EA", "#AA96DA", "#FCBAD3", "#FFD3B6", "#DCEDC1", "#F6E6CB"];
    for (i, color) in mermaid_colors.iter().enumerate() {
        out.push_str(&format!("  classDef wave{} fill:{},stroke:#333,stroke-width:1px\n", i, color));
    }

    out
}

/// Export multiple flow graphs as a single Mermaid diagram.
pub fn to_mermaid_multi(graphs: &[(String, DependencyGraph)]) -> String {
    let mut out = String::new();
    out.push_str("graph TD\n");

    for (flow_name, graph) in graphs {
        let depths = compute_depths(graph);
        let prefix = flow_name.replace(' ', "_");

        out.push_str(&format!("\n  subgraph {}\n", flow_name));

        for step in &graph.steps {
            let depth = depths.get(&step.name).copied().unwrap_or(0);
            let node_id = format!("{}_{}", prefix, step.name);
            out.push_str(&format!("    {}[{}]:::wave{}\n", node_id, step.name, depth % 6));
        }

        for step in &graph.steps {
            for dep in &step.depends_on {
                out.push_str(&format!(
                    "    {}_{} --> {}_{}\n",
                    prefix, dep, prefix, step.name
                ));
            }
        }

        out.push_str("  end\n");
    }

    // Style classes
    out.push('\n');
    let mermaid_colors = ["#A8D8EA", "#AA96DA", "#FCBAD3", "#FFD3B6", "#DCEDC1", "#F6E6CB"];
    for (i, color) in mermaid_colors.iter().enumerate() {
        out.push_str(&format!("  classDef wave{} fill:{},stroke:#333,stroke-width:1px\n", i, color));
    }

    out
}

// ── CLI entry point ─────────────────────────────────────────────────────

/// Compile an .axon file and export its dependency graph.
/// Format: "dot" (default) or "mermaid".
/// Returns exit code: 0 = success, 1 = compile error, 2 = I/O error.
pub fn run_graph(file: &str, format: &str) -> i32 {
    let source = match std::fs::read_to_string(file) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error: failed to read {}: {}", file, e);
            return 2;
        }
    };

    let tokens = match crate::lexer::Lexer::new(&source, file).tokenize() {
        Ok(t) => t,
        Err(e) => {
            eprintln!("error: lex failed: {:?}", e);
            return 1;
        }
    };

    let program = match crate::parser::Parser::new(tokens).parse() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("error: parse failed: {:?}", e);
            return 1;
        }
    };

    let ir = crate::ir_generator::IRGenerator::new().generate(&program);
    let graphs = graph_from_ir(&ir);

    if graphs.is_empty() {
        eprintln!("warning: no flows found in {}", file);
        return 0;
    }

    let output = match format {
        "mermaid" => {
            if graphs.len() == 1 {
                to_mermaid(&graphs[0].0, &graphs[0].1)
            } else {
                to_mermaid_multi(&graphs)
            }
        }
        _ => {
            if graphs.len() == 1 {
                to_dot(&graphs[0].0, &graphs[0].1)
            } else {
                to_dot_multi(&graphs)
            }
        }
    };

    print!("{}", output);
    0
}

// ── Helpers ─────────────────────────────────────────────────────────────

fn compute_depths(graph: &DependencyGraph) -> HashMap<String, usize> {
    let dep_map: HashMap<&str, &crate::step_deps::StepDependency> =
        graph.steps.iter().map(|s| (s.name.as_str(), s)).collect();

    let mut cache: HashMap<String, usize> = HashMap::new();

    fn depth_of(
        name: &str,
        dep_map: &HashMap<&str, &crate::step_deps::StepDependency>,
        cache: &mut HashMap<String, usize>,
    ) -> usize {
        if let Some(&cached) = cache.get(name) {
            return cached;
        }
        let d = match dep_map.get(name) {
            Some(d) => d,
            None => return 0,
        };
        if d.depends_on.is_empty() {
            cache.insert(name.to_string(), 0);
            return 0;
        }
        let max_child = d.depends_on.iter()
            .map(|dep| depth_of(dep, dep_map, cache))
            .max()
            .unwrap_or(0);
        let result = max_child + 1;
        cache.insert(name.to_string(), result);
        result
    }

    for step in &graph.steps {
        depth_of(&step.name, &dep_map, &mut cache);
    }

    cache
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::step_deps::{self, StepInfo};

    fn linear_steps() -> Vec<StepInfo> {
        vec![
            StepInfo { name: "Extract".into(), step_type: "step".into(), user_prompt: "Extract data".into(), argument: String::new() },
            StepInfo { name: "Analyze".into(), step_type: "step".into(), user_prompt: "Analyze ${Extract}".into(), argument: String::new() },
            StepInfo { name: "Report".into(), step_type: "step".into(), user_prompt: "Report on ${Analyze}".into(), argument: String::new() },
        ]
    }

    fn diamond_steps() -> Vec<StepInfo> {
        vec![
            StepInfo { name: "Start".into(), step_type: "step".into(), user_prompt: "Begin".into(), argument: String::new() },
            StepInfo { name: "PathA".into(), step_type: "step".into(), user_prompt: "Process ${Start} A".into(), argument: String::new() },
            StepInfo { name: "PathB".into(), step_type: "use_tool".into(), user_prompt: "Process ${Start} B".into(), argument: String::new() },
            StepInfo { name: "Merge".into(), step_type: "step".into(), user_prompt: "Merge ${PathA} and ${PathB}".into(), argument: String::new() },
        ]
    }

    fn independent_steps() -> Vec<StepInfo> {
        vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "Do A".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "Do B".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "Do C".into(), argument: String::new() },
        ]
    }

    #[test]
    fn dot_contains_digraph() {
        let graph = step_deps::analyze(&linear_steps());
        let dot = to_dot("TestFlow", &graph);
        assert!(dot.starts_with("digraph \"TestFlow\""));
        assert!(dot.contains('}'));
    }

    #[test]
    fn dot_contains_nodes() {
        let graph = step_deps::analyze(&linear_steps());
        let dot = to_dot("F", &graph);
        assert!(dot.contains("\"Extract\""));
        assert!(dot.contains("\"Analyze\""));
        assert!(dot.contains("\"Report\""));
    }

    #[test]
    fn dot_contains_edges() {
        let graph = step_deps::analyze(&linear_steps());
        let dot = to_dot("F", &graph);
        assert!(dot.contains("\"Extract\" -> \"Analyze\""));
        assert!(dot.contains("\"Analyze\" -> \"Report\""));
    }

    #[test]
    fn dot_wave_colors() {
        let graph = step_deps::analyze(&linear_steps());
        let dot = to_dot("F", &graph);
        // Extract is wave 0, Analyze wave 1, Report wave 2
        assert!(dot.contains("#A8D8EA")); // wave 0
        assert!(dot.contains("#AA96DA")); // wave 1
        assert!(dot.contains("#FCBAD3")); // wave 2
    }

    #[test]
    fn dot_parallel_cluster() {
        let graph = step_deps::analyze(&diamond_steps());
        let dot = to_dot("F", &graph);
        assert!(dot.contains("subgraph cluster_parallel_"));
        assert!(dot.contains("parallel wave"));
    }

    #[test]
    fn dot_multi_flows() {
        let g1 = step_deps::analyze(&linear_steps());
        let g2 = step_deps::analyze(&independent_steps());
        let graphs = vec![("Flow1".to_string(), g1), ("Flow2".to_string(), g2)];
        let dot = to_dot_multi(&graphs);

        assert!(dot.starts_with("digraph AXON"));
        assert!(dot.contains("subgraph cluster_Flow1"));
        assert!(dot.contains("subgraph cluster_Flow2"));
        assert!(dot.contains("Flow1_Extract"));
        assert!(dot.contains("Flow2_A"));
    }

    #[test]
    fn mermaid_contains_header() {
        let graph = step_deps::analyze(&linear_steps());
        let m = to_mermaid("TestFlow", &graph);
        assert!(m.contains("title: TestFlow"));
        assert!(m.contains("graph TD"));
    }

    #[test]
    fn mermaid_contains_nodes() {
        let graph = step_deps::analyze(&linear_steps());
        let m = to_mermaid("F", &graph);
        assert!(m.contains("Extract[Extract]"));
        assert!(m.contains("Analyze[Analyze]"));
        assert!(m.contains("Report[Report]"));
    }

    #[test]
    fn mermaid_contains_edges() {
        let graph = step_deps::analyze(&linear_steps());
        let m = to_mermaid("F", &graph);
        assert!(m.contains("Extract --> Analyze"));
        assert!(m.contains("Analyze --> Report"));
    }

    #[test]
    fn mermaid_tool_step_diamond_shape() {
        let graph = step_deps::analyze(&diamond_steps());
        let m = to_mermaid("F", &graph);
        // use_tool steps get diamond shape {{name}}
        assert!(m.contains("PathB{"));
    }

    #[test]
    fn mermaid_wave_classes() {
        let graph = step_deps::analyze(&linear_steps());
        let m = to_mermaid("F", &graph);
        assert!(m.contains("classDef wave0"));
        assert!(m.contains("classDef wave1"));
        assert!(m.contains("classDef wave2"));
        assert!(m.contains(":::wave0"));
        assert!(m.contains(":::wave1"));
    }

    #[test]
    fn mermaid_parallel_comment() {
        let graph = step_deps::analyze(&diamond_steps());
        let m = to_mermaid("F", &graph);
        assert!(m.contains("%% parallel wave"));
    }

    #[test]
    fn mermaid_multi_flows() {
        let g1 = step_deps::analyze(&linear_steps());
        let g2 = step_deps::analyze(&independent_steps());
        let graphs = vec![("Flow1".to_string(), g1), ("Flow2".to_string(), g2)];
        let m = to_mermaid_multi(&graphs);

        assert!(m.contains("subgraph Flow1"));
        assert!(m.contains("subgraph Flow2"));
        assert!(m.contains("Flow1_Extract"));
        assert!(m.contains("Flow2_A"));
    }

    #[test]
    fn empty_graph_dot() {
        let graph = step_deps::analyze(&[]);
        let dot = to_dot("Empty", &graph);
        assert!(dot.contains("digraph \"Empty\""));
        assert!(!dot.contains("->"));
    }

    #[test]
    fn empty_graph_mermaid() {
        let graph = step_deps::analyze(&[]);
        let m = to_mermaid("Empty", &graph);
        assert!(m.contains("graph TD"));
        assert!(!m.contains("-->"));
    }

    #[test]
    fn run_graph_file_not_found() {
        assert_eq!(run_graph("nonexistent_file.axon", "dot"), 2);
    }
}
