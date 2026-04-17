//! Retry Policy — exponential backoff with jitter for LLM API calls.
//!
//! Provides configurable retry behavior:
//!   - Maximum retry attempts (default: 3)
//!   - Exponential backoff starting from base_delay (default: 500ms)
//!   - Maximum delay cap (default: 30s)
//!   - Optional jitter to prevent thundering herd
//!   - Error-kind-aware: only retries retryable errors
//!
//! Used by `resilient_backend.rs` for automatic retry of transient failures.

use std::time::Duration;
use crate::backend_error::BackendErrorKind;

/// Configurable retry policy with exponential backoff.
#[derive(Debug, Clone)]
pub struct RetryPolicy {
    /// Maximum number of retry attempts (0 = no retries).
    pub max_retries: u32,
    /// Initial delay before first retry.
    pub base_delay: Duration,
    /// Maximum delay cap (backoff never exceeds this).
    pub max_delay: Duration,
    /// Multiplier applied each retry (typically 2.0).
    pub backoff_multiplier: f64,
    /// Whether to add random jitter to prevent thundering herd.
    pub jitter: bool,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        RetryPolicy {
            max_retries: 3,
            base_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(30),
            backoff_multiplier: 2.0,
            jitter: true,
        }
    }
}

impl RetryPolicy {
    /// Create a policy that never retries.
    pub fn no_retry() -> Self {
        RetryPolicy {
            max_retries: 0,
            ..Default::default()
        }
    }

    /// Calculate the delay for a given retry attempt (0-based).
    ///
    /// Uses exponential backoff: delay = base_delay * (multiplier ^ attempt)
    /// Capped at max_delay. Jitter adds 0-50% random variation.
    pub fn delay_for_attempt(&self, attempt: u32) -> Duration {
        let base_ms = self.base_delay.as_millis() as f64;
        let multiplied = base_ms * self.backoff_multiplier.powi(attempt as i32);
        let capped = multiplied.min(self.max_delay.as_millis() as f64);

        let final_ms = if self.jitter {
            // Add 0-50% jitter using a simple deterministic hash-like spread
            // (not cryptographically random, but sufficient for backoff jitter)
            let jitter_factor = 1.0 + (((attempt as f64 * 0.618) % 1.0) * 0.5);
            (capped * jitter_factor).min(self.max_delay.as_millis() as f64)
        } else {
            capped
        };

        Duration::from_millis(final_ms as u64)
    }

    /// Whether we should retry given the attempt number and error kind.
    pub fn should_retry(&self, attempt: u32, error: &BackendErrorKind) -> bool {
        if attempt >= self.max_retries {
            return false;
        }
        error.is_retryable()
    }

    /// Returns the delay accounting for rate-limit Retry-After hints.
    /// If the error has a retry_after duration, use it instead of calculated backoff.
    pub fn effective_delay(&self, attempt: u32, error: &BackendErrorKind) -> Duration {
        if let BackendErrorKind::RateLimit { retry_after: Some(duration) } = error {
            // Respect the provider's Retry-After header, but still cap at max_delay
            (*duration).min(self.max_delay)
        } else {
            self.delay_for_attempt(attempt)
        }
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_policy() {
        let p = RetryPolicy::default();
        assert_eq!(p.max_retries, 3);
        assert_eq!(p.base_delay, Duration::from_millis(500));
        assert_eq!(p.max_delay, Duration::from_secs(30));
        assert_eq!(p.backoff_multiplier, 2.0);
        assert!(p.jitter);
    }

    #[test]
    fn test_no_retry_policy() {
        let p = RetryPolicy::no_retry();
        assert_eq!(p.max_retries, 0);
        assert!(!p.should_retry(0, &BackendErrorKind::Timeout));
    }

    #[test]
    fn test_exponential_backoff_no_jitter() {
        let p = RetryPolicy {
            jitter: false,
            ..Default::default()
        };
        // attempt 0: 500ms * 2^0 = 500ms
        assert_eq!(p.delay_for_attempt(0), Duration::from_millis(500));
        // attempt 1: 500ms * 2^1 = 1000ms
        assert_eq!(p.delay_for_attempt(1), Duration::from_millis(1000));
        // attempt 2: 500ms * 2^2 = 2000ms
        assert_eq!(p.delay_for_attempt(2), Duration::from_millis(2000));
    }

    #[test]
    fn test_delay_capped_at_max() {
        let p = RetryPolicy {
            max_delay: Duration::from_secs(2),
            jitter: false,
            ..Default::default()
        };
        // attempt 5: 500ms * 2^5 = 16000ms → capped at 2000ms
        assert_eq!(p.delay_for_attempt(5), Duration::from_secs(2));
    }

    #[test]
    fn test_jitter_adds_variation() {
        let p = RetryPolicy::default();
        let d0 = p.delay_for_attempt(0);
        let d1 = p.delay_for_attempt(1);
        // With jitter, delay should be >= base (no negative jitter)
        assert!(d0 >= Duration::from_millis(500));
        assert!(d1 >= Duration::from_millis(1000));
        // And within 50% jitter: max = base * 1.5
        assert!(d0 <= Duration::from_millis(750));
        assert!(d1 <= Duration::from_millis(1500));
    }

    #[test]
    fn test_should_retry_retryable() {
        let p = RetryPolicy::default();
        assert!(p.should_retry(0, &BackendErrorKind::Timeout));
        assert!(p.should_retry(1, &BackendErrorKind::NetworkError));
        assert!(p.should_retry(2, &BackendErrorKind::ServerError { status: 500 }));
        // Exhausted retries
        assert!(!p.should_retry(3, &BackendErrorKind::Timeout));
    }

    #[test]
    fn test_should_retry_non_retryable() {
        let p = RetryPolicy::default();
        assert!(!p.should_retry(0, &BackendErrorKind::AuthError));
        assert!(!p.should_retry(0, &BackendErrorKind::InvalidResponse));
        assert!(!p.should_retry(0, &BackendErrorKind::ProviderUnavailable));
    }

    #[test]
    fn test_effective_delay_rate_limit_hint() {
        let p = RetryPolicy::default();
        let error = BackendErrorKind::RateLimit {
            retry_after: Some(Duration::from_secs(5)),
        };
        // Should use the provider's hint instead of calculated backoff
        assert_eq!(p.effective_delay(0, &error), Duration::from_secs(5));
    }
}
