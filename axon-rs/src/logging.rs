//! Logging — production-grade structured logging for AxonServer.
//!
//! Built on `tracing` + `tracing-subscriber` with:
//!   - JSON or human-readable (pretty) output to stdout
//!   - Optional daily-rotated file logging via `tracing-appender`
//!   - Configurable log level via `AXON_LOG` env var or `--log-level` CLI arg
//!   - Request correlation via tracing spans (request_id propagation)
//!
//! Designed for production SaaS workloads — structured JSON output is the default
//! for machine consumption (ELK, Datadog, CloudWatch, etc.).
//!
//! Usage:
//!   let _guard = axon::logging::init("info", "json", None);
//!   // guard must be held for program lifetime to ensure non-blocking writes flush

use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::fmt;
use tracing_subscriber::prelude::*;
use tracing_subscriber::EnvFilter;

/// Logging format selection.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum LogFormat {
    /// JSON structured output — default for production.
    Json,
    /// Human-readable pretty output — for local development.
    Pretty,
}

impl LogFormat {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "pretty" | "text" | "human" => LogFormat::Pretty,
            _ => LogFormat::Json,
        }
    }
}

/// Initialize the global tracing subscriber.
///
/// Returns a `LogGuard` that must be held for the program's lifetime.
/// Dropping the guard flushes and closes the non-blocking writer(s).
///
/// # Parameters
/// - `log_level`: default filter level (e.g., "info", "debug", "trace").
///   Overridden by `AXON_LOG` env var if set.
/// - `format`: "json" (default) or "pretty"
/// - `log_file_dir`: optional directory for daily-rotated log files.
///   If `Some`, a file writer layer is added alongside stdout.
pub fn init(log_level: &str, format: &str, log_file_dir: Option<&str>) -> LogGuard {
    let format = LogFormat::from_str(format);

    // Build env filter: AXON_LOG env takes precedence, then CLI arg, then default "info"
    let filter = EnvFilter::try_from_env("AXON_LOG")
        .unwrap_or_else(|_| {
            EnvFilter::try_new(log_level)
                .unwrap_or_else(|_| EnvFilter::new("info"))
        });

    // Stdout non-blocking writer
    let (stdout_writer, stdout_guard) = tracing_appender::non_blocking(std::io::stdout());

    // Build per-format to avoid type mismatches between json/pretty layer generics
    let file_guard = match format {
        LogFormat::Json => {
            let stdout_layer = fmt::layer()
                .json()
                .with_writer(stdout_writer)
                .with_target(true)
                .with_thread_ids(false)
                .with_file(true)
                .with_line_number(true)
                .with_span_list(true);

            match log_file_dir {
                Some(dir) => {
                    let file_appender = tracing_appender::rolling::daily(dir, "axon-server.log");
                    let (file_writer, fguard) = tracing_appender::non_blocking(file_appender);
                    let file_layer = fmt::layer()
                        .json()
                        .with_writer(file_writer)
                        .with_target(true)
                        .with_thread_ids(true)
                        .with_thread_names(true)
                        .with_file(true)
                        .with_line_number(true)
                        .with_span_list(true);

                    let subscriber = tracing_subscriber::registry()
                        .with(filter)
                        .with(stdout_layer)
                        .with(file_layer);
                    tracing::subscriber::set_global_default(subscriber)
                        .expect("Failed to set global tracing subscriber");
                    Some(fguard)
                }
                None => {
                    let subscriber = tracing_subscriber::registry()
                        .with(filter)
                        .with(stdout_layer);
                    tracing::subscriber::set_global_default(subscriber)
                        .expect("Failed to set global tracing subscriber");
                    None
                }
            }
        }
        LogFormat::Pretty => {
            let stdout_layer = fmt::layer()
                .pretty()
                .with_writer(stdout_writer)
                .with_target(true)
                .with_thread_ids(false)
                .with_file(true)
                .with_line_number(true);

            match log_file_dir {
                Some(dir) => {
                    let file_appender = tracing_appender::rolling::daily(dir, "axon-server.log");
                    let (file_writer, fguard) = tracing_appender::non_blocking(file_appender);
                    let file_layer = fmt::layer()
                        .json()
                        .with_writer(file_writer)
                        .with_target(true)
                        .with_thread_ids(true)
                        .with_thread_names(true)
                        .with_file(true)
                        .with_line_number(true)
                        .with_span_list(true);

                    let subscriber = tracing_subscriber::registry()
                        .with(filter)
                        .with(stdout_layer)
                        .with(file_layer);
                    tracing::subscriber::set_global_default(subscriber)
                        .expect("Failed to set global tracing subscriber");
                    Some(fguard)
                }
                None => {
                    let subscriber = tracing_subscriber::registry()
                        .with(filter)
                        .with(stdout_layer);
                    tracing::subscriber::set_global_default(subscriber)
                        .expect("Failed to set global tracing subscriber");
                    None
                }
            }
        }
    };

    LogGuard {
        _stdout_guard: stdout_guard,
        _file_guard: file_guard,
    }
}

/// Guard that must be held for the program's lifetime.
/// Dropping it flushes and closes non-blocking writers.
pub struct LogGuard {
    _stdout_guard: WorkerGuard,
    _file_guard: Option<WorkerGuard>,
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_log_format_from_str() {
        assert_eq!(LogFormat::from_str("json"), LogFormat::Json);
        assert_eq!(LogFormat::from_str("JSON"), LogFormat::Json);
        assert_eq!(LogFormat::from_str("pretty"), LogFormat::Pretty);
        assert_eq!(LogFormat::from_str("text"), LogFormat::Pretty);
        assert_eq!(LogFormat::from_str("human"), LogFormat::Pretty);
        assert_eq!(LogFormat::from_str("unknown"), LogFormat::Json);
    }

    #[test]
    fn test_log_format_default_is_json() {
        assert_eq!(LogFormat::from_str(""), LogFormat::Json);
    }
}
