# AXON Migration Guide — v1.25.0 → v1.26.0

> **Scope:** the Fase 33.y *Per-IRFlowNode async dispatcher* cycle
> introduced in v1.26.0. Adopters upgrading from v1.25.0 (Fase 33.x
> runtime activation of algebraic streaming) read this doc to
> decide which migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.26.0 is **strictly additive** (D4 wire byte-compat
> ratified end-to-end across the 33.y cycle). If you don't change
> anything, nothing changes — your v1.25.0 SSE wire bodies are
> preserved byte-identically for stub-backed flows + the canonical
> `Stream<T>` shape. What v1.26.0 activates: a structurally closed
> per-IRFlowNode async dispatcher covering **all 45 IRFlowNode
> variants** with compiler-enforced exhaustive matching (33.y.b–j);
> a new `FlowExecutionEvent::ToolCall` closed-catalog variant that
> plumbs upstream `FinishReason::ToolUse` through the wire surface
> (33.y.k D8 milestone); legacy shim infrastructure
> (`legacy_shim`/`ShimReason`/`NodeOutcome::LegacyShimHandled`/
> `DispatchError::LegacyShimFailed`) retired in lockstep (33.y.l
> D7 milestone); the new public crate surface
> `flow_dispatcher::dispatch_node` available to downstream crates
> for principled IRFlowNode async execution; `#[deprecated]`
> signals on `PlanError::LegacyOrchestrationRequired` +
> `flow_plan::unsupported_feature_reason` +
> `axon_server::run_streaming_legacy_path` pointing toward the 33.z
> production-wiring graduation.

---

## What changed in v1.26.0

| Surface | v1.25.0 | v1.26.0 |
|---|---|---|
| SSE wire body for stub backend + canonical `Stream<T>` | 1 axon.token "(stub)" + 1 axon.complete | **Byte-identical** (D4 wire byte-compat preserved end-to-end) |
| SSE wire body for canonical `step S { ask: "..." }` on real backends | Per upstream provider chunk via `Backend::stream()` (33.x.b) | **Byte-identical** (33.x.b production path unchanged) |
| `flow_dispatcher` module (Rust crate-public) | Did not exist | **New** — `pub async fn dispatch_node(node, ctx)` with compiler-enforced exhaustive match over all 45 IRFlowNode variants; 10-file module set (algebraic_handlers / cognitive / effects_bridge / lambda_tools / orchestration / parallel / pix / pure_shape / wire_integrations / mod) |
| `FlowExecutionEvent` closed catalog | 6 variants (FlowStart / FlowError / FlowComplete / StepStart / StepToken / StepComplete) | **+1 = 7 variants** — new `ToolCall { step_name, tool_name, content, timestamp_ms }` variant; serde-tagged `kind: "tool_call"`; cross-stack parity (Rust + Python) |
| `ChatRequest.tools` plumbing on `pure_shape`-routed handlers | `Vec::new()` baseline | **Synthesized from `step.apply_ref`** when non-empty (33.y.k); empty `apply_ref` → empty Vec → D4 byte-compat preserved |
| Production SSE consumer match arm for `ToolCall` | (variant did not exist) | Silent consume (`=> {}`); 33.z graduates this to a wire `axon.tool_call` SSE event family |
| `legacy_shim` + `ShimReason` 45-enum + `NodeOutcome::LegacyShimHandled` + `DispatchError::LegacyShimFailed` | Existed as 33.y.b–j transitional plumbing | **Retired** in 33.y.l (no longer compileable; `dispatch_node` has a NAMED async handler for every variant) |
| `PlanError::LegacyOrchestrationRequired` + `flow_plan::unsupported_feature_reason` + `axon_server::run_streaming_legacy_path` | Internal routing primitives | `#[deprecated(since = "1.26.0")]` with retirement note → `flow_dispatcher::dispatch_node`; 33.z grafts the dispatcher into the streaming surface end-to-end then deletes these |
| D7 invariant enforcement | (no dedicated gate) | **New** — `tests/fase33y_l_parity_gate.rs` (7 tests) greps `src/flow_dispatcher/*.rs` for `unimplemented!` / `todo!` / `panic!` (outside `#[cfg(test)]`) / `legacy_shim` / `ShimReason` / `LegacyShimHandled` / `LegacyShimFailed` references at every `cargo test` invocation |
| Dedicated CI workflow for 33.y cycle | (none) | **New** — `.github/workflows/fase_33y_dispatcher.yml` (33.y.n; ships with v1.26.0 release) |
| D12 robustness fuzz across the dispatcher surface | (33.x cycle covered streaming wire) | **New** — handler-totality + cancel propagation + orchestration composition + algebraic-semantics parity + tool-call interleaving (33.y.n; ~3000+ deterministic LCG iters) |

Every NEW surface (the public dispatcher, the `ToolCall` event
variant, the parity gate, the dedicated CI workflow) is **opt-in**.
Adopters that don't reach into `flow_dispatcher::*` from their own
code and don't consume `ToolCall` events from their SSE clients
see **no observable wire change**.

---

## The architectural arc — why this release matters

Pre-v1.26.0, the streaming path took **canonical** `step S { ask: "..." [apply: tool] }` shapes through `Backend::stream()` end-to-end (33.x.b–e production async); **non-canonical** shapes (orchestration `for x in [...]`, `Par { ... }`, `let x = ...`, `Conditional { if ... }`, PIX `Hibernate`/`Drill`/`Trail`, algebraic `ShieldApply`/`OtsApply`/`MandateApply`, etc.) fell back to a **synchronous LEGACY path** that materialized the full flow output then projected synthetic 3-word `axon.token` events as a post-hoc burst.

The Fase 33.y cycle **structurally closes** that gap. Every one of the **45 IRFlowNode variants** now has a NAMED async handler in `flow_dispatcher::dispatch_node` with compiler-enforced exhaustive matching. The dispatcher is **structurally complete** in v1.26.0; **production-side wiring** into `server_execute_streaming` graduates in **v1.27.x (Fase 33.z)** — at which point every adopter shape becomes per-chunk-streaming-eligible on the wire without any source change.

v1.26.0 ships the structural foundation. The downstream-crate API, the closed-catalog `ToolCall` event variant, the retired shim infrastructure, and the deprecation signals on the legacy routing primitives are the contract that 33.z will activate end-to-end. Adopters that want to start writing against the new dispatcher today (downstream crate authors, enterprise integrations) have a stable public surface to build on.

---

## Scenario A — You upgraded the server; nothing else changed

**Symptom:** None. Your existing client code keeps working.

**What you observe:**

| Adopter shape | v1.26.0 behavior |
|---|---|
| Adopter source uses canonical `step S { ask: "hi" output: Stream<Token> }` + stub backend (no real LLM key) | Wire body is byte-identical with v1.25.0 (1 axon.token "(stub)" + 1 axon.complete) |
| Adopter source uses canonical shape + a real LLM key (Anthropic / OpenAI / Gemini) | Wire body is byte-identical with v1.25.0 (per-upstream-chunk delivery via `Backend::stream()`; 33.x.b production path unchanged) |
| Adopter source declares `effects: <stream:<policy>>` on its tool | Wire body is byte-identical with v1.25.0 (`enforcement_summary` counters published, `stream_policies` carry-over from Fase 33.e) |
| Adopter source declares `apply: <tool>` on a canonical Step + real backend signals `FinishReason::ToolUse` | Wire body is byte-identical with v1.25.0 on the production SSE path; the new `FlowExecutionEvent::ToolCall` variant is silently consumed by the production consumer in v1.26.0 (33.z surfaces it as an `axon.tool_call` SSE event family) |
| Adopter source uses orchestration / PIX / algebraic / wire-integration / multi-agent / lambda shapes | Wire body is byte-identical with v1.25.0 (LEGACY path activates exactly as before + emits `axon-W002 streaming-not-supported` on `axon.complete.warnings[*]`); 33.z grafts the new dispatcher into the streaming surface so these shapes become per-chunk-streaming-eligible |
| Adopter source uses `axonendpoint ... transport: sse replay: true` | Wire body + replay entries are byte-identical with v1.25.0; `step_audit` array continues to populate per-step records as established in 33.x.f |

**Recipe:**

```bash
# 1. Bump the dep pin to 1.26.0 in your project's Cargo.toml /
#    pyproject.toml.
# 2. Build + restart.
cargo build --release            # or pip install -U axon-lang
systemctl restart axon-server    # or your equivalent
```

That's it. No source change, no client code change, no auth surface
change. Verified by the cycle's regression sweep: 1735 axon-rs lib
tests + 272 Fase 33.y integration tests + 68 test binaries with
**3349 passed / 0 failed** in the full sweep.

---

## Scenario B — You want to consume the new `ToolCall` event variant from a downstream crate or test harness

**Symptom:** You ship a downstream crate that drives `flow_dispatcher::dispatch_node` directly (enterprise integration, test harness, custom orchestration engine) and want to surface upstream `FinishReason::ToolUse` to your own clients.

**What v1.26.0 ships:** the new `FlowExecutionEvent::ToolCall` closed-catalog variant. Serde-tagged with `kind: "tool_call"`; cross-stack parity (Rust + Python). Emitted by `pure_shape::run_pure_shape` (both drain paths — direct + through-enforcer) whenever an upstream `ChatChunk.finish_reason` is `Some(FinishReason::ToolUse)`. The event surfaces BEFORE the text `StepToken` so adopters observing the event stream see the tool call request in arrival order.

The variant shape:

```rust
pub enum FlowExecutionEvent {
    // ... 6 existing variants ...

    /// §Fase 33.y.k — Tool-call request surfaced by an upstream
    /// provider's `FinishReason::ToolUse`. Closed catalog;
    /// serde-tagged `kind: "tool_call"`; is_step_scoped() returns
    /// true; is_terminator() returns false.
    #[serde(rename = "tool_call")]
    ToolCall {
        step_name: String,
        tool_name: String,
        content: String,         // tool-call delta (provider-specific shape)
        timestamp_ms: u64,
    },
}
```

**Recipe (Rust downstream crate):**

```rust
use axon::flow_dispatcher::{dispatch_node, DispatchCtx, NodeOutcome};
use axon::flow_execution_event::FlowExecutionEvent;
use axon::cancel_token::CancellationFlag;
use tokio::sync::mpsc;

// 1. Construct a dispatcher context. The mpsc tx is your event sink.
let (tx, mut rx) = mpsc::unbounded_channel();
let mut ctx = DispatchCtx::new(
    "MyFlow",
    "anthropic",                 // backend name; resolved via Registry
    "You are a helpful assistant.",
    CancellationFlag::new(),
    tx,
);

// 2. Dispatch the node. dispatch_node is async; the synthesized tool
//    spec from step.apply_ref is plumbed through ChatRequest.tools.
let step = build_my_ir_step("apply_search");  // step.apply_ref = "apply_search"
let outcome = dispatch_node(&axon::ir_nodes::IRFlowNode::Step(step), &mut ctx).await?;

// 3. Drain the event stream + observe ToolCall events in arrival order.
while let Some(event) = rx.recv().await {
    match event {
        FlowExecutionEvent::ToolCall { step_name, tool_name, content, timestamp_ms } => {
            tracing::info!(
                step = step_name,
                tool = tool_name,
                arrival_ms = timestamp_ms,
                "upstream signaled tool call: {content}"
            );
            // Surface to your downstream consumer in your preferred
            // shape (gRPC streaming response, WebSocket frame, etc.).
        }
        FlowExecutionEvent::StepToken { token, .. } => {
            // Text content arrives after the ToolCall preserves
            // arrival order.
            print!("{token}");
        }
        other => { /* dispatch other variants as needed */ }
    }
}
```

**Recipe (Python downstream consumer — cross-stack parity):**

```python
from axon.runtime.flow_execution_event import FlowExecutionEvent

# Consume the event stream (e.g., from axon-rs's exposed Python
# binding or via the SSE wire surface 33.z lights up).
async for event_json in event_stream():
    event = FlowExecutionEvent.from_json(event_json)
    if event.kind == "tool_call":
        # event is a ToolCall variant — same field shape as Rust.
        print(f"[tool_call] step={event.step_name} tool={event.tool_name}")
        print(f"            content={event.content}")
        print(f"            arrival_ms={event.timestamp_ms}")
```

**Caveat — wire emission lands in 33.z.** The production SSE consumer in `axon_server.rs` silently consumes `ToolCall` events in v1.26.0 (the match arm is `FlowExecutionEvent::ToolCall { .. } => {}` per the 33.y.l consumer-side scope). When 33.z grafts the per-IRFlowNode dispatcher into `server_execute_streaming`, the consumer will graduate to emit an `axon.tool_call` SSE event family. Until then, only adopters who drive `dispatch_node` directly observe the event variant on their own event sinks. Stub backends (`FinishReason::Stop`) never emit `ToolCall` — wire shape stays canonical 3-event (StepStart + StepToken + StepComplete) for adopters running on stub.

**Verification:**

```bash
# Run the 33.y.k closed-catalog tests:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33y_k_tools_first_class
# Expected: 14 passed; 0 failed (D4 byte-compat + closed-catalog +
# serde round-trip + composition tests).
```

---

## Scenario C — You author a downstream crate that needs principled IRFlowNode async execution

**Symptom:** You ship an enterprise integration, custom orchestration engine, test harness, or alternative wire format (gRPC streaming, WebSocket, Kafka topic) and want to drive `axon` IR flows through your own event sink WITHOUT going through the axon-server SSE handler.

**What v1.26.0 ships:** a stable `pub` crate surface on `axon::flow_dispatcher`:

| Symbol | Stability contract |
|---|---|
| `pub async fn dispatch_node(node: &IRFlowNode, ctx: &mut DispatchCtx) -> Result<NodeOutcome, DispatchError>` | **Stable** — exhaustive match over all 45 IRFlowNode variants; cancel-checked at entry of every handler (D3); zero `unimplemented!()`/`todo!()` markers (D7 enforced by `tests/fase33y_l_parity_gate.rs`) |
| `pub struct DispatchCtx` | **Stable surface, growing fields** — current fields: `flow_name` / `backend_name` / `system_prompt` / `cancel: CancellationFlag` / `tx: mpsc::UnboundedSender<FlowExecutionEvent>` / Arc-backed `enforcement_summaries` / `step_audit_records` / `runtime_warnings` / `branch_path: Vec<String>` / `step_counter: usize` / `let_bindings: HashMap<String, String>` / `pem_backend: Option<Arc<dyn PersistenceBackend>>` / `session_id` / `tenant_id` / `pending_effect_policy: Option<BackpressurePolicy>`. Future sub-fases may add fields; existing fields are stable. Builder methods: `with_pem` / `with_session_id` / `with_tenant_id`. |
| `pub enum NodeOutcome` | **`#[non_exhaustive]`** — current closed catalog: `Completed { output, tokens_emitted, step_index }` / `Break` / `LoopContinue` / `Return { value }`. Downstream crates MUST match with a catch-all arm (the attribute requires it from outside the crate); in-crate code uses exhaustive match. |
| `pub enum DispatchError` | **`#[non_exhaustive]`** — current closed catalog: `BackendError { name, message }` / `UpstreamCancelled` / `MissingDependency { name }` / `ChannelClosed`. (33.y.l retired `LegacyShimFailed`.) |
| `pub fn flow_plan::ir_flow_node_kind(node: &IRFlowNode) -> &'static str` | **Stable** — single source of truth for the wire-stable kind slug. 45 distinct slugs (step / probe / reason / validate / refine / weave / use_tool / remember / recall / conditional / for_in / let / return / break / continue / lambda_data_apply / par / hibernate / deliberate / consensus / forge / focus / associate / aggregate / explore / ingest / shield_apply / stream_block / navigate / drill / trail / corroborate / ots_apply / mandate_apply / compute_apply / listen / daemon_step / emit / publish / discover / persist / retrieve / mutate / purge / transact). |
| `pub use flow_dispatcher::{pure_shape, orchestration, parallel, effects_bridge, cognitive, algebraic_handlers, wire_integrations, pix, lambda_tools}` | **Module-level public** — direct access to per-architectural-group handler entries + helper functions (e.g., `algebraic_handlers::apply_shield` / `wire_integrations::publish_capability` / `pix::await_event_with_timeout`). Enterprise integrations override these helpers via future trait-object fields on DispatchCtx (deferred to 33.y.g.2 / enterprise R&D track). |

**Recipe (custom event-sink integration):**

```rust
use axon::flow_dispatcher::{dispatch_node, DispatchCtx, NodeOutcome, DispatchError};
use axon::flow_execution_event::FlowExecutionEvent;
use axon::cancel_token::CancellationFlag;
use axon::ir_nodes::IRFlowNode;
use std::sync::Arc;
use tokio::sync::mpsc;

/// Drive an axon IRFlowNode through your own event sink (gRPC,
/// WebSocket, Kafka, NATS, etc.).
async fn dispatch_to_my_sink(
    node: &IRFlowNode,
    backend_name: &str,
    my_sink: impl Fn(FlowExecutionEvent) + Send + 'static,
) -> Result<NodeOutcome, DispatchError> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let cancel = CancellationFlag::new();

    let mut ctx = DispatchCtx::new(
        "DownstreamFlow",
        backend_name,
        "system prompt",
        cancel.clone(),
        tx,
    );

    // Spawn a forwarder that drains the dispatcher's event channel
    // into your sink.
    let forwarder = tokio::spawn(async move {
        while let Some(event) = rx.recv().await {
            my_sink(event);
        }
    });

    // Dispatch. The dispatcher's exhaustive match is compiler-enforced
    // across all 45 IRFlowNode variants — adding a 46th in a future
    // axon-lang minor will fail your compile (the same discipline the
    // language repo uses internally).
    let outcome = dispatch_node(node, &mut ctx).await?;

    // Drop ctx.tx so the forwarder exits cleanly.
    drop(ctx);
    forwarder.await.ok();

    Ok(outcome)
}
```

**Recipe (cancel-budget compliance):**

The cancel discipline is identical to 33.x.e — `p95 cancel→None ≤ 100ms wall-clock` against real upstream providers. The dispatcher honors `ctx.cancel.is_cancelled()` at the entry of every handler (D3 invariant enforced by the `dispatch_node_honors_cancel_flag_at_entry` drift gate test that walks all 45 variants). Downstream crates that want to abort mid-stream call `ctx.cancel.cancel()` from any thread — the dispatcher returns `Err(DispatchError::UpstreamCancelled)` as soon as the in-flight handler reaches the next cancel checkpoint.

**Verification:**

```bash
# Run the 33.y dispatcher drift gate + diagnostic anchor:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33y_b_dispatcher_skeleton
# Expected: 9 passed; 0 failed (cartesian product cardinality +
# every-variant-routes + cancel-honored-at-entry + flow_plan slug
# coverage + DispatchCtx surface + DispatchError surface + no-panic).

cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33y_l_parity_gate
# Expected: 7 passed; 0 failed (D7 grep invariant + pinned module set).
```

---

## Scenario D — You depend on the deprecated streaming-vs-legacy routing primitives

**Symptom:** Your downstream crate or test harness pattern-matches on `flow_plan::PlanError::LegacyOrchestrationRequired`, calls `flow_plan::unsupported_feature_reason` directly, or invokes `axon_server::run_streaming_legacy_path`. After upgrading to v1.26.0, you observe deprecation warnings at compile time.

**What v1.26.0 ships:** `#[deprecated(since = "1.26.0")]` annotations on all three surfaces with retirement notes pointing to `flow_dispatcher::dispatch_node`. The annotations carry the following messages:

```
PlanError::LegacyOrchestrationRequired:
"Use the per-IRFlowNode async dispatcher
 (`flow_dispatcher::dispatch_node`) — 33.y graduates all 45
 IRFlowNode variants. This legacy fallback variant is on a
 retirement path; 33.z will remove it."

flow_plan::unsupported_feature_reason:
"Use the per-IRFlowNode async dispatcher
 (`flow_dispatcher::dispatch_node`). This function gates the
 legacy streaming-vs-sync fallback path which 33.z will retire."

axon_server::run_streaming_legacy_path:
"Use the per-IRFlowNode async dispatcher
 (`flow_dispatcher::dispatch_node`) — 33.y graduates all 45
 IRFlowNode variants. This legacy synthetic-token fallback
 path is on a retirement schedule for 33.z."
```

The functions and variant **still operate** in v1.26.0 — the deprecation is a forward signal for 33.z (axon-lang v1.27.x) when the per-IRFlowNode dispatcher gets grafted into `server_execute_streaming` end-to-end + the legacy fallback is deleted.

**Recipe (short-term: suppress the warnings):**

If your downstream code legitimately exercises the legacy fallback (e.g., a test harness verifying the W002 warning surface), add a module-level allow at the top of the file:

```rust
// Module-level allow — your downstream test legitimately drives
// the still-functional legacy fallback gate. Remove this allow
// when 33.z lands + the deprecated symbols are deleted.
#![allow(deprecated)]
```

This is the same pattern used by the axon-lang test files `fase33x_fuzz.rs` + `fase33x_g_warning_catalog.rs` (33.y.l added the allows in lockstep with the deprecation).

**Recipe (long-term: migrate to the dispatcher):**

For downstream code that wants to graduate to the per-IRFlowNode dispatcher BEFORE 33.z lands the production-side wiring:

| If your code did this in v1.25.0 | Migrate to this in v1.26.0 |
|---|---|
| Match on `Err(PlanError::LegacyOrchestrationRequired { reason, .. })` to gate fallback behavior | Drive the IR through `flow_dispatcher::dispatch_node` directly; the dispatcher succeeds for every IRFlowNode variant (no fallback needed) |
| Call `unsupported_feature_reason(flow, ir)` to introspect why a flow can't stream | The dispatcher streams every variant; introspect outcomes via the `FlowExecutionEvent` channel + `NodeOutcome` return |
| Call `run_streaming_legacy_path(...)` to materialize a flow as a synthetic-burst stream | Replace with `dispatch_node` over each IR node + collect events from the mpsc channel |

The migration recipes in Scenario C above are the canonical patterns. The axon-rs `tests/fase33y_*` test pack contains 272 worked examples across the 14 sub-fases (`b_dispatcher_skeleton`, `c_pure_shape_handlers`, `c_pure_shape_fuzz`, `d_orchestration_handlers`, `d_orchestration_fuzz`, `e_par_stream_handlers`, `e_par_stream_fuzz`, `f_cognitive_primitives`, `f_cognitive_fuzz`, `g_algebraic_handlers`, `g_algebraic_fuzz`, `h_wire_integrations`, `h_wire_fuzz`, `i_pix_handlers`, `j_lambda_tools`, `k_tools_first_class`, `l_parity_gate`).

---

## Scenario E — You run the D7 parity gate in your own CI

**Symptom:** You maintain a fork of axon-lang or ship a downstream crate that wraps `flow_dispatcher::*` and want to enforce the same D7 invariant the upstream cycle enforces.

**What v1.26.0 ships:** `tests/fase33y_l_parity_gate.rs` — a 7-test grep gate (~400 LOC) that scans `axon-rs/src/flow_dispatcher/*.rs` at every `cargo test` invocation for:

1. **No `unimplemented!()` / `todo!()` markers** — the language's D7 mandate forbids placeholder macros on the hot dispatch path. The grep covers every `.rs` file under the module, skips comment lines, and reports `<file>:<line> — <marker>` for any hit.
2. **No `panic!()` outside `#[cfg(test)]` regions** — a brace-depth heuristic identifies test-module regions (start: line containing `#[cfg(test)]` or `mod tests`; end: balanced closing brace); `panic!(` lines outside those regions are flagged.
3. **No `legacy_shim` references** — the retired shim function (33.y.l) cannot be re-introduced via merge.
4. **No `ShimReason` references** — the retired 45-variant catalog cannot be re-introduced.
5. **No `LegacyShimHandled` references** — the retired `NodeOutcome` variant cannot be re-introduced.
6. **No `LegacyShimFailed` references** — the retired `DispatchError` variant cannot be re-introduced.
7. **Pinned 10-file dispatcher module set** — `algebraic_handlers.rs` + `cognitive.rs` + `effects_bridge.rs` + `lambda_tools.rs` + `mod.rs` + `orchestration.rs` + `parallel.rs` + `pix.rs` + `pure_shape.rs` + `wire_integrations.rs`. A dropped module file (rebase accident, repo reorg) surfaces at PR time.

**Recipe (use the same gate for your downstream module):**

If your downstream crate ships a `flow_dispatcher_extensions` module (or any equivalent that subclasses the dispatcher's discipline), copy the parity-gate test as a starting template + adjust the `dispatcher_dir` path:

```rust
// In your downstream crate's tests/my_parity_gate.rs
use std::fs;
use std::path::PathBuf;

fn read_all_my_dispatcher_lines() -> Vec<(String, usize, String)> {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let dispatcher_dir = PathBuf::from(manifest_dir)
        .join("src")
        .join("my_dispatcher_extensions");
    // ... copy the discipline from
    // axon-rs/tests/fase33y_l_parity_gate.rs verbatim.
}

#[test]
fn no_unimplemented_or_todo_markers_in_my_dispatcher() {
    let lines = read_all_my_dispatcher_lines();
    let mut hits: Vec<String> = Vec::new();
    for (file, line_no, text) in &lines {
        let trimmed = text.trim_start();
        if trimmed.starts_with("//") { continue; }
        if text.contains("unimplemented!(") || text.contains("todo!(") {
            hits.push(format!("{file}:{line_no} — placeholder marker"));
        }
    }
    assert!(hits.is_empty(), "D7 violation in my dispatcher: {hits:?}");
}
```

The 7 invariants compose: a violation surfaces at `cargo test` time (no extra tooling needed); CI catches it on PR before merge.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33y_l_parity_gate
# Expected:
# running 7 tests
# test dispatcher_module_files_pinned_to_expected_set ... ok
# test no_shim_reason_symbol_references_in_dispatcher ... ok
# test no_legacy_shim_failed_error_references_in_dispatcher ... ok
# test no_legacy_shim_handled_outcome_references_in_dispatcher ... ok
# test no_legacy_shim_symbol_references_in_dispatcher ... ok
# test no_unimplemented_or_todo_markers_in_dispatcher ... ok
# test no_panic_outside_test_modules_in_dispatcher ... ok
# test result: ok. 7 passed; 0 failed
```

---

## Honest scope statement (carried verbatim from the plan vivo)

**What v1.26.0 ships in the 33.y cycle:**

- 33.y.a — plan vivo + diagnostic anchor + D1–D12 ratification
- 33.y.b — dispatcher skeleton + closed-catalog match + drift gate
- 33.y.c — 6 pure-shape variants graduated (Step / Probe / Reason / Validate / Refine / Weave)
- 33.y.d — 6 orchestration variants graduated (Let / Conditional / ForIn / Break / Continue / Return)
- 33.y.e — Par + Stream graduated + D9 algebraic-effect ↔ wire bridge
- 33.y.f — 10 cognitive primitives graduated + PEM async surface
- 33.y.g — 6 algebraic-effect handlers graduated (Shield / Ots / Mandate / Compute / Listen / DaemonStep)
- 33.y.h — 10 wire integrations graduated (Emit / Publish / Discover / Persist / Retrieve / Mutate / Purge / Transact / Deliberate / Consensus)
- 33.y.i — 3 PIX variants graduated (Hibernate / Drill / Trail) — **43 of 45**
- 33.y.j — Lambda + UseTool graduated — **🎉 45 of 45 FINAL**
- 33.y.k — D8 milestone: tools first-class on streaming path + `FlowExecutionEvent::ToolCall` closed-catalog variant
- 33.y.l — D7 milestone: parity gate + legacy shim retirement + `#[deprecated]` signals on legacy routing primitives
- 33.y.m — this document + ADOPTER_STREAMING.md extension
- 33.y.n — D12 fuzz consolidation + dedicated CI workflow
- 33.y.o — coordinated release v1.26.0 cross-stack + axon-enterprise v1.17.0 catch-up

**What is explicitly DEFERRED:**

| Followup | Scope |
|---|---|
| **Fase 33.z (axon-lang v1.27.x)** | Production-side wiring of `flow_dispatcher::dispatch_node` into `server_execute_streaming`. The 33.y dispatcher is structurally complete; 33.z grafts it into the streaming surface so orchestration / PIX / algebraic / wire-integration / multi-agent / lambda flows become per-chunk-streaming-eligible on the wire (currently they fall back to the legacy synthetic-burst path). 50-flow sync↔async parity corpus + deletion of the deprecated routing primitives lands here. |
| **Fase 33.y.g.2 / enterprise R&D track** | Real enterprise-integration overrides for the algebraic-effect helpers (`apply_shield` / `apply_ots` / `apply_mandate` / `invoke_compute` / `listen_on_channel` / `invoke_daemon`). OSS v1.26.0 ships identity-passthrough / canonical placeholders; enterprise R&D wires HIPAA PHI scrubber + legal privilege scanner + fintech AML pipeline + audio OTS resamplers + compute capability runtime + Fase 13 typed channels + Fase 16 daemon supervisor. |
| **Fase 33.y.e.2** | Concrete per-branch dispatch through `IRParallelBlock.branches` once the AST/IR extends with `branches: Vec<Vec<IRFlowNode>>`. v1.26.0 ships the public helper `run_branches_concurrently` against a payload-free `IRParallelBlock`; future Par-block IR extensions wire the helper into `dispatch_node` without breaking the v1.26.0 wire surface. |
| **Fase 33-followon-2** | Mid-stream tool call **execution** — currently v1.26.0 emits `ToolCall` events when upstream signals `FinishReason::ToolUse`, but tool result interleaving + execution resumption stays on the legacy synchronous path until a future cycle. |
| **Fase 34** | Per-token cryptographic chain signature for byte-exact stream replay. v1.26.0's per-step `step_audit` records satisfy regulated-vertical audit standards for most adopters; per-token chain ships if/when adopters need byte-exact stream replay. |

---

## Verification matrix

After upgrading to v1.26.0, run this matrix in your adopter
environment to verify the migration:

| Check | Command | Expected |
|---|---|---|
| OSS lib + integration suites | `cargo test --manifest-path axon-rs/Cargo.toml` | All 68 test binaries green; 3349 tests pass / 0 fail; lib count 1735 |
| 33.y dispatcher diagnostic anchor | `cargo test --manifest-path axon-rs/Cargo.toml --test fase33y_dispatcher_diagnostic` | 6 passed (sub-fase a foundational pin) |
| 33.y.b drift gate | `cargo test --manifest-path axon-rs/Cargo.toml --test fase33y_b_dispatcher_skeleton` | 9 passed (cartesian-product cardinality + every-variant-routes + cancel-honored + slug coverage + DispatchCtx + DispatchError + no-panic) |
| 33.y.k tools first-class | `cargo test --manifest-path axon-rs/Cargo.toml --test fase33y_k_tools_first_class` | 14 passed (D4 byte-compat + closed-catalog variant + serde + composition + 200-iter random apply_ref fuzz) |
| 33.y.l D7 parity gate | `cargo test --manifest-path axon-rs/Cargo.toml --test fase33y_l_parity_gate` | 7 passed (no markers + no panic outside tests + no retired symbols + pinned 10-file set) |
| Wire body byte-compat for stub | POST to any `transport: sse` route deployed with `backend: stub`; capture body | 1 axon.token "(stub)" + 1 axon.complete (identical to v1.25.0) |
| Wire body byte-compat for canonical Step + real backend | Set provider key + POST canonical `step S { ask: "..." output: Stream<Token> }`; capture body | Per upstream provider chunk (identical to v1.25.0) |
| Legacy fallback still operational | Deploy a flow with `for x in [...]` or other 33.x-deferred shape; POST it; inspect `axon.complete.warnings` | Single W002 entry with `fallback_mode: "unsupported_flow_shape"` (identical to v1.25.0; 33.z grafts the new dispatcher) |
| Deprecation signals visible | Build a downstream crate that references `PlanError::LegacyOrchestrationRequired` without `#![allow(deprecated)]` | Compile emits deprecation warning with the 33.z-retirement note |

---

## See also

- [ADOPTER_STREAMING.md § Universal algebraic streaming (Fase 33.y, v1.26.0+)](ADOPTER_STREAMING.md#universal-algebraic-streaming-fase-33y-v1260) — the canonical adopter guide for the dispatcher surface.
- [Fase 33.y plan vivo](fase_33y_algebraic_streaming_dispatcher.md) — internal sub-fase tracker + D1–D12 ratifications.
- [MIGRATION_v1.25.md](MIGRATION_v1.25.md) — previous-version migration guide; covers the Fase 33.x production-path activation that 33.y builds on.
- [MIGRATION_v1.24.md](MIGRATION_v1.24.md) — the Fase 33 primitive activation that 33.x activated at runtime.
- [axon-rs `tests/fase33y_*.rs`](../axon-rs/tests/) — canonical test pack for the 33.y cycle (18 test files: a/b foundation + c–j handler graduation + k tools first-class + l parity gate + dispatcher diagnostic anchor).
- [Fase 11.a — Stream<T> algebraic effect](fase_11_neuro_symbolic_axon.md) — the algebraic-effect foundation the 33.y cycle structurally closes across the entire IRFlowNode catalog.

---

*This document is part of the axon-lang public adopter surface.
PRs welcome — see `CONTRIBUTING.md`.*
