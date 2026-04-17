//! HTTP tool provider — executes tool calls as REST requests via reqwest.
//!
//! Tools declared with `provider: http` in .axon files dispatch their
//! argument as the request body to the URL specified in `runtime`.
//!
//! Request format:
//!   POST {runtime_url}
//!   Content-Type: application/json
//!   X-Axon-Tool: {tool_name}
//!
//!   Body: the tool argument (string, sent as JSON-wrapped if not already JSON)
//!
//! Response handling:
//!   - 2xx: response body becomes tool output (success)
//!   - 4xx/5xx: error message with status code (failure)
//!   - Connection error: descriptive error (failure)
//!
//! Timeout: parsed from ToolEntry.timeout field (e.g., "10s", "500ms").
//! Default timeout: 30 seconds.

use std::time::Duration;

use crate::tool_executor::ToolResult;
use crate::tool_registry::ToolEntry;

// ── Timeout parsing ───────────────────────────────────────────────────────

/// Parse a timeout string like "10s", "500ms", "2m" into Duration.
/// Returns None for empty or unparseable values.
fn parse_timeout(s: &str) -> Option<Duration> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }

    if let Some(secs) = s.strip_suffix("ms") {
        secs.trim().parse::<u64>().ok().map(Duration::from_millis)
    } else if let Some(secs) = s.strip_suffix('s') {
        secs.trim().parse::<u64>().ok().map(Duration::from_secs)
    } else if let Some(mins) = s.strip_suffix('m') {
        mins.trim()
            .parse::<u64>()
            .ok()
            .map(|m| Duration::from_secs(m * 60))
    } else {
        // Try as raw seconds
        s.parse::<u64>().ok().map(Duration::from_secs)
    }
}

/// Public accessor for timeout parsing (used by emcp module).
pub fn parse_timeout_pub(s: &str) -> Option<Duration> {
    parse_timeout(s)
}

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

// ── HTTP dispatch ─────────────────────────────────────────────────────────

/// Execute an HTTP tool call.
///
/// - `entry`: the tool's registry entry (must have provider == "http")
/// - `argument`: the argument string from the use_tool step
///
/// Returns a ToolResult with the HTTP response body on success,
/// or an error description on failure.
pub fn dispatch_http(entry: &ToolEntry, argument: &str) -> ToolResult {
    let url = entry.runtime.trim();

    if url.is_empty() {
        return ToolResult {
            success: false,
            output: format!(
                "HTTP tool '{}': no endpoint URL. Set runtime: \"https://...\" in tool definition.",
                entry.name
            ),
            tool_name: entry.name.clone(),
        };
    }

    // Validate URL scheme
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return ToolResult {
            success: false,
            output: format!(
                "HTTP tool '{}': invalid URL '{}'. Must start with http:// or https://.",
                entry.name, url
            ),
            tool_name: entry.name.clone(),
        };
    }

    let timeout = parse_timeout(&entry.timeout).unwrap_or(DEFAULT_TIMEOUT);

    // Build the request body — wrap as JSON string if not already JSON
    let body = if argument.trim_start().starts_with('{') || argument.trim_start().starts_with('[') {
        argument.to_string()
    } else {
        serde_json::json!({ "input": argument }).to_string()
    };

    // Execute the HTTP request
    match execute_request(url, &entry.name, &body, timeout) {
        Ok(response) => response,
        Err(e) => ToolResult {
            success: false,
            output: format!("HTTP tool '{}': {}", entry.name, e),
            tool_name: entry.name.clone(),
        },
    }
}

/// Perform the actual HTTP POST request.
fn execute_request(
    url: &str,
    tool_name: &str,
    body: &str,
    timeout: Duration,
) -> Result<ToolResult, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(timeout)
        .build()
        .map_err(|e| format!("failed to create HTTP client: {e}"))?;

    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .header("X-Axon-Tool", tool_name)
        .body(body.to_string())
        .send()
        .map_err(|e| {
            if e.is_timeout() {
                format!("request timed out after {}s", timeout.as_secs())
            } else if e.is_connect() {
                format!("connection failed to {url}")
            } else {
                format!("request failed: {e}")
            }
        })?;

    let status = response.status();
    let response_body = response
        .text()
        .map_err(|e| format!("failed to read response body: {e}"))?;

    if status.is_success() {
        Ok(ToolResult {
            success: true,
            output: response_body,
            tool_name: tool_name.to_string(),
        })
    } else {
        Ok(ToolResult {
            success: false,
            output: format!(
                "HTTP {}: {}",
                status.as_u16(),
                if response_body.len() > 200 {
                    format!("{}...", &response_body[..200])
                } else {
                    response_body
                }
            ),
            tool_name: tool_name.to_string(),
        })
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tool_registry::{ToolEntry, ToolSource};

    fn make_http_entry(name: &str, url: &str, timeout: &str) -> ToolEntry {
        ToolEntry {
            name: name.to_string(),
            provider: "http".to_string(),
            timeout: timeout.to_string(),
            runtime: url.to_string(),
            sandbox: None,
            max_results: None,
            output_schema: "JSON".to_string(),
            effect_row: vec!["network".to_string()],
            source: ToolSource::Program,
        }
    }

    // ── Timeout parsing ───────────────────────────────────────────

    #[test]
    fn parse_timeout_seconds() {
        assert_eq!(parse_timeout("10s"), Some(Duration::from_secs(10)));
        assert_eq!(parse_timeout("30s"), Some(Duration::from_secs(30)));
    }

    #[test]
    fn parse_timeout_milliseconds() {
        assert_eq!(parse_timeout("500ms"), Some(Duration::from_millis(500)));
        assert_eq!(parse_timeout("100ms"), Some(Duration::from_millis(100)));
    }

    #[test]
    fn parse_timeout_minutes() {
        assert_eq!(parse_timeout("2m"), Some(Duration::from_secs(120)));
    }

    #[test]
    fn parse_timeout_raw_number() {
        assert_eq!(parse_timeout("15"), Some(Duration::from_secs(15)));
    }

    #[test]
    fn parse_timeout_empty() {
        assert_eq!(parse_timeout(""), None);
        assert_eq!(parse_timeout("  "), None);
    }

    #[test]
    fn parse_timeout_invalid() {
        assert_eq!(parse_timeout("abc"), None);
        assert_eq!(parse_timeout("10x"), None);
    }

    // ── URL validation ────────────────────────────────────────────

    #[test]
    fn dispatch_empty_url_fails() {
        let entry = make_http_entry("DataAPI", "", "10s");
        let result = dispatch_http(&entry, "test query");
        assert!(!result.success);
        assert!(result.output.contains("no endpoint URL"));
    }

    #[test]
    fn dispatch_invalid_url_scheme_fails() {
        let entry = make_http_entry("DataAPI", "ftp://example.com", "10s");
        let result = dispatch_http(&entry, "test query");
        assert!(!result.success);
        assert!(result.output.contains("invalid URL"));
        assert!(result.output.contains("http://"));
    }

    // ── Connection errors (no server) ─────────────────────────────

    #[test]
    fn dispatch_connection_refused() {
        // Port 1 is almost certainly not listening
        let entry = make_http_entry("TestTool", "http://127.0.0.1:1/api", "2s");
        let result = dispatch_http(&entry, "test");
        assert!(!result.success);
        assert!(
            result.output.contains("connection failed")
                || result.output.contains("request failed")
                || result.output.contains("timed out"),
            "unexpected error: {}",
            result.output
        );
    }

    // ── Body wrapping ─────────────────────────────────────────────

    #[test]
    fn json_body_passthrough() {
        // If argument is already JSON, it should be sent as-is
        let arg = r#"{"query": "test"}"#;
        let body = if arg.trim_start().starts_with('{') {
            arg.to_string()
        } else {
            serde_json::json!({ "input": arg }).to_string()
        };
        assert_eq!(body, r#"{"query": "test"}"#);
    }

    #[test]
    fn plain_text_wrapped() {
        // If argument is plain text, it should be wrapped
        let arg = "search for cats";
        let body = if arg.trim_start().starts_with('{') || arg.trim_start().starts_with('[') {
            arg.to_string()
        } else {
            serde_json::json!({ "input": arg }).to_string()
        };
        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["input"], "search for cats");
    }

    #[test]
    fn array_body_passthrough() {
        let arg = r#"[1, 2, 3]"#;
        let body = if arg.trim_start().starts_with('{') || arg.trim_start().starts_with('[') {
            arg.to_string()
        } else {
            serde_json::json!({ "input": arg }).to_string()
        };
        assert_eq!(body, "[1, 2, 3]");
    }
}
