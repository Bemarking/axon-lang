//! Audit Trail — append-only log of administrative operations on AxonServer.
//!
//! Records every state-changing administrative action with:
//!   - Who performed it (key name or "anonymous")
//!   - What action was taken (deploy, config change, key management, etc.)
//!   - Target resource (flow name, config section, key name, webhook ID)
//!   - Detailed payload (JSON)
//!   - Timestamp
//!
//! The audit log is an in-memory ring buffer (configurable capacity).
//! Entries are append-only — they cannot be modified or deleted.
//!
//! Endpoints:
//!   - `GET /v1/audit` — query recent audit entries with filters
//!   - `GET /v1/audit/stats` — aggregated audit statistics

use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

// ── Action types ────────────────────────────────────────────────────────

/// Type of administrative action recorded in the audit log.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditAction {
    Deploy,
    ConfigUpdate,
    ConfigSave,
    ConfigLoad,
    ConfigDelete,
    KeyCreate,
    KeyRevoke,
    KeyRotate,
    WebhookRegister,
    WebhookRemove,
    WebhookToggle,
    DaemonDelete,
    Rollback,
    SessionWrite,
    SessionPurge,
    ServerShutdown,
    Execute,
}

impl AuditAction {
    pub fn as_str(&self) -> &'static str {
        match self {
            AuditAction::Deploy => "deploy",
            AuditAction::ConfigUpdate => "config_update",
            AuditAction::ConfigSave => "config_save",
            AuditAction::ConfigLoad => "config_load",
            AuditAction::ConfigDelete => "config_delete",
            AuditAction::KeyCreate => "key_create",
            AuditAction::KeyRevoke => "key_revoke",
            AuditAction::KeyRotate => "key_rotate",
            AuditAction::WebhookRegister => "webhook_register",
            AuditAction::WebhookRemove => "webhook_remove",
            AuditAction::WebhookToggle => "webhook_toggle",
            AuditAction::DaemonDelete => "daemon_delete",
            AuditAction::Rollback => "rollback",
            AuditAction::SessionWrite => "session_write",
            AuditAction::SessionPurge => "session_purge",
            AuditAction::ServerShutdown => "server_shutdown",
            AuditAction::Execute => "execute",
        }
    }
}

// ── Entry ───────────────────────────────────────────────────────────────

/// A single audit log entry.
#[derive(Debug, Clone, Serialize)]
pub struct AuditEntry {
    /// Sequential ID (monotonic).
    pub id: u64,
    /// Wall-clock timestamp (Unix seconds).
    pub timestamp: u64,
    /// Actor who performed the action (key name or "anonymous").
    pub actor: String,
    /// Type of action.
    pub action: AuditAction,
    /// Target resource (flow name, config section, key name, etc.).
    pub target: String,
    /// Additional detail (JSON payload).
    pub detail: serde_json::Value,
    /// Whether the action succeeded.
    pub success: bool,
}

// ── Filter ──────────────────────────────────────────────────────────────

/// Filter for querying audit entries.
#[derive(Debug, Clone, Default)]
pub struct AuditFilter {
    /// Filter by action type.
    pub action: Option<AuditAction>,
    /// Filter by actor name (exact match).
    pub actor: Option<String>,
    /// Filter by target (prefix match).
    pub target_prefix: Option<String>,
    /// Only entries after this timestamp.
    pub after: Option<u64>,
    /// Only entries before this timestamp.
    pub before: Option<u64>,
    /// Only successful or failed entries.
    pub success: Option<bool>,
}

impl AuditFilter {
    fn matches(&self, entry: &AuditEntry) -> bool {
        if let Some(action) = self.action {
            if entry.action != action {
                return false;
            }
        }
        if let Some(ref actor) = self.actor {
            if entry.actor != *actor {
                return false;
            }
        }
        if let Some(ref prefix) = self.target_prefix {
            if !entry.target.starts_with(prefix) {
                return false;
            }
        }
        if let Some(after) = self.after {
            if entry.timestamp < after {
                return false;
            }
        }
        if let Some(before) = self.before {
            if entry.timestamp > before {
                return false;
            }
        }
        if let Some(success) = self.success {
            if entry.success != success {
                return false;
            }
        }
        true
    }
}

// ── Stats ───────────────────────────────────────────────────────────────

/// Aggregated audit statistics.
#[derive(Debug, Clone, Serialize)]
pub struct AuditStats {
    pub total_entries: u64,
    pub buffered_entries: usize,
    pub actions_breakdown: HashMap<String, u64>,
    pub top_actors: Vec<(String, u64)>,
    pub failure_count: u64,
    pub oldest_timestamp: Option<u64>,
    pub newest_timestamp: Option<u64>,
}

// ── Audit log ───────────────────────────────────────────────────────────

/// Append-only audit log with configurable capacity.
pub struct AuditLog {
    entries: Vec<AuditEntry>,
    capacity: usize,
    next_id: u64,
    total_recorded: u64,
}

impl AuditLog {
    /// Create a new audit log with the given capacity.
    pub fn new(capacity: usize) -> Self {
        AuditLog {
            entries: Vec::new(),
            capacity,
            next_id: 1,
            total_recorded: 0,
        }
    }

    /// Record an audit entry. Returns the assigned ID.
    pub fn record(
        &mut self,
        actor: &str,
        action: AuditAction,
        target: &str,
        detail: serde_json::Value,
        success: bool,
    ) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        self.total_recorded += 1;

        let entry = AuditEntry {
            id,
            timestamp: now_secs(),
            actor: actor.to_string(),
            action,
            target: target.to_string(),
            detail,
            success,
        };

        self.entries.push(entry);

        // Trim oldest if over capacity
        while self.entries.len() > self.capacity {
            self.entries.remove(0);
        }

        id
    }

    /// Query recent entries (newest first), with optional filter and limit.
    pub fn query(&self, limit: usize, filter: Option<&AuditFilter>) -> Vec<&AuditEntry> {
        self.entries.iter().rev()
            .filter(|e| match filter {
                Some(f) => f.matches(e),
                None => true,
            })
            .take(limit)
            .collect()
    }

    /// Get a specific entry by ID.
    pub fn get(&self, id: u64) -> Option<&AuditEntry> {
        self.entries.iter().find(|e| e.id == id)
    }

    /// Compute aggregate statistics.
    pub fn stats(&self) -> AuditStats {
        let mut actions: HashMap<String, u64> = HashMap::new();
        let mut actors: HashMap<String, u64> = HashMap::new();
        let mut failure_count: u64 = 0;

        for entry in &self.entries {
            *actions.entry(entry.action.as_str().to_string()).or_insert(0) += 1;
            *actors.entry(entry.actor.clone()).or_insert(0) += 1;
            if !entry.success {
                failure_count += 1;
            }
        }

        let mut top_actors: Vec<(String, u64)> = actors.into_iter().collect();
        top_actors.sort_by(|a, b| b.1.cmp(&a.1));
        top_actors.truncate(10);

        AuditStats {
            total_entries: self.total_recorded,
            buffered_entries: self.entries.len(),
            actions_breakdown: actions,
            top_actors,
            failure_count,
            oldest_timestamp: self.entries.first().map(|e| e.timestamp),
            newest_timestamp: self.entries.last().map(|e| e.timestamp),
        }
    }

    /// Number of buffered entries.
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Total entries ever recorded (including evicted).
    pub fn total_recorded(&self) -> u64 {
        self.total_recorded
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Parse an action string to AuditAction.
pub fn parse_action(s: &str) -> Option<AuditAction> {
    match s {
        "deploy" => Some(AuditAction::Deploy),
        "config_update" => Some(AuditAction::ConfigUpdate),
        "config_save" => Some(AuditAction::ConfigSave),
        "config_load" => Some(AuditAction::ConfigLoad),
        "config_delete" => Some(AuditAction::ConfigDelete),
        "key_create" => Some(AuditAction::KeyCreate),
        "key_revoke" => Some(AuditAction::KeyRevoke),
        "key_rotate" => Some(AuditAction::KeyRotate),
        "webhook_register" => Some(AuditAction::WebhookRegister),
        "webhook_remove" => Some(AuditAction::WebhookRemove),
        "webhook_toggle" => Some(AuditAction::WebhookToggle),
        "daemon_delete" => Some(AuditAction::DaemonDelete),
        "rollback" => Some(AuditAction::Rollback),
        "session_write" => Some(AuditAction::SessionWrite),
        "session_purge" => Some(AuditAction::SessionPurge),
        "server_shutdown" => Some(AuditAction::ServerShutdown),
        _ => None,
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_and_query() {
        let mut log = AuditLog::new(100);
        let id = log.record("admin", AuditAction::Deploy, "FlowA", serde_json::json!({"flows": 1}), true);
        assert_eq!(id, 1);
        assert_eq!(log.len(), 1);
        assert_eq!(log.total_recorded(), 1);

        let entries = log.query(10, None);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].actor, "admin");
        assert_eq!(entries[0].action, AuditAction::Deploy);
        assert_eq!(entries[0].target, "FlowA");
        assert!(entries[0].success);
    }

    #[test]
    fn sequential_ids() {
        let mut log = AuditLog::new(100);
        let id1 = log.record("a", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        let id2 = log.record("b", AuditAction::KeyCreate, "key1", serde_json::json!(null), true);
        let id3 = log.record("a", AuditAction::ConfigUpdate, "rate_limit", serde_json::json!(null), true);

        assert_eq!(id1, 1);
        assert_eq!(id2, 2);
        assert_eq!(id3, 3);
    }

    #[test]
    fn capacity_eviction() {
        let mut log = AuditLog::new(3);
        for i in 0..5 {
            log.record("actor", AuditAction::Deploy, &format!("f{i}"), serde_json::json!(null), true);
        }

        assert_eq!(log.len(), 3);
        assert_eq!(log.total_recorded(), 5);

        // Oldest entries evicted — newest are f2, f3, f4
        let entries = log.query(10, None);
        assert_eq!(entries[0].target, "f4"); // newest first
        assert_eq!(entries[2].target, "f2"); // oldest remaining
    }

    #[test]
    fn get_by_id() {
        let mut log = AuditLog::new(100);
        log.record("a", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        let id = log.record("b", AuditAction::KeyCreate, "key1", serde_json::json!({"role": "admin"}), true);

        let entry = log.get(id).unwrap();
        assert_eq!(entry.actor, "b");
        assert_eq!(entry.action, AuditAction::KeyCreate);

        assert!(log.get(999).is_none());
    }

    #[test]
    fn filter_by_action() {
        let mut log = AuditLog::new(100);
        log.record("a", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        log.record("a", AuditAction::KeyCreate, "k1", serde_json::json!(null), true);
        log.record("a", AuditAction::Deploy, "F2", serde_json::json!(null), true);

        let filter = AuditFilter {
            action: Some(AuditAction::Deploy),
            ..Default::default()
        };
        let entries = log.query(10, Some(&filter));
        assert_eq!(entries.len(), 2);
        assert!(entries.iter().all(|e| e.action == AuditAction::Deploy));
    }

    #[test]
    fn filter_by_actor() {
        let mut log = AuditLog::new(100);
        log.record("alice", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        log.record("bob", AuditAction::Deploy, "F2", serde_json::json!(null), true);
        log.record("alice", AuditAction::ConfigUpdate, "rl", serde_json::json!(null), true);

        let filter = AuditFilter {
            actor: Some("alice".into()),
            ..Default::default()
        };
        let entries = log.query(10, Some(&filter));
        assert_eq!(entries.len(), 2);
        assert!(entries.iter().all(|e| e.actor == "alice"));
    }

    #[test]
    fn filter_by_target_prefix() {
        let mut log = AuditLog::new(100);
        log.record("a", AuditAction::Deploy, "flow:Alpha", serde_json::json!(null), true);
        log.record("a", AuditAction::Deploy, "flow:Beta", serde_json::json!(null), true);
        log.record("a", AuditAction::KeyCreate, "key:admin", serde_json::json!(null), true);

        let filter = AuditFilter {
            target_prefix: Some("flow:".into()),
            ..Default::default()
        };
        let entries = log.query(10, Some(&filter));
        assert_eq!(entries.len(), 2);
    }

    #[test]
    fn filter_by_success() {
        let mut log = AuditLog::new(100);
        log.record("a", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        log.record("a", AuditAction::Deploy, "F2", serde_json::json!(null), false);
        log.record("a", AuditAction::Deploy, "F3", serde_json::json!(null), true);

        let filter = AuditFilter {
            success: Some(false),
            ..Default::default()
        };
        let entries = log.query(10, Some(&filter));
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].target, "F2");
    }

    #[test]
    fn filter_combined() {
        let mut log = AuditLog::new(100);
        log.record("alice", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        log.record("bob", AuditAction::Deploy, "F2", serde_json::json!(null), true);
        log.record("alice", AuditAction::KeyCreate, "k1", serde_json::json!(null), true);
        log.record("alice", AuditAction::Deploy, "F3", serde_json::json!(null), false);

        let filter = AuditFilter {
            actor: Some("alice".into()),
            action: Some(AuditAction::Deploy),
            success: Some(true),
            ..Default::default()
        };
        let entries = log.query(10, Some(&filter));
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].target, "F1");
    }

    #[test]
    fn query_with_limit() {
        let mut log = AuditLog::new(100);
        for i in 0..10 {
            log.record("a", AuditAction::Deploy, &format!("f{i}"), serde_json::json!(null), true);
        }

        let entries = log.query(3, None);
        assert_eq!(entries.len(), 3);
        assert_eq!(entries[0].target, "f9"); // newest first
    }

    #[test]
    fn stats_aggregation() {
        let mut log = AuditLog::new(100);
        log.record("alice", AuditAction::Deploy, "F1", serde_json::json!(null), true);
        log.record("alice", AuditAction::Deploy, "F2", serde_json::json!(null), true);
        log.record("bob", AuditAction::KeyCreate, "k1", serde_json::json!(null), true);
        log.record("alice", AuditAction::ConfigUpdate, "rl", serde_json::json!(null), false);

        let stats = log.stats();
        assert_eq!(stats.total_entries, 4);
        assert_eq!(stats.buffered_entries, 4);
        assert_eq!(stats.failure_count, 1);
        assert_eq!(*stats.actions_breakdown.get("deploy").unwrap(), 2);
        assert_eq!(*stats.actions_breakdown.get("key_create").unwrap(), 1);
        assert_eq!(stats.top_actors[0].0, "alice");
        assert_eq!(stats.top_actors[0].1, 3);
        assert!(stats.oldest_timestamp.is_some());
        assert!(stats.newest_timestamp.is_some());
    }

    #[test]
    fn parse_action_roundtrip() {
        let actions = vec![
            AuditAction::Deploy, AuditAction::ConfigUpdate, AuditAction::ConfigSave,
            AuditAction::ConfigLoad, AuditAction::ConfigDelete, AuditAction::KeyCreate,
            AuditAction::KeyRevoke, AuditAction::KeyRotate, AuditAction::WebhookRegister,
            AuditAction::WebhookRemove, AuditAction::WebhookToggle, AuditAction::DaemonDelete,
            AuditAction::Rollback, AuditAction::SessionWrite, AuditAction::SessionPurge,
            AuditAction::ServerShutdown,
        ];

        for action in actions {
            let s = action.as_str();
            let parsed = parse_action(s).unwrap();
            assert_eq!(parsed, action);
        }

        assert!(parse_action("nonexistent").is_none());
    }

    #[test]
    fn entry_serializes() {
        let mut log = AuditLog::new(100);
        log.record("admin", AuditAction::Deploy, "FlowX", serde_json::json!({"count": 3}), true);

        let entry = log.get(1).unwrap();
        let json = serde_json::to_value(entry).unwrap();
        assert_eq!(json["id"], 1);
        assert_eq!(json["actor"], "admin");
        assert_eq!(json["action"], "deploy");
        assert_eq!(json["target"], "FlowX");
        assert_eq!(json["success"], true);
        assert_eq!(json["detail"]["count"], 3);
        assert!(json["timestamp"].is_u64());
    }

    #[test]
    fn stats_serializes() {
        let mut log = AuditLog::new(100);
        log.record("a", AuditAction::Deploy, "F1", serde_json::json!(null), true);

        let stats = log.stats();
        let json = serde_json::to_value(&stats).unwrap();
        assert_eq!(json["total_entries"], 1);
        assert_eq!(json["buffered_entries"], 1);
        assert!(json["actions_breakdown"].is_object());
        assert!(json["top_actors"].is_array());
    }
}
