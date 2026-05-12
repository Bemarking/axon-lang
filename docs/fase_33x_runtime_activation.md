---
title: "Plan vivo: Fase 33.x — Runtime activation of algebraic streaming (close the four-pillar contract on the production SSE path)"
status: ✅ 33.x.a SHIPPED 2026-05-12 — Founder bloque ratification verbatim "Ratificado todos los D-Letters. Muy importante, Nda de MVP, o souciones parciales, que sea full 100% completo que sea posible." D1–D11 LOCKED bloque. Diagnostic anchor `axon-rs/tests/fase33x_real_streaming_diagnostic.rs` (6 tests green) captures the v1.24.0 production-path wire shape verbatim — 1 synthetic axon.token with content "(stub)", 1 axon.complete with `stream_policies` populated and `enforcement_summary` absent, no `axon-W002` warning surface, replay binding inactive without explicit `replay: true`. As each 33.x sub-fase lands the anchor's assertions are rewritten in lockstep; the diff between this baseline and the post-33.x.m shape is the cycle's closure proof. Cycle scope is the production-path activation of the Fase 33.a-i primitives: replace the synchronous-burst producer inside `server_execute_streaming` with a true `Backend::stream()`-driven async per-step loop, wire `StreamPolicyEnforcer` into the chunk path so declared `<stream:<policy>>` runs in production, plumb `CancellationFlag` into reqwest body consumption so client-disconnect aborts upstream HTTP within ≤100ms wall-clock, retire the deferred mono-file `crate::backend` (Fase 24.j.2 debt), add `axon-W002 streaming-not-supported` closed-catalog warning, extend `/v1/replay/<trace_id>` to per-step granularity, and gate a real-provider E2E lane behind `AXON_RUN_REAL_PROVIDER_TEST`. Wire-format byte-compat preserved per Fase 33 D9. 33.x.b–33.x.m proceed per the established sub-fase founder sign-off cadence ("procede con 33.x.X (100% robusto)"). Quality bar per founder directive 2026-05-12: **NO MVP, NO partial solutions, full 100% production-complete from start**.
owner: AXON Runtime + Backends Team
created: 2026-05-12
target: axon-lang v1.25.0 (minor — runtime timing semantics change from synchronous-burst to true live per-token streaming; wire format byte-identical to v1.24.0; no new declaration fields; no new event types; adopter source unchanged)
depends_on: Fase 33.a-i SHIPPED v1.24.0 (FlowExecutionEvent catalog L1 + live mpsc consumer L2 + Backend::stream() per-provider L3 + stream_effect_dispatcher L4 + CancellationFlag/CancelOnDrop D6 + D12 fuzz + dedicated CI lane); Fase 24.b-j SHIPPED (trait + 7 native backends + locked-model dispatch + tokens.rs unified); Fase 23 SHIPPED (algebraic effects runtime — delimited continuations + handler stack)
charter_class: OSS — every adopter benefits transitively. This is the cycle that takes the architecturally-in-place primitives from v1.24.0 and makes them adopter-observable on the production SSE path. The Fase 33 framing ("SSE es una primitiva cognitiva, eso en axon lo es todo") is honored only after this cycle closes; v1.24.0 shipped the substrate, v1.25.0 ships the activation.
pillars: MATHEMATICS — the algebraic effect `<stream:<policy>>` is a delimited continuation whose handler now runs on the in-flight `Stream<ChatChunk>`, not on a post-hoc materialized String; LOGIC — every step whose tool declares a stream effect activates the enforcer in production (declaration ⟺ runtime contract, not declaration ⟺ wire JSON field); PHILOSOPHY — the declared effect IS the wire behavior, end-to-end, from network byte to adopter EventSource; COMPUTING — bounded buffers + atomic counters + cooperative cancellation with measurable ≤100ms p95 client-disconnect-to-task-abort budget, observable under load with real provider keys
---

> **Founder principle reinforcement (Fase 33 trigger, 2026-05-12):**
>
> *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto en todos los escenarios posibles. […] no pienses en kivi, piensa a axon necesita resolver esto."*
>
> **Honest scope statement carried verbatim from Fase 33.h (`ADOPTER_STREAMING.md` + `MIGRATION_v1.24.md`):**
>
> *"`server_execute_full` materializes all step outputs before chunking; producer/consumer split is structurally end-to-end but per-token wall-clock incrementality activates when Backend::stream() wires into per-step execution — that's a 33.x follow-up that does NOT modify the L1-L4 primitives."*
>
> **This plan delivers exactly that activation.**

---

## ▶ 1. Recap — what Fase 33.a-i closed and what stayed latent

### Architecturally shipped (v1.24.0)

| Layer | Module / surface | Status |
|---|---|---|
| **L1** | `flow_execution_event::FlowExecutionEvent { FlowStart, StepStart, StepToken, StepComplete, FlowComplete, FlowError }` cross-stack (Rust + Python with shared 12-entry corpus drift gate) | ✅ |
| **L2** | `server_execute_streaming(...) -> StreamingExecution { events: mpsc<FlowExecutionEvent>, exited: Arc<Notify> }` + `execute_sse_handler` consuming the receiver LIVE event-by-event onto the SSE wire | ✅ |
| **L3** | `Backend::stream() -> Pin<Box<dyn Stream<Item = Result<ChatChunk, BackendError>>>>` native for all 7 providers behind shared `sse_streaming.rs` (LineBuffer + SseEventParser + LineStream + SseEventStream) | ✅ |
| **L4** | `stream_effect_dispatcher::{resolve_stream_effect_for_step, StreamPolicyEnforcer}` with all 4 closed-catalog policies (`DropOldest`/`DegradeQuality`/`PauseUpstream`/`Fail`) honored under `Stream<ChatChunk>` adversarial unit tests | ✅ |
| **D6** | `cancel_token::{CancellationFlag, CancelOnDrop}` — monotone 2-state + RAII guard + idempotent + register-before-recheck wake-up pattern | ✅ |
| **D12** | `fase33_fuzz.rs` — ~2 000 deterministic LCG iters across 13 surfaces; all total + never-panic | ✅ |
| **CI** | `.github/workflows/fase_33_sse_cognitive_primitive.yml` — 7 parallel lanes covering each layer + D6 + D12 + D9 backwards-compat | ✅ |
| **Docs** | `ADOPTER_STREAMING.md` §"Real-time streaming (Fase 33, v1.24.0+)" + `MIGRATION_v1.24.md` 5 scenarios + cross-references to enforcer/cancel/fuzz | ✅ |

### Behaviorally latent — the gap this cycle closes

The production SSE handler resolves to this sequence today (verified at `axon-rs/src/axon_server.rs:18181-18290`):

```rust
fn server_execute_streaming(...) -> StreamingExecution {
    tokio::task::spawn_blocking(move || {
        // 1. Emit FlowStart
        emit(FlowStart { ... })?;

        // 2. SYNCHRONOUSLY call the legacy mono-file executor
        let (result, _) = server_execute_full(...);  // ← blocks until ALL steps complete

        // 3. AFTER completion, walk the materialized step_results
        for (i, step_name) in er.step_names.iter().enumerate() {
            let full_output = er.step_results.get(i)...;
            // 4. Synthetically chunk the final String into 3-word groups
            let chunks: Vec<String> = full_output
                .split_whitespace()
                .chunks(3)
                .map(|c| c.join(" "))
                .collect();
            for chunk in &chunks {
                emit(StepToken { content: chunk.clone(), ... })?;
            }
        }
    })
}
```

This means:

1. **The `Backend::stream()` trait surface (Fase 33.d) is never reached from the production SSE path.** Adopter-deployed flows produce one big LLM call via `crate::backend::call_multi` (synchronous, non-streaming), then the wire emits synthetic 3-word groups.
2. **`StreamPolicyEnforcer` (Fase 33.e) never runs on a real `Stream<ChatChunk>`.** The `effect_policies` field on `axon.complete` is populated for audit/replay correlation but the enforcer's policy semantics (drop/degrade/pause/fail) are exercised only by the unit-test surface — never by adopter chunks.
3. **`CancellationFlag` (Fase 33.f) is observed between event emissions, but the reqwest body inside the legacy `backend::call_multi` keeps draining until done.** Client disconnect today still pays the full upstream-completion latency.
4. **The declared `<stream:<policy>>` effect on adopter tools is compile-time documentation in production.** The type system threads it through `resolve_stream_effect_for_step`, but the runtime can't honor it without a real chunk stream to enforce against.
5. **Per-step audit trace (Fase 32.h `replay: true`) for SSE routes records the final response only.** Because `server_execute_full` returns one ServerExecutionResult, the replay store sees a single audit row, not the live token sequence.

The four-pillar contract is **complete in primitive but partial in production**. Fase 33.x makes it complete in production.

---

## ▶ 2. What 33.x closes — concrete code-level work

### 2.1 The bridge — `server_execute_streaming` calls `Backend::stream()` per step

Replace the body of `server_execute_streaming` ([axon_server.rs:18181](../axon-rs/src/axon_server.rs#L18181)) with an async loop that drives the Fase 24 trait directly:

```rust
async fn server_execute_streaming_async(
    state: SharedState,
    source: String,
    source_file: String,
    flow_name: String,
    backend_name: String,
    cancel: CancellationFlag,
    tx: mpsc::UnboundedSender<FlowExecutionEvent>,
) -> Result<(), FlowError> {
    let plan = build_streaming_plan(&source, &source_file, &flow_name, &backend_name)?;
    let backend = state.backend_registry.resolve(&backend_name)?;
    let effect_policies = resolve_stream_policies_for_flow(&source, &source_file, &flow_name);

    tx.send(FlowStart { ... })?;

    for (step_index, unit) in plan.units.iter().enumerate() {
        if cancel.is_cancelled() { return Err(FlowError::Cancelled); }
        tx.send(StepStart { step_name: unit.name.clone(), step_index, ... })?;

        let request = ChatRequest::from_unit(unit, &history);
        let chunk_stream = backend.stream(request).await?;

        // Wrap with policy enforcer if this step's tool declared <stream:<policy>>
        let enforced_stream = if let Some(policy) = effect_policies.get(&unit.name) {
            StreamPolicyEnforcer::new(*policy, default_buffer_capacity())
                .drain_stream(chunk_stream, &cancel)
        } else {
            chunk_stream
        };

        let mut token_index = 0u64;
        let mut chunks_seen = 0u64;
        let mut accumulated = String::new();

        tokio::pin!(enforced_stream);
        while let Some(chunk_result) = enforced_stream.next().await {
            if cancel.is_cancelled() { return Err(FlowError::Cancelled); }
            match chunk_result {
                Ok(chunk) => {
                    token_index += 1;
                    chunks_seen += 1;
                    accumulated.push_str(&chunk.delta);
                    tx.send(StepToken {
                        step_name: unit.name.clone(),
                        content: chunk.delta,
                        token_index,
                        timestamp_ms: now_ms(),
                    })?;
                    if chunk.finish_reason.is_some() { break; }
                }
                Err(e) => return Err(FlowError::BackendStreamFailed(e)),
            }
        }

        tx.send(StepComplete {
            step_name: unit.name.clone(),
            step_index,
            output_length: accumulated.len(),
            tokens_emitted: chunks_seen,
            timestamp_ms: now_ms(),
        })?;

        // Per-step audit trace, plumbed through the same channel
        audit_step(&state, &flow_name, &unit.name, &accumulated, &cancel).await?;
        history.push_assistant(accumulated);
    }

    tx.send(FlowComplete { ... })?;
    Ok(())
}
```

Key points:

- **Async-fn, not `spawn_blocking`.** The producer is a true async task that yields between chunks. No thread blocked waiting for a 60-second LLM call.
- **One mpsc send per backend chunk.** `chunk.delta` (the provider's actual text granularity) is forwarded verbatim. No `split_whitespace().chunks(3)` synthesis on this path.
- **Cancellation checked at every chunk + before each step.** Combined with §2.3 (in-stream cancel) this delivers the ≤100ms p95 budget.
- **Enforcer wraps the per-step stream once.** All four policies are exercised in production by adopter chunks.

### 2.2 Plan extraction — make `build_execution_plan` callable from both sync + async paths

Today `build_execution_plan` lives in `runner.rs` and produces `Vec<ExecutionUnit>` for synchronous CLI execution. Lift it (or a streaming-shaped sibling) to a shared `flow_plan` module:

```rust
// New: axon-rs/src/flow_plan.rs
pub struct StreamingExecutionUnit {
    pub name: String,
    pub system_prompt: String,
    pub user_prompt: String,
    pub tool_effects: Option<BackpressurePolicy>,  // resolved at plan time
    pub tools_available: Vec<ToolSpec>,
    pub max_tokens: Option<u32>,
}

pub fn build_streaming_plan(
    source: &str,
    source_file: &str,
    flow_name: &str,
    backend: &str,
) -> Result<StreamingExecutionPlan, PlanError> { ... }
```

The streaming plan resolves `tool_effects` per step at plan-build time (calling `resolve_stream_effect_for_step` from Fase 33.e), so the per-step loop above does not re-parse the AST per chunk. Pure + deterministic.

### 2.3 Cancellation observed inside the reqwest body

Today the per-provider `Backend::stream()` impls consume `reqwest::Response::bytes_stream()` until done or until the consumer drops the stream. For a real ≤100ms cancellation budget, each impl must race the body against the cancel flag:

```rust
// Inside backends::sse_streaming::SseEventStream::next
fn poll_next(self: Pin<&mut Self>, cx: &mut Context) -> Poll<Option<...>> {
    if self.cancel.is_cancelled() {
        return Poll::Ready(None);  // graceful end-of-stream
    }
    // ... existing line/event parsing ...
}
```

The `Backend::stream()` signature gains an optional `cancel: &CancellationFlag` parameter (or carries it via a `StreamContext` struct to avoid churning 7 impls). Each impl threads it into the `SseEventStream` / `LineStream` constructor. The reqwest body iterator's `poll_next` checks the flag before yielding the next chunk; when the flag fires, the iterator returns `Poll::Ready(None)` and the underlying `Drop` impl on the `reqwest::Response` aborts the HTTP request.

### 2.4 Per-step audit trace integration

`runner::run_audit_events` runs the audit handler stack per step in the CLI path. The streaming path bypasses it today (uses stub backend or skips audit when SSE is active). With 33.x.1 wiring real backends, the streaming path runs `audit_step(...)` (new helper) per step, recording:

- `step_name`, `tokens_emitted`, `output_hash` (SHA-256 of accumulated step output)
- `effect_policy_applied` (the BackpressurePolicy slug, or `None`)
- `chunks_dropped` (from the enforcer's `EnforcementSummary`)
- `chunks_degraded` (DegradeQuality count, when applicable)

This makes `/v1/replay/<trace_id>` (Fase 32.h) for SSE routes return the **per-step** sequence, not just the final response. Per-event chain (each `axon.token` individually signed) stays deferred to Fase 34.

### 2.5 Closed-catalog runtime warning when streaming is unsupported

When an adopter declares `output: Stream<T>` but routes through a backend that lacks `Backend::stream()` (custom adopter-provided backends, the legacy `stub` backend, or a future backend not yet ported), emit a closed-catalog runtime warning:

```rust
// New variant in axon::diagnostics::Warning
Warning::Axon_W002 {
    flow_name: String,
    step_name: String,
    backend_name: String,
    declared_output: String,        // "Stream<Token>"
    fallback_mode: FallbackMode,    // SyntheticWhitespace | SyntheticBpe | NotEmitted
}
```

`axon-W002` is the closed catalog (adding `axon-W003` requires a frontend change + a new test in the warning-emission gate). The warning surfaces:

- Once at flow-start in the `FlowStart` event (new optional `warnings` field, byte-compat by omission per D6).
- In the audit row (so adopters discover degraded streaming via `/v1/replay` even if their HTTP client ignores the SSE prelude).

### 2.6 Tokenizer-aware fallback chunking (optional, OSS only)

For custom adopter backends that return final text only, replace the `split_whitespace().chunks(3)` synthetic chunking with a tokenizer-aware chunking via the OSS BPE vocabulary (axon-csys, no vertical dict). Vertical-specific BPE (HIPAA/legal/fintech) is an axon-enterprise feature already shipped in v1.10.0+ that activates transitively. The OSS fallback delivers ~1-token chunks that match real provider granularity ~98% of the time on English prose; non-English degrades to the existing whitespace fallback with `axon-W002`.

### 2.7 Mono-file `crate::backend` retirement (Fase 24.j.2 debt closure)

With §2.1 routing the streaming path through the Fase 24 trait, the four remaining callers of `crate::backend::call_multi` / `call_multi_stream` (runner CLI sync path + ESK audit hook + audit_engine evidence packager + 1 more — identify exhaustively in the implementation) migrate to the trait. After migration:

```rust
// axon-rs/src/backend.rs  — DELETED (or shrunk to a re-export shim that proxies through Registry)
```

This closes the 24.j.2 follow-up debt explicitly tracked in the Fase 24 memory entry. Single source of truth = `backends::Registry`; no more parallel "mono-file vs trait" surface to keep in sync.

---

## ▶ 3. D-letter proposals (D1–D11)

| # | Statement | Pillar(s) |
|---|---|---|
| **D1** | **`Backend::stream()` is the only production path for `output: Stream<T>`** — after 33.x.1, the SSE handler MUST call `backend.stream(request)` per step and forward each `ChatChunk.delta` as one `StepToken` event. The synthetic 3-word `split_whitespace().chunks(3)` chunking is deleted from the SSE path; it survives only as the §2.6 fallback for backends without `stream()` (and that fallback fires `axon-W002`). | MATHEMATICS + LOGIC + COMPUTING |
| **D2** | **`StreamPolicyEnforcer` activates on every flow whose tool declares `<stream:<policy>>`** — the per-step backend stream is wrapped at flow-start (one wrapper per step that has a declared effect). The four closed-catalog policies (`DropOldest`/`DegradeQuality`/`PauseUpstream`/`Fail`) MUST exhibit byte-identical semantics in production to their unit-test surface (Fase 33.e). `EnforcementSummary` is published to the audit row via §2.4. | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D3** | **`CancellationFlag` is observed inside the reqwest body, not just between emissions** — each per-provider `Backend::stream()` impl threads the cancel flag into its `SseEventStream` / `LineStream` so the body iterator returns `Poll::Ready(None)` when the flag fires. Measurable contract: **p95 client-disconnect-to-task-abort ≤ 100ms** under a real (or local-loopback) HTTP server. This is a measurable invariant the §6 vertical lanes verify. | COMPUTING |
| **D4** | **Wire-format byte-identical to v1.24.0** — the SSE wire body shape stays the same. No new event types. `stream_policies` array on `axon.complete` retains its v1.24.0 shape. `FlowStart.warnings` is a new optional field that defaults to omitted (byte-compat with unknown-field-ignoring parsers per D6 Fase 33). Adopters consuming the v1.24.0 wire continue working bit-identically; the only observable change is **timing** (tokens arrive across the flow's lifetime, not in a burst at end). | COMPUTING (backwards-compat with Fase 30 D2 + Fase 31 D5 + Fase 32 D8/D9 + Fase 33 D9) |
| **D5** | **Closed-catalog runtime warning `axon-W002 streaming-not-supported`** — emitted once at flow-start when an adopter's declared `output: Stream<T>` falls through to a backend without `Backend::stream()`. Audit row records the warning. NO silent degradation. Adding `axon-W003` requires a frontend AST change + a closed-catalog test pin. | LOGIC + PHILOSOPHY |
| **D6** | **Per-step audit trace plumbed into replay store** — `/v1/replay/<trace_id>` for SSE routes returns the per-step sequence with `tokens_emitted` + `output_hash` + `effect_policy_applied` + `chunks_dropped` per step. Per-token chain signature (each `axon.token` cryptographically chained) stays deferred to Fase 34 — D6 here records the **per-step** granularity adopters need for FedRAMP AU-2 / FRE 502 / 21 CFR Part 11 audit trails. | COMPUTING + LOGIC |
| **D7** | **Mono-file `crate::backend` retirement is in scope of 33.x** — the Fase 24.j.2 follow-up debt closes in this cycle. All four remaining callers migrate to `backends::Registry`. Post-33.x, `axon-rs/src/backend.rs` either does not exist or is a 5-LOC re-export shim that proxies through the Registry. CI lane verifies the single source of truth. | COMPUTING (debt closure) |
| **D8** | **Stub backend stays for tests; CLI sync path is preserved** — `runner::execute_run` (sync, blocking CLI path with `on_chunk` callback printing tokens to stdout) keeps working unchanged. Only the **SSE handler** routes through the new async per-step loop. The stub backend remains the test default; when stub is selected the existing CLI synthetic-chunking path fires `axon-W002`. Two-path coexistence is explicit, not accidental. | COMPUTING + LOGIC |
| **D9** | **Tokenizer-aware fallback chunking is OPT-IN per backend** — the §2.6 BPE fallback runs only when (a) the backend lacks `stream()` AND (b) the adopter sets `transport: sse` AND (c) the runtime flag `axon_runtime.streaming.tokenizer_fallback = true` is set (defaults to `false` = whitespace fallback + `axon-W002`). Vertical BPE (axon-enterprise) inherits transitively when the adopter ships on the enterprise stack. | COMPUTING |
| **D10** | **Real-provider E2E lane is OPT-IN** — `.github/workflows/fase_33x_real_provider.yml` runs only when the workflow secret `AXON_RUN_REAL_PROVIDER_TEST=1` is present. Anthropic + OpenAI keys read from secrets, hit a short pinned prompt, verify p95 inter-chunk latency ≤100ms. NO flake on normal PR runs. Vertical lanes (Banking, Government, Legal, Medicine) re-run with real providers when the same secret is set. | COMPUTING (production-validation discipline) |
| **D11** | **Four-pillar trace requirement (meta, carried verbatim from Fase 33 D10)** — every Fase 33.x D-letter MUST map to ≥1 of {MATHEMATICS, LOGIC, PHILOSOPHY, COMPUTING}. D-letters that fail the trace are rewritten or cut. **Founder principle reinforcement**: SSE is a cognitive primitive; it is "todo"; therefore the activation cycle ships as a coherent contract or not at all (no partial / asterisked deliverables). | PHILOSOPHY (meta) |

---

## ▶ 4. Sub-fase shape — sequenced execution

Topologically sequenced. 33.x.1 unblocks 33.x.3 (enforcer activation against real chunks) + 33.x.4 (cancel plumbing inside reqwest body) + 33.x.5 (per-step audit). 33.x.2 is a co-requisite for 33.x.1 (plan extraction must be shared). 33.x.6 (W002) is independent. 33.x.7-10 are hardening + debt closure.

| Sub-phase | Layer / D-letter | LOC target | Status | Description |
|---|---|---|---|---|
| **33.x.a** | spec | doc-only | ✅ SHIPPED 2026-05-12 | This document + memory entry `project_fase_33x_plan.md` + MEMORY.md index update. Founder bloque ratification of D1–D11 verbatim ("Ratificado todos los D-Letters. Muy importante, Nda de MVP, o souciones parciales, que sea full 100% completo que sea posible."). Diagnostic anchor `axon-rs/tests/fase33x_real_streaming_diagnostic.rs` ships 6 tests green capturing the v1.24.0 production-path wire shape verbatim. Anchor surfaces: D1 synthetic 3-word chunking baseline + D2 `stream_policies` populated/`enforcement_summary` absent + D2 elision-when-no-effect + D3 wire shape well-formed + D5 no `axon-W002` warning surface + D6 replay binding inactive without `replay: true`. Each sub-fase rewrites the relevant anchor assertions in lockstep. |
| **33.x.b** | D1 + L3 (bridge) | ~400 | ⏳ | **The critical core.** Refactor `server_execute_streaming` from `spawn_blocking(server_execute_full)` + synthetic chunking into an async per-step loop driving `Backend::stream()`. Per step: resolve backend via Fase 24 `Registry`, build `ChatRequest`, `backend.stream(req).await`, forward each `ChatChunk.delta` as `StepToken`. Delete synthetic chunking on this path. Per-provider trait surface gains a `StreamContext { cancel: &CancellationFlag, audit_tx: ... }` parameter (preferred over churning the trait signature). |
| **33.x.c** | plan extraction (co-req) | ~250 | ⏳ | Lift `build_execution_plan` from `runner.rs` to `axon-rs/src/flow_plan.rs` (or new module). Add `build_streaming_plan` that pre-resolves per-step `tool_effects` via `resolve_stream_effect_for_step` so the hot loop in 33.x.b doesn't re-walk the AST per chunk. Shared by both CLI sync and server async paths. |
| **33.x.d** | D2 + L4 (enforcer activation) | ~200 | ⏳ | Wrap the per-step `Stream<ChatChunk>` from 33.x.b with `StreamPolicyEnforcer::drain_stream(stream, cancel)` when the step's tool declared `<stream:<policy>>`. The enforcer's `EnforcementSummary` (chunks_pushed/delivered/dropped/degraded) is published to the audit row via 33.x.f. Adversarial tests: fast producer + slow consumer × all four policies × 1k chunk seeds, verifying byte-identical semantics with the Fase 33.e unit-test surface. |
| **33.x.e** | D3 + D6 (cancel inside body) | ~150 | ⏳ | Each per-provider `Backend::stream()` impl threads the cancel flag through `SseEventStream` / `LineStream` so the body iterator returns `Poll::Ready(None)` on cancel. Measurable invariant: **p95 client-disconnect-to-task-abort ≤ 100ms** under a local axum server with a synthetic slow-drip backend mock. Integration test asserts the abort latency window. |
| **33.x.f** | D6 + audit | ~200 | ⏳ | Per-step audit trace integration. New helper `audit_step(state, flow, step_name, output, enforcement_summary, cancel)` plumbed through the streaming path. `replay::record_step_event` per step. `/v1/replay/<trace_id>` for SSE routes returns the per-step sequence (Fase 32.h binding retained, granularity refined). Per-token chain stays deferred to Fase 34. |
| **33.x.g** | D5 (axon-W002) | ~50 | ⏳ | Closed-catalog runtime warning `axon-W002 streaming-not-supported`. Emit once at flow-start when the resolved backend lacks `stream()`. New optional `warnings` field on `FlowStart` (default omitted, D4 wire byte-compat). Audit row mirrors. Closed-catalog test pin in `tests/fase33x_warning_catalog.rs`. |
| **33.x.h** | D9 (tokenizer fallback) | ~200 | ⏳ | Opt-in tokenizer-aware fallback chunking for backends without `stream()`. OSS path uses `axon-csys` generic BPE; enterprise inherits vertical BPE transitively when the adopter ships on enterprise. Defaults to OFF; adopter opts in via `axon_runtime.streaming.tokenizer_fallback = true`. Vertical lanes (banking/legal/fintech/healthcare) run with enterprise enabled. |
| **33.x.i** | D7 (mono-file retirement) | ~600 | ⏳ | Retire `crate::backend` mono-file. Migrate the 4 remaining callers (runner CLI sync path + ESK audit hook + audit_engine evidence packager + identify exhaustively) to `backends::Registry`. Post-migration `backend.rs` either does not exist or is a 5-LOC re-export shim. CI lane verifies single source of truth. Fase 24.j.2 debt closes here. |
| **33.x.j** | D10 (real-provider E2E) | ~300 | ⏳ | New workflow `.github/workflows/fase33x_real_provider.yml` gated on `AXON_RUN_REAL_PROVIDER_TEST` secret. Anthropic + OpenAI + Gemini lanes hit a short pinned prompt, verify p95 inter-chunk latency ≤100ms wall-clock. Vertical canonical patterns (banking/government/legal/medicine) re-run with real providers when the secret is set. NO flake on normal PR runs (gated lane). |
| **33.x.k** | D12 + drift (fuzz + CI) | ~400 | ⏳ | New `axon-rs/tests/fase33x_fuzz.rs` covering 33.x surfaces (~1 500 deterministic LCG iters across: cancel-during-stream propagation, enforcer + cancel interaction, plan-build stability under malformed source, axon-W002 catalog closure, audit_step replay binding). Extend `.github/workflows/fase_33_sse_cognitive_primitive.yml` with 33.x lanes OR add `.github/workflows/fase_33x_runtime_activation.yml` (TBD per implementation choice — favor extension to keep CI surface coherent). |
| **33.x.l** | adopter docs | ~400 | ⏳ | Extend `ADOPTER_STREAMING.md` with new §"Production-path activation (Fase 33.x, v1.25.0+)" — adopter checklist (what changes, what doesn't), 4-policy production behavior table, `axon-W002` reading guide, per-step replay binding example, real-provider E2E recipe. New `docs/MIGRATION_v1.25.md` (~250 LOC) with 4 scenarios: A=server-only upgrade (no source change), B=indexing per-step replay rows for compliance audit, C=tokenizer fallback opt-in, D=client-disconnect cancel-budget validation with curl + tcpdump. D4 wire byte-compat statement up front. |
| **33.x.m** | release | release | ⏳ | axon-lang v1.24.0 → v1.25.0 cross-stack: bump-my-version minor (Python pyproject + Rust Cargo.toml + Cargo.lock + 2 test pins). axon-frontend stays 0.11.1 (no AST changes — `tool_effects` resolution is runtime, not AST). axon-enterprise catch-up v1.16.0 (lean) PLUS substantive vertical layers: banking real-streaming audit + HIPAA real-streaming PHI scrubber (per-chunk, not per-final-response) + legal real-streaming privilege-trace + fintech real-streaming AML signal preservation across the live token sequence. PyPI + crates.io + GitHub Release with content-first notes. |

**Total target: ~3 200 LOC + ~400 new tests + 1 new CI workflow (or extension of fase_33).**

---

## ▶ 5. Vertical-grounded relevance

The same four high-profile verticals from Fase 32-33, now with **production-real** streaming:

- **Banking** — `POST /loan/decision` with `transport: sse + replay: true` streams the risk-explanation narration **token-by-token from Anthropic SSE**, not in a burst at end. PCI DSS Req 10 audit row records each step's token count + output hash + enforcement summary (DropOldest dropped 0/N chunks under slow-consumer client). Auditor retrieves via `GET /v1/replay/<trace_id>` and sees the per-step sequence — the same data the regulator can replay on appellate review.

- **Government** — `POST /benefits/eligibility` streams the eligibility-reasoning narrative live. FedRAMP AU-2 retention captures the live trace at per-step granularity. FOIA requests retrieve the per-step replay. Per-token chain signature is a Fase 34 follow-up; per-step is sufficient for AU-2.

- **Legal** — `POST /discovery/privilege` streams the privilege-assessment reasoning. FRE 502 waiver-doctrine appeals trace the per-step reasoning chain with the enforcement summary (DegradeQuality applied 0/N times under saturation). Per-chunk PHI scrubber path through the enterprise legal vertical inherits transitively.

- **Medicine** — `POST /clinical/decision-support` streams clinical recommendations to clinician UI **as Anthropic produces them**, not after a 30-second silence. The PHI scrubber (Fase 27.g) runs per-chunk via the enterprise HIPAA dict. 21 CFR Part 11 §11.10 audit captures the per-step live sequence. Cancel-safety: clinician closes the tab → upstream HTTP request to Anthropic aborts within ≤100ms (no wasted token quota, no orphaned audit row).

Each vertical pattern works at the wire-format level today (v1.24.0). Fase 33.x makes the **timing** real, which is what clinician/banking/legal/government UIs need adopter-observably.

---

## ▶ 6. Founder framing — why this cycle ships now

The Fase 33.i memory entry + the `ADOPTER_STREAMING.md §"Honest scope statement"` published 2026-05-12 said: *"server_execute_full materializes all step outputs before chunking; per-token wall-clock incrementality activates when Backend::stream() wires into per-step execution — that's a 33.x follow-up."*

Fase 33.x **is that follow-up**. It is not a new architecture; it is the activation of the architecture v1.24.0 shipped. The four-pillar contract:

| Pillar | v1.24.0 (Fase 33.a-i) | v1.25.0 (Fase 33.x) |
|---|---|---|
| **MATHEMATICS** | Algebraic effect catalog closed (Stream effect + 4 backpressure policies); enforcer semantics verified in unit tests against `Stream<ChatChunk>` adversarial | Same enforcer runs in production on the in-flight `Stream<ChatChunk>` from real LLM providers |
| **LOGIC** | Type checker recognizes `<stream:<policy>>`, threads it through `resolve_stream_effect_for_step`, populates `stream_policies` array for wire audit | Declared effect activates the runtime enforcer on the production chunk path; declaration ⟺ runtime contract, not declaration ⟺ wire JSON field |
| **PHILOSOPHY** | Wire format byte-identical to the streaming-perfect vision; SSE wire body shape locked | Wire **timing** is byte-perfect too — `axon.token` arrives at network granularity, not synthetic 3-word groups; the declared effect IS the wire behavior, end-to-end |
| **COMPUTING** | CancellationFlag + CancelOnDrop primitives verified in unit tests; producer/consumer split structurally in place | p95 client-disconnect-to-task-abort ≤100ms measured under load; bounded buffers honored under fast-producer/slow-consumer with adopter chunks; reqwest body aborts on cancel |

Without Fase 33.x, the founder principle *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto"* has an asterisk in the production path. Fase 33.x removes the asterisk.

---

## ▶ 7. Bloque ratification — RATIFICADAS 2026-05-12

Founder reviewed §1 (recap) + §2 (concrete code-level gap) + §3 (D1–D11) + §4 (sub-fase shape) + §5 (vertical-grounded) + §6 (founder framing) and ratified verbatim:

> **"Ratificado todos los D-letters. Muy importante, Nda de MVP, o souciones parciales, que sea full 100% completo que sea posible."** — 2026-05-12

D1–D11 are now the locked contract for the Fase 33.x cycle. **The "no MVP, no partial solutions, full 100% production-complete" mandate** is recorded here verbatim and binds every sub-fase 33.x.b–33.x.m. The diagnostic anchor `axon-rs/tests/fase33x_real_streaming_diagnostic.rs` (6 tests green at this commit) is the cycle's closure proof.

33.x.a is SHIPPED with the ratification commit. 33.x.b–33.x.m proceed per the established sub-fase founder sign-off cadence ("procede con 33.x.X (100% robusto)").

### Quality-bar interpretation of the "no MVP" mandate

Per `feedback_no_shortcuts.md` + this ratification, the following are NON-NEGOTIABLE for every sub-fase:

- **No `unwrap()` on adopter-reachable paths.** Every error case is named in a closed catalog enum + handled.
- **No `// TODO` / `// FIXME` markers shipping to master.** If a follow-up is unavoidable it ships as its own sub-fase with explicit founder sign-off.
- **No silent degradation.** D5 (`axon-W002`) is the canonical example; the principle generalizes — every fallback path emits a closed-catalog warning that the adopter can observe.
- **Every public function on the new surface is total + has a documented invariant.** `cargo doc` builds clean.
- **Every sub-fase ships with adversarial fuzz coverage** (~150-200 LCG seeds per public predicate) before the SHIPPED marker flips.
- **Every sub-fase ships with vertical canonical patterns exercised** (Banking/Government/Legal/Medicine) on the cycle's CI lane before the SHIPPED marker flips.
- **Every sub-fase that changes wire shape** asserts byte-compat against the Fase 30/31/32 wire surface via the existing D9 anchor tests; the assertion runs in the cycle's dedicated CI lane.
- **No partial migrations.** If a callsite is touched it migrates fully — no parallel "old-path-still-works-for-now" surfaces. The mono-file `crate::backend` retirement (33.x.i) ships AS migration of all 4 callers, not 3-of-4 with the last deferred.

Sub-fase landings honor `feedback_subfase_shipped_marker.md` — ⏳ → ✅ flip in plan vivo at landing + commit + push BEFORE pausing for next sign-off.

---

## ▶ 8. Out of scope (deferred to Fase 34+)

- **Per-event replay binding (per-token chain signature)** — Fase 33.x records per-**step** replay rows; per-token cryptographic chain (each `axon.token` signed + hash-chained for byte-exact replay-as-original) requires a Fase 11.c primitive extension and ships as Fase 34 if/when adopters need byte-exact stream replay (vs current per-step semantic replay).
- **Mid-stream tool calling** — function calling that interleaves a tool invocation into the live token stream (LLM emits `tool_call`, runtime invokes tool, result interleaves back into the stream). Out of scope for 33.x; tracked separately as Fase 33-followon-2.
- **gRPC bidirectional streaming binding** — Fase 33 + 33.x ship SSE only. gRPC is a future Fase orthogonal to the SSE work.
- **WebSocket upgrade from SSE** — out of scope (Fase 30 D2 chose SSE; revisit only with explicit founder reopening).
- **Per-event encryption** — `axon-csys-enterprise` HIPAA/PCI envelopes encrypt the final audit row; per-event symmetric AES envelope is a Fase 35 if regulated verticals need it.
- **Streaming-aware diagnostic rate-limit** — Fase 29's diagnostic gate operates per-flow; per-event diagnostic rate-limiting under saturation (1000 chunks/sec) is a Fase 36 if it surfaces in production.

---

## ▶ 9. Test surface target (~400 new tests)

| Surface | Test count | Module(s) |
|---|---|---|
| 33.x.b — `server_execute_streaming_async` per-step bridge unit | 40 | Rust |
| 33.x.b — `Backend::stream()` wired into production path (E2E with local axum mocks per provider × 7) | 70 | Rust |
| 33.x.c — `build_streaming_plan` purity + determinism + drift gate | 30 | Rust |
| 33.x.d — `StreamPolicyEnforcer` × 4 policies × 4 producer/consumer rate matrices | 80 | Rust |
| 33.x.e — Cancellation inside reqwest body, p95 ≤100ms invariant | 25 | Rust integration (real TcpListener + axum slow-drip backend mock) |
| 33.x.f — Per-step audit trace round-trip via `/v1/replay/<trace_id>` | 30 | Rust integration |
| 33.x.g — `axon-W002` catalog closure + emission paths × all 7 backends | 25 | Rust |
| 33.x.h — Tokenizer fallback (OSS BPE) chunking + opt-in flag wiring | 20 | Rust |
| 33.x.i — Mono-file `crate::backend` retirement — single-source-of-truth drift gate | 15 | Rust |
| 33.x.j — Real-provider E2E (gated `AXON_RUN_REAL_PROVIDER_TEST=1`) | 20 | Rust + GitHub Actions |
| 33.x.k — D12 fuzz (~1 500 LCG iters across 5 new surfaces) | 30 | Rust |
| 33.x.l — Vertical canonical patterns w/ real streaming (banking/government/legal/medicine × 4 cycles) | 20 | Rust integration |
| Cross-stack — Python audit row schema parity for per-step events | 15 | Python (consumer-only) |

---

## ▶ 10. Versioning + release plan

**Target**: axon-lang **v1.25.0** (minor — runtime timing semantics change from synchronous-burst to true live per-token streaming on the SSE path; wire format byte-identical to v1.24.0; no new declaration fields; no new event types; adopter source unchanged per D4).

**axon-frontend bump**: stays at 0.11.1 (no AST changes — `tool_effects` resolution happens at plan-build runtime, not in the AST).

**axon-enterprise catch-up**: v1.16.0 (lean catch-up consuming axon-lang ≥1.25.0) **plus substantive enterprise vertical layers**:

- Banking — real-streaming-aware audit row with per-chunk PCI DSS Req 10 hash chain (per-step granularity for Fase 33.x; per-token chain for Fase 34)
- Healthcare — real-streaming PHI scrubber that operates **per chunk** (the PHI scrubber runs on Anthropic's `content_block_delta` text, not on a post-hoc materialized String) — this is the 33.x activation of the Fase 27.g scrubber on the live stream
- Legal — real-streaming privilege-trace with per-step reasoning capture suitable for FRE 502 waiver-doctrine appeals
- Fintech — real-streaming AML/OFAC signal preservation across the live token sequence; per-step replay row binds to BSA case-file workflow

**Release order**: PyPI publish → crates.io publish (axon-lang only; axon-frontend stays at 0.11.1, no republish) → GitHub Release with content-first notes → axon-enterprise catch-up branch + PR + tag via refspec mapping + GitHub Release.

---

## ▶ 11. Founder-principle reinforcement

> *"Hacer que una aplicación AI sea determinista y fundada en nuestros cuatro pilares como lenguaje es el aporte a la humanidad por el que estamos trabajando"* — 2026-05-11, Fase 32 trigger.
>
> *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto"* — 2026-05-12, Fase 33 trigger.
>
> *"Axon for axon — every implementation makes axon better as a language, independent of who or how many adopt it"* — durable memory `feedback_axon_for_axon`.

Fase 32 made `axon` honor REST declarations. Fase 33 made `axon` honor STREAM declarations at the wire-format and primitive level. **Fase 33.x makes `axon` honor STREAM declarations at the production runtime level** — the per-step path inside `server_execute_streaming` calls `Backend::stream()`, the `StreamPolicyEnforcer` runs on real chunks, the `CancellationFlag` aborts the upstream HTTP request body within ≤100ms.

After Fase 33.x, when an adopter writes:

```axon
tool chat_token_stream {
    description: "Token-by-token LLM completion"
    effects: <stream:drop_oldest>
}
flow Chat() -> Unit {
    step Generate { ask: "hi" apply: chat_token_stream }
}
axonendpoint Chat { method: POST path: "/chat" execute: Chat }
```

the runtime contract is:

1. The HTTP POST to `/chat` opens `text/event-stream` (Fase 32.l + 33.a-i).
2. `Backend::stream()` opens the upstream HTTPS connection to Anthropic / OpenAI / Gemini / etc. (Fase 33.x.b).
3. Each network chunk arriving from the upstream provider is parsed (Fase 33.d), wrapped with `DropOldest` enforcer (Fase 33.x.d), and forwarded as one `axon.token` SSE event to the adopter's EventSource client.
4. If the adopter's client falls behind (slow consumer), the enforcer drops oldest queued chunks; the audit row records the drop count for compliance.
5. If the adopter's client disconnects (browser tab closed), the cancel flag fires; the reqwest body to Anthropic aborts within ≤100ms (Fase 33.x.e); no wasted token quota.
6. The per-step audit row binds to `/v1/replay/<trace_id>` (Fase 33.x.f) — the regulator replays the per-step reasoning chain.

That's the axon-shaped contribution to humanity's ability to deploy regulated, audit-defensible, **adopter-observably-real-time** AI.

---

## ▶ 12. How adopters consume this (post-shipping)

After Fase 33.x ships in v1.25.0, the adopter's canonical Kivi-shape source — **unchanged** from v1.23.0 / v1.24.0 — produces a wire whose body is byte-identical in format to v1.24.0 and **time-spaced** at backend chunk granularity:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
X-Axon-Trace-Id: f47ac10b-58cc-4372-a567-0e02b2c3d479

retry: 5000

event: axon.token
id: 1
data: {"step":"Generate","trace_id":"...","token":"Hello","timestamp_ms":1715517600000}

[~30ms later — Anthropic chunk]

event: axon.token
id: 2
data: {"step":"Generate","trace_id":"...","token":" world","timestamp_ms":1715517600030}

[~30ms later — Anthropic chunk]

event: axon.token
id: 3
data: {"step":"Generate","trace_id":"...","token":".","timestamp_ms":1715517600060}

...

event: axon.complete
id: 47
data: {
  "flow":"Chat",
  "steps_executed":1,
  "tokens_output":46,
  "backend":"anthropic",
  "success":true,
  "stream_policies":[{"step":"Generate","policy":"drop_oldest"}],
  "enforcement_summary":{
    "Generate":{"pushed":46,"delivered":46,"dropped":0,"degraded":0}
  }
}
```

Each `axon.token` arrives **as Anthropic produces it**, at the upstream provider's actual chunk granularity. `stream_policies` (v1.24.0 field, retained) names the active policy; `enforcement_summary` (new v1.25.0 field, optional, byte-compat by omission) reports what the enforcer did. The per-step audit row binds to `/v1/replay/<trace_id>` per Fase 33.x.f.

For adopters who don't depend on incremental delivery (consume the whole stream then use as final output), the wire format is bit-identical to v1.24.0 — they see the same JSON shape, just delivered over more time. D4 honors this absolutely.

---

## ▶ 13. The diagnostic anchor — what closes the cycle

[`axon-rs/tests/fase33x_real_streaming_diagnostic.rs`](../axon-rs/tests/fase33x_real_streaming_diagnostic.rs) lands with 33.x.a. Today (v1.24.0) it captures:

- Synthetic 3-word chunking on the SSE path (`token: "Hello world ."` from a stub flow → one `axon.token` per 3 words)
- Cancellation observed between event emissions only (reqwest body keeps draining)
- `stream_policies` populated but `enforcement_summary` absent
- Per-step audit row reflects final-response only

As each sub-fase ships, the diagnostic's assertions rewrite. When 33.x.m ships, the assertions read:

- One `axon.token` per upstream backend chunk (≥10 events from a real Anthropic prompt of ~50 tokens)
- Cancellation observed inside reqwest body, p95 abort ≤100ms (asserted under local axum slow-drip mock)
- `enforcement_summary` populated per step
- Per-step audit row reflects each step's `tokens_emitted` + `output_hash` + `effect_policy_applied`

That diagnostic crossing from pre-33.x-asserted shape to post-33.x-asserted shape is the cycle's closure proof.
