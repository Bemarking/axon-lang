//! Server Metrics — Prometheus exposition format for live AxonServer metrics.
//!
//! Generates text/plain Prometheus metrics from the running server state:
//!   - axon_server_uptime_seconds — server uptime
//!   - axon_server_requests_total — total API requests
//!   - axon_server_deployments_total — total deployments
//!   - axon_server_errors_total — total errors
//!   - axon_server_daemons_active — active daemons
//!   - axon_server_daemons_by_state — daemons by lifecycle state
//!   - axon_server_bus_events_published — events published on bus
//!   - axon_server_bus_topics_seen — unique topics seen
//!   - axon_server_versions_total — total flow versions tracked
//!   - axon_server_flows_tracked — number of tracked flows
//!   - axon_server_session_memory_count — ephemeral session entries
//!   - axon_server_session_store_count — persistent session entries
//!   - axon_server_rate_limiter_* — rate limiter state
//!   - axon_server_request_log_* — request log buffer state
//!   - axon_server_api_keys_* — API key counts
//!   - axon_server_webhooks_* — webhook registry and delivery stats
//!   - axon_server_audit_* — audit trail stats
//!   - axon_server_middleware_* — request middleware stats
//!   - axon_server_cors_permissive — CORS mode
//!   - axon_server_shutdown_initiated — shutdown state

use std::collections::HashMap;

/// Per-daemon metric for labeled Prometheus exposition.
#[derive(Debug, Clone)]
pub struct DaemonMetric {
    pub name: String,
    pub state: String,
    pub event_count: u64,
    pub restart_count: u32,
}

/// Per-client rate limiter metric for labeled Prometheus exposition.
#[derive(Debug, Clone)]
pub struct ClientRateLimitMetric {
    pub client_key: String,
    pub total_requests: u64,
    pub rejected: u64,
}

/// Per-topic metric for labeled Prometheus exposition.
#[derive(Debug, Clone)]
pub struct TopicMetric {
    pub topic: String,
    pub published: u64,
}

/// Per-flow execution metric for labeled Prometheus exposition.
#[derive(Debug, Clone)]
pub struct FlowMetric {
    pub flow_name: String,
    pub executions: u64,
    pub errors: u64,
    pub avg_latency_ms: u64,
}

/// Metrics snapshot from the running server.
#[derive(Debug, Clone)]
pub struct ServerSnapshot {
    pub uptime_secs: u64,
    pub server_start_timestamp: u64,
    pub total_requests: u64,
    pub total_deployments: u64,
    pub total_errors: u64,
    pub active_daemons: u32,
    pub daemon_states: HashMap<String, u32>,
    pub daemon_metrics: Vec<DaemonMetric>,
    pub daemon_total_restarts: u64,
    pub daemon_total_events: u64,
    pub bus_events_published: u64,
    pub bus_events_delivered: u64,
    pub bus_events_dropped: u64,
    pub bus_topics_seen: usize,
    pub bus_active_subscribers: usize,
    pub bus_topic_metrics: Vec<TopicMetric>,
    pub flows_tracked: usize,
    pub versions_total: usize,
    pub session_memory_count: usize,
    pub session_store_count: usize,
    pub deploy_count: u64,
    // ── Rate limiter ──
    pub rate_limiter_enabled: bool,
    pub rate_limiter_clients: usize,
    pub rate_limiter_max_requests: u32,
    pub rate_limiter_window_secs: u64,
    pub rate_limiter_client_metrics: Vec<ClientRateLimitMetric>,
    // ── Request log ──
    pub request_log_enabled: bool,
    pub request_log_buffered: usize,
    pub request_log_capacity: usize,
    pub request_log_total: u64,
    pub request_log_errors: u64,
    // ── API keys ──
    pub api_keys_enabled: bool,
    pub api_keys_active: usize,
    pub api_keys_total: usize,
    // ── Webhooks ──
    pub webhooks_total: usize,
    pub webhooks_active: usize,
    pub webhooks_deliveries_total: u64,
    pub webhooks_failures_total: u64,
    // ── Audit trail ──
    pub audit_buffered: usize,
    pub audit_total_recorded: u64,
    // ── Request middleware ──
    pub middleware_enabled: bool,
    pub middleware_requests_total: u64,
    pub middleware_slow_threshold_ms: u64,
    // ── CORS ──
    pub cors_enabled: bool,
    pub cors_permissive: bool,
    // ── Trace store ──
    pub trace_enabled: bool,
    pub trace_buffered: usize,
    pub trace_capacity: usize,
    pub trace_total_recorded: u64,
    pub trace_total_executions: u64,
    pub trace_total_errors: u64,
    pub flow_metrics: Vec<FlowMetric>,
    // ── Schedules ──
    pub schedules_total: usize,
    pub schedules_enabled: usize,
    pub schedules_total_runs: u64,
    pub schedules_total_errors: u64,
    pub schedules_avg_interval_secs: u64,
    // ── Shutdown ──
    pub shutdown_initiated: bool,
}

/// Generate Prometheus exposition format text from a server snapshot.
pub fn to_prometheus(snap: &ServerSnapshot) -> String {
    let mut out = String::new();

    // Uptime
    prom_gauge(&mut out, "axon_server_uptime_seconds", "Server uptime in seconds.", snap.uptime_secs);
    prom_gauge(&mut out, "axon_server_start_timestamp", "Server start time (Unix seconds).", snap.server_start_timestamp);

    // Requests
    prom_counter(&mut out, "axon_server_requests_total", "Total API requests handled.", snap.total_requests);

    // Deployments
    prom_counter(&mut out, "axon_server_deployments_total", "Total flow deployments.", snap.total_deployments);
    prom_counter(&mut out, "axon_server_deploy_count", "Total deploy operations.", snap.deploy_count);

    // Errors
    prom_counter(&mut out, "axon_server_errors_total", "Total errors encountered.", snap.total_errors);

    // Daemons
    prom_gauge(&mut out, "axon_server_daemons_active", "Number of active daemons.", snap.active_daemons as u64);

    // Daemon states
    if !snap.daemon_states.is_empty() {
        out.push_str("# HELP axon_server_daemons_by_state Daemons by lifecycle state.\n");
        out.push_str("# TYPE axon_server_daemons_by_state gauge\n");
        let mut states: Vec<_> = snap.daemon_states.iter().collect();
        states.sort_by_key(|(k, _)| (*k).clone());
        for (state, count) in states {
            out.push_str(&format!("axon_server_daemons_by_state{{state=\"{}\"}} {}\n", state, count));
        }
        out.push('\n');
    }

    // Daemon aggregate counters
    prom_counter(&mut out, "axon_server_daemon_total_restarts", "Total daemon restarts across all daemons.", snap.daemon_total_restarts);
    prom_counter(&mut out, "axon_server_daemon_total_events", "Total events processed across all daemons.", snap.daemon_total_events);

    // Per-daemon metrics (labeled)
    if !snap.daemon_metrics.is_empty() {
        out.push_str("# HELP axon_server_daemon_event_count Events processed by daemon.\n");
        out.push_str("# TYPE axon_server_daemon_event_count counter\n");
        let mut sorted: Vec<_> = snap.daemon_metrics.iter().collect();
        sorted.sort_by(|a, b| a.name.cmp(&b.name));
        for dm in &sorted {
            out.push_str(&format!(
                "axon_server_daemon_event_count{{daemon=\"{}\",state=\"{}\"}} {}\n",
                dm.name, dm.state, dm.event_count
            ));
        }
        out.push('\n');

        out.push_str("# HELP axon_server_daemon_restart_count Restart count by daemon.\n");
        out.push_str("# TYPE axon_server_daemon_restart_count counter\n");
        for dm in &sorted {
            out.push_str(&format!(
                "axon_server_daemon_restart_count{{daemon=\"{}\",state=\"{}\"}} {}\n",
                dm.name, dm.state, dm.restart_count
            ));
        }
        out.push('\n');
    }

    // Event bus
    prom_counter(&mut out, "axon_server_bus_events_published", "Total events published on the bus.", snap.bus_events_published);
    prom_counter(&mut out, "axon_server_bus_events_delivered", "Total events delivered to subscribers.", snap.bus_events_delivered);
    prom_counter(&mut out, "axon_server_bus_events_dropped", "Total events dropped (no subscriber).", snap.bus_events_dropped);
    prom_gauge(&mut out, "axon_server_bus_topics_seen", "Unique event topics seen.", snap.bus_topics_seen as u64);
    prom_gauge(&mut out, "axon_server_bus_active_subscribers", "Active event bus subscribers.", snap.bus_active_subscribers as u64);

    // Per-topic publish counts (labeled)
    if !snap.bus_topic_metrics.is_empty() {
        out.push_str("# HELP axon_server_bus_topic_published Events published per topic.\n");
        out.push_str("# TYPE axon_server_bus_topic_published counter\n");
        let mut sorted: Vec<_> = snap.bus_topic_metrics.iter().collect();
        sorted.sort_by(|a, b| a.topic.cmp(&b.topic));
        for tm in &sorted {
            out.push_str(&format!(
                "axon_server_bus_topic_published{{topic=\"{}\"}} {}\n",
                tm.topic, tm.published
            ));
        }
        out.push('\n');
    }

    // Versions
    prom_gauge(&mut out, "axon_server_flows_tracked", "Number of tracked flows.", snap.flows_tracked as u64);
    prom_gauge(&mut out, "axon_server_versions_total", "Total flow versions across all flows.", snap.versions_total as u64);

    // Session
    prom_gauge(&mut out, "axon_server_session_memory_count", "Ephemeral session memory entries.", snap.session_memory_count as u64);
    prom_gauge(&mut out, "axon_server_session_store_count", "Persistent session store entries.", snap.session_store_count as u64);

    // Rate limiter
    prom_gauge(&mut out, "axon_server_rate_limiter_enabled", "Whether rate limiting is enabled.", snap.rate_limiter_enabled as u64);
    prom_gauge(&mut out, "axon_server_rate_limiter_clients", "Number of tracked rate-limit clients.", snap.rate_limiter_clients as u64);
    prom_gauge(&mut out, "axon_server_rate_limiter_max_requests", "Max requests per window.", snap.rate_limiter_max_requests as u64);
    prom_gauge(&mut out, "axon_server_rate_limiter_window_secs", "Rate limit window in seconds.", snap.rate_limiter_window_secs);

    // Per-client rate limiter metrics (labeled)
    if !snap.rate_limiter_client_metrics.is_empty() {
        out.push_str("# HELP axon_server_rate_limiter_client_requests Total requests per client.\n");
        out.push_str("# TYPE axon_server_rate_limiter_client_requests counter\n");
        let mut sorted: Vec<_> = snap.rate_limiter_client_metrics.iter().collect();
        sorted.sort_by(|a, b| a.client_key.cmp(&b.client_key));
        for cm in &sorted {
            out.push_str(&format!(
                "axon_server_rate_limiter_client_requests{{client=\"{}\"}} {}\n",
                cm.client_key, cm.total_requests
            ));
        }
        out.push('\n');

        out.push_str("# HELP axon_server_rate_limiter_client_rejected Rejected requests per client.\n");
        out.push_str("# TYPE axon_server_rate_limiter_client_rejected counter\n");
        for cm in &sorted {
            out.push_str(&format!(
                "axon_server_rate_limiter_client_rejected{{client=\"{}\"}} {}\n",
                cm.client_key, cm.rejected
            ));
        }
        out.push('\n');
    }

    // Request log
    prom_gauge(&mut out, "axon_server_request_log_enabled", "Whether request logging is enabled.", snap.request_log_enabled as u64);
    prom_gauge(&mut out, "axon_server_request_log_buffered", "Entries currently in request log buffer.", snap.request_log_buffered as u64);
    prom_gauge(&mut out, "axon_server_request_log_capacity", "Max capacity of request log buffer.", snap.request_log_capacity as u64);
    prom_counter(&mut out, "axon_server_request_log_total", "Total requests recorded by request log.", snap.request_log_total);
    prom_counter(&mut out, "axon_server_request_log_errors", "Total error responses recorded.", snap.request_log_errors);

    // API keys
    prom_gauge(&mut out, "axon_server_api_keys_enabled", "Whether API key auth is enabled.", snap.api_keys_enabled as u64);
    prom_gauge(&mut out, "axon_server_api_keys_active", "Number of active (non-revoked) API keys.", snap.api_keys_active as u64);
    prom_gauge(&mut out, "axon_server_api_keys_total", "Total API keys (including revoked).", snap.api_keys_total as u64);

    // Webhooks
    prom_gauge(&mut out, "axon_server_webhooks_total", "Total registered webhooks.", snap.webhooks_total as u64);
    prom_gauge(&mut out, "axon_server_webhooks_active", "Active (enabled) webhooks.", snap.webhooks_active as u64);
    prom_counter(&mut out, "axon_server_webhooks_deliveries_total", "Total webhook deliveries attempted.", snap.webhooks_deliveries_total);
    prom_counter(&mut out, "axon_server_webhooks_failures_total", "Total webhook delivery failures.", snap.webhooks_failures_total);

    // Audit trail
    prom_gauge(&mut out, "axon_server_audit_buffered", "Entries currently in audit log buffer.", snap.audit_buffered as u64);
    prom_counter(&mut out, "axon_server_audit_total_recorded", "Total audit entries recorded.", snap.audit_total_recorded);

    // Request middleware
    prom_gauge(&mut out, "axon_server_middleware_enabled", "Whether request middleware is enabled.", snap.middleware_enabled as u64);
    prom_counter(&mut out, "axon_server_middleware_requests_total", "Total requests processed by middleware.", snap.middleware_requests_total);
    prom_gauge(&mut out, "axon_server_middleware_slow_threshold_ms", "Slow request threshold in milliseconds.", snap.middleware_slow_threshold_ms);

    // CORS
    prom_gauge(&mut out, "axon_server_cors_enabled", "Whether CORS is enabled.", snap.cors_enabled as u64);
    prom_gauge(&mut out, "axon_server_cors_permissive", "Whether CORS is in permissive (wildcard) mode.", snap.cors_permissive as u64);

    // Trace store
    prom_gauge(&mut out, "axon_server_trace_enabled", "Whether trace recording is enabled.", snap.trace_enabled as u64);
    prom_gauge(&mut out, "axon_server_trace_buffered", "Number of traces currently in buffer.", snap.trace_buffered as u64);
    prom_gauge(&mut out, "axon_server_trace_capacity", "Maximum trace buffer capacity.", snap.trace_capacity as u64);
    prom_counter(&mut out, "axon_server_trace_total_recorded", "Total traces recorded (including evicted).", snap.trace_total_recorded);
    prom_counter(&mut out, "axon_server_trace_total_executions", "Total flow executions via server.", snap.trace_total_executions);
    prom_counter(&mut out, "axon_server_trace_total_errors", "Total execution errors recorded in traces.", snap.trace_total_errors);

    // Per-flow execution metrics (labeled)
    if !snap.flow_metrics.is_empty() {
        out.push_str("# HELP axon_server_flow_executions Total executions per flow.\n");
        out.push_str("# TYPE axon_server_flow_executions counter\n");
        let mut sorted: Vec<_> = snap.flow_metrics.iter().collect();
        sorted.sort_by(|a, b| a.flow_name.cmp(&b.flow_name));
        for fm in &sorted {
            out.push_str(&format!("axon_server_flow_executions{{flow=\"{}\"}} {}\n", fm.flow_name, fm.executions));
        }
        out.push('\n');

        out.push_str("# HELP axon_server_flow_errors Total errors per flow.\n");
        out.push_str("# TYPE axon_server_flow_errors counter\n");
        for fm in &sorted {
            out.push_str(&format!("axon_server_flow_errors{{flow=\"{}\"}} {}\n", fm.flow_name, fm.errors));
        }
        out.push('\n');

        out.push_str("# HELP axon_server_flow_avg_latency_ms Average latency per flow in milliseconds.\n");
        out.push_str("# TYPE axon_server_flow_avg_latency_ms gauge\n");
        for fm in &sorted {
            out.push_str(&format!("axon_server_flow_avg_latency_ms{{flow=\"{}\"}} {}\n", fm.flow_name, fm.avg_latency_ms));
        }
        out.push('\n');
    }

    // Schedules
    prom_gauge(&mut out, "axon_server_schedules_total", "Total registered schedules.", snap.schedules_total as u64);
    prom_gauge(&mut out, "axon_server_schedules_enabled", "Number of enabled schedules.", snap.schedules_enabled as u64);
    prom_counter(&mut out, "axon_server_schedules_total_runs", "Total scheduled flow executions.", snap.schedules_total_runs);
    prom_counter(&mut out, "axon_server_schedules_total_errors", "Total errors from scheduled executions.", snap.schedules_total_errors);
    prom_gauge(&mut out, "axon_server_schedules_avg_interval_secs", "Average schedule interval in seconds.", snap.schedules_avg_interval_secs);

    // Shutdown
    prom_gauge(&mut out, "axon_server_shutdown_initiated", "Whether graceful shutdown has been initiated.", snap.shutdown_initiated as u64);

    out
}

fn prom_gauge(out: &mut String, name: &str, help: &str, value: u64) {
    out.push_str(&format!("# HELP {} {}\n", name, help));
    out.push_str(&format!("# TYPE {} gauge\n", name));
    out.push_str(&format!("{} {}\n\n", name, value));
}

fn prom_counter(out: &mut String, name: &str, help: &str, value: u64) {
    out.push_str(&format!("# HELP {} {}\n", name, help));
    out.push_str(&format!("# TYPE {} counter\n", name));
    out.push_str(&format!("{} {}\n\n", name, value));
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_snapshot() -> ServerSnapshot {
        let mut daemon_states = HashMap::new();
        daemon_states.insert("idle".to_string(), 2);
        daemon_states.insert("running".to_string(), 1);

        ServerSnapshot {
            uptime_secs: 3600,
            server_start_timestamp: 1700000000,
            total_requests: 150,
            total_deployments: 10,
            total_errors: 3,
            active_daemons: 3,
            daemon_states,
            daemon_metrics: vec![
                DaemonMetric { name: "worker-1".into(), state: "running".into(), event_count: 42, restart_count: 1 },
                DaemonMetric { name: "worker-2".into(), state: "idle".into(), event_count: 10, restart_count: 0 },
            ],
            daemon_total_restarts: 1,
            daemon_total_events: 52,
            bus_events_published: 50,
            bus_events_delivered: 45,
            bus_events_dropped: 5,
            bus_topics_seen: 8,
            bus_active_subscribers: 2,
            bus_topic_metrics: vec![
                TopicMetric { topic: "deploy".into(), published: 10 },
                TopicMetric { topic: "daemon.started".into(), published: 5 },
            ],
            flows_tracked: 4,
            versions_total: 12,
            session_memory_count: 5,
            session_store_count: 3,
            deploy_count: 10,
            rate_limiter_enabled: true,
            rate_limiter_clients: 3,
            rate_limiter_max_requests: 100,
            rate_limiter_window_secs: 60,
            rate_limiter_client_metrics: vec![
                ClientRateLimitMetric { client_key: "user-1".into(), total_requests: 50, rejected: 2 },
            ],
            request_log_enabled: true,
            request_log_buffered: 42,
            request_log_capacity: 1000,
            request_log_total: 150,
            request_log_errors: 5,
            api_keys_enabled: true,
            api_keys_active: 3,
            api_keys_total: 5,
            webhooks_total: 4,
            webhooks_active: 3,
            webhooks_deliveries_total: 20,
            webhooks_failures_total: 2,
            audit_buffered: 100,
            audit_total_recorded: 250,
            middleware_enabled: true,
            middleware_requests_total: 150,
            middleware_slow_threshold_ms: 5000,
            cors_enabled: true,
            cors_permissive: true,
            trace_enabled: true,
            trace_buffered: 25,
            trace_capacity: 500,
            trace_total_recorded: 42,
            trace_total_executions: 42,
            trace_total_errors: 3,
            flow_metrics: vec![
                FlowMetric { flow_name: "Pipeline".into(), executions: 50, errors: 3, avg_latency_ms: 120 },
            ],
            schedules_total: 3,
            schedules_enabled: 2,
            schedules_total_runs: 15,
            schedules_total_errors: 1,
            schedules_avg_interval_secs: 120,
            shutdown_initiated: false,
        }
    }

    #[test]
    fn prometheus_contains_uptime() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_uptime_seconds 3600"));
        assert!(prom.contains("# TYPE axon_server_uptime_seconds gauge"));
    }

    #[test]
    fn prometheus_contains_requests() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_requests_total 150"));
        assert!(prom.contains("# TYPE axon_server_requests_total counter"));
    }

    #[test]
    fn prometheus_contains_deployments() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_deployments_total 10"));
    }

    #[test]
    fn prometheus_contains_errors() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_errors_total 3"));
    }

    #[test]
    fn prometheus_contains_daemons() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_daemons_active 3"));
        assert!(prom.contains("axon_server_daemons_by_state{state=\"idle\"} 2"));
        assert!(prom.contains("axon_server_daemons_by_state{state=\"running\"} 1"));
    }

    #[test]
    fn prometheus_contains_bus_metrics() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_bus_events_published 50"));
        assert!(prom.contains("axon_server_bus_events_delivered 45"));
        assert!(prom.contains("axon_server_bus_events_dropped 5"));
        assert!(prom.contains("axon_server_bus_topics_seen 8"));
        assert!(prom.contains("axon_server_bus_active_subscribers 2"));
    }

    #[test]
    fn prometheus_contains_versions() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_flows_tracked 4"));
        assert!(prom.contains("axon_server_versions_total 12"));
    }

    #[test]
    fn prometheus_contains_session() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_session_memory_count 5"));
        assert!(prom.contains("axon_server_session_store_count 3"));
    }

    #[test]
    fn prometheus_has_help_and_type_for_all() {
        let prom = to_prometheus(&sample_snapshot());
        // Count HELP lines
        let help_count = prom.lines().filter(|l| l.starts_with("# HELP")).count();
        let type_count = prom.lines().filter(|l| l.starts_with("# TYPE")).count();
        assert!(help_count >= 56);
        assert_eq!(help_count, type_count);
    }

    #[test]
    fn prometheus_empty_daemon_states() {
        let mut snap = sample_snapshot();
        snap.daemon_states.clear();
        let prom = to_prometheus(&snap);
        assert!(!prom.contains("axon_server_daemons_by_state"));
    }

    #[test]
    fn prometheus_zero_snapshot() {
        let snap = ServerSnapshot {
            uptime_secs: 0,
            server_start_timestamp: 0,
            total_requests: 0,
            total_deployments: 0,
            total_errors: 0,
            active_daemons: 0,
            daemon_states: HashMap::new(),
            daemon_metrics: Vec::new(),
            daemon_total_restarts: 0,
            daemon_total_events: 0,
            bus_events_published: 0,
            bus_events_delivered: 0,
            bus_events_dropped: 0,
            bus_topics_seen: 0,
            bus_active_subscribers: 0,
            bus_topic_metrics: Vec::new(),
            flows_tracked: 0,
            versions_total: 0,
            session_memory_count: 0,
            session_store_count: 0,
            deploy_count: 0,
            rate_limiter_enabled: false,
            rate_limiter_clients: 0,
            rate_limiter_max_requests: 0,
            rate_limiter_window_secs: 0,
            rate_limiter_client_metrics: Vec::new(),
            request_log_enabled: false,
            request_log_buffered: 0,
            request_log_capacity: 0,
            request_log_total: 0,
            request_log_errors: 0,
            api_keys_enabled: false,
            api_keys_active: 0,
            api_keys_total: 0,
            webhooks_total: 0,
            webhooks_active: 0,
            webhooks_deliveries_total: 0,
            webhooks_failures_total: 0,
            audit_buffered: 0,
            audit_total_recorded: 0,
            middleware_enabled: false,
            middleware_requests_total: 0,
            middleware_slow_threshold_ms: 0,
            cors_enabled: false,
            cors_permissive: false,
            trace_enabled: false,
            trace_buffered: 0,
            trace_capacity: 0,
            trace_total_recorded: 0,
            trace_total_executions: 0,
            trace_total_errors: 0,
            flow_metrics: Vec::new(),
            schedules_total: 0,
            schedules_enabled: 0,
            schedules_total_runs: 0,
            schedules_total_errors: 0,
            schedules_avg_interval_secs: 0,
            shutdown_initiated: false,
        };
        let prom = to_prometheus(&snap);
        assert!(prom.contains("axon_server_uptime_seconds 0"));
        assert!(prom.contains("axon_server_requests_total 0"));
    }

    #[test]
    fn prometheus_contains_rate_limiter() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_rate_limiter_enabled 1"));
        assert!(prom.contains("axon_server_rate_limiter_clients 3"));
        assert!(prom.contains("axon_server_rate_limiter_max_requests 100"));
        assert!(prom.contains("axon_server_rate_limiter_window_secs 60"));
    }

    #[test]
    fn prometheus_contains_request_log() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_request_log_enabled 1"));
        assert!(prom.contains("axon_server_request_log_buffered 42"));
        assert!(prom.contains("axon_server_request_log_capacity 1000"));
        assert!(prom.contains("axon_server_request_log_total 150"));
        assert!(prom.contains("axon_server_request_log_errors 5"));
    }

    #[test]
    fn prometheus_contains_api_keys() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_api_keys_enabled 1"));
        assert!(prom.contains("axon_server_api_keys_active 3"));
        assert!(prom.contains("axon_server_api_keys_total 5"));
    }

    #[test]
    fn prometheus_contains_webhooks() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_webhooks_total 4"));
        assert!(prom.contains("axon_server_webhooks_active 3"));
        assert!(prom.contains("axon_server_webhooks_deliveries_total 20"));
        assert!(prom.contains("axon_server_webhooks_failures_total 2"));
    }

    #[test]
    fn prometheus_contains_audit() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_audit_buffered 100"));
        assert!(prom.contains("axon_server_audit_total_recorded 250"));
    }

    #[test]
    fn prometheus_contains_middleware() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_middleware_enabled 1"));
        assert!(prom.contains("axon_server_middleware_requests_total 150"));
        assert!(prom.contains("axon_server_middleware_slow_threshold_ms 5000"));
    }

    #[test]
    fn prometheus_contains_cors() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_cors_enabled 1"));
        assert!(prom.contains("axon_server_cors_permissive 1"));
    }

    #[test]
    fn prometheus_contains_shutdown() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_shutdown_initiated 0"));
    }

    #[test]
    fn prometheus_contains_trace_store() {
        let prom = to_prometheus(&sample_snapshot());
        assert!(prom.contains("axon_server_trace_enabled 1"));
        assert!(prom.contains("axon_server_trace_buffered 25"));
        assert!(prom.contains("axon_server_trace_capacity 500"));
        assert!(prom.contains("axon_server_trace_total_recorded 42"));
        assert!(prom.contains("axon_server_trace_total_executions 42"));
        assert!(prom.contains("axon_server_trace_total_errors 3"));
    }

    #[test]
    fn prometheus_valid_exposition_format() {
        let prom = to_prometheus(&sample_snapshot());
        // Every non-empty, non-comment line should be "metric_name{labels} value" or "metric_name value"
        for line in prom.lines() {
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            // Should have at least one space separating metric from value
            assert!(line.contains(' '), "Invalid line: {}", line);
        }
    }
}
