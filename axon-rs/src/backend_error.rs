//! Backend Error Classification — structured error types for LLM API calls.
//!
//! Provides `BackendErrorKind` enum that classifies API errors into categories
//! enabling retry/circuit-breaker decisions:
//!   - Retryable: Timeout, RateLimit, ServerError (5xx), NetworkError, StreamDropped
//!   - Non-retryable: AuthError, InvalidResponse, ProviderUnavailable
//!
//! Used by `resilient_backend.rs` to determine whether to retry a failed call.

use std::time::Duration;

/// Classification of backend API errors.
#[derive(Debug, Clone)]
pub enum BackendErrorKind {
    /// Request timed out (connect or read timeout).
    Timeout,
    /// Provider returned 429 Too Many Requests.
    RateLimit {
        /// Hint from the provider's Retry-After header, if present.
        retry_after: Option<Duration>,
    },
    /// Provider returned a server error (5xx).
    ServerError { status: u16 },
    /// Authentication failed (401/403) — API key invalid or expired.
    AuthError,
    /// Network-level error (DNS, connection refused, TLS, etc.).
    NetworkError,
    /// SSE stream dropped mid-response.
    StreamDropped,
    /// Provider response could not be parsed.
    InvalidResponse,
    /// Provider is unknown or not registered.
    ProviderUnavailable,
    /// Circuit breaker is open — calls are being rejected.
    CircuitOpen,
    /// Unclassified error.
    Unknown,
}

impl BackendErrorKind {
    /// Whether this error type is worth retrying.
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            BackendErrorKind::Timeout
                | BackendErrorKind::RateLimit { .. }
                | BackendErrorKind::ServerError { .. }
                | BackendErrorKind::NetworkError
                | BackendErrorKind::StreamDropped
        )
    }

    /// Human-readable error category for logging.
    pub fn category(&self) -> &'static str {
        match self {
            BackendErrorKind::Timeout => "timeout",
            BackendErrorKind::RateLimit { .. } => "rate_limit",
            BackendErrorKind::ServerError { .. } => "server_error",
            BackendErrorKind::AuthError => "auth_error",
            BackendErrorKind::NetworkError => "network_error",
            BackendErrorKind::StreamDropped => "stream_dropped",
            BackendErrorKind::InvalidResponse => "invalid_response",
            BackendErrorKind::ProviderUnavailable => "provider_unavailable",
            BackendErrorKind::CircuitOpen => "circuit_open",
            BackendErrorKind::Unknown => "unknown",
        }
    }

    /// Classify an HTTP status code into an error kind.
    pub fn from_status(status: u16) -> Self {
        match status {
            401 | 403 => BackendErrorKind::AuthError,
            429 => BackendErrorKind::RateLimit { retry_after: None },
            408 => BackendErrorKind::Timeout,
            s if s >= 500 => BackendErrorKind::ServerError { status: s },
            _ => BackendErrorKind::Unknown,
        }
    }

    /// Classify a reqwest error into an error kind.
    pub fn from_reqwest_error(e: &reqwest::Error) -> Self {
        if e.is_timeout() {
            BackendErrorKind::Timeout
        } else if e.is_connect() {
            BackendErrorKind::NetworkError
        } else if e.is_request() {
            BackendErrorKind::NetworkError
        } else if let Some(status) = e.status() {
            BackendErrorKind::from_status(status.as_u16())
        } else {
            BackendErrorKind::NetworkError
        }
    }
}

impl std::fmt::Display for BackendErrorKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.category())
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_retryable_errors() {
        assert!(BackendErrorKind::Timeout.is_retryable());
        assert!(BackendErrorKind::RateLimit { retry_after: None }.is_retryable());
        assert!(BackendErrorKind::ServerError { status: 500 }.is_retryable());
        assert!(BackendErrorKind::ServerError { status: 503 }.is_retryable());
        assert!(BackendErrorKind::NetworkError.is_retryable());
        assert!(BackendErrorKind::StreamDropped.is_retryable());
    }

    #[test]
    fn test_non_retryable_errors() {
        assert!(!BackendErrorKind::AuthError.is_retryable());
        assert!(!BackendErrorKind::InvalidResponse.is_retryable());
        assert!(!BackendErrorKind::ProviderUnavailable.is_retryable());
        assert!(!BackendErrorKind::CircuitOpen.is_retryable());
        assert!(!BackendErrorKind::Unknown.is_retryable());
    }

    #[test]
    fn test_from_status_classification() {
        assert!(matches!(BackendErrorKind::from_status(401), BackendErrorKind::AuthError));
        assert!(matches!(BackendErrorKind::from_status(403), BackendErrorKind::AuthError));
        assert!(matches!(BackendErrorKind::from_status(429), BackendErrorKind::RateLimit { .. }));
        assert!(matches!(BackendErrorKind::from_status(408), BackendErrorKind::Timeout));
        assert!(matches!(BackendErrorKind::from_status(500), BackendErrorKind::ServerError { status: 500 }));
        assert!(matches!(BackendErrorKind::from_status(502), BackendErrorKind::ServerError { status: 502 }));
        assert!(matches!(BackendErrorKind::from_status(503), BackendErrorKind::ServerError { status: 503 }));
        assert!(matches!(BackendErrorKind::from_status(400), BackendErrorKind::Unknown));
        assert!(matches!(BackendErrorKind::from_status(404), BackendErrorKind::Unknown));
    }

    #[test]
    fn test_category_strings() {
        assert_eq!(BackendErrorKind::Timeout.category(), "timeout");
        assert_eq!(BackendErrorKind::RateLimit { retry_after: None }.category(), "rate_limit");
        assert_eq!(BackendErrorKind::AuthError.category(), "auth_error");
        assert_eq!(BackendErrorKind::CircuitOpen.category(), "circuit_open");
    }

    #[test]
    fn test_display() {
        assert_eq!(format!("{}", BackendErrorKind::Timeout), "timeout");
        assert_eq!(format!("{}", BackendErrorKind::NetworkError), "network_error");
    }
}
