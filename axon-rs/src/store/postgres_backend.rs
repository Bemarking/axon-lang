//! §Fase 35.c (v1.30.0) — `PostgresStoreBackend`, the SQL substrate of
//! the `axonstore` cognitive data plane.
//!
//! This module makes `axonstore { backend: postgresql }` real: the four
//! store operations — `query` (retrieve), `insert` (persist), `mutate`,
//! `purge` — execute parameterized SQL against a `sqlx::PgPool` instead
//! of the key-value path. It is the substrate the four pillars (35.g-j)
//! enrich.
//!
//! # D6 — connection resolution
//!
//! [`resolve_dsn`] honors `connection: "env:VAR"` (resolve the named
//! environment variable) and a literal DSN. A missing env var is a
//! named [`StoreError::MissingEnvVar`] — never a panic, never a silent
//! fallback to the key-value store.
//!
//! # D7 — pooling + honest typed failure surface
//!
//! [`PostgresStoreBackend::connect`] builds ONE lazy, bounded
//! `sqlx::PgPool` (`connect_lazy` — no connection is opened until the
//! first operation). Every failure path — empty connection, missing
//! env var, malformed DSN, connect failure, SQL error, an unsupported
//! column type, a decode failure — surfaces as a typed [`StoreError`].
//! No panic; no silent empty result masking a failed query.
//!
//! # D4 — injection-proof, identifiers included
//!
//! Values flow through 35.b's [`build_pg_where`] as `$N` bind
//! placeholders. The *identifier* surface — table names and
//! `insert`/`mutate` column names, which ARE interpolated into SQL
//! text — is validated against [`filter::is_safe_identifier`]
//! (`[A-Za-z_]\w*`, ≤ 63 bytes) before being double-quoted. No
//! untrusted identifier reaches SQL.
//!
//! # Architecture — pure builders + thin async execution
//!
//! SQL construction ([`build_select_sql`], [`build_insert_sql`],
//! [`build_update_sql`], [`build_delete_sql`]) is **pure and total** —
//! no I/O — and therefore exhaustively unit-tested here without a
//! database. The async methods are thin: build → bind → execute. The
//! row-decode path and live execution are proven against a real
//! Postgres in 35.l (the integration harness).
//!
//! # Honest scope (D12)
//!
//! No DDL: `IRAxonStore` carries no column schema, so v1.30.0 operates
//! against existing tables (no `CREATE TABLE` / `migrate` / index). Each
//! operation is a single-statement autocommit; the multi-statement
//! `transact { … }` block is a documented future fase. The supported
//! column-type catalog is [`classify_pg_type`]; a column outside it is
//! a clear [`StoreError::UnsupportedColumnType`], not a silent miss.

use std::fmt;
use std::time::Duration;

use serde_json::Value as JsonValue;
use sqlx::postgres::{PgArguments, PgPoolOptions, PgRow};
use sqlx::query::Query;
use sqlx::{Column, PgPool, Postgres, Row, TypeInfo};

use crate::store::epistemic::EpistemicError;
use crate::store::filter::{self, build_pg_where, FilterError, SqlValue};

/// Upper bound on pooled connections per backend (D7 — bounded).
const MAX_POOL_CONNECTIONS: u32 = 10;
/// How long to wait to acquire a pooled connection before failing.
const ACQUIRE_TIMEOUT_SECS: u64 = 5;
/// How long an idle pooled connection is kept before being reaped.
const IDLE_TIMEOUT_SECS: u64 = 300;

// ════════════════════════════════════════════════════════════════════
//  Error catalog (typed, total — D7)
// ════════════════════════════════════════════════════════════════════

/// Every way an `axonstore` SQL operation can fail. The backend is
/// total: it returns one of these or a result — never a panic, never a
/// silent empty result masking a failure.
#[derive(Debug, Clone, PartialEq)]
pub enum StoreError {
    /// `connection` was empty or whitespace-only.
    EmptyConnection,
    /// `connection` was the bare prefix `env:` with no variable name.
    EmptyEnvVarName,
    /// `connection: "env:VAR"` and `VAR` is unset (or not UTF-8).
    MissingEnvVar { var: String },
    /// The resolved DSN is malformed — `connect_lazy` rejected it.
    PoolInit { dsn_masked: String, source: String },
    /// A table or column identifier failed the `[A-Za-z_]\w*` / 63-byte
    /// safety check (D4 — no untrusted identifier reaches SQL).
    InvalidIdentifier { kind: &'static str, name: String },
    /// `insert` / `mutate` was called with no column data.
    EmptyData { op: &'static str },
    /// The `where` expression did not compile (delegates to 35.b).
    Filter(FilterError),
    /// A `confidence_floor` violation — a sub-floor or un-elevated
    /// `persist` (delegates to 35.g's Pillar I epistemic data plane).
    Epistemic(EpistemicError),
    /// A live connection could not be acquired / the ping failed.
    Connect { source: String },
    /// A SQL statement failed at execution time.
    Query { op: &'static str, source: String },
    /// A retrieved column has a type outside the supported catalog
    /// ([`classify_pg_type`]). Honest scope, not a silent miss.
    UnsupportedColumnType { column: String, pg_type: String },
    /// A retrieved column of a supported type failed to decode.
    Decode { column: String, pg_type: String, source: String },
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::EmptyConnection => write!(
                f,
                "axonstore `connection` is empty — expected a DSN or an \
                 `env:VARNAME` reference"
            ),
            StoreError::EmptyEnvVarName => write!(
                f,
                "axonstore `connection` is the bare prefix `env:` with no \
                 variable name"
            ),
            StoreError::MissingEnvVar { var } => write!(
                f,
                "axonstore `connection: \"env:{var}\"` — environment \
                 variable `{var}` is not set (or not valid UTF-8)"
            ),
            StoreError::PoolInit { dsn_masked, source } => write!(
                f,
                "axonstore connection pool could not be initialised for \
                 `{dsn_masked}`: {source}"
            ),
            StoreError::InvalidIdentifier { kind, name } => write!(
                f,
                "unsafe {kind} identifier `{name}` — must match \
                 [A-Za-z_][A-Za-z0-9_]* and be ≤ 63 bytes"
            ),
            StoreError::EmptyData { op } => write!(
                f,
                "axonstore `{op}` was given no column data"
            ),
            StoreError::Filter(e) => write!(f, "where-expression: {e}"),
            StoreError::Epistemic(e) => write!(f, "{e}"),
            StoreError::Connect { source } => {
                write!(f, "axonstore could not reach the database: {source}")
            }
            StoreError::Query { op, source } => {
                write!(f, "axonstore `{op}` SQL failed: {source}")
            }
            StoreError::UnsupportedColumnType { column, pg_type } => write!(
                f,
                "column `{column}` has Postgres type `{pg_type}`, outside \
                 the v1.30.0 supported catalog"
            ),
            StoreError::Decode { column, pg_type, source } => write!(
                f,
                "column `{column}` (`{pg_type}`) failed to decode: {source}"
            ),
        }
    }
}

impl std::error::Error for StoreError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            StoreError::Filter(e) => Some(e),
            StoreError::Epistemic(e) => Some(e),
            _ => None,
        }
    }
}

impl From<FilterError> for StoreError {
    fn from(e: FilterError) -> Self {
        StoreError::Filter(e)
    }
}

impl From<EpistemicError> for StoreError {
    fn from(e: EpistemicError) -> Self {
        StoreError::Epistemic(e)
    }
}

// ════════════════════════════════════════════════════════════════════
//  D6 — connection resolution
// ════════════════════════════════════════════════════════════════════

/// Resolve an `axonstore` `connection` string into a concrete DSN.
///
/// - `"env:VAR"` → the value of environment variable `VAR`.
/// - any other non-empty value → a literal DSN, returned verbatim.
///
/// Leading/trailing whitespace is trimmed. An empty connection, a bare
/// `env:`, or a missing environment variable is a typed [`StoreError`]
/// — never a panic, never a silent fallback.
pub fn resolve_dsn(connection: &str) -> Result<String, StoreError> {
    let conn = connection.trim();
    if conn.is_empty() {
        return Err(StoreError::EmptyConnection);
    }
    match conn.strip_prefix("env:") {
        Some(var) => {
            let var = var.trim();
            if var.is_empty() {
                return Err(StoreError::EmptyEnvVarName);
            }
            std::env::var(var).map_err(|_| StoreError::MissingEnvVar {
                var: var.to_string(),
            })
        }
        None => Ok(conn.to_string()),
    }
}

/// Mask the password segment of a DSN for safe logging / `Debug`.
fn mask_dsn(dsn: &str) -> String {
    if let Some(at) = dsn.find('@') {
        if let Some(colon) = dsn[..at].rfind(':') {
            return format!("{}***{}", &dsn[..=colon], &dsn[at..]);
        }
    }
    dsn.to_string()
}

/// Validate a table / column identifier, mapping a failure to a typed
/// [`StoreError::InvalidIdentifier`] (D4).
fn check_identifier(name: &str, kind: &'static str) -> Result<(), StoreError> {
    if filter::is_safe_identifier(name) {
        Ok(())
    } else {
        Err(StoreError::InvalidIdentifier {
            kind,
            name: name.to_string(),
        })
    }
}

// ════════════════════════════════════════════════════════════════════
//  Pure SQL builders (no I/O — exhaustively unit-tested)
// ════════════════════════════════════════════════════════════════════

/// Build a parameterized `SELECT * FROM "table" WHERE …` statement.
///
/// §Fase 37.d (D3) — `bindings` resolves `${name}` placeholders in the
/// `where` expression to `$N` bind parameters (never string-spliced).
pub fn build_select_sql(
    table: &str,
    where_expr: &str,
    bindings: &std::collections::HashMap<String, String>,
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    let (clause, params) = build_pg_where(where_expr, 0, bindings)?;
    Ok((format!("SELECT * FROM \"{table}\" WHERE {clause}"), params))
}

/// Build a parameterized `DELETE FROM "table" WHERE …` statement.
pub fn build_delete_sql(
    table: &str,
    where_expr: &str,
    bindings: &std::collections::HashMap<String, String>,
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    let (clause, params) = build_pg_where(where_expr, 0, bindings)?;
    Ok((format!("DELETE FROM \"{table}\" WHERE {clause}"), params))
}

/// Build a parameterized `INSERT INTO "table" (…) VALUES (…)`.
///
/// A `NULL` data value renders as the inline `NULL` keyword (a fixed
/// SQL token, injection-safe) and consumes no `$N` placeholder — the
/// same discipline 35.b applies to `NULL` in a `where` clause. Postgres
/// infers the column type for an inline `NULL`.
pub fn build_insert_sql(
    table: &str,
    data: &[(String, SqlValue)],
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    if data.is_empty() {
        return Err(StoreError::EmptyData { op: "insert" });
    }

    let mut columns: Vec<String> = Vec::with_capacity(data.len());
    let mut value_frags: Vec<String> = Vec::with_capacity(data.len());
    let mut params: Vec<SqlValue> = Vec::new();
    let mut idx = 1usize;

    for (col, val) in data {
        check_identifier(col, "column")?;
        columns.push(format!("\"{col}\""));
        match val {
            SqlValue::Null => value_frags.push("NULL".to_string()),
            bound => {
                value_frags.push(format!("${idx}"));
                params.push(bound.clone());
                idx += 1;
            }
        }
    }

    let sql = format!(
        "INSERT INTO \"{table}\" ({}) VALUES ({})",
        columns.join(", "),
        value_frags.join(", "),
    );
    Ok((sql, params))
}

/// Build a parameterized `UPDATE "table" SET … WHERE …`.
///
/// The `WHERE` placeholders continue the numbering after the `SET`
/// placeholders **actually emitted** — not after the column count.
/// Because a `NULL` `SET` value renders inline (no placeholder), the
/// offset is the count of non-`NULL` `SET` values. (The frozen Python
/// reference offsets by column count and so mis-numbers the moment a
/// `SET` value is `NULL`.)
pub fn build_update_sql(
    table: &str,
    where_expr: &str,
    data: &[(String, SqlValue)],
    bindings: &std::collections::HashMap<String, String>,
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    if data.is_empty() {
        return Err(StoreError::EmptyData { op: "mutate" });
    }

    let mut set_frags: Vec<String> = Vec::with_capacity(data.len());
    let mut params: Vec<SqlValue> = Vec::new();
    let mut idx = 1usize;

    for (col, val) in data {
        check_identifier(col, "column")?;
        match val {
            SqlValue::Null => set_frags.push(format!("\"{col}\" = NULL")),
            bound => {
                set_frags.push(format!("\"{col}\" = ${idx}"));
                params.push(bound.clone());
                idx += 1;
            }
        }
    }

    // `idx - 1` SET placeholders were emitted; WHERE continues there.
    let set_param_count = idx - 1;
    let (clause, where_params) =
        build_pg_where(where_expr, set_param_count, bindings)?;
    params.extend(where_params);

    let sql = format!(
        "UPDATE \"{table}\" SET {} WHERE {clause}",
        set_frags.join(", "),
    );
    Ok((sql, params))
}

// ════════════════════════════════════════════════════════════════════
//  Column-type catalog (D12 honest scope) + row → JSON mapping
// ════════════════════════════════════════════════════════════════════

/// The supported Postgres column-type classes. A column whose type is
/// outside this closed catalog is a [`StoreError::UnsupportedColumnType`]
/// — an honest, documented boundary rather than a silent miss.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PgTypeClass {
    /// `BOOL`
    Bool,
    /// `INT2` (smallint)
    Int2,
    /// `INT4` (integer)
    Int4,
    /// `INT8` (bigint)
    Int8,
    /// `FLOAT4` (real)
    Float4,
    /// `FLOAT8` (double precision)
    Float8,
    /// `NUMERIC` / `DECIMAL` — JSON-encoded as a string (precision-safe)
    Numeric,
    /// `TEXT` / `VARCHAR` / `BPCHAR` / `NAME`
    Text,
    /// `UUID` — JSON-encoded as a hyphenated string
    Uuid,
    /// `TIMESTAMPTZ` — JSON-encoded as an RFC 3339 string
    TimestampTz,
    /// `TIMESTAMP` — JSON-encoded as an ISO 8601 (no-zone) string
    Timestamp,
    /// `DATE` — JSON-encoded as a `YYYY-MM-DD` string
    Date,
    /// `TIME` — JSON-encoded as a `HH:MM:SS` string
    Time,
    /// `JSON` / `JSONB` — passed through as the JSON value
    Json,
    /// `BYTEA` — JSON-encoded as a base64 string
    Bytea,
}

/// Classify a Postgres type name into a [`PgTypeClass`], or `None` if
/// the type is outside the v1.30.0 supported catalog. Pure + total.
pub fn classify_pg_type(pg_type: &str) -> Option<PgTypeClass> {
    Some(match pg_type.to_ascii_uppercase().as_str() {
        "BOOL" => PgTypeClass::Bool,
        "INT2" => PgTypeClass::Int2,
        "INT4" => PgTypeClass::Int4,
        "INT8" => PgTypeClass::Int8,
        "FLOAT4" => PgTypeClass::Float4,
        "FLOAT8" => PgTypeClass::Float8,
        "NUMERIC" => PgTypeClass::Numeric,
        "TEXT" | "VARCHAR" | "BPCHAR" | "NAME" => PgTypeClass::Text,
        "UUID" => PgTypeClass::Uuid,
        "TIMESTAMPTZ" => PgTypeClass::TimestampTz,
        "TIMESTAMP" => PgTypeClass::Timestamp,
        "DATE" => PgTypeClass::Date,
        "TIME" => PgTypeClass::Time,
        "JSON" | "JSONB" => PgTypeClass::Json,
        "BYTEA" => PgTypeClass::Bytea,
        _ => return None,
    })
}

/// A single retrieved row, as JSON-safe column → value pairs in column
/// order. Every value is `serde_json`-representable — UUID, TIMESTAMPTZ
/// and NUMERIC are pre-mapped to strings, so an adopter never has to
/// monkey-patch a JSON encoder (the kivi-reported Python pain).
#[derive(Debug, Clone, PartialEq)]
pub struct StoreRow {
    /// Column name → JSON value, in `SELECT` column order.
    pub columns: Vec<(String, JsonValue)>,
}

impl StoreRow {
    /// Look up a column's value by name.
    pub fn get(&self, column: &str) -> Option<&JsonValue> {
        self.columns
            .iter()
            .find(|(name, _)| name == column)
            .map(|(_, value)| value)
    }

    /// Render the row as a JSON object.
    pub fn to_json(&self) -> JsonValue {
        JsonValue::Object(self.columns.iter().cloned().collect())
    }
}

/// Decode one column of a `PgRow` into a JSON-safe value.
fn pg_value_to_json(
    row: &PgRow,
    idx: usize,
    column: &str,
    pg_type: &str,
) -> Result<JsonValue, StoreError> {
    let class = classify_pg_type(pg_type).ok_or_else(|| {
        StoreError::UnsupportedColumnType {
            column: column.to_string(),
            pg_type: pg_type.to_string(),
        }
    })?;

    // Each branch decodes as `Option<T>` so a SQL `NULL` maps to
    // `JsonValue::Null` rather than failing the decode.
    macro_rules! decode {
        ($t:ty, $conv:expr) => {{
            let opt: Option<$t> = row.try_get(idx).map_err(|e| {
                StoreError::Decode {
                    column: column.to_string(),
                    pg_type: pg_type.to_string(),
                    source: e.to_string(),
                }
            })?;
            match opt {
                None => JsonValue::Null,
                Some(v) => $conv(v),
            }
        }};
    }

    Ok(match class {
        PgTypeClass::Bool => decode!(bool, JsonValue::Bool),
        PgTypeClass::Int2 => decode!(i16, |v| JsonValue::from(v as i64)),
        PgTypeClass::Int4 => decode!(i32, |v| JsonValue::from(v as i64)),
        PgTypeClass::Int8 => decode!(i64, JsonValue::from),
        PgTypeClass::Float4 => decode!(f32, |v| JsonValue::from(v as f64)),
        PgTypeClass::Float8 => decode!(f64, JsonValue::from),
        PgTypeClass::Numeric => {
            decode!(sqlx::types::BigDecimal, |v: sqlx::types::BigDecimal| {
                JsonValue::String(v.to_string())
            })
        }
        PgTypeClass::Text => decode!(String, JsonValue::String),
        PgTypeClass::Uuid => {
            decode!(uuid::Uuid, |v: uuid::Uuid| JsonValue::String(
                v.hyphenated().to_string()
            ))
        }
        PgTypeClass::TimestampTz => {
            decode!(
                chrono::DateTime<chrono::Utc>,
                |v: chrono::DateTime<chrono::Utc>| JsonValue::String(
                    v.to_rfc3339()
                )
            )
        }
        PgTypeClass::Timestamp => {
            decode!(chrono::NaiveDateTime, |v: chrono::NaiveDateTime| {
                JsonValue::String(
                    v.format("%Y-%m-%dT%H:%M:%S%.f").to_string(),
                )
            })
        }
        PgTypeClass::Date => {
            decode!(chrono::NaiveDate, |v: chrono::NaiveDate| {
                JsonValue::String(v.to_string())
            })
        }
        PgTypeClass::Time => {
            decode!(chrono::NaiveTime, |v: chrono::NaiveTime| {
                JsonValue::String(v.to_string())
            })
        }
        PgTypeClass::Json => decode!(JsonValue, |v| v),
        PgTypeClass::Bytea => decode!(Vec<u8>, |v: Vec<u8>| {
            use base64::Engine;
            JsonValue::String(
                base64::engine::general_purpose::STANDARD.encode(v),
            )
        }),
    })
}

/// Map a whole `PgRow` to a [`StoreRow`]. `pub(crate)` so 35.i's
/// `row_stream` cursor drain shares one row-decode path with `query`.
pub(crate) fn map_pg_row(row: &PgRow) -> Result<StoreRow, StoreError> {
    let mut columns = Vec::with_capacity(row.len());
    for (idx, col) in row.columns().iter().enumerate() {
        let name = col.name().to_string();
        let pg_type = col.type_info().name().to_string();
        let value = pg_value_to_json(row, idx, &name, &pg_type)?;
        columns.push((name, value));
    }
    Ok(StoreRow { columns })
}

/// Bind one [`SqlValue`] onto a query. `NULL` is rendered inline by the
/// builders and so never reaches this function in practice; the `Null`
/// arm binds a typed NULL defensively to keep the function total.
/// `pub(crate)` so 35.i's `row_stream` binds cursor-query params
/// through the same path.
pub(crate) fn bind_value<'q>(
    q: Query<'q, Postgres, PgArguments>,
    value: &SqlValue,
) -> Query<'q, Postgres, PgArguments> {
    match value {
        SqlValue::Text(s) => q.bind(s.clone()),
        SqlValue::Integer(n) => q.bind(*n),
        SqlValue::Float(x) => q.bind(*x),
        SqlValue::Boolean(b) => q.bind(*b),
        SqlValue::Null => q.bind(Option::<String>::None),
    }
}

// ════════════════════════════════════════════════════════════════════
//  PostgresStoreBackend
// ════════════════════════════════════════════════════════════════════

/// A Postgres-backed `axonstore`. Holds one lazy, bounded `PgPool`.
/// Cheap to [`Clone`] (the pool is internally reference-counted).
#[derive(Clone)]
pub struct PostgresStoreBackend {
    /// The resolved DSN — masked whenever surfaced (`Debug`, errors).
    dsn: String,
    pool: PgPool,
}

impl fmt::Debug for PostgresStoreBackend {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Never expose the DSN password through `Debug`.
        f.debug_struct("PostgresStoreBackend")
            .field("dsn", &mask_dsn(&self.dsn))
            .finish()
    }
}

impl PostgresStoreBackend {
    /// Resolve `connection` and build a lazy, bounded connection pool.
    ///
    /// Synchronous and cheap: `connect_lazy` validates the DSN format
    /// but opens **no** connection — the first real connection is made
    /// on the first operation (D7 — lazy). A malformed DSN is a typed
    /// [`StoreError::PoolInit`].
    ///
    /// Must be called within a Tokio runtime context: a well-formed DSN
    /// registers a background connection reaper. In production this is
    /// always satisfied — the registry (35.d) is built while the axum
    /// server's runtime is live.
    pub fn connect(connection: &str) -> Result<Self, StoreError> {
        let dsn = resolve_dsn(connection)?;
        let pool = PgPoolOptions::new()
            .max_connections(MAX_POOL_CONNECTIONS)
            .min_connections(0)
            .acquire_timeout(Duration::from_secs(ACQUIRE_TIMEOUT_SECS))
            .idle_timeout(Duration::from_secs(IDLE_TIMEOUT_SECS))
            .connect_lazy(&dsn)
            .map_err(|e| StoreError::PoolInit {
                dsn_masked: mask_dsn(&dsn),
                source: e.to_string(),
            })?;
        Ok(Self { dsn, pool })
    }

    /// The resolved DSN with its password masked — safe to log.
    pub fn masked_dsn(&self) -> String {
        mask_dsn(&self.dsn)
    }

    /// The underlying pool — 35.i's `Stream<Row>` borrows it.
    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// `retrieve` — run `SELECT * FROM table WHERE <where_expr>` and map
    /// every row to a JSON-safe [`StoreRow`].
    ///
    /// v1.30.0 materializes the full result (`fetch_all`); 35.i adds the
    /// backpressured `Stream<Row>` variant (Pillar III).
    pub async fn query(
        &self,
        table: &str,
        where_expr: &str,
        bindings: &std::collections::HashMap<String, String>,
    ) -> Result<Vec<StoreRow>, StoreError> {
        let (sql, params) = build_select_sql(table, where_expr, bindings)?;
        let mut q = sqlx::query(&sql);
        for value in &params {
            q = bind_value(q, value);
        }
        let rows = q.fetch_all(&self.pool).await.map_err(|e| {
            StoreError::Query { op: "retrieve", source: e.to_string() }
        })?;
        rows.iter().map(map_pg_row).collect()
    }

    /// `persist` — run `INSERT INTO table (…) VALUES (…)`. Returns the
    /// number of rows inserted.
    pub async fn insert(
        &self,
        table: &str,
        data: &[(String, SqlValue)],
    ) -> Result<u64, StoreError> {
        let (sql, params) = build_insert_sql(table, data)?;
        let mut q = sqlx::query(&sql);
        for value in &params {
            q = bind_value(q, value);
        }
        let result = q.execute(&self.pool).await.map_err(|e| {
            StoreError::Query { op: "persist", source: e.to_string() }
        })?;
        Ok(result.rows_affected())
    }

    /// `mutate` — run `UPDATE table SET … WHERE …`. Returns the number
    /// of rows affected.
    pub async fn mutate(
        &self,
        table: &str,
        where_expr: &str,
        data: &[(String, SqlValue)],
        bindings: &std::collections::HashMap<String, String>,
    ) -> Result<u64, StoreError> {
        let (sql, params) = build_update_sql(table, where_expr, data, bindings)?;
        let mut q = sqlx::query(&sql);
        for value in &params {
            q = bind_value(q, value);
        }
        let result = q.execute(&self.pool).await.map_err(|e| {
            StoreError::Query { op: "mutate", source: e.to_string() }
        })?;
        Ok(result.rows_affected())
    }

    /// `purge` — run `DELETE FROM table WHERE …`. Returns the number of
    /// rows deleted.
    pub async fn purge(
        &self,
        table: &str,
        where_expr: &str,
        bindings: &std::collections::HashMap<String, String>,
    ) -> Result<u64, StoreError> {
        let (sql, params) = build_delete_sql(table, where_expr, bindings)?;
        let mut q = sqlx::query(&sql);
        for value in &params {
            q = bind_value(q, value);
        }
        let result = q.execute(&self.pool).await.map_err(|e| {
            StoreError::Query { op: "purge", source: e.to_string() }
        })?;
        Ok(result.rows_affected())
    }

    /// Verify database reachability with `SELECT 1`.
    pub async fn ping(&self) -> Result<(), StoreError> {
        sqlx::query("SELECT 1")
            .execute(&self.pool)
            .await
            .map(|_| ())
            .map_err(|e| StoreError::Connect { source: e.to_string() })
    }
}

// ════════════════════════════════════════════════════════════════════
//  Unit tests — pure surface (no database)
// ════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    fn txt(s: &str) -> SqlValue {
        SqlValue::Text(s.to_string())
    }

    /// Empty bindings — these `build_*_sql` tests pin the pre-37.d
    /// behaviour (no `${name}` resolution). The §Fase 37.d resolution
    /// is exercised by `tests/fase37_d_*` and `store::filter`.
    fn nb() -> std::collections::HashMap<String, String> {
        std::collections::HashMap::new()
    }

    // ── resolve_dsn ──────────────────────────────────────────────────

    #[test]
    fn resolve_empty_connection_errors() {
        assert_eq!(resolve_dsn(""), Err(StoreError::EmptyConnection));
        assert_eq!(resolve_dsn("    "), Err(StoreError::EmptyConnection));
    }

    #[test]
    fn resolve_literal_dsn_is_returned_verbatim() {
        let dsn = "postgresql://u:p@localhost:5432/axon";
        assert_eq!(resolve_dsn(dsn), Ok(dsn.to_string()));
    }

    #[test]
    fn resolve_literal_dsn_is_trimmed() {
        assert_eq!(
            resolve_dsn("  postgresql://h/db  "),
            Ok("postgresql://h/db".to_string())
        );
    }

    #[test]
    fn resolve_bare_env_prefix_errors() {
        assert_eq!(resolve_dsn("env:"), Err(StoreError::EmptyEnvVarName));
        assert_eq!(resolve_dsn("env:   "), Err(StoreError::EmptyEnvVarName));
    }

    #[test]
    fn resolve_missing_env_var_errors() {
        match resolve_dsn("env:AXON_NONEXISTENT_VAR_FASE35C") {
            Err(StoreError::MissingEnvVar { var }) => {
                assert_eq!(var, "AXON_NONEXISTENT_VAR_FASE35C");
            }
            other => panic!("expected MissingEnvVar, got {other:?}"),
        }
    }

    #[test]
    fn resolve_env_var_reads_the_environment() {
        // `PATH` is set on every supported OS — exercise the success
        // path without mutating the process environment.
        let resolved = resolve_dsn("env:PATH").expect("PATH resolves");
        assert_eq!(resolved, std::env::var("PATH").unwrap());
        assert!(!resolved.is_empty());
    }

    // ── connect / masking ────────────────────────────────────────────

    #[tokio::test]
    async fn connect_with_valid_dsn_is_lazy_and_succeeds() {
        // `connect_lazy` opens no connection — a well-formed DSN to a
        // host that may not exist still yields Ok.
        let backend =
            PostgresStoreBackend::connect("postgresql://u:p@localhost:5432/db")
                .expect("a well-formed DSN builds a lazy pool");
        let _ = format!("{backend:?}");
    }

    #[tokio::test]
    async fn connect_masks_the_password_in_dsn_and_debug() {
        // A deliberately fake credential — this test asserts the
        // backend never surfaces a DSN password.
        let fake_secret = "fakecred0";
        let backend = PostgresStoreBackend::connect(&format!(
            "postgresql://user:{fake_secret}@localhost:5432/axon"
        ))
        .unwrap();
        let masked = backend.masked_dsn();
        assert!(!masked.contains(fake_secret), "password must be masked");
        assert!(masked.contains("***"));
        assert!(!format!("{backend:?}").contains(fake_secret));
    }

    #[test]
    fn connect_empty_connection_errors() {
        assert!(matches!(
            PostgresStoreBackend::connect(""),
            Err(StoreError::EmptyConnection)
        ));
    }

    #[test]
    fn connect_missing_env_var_errors() {
        assert!(matches!(
            PostgresStoreBackend::connect("env:AXON_NONEXISTENT_VAR_FASE35C"),
            Err(StoreError::MissingEnvVar { .. })
        ));
    }

    #[test]
    fn connect_malformed_dsn_errors() {
        assert!(matches!(
            PostgresStoreBackend::connect("not a valid dsn at all"),
            Err(StoreError::PoolInit { .. })
        ));
    }

    // ── build_select_sql ─────────────────────────────────────────────

    #[test]
    fn select_with_filter() {
        let (sql, params) = build_select_sql("users", "id = 1", &nb()).unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE \"id\" = $1");
        assert_eq!(params, vec![SqlValue::Integer(1)]);
    }

    #[test]
    fn select_with_empty_filter_renders_where_true() {
        let (sql, params) = build_select_sql("users", "", &nb()).unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE TRUE");
        assert!(params.is_empty());
    }

    #[test]
    fn select_rejects_unsafe_table_name() {
        assert!(matches!(
            build_select_sql("users; DROP TABLE x", "", &nb()),
            Err(StoreError::InvalidIdentifier { kind: "table", .. })
        ));
    }

    #[test]
    fn select_propagates_filter_errors() {
        assert!(matches!(
            build_select_sql("users", "id = 1 AND", &nb()),
            Err(StoreError::Filter(_))
        ));
    }

    // ── build_delete_sql ─────────────────────────────────────────────

    #[test]
    fn delete_with_filter() {
        let (sql, params) =
            build_delete_sql("sessions", "expired = true", &nb()).unwrap();
        assert_eq!(sql, "DELETE FROM \"sessions\" WHERE \"expired\" = $1");
        assert_eq!(params, vec![SqlValue::Boolean(true)]);
    }

    #[test]
    fn delete_rejects_unsafe_table() {
        assert!(matches!(
            build_delete_sql("evil\"table", "a = 1", &nb()),
            Err(StoreError::InvalidIdentifier { .. })
        ));
    }

    // ── build_insert_sql ─────────────────────────────────────────────

    #[test]
    fn insert_basic() {
        let (sql, params) = build_insert_sql(
            "users",
            &[("name".into(), txt("Alice")), ("age".into(), SqlValue::Integer(30))],
        )
        .unwrap();
        assert_eq!(
            sql,
            "INSERT INTO \"users\" (\"name\", \"age\") VALUES ($1, $2)"
        );
        assert_eq!(params, vec![txt("Alice"), SqlValue::Integer(30)]);
    }

    #[test]
    fn insert_renders_null_inline_consuming_no_placeholder() {
        let (sql, params) = build_insert_sql(
            "t",
            &[
                ("a".into(), SqlValue::Integer(1)),
                ("b".into(), SqlValue::Null),
                ("c".into(), txt("x")),
            ],
        )
        .unwrap();
        assert_eq!(
            sql,
            "INSERT INTO \"t\" (\"a\", \"b\", \"c\") VALUES ($1, NULL, $2)"
        );
        assert_eq!(params, vec![SqlValue::Integer(1), txt("x")]);
    }

    #[test]
    fn insert_empty_data_errors() {
        assert_eq!(
            build_insert_sql("t", &[]),
            Err(StoreError::EmptyData { op: "insert" })
        );
    }

    #[test]
    fn insert_rejects_unsafe_column_name() {
        assert!(matches!(
            build_insert_sql("t", &[("a\"; DROP".into(), SqlValue::Integer(1))]),
            Err(StoreError::InvalidIdentifier { kind: "column", .. })
        ));
    }

    #[test]
    fn insert_rejects_unsafe_table_name() {
        assert!(matches!(
            build_insert_sql("t t", &[("a".into(), SqlValue::Integer(1))]),
            Err(StoreError::InvalidIdentifier { kind: "table", .. })
        ));
    }

    // ── build_update_sql ─────────────────────────────────────────────

    #[test]
    fn update_basic_where_offset_continues_after_set() {
        let (sql, params) = build_update_sql(
            "users",
            "id = 5",
            &[("name".into(), txt("Bob")), ("age".into(), SqlValue::Integer(40))],
            &nb(),
        )
        .unwrap();
        assert_eq!(
            sql,
            "UPDATE \"users\" SET \"name\" = $1, \"age\" = $2 WHERE \"id\" = $3"
        );
        assert_eq!(
            params,
            vec![txt("Bob"), SqlValue::Integer(40), SqlValue::Integer(5)]
        );
    }

    #[test]
    fn update_null_set_value_shifts_where_offset_by_non_null_count() {
        // The defect the Python reference has: a NULL SET value renders
        // inline, so the WHERE offset is the NON-NULL set count (1),
        // not the column count (2). `id` must be $2, not $3.
        let (sql, params) = build_update_sql(
            "users",
            "id = 5",
            &[("name".into(), SqlValue::Null), ("age".into(), SqlValue::Integer(40))],
            &nb(),
        )
        .unwrap();
        assert_eq!(
            sql,
            "UPDATE \"users\" SET \"name\" = NULL, \"age\" = $1 WHERE \"id\" = $2"
        );
        assert_eq!(params, vec![SqlValue::Integer(40), SqlValue::Integer(5)]);
    }

    #[test]
    fn update_with_empty_where_targets_all_rows() {
        let (sql, _) =
            build_update_sql("t", "", &[("a".into(), SqlValue::Integer(1))], &nb())
                .unwrap();
        assert_eq!(sql, "UPDATE \"t\" SET \"a\" = $1 WHERE TRUE");
    }

    #[test]
    fn update_empty_data_errors() {
        assert_eq!(
            build_update_sql("t", "id = 1", &[], &nb()),
            Err(StoreError::EmptyData { op: "mutate" })
        );
    }

    #[test]
    fn update_rejects_unsafe_column() {
        assert!(matches!(
            build_update_sql("t", "id = 1", &[("a-b".into(), SqlValue::Integer(1))], &nb()),
            Err(StoreError::InvalidIdentifier { kind: "column", .. })
        ));
    }

    #[test]
    fn update_propagates_filter_errors() {
        assert!(matches!(
            build_update_sql("t", "bad ;", &[("a".into(), SqlValue::Integer(1))], &nb()),
            Err(StoreError::Filter(_))
        ));
    }

    // ── D4 — injection resistance, end to end ────────────────────────

    #[test]
    fn injection_in_value_position_is_a_bound_parameter() {
        let (sql, params) =
            build_select_sql("users", "name = '; DROP TABLE users; --'", &nb())
                .unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE \"name\" = $1");
        assert_eq!(
            params,
            vec![txt("; DROP TABLE users; --")]
        );
    }

    #[test]
    fn injection_in_table_identifier_is_rejected_not_quoted() {
        assert!(matches!(
            build_select_sql("users\" WHERE 1=1; --", "", &nb()),
            Err(StoreError::InvalidIdentifier { .. })
        ));
    }

    // ── classify_pg_type ─────────────────────────────────────────────

    #[test]
    fn classify_every_supported_type() {
        let cases = [
            ("BOOL", PgTypeClass::Bool),
            ("INT2", PgTypeClass::Int2),
            ("INT4", PgTypeClass::Int4),
            ("INT8", PgTypeClass::Int8),
            ("FLOAT4", PgTypeClass::Float4),
            ("FLOAT8", PgTypeClass::Float8),
            ("NUMERIC", PgTypeClass::Numeric),
            ("TEXT", PgTypeClass::Text),
            ("VARCHAR", PgTypeClass::Text),
            ("BPCHAR", PgTypeClass::Text),
            ("NAME", PgTypeClass::Text),
            ("UUID", PgTypeClass::Uuid),
            ("TIMESTAMPTZ", PgTypeClass::TimestampTz),
            ("TIMESTAMP", PgTypeClass::Timestamp),
            ("DATE", PgTypeClass::Date),
            ("TIME", PgTypeClass::Time),
            ("JSON", PgTypeClass::Json),
            ("JSONB", PgTypeClass::Json),
            ("BYTEA", PgTypeClass::Bytea),
        ];
        for (name, expected) in cases {
            assert_eq!(classify_pg_type(name), Some(expected), "type {name}");
        }
    }

    #[test]
    fn classify_is_case_insensitive() {
        assert_eq!(classify_pg_type("int4"), Some(PgTypeClass::Int4));
        assert_eq!(classify_pg_type("TimestampTz"), Some(PgTypeClass::TimestampTz));
    }

    #[test]
    fn classify_unsupported_types_return_none() {
        for name in ["INT4[]", "INET", "POINT", "HSTORE", "CIDR", "MONEY", ""] {
            assert_eq!(classify_pg_type(name), None, "type {name} unsupported");
        }
    }

    // ── StoreRow ─────────────────────────────────────────────────────

    #[test]
    fn store_row_get_and_to_json() {
        let row = StoreRow {
            columns: vec![
                ("id".into(), JsonValue::from(7)),
                ("name".into(), JsonValue::String("Eve".into())),
            ],
        };
        assert_eq!(row.get("id"), Some(&JsonValue::from(7)));
        assert_eq!(row.get("missing"), None);
        assert_eq!(
            row.to_json(),
            serde_json::json!({ "id": 7, "name": "Eve" })
        );
    }

    // ── StoreError display ───────────────────────────────────────────

    #[test]
    fn every_store_error_has_a_non_empty_display() {
        let errors = [
            StoreError::EmptyConnection,
            StoreError::EmptyEnvVarName,
            StoreError::MissingEnvVar { var: "X".into() },
            StoreError::PoolInit {
                dsn_masked: "postgresql://u:***@h/db".into(),
                source: "bad".into(),
            },
            StoreError::InvalidIdentifier { kind: "table", name: "x;".into() },
            StoreError::EmptyData { op: "insert" },
            StoreError::Filter(FilterError::TooManyConditions { limit: 256 }),
            StoreError::Connect { source: "refused".into() },
            StoreError::Query { op: "retrieve", source: "syntax".into() },
            StoreError::UnsupportedColumnType {
                column: "geom".into(),
                pg_type: "POINT".into(),
            },
            StoreError::Decode {
                column: "ts".into(),
                pg_type: "TIMESTAMPTZ".into(),
                source: "overflow".into(),
            },
        ];
        for e in errors {
            assert!(!e.to_string().is_empty());
        }
    }

    #[test]
    fn filter_error_is_a_store_error_source() {
        use std::error::Error;
        let e = StoreError::Filter(FilterError::TooManyConditions { limit: 256 });
        assert!(e.source().is_some());
    }

    #[test]
    fn filter_error_converts_into_store_error() {
        let e: StoreError = FilterError::TooManyConditions { limit: 256 }.into();
        assert!(matches!(e, StoreError::Filter(_)));
    }
}
