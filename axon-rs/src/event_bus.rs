//! Event Bus + Daemon Supervisor — reactive infrastructure for AxonServer.
//!
//! Provides an in-process publish/subscribe event bus that daemons use to
//! communicate, plus a supervisor that monitors daemon health and manages
//! lifecycle transitions (Idle → Running → Hibernating → Crashed).
//!
//! Architecture:
//!   - `EventBus` — channel-based pub/sub with topic filtering.
//!   - `Event` — typed envelope: topic + payload + metadata.
//!   - `Subscription` — filtered receiver bound to a daemon.
//!   - `DaemonSupervisor` — health monitor with restart policy.
//!
//! The bus uses `tokio::sync::broadcast` for fan-out delivery:
//! every subscriber gets every event, filtering by topic on receive.

use std::collections::HashMap;
use std::fmt;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ── Event types ──────────────────────────────────────────────────────────

/// A typed event envelope flowing through the bus.
#[derive(Debug, Clone)]
pub struct Event {
    /// Topic name for routing (e.g., "deploy", "daemon.started", "flow.complete").
    pub topic: String,
    /// JSON payload — arbitrary structured data.
    pub payload: serde_json::Value,
    /// Source daemon or system component that emitted the event.
    pub source: String,
    /// Monotonic timestamp (elapsed since bus creation).
    pub timestamp: Duration,
}

impl fmt::Display for Event {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[{}] {} → {}", self.source, self.topic, self.payload)
    }
}

/// A subscription filter for topic-based routing.
#[derive(Debug, Clone)]
pub struct TopicFilter {
    /// Exact topic match, or prefix match if ends with ".*".
    pub pattern: String,
}

impl TopicFilter {
    pub fn new(pattern: &str) -> Self {
        TopicFilter {
            pattern: pattern.to_string(),
        }
    }

    /// Check if an event topic matches this filter.
    pub fn matches(&self, topic: &str) -> bool {
        if self.pattern == "*" {
            return true;
        }
        if let Some(prefix) = self.pattern.strip_suffix(".*") {
            topic.starts_with(prefix) && (topic.len() == prefix.len() || topic.as_bytes()[prefix.len()] == b'.')
        } else {
            self.pattern == topic
        }
    }
}

// ── Event Bus ────────────────────────────────────────────────────────────

/// Capacity of the broadcast channel (events buffered before oldest dropped).
const BUS_CAPACITY: usize = 1024;

/// In-process publish/subscribe event bus.
///
/// Uses `tokio::sync::broadcast` for fan-out. Each subscriber receives all
/// events and filters locally by topic. This is efficient for the expected
/// daemon count (tens, not thousands).
#[derive(Clone)]
pub struct EventBus {
    sender: tokio::sync::broadcast::Sender<Event>,
    created_at: Instant,
    stats: Arc<Mutex<BusStats>>,
}

/// Aggregate bus statistics.
#[derive(Debug, Clone, Default)]
pub struct BusStats {
    pub events_published: u64,
    pub events_delivered: u64,
    pub events_dropped: u64,
    pub active_subscribers: u32,
    pub topics_seen: Vec<String>,
    /// Per-topic publish counts.
    pub topic_publish_counts: HashMap<String, u64>,
    /// Recent event history (ring buffer, max 200).
    pub event_history: Vec<EventRecord>,
}

/// A recorded event for history/replay purposes.
#[derive(Debug, Clone)]
pub struct EventRecord {
    /// Topic name.
    pub topic: String,
    /// JSON payload.
    pub payload: serde_json::Value,
    /// Source.
    pub source: String,
    /// Wall-clock timestamp (Unix seconds).
    pub timestamp_secs: u64,
}

impl EventBus {
    /// Create a new event bus.
    pub fn new() -> Self {
        let (sender, _) = tokio::sync::broadcast::channel(BUS_CAPACITY);
        EventBus {
            sender,
            created_at: Instant::now(),
            stats: Arc::new(Mutex::new(BusStats::default())),
        }
    }

    /// Publish an event to all subscribers.
    pub fn publish(&self, topic: &str, payload: serde_json::Value, source: &str) -> Event {
        let event = Event {
            topic: topic.to_string(),
            payload,
            source: source.to_string(),
            timestamp: self.created_at.elapsed(),
        };

        {
            let mut stats = self.stats.lock().unwrap();
            stats.events_published += 1;
            if !stats.topics_seen.contains(&event.topic) {
                stats.topics_seen.push(event.topic.clone());
            }
            *stats.topic_publish_counts.entry(event.topic.clone()).or_insert(0) += 1;
            stats.event_history.push(EventRecord {
                topic: event.topic.clone(),
                payload: event.payload.clone(),
                source: event.source.clone(),
                timestamp_secs: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs(),
            });
            if stats.event_history.len() > 200 {
                stats.event_history.remove(0);
            }
        }

        // Send to all receivers; if none exist, event is silently dropped.
        let _ = self.sender.send(event.clone());
        event
    }

    /// Get recent event history, optionally filtered by topic.
    pub fn recent_events(&self, limit: usize, topic_filter: Option<&str>) -> Vec<EventRecord> {
        let stats = self.stats.lock().unwrap();
        stats.event_history.iter().rev()
            .filter(|e| match topic_filter {
                Some(t) => e.topic == t || t == "*" || (t.ends_with(".*") && e.topic.starts_with(&t[..t.len()-2])),
                None => true,
            })
            .take(limit)
            .cloned()
            .collect()
    }

    /// Create a subscription filtered by topic pattern.
    pub fn subscribe(&self, filter: TopicFilter) -> Subscription {
        let receiver = self.sender.subscribe();

        {
            let mut stats = self.stats.lock().unwrap();
            stats.active_subscribers += 1;
        }

        Subscription {
            receiver,
            filter,
            bus_stats: Arc::clone(&self.stats),
        }
    }

    /// Get current bus statistics.
    pub fn stats(&self) -> BusStats {
        self.stats.lock().unwrap().clone()
    }

    /// Number of active subscribers.
    pub fn subscriber_count(&self) -> usize {
        self.sender.receiver_count()
    }
}

/// A filtered subscription that receives events matching a topic pattern.
pub struct Subscription {
    receiver: tokio::sync::broadcast::Receiver<Event>,
    filter: TopicFilter,
    bus_stats: Arc<Mutex<BusStats>>,
}

impl Subscription {
    /// Receive the next matching event (async, blocks until available).
    pub async fn recv(&mut self) -> Result<Event, SubscriptionError> {
        loop {
            match self.receiver.recv().await {
                Ok(event) => {
                    if self.filter.matches(&event.topic) {
                        let mut stats = self.bus_stats.lock().unwrap();
                        stats.events_delivered += 1;
                        return Ok(event);
                    }
                    // Non-matching event — continue waiting.
                }
                Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                    let mut stats = self.bus_stats.lock().unwrap();
                    stats.events_dropped += n;
                    // Continue receiving — some events were missed.
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                    return Err(SubscriptionError::BusClosed);
                }
            }
        }
    }

    /// Try to receive a matching event without blocking.
    pub fn try_recv(&mut self) -> Result<Option<Event>, SubscriptionError> {
        loop {
            match self.receiver.try_recv() {
                Ok(event) => {
                    if self.filter.matches(&event.topic) {
                        let mut stats = self.bus_stats.lock().unwrap();
                        stats.events_delivered += 1;
                        return Ok(Some(event));
                    }
                    // Non-matching — try next.
                }
                Err(tokio::sync::broadcast::error::TryRecvError::Empty) => {
                    return Ok(None);
                }
                Err(tokio::sync::broadcast::error::TryRecvError::Lagged(n)) => {
                    let mut stats = self.bus_stats.lock().unwrap();
                    stats.events_dropped += n;
                    // Continue — try next available.
                }
                Err(tokio::sync::broadcast::error::TryRecvError::Closed) => {
                    return Err(SubscriptionError::BusClosed);
                }
            }
        }
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        let mut stats = self.bus_stats.lock().unwrap();
        stats.active_subscribers = stats.active_subscribers.saturating_sub(1);
    }
}

/// Errors from subscription operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubscriptionError {
    /// The event bus has been dropped (server shutting down).
    BusClosed,
}

impl fmt::Display for SubscriptionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SubscriptionError::BusClosed => write!(f, "event bus closed"),
        }
    }
}

// ── Daemon Supervisor ────────────────────────────────────────────────────

/// Restart policy for supervised daemons.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RestartPolicy {
    /// Never restart on crash.
    Never,
    /// Restart up to N times, then give up.
    OnCrash { max_restarts: u32 },
    /// Always restart (with exponential backoff).
    Always,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        RestartPolicy::OnCrash { max_restarts: 3 }
    }
}

/// A supervised daemon entry tracked by the supervisor.
#[derive(Debug, Clone, serde::Serialize)]
pub struct SupervisedDaemon {
    pub name: String,
    pub state: SupervisorState,
    pub restart_policy: RestartPolicy,
    pub restart_count: u32,
    pub last_heartbeat: Option<Duration>,
    pub crash_reason: Option<String>,
    pub uptime: Duration,
}

/// Supervisor-level daemon state (more granular than DaemonState).
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SupervisorState {
    /// Registered but not started.
    Registered,
    /// Actively running.
    Running,
    /// Waiting for an event (hibernating).
    Waiting,
    /// Restarting after a crash.
    Restarting,
    /// Stopped normally.
    Stopped,
    /// Crashed and won't be restarted (policy exhausted).
    Dead,
}

/// The daemon supervisor: monitors health, enforces restart policies,
/// and emits lifecycle events to the bus.
pub struct DaemonSupervisor {
    daemons: HashMap<String, SupervisedDaemon>,
    bus: EventBus,
    created_at: Instant,
    heartbeat_timeout: Duration,
}

impl DaemonSupervisor {
    /// Create a new supervisor attached to an event bus.
    pub fn new(bus: EventBus) -> Self {
        DaemonSupervisor {
            daemons: HashMap::new(),
            bus,
            created_at: Instant::now(),
            heartbeat_timeout: Duration::from_secs(30),
        }
    }

    /// Register a daemon for supervision with a restart policy.
    pub fn register(&mut self, name: &str, policy: RestartPolicy) {
        let daemon = SupervisedDaemon {
            name: name.to_string(),
            state: SupervisorState::Registered,
            restart_policy: policy,
            restart_count: 0,
            last_heartbeat: None,
            crash_reason: None,
            uptime: Duration::ZERO,
        };
        self.daemons.insert(name.to_string(), daemon);

        self.bus.publish(
            "supervisor.registered",
            serde_json::json!({ "daemon": name }),
            "supervisor",
        );
    }

    /// Mark a daemon as started.
    pub fn mark_started(&mut self, name: &str) -> bool {
        if let Some(d) = self.daemons.get_mut(name) {
            d.state = SupervisorState::Running;
            d.last_heartbeat = Some(self.created_at.elapsed());
            d.uptime = Duration::ZERO;

            self.bus.publish(
                "supervisor.started",
                serde_json::json!({ "daemon": name }),
                "supervisor",
            );
            true
        } else {
            false
        }
    }

    /// Record a heartbeat from a daemon.
    pub fn heartbeat(&mut self, name: &str) -> bool {
        if let Some(d) = self.daemons.get_mut(name) {
            d.last_heartbeat = Some(self.created_at.elapsed());
            true
        } else {
            false
        }
    }

    /// Mark a daemon as waiting for events (hibernating).
    pub fn mark_waiting(&mut self, name: &str) -> bool {
        if let Some(d) = self.daemons.get_mut(name) {
            d.state = SupervisorState::Waiting;

            self.bus.publish(
                "supervisor.waiting",
                serde_json::json!({ "daemon": name }),
                "supervisor",
            );
            true
        } else {
            false
        }
    }

    /// Report that a daemon has crashed. Returns whether it will be restarted.
    pub fn report_crash(&mut self, name: &str, reason: &str) -> bool {
        if let Some(d) = self.daemons.get_mut(name) {
            d.crash_reason = Some(reason.to_string());
            d.restart_count += 1;

            let will_restart = match d.restart_policy {
                RestartPolicy::Never => false,
                RestartPolicy::OnCrash { max_restarts } => d.restart_count <= max_restarts,
                RestartPolicy::Always => true,
            };

            if will_restart {
                d.state = SupervisorState::Restarting;
                self.bus.publish(
                    "supervisor.restarting",
                    serde_json::json!({
                        "daemon": name,
                        "reason": reason,
                        "restart_count": d.restart_count,
                    }),
                    "supervisor",
                );
            } else {
                d.state = SupervisorState::Dead;
                self.bus.publish(
                    "supervisor.dead",
                    serde_json::json!({
                        "daemon": name,
                        "reason": reason,
                        "restart_count": d.restart_count,
                    }),
                    "supervisor",
                );
            }

            will_restart
        } else {
            false
        }
    }

    /// Stop a daemon normally.
    pub fn stop(&mut self, name: &str) -> bool {
        if let Some(d) = self.daemons.get_mut(name) {
            d.state = SupervisorState::Stopped;

            self.bus.publish(
                "supervisor.stopped",
                serde_json::json!({ "daemon": name }),
                "supervisor",
            );
            true
        } else {
            false
        }
    }

    /// Remove a daemon from supervision.
    pub fn unregister(&mut self, name: &str) -> bool {
        if self.daemons.remove(name).is_some() {
            self.bus.publish(
                "supervisor.unregistered",
                serde_json::json!({ "daemon": name }),
                "supervisor",
            );
            true
        } else {
            false
        }
    }

    /// Get the state of a specific daemon.
    pub fn get(&self, name: &str) -> Option<&SupervisedDaemon> {
        self.daemons.get(name)
    }

    /// List all supervised daemons.
    pub fn list(&self) -> Vec<&SupervisedDaemon> {
        self.daemons.values().collect()
    }

    /// Count daemons in each state.
    pub fn state_counts(&self) -> HashMap<&'static str, usize> {
        let mut counts = HashMap::new();
        for d in self.daemons.values() {
            let key = match d.state {
                SupervisorState::Registered => "registered",
                SupervisorState::Running => "running",
                SupervisorState::Waiting => "waiting",
                SupervisorState::Restarting => "restarting",
                SupervisorState::Stopped => "stopped",
                SupervisorState::Dead => "dead",
            };
            *counts.entry(key).or_insert(0) += 1;
        }
        counts
    }

    /// Check all daemons for stale heartbeats. Returns names of timed-out daemons.
    pub fn check_heartbeats(&mut self) -> Vec<String> {
        let now = self.created_at.elapsed();
        let timeout = self.heartbeat_timeout;
        let mut timed_out = Vec::new();

        let names: Vec<String> = self
            .daemons
            .iter()
            .filter(|(_, d)| d.state == SupervisorState::Running)
            .filter(|(_, d)| {
                d.last_heartbeat
                    .map(|hb| now.saturating_sub(hb) > timeout)
                    .unwrap_or(false)
            })
            .map(|(name, _)| name.clone())
            .collect();

        for name in &names {
            self.report_crash(&name, "heartbeat timeout");
            timed_out.push(name.clone());
        }

        timed_out
    }

    /// Summary string for logging.
    pub fn summary(&self) -> String {
        let counts = self.state_counts();
        let total = self.daemons.len();
        let running = counts.get("running").copied().unwrap_or(0);
        let waiting = counts.get("waiting").copied().unwrap_or(0);
        let dead = counts.get("dead").copied().unwrap_or(0);
        format!(
            "{total} daemons ({running} running, {waiting} waiting, {dead} dead)"
        )
    }
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topic_filter_exact() {
        let f = TopicFilter::new("deploy");
        assert!(f.matches("deploy"));
        assert!(!f.matches("deploy.done"));
        assert!(!f.matches("undeploy"));
    }

    #[test]
    fn topic_filter_wildcard() {
        let f = TopicFilter::new("*");
        assert!(f.matches("deploy"));
        assert!(f.matches("supervisor.started"));
        assert!(f.matches("anything"));
    }

    #[test]
    fn topic_filter_prefix() {
        let f = TopicFilter::new("supervisor.*");
        assert!(f.matches("supervisor.started"));
        assert!(f.matches("supervisor.stopped"));
        assert!(f.matches("supervisor.dead"));
        assert!(!f.matches("deploy"));
        assert!(!f.matches("supervisorx"));
    }

    #[test]
    fn bus_publish_and_stats() {
        let bus = EventBus::new();
        bus.publish("test.event", serde_json::json!({"x": 1}), "test");
        bus.publish("test.event", serde_json::json!({"x": 2}), "test");
        bus.publish("other", serde_json::json!(null), "sys");

        let stats = bus.stats();
        assert_eq!(stats.events_published, 3);
        assert_eq!(stats.topics_seen.len(), 2);
        assert!(stats.topics_seen.contains(&"test.event".to_string()));
        assert!(stats.topics_seen.contains(&"other".to_string()));
    }

    #[tokio::test]
    async fn bus_subscribe_and_recv() {
        let bus = EventBus::new();
        let mut sub = bus.subscribe(TopicFilter::new("hello"));

        bus.publish("hello", serde_json::json!({"msg": "world"}), "test");
        bus.publish("ignore", serde_json::json!(null), "test");
        bus.publish("hello", serde_json::json!({"msg": "again"}), "test");

        let e1 = sub.try_recv().unwrap().unwrap();
        assert_eq!(e1.topic, "hello");
        assert_eq!(e1.payload["msg"], "world");

        let e2 = sub.try_recv().unwrap().unwrap();
        assert_eq!(e2.payload["msg"], "again");

        // No more matching events
        assert!(sub.try_recv().unwrap().is_none());
    }

    #[test]
    fn bus_subscriber_count() {
        let bus = EventBus::new();
        assert_eq!(bus.subscriber_count(), 0);

        let _sub1 = bus.subscribe(TopicFilter::new("*"));
        assert_eq!(bus.subscriber_count(), 1);

        let _sub2 = bus.subscribe(TopicFilter::new("deploy"));
        assert_eq!(bus.subscriber_count(), 2);

        drop(_sub1);
        assert_eq!(bus.subscriber_count(), 1);
    }

    #[test]
    fn supervisor_register_and_lifecycle() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("flow_a", RestartPolicy::default());
        assert_eq!(sup.get("flow_a").unwrap().state, SupervisorState::Registered);

        sup.mark_started("flow_a");
        assert_eq!(sup.get("flow_a").unwrap().state, SupervisorState::Running);

        sup.mark_waiting("flow_a");
        assert_eq!(sup.get("flow_a").unwrap().state, SupervisorState::Waiting);

        sup.stop("flow_a");
        assert_eq!(sup.get("flow_a").unwrap().state, SupervisorState::Stopped);
    }

    #[test]
    fn supervisor_crash_restart_policy() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        // OnCrash { max_restarts: 2 }
        sup.register("flow_b", RestartPolicy::OnCrash { max_restarts: 2 });
        sup.mark_started("flow_b");

        // First crash → restart
        assert!(sup.report_crash("flow_b", "panic"));
        assert_eq!(sup.get("flow_b").unwrap().state, SupervisorState::Restarting);

        // Second crash → restart
        sup.mark_started("flow_b");
        assert!(sup.report_crash("flow_b", "panic again"));
        assert_eq!(sup.get("flow_b").unwrap().state, SupervisorState::Restarting);

        // Third crash → dead (exceeded max_restarts=2)
        sup.mark_started("flow_b");
        assert!(!sup.report_crash("flow_b", "fatal"));
        assert_eq!(sup.get("flow_b").unwrap().state, SupervisorState::Dead);
        assert_eq!(sup.get("flow_b").unwrap().restart_count, 3);
    }

    #[test]
    fn supervisor_never_restart() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("ephemeral", RestartPolicy::Never);
        sup.mark_started("ephemeral");

        assert!(!sup.report_crash("ephemeral", "one shot"));
        assert_eq!(sup.get("ephemeral").unwrap().state, SupervisorState::Dead);
    }

    #[test]
    fn supervisor_always_restart() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("immortal", RestartPolicy::Always);
        sup.mark_started("immortal");

        for i in 0..10 {
            assert!(sup.report_crash("immortal", &format!("crash {i}")));
            assert_eq!(sup.get("immortal").unwrap().state, SupervisorState::Restarting);
            sup.mark_started("immortal");
        }
        assert_eq!(sup.get("immortal").unwrap().restart_count, 10);
    }

    #[test]
    fn supervisor_unregister() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("temp", RestartPolicy::Never);
        assert!(sup.unregister("temp"));
        assert!(sup.get("temp").is_none());
        assert!(!sup.unregister("temp")); // Already gone
    }

    #[test]
    fn supervisor_state_counts() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("a", RestartPolicy::Never);
        sup.register("b", RestartPolicy::Never);
        sup.register("c", RestartPolicy::Never);

        sup.mark_started("a");
        sup.mark_started("b");
        sup.mark_waiting("c");

        let counts = sup.state_counts();
        assert_eq!(counts.get("running"), Some(&2));
        assert_eq!(counts.get("waiting"), Some(&1));
    }

    #[test]
    fn supervisor_summary() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("x", RestartPolicy::Never);
        sup.register("y", RestartPolicy::Never);
        sup.mark_started("x");

        let s = sup.summary();
        assert!(s.contains("2 daemons"));
        assert!(s.contains("1 running"));
    }

    #[test]
    fn supervisor_heartbeat_timeout() {
        let bus = EventBus::new();
        let mut sup = DaemonSupervisor::new(bus);
        // Set a very short timeout for testing
        sup.heartbeat_timeout = Duration::from_millis(1);

        sup.register("slow", RestartPolicy::OnCrash { max_restarts: 1 });
        sup.mark_started("slow");

        // Simulate time passing by setting heartbeat in the past
        // (heartbeat was set by mark_started, so it's "now")
        // We need to wait just a tiny bit for the timeout to trigger
        std::thread::sleep(Duration::from_millis(5));

        let timed_out = sup.check_heartbeats();
        assert_eq!(timed_out, vec!["slow"]);
        assert_eq!(sup.get("slow").unwrap().state, SupervisorState::Restarting);
    }

    #[test]
    fn event_display() {
        let event = Event {
            topic: "deploy".to_string(),
            payload: serde_json::json!({"flow": "TestFlow"}),
            source: "client".to_string(),
            timestamp: Duration::from_secs(5),
        };
        let s = format!("{event}");
        assert!(s.contains("client"));
        assert!(s.contains("deploy"));
    }

    #[test]
    fn supervisor_emits_lifecycle_events() {
        let bus = EventBus::new();
        let mut sub = bus.subscribe(TopicFilter::new("supervisor.*"));
        let mut sup = DaemonSupervisor::new(bus);

        sup.register("d1", RestartPolicy::Never);
        sup.mark_started("d1");
        sup.stop("d1");

        // Should have received: registered, started, stopped
        let e1 = sub.try_recv().unwrap().unwrap();
        assert_eq!(e1.topic, "supervisor.registered");

        let e2 = sub.try_recv().unwrap().unwrap();
        assert_eq!(e2.topic, "supervisor.started");

        let e3 = sub.try_recv().unwrap().unwrap();
        assert_eq!(e3.topic, "supervisor.stopped");

        assert!(sub.try_recv().unwrap().is_none());
    }
}
