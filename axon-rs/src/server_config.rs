//! Server Config API — runtime-adjustable configuration for AxonServer.
//!
//! Provides a unified view of all configurable parameters and allows
//! runtime updates via `GET/PUT /v1/config`. Changes take effect immediately
//! without server restart.
//!
//! Configurable sections:
//!   - `rate_limit` — max_requests, window_secs, enabled
//!   - `request_log` — capacity, enabled
//!   - `auth` — enabled (read-only; reflects api_keys state)
//!
//! The config snapshot is a serializable struct that captures the current state.
//! Updates are partial: only fields present in the request are changed.

use serde::{Deserialize, Serialize};

// ── Config snapshot ────────────────────────────────────────────��────────

/// Complete server configuration snapshot.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigSnapshot {
    pub rate_limit: RateLimitSection,
    pub request_log: RequestLogSection,
    pub auth: AuthSection,
}

/// Rate limiter configuration section.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitSection {
    pub max_requests: u32,
    pub window_secs: u64,
    pub enabled: bool,
}

/// Request logger configuration section.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestLogSection {
    pub capacity: usize,
    pub enabled: bool,
}

/// Auth configuration section (read-only snapshot).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthSection {
    pub enabled: bool,
    pub active_keys: usize,
    pub total_keys: usize,
}

// ── Config update (partial) ─────────────────────────────────────────────

/// Partial configuration update request.
/// Only present fields are applied.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ConfigUpdate {
    pub rate_limit: Option<RateLimitUpdate>,
    pub request_log: Option<RequestLogUpdate>,
}

/// Partial rate limiter update.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RateLimitUpdate {
    pub max_requests: Option<u32>,
    pub window_secs: Option<u64>,
    pub enabled: Option<bool>,
}

/// Partial request logger update.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RequestLogUpdate {
    pub capacity: Option<usize>,
    pub enabled: Option<bool>,
}

// ── Change tracking ─────────────────────────────────────────────────────

/// A single config change that was applied.
#[derive(Debug, Clone, Serialize)]
pub struct ConfigChange {
    pub section: String,
    pub field: String,
    pub old_value: String,
    pub new_value: String,
}

/// Result of applying a config update.
#[derive(Debug, Clone, Serialize)]
pub struct ConfigUpdateResult {
    pub applied: bool,
    pub changes: Vec<ConfigChange>,
    pub snapshot: ConfigSnapshot,
}

// ── Snapshot builder ────────────────────────────────────────────────────

/// Build a ConfigSnapshot from the current server state components.
pub fn snapshot(
    rate_limiter: &crate::rate_limiter::RateLimiter,
    request_logger: &crate::request_log::RequestLogger,
    api_keys: &crate::api_keys::ApiKeyManager,
) -> ConfigSnapshot {
    let rl = rate_limiter.config();
    let log = request_logger.config();

    ConfigSnapshot {
        rate_limit: RateLimitSection {
            max_requests: rl.max_requests,
            window_secs: rl.window.as_secs(),
            enabled: rl.enabled,
        },
        request_log: RequestLogSection {
            capacity: log.capacity,
            enabled: log.enabled,
        },
        auth: AuthSection {
            enabled: api_keys.is_enabled(),
            active_keys: api_keys.active_count(),
            total_keys: api_keys.total_count(),
        },
    }
}

/// Build a ConfigSnapshot from rate_limiter, request_logger, and a pre-extracted AuthSection.
pub fn snapshot_with_auth(
    rate_limiter: &crate::rate_limiter::RateLimiter,
    request_logger: &crate::request_log::RequestLogger,
    auth: &AuthSection,
) -> ConfigSnapshot {
    let rl = rate_limiter.config();
    let log = request_logger.config();

    ConfigSnapshot {
        rate_limit: RateLimitSection {
            max_requests: rl.max_requests,
            window_secs: rl.window.as_secs(),
            enabled: rl.enabled,
        },
        request_log: RequestLogSection {
            capacity: log.capacity,
            enabled: log.enabled,
        },
        auth: auth.clone(),
    }
}

// ── Apply update ────────────────────────────────────────────────────────

/// Apply rate_limit portion of a config update. Returns changes.
pub fn apply_rate_limit(
    update: &RateLimitUpdate,
    rate_limiter: &mut crate::rate_limiter::RateLimiter,
) -> Vec<ConfigChange> {
    let mut changes = Vec::new();
    let old = rate_limiter.config().clone();

    if let Some(max) = update.max_requests {
        if max != old.max_requests {
            changes.push(ConfigChange {
                section: "rate_limit".into(),
                field: "max_requests".into(),
                old_value: old.max_requests.to_string(),
                new_value: max.to_string(),
            });
        }
    }
    if let Some(secs) = update.window_secs {
        if secs != old.window.as_secs() {
            changes.push(ConfigChange {
                section: "rate_limit".into(),
                field: "window_secs".into(),
                old_value: old.window.as_secs().to_string(),
                new_value: secs.to_string(),
            });
        }
    }
    if let Some(en) = update.enabled {
        if en != old.enabled {
            changes.push(ConfigChange {
                section: "rate_limit".into(),
                field: "enabled".into(),
                old_value: old.enabled.to_string(),
                new_value: en.to_string(),
            });
        }
    }

    rate_limiter.update_config(update.max_requests, update.window_secs, update.enabled);
    changes
}

/// Apply request_log portion of a config update. Returns changes.
pub fn apply_request_log(
    update: &RequestLogUpdate,
    request_logger: &mut crate::request_log::RequestLogger,
) -> Vec<ConfigChange> {
    let mut changes = Vec::new();
    let old = request_logger.config().clone();

    if let Some(cap) = update.capacity {
        if cap != old.capacity {
            changes.push(ConfigChange {
                section: "request_log".into(),
                field: "capacity".into(),
                old_value: old.capacity.to_string(),
                new_value: cap.to_string(),
            });
        }
    }
    if let Some(en) = update.enabled {
        if en != old.enabled {
            changes.push(ConfigChange {
                section: "request_log".into(),
                field: "enabled".into(),
                old_value: old.enabled.to_string(),
                new_value: en.to_string(),
            });
        }
    }

    request_logger.update_config(update.capacity, update.enabled);
    changes
}

/// Apply a partial config update. Dispatches to per-section apply functions.
/// Returns a result with the list of changes and the new snapshot.
pub fn apply(
    update: &ConfigUpdate,
    rate_limiter: &mut crate::rate_limiter::RateLimiter,
    request_logger: &mut crate::request_log::RequestLogger,
    auth_snap: &AuthSection,
) -> ConfigUpdateResult {
    let mut changes = Vec::new();

    if let Some(ref rl) = update.rate_limit {
        changes.extend(apply_rate_limit(rl, rate_limiter));
    }
    if let Some(ref log) = update.request_log {
        changes.extend(apply_request_log(log, request_logger));
    }

    let new_snapshot = snapshot_with_auth(rate_limiter, request_logger, auth_snap);

    ConfigUpdateResult {
        applied: !changes.is_empty(),
        changes,
        snapshot: new_snapshot,
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api_keys::ApiKeyManager;
    use crate::rate_limiter::{RateLimiter, RateLimitConfig};
    use crate::request_log::{RequestLogger, RequestLogConfig};

    fn make_components() -> (RateLimiter, RequestLogger, AuthSection) {
        let rl = RateLimiter::new(RateLimitConfig::default_config());
        let log = RequestLogger::new(RequestLogConfig::default_config());
        let auth = AuthSection { enabled: false, active_keys: 0, total_keys: 0 };
        (rl, log, auth)
    }

    #[test]
    fn snapshot_captures_defaults() {
        let (rl, log, auth) = make_components();
        let snap = snapshot_with_auth(&rl, &log, &auth);

        assert_eq!(snap.rate_limit.max_requests, 100);
        assert_eq!(snap.rate_limit.window_secs, 60);
        assert!(snap.rate_limit.enabled);
        assert_eq!(snap.request_log.capacity, 1000);
        assert!(snap.request_log.enabled);
        assert!(!snap.auth.enabled);
        assert_eq!(snap.auth.active_keys, 0);
    }

    #[test]
    fn snapshot_with_auth_enabled() {
        let rl = RateLimiter::new(RateLimitConfig::default_config());
        let log = RequestLogger::new(RequestLogConfig::default_config());
        let keys = ApiKeyManager::new(Some("master_tok"));
        let auth = AuthSection {
            enabled: keys.is_enabled(),
            active_keys: keys.active_count(),
            total_keys: keys.total_count(),
        };

        let snap = snapshot_with_auth(&rl, &log, &auth);
        assert!(snap.auth.enabled);
        assert_eq!(snap.auth.active_keys, 1);
        assert_eq!(snap.auth.total_keys, 1);
    }

    #[test]
    fn apply_rate_limit_changes() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                max_requests: Some(200),
                window_secs: Some(120),
                enabled: None,
            }),
            request_log: None,
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(result.applied);
        assert_eq!(result.changes.len(), 2);
        assert_eq!(result.snapshot.rate_limit.max_requests, 200);
        assert_eq!(result.snapshot.rate_limit.window_secs, 120);
        assert!(result.snapshot.rate_limit.enabled); // unchanged
    }

    #[test]
    fn apply_request_log_changes() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate {
            rate_limit: None,
            request_log: Some(RequestLogUpdate {
                capacity: Some(500),
                enabled: Some(false),
            }),
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(result.applied);
        assert_eq!(result.changes.len(), 2);
        assert_eq!(result.snapshot.request_log.capacity, 500);
        assert!(!result.snapshot.request_log.enabled);
    }

    #[test]
    fn apply_no_changes_when_same_values() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                max_requests: Some(100), // same as default
                window_secs: Some(60),   // same as default
                enabled: None,
            }),
            request_log: None,
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(!result.applied);
        assert!(result.changes.is_empty());
    }

    #[test]
    fn apply_empty_update() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate::default();
        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(!result.applied);
        assert!(result.changes.is_empty());
    }

    #[test]
    fn apply_combined_changes() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                max_requests: Some(50),
                window_secs: None,
                enabled: Some(false),
            }),
            request_log: Some(RequestLogUpdate {
                capacity: Some(2000),
                enabled: None,
            }),
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(result.applied);
        assert_eq!(result.changes.len(), 3);
        assert_eq!(result.snapshot.rate_limit.max_requests, 50);
        assert!(!result.snapshot.rate_limit.enabled);
        assert_eq!(result.snapshot.request_log.capacity, 2000);
    }

    #[test]
    fn change_tracking_records_old_and_new() {
        let (mut rl, mut log, auth) = make_components();

        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                max_requests: Some(250),
                window_secs: None,
                enabled: None,
            }),
            request_log: None,
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        assert_eq!(result.changes.len(), 1);
        let c = &result.changes[0];
        assert_eq!(c.section, "rate_limit");
        assert_eq!(c.field, "max_requests");
        assert_eq!(c.old_value, "100");
        assert_eq!(c.new_value, "250");
    }

    #[test]
    fn snapshot_serializes_to_json() {
        let (rl, log, auth) = make_components();
        let snap = snapshot_with_auth(&rl, &log, &auth);
        let json = serde_json::to_value(&snap).unwrap();

        assert_eq!(json["rate_limit"]["max_requests"], 100);
        assert_eq!(json["rate_limit"]["window_secs"], 60);
        assert_eq!(json["request_log"]["capacity"], 1000);
        assert_eq!(json["auth"]["enabled"], false);
    }

    #[test]
    fn update_result_serializes() {
        let (mut rl, mut log, auth) = make_components();
        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                max_requests: Some(75),
                window_secs: None,
                enabled: None,
            }),
            request_log: None,
        };

        let result = apply(&update, &mut rl, &mut log, &auth);
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["applied"], true);
        assert!(json["changes"].as_array().unwrap().len() == 1);
        assert_eq!(json["snapshot"]["rate_limit"]["max_requests"], 75);
    }

    #[test]
    fn disable_then_reenable_rate_limit() {
        let (mut rl, mut log, auth) = make_components();

        // Disable
        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                enabled: Some(false),
                ..Default::default()
            }),
            request_log: None,
        };
        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(!result.snapshot.rate_limit.enabled);

        // Re-enable with new limit
        let update = ConfigUpdate {
            rate_limit: Some(RateLimitUpdate {
                enabled: Some(true),
                max_requests: Some(500),
                ..Default::default()
            }),
            request_log: None,
        };
        let result = apply(&update, &mut rl, &mut log, &auth);
        assert!(result.snapshot.rate_limit.enabled);
        assert_eq!(result.snapshot.rate_limit.max_requests, 500);
    }
}
