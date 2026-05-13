---
title: "Plan vivo: Fase 33.z — Universal dispatcher into production (graft 33.y into the SSE streaming surface)"
status: ⏳ IN PROGRESS — 33.z.a SHIPPED 2026-05-13 (plan vivo + diagnostic anchor with **10 tests verde** + forensic baseline capture: Par + Conditional fall to legacy with axon-W002 firing; ForIn + Remember + ShieldApply + Emit + Hibernate + LambdaDataApply all 404 — route doesn't even register in v1.26.0). 33.z.b–j remaining (graft skeleton + default-on flip + 50-flow parity corpus + legacy retirement + cross-stack + fuzz + CI + docs + release). D1–D11 pending founder bloque ratification. Prerequisite to Fase 34 (tools as stream-producers).
owner: AXON Runtime + Backends Team
created: 2026-05-13
target: axon-lang v1.27.0 (minor — `server_execute_streaming` graduates from the v1.25.0 canonical-Step-only hot path to dispatching every IRFlowNode variant through `flow_dispatcher::dispatch_node`; legacy synchronous fallback retired entirely; wire byte-compat preserved for canonical happy path; new optional `axon.complete.dispatch_path` audit field surfaces which architectural-group graduated this flow)
depends_on: Fase 33.y SHIPPED v1.26.0 (per-IRFlowNode async dispatcher with compiler-enforced exhaustive match over all 45 IRFlowNode variants; 9 architectural-group public helpers; D8 `FlowExecutionEvent::ToolCall` closed-catalog variant; D7 grep parity gate; D12 ~16 650 LCG iters cycle-wide; legacy shim infrastructure retired). Fase 33.x SHIPPED v1.25.0 (production async path activated for canonical Step shape — `Backend::stream()` + `StreamPolicyEnforcer` + p95 cancel ≤100ms + per-step replay binding + axon-W002 warning catalog). Fase 23 SHIPPED (algebraic-effects runtime — delimited continuations + perform Stream.Yield handler stack + 4-policy BackpressurePolicy catalog).
charter_class: OSS — every adopter benefits transitively. axon-enterprise inherits via the v1.18.0 catch-up (33.z.j) — vertical ensembles (HIPAA clinical reasoning + FRE 502 / Upjohn / Hickman privilege scanners + BSA/OFAC/MiFID II AML investigative pipelines + FedRAMP AU-2 government decision support) immediately observe per-chunk granularity on every orchestration shape (Par/ForIn/Conditional/Reason/Validate/Refine/Weave/PIX/algebraic-handlers/wire-integrations/multi-agent/lambda) without per-tenant code change.
pillars: |
  MATHEMATICS — The 33.y dispatcher (`pub async fn dispatch_node(node, ctx)`) is total over the closed 45-variant `IRFlowNode` catalog; 33.z lifts that totality from the test surface to the production wire. Every adopter flow's IR tree walks through the SAME exhaustive match that `tests/fase33y_l_parity_gate.rs` enforces — the production hot path becomes a CATEGORICAL morphism from IR tree to wire event stream. No special cases. No "canonical Step" fast path with everything else falling back. One handler per variant, structurally.

  LOGIC — `axon-W002 streaming-not-supported` becomes structurally unreachable. After 33.z, EVERY flow that declares `<stream:<policy>>` effects activates the enforcer at runtime — there is no shape the planner can REJECT. The warning catalog (Fase 33.x.g) deprecates the `UnsupportedFlowShape` `FallbackMode` variant; the only remaining `axon-W002` triggers are `UnknownBackend` (backend not in registry) + `SourceCompilationFailed` (parse/type-check failure). The declaration ⟺ runtime contract is total.

  PHILOSOPHY — The four-pillar contract is fully redeemed at the WIRE level. Pre-33.z, an adopter writing a `Conditional`/`ForIn`/`Par`/`PIX`/`algebraic-effect-handler` flow observed v1.24.0-shape wire (synthetic 3-word burst, materialized AFTER the flow completed). Post-33.z, that same source emits per-upstream-provider chunks in arrival order through the full orchestration tree. The semantic that the paper §1-§6 promises (algebraic effects as wire-observable conversation with the LLM, not as compile-time-only annotations) becomes the LIVE production behavior, not the test-suite behavior.

  COMPUTING — Cancel-in-body propagates through the FULL orchestration tree at p95 ≤100ms (33.x.e budget preserved end-to-end). A client disconnect during `Par { branchA, branchB, branchC }` fires the cancel flag once; all three concurrent dispatch_node calls observe it at the next `await` boundary and short-circuit through `Err(UpstreamCancelled)`; the SSE response drops; the upstream HTTP connections to LLM providers abort within wall-clock budget. No buffered up-front of LLM calls. No stuck `tokio::spawn` tasks. Bounded buffers + atomic counters + per-branch cooperative cancellation, end-to-end.
---

> **Founder principle (Fase 33.z trigger, post-v1.26.0 review 2026-05-13):**
>
> *"todavía hay un gap para lograr que los algebraics effects funcionen como debe ser […] no trabajar en pos de este adopter, sino en pos de que la primitiva cognitiva sea 100% funcional y ofrezca el valor que indica el paper."*
>
> The Fase 33.z mandate is to lift the 33.y structural totality (which lives in `flow_dispatcher::dispatch_node` as a publicly-callable async function but is NOT invoked from `server_execute_streaming`) into the production hot path. After 33.z, every adopter's `axonendpoint POST` with stream effects observes per-chunk-streaming wire behavior regardless of flow shape — no `axon-W002 UnsupportedFlowShape` ever fires again.

---

## ▶ 1. Recap — what 33.y graduated, what gap 33.z closes

### 33.y (v1.26.0) closed the STRUCTURAL contract

For every one of the 45 `IRFlowNode` variants:

- A named async handler exists in [`axon-rs/src/flow_dispatcher/`](../axon-rs/src/flow_dispatcher/) (10 modules: `pure_shape` / `orchestration` / `parallel` / `effects_bridge` / `cognitive` / `algebraic_handlers` / `wire_integrations` / `pix` / `lambda_tools` / `mod`).
- `pub async fn dispatch_node(node, ctx)` exhaustively matches on the variant + dispatches to the handler (compiler-enforced; D1 totality milestone reached at 33.y.j 45/45 graduation).
- `D7` grep parity gate (`tests/fase33y_l_parity_gate.rs`) enforces zero `unimplemented!()`/`todo!()`/`legacy_shim`/`ShimReason`/`LegacyShimHandled`/`LegacyShimFailed` references in the dispatcher source at every `cargo test` invocation.
- `D8` cross-cutting milestone: `FlowExecutionEvent::ToolCall` closed-catalog variant + `ChatRequest.tools` plumbed through every pure_shape-routed handler (33.y.k).
- `D12` cycle-wide fuzz: ~16 650 deterministic LCG iters across per-sub-fase + 33.y.n consolidated cross-cutting packs.
- 3 357 tests pass / 0 fail across 68 test binaries.

### The honest scope statement carried forward into 33.z

From the 33.y.l plan vivo entry, verbatim:

> *"The production wiring of `dispatch_node` into `server_execute_streaming` is a separate transformation that doesn't fit in this cycle's footprint cleanly. 33.y.l ships what unblocks 33.y.m–o: the parity gate that confirms 45/45 graduation is structurally locked + the shim infrastructure is gone + the deprecation signal is live. The 50-flow parity corpus + production dispatcher wiring lands in 33.z (axon-lang v1.27.x)."*

### What this means observationally for an adopter on v1.26.0

| Adopter shape | v1.26.0 wire behavior |
|---|---|
| Canonical `step S { ask: "..." output: Stream<Token> }` + stub backend | 1 axon.token "(stub)" + 1 axon.complete (33.x.b hot path; UNCHANGED) |
| Canonical canonical + real backend (Anthropic/OpenAI/Gemini) | Per-upstream-chunk `axon.token` via `Backend::stream()` (33.x.b; UNCHANGED) |
| Orchestration: `Let` / `Conditional` / `ForIn` / `Par` / `Break` / `Continue` / `Return` | **LEGACY FALLBACK** — synthetic-burst materialization → 3-word chunks AFTER the flow completes + `axon-W002 streaming-not-supported` warning |
| Cognitive: `Remember` / `Recall` / `Forge` / `Focus` / `Associate` / `Aggregate` / `Explore` / `Ingest` / `Navigate` / `Corroborate` | **LEGACY FALLBACK** (same) |
| Algebraic handlers: `ShieldApply` / `OtsApply` / `MandateApply` / `ComputeApply` / `Listen` / `DaemonStep` | **LEGACY FALLBACK** (same) |
| Wire integrations: `Emit` / `Publish` / `Discover` / `Persist` / `Retrieve` / `Mutate` / `Purge` / `Transact` / `Deliberate` / `Consensus` | **LEGACY FALLBACK** (same) |
| PIX: `Hibernate` / `Drill` / `Trail` / `Corroborate` | **LEGACY FALLBACK** (same) |
| Lambda + tools: `LambdaDataApply` / `UseTool` | **LEGACY FALLBACK** (same) |
| `perform Stream.Yield` inside `handle Stream { Yield(v) → resume(()) } in { ... }` | **LEGACY FALLBACK** — the paper §6 algebraic primitive is materialized then chunked |

**41 of 45 IRFlowNode variants currently fall to the legacy synchronous-burst path on the production SSE wire**, even though the structural dispatcher in 33.y can handle every one of them.

### The deprecation signal already lives in v1.26.0

Per 33.y.l:

- [`PlanError::LegacyOrchestrationRequired`](../axon-rs/src/flow_plan.rs) — `#[deprecated(since = "1.26.0")]`
- [`flow_plan::unsupported_feature_reason`](../axon-rs/src/flow_plan.rs) — `#[deprecated(since = "1.26.0")]`
- [`axon_server::run_streaming_legacy_path`](../axon-rs/src/axon_server.rs) — `#[deprecated(since = "1.26.0")]`

Each annotation's note points to `flow_dispatcher::dispatch_node`. 33.z deletes all three.

---

## ▶ 2. Concrete code-level gap

| Location | Today (v1.26.0) | 33.z target |
|---|---|---|
| [axon-rs/src/axon_server.rs `server_execute_streaming`](../axon-rs/src/axon_server.rs) | Hot path branches on `plan_attempt: Result<StreamingExecutionPlan, PlanError>`. `Ok(plan)` with known backend → `run_streaming_async_path` (canonical Step iteration over `plan.steps: Vec<StreamingStep>` — flattened lossy projection). `Err(LegacyOrchestrationRequired { .. })` OR unknown backend → `run_streaming_legacy_path` synchronous burst. | Hot path becomes UNIFIED: for every flow, walk the FULL IR tree via `dispatch_node` per IRFlowNode → emit `FlowExecutionEvent`s on the mpsc channel → SSE handler forwards to the wire. The `StreamingExecutionPlan` data structure is retired (or kept only for an opt-in legacy compatibility flag, deprecated immediately). `run_streaming_async_path` is replaced by a single async producer that creates a `DispatchCtx`, walks the IR's body in order, and `await`s `dispatch_node` for each top-level node. |
| [axon-rs/src/axon_server.rs `run_streaming_async_path`](../axon-rs/src/axon_server.rs) `Vec<StreamingStep>` iteration | Linear per-step loop; constructs `ChatRequest` per step; emits `StepStart` / `StepToken` / `StepComplete` directly | Replaced by `dispatch_flow_through_dispatcher` — invokes `dispatch_node(top_level_node, &mut ctx).await` for each IR node; the dispatcher's per-variant handlers emit FlowExecutionEvents on `ctx.tx`; the production consumer in `execute_sse_handler` forwards each event variant to the wire. |
| [axon-rs/src/axon_server.rs `run_streaming_legacy_path`](../axon-rs/src/axon_server.rs) `#[deprecated]` | Synchronous burst path — calls `server_execute_full` then chunks materialized output into 3-word groups | DELETED. Compiler error if anything still calls it. The 33.z.e sub-fase verifies no in-tree caller remains + then removes the function. |
| [axon-rs/src/flow_plan.rs `PlanError::LegacyOrchestrationRequired`](../axon-rs/src/flow_plan.rs) `#[deprecated]` | Returned when a flow's IR has a variant the streaming planner doesn't model | DELETED (variant removed from enum; compiler errors on any remaining pattern match against it). |
| [axon-rs/src/flow_plan.rs `unsupported_feature_reason`](../axon-rs/src/flow_plan.rs) `#[deprecated]` | Walks the IR tree + reports the first variant in the closed-deferred-catalog | DELETED. |
| [axon-rs/src/runtime_warnings.rs `FallbackMode::UnsupportedFlowShape`](../axon-rs/src/runtime_warnings.rs) | One of 4 `axon-W002` warning trigger variants | DELETED. After 33.z, the warning surface is structurally unreachable for "unsupported flow shape" — every shape is supported. The 3 remaining `FallbackMode` variants (`UnknownBackend`, `SourceCompilationFailed`, `BackendLacksStream`) stay. |
| [axon-rs/src/axon_server.rs `ChatRequest.tools`](../axon-rs/src/axon_server.rs) | Hardcoded `Vec::new()` in `run_streaming_async_path` | Plumbed from the dispatcher's `pure_shape::run_step` per Fase 33.y.k's `synthesize_tools_from_step` (D8). Backend's tool-calling state machine fires upstream; `FlowExecutionEvent::ToolCall` emissions land on the production SSE wire as `axon.tool_call` events (the consumer match arm `=> {}` that v1.26.0 silently consumed in 33.y.k is GRADUATED to emit). |
| Cross-stack — Python `axon.runtime.streaming` | Same `unsupported_feature_reason` fallback path mirrored | Python side graduates in lockstep — `axon.flow_dispatcher` module gains a Python-facing dispatcher with the same 45-variant exhaustive match (cross-stack drift gate enforces 1-to-1 against the Rust side). |
| 50-flow sync↔async parity corpus | Does not exist | Ships in 33.z.d. 10 banking + 10 government + 10 legal + 10 medicine + 10 cross-vertical canonical flows, each exercising ≥3 IRFlowNode variants. For each flow, the sync runner output (`crate::runner::execute_full`) and the async dispatcher output are asserted byte-equal on `ServerExecutionResult.step_results[i]`. Drift gate runs in CI on every PR. |

---

## ▶ 3. D-letters proposed (D1–D11) — pending founder bloque ratification

- **D1 — Single hot path through the dispatcher.** `server_execute_streaming` invokes `flow_dispatcher::dispatch_node` for every IRFlowNode variant. No fast path for canonical Step. No fallback for non-canonical shapes. Compiler-enforced via the deletion of the legacy fork (the `match plan_attempt { Ok(plan) if backend_known => async; _ => legacy }` block is replaced by a single branch).

- **D2 — `axon-W002 UnsupportedFlowShape` becomes structurally unreachable.** The `FallbackMode::UnsupportedFlowShape` enum variant is deleted from `runtime_warnings.rs`. Any code still pattern-matching against it fails to compile. The warning catalog drops from 4 variants to 3.

- **D3 — Cancel propagation through orchestration depth.** Cancel fired during `Par { branchA, branchB, branchC }` (3 concurrent dispatcher invocations sharing the same `CancellationFlag` via `DispatchCtx::clone`) aborts all 3 substreams within p95 ≤100ms wall-clock (33.x.e budget preserved across depth ≥3 nesting). Same `CancellationFlag` instance threads through every per-variant handler via the cloned `DispatchCtx`. Measured invariant under load: random pre-cancel × random orchestration depth × 100 iters in 33.z.g fuzz.

- **D4 — Wire byte-compat preserved during the migration.** Canonical `step S { ask: "..." output: Stream<Token> }` + stub backend OR real backend emits BYTE-IDENTICAL wire body before/after 33.z. Adopters running on canonical shapes observe zero behavioral change. NEW wire shapes are observable ONLY for the 41 currently-falling-back IRFlowNode variants — adopters who don't use those shapes see nothing different.

- **D5 — `axon.tool_call` SSE event family graduates from silent consume to wire emission.** The production SSE consumer in `axon_server.rs::execute_sse_handler` graduates the `FlowExecutionEvent::ToolCall { .. } => {}` arm (33.y.k baseline) to actively emit an `axon.tool_call` SSE event with `data: {"step_name": "...", "tool_name": "...", "content": "...", "timestamp_ms": N}`. Cross-stack parity (Rust + Python adopter clients consume the same wire shape).

- **D6 — Per-step audit covers branched paths.** `StepAuditRecord` carries the new `branch_path: String` field (from `DispatchCtx::branch_path_string()`) — e.g., `"par[0].step[2]"`, `"conditional.then.step[1]"`, `"for_in[3].body[0]"`. Regulated-vertical replay (`/v1/replay/<trace_id>`) returns the full branched execution tree, not just a flat sequence. SHA-256 `output_hash_hex` per branched step independently. This is the audit shape the `MIGRATION_v1.27.md` Scenario B will document.

- **D7 — 50-flow sync↔async parity corpus.** New `axon-rs/tests/fixtures/fase33z_parity_corpus/` contains 50 canonical `.axon` source files (10 per vertical × 5 verticals). For each: drive through `crate::runner::execute_full` (sync) AND through the dispatcher (async via mpsc collected → flattened to `step_results`); assert byte-equal on `ServerExecutionResult.step_results[i].output` + step count + flow_success. Drift gate runs on every PR.

- **D8 — Legacy routing primitives DELETED.** `PlanError::LegacyOrchestrationRequired` variant + `flow_plan::unsupported_feature_reason` fn + `axon_server::run_streaming_legacy_path` fn all removed from the source tree in 33.z.e. The `#[deprecated(since = "1.26.0")]` notes carried the v1.26.0 → v1.27.x migration; v1.27.x deletes. Downstream crates that ignored deprecation warnings hit compile errors at upgrade — failure shape is "explicit retirement", not silent breakage.

- **D9 — Algebraic-semantics parity gate (D10 from 33.y promoted).** For every IRFlowNode variant in the 50-flow corpus, the dispatcher and sync runner produce byte-identical `step_results`. This is the operational definition of "semantic parity preserved through the migration". The drift gate is the CI lane.

- **D10 — Cross-stack contract (Python ↔ Rust dispatcher).** Python side ships `axon.flow_dispatcher.dispatch_node` with the same 45-variant exhaustive match. Cross-stack drift gate (mirroring 33.y.b's `flow_plan::ir_flow_node_kind` 1-to-1 anchor) asserts the Python and Rust dispatchers cover the same 45 slugs + produce semantically equivalent outcomes.

- **D11 — Production-grade D12 fuzz.** ~3 000+ deterministic LCG iters across: production hot path totality (drive every IRFlowNode variant through `server_execute_streaming` in random order × 100 iters = 4 500); cancel-through-orchestration-depth (random pre-cancel × random nesting depth × 100 iters = 100); tool-call SSE emission (random apply_ref + random FinishReason::ToolUse positioning × 250 iters = 250); sync↔async byte-equal on the 50-flow corpus (50 × 5 iters/flow = 250). Hand-rolled LCG (Knuth/MMIX, no external dep), 33.x precedent.

---

## ▶ 4. Sub-fase shape — sequenced execution

Topologically sequenced. 33.z.a (spec + diagnostic anchor) is the foundation. 33.z.b (graft skeleton) lifts the dispatcher invocation into the production hot path behind a feature flag. 33.z.c (streaming via dispatcher) flips the flag on by default. 33.z.d (parity corpus) is the regression-gating contract. 33.z.e (legacy retirement) deletes the deprecated primitives. 33.z.f–h close cross-stack drift + fuzz + CI. 33.z.i ships adopter docs. 33.z.j is the release.

| Sub-phase | Scope | LOC target | Status | Description |
|---|---|---|---|---|
| **33.z.a** | spec + diagnostic anchor | ~830 (plan vivo + 800 LOC test file) | ✅ SHIPPED 2026-05-13 | This plan vivo + new `axon-rs/tests/fase33z_dispatcher_production_diagnostic.rs` (~800 LOC, **10 tests verde in 0.05s**): 1 canonical-Step regression pin (must stay green throughout 33.z — D4 byte-compat preserved) + 8 architectural-group anchor shapes (Conditional / ForIn / Par / Remember / ShieldApply / Emit / Hibernate / LambdaDataApply) driven through `server_execute_streaming` end-to-end via `axum::Router::oneshot` against the in-tree `stub` backend + 1 catalog totality pin asserting the 45-variant `IRFlowNode` × `flow_plan::ir_flow_node_kind` slug-list 1-to-1 correspondence (mirrors the 33.y.b drift gate so a regression in the production-diagnostic surface AND the structural drift gate fail in lockstep). **Empirical baseline captured (post-v1.26.0):** Par + Conditional → HTTP 200 with 1 `axon.token` + **`axon-W002 unsupported_flow_shape`** warning fired on `axon.complete.warnings[*]` (the predicted legacy fallback). **ForIn, Remember, ShieldApply, Emit, Hibernate, LambdaDataApply → HTTP 404** — these 6 shapes don't even register a dynamic route in v1.26.0 (deeper gap than the original plan predicted: not just legacy fallback in the streaming dispatcher, but no deploy-time IR support either). This forensic capture is the inversion baseline: post-33.z.b graft skeleton accepts all 8 shapes end-to-end via `dispatch_node`; post-33.z.c default-on flip flips the assertions to "no W002 + per-chunk wire". Each subsequent sub-fase INVERTS the relevant anchor in lockstep. Capture discipline matches 33.y.a (eprintln baseline + non-asserting `if dep != OK { return }` guard so the anchor remains forensic — never blocks the build, always records observed pre-state for the inversion). Architectural-group representative coverage: 1 orchestration (Conditional/ForIn already covered partially by 33.y.a's Let-binding anchor; this extends to the explicit control-flow constructs) + 1 parallel (Par) + 1 cognitive (Remember) + 1 algebraic-handler (ShieldApply) + 1 wire-integration (Emit) + 1 PIX (Hibernate) + 1 lambda+tools (LambdaDataApply). All 8 anchor representatives are the non-canonical shapes that real regulated-vertical adopters depend on (HIPAA clinical reasoning uses ShieldApply + Reason; legal privilege scanner uses ShieldApply + Conditional; banking AML uses ForIn + Par; government decision support uses Hibernate + Trail). The 33.z cycle's promise is that these shapes graduate from legacy synthetic-burst (or HTTP 404) to per-chunk live SSE wire end-to-end. |
| **33.z.b** | graft skeleton — feature-flagged dispatcher invocation | ~1100 (700 surface deltas + 400 integration tests) | ⏳ pending bloque | New runtime flag `AXON_STREAMING_VIA_DISPATCHER` (env var + `axon::runtime_flags::set_streaming_via_dispatcher(bool)`). When ON, `server_execute_streaming` constructs a `DispatchCtx` + walks `flow.body` via `dispatch_node` for each node; when OFF (default v1.27.0-alpha), falls back to the v1.26.0 path. Both paths emit FlowExecutionEvents on the same `mpsc::UnboundedSender` so the SSE consumer is path-agnostic. New module `axon-rs/src/streaming_via_dispatcher.rs` ships the producer. **18 integration tests**: 8 anchor shapes (from 33.z.a) flipped to assert per-chunk wire when flag ON + 8 same shapes with flag OFF asserting v1.26.0 baseline preserved (D4 safety net) + 2 cancel propagation tests (pre-cancel × deep nesting). Feature-flagged gating mirrors the 33.x.h opt-in BPE chunking pattern — proven discipline for landing a new hot path without breaking adopters. |
| **33.z.c** | streaming via dispatcher (flag flips default ON) + tool-call SSE graduation | ~900 (300 surface deltas + 600 tests) | ⏳ pending bloque | `AXON_STREAMING_VIA_DISPATCHER` defaults flip from OFF to ON. Production SSE consumer's `FlowExecutionEvent::ToolCall { .. } => {}` arm in [axon_server.rs](../axon-rs/src/axon_server.rs) graduates to active emission: `axum::response::sse::Event::default().event("axon.tool_call").data(serde_json::to_string(&payload)?)` — closed-catalog wire event family (D5). **25 integration tests**: 8 anchor shapes assert per-chunk wire is default behavior (no flag set) + 4 axon.tool_call SSE wire emission tests (canonical Step + apply: anthropic_tool → upstream FinishReason::ToolUse → wire emits `event: axon.tool_call` interleaved with `axon.token`) + 4 cross-stack Python tests (Python adopter client receives identical wire bytes for the same flow + adopter) + 9 vertical canonical pattern tests (banking real-time decision audit, healthcare CDS reasoning trail, legal privilege scanner stream, fintech AML investigative — each exercising 3+ IRFlowNode variants with the dispatcher activated). |
| **33.z.d** | 50-flow sync↔async parity corpus + drift gate (D7 + D9) | ~2200 (1000 corpus + 1200 drift gate harness + tests) | ⏳ pending bloque | New `axon-rs/tests/fixtures/fase33z_parity_corpus/` directory with 50 canonical `.axon` source files: 10 banking (loan decision with `Conditional`, AML scoring with `ForIn`, transaction reasoning with `Par`, identity verification with `Remember`+`Recall`, etc.) + 10 government (benefit eligibility with `Conditional`, eligibility audit with `ForIn`, multi-agency consensus with `Consensus`, hearing prep with `Deliberate`, etc.) + 10 legal (privilege assessment with `ShieldApply`, discovery scope with `ForIn`+`ShieldApply`, doctrine analysis with `Reason`+`Validate`, etc.) + 10 medicine (clinical reasoning with `Reason`+`Validate`+`Weave`, CDS recommendation with `Par`+`ShieldApply`, drug-interaction check with `ForIn`+`ShieldApply`, etc.) + 10 cross-vertical (PII scan with `ShieldApply`, audit trail with `Trail`+`Drill`, multi-tenant routing with `Conditional`+`MandateApply`, etc.). New `axon-rs/tests/fase33z_d_parity_corpus.rs` drift gate harness: for each `.axon` file × each canonical adopter input, drive through `crate::runner::execute_full` (sync) AND `flow_dispatcher::dispatch_flow` (async via mpsc → collected `ServerExecutionResult`); assert byte-equal `step_results[i].output` + step count + `flow_success` + audit row count. Drift gate ships as a dedicated CI lane in the 33.y workflow extended (33.z.h). |
| **33.z.e** | legacy retirement — DELETE `PlanError::LegacyOrchestrationRequired` + `unsupported_feature_reason` + `run_streaming_legacy_path` + `FallbackMode::UnsupportedFlowShape` | ~600 (450 source deletions + 150 test updates) | ⏳ pending bloque | Grep `axon-rs/src` for any non-comment reference to these 4 symbols; expect zero remaining callers (the 33.z.b/c graft eliminated them); delete the symbols from source. Compiler error on any downstream crate still referencing them is the EXPLICIT failure shape that completes the deprecation cycle started in 33.y.l. The `#![allow(deprecated)]` module-level annotations in `axon-rs/tests/fase33x_fuzz.rs` + `axon-rs/tests/fase33x_g_warning_catalog.rs` (added in 33.y.l) are removed in lockstep. Test count drops by ~6 tests (the 33.x.g specific axon-W002 UnsupportedFlowShape variant tests, replaced by 1 structural-unreachability assertion in the new D2 anchor). |
| **33.z.f** | cross-stack drift gate Python ↔ Rust dispatcher | ~700 (400 Python parity surface + 300 drift gate) | ⏳ pending bloque | Python ships `axon.flow_dispatcher` module with same 45-variant exhaustive dispatch (Python's existing IR catalog already mirrors Rust's 45-name slug list per Fase 18 drift gate). New `tests/test_fase33z_python_dispatcher_parity.py`: drive 8 representative IR shapes through Python's dispatcher + Rust's dispatcher via FFI subprocess; assert byte-equal `step_results` output. Cross-stack contract anchored on `AXON_STRICT_TYPE_DRIVEN_TRANSPORT` env var name (per Fase 31 D7 precedent). |
| **33.z.g** | D12 production-grade fuzz | ~900 (650 fuzz file + 250 misc) | ⏳ pending bloque | New `axon-rs/tests/fase33z_production_fuzz.rs` (~650 LOC, ~5 100 LCG iters): production hot path totality (45 variants × 100 iters = 4 500 driving `server_execute_streaming` end-to-end against a local axum mock + assert no panic + canonical wire shape) + cancel-through-orchestration-depth (random nesting depth 1-5 × random pre-cancel timing × 100 iters = 100 — asserts p95 ≤100ms across depth) + tool-call SSE emission (random apply_ref + random FinishReason::ToolUse positioning × 250 iters = 250 — asserts `axon.tool_call` events interleave correctly) + sync↔async parity stress (50-flow corpus × 5 iters = 250 — asserts byte-equal under randomized adopter input). Total: ~5 100 deterministic LCG iters. Hand-rolled LCG (Knuth/MMIX, no external dep). |
| **33.z.h** | dedicated CI workflow extension | ~250 LOC | ⏳ pending bloque | `.github/workflows/fase_33y_dispatcher.yml` (from 33.y.n) extended with new jobs: `33.z.b dispatcher graft skeleton` / `33.z.c default-on flip` / `33.z.d 50-flow parity corpus` / `33.z.e legacy retirement grep gate` / `33.z.f cross-stack drift` / `33.z.g production-fuzz`. New aggregator `33z-cycle-summary` depending on every 33.z lane + the existing 33.y lanes — single-source-of-truth CI status for the combined cycle's contract. |
| **33.z.i** | adopter docs | ~800 LOC | ⏳ pending bloque | New `docs/MIGRATION_v1.27.md` (~500 LOC) with 5 scenario recipes: (A) server-only upgrade — adopter shapes that fell back in v1.26.0 now per-chunk-stream by default; (B) `axon.tool_call` SSE event family wire-emission for tool-using flows; (C) per-step audit branch_path for regulated-vertical replay; (D) deletion of `PlanError::LegacyOrchestrationRequired` migration path; (E) opt-out feature flag for shape-by-shape rollback during deployment hardening. `docs/ADOPTER_STREAMING.md` extension (~300 LOC) with new §"Total production streaming (Fase 33.z, v1.27.0+)" mapping D1–D11 to adopter-observable behavior. |
| **33.z.j** | release v1.27.0 cross-stack + axon-enterprise v1.18.0 catch-up | release | ⏳ pending bloque | axon-lang v1.26.0 → v1.27.0 cross-stack: bump-my-version minor across 6 files. axon-frontend stays 0.11.1 (no AST changes — production-side wiring is runtime layer only). axon-enterprise v1.18.0 lean catch-up + vertical-inheritance notes (HIPAA + Legal + Fintech + Government vertical ensembles immediately observe per-chunk granularity across every orchestration shape they actually use in production audit flows). PyPI + crates.io + GitHub Release with content-first notes. |

**Total target: ~7 750 LOC + ~120 new tests + ~5 100 fuzz iters + dedicated CI extension.**

---

## ▶ 5. Vertical-grounded relevance

The four high-profile regulated verticals (Banking PCI DSS Req 10 / Government FedRAMP AU-2 / Legal FRE 502 / Medicine HIPAA + 21 CFR Part 11 §11.10) — already canonical anchors in 33.y — now observe **per-chunk granularity on EVERY orchestration shape they actually deploy**, not just canonical Step:

- **Banking** — `POST /loan/decision` with `flow LoanDecision { step Identity { apply: kyc_scanner } step Credit { apply: bureau_lookup } step Adjudicate { ask: "..." } }` where `kyc_scanner` and `bureau_lookup` declare `<stream:fail>` effects:
  - **v1.26.0**: legacy fallback — full flow materialized → 3-word chunks emitted at end → adopter sees a 2-3 second pause then a burst.
  - **v1.27.0 (33.z)**: each step's `apply: <stream-tool>` produces per-chunk wire events as the tool emits them; the adjudication LLM call streams its reasoning chunks live; per-chunk replay audit captures `branch_path: "step[0].apply.kyc_scanner"` so PCI DSS Req 10 hash-chain verification works on the actual data flow.

- **Government** — `POST /benefits/eligibility` with `flow BenefitsAdjudication { for case_type in eligibility_paths { step Determine { ask: "..." apply: rules_engine } } }`:
  - **v1.26.0**: ForIn fails the streaming planner → legacy synthetic burst.
  - **v1.27.0 (33.z)**: each iteration's step emits chunks live; per-iteration audit row carries `branch_path: "for_in[3].body[0]"`; FedRAMP AU-2 per-step retention works on the actual branched trail.

- **Legal** — `POST /discovery/privilege-assessment` with `flow Privilege { par { step Doctrine { ask: "..." apply: privilege_scanner } step Workproduct { ask: "..." apply: workproduct_scanner } } step Reconcile { ... } }`:
  - **v1.26.0**: Par fails the planner → legacy burst.
  - **v1.27.0 (33.z)**: both branches' tool chunks interleave on the wire ordered by wall-clock arrival; the reconcile step streams its synthesis live; FRE 502 waiver-doctrine evidence trail captures both concurrent branches with full audit rows.

- **Medicine** — `POST /cds/recommendation` with `flow CDS { step Vitals { ask: "..." } step Differential { ask: "..." apply: clinical_reasoning } step ShieldedPHI { apply: hipaa_shield } step Recommend { ask: "..." } }` where `clinical_reasoning` declares `<stream:drop_oldest>` and `hipaa_shield` is an `IRFlowNode::ShieldApply`:
  - **v1.26.0**: ShieldApply fails the planner → legacy burst → 21 CFR Part 11 §11.10 audit captures a SINGLE post-hoc materialization, not the actual reasoning trail.
  - **v1.27.0 (33.z)**: each step streams live; the clinical reasoning chunks emerge as they're produced (the actual differential-diagnosis chain becomes observable on the wire); ShieldApply runs per-chunk PHI scrubbing; the full audit trail captures every step's branched path.

After 33.z, **every regulated-vertical adopter using ANY orchestration construct gets the same per-chunk wire behavior the paper's algebraic-effects primitive promises**, with full audit + replay + cancel discipline preserved.

---

## ▶ 6. What 33.z explicitly DOES NOT address

The 4 deferred items below are NOT in scope for 33.z. They are tracked as future cycles.

| Followup | Scope | Why deferred |
|---|---|---|
| **Fase 34** (axon-lang v1.28.x) — Tools as stream-producers | The `Tool` trait extension: tools today are "function call" semantics `(args) → String`. The paper's `effects: <stream:<policy>>` on a tool postulates "stream-producer" semantics `(args) → Stream<ToolChunk>`. Until tools can actually produce streams, the dispatcher's `apply: <stream-tool>` arm has nothing to stream — it invokes the existing synchronous `invoke_tool` and emits a single chunk. | 33.z lifts the structural totality of 33.y into production but inherits the existing tool-invocation semantics. Fase 34 is the architectural extension that makes the 4 disjunctions of `produces_stream(F)` (output-Stream-type / apply-stream-tool / use_tool-stream-tool / perform-Stream.Yield) converge on the same chunk-level wire behavior. 33.z is prerequisite to 34 because 34's dispatcher arm graduation requires the dispatcher to be wired into production first. |
| Per-token cryptographic chain signature | Each `axon.token` event independently signed + hash-chained for byte-exact replay-as-original | Out of scope. Per-step audit (D6 from 33.x.f) satisfies regulated-vertical retention. Per-token chain is Fase 35+. |
| Mid-stream tool-call **execution** | Tool result interleaving + execution resumption mid-stream | Out of scope. v1.27.0 emits `axon.tool_call` event when upstream signals ToolUse, but the tool result interleaving back into the same stream is its own cycle. |
| gRPC streaming binding | gRPC server-side streaming as alternative to SSE | Out of scope. Fase 30 D2 explicitly out-of-scope. |

---

## ▶ 7. Honest scope statement (carried forward to adopter docs)

**What v1.27.0 (33.z) ships**: the structural totality of 33.y graduated into the production hot path. Every of the 45 IRFlowNode variants dispatches through the same async pipeline on the SSE wire. The legacy synchronous fallback is DELETED.

**What v1.27.0 does NOT ship**: tools as actual stream producers. A tool with `effects: <stream:drop_oldest>` declaration still has its body invoked synchronously by the existing `invoke_tool` helper; the OSS reference impl returns a single materialized chunk. **The wire goes through the dispatcher (D1 D2 honored) but the tool itself doesn't yet stream.** Fase 34 closes that final layer.

**This is the honest staged delivery the paper's promise requires.** 33.z without 34 is necessary but not sufficient: the dispatcher being total means adopters STOP seeing the legacy burst path, but their `apply: <stream-tool>` still emits one chunk per step (not one chunk per tool-internal-step). Fase 34 graduates that to per-tool-internal-chunk.

After **both** 33.z + 34 land, the adopter shape

```axon
tool clinical_reasoning {
  effects: <stream:drop_oldest>
}

axonendpoint CDS {
  method: POST
  path: "/cds/recommendation"
  execute: CDSAssessment
}

flow CDSAssessment() {
  step Differential { ask: "..." apply: clinical_reasoning }
}
```

emits **token-by-token from inside the clinical_reasoning tool's own LLM call** on `Content-Type: text/event-stream` over POST, with drop_oldest backpressure honored, cancel propagated, per-step branch_path audit captured. That is the paper's promise, redeemed end-to-end.

---

*This document is the internal Fase 33.z plan vivo. It will be flipped to ✅ status sub-fase by sub-fase per the established discipline (33.y.a–o, 33.x.a–m, 33.a–i precedents). Adopter-facing docs ship in 33.z.i as `docs/MIGRATION_v1.27.md` + `docs/ADOPTER_STREAMING.md` extension.*
