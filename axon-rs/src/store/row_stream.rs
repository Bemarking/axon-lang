//! §Fase 35.i (v1.30.0) — Pillar III: `retrieve` is a `Stream<Row>`.
//!
//! A `retrieve from S where φ` is the coinductive selection σ_φ(S) —
//! not an eager set. A pg-backed `axonstore` becomes a first-class
//! **stream producer**: rows flow lazily off a cursor, drained through
//! a bounded, cancel-aware loop. `retrieve from huge_table` never
//! materializes the whole result — it streams, exactly like an LLM
//! token stream, and stays inside a memory bound.
//!
//! # Joins the Fase 34 streaming surface
//!
//! The drain reuses the **closed [`BackpressurePolicy`] catalog** Fase
//! 34 ratified (`drop_oldest` / `degrade_quality` / `pause_upstream` /
//! `fail`) and the same `CancellationFlag` cancel discipline as the
//! `unified_stream_handler`. A DB row is not a `ToolChunk` — it has no
//! token text, no SHA-256 accumulator, no wire terminator — so the
//! row drain is row-shaped rather than literally the token handler;
//! it joins the streaming *model* (lazy source + closed policy +
//! cancel-aware drain), which is what makes it unified with the
//! algebraic-effect surface.
//!
//! # The four policies, on rows
//!
//! - `Fail` — error the moment the result exceeds `max_rows`. Forces
//!   the caller to treat an oversized result as an explicit failure.
//! - `DropOldest` — keep the most recent `max_rows`; older rows are
//!   counted in `dropped`. A bounded tail window.
//! - `PauseUpstream` — stop polling the cursor at `max_rows` (the
//!   cursor pauses, the connection is released); `truncated` flags
//!   that more rows existed. A bounded head window.
//! - `DegradeQuality` — the OSS identity degrader: drain every row,
//!   no bound, no degradation. The enterprise layer overrides with a
//!   real row degrader (reservoir sampling, column projection).
//!
//! Cancel-aware: the [`CancellationFlag`] is polled between every row;
//! a cancelled drain stops immediately and reports `cancelled`.
//!
//! # OSS (§6 — 35.i is fully OSS)
//!
//! The streaming surface — the lazy cursor + the closed policy catalog
//! + the cancel-aware drain — is entirely OSS.

use std::collections::VecDeque;

use futures::{Stream, StreamExt};
use serde_json::{json, Value as JsonValue};

use crate::cancel_token::CancellationFlag;
use crate::store::filter::SqlValue;
use crate::store::postgres_backend::{
    bind_value, build_select_sql, map_pg_row, PostgresStoreBackend, StoreError,
    StoreRow,
};
use crate::stream_effect::BackpressurePolicy;

/// The default backpressure policy for a `retrieve` whose step carries
/// no explicit policy (`IRRetrieveStep` has no policy field in
/// v1.30.0). `PauseUpstream` is the safe default: the cursor streams
/// lazily (anti-OOM), the result is bounded, and an over-bound result
/// is *flagged* (`truncated`) rather than silently dropped or errored.
pub const DEFAULT_RETRIEVE_POLICY: BackpressurePolicy =
    BackpressurePolicy::PauseUpstream;

/// The default row bound for a streamed `retrieve`. Generous enough
/// for any realistic agent-store query; the point is that a pathological
/// `retrieve from billion_row_table` stays bounded.
pub const DEFAULT_MAX_ROWS: usize = 10_000;

// ════════════════════════════════════════════════════════════════════
//  Drain outcome
// ════════════════════════════════════════════════════════════════════

/// The result of draining a `retrieve` row stream under a policy.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct RowStreamOutcome {
    /// The rows that survived the policy, in cursor order.
    pub rows: Vec<StoreRow>,
    /// Total rows the cursor yielded before the drain stopped.
    pub total_seen: usize,
    /// Rows discarded by a `DropOldest` policy.
    pub dropped: usize,
    /// `true` iff a `PauseUpstream` policy stopped the drain at the
    /// bound while the cursor still had rows.
    pub truncated: bool,
    /// `true` iff the cancellation flag fired mid-drain.
    pub cancelled: bool,
}

// ════════════════════════════════════════════════════════════════════
//  The bounded, cancel-aware drain (pure over any row stream)
// ════════════════════════════════════════════════════════════════════

/// Drain a row stream under a [`BackpressurePolicy`], bounded by
/// `max_rows` and cancel-aware.
///
/// Generic over the source stream so the policy + cancel logic is
/// exhaustively unit-testable with a synthetic in-memory stream — the
/// live Postgres cursor is just one such source ([`stream_retrieve`]).
///
/// A row that fails to decode (`Err`) aborts the drain with that error
/// — never a silent skip.
pub async fn drain_with_policy<S>(
    mut stream: S,
    policy: BackpressurePolicy,
    max_rows: usize,
    cancel: &CancellationFlag,
) -> Result<RowStreamOutcome, StoreError>
where
    S: Stream<Item = Result<StoreRow, StoreError>> + Unpin,
{
    let mut kept: VecDeque<StoreRow> = VecDeque::new();
    let mut outcome = RowStreamOutcome::default();

    while let Some(item) = stream.next().await {
        // Cancel is polled BEFORE consuming the row — a cancelled
        // drain stops immediately, mirroring `unified_stream_handler`.
        if cancel.is_cancelled() {
            outcome.cancelled = true;
            break;
        }
        let row = item?;
        outcome.total_seen += 1;

        match policy {
            BackpressurePolicy::Fail => {
                if kept.len() >= max_rows {
                    return Err(StoreError::Query {
                        op: "retrieve",
                        source: format!(
                            "result set exceeds the {max_rows}-row stream \
                             bound (backpressure policy: fail)"
                        ),
                    });
                }
                kept.push_back(row);
            }
            BackpressurePolicy::DropOldest => {
                kept.push_back(row);
                if kept.len() > max_rows {
                    kept.pop_front();
                    outcome.dropped += 1;
                }
            }
            BackpressurePolicy::PauseUpstream => {
                if kept.len() >= max_rows {
                    // Stop polling — the cursor pauses + is dropped.
                    outcome.truncated = true;
                    break;
                }
                kept.push_back(row);
            }
            BackpressurePolicy::DegradeQuality => {
                // OSS identity degrader — every row, unbounded, no
                // degradation. Enterprise overrides this arm.
                kept.push_back(row);
            }
        }
    }

    outcome.rows = kept.into_iter().collect();
    Ok(outcome)
}

// ════════════════════════════════════════════════════════════════════
//  stream_retrieve — the live Postgres cursor drain
// ════════════════════════════════════════════════════════════════════

/// Run `retrieve` as a lazy cursor stream: open a server-side cursor
/// over `SELECT * FROM table WHERE φ`, decode rows one at a time, and
/// drain them through [`drain_with_policy`]. The full result set is
/// **never** materialized by `sqlx` — rows flow off the cursor as the
/// drain pulls them.
///
/// Cancel-aware via `cancel`; bounded by `policy` + `max_rows`.
pub async fn stream_retrieve(
    backend: &PostgresStoreBackend,
    table: &str,
    where_expr: &str,
    policy: BackpressurePolicy,
    max_rows: usize,
    cancel: &CancellationFlag,
    // §Fase 37.d (D3) — resolves `${name}` in `where_expr` to `$N`
    // bind parameters (the Request Binding Contract on the filter path).
    bindings: &std::collections::HashMap<String, String>,
) -> Result<RowStreamOutcome, StoreError> {
    // §Fase 37.x.b — resolve the table (schema + column types) via the
    // search-path-independent `resolve_table`; degrade to an empty map
    // on a resolution failure (§37.x.h / D6 surfaces the typed error).
    let resolved = backend.resolve_table(table).await;
    let no_types = std::collections::HashMap::new();
    let column_types = match &resolved {
        Ok(r) => &r.column_types,
        Err(_) => &no_types,
    };
    let (sql, params): (String, Vec<SqlValue>) =
        build_select_sql(table, where_expr, bindings, column_types)?;

    let mut query = sqlx::query(&sql);
    for value in &params {
        query = bind_value(query, value);
    }

    // `.fetch()` is the lazy cursor — rows are NOT all buffered.
    let cursor = query.fetch(backend.pool()).map(|item| {
        item.map_err(|e| StoreError::Query {
            op: "retrieve",
            source: e.to_string(),
        })
        .and_then(|pg_row| map_pg_row(&pg_row))
    });

    drain_with_policy(cursor, policy, max_rows, cancel).await
}

// ════════════════════════════════════════════════════════════════════
//  Streaming metadata for the retrieve envelope
// ════════════════════════════════════════════════════════════════════

/// Build the `"stream"` sub-object describing how a streamed
/// `retrieve` was drained — merged into the Pillar I epistemic
/// envelope (35.g) so the adopter sees both the trust grade AND the
/// streaming disposition of the result.
pub fn stream_metadata(
    policy: BackpressurePolicy,
    outcome: &RowStreamOutcome,
) -> JsonValue {
    json!({
        "policy": policy.slug(),
        "total_seen": outcome.total_seen,
        "dropped": outcome.dropped,
        "truncated": outcome.truncated,
        "cancelled": outcome.cancelled,
    })
}

// ════════════════════════════════════════════════════════════════════
//  Unit tests — the drain (synthetic streams, no database)
// ════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn row(id: i64) -> StoreRow {
        StoreRow {
            columns: vec![("id".to_string(), Value::from(id))],
        }
    }

    /// A synthetic Ok-row stream.
    fn ok_stream(
        n: usize,
    ) -> impl Stream<Item = Result<StoreRow, StoreError>> + Unpin {
        futures::stream::iter(
            (0..n as i64).map(|i| Ok(row(i))).collect::<Vec<_>>(),
        )
    }

    // ── Fail policy ──────────────────────────────────────────────────

    #[tokio::test]
    async fn fail_policy_allows_a_result_within_the_bound() {
        let outcome = drain_with_policy(
            ok_stream(5),
            BackpressurePolicy::Fail,
            10,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        assert_eq!(outcome.rows.len(), 5);
        assert_eq!(outcome.total_seen, 5);
    }

    #[tokio::test]
    async fn fail_policy_errors_when_the_result_exceeds_the_bound() {
        let result = drain_with_policy(
            ok_stream(50),
            BackpressurePolicy::Fail,
            10,
            &CancellationFlag::new(),
        )
        .await;
        assert!(matches!(result, Err(StoreError::Query { .. })));
    }

    // ── DropOldest policy ────────────────────────────────────────────

    #[tokio::test]
    async fn drop_oldest_keeps_the_most_recent_window() {
        let outcome = drain_with_policy(
            ok_stream(100),
            BackpressurePolicy::DropOldest,
            10,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        assert_eq!(outcome.rows.len(), 10, "bounded to the window");
        assert_eq!(outcome.dropped, 90);
        assert_eq!(outcome.total_seen, 100);
        // The window is the TAIL — rows 90..100.
        assert_eq!(outcome.rows.first().unwrap().get("id"), Some(&Value::from(90)));
        assert_eq!(outcome.rows.last().unwrap().get("id"), Some(&Value::from(99)));
    }

    // ── PauseUpstream policy ─────────────────────────────────────────

    #[tokio::test]
    async fn pause_upstream_truncates_at_the_bound() {
        let outcome = drain_with_policy(
            ok_stream(100),
            BackpressurePolicy::PauseUpstream,
            10,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        assert_eq!(outcome.rows.len(), 10);
        assert!(outcome.truncated, "more rows existed past the bound");
        // The window is the HEAD — rows 0..10.
        assert_eq!(outcome.rows.first().unwrap().get("id"), Some(&Value::from(0)));
        assert_eq!(outcome.rows.last().unwrap().get("id"), Some(&Value::from(9)));
    }

    #[tokio::test]
    async fn pause_upstream_within_the_bound_is_not_truncated() {
        let outcome = drain_with_policy(
            ok_stream(3),
            BackpressurePolicy::PauseUpstream,
            10,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        assert_eq!(outcome.rows.len(), 3);
        assert!(!outcome.truncated);
    }

    // ── DegradeQuality policy ────────────────────────────────────────

    #[tokio::test]
    async fn degrade_quality_is_the_oss_identity_drain() {
        let outcome = drain_with_policy(
            ok_stream(50),
            BackpressurePolicy::DegradeQuality,
            10,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        // OSS identity degrader — every row, the bound is not applied.
        assert_eq!(outcome.rows.len(), 50);
        assert_eq!(outcome.dropped, 0);
        assert!(!outcome.truncated);
    }

    // ── Cancellation ─────────────────────────────────────────────────

    #[tokio::test]
    async fn a_cancelled_flag_stops_the_drain_immediately() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let outcome = drain_with_policy(
            ok_stream(100),
            BackpressurePolicy::DegradeQuality,
            1000,
            &cancel,
        )
        .await
        .unwrap();
        assert!(outcome.cancelled);
        assert!(outcome.rows.is_empty(), "no row consumed after cancel");
    }

    // ── Decode error aborts ──────────────────────────────────────────

    #[tokio::test]
    async fn a_row_decode_error_aborts_the_drain() {
        let items: Vec<Result<StoreRow, StoreError>> = vec![
            Ok(row(0)),
            Err(StoreError::Decode {
                column: "x".into(),
                pg_type: "INT4".into(),
                source: "boom".into(),
            }),
            Ok(row(2)),
        ];
        let result = drain_with_policy(
            futures::stream::iter(items),
            BackpressurePolicy::DegradeQuality,
            100,
            &CancellationFlag::new(),
        )
        .await;
        assert!(matches!(result, Err(StoreError::Decode { .. })));
    }

    // ── Empty result ─────────────────────────────────────────────────

    #[tokio::test]
    async fn an_empty_result_drains_cleanly() {
        let outcome = drain_with_policy(
            ok_stream(0),
            DEFAULT_RETRIEVE_POLICY,
            DEFAULT_MAX_ROWS,
            &CancellationFlag::new(),
        )
        .await
        .unwrap();
        assert!(outcome.rows.is_empty());
        assert_eq!(outcome.total_seen, 0);
        assert!(!outcome.truncated && !outcome.cancelled);
    }

    // ── stream_metadata ──────────────────────────────────────────────

    #[test]
    fn stream_metadata_carries_the_drain_disposition() {
        let outcome = RowStreamOutcome {
            rows: vec![row(1)],
            total_seen: 100,
            dropped: 99,
            truncated: false,
            cancelled: false,
        };
        let meta = stream_metadata(BackpressurePolicy::DropOldest, &outcome);
        assert_eq!(meta["policy"], "drop_oldest");
        assert_eq!(meta["total_seen"], 100);
        assert_eq!(meta["dropped"], 99);
        assert_eq!(meta["truncated"], false);
    }

    #[test]
    fn defaults_are_pause_upstream_and_a_sane_bound() {
        assert_eq!(DEFAULT_RETRIEVE_POLICY, BackpressurePolicy::PauseUpstream);
        assert!(DEFAULT_MAX_ROWS >= 1000);
    }
}
