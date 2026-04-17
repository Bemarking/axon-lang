//! Flow Versioning — version tracking and rollback for deployed flows.
//!
//! Each deploy of a flow creates a new version entry. The version registry
//! tracks the full history per flow, supporting:
//!   - Version listing with metadata (source hash, timestamp, deploy count)
//!   - Active version tracking (which version is currently live)
//!   - Rollback to any previous version
//!   - Source diff between versions (via stored source snapshots)
//!
//! Versions are identified by a monotonic counter per flow (v1, v2, v3...).
//! The active version is always the most recently deployed unless rolled back.

use std::collections::HashMap;
use std::time::{Duration, Instant};

// ── Version types ────────────────────────────────────────────────────────

/// A single version of a deployed flow.
#[derive(Debug, Clone, serde::Serialize)]
pub struct FlowVersion {
    /// Version number (1-indexed, monotonic per flow).
    pub version: u32,
    /// SHA-256 hash of the source code (first 12 hex chars).
    pub source_hash: String,
    /// Full source snapshot for rollback.
    #[serde(skip_serializing)]
    pub source: String,
    /// Original filename.
    pub source_file: String,
    /// Backend used for compilation.
    pub backend: String,
    /// Flow names extracted from this source.
    pub flow_names: Vec<String>,
    /// Time of deployment (elapsed since registry creation).
    pub deployed_at: Duration,
    /// Whether this version is currently active.
    pub active: bool,
}

/// Version history for a single flow.
#[derive(Debug, Clone)]
pub struct FlowHistory {
    /// Flow name (key).
    pub flow_name: String,
    /// All versions, ordered by version number.
    pub versions: Vec<FlowVersion>,
    /// Currently active version number.
    pub active_version: u32,
    /// Total deploy count.
    pub deploy_count: u32,
}

impl FlowHistory {
    fn new(flow_name: &str) -> Self {
        FlowHistory {
            flow_name: flow_name.to_string(),
            versions: Vec::new(),
            active_version: 0,
            deploy_count: 0,
        }
    }

    /// Add a new version. Returns the version number.
    fn push_version(&mut self, source: &str, source_file: &str, backend: &str, flow_names: &[String], deployed_at: Duration) -> u32 {
        self.deploy_count += 1;
        let version = self.deploy_count;

        // Deactivate previous active version
        for v in &mut self.versions {
            v.active = false;
        }

        let hash = hash_source(source);
        self.versions.push(FlowVersion {
            version,
            source_hash: hash,
            source: source.to_string(),
            source_file: source_file.to_string(),
            backend: backend.to_string(),
            flow_names: flow_names.to_vec(),
            deployed_at,
            active: true,
        });
        self.active_version = version;
        version
    }

    /// Get a specific version.
    fn get_version(&self, version: u32) -> Option<&FlowVersion> {
        self.versions.iter().find(|v| v.version == version)
    }

    /// Get the active version.
    pub fn active(&self) -> Option<&FlowVersion> {
        self.versions.iter().find(|v| v.active)
    }

    /// Rollback to a specific version. Returns Ok(source) or Err if version not found.
    fn rollback(&mut self, target_version: u32) -> Result<String, String> {
        let exists = self.versions.iter().any(|v| v.version == target_version);
        if !exists {
            return Err(format!("version {} not found for flow '{}'", target_version, self.flow_name));
        }

        for v in &mut self.versions {
            v.active = v.version == target_version;
        }
        self.active_version = target_version;

        let source = self.versions.iter()
            .find(|v| v.version == target_version)
            .map(|v| v.source.clone())
            .unwrap();

        Ok(source)
    }
}

// ── Version Registry ─────────────────────────────────────────────────────

/// Registry tracking version history for all deployed flows.
pub struct VersionRegistry {
    histories: HashMap<String, FlowHistory>,
    created_at: Instant,
}

impl VersionRegistry {
    /// Create a new empty registry.
    pub fn new() -> Self {
        VersionRegistry {
            histories: HashMap::new(),
            created_at: Instant::now(),
        }
    }

    /// Record a new deployment. Returns (flow_name, version_number) pairs.
    pub fn record_deploy(
        &mut self,
        flow_names: &[String],
        source: &str,
        source_file: &str,
        backend: &str,
    ) -> Vec<(String, u32)> {
        let deployed_at = self.created_at.elapsed();
        let mut results = Vec::new();

        for name in flow_names {
            let history = self.histories
                .entry(name.clone())
                .or_insert_with(|| FlowHistory::new(name));

            let version = history.push_version(source, source_file, backend, flow_names, deployed_at);
            results.push((name.clone(), version));
        }

        results
    }

    /// Get version history for a flow.
    pub fn get_history(&self, flow_name: &str) -> Option<&FlowHistory> {
        self.histories.get(flow_name)
    }

    /// Get a specific version of a flow.
    pub fn get_version(&self, flow_name: &str, version: u32) -> Option<&FlowVersion> {
        self.histories.get(flow_name)?.get_version(version)
    }

    /// Get the active version of a flow.
    pub fn get_active(&self, flow_name: &str) -> Option<&FlowVersion> {
        self.histories.get(flow_name)?.active()
    }

    /// Rollback a flow to a specific version. Returns the source code.
    pub fn rollback(&mut self, flow_name: &str, target_version: u32) -> Result<String, String> {
        let history = self.histories.get_mut(flow_name)
            .ok_or_else(|| format!("flow '{}' not found", flow_name))?;
        history.rollback(target_version)
    }

    /// List all flows with their active version.
    pub fn list_flows(&self) -> Vec<FlowVersionSummary> {
        let mut flows: Vec<FlowVersionSummary> = self.histories.values().map(|h| {
            FlowVersionSummary {
                flow_name: h.flow_name.clone(),
                active_version: h.active_version,
                total_versions: h.versions.len() as u32,
                deploy_count: h.deploy_count,
                source_hash: h.active().map(|v| v.source_hash.clone()).unwrap_or_default(),
            }
        }).collect();
        flows.sort_by(|a, b| a.flow_name.cmp(&b.flow_name));
        flows
    }

    /// Total number of tracked flows.
    pub fn flow_count(&self) -> usize {
        self.histories.len()
    }

    /// Total number of versions across all flows.
    pub fn total_versions(&self) -> usize {
        self.histories.values().map(|h| h.versions.len()).sum()
    }
}

/// Summary of a flow's version state.
#[derive(Debug, Clone, serde::Serialize)]
pub struct FlowVersionSummary {
    pub flow_name: String,
    pub active_version: u32,
    pub total_versions: u32,
    pub deploy_count: u32,
    pub source_hash: String,
}

// ── Helpers ──────────────────────────────────────────────────────────────

/// Compute a short hash of source code (first 12 hex chars of a simple hash).
fn hash_source(source: &str) -> String {
    // Simple FNV-1a hash (no crypto dependency needed)
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in source.bytes() {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{:016x}", hash)[..12].to_string()
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_deterministic() {
        let h1 = hash_source("persona P { tone: \"analytical\" }");
        let h2 = hash_source("persona P { tone: \"analytical\" }");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 12);
    }

    #[test]
    fn hash_differs_for_different_source() {
        let h1 = hash_source("version 1");
        let h2 = hash_source("version 2");
        assert_ne!(h1, h2);
    }

    #[test]
    fn registry_record_deploy() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["Flow1".to_string()];
        let results = reg.record_deploy(&flows, "source v1", "test.axon", "anthropic");

        assert_eq!(results.len(), 1);
        assert_eq!(results[0], ("Flow1".to_string(), 1));
        assert_eq!(reg.flow_count(), 1);
        assert_eq!(reg.total_versions(), 1);
    }

    #[test]
    fn registry_multiple_deploys() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];

        reg.record_deploy(&flows, "v1 source", "f.axon", "anthropic");
        reg.record_deploy(&flows, "v2 source", "f.axon", "anthropic");
        reg.record_deploy(&flows, "v3 source", "f.axon", "anthropic");

        assert_eq!(reg.flow_count(), 1);
        assert_eq!(reg.total_versions(), 3);

        let history = reg.get_history("F").unwrap();
        assert_eq!(history.deploy_count, 3);
        assert_eq!(history.active_version, 3);
        assert_eq!(history.versions.len(), 3);

        // Only v3 should be active
        assert!(!history.versions[0].active);
        assert!(!history.versions[1].active);
        assert!(history.versions[2].active);
    }

    #[test]
    fn registry_get_version() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "src1", "f.axon", "anthropic");
        reg.record_deploy(&flows, "src2", "f.axon", "anthropic");

        let v1 = reg.get_version("F", 1).unwrap();
        assert_eq!(v1.version, 1);
        assert_eq!(v1.source, "src1");
        assert!(!v1.active);

        let v2 = reg.get_version("F", 2).unwrap();
        assert_eq!(v2.version, 2);
        assert!(v2.active);

        assert!(reg.get_version("F", 99).is_none());
        assert!(reg.get_version("NoSuch", 1).is_none());
    }

    #[test]
    fn registry_get_active() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "src1", "f.axon", "anthropic");
        reg.record_deploy(&flows, "src2", "f.axon", "anthropic");

        let active = reg.get_active("F").unwrap();
        assert_eq!(active.version, 2);
        assert!(active.active);
    }

    #[test]
    fn registry_rollback() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "source v1", "f.axon", "anthropic");
        reg.record_deploy(&flows, "source v2", "f.axon", "anthropic");
        reg.record_deploy(&flows, "source v3", "f.axon", "anthropic");

        // Active is v3
        assert_eq!(reg.get_active("F").unwrap().version, 3);

        // Rollback to v1
        let source = reg.rollback("F", 1).unwrap();
        assert_eq!(source, "source v1");
        assert_eq!(reg.get_active("F").unwrap().version, 1);

        // v2 and v3 should be inactive
        let h = reg.get_history("F").unwrap();
        assert!(h.versions[0].active);  // v1
        assert!(!h.versions[1].active); // v2
        assert!(!h.versions[2].active); // v3
    }

    #[test]
    fn registry_rollback_not_found() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "src", "f.axon", "anthropic");

        assert!(reg.rollback("F", 99).is_err());
        assert!(reg.rollback("NoSuch", 1).is_err());
    }

    #[test]
    fn registry_list_flows() {
        let mut reg = VersionRegistry::new();
        reg.record_deploy(&vec!["Alpha".to_string()], "a", "a.axon", "anthropic");
        reg.record_deploy(&vec!["Beta".to_string()], "b", "b.axon", "anthropic");
        reg.record_deploy(&vec!["Alpha".to_string()], "a2", "a.axon", "anthropic");

        let list = reg.list_flows();
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].flow_name, "Alpha");
        assert_eq!(list[0].active_version, 2);
        assert_eq!(list[0].total_versions, 2);
        assert_eq!(list[1].flow_name, "Beta");
        assert_eq!(list[1].active_version, 1);
    }

    #[test]
    fn registry_multi_flow_deploy() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["A".to_string(), "B".to_string()];
        let results = reg.record_deploy(&flows, "multi", "m.axon", "anthropic");

        assert_eq!(results.len(), 2);
        assert_eq!(reg.flow_count(), 2);

        // Both should be at version 1
        assert_eq!(reg.get_active("A").unwrap().version, 1);
        assert_eq!(reg.get_active("B").unwrap().version, 1);
    }

    #[test]
    fn version_source_hash_stored() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "persona P { tone: \"x\" }", "f.axon", "anthropic");

        let v = reg.get_version("F", 1).unwrap();
        assert!(!v.source_hash.is_empty());
        assert_eq!(v.source_hash.len(), 12);
    }

    #[test]
    fn flow_version_summary_serializes() {
        let summary = FlowVersionSummary {
            flow_name: "Test".into(),
            active_version: 3,
            total_versions: 5,
            deploy_count: 5,
            source_hash: "abc123def456".into(),
        };
        let json = serde_json::to_value(&summary).unwrap();
        assert_eq!(json["flow_name"], "Test");
        assert_eq!(json["active_version"], 3);
    }
}
