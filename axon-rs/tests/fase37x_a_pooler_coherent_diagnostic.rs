//! §Fase 37.x.a — Diagnostic anchor for the Pooler-Coherent Store cycle.
//!
//! Pins the **post-1.36.5 broken state** of the `axonstore` Postgres
//! backend so every later 37.x sub-fase inverts a specific §-assertion.
//! Same forensic discipline as the 33.a / 34.a / 35.a / 37.a anchors:
//! capture the current behaviour with `eprintln!`, assert it minimally,
//! and let a post-fix regression surface as an anchor-inversion failure.
//!
//! # The four findings (see `docs/fase/fase_37x_pooler_coherent_store.md` §2)
//!
//!  - **A** — `column_types()` introspects on its own `&self.pool`
//!    checkout, separate from the operation's checkout.
//!  - **B** — that introspection resolves the table via `to_regclass`,
//!    which honours the connection's ambient `search_path`.
//!  - **C** — when introspection yields nothing, `build_pg_where`
//!    emits a bare `"col" = $N` — the form that fails `operator does
//!    not exist: uuid = text` against a typed column.
//!  - The schema cache has **no invalidation** — a live `ALTER TABLE`
//!    leaves a `(dsn, table)` entry stale until a process restart.
//!
//! # What this anchor pins — and what it honestly cannot
//!
//! Findings A+B compose into a defect that manifests ONLY behind a
//! transaction-mode pooler: two pool checkouts land on two physical
//! sessions whose `search_path` differs, so introspection resolves the
//! table on one session and the operation runs on another. On a DIRECT
//! connection every checkout shares one DSN-configured `search_path` —
//! introspection and operation are always coherent, and the bug cannot
//! be reproduced. The faithful smoke-15 reproduction therefore needs a
//! real transaction pooler and belongs to **37.x.i**'s PgBouncer
//! harness; it is not forced into a non-deterministic test here.
//!
//! This file pins what IS deterministic now:
//!
//!  - §1 — Finding C, infra-free: an unknown-type equality filter
//!    compiles to a bare `$N` placeholder.        → 37.x.e inverts.
//!  - §2 — schema-anchored operation SQL, infra-free: with a resolved
//!    schema the operation SQL is `"schema"."table"`.
//!                                          → inverted by 37.x.c (D2).
//!  - §3 — the stale schema cache, real-Postgres: a `(dsn, table)`
//!    entry survives a live `ALTER TABLE` and miscasts the next
//!    operation.                                  → 37.x.f / D9 inverts.
//!  - §4 — multi-schema resolution, real-Postgres: a table present in
//!    two schemas resolves silently by `search_path` order, with no
//!    ambiguity signal.                  → 37.x.b / D1 + D5 invert/keep.
//!  - §5 — totality, infra-free: ALL FOUR pure SQL builders emit the
//!    schema-qualified relation when a schema resolved.
//!                                          → inverted by 37.x.c (D2).

use std::collections::HashMap;

use axon::store::filter::{build_pg_where, SqlValue};
use axon::store::postgres_backend::{
    build_delete_sql, build_insert_sql, build_select_sql, build_update_sql,
    PostgresStoreBackend,
};

/// A real `tenant_id` of an adopter Postgres schema (the smoke-15
/// value) — a `uuid` primary key, the column class this cycle exists
/// to make work.
const ADOPTER_UUID: &str = "83d078e1-b372-42ba-9572-ff8dc521386e";

/// An empty bindings / column-types map — the unknown-schema state.
fn empty() -> HashMap<String, String> {
    HashMap::new()
}

// ════════════════════════════════════════════════════════════════════
//  §1 — Finding C (infra-free): an unknown-type equality filter
//        compiles to a BARE `$N` placeholder.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s1_unknown_type_equality_filter_renders_a_bare_placeholder() {
    // The canonical request-bound agent filter: `${tenant_id}` from the
    // request body (Fase 37) reaches the `where:` clause as a bind
    // value. The column's type is unknown — `column_types` is empty
    // (introspection saw nothing). `build_pg_where` then emits a bare
    // `"id" = $1`: sqlx binds `$1` as Postgres `text`, so against a
    // `uuid` column Postgres looks for `uuid = text` — and fails.
    let bindings =
        HashMap::from([("tenant_id".to_string(), ADOPTER_UUID.to_string())]);

    let (clause, params) =
        build_pg_where("id == '${tenant_id}'", 0, &bindings, &empty())
            .expect("the where-expression compiles");

    eprintln!(
        "§1 anchor (Finding C — unknown-type equality → bare $N):\n\
         where-expr     = id == '${{tenant_id}}'\n\
         column_types   = {{}}  (empty — introspection saw nothing)\n\
         rendered WHERE = {clause:?}\n\
         bound params   = {params:?}\n\
         CONCLUSION: the clause is a BARE `\"id\" = $1`. $1 is bound as\n\
         Postgres `text`; against a `uuid` column this is the adopter's\n\
         `operator does not exist: uuid = text`.  37.x.e (D4) inverts\n\
         this to the type-agnostic `\"id\"::text = $1` for equality."
    );

    assert_eq!(
        clause, "\"id\" = $1",
        "§1: today an unknown-type equality renders a bare `$N` — no \
         `::type` cast, no `::text` column cast. 37.x.e (D4) inverts it."
    );
    assert!(
        !clause.contains("::"),
        "§1: there is NO cast of any kind on the bare placeholder — the \
         exact shape that fails `uuid = text`"
    );
    assert_eq!(
        params,
        vec![SqlValue::Text(ADOPTER_UUID.to_string())],
        "§1: the request-bound value is carried as a `text` parameter"
    );
}

// ════════════════════════════════════════════════════════════════════
//  §2 — Schema-anchored operation SQL (infra-free). 37.x.c (D2)
//        INVERTED this anchor: with a resolved schema the operation SQL
//        is emitted SCHEMA-QUALIFIED — `"public"."tenants"` — so it no
//        longer rides the ambient `search_path`. A `None` schema keeps
//        the bare pre-37.x form (D5).
// ════════════════════════════════════════════════════════════════════

#[test]
fn s2_operation_sql_is_schema_qualified_when_resolved() {
    // §37.x.c (D2) — given a resolved schema, the SELECT and INSERT name
    // the relation SCHEMA-QUALIFIED. `None` (resolution failed) keeps
    // the bare pre-37.x form. (The cast-less `$1` on an unknown-type
    // column stays pinned for D1+D8 / 37.x.g.)
    let (qualified, _) = build_select_sql(
        "tenants",
        Some("public"),
        "id == '${t}'",
        &empty(),
        &empty(),
    )
    .expect("build_select_sql");
    let (bare, _) =
        build_select_sql("tenants", None, "id == '${t}'", &empty(), &empty())
            .expect("build_select_sql");
    let (insert_sql, _) = build_insert_sql(
        "chat_history",
        Some("public"),
        &[("tenant_id".to_string(), SqlValue::Text(ADOPTER_UUID.to_string()))],
        &empty(),
    )
    .expect("build_insert_sql");

    eprintln!(
        "§2 (37.x.c — D2 schema-anchored operation SQL):\n\
         SELECT (schema resolved) = {qualified:?}\n\
         SELECT (schema absent)   = {bare:?}\n\
         INSERT (schema resolved) = {insert_sql:?}\n\
         CONCLUSION: a resolved schema renders `\"public\".\"tenants\"` —\n\
         the operation no longer rides the ambient `search_path`. A\n\
         `None` schema (resolution failed) keeps the bare form (D5)."
    );

    assert_eq!(
        qualified, "SELECT * FROM \"public\".\"tenants\" WHERE \"id\" = $1",
        "§2 (D2): a resolved schema → the SELECT is schema-qualified"
    );
    assert_eq!(
        bare, "SELECT * FROM \"tenants\" WHERE \"id\" = $1",
        "§2 (D5): a `None` schema → the bare pre-37.x form, unchanged"
    );
    assert_eq!(
        insert_sql,
        "INSERT INTO \"public\".\"chat_history\" (\"tenant_id\") VALUES ($1)",
        "§2 (D2): the INSERT is schema-qualified too; the cast-less `$1` \
         on an unknown-type column stays pinned for D1+D8 (37.x.g)"
    );
}

// ════════════════════════════════════════════════════════════════════
//  §5 — Totality (infra-free). 37.x.c (D2) INVERTED this anchor: ALL
//        FOUR pure SQL builders now emit the SCHEMA-QUALIFIED relation
//        when a schema resolved — D2 flipped every one, not three.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s5_all_four_sql_builders_qualify_with_a_resolved_schema() {
    // The store-op SQL surface is exactly four pure builders. §37.x.c
    // (D2) — each emits `"schema"."t"` given a resolved schema; this
    // guards the totality so a regression cannot fix three and miss the
    // fourth.
    let data = [("v".to_string(), SqlValue::Integer(1))];
    let sqls: Vec<(&str, String)> = vec![
        (
            "build_select_sql",
            build_select_sql("t", Some("app"), "", &empty(), &empty())
                .unwrap()
                .0,
        ),
        (
            "build_delete_sql",
            build_delete_sql("t", Some("app"), "", &empty(), &empty())
                .unwrap()
                .0,
        ),
        (
            "build_insert_sql",
            build_insert_sql("t", Some("app"), &data, &empty()).unwrap().0,
        ),
        (
            "build_update_sql",
            build_update_sql("t", Some("app"), "", &data, &empty(), &empty())
                .unwrap()
                .0,
        ),
    ];

    for (name, sql) in &sqls {
        eprintln!("§5 ({name}): {sql:?}");
        assert!(
            sql.contains("\"app\".\"t\""),
            "§5 (D2): `{name}` must emit the schema-qualified \
             `\"app\".\"t\"` — D2 flips ALL FOUR builders"
        );
    }
    assert_eq!(sqls.len(), 4, "§5: the store-op SQL surface is 4 builders");
}

// ════════════════════════════════════════════════════════════════════
//  Real-Postgres harness — §3 + §4 (graceful skip without a database)
// ════════════════════════════════════════════════════════════════════

/// Resolve the test database backend, or `None` to skip — identical
/// discipline to `fase35_l`'s harness: unset env var OR an unreachable
/// Postgres skips gracefully so `cargo test` passes on a bare machine.
async fn test_backend() -> Option<PostgresStoreBackend> {
    let dsn = match std::env::var("AXON_TEST_DATABASE_URL") {
        Ok(d) if !d.trim().is_empty() => d,
        _ => {
            eprintln!(
                "fase37x_a: AXON_TEST_DATABASE_URL unset — skipping the \
                 real-Postgres anchors (set it to run; CI always does)"
            );
            return None;
        }
    };
    let backend = match PostgresStoreBackend::connect(&dsn) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("fase37x_a: backend connect failed ({e}) — skipping");
            return None;
        }
    };
    if let Err(e) = backend.ping().await {
        eprintln!("fase37x_a: Postgres unreachable ({e}) — skipping");
        return None;
    }
    Some(backend)
}

/// Run a raw SQL statement (fixture DDL). Panics on failure — a broken
/// fixture is a test bug, not a graceful skip.
async fn exec(backend: &PostgresStoreBackend, sql: &str) {
    sqlx::query(sql)
        .execute(backend.pool())
        .await
        .unwrap_or_else(|e| panic!("fase37x_a fixture SQL failed:\n  {sql}\n  {e}"));
}

// ════════════════════════════════════════════════════════════════════
//  §3 — The stale schema cache (real-Postgres): a `(dsn, table)` entry
//        survives a live `ALTER TABLE` and miscasts the next operation.
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn s3_schema_cache_is_stale_after_a_live_alter_table() {
    let backend = match test_backend().await {
        Some(b) => b,
        None => return,
    };
    let table = "fase37xa_s3_stale";

    exec(&backend, &format!("DROP TABLE IF EXISTS {table}")).await;
    exec(&backend, &format!("CREATE TABLE {table} (probe uuid, label text)")).await;

    // Seed + a first retrieve: this populates the process-global
    // `SCHEMA_CACHE` for `(dsn, table)` with `{probe: uuid, label: text}`
    // and the typed-column filter works (`"probe" = $1::uuid`).
    backend
        .insert(
            table,
            &[
                ("probe".to_string(), SqlValue::Text(ADOPTER_UUID.to_string())),
                ("label".to_string(), SqlValue::Text("v1".to_string())),
            ],
        )
        .await
        .expect("§3: seed insert");
    let before = backend
        .query(table, &format!("probe = '{ADOPTER_UUID}'"), &empty())
        .await;
    eprintln!("§3 anchor — query BEFORE the ALTER: {:?}", before.is_ok());
    assert!(
        before.is_ok(),
        "§3 precondition: the typed-column filter works before the \
         ALTER (and the cache is now populated)"
    );

    // A live schema migration: `probe` becomes `text`. The process
    // schema cache still holds the STALE `{probe: uuid}` mapping.
    exec(
        &backend,
        &format!("ALTER TABLE {table} ALTER COLUMN probe TYPE text USING probe::text"),
    )
    .await;

    // The next retrieve hits the STALE cache → casts `$1::uuid` against
    // a column that is now `text` → `operator does not exist: text = uuid`.
    let after = backend
        .query(table, &format!("probe = '{ADOPTER_UUID}'"), &empty())
        .await;
    eprintln!(
        "§3 anchor (stale schema cache after ALTER TABLE):\n\
         after-ALTER query result = {after:?}\n\
         CONCLUSION: the cached `{{probe: uuid}}` entry survived the\n\
         ALTER; the next op miscasts `$1::uuid` against the now-`text`\n\
         column and FAILS. The cache has no invalidation. 37.x.f (D9)\n\
         inverts: a schema-drift SQLSTATE evicts the entry + retries."
    );
    assert!(
        after.is_err(),
        "§3: after a live `ALTER COLUMN ... TYPE`, the next operation \
         fails on the STALE cached column type — the cache has no \
         invalidation. 37.x.f (D9) makes it self-heal."
    );

    exec(&backend, &format!("DROP TABLE IF EXISTS {table}")).await;
}

// ════════════════════════════════════════════════════════════════════
//  §4 — Multi-schema resolution (real-Postgres): a table present in
//        two schemas resolves silently by `search_path` order.
// ════════════════════════════════════════════════════════════════════

#[tokio::test]
async fn s4_multi_schema_table_resolves_silently_by_search_path_order() {
    let base = match std::env::var("AXON_TEST_DATABASE_URL") {
        Ok(d) if !d.trim().is_empty() => d,
        _ => {
            eprintln!("fase37x_a s4: AXON_TEST_DATABASE_URL unset — skipping");
            return;
        }
    };
    let schema_a = "axon_f37xa_amb_a";
    let schema_b = "axon_f37xa_amb_b";
    let table = "dup_widgets";

    // Connect with a `search_path` that lists BOTH schemas, A before B.
    let sep = if base.contains('?') { '&' } else { '?' };
    let dsn = format!(
        "{base}{sep}options=-c%20search_path%3D{schema_a}%2C{schema_b}"
    );
    let backend = match PostgresStoreBackend::connect(&dsn) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("fase37x_a s4: connect failed ({e}) — skipping");
            return;
        }
    };
    if backend.ping().await.is_err() {
        eprintln!("fase37x_a s4: Postgres unreachable — skipping");
        return;
    }

    // The SAME table name in two schemas — the topology of a
    // schema-per-tenant adopter, or a legacy + working-schema overlap.
    for (schema, which) in [(schema_a, "from_schema_a"), (schema_b, "from_schema_b")]
    {
        exec(&backend, &format!("CREATE SCHEMA IF NOT EXISTS {schema}")).await;
        exec(&backend, &format!("DROP TABLE IF EXISTS {schema}.{table}")).await;
        exec(&backend, &format!("CREATE TABLE {schema}.{table} (which text)")).await;
        exec(
            &backend,
            &format!("INSERT INTO {schema}.{table} (which) VALUES ('{which}')"),
        )
        .await;
    }

    // Skip if the host/pooler dropped the `search_path` option (so the
    // unqualified name cannot resolve at all) — orthogonal to this pin.
    let resolves: Option<String> =
        sqlx::query_scalar(&format!("SELECT to_regclass('\"{table}\"')::text"))
            .fetch_one(backend.pool())
            .await
            .unwrap_or(None);
    if resolves.is_none() {
        eprintln!("fase37x_a s4: search_path option not honoured — skipping");
        for s in [schema_a, schema_b] {
            exec(&backend, &format!("DROP SCHEMA IF EXISTS {s} CASCADE")).await;
        }
        return;
    }

    // An unqualified `retrieve` resolves SILENTLY to the first schema on
    // the `search_path` — no ambiguity signal, no diagnostic.
    let rows = backend
        .query(table, "", &empty())
        .await
        .expect("§4: the unqualified retrieve resolves");
    let picked = rows.first().and_then(|r| r.get("which")).cloned();

    eprintln!(
        "§4 anchor (multi-schema → silent search_path-order resolution):\n\
         `{table}` exists in BOTH {schema_a} and {schema_b}\n\
         retrieve resolved {} row(s); picked `which` = {picked:?}\n\
         CONCLUSION: resolution is SILENT — `to_regclass` takes the\n\
         first `search_path` match, no ambiguity diagnostic. 37.x.b\n\
         (D1) keeps this resolvable case working (D5) and adds an\n\
         honest ambiguity error for the genuinely-unresolvable variant.",
        rows.len()
    );
    assert_eq!(
        picked,
        Some(serde_json::json!("from_schema_a")),
        "§4: today a multi-schema table resolves silently to the FIRST \
         `search_path` schema — no ambiguity error. 37.x.b (D1) keeps \
         this (D5) but makes the unresolvable-ambiguous case honest."
    );

    for s in [schema_a, schema_b] {
        exec(&backend, &format!("DROP SCHEMA IF EXISTS {s} CASCADE")).await;
    }
}
