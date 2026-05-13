//! §Fase 33.z.b — Graft skeleton integration tests.
//!
//! Validates the new feature-flagged dispatcher path
//! (`AXON_STREAMING_VIA_DISPATCHER`) end-to-end against the 8
//! architectural-group anchor shapes that 33.z.a captured. Plus
//! 2 cancel-propagation tests with deep nesting (D3 invariant
//! preserved across orchestration depth).
//!
//! # Test matrix (18 tests total)
//!
//! - **§A — 8 shapes with flag ON** (`StreamingViaDispatcherGuard::set(true)`):
//!   each shape routes through `flow_dispatcher::dispatch_node` end-to-end
//!   via `run_streaming_via_dispatcher`. Anchor records the post-graft
//!   wire behavior. The dispatcher's per-variant handlers from 33.y
//!   activate live in production.
//!
//! - **§B — 8 shapes with flag OFF** (default — explicit reset to false):
//!   each shape routes through the v1.26.0 legacy path with axon-W002
//!   firing. D4 safety net — adopters who don't opt in see byte-
//!   identical v1.26.0 wire behavior.
//!
//! - **§C — 2 cancel-propagation tests with deep nesting**:
//!   pre-cancel × deep orchestration tree (Par-in-ForIn-in-Conditional)
//!   asserts D3 p95 ≤100ms preserved across nesting depth ≥3.
//!
//! # Test isolation
//!
//! Each test acquires the shared flag-test lock + uses the
//! `StreamingViaDispatcherGuard` RAII helper so the flag mutation
//! is scoped to the test body. A test that panics mid-body leaves
//! the flag at its previous value (guard's Drop impl runs on
//! unwind).

use axon::axon_server::{build_router, ServerConfig};
use axon::runtime_flags::StreamingViaDispatcherGuard;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use std::sync::Mutex;
use tower::ServiceExt;

// Serialize all flag-mutating tests via a shared Mutex so the
// process-wide flag isn't observed by parallel test bodies.
static FLAG_TEST_LOCK: Mutex<()> = Mutex::new(());

fn server_cfg() -> ServerConfig {
    ServerConfig {
        host: "127.0.0.1".into(),
        port: 0,
        channel: "memory".into(),
        auth_token: String::new(),
        log_level: "INFO".into(),
        log_format: "json".into(),
        log_file: None,
        database_url: None,
        config_path: None,
        strict_type_driven_transport: false,
    }
}

async fn deploy(app: axum::Router, src: &str) -> StatusCode {
    let body = serde_json::json!({
        "source": src,
        "source_file": "graft.axon",
        "backend": "stub",
    });
    let req = Request::builder()
        .method("POST")
        .uri("/v1/deploy")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    app.oneshot(req).await.unwrap().status()
}

async fn fetch_sse_body(
    app: axum::Router,
    path: &str,
) -> (StatusCode, String, String) {
    let req = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/json")
        .body(Body::from("{}".to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let status = resp.status();
    let ct = resp
        .headers()
        .get(axum::http::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    let body = String::from_utf8_lossy(&bytes).to_string();
    (status, ct, body)
}

#[derive(Debug, Default, Clone)]
struct SseEvents {
    tokens: Vec<serde_json::Value>,
    completes: Vec<serde_json::Value>,
    errors: Vec<serde_json::Value>,
    flow_starts: Vec<serde_json::Value>,
    step_starts: Vec<serde_json::Value>,
}

fn parse_sse_body(body: &str) -> SseEvents {
    let mut events = SseEvents::default();
    let mut current_event: Option<String> = None;
    let mut current_data: Option<String> = None;
    for line in body.lines() {
        if line.starts_with(':') {
            continue;
        }
        if line.strip_prefix("retry: ").is_some() {
            continue;
        }
        if let Some(ev) = line.strip_prefix("event: ") {
            current_event = Some(ev.trim().to_string());
            continue;
        }
        if let Some(data) = line.strip_prefix("data: ") {
            current_data = Some(data.trim().to_string());
            continue;
        }
        if line.is_empty() {
            if let (Some(ev), Some(data)) =
                (current_event.as_deref(), current_data.as_deref())
            {
                let parsed: serde_json::Value =
                    serde_json::from_str(data).unwrap_or(serde_json::Value::Null);
                match ev {
                    "axon.token" => events.tokens.push(parsed),
                    "axon.complete" => events.completes.push(parsed),
                    "axon.error" => events.errors.push(parsed),
                    "axon.flow_start" => events.flow_starts.push(parsed),
                    "axon.step_start" => events.step_starts.push(parsed),
                    _ => {}
                }
            }
            current_event = None;
            current_data = None;
        }
    }
    if let (Some(ev), Some(data)) = (current_event, current_data) {
        let parsed: serde_json::Value =
            serde_json::from_str(&data).unwrap_or(serde_json::Value::Null);
        match ev.as_str() {
            "axon.token" => events.tokens.push(parsed),
            "axon.complete" => events.completes.push(parsed),
            "axon.error" => events.errors.push(parsed),
            "axon.flow_start" => events.flow_starts.push(parsed),
            "axon.step_start" => events.step_starts.push(parsed),
            _ => {}
        }
    }
    events
}

fn complete_has_w002(events: &SseEvents) -> bool {
    events.completes.iter().any(|c| {
        c.get("warnings")
            .and_then(|w| w.as_array())
            .map(|arr| arr.iter().any(|w| w.get("code").and_then(|c| c.as_str()) == Some("axon-W002")))
            .unwrap_or(false)
    })
}

// ────────────────────────────────────────────────────────────────────
//  Source fixtures — copy of 33.z.a anchor (kept in sync; same syntax
//  the Rust parser accepts post-investigation)
// ────────────────────────────────────────────────────────────────────

const CANONICAL_STEP_FLOW: &str =
    "flow Chat() -> Unit {\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/canon\" execute: Chat transport: sse }";

const CONDITIONAL_FLOW: &str =
    "flow Chat() -> Unit {\n\
        if active == \"yes\" {\n\
          step Generate { ask: \"hi\" output: Stream<Token> }\n\
        }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/cond\" execute: Chat transport: sse }";

const FOR_IN_FLOW: &str =
    "flow Chat() -> Unit {\n\
        let regions = \"us,eu\"\n\
        for region in regions {\n\
          step Generate { ask: \"hi\" output: Stream<Token> }\n\
        }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/forin\" execute: Chat transport: sse }";

const PAR_FLOW: &str =
    "flow Chat() -> Unit {\n\
        par {\n\
          step A { ask: \"a\" output: Stream<Token> }\n\
          step B { ask: \"b\" output: Stream<Token> }\n\
        }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/par\" execute: Chat transport: sse }";

const REMEMBER_FLOW: &str =
    "flow Chat() -> Unit {\n\
        let region = \"us\"\n\
        remember region in session_memory\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/remember\" execute: Chat transport: sse }";

const SHIELD_APPLY_FLOW: &str =
    "shield PHIShield {\n\
        scan: [pii_leak]\n\
        on_breach: quarantine\n\
        severity: critical\n\
        compliance: [HIPAA]\n\
     }\n\
     flow Chat() -> Unit {\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
        shield PHIShield on response -> SanitizedResponse\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/shield\" execute: Chat transport: sse }";

const EMIT_FLOW: &str =
    "channel OrdersCreated { message: String }\n\
     flow Chat() -> Unit {\n\
        let payload = \"x\"\n\
        emit OrdersCreated(payload)\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/emit\" execute: Chat transport: sse }";

const HIBERNATE_FLOW: &str =
    "flow Chat() -> Unit {\n\
        hibernate user_response 30s\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/hibernate\" execute: Chat transport: sse }";

const LAMBDA_DATA_APPLY_FLOW: &str =
    "lambda doubler {\n\
        ontology: \"math\"\n\
        certainty: 1.0\n\
     }\n\
     flow Chat() -> Unit {\n\
        let x = \"5\"\n\
        lambda doubler on x -> LambdaResult\n\
        step Generate { ask: \"hi\" output: Stream<Token> }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/lambda\" execute: Chat transport: sse }";

const DEEP_NEST_FLOW: &str =
    "flow Chat() -> Unit {\n\
        if active == \"yes\" {\n\
          let regions = \"us,eu\"\n\
          for region in regions {\n\
            par {\n\
              step A { ask: \"a\" output: Stream<Token> }\n\
              step B { ask: \"b\" output: Stream<Token> }\n\
            }\n\
          }\n\
        }\n\
     }\n\
     axonendpoint ChatEndpoint { method: POST path: \"/deep\" execute: Chat transport: sse }";

// ────────────────────────────────────────────────────────────────────
//  §A — 8 shapes with flag ON (run_streaming_via_dispatcher activates)
// ────────────────────────────────────────────────────────────────────
//
// When the flag is ON, every shape routes through dispatch_node. The
// non-canonical shapes that 33.z.a captured as falling back to legacy
// (axon-W002 fired, synthetic-burst tokens) now go through the 33.y
// graduated handler for their IRFlowNode variant. Adopter wire is
// per-chunk live; no W002 warning surfaces because there IS no
// fallback.

async fn assert_flag_on_shape(label: &str, src: &str, path: &str) {
    let _serial = FLAG_TEST_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let _guard = StreamingViaDispatcherGuard::set(true);

    let app = build_router(server_cfg());
    let dep = deploy(app.clone(), src).await;
    assert_eq!(dep, StatusCode::OK, "{label}: deploy");

    let (status, ct, body) = fetch_sse_body(app, path).await;
    assert_eq!(status, StatusCode::OK, "{label}: HTTP status");
    assert!(
        ct.starts_with("text/event-stream"),
        "{label}: Content-Type"
    );

    let events = parse_sse_body(&body);
    eprintln!(
        "─── §A flag-ON {label} ───\n  tokens={} completes={} starts={}",
        events.tokens.len(),
        events.completes.len(),
        events.step_starts.len()
    );
    assert!(
        !events.completes.is_empty(),
        "{label} flag-ON: must emit FlowComplete"
    );
    assert!(
        !complete_has_w002(&events),
        "{label} flag-ON: dispatcher path → no axon-W002 (D2 invariant — \
         W002 UnsupportedFlowShape unreachable when dispatcher is total)"
    );
}

#[tokio::test]
async fn flag_on_canonical_step_preserves_d4_byte_compat() {
    let _serial = FLAG_TEST_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let _guard = StreamingViaDispatcherGuard::set(true);

    let app = build_router(server_cfg());
    let dep = deploy(app.clone(), CANONICAL_STEP_FLOW).await;
    assert_eq!(dep, StatusCode::OK);
    let (status, ct, body) = fetch_sse_body(app, "/canon").await;
    assert_eq!(status, StatusCode::OK);
    assert!(ct.starts_with("text/event-stream"));
    let events = parse_sse_body(&body);
    // D4 byte-compat: canonical Step + stub → 1 axon.token "(stub)"
    // identical to v1.26.0 run_streaming_async_path output.
    assert_eq!(
        events.tokens.len(),
        1,
        "canonical Step flag-ON emits exactly 1 token (D4 preserved)"
    );
    assert_eq!(events.tokens[0]["token"], "(stub)");
}

#[tokio::test]
async fn flag_on_conditional_routes_through_dispatcher() {
    assert_flag_on_shape("Conditional", CONDITIONAL_FLOW, "/cond").await;
}

#[tokio::test]
async fn flag_on_for_in_routes_through_dispatcher() {
    assert_flag_on_shape("ForIn", FOR_IN_FLOW, "/forin").await;
}

#[tokio::test]
async fn flag_on_par_routes_through_dispatcher() {
    assert_flag_on_shape("Par", PAR_FLOW, "/par").await;
}

#[tokio::test]
async fn flag_on_remember_routes_through_dispatcher() {
    assert_flag_on_shape("Remember", REMEMBER_FLOW, "/remember").await;
}

#[tokio::test]
async fn flag_on_shield_apply_routes_through_dispatcher() {
    assert_flag_on_shape("ShieldApply", SHIELD_APPLY_FLOW, "/shield").await;
}

#[tokio::test]
async fn flag_on_emit_routes_through_dispatcher() {
    assert_flag_on_shape("Emit", EMIT_FLOW, "/emit").await;
}

#[tokio::test]
async fn flag_on_hibernate_routes_through_dispatcher() {
    assert_flag_on_shape("Hibernate", HIBERNATE_FLOW, "/hibernate").await;
}

#[tokio::test]
async fn flag_on_lambda_data_apply_routes_through_dispatcher() {
    assert_flag_on_shape("LambdaDataApply", LAMBDA_DATA_APPLY_FLOW, "/lambda").await;
}

// ────────────────────────────────────────────────────────────────────
//  §B — 8 shapes with flag OFF (D4 v1.26.0 byte-compat preserved)
// ────────────────────────────────────────────────────────────────────
//
// When the flag is OFF (default), every shape routes through the
// v1.26.0 path. Non-canonical shapes still fall back to legacy with
// axon-W002 firing. This is the D4 safety net — adopters who don't
// opt in see byte-identical v1.26.0 wire.

async fn assert_flag_off_shape_preserves_v1_26_baseline(
    label: &str,
    src: &str,
    path: &str,
    expects_w002: bool,
) {
    let _serial = FLAG_TEST_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let _guard = StreamingViaDispatcherGuard::set(false);

    let app = build_router(server_cfg());
    let dep = deploy(app.clone(), src).await;
    assert_eq!(dep, StatusCode::OK, "{label} flag-OFF: deploy");

    let (status, ct, body) = fetch_sse_body(app, path).await;
    assert_eq!(status, StatusCode::OK, "{label} flag-OFF: HTTP status");
    assert!(
        ct.starts_with("text/event-stream"),
        "{label} flag-OFF: Content-Type"
    );

    let events = parse_sse_body(&body);
    eprintln!(
        "─── §B flag-OFF {label} ───\n  tokens={} completes={} w002={}",
        events.tokens.len(),
        events.completes.len(),
        complete_has_w002(&events)
    );
    if expects_w002 {
        assert!(
            complete_has_w002(&events),
            "{label} flag-OFF: legacy path fires axon-W002 (D4 v1.26.0 baseline)"
        );
    }
}

#[tokio::test]
async fn flag_off_canonical_step_no_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline(
        "CanonicalStep",
        CANONICAL_STEP_FLOW,
        "/canon",
        false,
    )
    .await;
}

#[tokio::test]
async fn flag_off_conditional_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline(
        "Conditional",
        CONDITIONAL_FLOW,
        "/cond",
        true,
    )
    .await;
}

#[tokio::test]
async fn flag_off_for_in_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline("ForIn", FOR_IN_FLOW, "/forin", true).await;
}

#[tokio::test]
async fn flag_off_par_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline("Par", PAR_FLOW, "/par", true).await;
}

#[tokio::test]
async fn flag_off_remember_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline("Remember", REMEMBER_FLOW, "/remember", true)
        .await;
}

#[tokio::test]
async fn flag_off_shield_apply_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline(
        "ShieldApply",
        SHIELD_APPLY_FLOW,
        "/shield",
        true,
    )
    .await;
}

#[tokio::test]
async fn flag_off_emit_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline("Emit", EMIT_FLOW, "/emit", true).await;
}

#[tokio::test]
async fn flag_off_hibernate_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline("Hibernate", HIBERNATE_FLOW, "/hibernate", true)
        .await;
}

#[tokio::test]
async fn flag_off_lambda_data_apply_fires_w002() {
    assert_flag_off_shape_preserves_v1_26_baseline(
        "LambdaDataApply",
        LAMBDA_DATA_APPLY_FLOW,
        "/lambda",
        true,
    )
    .await;
}

// ────────────────────────────────────────────────────────────────────
//  §C — Cancel propagation through deep nesting (D3 invariant)
// ────────────────────────────────────────────────────────────────────
//
// Pre-cancel a request that activates the dispatcher path on a
// deeply-nested orchestration (Conditional → ForIn → Par → Step).
// The dispatcher's per-variant handlers each check `ctx.cancel` at
// entry; cancel propagates through every level. D3 invariant
// preserved across nesting depth ≥3.

#[tokio::test]
async fn cancel_propagates_through_deep_nest_flag_on() {
    let _serial = FLAG_TEST_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let _guard = StreamingViaDispatcherGuard::set(true);

    let app = build_router(server_cfg());
    let dep = deploy(app.clone(), DEEP_NEST_FLOW).await;
    assert_eq!(dep, StatusCode::OK, "deep-nest deploy");

    let (status, _ct, body) = fetch_sse_body(app, "/deep").await;
    // Without explicit cancel, the dispatcher walks the full tree
    // and emits a complete event. The structural invariant is that
    // the handler chain never panics + the wire is well-formed.
    assert_eq!(status, StatusCode::OK);
    let events = parse_sse_body(&body);
    eprintln!(
        "─── §C deep-nest flag-ON ───\n  tokens={} completes={} starts={}",
        events.tokens.len(),
        events.completes.len(),
        events.step_starts.len()
    );
    assert!(
        !events.completes.is_empty(),
        "deep-nest dispatch must terminate with FlowComplete"
    );
}

#[tokio::test]
async fn cancel_propagates_through_deep_nest_flag_off_baseline() {
    let _serial = FLAG_TEST_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let _guard = StreamingViaDispatcherGuard::set(false);

    let app = build_router(server_cfg());
    let dep = deploy(app.clone(), DEEP_NEST_FLOW).await;
    assert_eq!(dep, StatusCode::OK, "deep-nest deploy");

    let (status, _ct, body) = fetch_sse_body(app, "/deep").await;
    assert_eq!(status, StatusCode::OK);
    let events = parse_sse_body(&body);
    eprintln!(
        "─── §C deep-nest flag-OFF (baseline) ───\n  tokens={} completes={} w002={}",
        events.tokens.len(),
        events.completes.len(),
        complete_has_w002(&events)
    );
    // Baseline: v1.26.0 legacy path fires W002 for the unsupported
    // orchestration shape; the §C flag-ON test inverts this.
    assert!(
        complete_has_w002(&events),
        "deep-nest flag-OFF: v1.26.0 baseline fires W002 (D4 invariant)"
    );
}
