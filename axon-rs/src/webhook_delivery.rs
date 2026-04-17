//! Webhook Delivery — async HTTP delivery with retry and exponential backoff.
//!
//! When an event is dispatched to matching webhooks, this module handles the
//! actual HTTP POST to each webhook URL:
//!   - Timeout per request (configurable, default 10s)
//!   - Exponential backoff with jitter on failure (configurable retries)
//!   - HMAC signature header when webhook has a secret
//!   - Records delivery results back into WebhookRegistry
//!
//! Usage:
//!   - `deliver_one()` — single delivery attempt to one webhook
//!   - `deliver_with_retry()` — delivery with exponential backoff retries
//!   - `dispatch_all()` — spawn tokio tasks for all matched webhooks

use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;

use crate::webhooks::WebhookRegistry;

// ── Configuration ───────────────────────────────────────────────────────

/// Configuration for webhook delivery behavior.
#[derive(Debug, Clone, Serialize)]
pub struct DeliveryConfig {
    /// Timeout per HTTP request.
    pub timeout: Duration,
    /// Maximum retry attempts (0 = no retries, 1 = one retry, etc.).
    pub max_retries: u32,
    /// Base delay for exponential backoff (doubles each retry).
    pub base_delay: Duration,
    /// Maximum backoff delay cap.
    pub max_delay: Duration,
}

impl Default for DeliveryConfig {
    fn default() -> Self {
        DeliveryConfig {
            timeout: Duration::from_secs(10),
            max_retries: 3,
            base_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(30),
        }
    }
}

// ── Delivery result ─────────────────────────────────────────────────────

/// Result of a single delivery attempt.
#[derive(Debug, Clone, Serialize)]
pub struct DeliveryResult {
    pub webhook_id: String,
    pub topic: String,
    pub status_code: u16,
    pub success: bool,
    pub latency_ms: u64,
    pub attempts: u32,
    pub error: Option<String>,
}

// ── Delivery payload ────────────────────────────────────────────────────

/// Payload sent to webhook URL.
#[derive(Debug, Clone, Serialize)]
pub struct WebhookPayload {
    pub event: String,
    pub payload: serde_json::Value,
    pub source: String,
    pub timestamp: u64,
}

// ── Single delivery ─────────────────────────────────────────────────────

/// Deliver a single POST request to a webhook URL.
///
/// Returns (status_code, latency_ms, error).
/// status_code is 0 if the connection failed entirely.
pub async fn deliver_one(
    url: &str,
    body: &WebhookPayload,
    signature: Option<&str>,
    timeout: Duration,
) -> (u16, u64, Option<String>) {
    let start = std::time::Instant::now();

    let client = match reqwest::Client::builder()
        .timeout(timeout)
        .build()
    {
        Ok(c) => c,
        Err(e) => return (0, 0, Some(format!("client build error: {e}"))),
    };

    let mut request = client.post(url)
        .header("Content-Type", "application/json")
        .header("User-Agent", "AxonServer-Webhook/1.0");

    if let Some(sig) = signature {
        request = request.header("X-Axon-Signature", sig);
    }

    let body_bytes = match serde_json::to_vec(body) {
        Ok(b) => b,
        Err(e) => return (0, 0, Some(format!("serialize error: {e}"))),
    };

    request = request.body(body_bytes);

    match request.send().await {
        Ok(response) => {
            let latency = start.elapsed().as_millis() as u64;
            let status = response.status().as_u16();
            if (200..300).contains(&status) {
                (status, latency, None)
            } else {
                let error_text = response.text().await.unwrap_or_default();
                let msg = if error_text.len() > 200 {
                    format!("HTTP {status}: {}...", &error_text[..200])
                } else {
                    format!("HTTP {status}: {error_text}")
                };
                (status, latency, Some(msg))
            }
        }
        Err(e) => {
            let latency = start.elapsed().as_millis() as u64;
            if e.is_timeout() {
                (0, latency, Some("timeout".to_string()))
            } else if e.is_connect() {
                (0, latency, Some(format!("connection error: {e}")))
            } else {
                (0, latency, Some(format!("request error: {e}")))
            }
        }
    }
}

// ── Delivery with retry ─────────────────────────────────────────────────

/// Deliver to a webhook with exponential backoff retries.
///
/// Retries on: connection errors, timeouts, 5xx status codes.
/// Does NOT retry on: 4xx status codes (client error, won't improve).
pub async fn deliver_with_retry(
    url: &str,
    body: &WebhookPayload,
    signature: Option<&str>,
    config: &DeliveryConfig,
) -> DeliveryResult {
    let webhook_id = String::new(); // filled by caller
    let topic = body.event.clone();
    let mut last_status = 0u16;
    let mut _last_latency = 0u64;
    let mut last_error = None;
    let total_start = std::time::Instant::now();

    for attempt in 0..=config.max_retries {
        let (status, latency, error) = deliver_one(url, body, signature, config.timeout).await;

        last_status = status;
        _last_latency = latency;
        last_error = error.clone();

        // Success: 2xx
        if (200..300).contains(&status) {
            return DeliveryResult {
                webhook_id,
                topic,
                status_code: status,
                success: true,
                latency_ms: total_start.elapsed().as_millis() as u64,
                attempts: attempt + 1,
                error: None,
            };
        }

        // Don't retry 4xx (client errors won't improve)
        if (400..500).contains(&status) {
            return DeliveryResult {
                webhook_id,
                topic,
                status_code: status,
                success: false,
                latency_ms: total_start.elapsed().as_millis() as u64,
                attempts: attempt + 1,
                error,
            };
        }

        // Retry: 5xx, timeout, connection error
        if attempt < config.max_retries {
            let delay = compute_backoff(attempt, config.base_delay, config.max_delay);
            tokio::time::sleep(delay).await;
        }
    }

    // All retries exhausted
    DeliveryResult {
        webhook_id,
        topic,
        status_code: last_status,
        success: false,
        latency_ms: total_start.elapsed().as_millis() as u64,
        attempts: config.max_retries + 1,
        error: last_error,
    }
}

/// Compute exponential backoff delay with jitter.
fn compute_backoff(attempt: u32, base: Duration, max: Duration) -> Duration {
    let exp_ms = base.as_millis() as u64 * (1u64 << attempt.min(10));
    let capped = exp_ms.min(max.as_millis() as u64);
    // Simple deterministic jitter: vary by ±25% based on attempt
    let jitter_factor = match attempt % 4 {
        0 => 100,
        1 => 75,
        2 => 125,
        _ => 110,
    };
    let final_ms = capped * jitter_factor / 100;
    Duration::from_millis(final_ms)
}

// ── Batch dispatch ──────────────────────────────────────────────────────

/// Spawn async delivery tasks for all matching webhooks.
///
/// This function reads the webhook configs from the registry, then spawns
/// independent tokio tasks for each delivery. Results are recorded back
/// into the registry when each task completes.
///
/// Returns the number of delivery tasks spawned.
pub fn dispatch_all(
    registry: Arc<Mutex<WebhookRegistry>>,
    matched_ids: Vec<String>,
    topic: String,
    payload: serde_json::Value,
    source: String,
    config: DeliveryConfig,
) -> usize {
    // Collect webhook info we need outside the lock
    let mut targets: Vec<(String, String, Option<String>)> = Vec::new(); // (id, url, secret)

    {
        let reg = registry.lock().unwrap();
        for id in &matched_ids {
            if let Some(wh) = reg.get(id) {
                targets.push((wh.id.clone(), wh.url.clone(), wh.secret.clone()));
            }
        }
    }

    let count = targets.len();
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    for (webhook_id, url, secret) in targets {
        let registry = registry.clone();
        let topic = topic.clone();
        let payload = payload.clone();
        let source = source.clone();
        let config = config.clone();

        tokio::spawn(async move {
            let body = WebhookPayload {
                event: topic.clone(),
                payload,
                source,
                timestamp,
            };

            let signature = secret.as_ref().map(|s| {
                let body_bytes = serde_json::to_vec(&body).unwrap_or_default();
                WebhookRegistry::compute_signature(s, &body_bytes)
            });

            let mut result = deliver_with_retry(
                &url,
                &body,
                signature.as_deref(),
                &config,
            ).await;

            result.webhook_id = webhook_id.clone();

            // Record result back in registry
            if let Ok(mut reg) = registry.lock() {
                reg.record_completed(
                    &webhook_id,
                    &topic,
                    result.status_code,
                    result.latency_ms,
                    result.error.clone(),
                    result.attempts - 1,
                );
            }
        });
    }

    count
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delivery_config_defaults() {
        let config = DeliveryConfig::default();
        assert_eq!(config.timeout, Duration::from_secs(10));
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.base_delay, Duration::from_millis(500));
        assert_eq!(config.max_delay, Duration::from_secs(30));
    }

    #[test]
    fn delivery_config_serializable() {
        let config = DeliveryConfig::default();
        let json = serde_json::to_value(&config).unwrap();
        assert!(json["timeout"].is_object()); // Duration serializes as {secs, nanos}
        assert_eq!(json["max_retries"], 3);
    }

    #[test]
    fn delivery_result_serializable() {
        let result = DeliveryResult {
            webhook_id: "wh_1".to_string(),
            topic: "deploy".to_string(),
            status_code: 200,
            success: true,
            latency_ms: 45,
            attempts: 1,
            error: None,
        };
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["webhook_id"], "wh_1");
        assert_eq!(json["status_code"], 200);
        assert_eq!(json["success"], true);
        assert_eq!(json["attempts"], 1);
        assert!(json["error"].is_null());
    }

    #[test]
    fn delivery_result_with_error() {
        let result = DeliveryResult {
            webhook_id: "wh_2".to_string(),
            topic: "config.updated".to_string(),
            status_code: 500,
            success: false,
            latency_ms: 120,
            attempts: 4,
            error: Some("HTTP 500: Internal Server Error".to_string()),
        };
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["success"], false);
        assert_eq!(json["attempts"], 4);
        assert_eq!(json["error"], "HTTP 500: Internal Server Error");
    }

    #[test]
    fn webhook_payload_serializable() {
        let payload = WebhookPayload {
            event: "deploy".to_string(),
            payload: serde_json::json!({"flows": ["FlowA"]}),
            source: "server".to_string(),
            timestamp: 1700000000,
        };
        let json = serde_json::to_value(&payload).unwrap();
        assert_eq!(json["event"], "deploy");
        assert_eq!(json["source"], "server");
        assert_eq!(json["timestamp"], 1700000000u64);
        assert!(json["payload"]["flows"].is_array());
    }

    #[test]
    fn compute_backoff_exponential() {
        let base = Duration::from_millis(500);
        let max = Duration::from_secs(30);

        let d0 = compute_backoff(0, base, max);
        let d1 = compute_backoff(1, base, max);
        let d2 = compute_backoff(2, base, max);

        // Attempt 0: 500ms * 1 * jitter(100%) = 500ms
        assert_eq!(d0.as_millis(), 500);
        // Attempt 1: 500ms * 2 * jitter(75%) = 750ms
        assert_eq!(d1.as_millis(), 750);
        // Attempt 2: 500ms * 4 * jitter(125%) = 2500ms
        assert_eq!(d2.as_millis(), 2500);
    }

    #[test]
    fn compute_backoff_capped() {
        let base = Duration::from_secs(10);
        let max = Duration::from_secs(30);

        // Attempt 5: 10s * 32 = 320s, capped at 30s, then jitter
        let d = compute_backoff(5, base, max);
        assert!(d.as_secs() <= 40); // 30s + jitter margin
    }

    #[tokio::test]
    async fn deliver_one_connection_refused() {
        // Deliver to a port that's not listening
        let body = WebhookPayload {
            event: "test".to_string(),
            payload: serde_json::json!(null),
            source: "test".to_string(),
            timestamp: 0,
        };

        let (status, _latency, error) = deliver_one(
            "http://127.0.0.1:19999/nonexistent",
            &body,
            None,
            Duration::from_secs(2),
        ).await;

        assert_eq!(status, 0);
        assert!(error.is_some());
        let err_msg = error.unwrap();
        // Error message varies by platform; just check it's non-empty
        assert!(!err_msg.is_empty(), "expected non-empty error, got: {err_msg}");
    }

    #[tokio::test]
    async fn deliver_with_retry_connection_refused_exhausts_retries() {
        let body = WebhookPayload {
            event: "test".to_string(),
            payload: serde_json::json!(null),
            source: "test".to_string(),
            timestamp: 0,
        };

        let config = DeliveryConfig {
            timeout: Duration::from_secs(1),
            max_retries: 1, // Only 1 retry to keep test fast
            base_delay: Duration::from_millis(50),
            max_delay: Duration::from_millis(100),
        };

        let result = deliver_with_retry(
            "http://127.0.0.1:19999/nonexistent",
            &body,
            None,
            &config,
        ).await;

        assert!(!result.success);
        assert_eq!(result.attempts, 2); // initial + 1 retry
        assert!(result.error.is_some());
    }
}
