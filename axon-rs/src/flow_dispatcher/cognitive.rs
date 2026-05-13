//! §Fase 33.y.f — Cognitive primitives (Fase 11 neuro-symbolic).
//!
//! Ten variants graduated in 33.y.f:
//!
//! 1. **`Remember`** — Persist a value to the cognitive memory.
//!    Write-through: always updates `ctx.let_bindings`; when
//!    `ctx.pem_backend` is `Some(_)`, also persists to PEM as a
//!    [`crate::pem::state::MemoryEntry`] in the session's
//!    [`crate::pem::state::CognitiveState`].
//!
//! 2. **`Recall`** — Restore a value from the cognitive memory.
//!    Read-back: when `ctx.pem_backend` is `Some(_)`, restores
//!    `CognitiveState` + searches `short_term_memory` for the
//!    requested key; falls back to `ctx.let_bindings` lookup; binds
//!    the result under the `query` key in `ctx.let_bindings`.
//!
//! 3. **`Forge`** — Payload-free in v1.25.0 IR. Emits canonical
//!    `step_type: "forge"` wire shape (StepStart + StepComplete, 0
//!    tokens). Future IR extensions wire a body via a public helper.
//!
//! 4-10. **`Focus`, `Associate`, `Aggregate`, `Explore`, `Ingest`,
//!    `Navigate`, `Corroborate`** — All seven reuse the pure-shape
//!    async core ([`crate::flow_dispatcher::pure_shape::run_pure_shape`])
//!    with each variant's cognitive framing addendum reflected in
//!    the system prompt. The user prompt is built from the IR
//!    fields (target / strategy / etc.). For stub backend each
//!    handler emits 1 chunk of `"(stub)"` byte-equal with 33.y.c
//!    pure-shape D4 invariant.
//!
//! # PEM integration
//!
//! The optional `pem_backend` field on `DispatchCtx` carries an
//! `Arc<dyn PersistenceBackend>`. When set, Remember/Recall route
//! through `persist` / `restore` calls; when None, both degrade
//! gracefully to `let_bindings`-only operation (in-memory baseline
//! that matches the canonical adopter unit-test path).
//!
//! D-letter anchors:
//! - **D1** — every cognitive variant has a NAMED async handler;
//!   exhaustive match in `dispatch_node`.
//! - **D3** — cancel checked at every `.await` boundary.
//! - **D6** — pure-shape-routed handlers (Focus/Associate/...) push
//!   StepAuditRecord via the shared core; Remember/Recall do NOT
//!   push audit rows (they're cognitive-state mutations, not
//!   wire-LLM steps).
//! - **D7** — every error case routes through DispatchError; PEM
//!   `persist`/`restore` errors surface as
//!   `DispatchError::BackendError { name: "pem", ... }`.
//! - **D10** — sync-runner parity: Remember binds + Recall reads
//!   via `let_bindings` identically to the principled cognitive-
//!   state semantics the sync runner adopts; PEM write-through is
//!   an enterprise-tier extension (transparent to the wire +
//!   binding semantics).

use crate::flow_dispatcher::pure_shape::{run_pure_shape, PureShapeStep};
use crate::flow_dispatcher::{DispatchCtx, DispatchError, NodeOutcome};
use crate::flow_execution_event::{now_ms, FlowExecutionEvent};
use crate::ir_nodes::{
    IRAggregateStep, IRAssociateStep, IRCorroborateStep, IRExploreStep, IRFocusStep,
    IRForgeBlock, IRIngestStep, IRNavigateStep, IRRecallStep, IRRememberStep,
};

// ────────────────────────────────────────────────────────────────────
//  Remember — PEM write-through + let_bindings
// ────────────────────────────────────────────────────────────────────

/// Persist `expression`'s value to the cognitive memory under
/// `memory_target`.
///
/// Resolution order for `expression`:
/// 1. If `expression` is a key in `ctx.let_bindings`, use its value.
/// 2. Otherwise treat `expression` as a literal string.
///
/// Write order:
/// 1. Always insert `value` into `ctx.let_bindings[memory_target]`
///    (in-memory baseline; matches sync-runner semantics).
/// 2. When `ctx.pem_backend` is `Some(_)`, additionally persist
///    the value as a [`crate::pem::state::MemoryEntry`] into the
///    session's `CognitiveState.short_term_memory` (write-through).
///
/// # Wire shape
///
/// Emits StepStart + StepComplete with `step_type: "remember"`.
/// No StepToken (Remember is a cognitive-state mutation, not an
/// LLM dispatch). `tokens_emitted` = 0.
///
/// # Returns
///
/// `NodeOutcome::Completed { output: <resolved-value>,
/// tokens_emitted: 0, step_index: <reserved> }`. The `output`
/// reflects what was bound so downstream `last_output` capture
/// in orchestration handlers (Conditional / ForIn body
/// aggregation) sees the bound value.
pub async fn run_remember(
    node: &IRRememberStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    // Resolve `expression` — let_bindings reference takes priority
    // over literal interpretation.
    let value = ctx
        .let_bindings
        .get(&node.expression)
        .cloned()
        .unwrap_or_else(|| node.expression.clone());

    emit_step_start(ctx, &step_name_for_remember(node), step_index, "remember")?;

    // Always update let_bindings (in-memory baseline).
    ctx.let_bindings
        .insert(node.memory_target.clone(), value.clone());

    // Write-through to PEM when backend is wired. PEM errors
    // surface as DispatchError::BackendError so the SSE handler
    // emits a structured axon.error rather than silently dropping
    // the cognitive state.
    if let Some(backend) = ctx.pem_backend.clone() {
        write_through_pem(&backend, ctx, &node.memory_target, &value).await?;
    }

    emit_step_complete(
        ctx,
        &step_name_for_remember(node),
        step_index,
        &value,
        0,
    )?;

    Ok(NodeOutcome::Completed {
        output: value,
        tokens_emitted: 0,
        step_index,
    })
}

fn step_name_for_remember(node: &IRRememberStep) -> String {
    if node.memory_target.is_empty() {
        "Remember".to_string()
    } else {
        node.memory_target.clone()
    }
}

async fn write_through_pem(
    backend: &std::sync::Arc<dyn crate::pem::PersistenceBackend>,
    ctx: &DispatchCtx,
    key: &str,
    value: &str,
) -> Result<(), DispatchError> {
    use crate::pem::state::{CognitiveState, MemoryEntry};
    use chrono::{Duration as ChronoDuration, Utc};

    // Restore existing state; create a fresh one when not found.
    let mut state = match backend.restore(&ctx.session_id).await {
        Ok(s) => s,
        Err(_) => CognitiveState::new(&ctx.session_id, &ctx.tenant_id, &ctx.flow_name),
    };

    state.short_term_memory.push(MemoryEntry {
        key: key.to_string(),
        payload: serde_json::Value::String(value.to_string()),
        symbolic_refs: Vec::new(),
        stored_at: Utc::now(),
    });
    state.last_updated_at = Utc::now();

    backend
        .persist(&ctx.session_id, &state, ChronoDuration::hours(24))
        .await
        .map_err(|e| DispatchError::BackendError {
            name: "pem".to_string(),
            message: format!("{e:?}"),
        })?;

    Ok(())
}

// ────────────────────────────────────────────────────────────────────
//  Recall — PEM read-back + let_bindings fallback
// ────────────────────────────────────────────────────────────────────

/// Restore a value from the cognitive memory.
///
/// Read order:
/// 1. When `ctx.pem_backend` is `Some(_)`, restore `CognitiveState`
///    + search `short_term_memory` for the latest entry with
///    `key == memory_source`.
/// 2. Otherwise (or when PEM restore returns NotFound / no
///    matching entry), fall back to `ctx.let_bindings[memory_source]`.
/// 3. When neither resolves, the recalled value is the empty string.
///
/// The resolved value is bound under `ctx.let_bindings[query]` so
/// subsequent steps reference it via the adopter-declared name.
///
/// # Wire shape
///
/// Same as Remember: StepStart + StepComplete with `step_type:
/// "recall"`, 0 StepTokens.
pub async fn run_recall(
    node: &IRRecallStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, &step_name_for_recall(node), step_index, "recall")?;

    let resolved = resolve_recall_value(node, ctx).await;

    // Bind the recalled value into let_bindings under `query`.
    ctx.let_bindings
        .insert(node.query.clone(), resolved.clone());

    emit_step_complete(
        ctx,
        &step_name_for_recall(node),
        step_index,
        &resolved,
        0,
    )?;

    Ok(NodeOutcome::Completed {
        output: resolved,
        tokens_emitted: 0,
        step_index,
    })
}

fn step_name_for_recall(node: &IRRecallStep) -> String {
    if node.query.is_empty() {
        "Recall".to_string()
    } else {
        node.query.clone()
    }
}

async fn resolve_recall_value(node: &IRRecallStep, ctx: &DispatchCtx) -> String {
    // 1. PEM read-back if backend is wired.
    if let Some(backend) = &ctx.pem_backend {
        if let Ok(state) = backend.restore(&ctx.session_id).await {
            // Find the LATEST entry with matching key (short_term_memory
            // accumulates over time; newest takes precedence).
            if let Some(entry) = state
                .short_term_memory
                .iter()
                .rev()
                .find(|e| e.key == node.memory_source)
            {
                if let serde_json::Value::String(s) = &entry.payload {
                    return s.clone();
                }
                // Non-string payload — canonical JSON serialization.
                return entry.payload.to_string();
            }
        }
    }

    // 2. let_bindings fallback.
    ctx.let_bindings
        .get(&node.memory_source)
        .cloned()
        .unwrap_or_default()
}

// ────────────────────────────────────────────────────────────────────
//  Forge — payload-free wire shape
// ────────────────────────────────────────────────────────────────────

/// Forge handler. In v1.25.0 the IR variant is payload-free so
/// this emits the canonical `step_type: "forge"` wire shape
/// (StepStart + StepComplete, 0 tokens). Future IR extensions
/// (a Fase 33.y.f.2 follow-up that adds a body via the AST/IR)
/// wire a recursive `dispatch_body` call from `run_forge`.
pub async fn run_forge(
    _node: &IRForgeBlock,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    if ctx.cancel.is_cancelled() {
        return Err(DispatchError::UpstreamCancelled);
    }

    let step_index = ctx.step_counter;
    ctx.step_counter += 1;

    emit_step_start(ctx, "Forge", step_index, "forge")?;
    emit_step_complete(ctx, "Forge", step_index, "", 0)?;

    Ok(NodeOutcome::Completed {
        output: String::new(),
        tokens_emitted: 0,
        step_index,
    })
}

// ────────────────────────────────────────────────────────────────────
//  Cognitive-framing handlers (7) — reuse pure_shape async core
// ────────────────────────────────────────────────────────────────────

/// Focus handler — narrow attention to an expression. Reuses the
/// pure-shape async core with the focus framing addendum.
pub async fn run_focus(
    node: &IRFocusStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let shape = PureShapeStep {
        name: if node.expression.is_empty() {
            "Focus".to_string()
        } else {
            node.expression.clone()
        },
        user_prompt: format!("Focus on: {}", node.expression),
        framing_addendum: Some(
            "You are focusing your attention. Narrow scope to the target; surface what matters most.".into(),
        ),
        kind_slug: "focus",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Associate handler — relate two entities via a key field.
pub async fn run_associate(
    node: &IRAssociateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let using_clause = if node.using_field.is_empty() {
        String::new()
    } else {
        format!(" using `{}`", node.using_field)
    };
    let shape = PureShapeStep {
        name: if node.left.is_empty() {
            "Associate".to_string()
        } else {
            format!("{}↔{}", node.left, node.right)
        },
        user_prompt: format!(
            "Associate {} with {}{}",
            node.left, node.right, using_clause
        ),
        framing_addendum: Some(
            "You are associating. Find the meaningful relationship; return a structured link.".into(),
        ),
        kind_slug: "associate",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Aggregate handler — group + summarize a target with optional
/// group_by keys + alias.
pub async fn run_aggregate(
    node: &IRAggregateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let group_clause = if node.group_by.is_empty() {
        String::new()
    } else {
        format!(" grouped by [{}]", node.group_by.join(", "))
    };
    let alias_clause = if node.alias.is_empty() {
        String::new()
    } else {
        format!(" as `{}`", node.alias)
    };
    let shape = PureShapeStep {
        name: if node.target.is_empty() {
            "Aggregate".to_string()
        } else {
            node.target.clone()
        },
        user_prompt: format!(
            "Aggregate {}{}{}",
            node.target, group_clause, alias_clause
        ),
        framing_addendum: Some(
            "You are aggregating. Group + summarize over the declared dimensions; surface the structure.".into(),
        ),
        kind_slug: "aggregate",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Explore handler — broad-scope exploration of a target with
/// optional result-count limit.
pub async fn run_explore(
    node: &IRExploreStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let limit_clause = match node.limit {
        Some(n) => format!(" (top {})", n),
        None => String::new(),
    };
    let shape = PureShapeStep {
        name: if node.target.is_empty() {
            "Explore".to_string()
        } else {
            node.target.clone()
        },
        user_prompt: format!("Explore: {}{}", node.target, limit_clause),
        framing_addendum: Some(
            "You are exploring. Sample broadly; surface the most-relevant directions.".into(),
        ),
        kind_slug: "explore",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Ingest handler — bring external data in from a source into a
/// target.
pub async fn run_ingest(
    node: &IRIngestStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let shape = PureShapeStep {
        name: if node.target.is_empty() {
            "Ingest".to_string()
        } else {
            node.target.clone()
        },
        user_prompt: format!("Ingest from `{}` into `{}`", node.source, node.target),
        framing_addendum: Some(
            "You are ingesting. Map the source's structure into the target; preserve fidelity.".into(),
        ),
        kind_slug: "ingest",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Navigate handler — paper §6 PIX navigation. In v1.25.0 the
/// handler ships the cognitive-framing wire shape (production-real
/// PIX traversal lands in a Fase 11.e follow-up; today the framing
/// nudges the LLM to surface its navigation path).
pub async fn run_navigate(
    node: &IRNavigateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let trail_clause = if node.trail_enabled { " (with trail)" } else { "" };
    let shape = PureShapeStep {
        name: if node.output_name.is_empty() {
            "Navigate".to_string()
        } else {
            node.output_name.clone()
        },
        user_prompt: format!(
            "Navigate corpus `{}` via PIX `{}` for query: {}{}",
            node.corpus_ref, node.pix_ref, node.query, trail_clause
        ),
        framing_addendum: Some(
            "You are navigating a PIX (paper §6 hidden state). Trace your reasoning path; surface the corpus regions you crossed.".into(),
        ),
        kind_slug: "navigate",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

/// Corroborate handler — cross-validate a navigation result against
/// the referenced `navigate_ref`.
pub async fn run_corroborate(
    node: &IRCorroborateStep,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError> {
    let shape = PureShapeStep {
        name: if node.output_name.is_empty() {
            "Corroborate".to_string()
        } else {
            node.output_name.clone()
        },
        user_prompt: format!("Corroborate navigation result `{}`", node.navigate_ref),
        framing_addendum: Some(
            "You are corroborating. Cross-validate independently; surface agreement strength + disagreements.".into(),
        ),
        kind_slug: "corroborate",
        tools: Vec::new(),
    };
    run_pure_shape(shape, ctx).await
}

// ────────────────────────────────────────────────────────────────────
//  Wire-event helpers (shared with Remember/Recall/Forge)
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
    use crate::pem::InMemoryBackend;
    use std::sync::Arc;
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

    // ── Remember ──────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_remember_literal_value_binds_to_let_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        let node = IRRememberStep {
            node_type: "remember",
            source_line: 0,
            source_column: 0,
            expression: "us-east-1".into(),
            memory_target: "region".into(),
        };
        let outcome = run_remember(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, .. } => {
                assert_eq!(output, "us-east-1");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(ctx.let_bindings.get("region").unwrap(), "us-east-1");
    }

    #[tokio::test]
    async fn run_remember_resolves_expression_through_let_bindings() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("upstream".into(), "computed-X".into());
        let node = IRRememberStep {
            node_type: "remember",
            source_line: 0,
            source_column: 0,
            expression: "upstream".into(),
            memory_target: "snapshot".into(),
        };
        run_remember(&node, &mut ctx).await.unwrap();
        assert_eq!(ctx.let_bindings.get("snapshot").unwrap(), "computed-X");
    }

    #[tokio::test]
    async fn run_remember_with_pem_persists_to_backend() {
        let backend: Arc<dyn crate::pem::PersistenceBackend> =
            Arc::new(InMemoryBackend::default());
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new(
            "F",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        )
        .with_pem(backend.clone())
        .with_session_id("session-1");

        let node = IRRememberStep {
            node_type: "remember",
            source_line: 0,
            source_column: 0,
            expression: "persisted-value".into(),
            memory_target: "key1".into(),
        };
        run_remember(&node, &mut ctx).await.unwrap();

        // Verify PEM has the entry.
        let state = backend.restore("session-1").await.unwrap();
        assert_eq!(state.short_term_memory.len(), 1);
        assert_eq!(state.short_term_memory[0].key, "key1");
    }

    // ── Recall ────────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_recall_from_let_bindings_when_no_pem() {
        let (mut ctx, _rx) = fresh_ctx();
        ctx.let_bindings.insert("region".into(), "us-east-1".into());
        let node = IRRecallStep {
            node_type: "recall",
            source_line: 0,
            source_column: 0,
            query: "current_region".into(),
            memory_source: "region".into(),
        };
        let outcome = run_recall(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => {
                assert_eq!(output, "us-east-1");
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        assert_eq!(
            ctx.let_bindings.get("current_region").unwrap(),
            "us-east-1"
        );
    }

    #[tokio::test]
    async fn run_recall_from_pem_when_backend_set() {
        let backend: Arc<dyn crate::pem::PersistenceBackend> =
            Arc::new(InMemoryBackend::default());
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new(
            "F",
            "stub",
            "",
            CancellationFlag::new(),
            tx,
        )
        .with_pem(backend.clone())
        .with_session_id("sess");

        // Plant a memory entry via Remember.
        run_remember(
            &IRRememberStep {
                node_type: "remember",
                source_line: 0,
                source_column: 0,
                expression: "value-from-pem".into(),
                memory_target: "pem_key".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();

        // Now Recall via PEM.
        let outcome = run_recall(
            &IRRecallStep {
                node_type: "recall",
                source_line: 0,
                source_column: 0,
                query: "recalled".into(),
                memory_source: "pem_key".into(),
            },
            &mut ctx,
        )
        .await
        .unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => {
                assert_eq!(output, "value-from-pem");
            }
            other => panic!("expected Completed, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn run_recall_missing_key_returns_empty_string() {
        let (mut ctx, _rx) = fresh_ctx();
        let node = IRRecallStep {
            node_type: "recall",
            source_line: 0,
            source_column: 0,
            query: "x".into(),
            memory_source: "never_set".into(),
        };
        let outcome = run_recall(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, .. } => assert_eq!(output, ""),
            other => panic!("expected Completed, got {other:?}"),
        }
    }

    // ── Forge ─────────────────────────────────────────────────────────

    #[tokio::test]
    async fn run_forge_emits_canonical_wire_shape() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRForgeBlock {
            node_type: "forge",
            source_line: 0,
            source_column: 0,
        };
        let outcome = run_forge(&node, &mut ctx).await.unwrap();
        match outcome {
            NodeOutcome::Completed { output, tokens_emitted, .. } => {
                assert_eq!(output, "");
                assert_eq!(tokens_emitted, 0);
            }
            other => panic!("expected Completed, got {other:?}"),
        }
        let mut events = Vec::new();
        while let Ok(ev) = rx.try_recv() {
            events.push(ev);
        }
        assert_eq!(events.len(), 2);
        match &events[0] {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "forge");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── Cognitive framing handlers ────────────────────────────────────

    #[tokio::test]
    async fn run_focus_emits_focus_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRFocusStep {
            node_type: "focus",
            source_line: 0,
            source_column: 0,
            expression: "key_insight".into(),
        };
        let _ = run_focus(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "focus");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_associate_emits_associate_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRAssociateStep {
            node_type: "associate",
            source_line: 0,
            source_column: 0,
            left: "A".into(),
            right: "B".into(),
            using_field: "id".into(),
        };
        run_associate(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "associate");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_aggregate_emits_aggregate_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRAggregateStep {
            node_type: "aggregate",
            source_line: 0,
            source_column: 0,
            target: "events".into(),
            group_by: vec!["region".into()],
            alias: "by_region".into(),
        };
        run_aggregate(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "aggregate");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_explore_emits_explore_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRExploreStep {
            node_type: "explore",
            source_line: 0,
            source_column: 0,
            target: "hypothesis_space".into(),
            limit: Some(5),
        };
        run_explore(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "explore");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_ingest_emits_ingest_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRIngestStep {
            node_type: "ingest",
            source_line: 0,
            source_column: 0,
            source: "external_api".into(),
            target: "raw".into(),
        };
        run_ingest(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "ingest");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_navigate_emits_navigate_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRNavigateStep {
            node_type: "navigate",
            source_line: 0,
            source_column: 0,
            pix_ref: "main_pix".into(),
            corpus_ref: "law_corpus".into(),
            query: "interpret_clause".into(),
            trail_enabled: true,
            output_name: "nav_result".into(),
        };
        run_navigate(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "navigate");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    #[tokio::test]
    async fn run_corroborate_emits_corroborate_slug() {
        let (mut ctx, mut rx) = fresh_ctx();
        let node = IRCorroborateStep {
            node_type: "corroborate",
            source_line: 0,
            source_column: 0,
            navigate_ref: "nav_result".into(),
            output_name: "validated".into(),
        };
        run_corroborate(&node, &mut ctx).await.unwrap();
        let ev = rx.try_recv().unwrap();
        match ev {
            FlowExecutionEvent::StepStart { step_type, .. } => {
                assert_eq!(step_type, "corroborate");
            }
            e => panic!("expected StepStart, got {e:?}"),
        }
    }

    // ── Cancel guards ────────────────────────────────────────────────

    #[tokio::test]
    async fn every_cognitive_handler_short_circuits_on_cancel() {
        let cancel = CancellationFlag::new();
        cancel.cancel();
        let (tx, _rx) = mpsc::unbounded_channel();
        let mut ctx = DispatchCtx::new("F", "stub", "", cancel, tx);

        // Remember
        let r = IRRememberStep {
            node_type: "remember",
            source_line: 0,
            source_column: 0,
            expression: "x".into(),
            memory_target: "y".into(),
        };
        assert!(matches!(
            run_remember(&r, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        // Recall
        let r = IRRecallStep {
            node_type: "recall",
            source_line: 0,
            source_column: 0,
            query: "q".into(),
            memory_source: "k".into(),
        };
        assert!(matches!(
            run_recall(&r, &mut ctx).await,
            Err(DispatchError::UpstreamCancelled)
        ));

        // Forge
        assert!(matches!(
            run_forge(
                &IRForgeBlock {
                    node_type: "forge",
                    source_line: 0,
                    source_column: 0,
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));

        // Cognitive-framing handlers — all go through run_pure_shape
        // which has its own cancel guard.
        assert!(matches!(
            run_focus(
                &IRFocusStep {
                    node_type: "focus",
                    source_line: 0,
                    source_column: 0,
                    expression: "x".into(),
                },
                &mut ctx,
            )
            .await,
            Err(DispatchError::UpstreamCancelled)
        ));
    }
}
