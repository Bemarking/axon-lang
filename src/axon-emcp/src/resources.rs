//! MCP resources the connected agent can read by URI.
//!
//! Where **tools** are *actions* (the agent picks one, supplies
//! arguments, gets a result), **resources** are *citation-ready
//! references* — the agent reads them when it wants to quote a fact in
//! its reply. The two layers serve the same knowledge base; the
//! difference is whether the agent's prompt includes the URL (resource)
//! or whether the agent constructs a call (tool).
//!
//! URI scheme: `axon://`. Phase 0 ships one family:
//!
//! - `axon://primitives/<name>` — the markdown body for a primitive.
//!
//! Subsequent phases extend with:
//! - `axon://grammar/top_level`, `axon://grammar/composition`,
//!   `axon://grammar/ebnf`
//! - `axon://logic/flow_composition`, `axon://logic/session_duality`
//! - `axon://compliance/<framework>`

use std::sync::Arc;

use serde::Deserialize;
use serde_json::{json, Value};

use crate::knowledge::Catalog;
use crate::server::JsonRpcError;

/// Build the `resources/list` payload. Includes one entry per
/// primitive in the catalogue (so the agent can discover everything
/// without first calling `axon.primitives`).
pub fn list(catalog: &Arc<Catalog>) -> Vec<Value> {
    catalog
        .primitives()
        .map(|p| {
            json!({
                "uri": format!("axon://primitives/{}", p.name),
                "name": format!("AXON primitive: {}", p.name),
                "description": p.summary,
                "mimeType": "text/markdown",
            })
        })
        .collect()
}

/// Dispatch a `resources/read` request. Params shape (per MCP spec):
/// `{ "uri": "..." }`.
pub fn dispatch_read(params: Value, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    let req: ReadParams = serde_json::from_value(params)
        .map_err(|e| JsonRpcError::invalid_params(format!("resources/read params: {e}")))?;
    let parsed = parse_axon_uri(&req.uri)?;
    match parsed {
        AxonUri::Primitive(name) => read_primitive(name, &req.uri, catalog),
    }
}

#[derive(Debug, Deserialize)]
struct ReadParams {
    uri: String,
}

#[derive(Debug)]
enum AxonUri<'a> {
    Primitive(&'a str),
}

fn parse_axon_uri(uri: &str) -> Result<AxonUri<'_>, JsonRpcError> {
    let rest = uri.strip_prefix("axon://").ok_or_else(|| JsonRpcError {
        code: -32602,
        message: format!(
            "unsupported scheme in `{uri}` — this server serves `axon://` URIs only"
        ),
        data: None,
    })?;
    let (kind, tail) = rest.split_once('/').ok_or_else(|| JsonRpcError {
        code: -32602,
        message: format!("malformed axon:// URI `{uri}` — expected `axon://<kind>/<path>`"),
        data: None,
    })?;
    match kind {
        "primitives" => Ok(AxonUri::Primitive(tail)),
        other => Err(JsonRpcError {
            code: -32601,
            message: format!(
                "unknown axon:// resource kind `{other}` — Phase 0 serves \
                 only `axon://primitives/<name>`"
            ),
            data: None,
        }),
    }
}

fn read_primitive(name: &str, uri: &str, catalog: &Arc<Catalog>) -> Result<Value, JsonRpcError> {
    let prim = catalog.primitive(name).ok_or_else(|| JsonRpcError {
        code: -32602,
        message: format!(
            "unknown primitive `{name}` in `{uri}` — call axon.primitives to list available names"
        ),
        data: None,
    })?;
    // The `contents` array carries one entry per "fragment" of the
    // resource. We surface a single markdown blob: the frontmatter
    // header (machine-friendly summary) plus the prose body.
    let header = format!(
        "<!-- axon-emcp metadata -->\n\
         - **name**: `{}`\n- **summary**: {}\n- **category**: {}\n\
         - **top-level**: {}\n- **since**: {}\n\n",
        prim.name,
        prim.summary,
        prim.category.as_str(),
        prim.top_level,
        prim.since,
    );
    let text = format!("{header}{}", prim.body);
    Ok(json!({
        "contents": [
            {
                "uri": uri,
                "mimeType": "text/markdown",
                "text": text,
            }
        ]
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::knowledge::Category;
    use std::io::Write;
    use std::sync::Arc;

    fn catalog_with(name: &str) -> Arc<Catalog> {
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let n = N.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "axon-emcp-restest-{}-{n}-{name}",
            std::process::id(),
        ));
        let _ = std::fs::remove_dir_all(&dir);
        let prims = dir.join("primitives");
        std::fs::create_dir_all(&prims).unwrap();
        let mut f = std::fs::File::create(prims.join(format!("{name}.md"))).unwrap();
        write!(
            f,
            "---\nname: {name}\nsummary: s\ncategory: session_types\n\
             top_level: true\nsince: Fase X\n---\n\nBody.\n"
        )
        .unwrap();
        Arc::new(Catalog::load_from(&dir).unwrap())
    }

    #[test]
    fn list_emits_one_resource_per_primitive() {
        let cat = catalog_with("socket");
        let list = list(&cat);
        assert_eq!(list.len(), 1);
        assert_eq!(list[0]["uri"], "axon://primitives/socket");
        assert_eq!(list[0]["mimeType"], "text/markdown");
    }

    #[test]
    fn dispatch_read_returns_markdown_with_metadata_header() {
        let cat = catalog_with("socket");
        let v = dispatch_read(json!({ "uri": "axon://primitives/socket" }), &cat).unwrap();
        let text = v["contents"][0]["text"].as_str().unwrap();
        assert!(text.contains("axon-emcp metadata"));
        assert!(text.contains("**name**: `socket`"));
        assert!(text.contains("**top-level**: true"));
        assert!(text.contains("Body."));
    }

    #[test]
    fn dispatch_read_rejects_unsupported_scheme() {
        let cat = catalog_with("socket");
        let err = dispatch_read(json!({ "uri": "https://example.com/x" }), &cat)
            .expect_err("must reject");
        assert!(err.message.contains("unsupported scheme"));
    }

    #[test]
    fn dispatch_read_rejects_unknown_resource_kind() {
        let cat = catalog_with("socket");
        let err = dispatch_read(json!({ "uri": "axon://does_not_exist/x" }), &cat)
            .expect_err("must reject");
        assert!(err.message.contains("unknown axon:// resource kind"));
    }

    #[test]
    fn dispatch_read_rejects_unknown_primitive() {
        let cat = catalog_with("socket");
        let err = dispatch_read(json!({ "uri": "axon://primitives/nope" }), &cat)
            .expect_err("must reject");
        assert!(err.message.contains("unknown primitive"));
    }

    // Sanity that the Category enum import resolves (avoids unused-import
    // warnings on this module while the resources surface is small).
    #[test]
    fn category_str_smoke() {
        assert_eq!(Category::SessionTypes.as_str(), "session_types");
    }
}
