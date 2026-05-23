//! MCP tools the connected agent can invoke.
//!
//! Each tool is a `(name, description, inputSchema)` triple advertised
//! via `tools/list`, plus a handler dispatched via `tools/call`. The
//! `inputSchema` is JSON Schema (draft-07) — the agent uses it to
//! shape its calls, so it must be honest about every required field.
//!
//! Phase 0 ships **two** tools:
//!
//! - `axon.primitives` — list every primitive (optionally filtered by
//!   category). Lets the agent ground itself in the catalogue before
//!   composing.
//! - `axon.primitive_doc` — fetch the full markdown reference for one
//!   primitive (grammar, top-level status, since-version, prose body).
//!
//! Subsequent phases extend this set with `axon.check`, `axon.parse`,
//! `axon.examples`, `axon.compose`, `axon.validate_pattern`.

use std::sync::Arc;

use serde::Deserialize;
use serde_json::{json, Value};

use crate::knowledge::{Catalog, Category};
use crate::server::JsonRpcError;

/// Build the `tools/list` payload. Sorted by name for a deterministic
/// wire — the agent should not see the order shift across runs.
pub fn list() -> Vec<Value> {
    vec![
        json!({
            "name": "axon.primitives",
            "description": "List every AXON primitive known to this server. \
                Optionally filter by category. Use this FIRST when you need \
                to know what's available before composing a program. \
                Returns a sorted array of {name, summary, category, top_level, since}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "cognition", "cognitive_io", "data_plane",
                            "session_types", "wire", "operators"
                        ],
                        "description": "Limit to one primitive family. Omit to list all."
                    }
                },
                "additionalProperties": false
            }
        }),
        json!({
            "name": "axon.primitive_doc",
            "description": "Fetch the full reference for one AXON primitive by canonical \
                name. Returns its grammar fragment, top-level status, the cycle that \
                introduced it, and the complete markdown body (semantic constraints, \
                examples, what-it-is-not, see-also). ALWAYS call this before generating \
                a program that uses the primitive — the grammar is precise and the \
                diagnostics are strict.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Canonical primitive name (e.g. \"persona\", \
                            \"flow\", \"socket\", \"axonendpoint\")."
                    }
                },
                "required": ["name"],
                "additionalProperties": false
            }
        }),
    ]
}

/// Dispatch a `tools/call` request. `params` is the raw `params` field
/// of the JSON-RPC envelope: `{ "name": "...", "arguments": { ... } }`.
pub async fn dispatch_call(params: Value, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    let call: ToolCall = serde_json::from_value(params)
        .map_err(|e| JsonRpcError::invalid_params(format!("tools/call params: {e}")))?;
    match call.name.as_str() {
        "axon.primitives" => primitives(call.arguments, catalog),
        "axon.primitive_doc" => primitive_doc(call.arguments, catalog),
        other => Err(JsonRpcError {
            code: -32601,
            message: format!("unknown tool: `{other}`"),
            data: None,
        }),
    }
}

#[derive(Debug, Deserialize)]
struct ToolCall {
    name: String,
    #[serde(default)]
    arguments: Value,
}

// ─── axon.primitives ─────────────────────────────────────────────────────

#[derive(Debug, Deserialize, Default)]
struct PrimitivesArgs {
    #[serde(default)]
    category: Option<String>,
}

fn primitives(args: Value, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    let args: PrimitivesArgs = if args.is_null() {
        PrimitivesArgs::default()
    } else {
        serde_json::from_value(args)
            .map_err(|e| JsonRpcError::invalid_params(format!("axon.primitives: {e}")))?
    };
    let filter = args.category.as_deref().map(parse_category).transpose()?;
    let entries: Vec<Value> = catalog
        .primitives()
        .filter(|p| filter.map(|f| p.category == f).unwrap_or(true))
        .map(|p| {
            json!({
                "name": p.name,
                "summary": p.summary,
                "category": p.category.as_str(),
                "top_level": p.top_level,
                "since": p.since,
            })
        })
        .collect();
    Ok(mcp_text_result(&serde_json::to_string_pretty(&json!({
        "count": entries.len(),
        "primitives": entries,
    })).unwrap()))
}

fn parse_category(s: &str) -> Result<Category, JsonRpcError> {
    match s {
        "cognition" => Ok(Category::Cognition),
        "cognitive_io" => Ok(Category::CognitiveIo),
        "data_plane" => Ok(Category::DataPlane),
        "session_types" => Ok(Category::SessionTypes),
        "wire" => Ok(Category::Wire),
        "operators" => Ok(Category::Operators),
        other => Err(JsonRpcError::invalid_params(format!(
            "unknown category `{other}` — valid: cognition, cognitive_io, \
             data_plane, session_types, wire, operators"
        ))),
    }
}

// ─── axon.primitive_doc ──────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct PrimitiveDocArgs {
    name: String,
}

fn primitive_doc(args: Value, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    let args: PrimitiveDocArgs = serde_json::from_value(args)
        .map_err(|e| JsonRpcError::invalid_params(format!("axon.primitive_doc: {e}")))?;
    let prim = catalog.primitive(&args.name).ok_or_else(|| JsonRpcError {
        code: -32602,
        message: format!(
            "unknown primitive `{}` — call axon.primitives to see the catalogue",
            args.name
        ),
        data: None,
    })?;
    // We return both a structured `metadata` block (for the agent's
    // programmatic use) and a `text` block (the markdown body — which
    // is what the agent should actually quote / read).
    let payload = json!({
        "name": prim.name,
        "summary": prim.summary,
        "category": prim.category.as_str(),
        "top_level": prim.top_level,
        "grammar": prim.grammar,
        "since": prim.since,
        "body_markdown": prim.body,
    });
    Ok(json!({
        "content": [
            { "type": "text", "text": serde_json::to_string_pretty(&payload).unwrap() }
        ],
        "isError": false,
    }))
}

/// Wrap a string result in the canonical MCP `tools/call` content
/// shape: `{ content: [{ type: "text", text: ... }], isError: false }`.
fn mcp_text_result(text: &str) -> Value {
    json!({
        "content": [
            { "type": "text", "text": text }
        ],
        "isError": false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn catalog_with(name: &str, top: bool, cat: Category) -> Arc<Catalog> {
        // Build a real Catalog by writing one md file to a tempdir and
        // loading from it — exercises the same path the server takes
        // at startup. The dir name carries a monotonic counter so
        // parallel test invocations + repeated test runs never collide.
        use std::io::Write;
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let n = N.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "axon-emcp-toolstest-{}-{n}-{name}",
            std::process::id(),
        ));
        // Wipe any stale corpus from a prior run before writing.
        let _ = std::fs::remove_dir_all(&dir);
        let prims = dir.join("primitives");
        std::fs::create_dir_all(&prims).unwrap();
        let mut f = std::fs::File::create(prims.join(format!("{name}.md"))).unwrap();
        let body = format!(
            "---\nname: {name}\nsummary: test summary\ncategory: {}\ntop_level: {}\n\
             since: Fase X\ngrammar: |\n  {name} ...\n---\n\nBody.\n",
            cat.as_str(),
            top,
        );
        f.write_all(body.as_bytes()).unwrap();
        Arc::new(Catalog::load_from(&dir).unwrap())
    }

    #[tokio::test]
    async fn primitives_returns_every_entry_when_unfiltered() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({ "name": "axon.primitives", "arguments": {} }),
            &cat,
        )
        .await
        .unwrap();
        let text = v["content"][0]["text"].as_str().unwrap();
        let parsed: Value = serde_json::from_str(text).unwrap();
        assert_eq!(parsed["count"], 1);
        assert_eq!(parsed["primitives"][0]["name"], "socket");
        assert_eq!(parsed["primitives"][0]["top_level"], true);
    }

    #[tokio::test]
    async fn primitives_filters_by_category() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({ "name": "axon.primitives",
                    "arguments": { "category": "session_types" } }),
            &cat,
        )
        .await
        .unwrap();
        let parsed: Value =
            serde_json::from_str(v["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(parsed["count"], 1);
        // Filter that excludes:
        let v2 = dispatch_call(
            json!({ "name": "axon.primitives",
                    "arguments": { "category": "cognition" } }),
            &cat,
        )
        .await
        .unwrap();
        let parsed2: Value =
            serde_json::from_str(v2["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(parsed2["count"], 0);
    }

    #[tokio::test]
    async fn primitives_rejects_unknown_category() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let err = dispatch_call(
            json!({ "name": "axon.primitives",
                    "arguments": { "category": "bogus" } }),
            &cat,
        )
        .await
        .expect_err("must reject");
        assert_eq!(err.code, -32602);
        assert!(err.message.contains("unknown category"));
    }

    #[tokio::test]
    async fn primitive_doc_returns_full_metadata_and_body() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({ "name": "axon.primitive_doc",
                    "arguments": { "name": "socket" } }),
            &cat,
        )
        .await
        .unwrap();
        let text = v["content"][0]["text"].as_str().unwrap();
        let payload: Value = serde_json::from_str(text).unwrap();
        assert_eq!(payload["name"], "socket");
        assert_eq!(payload["top_level"], true);
        assert!(payload["body_markdown"].as_str().unwrap().contains("Body."));
        assert!(payload["grammar"].as_str().unwrap().contains("socket"));
    }

    #[tokio::test]
    async fn primitive_doc_rejects_unknown_name() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let err = dispatch_call(
            json!({ "name": "axon.primitive_doc",
                    "arguments": { "name": "does_not_exist" } }),
            &cat,
        )
        .await
        .expect_err("must reject");
        assert!(err.message.contains("unknown primitive"));
        assert!(err.message.contains("axon.primitives"));
    }

    #[tokio::test]
    async fn unknown_tool_returns_method_not_found() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let err = dispatch_call(
            json!({ "name": "axon.does_not_exist", "arguments": {} }),
            &cat,
        )
        .await
        .expect_err("must reject");
        assert_eq!(err.code, -32601);
    }
}
