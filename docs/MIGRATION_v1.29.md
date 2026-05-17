# AXON Migration Guide — v1.28.0 → v1.29.0

> **Scope:** the Fase 34 *Tools as stream-producers* cycle — the
> language-level capability for a `tool` to be a **first-class
> stream producer**, not just a synchronous request/response
> function. v1.29.0 ships the `Tool` trait streaming surface
> (`execute` / `stream` / `is_streaming`), the closed-catalog
> `ToolChunk` / `ToolFinishReason` / `ToolContext` types, the HTTP
> + MCP streaming adapters, the `unified_stream_handler`
> 4-disjunction convergence with real backpressure-policy
> enforcement, and the per-step tool-stream audit-row extension.
>
> **TL;DR — read this first:** v1.29.0 ships the streaming-tool
> **layer**, complete + tested end-to-end. It is **additive and
> backwards-compatible absolute** (D9): every existing tool —
> built-in `Calculator`/`DateTimeTool`, synchronous HTTP tools,
> synchronous MCP tools, adopter-registered native tools — keeps
> working **byte-equal**. There is **no wire flip** for any
> existing flow.
>
> The streaming-tool **dispatch arm** (`step S { apply: <stream-tool> }`
> draining a tool's `Stream<ToolChunk>` per chunk) is
> **embedder-activated**: it fires when a `ToolRegistry` is
> attached to the dispatcher's `DispatchCtx` via
> `with_tool_registry(...)`. The production HTTP server
> (`server_execute_streaming`) does **not** attach a registry in
> v1.29.0 — so HTTP-server traffic is unaffected. See the
> **Activation model** section below — this is the single most
> important thing to understand before adopting.

---

## What changed in v1.29.0

| Surface | v1.28.0 | v1.29.0 |
|---|---|---|
| `Tool` abstraction | Synchronous only — a tool was a request→response function (`execute()` returning a single `ToolResult`) | **Streaming surface added** — new `Tool` trait (Rust `axon::tool_trait::Tool`; Python `axon.runtime.tools.streaming.Tool`) with `async fn execute`, `async fn stream() → Stream<ToolChunk>`, `fn is_streaming() → bool`. Default `stream()` wraps `execute()` as a single-chunk stream (D9) |
| Tool chunk type | (none — tools returned `ToolResult`) | **New `ToolChunk` closed-catalog struct** `{ delta, finish_reason?, timestamp_ms }` + `ToolFinishReason` closed enum `{Stop, Error{message}, Cancelled}` + `ToolContext { cancel, trace_id }` + `ToolStream` type alias |
| `ToolEntry.is_streaming` | (field did not exist) | **New `bool` field** auto-derived at registration: `true` iff the tool's `effect_row` carries a `stream:<policy>` entry (`derive_is_streaming` is the canonical cross-stack rule) |
| HTTP tool surface | `dispatch_http` — synchronous `reqwest::blocking` POST, single response body → single `ToolResult` | **`HttpStreamingTool`** added — async `reqwest::Client` + `bytes_stream()` drain; Content-Type-driven framing (`text/event-stream` → per-SSE-event chunks; `application/x-ndjson`/`application/jsonl` → per-line chunks; everything else → single-chunk D9 wrap). Synchronous `dispatch_http` **unchanged** |
| MCP tool surface | `dispatch_mcp` — synchronous JSON-RPC 2.0 `tools/call`, single response | **`McpStreamingTool`** added — async JSON-RPC 2.0; streaming MCP servers (`application/x-ndjson`) emit per-`notifications/message` chunks, final `result` envelope closes the stream; non-streaming servers fall back to D9 single-chunk wrap; best-effort `notifications/cancelled` on cancel. Synchronous `dispatch_mcp` **unchanged** |
| Streaming-effect drain path | Disjunct (a) `output: Stream<T>` enforced `BackpressurePolicy` at chunk granularity via `StreamPolicyEnforcer`; disjunct (b) `apply: <stream-tool>` was **not wired** to a tool's `stream()` at all; disjunct (d) `Stream.Yield` static-scan emitted wire tokens with no policy involvement | **`unified_stream_handler`** added (`axon::flow_dispatcher::unified_stream`) — the single drain loop ALL `Stream<ToolChunk>`-producing disjunctions route through. Real `BackpressurePolicy` enforcement at chunk granularity for disjuncts (b)/(d) — `chunks_dropped`/`chunks_degraded` audit counters are now **real** (vs always-0) |
| Dispatcher streaming-tool arm | `step S { apply: <tool> }` always routed the tool to the LLM via `ChatRequest.tools` (intent-declaration semantics) | **`run_step_streaming_tool`** added — when (1) `step.apply_ref` is non-empty AND (2) a `ToolRegistry` is attached to `DispatchCtx` AND (3) the resolved entry has `is_streaming == true`, the dispatcher bypasses the LLM + drains the tool's `stream()` through `unified_stream_handler`. **Embedder-activated** — see Activation model |
| `StepAuditRecord` fields | 9 fields (`step_name` … `timestamp_ms`) | **4 optional fields added** — `tool_name`, `tool_chunks_emitted`, `tool_output_hash_hex`, `tool_terminator_kind`. Serde-elided when `None` (D4 byte-compat — legacy LLM-side rows serialize byte-identical to the pre-34.i shape) |
| `DispatchCtx` | (no tool-registry field) | **`tool_registry: Option<Arc<ToolRegistry>>` field added** + `with_tool_registry(...)` builder. `None` default — D9: dispatchers constructed without it behave exactly as v1.28.0 |
| Python tool surface | `axon.runtime.tools.base_tool` synchronous tools | **New `axon.runtime.tools.streaming` module** — `Tool` ABC + `ToolChunk` + `ToolFinishStop`/`ToolFinishError`/`ToolFinishCancelled` + `ToolContext` + `derive_is_streaming`. Coexists with `base_tool` (D9 — existing Python tools untouched) |

Every NEW surface is **additive**. **No existing adopter `.axon`
source changes behavior.** **No wire flip.** The cycle ships a
*capability*; the *production-server activation* of that capability
is explicitly out of Fase 34's scope (see below).

---

## The architectural arc — why this release matters

The AXON paper §3 describes a `tool` as something that can *be a
stream*: `tool T { effects: <stream:drop_oldest> }` declares that
`T` produces a backpressured chunk stream, not a single value.
Before v1.29.0, that declaration was **compile-time documentation
only** — the `<stream:<policy>>` effect annotation parsed, the
`is_streaming` intent was visible in the IR, but no runtime path
ever called a tool's `stream()` method, because tools had no
`stream()` method. A `tool` was structurally a synchronous
request→response function.

Fase 34 closes that gap. The cycle's 12 shipped sub-fases
(34.a–34.k; 34.m is the release) build, bottom-up:

1. **The `Tool` trait** (34.b) — `execute` + `stream` +
   `is_streaming`, cross-stack (Rust + Python).
2. **`is_streaming` derivation** (34.c) — the declaration→runtime
   contract: `<stream:<policy>>` in `effect_row` ⟹
   `is_streaming == true`.
3. **The dispatcher arm** (34.d) — `run_step_streaming_tool`, the
   branch point that routes a streaming tool's `stream()` to the
   wire.
4. **HTTP + MCP streaming adapters** (34.e, 34.f) — the first
   non-stub real stream producers: an HTTP tool consuming an
   upstream SSE/NDJSON endpoint, an MCP tool consuming JSON-RPC
   partial-response notifications.
5. **The 4-disjunction convergence** (34.g) — `unified_stream_handler`,
   the single drain loop with real backpressure-policy enforcement.
6. **The audit extension** (34.i) — per-step tool-stream
   provenance: `tool_name` / `tool_chunks_emitted` /
   `tool_output_hash_hex` / `tool_terminator_kind`.
7. **D12 fuzz** (34.j) — ~8 800 deterministic iterations across the
   new surface.
8. **Canonical patterns** (34.k) — 8 adopter-agnostic reference
   `Tool::stream()` implementations, cross-stack.

The result: a `tool` in AXON is now genuinely a stream producer.
The paper's promise — *"a tool can be a stream"* — is honored at
the type level, the runtime level, and the audit level.

---

## Activation model — read this before adopting

**v1.29.0 ships the streaming-tool LAYER. It does NOT auto-activate
it in the production HTTP server.**

The streaming-tool dispatch arm (`run_step_streaming_tool`) fires
only when **all three** conditions hold at dispatch time:

1. `step.apply_ref` is non-empty (`step S { apply: <tool> }`).
2. The dispatcher's `DispatchCtx` has a `ToolRegistry` attached
   (`DispatchCtx::with_tool_registry(registry)`).
3. The resolved `ToolEntry` has `is_streaming == true`.

The production SSE producer (`server_execute_streaming` →
`run_streaming_via_dispatcher`) constructs its `DispatchCtx`
**without** calling `with_tool_registry` — `tool_registry` is
`None`. So for HTTP-server traffic, condition (2) is false and the
streaming-tool arm **never fires**: `step S { apply: <tool> }` keeps
routing the tool to the LLM via `ChatRequest.tools` exactly as in
v1.28.0.

This is intentional and mirrors the Fase 33.y → 33.z pattern. In
33.y the per-IRFlowNode dispatcher shipped *structurally complete*
but dormant; 33.z was the dedicated production-wiring lift that
turned it on. Fase 34 ships the streaming-tool layer structurally
complete; wiring the `ToolRegistry` into `server_execute_streaming`
is a **separate, future production-activation** — it is not in
Fase 34's scope.

**Who gets the streaming-tool dispatch in v1.29.0:**

- **Embedders of the Rust runtime** who build their own
  `DispatchCtx` and call `with_tool_registry(...)` — full access
  (Scenario A).
- **Anyone calling `unified_stream_handler` directly** with a
  tool's `stream()` as the source — full access, no registry
  needed (Scenario B).

**Who does NOT (yet) get it:**

- Adopters consuming the production HTTP SSE server with no code
  changes — the wire is byte-identical to v1.28.0; streaming tools
  are dormant until the production-wiring activation ships.

This guide's scenarios are written for embedders. If you only
consume the HTTP server, **v1.29.0 is a no-op upgrade for you** —
bump the dependency pin, recompile, observe zero behavior change
(Scenario E).

---

## Scenario A — Activate streaming-tool dispatch (embedder)

**You embed the axon-rs runtime** and want `step S { apply: <stream-tool> }`
to drain the tool's chunk stream per-chunk onto the wire.

**Recipe:**

```rust
use std::sync::Arc;
use axon::cancel_token::CancellationFlag;
use axon::flow_dispatcher::{DispatchCtx, pure_shape::run_step};
use axon::tool_registry::ToolRegistry;
use tokio::sync::mpsc;

// 1. Build a ToolRegistry. Register your streaming tools — a tool
//    whose effect_row carries `stream:<policy>` is auto-flagged
//    is_streaming = true at registration (the 34.c derivation rule).
let mut registry = ToolRegistry::new();
// ... registry.register(entry) for each tool ...
let registry = Arc::new(registry);

// 2. Construct the DispatchCtx WITH the registry attached. This is
//    the activation switch — without with_tool_registry(...) the
//    streaming-tool arm stays dormant.
let (tx, mut rx) = mpsc::unbounded_channel();
let mut ctx = DispatchCtx::new(
    "MyFlow", "stub", "system prompt",
    CancellationFlag::new(), tx,
).with_tool_registry(registry);

// 3. Dispatch a step whose apply_ref names a streaming tool. The
//    dispatcher routes through run_step_streaming_tool →
//    unified_stream_handler, draining the tool's stream() per chunk.
let outcome = run_step(&step, &mut ctx).await?;

// 4. Each non-empty tool chunk surfaces as a FlowExecutionEvent::
//    StepToken on the rx channel — the same event family every
//    existing flow uses. No new SSE event types; no wire flip.
while let Ok(ev) = rx.try_recv() { /* forward to your SSE producer */ }
```

**What you observe:** the tool's `stream()` chunks reach the wire
as `StepToken` events as they arrive — not batched at end of
`execute()`. The `StepComplete` event + the `StepAuditRecord` carry
the tool-stream provenance (Scenario C).

**Backpressure:** if the tool's `effect_row` declares
`stream:drop_oldest` / `stream:degrade_quality` /
`stream:pause_upstream` / `stream:fail`, `unified_stream_handler`
enforces that policy at chunk granularity — see the
[ADOPTER_STREAMING.md](ADOPTER_STREAMING.md) §"Tools as
stream-producers" 4-policy behavior table.

---

## Scenario B — Implement a custom streaming tool

There are **two** real paths to a custom streaming tool in
v1.29.0. Pick by whether you embed the Rust runtime.

### B1 — The HTTP / MCP adapter path (no Rust code)

If your tool's work lives behind an HTTP or MCP endpoint that
already streams, construct the adapter directly — no trait impl
needed:

```rust
use std::time::Duration;
use axon::http_tool::HttpStreamingTool;
use axon::emcp::McpStreamingTool;

// HTTP tool — points at any endpoint. Content-Type drives framing:
//   text/event-stream      → one ToolChunk per SSE `data:` event
//   application/x-ndjson   → one ToolChunk per LF-delimited line
//   anything else          → one ToolChunk (full body) — D9 wrap
let http_tool = HttpStreamingTool::new(
    "my_http_streamer".to_string(),
    "https://my-service.example.com/stream".to_string(),
    Duration::from_secs(30),
);

// MCP tool — JSON-RPC 2.0. Streaming MCP servers emit
// notifications/message envelopes per chunk; the final `result`
// envelope closes the stream.
let mcp_tool = McpStreamingTool::new(
    "my_mcp_streamer".to_string(),
    "https://my-mcp-server.example.com/rpc".to_string(),
    Duration::from_secs(30),
);
```

Both implement the `Tool` trait — drive them through
`unified_stream_handler` (Scenario A) or call `.stream(args, ctx)`
directly. Every failure surface (connect / timeout / non-2xx /
mid-stream byte error / JSON-RPC error envelope) becomes an honest
`ToolFinishReason::Error` terminator — never a panic, never a
silent truncation.

### B2 — The `Tool` trait path (full control)

For a tool whose body is genuine Rust, implement the `Tool` trait.
The canonical reference is
[`axon-rs/tests/fase34_canonical_stream_tools.rs`](../axon-rs/tests/fase34_canonical_stream_tools.rs)
— 8 adopter-agnostic patterns. A minimal example:

```rust
use async_trait::async_trait;
use axon::tool_executor::ToolResult;
use axon::tool_trait::{Tool, ToolChunk, ToolContext, ToolFinishReason, ToolStream};
use futures::stream;

struct ProgressiveRefiner;

#[async_trait]
impl Tool for ProgressiveRefiner {
    async fn execute(&self, args: String, _ctx: ToolContext) -> ToolResult {
        // Synchronous path — D9. Adopters calling execute() directly
        // get the materialized result.
        ToolResult {
            success: true,
            output: format!("final:{args}"),
            tool_name: "ProgressiveRefiner".to_string(),
        }
    }

    async fn stream(&self, args: String, _ctx: ToolContext) -> ToolStream {
        // Real multi-chunk stream — emit per-stage, then a Stop
        // terminator. The terminator's finish_reason closes the
        // stream; intermediate chunks carry finish_reason: None.
        Box::pin(stream::iter(vec![
            ToolChunk::intermediate(format!("draft:{args}")),
            ToolChunk::intermediate(format!("refined:{args}")),
            ToolChunk::intermediate(format!("final:{args}")),
            ToolChunk::terminator("", ToolFinishReason::Stop),
        ]))
    }

    fn is_streaming(&self) -> bool {
        true
    }
}
```

**Cancel discipline (D5):** a long-running tool should poll
`ctx.cancel.is_cancelled()` between chunks and emit a
`ToolFinishReason::Cancelled` terminator when it fires. The
`CancelAwareCounter` pattern in
`fase34_canonical_stream_tools.rs` shows the lazy
`futures::stream::unfold` idiom for cooperative cancellation.

> **Honest scope note:** the dispatcher's tool-resolution bridge
> (`tool_dispatch_bridge::resolve_streaming_tool`) dispatches on a
> closed provider set — `stub` / `stub_stream` / `native` / `http`
> / `mcp`. There is **no extension arm for arbitrary adopter
> `Tool` impls** in v1.29.0. A custom B2 tool is therefore driven
> through `unified_stream_handler` **directly** by an embedder; it
> is not resolvable by `step S { apply: <custom-tool> }` through
> the registry. A registry extension point for adopter-defined
> `Tool` impls is future work. If you need registry-routed custom
> tools today, use the B1 (HTTP/MCP provider) path.

---

## Scenario C — Per-chunk tool-stream audit

**You operate in a regulated vertical** (banking PCI DSS Req 10,
government FedRAMP AU-2, legal FRE 502, medicine 21 CFR Part 11
§11.10) and need the per-step audit trail to capture the *tool's*
stream, distinct from the LLM-side counters.

v1.29.0 extends `StepAuditRecord` with four optional fields,
populated for steps that drained a streaming tool:

| Field | Type | Meaning |
|---|---|---|
| `tool_name` | `Option<String>` | The tool that produced the stream — `Some(name)` for `apply: <stream-tool>` steps; `None` for LLM-side `output: Stream<T>` + algebraic `Stream.Yield` (neither has a `Tool` impl backing the stream) |
| `tool_chunks_emitted` | `Option<u64>` | Count of `ToolChunk`s the source produced — **distinct from `tokens_emitted`**, which counts only non-empty deltas reaching the wire after policy enforcement. Comparing the two reconstructs the policy-enforcement story |
| `tool_output_hash_hex` | `Option<String>` | SHA-256 hex of the concatenated tool-stream deltas — the D6 content-addressable replay anchor for the tool's output |
| `tool_terminator_kind` | `Option<String>` | Closed-catalog slug `"stop"` / `"error"` / `"cancelled"` — the final `ToolFinishReason`. Auditors filter on this to find failure modes across a flow |

**Reading the audit trail:** the existing `GET /v1/replay/<trace_id>`
endpoint surfaces these fields automatically. The `step_audit`
array in the response carries each `StepAuditRecord` serialized; a
streaming-tool step includes the four new keys, a legacy LLM-side
step elides them (D4):

```json
{
  "trace_id": "550e8400-...",
  "step_audit": [
    {
      "step_name": "FetchData", "step_index": 0, "success": true,
      "tokens_emitted": 3, "output_hash_hex": "ba78...",
      "effect_policy_applied": "drop_oldest",
      "chunks_dropped": 1, "chunks_degraded": 0,
      "timestamp_ms": 1715648400500,
      "tool_name": "my_http_streamer",
      "tool_chunks_emitted": 5,
      "tool_output_hash_hex": "ba78...",
      "tool_terminator_kind": "stop"
    }
  ]
}
```

`tool_chunks_emitted: 5` vs `tokens_emitted: 3` vs
`chunks_dropped: 1`: the tool produced 5 chunks, the
`drop_oldest` policy dropped 1 under burst, and 3 non-empty deltas
reached the wire (the 5th was the empty-delta terminator). The
full enforcement story is auditable from one row.

**D4 byte-compat:** legacy LLM-side rows are serialized
**byte-identical** to the pre-34.i shape — serde elides the four
`None` fields. Existing audit consumers that parse `step_audit`
need no change; they simply gain four new keys on streaming-tool
rows.

---

## Scenario D — Cross-stack Python `Tool` parity

**You author tools in Python.** v1.29.0 ships a new Python module
`axon.runtime.tools.streaming` mirroring the Rust `Tool` trait:

```python
from axon.runtime.tools.streaming import (
    Tool, ToolChunk, ToolContext, ToolFinishStop, ToolFinishError,
)

class ProgressiveRefiner(Tool):
    async def execute(self, args: str, ctx: ToolContext):
        return f"final:{args}"

    async def stream(self, args, ctx):  # async generator
        yield ToolChunk.intermediate(f"draft:{args}")
        yield ToolChunk.intermediate(f"refined:{args}")
        yield ToolChunk.intermediate(f"final:{args}")
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True
```

The closed catalogs are byte-identical across stacks:
`ToolFinishReason` is exactly `{stop, error, cancelled}`;
`ToolChunk` is `{delta, finish_reason?, timestamp_ms}` with
`finish_reason` elided when `None`; `derive_is_streaming` applies
the same `stream:`-prefix rule. The cross-stack drift gates
(`tests/test_fase34_b_tool_trait_cross_stack.py`,
`test_fase34_c_registry_drift_cross_stack.py`,
`test_fase34_canonical_stream_tools.py`) fail loudly if either
stack drifts.

> **Honest scope note:** the streaming **dispatcher** is Rust-only.
> Python ships the `Tool` ABC + chunk types for cross-stack
> contract parity and for adopters authoring tools, but there is
> no Python `unified_stream_handler` — the per-chunk drain +
> policy enforcement + wire emission happens in the Rust runtime.
> A Python tool's `stream()` is consumed by draining its async
> generator directly (see
> `tests/test_fase34_canonical_stream_tools.py`).

---

## Scenario E — Backwards compatibility (the no-op upgrade)

**You consume the production HTTP server with no code changes.**
v1.29.0 is a no-op upgrade. Bump the dependency pin, recompile,
and observe:

- **Zero wire change.** Every existing flow — `output: Stream<T>`
  type-annotation flows, `apply: <tool>` LLM-tool-call flows,
  non-streaming flows — emits a **byte-identical** SSE/JSON body.
- **Zero tool behavior change.** Built-in tools
  (`Calculator`/`DateTimeTool`), synchronous HTTP tools (via the
  unchanged `dispatch_http`), synchronous MCP tools (via the
  unchanged `dispatch_mcp`), adopter native tools — all keep
  working exactly as v1.28.0.
- **Zero `.axon` source change.** Every source file compiles
  unchanged. A `tool T { effects: <stream:drop_oldest> }`
  declaration that parsed in v1.28.0 still parses; its
  `is_streaming` flag is now `true` in the registry, but with no
  registry attached to the production dispatcher the flag has no
  runtime effect on HTTP-server traffic.

The `Tool::stream()` default impl single-chunk-wraps `execute()`
via `ToolChunk::from_result` — so even a tool you never migrate
*is* a (trivial, one-chunk) stream producer when something calls
`stream()` on it. D9 is absolute.

---

## Backwards compatibility matrix

| Surface | Behavior in v1.29.0 |
|---|---|
| Existing `.axon` source (any shape) | **Compiles unchanged** — no grammar change in Fase 34 |
| Production HTTP SSE wire body (any existing flow) | **Byte-identical** — streaming-tool arm dormant without an attached registry |
| `FlowExecutionEvent` public enum | **No new variants** — tool-stream chunks surface through the existing `StepStart` / `StepToken` / `StepComplete` family. No `tool_stream_start` / `tool_stream_end` event types were added |
| Built-in / synchronous HTTP / synchronous MCP / native tools | **Byte-equal** — `dispatch_http` + `dispatch_mcp` synchronous paths unchanged; built-ins unchanged |
| `StepAuditRecord` struct | **4 optional fields added** — `tool_name` / `tool_chunks_emitted` / `tool_output_hash_hex` / `tool_terminator_kind`. Serde-elided when `None`; legacy rows serialize byte-identical. The struct now derives `Default` (additive) |
| `GET /v1/replay/<trace_id>` response | **`step_audit` rows gain 4 keys on streaming-tool steps**; LLM-side rows unchanged. No endpoint code change — the extension is serde-driven |
| `DispatchCtx` public struct | **`tool_registry` field added** — `Option<Arc<ToolRegistry>>`, `None` default. Embedders constructing `DispatchCtx` directly gain the `with_tool_registry` builder; no existing call site breaks |
| `ToolEntry` public struct | **`is_streaming: bool` field added** — auto-derived at `register_from_ir`. Code constructing `ToolEntry` literals must initialize it (the compiler catches missing fields explicitly) |
| `axon.tool_call` SSE event | **Unchanged** — still emitted when the upstream LLM signals `FinishReason::ToolUse` (intent declaration). Tool *stream* chunks are distinct: they flow as `StepToken` events |
| Python `axon.runtime.tools.base_tool` | **Unchanged** — the new `axon.runtime.tools.streaming` module is additive; existing Python tools untouched |

---

## What this release does NOT do

- **It does not auto-activate streaming-tool dispatch in the
  production HTTP server.** Wiring the `ToolRegistry` into
  `server_execute_streaming` is a separate future activation (see
  Activation model).
- **It does not add new SSE event types.** Tool-stream chunks
  surface through the existing `StepToken` event family — there is
  no `axon.tool_stream_start` / `axon.tool_stream_end`. (An earlier
  D7 *proposal* sketched such events; the shipped design routes
  tool chunks through the existing family, keeping `FlowExecutionEvent`
  a 6-variant closed catalog with D4 byte-compat intact.)
- **It does not flip any wire format.** Dialect selection
  (Fase 33.z.k) is orthogonal and unchanged.
- **It does not change the synchronous tool paths.**
  `dispatch_http` / `dispatch_mcp` / built-in dispatch are
  untouched.
- **It does not ship vertical-specific tools.** Verticals
  (banking / medicine / legal / government) are exclusive to
  axon-enterprise. The OSS crate ships only the 8 domain-neutral
  canonical patterns (34.k); vertical-grounded stream producers
  ship in axon-enterprise's v1.20.0 catch-up.

---

## Where to file bugs

| Symptom | Where |
|---|---|
| `Tool::stream()` default impl not single-chunk-wrapping `execute()` | Issue tag `fase-34.b` — D9 default-impl regression |
| `is_streaming` not `true` for a tool with `<stream:<policy>>` in `effect_row` | Issue tag `fase-34.c` — derivation-rule regression |
| `run_step_streaming_tool` not firing with a registry attached + `is_streaming` tool | Issue tag `fase-34.d` — dispatcher-arm regression |
| `HttpStreamingTool` mis-framing an upstream Content-Type | Issue tag `fase-34.e` — framing-classifier regression |
| `McpStreamingTool` dropping a `notifications/message` envelope | Issue tag `fase-34.f` — MCP envelope-parse regression |
| `chunks_dropped` / `chunks_degraded` reported `0` despite a declared policy + burst | Issue tag `fase-34.g` — `unified_stream_handler` enforcement regression |
| `StepAuditRecord` tool-stream fields absent on a streaming-tool replay row | Issue tag `fase-34.i` — audit-extension regression |
| Legacy LLM-side `step_audit` row NOT byte-identical to pre-34.i | Issue tag `fase-34.i` — D4 elision regression (treated as a blocker) |
| Python / Rust `Tool` surface drift | Issue tag `fase-34.b`/`fase-34.c` — cross-stack drift gate (blocker) |

---

## See also

- [`docs/ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) §"Tools as
  stream-producers (Fase 34, v1.29.0+)" — the full adopter
  reference: D-letter mapping, the 4-policy behavior table, the
  HTTP/MCP adapter framing reference, the canonical-pattern
  catalog.
- [`docs/MIGRATION_v1.28.md`](MIGRATION_v1.28.md) — the prior cycle
  (33.z.k multi-dialect wire format). v1.28.0 is the baseline this
  guide assumes.
- [`docs/fase/fase_34_tools_as_stream_producers.md`](fase_34_tools_as_stream_producers.md)
  — the plan vivo for the Fase 34 cycle. Source of truth for the
  D1–D13 invariant text + per-sub-fase landing status + honest
  scope statements.
- [`axon-rs/tests/fase34_canonical_stream_tools.rs`](../axon-rs/tests/fase34_canonical_stream_tools.rs)
  + [`tests/test_fase34_canonical_stream_tools.py`](../tests/test_fase34_canonical_stream_tools.py)
  — the 8 canonical `Tool::stream()` patterns, cross-stack. The
  reference implementations for Scenario B.
- The dedicated Fase 34 test files (`fase34_a` … `fase34_k` +
  `fase34_fuzz`) — every adopter-observable behavior in this guide
  is pinned by at least one test; reproduce locally with the
  `cargo test` / `python -m pytest` commands.
