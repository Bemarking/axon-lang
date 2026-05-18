//! §Fase 35.l — Real-Postgres integration tests (D14, the robustness
//! floor).
//!
//! Every Fase 35 SQL surface — the substrate (35.c-f), Pillar I
//! (epistemic, 35.g), Pillar III (`Stream<Row>`, 35.i), the type
//! mapping (35.c), Pillar II (audit chain, 35.h) and Pillar IV
//! (capability, 35.j) — exercised **end-to-end against a REAL
//! Postgres**. Not mocks: real rows, a real cursor, real type
//! decoding, real backpressure bounds.
//!
//! # The harness
//!
//! The test connects via the `AXON_TEST_DATABASE_URL` environment
//! variable. When it is unset, OR Postgres is unreachable, every test
//! **skips gracefully** — it logs the skip and returns, so
//! `cargo test` on a developer machine without Postgres still passes.
//! The CI harness (`.github/workflows/fase_35_axonstore.yml`) provides
//! a `postgres:16` service container and sets the env var, so the
//! tests run for real on every push + PR — the implementation is
//! proven against an actual database before v1.30.0 ships.
//!
//! # Fixtures
//!
//! Each test owns a uniquely-named fixture table, `DROP`s it first
//! (idempotent re-runs) and `CREATE`s it via raw SQL. The test harness
//! is allowed DDL — D12's "no DDL" boundary is about the `axonstore`
//! *runtime*, not the test that builds its own fixtures. Distinct
//! table names keep the parallel test run collision-free.

use axon::cancel_token::CancellationFlag;
use axon::ir_nodes::IRAxonStore;
use axon::store::audit_chain::{ChainVerdict, StoreAuditChain, StoreMutationKind};
use axon::store::capability::check_store_capability;
use axon::store::epistemic::{enforce_retrieve_floor, mark_retrieved};
use axon::store::filter::SqlValue;
use axon::store::postgres_backend::PostgresStoreBackend;
use axon::store::registry::{StoreHandle, StoreRegistry};
use axon::store::row_stream::stream_retrieve;
use axon::stream_effect::BackpressurePolicy;

/// §Fase 37.d — empty bindings: these Fase 35 integration tests use
/// only literal `where` clauses (no `${name}` placeholders).
fn nb() -> std::collections::HashMap<String, String> {
    std::collections::HashMap::new()
}

// ── Harness ─────────────────────────────────────────────────────────

/// Resolve the test database backend, or `None` to skip the test.
async fn test_backend() -> Option<PostgresStoreBackend> {
    let dsn = match std::env::var("AXON_TEST_DATABASE_URL") {
        Ok(d) if !d.trim().is_empty() => d,
        _ => {
            eprintln!(
                "fase35_l: AXON_TEST_DATABASE_URL unset — skipping \
                 real-Postgres integration (set it to run; CI always does)"
            );
            return None;
        }
    };
    let backend = match PostgresStoreBackend::connect(&dsn) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("fase35_l: backend connect failed ({e}) — skipping");
            return None;
        }
    };
    if let Err(e) = backend.ping().await {
        eprintln!("fase35_l: Postgres unreachable ({e}) — skipping");
        return None;
    }
    Some(backend)
}

/// Bind the backend or `return` from the test (graceful skip).
macro_rules! pg_or_skip {
    () => {
        match test_backend().await {
            Some(b) => b,
            None => return,
        }
    };
}

/// Run a raw SQL statement (fixture DDL / seed). Panics on failure —
/// a broken fixture is a test bug, not a graceful skip.
async fn exec(backend: &PostgresStoreBackend, sql: &str) {
    sqlx::query(sql)
        .execute(backend.pool())
        .await
        .unwrap_or_else(|e| panic!("fase35_l fixture SQL failed:\n  {sql}\n  {e}"));
}

/// `DROP` + `CREATE` a fresh fixture table.
async fn fresh_table(backend: &PostgresStoreBackend, table: &str, columns: &str) {
    exec(backend, &format!("DROP TABLE IF EXISTS {table}")).await;
    exec(backend, &format!("CREATE TABLE {table} ({columns})")).await;
}

async fn drop_table(backend: &PostgresStoreBackend, table: &str) {
    exec(backend, &format!("DROP TABLE IF EXISTS {table}")).await;
}

fn text(s: &str) -> SqlValue {
    SqlValue::Text(s.to_string())
}

// ════════════════════════════════════════════════════════════════════
//  Substrate (35.c-f) — real CRUD round-trips
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t1_substrate_insert_then_query_round_trip() {
    let backend = pg_or_skip!();
    let table = "fase35l_t1_substrate";
    fresh_table(&backend, table, "id INTEGER, name TEXT, active BOOLEAN").await;

    let inserted = backend
        .insert(
            table,
            &[
                ("id".into(), SqlValue::Integer(7)),
                ("name".into(), text("alice")),
                ("active".into(), SqlValue::Boolean(true)),
            ],
        )
        .await
        .expect("insert");
    assert_eq!(inserted, 1, "one row persisted");

    let rows = backend.query(table, "id = 7", &nb()).await.expect("query");
    assert_eq!(rows.len(), 1, "the persisted row is retrievable");
    assert_eq!(rows[0].get("name"), Some(&serde_json::json!("alice")));
    assert_eq!(rows[0].get("active"), Some(&serde_json::json!(true)));

    drop_table(&backend, table).await;
}

#[tokio::test]
async fn t2_substrate_mutate_updates_real_rows() {
    let backend = pg_or_skip!();
    let table = "fase35l_t2_mutate";
    fresh_table(&backend, table, "id INTEGER, status TEXT").await;
    backend
        .insert(table, &[("id".into(), SqlValue::Integer(1)), ("status".into(), text("draft"))])
        .await
        .expect("seed");

    let affected = backend
        .mutate(table, "id = 1", &[("status".into(), text("published"))], &nb())
        .await
        .expect("mutate");
    assert_eq!(affected, 1);

    let rows = backend.query(table, "id = 1", &nb()).await.expect("query");
    assert_eq!(rows[0].get("status"), Some(&serde_json::json!("published")));

    drop_table(&backend, table).await;
}

#[tokio::test]
async fn t3_substrate_purge_deletes_real_rows() {
    let backend = pg_or_skip!();
    let table = "fase35l_t3_purge";
    fresh_table(&backend, table, "id INTEGER").await;
    for i in 1..=5 {
        backend
            .insert(table, &[("id".into(), SqlValue::Integer(i))])
            .await
            .expect("seed");
    }

    let purged = backend.purge(table, "id <= 3", &nb()).await.expect("purge");
    assert_eq!(purged, 3, "three rows deleted");
    let survivors = backend.query(table, "", &nb()).await.expect("query");
    assert_eq!(survivors.len(), 2, "two rows survive");

    drop_table(&backend, table).await;
}

// ════════════════════════════════════════════════════════════════════
//  Pillar I (35.g) — confidence_floor filters REAL rows
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t4_pillar_i_confidence_floor_filters_real_rows() {
    let backend = pg_or_skip!();
    let table = "fase35l_t4_epistemic";
    // The reserved `_confidence` column carries each row's stored
    // epistemic confidence (NUMERIC — precision-safe).
    fresh_table(&backend, table, "id INTEGER, _confidence NUMERIC").await;
    // Seed five rows spanning the [0, 1] confidence band.
    for (id, conf) in [(1, "0.95"), (2, "0.50"), (3, "0.80"), (4, "0.10"), (5, "0.99")] {
        exec(
            &backend,
            &format!("INSERT INTO {table} (id, _confidence) VALUES ({id}, {conf})"),
        )
        .await;
    }

    let outcome =
        stream_retrieve(&backend, table, "", BackpressurePolicy::DegradeQuality, 1000, &CancellationFlag::new(), &nb())
            .await
            .expect("stream_retrieve");
    assert_eq!(outcome.rows.len(), 5, "all five rows off the cursor");

    // A confidence_floor of 0.8 keeps only 0.95 / 0.80 / 0.99 — the
    // 0.50 and 0.10 rows are below the floor.
    let floored = enforce_retrieve_floor(mark_retrieved(outcome.rows), Some(0.8));
    assert_eq!(floored.trusted.len(), 3, "three rows at or above the floor");
    assert_eq!(floored.below_floor.len(), 2, "two sub-floor rows filtered");

    drop_table(&backend, table).await;
}

// ════════════════════════════════════════════════════════════════════
//  Pillar III (35.i) — Stream<Row> backpressure over a REAL cursor
// ════════════════════════════════════════════════════════════════════

/// Seed `n` rows into a single-`id`-column table.
async fn seed_n(backend: &PostgresStoreBackend, table: &str, n: i64) {
    fresh_table(backend, table, "id INTEGER").await;
    // One multi-row INSERT keeps the fixture fast.
    let values: Vec<String> = (1..=n).map(|i| format!("({i})")).collect();
    exec(
        backend,
        &format!("INSERT INTO {table} (id) VALUES {}", values.join(", ")),
    )
    .await;
}

#[tokio::test]
async fn t5_pillar_iii_drop_oldest_bounds_a_real_cursor() {
    let backend = pg_or_skip!();
    let table = "fase35l_t5_dropoldest";
    seed_n(&backend, table, 50).await;

    let outcome = stream_retrieve(
        &backend, table, "", BackpressurePolicy::DropOldest, 10, &CancellationFlag::new(),
        &nb(),
    )
    .await
    .expect("stream_retrieve");
    assert_eq!(outcome.rows.len(), 10, "drop_oldest bounds to the window");
    assert_eq!(outcome.total_seen, 50, "the cursor yielded all 50");
    assert_eq!(outcome.dropped, 40, "40 older rows dropped");

    drop_table(&backend, table).await;
}

#[tokio::test]
async fn t6_pillar_iii_pause_upstream_truncates_a_real_cursor() {
    let backend = pg_or_skip!();
    let table = "fase35l_t6_pause";
    seed_n(&backend, table, 50).await;

    let outcome = stream_retrieve(
        &backend, table, "", BackpressurePolicy::PauseUpstream, 10, &CancellationFlag::new(),
        &nb(),
    )
    .await
    .expect("stream_retrieve");
    assert_eq!(outcome.rows.len(), 10, "pause_upstream stops at the bound");
    assert!(outcome.truncated, "more rows existed past the bound");

    drop_table(&backend, table).await;
}

#[tokio::test]
async fn t7_pillar_iii_fail_errors_past_the_bound() {
    let backend = pg_or_skip!();
    let table = "fase35l_t7_fail";
    seed_n(&backend, table, 50).await;

    let result = stream_retrieve(
        &backend, table, "", BackpressurePolicy::Fail, 10, &CancellationFlag::new(),
        &nb(),
    )
    .await;
    assert!(result.is_err(), "fail policy errors on an over-bound result");

    drop_table(&backend, table).await;
}

#[tokio::test]
async fn t8_pillar_iii_cancel_stops_the_real_drain() {
    let backend = pg_or_skip!();
    let table = "fase35l_t8_cancel";
    seed_n(&backend, table, 50).await;

    let cancel = CancellationFlag::new();
    cancel.cancel(); // pre-cancelled
    let outcome = stream_retrieve(
        &backend, table, "", BackpressurePolicy::DegradeQuality, 1000, &cancel,
        &nb(),
    )
    .await
    .expect("stream_retrieve");
    assert!(outcome.cancelled, "a pre-cancelled drain reports cancelled");
    assert!(outcome.rows.is_empty(), "no row consumed under a fired cancel");

    drop_table(&backend, table).await;
}

// ════════════════════════════════════════════════════════════════════
//  Type mapping (35.c) — UUID / TIMESTAMPTZ / NUMERIC / JSONB / BYTEA
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t9_type_mapping_is_json_safe_for_every_supported_type() {
    let backend = pg_or_skip!();
    let table = "fase35l_t9_types";
    fresh_table(
        &backend,
        table,
        "u UUID, ts TIMESTAMPTZ, n NUMERIC, j JSONB, b BYTEA, i INTEGER, f DOUBLE PRECISION",
    )
    .await;
    exec(
        &backend,
        &format!(
            "INSERT INTO {table} (u, ts, n, j, b, i, f) VALUES \
             (gen_random_uuid(), now(), 1234.5678, '{{\"k\":1}}'::jsonb, \
             '\\xDEADBEEF'::bytea, 42, 2.5)"
        ),
    )
    .await;

    let rows = backend.query(table, "", &nb()).await.expect("query");
    assert_eq!(rows.len(), 1);
    let r = &rows[0];
    // The kivi-reported Python pain — UUID / TIMESTAMPTZ / NUMERIC are
    // pre-mapped to JSON-safe values; no monkey-patched encoder needed.
    assert!(r.get("u").unwrap().is_string(), "UUID → string");
    assert!(r.get("ts").unwrap().is_string(), "TIMESTAMPTZ → RFC3339 string");
    assert!(r.get("n").unwrap().is_string(), "NUMERIC → precision-safe string");
    assert!(r.get("j").unwrap().is_object(), "JSONB → JSON object");
    assert!(r.get("b").unwrap().is_string(), "BYTEA → base64 string");
    assert!(r.get("i").unwrap().is_i64(), "INTEGER → JSON number");
    assert!(r.get("f").unwrap().is_f64(), "DOUBLE PRECISION → JSON number");
    assert_eq!(r.get("n").unwrap().as_str(), Some("1234.5678"));

    drop_table(&backend, table).await;
}

// ════════════════════════════════════════════════════════════════════
//  Pillar II (35.h) — audit chain over REAL mutations
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t10_pillar_ii_audit_chain_records_real_mutations() {
    let backend = pg_or_skip!();
    let table = "fase35l_t10_audit";
    fresh_table(&backend, table, "id INTEGER, v TEXT").await;

    // Drive three real mutations + chain each as it happens.
    let mut chain = StoreAuditChain::new();

    let n = backend
        .insert(table, &[("id".into(), SqlValue::Integer(1)), ("v".into(), text("a"))])
        .await
        .expect("insert");
    chain.record(StoreMutationKind::Persist, table, &format!("{n} row(s)"));

    let n = backend
        .mutate(table, "id = 1", &[("v".into(), text("b"))], &nb())
        .await
        .expect("mutate");
    chain.record(StoreMutationKind::Mutate, table, &format!("{n} row(s)"));

    let n = backend.purge(table, "id = 1", &nb()).await.expect("purge");
    chain.record(StoreMutationKind::Purge, table, &format!("{n} row(s)"));

    // The mutation history of three REAL operations verifies Intact.
    assert_eq!(chain.len(), 3);
    assert_eq!(
        chain.verify(),
        ChainVerdict::Intact,
        "the audit chain of three real mutations verifies tamper-free"
    );

    drop_table(&backend, table).await;
}

// ════════════════════════════════════════════════════════════════════
//  Pillar IV (35.j) — capability gate over a REAL resolved backend
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t11_pillar_iv_capability_gates_a_real_postgresql_store() {
    let backend = pg_or_skip!();
    let dsn = std::env::var("AXON_TEST_DATABASE_URL").unwrap();
    let _ = &backend; // the skip-guard already proved Postgres reachable

    // A registry with a capability-gated postgresql store.
    let registry = StoreRegistry::build(&[IRAxonStore {
        node_type: "axonstore",
        source_line: 0,
        source_column: 0,
        name: "vault".to_string(),
        backend: "postgresql".to_string(),
        connection: dsn,
        confidence_floor: None,
        isolation: String::new(),
        on_breach: String::new(),
        capability: "vault.read".to_string(),
    }])
    .expect("registry build");

    // The store resolves to a real Postgres backend.
    let handle = registry.resolve("vault").expect("resolve");
    assert!(matches!(handle, StoreHandle::Postgres(_)));

    // The capability gate denies a caller without `vault.read`...
    let required = registry.spec("vault").unwrap().capability.clone();
    assert!(
        check_store_capability("vault", &required, &["other.cap".to_string()])
            .is_err(),
        "a caller missing vault.read is denied"
    );
    // ...and admits one that holds it.
    assert!(
        check_store_capability("vault", &required, &["vault.read".to_string()])
            .is_ok(),
        "a caller holding vault.read is admitted"
    );
}

// ════════════════════════════════════════════════════════════════════
//  D4 — injection resistance, proven against a real database
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn t12_d4_a_malicious_where_value_cannot_drop_a_real_table() {
    let backend = pg_or_skip!();
    let table = "fase35l_t12_injection";
    fresh_table(&backend, table, "id INTEGER, name TEXT").await;
    backend
        .insert(table, &[("id".into(), SqlValue::Integer(1)), ("name".into(), text("safe"))])
        .await
        .expect("seed");

    // A classic injection payload, fully inside a quoted string value.
    // build_pg_where parameterizes it — Postgres treats it as a literal
    // string to compare, NOT as SQL. The table survives.
    let malicious = format!("name = '; DROP TABLE {table}; --'");
    let rows = backend.query(table, &malicious, &nb()).await.expect("query runs");
    assert!(rows.is_empty(), "no row literally named the payload");

    // The table is still here — the injection was inert.
    let survivors = backend.query(table, "", &nb()).await.expect("table intact");
    assert_eq!(survivors.len(), 1, "the injection did NOT drop the table");

    drop_table(&backend, table).await;
}
