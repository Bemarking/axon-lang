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
    IRPersistStep, IRPublish, IRPurgeStep, IRQuant, IRRetrieveStep, IRTransactBlock, IRYield,
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

/// §Fase 66.1 (Q1.c) — detect an UNRESOLVED `${reference}` left in a
/// `persist`/`mutate` value AFTER interpolation. An identifier-shaped `${name}`
/// (or `${e.field}`) that survived interpolation means the reference did not
/// resolve — a missing binding, or a loop-var field-access that missed. Sending
/// it verbatim to the database is SILENT CORRUPTION (kivi brief #28: `${e.to_id}`
/// arrived at Postgres as the literal text → `invalid input syntax for type
/// uuid`). The runtime fails honestly instead (the §59 doctrine). Only
/// identifier-shaped references are flagged, so a literal like `${100}` or a `$`
/// in free text is never a false positive.
fn unresolved_reference(value: &str) -> Option<String> {
    let bytes = value.as_bytes();
    let mut i = 0;
    while i + 2 < bytes.len() {
        if bytes[i] == b'$' && bytes[i + 1] == b'{' {
            let start = i + 2;
            if bytes[start].is_ascii_alphabetic() || bytes[start] == b'_' {
                if let Some(close) = value[start..].find('}') {
                    let inner = &value[start..start + close];
                    if inner
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.')
                    {
                        return Some(inner.to_string());
                    }
                }
            }
        }
        i += 1;
    }
    None
}

/// §Fase 66.1 (Q1.c) — fail a `persist`/`mutate` whose row carries an unresolved
/// `${reference}` rather than writing the literal to the database.
fn reject_unresolved_row(
    store_name: &str,
    op: &str,
    row: &[(String, SqlValue)],
) -> Result<(), DispatchError> {
    for (col, val) in row {
        if let SqlValue::Text(s) = val {
            if let Some(reference) = unresolved_reference(s) {
                return Err(DispatchError::BackendError {
                    name: "axonstore".to_string(),
                    message: format!(
                        "{op} into `{store_name}`: column `{col}` carries an \
                         UNRESOLVED reference `${{{reference}}}` after \
                         interpolation — it did not resolve to a binding (check \
                         the loop variable / step output). Refusing to write the \
                         literal `${{{reference}}}` to the database."
                    ),
                });
            }
        }
    }
    Ok(())
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

    // §Fase 74 — `emit` routing, in precedence order:
    //   1. §74.c — a `persistent_axonstore` channel + an attached durable
    //      OUTBOX → APPEND (survives the consumer being down / a crash on
    //      the durable backend). Durability is resolved from the bus's
    //      channel handle (the registry).
    //   2. §74.a — an attached event BUS + a registered typed channel →
    //      EMIT (ephemeral in-process delivery). Fails CLOSED on error.
    //   3. the legacy per-flow buffer (no bus / untyped topic) — pre-§74.
    let bus_handle = ctx
        .event_bus
        .as_ref()
        .and_then(|b| b.get_handle(&node.channel_ref).ok());
    let is_durable = bus_handle
        .as_ref()
        .map_or(false, |h| h.persistence == "persistent_axonstore");

    let emitted = if let (true, Some(outbox)) = (is_durable, ctx.event_outbox.clone()) {
        // §74.c — durable: append to the outbox (the receive driver drains
        // + delivers + acks; redeliverable until acked).
        let payload = serde_json::from_str::<serde_json::Value>(&resolved_value)
            .unwrap_or_else(|_| serde_json::Value::String(resolved_value.clone()));
        outbox.append(&node.channel_ref, payload);
        resolved_value.clone()
    } else if let Some(bus) = ctx.event_bus.clone() {
        if bus.get_handle(&node.channel_ref).is_ok() {
            // §74.a — ephemeral in-process delivery via the bus.
            let payload = serde_json::from_str::<serde_json::Value>(&resolved_value)
                .unwrap_or_else(|_| serde_json::Value::String(resolved_value.clone()));
            bus.emit(
                &node.channel_ref,
                crate::runtime::channels::TypedPayload::Scalar(payload),
            )
            .await
            .map_err(|e| DispatchError::BackendError {
                name: node.channel_ref.clone(),
                message: format!("emit to channel '{}' failed: {e}", node.channel_ref),
            })?;
            resolved_value.clone()
        } else {
            emit_to_channel(&node.channel_ref, &resolved_value, ctx)
        }
    } else {
        emit_to_channel(&node.channel_ref, &resolved_value, ctx)
    };

    // §Fase 74.e — record the producer's Chan-Output (`emit:<channel>`) in
    // the §11.c replay/audit chain when a sink is attached. Best-effort —
    // the emit already happened; a receipt-append failure is logged, not
    // fatal (hardened in §74.f's durable audit-chain sink).
    if let Some(log) = ctx.replay_log.clone() {
        let payload = serde_json::from_str::<serde_json::Value>(&emitted)
            .unwrap_or_else(|_| serde_json::Value::String(emitted.clone()));
        let token = crate::daemon::mint_channel_event_token(
            &format!("emit:{}", node.channel_ref),
            &ctx.flow_name,
            &payload,
            serde_json::Value::Null,
        );
        if let Err(e) = log.append(token).await {
            eprintln!("§74.e emit token append failed for '{}': {e}", node.channel_ref);
        }
    }

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

    // §Fase 77.b — a publish under a SIGNING shield (the IR pre-resolved
    // `sign`, §77.a) additionally records the EGRESS intent: the single
    // in-context fact the enterprise egress driver reads to know this
    // channel's durable events are signed-deliverable externally. Empty
    // `sign` ⇒ pure π-calc capability extrusion, byte-identical to pre-§77.
    if !node.sign.is_empty() {
        ctx.let_bindings
            .insert(format!("__egress_{}", node.channel_ref), node.sign.clone());
    }

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
            // §Fase 66.1 (Q1.c) — refuse to write an UNRESOLVED `${reference}`
            // (a missed loop-var field-access / step output) to the database;
            // fail honestly instead of silently corrupting the column.
            reject_unresolved_row(&node.store_name, "persist", &row)?;
            // §35.g Pillar I — a sub-floor or un-elevated write into a
            // confidence-floored store is a typed error.
            epistemic::enforce_persist_floor(&row, floor, &node.store_name)
                .map_err(|e| sql_dispatch_error(StoreError::from(e)))?;
            // §Fase 37.x.j (D2, D6.a) — Take the pin OUT of the shared
            // map (if any). On a MISS (empty map ≡ this is a par-branch
            // sub-context post-clone, or a non-eager-acquired path),
            // lazily acquire a fresh pin for the branch — D6.a default
            // per-branch sub-pin. Return the pin on the tail so the
            // next op against the same store in this same ctx reuses
            // it. The shared `Arc<Mutex<HashMap>>` lock is held only
            // across the take + insert (microseconds); the SQL dispatch
            // itself runs without the mutex.
            let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> = {
                ctx.pinned_conns.lock().unwrap().remove(&node.store_name)
            };
            if pin.is_none() {
                // D6.a lazy acquire — see retrieve site for full rationale.
                if let Ok(p) = backend.acquire_pin().await {
                    pin = Some(p);
                }
            }
            let n = {
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                backend
                    .insert(&mut store_conn, &node.store_name, &row)
                    .await
                    .map_err(sql_dispatch_error)?
            };
            if let Some(p) = pin {
                ctx.pinned_conns
                    .lock()
                    .unwrap()
                    .insert(node.store_name.clone(), p);
            }
            // §Fase 67.c — observable per-run row count.
            ctx.record_store_rows(crate::flow_dispatcher::StoreRowKind::Persisted, n as u64);
            format!("persisted {n} row(s) to `{}`", node.store_name)
        }
        Ok(None) => {
            let count = persist_to_store(&node.store_name, ctx);
            ctx.record_store_rows(
                crate::flow_dispatcher::StoreRowKind::Persisted,
                count as u64,
            );
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
            // §Fase 37.x.j (D2, D6.a) — Take the pin OUT of the shared
            // map. On a MISS (empty map = this is a par-branch sub-
            // context with a fresh Arc post-clone in `parallel.rs`, or
            // simply a non-eager-acquired path), lazily acquire a
            // fresh pin so this branch's ops still share a single
            // physical Postgres backend connection — closing the
            // unnamed-statement race per-branch (D6.a). When acquire
            // also fails (pool exhausted, etc.) the dispatch falls
            // through to `StoreConn::Pool` (legacy degraded path,
            // still functional; only the race protection is lost).
            let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> = {
                ctx.pinned_conns.lock().unwrap().remove(&node.store_name)
            };
            if pin.is_none() {
                if let Ok(p) = backend.acquire_pin().await {
                    // §Fase 37.x.j (D4 + D6.c) — emit lazy acquire
                    // event. `branch_index` is derived from the depth
                    // of `ctx.branch_path` (non-empty ≡ inside a par-
                    // block); the field is `None` for a linear parent
                    // path's lazy acquire (rare — usually parent path
                    // has eager pins from the dispatcher startup walk).
                    crate::store::pin_observability::emit_pin_acquire(
                        &node.store_name,
                        &ctx.flow_name,
                        "",
                        "lazy",
                        if ctx.branch_path.is_empty() {
                            None
                        } else {
                            Some(ctx.branch_path.len())
                        },
                    );
                    pin = Some(p);
                }
            }
            let stream_outcome_result = {
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                row_stream::stream_retrieve(
                    &backend,
                    &mut store_conn,
                    &node.store_name,
                    &node.where_expr,
                    // §Fase 67.b — the adopter `order_by:` / `limit:` clauses
                    // (this IS the `retrieve` step handler on the production
                    // dispatcher path — the daemon runs through here).
                    &node.order_by,
                    &node.limit_expr,
                    // §Fase 76.d — the adopter `aggregate:` / `group_by:`
                    // clauses (closed catalog; structural SQL).
                    &node.aggregate,
                    &node.group_by,
                    row_stream::DEFAULT_RETRIEVE_POLICY,
                    row_stream::DEFAULT_MAX_ROWS,
                    &ctx.cancel,
                    // §Fase 37.d (D3) — resolve `${name}` in the `where`
                    // clause to `$N` bind parameters via the filter
                    // compiler (never string-spliced into the SQL).
                    &ctx.let_bindings,
                )
                .await
            };
            if let Some(p) = pin {
                ctx.pinned_conns
                    .lock()
                    .unwrap()
                    .insert(node.store_name.clone(), p);
            }
            let stream_outcome = stream_outcome_result
            .map_err(sql_dispatch_error)?;
            // §Fase 67.c — observable per-run row count: the rows the
            // `where:` (+ §67.b LIMIT) actually matched, captured BEFORE
            // the epistemic floor consumes the vec. This is the number
            // brief #34 Q3 wanted — "did the sweep find work?".
            ctx.record_store_rows(
                crate::flow_dispatcher::StoreRowKind::Retrieved,
                stream_outcome.rows.len() as u64,
            );
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
//  §Fase 64.B — read a store's rows tenant-scoped (for the dynamic,
//  store-sourced MDN corpus graph: `corpus N from axonstore { … }`).
// ────────────────────────────────────────────────────────────────────

/// §Fase 64.B — read ALL rows of a store, **tenant-scoped**, reusing the flow's
/// connection-pinned Postgres backend (the §37.x.j pinned-conn path + the §40
/// RLS GUC `axon.current_tenant`). An empty `where` returns every row visible to
/// the CURRENT tenant — RLS scopes the result, so this is the §64.B
/// tenant-isolation guarantee, INHERITED by reusing the flow's pinned connection
/// rather than acquiring a fresh one (the cross-tenant leak the risk matrix
/// flagged). Returns `Ok(None)` when the store is not Postgres-backed: the
/// dynamic MDN corpus needs a real tabular backend (the KV path holds single
/// values, not typed rows).
pub async fn read_all_store_rows(
    ctx: &mut DispatchCtx,
    store_name: &str,
    // §Fase 66 (Q2) — optional column-scope filter (the navigate `where:`),
    // pushed to the SELECT that sources the corpus rows. Empty string = no
    // column filter (the §64 default: all rows visible to the axon-tenant via
    // RLS). A non-empty expr is compiled by the §37.d filter compiler (in
    // `stream_retrieve`), which resolves `${name}` → `$N` bind params against
    // `ctx.let_bindings` — injection-safe — so an adopter multiplexing
    // sub-tenants in one axon-tenant via a column scopes the MDN graph to a
    // single sub-tenant (`where: "tenant_id == '${tenant_id}'"`).
    where_expr: &str,
) -> Result<Option<Vec<crate::store::postgres_backend::StoreRow>>, DispatchError> {
    match resolve_pg_backend(ctx, store_name) {
        Ok(Some((backend, _floor))) => {
            // §37.x.j (D2/D6.a) — take the pin out of the shared map; lazily
            // acquire on a miss so this read shares the flow's single physical
            // tenant-scoped connection, then restore it.
            let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> =
                { ctx.pinned_conns.lock().unwrap().remove(store_name) };
            if pin.is_none() {
                if let Ok(p) = backend.acquire_pin().await {
                    pin = Some(p);
                }
            }
            let outcome = {
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                row_stream::stream_retrieve(
                    &backend,
                    &mut store_conn,
                    store_name,
                    // §Fase 66 (Q2) — the navigate `where:` column-scope filter
                    // (empty → all rows visible to the axon-tenant, RLS-scoped,
                    // the §64 default). `${name}` resolves to `$N` bind params
                    // against `let_bindings` (§37.d) — injection-safe.
                    where_expr,
                    // §Fase 67.b — navigate corpus scan has no adopter ORDER BY/LIMIT.
                    "",
                    "",
                    // §Fase 76.d — nor an aggregate.
                    "",
                    "",
                    row_stream::DEFAULT_RETRIEVE_POLICY,
                    row_stream::DEFAULT_MAX_ROWS,
                    &ctx.cancel,
                    &ctx.let_bindings,
                )
                .await
            };
            if let Some(p) = pin {
                ctx.pinned_conns
                    .lock()
                    .unwrap()
                    .insert(store_name.to_string(), p);
            }
            let outcome = outcome.map_err(sql_dispatch_error)?;
            Ok(Some(outcome.rows))
        }
        Ok(None) => Ok(None),
        Err(e) => Err(sql_dispatch_error(e)),
    }
}

/// §Fase 64.B — project the mapped columns out of the raw store rows into the
/// [`crate::mdn::Corpus::from_rows`] tuples: `(id, title)` from the documents
/// store, `(from, to, etype, weight)` from the edge store. Pure: takes already-
/// fetched rows (so it is unit-testable without a database). A row missing a
/// mapped column is dropped (resilient to live, evolving schemas).
pub fn extract_corpus_rows(
    doc_rows: &[crate::store::postgres_backend::StoreRow],
    edge_rows: &[crate::store::postgres_backend::StoreRow],
    src: &crate::ir_nodes::IRCorpusStoreSource,
) -> (Vec<(String, String)>, Vec<(String, String, String, f64)>) {
    let col = |row: &crate::store::postgres_backend::StoreRow, name: &str| {
        row.columns
            .iter()
            .find(|(c, _)| c == name)
            .map(|(_, v)| v.clone())
    };
    // JSON → plain string (a Postgres uuid/text both arrive as JSON String;
    // numbers/bools fall back to their compact JSON form, un-quoted).
    let as_str = |v: &serde_json::Value| -> String {
        match v {
            serde_json::Value::String(s) => s.clone(),
            other => other.to_string(),
        }
    };
    let docs = doc_rows
        .iter()
        .filter_map(|r| {
            let id = col(r, &src.doc_id)?;
            let title = col(r, &src.doc_title)?;
            Some((as_str(&id), as_str(&title)))
        })
        .collect();
    let edges = edge_rows
        .iter()
        .filter_map(|r| {
            let from = as_str(&col(r, &src.edge_from)?);
            let to = as_str(&col(r, &src.edge_to)?);
            let etype = as_str(&col(r, &src.edge_type)?);
            let weight = col(r, &src.edge_weight)?.as_f64().unwrap_or(0.0);
            Some((from, to, etype, weight))
        })
        .collect();
    (docs, edges)
}

/// §Fase 64.C — plan the per-edge weight reinforcements to PERSIST after a
/// navigation over an adaptive store-sourced corpus. The incremental semantic
/// signal of the just-recorded outcome (score `s_o`) on each traversed edge is
/// `Δ = η · (s_o − s̄)` (paper Def 6 for the latest outcome; `s̄` = mean over the
/// history INCLUDING `s_o`; the decay is 1 in the default config). Returns
/// `(from_id, to_id, etype_slug, Δ)` for every traversed edge with a NON-ZERO Δ.
/// A single outcome has `s_o = s̄ ⇒ Δ = 0 ⇒` nothing to persist: the relative
/// semantic signal needs variance across interactions (the paper's design).
/// Pure — `docs[i]` is the document at internal `DocId` `i` (`from_rows` interns
/// ids by first-seen order, so `DocId i ↔ docs[i]`).
pub fn plan_edge_reinforcements(
    corpus: &crate::mdn::Corpus,
    selected: &[crate::mdn::DocId],
    docs: &[(String, String)],
    score: f64,
    mean_score: f64,
    eta: f64,
) -> Vec<(String, String, String, f64)> {
    let delta = eta * (score - mean_score);
    if delta == 0.0 {
        return Vec::new();
    }
    let mut out = Vec::new();
    for pair in selected.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        for e in corpus.edges() {
            if e.from == a && e.to == b {
                if let (Some(fa), Some(tb)) = (docs.get(a as usize), docs.get(b as usize)) {
                    out.push((fa.0.clone(), tb.0.clone(), e.etype.slug().to_string(), delta));
                }
            }
        }
    }
    out
}

/// §Fase 64.C — PERSIST a reinforcement plan to the edge store via the atomic,
/// relative `UPDATE` ([`PostgresStoreBackend::reinforce`]), **tenant-scoped** by
/// reusing the flow's connection-pinned, RLS-scoped store connection (never a
/// fresh one). Best-effort: a single edge's failure (or a since-deleted edge)
/// must not abort the rest or fail the navigation — learning is advisory. A
/// non-Postgres backing is a no-op.
pub async fn persist_reinforcements(
    ctx: &mut DispatchCtx,
    edge_store: &str,
    weight_col: &str,
    from_col: &str,
    to_col: &str,
    etype_col: &str,
    plan: &[(String, String, String, f64)],
    epsilon: f64,
) -> Result<(), DispatchError> {
    if plan.is_empty() {
        return Ok(());
    }
    let Ok(Some((backend, _floor))) = resolve_pg_backend(ctx, edge_store) else {
        return Ok(());
    };
    let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> =
        { ctx.pinned_conns.lock().unwrap().remove(edge_store) };
    if pin.is_none() {
        if let Ok(p) = backend.acquire_pin().await {
            pin = Some(p);
        }
    }
    {
        let mut store_conn = match &mut pin {
            Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
            None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
        };
        for (from_id, to_id, etype, delta) in plan {
            let _ = backend
                .reinforce(
                    &mut store_conn,
                    edge_store,
                    weight_col,
                    from_col,
                    to_col,
                    etype_col,
                    &crate::store::filter::SqlValue::Text(from_id.clone()),
                    &crate::store::filter::SqlValue::Text(to_id.clone()),
                    &crate::store::filter::SqlValue::Text(etype.clone()),
                    *delta,
                    epsilon,
                )
                .await;
        }
    }
    if let Some(p) = pin {
        ctx.pinned_conns
            .lock()
            .unwrap()
            .insert(edge_store.to_string(), p);
    }
    Ok(())
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
            // §Fase 66.1 (Q1.c) — same honest-failure guard as persist.
            reject_unresolved_row(&node.store_name, "mutate", &row)?;
            // §Fase 37.x.j (D2, D6.a) — take-pin / lazy-acquire-on-miss
            // / dispatch / return-pin; see `run_persist` and
            // `run_retrieve` sites for the full rationale.
            let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> = {
                ctx.pinned_conns.lock().unwrap().remove(&node.store_name)
            };
            if pin.is_none() {
                if let Ok(p) = backend.acquire_pin().await {
                    // §Fase 37.x.j (D4 + D6.c) — emit lazy acquire
                    // event. `branch_index` is derived from the depth
                    // of `ctx.branch_path` (non-empty ≡ inside a par-
                    // block); the field is `None` for a linear parent
                    // path's lazy acquire (rare — usually parent path
                    // has eager pins from the dispatcher startup walk).
                    crate::store::pin_observability::emit_pin_acquire(
                        &node.store_name,
                        &ctx.flow_name,
                        "",
                        "lazy",
                        if ctx.branch_path.is_empty() {
                            None
                        } else {
                            Some(ctx.branch_path.len())
                        },
                    );
                    pin = Some(p);
                }
            }
            let n = {
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                backend
                    .mutate(&mut store_conn, &node.store_name, &node.where_expr, &row, &ctx.let_bindings)
                    .await
                    .map_err(sql_dispatch_error)?
            };
            if let Some(p) = pin {
                ctx.pinned_conns
                    .lock()
                    .unwrap()
                    .insert(node.store_name.clone(), p);
            }
            // §Fase 67.c — observable per-run row count.
            ctx.record_store_rows(crate::flow_dispatcher::StoreRowKind::Mutated, n as u64);
            format!("mutated {n} row(s) in `{}`", node.store_name)
        }
        Ok(None) => {
            let count = mutate_store(&node.store_name, &node.where_expr, ctx);
            ctx.record_store_rows(
                crate::flow_dispatcher::StoreRowKind::Mutated,
                count as u64,
            );
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
            // §Fase 37.x.j (D2, D6.a) — take-pin / lazy-acquire-on-miss
            // / dispatch / return-pin; see other sites for full rationale.
            let mut pin: Option<sqlx::pool::PoolConnection<sqlx::Postgres>> = {
                ctx.pinned_conns.lock().unwrap().remove(&node.store_name)
            };
            if pin.is_none() {
                if let Ok(p) = backend.acquire_pin().await {
                    // §Fase 37.x.j (D4 + D6.c) — emit lazy acquire
                    // event. `branch_index` is derived from the depth
                    // of `ctx.branch_path` (non-empty ≡ inside a par-
                    // block); the field is `None` for a linear parent
                    // path's lazy acquire (rare — usually parent path
                    // has eager pins from the dispatcher startup walk).
                    crate::store::pin_observability::emit_pin_acquire(
                        &node.store_name,
                        &ctx.flow_name,
                        "",
                        "lazy",
                        if ctx.branch_path.is_empty() {
                            None
                        } else {
                            Some(ctx.branch_path.len())
                        },
                    );
                    pin = Some(p);
                }
            }
            let n = {
                let mut store_conn = match &mut pin {
                    Some(p) => crate::store::store_conn::StoreConn::Pinned(p),
                    None => crate::store::store_conn::StoreConn::Pool(backend.pool()),
                };
                backend
                    .purge(&mut store_conn, &node.store_name, &node.where_expr, &ctx.let_bindings)
                    .await
                    .map_err(sql_dispatch_error)?
            };
            if let Some(p) = pin {
                ctx.pinned_conns
                    .lock()
                    .unwrap()
                    .insert(node.store_name.clone(), p);
            }
            // §Fase 67.c — observable per-run row count.
            ctx.record_store_rows(crate::flow_dispatcher::StoreRowKind::Purged, n as u64);
            format!("purged {n} row(s) from `{}`", node.store_name)
        }
        Ok(None) => {
            let count = purge_from_store(&node.store_name, &node.where_expr, ctx);
            ctx.record_store_rows(
                crate::flow_dispatcher::StoreRowKind::Purged,
                count as u64,
            );
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
//  Quant (§Fase 51.a — Hilbert-space projection block, surface only)
// ────────────────────────────────────────────────────────────────────

/// §Fase 51.a — the `quant` cognitive block. Wire shape: `step_type: "quant"`.
///
/// SURFACE ONLY: the OSS dispatcher recognizes the block and emits its
/// canonical start/complete wire shape but does **not** execute the
/// Hilbert-space body. Real evaluation is wired by:
///   - §51.d — the `ots:backend:quant_sim` / `qpu_native` effect injection +
///     the `yield` measurement point (one-shot continuation), and
///   - §51.e — the `QuantBackend` port + the capped (n ≤ 10) CPU reference
///     simulator,
/// with hardware acceleration (QuIDD / VRAM / QPU) only in the enterprise
/// backend (§51.f–i). Mirrors the payload-free completion of `run_transact`.
pub async fn run_quant(
    node: &IRQuant,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Quant", step_index, "quant")?;
    // Record the selected backend tag so a downstream observer can see which
    // effect the block declared (`quant_sim` default / `qpu_native`). No
    // Hilbert execution happens here in §51.a.
    ctx.let_bindings
        .insert("__quant_backend".to_string(), node.effect.clone());
    emit_step_complete(ctx, "Quant", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

/// §Fase 88.a — the `warden(<target>) within <Scope> { … }` adversarial
/// security-analysis block. Wire shape: `step_type: "warden"`.
///
/// SURFACE ONLY: the OSS dispatcher recognizes the block and emits the canonical
/// start/complete wire shape (recording the target + scope reference so an
/// observer sees the authorization binding) but does NOT run the analysis. The
/// real work — resolving the signed `scope`, ingesting authorized evidence,
/// abductive adversarial analysis, and emitting attested `Vulnerability`
/// findings — is the `WardenBackend` port + reference engine (§88.d) and the
/// enterprise engine (§88.f), all behind the §88.c authorization gate.
pub async fn run_warden(
    node: &crate::ir_nodes::IRWarden,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Warden", step_index, "warden")?;
    // Record the authorization binding (target + scope) for downstream observers.
    // No analysis happens here in §88.a.
    ctx.let_bindings
        .insert("__warden_scope".to_string(), node.scope_ref.clone());
    emit_step_complete(ctx, "Warden", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Yield (§Fase 51.d.2 — quant measurement point, surface only)
// ────────────────────────────────────────────────────────────────────

/// §Fase 51.d.2 — the `yield <expr>` measurement point. Wire shape:
/// `step_type: "yield"`.
///
/// SURFACE ONLY: the OSS dispatcher emits the canonical start/complete wire
/// shape but does NOT collapse amplitudes — the measurement + its one-shot
/// delimited continuation (suspend the classical thread, resolve via the
/// `quant_sim`/`qpu_native` handler, resume at the suspension point) is the
/// §51.e reference simulator / enterprise QuIDD-QPU backend. Mirrors the
/// payload-free completion of `run_quant`.
pub async fn run_yield(
    node: &IRYield,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }
    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Yield", step_index, "yield")?;
    emit_step_complete(ctx, "Yield", step_index, "", 0)?;

    // Record the measured expression so a downstream observer sees what the
    // quant block yields; no Hilbert collapse happens here in §51.d.2.
    ctx.let_bindings
        .insert("__quant_yield".to_string(), node.value_expr.clone());

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
                branch_path: ctx.branch_path_string(),
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
                branch_path: ctx.branch_path_string(),
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

    // ── §Fase 66.1 (Q1.c) — unresolved-reference guard ──────────────────

    #[test]
    fn unresolved_reference_flags_a_surviving_dollar_brace_identifier() {
        // The kivi #28 corruption: `${e.to_id}` survived interpolation.
        assert_eq!(unresolved_reference("${e.to_id}").as_deref(), Some("e.to_id"));
        assert_eq!(unresolved_reference("${missing}").as_deref(), Some("missing"));
        // Resolved values + genuine literals are NOT flagged (no false positives).
        assert_eq!(unresolved_reference("11111111-1111-1111-1111-111111111111"), None);
        assert_eq!(unresolved_reference("plain text"), None);
        assert_eq!(unresolved_reference("cost ${100}"), None); // numeric → not a ref
        assert_eq!(unresolved_reference(""), None);
    }

    #[test]
    fn reject_unresolved_row_errors_instead_of_writing_the_literal() {
        let ok = vec![("id".to_string(), SqlValue::Text("abc".to_string()))];
        assert!(reject_unresolved_row("s", "persist", &ok).is_ok());
        let bad = vec![("to_id".to_string(), SqlValue::Text("${e.to_id}".to_string()))];
        let err = reject_unresolved_row("ltm_edges", "persist", &bad).unwrap_err();
        match err {
            DispatchError::BackendError { message, .. } => {
                assert!(message.contains("UNRESOLVED"), "names the failure: {message}");
                assert!(message.contains("e.to_id"), "quotes the reference: {message}");
                assert!(message.contains("ltm_edges"), "names the store: {message}");
            }
            other => panic!("expected BackendError, got {other:?}"),
        }
    }

    // ── §Fase 64.B — extract_corpus_rows (store rows → from_rows tuples) ────

    fn mk_store_row(pairs: &[(&str, serde_json::Value)]) -> crate::store::postgres_backend::StoreRow {
        crate::store::postgres_backend::StoreRow {
            columns: pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect(),
        }
    }

    #[test]
    fn extract_corpus_rows_projects_the_mapped_columns() {
        use serde_json::json;
        let src = IRCorpusStoreSource {
            doc_store: "LtmSummaries".into(),
            doc_id: "id".into(),
            doc_title: "summary".into(),
            edge_store: "LtmEdges".into(),
            edge_from: "from_id".into(),
            edge_to: "to_id".into(),
            edge_type: "etype".into(),
            edge_weight: "weight".into(),
        };
        let doc_rows = vec![
            mk_store_row(&[("id", json!("uuid-a")), ("summary", json!("A")), ("noise", json!(1))]),
            mk_store_row(&[("id", json!("uuid-b")), ("summary", json!("B"))]),
        ];
        let edge_rows = vec![mk_store_row(&[
            ("from_id", json!("uuid-b")),
            ("to_id", json!("uuid-a")),
            ("etype", json!("cite")),
            ("weight", json!(0.9)),
        ])];
        let (docs, edges) = extract_corpus_rows(&doc_rows, &edge_rows, &src);
        assert_eq!(docs, vec![("uuid-a".into(), "A".into()), ("uuid-b".into(), "B".into())]);
        assert_eq!(edges, vec![("uuid-b".into(), "uuid-a".into(), "cite".into(), 0.9)]);
    }

    #[test]
    fn plan_edge_reinforcements_zero_for_one_outcome_nonzero_with_variance() {
        // §Fase 64.C — Δ = η·(s_o − s̄). A 2-doc graph a→b (cite); from_rows
        // interns a=0, b=1 ⇒ the edge is (0,1); the path [0,1] traverses it.
        let docs = vec![("id-a".to_string(), "A".to_string()), ("id-b".to_string(), "B".to_string())];
        let edges = vec![("id-a".to_string(), "id-b".to_string(), "cite".to_string(), 0.5)];
        let corpus = crate::mdn::Corpus::from_rows(&docs, &edges).unwrap();
        let selected = vec![0u32, 1u32];

        // Single outcome: s_o == s̄ ⇒ Δ = 0 ⇒ nothing to persist.
        let p0 = plan_edge_reinforcements(&corpus, &selected, &docs, 0.8, 0.8, 0.1);
        assert!(p0.is_empty(), "a single outcome reinforces nothing (relative signal)");

        // With variance: Δ = 0.1·(0.9 − 0.5) = 0.04 on the traversed edge.
        let p1 = plan_edge_reinforcements(&corpus, &selected, &docs, 0.9, 0.5, 0.1);
        assert_eq!(p1.len(), 1);
        assert_eq!(p1[0].0, "id-a");
        assert_eq!(p1[0].1, "id-b");
        assert_eq!(p1[0].2, "cite");
        assert!((p1[0].3 - 0.04).abs() < 1e-9, "Δ = η(s−s̄): got {}", p1[0].3);
    }

    #[test]
    fn extract_corpus_rows_drops_rows_missing_a_mapped_column() {
        use serde_json::json;
        let src = IRCorpusStoreSource {
            doc_store: "S".into(),
            doc_id: "id".into(),
            doc_title: "summary".into(),
            edge_store: "E".into(),
            edge_from: "f".into(),
            edge_to: "t".into(),
            edge_type: "ty".into(),
            edge_weight: "w".into(),
        };
        // second doc row lacks `summary` → dropped (resilient to schema drift).
        let doc_rows = vec![
            mk_store_row(&[("id", json!("a")), ("summary", json!("A"))]),
            mk_store_row(&[("id", json!("b"))]),
        ];
        let (docs, _edges) = extract_corpus_rows(&doc_rows, &[], &src);
        assert_eq!(docs.len(), 1, "a row missing a mapped column is dropped");
        assert_eq!(docs[0].0, "a");
    }

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
    async fn run_emit_routes_to_the_event_bus_when_attached() {
        // §Fase 74.a — with a shared typed bus attached + the channel
        // registered, `emit` DELIVERS to the bus (the producer side of
        // durable event delivery), NOT the legacy per-flow buffer.
        use crate::runtime::channels::{TypedChannelHandle, TypedEventBus, TypedPayload};
        let bus = std::sync::Arc::new(TypedEventBus::new());
        bus.register(TypedChannelHandle::new("HibCh", "Hib"));

        let (mut ctx, _rx) = fresh_ctx();
        ctx = ctx.with_event_bus(bus.clone());
        ctx.let_bindings
            .insert("payload".into(), r#"{"tenant_id":"acme"}"#.into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "HibCh".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        run_emit(&node, &mut ctx).await.unwrap();

        // It went to the bus (receivable), NOT the legacy buffer.
        assert!(
            !ctx.let_bindings.contains_key("__channel_HibCh"),
            "a bus-routed emit must not also append to the legacy buffer"
        );
        let event = bus.receive("HibCh").await.expect("the event is on the bus");
        match event.payload {
            TypedPayload::Scalar(v) => assert_eq!(v["tenant_id"], "acme"),
            other => panic!("expected the scalar payload, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_emit_appends_to_the_outbox_for_a_persistent_channel() {
        // §Fase 74.c — a `persistent_axonstore` channel + an attached outbox
        // → `emit` APPENDS to the durable outbox (not the ephemeral bus), so
        // the event survives the consumer being down.
        use crate::event_outbox::{EventOutbox, InMemoryEventOutbox};
        use crate::runtime::channels::{TypedChannelHandle, TypedEventBus};
        let bus = std::sync::Arc::new(TypedEventBus::new());
        let mut h = TypedChannelHandle::new("HibCh", "Hib");
        h.persistence = "persistent_axonstore".into();
        bus.register(h);
        let outbox = std::sync::Arc::new(InMemoryEventOutbox::new());

        let (mut ctx, _rx) = fresh_ctx();
        ctx = ctx.with_event_bus(bus).with_event_outbox(outbox.clone());
        ctx.let_bindings
            .insert("payload".into(), r#"{"tenant_id":"acme"}"#.into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "HibCh".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        run_emit(&node, &mut ctx).await.unwrap();

        // It landed in the durable outbox (not the legacy buffer).
        assert_eq!(outbox.pending_total(), 1, "the event is durably queued");
        assert!(!ctx.let_bindings.contains_key("__channel_HibCh"));
        let tail = outbox.unprocessed("HibCh");
        assert_eq!(tail[0].payload["tenant_id"], "acme");
    }

    #[tokio::test]
    async fn run_emit_records_a_replay_token_when_a_log_is_attached() {
        // §Fase 74.e — the producer's Chan-Output `emit` records an
        // `emit:<channel>` ReplayToken in the attached replay chain.
        use crate::replay_token::{InMemoryReplayLog, ReplayLog};
        use crate::runtime::channels::{TypedChannelHandle, TypedEventBus};
        let bus = std::sync::Arc::new(TypedEventBus::new());
        bus.register(TypedChannelHandle::new("HibCh", "Hib"));
        let log = std::sync::Arc::new(InMemoryReplayLog::new());

        let (mut ctx, _rx) = fresh_ctx();
        ctx = ctx.with_event_bus(bus).with_replay_log(log.clone());
        ctx.let_bindings
            .insert("payload".into(), r#"{"tenant_id":"acme"}"#.into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "HibCh".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        run_emit(&node, &mut ctx).await.unwrap();

        assert_eq!(log.len(), 1, "the emit recorded one replay token");
        let tokens = log.tokens_for_flow(&ctx.flow_name).await.unwrap();
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].effect_name, "emit:HibCh");
        assert_eq!(tokens[0].inputs["payload"]["tenant_id"], "acme");
    }

    #[tokio::test]
    async fn run_emit_ephemeral_channel_uses_the_bus_not_the_outbox() {
        // §Fase 74.c — an `ephemeral` channel goes to the bus even when an
        // outbox is attached (the outbox is only for `persistent_axonstore`).
        use crate::event_outbox::{EventOutbox, InMemoryEventOutbox};
        use crate::runtime::channels::{TypedChannelHandle, TypedEventBus};
        let bus = std::sync::Arc::new(TypedEventBus::new());
        bus.register(TypedChannelHandle::new("Tick", "T")); // default persistence = ephemeral
        let outbox = std::sync::Arc::new(InMemoryEventOutbox::new());
        let (mut ctx, _rx) = fresh_ctx();
        ctx = ctx.with_event_bus(bus.clone()).with_event_outbox(outbox.clone());
        ctx.let_bindings.insert("payload".into(), "t".into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "Tick".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        run_emit(&node, &mut ctx).await.unwrap();
        assert_eq!(outbox.pending_total(), 0, "ephemeral does not touch the outbox");
        assert!(bus.receive("Tick").await.is_ok(), "ephemeral went to the bus");
    }

    #[tokio::test]
    async fn run_emit_falls_back_to_buffer_for_an_unregistered_channel() {
        // §Fase 74.a — a bus is attached but the channel is NOT a registered
        // typed `channel` (e.g. a legacy topic string) → the legacy buffer
        // path applies, byte-identical to pre-§74.
        use crate::runtime::channels::TypedEventBus;
        let bus = std::sync::Arc::new(TypedEventBus::new());
        let (mut ctx, _rx) = fresh_ctx();
        ctx = ctx.with_event_bus(bus);
        ctx.let_bindings.insert("payload".into(), "hello".into());
        let node = IREmit {
            node_type: "emit",
            source_line: 0,
            source_column: 0,
            channel_ref: "unregistered".into(),
            value_ref: "payload".into(),
            value_is_channel: false,
        };
        run_emit(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("__channel_unregistered").unwrap(), "hello");
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
            sign: String::new(),
        };
        run_publish(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("__pub_secure_chan").unwrap(),
            "hipaa"
        );
        // §77.b — a NON-signing publish records no egress intent
        // (pre-§77 semantics byte-identical).
        assert!(!ctx.let_bindings.contains_key("__egress_secure_chan"));
        let first = rx.try_recv().unwrap();
        match first {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "publish");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    /// §Fase 77.b — a publish whose IR carries a resolved `sign` (a signing
    /// shield) records the egress intent the enterprise driver reads.
    #[tokio::test]
    async fn run_publish_records_egress_intent_for_signing_shield() {
        let (mut ctx, _rx) = fresh_ctx();
        let node = IRPublish {
            node_type: "publish",
            source_line: 0,
            source_column: 0,
            channel_ref: "SkillCompleted".into(),
            shield_ref: "WebhookEgress".into(),
            sign: "hmac_sha256".into(),
        };
        run_publish(&node, &mut ctx).await.unwrap();
        assert_eq!(
            ctx.let_bindings.get("__pub_SkillCompleted").unwrap(),
            "WebhookEgress"
        );
        assert_eq!(
            ctx.let_bindings.get("__egress_SkillCompleted").unwrap(),
            "hmac_sha256"
        );
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
            order_by: String::new(),
            limit_expr: String::new(),
            aggregate: String::new(),
            group_by: String::new(),
            cache: String::new(),
        };
        run_retrieve(&retrieve, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("retrieved_id").unwrap(), "42");
    }

    /// §Fase 67.c — each store op folds its row count into the shared
    /// per-run counter on the ctx; the counts ACCUMULATE (not overwrite)
    /// and are read by `collect_via_dispatcher` after the walk. Exercised
    /// here on the in-memory path (the postgres path needs a live DB; the
    /// wiring — handler → `ctx.record_store_rows` → counter — is identical).
    #[tokio::test]
    async fn store_ops_fold_observable_row_counts_into_the_ctx() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("id".into(), "1".into());
        let persist = IRPersistStep {
            node_type: "persist",
            fields: Vec::new(),
            source_line: 0,
            source_column: 0,
            store_name: "entities".into(),
        };
        // Zero before any op.
        assert_eq!(
            *ctx.store_row_counts.lock().unwrap(),
            crate::flow_dispatcher::StoreRowCounts::default()
        );
        run_persist(&persist, &mut ctx).await.unwrap();
        let after_one = ctx.store_row_counts.lock().unwrap().persisted;
        assert!(after_one >= 1, "a persist must count >=1 row, got {after_one}");
        // A second persist ACCUMULATES (proves `+=`, not overwrite).
        run_persist(&persist, &mut ctx).await.unwrap();
        let after_two = ctx.store_row_counts.lock().unwrap().persisted;
        assert_eq!(after_two, after_one * 2, "counts accumulate across ops");
        // The other buckets stay zero (no retrieve/mutate/purge ran).
        let c = *ctx.store_row_counts.lock().unwrap();
        assert_eq!((c.retrieved, c.mutated, c.purged), (0, 0, 0));
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
            sign: String::new(),
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
            order_by: String::new(),
            limit_expr: String::new(),
            aggregate: String::new(),
            group_by: String::new(),
            cache: String::new(),
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
            order_by: String::new(),
            limit_expr: String::new(),
            aggregate: String::new(),
            group_by: String::new(),
            cache: String::new(),
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
            order_by: String::new(),
            limit_expr: String::new(),
            aggregate: String::new(),
            group_by: String::new(),
            cache: String::new(),
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
