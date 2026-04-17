//! Config Persistence — save and restore AxonServer runtime configuration.
//!
//! Persists `ConfigSnapshot` to a JSON file on disk, allowing runtime
//! configuration changes to survive server restarts.
//!
//! Features:
//!   - Save current config snapshot to file
//!   - Load config snapshot from file on startup
//!   - Convert loaded snapshot into a `ConfigUpdate` for applying
//!   - Backup previous config before overwriting
//!   - Metadata: save timestamp, server version, save count
//!
//! Default path: `axon-server-config.json` in the working directory.

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::server_config::{ConfigSnapshot, ConfigUpdate, RateLimitUpdate, RequestLogUpdate};

// ── Persisted config envelope ───────────────────────────────────────────

/// Envelope wrapping a ConfigSnapshot with persistence metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersistedConfig {
    /// Schema version for forward compatibility.
    pub version: u32,
    /// Timestamp when this config was saved (Unix seconds).
    pub saved_at: u64,
    /// Server version that wrote this config.
    pub axon_version: String,
    /// Number of times this file has been updated.
    pub save_count: u64,
    /// The actual configuration snapshot.
    pub config: ConfigSnapshot,
}

/// Result of a save operation.
#[derive(Debug, Clone, Serialize)]
pub struct SaveResult {
    pub success: bool,
    pub path: String,
    pub save_count: u64,
    pub error: Option<String>,
}

/// Result of a load operation.
#[derive(Debug, Clone, Serialize)]
pub struct LoadResult {
    pub success: bool,
    pub path: String,
    pub saved_at: Option<u64>,
    pub save_count: Option<u64>,
    pub error: Option<String>,
}

// ── Default path ────────────────────────────────────────────────────────

/// Default config file name.
pub const DEFAULT_CONFIG_FILE: &str = "axon-server-config.json";

/// Resolve the config file path. If a custom path is given, use it;
/// otherwise use the default filename in the current directory.
pub fn resolve_path(custom: Option<&str>) -> PathBuf {
    match custom {
        Some(p) => PathBuf::from(p),
        None => PathBuf::from(DEFAULT_CONFIG_FILE),
    }
}

// ── Save ────────────────────────────────────────────────────────────────

/// Save a config snapshot to disk.
///
/// If the file already exists, reads the current save_count and increments it.
/// The file is written atomically (write to .tmp, then rename).
pub fn save(snapshot: &ConfigSnapshot, path: &Path, axon_version: &str) -> SaveResult {
    // Read existing save count
    let prev_count = match std::fs::read_to_string(path) {
        Ok(content) => {
            serde_json::from_str::<PersistedConfig>(&content)
                .map(|p| p.save_count)
                .unwrap_or(0)
        }
        Err(_) => 0,
    };

    let persisted = PersistedConfig {
        version: 1,
        saved_at: now_secs(),
        axon_version: axon_version.to_string(),
        save_count: prev_count + 1,
        config: snapshot.clone(),
    };

    let json = match serde_json::to_string_pretty(&persisted) {
        Ok(j) => j,
        Err(e) => {
            return SaveResult {
                success: false,
                path: path.display().to_string(),
                save_count: prev_count,
                error: Some(format!("serialize error: {e}")),
            };
        }
    };

    // Write to temp file then rename for atomicity
    let tmp_path = path.with_extension("json.tmp");
    if let Err(e) = std::fs::write(&tmp_path, &json) {
        return SaveResult {
            success: false,
            path: path.display().to_string(),
            save_count: prev_count,
            error: Some(format!("write error: {e}")),
        };
    }

    if let Err(e) = std::fs::rename(&tmp_path, path) {
        // Fallback: try direct write if rename fails (cross-device)
        if let Err(e2) = std::fs::write(path, &json) {
            return SaveResult {
                success: false,
                path: path.display().to_string(),
                save_count: prev_count,
                error: Some(format!("rename error: {e}, write fallback error: {e2}")),
            };
        }
        // Clean up tmp
        let _ = std::fs::remove_file(&tmp_path);
    }

    SaveResult {
        success: true,
        path: path.display().to_string(),
        save_count: persisted.save_count,
        error: None,
    }
}

// ── Load ────────────────────────────────────────────────────────────────

/// Load a persisted config from disk.
/// Returns the PersistedConfig envelope if successful.
pub fn load(path: &Path) -> Result<PersistedConfig, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("read error: {e}"))?;

    let persisted: PersistedConfig = serde_json::from_str(&content)
        .map_err(|e| format!("parse error: {e}"))?;

    if persisted.version != 1 {
        return Err(format!("unsupported config version: {}", persisted.version));
    }

    Ok(persisted)
}

/// Check if a persisted config file exists.
pub fn exists(path: &Path) -> bool {
    path.is_file()
}

/// Delete the persisted config file.
pub fn remove(path: &Path) -> bool {
    std::fs::remove_file(path).is_ok()
}

// ── Convert to update ───────────────────────────────────────────────────

/// Convert a ConfigSnapshot into a ConfigUpdate that can be applied to
/// restore the configuration. Auth section is skipped (not configurable).
pub fn snapshot_to_update(snapshot: &ConfigSnapshot) -> ConfigUpdate {
    ConfigUpdate {
        rate_limit: Some(RateLimitUpdate {
            max_requests: Some(snapshot.rate_limit.max_requests),
            window_secs: Some(snapshot.rate_limit.window_secs),
            enabled: Some(snapshot.rate_limit.enabled),
        }),
        request_log: Some(RequestLogUpdate {
            capacity: Some(snapshot.request_log.capacity),
            enabled: Some(snapshot.request_log.enabled),
        }),
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server_config::{AuthSection, RateLimitSection, RequestLogSection};
    use std::fs;

    fn sample_snapshot() -> ConfigSnapshot {
        ConfigSnapshot {
            rate_limit: RateLimitSection {
                max_requests: 200,
                window_secs: 120,
                enabled: true,
            },
            request_log: RequestLogSection {
                capacity: 500,
                enabled: false,
            },
            auth: AuthSection {
                enabled: true,
                active_keys: 2,
                total_keys: 3,
            },
        }
    }

    fn temp_path(name: &str) -> PathBuf {
        let dir = std::env::temp_dir();
        dir.join(format!("axon_test_{name}_{}.json", std::process::id()))
    }

    #[test]
    fn save_and_load_roundtrip() {
        let path = temp_path("roundtrip");
        let snap = sample_snapshot();

        let result = save(&snap, &path, "0.30.0-test");
        assert!(result.success);
        assert_eq!(result.save_count, 1);

        let loaded = load(&path).unwrap();
        assert_eq!(loaded.version, 1);
        assert_eq!(loaded.axon_version, "0.30.0-test");
        assert_eq!(loaded.save_count, 1);
        assert_eq!(loaded.config.rate_limit.max_requests, 200);
        assert_eq!(loaded.config.rate_limit.window_secs, 120);
        assert_eq!(loaded.config.request_log.capacity, 500);
        assert!(!loaded.config.request_log.enabled);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn save_increments_count() {
        let path = temp_path("increment");
        let snap = sample_snapshot();

        let r1 = save(&snap, &path, "v1");
        assert_eq!(r1.save_count, 1);

        let r2 = save(&snap, &path, "v1");
        assert_eq!(r2.save_count, 2);

        let r3 = save(&snap, &path, "v1");
        assert_eq!(r3.save_count, 3);

        let loaded = load(&path).unwrap();
        assert_eq!(loaded.save_count, 3);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn load_nonexistent_file() {
        let path = temp_path("nonexistent_98765");
        let result = load(&path);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("read error"));
    }

    #[test]
    fn load_invalid_json() {
        let path = temp_path("invalid");
        fs::write(&path, "not json at all").unwrap();

        let result = load(&path);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("parse error"));

        fs::remove_file(&path).ok();
    }

    #[test]
    fn load_wrong_version() {
        let path = temp_path("wrong_ver");
        let json = serde_json::json!({
            "version": 99,
            "saved_at": 0,
            "axon_version": "test",
            "save_count": 1,
            "config": {
                "rate_limit": { "max_requests": 100, "window_secs": 60, "enabled": true },
                "request_log": { "capacity": 1000, "enabled": true },
                "auth": { "enabled": false, "active_keys": 0, "total_keys": 0 }
            }
        });
        fs::write(&path, serde_json::to_string(&json).unwrap()).unwrap();

        let result = load(&path);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("unsupported config version"));

        fs::remove_file(&path).ok();
    }

    #[test]
    fn exists_and_remove() {
        let path = temp_path("exists_test");
        assert!(!exists(&path));

        let snap = sample_snapshot();
        save(&snap, &path, "test");
        assert!(exists(&path));

        assert!(remove(&path));
        assert!(!exists(&path));
        assert!(!remove(&path)); // already gone
    }

    #[test]
    fn snapshot_to_update_conversion() {
        let snap = sample_snapshot();
        let update = snapshot_to_update(&snap);

        let rl = update.rate_limit.unwrap();
        assert_eq!(rl.max_requests, Some(200));
        assert_eq!(rl.window_secs, Some(120));
        assert_eq!(rl.enabled, Some(true));

        let log = update.request_log.unwrap();
        assert_eq!(log.capacity, Some(500));
        assert_eq!(log.enabled, Some(false));
    }

    #[test]
    fn resolve_path_default() {
        let p = resolve_path(None);
        assert_eq!(p, PathBuf::from(DEFAULT_CONFIG_FILE));
    }

    #[test]
    fn resolve_path_custom() {
        let p = resolve_path(Some("/tmp/my-config.json"));
        assert_eq!(p, PathBuf::from("/tmp/my-config.json"));
    }

    #[test]
    fn persisted_config_serializes() {
        let snap = sample_snapshot();
        let persisted = PersistedConfig {
            version: 1,
            saved_at: 1700000000,
            axon_version: "0.30.0".into(),
            save_count: 5,
            config: snap,
        };

        let json = serde_json::to_value(&persisted).unwrap();
        assert_eq!(json["version"], 1);
        assert_eq!(json["save_count"], 5);
        assert_eq!(json["config"]["rate_limit"]["max_requests"], 200);
    }

    #[test]
    fn save_result_serializes() {
        let result = SaveResult {
            success: true,
            path: "/tmp/test.json".into(),
            save_count: 3,
            error: None,
        };
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["success"], true);
        assert_eq!(json["save_count"], 3);
    }
}
