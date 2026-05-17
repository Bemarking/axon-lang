//! §Fase 36.x.a — Mixed-flow streaming diagnostic anchor.
//!
//! Pins the v1.34.0 state that Fase 36.x closes — the agent pattern
//! (retrieve context → deliberate → persist) behind a streaming
//! `axonendpoint`. This file is the committed baseline; each later
//! sub-fase inverts a §-assertion:
//!
//!   §1 — `in_memory` is NOT a source-declarable `axonstore` backend.
//!        The type-checker rejects `backend: in_memory` even though
//!        the runtime `StoreRegistry` already supports it — so a
//!        mixed flow cannot run or be tested without a live Postgres.
//!        → §Fase 36.x.b inverts this (D2).
//!
//!   §2 — the streaming producer emits a DOUBLE TERMINATOR on the
//!        error path: `run_streaming_via_dispatcher` emits
//!        `FlowError` and then, unconditionally, `FlowComplete` — so
//!        an errored streaming flow puts BOTH `axon.error` AND
//!        `axon.complete` on the wire, violating the Fase 33
//!        "exactly one terminator" contract.
//!        → §Fase 36.x.c inverts this (D1).
//!
//! The diagnosis (founder hypothesis 2026-05-17): a real agent flow
//! mixes `axonstore` ops with a `step`; the streaming path was never
//! tested with that shape. Verified — the path DOES dispatch mixed
//! flows, but the wire is malformed on error and the shape is
//! structurally un-runnable without external infrastructure.

use axon::axon_server::{build_router, ServerConfig};
use axon::lexer::Lexer;
use axon::parser::Parser;
use axon::type_checker::TypeChecker;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;

// ─── §1 — `in_memory` is a source-declarable store backend ─────────
//
// INVERTED by §Fase 36.x.b (D2). The v1.34.0 baseline rejected
// `backend: in_memory` at the type-checker (`VALID_STORE_BACKENDS`
// omitted it) — so the canonical agent flow could not be declared
// against an in-memory store. 36.x.b added `in_memory` to the
// catalog; this assertion is now flipped to its fixed form and
// stands as the regression guard.

#[test]
fn s1_in_memory_store_backend_is_declarable_post_36xb() {
    let src = "axonstore mem { backend: in_memory }";
    let tokens = Lexer::new(src, "<diag>").tokenize().expect("lex");
    let prog = Parser::new(tokens).parse().expect("parse");
    let errors = TypeChecker::new(&prog).check();
    assert!(
        !errors.iter().any(|e| {
            let m = e.message.to_lowercase();
            m.contains("backend") && m.contains("in_memory")
        }),
        "§Fase 36.x.a §1 (inverted by 36.x.b / D2): `backend: \
         in_memory` is a first-class declarable axonstore backend — \
         it must type-check with no backend error. Errors: {:?}",
        errors.iter().map(|e| &e.message).collect::<Vec<_>>()
    );
}

// ─── §2 — the streaming error path emits a DOUBLE terminator ───────

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
        default_backend: None,
    }
}

async fn deploy(app: &axum::Router, src: &str) -> (StatusCode, serde_json::Value) {
    let body = serde_json::json!({ "source": src, "source_file": "diag.axon" });
    let req = Request::builder()
        .method("POST")
        .uri("/v1/deploy")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (status, serde_json::from_slice(&bytes).unwrap_or_default())
}

async fn hit_sse(app: &axum::Router, path: &str) -> (StatusCode, String) {
    let req = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/json")
        .header("accept", "text/event-stream")
        .body(Body::from("{}"))
        .unwrap();
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (status, String::from_utf8_lossy(&bytes).into_owned())
}

#[tokio::test]
async fn s2_streaming_error_path_emits_a_double_terminator() {
    // A `sqlite` store type-checks (sqlite ∈ VALID_STORE_BACKENDS)
    // but the runtime registry only implements `postgresql` +
    // `in_memory` — `StoreRegistry::build` rejects `sqlite` with
    // `UnknownBackend`. `run_streaming_via_dispatcher` then emits
    // `FlowError` AND, unconditionally, `FlowComplete`. Deterministic
    // — no env, no database.
    let app = build_router(server_cfg());
    let src = "axonstore mem { backend: sqlite connection: \"file:x.db\" }\n\
        flow ChatFlow() -> Unit {\n\
            retrieve mem { where: \"kind = 'history'\" as: history }\n\
            step Generate { ask: \"deliberate\" output: Stream<Token> }\n\
        }\n\
        axonendpoint ChatE { method: POST path: \"/chat\" execute: ChatFlow \
        backend: stub transport: sse }";
    let (dstatus, dbody) = deploy(&app, src).await;
    assert_eq!(
        dstatus,
        StatusCode::OK,
        "§36.x.a §2: a `sqlite` store type-checks — the deploy must \
         succeed. Body: {dbody}"
    );

    let (status, wire) = hit_sse(&app, "/chat").await;
    eprintln!("§36.x.a §2 — status={status}\n  wire:\n{wire}");

    let has_error = wire.contains("axon.error");
    let has_complete = wire.contains("axon.complete");

    assert!(
        has_error && has_complete,
        "§Fase 36.x.a §2 — v1.34.0 baseline: the streaming error path \
         emits BOTH `axon.error` AND `axon.complete` — a double \
         terminator, violating the Fase 33 one-terminator contract. \
         36.x.c (D1) inverts this: an errored flow must emit ONLY \
         `axon.error`. has_error={has_error} has_complete={has_complete}\n\
         wire:\n{wire}"
    );
}

// ─── §3 — diagnostic narrative, emitted for the record ─────────────

#[test]
fn s3_diagnostic_narrative() {
    eprintln!(
        "§Fase 36.x.a — mixed-flow streaming gap (v1.34.0 baseline):\n\
         A. run_streaming_via_dispatcher emits FlowError THEN an\n\
            unconditional FlowComplete — the SSE wire carries a double\n\
            terminator on every error path.\n\
         B. Zero test coverage — no `transport: sse` test in the\n\
            entire Fase 35 axonstore suite.\n\
         C. The agent pattern cannot run without a live Postgres —\n\
            `in_memory` is not a source-declarable store backend, and\n\
            sqlite/mysql type-check but have no runtime backend.\n\
         POST-36.x: `in_memory` is declarable (D2); the streaming\n\
         producer emits exactly one terminator (D1); the mixed\n\
         retrieve→step→persist flow is a tested primitive (D3)."
    );
}
