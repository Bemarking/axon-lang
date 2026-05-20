//! AXON CLI nativo — Fase D: Plataforma Runtime.
//!
//! All 14 commands handled natively. Python is no longer required.
//!   Active:  version, check, compile, run, trace, repl, inspect, ld, serve, deploy, diff, replay, stats, graph

use axon::audit_cli;
use axon::axon_server;
use axon::checker;
use axon::cost_estimator;
use axon::graph_export;
use axon::deployer;
use axon::compiler;
use axon::inspect;
use axon::lambda_data;
use axon::plan_diff;
use axon::repl;
use axon::replay;
use axon::runner;
use axon::runner::AXON_VERSION;
use axon::trace_stats;
use axon::tracer;

use clap::{Parser, Subcommand};
use std::process;

// ── Estructura CLI (espejo del CLI Python) ────────────────────────────────────

#[derive(Parser)]
#[command(
    name = "axon",
    about = "AXON — A programming language for AI cognition.",
    disable_version_flag = true,
    arg_required_else_help = true,
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Lex, parse, and type-check an .axon file.
    Check {
        file: String,
        #[arg(long)]
        no_color: bool,
        /// §λ-L-E Fase 13 D4 — promote warnings to errors (CI gate).
        /// Recommended for adopters preparing for v2.0 string-topic
        /// removal (see docs/migration_fase_13.md).
        #[arg(long)]
        strict: bool,
    },
    /// Compile an .axon file to IR JSON.
    Compile {
        file: String,
        #[arg(short, long, default_value = "anthropic")]
        backend: String,
        #[arg(short, long)]
        output: Option<String>,
        #[arg(long)]
        stdout: bool,
    },
    /// Compile and execute an .axon file.
    Run {
        file: String,
        #[arg(short, long, default_value = "anthropic")]
        backend: String,
        #[arg(long)]
        trace: bool,
        #[arg(long, default_value = "stub")]
        tool_mode: String,
        /// Stream LLM output in real-time (requires tool_mode=real).
        #[arg(long)]
        stream: bool,
        /// Output format: text (default) or json.
        #[arg(long, default_value = "text")]
        output: String,
        /// Export execution plan as JSON without executing.
        #[arg(long)]
        export_plan: bool,
    },
    /// Pretty-print a saved execution trace.
    Trace {
        file: String,
        #[arg(long)]
        no_color: bool,
    },
    /// Show axon-lang version.
    Version,
    /// Start an interactive AXON REPL session.
    Repl,
    /// Introspect the AXON standard library.
    Inspect {
        #[arg(default_value = "anchors")]
        target: String,
        #[arg(long)]
        all: bool,
    },
    /// Start the AxonServer (reactive daemon platform).
    Serve {
        #[arg(long, default_value = "127.0.0.1")]
        host: String,
        #[arg(long, default_value_t = 8420)]
        port: u16,
        #[arg(long, default_value = "memory")]
        channel: String,
        #[arg(long, default_value = "")]
        auth_token: String,
        #[arg(long, default_value = "info")]
        log_level: String,
        /// Log output format: "json" (default, structured) or "pretty" (human-readable).
        #[arg(long, default_value = "json")]
        log_format: String,
        /// Optional directory for daily-rotated log files.
        #[arg(long)]
        log_file: Option<String>,
        /// PostgreSQL connection URL (also reads DATABASE_URL env var).
        #[arg(long)]
        database_url: Option<String>,
        /// §Fase 31.f (D6 + D9) — Type-Driven Wire Inference activation.
        ///
        /// When set, `POST /v1/execute` promotes to SSE for any flow
        /// the type-checker inferred as stream-producing (D1) regardless
        /// of the client's `Accept:` header. Adopters who explicitly
        /// declared `transport: json` retain D3 opt-out semantics.
        ///
        /// Also readable from the env var
        /// `AXON_STRICT_TYPE_DRIVEN_TRANSPORT` (truthy values: "1",
        /// "true", "yes", "on" — case-insensitive). CLI flag wins
        /// when both are set.
        ///
        /// D6 default: false in v1.22.x, flips to true in v2.0.0.
        #[arg(long)]
        strict_type_driven_transport: bool,
        /// §Fase 36.g (D7) — Server-wide default execution backend.
        ///
        /// Rung 3 of the Backend Resolution Contract: an `axonendpoint`
        /// that declares no `backend:` of its own inherits this server
        /// default. Valid values are the closed catalog `anthropic |
        /// auto | gemini | glm | kimi | ollama | openai | openrouter |
        /// stub` — an unknown name aborts startup with exit code 1.
        ///
        /// Also readable from the env var `AXON_DEFAULT_BACKEND`; the
        /// CLI flag wins when both are set. Unset ≡ no server default
        /// (resolution falls through to the environment-available
        /// providers).
        #[arg(long)]
        backend: Option<String>,
        /// §Fase 38.j (D3 + D7 + D8) — Directory containing declared
        /// store-schema manifests (`*.axon-schema.json` files at the
        /// project root and/or under a `schemas/` subdirectory).
        ///
        /// When set, `POST /v1/deploy` loads and merges every manifest
        /// under the directory before running the deploy-time store
        /// verification pass. Declared columns (Fase 38 schema forms
        /// a/b/c) become the authoritative shape — any drift between
        /// the manifest and the LIVE Postgres introspection raises
        /// axon-T807 (DeclaredVsLiveDrift) and fails the deploy.
        ///
        /// Also readable from the env var `AXON_SCHEMAS_DIR`; the CLI
        /// flag wins when both are set. Unset ≡ no manifest loading —
        /// the v1.37.0 verify_postgres_schemas behavior is preserved
        /// verbatim (D5 absolute backwards-compat: an adopter who has
        /// not adopted Fase 38's compile-time schema observes ZERO
        /// behavior change at deploy).
        #[arg(long)]
        schemas_dir: Option<String>,
    },
    /// Lambda Data (ΛD) epistemic codec: encode, decode, inspect.
    Ld {
        /// Action: encode, decode, inspect.
        action: String,
        /// Source file (.axon for encode, .ld for decode/inspect).
        file: String,
    },
    /// Compare two exported execution plans.
    Diff {
        /// First plan JSON file (baseline).
        file_a: String,
        /// Second plan JSON file (changed).
        file_b: String,
        /// Output as JSON instead of human-readable.
        #[arg(long)]
        json: bool,
    },
    /// Replay an execution trace or compare two traces for regression.
    Replay {
        /// Trace JSON file to replay.
        file: String,
        /// Optional second trace file for regression comparison.
        #[arg(long)]
        compare: Option<String>,
        /// Output as JSON instead of human-readable.
        #[arg(long)]
        json: bool,
    },
    /// Compute aggregate statistics across execution traces.
    Stats {
        /// One or more trace JSON files.
        #[arg(required = true)]
        files: Vec<String>,
        /// Output as JSON instead of human-readable.
        #[arg(long)]
        json: bool,
        /// Output format: text (default), json, prometheus, csv.
        #[arg(long, default_value = "text")]
        format: String,
    },
    /// Export dependency graph as DOT (Graphviz) or Mermaid diagram.
    Graph {
        /// AXON source file to analyze.
        file: String,
        /// Output format: dot (default) or mermaid.
        #[arg(long, default_value = "dot")]
        format: String,
    },
    /// Estimate execution cost (tokens/USD) before running a flow.
    Estimate {
        /// AXON source file to analyze.
        file: String,
        /// Output format: text (default) or json.
        #[arg(long, default_value = "text")]
        format: String,
        /// Pricing model: sonnet (default), opus, or haiku.
        #[arg(long, default_value = "sonnet")]
        model: String,
    },
    /// Deploy .axon file to a running AxonServer.
    Deploy {
        file: String,
        #[arg(long, default_value = "http://localhost:8420")]
        server: String,
        #[arg(short, long, default_value = "anthropic")]
        backend: String,
        #[arg(long, default_value = "")]
        auth_token: String,
    },
    /// Generate a JSON compliance dossier from an .axon file (§ESK Fase 6.6).
    Dossier {
        file: String,
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Generate a JSON Software Bill of Materials from an .axon file.
    Sbom {
        file: String,
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Gap analysis against SOC 2 / ISO 27001 / FIPS 140-3 / CC EAL 4+.
    Audit {
        file: String,
        #[arg(long, default_value = "all")]
        framework: String,
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Assemble a deterministic audit evidence ZIP for external auditors.
    #[command(name = "evidence-package")]
    EvidencePackage {
        file: String,
        #[arg(short, long)]
        output: Option<String>,
        /// Free-form auditor intake note embedded in README.md.
        #[arg(long, default_value = "")]
        note: String,
    },
    /// §Fase 38.h (D10) — `axonstore` schema introspection / manifest export.
    Store {
        #[command(subcommand)]
        action: StoreCommands,
    },
}

#[derive(Subcommand)]
enum StoreCommands {
    /// Introspect one (or more) `postgresql` axonstore's live schema
    /// and emit a canonical `.axon-schema.json` manifest. The manifest
    /// is the §Fase 38.c durable contract between an adopter's
    /// `schema: "qualified.name"` (form b) / `schema: env:VAR` (form
    /// c) declaration and the columns the type-checker proves against
    /// (38.d / 38.e). Unmappable Postgres types (`enum`, `domain`,
    /// array, `citext`, PostGIS, custom composites) are HONESTLY
    /// omitted with a `# omitted: …` comment line — NEVER silently
    /// lossily mapped (D10 / D6).
    Introspect {
        /// Store names to introspect. At least one required.
        #[arg(required = true)]
        store_names: Vec<String>,
        /// Postgres connection string OR `env:VAR`. (The runtime's
        /// `resolve_dsn` accepts both shapes.)
        #[arg(long)]
        connection: String,
        /// Optional path to write the manifest. When omitted, the
        /// manifest is written to stdout.
        #[arg(long)]
        output: Option<String>,
        /// Optional path to an existing manifest. When set, the CLI
        /// emits a structural diff instead of the new manifest —
        /// added/removed columns + type changes + constraint flips.
        #[arg(long)]
        diff: Option<String>,
        /// §Fase 38.h forward-compat — `--json` is the default + only
        /// supported output format today; `--yaml` (a future
        /// `yaml-manifest` Cargo feature) is documented in §38.c.2.
        /// Accepting the flag now so adopters can pin it before YAML
        /// support lands.
        #[arg(long, default_value = "json")]
        format: String,
    },
}

// ── Entry point ───────────────────────────────────────────────────────────────

fn main() {
    let cli = Cli::parse();

    let exit_code = match cli.command {
        Commands::Version => {
            println!("axon-lang {AXON_VERSION}");
            0
        }
        Commands::Check { file, no_color, strict } => checker::run_check(&file, no_color, strict),
        Commands::Compile {
            file,
            backend,
            output,
            stdout,
        } => compiler::run_compile(&file, &backend, output.as_deref(), stdout),
        Commands::Run {
            file,
            backend,
            trace,
            tool_mode,
            stream,
            output,
            export_plan,
        } => runner::run_run(&file, &backend, trace, &tool_mode, stream, &output, export_plan),
        Commands::Trace { file, no_color } => tracer::run_trace(&file, no_color),
        Commands::Repl => repl::run_repl(),
        Commands::Inspect { target, all } => inspect::run_inspect(&target, all),
        Commands::Ld { action, file } => lambda_data::run_ld(&action, &file),
        Commands::Serve {
            host,
            port,
            channel,
            auth_token,
            log_level,
            log_format,
            log_file,
            database_url,
            strict_type_driven_transport,
            backend,
            schemas_dir,
        } => axon_server::run_serve(axon_server::ServerConfig {
            host,
            port,
            channel,
            auth_token,
            log_level,
            log_format,
            log_file,
            database_url: database_url.or_else(|| std::env::var("DATABASE_URL").ok()),
            config_path: None,
            // §Fase 31.f (D6 + D7) — Resolution order for the strict
            // flag (highest precedence first):
            //   1. CLI flag `--strict-type-driven-transport` (when
            //      present, always wins — explicit at run-time).
            //   2. Env var `AXON_STRICT_TYPE_DRIVEN_TRANSPORT` (12-
            //      factor app pattern; common in k8s/docker deploys).
            //   3. D6 default `false` (v1.22.x — backwards-compat).
            // D9 ratified — the default flips to `true` in v2.0.0.
            //
            // D7 cross-stack consistency — Python `axon serve`
            // reads the same env var name verbatim. Truthy values
            // are accepted case-insensitively: "1", "true", "yes",
            // "on". Any other value (including unset) is false.
            strict_type_driven_transport: strict_type_driven_transport
                || axon::axon_server::parse_truthy_env(
                    "AXON_STRICT_TYPE_DRIVEN_TRANSPORT",
                ),
            // §Fase 36.g (D7) — server default backend (rung 3 of the
            // Backend Resolution Contract). Resolution order, highest
            // precedence first:
            //   1. CLI flag `--backend <name>` (explicit at run-time).
            //   2. Env var `AXON_DEFAULT_BACKEND` (12-factor; common
            //      in k8s/docker deploys).
            //   3. `None` — no server default; the ladder falls
            //      through to the environment-available `auto` rungs.
            // An empty string from either surface collapses to `None`.
            // The value is validated against the closed catalog at
            // `run_serve` startup — an unknown name fails fast.
            default_backend: backend
                .or_else(|| std::env::var("AXON_DEFAULT_BACKEND").ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty()),
            // §Fase 38.j (D3 + D7 + D8) — Resolution order for the
            // declared store-schema manifest directory (highest
            // precedence first):
            //   1. CLI flag `--schemas-dir <path>` (explicit at run-
            //      time; common in dev + `docker run` overrides).
            //   2. Env var `AXON_SCHEMAS_DIR` (12-factor app pattern;
            //      common in k8s/docker `Deployment` manifests).
            //   3. `None` — no manifest loading; v1.37.0 deploy-time
            //      verify is preserved verbatim (D5 absolute).
            // An empty string from either surface collapses to `None`.
            // The directory's existence is NOT verified at startup —
            // a missing dir resolves to "no manifest files" the same
            // way an empty dir does (`load_and_merge_manifests` is
            // total). Failures, if any, surface at deploy time as
            // structured T805/T807/duplicate-store errors.
            schemas_dir: schemas_dir
                .or_else(|| std::env::var("AXON_SCHEMAS_DIR").ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty()),
        }),
        Commands::Diff {
            file_a,
            file_b,
            json,
        } => plan_diff::run_diff(&file_a, &file_b, json),
        Commands::Replay {
            file,
            compare,
            json,
        } => replay::run_replay(&file, compare.as_deref(), json),
        Commands::Stats { files, json, format } => {
            let effective_format = if json { "json".to_string() } else { format };
            trace_stats::run_stats(&files, &effective_format)
        }
        Commands::Graph { file, format } => graph_export::run_graph(&file, &format),
        Commands::Estimate { file, format, model } => cost_estimator::run_estimate(&file, &format, &model),
        Commands::Deploy {
            file,
            server,
            backend,
            auth_token,
        } => deployer::run_deploy(&deployer::DeployConfig {
            file,
            server,
            backend,
            auth_token,
        }),
        Commands::Dossier { file, output } => audit_cli::run_dossier(&file, output.as_deref()),
        Commands::Sbom { file, output } => audit_cli::run_sbom(&file, output.as_deref()),
        Commands::Audit { file, framework, output } => {
            audit_cli::run_audit(&file, &framework, output.as_deref())
        }
        Commands::EvidencePackage { file, output, note } => {
            audit_cli::run_evidence_package(&file, output.as_deref(), &note)
        }
        Commands::Store { action } => run_store_command(action),
    };

    process::exit(exit_code);
}

/// §Fase 38.h (D10) — `axon store …` subcommand dispatcher. Spins a
/// one-shot Tokio runtime (the CLI runs in a sync `fn main`; the
/// introspection uses `sqlx::PgConnection` which is async).
fn run_store_command(action: StoreCommands) -> i32 {
    let runtime = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => {
            eprintln!("axon-lang: failed to start async runtime: {e}");
            return 2;
        }
    };
    match action {
        StoreCommands::Introspect {
            store_names,
            connection,
            output,
            diff,
            format,
        } => {
            if format != "json" {
                eprintln!(
                    "axon-lang: `--format {format}` is not yet supported. \
                     v1.38.0 ships canonical JSON only; YAML (`--format \
                     yaml`) is committed for a 38.c.2 follow-on behind \
                     the `yaml-manifest` Cargo feature."
                );
                return 2;
            }
            runtime.block_on(async move {
                run_store_introspect(&store_names, &connection, output.as_deref(), diff.as_deref())
                    .await
            })
        }
    }
}

/// The actual introspection + emission. Returns the process exit code.
async fn run_store_introspect(
    store_names: &[String],
    connection: &str,
    output: Option<&str>,
    diff_path: Option<&str>,
) -> i32 {
    use axon::store::introspect_cli::{
        introspect_stores, render_introspection_output,
    };
    use axon::store_introspect::{format_manifest_diff, manifest_diff};
    use axon::store_schema_manifest::Manifest;

    let (manifest, omissions) = match introspect_stores(connection, store_names).await {
        Ok(pair) => pair,
        Err(e) => {
            eprintln!("axon-lang: introspection failed — {e}");
            return 1;
        }
    };

    // — Diff mode: compare against an existing manifest. —
    if let Some(existing_path) = diff_path {
        let existing_src = match std::fs::read_to_string(existing_path) {
            Ok(s) => s,
            Err(e) => {
                eprintln!(
                    "axon-lang: failed to read existing manifest at \
                     `{existing_path}`: {e}"
                );
                return 1;
            }
        };
        let existing = match Manifest::parse_json(&existing_src) {
            Ok(m) => m,
            Err(e) => {
                eprintln!(
                    "axon-lang: failed to parse existing manifest at \
                     `{existing_path}` — {e}"
                );
                return 1;
            }
        };
        let diff = manifest_diff(&existing, &manifest);
        if diff.is_empty() {
            println!("manifest is up to date — no drift between live database and `{existing_path}`.");
            return 0;
        }
        print!("{}", format_manifest_diff(&diff));
        for omission in &omissions {
            println!("{}", omission.as_comment_line());
        }
        return 0;
    }

    // — Default mode: emit the manifest. —
    let rendered = render_introspection_output(&manifest, &omissions);
    match output {
        Some(path) => match std::fs::write(path, &rendered) {
            Ok(()) => 0,
            Err(e) => {
                eprintln!("axon-lang: failed to write manifest to `{path}`: {e}");
                1
            }
        },
        None => {
            println!("{rendered}");
            0
        }
    }
}
