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
7. [Type-checker enforcement rules](#type-checker-enforcement-rules)
8. [Common compile errors + fixes](#common-compile-errors--fixes)
9. [Backwards compatibility matrix](#backwards-compatibility-matrix)
10. [Production deployment cookbook](#production-deployment-cookbook)
11. [Troubleshooting checklist](#troubleshooting-checklist)
12. [Client-side EventSource recipe](#client-side-eventsource-recipe)
13. [LSP / IDE integration recipe](#lsp--ide-integration-recipe)
14. [CI integration recipe](#ci-integration-recipe)
15. [Cross-stack contract: Python ↔ Rust](#cross-stack-contract-python--rust)
16. [Where to file bugs](#where-to-file-bugs)

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
