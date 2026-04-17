//! `axon deploy` — hot-deploy .axon source to a running AxonServer.
//!
//! Reads an .axon file, sends its source to the server's `/v1/deploy`
//! endpoint via HTTP POST, and reports the result.
//!
//! Usage:
//!   axon deploy myflow.axon --server http://localhost:8420
//!   axon deploy myflow.axon --server http://prod:8420 --auth-token SECRET
//!
//! Exit codes:
//!   0 — deploy succeeded
//!   1 — deploy failed (compilation error on server)
//!   2 — I/O or connection error

use std::io::IsTerminal;
use std::time::Duration;

// ── Deploy configuration ──────────────────────────────────────────────────

/// Configuration for a deploy operation.
#[derive(Debug, Clone)]
pub struct DeployConfig {
    pub file: String,
    pub server: String,
    pub backend: String,
    pub auth_token: String,
}

// ── Deploy response ───────────────────────────────────────────────────────

/// Parsed response from the server's /v1/deploy endpoint.
#[derive(Debug)]
pub struct DeployResult {
    pub success: bool,
    pub deployed: Vec<String>,
    pub error: Option<String>,
    pub phase: Option<String>,
    pub raw_json: serde_json::Value,
}

// ── Deploy execution ──────────────────────────────────────────────────────

const DEPLOY_TIMEOUT: Duration = Duration::from_secs(30);

/// Execute a deploy operation. Returns exit code.
pub fn run_deploy(config: &DeployConfig) -> i32 {
    let use_color = std::io::stdout().is_terminal();

    // 1. Read the source file
    let source = match std::fs::read_to_string(&config.file) {
        Ok(s) => s,
        Err(e) => {
            let msg = format!("Cannot read '{}': {e}", config.file);
            if use_color {
                eprintln!("\x1b[1;31m{msg}\x1b[0m");
            } else {
                eprintln!("{msg}");
            }
            return 2;
        }
    };

    // 2. Validate server URL
    if !config.server.starts_with("http://") && !config.server.starts_with("https://") {
        let msg = format!(
            "Invalid server URL '{}'. Must start with http:// or https://.",
            config.server
        );
        if use_color {
            eprintln!("\x1b[1;31m{msg}\x1b[0m");
        } else {
            eprintln!("{msg}");
        }
        return 2;
    }

    // 3. Build the deploy URL
    let deploy_url = format!(
        "{}/v1/deploy",
        config.server.trim_end_matches('/')
    );

    if use_color {
        eprintln!(
            "\x1b[1;36m⬡ Deploying '{}' to {}\x1b[0m",
            config.file, config.server
        );
    } else {
        eprintln!("Deploying '{}' to {}", config.file, config.server);
    }

    // 4. Send the deploy request
    let result = send_deploy(&deploy_url, &config.file, &source, &config.backend, &config.auth_token);

    match result {
        Ok(deploy) => {
            if deploy.success {
                let names = deploy.deployed.join(", ");
                if use_color {
                    eprintln!(
                        "\x1b[1;32m  ✓ Deployed: {names} ({} flow{})\x1b[0m",
                        deploy.deployed.len(),
                        if deploy.deployed.len() == 1 { "" } else { "s" },
                    );
                } else {
                    eprintln!(
                        "  Deployed: {names} ({} flow{})",
                        deploy.deployed.len(),
                        if deploy.deployed.len() == 1 { "" } else { "s" },
                    );
                }
                0
            } else {
                let error = deploy.error.unwrap_or_else(|| "unknown error".to_string());
                let phase = deploy.phase.unwrap_or_else(|| "unknown".to_string());
                if use_color {
                    eprintln!(
                        "\x1b[1;31m  ✗ Deploy failed ({phase}): {error}\x1b[0m",
                    );
                } else {
                    eprintln!("  Deploy failed ({phase}): {error}");
                }
                1
            }
        }
        Err(e) => {
            if use_color {
                eprintln!("\x1b[1;31m  ✗ {e}\x1b[0m");
            } else {
                eprintln!("  {e}");
            }
            2
        }
    }
}

/// Send the deploy request to the server.
fn send_deploy(
    url: &str,
    filename: &str,
    source: &str,
    backend: &str,
    auth_token: &str,
) -> Result<DeployResult, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(DEPLOY_TIMEOUT)
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let body = serde_json::json!({
        "source": source,
        "filename": filename,
        "backend": backend,
    });

    let mut request = client
        .post(url)
        .header("Content-Type", "application/json");

    if !auth_token.is_empty() {
        request = request.header("Authorization", format!("Bearer {auth_token}"));
    }

    let response = request
        .body(body.to_string())
        .send()
        .map_err(|e| {
            if e.is_timeout() {
                format!("Server timed out after {}s", DEPLOY_TIMEOUT.as_secs())
            } else if e.is_connect() {
                format!("Cannot connect to server at {url}. Is `axon serve` running?")
            } else {
                format!("Request failed: {e}")
            }
        })?;

    let status = response.status();

    if status == reqwest::StatusCode::UNAUTHORIZED {
        return Err("Authentication required. Use --auth-token <TOKEN>.".to_string());
    }
    if status == reqwest::StatusCode::FORBIDDEN {
        return Err("Invalid auth token. Check your --auth-token value.".to_string());
    }

    let text = response
        .text()
        .map_err(|e| format!("Failed to read response: {e}"))?;

    if !status.is_success() {
        return Err(format!("Server returned HTTP {}: {text}", status.as_u16()));
    }

    let json: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("Invalid JSON response: {e}"))?;

    let success = json["success"].as_bool().unwrap_or(false);
    let deployed = json["deployed"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let error = json["error"].as_str().map(String::from);
    let phase = json["phase"].as_str().map(String::from);

    Ok(DeployResult {
        success,
        deployed,
        error,
        phase,
        raw_json: json,
    })
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deploy_config_defaults() {
        let cfg = DeployConfig {
            file: "test.axon".into(),
            server: "http://localhost:8420".into(),
            backend: "anthropic".into(),
            auth_token: String::new(),
        };
        assert_eq!(cfg.file, "test.axon");
        assert_eq!(cfg.server, "http://localhost:8420");
    }

    #[test]
    fn deploy_file_not_found() {
        let cfg = DeployConfig {
            file: "nonexistent_file_xyz.axon".into(),
            server: "http://localhost:8420".into(),
            backend: "anthropic".into(),
            auth_token: String::new(),
        };
        assert_eq!(run_deploy(&cfg), 2);
    }

    #[test]
    fn deploy_invalid_server_url() {
        // Write a temp file so we get past the file-read check
        let tmp = std::env::temp_dir().join("axon_test_deploy_url.axon");
        std::fs::write(&tmp, "persona P { tone: \"analytical\" }\n").unwrap();

        let cfg = DeployConfig {
            file: tmp.to_str().unwrap().into(),
            server: "ftp://badscheme".into(),
            backend: "anthropic".into(),
            auth_token: String::new(),
        };
        assert_eq!(run_deploy(&cfg), 2);
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn deploy_connection_refused() {
        let tmp = std::env::temp_dir().join("axon_test_deploy_conn.axon");
        std::fs::write(&tmp, "persona P { tone: \"analytical\" }\n").unwrap();

        let cfg = DeployConfig {
            file: tmp.to_str().unwrap().into(),
            server: "http://127.0.0.1:1".into(), // unreachable port
            backend: "anthropic".into(),
            auth_token: String::new(),
        };
        assert_eq!(run_deploy(&cfg), 2);
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn deploy_result_parsing() {
        let json: serde_json::Value = serde_json::json!({
            "success": true,
            "deployed": ["FlowA", "FlowB"],
            "flow_count": 2,
            "backend": "anthropic"
        });

        let success = json["success"].as_bool().unwrap_or(false);
        let deployed: Vec<String> = json["deployed"]
            .as_array()
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
            .unwrap_or_default();

        assert!(success);
        assert_eq!(deployed, vec!["FlowA", "FlowB"]);
    }

    #[test]
    fn deploy_error_result_parsing() {
        let json: serde_json::Value = serde_json::json!({
            "success": false,
            "error": "parse error: unexpected token",
            "phase": "parser"
        });

        let success = json["success"].as_bool().unwrap_or(false);
        let error = json["error"].as_str().map(String::from);
        let phase = json["phase"].as_str().map(String::from);

        assert!(!success);
        assert_eq!(error.unwrap(), "parse error: unexpected token");
        assert_eq!(phase.unwrap(), "parser");
    }

    #[test]
    fn deploy_url_construction() {
        let base = "http://localhost:8420";
        let url = format!("{}/v1/deploy", base.trim_end_matches('/'));
        assert_eq!(url, "http://localhost:8420/v1/deploy");

        let base_trailing = "http://localhost:8420/";
        let url = format!("{}/v1/deploy", base_trailing.trim_end_matches('/'));
        assert_eq!(url, "http://localhost:8420/v1/deploy");
    }
}
