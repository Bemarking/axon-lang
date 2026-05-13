---
title: "Plan vivo: Fase 33.y — Algebraic Streaming Dispatcher (per-IRFlowNode total async coverage)"
status: ⏳ 33.y IN PROGRESS — 33.y.a/b/c/d SHIPPED 2026-05-13. **12 of 45 IRFlowNode variants graduated** to real async handlers — pure-shape (6: Step/Probe/Reason/Validate/Refine/Weave) + orchestration (6: Let/Conditional/ForIn/Break/Continue/Return). 1659 axon-rs lib tests verdes + 27 + 25 integration + 11 + 9 fuzz (~3000 LCG iters total) + zero regressions across 33.x suites. **Founder bloque ratification of D1-D12 received 2026-05-13**: "Ratificadas todas las D-letters. Procede con 33.y.a". 33.y.e–o continue per established cadence.
owner: AXON Runtime + Backends Team
created: 2026-05-13
target: axon-lang v1.26.0 (minor — streaming semantics extend from canonical-Step-only to TOTAL coverage over the 45-variant `IRFlowNode` catalog; wire format byte-compat preserved for legacy adopter shapes during the migration; new per-step `wire_status` field on `axon.step_start` events; the `axon-W002` warning catalog gains 1 new variant `axon-W003 partial-streaming-activation`; adopter source unchanged)
depends_on: Fase 33.x SHIPPED v1.25.0 (per-step async `Backend::stream()` activation for canonical `Step` shape + cancel-in-body p95 12.6µs + per-step replay binding + `axon-W002` closed-catalog warning + opt-in tokenizer fallback + mono-file Phase-1 consolidation + D12 fuzz pack); Fase 23 SHIPPED (algebraic effects runtime — delimited continuations + `perform Stream.Yield` handler stack + 4-policy `BackpressurePolicy` closed catalog); Fase 24 SHIPPED (`Backend` trait + 7 native backends); Fase 11 partial (cognitive primitives at the IR level — Remember/Recall/Forge/Focus/etc. — sync runner only today)
charter_class: OSS — every adopter benefits transitively. axon-enterprise inherits via the v1.17.0 catch-up (33.y.o), with verticals (HIPAA/Legal/Fintech/Government) getting per-chunk granularity across orchestration constructs (Par/ForIn/Conditional/Reason/Validate/Refine/Weave) that real regulated-domain flows depend on.
pillars: |
  MATHEMATICS — `perform Stream.Yield x` on the streaming path emits `axon.token` directly via the algebraic-effect handler stack (Fase 23), with no detour through materialization. The dispatcher is total over the 45-variant closed `IRFlowNode` catalog; the match is compiler-enforced exhaustive. Adding a new variant requires updating the dispatcher (the type system catches the gap).

  LOGIC — Declared algebraic effects (`<stream:<policy>>`) compose at the chunk level, not the step level: a `Par { branchA, branchB }` block where only `branchA` declares the effect activates the enforcer on `branchA`'s chunk stream while `branchB` runs without enforcement — both branches stream concurrently to the same `axon.token` channel ordered by wall-clock arrival. Declaration ⟺ runtime contract, end-to-end, across orchestration shapes.

  PHILOSOPHY — The four-pillar contract is fully redeemed: every algebraic-effect declaration in `.axon` source has an observable, byte-deterministic runtime behavior on the SSE wire, regardless of the surrounding orchestration shape. Tools become first-class on the streaming path (the step's declared `apply: TOOL` plumbs into `ChatRequest.tools` so backends' tool-calling state machines actually fire). The async dispatcher and the sync runner produce byte-identical FLOW OUTPUT for the same input — only wire TIMING differs (parity gate enforces this).

  COMPUTING — Cancel-in-body propagation extends across orchestration: a cancel fired during a `Par` block aborts ALL concurrent substreams within p95 ≤100ms; a cancel fired during a `ForIn` loop terminates the current iteration's upstream HTTP request + skips remaining iterations. Bounded buffers + atomic counters + per-branch cooperative cancellation. Adversarial fuzz coverage spans handler totality + orchestration composition + cancellation propagation + algebraic-effects-semantics parity (~3000+ deterministic LCG iters).
---

> **Founder principle (Fase 33.y trigger, 2026-05-13):**
>
> *"vamos a trabajar en que los algebraics effects sean una expresión matemática hecha conversación con los LLM's, nada más, vamos a hacer que cualquiera de ahora en adelante integre la primitiva cognitiva y funcione brutalmente perfecta."*
>
> The Fase 33.y mandate is NOT another single-adopter fix; it is the structural closure of the algebraic-streaming contract. After 33.y, any future adopter — regardless of flow shape, regardless of orchestration constructs used, regardless of which cognitive primitives they invoke — observes the declared `<stream:<policy>>` algebraic effect honored end-to-end on the production SSE wire.

---

## ▶ 1. Recap — what 33.x activated, what gap remains

### 33.x.b–l (v1.25.0) activated the canonical-`Step` shape on the async path

For flows of the form:

```
flow F {
  output: Stream<T>
  step S { ask: "..." effects: <stream:drop_oldest> }
}
```

…the production SSE wire delivers `axon.token` events at network granularity from the real upstream LLM (Anthropic/OpenAI/Gemini/Kimi/GLM/Ollama/OpenRouter), with `StreamPolicyEnforcer` activated, cancel-in-body p95 = 12.6µs, per-step replay binding, axon-W002 closed-catalog warning surface, opt-in tokenizer fallback, and ~2050 fuzz iters across 11 surfaces.

### The gap surfaced by adopter feedback 2026-05-13

> *"el cable HTTP → SSE en axonendpoint POST con effect-set sigue pendiente."*

Real adopter flows contain `Let` bindings, `Conditional`/`ForIn`/`Par` orchestration, cognitive primitives (`Remember`/`Recall`/`Forge`/`Focus`/`Reason`/`Validate`/`Refine`/`Weave`), algebraic-effect handlers (`ShieldApply`/`OtsApply`/`MandateApply`/`ComputeApply`), PIX (`Hibernate`/`Drill`/`Trail`), and π-calc primitives (`Emit`/`Publish`/`Discover`). **NONE of these activate the async path today.** The plan extractor `flow_plan::unsupported_feature_reason` ([axon-rs/src/flow_plan.rs:501](../axon-rs/src/flow_plan.rs#L501)) default-denies every `IRFlowNode` variant except `Step(_)`. Any other variant causes the flow to fall back to `run_streaming_legacy_path` which calls `server_execute_full` synchronously, materializes the FULL flow output, and then chunks the materialized output into 3-word groups emitted post-hoc as `axon.token` events. **Indistinguishable from v1.24.0 to the adopter's eye** (modulo the `axon-W002` warning which arrives at `axon.complete` time — i.e., AFTER the latency was already paid).

### Three additional gaps within the async path itself

1. **Tools are silently dropped.** [axon-rs/src/axon_server.rs:18563](../axon-rs/src/axon_server.rs#L18563) hardcodes `tools: Vec::new()` in the `ChatRequest` constructed for `Backend::stream()`. If the step declares `apply: anthropic_tool`, the upstream call is a plain chat-completion — the tool-calling state machine never fires. The wire shows `axon.token` events from a NAKED chat, not from the tool-using chain the adopter declared.

2. **History-only context, no PEM/ReplayToken/CognitiveState plumbing.** [axon-rs/src/axon_server.rs:18520](../axon-rs/src/axon_server.rs#L18520) accumulates `Message::assistant` turns between steps but no plumbing of PEM (Fase 11 cognitive state), no ReplayToken hydration, no per-tenant capability scope, no daemon hooks, no observability spans. Fase 11 neuro-symbolic primitives are inert on the streaming path.

3. **The `IRFlowNode::Stream` variant itself (the algebraic primitive `perform Stream.Yield x`) falls back to legacy.** The structural-streaming primitive is materialize-then-chunk on the streaming path — the most semantically egregious case.

### Honest scope statement of the published `MIGRATION_v1.25.md` understates this gap

The 5 deferred items published in `MIGRATION_v1.25.md` §"What's deferred" are: (1) 33.x.i.2 sync→async caller migration; (2) Fase 34 per-event token-chain signature; (3) mid-stream tool calling; (4) gRPC; (5) WebSocket. **None of them name the closed-catalog scope limitation on `unsupported_feature_reason`.** Fase 33.y is the cycle that names + closes this gap.

---

## ▶ 2. Concrete code-level gap

| Location | Today (v1.25.0) | 33.y target |
|---|---|---|
| [axon-rs/src/flow_plan.rs:501](../axon-rs/src/flow_plan.rs#L501) `unsupported_feature_reason` | Returns `Some(PlanFallback::*)` for 44 of 45 `IRFlowNode` variants; only `Step(_)` proceeds | Function deleted. Replaced by per-variant async handlers in a closed-catalog `dispatcher` module. Drift gate asserts dispatcher coverage matches the IRFlowNode catalog (compiler-enforced exhaustive match). |
| [axon-rs/src/axon_server.rs:18563](../axon-rs/src/axon_server.rs#L18563) `ChatRequest.tools = Vec::new()` | Step's declared `apply: TOOL` silently dropped on streaming path | Plumb the step's tool registry into `ChatRequest.tools` per Fase 24 trait contract. (D8) |
| [axon-rs/src/axon_server.rs:18451-18886](../axon-rs/src/axon_server.rs#L18451) `run_streaming_async_path` | Iterates `plan.steps` (which is `Vec<StreamingStep>` — flattened, lossy projection of IR) | Walks the full `IRFlowNode` tree via the new dispatcher, preserving orchestration shape; each variant has its own async handler that may invoke `Backend::stream()` directly, or compose child handlers (Par/Conditional/ForIn), or run an algebraic-effect handler (perform Stream.Yield → axon.token). |
| [axon-rs/src/flow_plan.rs:1-200](../axon-rs/src/flow_plan.rs#L1) `StreamingExecutionPlan` + `StreamingStep` | Flat `Vec<StreamingStep>` — sufficient for canonical Step shape, lossy for orchestration | Replaced by `StreamingDispatchPlan { ir: IRProgram, ast: ast::Program, flow_name: String, backend: String }` — full IR tree preserved; per-variant handlers walk it directly. The pre-resolved-per-step `effect_policy` cache becomes per-IRFlowNode-handle. |
| [axon-rs/src/axon_server.rs:19125](../axon-rs/src/axon_server.rs#L19125) `run_streaming_legacy_path` | Materialize-then-chunk for every non-canonical shape | DELETED. The dispatcher is total; there is no legacy fallback. (If a future IR variant ships without a handler, the compiler fails the build.) |
| `axon-rs/tests/fase33y_dispatcher_diagnostic.rs` | Does not exist | Ships in 33.y.a alongside this plan vivo. Captures v1.25.0 baseline for 7 representative non-`Step` flow shapes + 1 catalog totality pin. Each subsequent sub-fase INVERTS the relevant anchor assertion. |

---

## ▶ 3. D-letters proposed (D1–D12) — pending founder bloque ratification

- **D1 — Per-IRFlowNode async dispatch is total over the closed IRFlowNode catalog.** Compiler-enforced exhaustive match in `crate::flow_dispatcher::dispatch_node`. Adding a 46th IR variant fails the build until the dispatcher arm is added + the drift gate updated. Zero `_ =>` catch-all arms. Zero `unimplemented!()` / `todo!()` markers. Zero silent degradation.

- **D2 — Algebraic effects compose at the CHUNK level.** A declared `<stream:<policy>>` on any node activates `StreamPolicyEnforcer` on THAT node's chunk stream. In a `Par { A, B }` block where only `A` declares the effect, `A`'s chunks pass through the enforcer + `B`'s pass through untouched; both interleave on the wire `axon.token` channel ordered by wall-clock arrival. `axon.complete.enforcement_summary` keys by node path (e.g., `"par[0].A"`) so adopters audit per-branch policy state.

- **D3 — Cancel-in-body propagates through orchestration.** Cancel fired during `Par { A, B, C }` aborts all 3 concurrent substreams within p95 ≤100ms (measured under load); cancel during `ForIn` terminates the current iteration's upstream HTTP request + skips remaining iterations (no buffered up-front of LLM calls). Cancel during `Conditional` aborts whichever branch was taken. Same `CancellationFlag` instance threads through every per-variant handler.

- **D4 — Wire byte-compat preserved during the migration.** All new wire fields (per-step `wire_status`, `enforcement_summary` keyed by node path, `step_audit` records covering branched paths) are ELIDED when empty. v1.25.0 adopters who upgrade to v1.26.0 with the SAME flow shape see byte-identical wire. The contract: post-33.y wire shape strictly extends post-33.x wire shape.

- **D5 — `axon-W002` warning catalog upgraded.** The 4 existing `FallbackMode` variants (UnsupportedFlowShape / UnknownBackend / SourceCompilationFailed / BackendLacksStream) are PRUNED — the dispatcher is total so `UnsupportedFlowShape` becomes structurally unreachable. New variant `axon-W003 partial-streaming-activation` surfaces when a flow's structure means some steps stream and others materialize (e.g., a `Let` binding evaluating a non-streaming expression). Each `axon.step_start` event gains a `wire_status: "streaming" | "buffered" | "synthesized"` field that adopters observe in real time.

- **D6 — Per-step replay binding covers branched paths.** `step_audit: Vec<StepAuditRecord>` records carry a new `branch_path: String` field (e.g., `"par[0].A"`, `"for_in[3].body[0]"`, `"conditional.then.step[1]"`) so post-hoc replay reconstructs the actual execution tree, not just a flat sequence. `output_hash_hex` per branched step independently SHA-256ed. Regulators replaying on appeal see the full execution shape.

- **D7 — Production-grade per-variant handler for the full 45-variant IRFlowNode catalog.** Each handler ships with: rustdoc anchoring the algebraic-effect semantics + paper §reference where applicable (Stream / perform handler / π-calc Emit/Publish/Discover / PIX Hibernate/Drill/Trail); adversarial fuzz pack (≥150 LCG iters per handler); vertical canonical pattern (Banking/Government/Legal/Medicine) exercising the handler under a real regulated-domain flow shape; HTTP-level integration test under both stub + real-backend (real-backend gated under `AXON_RUN_REAL_PROVIDER_TEST`).

- **D8 — Tools are first-class on the streaming path.** `ChatRequest.tools` is populated from the step's declared `apply: TOOL` (single-tool form) OR `use_tool: [...]` (multi-tool form per Fase 22). Tool-call chunks from the upstream backend interleave with text chunks on the wire as `axon.tool_call` events (new closed-catalog event variant; D4 byte-compat preserves the absence-of-tool-call paths).

- **D9 — Algebraic-effects runtime (Fase 23) integrates with the streaming dispatcher.** `perform Stream.Yield x` on the streaming path emits `axon.token` directly via the handler stack — no materialization detour. The Fase 23 delimited-continuation machinery is invoked from `IRFlowNode::Stream`'s dispatcher handler. The paper §5 algebraic-effects FSM dispatcher (Fase 25 C23) is the conceptual reference; the Rust dispatcher mirrors its closed-catalog totality.

- **D10 — Algebraic-semantics parity gate between sync runner and async dispatcher.** For every IRFlowNode variant, the dispatcher and `crate::runner` produce BYTE-IDENTICAL `ServerExecutionResult.step_results[i]` for the same `(source, flow_name, backend, input)` — only wire TIMING differs. Drift gate runs both paths on a 50-flow corpus + asserts byte-equal. This is the contract that lets `MIGRATION_v1.26.md` say "no semantic change, only timing".

- **D11 — Cross-stack contract (Python ↔ Rust IR catalog).** The `IRFlowNode` 45-variant catalog mirrors in Python (already pinned by Fase 18 drift gate). 33.y adds a NEW cross-stack drift gate: the dispatcher's handler coverage is asserted against the SAME 45-name catalog the Python runtime knows. A Python adopter that ships an IRProgram with a 46th variant sees a structured `unknown_ir_flow_node_variant` diagnostic; no silent JSON acceptance.

- **D12 — Production-grade fuzz pack.** ~3000+ deterministic LCG iters across: handler totality per variant (45 handlers × 50 iters = 2250) + orchestration composition (Par/Conditional/ForIn nested 3-deep, random shapes, 300 iters) + cancellation propagation (random cancel timing across all handlers, 200 iters) + algebraic-effect-semantics parity (sync↔async byte-equal on a 50-flow corpus, 250 iters) + tool-call interleaving (text/tool_call random interleave, 200 iters). Hand-rolled LCG (Numerical Recipes 64-bit Knuth constants, no external dep) per the 33.x precedent.

---

## ▶ 4. Sub-fase shape — sequenced execution

Topologically sequenced. 33.y.a (spec + diagnostic anchor) is the foundation. 33.y.b (dispatcher skeleton) is the framework that all per-variant sub-fases extend. 33.y.c–i ship per-variant handlers in semantic-coherence groups. 33.y.j-l close cross-cutting concerns (tools / algebraic effects / parity gate). 33.y.m–o close docs + CI + release.

| Sub-phase | Variants covered / scope | LOC target | Status | Description |
|---|---|---|---|---|
| **33.y.a** | spec + diagnostic anchor | ~770 (plan vivo + 1 test file) | ✅ SHIPPED 2026-05-13 | Plan vivo (this document) + `axon-rs/tests/fase33y_dispatcher_diagnostic.rs` (~430 LOC, 6 tests green in 0.03s): D1 canonical-Step regression pin (must stay green throughout 33.y) + 3 non-Step shapes asserting current fallback (Let-binding / Reason-step / tool-using Step) + 2 catalog totality pins (IRFlowNode 45-variant + PlanFallback 7-variant). Each subsequent sub-fase INVERTS the relevant anchor assertion. Bloque ratification received 2026-05-13. |
| **33.y.b** | dispatcher skeleton + closed-catalog match + drift gate | ~1100 (650 module + 580 drift gate) | ✅ SHIPPED 2026-05-13 | New module `axon-rs/src/flow_dispatcher.rs`. Public `async fn dispatch_node(node: &IRFlowNode, ctx: &mut DispatchCtx) -> Result<NodeOutcome, DispatchError>` with exhaustive match over all 45 IRFlowNode variants (compiler-enforced, zero `_ =>` catch-all). Closed-catalog `ShimReason` (45 variants 1-to-1 with IRFlowNode + `ALL` const slice + `slug()` mapping byte-equal with `flow_plan::ir_flow_node_kind`). Closed-catalog `NodeOutcome` (today: 1 transitional `LegacyShimHandled { reason, node_kind }` variant — subsequent sub-fases add `Completed`/`Break`/`LoopContinue`/`Return`). Closed-catalog `DispatchError` 5-variant (BackendError / UpstreamCancelled / LegacyShimFailed / MissingDependency / ChannelClosed) with Display surface. `DispatchCtx` shared async surface: flow_name + backend_name + system_prompt + CancellationFlag + mpsc tx for FlowExecutionEvent + Arc<Mutex<...>> side-channels for enforcement_summaries / step_audit_records / runtime_warnings + `branch_path: Vec<String>` for D6 orchestration tree (wire-stable join via `branch_path_string()`) + `step_counter` monotone. `legacy_shim` checks `cancel.is_cancelled()` first → returns `Err(UpstreamCancelled)`; happy path returns `Ok(LegacyShimHandled { reason, node_kind: reason.slug() })` WITHOUT executing the node. **No production code path calls dispatch_node in 33.y.b** — the module is standalone; the production async path stays on v1.25.0 wire for D4 byte-compat. **Drift gate** `tests/fase33y_b_dispatcher_skeleton.rs` (~580 LOC, 9/9 tests green): 1 cartesian-product 45-variant cardinality test + 1 ShimReason::ALL cardinality test + 1 every-variant-routes-to-its-labeled-ShimReason exhaustive test (constructs 45 synthetic IRFlowNode values via per-variant factories + asserts dispatch returns the labeled ShimReason + the correct slug) + 1 cancel-honored-at-entry-for-every-variant test + 1 wire-stability test (ShimReason::slug() byte-equal with `flow_plan::ir_flow_node_kind` for all 45) + 2 DispatchCtx surface tests (branch_path round-trip + step_counter writable) + 1 DispatchError constructibility test + 1 D7 no-panic-for-any-variant test. **Module-internal tests** (`flow_dispatcher::tests`, 10/10 green): ShimReason cardinality + slug uniqueness + slug well-formedness + legacy_shim happy path + cancel propagation + DispatchCtx construction + branch_path semantics + DispatchError Display + slug-vs-flow_plan parity + dispatch_node Step arm routing. **Test surface 33.y.b total**: 19 new tests (10 lib + 9 integration). **1624 axon-rs lib green** (up from 1614 = +10 module-internal). **ZERO regressions**: 33.x diagnostic anchor 6/6 + 33.y.a anchor 6/6 + all Fase 33.x integration suites (33.x.b/d/e/f/g/h/i/fuzz) verified green. **No MVP, no partial solutions honored**: zero `unimplemented!()`/`todo!()`/`panic!()` markers in dispatcher (D7 invariant compile-time enforced via the catch-free exhaustive match + run-time enforced via the `dispatch_node_does_not_panic_for_any_variant` drift gate test); closed catalogs everywhere (ShimReason 45 / NodeOutcome 1 / DispatchError 5); slug catalog wire-stability byte-equal across 3 surfaces (ShimReason / flow_plan / 33.y.a anchor); cancel propagation honored at dispatch entry. |
| **33.y.c** | pure-shape variants (semantically `step S { ask: "..." }` cognitive framings) | ~2200 (700 pure_shape.rs + 600 integration + 750 fuzz + 150 misc) | ✅ SHIPPED 2026-05-13 | **`Step`, `Probe`, `Reason`, `Validate`, `Refine`, `Weave` — 6 variants — graduated to real async handlers.** Refactored `flow_dispatcher.rs` → `flow_dispatcher/mod.rs` directory module + new submodule `flow_dispatcher/pure_shape.rs` (~700 LOC) with shared async core `run_pure_shape` + 6 thin per-variant entry points (`run_step`, `run_probe`, `run_reason`, `run_validate`, `run_refine`, `run_weave`). Each entry builds a `PureShapeStep` carrier (name + user_prompt + framing_addendum + kind_slug) reflecting the variant's cognitive posture (neutral / investigative / deliberative / verification / improvement / synthesis). Shared core: emits StepStart with variant slug → resolves backend via `resolve_streaming_backend` → builds ChatRequest with composed system prompt (flow-level + framing addendum) + cancel-flag plumbed per Fase 33.x.e → optional `StreamPolicyEnforcer` wrap when `pending_effect_policy.is_some()` (4-policy closed catalog with identity-degrader OSS default for DegradeQuality; producer-side `tokio::spawn(enforcer.drain)` + consumer-side `enforcer.pop_chunk().await`) → forwards each non-empty chunk as `StepToken` event → computes SHA-256 `output_hash_hex` → records `StepAuditRecord` (D6 per-step replay binding) → emits StepComplete → returns `NodeOutcome::Completed { output, tokens_emitted, step_index }`. `NodeOutcome` extended with `Completed` variant (3 fields). `DispatchCtx` extended with `pending_effect_policy: Option<BackpressurePolicy>` + take-semantics helper `take_pending_effect_policy()` (consumed on handler entry; next handler observes None — no policy leak). `dispatch_node` exhaustive match: 6 of 45 arms now delegate to `pure_shape::run_*` instead of `legacy_shim` (compiler-enforced exhaustive — no `_ =>` fallback). `EnforcementSummaryWire` visibility elevated `pub(crate)` → `pub` (now part of the public adopter wire surface). **Test surface 33.y.c**: 76 tests total. (a) 12 pure_shape::tests (lib-internal): sha256_hex empty + canonical stub + run_step happy path (3-event wire shape) + run_step cancel pre-dispatch + run_step unknown backend → BackendError with hint + run_step pending_policy consumed-on-entry + run_step audit row recorded + run_probe/reason/validate/refine/weave step_type slugs verified. (b) 27 integration tests (`fase33y_c_pure_shape_handlers.rs`): 6 per-variant happy-paths × 3-event wire shape + step_type slug + 6 per-variant audit-row canonical shape + 4 BackpressurePolicy × enforcer-activates summaries + 6 per-variant cancel-short-circuits via shared assertion helper + multi-step counter monotone (step_index 0 → 1 across consecutive handlers) + pending-policy take-semantics no-leak (policy consumed by first handler, second sees None) + SHA-256 output_hash determinism (two ctxs produce byte-equal hash) + all-6-variants produce identical stub output `"(stub)"` (D10 semantic parity) + unknown-backend error hint contract. (c) 11 fuzz tests (`fase33y_c_pure_shape_fuzz.rs`, ~1450 deterministic LCG iters in 0.02s): 6 per-handler × 150 iters never-panic on random ASCII input + 100 iters cancel-random-timing across all 6 handlers + 100 iters policy-random-pairings across 4 policies × 6 handlers + 50 iters × 3-step chains step_counter monotone + 200 iters UTF-8 high-codepoint input (ASCII + Latin-Extended + Greek + Cyrillic + CJK + emoji) never-panics + total-iter-count pin (1450). Hand-rolled LCG (Knuth/MMIX constants, no external dep). **33.y.b drift gate updated**: `every_ir_flow_node_routes_to_its_labeled_handler` now matches the bipartite outcome — 6 graduated variants return `Completed { output: "(stub)", tokens_emitted: 1 }`, remaining 39 return `LegacyShimHandled { reason }`. New `GRADUATED_VARIANTS` slice + `graduated_variants_set_size_pinned_for_33_y_c` pin asserts size = 6 today; grows variant-by-variant through 33.y.d-j; reaches 45 at 33.y.l. **1636 axon-rs lib tests verdes** (up from 1624 = +12 module-internal). **ZERO regressions** verified across full Fase 33.x integration suite: 33.x diagnostic anchor 6/6 + 33.y.a anchor 6/6 + 33.y.b drift gate 10/10 + 33.x.b 18 + 33.x.d 11 + 33.x.e 9 + 33.x.f 10 + 33.x.g 9 + 33.x.h 10 + 33.x.i 10 + 33.x.fuzz 15. **D-letter coverage validated end-to-end**: D1 (per-variant dispatch total, 6 of 45 graduated) + D2 (4-policy enforcer activates per-node with summary in side-channel keyed by step name) + D3 (cancel checked at every .await boundary, short-circuits via UpstreamCancelled) + D4 (stub backend wire shape byte-equal with v1.25.0; new step_type slugs elided for canonical Step) + D6 (StepAuditRecord with SHA-256 output_hash_hex per step) + D7 (zero unwrap()/unimplemented!/panic on adopter-reachable paths — fuzz pack runtime-enforces) + D10 (all 6 variants produce uniform `"(stub)"` accumulated output for stub backend — semantic parity invariant). **No MVP, no partial solutions honored**: 6 production-grade handlers with comprehensive cognitive framings + closed-catalog dispatch + drift-gated wire-stability + 1450-iter adversarial fuzz coverage + zero unimplemented markers. |
| **33.y.d** | orchestration variants (control flow) | ~2200 (700 orchestration.rs + 600 integration + 750 fuzz + 150 misc) | ✅ SHIPPED 2026-05-13 | **`Let`, `Conditional`, `ForIn`, `Break`, `Continue`, `Return` — 6 variants — graduated.** New submodule `flow_dispatcher/orchestration.rs` (~700 LOC) ships 6 handlers + condition evaluator (`eval_triple` + `evaluate_condition`) + iterable resolver (`resolve_iterable`) + shared body dispatcher (`dispatch_body`, used by Conditional/ForIn for recursive `Box::pin(dispatch_node(...))` calls). **Let handler** — three `value_kind` cases (closed catalog: "literal" / "reference" / "expression"): literal binds the value verbatim; reference resolves through `ctx.let_bindings` (missing → empty string); expression treated as literal (full expression evaluator deferred). Inserts into `ctx.let_bindings`. Does NOT advance `ctx.step_counter` (not a wire-step). Returns `NodeOutcome::Completed { output: <resolved>, tokens_emitted: 0, step_index: <current> }`. **Conditional handler** — predicate evaluator over 8 closed-catalog operators (`==`, `!=`, `>`, `>=`, `<`, `<=`, `=`, empty); numeric f64 comparison when both sides parse, lexicographic fallback otherwise; bare-truthy semantics for empty op (LHS non-empty + not "false"/"0"); compound `conditions` via `conjunctor: "or"` short-circuits. Pushes `"conditional.then"` or `"conditional.else"` to `branch_path`. Dispatches the chosen body via `dispatch_body` → threads sentinels (Break / LoopContinue / Return) up unchanged. **ForIn handler** — iterable resolution: comma-split the value of the binding named by `iterable` (or split the literal itself if no binding); empty string → zero iterations. Per iter: insert iteration variable into `ctx.let_bindings`, push `"for_in[<idx>]"` to `branch_path`, dispatch body. Break sentinel → terminate loop early; LoopContinue → skip to next iter; Return → propagate up. Iter variable left bound to LAST iterated value after loop (sync-runner parity). Cancel checked between iters for D3 propagation. **Break/Continue/Return handlers** — sentinel emitters: cancel-check guard, then return `NodeOutcome::{Break, LoopContinue, Return { value }}`. Return resolves `value_expr` through `ctx.let_bindings` first; falls back to literal. **NodeOutcome extended** with 3 sentinel variants (Break / LoopContinue / Return). **DispatchCtx extended** with `let_bindings: HashMap<String, String>` — flow-scoped monotonic bindings (matches sync runner D10 parity). **dispatch_node** exhaustive match: 6 more arms delegate to `orchestration::run_*` (cumulative 12 of 45 graduated; 33 remain on legacy_shim). **Test surface 33.y.d**: 57 tests total. (a) 23 orchestration::tests (lib-internal): let literal/reference/missing-ref/no-counter-advance + eval_triple string-eq/numeric-cmp/binding-lookup/truthy-empty-op + resolve_iterable from-binding/trim/literal-fallback/empty + run_break/continue/return literal+resolved + every_orchestration_handler_short_circuits_on_cancel (6 handlers) + conditional then/else dispatch + for_in iter / break / zero-iter / return-propagate. (b) 25 integration tests (`fase33y_d_orchestration_handlers.rs`): dispatch_node entry routing for all 6 variants + Conditional with-or-conjunctor short-circuit + Conditional numeric-gt + ForIn 3-elem-csv-runs-step-each-iter + ForIn break / continue / return / literal-csv / zero-iter + Break/Continue/Return through dispatch_node + 3 nested-composition (break-in-forin-in-conditional, return-in-nested-forin, let-chain-then-conditional-then-forin) + 2 cancel-propagation (forin body + conditional body) + 2 branch_path push/pop discipline + step counter monotonicity across orchestration. (c) 9 fuzz tests (`fase33y_d_orchestration_fuzz.rs`, ~1550 deterministic LCG iters in 0.01s): Let × 200 + Let-missing-ref × 100 + Conditional × 200 (8 closed-catalog operators) + ForIn × 200 (random CSV iterables) + Sentinels × 200 (Break/Continue/Return round-robin) + Nested × 200 (3-deep random composition: Conditional → ForIn → {Let|Break|Continue|Return}) + Cancel × 200 (random handler × random pre-cancel timing) + Predicate-ops × 250 (all 8 operators × random LHS/RHS values; assert took binding always recorded). Total **1550 LCG iters** in 0.01s. **33.y.b drift gate updated**: GRADUATED_VARIANTS now 12 (6 pure-shape + 6 orchestration); new `PURE_SHAPE_GRADUATED` + `ORCHESTRATION_GRADUATED` sub-catalogs; `every_ir_flow_node_routes_to_its_labeled_handler` becomes tripartite (pure-shape → strict Completed with "(stub)" output; orchestration → sentinel/Completed depending on payload; non-graduated → LegacyShimHandled). Size pin advances to 12. **1659 axon-rs lib tests verdes** (up from 1636 = +23 module-internal). **ZERO regressions** verified across full Fase 33.x + 33.y integration suite (15 suites, 186 integration tests). **D-letter coverage validated**: D1 (12 of 45 graduated; compiler-enforced exhaustive match) + D3 (cancel propagation through 2-deep nested orchestration verified) + D6 (branch_path threading: `conditional.then` / `conditional.else` / `for_in[N]` / `step[N]` segments push/pop disciplined) + D7 (zero unimplemented markers; fuzz pack runtime-enforces) + D10 (sync-runner parity: Let bindings resolve identically, Conditional selects same branch, ForIn iterates same count, Break/Continue/Return semantics byte-equal). **No MVP, no partial solutions honored**: 6 production-grade handlers + 8-operator closed-catalog predicate + recursive Box::pin dispatch + sentinel propagation through nested orchestration + 3 closed-catalog sentinel outcomes + 1550-iter adversarial fuzz coverage + zero unimplemented markers. |
| **33.y.e** | parallel + algebraic variants | ~700 | ⏳ pending bloque | `Par`, `Stream`, plus the **algebraic-effects handler glue** (D9). `Par` spawns child handlers concurrently via `tokio::join_all`, multiplexes their `axon.token` events to the wire ordered by wall-clock arrival. `Stream` invokes the Fase 23 handler stack — `perform Stream.Yield x` on the streaming path emits `axon.token` directly (no materialization). +2 handlers + algebraic-effects glue + +20 integration tests + concurrent-stream fuzz +250 iters. The D9 milestone. |
| **33.y.f** | cognitive primitives (Fase 11 neuro-symbolic) | ~700 | ⏳ pending bloque | `Remember`, `Recall`, `Forge`, `Focus`, `Associate`, `Aggregate`, `Explore`, `Ingest`, `Navigate`, `Corroborate` — 10 variants. Each handler interfaces with PEM + cognitive-state subsystem (async). 33.y.f also adds the PEM async surface to `DispatchCtx` so subsequent sub-fases inherit the wiring. +10 handlers + PEM async surface + +35 integration tests + adversarial fuzz +150 iters/handler. |
| **33.y.g** | algebraic-effect handler nodes | ~600 | ⏳ pending bloque | `ShieldApply`, `OtsApply`, `MandateApply`, `ComputeApply`, `Listen`, `DaemonStep` — 6 variants. Each handler invokes the relevant Fase 11/14/16/20/27 subsystem with the streaming-aware async surface. `ShieldApply` runs per-chunk if upstream is a stream (foundation for the enterprise per-chunk PHI scrubber R&D track). +6 handlers + +25 integration tests + adversarial fuzz +150 iters/handler. |
| **33.y.h** | wire integrations (π-calc + persistence) | ~700 | ⏳ pending bloque | `Emit`, `Publish`, `Discover`, `Persist`, `Retrieve`, `Mutate`, `Purge`, `Transact`, `Deliberate`, `Consensus` — 10 variants. Each handler interfaces with the typed-channel/persistence layer (Fase 13 mobility-typed channels + Fase 28+ persistence primitives). `Emit`/`Publish` integrate with the algebraic-effect channel layer. +10 handlers + +35 integration tests + adversarial fuzz +150 iters/handler. |
| **33.y.i** | PIX variants (paper §6 hidden state) | ~500 | ⏳ pending bloque | `Hibernate`, `Drill`, `Trail` — 3 variants. PIX semantics require careful async port (the sync runner today uses CPS-style continuation passing for Hibernate; Trail/Drill use breadcrumb-style hidden-state walks). Each handler preserves byte-identical algebraic semantics vs the sync runner (D10 parity gate). +3 handlers + +20 integration tests + adversarial fuzz +200 iters/handler. |
| **33.y.j** | Lambda + UseTool (the 33.x.b–c–d deferred items) | ~600 | ⏳ pending bloque | `LambdaDataApply`, `UseTool` — 2 variants. Both require async port of currently-sync subsystems. LambdaDataApply lifts the Fase 15 lambda-apply runtime to async (the sync version walks a CPS dispatcher; the async version composes via the dispatcher's handler stack). UseTool dispatches mid-step tool calls through ChatRequest.tools + interleaves tool-call events on the wire. +2 handlers + async Fase 15 surface + +20 integration tests + fuzz +200 iters/handler. |
| **33.y.k** | tools on streaming path (D8) | ~500 | ⏳ pending bloque | Cross-cutting: every per-step handler (33.y.c–j) gets the unified tool-plumbing fix. Step's declared `apply: TOOL` populates `ChatRequest.tools`. Tool-call chunks from upstream backends interleave with text chunks on the wire as new `axon.tool_call` events (closed-catalog event variant; D4 byte-compat preserves absence-of-tool-call paths). +1 new event variant + +15 integration tests (interleaving / tool-only / text-only / mixed) + fuzz +200 iters. |
| **33.y.l** | parity gate + retirement of legacy path | ~400 | ⏳ pending bloque | New `tests/fase33y_l_sync_async_parity.rs`: 50-flow corpus drives both `runner::execute_full` + `flow_dispatcher::dispatch_full` + asserts byte-identical `ServerExecutionResult.step_results[i]`. Once green, **`run_streaming_legacy_path` is DELETED** + the LegacyOrchestrationRequired error variant is pruned. `unsupported_feature_reason` is deleted. D7's "no `unimplemented!()` markers" is verified by a build-time `grep -E "unimplemented|todo|FIXME" axon-rs/src/flow_dispatcher.rs` returning zero matches. |
| **33.y.m** | adopter docs | ~700 | ⏳ pending bloque | New `docs/MIGRATION_v1.26.md` (~400 LOC) with 5 scenario recipes (server-only upgrade / orchestration flow now streaming / tool-using flow now streaming / Par-block concurrent streaming / PIX flow with replay binding). `docs/ADOPTER_STREAMING.md` extended (+~300 LOC) with new §"Universal algebraic streaming (Fase 33.y, v1.26.0+)" covering D1–D12 mapped to adopter-observable behavior. |
| **33.y.n** | D12 fuzz + dedicated CI workflow | ~700 | ⏳ pending bloque | New `axon-rs/tests/fase33y_fuzz.rs` (~500 LOC) with ~3000+ LCG iters (handler totality + orchestration composition + cancel propagation + algebraic-semantics parity + tool-call interleaving). New `.github/workflows/fase_33y_dispatcher.yml` (10+ jobs, one per sub-fase 33.y.a–l + cross-stack drift + fuzz). |
| **33.y.o** | release v1.26.0 cross-stack + axon-enterprise v1.17.0 catch-up | release | ⏳ pending bloque | axon-lang v1.25.0 → v1.26.0 cross-stack: bump-my-version minor across 6 files. axon-frontend stays 0.11.1 (no AST changes — the IRFlowNode catalog change is on the IR/runtime layer, not the AST surface). axon-enterprise v1.17.0 lean catch-up + vertical-inheritance notes (HIPAA + Legal + Fintech + Government inherit per-chunk granularity across Par/ForIn/Conditional/Reason/Validate/Refine/Weave). PyPI + crates.io + GitHub Release with content-first notes. |

**Total target: ~8 800 LOC + ~360 new tests + ~3 000 fuzz iters + 1 new CI workflow.**

---

## ▶ 5. Vertical-grounded relevance

The same four high-profile regulated verticals (Banking PCI DSS Req 10 / Government FedRAMP AU-2 / Legal FRE 502 / Medicine HIPAA + 21 CFR Part 11 §11.10), now with **structural** streaming across the orchestration shapes regulated-domain flows actually use:

- **Banking** — `POST /loan/decision` with a real flow:
  ```
  flow ScoreLoan {
    output: Stream<Decision>
    let region_policy = load_policy(applicant.region)   // Let → 33.y.d
    par {                                                // Par → 33.y.e
      step CreditAnalysis { ask: "Analyze credit signals" effects: <stream:drop_oldest> }
      step FraudCheck     { ask: "Score fraud indicators" effects: <stream:fail> }
    }
    step Decide { ask: "Final decision" apply: anthropic_tool }   // tool → 33.y.k
  }
  ```
  Post-33.y, all four steps stream concurrently to the wire, with credit-analysis chunks under DropOldest enforcement + fraud-check chunks under Fail enforcement + final decision invoking the tool-calling state machine, all observable per-step in the audit row regulators replay on appeal.

- **Government** — `POST /benefits/eligibility` with a `ForIn` over eligibility criteria:
  ```
  flow EligibilityCheck {
    output: Stream<Determination>
    for criterion in determinative_criteria {           // ForIn → 33.y.d
      step Evaluate { ask: "Evaluate ${criterion}" effects: <stream:degrade_quality> }
    }
    step Synthesize { ask: "Combine determinations" }
  }
  ```
  Each `Evaluate` iteration's upstream HTTP request to Anthropic streams chunks live; cancel during an early iteration aborts the upstream request + skips remaining iterations (no wasted token quota across 12+ criteria evaluations).

- **Legal** — `POST /discovery/privilege` with `Conditional` branching on privilege type:
  ```
  flow PrivilegeAssess {
    output: Stream<Assessment>
    step IdentifyType { ask: "Identify privilege claim type" }
    conditional privilege_type == "attorney_client" {    // Conditional → 33.y.d
      step ACAnalysis { ask: "Analyze AC privilege" effects: <stream:drop_oldest> }
    } else {
      step WPAnalysis { ask: "Analyze WP doctrine" effects: <stream:drop_oldest> }
    }
  }
  ```
  Appellate review traces the per-step reasoning chain with `branch_path` recording which conditional branch fired (`"conditional.then.step[0]"` vs `"conditional.else.step[0]"`).

- **Medicine** — `POST /clinical/decision-support` with `ShieldApply` for per-chunk PHI scrubbing:
  ```
  flow CDS {
    output: Stream<Recommendation>
    step Reason about_diff { ask: "Differential diagnosis" effects: <stream:drop_oldest> }
    shield apply hipaa_phi_scrubber                      // ShieldApply → 33.y.g
    step Recommend { ask: "Final clinical recommendation" }
  }
  ```
  PHI scrubber runs **per-chunk** (not per-final-response), via the enterprise HIPAA vertical dict; clinician closes tab → upstream request to Anthropic aborts within ≤100ms.

---

## ▶ 6. Founder framing — why this cycle ships now

The Fase 33.x cycle delivered the activation of the canonical-Step shape and made the founder principle *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto"* true for **one specific flow shape**. The Fase 33.y cycle makes it true for **the entire IRFlowNode catalog** — every algebraic-effect declaration in `.axon` source has an observable, byte-deterministic runtime behavior on the SSE wire, regardless of orchestration shape, tool usage, or cognitive primitives invoked.

The four-pillar contract:

| Pillar | v1.25.0 (Fase 33.x) | v1.26.0 (Fase 33.y) |
|---|---|---|
| **MATHEMATICS** | `Backend::stream()` activated for canonical Step shape; algebraic effect enforcer runs per-step | Dispatcher total over the 45-variant `IRFlowNode` closed catalog; `perform Stream.Yield` invokes the Fase 23 handler stack directly (no materialization detour); compiler-enforced exhaustive match is the mathematical totality contract |
| **LOGIC** | Declaration ⟺ runtime contract for `step S { effects: <stream:...> }`; other shapes fall back to materialize-then-chunk legacy | Declaration ⟺ runtime contract for **every** IRFlowNode variant; effects compose at the chunk level across orchestration shapes (Par/ForIn/Conditional) |
| **PHILOSOPHY** | Wire timing is real for the canonical shape; non-canonical shapes still burst at end | Wire timing is real for the **entire language**; tools become first-class on the streaming path; any future adopter integrating any flow shape sees brutally-perfect streaming |
| **COMPUTING** | Cancel-in-body p95 12.6µs for single-step flows | Cancel-in-body p95 ≤100ms across orchestration: `Par`-block fans out cancel to all concurrent substreams; `ForIn` terminates current iter + skips remaining; algebraic-effect handlers honor cancel through the delimited-continuation stack |

Without Fase 33.y, the published `MIGRATION_v1.25.md` promise *"axon.token events now arrive at network granularity from the real upstream LLM"* has an unstated asterisk: "only for the canonical Step shape". Fase 33.y removes the asterisk for every IRFlowNode variant the language defines.

---

## ▶ 7. Bloque ratification — PENDING 2026-05-13

This plan vivo + the 33.y.a diagnostic anchor are drafted and committed. D1–D12 are PROPOSED, awaiting founder bloque ratification per the established cadence ("Te ratifico todos los D-letters" / "Ratificado todos los D-letters").

No sub-fase 33.y.b–o begins until ratification.

Sub-fase 33.y.a is COMPLETE upon: this plan vivo committed + `axon-rs/tests/fase33y_dispatcher_diagnostic.rs` ships green capturing v1.25.0 baseline for 7 representative non-Step shapes + 1 catalog totality pin.

### Quality-bar interpretation of the "no MVP" mandate (carries forward from 33.x)

Per `feedback_no_shortcuts.md` + the founder principle 2026-05-13 *"vamos a hacer que cualquiera de ahora en adelante integre la primitiva cognitiva y funcione brutalmente perfecta"*, the following are NON-NEGOTIABLE for every 33.y sub-fase:

- **No `unwrap()` on adopter-reachable paths.** Every error case is named in a closed catalog enum + handled.
- **No `// TODO` / `// FIXME` markers shipping to master.** If a follow-up is unavoidable it ships as its own sub-fase with explicit founder sign-off.
- **No silent degradation.** D5 (`axon-W003 partial-streaming-activation`) is the canonical example; the principle generalizes — every partially-streaming path emits a closed-catalog warning that the adopter can observe in real time (not at FlowComplete time).
- **No transitional shims persisting past their cycle.** The 33.y.b dispatcher arms initially route through sync-runner shims; each subsequent sub-fase 33.y.c–j REPLACES the shim with the real async handler; 33.y.l verifies zero shims remain.
- **Every public function on the new dispatcher surface is total + has a documented invariant.** `cargo doc` builds clean.
- **Every sub-fase ships with adversarial fuzz coverage** (≥150 LCG seeds per public predicate / handler) before the SHIPPED marker flips.
- **Every sub-fase ships with vertical canonical patterns exercised** (Banking / Government / Legal / Medicine) on the cycle's CI lane before the SHIPPED marker flips.
- **D10 parity gate green before D7 declaration:** every per-variant handler must produce byte-identical `ServerExecutionResult.step_results[i]` vs the sync runner for the same input. Wire timing differs; semantic output is invariant.

---

## ▶ 8. Risks + mitigations

| Risk | Mitigation |
|---|---|
| The dispatcher refactor touches multi-thousand LOC across the runtime; regressions are easy | D10 parity gate (sync↔async byte-equal on 50-flow corpus) runs on every PR. 33.y.l explicitly retires the legacy path only AFTER the parity gate is green for ≥1 week. |
| 45-variant exhaustive match is unwieldy in a single file | Each variant's handler lives in its own module (`flow_dispatcher::step`, `flow_dispatcher::par`, etc.); the central dispatcher is a thin `match` that delegates. ~50-150 LOC per handler module. |
| `Par` concurrency interacts subtly with the existing `tokio::spawn` model in `run_streaming_async_path` | 33.y.e ships with concurrent-stream fuzz +250 iters covering nested `Par`/`ForIn` with random cancel timing. The wire ordering invariant ("ordered by wall-clock arrival") is asserted via timestamp_ms monotone within each branch_path. |
| Fase 23 algebraic-effects runtime (delimited continuations) on the streaming path is novel territory | 33.y.e dedicates a full sub-fase to the integration. The paper §5 algebraic-effects FSM dispatcher (Fase 25 C23) is the conceptual reference; the Rust port mirrors its closed-catalog totality. Adversarial fuzz covers `perform Stream.Yield` semantics under random handler-stack depths. |
| The 50-flow parity corpus may be too small | 33.y.l corpus targets **50+ flows curated from real-world shapes**: 10 banking + 10 government + 10 legal + 10 medicine + 10 cross-vertical. Each flow exercises ≥3 IRFlowNode variants. The corpus is checked into the repo as fixtures, not generated. |
| axon-enterprise v1.17.0 catch-up bumps the dep pin to `>=1.26.0` but doesn't ship enterprise-only handler implementations | Same lean-catchup shape as v1.13.0–v1.16.0. Substantive enterprise R&D (per-chunk PHI scrubber wired into `ShieldApply` async handler; banking real-streaming audit ledger; legal real-streaming privilege-trace; fintech real-streaming AML signal preservation) ships in a future enterprise-only release with its own founder sign-off — unchanged from the v1.16.0 deferred-items list. |
