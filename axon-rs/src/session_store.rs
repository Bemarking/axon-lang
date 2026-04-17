//! Session state / memory persistence — file-backed key-value store.
//!
//! Provides in-memory session state for `remember`/`recall` steps and
//! file-backed persistence for `persist`/`retrieve`/`mutate`/`purge` steps.
//!
//! Storage format: JSON file (`.axon-session.json`) next to the source file.
//! Each entry: { key, value, timestamp, source_step }.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// A single memory entry in the session store.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemoryEntry {
    pub key: String,
    pub value: String,
    pub timestamp: u64,
    pub source_step: String,
}

/// Session store — holds in-memory state and manages file persistence.
#[derive(Debug)]
pub struct SessionStore {
    /// In-memory entries (remember/recall — ephemeral within a run).
    memory: HashMap<String, MemoryEntry>,
    /// Persistent entries (persist/retrieve — file-backed across runs).
    store: HashMap<String, MemoryEntry>,
    /// Path to the persistent store file.
    store_path: PathBuf,
    /// Whether the persistent store has been modified (needs flush).
    dirty: bool,
}

impl SessionStore {
    /// Create a new session store. Loads existing persistent data if present.
    pub fn new(source_file: &str) -> Self {
        let store_path = Self::store_path_for(source_file);
        let store = Self::load_store(&store_path);

        SessionStore {
            memory: HashMap::new(),
            store,
            store_path,
            dirty: false,
        }
    }

    /// Derive the store file path from the source file path.
    fn store_path_for(source_file: &str) -> PathBuf {
        let p = Path::new(source_file);
        let stem = p.file_stem().unwrap_or_default().to_string_lossy();
        let dir = p.parent().unwrap_or_else(|| Path::new("."));
        dir.join(format!(".{stem}.session.json"))
    }

    /// Load persistent store from disk, or return empty if not found.
    fn load_store(path: &Path) -> HashMap<String, MemoryEntry> {
        match std::fs::read_to_string(path) {
            Ok(json) => {
                let entries: Vec<MemoryEntry> = serde_json::from_str(&json).unwrap_or_default();
                entries.into_iter().map(|e| (e.key.clone(), e)).collect()
            }
            Err(_) => HashMap::new(),
        }
    }

    /// Flush persistent store to disk.
    pub fn flush(&self) -> Result<(), String> {
        if !self.dirty {
            return Ok(());
        }
        let entries: Vec<&MemoryEntry> = self.store.values().collect();
        let json = serde_json::to_string_pretty(&entries)
            .map_err(|e| format!("Failed to serialize session store: {e}"))?;
        std::fs::write(&self.store_path, json)
            .map_err(|e| format!("Failed to write session store: {e}"))?;
        Ok(())
    }

    // ── Remember / Recall (ephemeral in-memory) ─────────────────────────

    /// Store a value in ephemeral memory.
    pub fn remember(&mut self, key: &str, value: &str, source_step: &str) {
        let entry = MemoryEntry {
            key: key.to_string(),
            value: value.to_string(),
            timestamp: current_timestamp(),
            source_step: source_step.to_string(),
        };
        self.memory.insert(key.to_string(), entry);
    }

    /// Recall a value from ephemeral memory. Returns None if not found.
    pub fn recall(&self, key: &str) -> Option<&MemoryEntry> {
        self.memory.get(key)
    }

    /// List all ephemeral memory entries.
    pub fn memory_entries(&self) -> Vec<&MemoryEntry> {
        self.memory.values().collect()
    }

    // ── Persist / Retrieve / Mutate / Purge (file-backed) ───────────────

    /// Persist a value to the file-backed store.
    pub fn persist(&mut self, key: &str, value: &str, source_step: &str) {
        let entry = MemoryEntry {
            key: key.to_string(),
            value: value.to_string(),
            timestamp: current_timestamp(),
            source_step: source_step.to_string(),
        };
        self.store.insert(key.to_string(), entry);
        self.dirty = true;
    }

    /// Retrieve a value from the file-backed store.
    pub fn retrieve(&self, key: &str) -> Option<&MemoryEntry> {
        self.store.get(key)
    }

    /// Retrieve all entries matching a simple query (substring match on key or value).
    pub fn retrieve_query(&self, query: &str) -> Vec<&MemoryEntry> {
        let q = query.to_lowercase();
        self.store
            .values()
            .filter(|e| e.key.to_lowercase().contains(&q) || e.value.to_lowercase().contains(&q))
            .collect()
    }

    /// Mutate (update) an existing entry in the store.
    /// Returns true if the key existed and was updated.
    pub fn mutate(&mut self, key: &str, new_value: &str, source_step: &str) -> bool {
        if self.store.contains_key(key) {
            self.persist(key, new_value, source_step);
            true
        } else {
            false
        }
    }

    /// Purge (delete) an entry from the store.
    /// Returns true if the key existed and was removed.
    pub fn purge(&mut self, key: &str) -> bool {
        if self.store.remove(key).is_some() {
            self.dirty = true;
            true
        } else {
            false
        }
    }

    /// Purge all entries matching a query (substring match).
    /// Returns the number of entries removed.
    pub fn purge_query(&mut self, query: &str) -> usize {
        let q = query.to_lowercase();
        let keys_to_remove: Vec<String> = self
            .store
            .iter()
            .filter(|(_, e)| e.key.to_lowercase().contains(&q) || e.value.to_lowercase().contains(&q))
            .map(|(k, _)| k.clone())
            .collect();
        let count = keys_to_remove.len();
        for k in keys_to_remove {
            self.store.remove(&k);
        }
        if count > 0 {
            self.dirty = true;
        }
        count
    }

    /// Number of entries in the persistent store.
    pub fn store_count(&self) -> usize {
        self.store.len()
    }

    /// Number of entries in ephemeral memory.
    pub fn memory_count(&self) -> usize {
        self.memory.len()
    }

    /// Path to the store file (for display).
    pub fn store_path(&self) -> &Path {
        &self.store_path
    }
}

fn current_timestamp() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_store(name: &str) -> SessionStore {
        let tmp = std::env::temp_dir().join(format!("axon_test_{name}.axon"));
        SessionStore::new(tmp.to_str().unwrap())
    }

    #[test]
    fn remember_and_recall() {
        let mut store = temp_store("rem_recall");
        store.remember("key1", "value1", "step_a");
        let entry = store.recall("key1").unwrap();
        assert_eq!(entry.value, "value1");
        assert_eq!(entry.source_step, "step_a");
        assert!(store.recall("nonexistent").is_none());
    }

    #[test]
    fn remember_overwrites() {
        let mut store = temp_store("rem_overwrite");
        store.remember("k", "v1", "s1");
        store.remember("k", "v2", "s2");
        assert_eq!(store.recall("k").unwrap().value, "v2");
    }

    #[test]
    fn persist_and_retrieve() {
        let mut store = temp_store("persist_ret");
        store.persist("data", "hello world", "persist_step");
        let entry = store.retrieve("data").unwrap();
        assert_eq!(entry.value, "hello world");
        assert!(store.retrieve("missing").is_none());
    }

    #[test]
    fn retrieve_query_matches() {
        let mut store = temp_store("ret_query");
        store.persist("analysis_result", "the answer is 42", "s1");
        store.persist("user_pref", "dark mode", "s2");
        store.persist("analysis_notes", "see appendix", "s3");

        let results = store.retrieve_query("analysis");
        assert_eq!(results.len(), 2);
    }

    #[test]
    fn mutate_existing() {
        let mut store = temp_store("mutate");
        store.persist("k", "old", "s1");
        assert!(store.mutate("k", "new", "s2"));
        assert_eq!(store.retrieve("k").unwrap().value, "new");
    }

    #[test]
    fn mutate_missing_returns_false() {
        let mut store = temp_store("mutate_miss");
        assert!(!store.mutate("nope", "val", "s1"));
    }

    #[test]
    fn purge_existing() {
        let mut store = temp_store("purge");
        store.persist("k", "v", "s1");
        assert!(store.purge("k"));
        assert!(store.retrieve("k").is_none());
    }

    #[test]
    fn purge_missing_returns_false() {
        let mut store = temp_store("purge_miss");
        assert!(!store.purge("nope"));
    }

    #[test]
    fn purge_query_removes_matching() {
        let mut store = temp_store("purge_q");
        store.persist("temp_a", "x", "s1");
        store.persist("temp_b", "y", "s2");
        store.persist("keep_c", "z", "s3");
        let removed = store.purge_query("temp");
        assert_eq!(removed, 2);
        assert_eq!(store.store_count(), 1);
    }

    #[test]
    fn flush_and_reload() {
        let tmp = std::env::temp_dir().join("axon_test_flush.axon");
        let store_path = {
            let mut store = SessionStore::new(tmp.to_str().unwrap());
            store.persist("persistent_key", "persistent_value", "test");
            store.flush().unwrap();
            store.store_path().to_path_buf()
        };

        // Reload from disk
        let store2 = SessionStore::new(tmp.to_str().unwrap());
        let entry = store2.retrieve("persistent_key").unwrap();
        assert_eq!(entry.value, "persistent_value");

        // Cleanup
        let _ = std::fs::remove_file(&store_path);
    }

    #[test]
    fn memory_count_and_store_count() {
        let mut store = temp_store("counts");
        store.remember("a", "1", "s");
        store.remember("b", "2", "s");
        store.persist("x", "10", "s");
        assert_eq!(store.memory_count(), 2);
        assert_eq!(store.store_count(), 1);
    }

    #[test]
    fn store_path_derives_from_source() {
        let store = SessionStore::new("/path/to/myprogram.axon");
        let path_str = store.store_path().to_string_lossy();
        assert!(path_str.contains(".myprogram.session.json"));
    }

    #[test]
    fn timestamp_is_recent() {
        let mut store = temp_store("timestamp");
        store.remember("k", "v", "s");
        let ts = store.recall("k").unwrap().timestamp;
        assert!(ts > 1700000000); // After ~2023
    }
}
