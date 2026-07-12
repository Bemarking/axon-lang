//! §Fase 108.b — the dataspace deploy hook: a DECLARED dataspace is
//! INSTANTIATED in the deterministic columnar engine at deploy time.
//!
//! The ground-truth finding this pins against regression: before §108.b,
//! `dataspace_specs` was `#[serde(skip)]`-hidden and read by nothing — a
//! declared dataspace reached no runtime state at all. These tests deploy
//! through the REAL `/v1/deploy` handler (the §95.f real-path discipline)
//! and assert the engine holds the declared store with the declared
//! schema.

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::util::ServiceExt;

fn server_cfg() -> axon::axon_server::ServerConfig {
    axon::axon_server::ServerConfig {
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
        schemas_dir: None,
    }
}

async fn deploy(app: axum::Router, src: &str) -> serde_json::Value {
    let body = serde_json::json!({
        "source": src,
        "source_file": "test.axon",
        "backend": "stub",
    });
    let req = Request::builder()
        .method("POST")
        .uri("/v1/deploy")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    serde_json::from_slice(&bytes).unwrap_or_default()
}

#[tokio::test]
async fn deploy_instantiates_the_declared_dataspace_in_the_engine() {
    let (app, state) = axon::axon_server::build_router_with_state(server_cfg());
    let src = r#"
dataspace Leads {
    column email: Text
    column score: Float
    column visits: Int
}

flow Noop() -> Text {
    let x = "ok"
}
"#;
    let json = deploy(app, src).await;
    assert_eq!(
        json.get("success").and_then(|v| v.as_bool()),
        Some(true),
        "deploy must succeed: {json}"
    );

    let engine = {
        let s = state.lock().unwrap();
        s.dataspace_engine.clone()
    };
    let engine = engine.read().unwrap();
    let store = engine
        .store("Leads")
        .expect("the DECLARED dataspace must exist in the engine — the §108 ground-truth fix");
    assert_eq!(store.schema().len(), 3);
    assert_eq!(store.column_index("email"), Some(0));
    assert_eq!(
        store.schema()[1].1,
        axon::dataspace_engine::ColumnType::Float
    );
    assert_eq!(store.row_count(), 0, "born empty — ingest is §108.c");
}

#[tokio::test]
async fn redeploy_replaces_the_store_new_names_accumulate() {
    let (app, state) = axon::axon_server::build_router_with_state(server_cfg());
    deploy(
        app.clone(),
        "dataspace A { column x: Int }\nflow F() -> Text { let v = \"1\" }",
    )
    .await;
    deploy(
        app,
        "dataspace B { column y: Text }\nflow G() -> Text { let v = \"2\" }",
    )
    .await;

    let engine = {
        let s = state.lock().unwrap();
        s.dataspace_engine.clone()
    };
    let engine = engine.read().unwrap();
    assert!(engine.store("A").is_some(), "earlier deploy's store survives");
    assert!(engine.store("B").is_some(), "new deploy's store lands");
}

#[tokio::test]
async fn a_t928_violation_refuses_the_deploy() {
    // The compile gate runs inside deploy: an empty-schema dataspace is
    // refused at the type_checker phase — the engine never sees it.
    let (app, state) = axon::axon_server::build_router_with_state(server_cfg());
    let json = deploy(
        app,
        "dataspace Empty { }\nflow F() -> Text { let v = \"1\" }",
    )
    .await;
    assert_eq!(json.get("success").and_then(|v| v.as_bool()), Some(false));
    assert!(
        json.get("error")
            .and_then(|e| e.as_str())
            .unwrap_or_default()
            .contains("T928"),
        "the refusal names the law: {json}"
    );
    let engine = {
        let s = state.lock().unwrap();
        s.dataspace_engine.clone()
    };
    assert!(
        engine.read().unwrap().is_empty(),
        "a refused deploy must leave no engine state"
    );
}
