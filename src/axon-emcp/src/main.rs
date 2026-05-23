//! `axon-emcp` — the official ℰMCP (Epistemic Model Context Protocol)
//! server for AXON.
//!
//! Speaks MCP over stdio + JSON-RPC 2.0. Once an agent (Claude Code,
//! Codex, Cursor, Continue, Cline, …) launches this binary as an MCP
//! subprocess, it can:
//!
//! - Call **tools** (`axon.check`, `axon.parse`, `axon.primitives`,
//!   `axon.primitive_doc`, `axon.compose`) to validate code, look up
//!   grammar, request idiomatic scaffolds.
//! - Read **resources** (`axon://primitives/{name}`,
//!   `axon://grammar/top_level`, …) — the canonical reference
//!   material the agent quotes in replies.
//! - Invoke **prompts** (`flow_design`, `shield_design`,
//!   `session_design`) — host-surfaced design recipes.
//!
//! The wire is **stdio-only**: STDOUT carries JSON-RPC frames (one per
//! line), STDERR carries logs. Anything written to stdout that is not a
//! valid JSON-RPC frame corrupts the agent's parser — so we route every
//! `tracing` event through stderr by default.
//!
//! # Subcommands (§Fase 6.a)
//!
//! In addition to the default MCP-server mode, this binary supports a
//! handful of contributor-facing subcommands that run, exit, and do
//! NOT enter the MCP loop:
//!
//! - `axon-emcp scaffold-primitive <name>` — stamp a markdown doc
//!   skeleton for one primitive (frontmatter pre-populated from
//!   [`axon_frontend::PRIMITIVE_REGISTRY`]).
//! - `axon-emcp --help` — print usage.
//! - `axon-emcp --version` — print the crate version.
//!
//! No arguments → MCP server mode (the default).

#![forbid(unsafe_code)]
#![deny(missing_docs)]

// All modules live in `src/lib.rs` so the binary and the integration
// test suite (under `tests/`) compile against one copy of each. We
// import only the surfaces the binary entrypoint actually needs.
use axon_emcp::{knowledge, scaffold, server};

use std::path::PathBuf;
use std::process::ExitCode;

use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> ExitCode {
    // §Fase 6.a — subcommand dispatch BEFORE tracing setup. Scaffold
    // and help-style flags are interactive CLI invocations: their
    // stderr is read by humans, and the MCP-server's tracing
    // configuration (compact formatter, info level) is wrong for
    // that audience. The MCP-server lane keeps its own setup below.
    let args: Vec<String> = std::env::args().collect();
    if let Some(sub) = args.get(1) {
        match sub.as_str() {
            "scaffold-primitive" => return run_scaffold_primitive(&args[2..]),
            "--help" | "-h" => return run_help(),
            "--version" | "-V" => return run_version(),
            // Any other first-arg token falls through to MCP server
            // mode — the agent might pass flags we don't yet
            // recognise (e.g. `--protocol-version`), and tolerating
            // them keeps the server forward-compatible.
            _ => {}
        }
    }

    // ── MCP server mode (the default) ─────────────────────────────────

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

/// `scaffold-primitive <name>` — stamp a markdown doc skeleton with
/// frontmatter pre-populated from the canonical registry.
///
/// Exit codes:
/// - `0` success — the file was written.
/// - `1` runtime failure (file already exists, knowledge dir missing,
///   write error). Stderr carries the diagnostic.
/// - `2` usage error (no `<name>` argument). Stderr carries usage hint.
fn run_scaffold_primitive(args: &[String]) -> ExitCode {
    if args.is_empty() {
        eprintln!("usage: axon-emcp scaffold-primitive <name>");
        eprintln!();
        eprintln!("Stamps src/knowledge/primitives/<name>.md with the frontmatter pre-populated");
        eprintln!("from axon_frontend::PRIMITIVE_REGISTRY. The name must already exist in the");
        eprintln!("registry (add it there first if it's a new primitive).");
        return ExitCode::from(2);
    }
    let name = &args[0];

    let knowledge_dir = match resolve_knowledge_dir() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(1);
        }
    };

    match scaffold::run(name, &knowledge_dir) {
        Ok(msg) => {
            // Subcommand output goes to stderr per the MCP discipline
            // (stdout is reserved for JSON-RPC; if a contributor pipes
            // `axon-emcp scaffold-primitive foo | something`, they
            // should not get a CLI message mixed in).
            eprintln!("{msg}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(1)
        }
    }
}

/// Resolve the corpus root for contributor-facing subcommands.
/// Resolution order:
///
/// 1. `AXON_EMCP_KNOWLEDGE_DIR` env var (operator override).
/// 2. `<cwd>/src/knowledge` (running from the repo root).
/// 3. `<cwd>/../knowledge` (running from inside `src/axon-emcp/`).
///
/// Fails with a structured error message if none resolve — the
/// scaffold CLI is not useful from an installed binary outside the
/// repo, by design.
fn resolve_knowledge_dir() -> Result<PathBuf, String> {
    if let Ok(s) = std::env::var("AXON_EMCP_KNOWLEDGE_DIR") {
        let p = PathBuf::from(&s);
        if p.is_dir() {
            return Ok(p);
        }
        return Err(format!(
            "AXON_EMCP_KNOWLEDGE_DIR points to non-directory: {s}"
        ));
    }
    let cwd = std::env::current_dir()
        .map_err(|e| format!("could not read cwd: {e}"))?;
    for candidate in [cwd.join("src").join("knowledge"), cwd.join("..").join("knowledge")] {
        if candidate.is_dir() {
            return Ok(candidate);
        }
    }
    Err(format!(
        "could not find knowledge directory — run from the repo root, \
         or set AXON_EMCP_KNOWLEDGE_DIR to point to src/knowledge/. \
         cwd = {}",
        cwd.display()
    ))
}

/// `--help` / `-h` — print usage to stderr and exit 0.
fn run_help() -> ExitCode {
    eprintln!(
        "{name} — the official ℰMCP server for AXON, plus contributor subcommands.\n\
         \n\
         USAGE:\n  \
           {name} [SUBCOMMAND]\n\
         \n\
         SUBCOMMANDS:\n  \
           (none)                 Start the MCP server (default — speaks JSON-RPC 2.0 on stdio)\n  \
           scaffold-primitive <name>\n                                Stamp a markdown doc skeleton for one primitive\n  \
           --help, -h             Print this help\n  \
           --version, -V          Print the crate version\n\
         \n\
         ENV:\n  \
           AXON_EMCP_KNOWLEDGE_DIR  Override the corpus root (default: in-tree dev path, then embedded)\n  \
           RUST_LOG                 Tracing filter (e.g. axon_emcp=debug)\n",
        name = env!("CARGO_PKG_NAME")
    );
    ExitCode::SUCCESS
}

/// `--version` / `-V` — print `<name> <version>` to stderr and exit 0.
fn run_version() -> ExitCode {
    eprintln!("{} {}", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION"));
    ExitCode::SUCCESS
}
