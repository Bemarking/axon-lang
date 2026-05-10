---
title: "Plan vivo: Fase 30 — HTTP Transport for Algebraic Stream Effects"
status: IN PROGRESS 2026-05-10 — D1–D8 RATIFIED en bloque por founder ("aprobadas todas D-letters"); 30.a SHIPPED; 30.b–30.i execution starting per incremental founder sign-off cadence
owner: AXON Compiler + Runtime Team
created: 2026-05-10
target: axon-lang — next available minor release after v1.20.0 (cadence determined by preceding patches; expected v1.21.0 if no v1.20.x patches intervene). Cross-stack Python + Rust. axon-enterprise catch-up follows the same pattern as v1.11.0 (Fase 28 cascade)
depends_on: Fase 11.a SHIPPED (Stream<T> algebraic effect + 4-policy backpressure catalog); Fase 23 SHIPPED (algebraic effects runtime with perform/handle/resume/abort); Fase 28 SHIPPED (adopter diagnostic robustness — Fase 30 inherits the source-context block + smart-suggest for new error messages)
charter_class: OSS — every adopter benefits; no enterprise-only surface. axon-enterprise gets the surface transitively via a catch-up release
---

> **Sibling adopter-facing docs:**
> - [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) (NEW, ships in 30.h) — end-to-end adopter guide for the transport surface.
> - [`STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — Fase 11.a doc covering the `Stream<T>` algebraic effect + the 4 backpressure policies. Extended in 30.h with a new "HTTP wire format" section.
> - [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Fase 28 adopter-facing diagnostic guide; cross-linked from the new streaming guide.

---

## ▶ Status snapshot (2026-05-10 — IN PROGRESS, D1–D8 ratified)

> **Founder principle reinforced 2026-05-10 con la ratificación de D1–D8:**
> *"todas las implementaciones de axon se hacen para hacer de axon un
> mejor lenguaje de programación, robusto, potente, alto nivel,
> indistintamente de quien o cuantos nos vayan a usar"*.
>
> This Fase ships the language primitive, not an adopter fix. Kivi's
> diagnosis surfaced the gap; the language gains a permanent
> first-class HTTP transport surface. Future adopters who never
> knew the trigger existed benefit identically. Quality bar: a
> compiler PhD reading the resulting parser + type-checker + runtime
> should see a coherent first-class primitive, not a workaround.


Fase 11.a (Stream<T> algebraic effect + 4-policy backpressure catalog) is
**compile-time complete**: the parser accepts `effects: [stream:drop_oldest]`
on tools that produce / consume `Stream<T>`, the type-checker enforces
mandatory-policy-declaration, and the runtime `stream_runtime.rs` ships
the four policies as a bounded async channel.

What it never closed: **the HTTP wire transport mapping**. When an
adopter deploys an `axonendpoint` whose `execute:` flow has a stream
effect, the existing `/v1/execute` handler always returns a single
JSON response. There is **no language-level way** to declare "this
endpoint emits Server-Sent Events". The Kivi adopter team surfaced
the gap on 2026-05-10 after 28.k landed; their diagnosis verbatim:

> *"el doc STREAM_EFFECTS.md cubre la sintaxis del effect-set y las
> políticas de backpressure, pero NO documenta cómo se promueve un
> axonendpoint HTTP a SSE wire format."*

Code investigation 2026-05-10 confirmed the gap (see § Investigation
summary). Fase 30 closes it.

**Founder principle (carried from Fase 28):** *adopters never diagnose
our bugs; we diagnose theirs.* Kivi correctly identified the missing
surface; Fase 30 ships it as a first-class language feature, not as
an ad-hoc fix.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 30.a Engineering spec + D-letter ratification | ✅ SHIPPED 2026-05-10 | doc-only | — | This doc (commit `dec38ba` initial draft) + bloque ratification commit; D1–D8 RATIFIED verbatim per founder ("aprobadas todas D-letters") + founder principle reinforced ("axon implementations are for axon as a better language, independent of adopter set"). Memoria `feedback_axon_for_axon.md` saved as durable directive. |
| 30.b Parser `transport` + `keepalive` fields (Python + Rust + drift gate) | ⏳ pending | ~150 (Py) + ~150 (Rust) + ~80 (drift fixture + tests) | Python + Rust | `axon/compiler/parser.py` `_parse_axonendpoint` + `axon-frontend/src/parser.rs` `parse_axonendpoint`; AST `AxonEndpointDefinition.transport: str = "json"` + `keepalive: str | None = None`; closed enum `{json, sse, ndjson}` for transport (D2); drift-gate fixture extending `tests/fixtures/fase28_drift_gate/corpus.json` pattern with new `fase30_transport/corpus.json` (10 entries × 4 expected fields); smart-suggest hint added to recognize `transport: <typo>` per Fase 28.e |
| 30.c Type-checker enforcement (`transport: sse` requires Stream-effect flow) | ⏳ pending | ~250 | Python | `axon/compiler/type_checker.py` — new validation pass: when `axonendpoint.transport == "sse"`, walk to the named `execute:` flow, assert at least one of: (a) `output: Stream<T>` declared on a step, (b) at least one tool reachable from the flow declares `effects: [stream:<policy>]`, (c) the flow body contains `perform Stream.Yield(...)`. Compile error with hint + source-context block (28.d format) when violated. Rust frontend port deferred to 30.c.2 (Python is the canonical type-checker per Fase 18) |
| 30.d Runtime SSE single-shot path en `/v1/execute` | ⏳ pending | ~350 | Rust | `axon-rs/src/axon_server.rs` `execute_handler`: when the deployed flow's axonendpoint declares `transport: sse` OR (`transport: json` + flow has stream effect + client sent `Accept: text/event-stream`), promote response to `text/event-stream`. SSE chunks emitted per-step: `event: axon.token\ndata: {...}\n\n`. Terminator `event: axon.complete\ndata: {...final...}\n\n`. Error mid-stream: `event: axon.error\ndata: {...}\n\n` then close. New `sse_response_envelope` builder shared with `/v1/execute/stream` two-stage path to avoid drift between transports |
| 30.e Content-negotiation fallback (D4 safety net) | ⏳ pending | ~150 | Rust | Same `execute_handler` adds: detect `Accept: text/event-stream` request header; if flow has stream effect AND no explicit `transport: json` declared, auto-promote. If `transport: json` explicit → server respects declared transport (D5 declared > negotiated). Test matrix: 3×3×2 = 18 (transport×accept×has-stream-effect) |
| 30.f Keepalive comment emission (D6) | ⏳ pending | ~80 | Rust | When transport is SSE, server spawns a `tokio::time::interval` task emitting `: keepalive\n\n` SSE comment line every `keepalive` duration (default 15s; parsable values `5s|15s|30s|60s`). Required for load balancers with idle-timeout cuts (AWS ALB 60s, CloudFlare 100s, Cloudflare Tunnel 90s). Cancel task on flow completion or client disconnect |
| 30.g CI matrix + cross-stack drift gate + SSE conformance fuzz | ⏳ pending | ~400 (YAML + tests) | YAML + Python + Rust | New `.github/workflows/fase_30_http_transport.yml` with 3 lanes: parser-drift (Py 3.12/3.13 + Rust matrix; shared fixture parsed identical on both stacks); type-checker-enforcement (positive/negative test pack); runtime-sse (axum testkit + actual SSE event stream parse-back; 100-iter deterministic fuzz of malformed `transport` values verifying recovery never crashes; SSE wire-format conformance vs `eventsource-parser` reference impl) |
| 30.h Adopter documentation surface | ⏳ pending | ~500 (Markdown new) + ~150 (extend existing) | Docs | New `docs/ADOPTER_STREAMING.md` covering: § Quick start (axonendpoint with transport: sse); § Single-shot vs two-stage patterns; § SSE wire format spec (event names, data envelope, keepalive, error mid-stream); § Content-negotiation fallback semantics; § Type-checker enforcement rules + common compile errors; § Backwards compat matrix; § CI integration recipe; § LSP / IDE recipe (auto-suggest of stream-aware flows). Extends `docs/STREAM_EFFECTS.md` with new § "HTTP wire format" section that links to the new doc (closes Kivi's diagnosis gap verbatim). Cross-link from `docs/ADOPTER_DIAGNOSTICS.md` § Common error patterns (extends Pattern 4) |
| 30.i Coordinated cross-stack release | ⏳ pending | release | — | bump-my-version minor bump from then-current axon-lang version; commit + tag via the existing `coordinated-release.yml` workflow; cargo publish axon-frontend + axon-lang to crates.io; GitHub Release with content-first notes (per versioning discipline — describe the surface added, not the Fase number). axon-enterprise catch-up follows the same shape as v1.11.0 (bump 2 files + dep pin) |

**Tests target**: ~120 new tests across:

- Parser positive/negative for `transport` + `keepalive` fields (Python + Rust mirror, ~30 each)
- Drift gate corpus parametrized: 10 entries × 4 fields = 40 assertions per stack
- Type-checker positive (Stream<T> output flow + transport: sse → clean) + negative (`transport: sse` on a non-stream flow → compile error with hint), ~25 tests
- Runtime SSE wire-format conformance: chunk shape, keepalive interval, error mid-stream, client-disconnect cleanup, ~20 tests
- Content-negotiation matrix: 18 (transport×accept×has-stream-effect)
- 100-iter deterministic fuzz of malformed `transport` + `keepalive` values, recovery never crashes (D12 from Fase 28 budget pattern)

**Total ship**: ~2100 LOC + ~120 tests + 2 markdown files + CI workflow extension.

---

## 1. Investigation summary — why now, what's missing

### 1.1 Code-level findings (verified 2026-05-10 by direct source inspection)

**Finding 1**: [`axon/compiler/parser.py:4801-4841`](../axon/compiler/parser.py#L4801) —
`_parse_axonendpoint()` accepts the field set:

```
{method, path, body, execute, output, shield, retries, timeout, compliance}
```

…and silently skips unknown fields via the catch-all `case _: self._skip_value()`
at line 4837. Adopters writing `transport: sse` get **zero feedback** —
no parse error, no warning, no runtime effect. The field is dropped.

**Finding 2**: [`axon-rs/src/axon_server.rs:1648-1820`](../axon-rs/src/axon_server.rs#L1648) —
`execute_handler` is the `/v1/execute` HTTP route. It always returns
`Json(...)` regardless of the flow's effect set. There is no
inspection of `effects: [stream:<policy>]` at this layer, no
content-negotiation, no SSE branch.

**Finding 3**: [`axon-rs/src/axon_server.rs:17579-17684`](../axon-rs/src/axon_server.rs#L17579) —
`execute_stream_handler` (route `/v1/execute/stream`) exists but
does NOT return SSE bytes directly. It executes the flow, publishes
tokens to the EventBus as `flow.stream.{trace_id}` events, and returns
**a JSON envelope** carrying a `consume_url` pointing at a SEPARATE
SSE endpoint (`/v1/events/stream?topic=...`). Adopters need TWO
HTTP calls to consume the stream — single-shot SSE is unimplemented.

**Finding 4**: [`axon-rs/src/axon_server.rs:17294-17345`](../axon-rs/src/axon_server.rs#L17294) —
`events_stream_handler` (route `/v1/events/stream`) is the only
endpoint that returns `text/event-stream` — but it's an
EventBus-consumer surface, not a single-shot execute path. It requires
the client to know the `topic` from a prior `/v1/execute/stream` call.

**Finding 5**: [`docs/STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — the
adopter-facing doc for the Fase 11.a effect catalog covers:
- The 4 closed backpressure policies
- The source syntax `effects: [stream:<policy>]`
- Compile-time type checking

…and **explicitly does not cover** HTTP transport mapping. Kivi's
verbatim diagnosis pinpointed this gap.

### 1.2 Why this is a real adopter-impacting gap, not a documentation issue

The Python axon-lang parser, the Rust axon-frontend parser, the type-checker,
the IR generator, and the runtime all carry the stream effect correctly
through every layer **up to but not including** the HTTP transport mapping
in `axon-rs/src/axon_server.rs`. Adopters who deploy a stream-effect flow
get a 200 OK with a JSON body that has the final result only — no per-step
tokens, no incremental rendering, no SSE wire format. The effect declaration
"works" in the sense that the type-checker accepts it; it "doesn't work"
in the sense that the runtime output looks identical to a non-streaming flow.

Two adopter pain shapes:

- **Single-shot consumers** (chat-app frontends, terminal CLIs, browser
  EventSource clients): expect `POST /endpoint` to return SSE chunks
  directly. Today they get JSON only. They have no way to opt into SSE
  at the language level.
- **Pub/sub multi-consumer** scenarios (dashboards consuming live
  inference logs from N tenants): the existing two-stage pattern
  (`POST /v1/execute/stream` → JSON with topic → `GET /v1/events/stream?topic=...`)
  is appropriate. Fase 30 **preserves** this path (D8 ratified) for
  these cases.

### 1.3 The v1.19.x pattern repeating

This gap is structurally identical to the v1.19.2/3/4 trilogy that
motivated Fase 28: the language has primitives the runtime doesn't
fully wire. Fase 11.a shipped Stream<T> as compile-time complete;
the runtime wiring went 80% of the distance (algebraic effect handler
+ EventBus publish + SSE consumption surface) but stopped short of
the last 20% (single-shot SSE from `/v1/execute`). Fase 30 closes
the same shape of gap.

---

## 2. Architecture decisions

### 2.1 Why declarative `transport: sse` (not pure runtime content-negotiation)

Pure content-negotiation (Option B in the founder's option matrix)
makes SSE behavior **invisible at the source level**. Compliance
officers reading the `.axon` file can't tell whether
`axonendpoint LiveAudit { ... }` emits PHI tokens incrementally
to a streaming consumer or batches them into a single JSON response
— that's a different audit risk profile.

Declarative `transport: sse` makes the wire format part of the
language contract:
- **Auditable at compile time** — appears in IR JSON, audit log, source review
- **Type-checker enforceable** — `transport: sse` without a Stream-producing
  flow fails compile (D3) instead of silently degrading at runtime
- **Independent of client correctness** — a client that forgets to send
  `Accept: text/event-stream` still gets SSE if the server declared it
  (D5 — declared > negotiated)
- **Visible in the OpenAPI surface** that Fase 21.e generates — adopter
  tooling sees the transport choice in the published spec

### 2.2 Why also keep content-negotiation as a fallback (D4)

Most adopters won't edit every `.axon` file the moment v1.21.0 ships.
The content-negotiation fallback lets existing flows with
`effects: [stream:...]` upgrade transparently for clients that send
`Accept: text/event-stream` — adopter gets SSE without source change.
This is the *safety net*; the declarative path is the *contract*.

Conflict resolution (D5): declared transport always wins. If
`transport: json` is explicit, server returns JSON even when client
asks for SSE. Rationale: explicit declaration is an intent statement
("this endpoint is NOT a streaming endpoint"); honoring the Accept
header would override intent.

### 2.3 Why a closed `transport` enum (D2)

Open-ended transport values invite incompatible adopter implementations.
The closed enum `{json, sse, ndjson}`:

- **json** (default) — existing behavior preserved verbatim
- **sse** — Server-Sent Events per W3C spec + WHATWG HTML living standard
- **ndjson** — reserved namespace; wire implementation ships in a future
  Fase. Parser accepts the value so the field name space is stable;
  type-checker accepts (it just enables negotiated SSE today as a
  graceful degradation); runtime emits a warning "ndjson reserved,
  serving as application/json line-delimited equivalent for now"

WebSocket / gRPC server-streaming / HTTP/2 trailers are intentionally
out of scope — see § Out of scope.

### 2.4 Why keepalive is mandatory metadata (D6)

Real-world load balancers cut idle TCP connections aggressively:

| LB | Default idle timeout | Configurable max |
|---|---|---|
| AWS ALB | 60s | 4000s |
| CloudFlare Free / Pro | 100s | (paid tiers vary) |
| CloudFlare Tunnel | 90s | (fixed) |
| Google Cloud Load Balancer | 30s | 1200s |
| nginx default | 60s | unlimited |

Without periodic keepalive comments, an SSE stream that sends no tokens
for >60s gets killed mid-stream by the LB — the client sees connection
reset, not flow completion. Default keepalive 15s leaves >4× margin
under AWS ALB's 60s default. Adopters with tighter LB timeouts
configure `keepalive: 5s`; adopters with slow LLM backends and lenient
LBs can set `keepalive: 30s` to reduce wire chatter.

---

## 3. Cross-stack contract (D7)

The Python parser (canonical) and the Rust axon-frontend parser MUST
produce byte-identical AST on the same `.axon` source. Locked in CI
by extending the Fase 28 drift-gate pattern.

### 3.1 Shared fixture corpus

```
tests/fixtures/fase30_transport/corpus.json
```

Each entry pins:

```json
{
  "name": "axonendpoint_with_sse_transport",
  "source": "axonendpoint Live { method: POST path: \"/live\" execute: orchestrate output: Stream<Token> transport: sse keepalive: 15s }",
  "expected_transport": "sse",
  "expected_keepalive": "15s",
  "expected_parse_error": null,
  "expected_typecheck_verdict": "clean"
}
```

Negative entries pin the compile-error path:

```json
{
  "name": "transport_sse_on_non_stream_flow",
  "source": "...flow Plain() {} ... axonendpoint X { execute: Plain transport: sse }",
  "expected_transport": "sse",
  "expected_typecheck_verdict": "error",
  "expected_error_contains": "transport: sse requires the execute flow to produce a Stream<T>"
}
```

### 3.2 Drift-gate tests

- **Python pack** `tests/test_fase30_drift_gate.py`: parametrized over corpus;
  runs Python parser + type-checker, asserts every expected_* matches.
- **Rust integration test** `axon-frontend/tests/fase30_drift_gate.rs`: reads
  same JSON via serde; runs Rust parser; asserts parsed AST has same
  `transport` + `keepalive` values. (Type-check stays Python-only per
  Fase 18 decision; Rust port deferred to 30.c.2.)
- **CI lane** `.github/workflows/fase_30_http_transport.yml` runs both packs.

---

## 4. Wire format spec (SSE)

### 4.1 Per-step token event

```
event: axon.token
id: <monotonic counter scoped to trace_id>
data: {"step":"<step_name>","trace_id":<u64>,"token":"<utf-8 chunk>","timestamp_ms":<i64>}

```

(Note: trailing blank line per W3C SSE spec ends one event.)

### 4.2 Final completion event

```
event: axon.complete
id: <last counter>
data: {"trace_id":<u64>,"steps_executed":<u32>,"tokens_input":<u32>,"tokens_output":<u32>,"latency_ms":<u32>,"backend":"<backend_name>","success":true}

```

After this event, the server closes the response. Client EventSource
sees a clean disconnect.

### 4.3 Error mid-stream

```
event: axon.error
id: <counter>
data: {"trace_id":<u64>,"step":"<offending_step>","error":"<message>","recoverable":false}

```

Server then closes. Client decides whether to retry (EventSource's
default exponential-backoff reconnect kicks in if not stopped).

### 4.4 Keepalive (D6)

```
: keepalive
\n
```

(SSE comment line, single colon at start; W3C spec compliant.)

Emitted every `keepalive` duration. Default 15s. Stops on flow
completion or client disconnect.

### 4.5 Retry hint (initial event)

First event in every SSE response includes the W3C `retry:` directive:

```
retry: 5000

```

Telling EventSource clients to wait 5s before reconnecting if the
stream drops mid-flight. Adopters with strict reconnect SLAs override
via future `axonendpoint.retry_hint:` field (out of scope for 30).

### 4.6 Multiplexing semantics

A single `axonendpoint POST /endpoint` request maps to a single SSE
stream that ends with a single completion event. Multiple concurrent
clients to the same endpoint get **independent streams** (no shared
EventBus topic at this layer — that's the two-stage path's territory).

---

## 5. Type-checker rules (30.c, D3)

### 5.1 Trigger condition

When the Python type-checker walks an `AxonEndpointDefinition` whose
`transport` field equals `"sse"`:

1. Resolve the `execute:` field → the target flow's `FlowDefinition` node.
2. Walk the flow body + its tool dependencies.
3. Assert AT LEAST ONE of:
   - **(a)** Some step declares `output: Stream<T>` for any `T`.
   - **(b)** Some tool reachable from the flow declares
     `effects: [stream:<policy>]` for any of the 4 policies.
   - **(c)** Some step body contains `perform Stream.Yield(...)` (Fase 23
     algebraic effect operation; the type-checker walks the effect surface
     introduced in Fase 23.b).

### 5.2 Failure message shape

When none of (a)/(b)/(c) hold, the type-checker raises
`AxonTypeError` with:

```
[line N, col M]: axonendpoint 'Live' declares transport: sse, but its execute flow 'Plain' does not produce a Stream<T>.

  --> contract.axon:N:M
   |
 N | axonendpoint Live {
   |     ^^^^^^^^^^^^^^^^
   |
   = note: transport: sse requires the execute flow to produce streaming output
   = help: either
       (a) change the flow's step output to `output: Stream<Token>`, or
       (b) add `effects: [stream:drop_oldest]` (or another policy) to the tool the flow uses, or
       (c) emit chunks via `perform Stream.Yield(<value>)` inside the flow body,
       (d) drop `transport: sse` and let the endpoint return JSON normally
   = see: docs/ADOPTER_STREAMING.md § Type-checker enforcement
```

Uses Fase 28.d source-context block + Fase 28.e smart-suggest hint
infrastructure (already shipped). Format passes through the existing
`SourceSnippet` rendering.

### 5.3 Negative test cases pinned in corpus

The fixture corpus includes negative entries that the type-checker MUST
reject. The Python test pack parametrizes over them and asserts the
exact failure message contains the expected substring.

### 5.4 Backwards compat carve-out

When `transport` is absent (default `json`), the type-checker performs
NO additional validation beyond the existing pre-Fase-30 axonendpoint
checks. Adopters with no `transport` field see zero behavior change.

---

## 6. Runtime behavior (30.d + 30.e + 30.f)

### 6.1 Decision matrix

| `transport` declared | Flow has stream effect | Client `Accept: text/event-stream` | Server response |
|---|---|---|---|
| absent (default `json`) | no | any | `Content-Type: application/json` |
| absent | yes | absent / `*/*` / `application/json` | `Content-Type: application/json` (legacy) |
| absent | yes | `text/event-stream` | `Content-Type: text/event-stream` (D4 content-nego fallback) |
| `json` (explicit) | any | any | `Content-Type: application/json` (D5 declared wins) |
| `sse` | yes | any | `Content-Type: text/event-stream` (D5 declared wins) |
| `sse` | **no** (would be unreachable) | any | unreachable — type-checker (D3) rejects this combo at compile time |
| `ndjson` | yes | any | `Content-Type: application/x-ndjson` (placeholder per D2; ships in future Fase, emits warning header `X-Axon-NDJSON-Reserved: true`) |

### 6.2 SSE handler implementation skeleton

```rust
async fn execute_sse_handler(
    state: SharedState,
    headers: HeaderMap,
    payload: ExecuteRequest,
) -> Result<Sse<impl Stream<Item = Result<axum::response::sse::Event, Infallible>>>, StatusCode> {
    // 1. Authn + flow lookup + version pinning (same as execute_handler).
    // 2. Spawn the flow execution in a background task; channel its
    //    per-step tokens into an mpsc receiver.
    // 3. Spawn a keepalive ticker per `keepalive` duration on a parallel
    //    select! arm; merge keepalive comments into the SSE stream.
    // 4. Map each token → Event { event: "axon.token", id: <counter>, data: <json> }.
    // 5. On flow completion → Event { event: "axon.complete", data: <final envelope> }.
    // 6. On error mid-stream → Event { event: "axon.error", ... } then close.
    // 7. On client disconnect → abort the background flow task (D11 ratified
    //    in Fase 11.a — cancel-safety is mandatory for stream effects).
}
```

(Pseudo-code; full implementation in 30.d.)

### 6.3 Client-disconnect cleanup (cancel-safety)

When the SSE consumer disconnects (closes the EventSource), the server:
- Cancels the background flow task via `tokio::task::JoinHandle::abort()`
- Cancels the keepalive ticker
- Releases backend rate-limit quota holds (the algebraic effect handler's
  `abort` operation from Fase 23.b fires)
- Records a `trace_status: cancelled` entry in the trace store
- Emits an audit-log entry `client_disconnect`

This is the Fase 11.a D11 cancel-safety contract; Fase 30 enforces it
at the HTTP boundary explicitly.

### 6.4 Concurrency + backend rate limits

Each SSE request holds one backend execution slot. If the flow's tool
declares `effects: [stream:drop_oldest]` and the buffer fills before
the backend produces the next token, the algebraic effect handler
applies the policy as it does today (Fase 11.a runtime). The HTTP
layer is transparent to backpressure decisions.

---

## 7. Backwards compatibility (D9 from Fase 28 still ratified)

| Adopter scenario | Behavior before Fase 30 | Behavior after Fase 30 |
|---|---|---|
| `axonendpoint X { method: POST execute: F }` without `transport` field | JSON response | JSON response (D1 default; unchanged) |
| `axonendpoint X { ... transport: sse }` (was silently ignored before) | JSON response | SSE response (NEW — was previously a parsed-but-dropped no-op) |
| Flow with `effects: [stream:...]`, client sends `Accept: text/event-stream` | JSON response | SSE response (D4 content-nego) |
| Two-stage `POST /v1/execute/stream` + `GET /v1/events/stream?topic=...` | Works | Works unchanged (D8 preserved) |
| Existing v1.20.0 `parse()` / `parse_with_recovery()` API consumers | Works | Works unchanged |
| Existing v1.20.0 deployed axonendpoints (no source change) | JSON | JSON (no change unless adopter sends `Accept: text/event-stream`) |

The ONLY behavior change for adopters who don't edit their source is:
clients that explicitly send `Accept: text/event-stream` on a
stream-effect flow now get SSE. If this is undesirable, the adopter
declares `transport: json` explicit and the negotiation is suppressed
(D5).

---

## 8. Tests target

| Category | Tests | Stack |
|---|---|---|
| Parser positive: `transport: {json,sse,ndjson}` accepted | 6 | Py + Rust = 12 |
| Parser negative: `transport: bogus` rejected with suggest hint | 3 | Py + Rust = 6 |
| Parser: `keepalive: {5s,15s,30s,60s}` accepted | 4 | Py + Rust = 8 |
| Parser: `keepalive` without `transport: sse` warning | 1 | Py + Rust = 2 |
| Drift-gate corpus parametrized | 10 entries × 4 expected fields | Py = 40, Rust = 40 |
| Type-checker: positive (stream-output flow + transport: sse) | 5 | Py |
| Type-checker: negative (non-stream flow + transport: sse) | 5 | Py |
| Type-checker: edge cases (multi-step, ots-apply, listen) | 5 | Py |
| Runtime SSE wire format: per-step token event shape | 4 | Rust |
| Runtime: completion event | 2 | Rust |
| Runtime: error mid-stream | 3 | Rust |
| Runtime: keepalive interval | 2 | Rust |
| Runtime: client-disconnect cancel-safety | 3 | Rust |
| Content-negotiation matrix (transport × Accept × has-stream) | 18 | Rust |
| 100-iter deterministic fuzz: malformed `transport`/`keepalive` recovery | 1 (parametrized 100) | Py + Rust |
| **Total** | **~120 unique + drift parametrized** | **cross-stack** |

---

## 9. Out of scope (deferred to future Fases)

- **WebSocket transport** (`transport: ws`): bidirectional, frame-based,
  persistent connection. Different semantic profile (client sends back
  messages mid-stream — `axonendpoint` is currently uni-directional).
  Fase 31 candidate.
- **gRPC server-streaming**: requires protobuf surface + service definition
  generation. Out of scope as gRPC is not a current axon-lang transport
  primitive. Enterprise-only candidate.
- **NDJSON wire emission**: namespace reserved in D2 enum (parser accepts
  `transport: ndjson`); wire implementation deferred. When shipped, the
  shape will be `application/x-ndjson` with one JSON object per line, no
  SSE event-name framing. Future Fase.
- **HTTP/2 trailers** for completion metadata: adopters who want
  steam-end metadata in headers rather than a final SSE event. HTTP/2
  trailers are an emerging surface; defer pending adopter demand.
- **WebSocket-style binary frame transport** for non-text payloads
  (audio chunks, image tiles, telemetry binary frames): Fase 11.b
  ws_binary accumulator handles ingress; egress transport for binary
  is a separate fase.
- **Per-step event-name customization** (`event: my.custom.token` instead
  of `event: axon.token`): canonical event names are fixed in this Fase
  for cross-deployment client compat. Future adopter-config knob.
- **Server-side filtering / windowing** (e.g., "emit every Nth token"
  for slow clients): the stream effect runtime handles backpressure via
  the 4 policies; rate-shaping is out of scope at the HTTP layer.

---

## 10. D-letters proposed (8) — awaiting bloque ratification

### D1 — Default transport = `json`

**Proposal:** When the `transport` field is absent on an `axonendpoint`,
the server returns `application/json` exactly as today. Backwards-compat
preserved for every existing axonendpoint without source change.

**Recommendation:** Ratify. Identical to Fase 28's D9 discipline:
new features are opt-in, never breaking existing adopters.

### D2 — Closed enum `transport: {json, sse, ndjson}`

**Proposal:** Parser accepts exactly these three values; any other
value is a parse error with smart-suggest hint (Fase 28.e). Extension
requires a compiler patch.

**Recommendation:** Ratify. Open-ended values invite incompatible
adopter implementations. `ndjson` is reserved namespace; wire emission
ships in a future Fase but the parser accepts the value today so the
namespace is stable.

### D3 — Type-checker enforcement: `transport: sse` requires Stream-producing flow

**Proposal:** `transport: sse` triggers a compile-time check that
the `execute:` flow produces a `Stream<T>` (via `output: Stream<T>`,
or a tool with `effects: [stream:<policy>]`, or `perform Stream.Yield(...)`
in a step body). Compile error with source-context block + smart-suggest
remediation when violated.

**Recommendation:** Ratify. Closes the runtime-silent-failure path
that pure content-negotiation (Option B) leaves open. Compliance officers
auditing the source see the contract.

### D4 — Content-negotiation fallback safety net

**Proposal:** When `transport` is absent (default json) AND the flow
has a stream effect AND the client sends `Accept: text/event-stream`,
the server auto-promotes to SSE. This is the "I forgot to edit my
axonendpoint" backwards-compat upgrade path.

**Recommendation:** Ratify. Adopters can flip behavior at the client
level without a redeploy; existing JSON-only clients keep working.

### D5 — Declared transport wins over Accept header

**Proposal:** When `transport: sse` OR `transport: json` is declared
explicitly, the server honors the declaration regardless of the client's
`Accept` header. Only the absent-default case (D4) negotiates.

**Recommendation:** Ratify. Explicit declaration is intent; honoring
Accept would override intent. Adopters who want negotiation simply
omit the field.

### D6 — Keepalive default 15s + closed enum `{5s, 15s, 30s, 60s}`

**Proposal:** `keepalive` is an optional duration field on axonendpoints
with `transport: sse`. Accepted values are the 4 fixed durations
covering the common LB idle-timeout window. Default 15s.

**Recommendation:** Ratify. Default sized for AWS ALB 60s idle timeout
with >4× margin. Closed enum prevents adopter typos like
`keepalive: 15` (no unit) or `keepalive: 90s` (too sparse for tight LBs).

### D7 — Cross-stack byte-identical (extends Fase 28's D7)

**Proposal:** Python axon-lang parser and Rust axon-frontend parser
produce byte-identical AST for `transport` + `keepalive` fields on
every input in the shared `tests/fixtures/fase30_transport/corpus.json`
corpus. Locked in CI by the existing drift-gate workflow pattern.

**Recommendation:** Ratify. Same discipline as Fase 28; carries the
existing test infra forward.

### D8 — Two-stage `/v1/execute/stream` + `/v1/events/stream?topic=...` preserved

**Proposal:** The existing two-stage pub/sub pattern stays operational.
Adopters who need multi-consumer fan-out (one inference, N dashboards
consuming the same stream concurrently) keep using it. Fase 30 adds
the single-shot path; it doesn't remove the two-stage path.

**Recommendation:** Ratify. Different semantic profiles serve different
adopter needs; coexistence is honest.

---

## 11. Why minor release (SemVer minor bump)

New observable surfaces (`transport` + `keepalive` fields, SSE wire
format, content-negotiation, type-checker enforcement) are **pure
additions**. Adopters without source change see zero behavior delta
(D1 + D9). The minor-bump signals new features without breaking changes.

Per versioning discipline (`feedback_versioning_discipline.md`): the
target version is "next available minor release after v1.20.0", not
hardcoded. Expected v1.21.0 if no v1.20.x patches intervene; could
shift to v1.22.0 if a v1.21.0 patch ships first. Fase content is
stable; version number adapts to cadence.

---

## 12. Migration path

### 12.1 For adopters who want SSE on a deployed axonendpoint

```axon
// Before — runs through /v1/execute, returns JSON
axonendpoint LiveDeliberation {
    method:  POST
    path:    "/live"
    execute: orchestrate    // flow with `effects: [stream:drop_oldest]`
}

// After — POST /live returns text/event-stream directly
axonendpoint LiveDeliberation {
    method:    POST
    path:      "/live"
    execute:   orchestrate
    transport: sse          // ← single field opt-in
    keepalive: 15s          // ← optional; default 15s
}
```

The type-checker verifies that `orchestrate` produces a Stream<T> at
compile time. Redeploy via the existing `axon deploy` flow. Adopter
EventSource clients connect to `POST /live`; no other code change.

### 12.2 For adopters using EventSource without changing the source

If the deployed flow has `effects: [stream:...]` and the client sends
`Accept: text/event-stream`, the content-negotiation fallback (D4)
auto-upgrades. No `.axon` change needed. The adopter pays a
"silent contract" tax — compliance review can't see the SSE behavior
in the source — but it works.

### 12.3 For adopters who DO NOT want SSE on a stream-effect flow

Explicit opt-out: declare `transport: json`. Server respects the
declaration even when clients send `Accept: text/event-stream` (D5).

```axon
axonendpoint BatchExport {
    method:    POST
    path:      "/batch"
    execute:   build_report    // flow with stream effect but we want batched output
    transport: json            // ← explicit opt-out
}
```

### 12.4 For adopter clients consuming SSE

Standard W3C EventSource:

```javascript
const es = new EventSource('/live', { withCredentials: true });
es.addEventListener('axon.token', (e) => {
    const { step, token } = JSON.parse(e.data);
    appendToUI(step, token);
});
es.addEventListener('axon.complete', (e) => {
    const final = JSON.parse(e.data);
    finalize(final);
    es.close();
});
es.addEventListener('axon.error', (e) => {
    const err = JSON.parse(e.data);
    showError(err);
    es.close();
});
```

Python adopter clients use `httpx` or `sseclient-py`:

```python
import httpx
with httpx.stream("POST", "/live", json={"input": ...}) as r:
    for line in r.iter_lines():
        if line.startswith("event: axon.token"):
            ...
```

(Full recipes in `docs/ADOPTER_STREAMING.md` ship in 30.h.)

---

## 13. How to apply (when shipped)

When an adopter reports "my SSE doesn't work" / "POST returns JSON not
chunks" / "EventSource sees no events", check:

1. **Does the axonendpoint declare `transport: sse`?**
   - If no → either add it OR have the client send `Accept: text/event-stream`
     (D4 fallback)
2. **Does the execute flow produce a Stream<T>?**
   - If no → the type-checker should have rejected `transport: sse`
     at compile time. If it didn't, that's a Fase 30 bug — file an
     issue on axon-lang.
3. **Is the keepalive default surviving the LB idle timeout?**
   - If client sees connection reset after 15-60s with no data → adopter's
     LB cut the connection. Lower keepalive (`keepalive: 5s`) or extend
     LB idle timeout.
4. **Is the client EventSource attaching the right event-name listeners?**
   - axon emits `axon.token` / `axon.complete` / `axon.error`. A naive
     `es.onmessage = ...` listener catches only unnamed `data:` events
     and misses everything axon emits. Point the adopter at the recipe
     in `ADOPTER_STREAMING.md` § Client integration.

---

## See also

- [Plan vivo Fase 28 — Adopter Diagnostic Robustness](fase_28_adopter_diagnostic_robustness.md)
  — shipped infrastructure (source-context blocks, smart-suggest, drift gate)
  that Fase 30 reuses for its new compile-error surfaces.
- [Plan vivo Fase 29 — Enterprise Diagnostic Enhancements](fase_29_enterprise_diagnostic_enhancements.md)
  — sibling enterprise-only follow-on; Fase 30 is OSS-classified
  (every adopter benefits), Fase 29 is ENTERPRISE-only.
- [`STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — Fase 11.a effect catalog
  doc that this Fase extends with HTTP wire format.
- [Reference: v1.19.x parser patches](../axon-lang/docs/...) (memory entry)
  — the trilogy that motivated Fase 28 and surfaced the broader pattern
  Fase 30 also addresses: "language has primitives the runtime doesn't
  fully wire".

---

*This document is the canonical Fase 30 plan vivo. Status updates are
applied in place as sub-fases ship. Cross-link from the README CLI
Usage section in 30.h once `transport:` is publicly documented.*
