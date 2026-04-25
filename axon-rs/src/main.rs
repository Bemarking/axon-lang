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
use axon::trace_stats;
use axon::tracer;

use clap::{Parser, Subcommand};
use std::process;

const AXON_VERSION: &str = "1.4.0";

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
    };

    process::exit(exit_code);
}
