# AXON v2.4.0 — Public streaming surface + Proof-Carrying Code

> **Released:** 2026-05-28 (streaming) · 2026-05-30 (PCC additions)
> **Type:** minor bump · additive API surface · zero breaking change
> **Theme:** two additive headline surfaces — (1) §Fase 50.d/2 cross-stack
> catch-up publicizing the streaming entry point so embedders can drive real
> per-token SSE, and (2) §Fase 51/52 **Proof-Carrying Code**: a new
> `axon::pcc` module + `axon pcc prove`/`verify` CLI that emit a portable,
> machine-checkable proof object an INDEPENDENT verifier re-checks against the
> artifact — without trusting the compiler that produced it (Necula 1997).

---

## What's new — Part 1: streaming surface

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

v2.4.0 pins `axon-frontend = "=1.3.0"`. **axon-frontend 1.3.0** is a
companion release: 1.2.0 was already published to crates.io WITHOUT the
`requires_capabilities` field, so the PCC capability-containment lowering
(`requires_capabilities` on `IRAxonEndpoint`, §51.x.1) ships as the additive
1.3.0 bump. Publish order: axon-frontend 1.3.0 → axon-lang 2.4.0.

---

## What's new — Part 2: Proof-Carrying Code (§Fase 51 / 52)

A new `pub mod pcc` turns "trust the axon compiler" into "verify the proof."
Every `apx` / `axonendpoint` can carry a portable, serializable **proof
object** (`ProofTerm` / `ProofBundle`) certifying a declared contract; a
minimal **independent checker** re-derives the property from the artifact and
verifies the witness — it never trusts the witness, and binds each proof to a
specific artifact via a SHA-256 IR digest (a proof for program A cannot be
replayed against program B).

This is **Proof-Carrying Code** (Necula 1997): the producer ships code + a
proof; the consumer runs a small trusted checker, cheaper than generation and
independent of trust in the producer. It is categorically stronger than the
existing attestation surfaces (SBOM / in-toto / SLSA / ComplianceDossier),
which are builder-signed claims you trust the signer for.

### Six property classes

- **ComplianceCoverage** — an endpoint's declared `compliance: [...]` is fully
  provided by its resolved shield (`covers(provided, required) == ∅`).
- **EffectRowSoundness** — a tool's declared effect row is well-formed over
  the known effect-base catalog (+ stream-qualifier validity).
- **CapabilityIsolation** — each axonstore capability gate is grammatical.
- **ResourceBounds** — endpoint retry counts + socket backpressure credits are
  finite and in-bounds.
- **ShieldHaltGuarantee** — a `on_breach: halt` shield is non-vacuous (a
  non-empty `scan:` so the halt can actually fire).
- **CapabilityContainment** (§51.x.1) — the capabilities reachable through an
  endpoint's executed flow are a subset of what the endpoint declares in
  `requires:`. The negation is a **capability leak**: an under-declared
  endpoint that could reach a more-privileged store. The reachability walk is
  an exhaustive, no-wildcard match over every `IRFlowNode` variant (§51.x.3 —
  the compiler enforces it can never silently miss a future node).

### `check_bundle` deployability aggregate (§52.a)

`axon::pcc::check_bundle(&ProofBundle, &IRProgram) -> BundleReport` is the one
trusted predicate for "is this bundle deployable" (`all_verified()` +
`refutations()`). The policy lives in the checker, not in consumer glue — so
the `axon pcc verify` CLI and any downstream deploy gate render identical
verdicts. (`axon-enterprise` v3.1.0 consumes exactly this for a fail-closed
proof-at-deploy gate.)

### `axon pcc` CLI (§51.f)

- **`axon pcc prove <source.axon> [-o bundle.json]`** — compile, generate the
  full `ProofBundle` across all property classes, emit JSON.
- **`axon pcc verify <source.axon> <bundle.json>`** — recompile the source (an
  INDEPENDENT re-derivation), check every proof against it, exit 0 iff all
  verified.

### Surface (all additive)

`pub mod pcc` re-exports `ProofTerm`, `ProofBundle`, `PropertyClass` (6
variants), the witness structs, `check_proof`, `check_bundle`, `BundleReport`,
`generate_all_proofs`, `artifact_digest`, and the per-class generators. Plus
`pub mod pcc_cli` for the CLI entry points. No existing surface changed.

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

- `axon-lang` lib: **2316 / 2316 green** (streaming publicity is shape-only;
  +71 of those are the new `pcc` suite — 13 ComplianceCoverage + 12
  EffectRowSoundness + 7 CapabilityIsolation + 10 ResourceBounds + 8
  ShieldHaltGuarantee + 9 CapabilityContainment + 5 check_bundle + 4 CLI +
  3 §51.x.3 invariant gates, incl. adversarial forged-witness + digest-mismatch
  cases per class).
- `axon-frontend` lib: 535+ green (incl. the `requires_capabilities` lowering).
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
