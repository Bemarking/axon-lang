//! API Key Management — multi-tenant key registry for AxonServer.
//!
//! Manages named API keys with metadata, permissions, and per-key rate limits.
//! Keys are stored in memory with optional file-backed persistence.
//!
//! Features:
//!   - Create, revoke, list, and validate API keys
//!   - Per-key metadata: name, role, created_at, last_used
//!   - Per-key rate limit override
//!   - Key rotation (revoke old, create new)
//!
//! Integration: replaces single auth_token check with multi-key validation.

use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

// ── Types ────────────────────────────────────────────────────────────────

/// Role/permission level for an API key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum KeyRole {
    /// Full access to all endpoints.
    Admin,
    /// Can deploy, estimate, read metrics — but not manage keys.
    Operator,
    /// Read-only: health, metrics, versions, logs.
    ReadOnly,
}

impl KeyRole {
    pub fn as_str(&self) -> &'static str {
        match self {
            KeyRole::Admin => "admin",
            KeyRole::Operator => "operator",
            KeyRole::ReadOnly => "readonly",
        }
    }

    /// Whether this role can perform write operations (deploy, session writes, etc.).
    pub fn can_write(&self) -> bool {
        matches!(self, KeyRole::Admin | KeyRole::Operator)
    }

    /// Whether this role can manage API keys.
    pub fn can_manage_keys(&self) -> bool {
        matches!(self, KeyRole::Admin)
    }
}

/// A registered API key with metadata.
#[derive(Debug, Clone, Serialize)]
pub struct ApiKey {
    /// The key name (human-readable identifier).
    pub name: String,
    /// The secret token value.
    #[serde(skip_serializing)]
    pub token: String,
    /// Permission role.
    pub role: KeyRole,
    /// Creation timestamp (Unix seconds).
    pub created_at: u64,
    /// Last used timestamp (Unix seconds), None if never used.
    pub last_used: Option<u64>,
    /// Optional per-key rate limit (requests per window).
    pub rate_limit: Option<u32>,
    /// Whether the key is active (not revoked).
    pub active: bool,
    /// Total requests made with this key.
    pub request_count: u64,
}

/// Result of validating a token.
#[derive(Debug, Clone)]
pub struct ValidationResult {
    pub valid: bool,
    pub key_name: Option<String>,
    pub role: Option<KeyRole>,
    pub rate_limit: Option<u32>,
}

// ── Manager ──────────────────────────────────────────────────────────────

/// API key registry and validator.
pub struct ApiKeyManager {
    /// Map of token → ApiKey.
    keys: HashMap<String, ApiKey>,
    /// Whether key management is enabled. If false, all auth is bypassed.
    enabled: bool,
}

impl ApiKeyManager {
    /// Create a new manager. If a master token is provided, it becomes the
    /// initial admin key.
    pub fn new(master_token: Option<&str>) -> Self {
        let mut mgr = ApiKeyManager {
            keys: HashMap::new(),
            enabled: false,
        };

        if let Some(token) = master_token {
            if !token.is_empty() {
                mgr.create_key("master", token, KeyRole::Admin, None);
                mgr.enabled = true;
            }
        }

        mgr
    }

    /// Whether key management is enabled.
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Create a new API key. Returns true if created (false if token already exists).
    pub fn create_key(&mut self, name: &str, token: &str, role: KeyRole, rate_limit: Option<u32>) -> bool {
        if self.keys.contains_key(token) {
            return false;
        }

        let key = ApiKey {
            name: name.to_string(),
            token: token.to_string(),
            role,
            created_at: now_secs(),
            last_used: None,
            rate_limit,
            active: true,
            request_count: 0,
        };

        self.keys.insert(token.to_string(), key);
        if !self.enabled {
            self.enabled = true;
        }
        true
    }

    /// Validate a token and record usage. Returns validation result.
    pub fn validate(&mut self, token: &str) -> ValidationResult {
        if !self.enabled {
            return ValidationResult {
                valid: true,
                key_name: None,
                role: None,
                rate_limit: None,
            };
        }

        match self.keys.get_mut(token) {
            Some(key) if key.active => {
                key.last_used = Some(now_secs());
                key.request_count += 1;
                ValidationResult {
                    valid: true,
                    key_name: Some(key.name.clone()),
                    role: Some(key.role),
                    rate_limit: key.rate_limit,
                }
            }
            _ => ValidationResult {
                valid: false,
                key_name: None,
                role: None,
                rate_limit: None,
            },
        }
    }

    /// Validate without recording usage (peek).
    pub fn peek(&self, token: &str) -> ValidationResult {
        if !self.enabled {
            return ValidationResult {
                valid: true,
                key_name: None,
                role: None,
                rate_limit: None,
            };
        }

        match self.keys.get(token) {
            Some(key) if key.active => ValidationResult {
                valid: true,
                key_name: Some(key.name.clone()),
                role: Some(key.role),
                rate_limit: key.rate_limit,
            },
            _ => ValidationResult {
                valid: false,
                key_name: None,
                role: None,
                rate_limit: None,
            },
        }
    }

    /// Revoke a key by token. Returns true if found and revoked.
    pub fn revoke(&mut self, token: &str) -> bool {
        match self.keys.get_mut(token) {
            Some(key) if key.active => {
                key.active = false;
                true
            }
            _ => false,
        }
    }

    /// Revoke a key by name. Returns true if found and revoked.
    pub fn revoke_by_name(&mut self, name: &str) -> bool {
        let token = self.keys.iter()
            .find(|(_, k)| k.name == name && k.active)
            .map(|(t, _)| t.clone());

        match token {
            Some(t) => self.revoke(&t),
            None => false,
        }
    }

    /// Rotate a key: revoke old token, create new one with same name/role.
    /// Returns the new token if successful.
    pub fn rotate(&mut self, old_token: &str, new_token: &str) -> Option<String> {
        let (name, role, rate_limit) = match self.keys.get(old_token) {
            Some(key) if key.active => (key.name.clone(), key.role, key.rate_limit),
            _ => return None,
        };

        self.revoke(old_token);
        if self.create_key(&name, new_token, role, rate_limit) {
            Some(name)
        } else {
            None
        }
    }

    /// List all keys (active and revoked). Tokens are masked.
    pub fn list(&self) -> Vec<ApiKeySummary> {
        let mut result: Vec<ApiKeySummary> = self.keys.values().map(|k| {
            ApiKeySummary {
                name: k.name.clone(),
                role: k.role,
                active: k.active,
                created_at: k.created_at,
                last_used: k.last_used,
                rate_limit: k.rate_limit,
                request_count: k.request_count,
                token_prefix: mask_token(&k.token),
            }
        }).collect();
        result.sort_by(|a, b| a.name.cmp(&b.name));
        result
    }

    /// Number of active keys.
    pub fn active_count(&self) -> usize {
        self.keys.values().filter(|k| k.active).count()
    }

    /// Total keys (including revoked).
    pub fn total_count(&self) -> usize {
        self.keys.len()
    }
}

/// Summary of an API key (token masked).
#[derive(Debug, Clone, Serialize)]
pub struct ApiKeySummary {
    pub name: String,
    pub role: KeyRole,
    pub active: bool,
    pub created_at: u64,
    pub last_used: Option<u64>,
    pub rate_limit: Option<u32>,
    pub request_count: u64,
    pub token_prefix: String,
}

// ── Helpers ──────────────────────────────────────────────────────────────

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn mask_token(token: &str) -> String {
    if token.len() <= 4 {
        "****".to_string()
    } else {
        format!("{}****", &token[..4])
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_and_validate() {
        let mut mgr = ApiKeyManager::new(None);
        assert!(!mgr.is_enabled());

        mgr.create_key("test-key", "tok_abc123", KeyRole::Operator, None);
        assert!(mgr.is_enabled());

        let result = mgr.validate("tok_abc123");
        assert!(result.valid);
        assert_eq!(result.key_name.unwrap(), "test-key");
        assert_eq!(result.role.unwrap(), KeyRole::Operator);
    }

    #[test]
    fn master_token_creates_admin() {
        let mgr = ApiKeyManager::new(Some("master_secret"));
        assert!(mgr.is_enabled());
        assert_eq!(mgr.active_count(), 1);

        let result = mgr.peek("master_secret");
        assert!(result.valid);
        assert_eq!(result.role.unwrap(), KeyRole::Admin);
    }

    #[test]
    fn invalid_token_rejected() {
        let mut mgr = ApiKeyManager::new(Some("valid"));
        let result = mgr.validate("invalid");
        assert!(!result.valid);
        assert!(result.key_name.is_none());
    }

    #[test]
    fn disabled_manager_allows_all() {
        let mut mgr = ApiKeyManager::new(None);
        let result = mgr.validate("anything");
        assert!(result.valid);
        assert!(result.role.is_none());
    }

    #[test]
    fn revoke_key() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("temp", "tok_temp", KeyRole::ReadOnly, None);
        assert!(mgr.validate("tok_temp").valid);

        assert!(mgr.revoke("tok_temp"));
        assert!(!mgr.validate("tok_temp").valid);

        // Revoke again returns false
        assert!(!mgr.revoke("tok_temp"));
    }

    #[test]
    fn revoke_by_name() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("mykey", "tok_mykey", KeyRole::Operator, None);
        assert!(mgr.revoke_by_name("mykey"));
        assert!(!mgr.validate("tok_mykey").valid);
        assert!(!mgr.revoke_by_name("mykey")); // already revoked
    }

    #[test]
    fn rotate_key() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("service", "old_token", KeyRole::Operator, Some(50));

        let name = mgr.rotate("old_token", "new_token").unwrap();
        assert_eq!(name, "service");

        // Old token revoked
        assert!(!mgr.validate("old_token").valid);

        // New token active with same role
        let result = mgr.validate("new_token");
        assert!(result.valid);
        assert_eq!(result.role.unwrap(), KeyRole::Operator);
        assert_eq!(result.rate_limit, Some(50));
    }

    #[test]
    fn rotate_invalid_token_fails() {
        let mut mgr = ApiKeyManager::new(None);
        assert!(mgr.rotate("nonexistent", "new").is_none());
    }

    #[test]
    fn duplicate_token_rejected() {
        let mut mgr = ApiKeyManager::new(None);
        assert!(mgr.create_key("a", "same_token", KeyRole::Admin, None));
        assert!(!mgr.create_key("b", "same_token", KeyRole::ReadOnly, None));
    }

    #[test]
    fn list_keys_masked() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("alpha", "tok_alpha_long", KeyRole::Admin, None);
        mgr.create_key("beta", "tok_beta_long", KeyRole::ReadOnly, Some(10));

        let list = mgr.list();
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].name, "alpha");
        assert_eq!(list[1].name, "beta");
        assert!(list[0].token_prefix.contains("****"));
        assert!(!list[0].token_prefix.contains("alpha_long"));
    }

    #[test]
    fn request_count_increments() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("counter", "tok_count", KeyRole::Operator, None);

        for _ in 0..5 {
            mgr.validate("tok_count");
        }

        let list = mgr.list();
        let key = list.iter().find(|k| k.name == "counter").unwrap();
        assert_eq!(key.request_count, 5);
    }

    #[test]
    fn last_used_updated() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("timed", "tok_timed", KeyRole::ReadOnly, None);

        let list = mgr.list();
        assert!(list[0].last_used.is_none());

        mgr.validate("tok_timed");

        let list = mgr.list();
        assert!(list[0].last_used.is_some());
        assert!(list[0].last_used.unwrap() > 1700000000);
    }

    #[test]
    fn key_role_permissions() {
        assert!(KeyRole::Admin.can_write());
        assert!(KeyRole::Admin.can_manage_keys());

        assert!(KeyRole::Operator.can_write());
        assert!(!KeyRole::Operator.can_manage_keys());

        assert!(!KeyRole::ReadOnly.can_write());
        assert!(!KeyRole::ReadOnly.can_manage_keys());
    }

    #[test]
    fn per_key_rate_limit() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("limited", "tok_limited", KeyRole::Operator, Some(25));

        let result = mgr.validate("tok_limited");
        assert_eq!(result.rate_limit, Some(25));

        mgr.create_key("unlimited", "tok_unlimited", KeyRole::Admin, None);
        let result = mgr.validate("tok_unlimited");
        assert_eq!(result.rate_limit, None);
    }

    #[test]
    fn active_and_total_counts() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("a", "t1", KeyRole::Admin, None);
        mgr.create_key("b", "t2", KeyRole::Operator, None);
        mgr.create_key("c", "t3", KeyRole::ReadOnly, None);

        assert_eq!(mgr.active_count(), 3);
        assert_eq!(mgr.total_count(), 3);

        mgr.revoke("t2");
        assert_eq!(mgr.active_count(), 2);
        assert_eq!(mgr.total_count(), 3);
    }

    #[test]
    fn mask_token_works() {
        assert_eq!(mask_token("abcdef"), "abcd****");
        assert_eq!(mask_token("ab"), "****");
        assert_eq!(mask_token(""), "****");
    }

    #[test]
    fn summary_serializes() {
        let summary = ApiKeySummary {
            name: "test".into(),
            role: KeyRole::Admin,
            active: true,
            created_at: 1700000000,
            last_used: None,
            rate_limit: None,
            request_count: 0,
            token_prefix: "tok_****".into(),
        };
        let json = serde_json::to_string(&summary).unwrap();
        assert!(json.contains("\"role\":\"admin\""));
        assert!(json.contains("\"active\":true"));
        assert!(json.contains("\"tok_****\""));
    }

    #[test]
    fn peek_does_not_update_usage() {
        let mut mgr = ApiKeyManager::new(None);
        mgr.create_key("peek_test", "tok_peek", KeyRole::ReadOnly, None);

        mgr.peek("tok_peek");
        mgr.peek("tok_peek");

        let list = mgr.list();
        let key = list.iter().find(|k| k.name == "peek_test").unwrap();
        assert_eq!(key.request_count, 0);
        assert!(key.last_used.is_none());
    }
}
