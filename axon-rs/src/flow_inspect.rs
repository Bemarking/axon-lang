//! Flow Inspector — runtime introspection for deployed AXON flows.
//!
//! Given a flow name and its stored source, re-compiles (lex → parse → IR)
//! and extracts structured metadata:
//!   - Flow signature (name, parameters, return type)
//!   - Steps with persona refs, tools used, probes, weaves
//!   - Data edges (step dependencies)
//!   - Execution levels (parallelism structure)
//!   - Anchors defined in the source
//!   - Tools declared in the source
//!   - Personas referenced
//!   - Source hash and line count
//!
//! Used by:
//!   - `GET /v1/inspect/:name` — API endpoint for flow introspection

use serde::Serialize;

// ── Inspection result ───────────────────────────────────────────────────

/// Complete inspection report for a deployed flow.
#[derive(Debug, Clone, Serialize)]
pub struct FlowInspection {
    /// Flow name.
    pub name: String,
    /// Source file name.
    pub source_file: String,
    /// Source hash (from version registry).
    pub source_hash: String,
    /// Number of lines in the source.
    pub source_lines: usize,
    /// Flow signature details.
    pub signature: FlowSignature,
    /// Steps in the flow.
    pub steps: Vec<StepInfo>,
    /// Data edges between steps.
    pub edges: Vec<EdgeInfo>,
    /// Execution levels (parallelism structure).
    pub execution_levels: Vec<Vec<String>>,
    /// Anchors defined in the source.
    pub anchors: Vec<AnchorInfo>,
    /// Tools declared in the source.
    pub tools: Vec<ToolInfo>,
    /// Unique personas referenced across all steps.
    pub personas_referenced: Vec<String>,
    /// Compilation metadata.
    pub compilation: CompilationInfo,
}

/// Flow signature — name, parameters, return type.
#[derive(Debug, Clone, Serialize)]
pub struct FlowSignature {
    pub name: String,
    pub parameters: Vec<ParameterInfo>,
    pub return_type: String,
    pub return_type_optional: bool,
}

/// A flow parameter.
#[derive(Debug, Clone, Serialize)]
pub struct ParameterInfo {
    pub name: String,
    pub type_name: String,
}

/// Information about a single step in a flow.
#[derive(Debug, Clone, Serialize)]
pub struct StepInfo {
    pub name: String,
    pub persona_ref: String,
    pub has_tool_use: bool,
    pub has_probe: bool,
    pub has_reason: bool,
    pub has_weave: bool,
    pub output_type: String,
    pub source_line: u32,
}

/// A data edge between steps.
#[derive(Debug, Clone, Serialize)]
pub struct EdgeInfo {
    pub from: String,
    pub to: String,
    pub type_name: String,
}

/// Anchor information.
#[derive(Debug, Clone, Serialize)]
pub struct AnchorInfo {
    pub name: String,
    pub description: String,
    pub enforce: String,
    pub on_violation: String,
    pub source_line: u32,
}

/// Tool declaration information.
#[derive(Debug, Clone, Serialize)]
pub struct ToolInfo {
    pub name: String,
    pub provider: String,
    pub timeout: String,
    pub sandbox: Option<bool>,
    pub source_line: u32,
}

/// Compilation metadata.
#[derive(Debug, Clone, Serialize)]
pub struct CompilationInfo {
    pub success: bool,
    pub token_count: usize,
    pub flow_count: usize,
    pub anchor_count: usize,
    pub tool_count: usize,
    pub type_errors: Vec<String>,
}

// ── Inspector ───────────────────────────────────────────────────────────

/// Inspect a flow by re-compiling its source.
///
/// Returns `Ok(inspection)` if the flow is found in the IR, or
/// `Err(message)` if compilation fails or flow not found.
pub fn inspect_flow(
    flow_name: &str,
    source: &str,
    source_file: &str,
    source_hash: &str,
) -> Result<FlowInspection, String> {
    // Lex
    let tokens = crate::lexer::Lexer::new(source, source_file)
        .tokenize()
        .map_err(|e| format!("lex error: {e:?}"))?;

    let token_count = tokens.len();

    // Parse
    let mut parser = crate::parser::Parser::new(tokens);
    let program = parser
        .parse()
        .map_err(|e| format!("parse error: {e:?}"))?;

    // Type check (non-fatal — report but continue)
    let type_errors = crate::type_checker::TypeChecker::new(&program).check();
    let type_error_msgs: Vec<String> = type_errors.iter().map(|e| format!("{e:?}")).collect();

    // IR generation
    let ir = crate::ir_generator::IRGenerator::new().generate(&program);

    // Find the target flow
    let ir_flow = ir
        .flows
        .iter()
        .find(|f| f.name == flow_name)
        .ok_or_else(|| format!("flow '{}' not found in IR (available: {})",
            flow_name,
            ir.flows.iter().map(|f| f.name.as_str()).collect::<Vec<_>>().join(", ")))?;

    // Extract signature
    let signature = FlowSignature {
        name: ir_flow.name.clone(),
        parameters: ir_flow
            .parameters
            .iter()
            .map(|p| ParameterInfo {
                name: p.name.clone(),
                type_name: p.type_name.clone(),
            })
            .collect(),
        return_type: if ir_flow.return_type_generic.is_empty() {
            ir_flow.return_type_name.clone()
        } else {
            format!("{}<{}>", ir_flow.return_type_name, ir_flow.return_type_generic)
        },
        return_type_optional: ir_flow.return_type_optional,
    };

    // Extract steps
    let mut steps = Vec::new();
    let mut personas_set = std::collections::BTreeSet::new();

    for node in &ir_flow.steps {
        if let crate::ir_nodes::IRFlowNode::Step(step) = node {
            if !step.persona_ref.is_empty() {
                personas_set.insert(step.persona_ref.clone());
            }
            steps.push(StepInfo {
                name: step.name.clone(),
                persona_ref: step.persona_ref.clone(),
                has_tool_use: step.use_tool.is_some(),
                has_probe: step.probe.is_some(),
                has_reason: step.reason.is_some(),
                has_weave: step.weave.is_some(),
                output_type: step.output_type.clone(),
                source_line: step.source_line,
            });
        }
    }

    // Extract edges
    let edges: Vec<EdgeInfo> = ir_flow
        .edges
        .iter()
        .map(|e| EdgeInfo {
            from: e.source_step.clone(),
            to: e.target_step.clone(),
            type_name: e.type_name.clone(),
        })
        .collect();

    // Anchors
    let anchors: Vec<AnchorInfo> = ir
        .anchors
        .iter()
        .map(|a| AnchorInfo {
            name: a.name.clone(),
            description: a.description.clone(),
            enforce: a.enforce.clone(),
            on_violation: a.on_violation.clone(),
            source_line: a.source_line,
        })
        .collect();

    // Tools
    let tools: Vec<ToolInfo> = ir
        .tools
        .iter()
        .map(|t| ToolInfo {
            name: t.name.clone(),
            provider: t.provider.clone(),
            timeout: t.timeout.clone(),
            sandbox: t.sandbox,
            source_line: t.source_line,
        })
        .collect();

    let source_lines = source.lines().count();

    Ok(FlowInspection {
        name: flow_name.to_string(),
        source_file: source_file.to_string(),
        source_hash: source_hash.to_string(),
        source_lines,
        signature,
        steps,
        edges,
        execution_levels: ir_flow.execution_levels.clone(),
        anchors,
        tools,
        personas_referenced: personas_set.into_iter().collect(),
        compilation: CompilationInfo {
            success: type_error_msgs.is_empty(),
            token_count,
            flow_count: ir.flows.len(),
            anchor_count: ir.anchors.len(),
            tool_count: ir.tools.len(),
            type_errors: type_error_msgs,
        },
    })
}

/// Quick summary for listing all deployed flows.
#[derive(Debug, Clone, Serialize)]
pub struct FlowSummary {
    pub name: String,
    pub source_file: String,
    pub source_hash: String,
    pub step_count: usize,
    pub has_anchors: bool,
    pub has_tools: bool,
}

/// Inspect all flows in a source, returning summaries.
pub fn inspect_all_flows(
    source: &str,
    source_file: &str,
    source_hash: &str,
) -> Result<Vec<FlowSummary>, String> {
    let tokens = crate::lexer::Lexer::new(source, source_file)
        .tokenize()
        .map_err(|e| format!("lex error: {e:?}"))?;

    let mut parser = crate::parser::Parser::new(tokens);
    let program = parser.parse().map_err(|e| format!("parse error: {e:?}"))?;
    let ir = crate::ir_generator::IRGenerator::new().generate(&program);

    let has_anchors = !ir.anchors.is_empty();
    let has_tools = !ir.tools.is_empty();

    Ok(ir
        .flows
        .iter()
        .map(|f| {
            let step_count = f
                .steps
                .iter()
                .filter(|n| matches!(n, crate::ir_nodes::IRFlowNode::Step(_)))
                .count();

            FlowSummary {
                name: f.name.clone(),
                source_file: source_file.to_string(),
                source_hash: source_hash.to_string(),
                step_count,
                has_anchors,
                has_tools,
            }
        })
        .collect())
}

// ── Graph export ────────────────────────────────────────────────────────

/// Supported graph output formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GraphFormat {
    Dot,
    Mermaid,
}

impl GraphFormat {
    /// Parse from string ("dot", "mermaid"). Defaults to Dot.
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "mermaid" => GraphFormat::Mermaid,
            _ => GraphFormat::Dot,
        }
    }

    pub fn content_type(&self) -> &'static str {
        match self {
            GraphFormat::Dot => "text/vnd.graphviz",
            GraphFormat::Mermaid => "text/plain",
        }
    }
}

/// Graph export result.
#[derive(Debug, Clone, Serialize)]
pub struct GraphExport {
    /// Flow name.
    pub flow_name: String,
    /// Output format ("dot" or "mermaid").
    pub format: String,
    /// The graph source text.
    pub graph: String,
    /// Number of nodes (steps) in the graph.
    pub node_count: usize,
    /// Number of edges in the graph.
    pub edge_count: usize,
    /// Number of parallel groups detected.
    pub parallel_groups: usize,
    /// Maximum dependency depth.
    pub max_depth: usize,
}

/// Generate a graph export for a specific flow from its source.
///
/// Compiles source → IR → DependencyGraph → DOT/Mermaid.
pub fn export_flow_graph(
    flow_name: &str,
    source: &str,
    source_file: &str,
    format: GraphFormat,
) -> Result<GraphExport, String> {
    // Compile to IR
    let tokens = crate::lexer::Lexer::new(source, source_file)
        .tokenize()
        .map_err(|e| format!("lex error: {e:?}"))?;

    let mut parser = crate::parser::Parser::new(tokens);
    let program = parser.parse().map_err(|e| format!("parse error: {e:?}"))?;
    let ir = crate::ir_generator::IRGenerator::new().generate(&program);

    // Build graphs from IR
    let graphs = crate::graph_export::graph_from_ir(&ir);

    // Find the target flow's graph
    let (name, graph) = graphs
        .into_iter()
        .find(|(n, _)| n == flow_name)
        .ok_or_else(|| format!("flow '{}' not found in graph analysis", flow_name))?;

    let node_count = graph.steps.len();
    let edge_count: usize = graph.steps.iter().map(|s| s.depends_on.len()).sum();
    let parallel_group_count = graph.parallel_groups.len();
    let max_depth = graph.max_depth;

    let (graph_text, format_str) = match format {
        GraphFormat::Dot => (crate::graph_export::to_dot(&name, &graph), "dot"),
        GraphFormat::Mermaid => (crate::graph_export::to_mermaid(&name, &graph), "mermaid"),
    };

    Ok(GraphExport {
        flow_name: name,
        format: format_str.to_string(),
        graph: graph_text,
        node_count,
        edge_count,
        parallel_groups: parallel_group_count,
        max_depth,
    })
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_SOURCE: &str = r#"
persona Analyst {
  tone: "analytical"
  domain: ["data", "statistics"]
}

anchor NoHallucination {
  description: "Prevent fabrication"
  require: factual
  enforce: strict
  on_violation: retry
}

tool Calculator {
  provider: builtin
  timeout: 5s
}

flow Analyze(data: Text) -> Report {
  step gather use Analyst {
    given: data
    ask: "Summarize the data"
  }
  step conclude use Analyst {
    given: gather.output
    ask: "Draw conclusions"
  }
}
"#;

    #[test]
    fn inspect_flow_basic() {
        let result = inspect_flow("Analyze", SAMPLE_SOURCE, "test.axon", "abc123");
        assert!(result.is_ok());

        let inspection = result.unwrap();
        assert_eq!(inspection.name, "Analyze");
        assert_eq!(inspection.source_file, "test.axon");
        assert_eq!(inspection.source_hash, "abc123");
        assert!(inspection.source_lines > 0);

        // Signature
        assert_eq!(inspection.signature.name, "Analyze");
        assert_eq!(inspection.signature.parameters.len(), 1);
        assert_eq!(inspection.signature.parameters[0].name, "data");
        assert_eq!(inspection.signature.parameters[0].type_name, "Text");

        // Steps
        assert_eq!(inspection.steps.len(), 2);
        assert_eq!(inspection.steps[0].name, "gather");
        assert_eq!(inspection.steps[1].name, "conclude");

        // Personas referenced
        assert!(inspection.personas_referenced.contains(&"Analyst".to_string()));

        // Anchors
        assert_eq!(inspection.anchors.len(), 1);
        assert_eq!(inspection.anchors[0].name, "NoHallucination");

        // Tools
        assert_eq!(inspection.tools.len(), 1);
        assert_eq!(inspection.tools[0].name, "Calculator");

        // Compilation (type errors are non-fatal for inspection)
        assert_eq!(inspection.compilation.flow_count, 1);
    }

    #[test]
    fn inspect_flow_not_found() {
        let result = inspect_flow("NonExistent", SAMPLE_SOURCE, "test.axon", "abc");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("not found"));
    }

    #[test]
    fn inspect_flow_invalid_source() {
        let result = inspect_flow("X", "this is not valid axon {{{{", "bad.axon", "x");
        assert!(result.is_err());
    }

    #[test]
    fn inspect_all_flows_basic() {
        let result = inspect_all_flows(SAMPLE_SOURCE, "test.axon", "hash123");
        assert!(result.is_ok());

        let summaries = result.unwrap();
        assert_eq!(summaries.len(), 1);
        assert_eq!(summaries[0].name, "Analyze");
        assert_eq!(summaries[0].step_count, 2);
        assert!(summaries[0].has_anchors);
        assert!(summaries[0].has_tools);
    }

    #[test]
    fn flow_inspection_serializable() {
        let result = inspect_flow("Analyze", SAMPLE_SOURCE, "test.axon", "abc123").unwrap();
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["name"], "Analyze");
        assert!(json["signature"].is_object());
        assert!(json["steps"].is_array());
        assert!(json["anchors"].is_array());
        assert!(json["tools"].is_array());
        assert!(json["compilation"].is_object());
        assert!(json["compilation"].is_object());
    }

    #[test]
    fn flow_summary_serializable() {
        let summary = FlowSummary {
            name: "TestFlow".to_string(),
            source_file: "test.axon".to_string(),
            source_hash: "abc".to_string(),
            step_count: 3,
            has_anchors: true,
            has_tools: false,
        };
        let json = serde_json::to_value(&summary).unwrap();
        assert_eq!(json["name"], "TestFlow");
        assert_eq!(json["step_count"], 3);
        assert_eq!(json["has_anchors"], true);
        assert_eq!(json["has_tools"], false);
    }

    #[test]
    fn step_info_details() {
        let result = inspect_flow("Analyze", SAMPLE_SOURCE, "test.axon", "abc").unwrap();
        let gather = &result.steps[0];
        assert_eq!(gather.persona_ref, "Analyst");
        assert!(!gather.has_tool_use);
        assert!(!gather.has_probe);
        assert!(!gather.has_reason);
        assert!(!gather.has_weave);
    }

    #[test]
    fn compilation_info_details() {
        let result = inspect_flow("Analyze", SAMPLE_SOURCE, "test.axon", "abc").unwrap();
        assert!(result.compilation.token_count > 0);
        assert_eq!(result.compilation.anchor_count, 1);
        assert_eq!(result.compilation.tool_count, 1);
    }

    #[test]
    fn graph_format_parsing() {
        assert_eq!(GraphFormat::from_str("dot"), GraphFormat::Dot);
        assert_eq!(GraphFormat::from_str("mermaid"), GraphFormat::Mermaid);
        assert_eq!(GraphFormat::from_str("MERMAID"), GraphFormat::Mermaid);
        assert_eq!(GraphFormat::from_str("unknown"), GraphFormat::Dot); // default
        assert_eq!(GraphFormat::Dot.content_type(), "text/vnd.graphviz");
        assert_eq!(GraphFormat::Mermaid.content_type(), "text/plain");
    }

    #[test]
    fn export_flow_graph_dot() {
        let result = export_flow_graph("Analyze", SAMPLE_SOURCE, "test.axon", GraphFormat::Dot);
        assert!(result.is_ok());
        let export = result.unwrap();
        assert_eq!(export.flow_name, "Analyze");
        assert_eq!(export.format, "dot");
        assert!(export.graph.contains("digraph"));
        assert!(export.graph.contains("gather"));
        assert!(export.graph.contains("conclude"));
        assert!(export.node_count >= 2);
    }

    #[test]
    fn export_flow_graph_mermaid() {
        let result = export_flow_graph("Analyze", SAMPLE_SOURCE, "test.axon", GraphFormat::Mermaid);
        assert!(result.is_ok());
        let export = result.unwrap();
        assert_eq!(export.format, "mermaid");
        assert!(export.graph.contains("graph TD"));
        assert!(export.graph.contains("gather"));
        assert!(export.graph.contains("conclude"));
    }

    #[test]
    fn export_flow_graph_not_found() {
        let result = export_flow_graph("NonExistent", SAMPLE_SOURCE, "test.axon", GraphFormat::Dot);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("not found"));
    }

    #[test]
    fn graph_export_serializable() {
        let result = export_flow_graph("Analyze", SAMPLE_SOURCE, "test.axon", GraphFormat::Dot).unwrap();
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["flow_name"], "Analyze");
        assert_eq!(json["format"], "dot");
        assert!(json["graph"].as_str().unwrap().contains("digraph"));
        assert!(json["node_count"].as_u64().unwrap() >= 2);
    }
}
