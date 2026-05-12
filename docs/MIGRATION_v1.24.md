# AXON Migration Guide — v1.23.x → v1.24.0

> **Scope:** the Fase 33 *SSE as Cognitive Primitive* architectural cycle
> introduced in v1.24.0. Adopters upgrading from v1.23.x
> (Fase 32 axonendpoint REST) read this doc to decide which migration
> scenario applies + execute the recipe.
>
> **TL;DR:** v1.24.0 is **strictly additive** (D9 ratified wire byte-
> compat). If you don't change anything, nothing changes — your
> v1.23.x SSE wire bodies are preserved byte-identically. What
> v1.24.0 adds: real per-token live forwarding on the SSE wire (33.c
> Layer 2), real native `Backend::stream()` for all 7 LLM providers
> (33.d Layer 3), the algebraic-effect `<stream:<policy>>` → wire
> behavior bridge (33.e Layer 4), cooperative cancellation
> (33.f D6), and a 7-lane CI workflow + ~2 000-iter D12 fuzz pack
> (33.g) pinning the contract.

---

## What changed in v1.24.0

| Surface | v1.23.x | v1.24.0 |
|---|---|---|
| SSE wire body byte format | Established (Fase 30/31/32) | **Byte-identical** (D9). Existing parsers + clients unaffected. |
| `axon.token` event arrival timing | Burst-arrived at end of `server_execute_full` | **Live per-token forwarding** via the new `FlowExecutionEvent` receiver pipeline (33.c). Adopter-observable against real native backends once 33.x lands. |
| `Backend::stream()` per provider | `BackendError::Generic("streaming not yet implemented")` on every provider | **Real per-provider impl**: Anthropic SSE, OpenAI-compat SSE (covers openai/kimi/glm/ollama/openrouter), Gemini `:streamGenerateContent?alt=sse` (33.d). |
| `tool X { effects: <stream:<policy>> }` annotation | Compile-time documentation only | **Runtime binding** — declared policy surfaces on the `axon.complete` wire envelope's new optional `stream_policies` array (33.e). |
| `axon.complete` JSON payload | 8 fields | **Same 8 fields PLUS** an optional `stream_policies: [{step, policy}, …]` array, elided when no `<stream:>` effects declared. |
| Client disconnect mid-stream | Producer ran to completion against a dropped channel | **Cooperative cancellation** — consumer's SSE `tx.send()` error fires `cancel.cancel()`, producer exits via the same early-return path (33.f). |
| CI lane for SSE wire contract | Implicit via Fase 30/31/32 anchor tests | **Dedicated 7-lane workflow** `.github/workflows/fase_33_sse_cognitive_primitive.yml` + ~2 000-iter D12 fuzz (33.g). |

The `stream_policies` field is **optional** + **elided when empty**;
existing JSON parsers see no observable wire change for any flow that
doesn't declare a `<stream:>` effect.

---

## Scenario A — You upgraded the server; nothing else changed

**Symptom:** None. Your existing client code keeps working.

**Why:** D9 wire byte-compat is ratified + tested at PR time via the
dedicated D9 anchor CI lane. Every Fase 30 / 31 / 32 wire shape pre-
v1.24.0 is preserved verbatim in v1.24.0.

**Recipe:** Upgrade the server. Re-run your existing SSE integration
tests. They pass.

```bash
pip install --upgrade axon-lang>=1.24.0
# or for Rust callers:
cargo update -p axon-lang --precise 1.24.0
```

If any test breaks at the wire-body level, that's a D9 anchor
regression — file a bug with the captured wire body. The anchor lane
in CI catches this BEFORE a release ships; an in-the-wild D9
regression is a release-blocker.

---

## Scenario B — You want to surface declared `<stream:>` policies in
            your observability dashboard

**Use case:** Your axon source declares `tool X { effects:
<stream:drop_oldest> }` and you want your monitoring stack to
correlate "this endpoint runs under drop_oldest backpressure" with
the wire-level latency / error / throughput signals.

**Recipe:**

1. Upgrade the server to v1.24.0 (as above).

2. Index the `stream_policies` field on `axon.complete` events:

```javascript
// EventSource consumer
es.addEventListener("axon.complete", (e) => {
    const data = JSON.parse(e.data);
    if (data.stream_policies?.length) {
        // [{"step":"Generate","policy":"drop_oldest"}, ...]
        observability.tag({
            policies: data.stream_policies.map(p => `${p.step}:${p.policy}`).join(","),
            trace_id: data.trace_id,
            flow: data.flow,
        });
    }
});
```

3. No source-side changes needed. The field auto-surfaces when ANY
   step in the flow references a tool whose `effects:` row carries a
   `stream:<slug>` entry.

**The closed catalog of policy slugs:**

| Slug | Wire-visible meaning |
|---|---|
| `drop_oldest` | Bounded buffer; oldest queued item dropped on overflow. Lossy but never blocks. |
| `degrade_quality` | Bounded buffer; on overflow, the new item is degraded via a tool-declared function. The compiler REQUIRES a degrader for this policy. |
| `pause_upstream` | Bounded buffer; producer blocks until consumer drains. Lossless. |
| `fail` | Bounded buffer; on overflow, producer surfaces a typed `StreamError::Overflow`. Consumer sees a mid-stream `axon.error` event. |

Adding a fifth slug requires a compiler patch — adopters cannot invent
"retry_forever" and starve the rest of the runtime.

---

## Scenario C — You're consuming SSE from a native LLM backend and
            saw the "streaming not yet implemented" error pre-v1.24.0

**Symptom:** A flow that uses `transport: sse` + a tool with a real
native backend (anthropic / openai / kimi / glm / ollama / openrouter /
gemini) was returning `axon.error` events with message
`"streaming not yet implemented for the X backend"`.

**Why:** Pre-v1.24.0 every native backend's `Backend::stream()`
returned an explicit typed stub (Fase 24 acceptance pattern: "no
unimplemented!() / panic!() in merged code"). The 7 stubs were the
deliberate honest scope statement that streaming was a Fase 24.x.2
follow-up.

**Fix (no source change required):** Upgrade to v1.24.0. All 7 native
backends now ship real streaming via three distinct impls (architecture
insight: openai-compat covers 4 providers through a shared backbone):

```
anthropic   →  /v1/messages with stream:true (SSE, typed events)
openai      ↘
kimi         |
glm          ├── /v1/chat/completions with stream:true (OpenAI-compat SSE)
ollama       |
openrouter  ↗
gemini      →  /v1beta/models/<model>:streamGenerateContent?alt=sse
```

Each impl fails-fast on non-200 (retrying mid-stream replays partial
tokens — semantically wrong); the typed `BackendError` you see on the
wire's `axon.error` event reflects the provider's actual response
status (401 → Auth, 429 → RateLimit, 5xx → Generic with status).

---

## Scenario D — You depend on the pre-33.c "synchronous burst" timing

**Symptom:** Your client assumed ALL token events arrived in a burst
BEFORE `axon.complete`, with no inter-event idle gap.

**Why:** Pre-33.c (v1.23.x), `execute_sse_handler` awaited the
entire flow execution via `server_execute_full`, then iterated the
already-collected `step_results` and emitted them all at once into
the SSE channel. The wire body LOOKED token-by-token but ALL events
were already buffered before the first byte reached the client.

**Reality:** This was a bug surfaced by the adopter trail post-
v1.23.1. The W3C SSE spec does NOT require all events before
terminator; clients SHOULD treat each event as it arrives.

**Fix:** None known to be needed. The new behavior is strictly more
correct. If your client implements EventSource correctly per the
W3C spec, the per-event dispatch already handles inter-event idle
gaps + the keepalive comment lines.

If you find a real regression where your client depended on the
burst behavior, file a bug. The D9 anchor lane in CI pins the wire
byte format; we're confident no byte-level regression has shipped.

---

## Scenario E — You want to bind external scope to streaming lifetime

**Use case:** You have an adopter-side resource (e.g. an external
work-queue lock, a multi-tenant rate limit reservation, a
database transaction) whose lifetime should match the streaming
SSE response. When the client disconnects, you want the external
resource released within a bounded time.

**Recipe:** The Fase 33.f cancel-safety primitives are part of the
public adopter API. Construct a `CancellationFlag` on the adopter
side and install a `CancelOnDrop` guard that releases your
external resource:

```rust
use axon::cancel_token::{CancellationFlag, CancelOnDrop};

let flag = CancellationFlag::new();
let observer = flag.clone();

// Spawn the work that depends on the external resource:
tokio::spawn(async move {
    // ... acquire the resource ...
    // Bind release to scope exit (any path: normal, ?, panic, abort).
    let _release_guard = CancelOnDrop::new(observer);
    // ... do work; check flag.is_cancelled() between iterations ...
});

// When the SSE response is dropped (client disconnect, server-side
// shutdown), call flag.cancel() to wake any awaiting consumers and
// signal the spawned work to exit.
```

The cancellation is **monotone** (once set, never returns to non-
cancelled) and **idempotent** (multiple cancels are safe). The
`CancelOnDrop` guard fires on every scope-exit shape: normal
return, `?`-return, panic, task abort.

---

## What we deferred to 33.x (honest scope statement)

`server_execute_full` is currently synchronous — it materializes
all step outputs (via `Backend::complete()`) before the per-token
chunker emits the `FlowExecutionEvent` sequence. The producer/
consumer split shipped in 33.c is structurally end-to-end, but the
producer itself emits all events in microseconds when running
against the stub backend or a non-streaming Backend.complete()
path. There's no real per-token network roundtrip in v1.24.0
without an explicit `Backend::stream()` wiring at the per-step
execution site.

The next sub-fase (**33.x**, post-v1.24.0) wires
`Backend::stream()` into `server_execute_full`'s per-step
execution. At that point each chunk's actual network roundtrip
surfaces as a wall-clock inter-event gap on the wire, the
`StreamPolicyEnforcer` actually observes overflow under saturating
producers, and the `CancellationFlag` gets a meaningful window to
abort mid-flight backend requests when a client disconnects.

The architecture shipped in v1.24.0 is the complete contract;
v1.24.x point releases activate it without further adopter-facing
changes. We document this explicitly because adopters deserve to
know the difference between "architecturally in place" and
"adopter-observable end-to-end".

---

## D9 wire byte-compat anchor — the regression we will NEVER ship

The dedicated CI workflow `.github/workflows/fase_33_sse_cognitive_primitive.yml`
lane 7 (**D9 backwards-compat anchor**) re-runs the full Fase 30/
31/32 SSE-family test surface (10+8+12+15+17+23+11+4 = 100+ tests)
on every PR. Any byte-level perturbation in:

- The `retry: 5000\n\n` directive leading every response
- The `event: axon.token / axon.complete / axon.error` event types
- The `id:` monotonicity (always starts at 1, increments by 1)
- The `data:` JSON payload field set (pre-33.e fields preserved)
- The keepalive comment shape `: keepalive\n\n` at the declared
  interval
- The `Content-Type: text/event-stream` header

… breaks the build before a release can ship. Adopters can trust
the D9 invariant operationally; we trust it at engineering-process
level via the anchor lane.

---

## See also

- [`ADOPTER_STREAMING.md` §"Real-time streaming (Fase 33, v1.24.0+)"](ADOPTER_STREAMING.md#real-time-streaming-fase-33-v1240) — the full adopter guide for the Fase 33 cycle.
- [`MIGRATION_v1.23.md`](MIGRATION_v1.23.md) — previous migration (Fase 32 axonendpoint REST primitive).
- [`fase_33_sse_as_cognitive_primitive.md`](fase_33_sse_as_cognitive_primitive.md) — internal sub-fase tracker + D-letter ratifications (D1–D10).
- [`STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — the algebraic-effect Stream<T> + backpressure-policy catalog reference.
- [`axon-rs/src/cancel_token.rs`](../axon-rs/src/cancel_token.rs) — public `CancellationFlag` + `CancelOnDrop` API surface (Fase 33.f).
- [`axon-rs/src/stream_effect_dispatcher.rs`](../axon-rs/src/stream_effect_dispatcher.rs) — `<stream:<policy>>` → runtime dispatcher (Fase 33.e).
- [`axon-rs/tests/fase33_fuzz.rs`](../axon-rs/tests/fase33_fuzz.rs) — D12 robustness fuzz pack (~2 000 deterministic iterations across 13 surfaces).

---

*This document is part of the axon-lang public adopter surface. PRs
welcome.*
