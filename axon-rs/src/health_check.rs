//! Health Check — structured health assessment for AxonServer subsystems.
//!
//! Provides readiness/liveness checks with per-component status:
//!   - `event_bus` — event bus operational (has published or has subscribers)
//!   - `supervisor` — daemon supervisor (no dead daemons)
//!   - `session_store` — session store accessible
//!   - `version_registry` — flow version registry accessible
//!   - `rate_limiter` — rate limiter status and configuration
//!   - `request_logger` — request log buffer utilization
//!   - `api_keys` — API key manager status
//!   - `webhooks` — webhook registry and delivery health
//!   - `audit_log` — audit trail buffer utilization
//!
//! Endpoints:
//!   - `/v1/health` — full health report with component details
//!   - `/v1/health/live` — liveness probe (always up if responding)
//!   - `/v1/health/ready` — readiness probe (all components healthy or degraded)

use serde::Serialize;
use std::collections::HashMap;

// ── Types ────────────────────────────────────────────────────────────────

/// Overall health status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum HealthStatus {
    /// All components operational.
    Healthy,
    /// Some components impaired but server can still serve requests.
    Degraded,
    /// Critical failure — server cannot serve requests reliably.
    Unhealthy,
}

impl HealthStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            HealthStatus::Healthy => "healthy",
            HealthStatus::Degraded => "degraded",
            HealthStatus::Unhealthy => "unhealthy",
        }
    }
}

/// Result of checking a single component.
#[derive(Debug, Clone, Serialize)]
pub struct ComponentCheck {
    pub name: String,
    pub status: HealthStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

/// Full health report.
#[derive(Debug, Clone, Serialize)]
pub struct HealthReport {
    pub status: HealthStatus,
    pub uptime_secs: u64,
    pub axon_version: String,
    pub components: Vec<ComponentCheck>,
}

// ── Input snapshot ───────────────────────────────────────────────────────

/// Lightweight snapshot of server state for health evaluation.
/// Decouples health logic from the locked ServerState.
pub struct HealthInput {
    pub uptime_secs: u64,
    pub axon_version: String,
    pub daemon_count: usize,
    pub daemon_state_counts: HashMap<String, usize>,
    pub bus_events_published: u64,
    pub bus_subscriber_count: usize,
    pub session_memory_count: usize,
    pub session_store_count: usize,
    pub flows_tracked: usize,
    pub versions_total: usize,
    // D45: new component fields
    pub rate_limiter_enabled: bool,
    pub rate_limiter_max_requests: u32,
    pub rate_limiter_window_secs: u64,
    pub request_log_enabled: bool,
    pub request_log_entries: usize,
    pub request_log_capacity: usize,
    pub api_keys_enabled: bool,
    pub api_keys_active: usize,
    pub api_keys_total: usize,
    pub webhooks_active: usize,
    pub webhooks_total: usize,
    pub webhooks_total_failures: u64,
    pub audit_log_entries: usize,
    pub audit_log_total_recorded: u64,
}

// ── Evaluation ───────────────────────────────────────────────────────────

/// Evaluate full health from a server snapshot.
pub fn evaluate(input: &HealthInput) -> HealthReport {
    let mut components = Vec::new();

    // Event bus check
    components.push(check_event_bus(input));

    // Supervisor check
    components.push(check_supervisor(input));

    // Session store check
    components.push(check_session_store(input));

    // Version registry check
    components.push(check_version_registry(input));

    // Rate limiter check
    components.push(check_rate_limiter(input));

    // Request logger check
    components.push(check_request_logger(input));

    // API keys check
    components.push(check_api_keys(input));

    // Webhooks check
    components.push(check_webhooks(input));

    // Audit log check
    components.push(check_audit_log(input));

    // Aggregate status: unhealthy if any unhealthy, degraded if any degraded
    let status = aggregate_status(&components);

    HealthReport {
        status,
        uptime_secs: input.uptime_secs,
        axon_version: input.axon_version.clone(),
        components,
    }
}

/// Liveness check — always alive if the server is responding.
pub fn liveness() -> serde_json::Value {
    serde_json::json!({
        "status": "alive"
    })
}

/// Readiness check — ready if no component is unhealthy.
pub fn readiness(input: &HealthInput) -> serde_json::Value {
    let report = evaluate(input);
    let ready = report.status != HealthStatus::Unhealthy;
    serde_json::json!({
        "ready": ready,
        "status": report.status.as_str()
    })
}

// ── Component checks ─────────────────────────────────────────────────────

fn check_event_bus(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "events_published": input.bus_events_published,
        "subscriber_count": input.bus_subscriber_count,
    });

    // Bus is always healthy — it's an in-process channel, never "down"
    ComponentCheck {
        name: "event_bus".to_string(),
        status: HealthStatus::Healthy,
        message: None,
        details: Some(details),
    }
}

fn check_supervisor(input: &HealthInput) -> ComponentCheck {
    let dead = input.daemon_state_counts.get("dead").copied().unwrap_or(0);
    let total = input.daemon_count;

    let details = serde_json::json!({
        "daemon_count": total,
        "states": input.daemon_state_counts,
    });

    let (status, message) = if dead > 0 && dead == total && total > 0 {
        (HealthStatus::Unhealthy, Some(format!("all {} daemons dead", total)))
    } else if dead > 0 {
        (HealthStatus::Degraded, Some(format!("{} of {} daemons dead", dead, total)))
    } else {
        (HealthStatus::Healthy, None)
    };

    ComponentCheck {
        name: "supervisor".to_string(),
        status,
        message,
        details: Some(details),
    }
}

fn check_session_store(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "memory_entries": input.session_memory_count,
        "persistent_entries": input.session_store_count,
    });

    // Session store is in-process HashMap + file — always accessible
    ComponentCheck {
        name: "session_store".to_string(),
        status: HealthStatus::Healthy,
        message: None,
        details: Some(details),
    }
}

fn check_version_registry(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "flows_tracked": input.flows_tracked,
        "versions_total": input.versions_total,
    });

    ComponentCheck {
        name: "version_registry".to_string(),
        status: HealthStatus::Healthy,
        message: None,
        details: Some(details),
    }
}

fn check_rate_limiter(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "enabled": input.rate_limiter_enabled,
        "max_requests": input.rate_limiter_max_requests,
        "window_secs": input.rate_limiter_window_secs,
    });

    ComponentCheck {
        name: "rate_limiter".to_string(),
        status: HealthStatus::Healthy,
        message: if !input.rate_limiter_enabled { Some("disabled".to_string()) } else { None },
        details: Some(details),
    }
}

fn check_request_logger(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "enabled": input.request_log_enabled,
        "entries": input.request_log_entries,
        "capacity": input.request_log_capacity,
    });

    // Degraded if buffer is >90% full
    let (status, message) = if !input.request_log_enabled {
        (HealthStatus::Healthy, Some("disabled".to_string()))
    } else if input.request_log_capacity > 0 && input.request_log_entries * 100 / input.request_log_capacity > 90 {
        (HealthStatus::Degraded, Some(format!("buffer {}% full ({}/{})", input.request_log_entries * 100 / input.request_log_capacity, input.request_log_entries, input.request_log_capacity)))
    } else {
        (HealthStatus::Healthy, None)
    };

    ComponentCheck {
        name: "request_logger".to_string(),
        status,
        message,
        details: Some(details),
    }
}

fn check_api_keys(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "enabled": input.api_keys_enabled,
        "active_keys": input.api_keys_active,
        "total_keys": input.api_keys_total,
    });

    // Degraded if auth enabled but no active keys (locked out risk)
    let (status, message) = if input.api_keys_enabled && input.api_keys_active == 0 && input.api_keys_total > 0 {
        (HealthStatus::Degraded, Some("all keys revoked — only master token works".to_string()))
    } else {
        (HealthStatus::Healthy, None)
    };

    ComponentCheck {
        name: "api_keys".to_string(),
        status,
        message,
        details: Some(details),
    }
}

fn check_webhooks(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "active_webhooks": input.webhooks_active,
        "total_webhooks": input.webhooks_total,
        "total_failures": input.webhooks_total_failures,
    });

    // Degraded if >50% of webhooks have failures
    let (status, message) = if input.webhooks_total > 0 && input.webhooks_total_failures > input.webhooks_total as u64 * 5 {
        (HealthStatus::Degraded, Some(format!("{} delivery failures across {} webhooks", input.webhooks_total_failures, input.webhooks_total)))
    } else {
        (HealthStatus::Healthy, None)
    };

    ComponentCheck {
        name: "webhooks".to_string(),
        status,
        message,
        details: Some(details),
    }
}

fn check_audit_log(input: &HealthInput) -> ComponentCheck {
    let details = serde_json::json!({
        "buffered_entries": input.audit_log_entries,
        "total_recorded": input.audit_log_total_recorded,
    });

    ComponentCheck {
        name: "audit_log".to_string(),
        status: HealthStatus::Healthy,
        message: None,
        details: Some(details),
    }
}

fn aggregate_status(components: &[ComponentCheck]) -> HealthStatus {
    let mut worst = HealthStatus::Healthy;
    for c in components {
        match c.status {
            HealthStatus::Unhealthy => return HealthStatus::Unhealthy,
            HealthStatus::Degraded => worst = HealthStatus::Degraded,
            HealthStatus::Healthy => {}
        }
    }
    worst
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_input() -> HealthInput {
        let mut states = HashMap::new();
        states.insert("running".to_string(), 2);
        states.insert("waiting".to_string(), 1);

        HealthInput {
            uptime_secs: 3600,
            axon_version: "0.31.0".to_string(),
            daemon_count: 3,
            daemon_state_counts: states,
            bus_events_published: 100,
            bus_subscriber_count: 3,
            session_memory_count: 5,
            session_store_count: 2,
            flows_tracked: 4,
            versions_total: 10,
            rate_limiter_enabled: true,
            rate_limiter_max_requests: 100,
            rate_limiter_window_secs: 60,
            request_log_enabled: true,
            request_log_entries: 50,
            request_log_capacity: 1000,
            api_keys_enabled: true,
            api_keys_active: 3,
            api_keys_total: 5,
            webhooks_active: 2,
            webhooks_total: 3,
            webhooks_total_failures: 0,
            audit_log_entries: 100,
            audit_log_total_recorded: 150,
        }
    }

    #[test]
    fn healthy_report_all_green() {
        let report = evaluate(&sample_input());
        assert_eq!(report.status, HealthStatus::Healthy);
        assert_eq!(report.components.len(), 9);
        for c in &report.components {
            assert_eq!(c.status, HealthStatus::Healthy, "component {} not healthy", c.name);
        }
    }

    #[test]
    fn degraded_when_some_daemons_dead() {
        let mut input = sample_input();
        input.daemon_state_counts.insert("dead".to_string(), 1);
        let report = evaluate(&input);
        assert_eq!(report.status, HealthStatus::Degraded);
        let sup = report.components.iter().find(|c| c.name == "supervisor").unwrap();
        assert_eq!(sup.status, HealthStatus::Degraded);
        assert!(sup.message.as_ref().unwrap().contains("1 of"));
    }

    #[test]
    fn unhealthy_when_all_daemons_dead() {
        let mut states = HashMap::new();
        states.insert("dead".to_string(), 3);
        let mut input = sample_input();
        input.daemon_count = 3;
        input.daemon_state_counts = states;
        let report = evaluate(&input);
        assert_eq!(report.status, HealthStatus::Unhealthy);
        let sup = report.components.iter().find(|c| c.name == "supervisor").unwrap();
        assert_eq!(sup.status, HealthStatus::Unhealthy);
        assert!(sup.message.as_ref().unwrap().contains("all 3 daemons dead"));
    }

    #[test]
    fn healthy_when_no_daemons() {
        let mut input = sample_input();
        input.daemon_count = 0;
        input.daemon_state_counts.clear();
        let report = evaluate(&input);
        assert_eq!(report.status, HealthStatus::Healthy);
    }

    #[test]
    fn liveness_always_alive() {
        let live = liveness();
        assert_eq!(live["status"], "alive");
    }

    #[test]
    fn readiness_true_when_healthy() {
        let ready = readiness(&sample_input());
        assert_eq!(ready["ready"], true);
        assert_eq!(ready["status"], "healthy");
    }

    #[test]
    fn readiness_true_when_degraded() {
        let mut input = sample_input();
        input.daemon_state_counts.insert("dead".to_string(), 1);
        let ready = readiness(&input);
        assert_eq!(ready["ready"], true);
        assert_eq!(ready["status"], "degraded");
    }

    #[test]
    fn readiness_false_when_unhealthy() {
        let mut states = HashMap::new();
        states.insert("dead".to_string(), 2);
        let mut input = sample_input();
        input.daemon_count = 2;
        input.daemon_state_counts = states;
        let ready = readiness(&input);
        assert_eq!(ready["ready"], false);
        assert_eq!(ready["status"], "unhealthy");
    }

    #[test]
    fn report_includes_uptime_and_version() {
        let report = evaluate(&sample_input());
        assert_eq!(report.uptime_secs, 3600);
        assert_eq!(report.axon_version, "0.31.0");
    }

    #[test]
    fn component_details_present() {
        let report = evaluate(&sample_input());
        for c in &report.components {
            assert!(c.details.is_some(), "component {} missing details", c.name);
        }
    }

    #[test]
    fn event_bus_details_contain_counts() {
        let report = evaluate(&sample_input());
        let bus = report.components.iter().find(|c| c.name == "event_bus").unwrap();
        let d = bus.details.as_ref().unwrap();
        assert_eq!(d["events_published"], 100);
        assert_eq!(d["subscriber_count"], 3);
    }

    #[test]
    fn supervisor_details_contain_states() {
        let report = evaluate(&sample_input());
        let sup = report.components.iter().find(|c| c.name == "supervisor").unwrap();
        let d = sup.details.as_ref().unwrap();
        assert_eq!(d["daemon_count"], 3);
        assert!(d["states"].is_object());
    }

    #[test]
    fn session_store_details() {
        let report = evaluate(&sample_input());
        let sess = report.components.iter().find(|c| c.name == "session_store").unwrap();
        let d = sess.details.as_ref().unwrap();
        assert_eq!(d["memory_entries"], 5);
        assert_eq!(d["persistent_entries"], 2);
    }

    #[test]
    fn version_registry_details() {
        let report = evaluate(&sample_input());
        let ver = report.components.iter().find(|c| c.name == "version_registry").unwrap();
        let d = ver.details.as_ref().unwrap();
        assert_eq!(d["flows_tracked"], 4);
        assert_eq!(d["versions_total"], 10);
    }

    #[test]
    fn health_status_serialization() {
        let json = serde_json::to_string(&HealthStatus::Healthy).unwrap();
        assert_eq!(json, "\"healthy\"");
        let json = serde_json::to_string(&HealthStatus::Degraded).unwrap();
        assert_eq!(json, "\"degraded\"");
        let json = serde_json::to_string(&HealthStatus::Unhealthy).unwrap();
        assert_eq!(json, "\"unhealthy\"");
    }

    #[test]
    fn full_report_serializable() {
        let report = evaluate(&sample_input());
        let json = serde_json::to_string(&report).unwrap();
        assert!(json.contains("\"healthy\""));
        assert!(json.contains("\"event_bus\""));
        assert!(json.contains("\"supervisor\""));
        assert!(json.contains("\"session_store\""));
        assert!(json.contains("\"version_registry\""));
        assert!(json.contains("\"rate_limiter\""));
        assert!(json.contains("\"request_logger\""));
        assert!(json.contains("\"api_keys\""));
        assert!(json.contains("\"webhooks\""));
        assert!(json.contains("\"audit_log\""));
    }

    #[test]
    fn aggregate_picks_worst_status() {
        let checks = vec![
            ComponentCheck { name: "a".into(), status: HealthStatus::Healthy, message: None, details: None },
            ComponentCheck { name: "b".into(), status: HealthStatus::Degraded, message: None, details: None },
            ComponentCheck { name: "c".into(), status: HealthStatus::Healthy, message: None, details: None },
        ];
        assert_eq!(aggregate_status(&checks), HealthStatus::Degraded);

        let checks2 = vec![
            ComponentCheck { name: "a".into(), status: HealthStatus::Degraded, message: None, details: None },
            ComponentCheck { name: "b".into(), status: HealthStatus::Unhealthy, message: None, details: None },
        ];
        assert_eq!(aggregate_status(&checks2), HealthStatus::Unhealthy);
    }

    #[test]
    fn rate_limiter_details() {
        let report = evaluate(&sample_input());
        let rl = report.components.iter().find(|c| c.name == "rate_limiter").unwrap();
        assert_eq!(rl.status, HealthStatus::Healthy);
        let d = rl.details.as_ref().unwrap();
        assert_eq!(d["enabled"], true);
        assert_eq!(d["max_requests"], 100);
        assert_eq!(d["window_secs"], 60);
    }

    #[test]
    fn rate_limiter_disabled_shows_message() {
        let mut input = sample_input();
        input.rate_limiter_enabled = false;
        let report = evaluate(&input);
        let rl = report.components.iter().find(|c| c.name == "rate_limiter").unwrap();
        assert_eq!(rl.status, HealthStatus::Healthy);
        assert_eq!(rl.message.as_deref(), Some("disabled"));
    }

    #[test]
    fn request_logger_degraded_when_buffer_full() {
        let mut input = sample_input();
        input.request_log_entries = 950;
        input.request_log_capacity = 1000;
        let report = evaluate(&input);
        let rl = report.components.iter().find(|c| c.name == "request_logger").unwrap();
        assert_eq!(rl.status, HealthStatus::Degraded);
        assert!(rl.message.as_ref().unwrap().contains("95%"));
    }

    #[test]
    fn request_logger_healthy_when_low_usage() {
        let report = evaluate(&sample_input());
        let rl = report.components.iter().find(|c| c.name == "request_logger").unwrap();
        assert_eq!(rl.status, HealthStatus::Healthy);
        assert!(rl.message.is_none());
    }

    #[test]
    fn api_keys_degraded_when_all_revoked() {
        let mut input = sample_input();
        input.api_keys_active = 0;
        input.api_keys_total = 3;
        let report = evaluate(&input);
        let ak = report.components.iter().find(|c| c.name == "api_keys").unwrap();
        assert_eq!(ak.status, HealthStatus::Degraded);
        assert!(ak.message.as_ref().unwrap().contains("all keys revoked"));
    }

    #[test]
    fn api_keys_healthy_when_disabled() {
        let mut input = sample_input();
        input.api_keys_enabled = false;
        input.api_keys_active = 0;
        input.api_keys_total = 0;
        let report = evaluate(&input);
        let ak = report.components.iter().find(|c| c.name == "api_keys").unwrap();
        assert_eq!(ak.status, HealthStatus::Healthy);
    }

    #[test]
    fn webhooks_degraded_when_many_failures() {
        let mut input = sample_input();
        input.webhooks_total = 2;
        input.webhooks_total_failures = 20; // > 2*5 = 10
        let report = evaluate(&input);
        let wh = report.components.iter().find(|c| c.name == "webhooks").unwrap();
        assert_eq!(wh.status, HealthStatus::Degraded);
        assert!(wh.message.as_ref().unwrap().contains("20 delivery failures"));
    }

    #[test]
    fn webhooks_healthy_with_low_failures() {
        let report = evaluate(&sample_input());
        let wh = report.components.iter().find(|c| c.name == "webhooks").unwrap();
        assert_eq!(wh.status, HealthStatus::Healthy);
    }

    #[test]
    fn audit_log_details() {
        let report = evaluate(&sample_input());
        let al = report.components.iter().find(|c| c.name == "audit_log").unwrap();
        assert_eq!(al.status, HealthStatus::Healthy);
        let d = al.details.as_ref().unwrap();
        assert_eq!(d["buffered_entries"], 100);
        assert_eq!(d["total_recorded"], 150);
    }
}
