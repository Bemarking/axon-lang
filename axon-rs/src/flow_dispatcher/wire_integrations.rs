//! §Fase 33.y.h — Wire-integration handler nodes.
//!
//! Ten variants graduated in 33.y.h, organised in 3 architectural
//! groups:
//!
//! 1. **π-calc typed channels** (Fase 13) — `Emit` / `Publish` /
//!    `Discover`. Output prefix + capability extrusion + dual
//!    discovery. OSS in-memory backing via `ctx.let_bindings` under
//!    `__channel_<ref>` / `__pub_<ref>` / `__cap_<ref>` namespaced
//!    keys; enterprise integrations override via future
//!    `channel_runtime` field on `DispatchCtx`.
//!
//! 2. **Persistence primitives** — `Persist` / `Retrieve` / `Mutate`
//!    / `Purge` / `Transact`. OSS reference uses
//!    `ctx.let_bindings` namespaced keys (`__store_<name>_<entry>`)
//!    as in-memory backing; enterprise integrations override via
//!    future `persistence_runtime` field (Postgres / Redis / etc.).
//!
//! 3. **Multi-agent deliberation** — `Deliberate` / `Consensus`.
//!    Both are payload-free in v1.25.0; handlers emit canonical
//!    wire shape only. Future IR extensions wire bodies into
//!    helpers.
//!
//! # OSS reference impl discipline
//!
//! Like 33.y.g's algebraic-effect handlers, 33.y.h ships an OSS
//! **framework** with public helper functions that enterprise
//! integrations override. The OSS defaults use simple `let_bindings`
//! namespaced keys so adopters running on the reference impl get
//! sensible in-memory semantics; enterprise R&D wires
//! production-grade backends transparently.
//!
//! # D-letter anchors
//!
//! - **D1** — every variant has a NAMED async handler; exhaustive
//!   match in `dispatch_node`.
//! - **D3** — cancel checked at every `.await` boundary.
//! - **D7** — every error case routes through `DispatchError`; OSS
//!   helpers cannot fail (they manipulate in-memory state);
//!   enterprise overrides surface `DispatchError::BackendError`.
//! - **D10** — sync-runner parity: in-memory let_bindings semantics
//!   match the principled persistence + channel discipline.

use crate::flow_dispatcher::{DispatchCtx, DispatchError, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use crate::ir_nodes::{
    IRConsensusBlock, IRDeliberateBlock, IRDiscover, IREmit, IRMutateStep,
    IRPersistStep, IRPublish, IRPurgeStep, IRRetrieveStep, IRTransactBlock,
};
use crate::store::audit_chain::StoreMutationKind;
use crate::store::capability;
use crate::store::epistemic;
use crate::store::row_stream;
use crate::store::filter::SqlValue;
use crate::store::postgres_backend::{PostgresStoreBackend, StoreError};
use crate::store::registry::StoreHandle;

// ────────────────────────────────────────────────────────────────────
//  Public helpers (enterprise hooks override these)
// ────────────────────────────────────────────────────────────────────
//
// Each helper uses `ctx.let_bindings` with prefixed keys as the OSS
// in-memory backing store. Namespace prefixes:
//   - `__channel_<ref>` — π-calc channel buffer (Emit/Discover)
//   - `__pub_<ref>` — published capability extrusion (Publish)
//   - `__cap_<ref>` — discovered capability binding
//   - `__store_<name>_<entry>` — persistence store entry
//   - `__txn_active` — active transaction marker

/// Emit a value onto a typed channel. OSS default: append the
/// resolved value to a `__channel_<ref>` queue (newline-separated
/// in let_bindings). Enterprise overrides route through the
/// typed-channel runtime (Fase 13 + axon_enterprise.channels).
pub fn emit_to_channel(channel_ref: &str, value: &str, ctx: &mut DispatchCtx) -> String {
    let key = format!("__channel_{channel_ref}");
    let existing = ctx.let_bindings.get(&key).cloned().unwrap_or_default();
    let updated = if existing.is_empty() {
        value.to_string()
    } else {
        format!("{existing}\n{value}")
    };
    ctx.let_bindings.insert(key, updated);
    value.to_string()
}

/// Publish a capability (channel_ref guarded by shield_ref) for
/// later discovery. OSS default: bind `__pub_<channel_ref> =
/// <shield_ref>` in let_bindings. Enterprise overrides hook into
/// the capability registry.
pub fn publish_capability(channel_ref: &str, shield_ref: &str, ctx: &mut DispatchCtx) -> String {
    let key = format!("__pub_{channel_ref}");
    ctx.let_bindings.insert(key, shield_ref.to_string());
    format!("published {channel_ref} with {shield_ref}")
}

/// Discover a previously-published capability. OSS default: look
/// up `__pub_<capability_ref>` in let_bindings; returns the shield
/// reference (or empty if not found). Enterprise overrides query
/// the capability registry.
pub fn discover_capability(capability_ref: &str, ctx: &DispatchCtx) -> String {
    let key = format!("__pub_{capability_ref}");
    ctx.let_bindings.get(&key).cloned().unwrap_or_default()
}

/// Persist the current let_bindings under `store_name`. OSS
/// default: copies all NON-prefixed (user-level) bindings into
/// `__store_<name>_<entry>` keys. Returns the count of entries
/// snapshotted. Enterprise overrides route to Postgres / Redis /
/// adopter-pluggable backends.
pub fn persist_to_store(store_name: &str, ctx: &mut DispatchCtx) -> usize {
    // Collect non-prefixed (user-level) bindings first.
    let prefix = format!("__store_{store_name}_");
    let user_bindings: Vec<(String, String)> = ctx
        .let_bindings
        .iter()
        .filter(|(k, _)| !k.starts_with("__"))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let count = user_bindings.len();
    for (k, v) in user_bindings {
        ctx.let_bindings.insert(format!("{prefix}{k}"), v);
    }
    count
}

/// Retrieve a value from a persistence store. OSS default: looks
/// up `__store_<name>_<where_expr>` in let_bindings. `where_expr`
/// is treated as the entry key in this OSS reference (a full
/// query predicate language is enterprise R&D). Returns the
/// stored value (or empty if not found).
pub fn retrieve_from_store(
    store_name: &str,
    where_expr: &str,
    ctx: &DispatchCtx,
) -> String {
    let key = format!("__store_{store_name}_{where_expr}");
    ctx.let_bindings.get(&key).cloned().unwrap_or_default()
}

/// Mutate entries in a store matching where_expr. OSS default:
/// updates `__store_<name>_<where_expr>` with the value resolved
/// from let_bindings[where_expr] (or where_expr literal). Returns
/// the count of affected entries (0 or 1 in OSS; multi-row
/// updates are enterprise R&D).
pub fn mutate_store(store_name: &str, where_expr: &str, ctx: &mut DispatchCtx) -> u64 {
    let key = format!("__store_{store_name}_{where_expr}");
    if !ctx.let_bindings.contains_key(&key) {
        return 0;
    }
    let new_value = ctx
        .let_bindings
        .get(where_expr)
        .cloned()
        .unwrap_or_else(|| where_expr.to_string());
    ctx.let_bindings.insert(key, new_value);
    1
}

/// Purge entries from a store matching where_expr. OSS default:
/// removes `__store_<name>_<where_expr>` from let_bindings.
/// Returns the count of purged entries.
pub fn purge_from_store(
    store_name: &str,
    where_expr: &str,
    ctx: &mut DispatchCtx,
) -> u64 {
    let key = format!("__store_{store_name}_{where_expr}");
    if ctx.let_bindings.remove(&key).is_some() {
        1
    } else {
        0
    }
}

// ────────────────────────────────────────────────────────────────────
//  §Fase 35.f — axonstore SQL routing
// ────────────────────────────────────────────────────────────────────
//
// `run_persist`/`run_retrieve`/`run_mutate`/`run_purge` consult the
// `DispatchCtx`'s `store_registry` (Fase 35.d). A `postgresql`-backed
// store routes through `PostgresStoreBackend`; every other store —
// and every store when no registry is attached — takes the byte-
// identical key-value path above (D3, absolute). D5: this is the SAME
// `PostgresStoreBackend` the sync runner uses (35.e), so the two
// execution paths never diverge.

/// Resolve a store name to its Postgres backend + declared
/// `confidence_floor`, if it routes to SQL.
///
/// - `Ok(None)` — the key-value path: no registry attached, or the
///   store is `in_memory` / undeclared.
/// - `Ok(Some((backend, floor)))` — the SQL path; `floor` is the
///   store's `confidence_floor` (Pillar I, 35.g).
/// - `Err(StoreError)` — a declared `postgresql` store whose
///   connection could not be resolved. D2 — surfaced loudly, NEVER a
///   silent fallback to the key-value store.
fn resolve_pg_backend(
    ctx: &DispatchCtx,
    store_name: &str,
) -> Result<Option<(PostgresStoreBackend, Option<f64>)>, StoreError> {
    let Some(registry) = ctx.store_registry.as_ref() else {
        return Ok(None);
    };
    match registry.resolve(store_name)? {
        StoreHandle::InMemory => Ok(None),
        StoreHandle::Postgres(backend) => {
            let floor =
                registry.spec(store_name).and_then(|s| s.confidence_floor);
            Ok(Some((backend, floor)))
        }
    }
}

/// Build the row a `persist`/`mutate` writes — every user-level
/// let-binding (the `__`-prefixed namespace keys are runtime
/// bookkeeping) as a text column, sorted by name for deterministic
/// SQL. Mirrors `persist_to_store`'s snapshot discipline.
fn sql_row_from_bindings(ctx: &DispatchCtx) -> Vec<(String, SqlValue)> {
    let mut row: Vec<(String, SqlValue)> = ctx
        .let_bindings
        .iter()
        .filter(|(k, _)| !k.starts_with("__"))
        .map(|(k, v)| (k.clone(), SqlValue::Text(v.clone())))
        .collect();
    row.sort_by(|a, b| a.0.cmp(&b.0));
    row
}

/// §Fase 35.o / 35.p — Build the SQL row a `persist` (`INSERT`
/// columns) or a `mutate` (`UPDATE … SET` assignments) writes.
///
/// When the step declared a `{ col: value }` block, the row is EXACTLY
/// those columns, with each value expression interpolated against the
/// flow's `let_bindings` via the SAME `${name}` engine the sync runner
/// uses ([`crate::exec_context::interpolate_vars`], D5 — the two
/// execution paths never diverge). When no block was declared
/// (`fields` empty), it falls back to `sql_row_from_bindings` — the
/// v1.31.0 user-bindings form — so a `persist`/`mutate` with no block
/// is byte-for-byte unchanged.
fn store_row(fields: &[(String, String)], ctx: &DispatchCtx) -> Vec<(String, SqlValue)> {
    if fields.is_empty() {
        return sql_row_from_bindings(ctx);
    }
    fields
        .iter()
        .map(|(col, expr)| {
            (
                col.clone(),
                SqlValue::Text(crate::exec_context::interpolate_vars(
                    expr,
                    &ctx.let_bindings,
                )),
            )
        })
        .collect()
}

/// Map a [`StoreError`] to a [`DispatchError`] so a failed SQL store
/// op surfaces as a structured `axon.error` event — never a panic,
/// never a silent empty result.
fn sql_dispatch_error(e: StoreError) -> DispatchError {
    DispatchError::BackendError {
        name: "axonstore".to_string(),
        message: e.to_string(),
    }
}

/// §Fase 35.j Pillar IV — re-check a capability-gated store against the
/// request's held capabilities before any access. A no-op when no
/// capability context is attached (`held_capabilities == None`) — the
/// type-checker's compile-time guarantee + the endpoint's Fase 32.g
/// `requires:` gate stand. A denial surfaces as a structured
/// `axon.error`, never a silent read of isolated data.
fn enforce_store_capability(
    ctx: &DispatchCtx,
    store_name: &str,
) -> Result<(), DispatchError> {
    let Some(held) = ctx.held_capabilities.as_ref() else {
        return Ok(());
    };
    let required = ctx
        .store_registry
        .as_ref()
        .and_then(|r| r.spec(store_name))
        .map(|s| s.capability.as_str())
        .unwrap_or("");
    capability::check_store_capability(store_name, required, held).map_err(
        |denied| DispatchError::BackendError {
            name: "axonstore.capability".to_string(),
            message: denied.to_string(),
        },
    )
}

/// §Fase 35.h Pillar II — append a mutation delta to the flow's
/// tamper-evident HMAC-Merkle audit chain. Called after a `persist` /
/// `mutate` / `purge` succeeds (a failed op `return`s before reaching
/// here). Best-effort: a poisoned lock is recovered, never panicked.
fn record_store_mutation(
    ctx: &DispatchCtx,
    kind: StoreMutationKind,
    store: &str,
    summary: &str,
) {
    let mut chain = ctx
        .audit_chain
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    chain.record(kind, store, summary);
}

// ────────────────────────────────────────────────────────────────────
//  Emit (Fase 13 π-calc output prefix)
// ────────────────────────────────────────────────────────────────────

/// Emit a value onto a channel. Wire shape: `step_type: "emit"`.
pub async fn run_emit(
    node: &IREmit,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.channel_ref.is_empty() {
        "Emit".to_string()
    } else {
        node.channel_ref.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "emit")?;

    // Resolve value_ref through let_bindings; literal if missing.
    let resolved_value = ctx
        .let_bindings
        .get(&node.value_ref)
        .cloned()
        .unwrap_or_else(|| node.value_ref.clone());

    let emitted = emit_to_channel(&node.channel_ref, &resolved_value, ctx);

    emit_step_complete(ctx, &step_name, step_index, &emitted, 0)?;

    Ok(NodeOutcome::Completed {
        output: emitted,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Publish (Fase 13 π-calc capability extrusion)
// ────────────────────────────────────────────────────────────────────

/// Publish a capability. Wire shape: `step_type: "publish"`.
pub async fn run_publish(
    node: &IRPublish,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.channel_ref.is_empty() {
        "Publish".to_string()
    } else {
        node.channel_ref.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "publish")?;

    let output = publish_capability(&node.channel_ref, &node.shield_ref, ctx);

    emit_step_complete(ctx, &step_name, step_index, &output, 0)?;

    Ok(NodeOutcome::Completed {
        output,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Discover (Fase 13 π-calc dual of Publish)
// ────────────────────────────────────────────────────────────────────

/// Discover a capability. Wire shape: `step_type: "discover"`.
/// Binds the discovered shield reference under `alias` in
/// let_bindings.
pub async fn run_discover(
    node: &IRDiscover,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.alias.is_empty() {
        "Discover".to_string()
    } else {
        node.alias.clone()
    };
    emit_step_start(ctx, &step_name, step_index, "discover")?;

    let discovered = discover_capability(&node.capability_ref, ctx);
    if !node.alias.is_empty() {
        ctx.let_bindings.insert(node.alias.clone(), discovered.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &discovered, 0)?;

    Ok(NodeOutcome::Completed {
        output: discovered,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Persist
// ────────────────────────────────────────────────────────────────────

/// Persist the current bindings to a store. Wire shape:
/// `step_type: "persist"`.
pub async fn run_persist(
    node: &IRPersistStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.store_name.is_empty() {
        "Persist".to_string()
    } else {
        node.store_name.clone()
    };
    // §Fase 35.j Pillar IV — capability gate (before any side effect).
    enforce_store_capability(ctx, &node.store_name)?;
    emit_step_start(ctx, &step_name, step_index, "persist")?;

    let output = match resolve_pg_backend(ctx, &node.store_name) {
        Ok(Some((backend, floor))) => {
            // §35.o — scope the row to the declared `{ col: value }`
            // block when present; else the v1.31.0 user-bindings form.
            let row = store_row(&node.fields, ctx);
            // §35.g Pillar I — a sub-floor or un-elevated write into a
            // confidence-floored store is a typed error.
            epistemic::enforce_persist_floor(&row, floor, &node.store_name)
                .map_err(|e| sql_dispatch_error(StoreError::from(e)))?;
            // §Fase 37.x.j (D1) — wrap the backend pool in a `StoreConn`
            // and dispatch through it. Sub-fases 37.x.j.4/5 will switch
            // this to `StoreConn::Pinned(&mut ctx.pinned_conn)` so the
            // insert runs on the same physical Postgres backend as every
            // other op against this store in the flow.
            let mut store_conn = crate::store::store_conn::StoreConn::Pool(backend.pool());
            let n = backend
                .insert(&mut store_conn, &node.store_name, &row)
                .await
                .map_err(sql_dispatch_error)?;
            format!("persisted {n} row(s) to `{}`", node.store_name)
        }
        Ok(None) => {
            let count = persist_to_store(&node.store_name, ctx);
            format!("persisted {count} entries to `{}`", node.store_name)
        }
        Err(e) => return Err(sql_dispatch_error(e)),
    };

    // §Fase 35.h Pillar II — chain the mutation.
    record_store_mutation(ctx, StoreMutationKind::Persist, &node.store_name, &output);
    emit_step_complete(ctx, &step_name, step_index, &output, 0)?;

    Ok(NodeOutcome::Completed {
        output,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Retrieve
// ────────────────────────────────────────────────────────────────────

/// Retrieve from a store. Wire shape: `step_type: "retrieve"`.
/// Binds the retrieved value under `alias` in let_bindings.
pub async fn run_retrieve(
    node: &IRRetrieveStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.alias.is_empty() {
        "Retrieve".to_string()
    } else {
        node.alias.clone()
    };
    // §Fase 35.j Pillar IV — capability gate (before any side effect).
    enforce_store_capability(ctx, &node.store_name)?;
    emit_step_start(ctx, &step_name, step_index, "retrieve")?;

    let value = match resolve_pg_backend(ctx, &node.store_name) {
        Ok(Some((backend, floor))) => {
            // §35.i Pillar III — retrieve drains off a lazy cursor,
            // bounded + cancel-aware (never materializes a huge result
            // set). §35.g Pillar I — every tuple born Untrusted,
            // confidence_floor filters sub-floor rows. The bound value
            // is an epistemic envelope carrying both dispositions.
            // §Fase 37.x.j (D1) — wrap the backend pool in a `StoreConn`.
            // 37.x.j.5 will switch this to `StoreConn::Pinned(...)` from
            // `ctx.pinned_conns` so the retrieve runs on the flow-pinned
            // physical connection.
            let mut store_conn = crate::store::store_conn::StoreConn::Pool(backend.pool());
            let stream_outcome = row_stream::stream_retrieve(
                &backend,
                &mut store_conn,
                &node.store_name,
                &node.where_expr,
                row_stream::DEFAULT_RETRIEVE_POLICY,
                row_stream::DEFAULT_MAX_ROWS,
                &ctx.cancel,
                // §Fase 37.d (D3) — resolve `${name}` in the `where`
                // clause to `$N` bind parameters via the filter
                // compiler (never string-spliced into the SQL).
                &ctx.let_bindings,
            )
            .await
            .map_err(sql_dispatch_error)?;
            let metadata = row_stream::stream_metadata(
                row_stream::DEFAULT_RETRIEVE_POLICY,
                &stream_outcome,
            );
            let floored = epistemic::enforce_retrieve_floor(
                epistemic::mark_retrieved(stream_outcome.rows),
                floor,
            );
            let mut envelope = epistemic::retrieve_envelope(&floored, floor);
            envelope["stream"] = metadata;
            serde_json::to_string(&envelope).unwrap_or_else(|_| "{}".to_string())
        }
        Ok(None) => retrieve_from_store(&node.store_name, &node.where_expr, ctx),
        Err(e) => return Err(sql_dispatch_error(e)),
    };
    if !node.alias.is_empty() {
        ctx.let_bindings.insert(node.alias.clone(), value.clone());
    }

    emit_step_complete(ctx, &step_name, step_index, &value, 0)?;

    Ok(NodeOutcome::Completed {
        output: value,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Mutate
// ────────────────────────────────────────────────────────────────────

/// Mutate entries in a store. Wire shape: `step_type: "mutate"`.
pub async fn run_mutate(
    node: &IRMutateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.store_name.is_empty() {
        "Mutate".to_string()
    } else {
        node.store_name.clone()
    };
    // §Fase 35.j Pillar IV — capability gate (before any side effect).
    enforce_store_capability(ctx, &node.store_name)?;
    emit_step_start(ctx, &step_name, step_index, "mutate")?;

    let output = match resolve_pg_backend(ctx, &node.store_name) {
        Ok(Some((backend, _floor))) => {
            // §35.p — scope the UPDATE SET to the declared
            // `{ col: value }` block when present; else the v1.31.0
            // user-bindings form.
            let row = store_row(&node.fields, ctx);
            // §Fase 37.x.j (D1) — see `insert` call site above for the
            // StoreConn::Pool legacy wrapper rationale.
            let mut store_conn = crate::store::store_conn::StoreConn::Pool(backend.pool());
            let n = backend
                .mutate(&mut store_conn, &node.store_name, &node.where_expr, &row, &ctx.let_bindings)
                .await
                .map_err(sql_dispatch_error)?;
            format!("mutated {n} row(s) in `{}`", node.store_name)
        }
        Ok(None) => {
            let count = mutate_store(&node.store_name, &node.where_expr, ctx);
            format!("mutated {count} entries in `{}`", node.store_name)
        }
        Err(e) => return Err(sql_dispatch_error(e)),
    };

    // §Fase 35.h Pillar II — chain the mutation.
    record_store_mutation(ctx, StoreMutationKind::Mutate, &node.store_name, &output);
    emit_step_complete(ctx, &step_name, step_index, &output, 0)?;

    Ok(NodeOutcome::Completed {
        output,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Purge
// ────────────────────────────────────────────────────────────────────

/// Purge entries from a store. Wire shape: `step_type: "purge"`.
pub async fn run_purge(
    node: &IRPurgeStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    let step_name = if node.store_name.is_empty() {
        "Purge".to_string()
    } else {
        node.store_name.clone()
    };
    // §Fase 35.j Pillar IV — capability gate (before any side effect).
    enforce_store_capability(ctx, &node.store_name)?;
    emit_step_start(ctx, &step_name, step_index, "purge")?;

    let output = match resolve_pg_backend(ctx, &node.store_name) {
        Ok(Some((backend, _floor))) => {
            // §Fase 37.x.j (D1) — see other call sites in this file
            // for the StoreConn::Pool legacy wrapper rationale.
            let mut store_conn = crate::store::store_conn::StoreConn::Pool(backend.pool());
            let n = backend
                .purge(&mut store_conn, &node.store_name, &node.where_expr, &ctx.let_bindings)
                .await
                .map_err(sql_dispatch_error)?;
            format!("purged {n} row(s) from `{}`", node.store_name)
        }
        Ok(None) => {
            let count = purge_from_store(&node.store_name, &node.where_expr, ctx);
            format!("purged {count} entries from `{}`", node.store_name)
        }
        Err(e) => return Err(sql_dispatch_error(e)),
    };

    // §Fase 35.h Pillar II — chain the mutation.
    record_store_mutation(ctx, StoreMutationKind::Purge, &node.store_name, &output);
    emit_step_complete(ctx, &step_name, step_index, &output, 0)?;

    Ok(NodeOutcome::Completed {
        output,
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Transact (payload-free in v1.25.0)
// ────────────────────────────────────────────────────────────────────

/// Transaction marker. Wire shape: `step_type: "transact"`.
/// Payload-free in v1.25.0; binds `__txn_active = "true"` so
/// nested wire-integration handlers can detect transactional
/// context (foundation for enterprise distributed-tx integration).
pub async fn run_transact(
    _node: &IRTransactBlock,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Transact", step_index, "transact")?;

    ctx.let_bindings
        .insert("__txn_active".to_string(), "true".to_string());

    emit_step_complete(ctx, "Transact", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Deliberate (payload-free multi-agent block)
// ────────────────────────────────────────────────────────────────────

/// Multi-agent deliberation block. Wire shape:
/// `step_type: "deliberate"`. Payload-free in v1.25.0.
pub async fn run_deliberate(
    _node: &IRDeliberateBlock,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Deliberate", step_index, "deliberate")?;
    emit_step_complete(ctx, "Deliberate", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Consensus (payload-free multi-agent block)
// ────────────────────────────────────────────────────────────────────

/// Multi-agent consensus block. Wire shape:
/// `step_type: "consensus"`. Payload-free in v1.25.0.
pub async fn run_consensus(
    _node: &IRConsensusBlock,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Consensus", step_index, "consensus")?;
    emit_step_complete(ctx, "Consensus", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Wire-event helpers (shared)
// ────────────────────────────────────────────────────────────────────

fn emit_step_start(
    ctx: &mut DispatchCtx,
    step_name: &str,
    step_index: usize,
    step_type: &str,
) -> Result<(), DispatchError> {
    ctx.tx
        .send(FlowExecutionEvent::StepStart {
            step_name: step_name.to_string(),
            step_index,
            step_type: step_type.to_string(),
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)
}

fn emit_step_complete(
    ctx: &mut DispatchCtx,
    step_name: &str,
    step_index: usize,
    full_output: &str,
    tokens_output: u64,
) -> Result<(), DispatchError> {
    ctx.tx
        .send(FlowExecutionEvent::StepComplete {
            step_name: step_name.to_string(),
            step_index,
            success: true,
            full_output: full_output.to_string(),
            tokens_input: 0,
            tokens_output,
            timestamp_ms: now_ms(),
        })
        .map_err(|_| DispatchError::ChannelClosed)
}

// ────────────────────────────────────────────────────────────────────
//  Unit tests
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cancel_token::CancellationFlag;
    use crate::ir_nodes::*;
    use tokio::sync::mpsc;

    fn fresh_ctx() -> (
        DispatchCtx,
        mpsc::UnboundedReceiver<FlowExecutionEvent>,
    ) {
        let (tx, rx) = mpsc::unbounded_channel();
        let ctx = DispatchCtx::new(
            "TestFlow",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        );
        (ctx, rx)
    }

    // ── Helpers ─────────────────────────────────────────────────────

    #[test]
    fn emit_to_channel_appends_to_buffer() {
        let (mut ctx, _rx) = fresh_ctx();
        emit_to_channel("c1", "v1", &mut ctx);
        emit_to_channel("c1", "v2", &mut ctx);
        let buffer = ctx.let_bindings.get("__channel_c1").unwrap();
        assert_eq!(buffer, "v1\nv2");
    }

    #[test]
    fn publish_then_discover_round_trip() {
        let (mut ctx, _rx) = fresh_ctx();
        publish_capability("user_inbox", "shield_pii", &mut ctx);
        assert_eq!(discover_capability("user_inbox", &ctx), "shield_pii");
    }

    #[test]
    fn discover_missing_returns_empty() {
        let (ctx, _rx) = fresh_ctx();
        assert_eq!(discover_capability("never_set", &ctx), "");
    }

    #[test]
    fn persist_snapshots_user_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("name".into(), "alice".into());
        ctx.let_bindings.insert("age".into(), "30".into());
        ctx.let_bindings
            .insert("__internal".into(), "should_not_be_snapshotted".into());
        let count = persist_to_store("users", &mut ctx);
        assert_eq!(count, 2);
        assert_eq!(ctx.let_bindings.get("__store_users_name").unwrap(), "alice");
        assert_eq!(ctx.let_bindings.get("__store_users_age").unwrap(), "30");
        assert!(!ctx.let_bindings.contains_key("__store_users___internal"));
    }

    #[test]
    fn retrieve_from_store_returns_persisted_value() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("city".into(), "Bogota".into());
        persist_to_store("locations", &mut ctx);
        assert_eq!(retrieve_from_store("locations", "city", &ctx), "Bogota");
    }

    #[test]
    fn mutate_store_updates_existing_entry() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("counter".into(), "1".into());
        persist_to_store("metrics", &mut ctx);
        ctx.let_bindings.insert("counter".into(), "2".into());
        let count = mutate_store("metrics", "counter", &mut ctx);
        assert_eq!(count, 1);
        assert_eq!(
            ctx.let_bindings.get("__store_metrics_counter").unwrap(),
            "2"
        );
    }

    #[test]
    fn mutate_missing_entry_returns_zero() {
        let (mut ctx, _rx) = fresh_ctx();
        assert_eq!(mutate_store("empty", "k", &mut ctx), 0);
    }

    #[test]
    fn purge_removes_entry() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("key".into(), "value".into());
        persist_to_store("s", &mut ctx);
        let count = purge_from_store("s", "key", &mut ctx);
        assert_eq!(count, 1);
        assert!(!ctx.let_bindings.contains_key("__store_s_key"));
    }

    #[test]
    fn purge_missing_returns_zero() {
        let (mut ctx, _rx) = fresh_ctx();
        assert_eq!(purge_from_store("s", "absent", &mut ctx), 0);
    }

    // ── Handlers ────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_emit_appends_to_channel_buffer() {
        let (mut ctx, mut rx) = fresh_ctx();
        ctx.let_bindings.insert("payload".into(), "hello".into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "out_channel".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        let outcome = run_emit(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => assert_eq!(output, "hello"),
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(
            ctx.let_bindings.get("__channel_out_channel").unwrap(),
            "hello"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "emit");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_publish_records_capability() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRPublish {
            node_type: "publish",
            source_line: 0,
            source_column: 0,
            channel_ref: "secure_chan".into(),
            shield_ref: "hipaa".into(),
        };
        run_publish(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("__pub_secure_chan").unwrap(),
            "hipaa"
        );
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "publish");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_discover_binds_under_alias() {
        let (mut ctx, mut rx) = fresh_ctx();
        // Pre-publish
        publish_capability("secure_chan", "hipaa", &mut ctx);

        let node = IRDiscover {
            node_type: "discover",
            source_line: 0,
            source_column: 0,
            capability_ref: "secure_chan".into(),
            alias: "found".into(),
        };
        run_discover(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("found").unwrap(), "hipaa");
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "discover");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_persist_then_retrieve_round_trip() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("id".into(), "42".into());
        ctx.let_bindings.insert("name".into(), "test".into());

        let persist = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "entities".into(),
        };
        run_persist(&persist, &mut ctx).await.unwrap();

        // Clear and retrieve
        let retrieve = IRRetrieveStep {
            node_type: "retrieve",
            source_line: 0,
            source_column: 0,
            store_name: "entities".into(),
            where_expr: "id".into(),
            alias: "retrieved_id".into(),
        };
        run_retrieve(&retrieve, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("retrieved_id").unwrap(), "42");
    }

    /// §Fase 35.o — `store_row` with a declared `{ col: value }`
    /// block builds the SQL row from EXACTLY those columns, value
    /// expressions interpolated against `let_bindings`. No other
    /// context binding leaks in — the gap-report blocker, closed.
    #[test]
    fn store_row_scopes_to_the_declared_field_block() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("message".into(), "hello".into());
        ctx.let_bindings.insert("tenant_id".into(), "acme".into());
        ctx.let_bindings
            .insert("channel_kind".into(), "whatsapp".into());
        let node = IRPersistStep {
            node_type: "persist",
            source_line: 0,
            source_column: 0,
            store_name: "chat_history".into(),
            fields: vec![
                ("sender".into(), "user".into()),
                ("content".into(), "${message}".into()),
                ("tenant_id".into(), "${tenant_id}".into()),
            ],
        };
        let row = store_row(&node.fields, &ctx);
        assert_eq!(
            row,
            vec![
                ("sender".to_string(), SqlValue::Text("user".into())),
                ("content".to_string(), SqlValue::Text("hello".into())),
                ("tenant_id".to_string(), SqlValue::Text("acme".into())),
            ]
        );
        // `message` / `channel_kind` are raw context bindings, NOT
        // columns of `chat_history` — they must not reach the row.
        assert!(!row
            .iter()
            .any(|(c, _)| c == "channel_kind" || c == "message"));
    }

    /// §Fase 35.o — `store_row` with no declared block falls back to
    /// the v1.31.0 user-bindings form, byte-for-byte (backward-compat).
    #[test]
    fn store_row_without_a_block_falls_back_to_user_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("a".into(), "1".into());
        ctx.let_bindings.insert("b".into(), "2".into());
        let node = IRPersistStep {
            node_type: "persist",
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
            fields: Vec::new(),
        };
        assert_eq!(store_row(&node.fields, &ctx), sql_row_from_bindings(&ctx));
    }

    /// §Fase 35.p — an `IRMutateStep`'s `{ col: value }` SET block
    /// flows through the SAME `store_row` the dispatcher's `run_mutate`
    /// uses; the `UPDATE SET` is scoped to exactly those columns.
    #[test]
    fn store_row_for_a_mutate_node_scopes_to_its_set_block() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("new_balance".into(), "500".into());
        ctx.let_bindings.insert("tenant_id".into(), "acme".into());
        let node = IRMutateStep {
            node_type: "mutate",
            source_line: 0,
            source_column: 0,
            store_name: "accounts".into(),
            where_expr: "id = 1".into(),
            fields: vec![
                ("balance".into(), "${new_balance}".into()),
                ("status".into(), "active".into()),
            ],
        };
        let row = store_row(&node.fields, &ctx);
        assert_eq!(
            row,
            vec![
                ("balance".to_string(), SqlValue::Text("500".into())),
                ("status".to_string(), SqlValue::Text("active".into())),
            ]
        );
        // `tenant_id` is a flow binding, not a column — must not leak.
        assert!(!row.iter().any(|(c, _)| c == "tenant_id"));
    }

    #[tokio::test]
    async fn run_mutate_updates_existing() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("counter".into(), "1".into());
        let persist = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "stats".into(),
        };
        run_persist(&persist, &mut ctx).await.unwrap();

        ctx.let_bindings.insert("counter".into(), "2".into());
        let mutate = IRMutateStep {
            node_type: "mutate",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "stats".into(),
            where_expr: "counter".into(),
        };
        let outcome = run_mutate(&mutate, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => {
                assert!(output.contains("mutated 1 entries"));
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(
            ctx.let_bindings.get("__store_stats_counter").unwrap(),
            "2"
        );
    }

    #[tokio::test]
    async fn run_purge_removes_persisted_entry() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("tmp".into(), "data".into());
        run_persist(
            &IRPersistStep {
                node_type: "persist",
            fields: Vec::new(),
                source_line: 0,
                source_column: 0,
                store_name: "scratch".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();

        let outcome = run_purge(
            &IRPurgeStep {
                node_type: "purge",
                source_line: 0,
                source_column: 0,
                store_name: "scratch".into(),
                where_expr: "tmp".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => {
                assert!(output.contains("purged 1 entries"));
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert!(!ctx.let_bindings.contains_key("__store_scratch_tmp"));
    }

    #[tokio::test]
    async fn run_transact_sets_active_marker() {
        let (mut ctx, mut rx) = fresh_ctx();
        run_transact(
            &IRTransactBlock {
                node_type: "transact",
                source_line: 0,
                source_column: 0,
            },
            &mut ctx,
        )
        .await
        .unwrap();
        assert_eq!(ctx.let_bindings.get("__txn_active").unwrap(), "true");
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "transact");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_deliberate_canonical_wire_shape() {
        let (mut ctx, mut rx) = fresh_ctx();
        run_deliberate(
            &IRDeliberateBlock {
                node_type: "deliberate",
                source_line: 0,
                source_column: 0,
            },
            &mut ctx,
        )
        .await
        .unwrap();
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "deliberate");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_consensus_canonical_wire_shape() {
        let (mut ctx, mut rx) = fresh_ctx();
        run_consensus(
            &IRConsensusBlock {
                node_type: "consensus",
                source_line: 0,
                source_column: 0,
            },
            &mut ctx,
        )
        .await
        .unwrap();
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "consensus");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn every_handler_short_circuits_on_cancel() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        // Cancel each handler in turn — inline IR construction so
        // the borrow checker sees the IR as an owned local.
        let emit = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "c".into(),
            value_ref: "v".into(),
            value_is_channel: false,
        };
        assert!(matches!(run_emit(&emit, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let publish = IRPublish {
            node_type: "publish",
            source_line: 0,
            source_column: 0,
            channel_ref: "c".into(),
            shield_ref: "s".into(),
        };
        assert!(matches!(run_publish(&publish, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let discover = IRDiscover {
            node_type: "discover",
            source_line: 0,
            source_column: 0,
            capability_ref: "c".into(),
            alias: "a".into(),
        };
        assert!(matches!(run_discover(&discover, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let persist = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
        };
        assert!(matches!(run_persist(&persist, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let retrieve = IRRetrieveStep {
            node_type: "retrieve",
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
            where_expr: "w".into(),
            alias: "a".into(),
        };
        assert!(matches!(run_retrieve(&retrieve, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let mutate = IRMutateStep {
            node_type: "mutate",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
            where_expr: "w".into(),
        };
        assert!(matches!(run_mutate(&mutate, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let purge = IRPurgeStep {
            node_type: "purge",
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
            where_expr: "w".into(),
        };
        assert!(matches!(run_purge(&purge, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let transact = IRTransactBlock {
            node_type: "transact",
            source_line: 0,
            source_column: 0,
        };
        assert!(matches!(run_transact(&transact, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let deliberate = IRDeliberateBlock {
            node_type: "deliberate",
            source_line: 0,
            source_column: 0,
        };
        assert!(matches!(run_deliberate(&deliberate, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));

        let consensus = IRConsensusBlock {
            node_type: "consensus",
            source_line: 0,
            source_column: 0,
        };
        assert!(matches!(run_consensus(&consensus, &mut ctx).await, Err(DispatchError::UpstreamCancelled)));
    }

    // ── §Fase 35.f — axonstore SQL routing ──────────────────────────

    fn axonstore(name: &str, backend: &str, connection: &str) -> IRAxonStore {
        IRAxonStore {
            node_type: "axonstore",
            source_line: 0,
            source_column: 0,
            name: name.to_string(),
            backend: backend.to_string(),
            connection: connection.to_string(),
            confidence_floor: None,
            isolation: String::new(),
            on_breach: String::new(),
            capability: String::new(),
            column_schema: None,
        }
    }

    fn ctx_with_registry(
        specs: &[IRAxonStore],
    ) -> (DispatchCtx, mpsc::UnboundedReceiver<FlowExecutionEvent>) {
        let (tx, rx) = mpsc::unbounded_channel();
        let registry = crate::store::registry::StoreRegistry::build(specs).unwrap();
        let ctx = DispatchCtx::new("TestFlow", "stub", "", CancellationFlag::new(), tx)
            .with_store_registry(std::sync::Arc::new(registry));
        (ctx, rx)
    }

    #[test]
    fn resolve_pg_backend_no_registry_is_kv() {
        // No registry attached (the DispatchCtx::new default) → every
        // store op is key-value (D3 — pre-35 behavior unchanged).
        let (ctx, _rx) = fresh_ctx();
        assert!(resolve_pg_backend(&ctx, "anything").unwrap().is_none());
    }

    #[test]
    fn resolve_pg_backend_in_memory_store_is_kv() {
        let (ctx, _rx) = ctx_with_registry(&[axonstore("cache", "in_memory", "")]);
        assert!(resolve_pg_backend(&ctx, "cache").unwrap().is_none());
        // An undeclared store also takes the key-value path.
        assert!(resolve_pg_backend(&ctx, "undeclared").unwrap().is_none());
    }

    #[test]
    fn resolve_pg_backend_missing_env_var_errors_not_kv_fallback() {
        // D2 — a declared postgresql store whose env var is unset MUST
        // surface a typed error, never degrade silently to KV.
        let (ctx, _rx) = ctx_with_registry(&[axonstore(
            "tenants",
            "postgresql",
            "env:AXON_NONEXISTENT_VAR_FASE35F",
        )]);
        assert!(matches!(
            resolve_pg_backend(&ctx, "tenants"),
            Err(StoreError::MissingEnvVar { .. })
        ));
    }

    #[tokio::test]
    async fn run_retrieve_postgresql_missing_env_surfaces_backend_error() {
        // The SQL path is reached and fails honestly through the
        // dispatcher — a structured DispatchError, never a silent
        // empty KV result.
        let (mut ctx, _rx) = ctx_with_registry(&[axonstore(
            "tenants",
            "postgresql",
            "env:AXON_NONEXISTENT_VAR_FASE35F",
        )]);
        let node = IRRetrieveStep {
            node_type: "retrieve",
            source_line: 0,
            source_column: 0,
            store_name: "tenants".into(),
            where_expr: "id = 1".into(),
            alias: "found".into(),
        };
        assert!(matches!(
            run_retrieve(&node, &mut ctx).await,
            Err(DispatchError::BackendError { .. })
        ));
    }

    #[tokio::test]
    async fn run_persist_postgresql_malformed_dsn_surfaces_backend_error() {
        let (mut ctx, _rx) =
            ctx_with_registry(&[axonstore("events", "postgresql", "not a dsn")]);
        ctx.let_bindings.insert("kind".into(), "login".into());
        let node = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "events".into(),
        };
        assert!(matches!(
            run_persist(&node, &mut ctx).await,
            Err(DispatchError::BackendError { .. })
        ));
    }

    #[tokio::test]
    async fn run_persist_in_memory_store_keeps_byte_identical_kv_path() {
        // D3 — a registry IS attached but the store is in_memory, so
        // the key-value path runs: output shape says "entries" (not
        // "row(s)") and the namespaced `__store_` key is written.
        let (mut ctx, _rx) = ctx_with_registry(&[axonstore("cache", "in_memory", "")]);
        ctx.let_bindings.insert("k".into(), "v".into());
        let node = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "cache".into(),
        };
        match run_persist(&node, &mut ctx).await.unwrap() {
            NodeOutcome::Completed { output, .. } => {
                assert!(output.contains("entries"), "KV path output shape");
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("__store_cache_k").unwrap(), "v");
    }

    #[tokio::test]
    async fn run_persist_below_confidence_floor_is_blocked() {
        // §35.g Pillar I — the epistemic gate is wired into the
        // dispatcher's persist handler: an un-elevated write (no
        // `_confidence`) into a confidence-floored store is a typed
        // BackendError, before any row is written.
        let mut store =
            axonstore("ledger", "postgresql", "postgresql://u:p@localhost:5432/db");
        store.confidence_floor = Some(0.8);
        let (mut ctx, _rx) = ctx_with_registry(&[store]);
        ctx.let_bindings.insert("amount".into(), "100".into()); // no `_confidence`
        let node = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "ledger".into(),
        };
        assert!(matches!(
            run_persist(&node, &mut ctx).await,
            Err(DispatchError::BackendError { .. })
        ));
    }

    // ── §Fase 35.j — Pillar IV capability-gated store access ────────

    fn gated_kv(name: &str, capability: &str) -> IRAxonStore {
        let mut s = axonstore(name, "in_memory", "");
        s.capability = capability.to_string();
        s
    }

    fn ctx_with_caps(
        specs: &[IRAxonStore],
        held: Vec<String>,
    ) -> (DispatchCtx, mpsc::UnboundedReceiver<FlowExecutionEvent>) {
        let (tx, rx) = mpsc::unbounded_channel();
        let registry = crate::store::registry::StoreRegistry::build(specs).unwrap();
        let ctx = DispatchCtx::new("F", "stub", "", CancellationFlag::new(), tx)
            .with_store_registry(std::sync::Arc::new(registry))
            .with_held_capabilities(held);
        (ctx, rx)
    }

    fn retrieve_node(store: &str) -> IRRetrieveStep {
        IRRetrieveStep {
            node_type: "retrieve",
            source_line: 0,
            source_column: 0,
            store_name: store.to_string(),
            where_expr: "k".to_string(),
            alias: "v".to_string(),
        }
    }

    #[tokio::test]
    async fn retrieve_denied_when_capability_not_held() {
        // The gated store demands `tenant.read`; the request carries
        // only `audit.write` → a typed denial, never a silent read.
        let (mut ctx, _rx) = ctx_with_caps(
            &[gated_kv("tenants", "tenant.read")],
            vec!["audit.write".to_string()],
        );
        assert!(matches!(
            run_retrieve(&retrieve_node("tenants"), &mut ctx).await,
            Err(DispatchError::BackendError { .. })
        ));
    }

    #[tokio::test]
    async fn retrieve_allowed_when_capability_held() {
        // Holding the capability clears the gate; the in_memory KV
        // path then runs to completion.
        let (mut ctx, _rx) = ctx_with_caps(
            &[gated_kv("tenants", "tenant.read")],
            vec!["tenant.read".to_string()],
        );
        assert!(run_retrieve(&retrieve_node("tenants"), &mut ctx).await.is_ok());
    }

    #[tokio::test]
    async fn persist_into_gated_store_denied_without_capability() {
        let (mut ctx, _rx) =
            ctx_with_caps(&[gated_kv("ledger", "ledger.write")], vec![]);
        let node = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "ledger".into(),
        };
        assert!(matches!(
            run_persist(&node, &mut ctx).await,
            Err(DispatchError::BackendError { .. })
        ));
    }

    #[tokio::test]
    async fn ungated_store_needs_no_capability() {
        // An in_memory store with no `capability:` — accessible even
        // with an empty held set.
        let (mut ctx, _rx) =
            ctx_with_caps(&[axonstore("cache", "in_memory", "")], vec![]);
        assert!(run_retrieve(&retrieve_node("cache"), &mut ctx).await.is_ok());
    }

    #[tokio::test]
    async fn no_capability_context_skips_the_runtime_recheck() {
        // `held_capabilities == None` (DispatchCtx::new default) → the
        // runtime re-check is a no-op; the compile-time guarantee
        // stands. A gated store is reachable here (the dispatcher was
        // not given a capability context).
        let (mut ctx, _rx) = ctx_with_registry(&[gated_kv("tenants", "tenant.read")]);
        assert!(ctx.held_capabilities.is_none());
        assert!(run_retrieve(&retrieve_node("tenants"), &mut ctx).await.is_ok());
    }

    // ── §Fase 35.h — Pillar II audit-chained mutations ──────────────

    #[tokio::test]
    async fn persist_appends_a_delta_to_the_audit_chain() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("k".into(), "v".into());
        let node = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "s".into(),
        };
        run_persist(&node, &mut ctx).await.unwrap();
        let chain = ctx.audit_chain.lock().unwrap();
        assert_eq!(chain.len(), 1);
        assert_eq!(
            chain.verify(),
            crate::store::audit_chain::ChainVerdict::Intact
        );
    }

    #[tokio::test]
    async fn retrieve_does_not_append_an_audit_delta() {
        // `retrieve` reads — it is not a mutation; D9 chains only
        // persist/mutate/purge.
        let (mut ctx, _rx) = fresh_ctx();
        run_retrieve(&retrieve_node("s"), &mut ctx).await.unwrap();
        assert!(ctx.audit_chain.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn persist_mutate_purge_chain_into_one_verifiable_history() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("k".into(), "v".into());
        run_persist(
            &IRPersistStep {
                node_type: "persist",
            fields: Vec::new(),
                source_line: 0,
                source_column: 0,
                store_name: "s".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        run_mutate(
            &IRMutateStep {
                node_type: "mutate",
            fields: Vec::new(),
                source_line: 0,
                source_column: 0,
                store_name: "s".into(),
                where_expr: "k".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        run_purge(
            &IRPurgeStep {
                node_type: "purge",
                source_line: 0,
                source_column: 0,
                store_name: "s".into(),
                where_expr: "k".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        let chain = ctx.audit_chain.lock().unwrap();
        assert_eq!(chain.len(), 3, "three mutations → three chained deltas");
        assert_eq!(
            chain.verify(),
            crate::store::audit_chain::ChainVerdict::Intact
        );
    }

    #[test]
    fn sql_row_from_bindings_excludes_namespace_keys_and_sorts() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("name".into(), "Alice".into());
        ctx.let_bindings.insert("id".into(), "7".into());
        ctx.let_bindings
            .insert("__store_internal".into(), "bookkeeping".into());
        let row = sql_row_from_bindings(&ctx);
        assert_eq!(
            row,
            vec![
                ("id".to_string(), SqlValue::Text("7".to_string())),
                ("name".to_string(), SqlValue::Text("Alice".to_string())),
            ]
        );
    }
}
