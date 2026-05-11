# Stream\<T\> — temporal algebraic effect with mandatory backpressure

§λ-L-E Fase 11.a. Closes the gap where reactive / streaming
workloads (WebSocket audio, microphone taps, multipart uploads,
server-sent telemetry) were expressed as ad-hoc async generators
with no language-level guarantee about what happens under load.

## Why first-class

Every real streaming system faces the same question: *what does the
producer do when the consumer can't keep up?* Silently dropping is
dangerous; silently blocking is dangerous; silently buffering
without bound is dangerous. The only safe answer is "the author
chose, on purpose". Axon's type system enforces that choice: a
`Stream<T>` parameter or return without a declared backpressure
policy **fails to compile**.

## The closed policy catalogue

| Slug | Runtime behaviour | When to pick it |
|---|---|---|
| `drop_oldest` | Evict the oldest item to make room for a new one | "Keep only the most recent" telemetry |
| `degrade_quality` | Apply a pure degradation function (e.g. resample) + keep going | Audio / video under temporary congestion |
| `pause_upstream` | Block the producer until the buffer drains | Request/response; safe only when the producer CAN wait |
| `fail` | Raise `StreamError::Overflow` and cancel | Critical pipelines; fail fast, caller decides |

Catalogue is closed — extension requires a compiler patch. Composing
the four primitives (e.g. "try degrade; if still full, fail") lives
in runtime combinators outside the catalogue.

## Source syntax

Declare the policy on the tool that produces or consumes the
stream. The compiler walks the flow body and verifies that every
flow using `Stream<T>` reaches a tool that declares the effect.

```axon
tool ingest_audio {
  provider: local
  timeout:  30s
  effects:  <stream:drop_oldest>
}

flow Transcribe(audio: Stream<Bytes>) {
  step Analyze {
    given: audio
    ask:   "summarise"
    apply: ingest_audio
  }
}
```

Qualifier options (capacity, degradation function) pass through
the annotation body. The runtime parses them in
[`axon-rs/src/stream_effect.rs`](../axon-rs/src/stream_effect.rs):

```
effects: <stream:degrade_quality>
```

## Runtime contract

`axon-rs::stream_runtime::Stream<T>` and its Python mirror
`axon.runtime.stream_primitive.Stream` implement the four policies
identically. Cross-language behavioural parity is load-bearing: a
flow compiled against the Rust type checker and executed via Python
(or vice versa) MUST exhibit identical policy dispatch.

Metrics emitted per stream (counters only, no tenant tags — adopters
wrap and tag per tenant):

```
axon_stream_items_pushed_total
axon_stream_items_delivered_total
axon_stream_drop_oldest_hits_total
axon_stream_degrade_quality_hits_total
axon_stream_pause_upstream_blocks_total
axon_stream_fail_overflows_total
```

## Compile-time errors (selected)

```
error: Flow 'Transcribe' uses 'Stream<T>' in its signature but no
       reachable tool declares a 'stream:<policy>' effect. Every
       Stream<T> needs a backpressure policy: drop_oldest,
       degrade_quality, pause_upstream, fail. Declare the policy on
       the tool that produces or consumes the stream
       (e.g. `effects: <stream:drop_oldest>`).
```

```
error: Effect 'stream' in tool 'ingest_audio' requires a
       backpressure policy qualifier 'stream:<policy>'. Valid
       policies: drop_oldest, degrade_quality, pause_upstream, fail.
```

```
error: Unknown backpressure policy 'retry_forever' in tool 'x'.
       Valid: drop_oldest, degrade_quality, pause_upstream, fail.
```

## HTTP wire format (Fase 30)

§λ-L-E Fase 30 closes the gap between `Stream<T>` (the algebraic effect)
and its on-the-wire HTTP transport. Before Fase 30 there was no
language-level way to declare *"this axonendpoint emits Server-Sent
Events"* — the parser silently accepted `transport: sse` on the
axonendpoint and the runtime returned a single JSON response anyway.
Fase 30 makes the wire shape a first-class declaration.

### Quick mapping

| `Stream<T>` shape in the flow | `axonendpoint` declaration | HTTP response |
|---|---|---|
| Any of the 3 disjuncts (a/b/c — see [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md#type-checker-enforcement-rules)) | `transport: sse` | `Content-Type: text/event-stream` — see W3C SSE wire format spec below |
| Any of the 3 disjuncts | omitted (defaults to `transport: json`) | `Content-Type: application/json` — single value, last step's output |
| No stream effect | `transport: sse` declared | **compile error** — type-checker enforces the soundness rule (Fase 30.c) |
| No stream effect | omitted | `Content-Type: application/json` — unchanged |

### W3C SSE wire format

Each per-step token emitted by the `Stream<T>` runtime surfaces as one
W3C SSE event with the shape:

```
event: axon.token
id: <monotonic_u64>
data: {"step":"<step_name>","trace_id":<int>,"token":"<text>","timestamp_ms":<int>}
```

The final completion envelope:

```
event: axon.complete
id: <last>
data: {"trace_id":<int>,"flow":"<name>","backend":"<provider>",...}
```

Each response also leads with the W3C `retry: 5000` reconnect hint and
honors the `keepalive:` field on the axonendpoint by emitting
`: keepalive\n\n` comment lines at the declared interval (default 15s,
closed enum `{5s, 15s, 30s, 60s}`).

### Where to look in the code

- Axonendpoint parser surface (Python + Rust): `transport: {json,sse,ndjson}` + `keepalive: {5s,15s,30s,60s}` closed-enum frozensets in [`axon/compiler/parser.py`](../axon/compiler/parser.py) + [`axon-frontend/src/parser.rs`](../axon-frontend/src/parser.rs).
- Type-checker enforcement (Fase 30.c): [`axon/compiler/type_checker.py`](../axon/compiler/type_checker.py) `_flow_produces_stream` master predicate.
- Runtime SSE handler: [`axon-rs/src/axon_server.rs`](../axon-rs/src/axon_server.rs) `execute_sse_handler` (`POST /v1/execute/sse`).
- Content-negotiation wrapper: same file, `execute_handler_with_negotiation` (`POST /v1/execute`).
- Adopter-facing guide: [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — comprehensive recipe + deployment cookbook + troubleshooting.

### Backpressure policy reaches the wire

The four `Stream<T>` backpressure policies operate at the runtime layer
(buffer overflow handling) — they do NOT change the wire format. A
`Stream<Bytes>` declared with `<stream:drop_oldest>` and routed onto
`transport: sse` emits exactly the same `axon.token`/`axon.complete`
event shape as one declared with `<stream:fail>`. The policy choice
shows up in the response body only via the `axon.error` event if the
runtime invokes `fail` and aborts mid-stream — adopters who picked
`drop_oldest`/`degrade_quality` see a clean `axon.complete` envelope
even when the buffer overflowed (the dropped/degraded items are
reflected in the `axon_stream_*` metrics above, never in the wire
events).

## What §11.a does NOT include (deferred)

- **Full dataflow-propagating check.** §11.a does the conservative
  approximation: any flow that declares `Stream<T>` in its signature
  must reach a tool that declares the effect. An adopter who has a
  `Stream<T>` threaded through N flows where only the root one
  declares the type will get the error. Full propagation lands when
  the AST grows attribute nodes.
- **Combinator library.** `merge`, `zip`, `debounce`, `throttle` live
  outside the primitive; future phase.
- **Backpressure-aware codegen**. The runtime implementation is
  fixed; compiling to a target that needs a different coroutine
  shape (e.g. WASM) is follow-up work.

## Where to look in the code

- Closed catalogue + annotation parser: [`axon-rs/src/stream_effect.rs`](../axon-rs/src/stream_effect.rs)
- Runtime impl: [`axon-rs/src/stream_runtime.rs`](../axon-rs/src/stream_runtime.rs)
- Python mirror: [`axon/runtime/stream_primitive.py`](../axon/runtime/stream_primitive.py)
- Checker pass: `axon-rs::type_checker::check_refinement_and_stream_contracts`
- Python mirror: [`axon/compiler/refinement_check.py`](../axon/compiler/refinement_check.py)
- Integration tests: [`axon-rs/tests/fase_11a_refinement_and_stream.rs`](../axon-rs/tests/fase_11a_refinement_and_stream.rs)
- Python unit tests: [`tests/test_fase_11a_stream.py`](../tests/test_fase_11a_stream.py)
