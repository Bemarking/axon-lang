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
//! `sqlx::PgPool` (`connect_lazy_with` — no connection is opened until
//! the first operation). Every failure path — empty connection, missing
//! env var, malformed DSN, connect failure, SQL error, an unsupported
//! column type, a decode failure — surfaces as a typed [`StoreError`].
//! No panic; no silent empty result masking a failed query.
//!
//! # Gap 3 (v1.36.3) — transaction-mode pooler safety
//!
//! The pool's `PgConnectOptions` set `statement_cache_capacity(0)`
//! unconditionally. sqlx otherwise caches server-side prepared
//! statements under generated names (`sqlx_s_1`, …); behind a
//! transaction-mode pooler — PgBouncer `pool_mode=transaction`,
//! Supabase Supavisor (`:6543`), Neon, RDS Proxy — successive
//! operations land on different physical sessions, so a name minted on
//! one collides on the next (`prepared statement "sqlx_s_1" already
//! exists`). Capacity 0 routes every query through the *unnamed*
//! prepared statement — collision-free by construction, harmless on a
//! direct/session-mode connection. An axonstore DSN is pooler-agnostic
//! with no knob to misconfigure. Each connection also carries an
//! `application_name` of `axon-store/<store>` so every session is
//! attributable to its declaration in `pg_stat_activity`, pooler logs
//! and DBA dashboards.
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
use std::str::FromStr;
use std::time::Duration;

use serde_json::Value as JsonValue;
use sqlx::postgres::{PgArguments, PgConnectOptions, PgPoolOptions, PgRow};
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

/// The `application_name` stamped on an axonstore's Postgres
/// connections (Gap 3 bonus, v1.36.3).
///
/// `axon-store/<store_name>` makes every session attributable to its
/// `axonstore` declaration in `pg_stat_activity`, pooler logs and DBA
/// dashboards; a bare `axon-store` when no store name is available.
///
/// Total and bounded: Postgres caps `application_name` at
/// `NAMEDATALEN - 1` (63 bytes) and *silently truncates* a longer
/// value. This caps it ourselves on a UTF-8 char boundary so the
/// stamped name is exactly what a DBA sees — never a server-mangled
/// suffix.
fn application_name_for(store_name: &str) -> String {
    const MAX: usize = 63;
    let full = if store_name.is_empty() {
        "axon-store".to_string()
    } else {
        format!("axon-store/{store_name}")
    };
    if full.len() <= MAX {
        return full;
    }
    let mut cut = MAX;
    while cut > 0 && !full.is_char_boundary(cut) {
        cut -= 1;
    }
    full[..cut].to_string()
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
/// §v1.36.4 — `column_types` (the `column → udt_name` map) lets
/// [`build_pg_where`] cast each `where`-clause value to its column's
/// Postgres type. Pass an empty map when the schema is unknown — the
/// filter then renders bare `$N` placeholders.
pub fn build_select_sql(
    table: &str,
    where_expr: &str,
    bindings: &std::collections::HashMap<String, String>,
    column_types: &std::collections::HashMap<String, String>,
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    let (clause, params) = build_pg_where(where_expr, 0, bindings, column_types)?;
    Ok((format!("SELECT * FROM \"{table}\" WHERE {clause}"), params))
}

/// Build a parameterized `DELETE FROM "table" WHERE …` statement.
///
/// §v1.36.4 — `column_types` drives the `where`-clause value cast (see
/// [`build_select_sql`]).
pub fn build_delete_sql(
    table: &str,
    where_expr: &str,
    bindings: &std::collections::HashMap<String, String>,
    column_types: &std::collections::HashMap<String, String>,
) -> Result<(String, Vec<SqlValue>), StoreError> {
    check_identifier(table, "table")?;
    let (clause, params) = build_pg_where(where_expr, 0, bindings, column_types)?;
    Ok((format!("DELETE FROM \"{table}\" WHERE {clause}"), params))
}

/// §v1.36.2 — process-global cache `(dsn, table) → {column → type}`.
/// A table's column types are stable for the lifetime of a process, so
/// one introspection per `(connection, table)` suffices. §v1.36.5 —
/// only a non-empty map is cached, so a transient introspection
/// failure never poisons a `(dsn, table)` entry permanently.
static SCHEMA_CACHE: std::sync::LazyLock<
    std::sync::Mutex<
        std::collections::HashMap<
            (String, String),
            std::sync::Arc<std::collections::HashMap<String, String>>,
        >,
    >,
> = std::sync::LazyLock::new(|| {
    std::sync::Mutex::new(std::collections::HashMap::new())
});

/// §v1.36.2 — the `::<type>` cast suffix for a `$N` value placeholder.
///
/// axon's runtime carries no column schema (D12), so a `text`-bound
/// value cannot reach a `uuid` / `int` / `timestamptz` column: Postgres
/// has no cross-type operator. The cure is to cast the VALUE to the
/// column's type — `$N::uuid` is a valid explicit cast over the bound
/// parameter (`'83d0…'::uuid` parses the text). v1.36.2 applies it to
/// every WRITE placeholder (`INSERT` values, `UPDATE … SET`); §v1.36.4
/// applies the identical cure to the read side via [`build_pg_where`]
/// (`"col" {op} $N::<type>`). The column's Postgres type name comes
/// from a cached `to_regclass` + `pg_catalog` introspection
/// ([`PostgresStoreBackend::column_types`]).
///
/// Empty when the column type is unknown (introspection missed the
/// column, or ran against a table outside `current_schema()`) or the
/// type name is not a safe identifier — the builder then emits a bare
/// `$N`: a `text` column still works, a typed column fails LOUDLY (no
/// regression, no silent-wrong write).
fn write_cast(
    column_types: &std::collections::HashMap<String, String>,
    column: &str,
) -> String {
    match column_types.get(column) {
        Some(udt) if filter::is_safe_identifier(udt) => format!("::{udt}"),
        _ => String::new(),
    }
}

/// Build a parameterized `INSERT INTO "table" (…) VALUES (…)`.
///
/// A `NULL` data value renders as the inline `NULL` keyword (a fixed
/// SQL token, injection-safe) and consumes no `$N` placeholder — the
/// same discipline 35.b applies to `NULL` in a `where` clause. Postgres
/// infers the column type for an inline `NULL`.
///
/// §v1.36.2 — each `$N` value placeholder is cast to its column's
/// introspected type (`column_types`) so a `text`-bound value writes
/// into a `uuid` / `int` / `timestamptz` column. An empty
/// `column_types` map emits bare `$N` (the pre-1.36.2 behaviour).
pub fn build_insert_sql(
    table: &str,
    data: &[(String, SqlValue)],
    column_types: &std::collections::HashMap<String, String>,
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
                value_frags.push(format!("${idx}{}", write_cast(column_types, col)));
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
///
/// §v1.36.2 — each `SET` value placeholder is cast to its column's
/// introspected type (`column_types`), the same `$N::<type>` cure
/// `build_insert_sql` applies, so a `text`-bound value writes into a
/// non-`text` column. §v1.36.4 — the same `column_types` map is now
/// threaded into the `WHERE` side too, so a `where`-clause value is
/// cast to its column's type (`"col" {op} $N::<type>`).
pub fn build_update_sql(
    table: &str,
    where_expr: &str,
    data: &[(String, SqlValue)],
    bindings: &std::collections::HashMap<String, String>,
    column_types: &std::collections::HashMap<String, String>,
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
                set_frags.push(format!(
                    "\"{col}\" = ${idx}{}",
                    write_cast(column_types, col)
                ));
                params.push(bound.clone());
                idx += 1;
            }
        }
    }

    // `idx - 1` SET placeholders were emitted; WHERE continues there.
    let set_param_count = idx - 1;
    let (clause, where_params) =
        build_pg_where(where_expr, set_param_count, bindings, column_types)?;
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
    /// Equivalent to [`connect_named`](Self::connect_named) with no
    /// store name — the connection's `application_name` is the bare
    /// `axon-store`. Prefer `connect_named` so each session is
    /// attributable to its declaring `axonstore`.
    pub fn connect(connection: &str) -> Result<Self, StoreError> {
        Self::connect_named(connection, "")
    }

    /// Resolve `connection` and build a lazy, bounded connection pool,
    /// stamping each connection's `application_name` with `store_name`.
    ///
    /// Synchronous and cheap: the DSN is parsed into a
    /// [`PgConnectOptions`] (a malformed DSN is a typed
    /// [`StoreError::PoolInit`]) but `connect_lazy_with` opens **no**
    /// connection — the first real connection is made on the first
    /// operation (D7 — lazy).
    ///
    /// Two production-grade properties are set on every connection:
    ///
    /// - **`statement_cache_capacity(0)`** (Gap 3) — disables sqlx's
    ///   named server-side prepared-statement cache so the backend is
    ///   safe behind a transaction-mode pooler (PgBouncer
    ///   `pool_mode=transaction`, Supabase Supavisor `:6543`, Neon, RDS
    ///   Proxy), where a cached name minted on one physical session
    ///   collides on the next (`prepared statement "sqlx_s_1" already
    ///   exists`). Applied unconditionally — harmless on a direct
    ///   connection, and there is no knob to misconfigure.
    /// - **`application_name`** — `axon-store/<store_name>` (bare
    ///   `axon-store` when `store_name` is empty), capped at the
    ///   Postgres 63-byte `NAMEDATALEN-1` limit on a char boundary, so
    ///   every axon-owned session is identifiable in `pg_stat_activity`,
    ///   pooler logs and DBA dashboards.
    ///
    /// Must be called within a Tokio runtime context: a well-formed DSN
    /// registers a background connection reaper. In production this is
    /// always satisfied — the registry (35.d) is built while the axum
    /// server's runtime is live.
    pub fn connect_named(
        connection: &str,
        store_name: &str,
    ) -> Result<Self, StoreError> {
        let dsn = resolve_dsn(connection)?;
        let opts = PgConnectOptions::from_str(&dsn)
            .map_err(|e| StoreError::PoolInit {
                dsn_masked: mask_dsn(&dsn),
                source: e.to_string(),
            })?
            .statement_cache_capacity(0)
            .application_name(&application_name_for(store_name));
        let pool = PgPoolOptions::new()
            .max_connections(MAX_POOL_CONNECTIONS)
            .min_connections(0)
            .acquire_timeout(Duration::from_secs(ACQUIRE_TIMEOUT_SECS))
            .idle_timeout(Duration::from_secs(IDLE_TIMEOUT_SECS))
            .connect_lazy_with(opts);
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
        let column_types = self.column_types(table).await;
        let (sql, params) =
            build_select_sql(table, where_expr, bindings, &column_types)?;
        let mut q = sqlx::query(&sql);
        for value in &params {
            q = bind_value(q, value);
        }
        let rows = q.fetch_all(&self.pool).await.map_err(|e| {
            StoreError::Query { op: "retrieve", source: e.to_string() }
        })?;
        rows.iter().map(map_pg_row).collect()
    }

    /// The `column → type-name` map for `table`, introspected once per
    /// `(dsn, table)` and cached process-globally (a table's column
    /// types are stable). Drives the `$N::<type>` cast on both the
    /// write side (`build_insert_sql` / `build_update_sql` SET) and the
    /// read side (`build_pg_where`, §v1.36.4).
    ///
    /// §v1.36.5 — the introspection resolves `table` via
    /// [`to_regclass`], which honours the connection's **full
    /// `search_path`** — exactly the resolution an unqualified
    /// `SELECT * FROM "table"` performs. The earlier query keyed on
    /// `table_schema = current_schema()`, which is only the *first*
    /// schema of the `search_path`: a table reachable via `search_path`
    /// but living in a later schema (an adopter's legacy schema) was
    /// invisible to introspection, so every typed column fell back to a
    /// bare `$N` and a `uuid`/`int` filter failed with `operator does
    /// not exist`. `to_regclass` + `pg_catalog` closes that gap.
    ///
    /// On ANY error — permission, a table that does not resolve — the
    /// map is empty and the SQL builders fall back to bare `$N` (a
    /// `text` column still works; a typed column fails loudly). §v1.36.5
    /// — an **empty** map is NEVER cached: a real table always has ≥ 1
    /// column, so an empty result is always a failure (a transient
    /// introspection error, an unresolved name). Caching it would
    /// poison every later lookup; leaving it uncached lets the next
    /// operation retry.
    ///
    /// `pub(crate)` so the `row_stream` cursor drain shares the same
    /// introspection + cache as `query` / `mutate` / `purge`.
    pub(crate) async fn column_types(
        &self,
        table: &str,
    ) -> std::sync::Arc<std::collections::HashMap<String, String>> {
        let key = (self.dsn.clone(), table.to_string());
        if let Some(hit) = SCHEMA_CACHE.lock().unwrap().get(&key) {
            return hit.clone();
        }
        let mut map: std::collections::HashMap<String, String> =
            std::collections::HashMap::new();
        // `to_regclass($1)` resolves the (double-quoted) table name via
        // the session `search_path` — the SAME resolution the store's
        // own `SELECT * FROM "table"` uses. `pg_attribute` + `pg_type`
        // then yield every live column's type name (`uuid`, `int4`,
        // `timestamptz`, …), each a valid `$N::<type>` cast target.
        let regclass_arg = format!("\"{table}\"");
        let rows = sqlx::query(
            "SELECT a.attname AS column_name, t.typname AS type_name \
             FROM pg_catalog.pg_attribute a \
             JOIN pg_catalog.pg_type t ON t.oid = a.atttypid \
             WHERE a.attrelid = to_regclass($1) \
               AND a.attnum > 0 AND NOT a.attisdropped",
        )
        .bind(regclass_arg)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        for row in &rows {
            let col: String = row.try_get("column_name").unwrap_or_default();
            let ty: String = row.try_get("type_name").unwrap_or_default();
            if !col.is_empty() && !ty.is_empty() {
                map.insert(col, ty);
            }
        }
        let arc = std::sync::Arc::new(map);
        // §v1.36.5 — cache only a NON-EMPTY map (see the doc above).
        if !arc.is_empty() {
            SCHEMA_CACHE
                .lock()
                .unwrap()
                .insert(key, std::sync::Arc::clone(&arc));
        }
        arc
    }

    /// `persist` — run `INSERT INTO table (…) VALUES (…)`. Returns the
    /// number of rows inserted.
    pub async fn insert(
        &self,
        table: &str,
        data: &[(String, SqlValue)],
    ) -> Result<u64, StoreError> {
        let column_types = self.column_types(table).await;
        let (sql, params) = build_insert_sql(table, data, &column_types)?;
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
        let column_types = self.column_types(table).await;
        let (sql, params) =
            build_update_sql(table, where_expr, data, bindings, &column_types)?;
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
        let column_types = self.column_types(table).await;
        let (sql, params) =
            build_delete_sql(table, where_expr, bindings, &column_types)?;
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

    // ── Gap 3 (v1.36.3) — pooler safety + application_name ───────────

    #[tokio::test]
    async fn connect_named_with_valid_dsn_is_lazy_and_succeeds() {
        // `connect_named` builds the same lazy pool — Gap 3 only adds
        // `statement_cache_capacity(0)` + `application_name`, neither of
        // which opens a connection.
        let backend = PostgresStoreBackend::connect_named(
            "postgresql://u:p@localhost:5432/db",
            "claims",
        )
        .expect("a well-formed DSN builds a lazy pool");
        let _ = format!("{backend:?}");
    }

    #[test]
    fn connect_named_malformed_dsn_errors() {
        assert!(matches!(
            PostgresStoreBackend::connect_named("not a dsn", "claims"),
            Err(StoreError::PoolInit { .. })
        ));
    }

    #[test]
    fn application_name_carries_the_store_name() {
        assert_eq!(application_name_for("claims"), "axon-store/claims");
        assert_eq!(
            application_name_for("tenant_audit_log"),
            "axon-store/tenant_audit_log"
        );
    }

    #[test]
    fn application_name_empty_store_is_bare() {
        // `connect` delegates with no store name — the bare label, with
        // no dangling slash.
        assert_eq!(application_name_for(""), "axon-store");
    }

    #[test]
    fn application_name_capped_at_postgres_namedatalen() {
        // Postgres silently truncates `application_name` past 63 bytes;
        // we cap it ourselves so the stamped name is exactly observed.
        let long = "s".repeat(200);
        let name = application_name_for(&long);
        assert!(name.len() <= 63, "must fit NAMEDATALEN-1, got {}", name.len());
        assert!(name.starts_with("axon-store/s"));
    }

    #[test]
    fn application_name_truncation_respects_char_boundaries() {
        // A multi-byte tail must never be cut mid-codepoint — the result
        // is always valid UTF-8 (`String` guarantees it, but the cut
        // must land on a boundary or the slice panics).
        let name = application_name_for(&"é".repeat(100));
        assert!(name.len() <= 63);
        assert!(name.is_char_boundary(name.len()));
    }

    // ── build_select_sql ─────────────────────────────────────────────

    #[test]
    fn select_with_filter() {
        let (sql, params) =
            build_select_sql("users", "id = 1", &nb(), &nb()).unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE \"id\" = $1");
        assert_eq!(params, vec![SqlValue::Integer(1)]);
    }

    #[test]
    fn select_casts_the_filter_value_to_its_introspected_column_type() {
        // §v1.36.4 — a known column type casts the WHERE value, so the
        // comparison uses the native operator (`int4 = int4`).
        let types = std::collections::HashMap::from([(
            "id".to_string(),
            "int4".to_string(),
        )]);
        let (sql, _) =
            build_select_sql("users", "id = 1", &nb(), &types).unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE \"id\" = $1::int4");
    }

    #[test]
    fn select_with_empty_filter_renders_where_true() {
        let (sql, params) = build_select_sql("users", "", &nb(), &nb()).unwrap();
        assert_eq!(sql, "SELECT * FROM \"users\" WHERE TRUE");
        assert!(params.is_empty());
    }

    #[test]
    fn select_rejects_unsafe_table_name() {
        assert!(matches!(
            build_select_sql("users; DROP TABLE x", "", &nb(), &nb()),
            Err(StoreError::InvalidIdentifier { kind: "table", .. })
        ));
    }

    #[test]
    fn select_propagates_filter_errors() {
        assert!(matches!(
            build_select_sql("users", "id = 1 AND", &nb(), &nb()),
            Err(StoreError::Filter(_))
        ));
    }

    // ── build_delete_sql ─────────────────────────────────────────────

    #[test]
    fn delete_with_filter() {
        let (sql, params) =
            build_delete_sql("sessions", "expired = true", &nb(), &nb())
                .unwrap();
        assert_eq!(sql, "DELETE FROM \"sessions\" WHERE \"expired\" = $1");
        assert_eq!(params, vec![SqlValue::Boolean(true)]);
    }

    #[test]
    fn delete_rejects_unsafe_table() {
        assert!(matches!(
            build_delete_sql("evil\"table", "a = 1", &nb(), &nb()),
            Err(StoreError::InvalidIdentifier { .. })
        ));
    }

    // ── build_insert_sql ─────────────────────────────────────────────

    #[test]
    fn insert_basic() {
        let (sql, params) = build_insert_sql(
            "users",
            &[("name".into(), txt("Alice")), ("age".into(), SqlValue::Integer(30))],
            &nb(),
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
            &nb(),
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
            build_insert_sql("t", &[], &nb()),
            Err(StoreError::EmptyData { op: "insert" })
        );
    }

    #[test]
    fn insert_rejects_unsafe_column_name() {
        assert!(matches!(
            build_insert_sql("t", &[("a\"; DROP".into(), SqlValue::Integer(1))], &nb()),
            Err(StoreError::InvalidIdentifier { kind: "column", .. })
        ));
    }

    #[test]
    fn insert_rejects_unsafe_table_name() {
        assert!(matches!(
            build_insert_sql("t t", &[("a".into(), SqlValue::Integer(1))], &nb()),
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
            build_update_sql("t", "", &[("a".into(), SqlValue::Integer(1))], &nb(), &nb())
                .unwrap();
        assert_eq!(sql, "UPDATE \"t\" SET \"a\" = $1 WHERE TRUE");
    }

    #[test]
    fn update_empty_data_errors() {
        assert_eq!(
            build_update_sql("t", "id = 1", &[], &nb(), &nb()),
            Err(StoreError::EmptyData { op: "mutate" })
        );
    }

    #[test]
    fn update_rejects_unsafe_column() {
        assert!(matches!(
            build_update_sql(
                "t",
                "id = 1",
                &[("a-b".into(), SqlValue::Integer(1))],
                &nb(),
                &nb(),
            ),
            Err(StoreError::InvalidIdentifier { kind: "column", .. })
        ));
    }

    #[test]
    fn update_propagates_filter_errors() {
        assert!(matches!(
            build_update_sql(
                "t",
                "bad ;",
                &[("a".into(), SqlValue::Integer(1))],
                &nb(),
                &nb(),
            ),
            Err(StoreError::Filter(_))
        ));
    }

    // ── §v1.36.2 — typed-column write cast ───────────────────────────

    #[test]
    fn insert_casts_each_value_to_its_introspected_column_type() {
        let types = std::collections::HashMap::from([
            ("tenant_id".to_string(), "uuid".to_string()),
            ("note".to_string(), "text".to_string()),
            ("n".to_string(), "int4".to_string()),
        ]);
        let (sql, _) = build_insert_sql(
            "chat_history",
            &[
                ("tenant_id".into(), txt("83d078e1-b372-42ba-9572-ff8dc521386e")),
                ("note".into(), txt("hi")),
                ("n".into(), SqlValue::Integer(3)),
            ],
            &types,
        )
        .unwrap();
        assert_eq!(
            sql,
            "INSERT INTO \"chat_history\" (\"tenant_id\", \"note\", \"n\") \
             VALUES ($1::uuid, $2::text, $3::int4)",
            "§v1.36.2 — each value placeholder is cast to its column's \
             introspected type so a text-bound value writes into a \
             uuid / int column"
        );
    }

    #[test]
    fn update_set_casts_each_value_to_its_introspected_column_type() {
        let types = std::collections::HashMap::from([(
            "status".to_string(),
            "uuid".to_string(),
        )]);
        let (sql, _) = build_update_sql(
            "t",
            "id = 1",
            &[("status".into(), txt("83d078e1-b372-42ba-9572-ff8dc521386e"))],
            &nb(),
            &types,
        )
        .unwrap();
        assert_eq!(
            sql,
            "UPDATE \"t\" SET \"status\" = $1::uuid WHERE \"id\" = $2",
            "§v1.36.2 — the SET value is cast to the column type; `id` \
             is absent from the type map so its WHERE placeholder is \
             bare (§v1.36.4 unknown-type fallback)"
        );
    }

    #[test]
    fn update_where_value_is_cast_to_its_column_type() {
        // §v1.36.4 — when the WHERE column's type IS known, its value
        // placeholder is cast too (the SET-side cure applied to WHERE).
        let types = std::collections::HashMap::from([
            ("status".to_string(), "text".to_string()),
            ("id".to_string(), "int8".to_string()),
        ]);
        let (sql, _) = build_update_sql(
            "t",
            "id = 1",
            &[("status".into(), txt("done"))],
            &nb(),
            &types,
        )
        .unwrap();
        assert_eq!(
            sql,
            "UPDATE \"t\" SET \"status\" = $1::text WHERE \"id\" = $2::int8"
        );
    }

    #[test]
    fn unknown_column_type_falls_back_to_a_bare_placeholder() {
        // An empty type map (introspection missed the table / column)
        // → bare `$N`, the pre-1.36.2 behaviour: a `text` column still
        // works, a typed column fails LOUDLY — no regression, no
        // silent-wrong write.
        let (sql, _) =
            build_insert_sql("t", &[("x".into(), txt("v"))], &nb()).unwrap();
        assert_eq!(sql, "INSERT INTO \"t\" (\"x\") VALUES ($1)");
    }

    #[test]
    fn an_unsafe_column_type_name_is_not_spliced_into_sql() {
        // Defense in depth: `udt_name` comes from Postgres, but a type
        // name that is not a safe identifier is never spliced — the
        // builder falls back to a bare `$N`.
        let types = std::collections::HashMap::from([(
            "x".to_string(),
            "uuid; DROP TABLE t".to_string(),
        )]);
        let (sql, _) =
            build_insert_sql("t", &[("x".into(), txt("v"))], &types).unwrap();
        assert_eq!(
            sql, "INSERT INTO \"t\" (\"x\") VALUES ($1)",
            "an unsafe type name yields no cast — never a splice"
        );
    }

    // ── D4 — injection resistance, end to end ────────────────────────

    #[test]
    fn injection_in_value_position_is_a_bound_parameter() {
        let (sql, params) =
            build_select_sql(
                "users",
                "name = '; DROP TABLE users; --'",
                &nb(),
                &nb(),
            )
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
            build_select_sql("users\" WHERE 1=1; --", "", &nb(), &nb()),
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
