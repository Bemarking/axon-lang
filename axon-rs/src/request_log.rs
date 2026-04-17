//! Request Logger — structured audit log for AxonServer API requests.
//!
//! Records each API request as a structured `RequestLogEntry` with:
//!   - method, path, status code, latency
//!   - client key (from auth token or "anonymous")
//!   - timestamp (monotonic + wall clock)
//!
//! The log is an in-memory ring buffer with configurable capacity.
//! Entries can be queried by path, status, or time range.
//!
//! Endpoints:
//!   - `GET /v1/logs` — query recent request logs
//!   - `GET /v1/logs/stats` — aggregate request statistics

use std::collections::VecDeque;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;

// ── Entry ────────────────────────────────────────────────────────────────

/// A single request log entry.
#[derive(Debug, Clone, Serialize)]
pub struct RequestLogEntry {
    /// Wall-clock timestamp (Unix seconds).
    pub timestamp: u64,
    /// HTTP method (GET, POST, DELETE).
    pub method: String,
    /// Request path (e.g., "/v1/deploy").
    pub path: String,
    /// HTTP status code.
    pub status: u16,
    /// Request latency in microseconds.
    pub latency_us: u64,
    /// Client identifier (auth token or "anonymous").
    pub client_key: String,
}

// ── Config ───────────────────────────────────────────────────────────────

/// Request logger configuration.
#[derive(Debug, Clone)]
pub struct RequestLogConfig {
    /// Maximum entries in the ring buffer.
    pub capacity: usize,
    /// Whether logging is enabled.
    pub enabled: bool,
}

impl RequestLogConfig {
    /// Default: 1000 entries, enabled.
    pub fn default_config() -> Self {
        RequestLogConfig {
            capacity: 1000,
            enabled: true,
        }
    }

    /// Disabled logger.
    pub fn disabled() -> Self {
        RequestLogConfig {
            capacity: 0,
            enabled: false,
        }
    }
}

// ── Logger ───────────────────────────────────────────────────────────────

/// In-memory ring buffer request logger.
pub struct RequestLogger {
    config: RequestLogConfig,
    entries: VecDeque<RequestLogEntry>,
    started_at: Instant,
    total_requests: u64,
    total_errors: u64,
}

impl RequestLogger {
    /// Create a new request logger.
    pub fn new(config: RequestLogConfig) -> Self {
        RequestLogger {
            entries: VecDeque::with_capacity(config.capacity.min(1024)),
            config,
            started_at: Instant::now(),
            total_requests: 0,
            total_errors: 0,
        }
    }

    /// Record a request.
    pub fn record(&mut self, method: &str, path: &str, status: u16, latency: Duration, client_key: &str) {
        if !self.config.enabled {
            return;
        }

        self.total_requests += 1;
        if status >= 400 {
            self.total_errors += 1;
        }

        let entry = RequestLogEntry {
            timestamp: wall_clock_secs(),
            method: method.to_string(),
            path: path.to_string(),
            status,
            latency_us: latency.as_micros() as u64,
            client_key: client_key.to_string(),
        };

        if self.entries.len() >= self.config.capacity && self.config.capacity > 0 {
            self.entries.pop_front();
        }
        if self.config.capacity > 0 {
            self.entries.push_back(entry);
        }
    }

    /// Get the configuration.
    pub fn config(&self) -> &RequestLogConfig {
        &self.config
    }

    /// Update the configuration at runtime.
    pub fn update_config(&mut self, capacity: Option<usize>, enabled: Option<bool>) {
        if let Some(cap) = capacity {
            self.config.capacity = cap;
            // Trim entries if new capacity is smaller
            while self.entries.len() > cap {
                self.entries.pop_front();
            }
        }
        if let Some(en) = enabled {
            self.config.enabled = en;
        }
    }

    /// Get recent entries (newest first), optionally filtered.
    pub fn recent(&self, limit: usize, filter: Option<&LogFilter>) -> Vec<&RequestLogEntry> {
        let result: Vec<&RequestLogEntry> = self.entries.iter().rev()
            .filter(|e| match filter {
                Some(f) => f.matches(e),
                None => true,
            })
            .take(limit)
            .collect();
        // Already newest-first from rev()
        result
    }

    /// Compute aggregate statistics.
    pub fn stats(&self) -> LogStats {
        let entries: Vec<&RequestLogEntry> = self.entries.iter().collect();

        let mut path_counts: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
        let mut status_counts: std::collections::HashMap<u16, u64> = std::collections::HashMap::new();
        let mut total_latency_us: u64 = 0;
        let mut max_latency_us: u64 = 0;

        for e in &entries {
            *path_counts.entry(e.path.clone()).or_insert(0) += 1;
            *status_counts.entry(e.status).or_insert(0) += 1;
            total_latency_us += e.latency_us;
            if e.latency_us > max_latency_us {
                max_latency_us = e.latency_us;
            }
        }

        let avg_latency_us = if entries.is_empty() {
            0
        } else {
            total_latency_us / entries.len() as u64
        };

        let mut top_paths: Vec<(String, u64)> = path_counts.into_iter().collect();
        top_paths.sort_by(|a, b| b.1.cmp(&a.1));
        top_paths.truncate(10);

        let mut status_breakdown: Vec<(u16, u64)> = status_counts.into_iter().collect();
        status_breakdown.sort_by_key(|(k, _)| *k);

        LogStats {
            total_requests: self.total_requests,
            total_errors: self.total_errors,
            buffered_entries: self.entries.len(),
            avg_latency_us,
            max_latency_us,
            top_paths,
            status_breakdown,
            uptime_secs: self.started_at.elapsed().as_secs(),
        }
    }

    /// Number of buffered entries.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether the buffer is empty.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Total requests recorded (including evicted).
    pub fn total_requests(&self) -> u64 {
        self.total_requests
    }

    /// Clear all entries.
    pub fn clear(&mut self) {
        self.entries.clear();
    }
}

// ── Filter ───────────────────────────────────────────────────────────────

/// Filter for querying log entries.
#[derive(Debug, Clone, Default, Serialize)]
pub struct LogFilter {
    /// Filter by path prefix (e.g., "/v1/deploy").
    pub path_prefix: Option<String>,
    /// Filter by minimum status code.
    pub min_status: Option<u16>,
    /// Filter by maximum status code.
    pub max_status: Option<u16>,
    /// Filter by client key.
    pub client_key: Option<String>,
}

impl LogFilter {
    /// Check if an entry matches this filter.
    pub fn matches(&self, entry: &RequestLogEntry) -> bool {
        if let Some(ref prefix) = self.path_prefix {
            if !entry.path.starts_with(prefix) {
                return false;
            }
        }
        if let Some(min) = self.min_status {
            if entry.status < min {
                return false;
            }
        }
        if let Some(max) = self.max_status {
            if entry.status > max {
                return false;
            }
        }
        if let Some(ref key) = self.client_key {
            if entry.client_key != *key {
                return false;
            }
        }
        true
    }
}

// ── Stats ────────────────────────────────────────────────────────────────

/// Aggregate request statistics.
#[derive(Debug, Clone, Serialize)]
pub struct LogStats {
    pub total_requests: u64,
    pub total_errors: u64,
    pub buffered_entries: usize,
    pub avg_latency_us: u64,
    pub max_latency_us: u64,
    pub top_paths: Vec<(String, u64)>,
    pub status_breakdown: Vec<(u16, u64)>,
    pub uptime_secs: u64,
}

// ── Helpers ──────────────────────────────────────────────────────────────

fn wall_clock_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_and_retrieve() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/health", 200, Duration::from_micros(500), "anon");
        logger.record("POST", "/v1/deploy", 200, Duration::from_micros(1500), "token_a");

        assert_eq!(logger.len(), 2);
        assert_eq!(logger.total_requests(), 2);

        let recent = logger.recent(10, None);
        assert_eq!(recent.len(), 2);
        // Newest first
        assert_eq!(recent[0].path, "/v1/deploy");
        assert_eq!(recent[1].path, "/v1/health");
    }

    #[test]
    fn ring_buffer_eviction() {
        let config = RequestLogConfig { capacity: 3, enabled: true };
        let mut logger = RequestLogger::new(config);

        for i in 0..5 {
            logger.record("GET", &format!("/v1/req{}", i), 200, Duration::from_micros(100), "c");
        }

        assert_eq!(logger.len(), 3);
        assert_eq!(logger.total_requests(), 5);

        let recent = logger.recent(10, None);
        assert_eq!(recent[0].path, "/v1/req4");
        assert_eq!(recent[2].path, "/v1/req2");
    }

    #[test]
    fn disabled_logger_no_recording() {
        let mut logger = RequestLogger::new(RequestLogConfig::disabled());
        logger.record("GET", "/v1/health", 200, Duration::from_micros(100), "c");
        assert_eq!(logger.len(), 0);
        assert_eq!(logger.total_requests(), 0);
    }

    #[test]
    fn error_counting() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/a", 200, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/b", 401, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/c", 500, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/d", 429, Duration::from_micros(100), "c");

        let stats = logger.stats();
        assert_eq!(stats.total_requests, 4);
        assert_eq!(stats.total_errors, 3); // 401, 500, 429
    }

    #[test]
    fn filter_by_path_prefix() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/health", 200, Duration::from_micros(100), "c");
        logger.record("POST", "/v1/deploy", 200, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/health/live", 200, Duration::from_micros(100), "c");

        let filter = LogFilter { path_prefix: Some("/v1/health".into()), ..Default::default() };
        let result = logger.recent(10, Some(&filter));
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn filter_by_status_range() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/a", 200, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/b", 401, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/c", 500, Duration::from_micros(100), "c");

        let filter = LogFilter { min_status: Some(400), ..Default::default() };
        let result = logger.recent(10, Some(&filter));
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn filter_by_client_key() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/a", 200, Duration::from_micros(100), "alice");
        logger.record("GET", "/v1/b", 200, Duration::from_micros(100), "bob");
        logger.record("GET", "/v1/c", 200, Duration::from_micros(100), "alice");

        let filter = LogFilter { client_key: Some("alice".into()), ..Default::default() };
        let result = logger.recent(10, Some(&filter));
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn stats_computation() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/health", 200, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/health", 200, Duration::from_micros(300), "c");
        logger.record("POST", "/v1/deploy", 200, Duration::from_micros(500), "c");

        let stats = logger.stats();
        assert_eq!(stats.total_requests, 3);
        assert_eq!(stats.total_errors, 0);
        assert_eq!(stats.buffered_entries, 3);
        assert_eq!(stats.avg_latency_us, 300); // (100+300+500)/3
        assert_eq!(stats.max_latency_us, 500);
        assert_eq!(stats.top_paths[0].0, "/v1/health");
        assert_eq!(stats.top_paths[0].1, 2);
    }

    #[test]
    fn stats_empty_logger() {
        let logger = RequestLogger::new(RequestLogConfig::default_config());
        let stats = logger.stats();
        assert_eq!(stats.total_requests, 0);
        assert_eq!(stats.avg_latency_us, 0);
        assert_eq!(stats.max_latency_us, 0);
    }

    #[test]
    fn clear_entries() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/a", 200, Duration::from_micros(100), "c");
        logger.record("GET", "/v1/b", 200, Duration::from_micros(100), "c");
        assert_eq!(logger.len(), 2);

        logger.clear();
        assert_eq!(logger.len(), 0);
        assert!(logger.is_empty());
        // total_requests preserved
        assert_eq!(logger.total_requests(), 2);
    }

    #[test]
    fn entry_serializes_to_json() {
        let entry = RequestLogEntry {
            timestamp: 1700000000,
            method: "POST".into(),
            path: "/v1/deploy".into(),
            status: 200,
            latency_us: 1500,
            client_key: "token_abc".into(),
        };
        let json = serde_json::to_string(&entry).unwrap();
        assert!(json.contains("\"method\":\"POST\""));
        assert!(json.contains("\"path\":\"/v1/deploy\""));
        assert!(json.contains("\"status\":200"));
        assert!(json.contains("\"latency_us\":1500"));
    }

    #[test]
    fn stats_serializes_to_json() {
        let stats = LogStats {
            total_requests: 100,
            total_errors: 5,
            buffered_entries: 50,
            avg_latency_us: 250,
            max_latency_us: 5000,
            top_paths: vec![("/v1/health".into(), 40)],
            status_breakdown: vec![(200, 95), (500, 5)],
            uptime_secs: 3600,
        };
        let json = serde_json::to_string(&stats).unwrap();
        assert!(json.contains("\"total_requests\":100"));
        assert!(json.contains("\"total_errors\":5"));
    }

    #[test]
    fn recent_with_limit() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        for i in 0..10 {
            logger.record("GET", &format!("/v1/r{}", i), 200, Duration::from_micros(100), "c");
        }
        let recent = logger.recent(3, None);
        assert_eq!(recent.len(), 3);
        assert_eq!(recent[0].path, "/v1/r9");
    }

    #[test]
    fn combined_filter() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("POST", "/v1/deploy", 200, Duration::from_micros(100), "alice");
        logger.record("POST", "/v1/deploy", 500, Duration::from_micros(100), "alice");
        logger.record("POST", "/v1/deploy", 200, Duration::from_micros(100), "bob");
        logger.record("GET", "/v1/health", 200, Duration::from_micros(100), "alice");

        let filter = LogFilter {
            path_prefix: Some("/v1/deploy".into()),
            client_key: Some("alice".into()),
            min_status: Some(200),
            max_status: Some(299),
        };
        let result = logger.recent(10, Some(&filter));
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].status, 200);
    }

    #[test]
    fn default_config_values() {
        let cfg = RequestLogConfig::default_config();
        assert_eq!(cfg.capacity, 1000);
        assert!(cfg.enabled);
    }

    #[test]
    fn timestamp_is_recent() {
        let mut logger = RequestLogger::new(RequestLogConfig::default_config());
        logger.record("GET", "/v1/a", 200, Duration::from_micros(100), "c");
        let recent = logger.recent(1, None);
        assert!(recent[0].timestamp > 1700000000);
    }
}
