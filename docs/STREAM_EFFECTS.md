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
