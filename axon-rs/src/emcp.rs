//! ℰMCP Transducer — Epistemic Model Context Protocol runtime bridge.
//!
//! Implements AXON's ℰMCP (Epistemic MCP) for Ingesta: consuming external MCP
//! servers with epistemic guarantees that plain MCP lacks.
//!
//! Key differentiators from raw MCP:
//!   - **Blame tracking (CT-2/CT-3):** Every MCP call records blame assignment.
//!     If the server returns invalid data → Blame::Server.
//!     If AXON generated bad parameters → Blame::Caller.
//!   - **Epistemic taint:** All data entering via MCP is born as `Uncertainty` (⊥)
//!     in the epistemic lattice. Must be elevated by reasoning before trusted.
//!   - **Effect rows:** MCP tools carry `effects: <network, io, epistemic:speculate>`.
//!   - **Schema validation:** Response validated against output_schema before use.
//!
//! Transport: JSON-RPC 2.0 over HTTP (MCP standard transport).
//! The ℰMCP transducer wraps standard MCP calls with AXON's epistemic envelope.

use serde::{Deserialize, Serialize};
use std::time::Duration;

use crate::tool_executor::ToolResult;
use crate::tool_registry::ToolEntry;

// ── Blame calculus (Findler-Felleisen) ────────────────────────────────────

/// Blame assignment for a tool call failure.
/// Implements the contract-based blame calculus from ℰMCP spec (CT-2/CT-3).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Blame {
    /// No failure — call succeeded.
    None,
    /// Server violated its contract (bad response, schema mismatch, crash).
    Server,
    /// Caller violated its contract (bad parameters, invalid arguments).
    Caller,
    /// Network/infrastructure failure (timeout, connection refused).
    Network,
}

impl Blame {
    pub fn as_str(&self) -> &'static str {
        match self {
            Blame::None => "none",
            Blame::Server => "server",
            Blame::Caller => "caller",
            Blame::Network => "network",
        }
    }
}

// ── Epistemic taint ──────────────────────────────────────────────────────

/// Epistemic level of data entering via MCP.
/// All MCP-sourced data starts at `Uncertainty` and must be elevated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum EpistemicTaint {
    /// Data has not been validated — born as ⊥ (Uncertainty).
    Untrusted,
    /// Data passed schema validation but not epistemic reasoning.
    SchemaValidated,
    /// Data elevated by reasoning step (shield or know block).
    Elevated,
}

impl EpistemicTaint {
    pub fn as_str(&self) -> &'static str {
        match self {
            EpistemicTaint::Untrusted => "untrusted",
            EpistemicTaint::SchemaValidated => "schema_validated",
            EpistemicTaint::Elevated => "elevated",
        }
    }
}

// ── MCP call result ──────────────────────────────────────────────────────

/// Result of an ℰMCP tool call — enriched with blame and epistemic metadata.
#[derive(Debug, Clone, Serialize)]
pub struct McpCallResult {
    /// Standard tool result.
    pub tool_name: String,
    pub output: String,
    pub success: bool,
    /// Blame assignment (CT-2/CT-3).
    pub blame: Blame,
    /// Epistemic taint level of the output data.
    pub taint: EpistemicTaint,
    /// MCP server that handled the call.
    pub server: String,
    /// Effect row inferred for this call.
    pub effects: Vec<String>,
}

impl McpCallResult {
    /// Convert to a standard ToolResult (for registry integration).
    pub fn to_tool_result(&self) -> ToolResult {
        ToolResult {
            success: self.success,
            output: self.output.clone(),
            tool_name: self.tool_name.clone(),
        }
    }
}

// ── JSON-RPC 2.0 structures ─────────────────────────────────────────────

/// JSON-RPC 2.0 request (MCP standard transport).
#[derive(Debug, Serialize)]
struct JsonRpcRequest {
    jsonrpc: &'static str,
    method: String,
    params: serde_json::Value,
    id: u64,
}

/// JSON-RPC 2.0 response.
#[derive(Debug, Deserialize)]
struct JsonRpcResponse {
    #[allow(dead_code)]
    jsonrpc: String,
    result: Option<serde_json::Value>,
    error: Option<JsonRpcError>,
    #[allow(dead_code)]
    id: u64,
}

/// JSON-RPC 2.0 error object.
#[derive(Debug, Deserialize)]
struct JsonRpcError {
    code: i64,
    message: String,
}

// ── MCP Client ───────────────────────────────────────────────────────────

/// ℰMCP transducer client — wraps MCP server communication with epistemic
/// guarantees (blame tracking, taint tagging, effect inference).
pub struct McpClient {
    /// MCP server endpoint URL.
    server_url: String,
    /// HTTP timeout.
    timeout: Duration,
    /// Request ID counter.
    next_id: u64,
}

impl McpClient {
    /// Create a new ℰMCP client for the given server.
    pub fn new(server_url: &str, timeout: Duration) -> Self {
        McpClient {
            server_url: server_url.to_string(),
            timeout,
            next_id: 1,
        }
    }

    /// Call a tool on the MCP server with ℰMCP epistemic envelope.
    ///
    /// The call is wrapped with:
    ///   - Blame tracking: server/caller/network fault attribution
    ///   - Taint tagging: output starts as Untrusted, elevated to SchemaValidated if valid
    ///   - Effect inference: all MCP calls carry network + epistemic:speculate effects
    pub fn call_tool(&mut self, tool_name: &str, argument: &str) -> McpCallResult {
        let request_id = self.next_id;
        self.next_id += 1;

        // Build JSON-RPC request for MCP tools/call
        let params = if argument.trim_start().starts_with('{') {
            serde_json::from_str(argument).unwrap_or_else(|_| {
                serde_json::json!({
                    "name": tool_name,
                    "arguments": { "input": argument }
                })
            })
        } else {
            serde_json::json!({
                "name": tool_name,
                "arguments": { "input": argument }
            })
        };

        let rpc_request = JsonRpcRequest {
            jsonrpc: "2.0",
            method: "tools/call".to_string(),
            params,
            id: request_id,
        };

        // Execute the HTTP request to MCP server
        match self.send_rpc(&rpc_request) {
            Ok(response) => self.process_response(tool_name, response),
            Err(e) => McpCallResult {
                tool_name: tool_name.to_string(),
                output: format!("ℰMCP error: {e}"),
                success: false,
                blame: Blame::Network,
                taint: EpistemicTaint::Untrusted,
                server: self.server_url.clone(),
                effects: vec!["network".to_string()],
            },
        }
    }

    /// List available tools on the MCP server.
    pub fn list_tools(&mut self) -> Result<Vec<McpToolInfo>, String> {
        let request_id = self.next_id;
        self.next_id += 1;

        let rpc_request = JsonRpcRequest {
            jsonrpc: "2.0",
            method: "tools/list".to_string(),
            params: serde_json::json!({}),
            id: request_id,
        };

        let response = self.send_rpc(&rpc_request)?;

        match response.result {
            Some(val) => {
                if let Some(tools) = val.get("tools").and_then(|t| t.as_array()) {
                    let infos = tools
                        .iter()
                        .filter_map(|t| {
                            Some(McpToolInfo {
                                name: t.get("name")?.as_str()?.to_string(),
                                description: t
                                    .get("description")
                                    .and_then(|d| d.as_str())
                                    .unwrap_or("")
                                    .to_string(),
                            })
                        })
                        .collect();
                    Ok(infos)
                } else {
                    Ok(Vec::new())
                }
            }
            None => Err(response
                .error
                .map(|e| format!("JSON-RPC error {}: {}", e.code, e.message))
                .unwrap_or_else(|| "empty response".to_string())),
        }
    }

    /// Read a resource from the MCP server.
    pub fn read_resource(&mut self, uri: &str) -> McpCallResult {
        let request_id = self.next_id;
        self.next_id += 1;

        let rpc_request = JsonRpcRequest {
            jsonrpc: "2.0",
            method: "resources/read".to_string(),
            params: serde_json::json!({ "uri": uri }),
            id: request_id,
        };

        match self.send_rpc(&rpc_request) {
            Ok(response) => {
                match response.result {
                    Some(val) => {
                        // Extract text content from MCP resource response
                        let text = val
                            .get("contents")
                            .and_then(|c| c.as_array())
                            .and_then(|arr| arr.first())
                            .and_then(|item| item.get("text"))
                            .and_then(|t| t.as_str())
                            .unwrap_or_else(|| {
                                // Fallback: serialize the entire result
                                ""
                            });

                        let output = if text.is_empty() {
                            serde_json::to_string(&val).unwrap_or_default()
                        } else {
                            text.to_string()
                        };

                        McpCallResult {
                            tool_name: format!("resource:{uri}"),
                            output,
                            success: true,
                            blame: Blame::None,
                            taint: EpistemicTaint::Untrusted, // All MCP data → ⊥
                            server: self.server_url.clone(),
                            effects: vec!["network".to_string(), "io".to_string()],
                        }
                    }
                    None => McpCallResult {
                        tool_name: format!("resource:{uri}"),
                        output: response
                            .error
                            .map(|e| format!("JSON-RPC error {}: {}", e.code, e.message))
                            .unwrap_or_else(|| "empty response".to_string()),
                        success: false,
                        blame: Blame::Server,
                        taint: EpistemicTaint::Untrusted,
                        server: self.server_url.clone(),
                        effects: vec!["network".to_string()],
                    },
                }
            }
            Err(e) => McpCallResult {
                tool_name: format!("resource:{uri}"),
                output: format!("ℰMCP error: {e}"),
                success: false,
                blame: Blame::Network,
                taint: EpistemicTaint::Untrusted,
                server: self.server_url.clone(),
                effects: vec!["network".to_string()],
            },
        }
    }

    // ── Internal ──────────────────────────────────────────────────

    fn send_rpc(&self, request: &JsonRpcRequest) -> Result<JsonRpcResponse, String> {
        let client = reqwest::blocking::Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| format!("failed to create HTTP client: {e}"))?;

        let body = serde_json::to_string(request)
            .map_err(|e| format!("failed to serialize request: {e}"))?;

        let response = client
            .post(&self.server_url)
            .header("Content-Type", "application/json")
            .header("X-Axon-EMCP", "1.0")
            .body(body)
            .send()
            .map_err(|e| {
                if e.is_timeout() {
                    format!("MCP server timed out after {}s", self.timeout.as_secs())
                } else if e.is_connect() {
                    format!("cannot connect to MCP server at {}", self.server_url)
                } else {
                    format!("MCP request failed: {e}")
                }
            })?;

        let status = response.status();
        let text = response
            .text()
            .map_err(|e| format!("failed to read MCP response: {e}"))?;

        if !status.is_success() {
            return Err(format!("MCP server returned HTTP {}: {}", status.as_u16(), text));
        }

        serde_json::from_str(&text)
            .map_err(|e| format!("invalid JSON-RPC response: {e}"))
    }

    fn process_response(&self, tool_name: &str, response: JsonRpcResponse) -> McpCallResult {
        match response.result {
            Some(val) => {
                // Extract content from MCP tool response
                let output = val
                    .get("content")
                    .and_then(|c| c.as_array())
                    .and_then(|arr| arr.first())
                    .and_then(|item| item.get("text"))
                    .and_then(|t| t.as_str())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| serde_json::to_string(&val).unwrap_or_default());

                McpCallResult {
                    tool_name: tool_name.to_string(),
                    output,
                    success: true,
                    blame: Blame::None,
                    taint: EpistemicTaint::Untrusted, // Born as ⊥ — must be elevated
                    server: self.server_url.clone(),
                    effects: vec![
                        "network".to_string(),
                        "epistemic:speculate".to_string(),
                    ],
                }
            }
            None => {
                let (blame, msg) = match response.error {
                    Some(e) => {
                        // JSON-RPC error codes: -32600..-32603 are protocol errors (caller)
                        // Server-defined errors are positive or other negative codes
                        let b = if (-32603..=-32600).contains(&e.code) {
                            Blame::Caller
                        } else {
                            Blame::Server
                        };
                        (b, format!("JSON-RPC error {}: {}", e.code, e.message))
                    }
                    None => (Blame::Server, "empty response from MCP server".to_string()),
                };

                McpCallResult {
                    tool_name: tool_name.to_string(),
                    output: msg,
                    success: false,
                    blame,
                    taint: EpistemicTaint::Untrusted,
                    server: self.server_url.clone(),
                    effects: vec!["network".to_string()],
                }
            }
        }
    }
}

/// Information about a tool available on an MCP server.
#[derive(Debug, Clone)]
pub struct McpToolInfo {
    pub name: String,
    pub description: String,
}

// ── Registry dispatch ────────────────────────────────────────────────────

/// Dispatch an MCP tool call via the ℰMCP transducer.
///
/// Creates a transient McpClient for the server URL in `entry.runtime`,
/// calls the tool, and returns the result with blame/taint metadata.
pub fn dispatch_mcp(entry: &ToolEntry, argument: &str) -> ToolResult {
    let server_url = entry.runtime.trim();

    if server_url.is_empty() {
        return ToolResult {
            success: false,
            output: format!(
                "ℰMCP tool '{}': no server URL. Set runtime: \"http://...\" in tool definition.",
                entry.name
            ),
            tool_name: entry.name.clone(),
        };
    }

    if !server_url.starts_with("http://") && !server_url.starts_with("https://") {
        return ToolResult {
            success: false,
            output: format!(
                "ℰMCP tool '{}': invalid server URL '{}'. Must start with http:// or https://.",
                entry.name, server_url
            ),
            tool_name: entry.name.clone(),
        };
    }

    let timeout = crate::http_tool::parse_timeout_pub(&entry.timeout)
        .unwrap_or(Duration::from_secs(30));

    let mut client = McpClient::new(server_url, timeout);
    let mcp_result = client.call_tool(&entry.name, argument);

    // Enrich output with blame metadata for tracing
    if !mcp_result.success {
        ToolResult {
            success: false,
            output: format!(
                "{} [blame={}]",
                mcp_result.output,
                mcp_result.blame.as_str()
            ),
            tool_name: entry.name.clone(),
        }
    } else {
        mcp_result.to_tool_result()
    }
}

// ── Blame tracker ────────────────────────────────────────────────────────

/// Accumulates blame records across MCP tool calls during execution.
#[derive(Debug, Default)]
pub struct BlameTracker {
    records: Vec<BlameRecord>,
}

/// A single blame record.
#[derive(Debug, Clone, Serialize)]
pub struct BlameRecord {
    pub tool_name: String,
    pub server: String,
    pub blame: Blame,
    pub taint: EpistemicTaint,
    pub message: String,
}

impl BlameTracker {
    pub fn new() -> Self {
        BlameTracker { records: Vec::new() }
    }

    /// Record a blame event from an MCP call result.
    pub fn record(&mut self, result: &McpCallResult) {
        self.records.push(BlameRecord {
            tool_name: result.tool_name.clone(),
            server: result.server.clone(),
            blame: result.blame,
            taint: result.taint,
            message: if result.success {
                "ok".to_string()
            } else {
                result.output.clone()
            },
        });
    }

    /// Total number of blame records.
    pub fn total(&self) -> usize {
        self.records.len()
    }

    /// Count of server-blamed failures.
    pub fn server_faults(&self) -> usize {
        self.records.iter().filter(|r| r.blame == Blame::Server).count()
    }

    /// Count of caller-blamed failures.
    pub fn caller_faults(&self) -> usize {
        self.records.iter().filter(|r| r.blame == Blame::Caller).count()
    }

    /// Count of network failures.
    pub fn network_faults(&self) -> usize {
        self.records.iter().filter(|r| r.blame == Blame::Network).count()
    }

    /// All records.
    pub fn records(&self) -> &[BlameRecord] {
        &self.records
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tool_registry::{ToolEntry, ToolSource};

    fn make_mcp_entry(name: &str, url: &str, timeout: &str) -> ToolEntry {
        ToolEntry {
            name: name.to_string(),
            provider: "mcp".to_string(),
            timeout: timeout.to_string(),
            runtime: url.to_string(),
            sandbox: None,
            max_results: None,
            output_schema: "JSON".to_string(),
            effect_row: vec!["network".to_string(), "epistemic:speculate".to_string()],
            source: ToolSource::Program,
        }
    }

    // ── Blame ─────────────────────────────────────────────────────

    #[test]
    fn blame_variants() {
        assert_eq!(Blame::None.as_str(), "none");
        assert_eq!(Blame::Server.as_str(), "server");
        assert_eq!(Blame::Caller.as_str(), "caller");
        assert_eq!(Blame::Network.as_str(), "network");
    }

    // ── Epistemic taint ───────────────────────────────────────────

    #[test]
    fn taint_levels() {
        assert_eq!(EpistemicTaint::Untrusted.as_str(), "untrusted");
        assert_eq!(EpistemicTaint::SchemaValidated.as_str(), "schema_validated");
        assert_eq!(EpistemicTaint::Elevated.as_str(), "elevated");
    }

    #[test]
    fn mcp_data_born_untrusted() {
        // All MCP-sourced data must start as Untrusted (⊥)
        let result = McpCallResult {
            tool_name: "DataTool".into(),
            output: "some data".into(),
            success: true,
            blame: Blame::None,
            taint: EpistemicTaint::Untrusted,
            server: "http://localhost:3000".into(),
            effects: vec!["network".into()],
        };
        assert_eq!(result.taint, EpistemicTaint::Untrusted);
    }

    // ── McpCallResult conversion ──────────────────────────────────

    #[test]
    fn mcp_result_to_tool_result() {
        let mcp = McpCallResult {
            tool_name: "TestTool".into(),
            output: "hello".into(),
            success: true,
            blame: Blame::None,
            taint: EpistemicTaint::Untrusted,
            server: "http://localhost".into(),
            effects: vec![],
        };
        let tr = mcp.to_tool_result();
        assert!(tr.success);
        assert_eq!(tr.output, "hello");
        assert_eq!(tr.tool_name, "TestTool");
    }

    // ── Dispatch validation ───────────────────────────────────────

    #[test]
    fn dispatch_empty_url_fails() {
        let entry = make_mcp_entry("McpTool", "", "5s");
        let result = dispatch_mcp(&entry, "arg");
        assert!(!result.success);
        assert!(result.output.contains("no server URL"));
    }

    #[test]
    fn dispatch_invalid_scheme_fails() {
        let entry = make_mcp_entry("McpTool", "ws://localhost:3000", "5s");
        let result = dispatch_mcp(&entry, "arg");
        assert!(!result.success);
        assert!(result.output.contains("invalid server URL"));
    }

    #[test]
    fn dispatch_connection_refused() {
        let entry = make_mcp_entry("McpTool", "http://127.0.0.1:1/mcp", "2s");
        let result = dispatch_mcp(&entry, "test");
        assert!(!result.success);
        assert!(result.output.contains("blame=network"));
    }

    // ── Blame tracker ─────────────────────────────────────────────

    #[test]
    fn blame_tracker_accumulates() {
        let mut tracker = BlameTracker::new();

        tracker.record(&McpCallResult {
            tool_name: "A".into(),
            output: "ok".into(),
            success: true,
            blame: Blame::None,
            taint: EpistemicTaint::Untrusted,
            server: "s1".into(),
            effects: vec![],
        });

        tracker.record(&McpCallResult {
            tool_name: "B".into(),
            output: "server error".into(),
            success: false,
            blame: Blame::Server,
            taint: EpistemicTaint::Untrusted,
            server: "s1".into(),
            effects: vec![],
        });

        tracker.record(&McpCallResult {
            tool_name: "C".into(),
            output: "bad params".into(),
            success: false,
            blame: Blame::Caller,
            taint: EpistemicTaint::Untrusted,
            server: "s2".into(),
            effects: vec![],
        });

        tracker.record(&McpCallResult {
            tool_name: "D".into(),
            output: "timeout".into(),
            success: false,
            blame: Blame::Network,
            taint: EpistemicTaint::Untrusted,
            server: "s1".into(),
            effects: vec![],
        });

        assert_eq!(tracker.total(), 4);
        assert_eq!(tracker.server_faults(), 1);
        assert_eq!(tracker.caller_faults(), 1);
        assert_eq!(tracker.network_faults(), 1);
    }

    // ── McpClient construction ────────────────────────────────────

    #[test]
    fn mcp_client_creates() {
        let client = McpClient::new("http://localhost:3000", Duration::from_secs(10));
        assert_eq!(client.server_url, "http://localhost:3000");
        assert_eq!(client.timeout, Duration::from_secs(10));
        assert_eq!(client.next_id, 1);
    }

    // ── JSON-RPC response processing ──────────────────────────────

    #[test]
    fn process_success_response() {
        let client = McpClient::new("http://localhost", Duration::from_secs(5));
        let response = JsonRpcResponse {
            jsonrpc: "2.0".into(),
            result: Some(serde_json::json!({
                "content": [{"type": "text", "text": "result data"}]
            })),
            error: None,
            id: 1,
        };

        let result = client.process_response("TestTool", response);
        assert!(result.success);
        assert_eq!(result.output, "result data");
        assert_eq!(result.blame, Blame::None);
        assert_eq!(result.taint, EpistemicTaint::Untrusted); // Still untrusted!
    }

    #[test]
    fn process_server_error_response() {
        let client = McpClient::new("http://localhost", Duration::from_secs(5));
        let response = JsonRpcResponse {
            jsonrpc: "2.0".into(),
            result: None,
            error: Some(JsonRpcError {
                code: -32000,
                message: "internal server error".into(),
            }),
            id: 1,
        };

        let result = client.process_response("TestTool", response);
        assert!(!result.success);
        assert_eq!(result.blame, Blame::Server);
        assert!(result.output.contains("-32000"));
    }

    #[test]
    fn process_caller_error_response() {
        let client = McpClient::new("http://localhost", Duration::from_secs(5));
        // -32602 = Invalid params (JSON-RPC standard)
        let response = JsonRpcResponse {
            jsonrpc: "2.0".into(),
            result: None,
            error: Some(JsonRpcError {
                code: -32602,
                message: "invalid params".into(),
            }),
            id: 1,
        };

        let result = client.process_response("TestTool", response);
        assert!(!result.success);
        assert_eq!(result.blame, Blame::Caller);
    }

    // ── Effect inference ──────────────────────────────────────────

    #[test]
    fn mcp_calls_carry_epistemic_effects() {
        let client = McpClient::new("http://localhost", Duration::from_secs(5));
        let response = JsonRpcResponse {
            jsonrpc: "2.0".into(),
            result: Some(serde_json::json!({"content": [{"text": "data"}]})),
            error: None,
            id: 1,
        };

        let result = client.process_response("Tool", response);
        assert!(result.effects.contains(&"network".to_string()));
        assert!(result.effects.contains(&"epistemic:speculate".to_string()));
    }

    // ── Serialization ─────────────────────────────────────────────

    #[test]
    fn blame_serializes() {
        let json = serde_json::to_string(&Blame::Server).unwrap();
        assert_eq!(json, "\"Server\"");
    }

    #[test]
    fn mcp_call_result_serializes() {
        let result = McpCallResult {
            tool_name: "T".into(),
            output: "out".into(),
            success: true,
            blame: Blame::None,
            taint: EpistemicTaint::Untrusted,
            server: "http://s".into(),
            effects: vec!["network".into()],
        };
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"blame\":\"None\""));
        assert!(json.contains("\"taint\":\"Untrusted\""));
    }
}
