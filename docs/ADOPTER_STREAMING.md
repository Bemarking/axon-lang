# AXON Adopter Streaming Guide

> **Audience:** engineers integrating an `axonendpoint`-fronted HTTP service
> that emits Server-Sent Events (SSE) or other streaming wire formats from
> a flow with `Stream<T>` algebraic effects.
>
> **Scope:** every transport surface introduced by **Fase 30 / axon-lang
> v1.21.0** — the new `transport:` and `keepalive:` axonendpoint fields,
> the `POST /v1/execute/sse` single-shot route, content-negotiation
> fallback on `POST /v1/execute`, type-checker enforcement, and the W3C
> SSE wire format axon emits.
>
> **Founder principle:** *axon ships language primitives, not adopter
> patches.* If you can't express your streaming wire shape as a
> declaration on the axonendpoint, that's a gap in axon-lang — open an
> issue. Adopters should never have to hand-roll SSE encoding for
> deployed flows.

---

## Table of Contents

1. [What changed in v1.21.0](#what-changed-in-v1210)
2. [Quick start](#quick-start)
3. [Two streaming patterns: single-shot vs two-stage](#two-streaming-patterns-single-shot-vs-two-stage)
4. [The `transport:` and `keepalive:` axonendpoint fields](#the-transport-and-keepalive-axonendpoint-fields)
5. [SSE wire format specification](#sse-wire-format-specification)
6. [Content-negotiation fallback semantics](#content-negotiation-fallback-semantics)
7. [Type-driven default transport (Fase 31, v1.22.0+)](#type-driven-default-transport-fase-31-v1220)
8. [Type-checker enforcement rules](#type-checker-enforcement-rules)
9. [Common compile errors + fixes](#common-compile-errors--fixes)
10. [Backwards compatibility matrix](#backwards-compatibility-matrix)
11. [Production deployment cookbook](#production-deployment-cookbook)
12. [Troubleshooting checklist](#troubleshooting-checklist)
13. [Client-side EventSource recipe](#client-side-eventsource-recipe)
14. [LSP / IDE integration recipe](#lsp--ide-integration-recipe)
15. [CI integration recipe](#ci-integration-recipe)
16. [Cross-stack contract: Python ↔ Rust](#cross-stack-contract-python--rust)
17. [Real-time streaming (Fase 33, v1.24.0+)](#real-time-streaming-fase-33-v1240)
18. [Production-path activation (Fase 33.x, v1.25.0+)](#production-path-activation-fase-33x-v1250)
19. [Universal algebraic streaming (Fase 33.y, v1.26.0+)](#universal-algebraic-streaming-fase-33y-v1260)
20. [Where to file bugs](#where-to-file-bugs)

---

## What changed in v1.21.0

Before v1.21.0, axon's `axonendpoint` declarations carried no information
about HTTP wire format. Every deployed flow's `POST /v1/execute` handler
returned a single JSON response, even when the underlying flow emitted a
`Stream<T>` algebraic effect. Adopters who needed SSE were forced through
the two-stage `POST /v1/execute/stream` + `GET /v1/events/stream`
pattern with no way to declare "this endpoint speaks SSE natively".

v1.21.0 closes that loop:

| Surface | Before (v1.20.x) | After (v1.21.0) |
|---|---|---|
| axonendpoint transport declaration | none — `transport: sse` was silently parsed and dropped | First-class `transport: {json,sse,ndjson}` enum on every axonendpoint |
| Keepalive comment emission | none — long flows died at LB idle-timeout | First-class `keepalive: {5s,15s,30s,60s}` enum; default 15s when SSE |
| Single-shot SSE route | not implemented | `POST /v1/execute/sse` returns Content-Type: text/event-stream directly |
| Content negotiation | not implemented | `POST /v1/execute` auto-promotes to SSE when adopter sends `Accept: text/event-stream` AND flow has stream effects |
| Type-checker enforcement | none | `transport: sse` on a flow that doesn't produce a stream → compile error with 4-option remediation hint |
| Two-stage pattern | only option for SSE | preserved verbatim (D8) — adopters who built on it keep working |

**Backwards compatibility (D9 ratified):** every existing `POST /v1/execute`
client that does NOT send `Accept: text/event-stream` continues to get
the legacy JSON response shape verbatim. The new behavior is opt-in
through either the axonendpoint declaration or the explicit Accept header.

---

## Quick start

1. Declare the transport on the axonendpoint:

```axon
flow Transcribe(audio: Stream<Bytes>) {
    step Analyze {
        given: audio
        ask:   "summarise"
        apply: ingest_audio
    }
}

tool ingest_audio {
    provider: local
    timeout:  30s
    effects:  <stream:drop_oldest>
}

axonendpoint LiveTranscribe {
    method:    POST
    path:      "/v1/live/transcribe"
    execute:   Transcribe
    transport: sse
    keepalive: 15s
}
```

2. Deploy:

```bash
axon deploy src/live_transcribe.axon
```

3. The deployed flow is now reachable at two routes:

| Route | Behavior |
|---|---|
| `POST /v1/execute/sse` with `{"flow_name": "Transcribe", "backend": "..."}` | Always returns `Content-Type: text/event-stream` — the response body IS the SSE stream |
| `POST /v1/execute` with `{"flow": "Transcribe", ...}` | Returns SSE because the axonendpoint declared `transport: sse` (D5 force-promote) |

4. Consume from a browser:

```javascript
const es = new EventSource("/v1/execute/sse", {
    /* EventSource cannot send POST; use fetch + readable stream OR
       configure a proxy that converts GET → POST upstream. */
});
es.addEventListener("axon.token",    (e) => console.log("chunk:",   JSON.parse(e.data)));
es.addEventListener("axon.complete", (e) => console.log("done:",    JSON.parse(e.data)));
es.addEventListener("axon.error",    (e) => console.error("error:", JSON.parse(e.data)));
```

For a server-side or non-browser client, see [Client-side EventSource recipe](#client-side-eventsource-recipe).

---

## Two streaming patterns: single-shot vs two-stage

axon ships **two** SSE patterns. Pick the one whose semantics match your
deployment. Both are preserved at the language and runtime level (D8
ratified — the two-stage pattern is not deprecated).

### Pattern A — Single-shot (v1.21.0, recommended for greenfield)

```
HTTP request    │ POST /v1/execute/sse           {"flow_name": "F", ...}
HTTP response   │ Content-Type: text/event-stream
                │
                │ retry: 5000
                │
                │ event: axon.token
                │ id: 1
                │ data: {"step":"S1","trace_id":42,"token":"hello"}
                │
                │ event: axon.token
                │ id: 2
                │ data: {"step":"S1","trace_id":42,"token":"world"}
                │
                │ event: axon.complete
                │ id: 3
                │ data: {"trace_id":42,"flow":"F","success":true,...}
```

**One HTTP call** → one streaming response. Client connects once,
receives all events on the same connection, server closes when the flow
finishes. Use this when:

- Your front-end speaks SSE directly via `EventSource` (or `fetch` with a
  `ReadableStream`).
- Your load balancer + reverse proxy keep long-lived connections alive
  (with the `keepalive:` field configured below).
- You don't need a separate consumer process to attach to the stream
  later.

### Pattern B — Two-stage publish + subscribe (v1.15.0+, preserved)

```
HTTP request 1  │ POST /v1/execute/stream        {"flow_name": "F", ...}
HTTP response 1 │ Content-Type: application/json
                │ {"trace_id": 42, "consume_url":
                │  "/v1/events/stream?topic=flow.stream.42"}

HTTP request 2  │ GET /v1/events/stream?topic=flow.stream.42
HTTP response 2 │ Content-Type: text/event-stream
                │ ...same SSE wire format as Pattern A...
```

**Two HTTP calls** — the producer is detached from the consumer. Use this
when:

- The process emitting the stream is not the same process consuming it
  (e.g. multi-region edge fan-out).
- You want to attach multiple consumers to the same stream.
- You need to publish first and have the consumer subscribe later (within
  the trace retention window).

### When to pick which

| You need | Pick |
|---|---|
| Browser SSE consumption | Pattern A |
| Backend-to-backend single stream | Pattern A |
| Fan-out to multiple consumers | Pattern B |
| Decoupled producer / consumer | Pattern B |
| Replay-after-disconnect via `Last-Event-ID` | Pattern A (currently — Pattern B candidate for a future fase) |

---

## The `transport:` and `keepalive:` axonendpoint fields

Two closed-enum fields control the wire shape of every axonendpoint.

### `transport: {json, sse, ndjson}`

| Value | Default? | Wire format on `/v1/execute` |
|---|---|---|
| `json` | yes (when field omitted, D1 ratified) | Single `Content-Type: application/json` response (unchanged from v1.20.x) |
| `sse` | no | Server-Sent Events stream — same shape as `/v1/execute/sse` |
| `ndjson` | no | Reserved for a future fase (parser accepts; runtime emits SSE today — the namespace is reserved so adopters who declare `ndjson` get forwards-compat at the language level) |

The enum is **closed** — `transport: streaming` or any other value is a
compile error with a smart-suggest hint.

### `keepalive: {5s, 15s, 30s, 60s}`

Controls the interval between `: keepalive\n\n` W3C SSE comment lines.
The comment is a no-op at the EventSource layer (the client silently
discards it) but counts as wire activity for load balancers, keeping the
TCP connection alive across idle periods inside the flow.

| Value | Use when |
|---|---|
| `5s` (omit-default falls to `15s`) | Aggressive LB timeouts (e.g. some CDN tunnels with 30s default) |
| `15s` | **D6 default** — comfortable below AWS ALB 60s, Cloudflare 100s, nginx 60s defaults |
| `30s` | Long flows on permissive LB configs |
| `60s` | Low-frequency telemetry where extra wire traffic costs more than reconnects |

The default is 15s. Override only when your deployment topology demands
it. The enum is **closed** — `keepalive: 1m` or `keepalive: 10s` is a
compile error.

### Where the fields go

```axon
axonendpoint Live {
    method:    POST          // standard axonendpoint fields
    path:      "/v1/live"
    execute:   StreamFlow
    transport: sse           // ← new in v1.21.0
    keepalive: 15s           // ← new in v1.21.0; only meaningful when transport is sse|ndjson
    shield:    none          // shield, retries, timeout, compliance unchanged
}
```

Field order is irrelevant — the parser accepts any permutation.

---

## SSE wire format specification

Every SSE response axon emits — whether single-shot Pattern A or two-stage
Pattern B — conforms to the same wire spec. Verify the events your client
sees match this contract.

### Header

```
Content-Type: text/event-stream
```

### Event 0 — Retry directive

Every SSE response begins with the W3C `retry:` reconnect hint, on its
own line, with no `id:` (per W3C convention for retry-only events).

```
retry: 5000
```

5000 milliseconds is the default reconnect interval EventSource will use
if the connection drops. Your client can override by sending its own
`Last-Event-ID` header on reconnect.

### Event N — Per-step token

For each chunk of streaming output a step produces:

```
event: axon.token
id: 1
data: {"step":"<step_name>","trace_id":<int>,"token":"<text>","timestamp_ms":<int>}
```

- `id:` is a **strictly monotonic non-zero u64** per response. EventSource
  exposes the most recent id on the client side; resume support via
  `Last-Event-ID` is the standard W3C mechanism (server-side replay lands
  in a future fase — currently the id is observable but not
  resume-enforced).
- `step` is the axon flow step that produced the chunk.
- `token` is the user-facing text — already decoded UTF-8, no
  base64.
- `timestamp_ms` is the wall-clock time the chunk was produced, useful
  for client-side latency calculations.

### Event N+1 — Final completion envelope

```
event: axon.complete
id: <last>
data: {"trace_id":<int>,"flow":"<name>","backend":"<provider>",
       "steps_executed":<int>,"tokens_input":<int>,"tokens_output":<int>,
       "latency_ms":<int>,"success":<bool>}
```

After this event the server closes the response. EventSource will then
trigger its reconnect policy unless you call `.close()`.

### Event N′ — Mid-stream error (rare)

If the flow fails mid-execution, the stream emits one error event and
closes:

```
event: axon.error
id: <n>
data: {"trace_id":<int>,"error":"<message>","recoverable":false}
```

`recoverable: false` is the default — the trace already failed; reconnect
will not retry the same trace. A future fase may introduce
`recoverable: true` for transient backend errors.

### Keepalive comment (W3C `comment line`)

During inactivity exceeding the configured `keepalive:` interval, the
server emits:

```
: keepalive
```

This is a comment line per W3C SSE §"comment line". `EventSource` clients
silently discard it. Intermediate proxies and load balancers see it as
wire activity and refrain from tearing the TCP connection down.

### Framing invariants

axon's SSE responses guarantee:

1. The `retry:` directive appears **exactly once**, **before** the first
   `event:` line.
2. Every `id:` field carries a strictly-monotonic non-zero u64 across
   the response.
3. No bare `\r` (CR) characters — only `\n` (LF) line endings. Mixed line
   endings would break some EventSource implementations on the wire.
4. The response body ends with `\n\n` (the W3C blank-line event
   separator).
5. `Content-Type: text/event-stream` is set on every 200 response from
   `/v1/execute/sse`, including the error path (a not-deployed flow
   still produces a wire-valid SSE error response, not a 404).

These invariants are gated by the
[Fase 30 conformance fuzz](../axon-rs/tests/fase30_sse_fuzz.rs) on every
PR; if any of them ever drift, the fuzz lane in
[`.github/workflows/fase_30_http_transport.yml`](../.github/workflows/fase_30_http_transport.yml)
turns red.

---

## Content-negotiation fallback semantics

The legacy `POST /v1/execute` route did NOT speak SSE before v1.21.0.
v1.21.0 introduces a strictly-additive negotiation layer with two
ratified rules:

### D5 — Declared transport always wins

If the axonendpoint declares `transport: sse|ndjson`, every `/v1/execute`
request for that flow returns SSE **regardless of the client's Accept
header**. Symmetrically, `transport: json` always returns JSON.

### D4 — Accept header as a fallback safety net

If the axonendpoint does NOT declare a transport (the default `json` is
in effect) AND the flow has stream effects (Stream<T> output, stream
effect tool, or `perform Stream.Yield`) AND the client sends
`Accept: text/event-stream` → the server promotes to SSE.

### Decision matrix

| axonendpoint declaration | flow has stream effect | `Accept` header | Response |
|---|---|---|---|
| `transport: sse` or `ndjson` | — | any | SSE (D5) |
| `transport: json` | — | any | JSON (D5) |
| absent / not declared | no | any | JSON (D9 backcompat) |
| absent / not declared | yes | absent or other | JSON |
| absent / not declared | yes | `text/event-stream` | SSE (D4) |

### Why a fallback layer at all

Adopters who upgrade from v1.20.x and start their clients sending the
new Accept header get SSE behavior without any axon source edits.
Adopters who want to opt out explicitly add `transport: json` to the
axonendpoint — the D5 declaration suppresses negotiation. Adopters who
want SSE always-on add `transport: sse` and never depend on the client's
Accept header to be set correctly.

---

## Type-driven default transport (Fase 31, v1.22.0+)

Fase 30 D4 + D5 require either an explicit declaration on the
axonendpoint OR an `Accept: text/event-stream` header from the client
to promote to SSE. After v1.21.x adoption surfaced an empirical
mismatch — the language's type system **internally inferred** SSE
for stream-effect flows yet refused to surface that inference at the
wire layer without one of the two opt-ins — Fase 31 closed the gap.

The new behavior is **opt-in via flag** in v1.22.0 (D6) and **flips
to default-on** in v2.0.0 (D9). See [MIGRATION_v1.22.md](MIGRATION_v1.22.md)
for the four-scenario migration recipe.

### The inference rule (D1)

```
implicit_transport(F, E) =
    declared_transport(E)         if declared(transport, E)
    "sse"                          if produces_stream(F) ∧ ¬declared(transport, E)
    "json"                         otherwise
```

The `produces_stream(F)` predicate is the 3-disjunct disjunction
from Fase 30.c (see § Type-checker enforcement rules below). When
the flag is on, the inference verdict drives the HTTP wire shape
directly — no `Accept:` header required, no source declaration
required.

### Compile-time warning `axon-W001`

When a flow has stream effects AND the axonendpoint omits the
`transport:` declaration, the compiler emits a non-fatal warning
at build time:

```
warning[axon-W001]: implicit `transport: sse` inferred from stream
effects on axonendpoint 'ChatEndpoint' (flow 'Chat' produces a
stream via step 'Generate' applies tool 'chat_token_stream' with
effects `<stream:drop_oldest>`). Declare `transport: sse` to
silence this warning and lock in SSE behavior, or `transport:
json` to opt out and keep the legacy JSON wire format. When
`strict_type_driven_transport: true`, this endpoint emits SSE on
/v1/execute by default.
```

The warning is **rate-limited** — one per axonendpoint per build
pass — and **suppressed** when:

- The axonendpoint declares any explicit `transport:` value.
- The flow does not produce a stream.
- The `execute:` flow doesn't resolve (orphan endpoint — a
  separate error already fires).

Strict mode (Fase 28.h `--strict`) promotes the warning to an
error. CI pipelines that want the strongest signal turn `--strict`
on.

### Runtime diagnostic header `X-Axon-Stream-Available`

When `/v1/execute` serves a JSON response for a flow that **does**
have stream effects (because the flag is off OR because the adopter
opted out via `transport: json`), the response carries:

```
X-Axon-Stream-Available: 1; reason=<flag_off|declared_json>;
                            flow=<name>;
                            opt_in=transport:sse,Accept:text/event-stream
```

The `reason` value is a closed set per **D5**:

- `flag_off` — the strict flag is off AND the client sent no
  `Accept:` header. The opt-in is one of: flip the flag, declare
  `transport: sse`, or send `Accept: text/event-stream`.
- `declared_json` — the adopter explicitly declared `transport:
  json` (D3 opt-out). The header still fires so clients see the
  trade-off — the language never silently overrides the adopter's
  choice.

Header is **never** emitted on SSE responses (the wire is already
streaming), on JSON responses for non-stream-effect flows (nothing
to surface), or on orphan endpoints (separate error path).

### Opt-in surfaces

The strict flag is opt-in via two converging surfaces (D6 + D7
cross-stack consistency):

```bash
# Surface 1 — CLI flag (k8s / docker / systemd)
axon serve --strict-type-driven-transport

# Surface 2 — env var (12-factor app)
export AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1
axon serve
```

Truthy alphabet: `1`, `true`, `yes`, `on` (case-insensitive,
whitespace-trimmed). The CLI flag wins when both are set. Default
is `false` in v1.22.x; flips to `true` in v2.0.0.

### Decision matrix (4 dimensions × 16 cells)

| strict | endpoint decl | stream effect | `Accept:` SSE | response |
|---|---|---|---|---|
| any | `json` (D3) | any | any | JSON |
| any | `sse` / `ndjson` | any | any | SSE |
| OFF (default) | absent | no | any | JSON |
| OFF | absent | yes | no | JSON (with `X-Axon-Stream-Available: reason=flag_off`) |
| OFF | absent | yes | yes | SSE (Fase 30 D4) |
| ON | absent | no | any | JSON |
| **ON** | **absent** | **yes** | **any** | **SSE (Fase 31 D1)** |

The bottom-right row is the new Fase 31 behavior. The middle four
rows preserve Fase 30 verbatim — D8 backwards-compat is absolute
when the flag is off.

### Cross-stack contract (D7)

The env var name `AXON_STRICT_TYPE_DRIVEN_TRANSPORT` is the
canonical cross-stack handshake. Python `axon serve` and Rust
`axon-rs` accept it byte-identically. A 100-bucket × 10-iteration
deterministic fuzz lane in CI confirms the inference function on
both stacks produces byte-identical verdicts under adversarial
input.

---

## Type-checker enforcement rules

The type-checker enforces a **soundness invariant** at compile time
(Fase 30.c, plan vivo §5):

> If an axonendpoint declares `transport: sse` or `transport: ndjson`,
> the flow named in `execute:` MUST produce a stream.

A flow "produces a stream" iff any of the three disjuncts holds:

- **(a) type-level** — any step in the flow has `output: Stream<T>` for some `T`.
- **(b) effect-level** — any step uses a tool whose `effects:` list includes
  `<stream:<policy>>` (one of the four ratified backpressure policies).
- **(c) operational** — any step explicitly `perform`s a `Stream.Yield(...)` effect.

The check is performed by `axon/compiler/type_checker.py` (and a
forthcoming Rust mirror in axon-frontend). The predicate is formal and
walks the flow AST + a symbol table for tool lookups; it is sound but
intentionally conservative — an adopter who threads a `Stream<T>` through
N flows where only the root one declares the type may need to declare the
effect explicitly on the leaf flow. See [Common compile errors + fixes]
below for the canonical remediation.

---

## Common compile errors + fixes

### Error 1 — `transport: sse` on a non-streaming flow

```
error: axonendpoint 'Live' declares `transport: sse` but its execute
  flow 'Compute' does not produce a stream. `transport: sse|ndjson`
  requires the flow to emit Stream<T> tokens (Fase 30.c). Four ways
  to satisfy the contract:
    1. Add a step with `output: Stream<T>` for some T.
    2. Use a tool whose `effects:` includes `<stream:<policy>>`.
    3. Add `perform Stream.Yield(...)` in a step body.
    4. Drop `transport: sse` and let the flow return a single JSON value.
```

**Fix:** pick whichever of the four options matches your design intent.
Most adopters reach for option 2 — declare the streaming effect on the
tool that produces the chunks:

```axon
tool emit_chunks {
    provider: local
    effects:  <stream:drop_oldest>   // ← option 2
}

flow Compute() {
    step Emit {
        apply: emit_chunks
    }
}

axonendpoint Live {
    method:    POST
    path:      "/v1/live"
    execute:   Compute
    transport: sse                   // now compiles
}
```

### Error 2 — Unknown transport value

```
error: Unknown transport value 'streaming' in axonendpoint 'Live'.
       Valid: json, sse, ndjson. Did you mean `sse`?
```

**Fix:** the closed enum is `{json, sse, ndjson}`. The smart-suggest hint
(Fase 28.e) catches near-misses automatically.

### Error 3 — Invalid keepalive value

```
error: Unknown keepalive value '10s' in axonendpoint 'Live'.
       Valid: 5s, 15s, 30s, 60s. Did you mean `5s`?
```

**Fix:** the closed enum is `{5s, 15s, 30s, 60s}`. If you genuinely need
a different interval, open an issue — the enum is conservative by design
to keep adopter configurations interoperable across deployments.

### Error 4 — Missing colon (v1.19.4 surface, applies here too)

```
error: expected `:` after `transport` keyword in axonendpoint 'Live'.
       Did you mean `transport: sse`?
```

**Fix:** every axonendpoint field is `key: value`. The colon is required.

---

## Backwards compatibility matrix

| Adopter shape pre-v1.21.0 | After upgrading to v1.21.0 |
|---|---|
| `axonendpoint` with no `transport` field | Unchanged — `transport: json` is the default (D1 ratified) |
| `axonendpoint` with `transport: sse` (was silently dropped in v1.20.x) | NOW emits SSE — adopters who declared this intentionally get the behavior they wanted |
| Two-stage pattern (`/v1/execute/stream` + `/v1/events/stream`) | Unchanged — preserved verbatim (D8 ratified) |
| `POST /v1/execute` clients without `Accept: text/event-stream` | Unchanged — JSON response (D9 ratified) |
| `POST /v1/execute` clients with `Accept: text/event-stream` on a flow with stream effects | NOW gets SSE auto-promotion (D4) — set `transport: json` on the axonendpoint to suppress |
| Clients consuming SSE via the existing two-stage pattern | Unchanged — same wire format, same events, same envelope |

The **only behavior change** for unedited adopter source code:
`POST /v1/execute` requests with `Accept: text/event-stream` against a
flow that emits stream effects now get SSE instead of JSON. To suppress,
add `transport: json` explicitly on the axonendpoint.

---

## Production deployment cookbook

### AWS Application Load Balancer

```yaml
# ALB target group → axon-rs server
HealthCheck:
  Path: /v1/health
  IntervalSeconds: 30
TargetGroupAttributes:
  - Key: deregistration_delay.timeout_seconds
    Value: "60"
  - Key: stickiness.enabled
    Value: "false"
# ALB idle timeout (default 60s) — keepalive: 15s comfortably below.
LoadBalancerAttributes:
  - Key: idle_timeout.timeout_seconds
    Value: "60"
```

axonendpoint declaration:

```axon
axonendpoint Live {
    transport: sse
    keepalive: 15s   // < 60s ALB idle timeout
}
```

### Cloudflare (proxy + CDN)

Cloudflare's free + pro plans buffer SSE responses by default. Set the
`Cache-Control: no-cache, no-transform` header (axon-rs sets this on
every `/v1/execute/sse` response automatically) and verify under
**Caching > Configuration**:

- Browser Cache TTL: Respect Existing Headers
- Cache Level: Bypass

For Cloudflare Workers in front of axon: ensure `request.cf.cacheTtl` is
0 for the SSE route.

```axon
axonendpoint Live {
    transport: sse
    keepalive: 30s   // < 100s Cloudflare default
}
```

### nginx reverse proxy

```nginx
location /v1/execute/sse {
    proxy_pass http://axon_upstream;
    proxy_http_version 1.1;
    proxy_set_header Connection "";        # disable HTTP/1.1 close
    proxy_buffering off;                   # flush events immediately
    proxy_cache off;
    proxy_read_timeout 1h;                 # > flow's max duration
    proxy_set_header X-Accel-Buffering no; # for legacy front-ends
}
```

```axon
axonendpoint Live {
    transport: sse
    keepalive: 30s   // nginx default proxy_read_timeout 60s would still cut us off; tune both
}
```

### GCP HTTPS Load Balancer

GCP HTTP(S) LB's default backend service timeout is 30 seconds — set it
higher for streaming endpoints:

```bash
gcloud compute backend-services update axon-backend \
    --global \
    --timeout=86400  # 24 hours; tune to your flow's max duration
```

```axon
axonendpoint Live {
    transport: sse
    keepalive: 15s   // < 30s would have been the default
}
```

### Kubernetes Ingress (nginx-ingress)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/server-snippet: |
      add_header X-Accel-Buffering no;
```

---

## Troubleshooting checklist

When an adopter reports "SSE isn't working", walk this checklist in
order. Each step pins one layer of the stack so the failure surface is
isolated.

### 1. Is `transport: sse` declared on the axonendpoint?

```bash
axon parse src/your.axon --json | jq '.declarations[] | select(.kind == "axonendpoint")'
```

If the `transport` field is absent or `json`, the server returns JSON.
This is the most common failure — add the declaration.

### 2. Does the execute flow produce a stream?

If `transport: sse` is declared but the flow has no stream effect, the
type-checker should have already flagged the issue at compile time. If
it didn't, the flow's predicate may rely on disjunct (c) `perform
Stream.Yield(...)` which is harder to reach via the Rust frontend's
walker. See [Type-checker enforcement rules](#type-checker-enforcement-rules)
for the formal disjunction.

### 3. Is the keepalive interval surviving the load balancer's idle timeout?

Check the LB's idle timeout vs the axonendpoint's keepalive value:

| LB | Idle timeout | Min keepalive value |
|---|---|---|
| AWS ALB | 60s default | 15s or 30s |
| Cloudflare | 100s | 30s or 60s |
| Cloudflare Tunnel | 90s | 30s or 60s |
| GCP HTTPS LB | 30s default | 15s |
| nginx (default) | 60s `proxy_read_timeout` | 15s or 30s |

If the connection drops at exactly the LB's idle timeout, the keepalive
is set too high or not propagating. Verify the response carries
`: keepalive` comments on the wire:

```bash
curl -N -X POST http://localhost:8443/v1/execute/sse \
    -H "Content-Type: application/json" \
    -d '{"flow_name":"YourFlow","backend":"stub"}'
```

You should see `: keepalive` lines at the declared interval.

### 4. Is the client EventSource attaching the right event-name listeners?

The axon wire format uses **named events**, not the default unnamed
event. A client doing only `es.onmessage = ...` will miss everything;
attach explicit listeners:

```javascript
es.addEventListener("axon.token",    handler);
es.addEventListener("axon.complete", handler);
es.addEventListener("axon.error",    handler);
```

### 5. Are intermediate proxies buffering the response?

Some reverse proxies + CDNs buffer SSE by default. Confirm `proxy_buffering
off` (nginx), no Cloudflare caching, and `X-Accel-Buffering: no` are
honored end-to-end.

### 6. Did the negotiation classifier pick the wrong branch?

The `/v1/execute` negotiation wrapper consults BOTH the parsed AST and a
defensive source-text predicate. Adopter source that the Rust frontend
parses incompletely (a known Fase 30.e gap on `output: Stream<T>` inside
step bodies + `use <tool>` inside step bodies) still triggers SSE
promotion via the source-text path. If you suspect a misclassification,
hit `/v1/execute/sse` directly — that route bypasses negotiation entirely.

### 7. Is the deployed source what you think it is?

```bash
curl http://localhost:8443/v1/flows/YourFlow | jq '.source'
```

Active deployment may lag the source on disk — re-deploy explicitly to
sync.

---

## Client-side EventSource recipe

### Browser

```html
<script>
const es = new EventSource("/v1/execute/sse?flow_name=Live&backend=anthropic");

let buffer = "";
es.addEventListener("axon.token", (ev) => {
    const { step, token } = JSON.parse(ev.data);
    buffer += token + " ";
    document.getElementById("out").textContent = buffer;
});

es.addEventListener("axon.complete", (ev) => {
    const env = JSON.parse(ev.data);
    console.log("done, trace:", env.trace_id, "latency:", env.latency_ms, "ms");
    es.close();
});

es.addEventListener("axon.error", (ev) => {
    const err = JSON.parse(ev.data);
    console.error("flow failed:", err.error);
    es.close();
});

es.onerror = (ev) => {
    // Per W3C: EventSource auto-reconnects unless explicitly closed.
    if (es.readyState === EventSource.CLOSED) console.warn("stream closed");
};
</script>
```

> **Note:** `EventSource` cannot send `POST` directly. For POST-based SSE
> consumption, use `fetch` with a `ReadableStream` reader (below) or
> deploy a thin GET-proxy in front of `POST /v1/execute/sse`.

### Browser via `fetch` + `ReadableStream` (POST)

```javascript
async function streamFlow(flow) {
    const resp = await fetch("/v1/execute/sse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow_name: flow, backend: "anthropic" }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // Naive line-delimited parse — production code should use a
        // proper SSE parser like `eventsource-parser`.
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const lines = block.split("\n");
            const evt = {};
            for (const line of lines) {
                const [k, ...rest] = line.split(":");
                evt[k.trim()] = rest.join(":").trim();
            }
            if (evt.event === "axon.token")    handleToken(JSON.parse(evt.data));
            if (evt.event === "axon.complete") handleComplete(JSON.parse(evt.data));
            if (evt.event === "axon.error")    handleError(JSON.parse(evt.data));
        }
    }
}
```

### Python (httpx + SSE iter)

```python
import json

import httpx

async def stream_flow(flow_name: str) -> None:
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "http://localhost:8443/v1/execute/sse",
            json={"flow_name": flow_name, "backend": "anthropic"},
            timeout=None,  # streaming endpoint — no overall timeout
        ) as resp:
            current_event: dict[str, str] = {}
            async for line in resp.aiter_lines():
                if not line:
                    # Blank line → event boundary.
                    if current_event:
                        on_event(current_event)
                    current_event = {}
                    continue
                if line.startswith(":"):
                    continue  # keepalive comment
                key, _, value = line.partition(":")
                current_event[key.strip()] = value.strip()

def on_event(evt: dict[str, str]) -> None:
    name = evt.get("event")
    data = json.loads(evt["data"]) if "data" in evt else {}
    if name == "axon.token":
        print(f"chunk: {data['token']}")
    elif name == "axon.complete":
        print(f"done: trace={data['trace_id']} latency={data['latency_ms']}ms")
    elif name == "axon.error":
        print(f"error: {data['error']}")
```

### Rust (reqwest + eventsource-stream)

```rust
use eventsource_stream::Eventsource;
use futures::StreamExt;
use serde_json::Value;

let resp = reqwest::Client::new()
    .post("http://localhost:8443/v1/execute/sse")
    .json(&serde_json::json!({
        "flow_name": "Live",
        "backend": "anthropic"
    }))
    .send()
    .await?;

let mut stream = resp.bytes_stream().eventsource();
while let Some(event) = stream.next().await {
    let event = event?;
    let data: Value = serde_json::from_str(&event.data)?;
    match event.event.as_str() {
        "axon.token"    => println!("chunk: {}", data["token"]),
        "axon.complete" => { println!("done"); break; }
        "axon.error"    => { eprintln!("error: {}", data["error"]); break; }
        _ => {}
    }
}
```

---

## LSP / IDE integration recipe

The `axon-lsp` server (v0.2.0+) ships completion + hover for the new
fields. Adopters using the
[VSCode extension](https://marketplace.visualstudio.com/items?itemName=Bemarking.axon-lsp)
or any LSP-compatible IDE get:

- **Completion** of `transport:` field name inside `axonendpoint` blocks.
- **Completion** of the closed enum values `{json, sse, ndjson}` after
  the colon.
- **Completion** of `keepalive:` + its closed enum `{5s, 15s, 30s, 60s}`.
- **Hover** on `transport` showing the field's effect on wire format
  + the D5 vs D4 negotiation rules.
- **Diagnostic** rendering of the Fase 30.c type-checker errors via the
  Fase 28.f structured JSON output.

If a completion or diagnostic is missing for a Fase 30 surface, file an
issue against
[axon-lsp](https://github.com/Bemarking/axon-lsp) — it's a separate repo
that catches up to axon-lang on each minor release.

---

## CI integration recipe

### Verifying SSE wire conformance in your own pipeline

```yaml
name: SSE Conformance
on: [push, pull_request]
jobs:
  sse-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install axon-lang>=1.21.0 httpx
      - run: axon parse src/                       # gate compile-time
      - run: axon deploy src/your.axon --dry-run   # gate deploy shape
      - name: Smoke-test SSE
        run: |
          # Spin up axon-rs server in the background, hit /v1/execute/sse,
          # assert wire format invariants on the response body.
          python scripts/sse_smoke.py
```

`scripts/sse_smoke.py` should at minimum assert:

- Response `Content-Type` starts with `text/event-stream`.
- Body contains `retry: 5000` before any `event:` line.
- Every `id:` field carries a strictly-monotonic non-zero u64.
- Body ends with `\n\n`.

The axon-lang project's
[`axon-rs/tests/fase30_sse_fuzz.rs`](../axon-rs/tests/fase30_sse_fuzz.rs)
is the canonical reference for these checks.

### Gating the transport declaration on a code review

Add a grep step that flags axonendpoints declaring `transport: sse`
without an accompanying `keepalive` — the type-checker enforces the
streaming contract but not the deployment-readiness contract:

```bash
# Find any sse-transport endpoint without an explicit keepalive.
ack -A 10 "transport: sse" src/ | grep -v -E "keepalive:|^$|^--" \
    | tee /tmp/missing-keepalive.txt
[ -s /tmp/missing-keepalive.txt ] && {
    echo "Endpoints with transport: sse must declare keepalive:" >&2
    cat /tmp/missing-keepalive.txt >&2
    exit 1
}
```

(Not enforced at the language level — defaulting to 15s is correct for
most deployments. This is a project-specific lint.)

---

## Cross-stack contract: Python ↔ Rust

axon-lang ships **two frontends** at v1.21.0:

- **Python:** `axon-lang` PyPI package — the canonical reference
  implementation; covers the broadest CLI / runtime surface, including
  the Fase 30.c type-checker enforcement.
- **Rust:** `axon-frontend` crates.io crate — pure-frontend (lexer,
  parser, AST); consumed by `axon-rs` (the Rust runtime serving the SSE
  routes) and `axon-lsp` (the LSP server).

**D7 ratified (extends Fase 28 D7) — byte-identical parse of `transport`
and `keepalive` fields across both stacks.** The Fase 30 drift gate
([`.github/workflows/fase_30_http_transport.yml`](../.github/workflows/fase_30_http_transport.yml))
runs both parsers against the shared corpus at
`tests/fixtures/fase30_transport/corpus.json` on every PR; if they ever
disagree on a single entry, exactly one lane fails. Adopters never see
the drift — it's caught at PR-time.

### Known cross-stack gaps (documented for transparency)

The Rust frontend's parser today has two known gaps relative to the
Python parser, identified during Fase 30.e development:

1. `output: Stream<T>` inside step bodies — the Rust AST's `StepNode`
   doesn't currently surface a parametric output type.
2. `use <tool>("args")` inside step bodies — the Rust AST's `StepNode`
   doesn't currently carry a `use_tool` field.

These gaps mean the Rust-side AST predicate (disjuncts a + b of the 30.c
formal predicate) under-detects some streaming flows. To compensate, the
30.e content-negotiation classifier consults a **defensive source-text
predicate** alongside the AST walk and OR-combines the verdicts — so the
adopter-visible behavior is correct on both stacks. The canonical fix is
a Rust frontend completion sub-fase tracked in the
[Fase 30 plan vivo](./fase_30_http_transport_stream_effects.md).

---

## Dynamic routes (Fase 32, v1.23.0+)

§Fase 32.j addition. Pre-v1.23.0 the SSE wire format above only fired on
`POST /v1/execute` (legacy RPC path) and `POST /v1/execute/sse`
(explicit two-stage). v1.23.0 makes every `axonendpoint` declaration a
real HTTP route at the declared `(method, path)`. **The Fase 30 + 31
transport semantics described above apply uniformly to dynamic
routes** — `POST /chat` (the adopter's declared path) returns the same
wire format `POST /v1/execute` would have under the same `transport:`
declaration + Accept header + strict-mode flag.

### Per-route negotiation matrix

The 8-cell negotiation matrix is keyed by the ROUTE'S declaration
(via `axonendpoint.transport:` + `axonendpoint.transport_explicit`),
not by the underlying flow. Two axonendpoints sharing one flow but
declaring DIFFERENT transports each honor their own contract:

```axon
tool chat_tokens { description: "stream" effects: <stream:drop_oldest> }
flow Chat() -> Unit { step Generate { ask: "x" apply: chat_tokens } }

axonendpoint ChatSse  { method: POST path: "/chat-sse"  execute: Chat transport: sse }
axonendpoint ChatJson { method: POST path: "/chat-json" execute: Chat transport: json }
```

- `POST /chat-sse` → `Content-Type: text/event-stream` (D5 declared sse).
- `POST /chat-json` → `Content-Type: application/json` (D3 sacred opt-out, even with `Accept: text/event-stream`).

The Fase 32.e `classify_dynamic_route_wire` function is a pure +
total 5-input predicate over `(transport, transport_explicit,
implicit_transport, client_wants_sse, strict_mode)`. The 8-cell
truth table is unit-tested in
[`axon-rs::axon_server::dynamic_route_wire_truth_table`](../axon-rs/src/axon_server.rs).

### Keepalive honored on declared paths

The `keepalive: 5s | 15s | 30s | 60s` field works identically on
dynamic routes:

```axon
axonendpoint Chat {
    method:    POST
    path:      "/chat"
    execute:   StreamingChat
    transport: sse
    keepalive: 15s        // honored on POST /chat exactly as on /v1/execute/sse
}
```

EventSource clients connect to the declared path directly:

```javascript
const evt = new EventSource("/chat");
evt.onmessage = (e) => console.log(e.data);
```

### X-Axon-Stream-Available diagnostic on dynamic routes

Fase 31.e's diagnostic header fires on dynamic-route JSON responses
when the underlying flow has stream effects (i.e. the inference
COULD have promoted to SSE but didn't due to D3 declared-json or
flag-off + missing Accept). The shape is identical to `/v1/execute`:

```
X-Axon-Stream-Available: 1; reason=flag_off; flow=Chat;
opt_in=transport:sse,Accept:text/event-stream
```

Adopters debugging "why am I getting JSON on /chat" find the diagnostic
in their client logs without spelunking the source.

### Replay-Status on `GET /v1/replay/<trace_id>`

Fase 32.h adds the replay binding for POST/PUT axonendpoints (D9
plan-vivo). The retrieval handler `GET /v1/replay/<trace_id>` carries
a `Replay-Status: deterministic | non_deterministic` HTTP header
indicating whether the original execution can be byte-identically
re-executed. See [`ADOPTER_REST.md` §9](ADOPTER_REST.md#replay-token-binding--regulator-grade-audit-d9)
for the full retrieval shape.

### SSE bypasses output validation + replay binding

The runtime validates `output: T` and writes replay entries only on
JSON-transport responses (the bytes can be captured + hashed at the
wire layer). SSE / ndjson responses pass through unchanged — per-event
typed-stream validation + token-chain replay are tracked as a future
fase. If your flow produces a `Stream<T>` AND you need replay audit,
declare `transport: json` to opt out of streaming + opt in to replay,
or layer enterprise streaming-audit primitives.

---

## Real-time streaming (Fase 33, v1.24.0+)

> **TL;DR for adopters upgrading from v1.23.x → v1.24.0:** the SSE wire
> body is **byte-identical** with v1.23.x — same `retry:` directive,
> same `event:` types, same `data:` JSON shape, same `id:` monotonicity.
> What changes is **when** each event arrives on the wire: pre-33.c
> token events burst-arrived at end of execution; v1.24.0+ delivers
> them AS THEY ARE PRODUCED. **No client-side migration required for
> wire-compat clients.** Opt-in observability via the new
> `stream_policies` field on `axon.complete` documented below.

Fase 33 closes the architectural cycle from algebraic-effect declaration
to adopter-observable token-by-token streaming. The trigger was the
adopter trail post-v1.23.1: *"10 bumps en 5 días. Mismo resultado. […]
es un piece de arquitectura que necesita su propio cycle"*. The fix is
not a parser patch — it's four cooperating runtime layers, each shipped
behind founder sign-off so adopters can adopt incrementally.

### The four layers, in plain language

| Layer | What changed | Adopter-visible effect |
|---|---|---|
| **Layer 1** — `FlowExecutionEvent` (33.b) | Replaced the stale `step_names=[] / step_results=[]` shape with a closed 6-variant event catalog | Wire body now shows `step:"Generate"` + `token:"(stub)"` instead of the pre-33.b hollow `step:"" / token:""` for stub-backend dispatches |
| **Layer 2** — live forwarding (33.c) | `execute_sse_handler` consumes a `FlowExecutionEvent` receiver LIVE; no batching after `server_execute_full` returns | Tokens arrive at the client AS the runtime emits them, not all at once after the flow completes (visible against real backends) |
| **Layer 3** — native `Backend::stream()` (33.d) | All 7 native LLM backends ship real per-provider SSE streaming. OpenAI-compat covers openai/kimi/glm/ollama/openrouter; Anthropic + Gemini ship their own protocols | When `backend: anthropic` (or any other native backend) executes a flow with `Stream<T>` output, each provider chunk surfaces as one `axon.token` event |
| **Layer 4** — stream-effect dispatcher (33.e) | `tool X { effects: <stream:<policy>> }` annotations now bind to actual runtime behavior via the new `stream_effect_dispatcher` module | `axon.complete` wire envelope carries a new optional `stream_policies` array surfacing which policies fired on which steps |

Two transversal invariants pinned in CI on every PR:

- **D6 cancel-safety** (33.f): client disconnect → SSE consumer's
  `tx.send().await.is_err()` → `cancel.cancel()` → producer's next
  `tx.send()` fails → producer exits early via a single shared
  `emit` closure that checks both signals.
- **D12 robustness fuzz** (33.g): ~2 000 deterministic iterations
  across 13 surfaces. The closed catalogs (`FlowExecutionEvent::ALL`,
  `BackpressurePolicy::ALL`) are pinned to their exact variant set;
  adding a new variant breaks the build cross-stack.

### What does NOT change (D9 wire byte-compat, ratified)

Every adopter contract built against the Fase 30/31/32 wire shape
continues to work bit-identically:

- `retry: 5000\n\n` still leads every response.
- `event: axon.token\nid: N\ndata: {...}\n\n` for each token event,
  monotone ids starting at 1.
- `event: axon.complete\nid: M\ndata: {...}\n\n` terminates.
- The `data:` JSON keeps every pre-33 field (`step`, `token`,
  `trace_id`, `timestamp_ms` on tokens; `flow`, `backend`,
  `steps_executed`, `tokens_input`, `tokens_output`, `latency_ms`,
  `success` on complete).
- Existing keepalive (`: keepalive\n\n` at the declared interval)
  fires identically. Per-route transport classification (Fase 32.e)
  is unchanged. Negotiation (Fase 30.e/31.c) is unchanged.

The CI workflow `.github/workflows/fase_33_sse_cognitive_primitive.yml`
lane 7 (**D9 backwards-compat anchor**) re-runs the full Fase 30/31/32
SSE test surface on every PR; any byte-level perturbation breaks the
build.

### `stream_policies` — observe declared policies on the wire

When a step's referenced tool declares `effects: <stream:<policy>>`,
the SSE handler now surfaces the resolved policy on the
`axon.complete` envelope's JSON payload:

```axon
tool chat_stream {
    provider: anthropic
    effects:  <stream:drop_oldest>
}

flow Chat() -> Unit {
    step Generate {
        ask:   "hi"
        apply: chat_stream
        output: Stream<Token>
    }
}

axonendpoint ChatEndpoint {
    method:    POST
    path:      "/chat"
    execute:   Chat
    transport: sse
}
```

Wire body (only the complete event shown):

```
event: axon.complete
id: 2
data: {"trace_id":1,"flow":"Chat","backend":"anthropic","steps_executed":1,"tokens_input":12,"tokens_output":42,"latency_ms":3214,"success":true,"stream_policies":[{"step":"Generate","policy":"drop_oldest"}]}
```

Pre-33.e wire body for the same flow:

```
event: axon.complete
id: 2
data: {"trace_id":1,"flow":"Chat","backend":"anthropic","steps_executed":1,"tokens_input":12,"tokens_output":42,"latency_ms":3214,"success":true}
```

The field is **elided when empty** (the flow has no declared stream
effects), so adopter clients that don't know about the field don't
observe any change. JSON parsers treat the new key as a no-op when
unknown.

#### The closed policy catalog

Four policies, sealed at the compiler level:

| Slug | Semantics | When to use |
|---|---|---|
| `drop_oldest` | Buffer bounded; when full, drop the OLDEST queued token to make room for the new one. Lossy but never blocks. | Telemetry / "live tail" streams where the freshest data matters and history is disposable. |
| `degrade_quality` | Buffer bounded; when full, the new token is degraded through a tool-declared degrader function (e.g. emit a summary token) before being pushed. Lossy but never blocks; the consumer still gets a token per produced item, just lower fidelity. | Audio downsampling, image resampling under bandwidth pressure. The compiler REQUIRES a degrader function. |
| `pause_upstream` | Buffer bounded; producer blocks until the consumer drains. Lossless; safest for request/response. **DO NOT use on real-time ingest paths** (microphones, market feeds) or the upstream source hangs. | LLM chat over a slow client. The natural choice for token streaming. |
| `fail` | Buffer bounded; on overflow, the producer surfaces a typed `StreamError::Overflow`. The consumer sees a mid-stream error event. | Callers that need explicit failure on saturation (audit trails, financial pipelines where dropped data is illegal). |

Adding a fifth policy requires a frontend patch + breaks every
dispatcher's exhaustive match — caught at build time, not at adopter
bug-report time.

### Per-provider streaming notes (Fase 33.d)

All seven native LLM backends speak their provider's canonical
streaming protocol:

| Backend | Wire protocol | Where the impl lives |
|---|---|---|
| `anthropic` | SSE with typed events: `message_start`, `content_block_delta`, `message_delta`, `message_stop`, `ping` (dropped) | `axon-rs/src/backends/anthropic.rs::stream` |
| `openai` | OpenAI SSE with `[DONE]` sentinel | `axon-rs/src/backends/openai_compat.rs::stream` (shared) |
| `kimi` | OpenAI-compat SSE (delegates to openai_compat) | same as openai |
| `glm` | OpenAI-compat SSE (delegates to openai_compat) | same as openai |
| `ollama` | OpenAI-compat SSE via `/v1/chat/completions` (the ollama daemon's native ndjson surface at `/api/chat` is a 33.x follow-up) | same as openai |
| `openrouter` | OpenAI-compat SSE (delegates to openai_compat) | same as openai |
| `gemini` | `:streamGenerateContent?alt=sse` with `candidates[0].content.parts[*].text` deltas | `axon-rs/src/backends/gemini.rs::stream` |

Each impl fails-fast on non-200 (retrying mid-stream replays partial
tokens — semantically wrong); the typed `BackendError` you see on the
wire's `axon.error` event reflects the provider's actual response
(401 → Auth, 429 → RateLimit, 5xx → Generic with status).

### Migration recipe v1.23.x → v1.24.0

**For wire-compat clients (the vast majority):**

No changes required. Re-run your existing SSE integration tests
against an axon-lang v1.24.0 server; the wire body is byte-identical.
You'll observe lower **time-to-first-byte for token events** when
your flow uses a real native backend (Fase 33.d wired in per-step in
the 33.x follow-up; see the "Honest scope statement" below).

**For clients that want to observe declared policies on the wire:**

After upgrading the server, look for the new `stream_policies` array
on `axon.complete` event data when the flow's tool declarations carry
`effects: <stream:<policy>>`. Existing JSON parsers ignore the
field; observability dashboards can index it directly.

```javascript
es.addEventListener("axon.complete", (e) => {
    const data = JSON.parse(e.data);
    if (data.stream_policies?.length) {
        console.log("Active policies:", data.stream_policies);
        // e.g. [{"step":"Generate","policy":"drop_oldest"}]
    }
});
```

**For clients that depended on the pre-33.c "synchronous burst" timing:**

None known. The pre-33.c behavior was a bug surfaced by the adopter
trail; if your client depended on it implicitly (e.g. assumed ALL
token events would arrive before `axon.complete` did, with no
inter-event idle gap), the new behavior is strictly more correct and
matches the W3C SSE spec. Open a bug if you find a real regression;
the CI lane 7 D9 anchor pins the wire format byte-by-byte and
catches any drift at PR time.

### Honest scope statement (what 33.x is still going to add)

The synchronous `server_execute_full` path currently materializes
all step outputs before the chunker runs. So Fase 33.c's live
forwarding architecture is **structurally** in place (the
`FlowExecutionEvent` producer/consumer split is wired end-to-end),
but the producer itself emits all events in microseconds for the
stub backend — there's no real per-token network roundtrip to
amortize.

The next sub-fase (**33.x**, post-v1.24.0) wires `Backend::stream()`
(Fase 33.d, already shipped per-provider) into the **per-step
execution path** inside `server_execute_full`. At that point each
chunk's actual network roundtrip surfaces as a wall-clock inter-
event gap on the wire, the `StreamPolicyEnforcer` (Fase 33.e)
actually observes overflow under saturating producers, and the
cancellation primitive (Fase 33.f) gets a meaningful window to
abort mid-flight backend requests when a client disconnects.

The architecture shipped in v1.24.0 is the complete contract. The
v1.24.x point release(s) activate it without further adopter-facing
changes.

### Vertical patterns — same as v1.23 + token-by-token UX

The four high-profile verticals from Fase 32 unlock token-by-token
delivery as soon as 33.x activates:

- **Banking** — `POST /loan/decision` with `transport: sse + replay: true`
  streams the risk-explanation narration token-by-token. Auditors
  retrieve via `GET /v1/replay/<trace_id>` and see the FULL token
  sequence + final decision. PCI DSS Req 10 audit-defensible.
- **Government** — `POST /benefits/eligibility` streams the eligibility-
  reasoning narrative. FOIA requests retrieve the live trace.
- **Legal** — `POST /discovery/privilege` streams the privilege-
  assessment reasoning. FRE 502 waiver-doctrine appeals trace the
  exact reasoning steps.
- **Medicine** — `POST /clinical/decision-support` streams clinical
  recommendations to clinician UI token-by-token. The PHI scrubber
  (Fase 27.g) runs upstream of every chunk. 21 CFR Part 11 §11.10
  audit retains the full stream.

Each pattern works today with `Content-Type: text/event-stream`
(v1.23.1) but the wire body burst-arrives at end-of-flow. Fase 33
makes the token-by-token delivery REAL.

### Cancel-safety in the wire (D6)

When the SSE client disconnects (browser navigation, TCP RST, network
partition), the runtime cooperatively terminates:

1. Consumer's per-token `tx.send().await` returns `Err`.
2. Consumer calls `cancel.cancel()` and breaks the wire-emission loop.
3. Producer's next `tx.send()` into the `FlowExecutionEvent` channel
   fails (consumer dropped the receiver).
4. Producer exits via the same early-return path that an explicit
   cancellation would trigger.
5. The `CancelOnDrop` RAII guard installed at the top of the spawned
   task fires `cancel.cancel()` if the task is aborted (panic, task
   abort), so the producer always sees the signal even on
   abnormal exit.

Adopter-visible effect:

- No further wire events are sent after disconnect.
- The trace record (`trace_store`) reflects partial execution.
- No leaked tokio tasks; no unbounded memory growth from a
  disconnected-but-still-producing flow.

The cancellation primitive (`axon::cancel_token::CancellationFlag` +
`CancelOnDrop`) is part of the public adopter surface for
integration code that needs to bind external scopes to the
streaming lifetime — see `cancel_token.rs` for the API.

### Where to file bugs (Fase 33-specific)

| Symptom | Where |
|---|---|
| Wire body byte-different from v1.23.x for the same source (D9 violation) | `axon-lang` issue tracker — D9 anchor regression, treat as blocker |
| `stream_policies` array absent from `axon.complete` when source declares `<stream:policy>` | `axon-lang` issue tracker — Fase 33.e resolver regression |
| `stream_policies` array carries a policy slug not in `{drop_oldest, degrade_quality, pause_upstream, fail}` | `axon-lang` issue tracker — closed-catalog violation |
| Tokens still burst-arriving at end of flow on a real native backend (post-33.x) | `axon-lang` issue tracker — Layer 2 live-forwarding regression |
| Client disconnect doesn't cause producer to exit within ~100ms of the next event boundary | `axon-lang` issue tracker — D6 cancel-safety regression |
| Per-provider stream() returns 200 but mid-stream JSON parses fail silently | `axon-lang` issue tracker — chunk parser regression; include the provider name + the raw SSE body |

---

## Production-path activation (Fase 33.x, v1.25.0+)

**D4 wire byte-compat ratified up front**: every adopter on
v1.24.0 can upgrade to v1.25.0 **without changing a single line
of `.axon` source**. The wire shape adopters consume is byte-
identical for stub-backed flows + the canonical happy path; new
features (per-step replay audit, BPE tokenizer fallback, W002
warning) surface ONLY via optional wire fields that are elided
when not active.

Fase 33.x activates the four-pillar contract on the production
SSE path. Where Fase 33.a-i shipped the architectural primitives
in isolation, Fase 33.x activates them inside
`server_execute_streaming` so adopter flows that declare
`output: Stream<T>` or `apply: <stream-effect-tool>` see:

- **D1 + D2** — real per-chunk delivery via `Backend::stream()` +
  `StreamPolicyEnforcer` running in production on declared
  `<stream:<policy>>` effects (not just compile-time validated).
- **D3** — cancel inside the reqwest body, **p95 cancel→None
  ≤ 100ms wall-clock** (measured 12.6µs against the local-loopback
  slow-drip mock — 7950× under budget; live wire is asserted by
  the opt-in real-provider lane).
- **D5** — closed-catalog `axon-W002 streaming-not-supported`
  warning surfaces on `axon.complete.warnings[*]` when the
  async path falls back to the legacy synchronous-burst delivery.
- **D6** — per-step audit trail in `/v1/replay/<trace_id>` for
  SSE routes whose axonendpoint declared `replay: true`.
- **D7** — mono-file `crate::backend` retirement (Phase 1):
  consolidated single source of truth for the canonical 7-provider
  set + deprecated synchronous call surface.
- **D9** — opt-in BPE-tokenized fallback chunking for legacy-path
  flow shapes (defaults OFF; preserves v1.24.0 wire byte-compat).
- **D10** — real-provider E2E lane (Anthropic / OpenAI / Gemini +
  4 vertical canonical patterns) gated on
  `AXON_RUN_REAL_PROVIDER_TEST` repository variable.
- **D12** — robustness fuzz across 11 surfaces, ~2050 deterministic
  LCG iterations.

### Adopter checklist — what changes, what doesn't

| Concern | v1.24.0 | v1.25.0 |
|---|---|---|
| `.axon` source needed? | — | NONE for the happy path; `replay: true` enables per-step audit |
| Wire body for stub + canonical `Stream<T>` | 1 axon.token "(stub)" + 1 axon.complete | **Identical** (D4 byte-compat) |
| Wire body for real backend (Anthropic / OpenAI / Gemini) | Hits `crate::backend::call_multi`; synthetic 3-word chunking | **Per upstream provider chunk** (real granularity via `Backend::stream()`) |
| `axon.complete.stream_policies` for declared effects | Populated (Fase 33.e) | **Populated + `enforcement_summary` adds production counters** |
| `axon.complete.warnings` | (field does not exist) | New optional field; carries W002 when LEGACY path fires |
| `GET /v1/replay/<uuid>` for SSE routes with `replay: true` | Returns 404 (Fase 32.h SSE bypasses replay) | **Returns entry with `step_audit` array (D6 per-step audit)** |
| Client-disconnect cancel propagation latency | Between event emissions (Fase 33.f baseline) | **p95 12.6µs measured (D3 invariant); reqwest body aborts mid-stream** |
| Adopter-side EventSource code | Unchanged | Unchanged |
| Auth surface (Fase 32.g `requires:` capabilities) | Unchanged | Unchanged |
| Adopter test suites | Pass unchanged | Pass unchanged (verified: 49 integration suites + 1614 lib + Python parity) |

### 4-policy production behavior table

When a tool declares `effects: <stream:<policy>>` and the flow
activates the async streaming path (33.x.b), the
`StreamPolicyEnforcer` runs on the per-step
`Stream<ChatChunk>`. Each policy produces a specific behavior +
specific counters on the wire's `enforcement_summary` field.

| Policy declaration | Production behavior | Wire counters fire when... |
|---|---|---|
| `<stream:drop_oldest>` | Bounded buffer; when full, **drops the oldest queued chunk** + accepts the new one | Fast producer + slow consumer; `drop_oldest_hits` > 0 |
| `<stream:degrade_quality>` | Calls the configured degrader fn on every push (identity-degrader OSS default; enterprise vertical impls override) | Always — counter increments per push regardless of saturation |
| `<stream:pause_upstream>` | Bounded buffer; when full, **blocks the producer's push until the consumer drains** | Fast producer + slow consumer; `pause_upstream_blocks` > 0 |
| `<stream:fail>` | Bounded buffer; when full, **returns Overflow error to the producer** + closes the stream | Fast producer reaches capacity; `fail_overflows` ≥ 1 |

Adopters reading `axon.complete.enforcement_summary` get the
exhaustive snapshot per step:

```json
"enforcement_summary": {
  "Generate": {
    "policy_slug": "drop_oldest",
    "chunks_pushed": 46,
    "chunks_delivered": 46,
    "drop_oldest_hits": 0,
    "degrade_quality_hits": 0,
    "pause_upstream_blocks": 0,
    "fail_overflows": 0,
    "failed": false
  }
}
```

### `axon-W002 streaming-not-supported` reading guide

The W002 warning surfaces on `axon.complete.warnings[*]` when
`server_execute_streaming` decides the LEGACY synchronous path
instead of the async per-step `Backend::stream()` loop. **No
silent degradation** — the warning is OBSERVABLE on every wire
that fell back.

`FallbackMode` closed catalog (4 variants):

| `fallback_mode` value | What it means | Adopter action |
|---|---|---|
| `"unsupported_flow_shape"` | Flow uses `anchors`, `apply: <lambda>`, `let` bindings, mid-stream `use_tool`, `hibernate`, `drill`/`trail` PIX, or another IRFlowNode variant the streaming planner doesn't model (33.x.b scope) | None required for compatibility — flow runs correctly on the legacy path. To gain per-token streaming, refactor the flow to the canonical `step S { ask: "..." [apply: tool] }` shape. |
| `"unknown_backend"` | Resolver returned `None` for the requested backend name | Check the backend name spelling; consult `CANONICAL_PROVIDERS` for the canonical 7-name set. |
| `"source_compilation_failed"` | Lex / parse / type-check / IR-generation error | Fix the source error (see ADOPTER_DIAGNOSTICS.md Fase 28 for the diagnostic shape). |
| `"backend_lacks_stream"` | Reserved — for future adopter-provided custom backends that implement `Backend::complete()` but not `Backend::stream()` | Implement `Backend::stream()` for your custom backend, OR set `axon_runtime::set_tokenizer_fallback(true)` for BPE-tokenized fallback chunking. |

The warning record also includes `flow_name` + `backend` +
human-readable `message`. Audit-row mirror at
`/v1/replay/<uuid>.runtime_warnings[*]` preserves the same
shape (always present as JSON array, possibly `[]` — adopter
dashboards depend on stable wire-field shape).

### Per-step replay binding example (D6)

For SSE routes whose axonendpoint declared `replay: true` (or
POST without explicit `replay:`, which defaults to enabled per
Fase 32.h D9), the v1.25.0+ server records a per-step audit
trail. Auditors retrieve it via `GET /v1/replay/<trace_id>` and
see:

```json
{
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "endpoint_name": "ClinicalDecisionSupport",
  "flow_name": "CDSAssessment",
  "method": "POST",
  "path": "/cds/decision",
  "client_id": "tenant-X",
  "capabilities_used": ["clinician.assess"],
  "response_status": 200,
  "response_content_type": "text/event-stream",
  "model_version": "axon.runtime.dynamic_route.sse.v1",
  "deterministic": false,
  "step_audit": [
    {
      "step_name": "TriageVitals",
      "step_index": 0,
      "success": true,
      "tokens_emitted": 47,
      "output_hash_hex": "9a1f2c3d4e5b6a7f...",
      "effect_policy_applied": null,
      "chunks_dropped": 0,
      "chunks_degraded": 0,
      "timestamp_ms": 1715517600123
    },
    {
      "step_name": "DifferentialReasoning",
      "step_index": 1,
      "success": true,
      "tokens_emitted": 134,
      "output_hash_hex": "0b1c2d3e4f5a6b7c...",
      "effect_policy_applied": "drop_oldest",
      "chunks_dropped": 0,
      "chunks_degraded": 0,
      "timestamp_ms": 1715517605456
    }
  ],
  "runtime_warnings": []
}
```

**Why this matters for regulated verticals**:

- **Banking** (PCI DSS Req 10) — auditors need per-step
  `tokens_emitted` + `output_hash_hex` so each LLM call in a
  multi-step risk-assessment flow is independently auditable.
- **Government** (FedRAMP AU-2) — FOIA retrieval gets the
  per-step reasoning chain, not just the final response.
- **Legal** (FRE 502 waiver-doctrine) — appellate review traces
  the per-step privilege-assessment.
- **Medicine** (21 CFR Part 11 §11.10) — CDS audit retains
  per-step recommendation provenance with `output_hash_hex` as
  the content-addressable anchor.

**Per-token chain signature is NOT in this scope** — each
`axon.token` event is NOT individually cryptographically chained
(would require Fase 11.c primitive extension; ships as Fase 34
if/when regulated adopters need byte-exact stream replay-as-
original). The `step_audit` records here are the **per-step**
granularity that satisfies the regulated-vertical audit
requirements as of v1.25.0.

### Real-provider E2E recipe (33.x.j opt-in lane)

The dedicated CI workflow
`.github/workflows/fase_33x_real_provider.yml` runs 7 lanes
against real upstream providers when adopter forks opt in.
Default OSS CI **does NOT** consume token quota or risk
network-jitter-induced flake.

**One-time setup for your fork:**

```bash
# 1. Set the repository variable (Settings → Variables → Actions):
AXON_RUN_REAL_PROVIDER_TEST=1

# 2. Set the per-provider key secrets you want to validate
#    (Settings → Secrets → Actions):
ANTHROPIC_API_KEY=sk-ant-...   # optional but recommended
OPENAI_API_KEY=sk-...           # optional
GEMINI_API_KEY=AIza...          # optional
```

**Trigger:**

```bash
# In your fork on GitHub: Actions → "Fase 33.x.j — Real-provider
# E2E (gated)" → Run workflow. Or via gh CLI:
gh workflow run fase_33x_real_provider.yml
```

**What runs:**

| Lane | Asserts |
|---|---|
| `anthropic` | Stream from Claude opens + ≥5 chunks + **p95 inter-chunk arrival ≤ 100ms** wall-clock |
| `openai` | Same against GPT |
| `gemini` | Same against Gemini |
| `vertical-banking` | PCI DSS Req 10 prompt: loan-decision multi-chunk stream |
| `vertical-government` | FedRAMP AU-2 prompt: benefits-eligibility stream |
| `vertical-legal` | FRE 502 prompt: privilege-assessment stream |
| `vertical-medicine` | 21 CFR Part 11 prompt: CDS recommendation stream |

Lanes for unset keys skip cleanly with an `eprintln!` in the CI
log — a fork with only `ANTHROPIC_API_KEY` still validates
Anthropic + all 4 vertical lanes (which use Anthropic by
default), while OpenAI/Gemini lanes skip without failing.

**Local invocation:**

```bash
# Set keys + run the lane locally:
export ANTHROPIC_API_KEY=sk-ant-...
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33x_j_real_provider -- --ignored --nocapture
```

### v1.24.0 → v1.25.0 upgrade in one command

For adopters running the OSS stack on a single deploy host:

```bash
# Bump the dep pin in your adopter project's Cargo.toml or
# pyproject.toml from 1.24.0 → 1.25.0, then:
cargo build --release            # or pip install -U axon-lang
systemctl restart axon-server    # or your equivalent
```

That's the entire migration for the happy path. The wire body
your EventSource clients consume is byte-identical for stub-
backed flows + the canonical `Stream<T>` shape. For full
scenario-driven recipes (per-step replay indexing, tokenizer
fallback opt-in, cancel-budget validation), see
[MIGRATION_v1.25.md](MIGRATION_v1.25.md).

---

## Universal algebraic streaming (Fase 33.y, v1.26.0+)

**D4 wire byte-compat ratified end-to-end**: every adopter on
v1.25.0 can upgrade to v1.26.0 **without changing a single line
of `.axon` source**. The wire shape adopters consume is byte-
identical for stub-backed flows + the canonical happy path; new
surfaces (`flow_dispatcher::dispatch_node` public API + the
`FlowExecutionEvent::ToolCall` closed-catalog variant + the D7
parity gate + the deprecation signals on legacy routing
primitives) are opt-in for downstream-crate authors and don't
mutate the production SSE wire body in v1.26.0.

Fase 33.y **structurally closes** the per-IRFlowNode dispatch
contract: every one of the 45 IRFlowNode variants (Step / Probe /
Reason / Validate / Refine / Weave / UseTool / Remember / Recall /
Conditional / ForIn / Let / Return / Break / Continue /
LambdaDataApply / Par / Hibernate / Deliberate / Consensus /
Forge / Focus / Associate / Aggregate / Explore / Ingest /
ShieldApply / Stream / Navigate / Drill / Trail / Corroborate /
OtsApply / MandateApply / ComputeApply / Listen / DaemonStep /
Emit / Publish / Discover / Persist / Retrieve / Mutate / Purge /
Transact) has a NAMED async handler in `flow_dispatcher::
dispatch_node` with compiler-enforced exhaustive matching. The
dispatcher is **structurally complete** in v1.26.0; **production-
side wiring** into `server_execute_streaming` graduates in v1.27.x
(Fase 33.z) — at which point every adopter shape becomes per-
chunk-streaming-eligible on the wire without any source change.

### Adopter checklist — what changes, what doesn't

| Concern | v1.25.0 | v1.26.0 |
|---|---|---|
| `.axon` source needed? | — | NONE for the happy path; downstream crates that consume `flow_dispatcher::*` opt in |
| Wire body for stub + canonical `Stream<T>` | 1 axon.token "(stub)" + 1 axon.complete | **Identical** (D4 byte-compat preserved end-to-end) |
| Wire body for canonical Step + real backend (Anthropic / OpenAI / Gemini) | Per upstream provider chunk via `Backend::stream()` | **Identical** (33.x.b production async path unchanged) |
| Wire body for orchestration / PIX / algebraic / wire-integration / multi-agent / lambda shapes | Legacy fallback synthetic-burst + `axon-W002 streaming-not-supported` warning | **Identical** (legacy fallback still operational; 33.z grafts the new dispatcher) |
| Public crate surface for IRFlowNode async execution | (none — `flow_dispatcher` did not exist) | **New** — `pub async fn dispatch_node` + `DispatchCtx` + `NodeOutcome` (`#[non_exhaustive]`) + `DispatchError` (`#[non_exhaustive]`) |
| `FlowExecutionEvent` closed catalog | 6 variants | **+1 = 7** — new `ToolCall { step_name, tool_name, content, timestamp_ms }` variant; cross-stack parity (Rust + Python) |
| `ChatRequest.tools` plumbing on `pure_shape` handlers | `Vec::new()` baseline | **Synthesized from `step.apply_ref`** when non-empty; empty → empty (D4) |
| Production SSE consumer behavior for `ToolCall` events | (variant did not exist) | Silently consumed; 33.z grafts the `axon.tool_call` SSE event family |
| Legacy shim infrastructure (`legacy_shim` / `ShimReason` / `NodeOutcome::LegacyShimHandled` / `DispatchError::LegacyShimFailed`) | Existed as 33.y.b–j transitional plumbing | **Retired** (compile-time gone; D7 grep gate enforces) |
| `PlanError::LegacyOrchestrationRequired` + `flow_plan::unsupported_feature_reason` + `axon_server::run_streaming_legacy_path` | Internal routing primitives | `#[deprecated(since = "1.26.0")]` pointing toward `flow_dispatcher::dispatch_node`; 33.z grafts + deletes |

### D-letters mapped to adopter-observable behavior

The 33.y cycle's D-letters compose into a layered contract.
Adopters observe each D-letter through a specific surface:

| D-letter | What it guarantees | How adopters observe it |
|---|---|---|
| **D1 — totality** | Every one of the 45 IRFlowNode variants dispatches through a NAMED async handler; no `_ =>` catch-all in `dispatch_node`; compile-time exhaustive match | A future axon-lang minor that adds a 46th IRFlowNode variant fails the upstream compile + your downstream code's pattern matches on `NodeOutcome` / `DispatchError` (both `#[non_exhaustive]`) cleanly retain the catch-all arm without behavior change |
| **D2 — 4-policy enforcer** | The `StreamPolicyEnforcer` activates per-node when a step declares an effect policy; closed catalog of 4 backpressure policies (DropOldest / DropNewest / FailOnOverflow / DegradeQuality); per-policy counters surface on the audit row | `axon.complete.enforcement_summary` continues to emit per-step `chunks_dropped` / `chunks_degraded` counters (33.x.d unchanged); downstream crates using `dispatch_node` directly observe the same counters via `ctx.enforcement_summaries` Arc-backed side-channel |
| **D3 — cancel propagation** | Every handler entry calls `ctx.cancel.is_cancelled()` first; cancel walks all 45 variants; `p95 cancel→None ≤ 100ms wall-clock` invariant preserved from 33.x.e | Set `ctx.cancel.cancel()` from any thread; the in-flight handler returns `Err(DispatchError::UpstreamCancelled)` at the next checkpoint. Validated by `dispatch_node_honors_cancel_flag_at_entry` drift gate test walking all 45 variants |
| **D4 — wire byte-compat** | The production SSE wire body for canonical Step + stub backend + canonical Step + real backend is byte-identical with v1.25.0. New `ToolCall` event variant is elided from the production wire in v1.26.0 (silently consumed by the SSE handler) | POST any canonical-shape route deployed with stub or real backend; capture body; diff against v1.25.0 capture. Adopters observe zero difference |
| **D6 — per-step audit** | Per-step `step_audit` records on `/v1/replay/<trace_id>` continue to populate as established in 33.x.f; the dispatcher's StepAuditRecord shape is identical | Adopters that index per-step replay rows for compliance audit see byte-identical `step_audit` array shape (33.x.f Scenario B in MIGRATION_v1.25.md) |
| **D7 — no markers** | Zero `unimplemented!()` / `todo!()` / `panic!()` (outside `#[cfg(test)]`) / `legacy_shim` / `ShimReason` / `LegacyShimHandled` / `LegacyShimFailed` references in `src/flow_dispatcher/*.rs`. Enforced by `tests/fase33y_l_parity_gate.rs` (7-test grep gate) at every `cargo test` invocation | Downstream forks that re-introduce any of these markers via merge fail the parity gate at PR time with `<file>:<line>` location precision (Scenario E in MIGRATION_v1.26.md) |
| **D8 — tools first-class** | A canonical Step's declared `apply: <tool>` plumbs through `ChatRequest.tools`; upstream `FinishReason::ToolUse` triggers a `FlowExecutionEvent::ToolCall { step_name, tool_name, content, timestamp_ms }` emission BEFORE the text `StepToken` (preserves arrival ordering); serde-tagged `kind: "tool_call"`; cross-stack parity (Rust + Python) | Downstream crates that consume `FlowExecutionEvent` directly observe `ToolCall` events in arrival order; production SSE consumer surfaces them as `axon.tool_call` events in 33.z |
| **D9 — algebraic** | `perform Stream.Yield x` inside a Fase 23 algebraic-effect handler frame bridges to wire `axon.token` events via `effects_bridge::bridge_effect_stream_yield` static-scan over the instruction tree; closed-catalog projection over all 8 `Value` variants | Downstream crates wiring `IRStreamBlock` through the dispatcher see one `axon.token` per static Yield with `token_index` monotonic from 1; production wire activates this surface end-to-end in 33.z |
| **D10 — sync-runner parity** | The dispatcher's outcome semantics are byte-equal with the sync runner's for the canonical Step shape; the 50-flow sync↔async parity corpus deferred to 33.z confirms parity for all other shapes pre-production-graduation | Adopters that run the same flow through CLI (`runner::execute_full`) and through the dispatcher observe semantically equivalent outcomes (currently the streaming surface uses the v1.25.0 path; 33.z lights up dispatcher parity end-to-end) |
| **D11 — cross-stack** | `FlowExecutionEvent::ToolCall` ships with Python parity in `axon.runtime.flow_execution_event`; closed-catalog drift gate enforces 1-to-1 mapping between Rust and Python event variants | Python downstream consumers observe the same field shape + serde tag as Rust; a future variant addition that breaks parity fails the cross-stack drift gate |
| **D12 — fuzz + CI** | ~3000+ deterministic LCG iterations across handler-totality + cancel propagation + orchestration composition + algebraic-semantics parity + tool-call interleaving (33.y.n consolidates the per-sub-fase fuzz packs); dedicated 10-job CI workflow `.github/workflows/fase_33y_dispatcher.yml` (33.y.n) | Downstream forks running `cargo test` exercise all fuzz packs (each sub-fase 33.y.c–k ships its own deterministic LCG seed); CI workflow runs the full 33.y matrix on every PR |

### The public dispatcher surface

```rust
// New in v1.26.0 — the structurally-closed per-IRFlowNode dispatcher.
//
// dispatch_node is the canonical entry point. Pass an IRFlowNode +
// a DispatchCtx; the dispatcher matches exhaustively over all 45
// variants + dispatches to the per-variant async handler. Cancel
// is checked at entry of every handler (D3); events surface via
// the ctx.tx mpsc channel; per-step audit rows accumulate in
// ctx.step_audit_records Arc-backed side-channel.
pub async fn dispatch_node(
    node: &IRFlowNode,
    ctx: &mut DispatchCtx,
) -> Result<NodeOutcome, DispatchError>;

#[derive(Clone)]
pub struct DispatchCtx {
    pub flow_name: String,
    pub backend_name: String,
    pub system_prompt: String,
    pub cancel: CancellationFlag,
    pub tx: mpsc::UnboundedSender<FlowExecutionEvent>,
    pub enforcement_summaries: Arc<Mutex<HashMap<String, EnforcementSummaryWire>>>,
    pub step_audit_records: Arc<Mutex<Vec<StepAuditRecord>>>,
    pub runtime_warnings: Arc<Mutex<Vec<RuntimeWarning>>>,
    pub branch_path: Vec<String>,
    pub step_counter: usize,
    pub let_bindings: HashMap<String, String>,
    pub pem_backend: Option<Arc<dyn PersistenceBackend>>,
    pub session_id: String,
    pub tenant_id: String,
    pub pending_effect_policy: Option<BackpressurePolicy>,
}

impl DispatchCtx {
    pub fn new(
        flow_name: &str,
        backend_name: &str,
        system_prompt: &str,
        cancel: CancellationFlag,
        tx: mpsc::UnboundedSender<FlowExecutionEvent>,
    ) -> Self;

    pub fn with_pem(self, backend: Arc<dyn PersistenceBackend>) -> Self;
    pub fn with_session_id(self, id: impl Into<String>) -> Self;
    pub fn with_tenant_id(self, id: impl Into<String>) -> Self;
    pub fn branch_path_string(&self) -> String;
    pub fn take_pending_effect_policy(&mut self) -> Option<BackpressurePolicy>;
}

#[non_exhaustive]
pub enum NodeOutcome {
    Completed { output: String, tokens_emitted: u64, step_index: usize },
    Break,
    LoopContinue,
    Return { value: String },
}

#[non_exhaustive]
pub enum DispatchError {
    BackendError { name: String, message: String },
    UpstreamCancelled,
    MissingDependency { name: &'static str },
    ChannelClosed,
}
```

### The new `ToolCall` event variant

```rust
// New in v1.26.0 — closed-catalog variant for upstream tool-call
// signals. Cross-stack parity with Python axon.runtime.flow_execution_event.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum FlowExecutionEvent {
    // ... 6 existing variants ...

    #[serde(rename = "tool_call")]
    ToolCall {
        step_name: String,
        tool_name: String,
        content: String,
        timestamp_ms: u64,
    },
}

impl FlowExecutionEvent {
    /// "tool_call" — the wire-stable kind slug.
    pub fn kind(&self) -> &'static str;

    /// true for ToolCall — the event scopes to a step (not the flow).
    pub fn is_step_scoped(&self) -> bool;

    /// false for ToolCall — ToolCall is observational, not terminal.
    pub fn is_terminator(&self) -> bool;
}
```

### Architectural groups inside the dispatcher

The dispatcher organizes the 45 variants into **9 architectural
groups** (one module per group; the 10th module is `mod.rs` which
hosts the exhaustive `dispatch_node` match). Each group has its
own discipline + per-group public helpers that enterprise
integrations override:

| Group | Module | Variants (count) | Output discipline | Public helpers (enterprise overrides) |
|---|---|---|---|---|
| Pure-shape | `pure_shape.rs` | Step / Probe / Reason / Validate / Refine / Weave (**6**) | Stub backend emits `"(stub)"` + 1 token; real backend emits per-chunk via `Backend::stream()` (D4 byte-compat) | `run_pure_shape` shared async core; `synthesize_tools_from_step` (D8) |
| Orchestration | `orchestration.rs` | Let / Conditional / ForIn / Break / Continue / Return (**6**) | Sentinel + Completed mix; 0 tokens (orchestration is control-flow, not LLM-call) | `dispatch_body` recursive walker (via `Box::pin`); `eval_triple` 8-operator closed-catalog predicate |
| Parallel + algebraic | `parallel.rs` + `effects_bridge.rs` | Par / Stream (**2**) | Concurrent dispatch via `join_all` over per-branch DispatchCtx clones; algebraic-effect ↔ wire bridge via `bridge_effect_stream_yield` static-scan | `run_branches_concurrently` (Par); `bridge_effect_stream_yield` (Stream — D9 milestone) |
| Cognitive primitives | `cognitive.rs` | Remember / Recall / Forge + Focus / Associate / Aggregate / Explore / Ingest / Navigate / Corroborate (**10**) | PEM-bound (Remember/Recall/Forge — 0 tokens) + cognitive-framing (Focus..Corroborate — 1 token via pure_shape) | `Arc<dyn PersistenceBackend>` integration; cognitive-framing addendum per variant |
| Algebraic-effect handlers | `algebraic_handlers.rs` | ShieldApply / OtsApply / MandateApply / ComputeApply / Listen / DaemonStep (**6**) | Identity-passthrough (OSS) / placeholder (`compute:<name>(...)` / `(awaiting <channel>)` / `daemon:<ref>`); 0 tokens | `apply_shield` / `apply_ots` / `apply_mandate` / `invoke_compute` / `listen_on_channel` / `invoke_daemon` (enterprise overrides) |
| Wire integrations | `wire_integrations.rs` | Emit / Publish / Discover / Persist / Retrieve / Mutate / Purge / Transact / Deliberate / Consensus (**10**) | In-memory `__channel_<ref>` / `__store_<name>_<entry>` namespaced let_bindings; canonical placeholders for multi-agent variants; 0 tokens | `emit_to_channel` / `publish_capability` / `discover_capability` / `persist_to_store` / `retrieve_from_store` / `mutate_store` / `purge_from_store` (enterprise overrides) |
| PIX | `pix.rs` | Hibernate / Drill / Trail (**3**) | Canonical placeholder (`(hibernating <event> timeout=<t>)` / `(drilled <pix_ref> path=<p> query=<q>)` / `(trail of <ref>)`); 0 tokens; CPS suspend/resume in enterprise R&D | `await_event_with_timeout` (Hibernate); `drill_pix_subtree` (Drill); `trail_navigation` (Trail) |
| Lambda + tools | `lambda_tools.rs` | LambdaDataApply / UseTool (**2** — FINAL) | Canonical placeholder (`lambda:<name>(<resolved>)` / `tool:<name>(<resolved>)`); 0 tokens | `apply_lambda_data` (Fase 15 CPS dispatcher); `invoke_tool` (Fase 22 tool registry) |

**Total: 9 groups × 45 variants = compiler-enforced exhaustive coverage.**

### Quick recipes

**Drive an IRFlowNode through your own event sink:**

```rust
use axon::flow_dispatcher::{dispatch_node, DispatchCtx, NodeOutcome};
use axon::flow_execution_event::FlowExecutionEvent;
use axon::cancel_token::CancellationFlag;
use axon::ir_nodes::IRFlowNode;
use tokio::sync::mpsc;

async fn drive(node: &IRFlowNode, backend: &str) -> anyhow::Result<NodeOutcome> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let mut ctx = DispatchCtx::new(
        "MyFlow",
        backend,
        "system prompt",
        CancellationFlag::new(),
        tx,
    );

    // Spawn a sink forwarder.
    let sink = tokio::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                FlowExecutionEvent::ToolCall { step_name, tool_name, content, timestamp_ms } => {
                    eprintln!("[tool_call] {step_name}.{tool_name} @ {timestamp_ms}ms: {content}");
                }
                FlowExecutionEvent::StepToken { token, .. } => {
                    print!("{token}");
                }
                _ => {}
            }
        }
    });

    let outcome = dispatch_node(node, &mut ctx).await?;
    drop(ctx);
    sink.await.ok();
    Ok(outcome)
}
```

**Cancel an in-flight dispatch with p95 ≤100ms latency:**

```rust
let cancel = CancellationFlag::new();
let mut ctx = DispatchCtx::new("F", "anthropic", "", cancel.clone(), tx);

// Spawn the dispatch on a separate task so we can cancel from the
// main task.
let handle = tokio::spawn(async move {
    dispatch_node(&node, &mut ctx).await
});

// After 500ms of work, cancel.
tokio::time::sleep(std::time::Duration::from_millis(500)).await;
cancel.cancel();

// The handler returns Err(DispatchError::UpstreamCancelled) at the
// next cancel checkpoint — p95 ≤100ms wall-clock (D3 invariant
// from 33.x.e preserved end-to-end through the dispatcher).
match handle.await? {
    Err(DispatchError::UpstreamCancelled) => {
        eprintln!("dispatch cancelled cleanly");
    }
    Ok(outcome) => {
        eprintln!("dispatch completed before cancel: {outcome:?}");
    }
    Err(e) => return Err(e.into()),
}
```

**Enforce the D7 invariant in your downstream module:**

See [MIGRATION_v1.26.md Scenario E](MIGRATION_v1.26.md#scenario-e--you-run-the-d7-parity-gate-in-your-own-ci)
for the 7-test grep gate template you can copy + adapt.

### What 33.z (axon-lang v1.27.x) graduates

When `flow_dispatcher::dispatch_node` gets grafted into
`server_execute_streaming` (the production-side wiring deferred
from 33.y.l to 33.z):

- Orchestration / PIX / algebraic / wire-integration / multi-agent / lambda flows become **per-chunk-streaming-eligible on the wire** (currently they fall back to the legacy synthetic-burst path with `axon-W002 streaming-not-supported`).
- The `axon.tool_call` SSE event family lights up — production SSE consumers observe `data: {"kind": "tool_call", "step_name": "...", ...}` interleaved with `axon.token` events in arrival order.
- The deprecated routing primitives (`PlanError::LegacyOrchestrationRequired` + `flow_plan::unsupported_feature_reason` + `axon_server::run_streaming_legacy_path`) are deleted; downstream code that ignored the deprecation warnings hits compile errors at the 33.z upgrade.
- 50-flow sync↔async parity corpus lands as the regression-gating contract — covers 10 banking + 10 government + 10 legal + 10 medicine + 10 cross-vertical flow shapes; each flow exercises ≥3 IRFlowNode variants.

Adopters upgrading v1.25.0 → v1.26.0 → v1.27.x in sequence see
**zero behavioral change at each hop for the canonical happy
path**; v1.27.x activates the dispatcher's universal coverage on
the production wire so non-canonical shapes also stream per-chunk.
Adopters that jump v1.25.0 → v1.27.x get both transitions at once
(the v1.26.0 surface deltas are strictly additive so the
intermediate hop is safe but not required).

### Migration scenarios

For the 5 worked recipes (server-only upgrade / consuming
ToolCall from a downstream crate / authoring a dispatcher-based
downstream crate / migrating off the deprecated routing
primitives / running the D7 parity gate in your own CI), see
[MIGRATION_v1.26.md](MIGRATION_v1.26.md).

---

## Where to file bugs

| Symptom | Where |
|---|---|
| `transport: sse` declared but `/v1/execute/sse` returns 404 | `axon-lang` issue tracker — route registration regression |
| SSE wire format invariant violated (no retry, non-monotonic ids, bare CR, missing terminator) | `axon-lang` issue tracker — wire conformance regression |
| Type-checker accepted `transport: sse` on a non-streaming flow | `axon-lang` issue tracker — soundness violation |
| Type-checker rejected `transport: sse` on a flow that genuinely produces a stream | `axon-lang` issue tracker — completeness violation; include the flow source |
| Keepalive comments not appearing on the wire during slow flow execution | `axon-lang` issue tracker — runtime regression |
| Python and Rust frontends disagree on the same source for `transport`/`keepalive` | `axon-lang` issue tracker — drift-gate violation, treated as a blocker |
| Cloudflare / ALB / nginx kept dropping the connection despite correct keepalive | check [Production deployment cookbook] above first; then `axon-lang` issue tracker with LB config attached |
| LSP doesn't complete the new fields | `axon-lsp` issue tracker |

---

## See also

- [STREAM_EFFECTS.md § HTTP wire format](STREAM_EFFECTS.md#http-wire-format-fase-30) — the algebraic-effect side of the contract.
- [Fase 30 plan vivo](fase_30_http_transport_stream_effects.md) — internal sub-fase tracker + D-letter ratifications (D1–D8).
- [ADOPTER_DIAGNOSTICS.md](ADOPTER_DIAGNOSTICS.md) — Fase 28 adopter-facing diagnostic guide; covers the error-message shape used by the Fase 30.c type-checker errors above.
- [axon-rs `tests/fase30_sse_runtime.rs`](../axon-rs/tests/fase30_sse_runtime.rs) — canonical SSE wire-format conformance test pack.
- [axon-rs `tests/fase30_sse_fuzz.rs`](../axon-rs/tests/fase30_sse_fuzz.rs) — D12 budget fuzz; reference for adopter-side SSE smoke-test scripts.
- [Fase 11.a — Stream<T> algebraic effect](fase_11_neuro_symbolic_axon.md) — the algebraic-effect foundation that Fase 30 routes onto the wire.

---

*This document is part of the axon-lang public adopter surface. PRs
welcome — see `CONTRIBUTING.md`.*
