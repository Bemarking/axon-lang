---
title: "Plan vivo: Fase 34 — Tools as stream-producers (the paper's four disjunctions converge)"
status: 🚀 IN PROGRESS — D1–D13 ratificadas bloque 2026-05-14 (founder "vamos con esta fase 34, estaba previsto"). Both strict prerequisites SHIPPED: Fase 33.z v1.27.0 (production dispatcher wiring) + Fase 33.z.k v1.28.0 (wire-format adapter cycle CLOSED).
owner: AXON Runtime + Backends Team
created: 2026-05-13
target: axon-lang v1.29.0 (minor — the `Tool` trait gains a `stream(args) → Stream<ToolChunk>` surface; the tool registry exposes a streaming dispatch; the 4 disjunctions of `produces_stream(F)` — `output: Stream<T>` / `apply: <stream-tool>` / `use_tool: <stream-tool>` / `perform Stream.Yield` — converge on a SINGLE chunk-level wire behavior; existing tools default to single-chunk streaming for D9 backwards-compat)
depends_on: Fase 33.z SHIPPED v1.27.0 (production hot path through `flow_dispatcher::dispatch_node`; 50-flow sync↔async parity corpus; legacy synchronous fallback DELETED; `axon.tool_call` SSE event family active on the wire). Fase 33.y SHIPPED v1.26.0 (per-IRFlowNode async dispatcher; 9 architectural-group helpers; D8 ToolCall variant; D7 grep parity gate). Fase 22 SHIPPED (7 native LLM backends + tool-calling state machine). Fase 23 SHIPPED (algebraic-effects runtime — delimited continuations + Stream.Yield handler stack).
charter_class: OSS — every adopter that declares `effects: <stream:<policy>>` on a tool sees the paper's promise honored end-to-end. axon-enterprise inherits via the v1.20.0 catch-up (34.m) — vertical-grade stream-producer tools (HIPAA PHI scrubber + legal privilege scanner + fintech AML pipeline as actual `Stream<ToolChunk>` producers rather than identity placeholders) land in axon-enterprise's vertical R&D track in lockstep.
pillars: |
  MATHEMATICS — The paper §1-§6 defines `effects: <stream:<policy>>` on a tool as the categorical statement "this tool is a STREAM PRODUCER with policy ⟨policy⟩". Today the runtime reinterprets this as "the LLM-call upstream of the tool produces a stream with that policy" — semantically adjacent but categorically WRONG. Fase 34 corrects the morphism: the tool itself becomes the stream producer; the `Tool` trait gains `stream()`; the dispatcher's `apply: <stream-tool>` arm invokes `stream()` instead of `execute()`; the per-chunk `Stream<ToolChunk>` flows through `StreamPolicyEnforcer` with the tool's declared policy; the chunks emerge as wire `axon.token` events. One categorical operation: `handle Stream { Yield(v) → resume(()) } in { tool.stream(args) }`.

  LOGIC — The 4 disjunctions of `produces_stream(F)` defined by the paper §3 finally converge on the SAME chunk-level wire behavior. Pre-34, each disjunction takes a different runtime path: (a) `output: Stream<T>` goes through `Backend::stream()`, (b) `apply: <stream-tool>` falls back to synchronous tool + materialization, (c) `use_tool: <stream-tool>` (same as b under different syntax), (d) `perform Stream.Yield` has a `bridge_effect_stream_yield` static-scan that emits one event per static Yield. Post-34, all 4 disjunctions invoke the SAME `unified_stream_handler` that drains a `Stream<ToolChunk>` through the same `StreamPolicyEnforcer` with the declared policy. ONE handler. ONE wire shape. ONE audit trail. ONE cancel discipline.

  PHILOSOPHY — This is the cycle where the paper's mathematical promise becomes the LIVE production behavior, not a compile-time annotation. Pre-34, `effects: <stream:drop_oldest>` is a string captured in the IR + projected onto `axon.complete.stream_policies` for adopter introspection — it has no runtime effect on the tool's body. Post-34, that string becomes a constraint enforced AT THE TOOL CALL: the tool's chunk stream is wrapped in the enforcer; drop_oldest semantically means "discard older chunks when the buffer is full"; cancel semantically means "abort the tool's HTTP request to OpenAI/Anthropic/MCP server"; per-chunk audit semantically means "SHA-256 the tool's complete chunk sequence, not the materialized post-hoc string". The four-pillar contract reaches the most fundamental conversation primitive: the tool itself.

  COMPUTING — Cancel propagation extends INTO the tool body: a client disconnect aborts the tool's outbound HTTP request to its provider (OpenAI / Anthropic / Gemini / MCP server / HTTP endpoint / native Rust execution) within the same p95 ≤100ms wall-clock budget that 33.x.e established for LLM-side streams. For HTTP tools: `reqwest::Response::bytes_stream()` drops + the connection aborts. For MCP tools: JSON-RPC cancellation message sent. For native tools: cancellation flag checked at the next yield point. The cancel discipline is uniform across every tool dispatch surface. Bounded buffers + atomic counters + cooperative cancellation, end-to-end, INSIDE the tool.
---

> **Founder principle (Fase 34 trigger, post-v1.26.0 review 2026-05-13):**
>
> *"todavía hay un gap para lograr que los algebraics effects funcionen como debe ser […] no trabajar en pos de este adopter, sino en pos de que la primitiva cognitiva sea 100% funcional y ofrezca el valor que indica el paper, es decir, pensar de forma ambiciosa."*
>
> The Fase 34 mandate is the deepest architectural extension since the algebraic-effects runtime itself (Fase 23). Tools become first-class stream producers. The runtime semantics of `effects: <stream:<policy>>` on a tool finally matches the paper's categorical promise. After 34, ANY adopter who declares the algebraic effect on a tool sees `text/event-stream` chunks flowing token-by-token FROM INSIDE the tool's body, with backpressure honored, cancel propagated, audit captured. The "primitiva cognitiva" is 100% functional.

---

## ▶ 1. Recap — what 33.z lifted to production, what 34 closes

### 33.z (v1.27.0) made the dispatcher TOTAL in production

For every one of the 45 `IRFlowNode` variants:

- The production SSE wire goes through `flow_dispatcher::dispatch_node` on the hot path (no legacy fallback).
- `axon.tool_call` SSE event family emits when upstream signals `FinishReason::ToolUse`.
- 50-flow sync↔async parity corpus enforces byte-equal `step_results` across the migration.
- `PlanError::LegacyOrchestrationRequired` + `unsupported_feature_reason` + `run_streaming_legacy_path` DELETED.
- Per-step audit captures `branch_path` for every variant.

### The gap 33.z does NOT close, by design

`pure_shape::run_step` for `step S { apply: clinical_reasoning }` where `clinical_reasoning` declares `effects: <stream:drop_oldest>`:

1. Synthesizes a `ToolSpec` from `step.apply_ref` (33.y.k D8).
2. Plumbs the `ToolSpec` into `ChatRequest.tools` — the LLM-side tool-calling state machine knows about it.
3. Calls `Backend::stream()` — gets a `Stream<ChatChunk>` from the upstream LLM.
4. If the LLM signals `FinishReason::ToolUse`, emits `FlowExecutionEvent::ToolCall` → `axon.tool_call` SSE event.
5. The TOOL ITSELF is invoked by either: (a) the LLM running it server-side (Anthropic computer use / OpenAI function calling with parallel execution), OR (b) the adopter's downstream client receiving the tool-call payload + executing it locally + sending a follow-up request.

**In NEITHER (a) NOR (b) does the runtime invoke the tool's body itself as a stream.** The `effects: <stream:drop_oldest>` declaration on `clinical_reasoning` is captured in the IR + recorded in audit but it shapes NOTHING at runtime: the tool's execution path is the existing synchronous `invoke_tool` returning a materialized `String`, OR the LLM-side tool execution that returns a single materialized chunk.

### What the paper §3-§6 actually postulates

`effects: <stream:drop_oldest>` on a tool means **the tool IS a stream-producer**:

```
tool clinical_reasoning {
  effects: <stream:drop_oldest>
  // ...
}
```

is, mathematically:

```
clinical_reasoning : (args: Args) → Stream<ToolChunk> ! { Stream :: drop_oldest }
```

The tool returns a `Stream<ToolChunk>` (NOT a materialized `String`). The `! { Stream :: drop_oldest }` effect row declares the algebraic effect with its backpressure policy.

When invoked from a flow:

```
flow CDS() {
  step Differential { ask: "..." apply: clinical_reasoning }
}
```

the categorical operation is:

```
handle Stream {
  Yield(chunk) → resume(())     // emit chunk to the consumer
} in {
  clinical_reasoning(diagnose_context)
}
```

**The runtime equivalent of this handler is: drain the tool's `Stream<ToolChunk>` through `StreamPolicyEnforcer(drop_oldest)` and forward each delivered chunk to `ctx.tx` as a `FlowExecutionEvent::StepToken`, which the production SSE consumer (post-33.z) emits as an `axon.token` event with `Content-Type: text/event-stream`.**

This is what does NOT exist today, at any layer of the runtime.

---

## ▶ 2. The four disjunctions of `produces_stream(F)` and their current state

The paper §3 defines a flow `F` produces a stream iff:

| Disjunction | Adopter shape | v1.27.0 runtime path |
|---|---|---|
| **(a) Type-level** — step output type is `Stream<T>` | `step S { output: Stream<Token> }` | `Backend::stream()` per step (Fase 33.x.b) ✅ live per-chunk |
| **(b) Effect-level — apply syntax** — step applies a tool with stream effect | `step S { apply: stream_tool }` | dispatcher emits `axon.tool_call` (33.z D5) but the tool itself runs synchronously ⚠️ partial |
| **(c) Effect-level — use_tool syntax** — same as (b) under different sugar | `step S { use_tool: stream_tool }` | same as (b) ⚠️ partial |
| **(d) Imperative** — body contains `perform Stream.Yield(x)` inside `handle Stream { ... } in { ... }` | `step S { ... perform Stream.Yield(x); ... }` | `bridge_effect_stream_yield` static-scan over the Fase 23 IRPerform tree (33.y.e) ⚠️ existed before 33.z; coverage in 33.z via dispatcher graft |

**Fase 34's contract**: post-34, all 4 disjunctions invoke the SAME `unified_stream_handler`. Disjunctions (b) and (c) graduate from "partial — tool runs synchronously" to "complete — tool produces a stream that flows through the enforcer". Disjunctions (a) and (d) stay byte-equal in wire behavior (D9 backwards-compat) but now share the same internal handler.

---

## ▶ 3. Concrete code-level gap

| Location | Today (v1.27.0) | 34 target |
|---|---|---|
| [axon-rs/src/tool_registry.rs](../axon-rs/src/tool_registry.rs) `ToolEntry` | `pub struct ToolEntry { name, provider, timeout, runtime, sandbox, max_results, output_schema, effect_row, source }` — function-call semantics; `effect_row: Vec<String>` carries the IR effect declarations but is dead weight at runtime | Extended with `is_streaming: bool` derived at registration from `effect_row.iter().any(\|e\| e.starts_with("stream:"))`; new method `Tool::stream(args, ctx) → Stream<ToolChunk>` on the trait |
| [axon-rs/src/tool_executor.rs](../axon-rs/src/tool_executor.rs) `ToolResult` | `pub struct ToolResult { success: bool, output: String, tool_name: String }` — single materialized output | New `ToolChunk { delta: String, finish_reason: Option<FinishReason>, timestamp_ms: u64 }` closed-catalog struct. `ToolResult` retained for non-streaming tools (D9). New `pub async fn dispatch_stream(name, args, ctx) → Stream<ToolChunk>` parallel to existing `dispatch(name, args) → Option<ToolResult>`. |
| `Tool` trait (currently the registry IS the dispatch — no formal trait) | Tool dispatch is a closed match in `tool_executor::dispatch` over hardcoded `tool_name`; provider adapters live in separate modules (`http_tool` / `emcp` / etc.) | New `pub trait Tool { async fn execute(&self, args, ctx) → ToolResult; async fn stream(&self, args, ctx) → Stream<ToolChunk> { /* default: wrap execute() as single-chunk stream */ } }` — adopters implement `stream()` only when they truly stream; D9 backwards-compat for non-streaming tools via default impl. |
| [axon-rs/src/http_tool.rs](../axon-rs/src/http_tool.rs) HTTP REST tool adapter | Synchronous POST returning materialized response body | Streaming HTTP via `reqwest::Response::bytes_stream()`; SSE-aware adapters consume upstream SSE (when the HTTP tool itself talks to an SSE endpoint) and re-emit as `ToolChunk`s; cancel propagates via reqwest abort (33.x.e budget preserved INSIDE the tool's HTTP call). |
| [axon-rs/src/emcp.rs](../axon-rs/src/emcp.rs) MCP transducer | Synchronous JSON-RPC 2.0 request/response | Streaming MCP via JSON-RPC partial responses (the MCP spec supports streaming notifications); fallback to single-chunk wrap when MCP server doesn't stream. |
| [axon-rs/src/flow_dispatcher/pure_shape.rs](../axon-rs/src/flow_dispatcher/pure_shape.rs) `run_step` | When `step.apply_ref` is non-empty: synthesize `ToolSpec` → plumb into `ChatRequest.tools` → call `Backend::stream()` → emit `FlowExecutionEvent::ToolCall` on `FinishReason::ToolUse` | Branch on tool's streaming surface: IF the resolved tool entry has `is_streaming: true` AND the step's effect_row carries `<stream:<policy>>`: bypass the LLM upstream call entirely; invoke `tool.stream(args, ctx).await` directly; wrap in `StreamPolicyEnforcer(policy)`; drain to `ctx.tx` as `FlowExecutionEvent::StepToken` per chunk. ELSE: existing LLM-call path. (The "LLM is the entry point to the tool" path stays for non-streaming tools.) |
| [axon-rs/src/flow_dispatcher/effects_bridge.rs](../axon-rs/src/flow_dispatcher/effects_bridge.rs) `bridge_effect_stream_yield` | Static-scan over `IRPerform` tree → emit one `axon.token` per static `perform Stream.Yield(x)` | Becomes a SPECIALIZATION of the new `unified_stream_handler`: the unified handler takes a `Stream<ToolChunk>` + drains; the existing bridge wraps the static `perform` scan as a synthetic `Stream<ToolChunk>` source. ONE codepath downstream of the source distinction. |
| [axon-rs/src/axon_server.rs `flow_produces_stream_runtime`](../axon-rs/src/axon_server.rs) (Fase 31 disjunct b) | Checks `FlowStep::UseTool` ↔ tool effects | Extended to ALSO check `FlowStep::Step { apply_ref }` ↔ tool effects (currently disjunct b only fires for the `use_tool: foo` syntax, not the `step S { apply: foo }` syntax — the adopter shape that prompted this entire cycle). Cross-stack drift gate keeps Python side aligned. |
| Cross-stack — Python `axon.tool` (Python tool dispatch surface) | Same function-call semantics; Python tools are async functions returning materialized strings | Python `class Tool` gains `async def stream(self, args, ctx) -> AsyncIterator[ToolChunk]` with default impl wrapping `execute()`. Cross-stack drift gate enforces 1-to-1 trait surface. |
| Adopter source-level — `effects: <stream:<policy>>` on a tool declaration | Captured in IR but runtime-inert (only shapes `axon.complete.stream_policies` audit field) | Becomes the RUNTIME DRIVER: presence of `stream:` in the tool's effect_row promotes the registry entry to `is_streaming: true`; downstream dispatcher routes through `tool.stream()`. |

---

## ▶ 4. D-letters proposed (D1–D13) — pending founder bloque ratification

- **D1 — Tool trait gains a streaming surface.** New `pub trait Tool { async fn execute(&self, args, ctx) → ToolResult; async fn stream(&self, args, ctx) → Stream<ToolChunk>; fn is_streaming(&self) → bool; }`. Default impl of `stream()` wraps `execute()` as a single-chunk stream (D9 backwards-compat: every existing non-streaming tool keeps working byte-equal). Default impl of `is_streaming()` returns `false`. Adopters and provider adapters override either OR both as their semantics require.

- **D2 — `is_streaming` derived from the IR effect_row.** When the tool registry registers a tool from a parsed `tool Name { effects: <stream:<policy>>; ... }` declaration, `is_streaming` is automatically set to `true` (the declaration → runtime contract). Adopters who programmatically register tools via the registry API can set `is_streaming` explicitly. The drift gate asserts: for every `tool` declaration with `<stream:...>` in `effect_row`, the registered entry has `is_streaming == true`.

- **D3 — The 4 disjunctions of `produces_stream(F)` converge on `unified_stream_handler`.** ONE handler in `flow_dispatcher` takes a `Stream<ToolChunk>` source (regardless of where it came from) + drains it through `StreamPolicyEnforcer` with the declared policy + emits `FlowExecutionEvent::StepToken` per delivered chunk + records `StepAuditRecord` with full SHA-256 hash of the concatenated stream + cancel-discipline via `ctx.cancel`. Disjunctions (a) and (d) keep their existing source-construction paths but route the resulting stream through the SAME `unified_stream_handler`.

- **D4 — Wire byte-compat preserved on disjunction (a).** Adopters with `step S { output: Stream<Token> }` + canonical Step shape observe BYTE-IDENTICAL wire body before/after 34. The `unified_stream_handler` is the same chunk-emission discipline; only the internal source-construction-then-handle composition changes.

- **D5 — Cancel propagation INTO tool bodies at p95 ≤100ms.** The same `CancellationFlag` instance that 33.x.e established at the LLM-side now threads through the tool's stream surface. For HTTP tools: `reqwest::Response::bytes_stream()`'s body iterator polls the flag at every chunk arrival; cancel triggers `drop(response_body)` → connection abort within wall-clock budget. For MCP tools: send JSON-RPC `$/cancelRequest` notification on cancel. For native built-in tools: cancel checked at every async yield point. Measured invariant: ~250 LCG iters in the 34.j fuzz pack assert p95 ≤100ms under random cancel timing × random tool dispatch surface.

- **D6 — Per-step audit captures the FULL tool stream.** `StepAuditRecord` for a step that invokes a stream-tool gains: `tool_name: String`, `tool_chunks_emitted: u64`, `tool_output_hash_hex: String` (SHA-256 of the concatenated tool chunk deltas, NOT the LLM-side accumulated output), `effect_policy_applied: Option<String>` (the tool's declared backpressure policy slug). Regulated-vertical compliance audit reconstructs the actual tool execution trail.

- **D7 — `axon.tool_call` SSE event emission graduates.** Pre-34 (33.z): `axon.tool_call` event surfaces when upstream LLM signals `FinishReason::ToolUse` (intent declaration). Post-34: a new `axon.tool_stream_start` event emits when a stream-tool invocation begins, then `axon.token` events with `source: "tool_stream"` field emit per chunk, then `axon.tool_stream_end` emits when the tool's stream closes. Adopter clients distinguish "LLM wants to call a tool" (FinishReason::ToolUse) from "tool is producing chunks" (tool_stream_start → tokens → tool_stream_end). The wire shape extends the existing v1.27.0 event family; D4 byte-compat preserved (new event types are additive).

- **D8 — Algebraic-semantics parity sync↔async.** For every flow in the 50-flow corpus (carried forward from 33.z.d), the sync runner output and the async dispatcher output remain byte-equal after 34. The corpus is extended with 10 new stream-tool flows (2 per vertical × 5 verticals) that exercise the new runtime path; for these new flows, the sync runner output is the materialized concatenation of all tool chunks (sync runner doesn't observe per-chunk semantics) and the async dispatcher output is the same concatenation observable on the wire as `step_results[i].output`. Byte-equal asserted.

- **D9 — Backwards compatibility absolute.** Every existing tool (built-in Calculator/DateTimeTool, HTTP tools without streaming endpoints, MCP tools without streaming notifications, native Rust tools registered by adopters) keeps working byte-equal in v1.28.0. The `Tool::stream()` default impl single-chunk-wraps `execute()`; adopters who haven't migrated to streaming see ZERO behavioral change in the wire body for any tool that doesn't declare `<stream:<policy>>` in its effect_row.

- **D10 — Cross-stack contract (Python ↔ Rust `Tool` trait).** Python `axon.tool.Tool` class gains `async def stream(self, args, ctx) -> AsyncIterator[ToolChunk]` with default impl wrapping `execute()`. Cross-stack drift gate asserts: same method signatures, same `ToolChunk` field shape, same `is_streaming` derivation rule from `effect_row`.

- **D11 — All 4 disjunctions surface in the diagnostic anchor.** New `axon-rs/tests/fase34_a_unified_stream_handler_diagnostic.rs` ships 4 representative flow shapes (one per disjunction) + asserts that each produces semantically-equivalent wire output: chunk count, output SHA-256, audit row shape. The diagnostic anchor is the foundation that every subsequent 34.b–l sub-fase preserves.

- **D12 — Production-grade D12 fuzz spans the new tool-stream surface.** New `axon-rs/tests/fase34_fuzz.rs` (~700 LOC, ~4 000 LCG iters): per-tool-surface streaming totality (HTTP tool / MCP tool / native built-in / stub tool, each × 500 iters = 2 000); cancel-into-tool-body (random pre-cancel × random tool surface × 250 iters = 250); 4-disjunction convergence (random disjunction × random body shape × 250 iters = 250); backpressure policy enforcement under load (each of 4 policies × random buffer pressure × 250 iters = 1 000); cross-stack tool stream round-trip (Python → Rust → wire × 500 iters = 500). Hand-rolled LCG (Knuth/MMIX, 33.x precedent).

- **D13 — Vertical-grounded stream-producer canonical patterns.** New `axon-rs/tests/fase34_vertical_stream_tools.rs` ships 8 canonical patterns: (banking) `pci_compliance_log_streamer` + `bureau_lookup_streamer` (both regulated as PCI DSS Req 10 stream-of-events tools); (medicine) `clinical_reasoning_streamer` + `phi_scrubber_streamer` (HIPAA Safe Harbor §164.514(b)(2) per-chunk PHI redaction); (legal) `privilege_assessment_streamer` + `discovery_scope_streamer` (FRE 502 waiver-doctrine per-chunk evaluation); (government) `eligibility_reasoning_streamer` + `audit_trail_streamer` (FedRAMP AU-2 per-step retention). Each tool: real implementation as `async fn stream(args, ctx) → Stream<ToolChunk>` (not single-chunk wrapper); each pattern: exercises `step S { apply: <streamer> }` through the dispatcher; asserts the wire emits per-tool-internal-chunk + audit captures the regulated-compliance shape.

---

## ▶ 5. Sub-fase shape — sequenced execution

Topologically sequenced. 34.a (spec + diagnostic anchor) is the foundation. 34.b–c lay the trait + registry extension. 34.d wires the dispatcher arm. 34.e–f extend HTTP + MCP tool surfaces. 34.g closes the bridge convergence (4 disjunctions → 1 handler). 34.h–i close cancel + audit extensions. 34.j is fuzz. 34.k is vertical patterns. 34.l is docs. 34.m is release.

| Sub-phase | Scope | LOC target | Status | Description |
|---|---|---|---|---|
| **34.a** | spec + diagnostic anchor | ~470 LOC | ✅ SHIPPED 2026-05-14 — this plan vivo housekeeping + new `axon-rs/tests/fase34_a_unified_stream_handler_diagnostic.rs` (470 LOC, **7 tests**). §1 disjunct (a) type-level `output: Stream<T>` → axon-dialect baseline 1 axon.token + 1 axon.complete (POST-34: byte-identical, D4); §2 disjunct (b) `apply: <stream-tool>` with `<stream:drop_oldest>` → Q1 openai-dialect wire baseline with exactly 1 content-delta (the LLM-upstream materialized chunk; PRE-34 gap = tool body runs synchronously; POST-34 inversion in 34.d emits per-tool-chunk frames); §3 disjunct (c) `use_tool`-syntax semantic-equivalent-to-(b) at the dispatcher layer (synchronous tool gap shared); §4 disjunct (d) `perform Stream.Yield(x)` static-scan baseline pin (Fase 33.y.e `bridge_effect_stream_yield`); §5 **closed-catalog totality pin** asserting EXACTLY 4 disjunctions per the paper §3 (adding a 5th requires paper update + deliberate sub-fase + cross-stack drift gate); §6 `ToolEntry.effect_row` carries `<stream:<policy>>` declarations but is runtime-inert (POST-34 34.b/c lifts to structural `is_streaming` field); §7 `ToolResult` is the v1.28.0 single-materialized return type (POST-34 34.b adds `ToolChunk` + `Tool::stream()` default-wraps `execute()`). Zero regressions across full Rust suite. |
| **34.b** | `Tool` trait + `ToolChunk` closed-catalog struct | ~600 | ⏳ pending bloque | New `pub trait Tool { ... }` in `axon-rs/src/tool_trait.rs` with `execute()` + default `stream()` + default `is_streaming()`. New `ToolChunk { delta, finish_reason, timestamp_ms }`. Existing `tool_executor::dispatch` retained for non-streaming dispatch; new `dispatch_stream` parallel surface. **15 lib unit tests** asserting trait surface + default impls + ToolChunk serde round-trip. Cross-stack mirror in Python `axon.tool` package (D10 parity). |
| **34.c** | `ToolRegistry` `is_streaming` derivation + drift gate | ~500 | ⏳ pending bloque | `ToolEntry` extended with `is_streaming: bool`; registration path derives this from `effect_row.iter().any(\|e\| e.starts_with("stream:"))`. New drift gate `axon-rs/tests/fase34_c_registry_drift.rs`: for every `tool` declaration in a synthetic 30-tool corpus (10 declaring `<stream:...>` + 20 not), assert `is_streaming == declaration` 1-to-1. **8 integration tests** + 1 lib unit. |
| **34.d** | Dispatcher arm — `pure_shape::run_step` branches on `is_streaming` | ~900 | ⏳ pending bloque | `pure_shape::run_step` gains the streaming branch: when `step.apply_ref` resolves to a tool with `is_streaming == true`: bypass `Backend::stream()` entirely (the LLM-side path) + invoke `tool.stream(args, ctx).await` + wrap result in `StreamPolicyEnforcer(declared_policy)` + drain to `ctx.tx` as `FlowExecutionEvent::StepToken` per chunk + record `StepAuditRecord` with `tool_name` + per-chunk count + SHA-256 of concatenated deltas. **20 integration tests**: stream-tool happy path × 4 tool surfaces (built-in, HTTP, MCP, stub) + cancel mid-stream × 4 + backpressure × 4 policies + audit row shape × 4 surfaces + composition with orchestration (stream-tool inside ForIn / Conditional / Par) × 4. |
| **34.e** | HTTP tool streaming adapter | ~700 | ⏳ pending bloque | [axon-rs/src/http_tool.rs](../axon-rs/src/http_tool.rs) extended with `async fn stream(...)` implementation: `reqwest::Client::post(url).send().await?.bytes_stream()` drained chunk-by-chunk; per-chunk poll of `ctx.cancel` (D5 budget); auto-parse SSE upstream when `Content-Type: text/event-stream` (recursive: HTTP tool talking to an SSE endpoint emits the upstream chunks); JSON-line streaming for `Content-Type: application/x-ndjson`. **18 tests**: 6 streaming shapes (raw bytes / SSE upstream / ndjson upstream / chunked transfer / multipart / compressed gzip stream) + 6 cancel propagation (random pre-cancel timing) + 6 error handling (upstream timeout / connection drop / partial body / malformed chunk / 5xx mid-stream / network reset). |
| **34.f** | MCP transducer streaming adapter | ~600 | ⏳ pending bloque | [axon-rs/src/emcp.rs](../axon-rs/src/emcp.rs) extended with `async fn stream(...)` over MCP JSON-RPC 2.0 partial responses: a `notifications/message` stream emits as `ToolChunk`s; final `result` payload closes the stream; `$/cancelRequest` sent on cancel; MCP servers that don't stream fallback to single-chunk wrap. **12 tests**: streaming MCP happy path + cancel + error handling + fallback when MCP doesn't stream. |
| **34.g** | 4-disjunction convergence — `unified_stream_handler` | ~800 | ⏳ pending bloque | New `axon-rs/src/flow_dispatcher/unified_stream.rs` ships `unified_stream_handler<S: Stream<Item = ToolChunk>>(source: S, policy: Option<BackpressurePolicy>, ctx: &mut DispatchCtx) → ToolStreamSummary`. ALL 4 disjunctions converge to invoke this handler: (a) `output: Stream<T>` constructs a source from `Backend::stream()` chunks mapped to `ToolChunk` via `From<ChatChunk>` impl + invokes handler; (b)/(c) construct source from `tool.stream(args, ctx).await` + invoke handler; (d) construct source from `bridge_effect_stream_yield`'s static-scan emissions wrapped in a one-shot mpsc producer + invoke handler. Effects bridge in `effects_bridge.rs` graduates from one-off emission to source-construction-then-unified-handle. **22 integration tests**: all 4 disjunctions assert byte-equal wire output for semantically-equivalent flows + 4 cancel + 4 backpressure + 4 audit shape + 6 composition with orchestration. |
| **34.h** | Cancel-into-tool-body (D5) p95 ≤100ms invariant | ~500 | ⏳ pending bloque | Stress measurement: 30 trials × 4 tool surfaces (HTTP / MCP / native / stub) × random cancel timing × random chunk arrival cadence → assert p95 ≤100ms wall-clock from cancel.cancel() to source stream drop. Mirror of the 33.x.e measurement discipline but at the tool layer. New `axon-rs/tests/fase34_h_cancel_into_tool.rs`. |
| **34.i** | Audit extension — `tool_chunks_emitted` + `tool_output_hash_hex` (D6) | ~400 | ⏳ pending bloque | `StepAuditRecord` extended with 4 new optional fields (elided when empty per D4 byte-compat) covering tool stream emission. `/v1/replay/<trace_id>` returns the extended shape. New `axon-rs/tests/fase34_i_audit_tool_stream.rs` asserts the shape end-to-end. |
| **34.j** | D12 fuzz | ~700 | ⏳ pending bloque | New `axon-rs/tests/fase34_fuzz.rs` (~700 LOC, ~4 000 LCG iters covering per-tool-surface streaming totality + cancel-into-tool-body + 4-disjunction convergence + backpressure policy enforcement under load + cross-stack tool stream round-trip). Hand-rolled LCG (Knuth/MMIX, no external dep). |
| **34.k** | Vertical canonical stream-producer patterns (D13) | ~1000 | ⏳ pending bloque | New `axon-rs/tests/fase34_vertical_stream_tools.rs` ships 8 canonical patterns (2 per vertical × banking / medicine / legal / government). Each tool: real implementation as `async fn stream(args, ctx) → Stream<ToolChunk>` (not single-chunk wrapper); each pattern: exercises `step S { apply: <streamer> }` through the dispatcher; asserts the wire emits per-tool-internal-chunk + audit captures the regulated-compliance shape. Cross-stack mirror as `tests/test_fase34_vertical_stream_tools.py` (Python parity). |
| **34.l** | Adopter docs | ~800 | ⏳ pending | New `docs/MIGRATION_v1.29.md` (~500 LOC) with 5 scenario recipes: (A) server-only upgrade — stream-tools auto-stream once you declare `<stream:<policy>>`; (B) implementing a custom streaming tool — adopter writes a `Tool::stream()` impl; (C) per-chunk audit for regulated-vertical replay; (D) cross-stack — Python Tool::stream parity; (E) backwards-compat — existing tools keep working byte-equal. `docs/ADOPTER_STREAMING.md` extension (~300 LOC) with new §"Tools as stream-producers (Fase 34, v1.29.0+)" mapping D1–D13 to adopter-observable behavior. The §"What the paper means by stream-effect tools" canonical section finally lands. |
| **34.m** | release v1.29.0 cross-stack + axon-enterprise v1.20.0 catch-up | release | ⏳ pending | axon-lang v1.28.0 → v1.29.0 cross-stack: bump-my-version minor across 6 files. axon-frontend bumps from 0.12.0 → 0.13.0 if Tool trait surface requires AST changes (TBD; may stay 0.12.0 if the trait is runtime-only). axon-enterprise v1.20.0 substantive release: vertical-grade `Tool::stream()` implementations land in `axon_enterprise.shield` (HIPAA PHI scrubber streamer + legal privilege scanner streamer + fintech AML pipeline streamer + government audit trail streamer) — NOT identity placeholders, real per-chunk processing. PyPI + crates.io + GitHub Release with content-first notes. |

**Total target: ~9 200 LOC + ~150 new tests + ~4 000 fuzz iters + cross-stack drift gate + vertical R&D.**

---

## ▶ 6. Vertical-grounded relevance

The four high-profile regulated verticals — Banking PCI DSS Req 10 / Government FedRAMP AU-2 / Legal FRE 502 / Medicine HIPAA + 21 CFR Part 11 §11.10 — finally get **per-tool-internal-chunk** observability for the audit trail. Pre-34, the tool was a black box returning a materialized string; post-34, the tool's reasoning chain is wire-observable AS IT'S BEING PRODUCED.

- **Banking** — `tool aml_investigator { effects: <stream:fail> }`. A loan-decision flow's `step Investigate { apply: aml_investigator }` invokes the AML tool, which internally calls OpenAI o1-pro with reasoning_effort=high. Pre-34: the tool returned a single chunk with the materialized reasoning (loan decision UI sees a 30-second pause then a paragraph). Post-34: the tool's stream emits each reasoning step live + the loan officer sees the chain as it's being built (UX win + PCI DSS Req 10 hash-chain captures every reasoning chunk independently).

- **Government** — `tool eligibility_reasoner { effects: <stream:drop_oldest> }`. FedRAMP AU-2 retention captures the full reasoning trail; the audit officer reviewing an appeal sees the actual chunks the LLM produced (not just the final determination).

- **Legal** — `tool privilege_scanner { effects: <stream:degrade_quality> }`. The scanner processes a 50-document discovery batch; pre-34, the lawyer waits for the materialized output then reviews; post-34, each document's privilege assessment streams live + the lawyer can interrupt early if she sees an obvious privilege call (D5 cancel-into-tool-body — the upstream LLM call to the scanner provider aborts within 100ms).

- **Medicine** — `tool clinical_reasoner { effects: <stream:drop_oldest> }` (the adopter's actual shape from the founder's report). The differential-diagnosis tool's reasoning chain emits live; the clinician sees the diagnostic candidates as the LLM produces them; HIPAA Safe Harbor PHI scrubbing happens at the chunk level (not post-hoc on the materialized output — which is what current adopter shape forces); 21 CFR Part 11 §11.10 captures the actual reasoning trail.

**This is the cycle where regulated-vertical adopters stop getting "synthesized per-step audit" and start getting "per-tool-chunk audit, captured at the source, byte-deterministic".**

---

## ▶ 7. Honest scope statement (carried forward to adopter docs)

**What v1.29.0 (Fase 34) ships**: tools become first-class stream-producers. The `Tool::stream()` trait method exists; the registry derives `is_streaming` from declarations; the dispatcher invokes `tool.stream()` for stream-tools; the 4 disjunctions of `produces_stream(F)` converge on a single `unified_stream_handler`; cancel propagates into tool bodies at p95 ≤100ms; per-chunk audit captures the actual tool execution trail. Each chunk emerges through whichever wire dialect the axonendpoint declared (Fase 33.z.k surface).

**What v1.29.0 does NOT ship**:
- **Mid-stream tool result interleaving**: when the LLM upstream of a flow signals `FinishReason::ToolUse`, the runtime emits `axon.tool_call` (33.z D5) but the tool's response is NOT yet streamed back INTO the same LLM stream to resume the LLM's reasoning with the tool result mid-conversation. That's Fase 35 (the "tool-result interleaving" cycle).
- **Per-tool-chunk cryptographic chain signature**: per-chunk hash chains for byte-exact replay-as-original at the tool layer. Deferred to Fase 36+.
- **Distributed tool dispatch with stream forwarding**: tools running on remote axon-cluster nodes streaming back to the originating dispatcher. Deferred.
- **gRPC server-side streaming for tools**: out of scope (Fase 30 D2 carries forward).

After 34 lands, the **declarative path** for adopters is complete: declare `effects: <stream:<policy>>` on your tool, write its `stream()` impl, and the runtime honors the paper's promise end-to-end. The remaining gaps are about more sophisticated composition (mid-stream interleaving) and finer-grained auditing (per-chunk chain signature) — not about the primitive itself.

---

## ▶ 8. Why 33.z is strictly prerequisite

**The 34.d dispatcher arm graduation requires the dispatcher to be ON in production.** Pre-33.z, `flow_dispatcher::dispatch_node` is callable from downstream crates but NOT invoked from `server_execute_streaming`. If we landed 34's `Tool::stream()` surface + the `pure_shape::run_step` branching before 33.z, the extension would be dormant: production traffic would still route through `run_streaming_legacy_path` for any non-canonical shape + miss the new tool-stream branch entirely.

The sequencing 33.z → 33.z.k → 34 means:
1. **v1.27.0 (33.z)**: every adopter flow shape activates the dispatcher in production. Adopters STOP seeing the legacy burst path. `axon.tool_call` events emit when the LLM upstream signals ToolUse.
2. **v1.28.0 (33.z.k)**: closed 5-dialect SSE wire-format surface `{axon, openai, kimi, glm, anthropic}` + Q7 algebraic-policy preservation channel `axon_metadata`/`event: axon.metadata`. Algebraic-effect flows default to openai wire; adopter SDKs (litellm, langchain, vercel/ai, instructor, anthropic-sdk, Moonshot Kimi, Zhipu GLM) consume axon's output verbatim.
3. **v1.29.0 (34)**: tools themselves become stream producers. Adopters who declare `<stream:<policy>>` on a tool see per-tool-chunk wire emission flowing through the dialect they declared.

Adopters upgrading v1.26.0 → v1.27.0 → v1.28.0 → v1.29.0 in sequence see:
- v1.27.0 hop: their non-canonical-shape flows (Conditional/ForIn/Par/Remember/...) graduate from synthetic burst to per-chunk wire from the LLM.
- v1.28.0 hop: their algebraic-effect flows default to the openai dialect wire (or whichever dialect they declared via `transport: sse(<dialect>)`); zero-shim adopter SDK consumption.
- v1.29.0 hop: their stream-tool declarations finally activate at runtime — per-tool-internal-chunk wire emission, cancel into tool body, full audit — each chunk flowing through the dialect projection of their choice.

Adopters who jump v1.26.0 → v1.29.0 get all three transitions at once. All hops are strictly additive (D4 byte-compat on canonical shapes; D9 backwards-compat on existing tools; Q5 escape valve preserves W3C wire indefinitely).

---

*This document is the internal Fase 34 plan vivo. It will be flipped to ✅ status sub-fase by sub-fase per the established discipline (33.y, 33.x, 33.a-i precedents). Adopter-facing docs ship in 34.l as `docs/MIGRATION_v1.28.md` + `docs/ADOPTER_STREAMING.md` extension. The §"What the paper means by stream-effect tools" canonical adopter section, which has been promised since Fase 23, finally lands here.*
