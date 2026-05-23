//! MCP protocol over stdio + JSON-RPC 2.0.
//!
//! The Model Context Protocol (MCP, Anthropic 2024) is a minimal
//! JSON-RPC 2.0 dialect:
//!
//! - Transport: line-delimited UTF-8 JSON frames on stdin/stdout (one
//!   frame per line; trailing newline mandatory).
//! - Handshake: client sends `initialize` (with its protocol-version);
//!   server replies with its own protocolVersion + capabilities; client
//!   sends `notifications/initialized`; ready.
//! - Request/response: `id` echoes; `result` xor `error`.
//! - Notifications: `id` absent → no reply.
//! - Methods we serve (Phase 0): `initialize`, `tools/list`,
//!   `tools/call`, `resources/list`, `resources/read`, `ping`.
//!
//! Anything beyond this subset returns `-32601 method not found`.
//! Everything is dispatched off a single match in [`dispatch`].

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

use crate::knowledge::Catalog;
use crate::{resources, tools};

/// The MCP protocol version this server speaks. Bumped only when the
/// server's externally-visible JSON-RPC shape changes incompatibly.
pub const MCP_PROTOCOL_VERSION: &str = "2024-11-05";

/// Server-side product identifier (surfaced in the `initialize`
/// response so the agent can show it to the user / log it).
pub const SERVER_NAME: &str = "axon-emcp";

/// Run the stdio MCP loop. Returns `Ok(())` on clean EOF (the agent
/// closed the pipe); `Err` on a fatal transport failure (the agent
/// produced bytes that don't parse as line-delimited JSON, or we lost
/// the ability to write stdout).
pub async fn run_stdio(catalog: Catalog) -> std::io::Result<()> {
    let catalog = Arc::new(catalog);
    let mut stdin = BufReader::new(tokio::io::stdin());
    let mut stdout = tokio::io::stdout();
    let mut line = String::new();
    loop {
        line.clear();
        let n = stdin.read_line(&mut line).await?;
        if n == 0 {
            // EOF — agent closed stdin. Clean shutdown.
            return Ok(());
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        tracing::debug!(bytes = trimmed.len(), "← request");
        let response = handle_one(trimmed, &catalog).await;
        if let Some(resp_bytes) = response {
            stdout.write_all(&resp_bytes).await?;
            stdout.write_all(b"\n").await?;
            stdout.flush().await?;
            tracing::debug!(bytes = resp_bytes.len(), "→ response");
        }
        // Notifications (no `id`) produce no response — we silently
        // continue without writing to stdout.
    }
}

/// Parse one JSON-RPC frame, dispatch it, and serialise the reply.
///
/// Returns `Some(bytes)` for a request (a reply is owed) and `None` for
/// a notification (no reply by JSON-RPC spec).
async fn handle_one(line: &str, catalog: &Arc<Catalog>) -> Option<Vec<u8>> {
    // First, try to parse as a generic `Request` so we can recover the
    // `id` for error responses even when the method/params are malformed.
    let parsed: Result<Request, serde_json::Error> = serde_json::from_str(line);
    let req = match parsed {
        Ok(r) => r,
        Err(e) => {
            // We can't recover the id — JSON-RPC §5 says respond with a
            // null-id error in this case.
            return Some(error_response(
                Value::Null,
                JsonRpcError::parse_error(&e.to_string()),
            ));
        }
    };

    let is_notification = req.id.is_none();
    let id = req.id.clone().unwrap_or(Value::Null);

    let outcome = dispatch(&req, catalog).await;

    if is_notification {
        // No reply per JSON-RPC §4.1.
        return None;
    }
    Some(match outcome {
        Ok(result) => success_response(id, result),
        Err(err) => error_response(id, err),
    })
}

/// Method router. Every supported MCP method dispatches here; unknown
/// methods produce `-32601 method not found`.
async fn dispatch(req: &Request, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    match req.method.as_str() {
        // ── Lifecycle ────────────────────────────────────────────────────
        "initialize" => Ok(initialize_response()),
        "notifications/initialized" => Ok(Value::Null), // ignored, no-op
        "ping" => Ok(Value::Object(serde_json::Map::new())),

        // ── Tools ────────────────────────────────────────────────────────
        "tools/list" => Ok(json!({ "tools": tools::list() })),
        "tools/call" => tools::dispatch_call(req.params.clone(), catalog).await,

        // ── Resources ────────────────────────────────────────────────────
        "resources/list" => Ok(json!({ "resources": resources::list(catalog) })),
        "resources/read" => resources::dispatch_read(req.params.clone(), catalog),

        // ── Anything else: per JSON-RPC §5.1, `-32601 method not found`.
        other => Err(JsonRpcError {
            code: -32601,
            message: format!("method not found: `{other}`"),
            data: None,
        }),
    }
}

/// The `initialize` response carries the server's protocol-version +
/// capabilities. Our capabilities are minimal-but-honest: we serve tools
/// and resources, not prompts (yet) or sampling.
fn initialize_response() -> Value {
    json!({
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {
            "name": SERVER_NAME,
            "version": env!("CARGO_PKG_VERSION"),
        },
        "capabilities": {
            "tools": { "listChanged": false },
            "resources": { "listChanged": false, "subscribe": false },
            // Future phases will add: "prompts": { … }, "logging": { … }.
        },
        "instructions": include_str!("server_instructions.txt"),
    })
}

// ─── JSON-RPC 2.0 frame types ────────────────────────────────────────────

/// One JSON-RPC 2.0 request frame. `params` is captured as `Value` so
/// each tool can deserialise the shape it expects without forcing the
/// dispatcher to know every schema.
#[derive(Debug, Deserialize)]
struct Request {
    /// `"2.0"` — JSON-RPC version tag. Required by spec. We accept any
    /// value (some agents send `"2"` or omit it) to be permissive.
    #[serde(default)]
    #[allow(dead_code)]
    jsonrpc: String,
    /// The method name (e.g. `"tools/list"`).
    method: String,
    /// Method-specific parameters. `null` / missing is fine; the tool
    /// handler decides what shape it needs.
    #[serde(default)]
    params: Value,
    /// Request id. **Absent** ⇒ notification (no reply). Present ⇒ must
    /// be echoed in the reply.
    #[serde(default)]
    id: Option<Value>,
}

/// JSON-RPC 2.0 error object.
#[derive(Debug, Serialize, Clone)]
pub struct JsonRpcError {
    /// Numeric error code (-32700 to -32603 are reserved by JSON-RPC).
    pub code: i64,
    /// Human-readable message — surfaced to the agent verbatim.
    pub message: String,
    /// Optional machine-readable detail. We attach typed diagnostic data
    /// here for `axon.check` etc.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl JsonRpcError {
    /// `-32700` — invalid JSON received by the server (parse error).
    pub fn parse_error(detail: &str) -> Self {
        Self { code: -32700, message: format!("parse error: {detail}"), data: None }
    }
    /// `-32602` — the method exists but the params are invalid.
    pub fn invalid_params(detail: impl Into<String>) -> Self {
        Self { code: -32602, message: detail.into(), data: None }
    }
    /// `-32603` — internal server fault. Used sparingly; most errors
    /// have a more specific code.
    pub fn internal(detail: impl Into<String>) -> Self {
        Self { code: -32603, message: detail.into(), data: None }
    }
}

fn success_response(id: Value, result: Value) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": result,
    }))
    .expect("serialising a JSON-RPC success frame cannot fail")
}

fn error_response(id: Value, err: JsonRpcError) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": err,
    }))
    .expect("serialising a JSON-RPC error frame cannot fail")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cat() -> Arc<Catalog> {
        Arc::new(Catalog::empty_for_tests())
    }

    #[tokio::test]
    async fn initialize_carries_version_capabilities_and_instructions() {
        let req = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}"#;
        let resp = handle_one(req, &cat()).await.expect("reply owed");
        let v: Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["jsonrpc"], "2.0");
        assert_eq!(v["id"], 1);
        assert_eq!(v["result"]["protocolVersion"], MCP_PROTOCOL_VERSION);
        assert_eq!(v["result"]["serverInfo"]["name"], SERVER_NAME);
        assert!(v["result"]["capabilities"]["tools"].is_object());
        assert!(v["result"]["capabilities"]["resources"].is_object());
        assert!(v["result"]["instructions"].as_str().unwrap().contains("AXON"));
    }

    #[tokio::test]
    async fn notification_produces_no_reply() {
        let req = r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#;
        let resp = handle_one(req, &cat()).await;
        assert!(resp.is_none(), "notifications must not yield a reply");
    }

    #[tokio::test]
    async fn unknown_method_returns_method_not_found() {
        let req = r#"{"jsonrpc":"2.0","id":7,"method":"axon.does_not_exist"}"#;
        let resp = handle_one(req, &cat()).await.expect("reply owed");
        let v: Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["error"]["code"], -32601);
        assert!(v["error"]["message"].as_str().unwrap().contains("not found"));
    }

    #[tokio::test]
    async fn malformed_json_returns_parse_error_with_null_id() {
        let resp = handle_one("{ not valid json", &cat()).await.expect("reply owed");
        let v: Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["error"]["code"], -32700);
        assert_eq!(v["id"], Value::Null);
    }

    #[tokio::test]
    async fn tools_list_returns_an_array() {
        let req = r#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#;
        let resp = handle_one(req, &cat()).await.expect("reply owed");
        let v: Value = serde_json::from_slice(&resp).unwrap();
        let tools = v["result"]["tools"].as_array().expect("tools array");
        assert!(!tools.is_empty(), "we ship at least one tool on day 0");
        // Every tool advertises {name, description, inputSchema}.
        for t in tools {
            assert!(t["name"].is_string());
            assert!(t["description"].is_string());
            assert!(t["inputSchema"].is_object());
        }
    }

    #[tokio::test]
    async fn resources_list_returns_an_array() {
        let req = r#"{"jsonrpc":"2.0","id":3,"method":"resources/list"}"#;
        let resp = handle_one(req, &cat()).await.expect("reply owed");
        let v: Value = serde_json::from_slice(&resp).unwrap();
        assert!(v["result"]["resources"].is_array());
    }
}
