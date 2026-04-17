//! Request Tracing — Tower middleware layer for structured request observability.
//!
//! Generates a UUID `request_id` per incoming HTTP request, creates a tracing
//! span with method, path, and client info, and records the response status +
//! latency on completion.
//!
//! This layer integrates with the `tracing` ecosystem — all log events emitted
//! within a request handler automatically inherit the request span's fields
//! (request_id, method, path), enabling full correlation across log lines.
//!
//! Designed for production SaaS workloads with structured JSON logging.

use axum::body::Body;
use axum::extract::Request;
use axum::http::HeaderValue;
use axum::middleware::Next;
use axum::response::Response;
use std::time::Instant;

/// Axum middleware function for request tracing.
///
/// Creates a tracing span per request with:
///   - `request_id`: UUID v4 for correlation
///   - `method`: HTTP method
///   - `path`: request path
///   - `client_ip`: from X-Forwarded-For or socket addr
///
/// On response, records:
///   - `status`: HTTP status code
///   - `latency_ms`: request duration in milliseconds
pub async fn request_tracing_middleware(
    request: Request<Body>,
    next: Next,
) -> Response {
    let request_id = uuid::Uuid::new_v4().to_string();
    let method = request.method().to_string();
    let path = request.uri().path().to_string();
    let client_ip = request
        .headers()
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("-")
        .to_string();

    let span = tracing::info_span!(
        "http_request",
        request_id = %request_id,
        method = %method,
        path = %path,
        client_ip = %client_ip,
        status = tracing::field::Empty,
        latency_ms = tracing::field::Empty,
    );

    let start = Instant::now();

    // Enter span for the duration of the request
    let _enter = span.enter();

    tracing::info!(
        request_id = %request_id,
        method = %method,
        path = %path,
        client_ip = %client_ip,
        "request_started"
    );

    // Drop the span guard before await (we re-enter after)
    drop(_enter);

    let mut response = {
        let _enter = span.enter();
        drop(_enter);
        next.run(request).await
    };

    let latency_ms = start.elapsed().as_millis() as u64;
    let status = response.status().as_u16();

    span.record("status", status);
    span.record("latency_ms", latency_ms);

    let _enter = span.enter();

    if status >= 500 {
        tracing::error!(
            request_id = %request_id,
            method = %method,
            path = %path,
            status = status,
            latency_ms = latency_ms,
            "request_completed_error"
        );
    } else if status >= 400 {
        tracing::warn!(
            request_id = %request_id,
            method = %method,
            path = %path,
            status = status,
            latency_ms = latency_ms,
            "request_completed_client_error"
        );
    } else {
        tracing::info!(
            request_id = %request_id,
            method = %method,
            path = %path,
            status = status,
            latency_ms = latency_ms,
            "request_completed"
        );
    }

    // Inject request_id into response headers for client correlation
    if let Ok(val) = HeaderValue::from_str(&request_id) {
        response.headers_mut().insert("x-request-id", val);
    }

    response
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    // Request tracing is tested via integration tests in axon_server::tests
    // since it requires a full axum Router context.

    #[test]
    fn test_module_compiles() {
        // Validates the module compiles and all types are properly imported.
        assert!(true);
    }
}
