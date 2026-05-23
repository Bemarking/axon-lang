//! `axon-emcp` — the official ℰMCP (Epistemic Model Context Protocol)
//! server for AXON.
//!
//! Speaks MCP over stdio + JSON-RPC 2.0. Once an agent (Claude Code,
//! Codex, Cursor, Continue, Cline, …) launches this binary as an MCP
//! subprocess, it can:
//!
//! - Call **tools** (`axon.check`, `axon.parse`, `axon.primitives`,
//!   `axon.primitive_doc`, `axon.examples`, `axon.compose`, …) to
//!   validate code, look up grammar, and request idiomatic scaffolds.
//! - Read **resources** (`axon://primitives/{name}`,
//!   `axon://grammar/top_level`, …) — the canonical, citation-ready
//!   reference material the agent can quote in its replies.
//!
//! The wire is **stdio-only**: STDOUT carries JSON-RPC frames (one per
//! line), STDERR carries logs. Anything written to stdout that is not a
//! valid JSON-RPC frame corrupts the agent's parser — so we route every
//! `tracing` event through stderr by default.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

// All modules live in `src/lib.rs` so the binary and the integration
// test suite (under `tests/`) compile against one copy of each. We
// import only the surfaces the binary entrypoint actually needs.
use axon_emcp::{knowledge, server};

use std::process::ExitCode;

use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> ExitCode {
    // Stderr-only tracing. The MCP wire owns stdout — any other writer
    // there is a protocol violation. The `RUST_LOG` env var follows the
    // rest of the workspace (e.g. `RUST_LOG=axon_emcp=debug`).
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with_writer(std::io::stderr)
        .with_target(false)
        .compact()
        .init();

    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        "axon-emcp starting — ℰMCP OFICIAL"
    );

    // Load the knowledge base once at startup. The base lives under
    // `src/knowledge/` (relative to the repo root); we resolve it from
    // the binary's compile-time path so an installed binary still finds
    // its corpus — see `knowledge::Catalog::load_default()` for the
    // resolution order.
    let catalog = match knowledge::Catalog::load_default() {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "failed to load knowledge base — refusing to start");
            return ExitCode::from(2);
        }
    };
    tracing::info!(
        primitives = catalog.primitive_count(),
        "knowledge base loaded"
    );

    // Hand off to the stdio MCP loop. Returns when the agent disconnects
    // (clean EOF on stdin) or on a fatal transport error.
    match server::run_stdio(catalog).await {
        Ok(()) => {
            tracing::info!("axon-emcp shutting down cleanly");
            ExitCode::SUCCESS
        }
        Err(e) => {
            tracing::error!(error = %e, "axon-emcp transport error");
            ExitCode::FAILURE
        }
    }
}
