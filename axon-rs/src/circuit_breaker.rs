//! Circuit Breaker — per-provider failure protection for LLM API calls.
//!
//! State machine with three states:
//!   - **Closed**: Normal operation. Failures increment a counter.
//!     After `failure_threshold` consecutive failures → transitions to Open.
//!   - **Open**: All calls are immediately rejected (fail fast).
//!     After `cooldown` duration → transitions to HalfOpen.
//!   - **HalfOpen**: Allows a limited number of probe calls.
//!     If `success_threshold` successes → transitions to Closed.
//!     Any failure → transitions back to Open.
//!
//! Each LLM provider gets its own `CircuitBreaker` instance.

use std::time::{Duration, Instant};

/// Circuit breaker state.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CircuitState {
    /// Normal operation — calls pass through.
    Closed,
    /// Calls are rejected — too many recent failures.
    Open,
    /// Probing — allowing limited calls to test recovery.
    HalfOpen,
}

impl std::fmt::Display for CircuitState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CircuitState::Closed => write!(f, "closed"),
            CircuitState::Open => write!(f, "open"),
            CircuitState::HalfOpen => write!(f, "half_open"),
        }
    }
}

/// Per-provider circuit breaker.
#[derive(Debug)]
pub struct CircuitBreaker {
    state: CircuitState,
    /// Consecutive failure count.
    failure_count: u32,
    /// Consecutive success count in half-open state.
    success_count: u32,
    /// Number of failures to trigger open state.
    failure_threshold: u32,
    /// Number of successes in half-open to close the circuit.
    success_threshold: u32,
    /// How long to wait in open state before probing.
    cooldown: Duration,
    /// When the circuit was last opened.
    last_opened_at: Option<Instant>,
    /// Provider name for logging.
    provider: String,
    /// Total number of times the circuit has opened.
    total_opens: u64,
}

impl CircuitBreaker {
    /// Create a new circuit breaker with the given thresholds.
    pub fn new(provider: &str, failure_threshold: u32, success_threshold: u32, cooldown: Duration) -> Self {
        CircuitBreaker {
            state: CircuitState::Closed,
            failure_count: 0,
            success_count: 0,
            failure_threshold,
            success_threshold,
            cooldown,
            last_opened_at: None,
            provider: provider.to_string(),
            total_opens: 0,
        }
    }

    /// Create a circuit breaker with sensible defaults.
    pub fn with_defaults(provider: &str) -> Self {
        Self::new(provider, 5, 2, Duration::from_secs(30))
    }

    /// Check if a call is allowed. Transitions Open→HalfOpen if cooldown elapsed.
    pub fn can_execute(&mut self) -> bool {
        match self.state {
            CircuitState::Closed => true,
            CircuitState::HalfOpen => true,
            CircuitState::Open => {
                // Check if cooldown has elapsed
                if let Some(opened_at) = self.last_opened_at {
                    if opened_at.elapsed() >= self.cooldown {
                        self.state = CircuitState::HalfOpen;
                        self.success_count = 0;
                        tracing::info!(
                            provider = %self.provider,
                            state = "half_open",
                            "circuit_breaker_transition"
                        );
                        true
                    } else {
                        false
                    }
                } else {
                    false
                }
            }
        }
    }

    /// Record a successful call.
    pub fn record_success(&mut self) {
        match self.state {
            CircuitState::Closed => {
                // Reset failure count on success
                self.failure_count = 0;
            }
            CircuitState::HalfOpen => {
                self.success_count += 1;
                if self.success_count >= self.success_threshold {
                    self.state = CircuitState::Closed;
                    self.failure_count = 0;
                    self.success_count = 0;
                    tracing::info!(
                        provider = %self.provider,
                        state = "closed",
                        "circuit_breaker_transition"
                    );
                }
            }
            CircuitState::Open => {
                // Should not happen — calls are rejected when open
            }
        }
    }

    /// Record a failed call.
    pub fn record_failure(&mut self) {
        match self.state {
            CircuitState::Closed => {
                self.failure_count += 1;
                if self.failure_count >= self.failure_threshold {
                    self.state = CircuitState::Open;
                    self.last_opened_at = Some(Instant::now());
                    self.total_opens += 1;
                    tracing::warn!(
                        provider = %self.provider,
                        state = "open",
                        failure_count = self.failure_count,
                        total_opens = self.total_opens,
                        "circuit_breaker_transition"
                    );
                }
            }
            CircuitState::HalfOpen => {
                // Any failure in half-open → back to open
                self.state = CircuitState::Open;
                self.last_opened_at = Some(Instant::now());
                self.success_count = 0;
                self.total_opens += 1;
                tracing::warn!(
                    provider = %self.provider,
                    state = "open",
                    reason = "half_open_failure",
                    total_opens = self.total_opens,
                    "circuit_breaker_transition"
                );
            }
            CircuitState::Open => {
                // Already open — no-op
            }
        }
    }

    /// Current state.
    pub fn state(&self) -> CircuitState {
        self.state
    }

    /// Provider name.
    pub fn provider(&self) -> &str {
        &self.provider
    }

    /// Manually reset the circuit to closed state.
    pub fn reset(&mut self) {
        self.state = CircuitState::Closed;
        self.failure_count = 0;
        self.success_count = 0;
        self.last_opened_at = None;
    }

    /// Total number of times this circuit has opened.
    pub fn total_opens(&self) -> u64 {
        self.total_opens
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_initial_state_is_closed() {
        let cb = CircuitBreaker::with_defaults("test");
        assert_eq!(cb.state(), CircuitState::Closed);
        assert_eq!(cb.total_opens(), 0);
    }

    #[test]
    fn test_success_resets_failure_count() {
        let mut cb = CircuitBreaker::with_defaults("test");
        cb.record_failure();
        cb.record_failure();
        cb.record_success();
        // After success, failure count resets — 5 more failures needed
        for _ in 0..4 {
            cb.record_failure();
        }
        assert_eq!(cb.state(), CircuitState::Closed);
    }

    #[test]
    fn test_opens_after_threshold() {
        let mut cb = CircuitBreaker::new("test", 3, 2, Duration::from_secs(30));
        assert!(cb.can_execute());
        cb.record_failure();
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Closed);
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert_eq!(cb.total_opens(), 1);
    }

    #[test]
    fn test_open_rejects_calls() {
        let mut cb = CircuitBreaker::new("test", 2, 1, Duration::from_secs(60));
        cb.record_failure();
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert!(!cb.can_execute());
    }

    #[test]
    fn test_half_open_after_cooldown() {
        let mut cb = CircuitBreaker::new("test", 2, 1, Duration::from_millis(10));
        cb.record_failure();
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);

        // Wait for cooldown
        std::thread::sleep(Duration::from_millis(15));

        assert!(cb.can_execute());
        assert_eq!(cb.state(), CircuitState::HalfOpen);
    }

    #[test]
    fn test_half_open_to_closed_on_success() {
        let mut cb = CircuitBreaker::new("test", 2, 2, Duration::from_millis(10));
        cb.record_failure();
        cb.record_failure();

        std::thread::sleep(Duration::from_millis(15));
        cb.can_execute(); // Transition to HalfOpen

        cb.record_success();
        assert_eq!(cb.state(), CircuitState::HalfOpen);
        cb.record_success();
        assert_eq!(cb.state(), CircuitState::Closed);
    }

    #[test]
    fn test_half_open_to_open_on_failure() {
        let mut cb = CircuitBreaker::new("test", 2, 2, Duration::from_millis(10));
        cb.record_failure();
        cb.record_failure();

        std::thread::sleep(Duration::from_millis(15));
        cb.can_execute(); // Transition to HalfOpen

        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert_eq!(cb.total_opens(), 2);
    }

    #[test]
    fn test_reset() {
        let mut cb = CircuitBreaker::new("test", 2, 1, Duration::from_secs(60));
        cb.record_failure();
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);

        cb.reset();
        assert_eq!(cb.state(), CircuitState::Closed);
        assert!(cb.can_execute());
    }

    #[test]
    fn test_can_execute_closed() {
        let mut cb = CircuitBreaker::with_defaults("test");
        assert!(cb.can_execute());
    }

    #[test]
    fn test_display_state() {
        assert_eq!(format!("{}", CircuitState::Closed), "closed");
        assert_eq!(format!("{}", CircuitState::Open), "open");
        assert_eq!(format!("{}", CircuitState::HalfOpen), "half_open");
    }
}
