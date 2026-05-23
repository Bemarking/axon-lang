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

use crate::compiler_pipeline;
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
        json!({
            "name": "axon.check",
            "description": "Validate AXON source code. Runs the same lex → parse → \
                type-check pipeline the `axon check` CLI uses, and returns structured \
                diagnostics (severity + stage + message + line/column). Use this AFTER \
                generating a program, BEFORE presenting it to the user as working. \
                Never claim a program is correct until axon.check returns ok=true. The \
                pipeline stops at the first failing stage: a lex error means parse + \
                type-check did not run.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "The complete AXON source text to validate. Pass \
                            the whole program (top-level declarations only — fragments \
                            are usually rejected)."
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional virtual filename for the diagnostics. \
                            Defaults to \"<axon.check input>\"."
                    }
                },
                "required": ["source"],
                "additionalProperties": false
            }
        }),
        json!({
            "name": "axon.parse",
            "description": "Parse AXON source to its Intermediate Representation (IR). \
                Returns the same JSON shape `axon parse` would print: a `Program` node \
                whose children are every declared primitive (`flows`, `personas`, \
                `axonendpoints`, `axonstores`, `sockets`, `sessions`, …). Use this when \
                you need to REASON ABOUT what you just wrote — e.g. to confirm the \
                program has the right shape before refining it. On failure returns the \
                same diagnostic shape as axon.check.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "The complete AXON source text to parse."
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional virtual filename. Defaults to \
                            \"<axon.parse input>\"."
                    }
                },
                "required": ["source"],
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
        "axon.check" => check(call.arguments),
        "axon.parse" => parse(call.arguments),
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

// ─── axon.check ──────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct CheckArgs {
    source: String,
    #[serde(default)]
    filename: Option<String>,
}

fn check(args: Value) -> Result<Value, JsonRpcError> {
    let args: CheckArgs = serde_json::from_value(args)
        .map_err(|e| JsonRpcError::invalid_params(format!("axon.check: {e}")))?;
    let filename = args.filename.as_deref().unwrap_or("<axon.check input>");
    let outcome = compiler_pipeline::run(&args.source, filename);
    let payload = compiler_pipeline::outcome_to_check_payload(&outcome);
    // The MCP `tools/call` contract: wrap the payload in `content` so
    // the agent's parser sees a uniform `{content, isError}` envelope.
    // `isError` flips on a *blocking* check failure (so the agent's
    // reflex is "look at the errors", not "the tool itself broke").
    let is_error = !payload["ok"].as_bool().unwrap_or(true);
    Ok(json!({
        "content": [
            { "type": "text", "text": serde_json::to_string_pretty(&payload).unwrap() }
        ],
        "isError": is_error,
    }))
}

// ─── axon.parse ──────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct ParseArgs {
    source: String,
    #[serde(default)]
    filename: Option<String>,
}

fn parse(args: Value) -> Result<Value, JsonRpcError> {
    let args: ParseArgs = serde_json::from_value(args)
        .map_err(|e| JsonRpcError::invalid_params(format!("axon.parse: {e}")))?;
    let filename = args.filename.as_deref().unwrap_or("<axon.parse input>");
    let outcome = compiler_pipeline::run(&args.source, filename);
    let payload = compiler_pipeline::outcome_to_parse_payload(outcome);
    let is_error = !payload["ok"].as_bool().unwrap_or(true);
    Ok(json!({
        "content": [
            { "type": "text", "text": serde_json::to_string_pretty(&payload).unwrap() }
        ],
        "isError": is_error,
    }))
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

    // ── Phase 1: axon.check ─────────────────────────────────────────────

    #[tokio::test]
    async fn check_returns_ok_for_a_well_formed_program() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({
                "name": "axon.check",
                "arguments": { "source": "persona X { tone: precise }" }
            }),
            &cat,
        )
        .await
        .unwrap();
        assert_eq!(v["isError"], false);
        let payload: Value =
            serde_json::from_str(v["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(payload["ok"], true);
        assert_eq!(payload["errors"].as_array().unwrap().len(), 0);
    }

    #[tokio::test]
    async fn check_returns_diagnostic_with_isError_on_syntax_garbage() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({
                "name": "axon.check",
                "arguments": { "source": "@@@" }
            }),
            &cat,
        )
        .await
        .unwrap();
        // `isError` MUST flip — agents key off this for the "go fix it"
        // reflex; a malformed program is a typed failure, not a tool fault.
        assert_eq!(v["isError"], true);
        let payload: Value =
            serde_json::from_str(v["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(payload["ok"], false);
        let errors = payload["errors"].as_array().unwrap();
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0]["severity"], "error");
        // The stage is whichever the pipeline failed at (lex or parse —
        // depends on how `@@@` is classified). Either is acceptable, but
        // it must be one of the closed catalog values.
        let stage = errors[0]["stage"].as_str().unwrap();
        assert!(matches!(stage, "lex" | "parse"));
        assert!(errors[0]["line"].as_u64().unwrap() >= 1);
    }

    #[tokio::test]
    async fn check_rejects_missing_source_argument() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let err = dispatch_call(
            json!({ "name": "axon.check", "arguments": {} }),
            &cat,
        )
        .await
        .expect_err("missing required `source` must reject");
        assert_eq!(err.code, -32602);
        assert!(err.message.contains("axon.check"));
    }

    #[tokio::test]
    async fn check_accepts_optional_filename_for_diagnostics() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        // The filename does not affect the diagnostic shape we surface
        // (we don't pipe source_snippet through to the agent yet) but
        // it must be accepted as an optional argument.
        let v = dispatch_call(
            json!({
                "name": "axon.check",
                "arguments": {
                    "source": "persona X { tone: precise }",
                    "filename": "my_draft.axon"
                }
            }),
            &cat,
        )
        .await
        .unwrap();
        assert_eq!(v["isError"], false);
    }

    // ── Phase 1: axon.parse ─────────────────────────────────────────────

    #[tokio::test]
    async fn parse_returns_ir_for_a_well_formed_program() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({
                "name": "axon.parse",
                "arguments": { "source": "persona X { tone: precise }" }
            }),
            &cat,
        )
        .await
        .unwrap();
        assert_eq!(v["isError"], false);
        let payload: Value =
            serde_json::from_str(v["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(payload["ok"], true);
        assert_eq!(payload["stage"], "ir_generate");
        // The IR's root is a `Program` node. The agent uses this to
        // confirm the file's top-level shape before composing more.
        assert_eq!(payload["ir"]["node_type"], "program");
        // Personas declared at top-level land in the `personas` array.
        let personas = payload["ir"]["personas"].as_array().unwrap();
        assert_eq!(personas.len(), 1);
        assert_eq!(personas[0]["name"], "X");
    }

    #[tokio::test]
    async fn parse_returns_same_diagnostic_shape_as_check_on_failure() {
        let cat = catalog_with("socket", true, Category::SessionTypes);
        let v = dispatch_call(
            json!({
                "name": "axon.parse",
                "arguments": { "source": "@@@" }
            }),
            &cat,
        )
        .await
        .unwrap();
        assert_eq!(v["isError"], true);
        let payload: Value =
            serde_json::from_str(v["content"][0]["text"].as_str().unwrap()).unwrap();
        // The failure shape is uniform with axon.check — same keys,
        // same severity vocabulary. (parse just adds `ir` on success.)
        assert_eq!(payload["ok"], false);
        assert!(payload["errors"].as_array().unwrap().len() >= 1);
        assert!(payload["ir"].is_null());
    }
}
