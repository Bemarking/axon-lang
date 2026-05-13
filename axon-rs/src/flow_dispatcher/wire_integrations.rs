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
    emit_step_start(ctx, &step_name, step_index, "persist")?;

    let count = persist_to_store(&node.store_name, ctx);
    let output = format!("persisted {count} entries to `{}`", node.store_name);

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
    emit_step_start(ctx, &step_name, step_index, "retrieve")?;

    let value = retrieve_from_store(&node.store_name, &node.where_expr, ctx);
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
    emit_step_start(ctx, &step_name, step_index, "mutate")?;

    let count = mutate_store(&node.store_name, &node.where_expr, ctx);
    let output = format!("mutated {count} entries in `{}`", node.store_name);

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
    emit_step_start(ctx, &step_name, step_index, "purge")?;

    let count = purge_from_store(&node.store_name, &node.where_expr, ctx);
    let output = format!("purged {count} entries from `{}`", node.store_name);

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

    #[tokio::test]
    async fn run_mutate_updates_existing() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("counter".into(), "1".into());
        let persist = IRPersistStep {
            node_type: "persist",
            source_line: 0,
            source_column: 0,
            store_name: "stats".into(),
        };
        run_persist(&persist, &mut ctx).await.unwrap();

        ctx.let_bindings.insert("counter".into(), "2".into());
        let mutate = IRMutateStep {
            node_type: "mutate",
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
}
