# AXON v2.4.0 — Public streaming surface for downstream embedders

> **Released:** 2026-05-28
> **Type:** minor bump · additive API surface · zero breaking change
> **Theme:** §Fase 50.d/2 cross-stack catch-up — publicize the streaming
> entry point + state constructor so `axon-enterprise` (and any other
> downstream embedder) can drive real per-token SSE streaming without
> reimplementing the per-IRFlowNode dispatcher.

---

## What's new

### Public streaming API for embedders (§Fase 50.d/2)

Pre-v2.4.0, the streaming counterpart to
`axon::runner::execute_server_flow` lived behind module privacy:

- `axon::axon_server::server_execute_streaming` — the streaming entry
  point itself — was `fn` (module-private).
- `axon::axon_server::StreamingExecution` — the return-type handle
  (events receiver + per-step side-channels) — was `pub(crate)`.
- `axon::axon_server::SharedState` — the `Arc<Mutex<ServerState>>`
  alias — was a private `type`.
- `axon::axon_server::ServerState::new` — the constructor — was
  module-private `fn`.

This meant downstream Rust crates that consume `axon-lang` as a
versioned Cargo dep (notably `axon-enterprise`, which drives the
SaaS REST surface) could call the SYNCHRONOUS
`execute_server_flow` for batched-at-end execution but had no way
to reach the streaming path. Their only options were:

1. Reimplement the per-IRFlowNode async dispatcher on their side
   (massive scope creep + drift risk against the OSS canonical
   path).
2. Project batched per-step chunks as a sequence of SSE events
   AFTER execution completes (the `axon-enterprise` §Fase 50.d/1
   approach — correct wire shape but timing batched).

v2.4.0 closes that gap by publicizing the existing primitives:

- **`pub fn axon::axon_server::server_execute_streaming(...)`**
- **`pub struct axon::axon_server::StreamingExecution { ... }`** (the
  events receiver field stays `pub`, plus the per-step
  enforcement_summaries / step_audit_records / runtime_warnings
  side-channels)
- **`pub type axon::axon_server::SharedState`**
- **`pub fn axon::axon_server::ServerState::new(config: ServerConfig)`**
- **`impl Default for axon::axon_server::ServerConfig`** — minimal
  in-memory config (no DB, no auth token, INFO logs to stdout, no
  persisted state path). Total + side-effect-free when no on-disk
  recovery files exist.

The surface change is purely **additive** — every existing internal
call site keeps compiling, no signatures changed, no semantics
moved. Downstream embedders that don't need the streaming path see
no behavioural difference.

### Usage shape

```rust
use axon::axon_server::{ServerConfig, ServerState, server_execute_streaming};
use axon::cancel_token::CancellationFlag;
use std::sync::{Arc, Mutex};

let state = Arc::new(Mutex::new(ServerState::new(ServerConfig::default())));
let cancel = CancellationFlag::new();
let streaming = server_execute_streaming(
    state,
    source_text.to_string(),
    "<deploy-api>".to_string(),
    "ChatFlow".to_string(),
    "kimi".to_string(),
    cancel,
    None,                       // held_capabilities
    Some(body_json),
    request_path_map,
    request_query_map,
);

// Drive an SSE wire from the events receiver:
let mut rx = streaming.events;
while let Some(event) = rx.recv().await {
    // emit `axon.token` for `FlowExecutionEvent::StepToken`, etc.
}
```

### Workspace consistency: axon-frontend pin sync

The `axon-rs/Cargo.toml` dependency pin on `axon-frontend` was
stale at `=1.1.0` while `axon-frontend/Cargo.toml` had been bumped
to `1.2.0` in-tree. v2.4.0 updates the pin to `=1.2.0` so the
workspace builds cleanly without lockfile coercion.

---

## What didn't change

- **No semantic / behavioural change.** The publicity bump is shape-
  only; every existing call site of `server_execute_streaming` /
  `StreamingExecution` / `ServerState::new` inside `axon-rs` itself
  is byte-identical.
- **No wire change.** SSE event names, envelope shape, headers all
  stable per the §Fase 33.e contract.
- **No type system extension.** `Stream<T>` semantics unchanged.
- **`execute_server_flow` synchronous path unchanged.** Adopters
  using the batched/non-streaming entry point see zero
  difference.
- **Per-tenant LLM API key threading.** The current
  `server_execute_streaming` signature does NOT take an
  `api_key_override` parameter (state-based key lookup only).
  Downstream embedders that need per-tenant keys on the streaming
  path either set env vars at request scope (not thread-safe
  across concurrent requests) OR keep using batched-emit. A
  follow-up `axon-lang v2.5.0 / §Fase 50.d/3` will thread
  `api_key_override` through the streaming path; until then,
  per-tenant streaming requires the env-var-injection bridge on
  the embedder side.

---

## Who should upgrade

- **`axon-enterprise` v3.0.x adopters** — pin `axon-lang = "=2.4.0"`
  to unlock the §Fase 50.d/2 real per-token streaming on the
  enterprise SaaS REST surface.
- **Any downstream Rust crate** that wants to embed AXON streaming
  semantics in its own HTTP / SSE / NDJSON layer.
- **CLI / Python-only adopters** — no urgency. The publicity bump
  doesn't affect the `axon` binary or the Python `axon_lang`
  package's adopter-visible surface; the bump exists to unblock
  programmatic Rust embedders.

---

## How to upgrade

### Rust dep
```toml
[dependencies]
axon-lang = "=2.4.0"
```

### Python package
```bash
pip install --upgrade axon-lang  # 2.4.0
```

### CLI
```bash
cargo install axon-lang --version 2.4.0
# or download platform binary from the GitHub Release v2.4.0 page
```

---

## Tests

- `axon-lang` lib: **2245 / 2245 green** (no test changes; the
  publicity bump compiles into the same test surface).
- `axon-frontend` lib: 535 / 535 green.
- `axon-csys` lib: 13 / 13 green.
- Workspace build clean post-bump.

---

## §Fase 50 cycle context

§Fase 50 is the `axon-enterprise` runtime-invocation port that
replaces the §Fase 49.b/4 stub executor with `AxonRuntimeFlowExecutor`.
The cycle ships 6 enterprise-side sub-fases (50.a non-streaming
runtime → 50.b LLM backend + per-tenant secret → 50.c algebraic-
effect dispatcher surfacing → 50.d/1 SSE wire shape via batched emit
→ 50.e vertical scanner registration → 50.f per-step audit
emission), plus this v2.4.0 cross-stack catch-up (§50.d/2) that
unblocks real per-token SSE timing on the enterprise side.

Post-v2.4.0, `axon-enterprise` swaps its `execute_streaming` from
batched-emit (which projects per-step chunks AFTER synchronous
execution) to real per-token (driven by the events receiver from
this v2.4.0 public `server_execute_streaming`). Wire bytes
identical between batched-emit and real-time; only inter-event
delay changes.

---

## Acknowledgements

Diagnosed by the Kivi M_v3-3 cutover acceptance criterion (brief
#11 §F): SSE per-token timing with the `axon.complete` envelope
shape the OSS smoke 18 trail produced. Without v2.4.0's publicity
bump, enterprise embedders could match the wire shape (batched-
emit) but not the timing. v2.4.0 closes the timing gap by exposing
the primitive that already existed; the dependency on adopter-side
self-rolled streaming is removed.

— Bemarking AI · `support@bemarking.com.co`
