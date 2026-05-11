//! §Fase 32.h — Replay-token binding for first-class axonendpoint routes.
//!
//! Per D9 (plan vivo numbering), every successful 2xx response to a
//! POST/PUT axonendpoint with replay enabled is registered in an
//! append-only log keyed by trace_id. Regulators / auditors retrieve
//! the original (request body, response body, metadata) tuple via
//! `GET /v1/replay/<trace_id>` — the foundation of audit-defensible AI
//! in regulated production (banking PCI DSS Req 10, government
//! FedRAMP AU-2, legal FRE 502, medicine 21 CFR Part 11).
//!
//! ## Default semantics (D9 backwards-compat)
//!
//! - `method ∈ {POST, PUT}` AND `replay:` omitted → replay enabled.
//! - `method ∈ {GET, DELETE}` AND `replay:` omitted → replay disabled
//!   (GET/DELETE are natively idempotent per HTTP spec; replaying
//!   them is a category error since the verb itself implies repeat-
//!   safe execution).
//! - `replay: true | false` explicit declaration overrides both
//!   defaults — adopters can disable replay on a sensitive POST
//!   (e.g. tokenization endpoints) or enable it on a custom GET
//!   that DOES need audit.
//!
//! ## Determinism status
//!
//! The replay entry carries a `deterministic: bool` flag. Set to
//! `true` when the runtime can prove the response was produced
//! deterministically (stub backend, locked LLM models with seed +
//! temperature=0). Set to `false` otherwise. The HTTP response of
//! `GET /v1/replay/<trace_id>` carries this as the
//! `Replay-Status: deterministic | non_deterministic` header so
//! auditors know whether they can re-execute and expect byte-identical
//! output, or whether they're inspecting the historical record only.
//!
//! ## Pillar trace per D12
//!
//! - **MATHEMATICS** — same input + same model state ⟹ same output
//!   (deterministic backends: stub, locked LLM with seed=k +
//!   temperature=0).
//! - **PHILOSOPHY** — the language honors its own declarations:
//!   adopters write `replay: true` and the runtime registers the
//!   binding without any middleware-of-middleware indirection.
//! - **LOGIC** — replay default is a total function over the
//!   method: `default(POST|PUT) = true`, `default(GET|DELETE) = false`.
//! - **COMPUTING** — regulatory replay is the foundation of audit-
//!   defensible AI in regulated production.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};

/// Default retention window for replay entries — 30 days per plan
/// vivo §9.2. In-memory store uses a capacity-bounded LRU layered
/// on top of this; production deployments swap in the enterprise
/// persistence backend for longer retention.
pub const DEFAULT_RETENTION: Duration = Duration::from_secs(30 * 24 * 60 * 60);

/// One replay binding entry. Immutable once minted.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AxonendpointReplayEntry {
    /// UUID v4 generated per dynamic-route request; the lookup key
    /// for `GET /v1/replay/<trace_id>`.
    pub trace_id: String,
    /// Unix-millis timestamp when the entry was recorded.
    pub timestamp_ms: u64,
    /// Source-declared axonendpoint name (audit-trail anchor).
    pub endpoint_name: String,
    /// `execute:` target — the flow that ran.
    pub flow_name: String,
    pub method: String,
    pub path: String,
    /// `client_id` extracted from `Authorization` header at request
    /// time (or `"anonymous"`). Same value the audit log records.
    pub client_id: String,
    /// Capability slugs the bearer held — projected into the entry
    /// so auditors can correlate the auth context.
    pub capabilities_used: Vec<String>,
    /// SHA-256 of the request body bytes (hex-encoded).
    pub request_body_hash_hex: String,
    /// Raw request body bytes (retained per audit policy; in-memory
    /// store; enterprise persistence layers encryption-at-rest).
    pub request_body: Vec<u8>,
    /// Response HTTP status code.
    pub response_status: u16,
    /// SHA-256 of the response body bytes (hex-encoded).
    pub response_body_hash_hex: String,
    /// Response Content-Type header verbatim (so the replay returns
    /// the original wire format).
    pub response_content_type: String,
    /// Raw response body bytes.
    pub response_body: Vec<u8>,
    /// Runtime version slug stored alongside the entry — production
    /// adopters bump this so replays from older versions are clearly
    /// distinguishable.
    pub model_version: String,
    /// Was the response produced deterministically? `true` for stub
    /// + locked-model backends; `false` for temperature>0 LLM calls.
    /// Surfaces in the `Replay-Status` HTTP header.
    pub deterministic: bool,
}

/// In-memory replay log. Indexed by `trace_id` for O(1) GET. Bounded
/// by capacity (default 10_000 entries — generous for the regulated-
/// vertical case where every POST gets replay-bound); oldest entry
/// evicted on overflow.
#[derive(Debug)]
pub struct AxonendpointReplayLog {
    entries: HashMap<String, AxonendpointReplayEntry>,
    /// Insertion-time tracker for capacity-bounded LRU. Separate from
    /// `timestamp_ms` because the latter is wall-clock (replay-readable)
    /// while this is monotonic for eviction ordering.
    inserted_at: HashMap<String, Instant>,
    capacity: usize,
    retention: Duration,
}

impl Default for AxonendpointReplayLog {
    fn default() -> Self {
        Self::new(10_000, DEFAULT_RETENTION)
    }
}

impl AxonendpointReplayLog {
    pub fn new(capacity: usize, retention: Duration) -> Self {
        Self {
            entries: HashMap::new(),
            inserted_at: HashMap::new(),
            capacity,
            retention,
        }
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// SHA-256 hex of body bytes. Stable across stacks.
    pub fn hash_body_hex(body: &[u8]) -> String {
        let mut h = Sha256::new();
        h.update(body);
        let digest = h.finalize();
        let mut s = String::with_capacity(64);
        for byte in digest.iter() {
            s.push_str(&format!("{byte:02x}"));
        }
        s
    }

    /// Append an entry. If at capacity AND the key is new, evicts
    /// the oldest entry first (by `inserted_at`). Same key overwrites
    /// in place (idempotent — a retry would just refresh metadata).
    pub fn append(&mut self, entry: AxonendpointReplayEntry) {
        let key = entry.trace_id.clone();
        if !self.entries.contains_key(&key) && self.entries.len() >= self.capacity {
            // Find oldest by insertion time.
            if let Some(oldest_key) = self
                .inserted_at
                .iter()
                .min_by_key(|(_, t)| **t)
                .map(|(k, _)| k.clone())
            {
                self.entries.remove(&oldest_key);
                self.inserted_at.remove(&oldest_key);
            }
        }
        self.inserted_at.insert(key.clone(), Instant::now());
        self.entries.insert(key, entry);
    }

    pub fn get(&self, trace_id: &str) -> Option<&AxonendpointReplayEntry> {
        self.entries.get(trace_id)
    }

    /// Reap entries older than the retention window. Returns the
    /// number reaped. Intended for periodic background sweeps.
    pub fn reap_expired(&mut self) -> usize {
        let now = Instant::now();
        let retention = self.retention;
        let before = self.entries.len();
        let to_remove: Vec<String> = self
            .inserted_at
            .iter()
            .filter(|(_, t)| now.duration_since(**t) > retention)
            .map(|(k, _)| k.clone())
            .collect();
        for k in &to_remove {
            self.entries.remove(k);
            self.inserted_at.remove(k);
        }
        before - self.entries.len()
    }
}

/// §Fase 32.h — Resolve the effective `replay` boolean for a route.
///
/// Pure + total function over `(method, replay_explicit, replay)`.
/// When the source declared `replay:` explicitly, the declared value
/// wins regardless of method. Otherwise the method-default fires:
/// POST/PUT → true, GET/DELETE/PATCH/* → false.
///
/// PATCH semantically updates state but the plan vivo §9 only
/// guarantees the binding for POST/PUT. Adopters who want replay on
/// PATCH declare `replay: true` explicitly.
pub fn resolve_replay_enabled(method: &str, replay_explicit: bool, replay: bool) -> bool {
    if replay_explicit {
        return replay;
    }
    matches!(method, "POST" | "PUT")
}

/// Determine whether a response was produced deterministically given
/// the resolved backend. Stub backends are deterministic by
/// construction; production LLM calls with temperature>0 are not.
/// Locked-model backends with seed + temperature=0 are deterministic
/// per the Fase 22.g.2 locked-model machinery.
///
/// For the OSS surface this is conservatively reported as
/// `backend == "stub"` (always deterministic). The enterprise
/// surface layers locked-model + seed checks on top.
pub fn is_backend_deterministic(backend: &str) -> bool {
    backend == "stub"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_post_replay_enabled() {
        assert!(resolve_replay_enabled("POST", false, false));
    }

    #[test]
    fn default_put_replay_enabled() {
        assert!(resolve_replay_enabled("PUT", false, false));
    }

    #[test]
    fn default_get_replay_disabled() {
        assert!(!resolve_replay_enabled("GET", false, false));
    }

    #[test]
    fn default_delete_replay_disabled() {
        assert!(!resolve_replay_enabled("DELETE", false, false));
    }

    #[test]
    fn explicit_false_overrides_post_default() {
        assert!(!resolve_replay_enabled("POST", true, false));
    }

    #[test]
    fn explicit_true_overrides_get_default() {
        assert!(resolve_replay_enabled("GET", true, true));
    }

    #[test]
    fn stub_backend_is_deterministic() {
        assert!(is_backend_deterministic("stub"));
    }

    #[test]
    fn llm_backend_is_not_deterministic_by_default() {
        assert!(!is_backend_deterministic("anthropic"));
        assert!(!is_backend_deterministic("openai"));
    }

    fn make_entry(trace_id: &str) -> AxonendpointReplayEntry {
        AxonendpointReplayEntry {
            trace_id: trace_id.to_string(),
            timestamp_ms: 0,
            endpoint_name: "E".to_string(),
            flow_name: "F".to_string(),
            method: "POST".to_string(),
            path: "/p".to_string(),
            client_id: "anon".to_string(),
            capabilities_used: vec![],
            request_body_hash_hex: AxonendpointReplayLog::hash_body_hex(b"{}"),
            request_body: b"{}".to_vec(),
            response_status: 200,
            response_body_hash_hex: AxonendpointReplayLog::hash_body_hex(b"ok"),
            response_content_type: "application/json".to_string(),
            response_body: b"ok".to_vec(),
            model_version: "axon.runtime.dynamic_route.v1".to_string(),
            deterministic: true,
        }
    }

    #[test]
    fn log_append_and_get_round_trip() {
        let mut log = AxonendpointReplayLog::default();
        let e = make_entry("t1");
        log.append(e);
        let got = log.get("t1").expect("entry must be present");
        assert_eq!(got.trace_id, "t1");
        assert_eq!(got.response_body, b"ok");
    }

    #[test]
    fn get_unknown_trace_id_returns_none() {
        let log = AxonendpointReplayLog::default();
        assert!(log.get("nope").is_none());
    }

    #[test]
    fn same_trace_id_overwrite_in_place() {
        let mut log = AxonendpointReplayLog::default();
        let mut e1 = make_entry("t1");
        e1.response_body = b"first".to_vec();
        log.append(e1);
        let mut e2 = make_entry("t1");
        e2.response_body = b"second".to_vec();
        log.append(e2);
        assert_eq!(log.len(), 1);
        assert_eq!(log.get("t1").unwrap().response_body, b"second");
    }

    #[test]
    fn capacity_eviction_drops_oldest() {
        let mut log = AxonendpointReplayLog::new(2, DEFAULT_RETENTION);
        log.append(make_entry("a"));
        std::thread::sleep(Duration::from_millis(1));
        log.append(make_entry("b"));
        std::thread::sleep(Duration::from_millis(1));
        log.append(make_entry("c"));
        assert_eq!(log.len(), 2);
        assert!(log.get("a").is_none(), "oldest must be evicted");
        assert!(log.get("c").is_some());
    }

    #[test]
    fn reap_expired_removes_old_entries() {
        let mut log = AxonendpointReplayLog::new(10, Duration::from_millis(0));
        log.append(make_entry("t1"));
        log.append(make_entry("t2"));
        std::thread::sleep(Duration::from_millis(2));
        assert_eq!(log.reap_expired(), 2);
        assert!(log.is_empty());
    }

    #[test]
    fn hash_body_hex_is_64_chars_lowercase() {
        let h = AxonendpointReplayLog::hash_body_hex(b"hello");
        assert_eq!(h.len(), 64);
        for c in h.chars() {
            assert!(c.is_ascii_hexdigit() && !c.is_ascii_uppercase());
        }
    }

    #[test]
    fn hash_body_hex_deterministic() {
        let a = AxonendpointReplayLog::hash_body_hex(b"{\"x\":1}");
        let b = AxonendpointReplayLog::hash_body_hex(b"{\"x\":1}");
        assert_eq!(a, b);
    }
}
