//! Tool registry — extensible tool dispatch for AXON execution.
//!
//! The `ToolRegistry` collects tool definitions from two sources:
//!   1. Built-in tools: Calculator, DateTimeTool (always available)
//!   2. Program-defined tools: declared via `tool Name { ... }` in .axon files
//!
//! When a `use_tool` step fires, the runner queries the registry:
//!   - Built-in tools execute natively (no LLM call)
//!   - Program-defined tools with known providers execute via provider adapters
//!   - Unknown tools fall through to LLM dispatch
//!
//! Provider adapters:
//!   - "native"  → built-in Calculator/DateTimeTool
//!   - "stub"    → returns a stub response (for testing/development)
//!   - "http"    → REST endpoint via reqwest (URL in runtime field)
//!   - "mcp"     → ℰMCP transducer (JSON-RPC 2.0 + blame + taint)
//!   - others    → fall through to LLM (future: gRPC, etc.)

use std::collections::HashMap;

use crate::emcp;
use crate::http_tool;
use crate::ir_nodes::IRToolSpec;
use crate::tool_executor::{self, ToolResult};

// ── Tool entry ─────────────────────────────────────────────────────────────

/// A registered tool with its metadata and dispatch configuration.
#[derive(Debug, Clone)]
pub struct ToolEntry {
    pub name: String,
    pub provider: String,
    pub timeout: String,
    pub runtime: String,
    pub sandbox: Option<bool>,
    pub max_results: Option<i64>,
    pub output_schema: String,
    pub effect_row: Vec<String>,
    pub source: ToolSource,
}

/// Where the tool was defined.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolSource {
    /// Built-in tool (Calculator, DateTimeTool).
    Builtin,
    /// Defined in the AXON program via `tool Name { ... }`.
    Program,
}

// ── Tool registry ──────────────────────────────────────────────────────────

/// Central registry for all available tools during execution.
#[derive(Debug)]
pub struct ToolRegistry {
    tools: HashMap<String, ToolEntry>,
}

impl ToolRegistry {
    /// Create a new registry pre-loaded with built-in tools.
    pub fn new() -> Self {
        let mut registry = ToolRegistry {
            tools: HashMap::new(),
        };
        registry.register_builtins();
        registry
    }

    /// Register the built-in native tools.
    fn register_builtins(&mut self) {
        self.tools.insert(
            "Calculator".to_string(),
            ToolEntry {
                name: "Calculator".to_string(),
                provider: "native".to_string(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                max_results: None,
                output_schema: "number".to_string(),
                effect_row: vec!["compute".to_string()],
                source: ToolSource::Builtin,
            },
        );
        self.tools.insert(
            "DateTimeTool".to_string(),
            ToolEntry {
                name: "DateTimeTool".to_string(),
                provider: "native".to_string(),
                timeout: String::new(),
                runtime: String::new(),
                sandbox: None,
                max_results: None,
                output_schema: String::new(),
                effect_row: vec!["read".to_string()],
                source: ToolSource::Builtin,
            },
        );
    }

    /// Register tools from the IR program's tool definitions.
    pub fn register_from_ir(&mut self, tool_specs: &[IRToolSpec]) {
        for spec in tool_specs {
            self.tools.insert(
                spec.name.clone(),
                ToolEntry {
                    name: spec.name.clone(),
                    provider: spec.provider.clone(),
                    timeout: spec.timeout.clone(),
                    runtime: spec.runtime.clone(),
                    sandbox: spec.sandbox,
                    max_results: spec.max_results,
                    output_schema: spec.output_schema.clone(),
                    effect_row: spec.effect_row.clone(),
                    source: ToolSource::Program,
                },
            );
        }
    }

    /// Register a single tool entry directly.
    pub fn register(&mut self, entry: ToolEntry) {
        self.tools.insert(entry.name.clone(), entry);
    }

    /// Look up a tool by name.
    pub fn get(&self, name: &str) -> Option<&ToolEntry> {
        self.tools.get(name)
    }

    /// Check if a tool is registered.
    pub fn contains(&self, name: &str) -> bool {
        self.tools.contains_key(name)
    }

    /// Dispatch a tool call. Returns:
    ///   - `Some(ToolResult)` if the tool was handled locally
    ///   - `None` if the tool should fall through to LLM
    pub fn dispatch(&self, tool_name: &str, argument: &str) -> Option<ToolResult> {
        let entry = self.tools.get(tool_name)?;

        match entry.provider.as_str() {
            // Native built-in execution
            "native" => tool_executor::dispatch(tool_name, argument),

            // Stub provider: returns a synthetic response for testing
            "stub" => Some(ToolResult {
                success: true,
                output: format!("[stub] {}({})", tool_name, argument),
                tool_name: tool_name.to_string(),
            }),

            // HTTP provider: REST endpoint dispatch
            "http" => Some(http_tool::dispatch_http(entry, argument)),

            // ℰMCP provider: epistemic MCP transducer (JSON-RPC + blame + taint)
            "mcp" => Some(emcp::dispatch_mcp(entry, argument)),

            // Known providers that currently fall through to LLM
            // Future: "grpc" adapters
            _ => None,
        }
    }

    /// Number of registered tools.
    pub fn len(&self) -> usize {
        self.tools.len()
    }

    /// Check if registry is empty.
    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    /// List all registered tool names.
    pub fn tool_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.tools.keys().map(|k| k.as_str()).collect();
        names.sort();
        names
    }

    /// List only built-in tool names.
    pub fn builtin_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self
            .tools
            .values()
            .filter(|e| e.source == ToolSource::Builtin)
            .map(|e| e.name.as_str())
            .collect();
        names.sort();
        names
    }

    /// List only program-defined tool names.
    pub fn program_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self
            .tools
            .values()
            .filter(|e| e.source == ToolSource::Program)
            .map(|e| e.name.as_str())
            .collect();
        names.sort();
        names
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_registry_has_builtins() {
        let reg = ToolRegistry::new();
        assert!(reg.contains("Calculator"));
        assert!(reg.contains("DateTimeTool"));
        assert_eq!(reg.len(), 2);
        assert_eq!(reg.builtin_names(), vec!["Calculator", "DateTimeTool"]);
        assert!(reg.program_names().is_empty());
    }

    #[test]
    fn register_program_tool() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "WebSearch".to_string(),
            provider: "brave".to_string(),
            timeout: "10s".to_string(),
            runtime: String::new(),
            sandbox: None,
            max_results: Some(5),
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });

        assert!(reg.contains("WebSearch"));
        assert_eq!(reg.len(), 3);
        assert_eq!(reg.program_names(), vec!["WebSearch"]);

        let entry = reg.get("WebSearch").unwrap();
        assert_eq!(entry.provider, "brave");
        assert_eq!(entry.max_results, Some(5));
    }

    #[test]
    fn register_from_ir_specs() {
        let mut reg = ToolRegistry::new();
        let specs = vec![
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 1,
                source_column: 1,
                name: "WebSearch".to_string(),
                provider: "brave".to_string(),
                max_results: Some(5),
                filter_expr: String::new(),
                timeout: "10s".to_string(),
                runtime: String::new(),
                sandbox: None,
                input_schema: Vec::new(),
                output_schema: String::new(),
                effect_row: Vec::new(),
            },
            IRToolSpec {
                node_type: "ToolDefinition",
                source_line: 5,
                source_column: 1,
                name: "DataAnalyzer".to_string(),
                provider: "stub".to_string(),
                max_results: None,
                filter_expr: String::new(),
                timeout: String::new(),
                runtime: "python".to_string(),
                sandbox: Some(true),
                input_schema: Vec::new(),
                output_schema: String::new(),
                effect_row: Vec::new(),
            },
        ];

        reg.register_from_ir(&specs);

        assert_eq!(reg.len(), 4); // 2 builtins + 2 program
        assert!(reg.contains("WebSearch"));
        assert!(reg.contains("DataAnalyzer"));
        assert_eq!(reg.program_names(), vec!["DataAnalyzer", "WebSearch"]);
    }

    #[test]
    fn dispatch_builtin_calculator() {
        let reg = ToolRegistry::new();
        let result = reg.dispatch("Calculator", "2 + 3").unwrap();
        assert!(result.success);
        assert_eq!(result.output, "5");
    }

    #[test]
    fn dispatch_builtin_datetime() {
        let reg = ToolRegistry::new();
        let result = reg.dispatch("DateTimeTool", "year").unwrap();
        assert!(result.success);
        let year: i32 = result.output.parse().unwrap();
        assert!(year >= 2024);
    }

    #[test]
    fn dispatch_stub_provider() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "TestTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });

        let result = reg.dispatch("TestTool", "hello world").unwrap();
        assert!(result.success);
        assert_eq!(result.output, "[stub] TestTool(hello world)");
    }

    #[test]
    fn dispatch_unknown_provider_falls_through() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "WebSearch".to_string(),
            provider: "brave".to_string(),
            timeout: "10s".to_string(),
            runtime: String::new(),
            sandbox: None,
            max_results: Some(5),
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });

        // brave provider not handled locally → falls through to LLM
        assert!(reg.dispatch("WebSearch", "query").is_none());
    }

    #[test]
    fn dispatch_unregistered_tool_returns_none() {
        let reg = ToolRegistry::new();
        assert!(reg.dispatch("NonExistent", "arg").is_none());
    }

    #[test]
    fn program_tool_overrides_builtin() {
        let mut reg = ToolRegistry::new();
        // Override Calculator with a stub provider
        reg.register(ToolEntry {
            name: "Calculator".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });

        let entry = reg.get("Calculator").unwrap();
        assert_eq!(entry.source, ToolSource::Program);
        assert_eq!(entry.provider, "stub");

        // Now dispatches via stub, not native
        let result = reg.dispatch("Calculator", "2+3").unwrap();
        assert_eq!(result.output, "[stub] Calculator(2+3)");
    }

    #[test]
    fn tool_names_sorted() {
        let mut reg = ToolRegistry::new();
        reg.register(ToolEntry {
            name: "ZetaTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });
        reg.register(ToolEntry {
            name: "AlphaTool".to_string(),
            provider: "stub".to_string(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            max_results: None,
            output_schema: String::new(),
            effect_row: Vec::new(),
            source: ToolSource::Program,
        });

        let names = reg.tool_names();
        assert_eq!(
            names,
            vec!["AlphaTool", "Calculator", "DateTimeTool", "ZetaTool"]
        );
    }
}
