---
title: "Plan vivo: Fase 33 — SSE as Cognitive Primitive (real-time algebraic-effect streaming end-to-end)"
status: IN PROGRESS 2026-05-12 — D1–D10 RATIFICADAS bloque; 33.a + 33.b + 33.c SHIPPED; 33.d–33.i execution per incremental founder sign-off cadence (Fase 28/30/31/32 established pattern). Trigger = adopter MIGRATION_TO_AXON.md trail 2026-05-12 post-v1.23.1
owner: AXON Runtime + Backends Team
created: 2026-05-12
target: axon-lang v1.24.0 (minor — SSE wire semantics change from synchronous-burst to live incremental streaming; D9 backwards-compat preserved for clients that don't depend on incremental delivery)
depends_on: Fase 11.a SHIPPED (Stream<T> algebraic effect catalog); Fase 11.b SHIPPED (zero-copy buffers); Fase 23 SHIPPED (algebraic effects runtime — delimited continuations); Fase 24 SHIPPED (7 native Rust LLM backends with `BackendError::Generic("streaming not yet implemented")` stubs); Fase 30 SHIPPED v1.21.0 (HTTP transport surface — SSE wire-format invariants); Fase 31 SHIPPED v1.22.0 (Type-Driven Wire Inference); Fase 32 SHIPPED v1.23.0/v1.23.1 (Axonendpoint as First-Class HTTP REST + Rust parser disjunct (a))
charter_class: OSS — every adopter benefits transitively. Real-time token streaming from backend → through algebraic effect → onto SSE wire is the foundational behavior that makes axon a streaming-native cognitive language, not just a streaming-headers language
pillars: MATHEMATICS — Stream<T> algebraic effect is a delimited continuation; LOGIC — the type system's effect declaration IS the runtime's wire behavior (declared `Stream<T>` ⟺ live SSE events); PHILOSOPHY — SSE is a cognitive primitive in axon; it is "todo" — must work perfectly across all four pillars; COMPUTING — D9 backwards-compat preserved for adopters not consuming incremental delivery
---

> **Founder directive 2026-05-12 (verbatim, post-v1.23.1):**
>
> *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto en todos los escenarios posibles. […] no pienses en kivi, piensa a axon necesita resolver esto."*
>
> **Adopter trail (verbatim, post-v1.23.1, after 10 bumps in 5 days):**
>
> *"10 bumps en 5 días. Mismo resultado. […] el feature está más cerca de los cimientos del runtime de lo que parecía — no es un parser fix, no es un patch quirúrgico, es un piece de arquitectura que necesita su propio cycle."*
>
> *"kivi sirvió de production-validator para axon en algo que descubrieron junto con nosotros. […] el agente que termina saliendo es el primero con SSE algebraic effects nativo en cuanto el cable cae."*

---

## ▶ 1. What v1.23.1 closed (Fase 32.l) — the Content-Type layer

Fase 32.l (commit `cdef6bf`, released as v1.23.1) closed the Rust parser disjunct (a) gap: `step S { output: Stream<T> }` is now correctly captured into the AST (was previously dropping `<T>` and reading only `"Stream"`). This propagates through:

- `flow_has_stream_output` → returns `true` for the canonical shape (previously `false`).
- `produces_stream` → returns `true`.
- `implicit_transport` → resolves to `"sse"` (previously `"json"`).
- `classify_dynamic_route_wire` → returns `DynamicRouteWire::Sse` (previously `Json`).
- `dynamic_endpoint_handler` → dispatches to `execute_sse_handler`.
- Wire `Content-Type` → `text/event-stream` (previously `application/json`).

This was **necessary but not sufficient**. The wire header is correct; the wire BODY is hollow.

---

## ▶ 2. What v1.23.1 did NOT close — the four architectural layers

Diagnostic test [`axon-rs/tests/fase33_sse_full_body_diagnostic.rs`](../axon-rs/tests/fase33_sse_full_body_diagnostic.rs) (committed `bb98347`) captures the v1.23.1 wire shape verbatim — and surfaces four distinct architectural gaps that compose into the adopter's "mismo resultado" experience:

### Layer 1 — Data-flow gap (runner → ServerExecutionResult)

The wire body for the canonical Kivi-shape source produces:

```
retry: 5000
event: axon.token
id: 1
data: {"step":"","timestamp_ms":...,"token":"","trace_id":1}
event: axon.complete
id: 2
data: {"steps_executed":0,...}
```

`step:""`, `token:""`, `steps_executed:0` — even though `runner.rs` prints "1 steps completed (stub mode)" on stdout. The step results never propagate from the runner into `ServerExecutionResult.step_names`/`step_results`. The `StreamEmitter` for-loop iterates the empty `step_names`, emits nothing, then `finalize()` pushes the sentinel-only token (empty step, empty content, `is_final: true`). The client sees one empty `axon.token` event followed by `axon.complete` with `steps_executed: 0`.

This is a runtime data-flow bug independent of streaming semantics. Fixing it makes the wire body carry real content; the streaming semantics (#2-#4 below) still need their own work.

### Layer 2 — Execution-model gap (synchronous → async stream)

`server_execute_full` is synchronous. `execute_sse_handler` spawns it on `tokio::task::spawn_blocking`, awaits the entire flow execution, THEN starts emitting `axon.token` events from the collected `step_results`. The wire's `retry: 5000` directive fires immediately, but data events don't appear until execution completes — for a real LLM call that's 30-60 seconds of silence followed by a burst.

Per W3C SSE this is valid: clients keep the connection open and consume events as they arrive. But for adopter UX (chat-with-LLM, clinician CDS, etc.) where token-by-token rendering is the expected behavior, the user-visible result is "broken streaming" even though the wire format is technically correct.

### Layer 3 — Backend-streaming gap (LLM provider streams are stubbed)

All 7 native Rust LLM backends (`axon-rs::backends::{anthropic, openai, gemini, kimi, glm, ollama, openrouter}`) ship `BackendError::Generic("streaming not yet implemented")` on their `stream() -> Pin<Box<dyn Stream<...>>>` surface (per memory: "Streaming explícito BackendError::Generic 'not yet implemented' born-mature en cada backend (per-provider streaming impls ship as 24.x.2 followups)").

Even with (#2) fixed (executor refactored to async), there is no source-of-truth stream to consume. The flow runtime would call `backend.stream(...)` and receive an error.

The 7 providers each have their own streaming protocol:
- **Anthropic** — SSE-like format (`event: content_block_delta` + `data: {"type": "content_block_delta", "delta": {...}}`).
- **OpenAI** — SSE with `data: {chunk}\n\n` chunks, terminated by `data: [DONE]\n\n`.
- **Gemini** — `:streamGenerateContent` JSON-streaming (NOT SSE — newline-delimited JSON).
- **Kimi** — OpenAI-compatible SSE.
- **GLM** — Server-Sent-Events or chunked JSON depending on family.
- **Ollama** — newline-delimited JSON (`/api/chat` with `stream: true`).
- **OpenRouter** — OpenAI-compatible SSE.

Each needs a real `Stream<Item = Result<BackendChunk, BackendError>>` impl.

### Layer 4 — Algebraic-effect runtime gap (tool stream effects don't fire)

The declaration:

```axon
tool chat_token_stream {
    description: "Token-by-token LLM completion"
    effects: <stream:drop_oldest>
}
flow Chat() -> Unit {
    step Generate { ask: "hi" apply: chat_token_stream }
}
```

The type checker (Fase 11.a + Fase 30.c disjunct (b)) recognizes the `stream:drop_oldest` effect, marks the flow as stream-producing, and inference fires `implicit_transport = "sse"` (Fase 31.b). But at **runtime**, the `apply: chat_token_stream` step invocation does NOT activate any stream-effect handler that emits each token to the SSE channel. The effect declaration is **compile-time documentation**, not a runtime contract.

To close this: the algebraic-effect handler dispatch (Fase 23 runtime — delimited continuations + handlers) needs a `stream:<policy>` effect handler that:
1. Receives `Stream<Token>` chunks from the underlying backend stream (layer 3).
2. Applies the declared backpressure policy (`drop_oldest`, `degrade_quality`, `pause_upstream`, `fail` — Fase 11.a's 4-policy catalog).
3. Forwards each token to the SSE wire channel (layer 2) AS IT ARRIVES.

This wires the four pillars together: MATHEMATICS (algebraic effect = delimited continuation = the `Stream<T>` monad), LOGIC (effect-row in type ⟺ effect-handler at runtime), PHILOSOPHY (declared effect IS the wire behavior), COMPUTING (backpressure policy is honored on the wire — adopters writing `<stream:drop_oldest>` get tokens dropped under saturation, not arbitrary blocking).

---

## ▶ 3. D-letter proposals (D1–D10)

| # | Statement | Pillar(s) |
|---|---|---|
| **D1** | **Real-time SSE streaming is a foundational behavior, not a wire-format header** — every accepted source where the type system infers `Stream<T>` MUST produce a wire that emits each backend chunk as a discrete `axon.token` event AS IT ARRIVES, with the underlying backend's actual chunk granularity (not synthetic 3-word rechunking). | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D2** | **Data-flow integrity (Layer 1) ratified at the type level** — `ServerExecutionResult` is replaced by an event-stream return type `Stream<FlowExecutionEvent>` where `FlowExecutionEvent ∈ {StepStart, StepToken, StepComplete, FlowComplete, FlowError}`. The runner emits each event as it occurs; the SSE handler consumes the stream and forwards directly. | LOGIC + COMPUTING |
| **D3** | **Backend streaming is canonical, not opt-in** — every Fase 24 native backend MUST implement `Backend::stream() -> Pin<Box<dyn Stream<Item = Result<BackendChunk, BackendError>>>>` natively. The `BackendError::Generic("streaming not yet implemented")` stub is removed. Per-provider impls: Anthropic SSE / OpenAI SSE / Gemini JSON-stream / Kimi OpenAI-compat / GLM SSE / Ollama JSON-stream / OpenRouter OpenAI-compat. | COMPUTING |
| **D4** | **Algebraic-effect runtime honors the `<stream:<policy>>` declaration** — when a tool declares `effects: <stream:drop_oldest>` (or any of the 4 policies from Fase 11.a), the Fase 23 effect handler dispatcher consumes the backend stream + applies the declared backpressure policy + forwards each token to the SSE wire. The declaration becomes the runtime contract. | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D5** | **Keepalive only fires during real inactivity** — `axum::response::sse::KeepAlive` interval is honored, but the comment lines `: keepalive\n\n` only fire when the upstream stream is genuinely silent (>15s gap between backend chunks). With real backend streaming (D3), keepalive becomes meaningful instead of a synthetic burst-pre-emit comment. | COMPUTING |
| **D6** | **Cancel-safety: client disconnect aborts upstream execution** — when the adopter's HTTP client disconnects (browser tab closed, EventSource.close()), the spawned execution task receives a cancellation signal and aborts the backend stream consumer. Today the executor runs to completion regardless. Fase 33 adds `tokio::task::JoinHandle::abort` on `oneshot` cancellation channel triggered by SSE response drop. | COMPUTING |
| **D7** | **Backpressure honored end-to-end** — when the adopter declares `<stream:drop_oldest>` and the client drains slowly, the runtime drops oldest tokens from the buffer (NOT the connection). When the adopter declares `<stream:pause_upstream>`, the runtime sends backpressure to the backend (where supported — OpenAI/Anthropic SSE don't have a backpressure mechanism, so `pause_upstream` degrades to `drop_oldest` with a runtime warning). | LOGIC + COMPUTING |
| **D8** | **D8 + D9 + D10 absolute backwards-compat preserved from Fase 32** — `/v1/execute` legacy path unaffected; dynamic-route Content-Type matrix unchanged; D9 `replay: true` binding integrates with streaming (per-event chain replayability is a future Fase 34 — Fase 33 records the FINAL flow output for non-streaming POSTs, defers streaming-replay). | COMPUTING |
| **D9** | **Backwards-compat for the wire body** — adopters whose clients accept the synchronous-burst behavior (consume the stream and use it as final output) MUST continue to work without source change. The new live-streaming behavior is the same SSE wire format byte-for-byte; the only observable difference is timing (tokens arrive over time instead of all at once). No new `transport:` enum values; no new declaration fields. | COMPUTING |
| **D10** | **Four-pillar trace requirement (meta)** — every Fase 33 D-letter MUST map to ≥ 1 of {MATHEMATICS, LOGIC, PHILOSOPHY, COMPUTING}. D-letters that fail the trace are rewritten or cut. **Founder principle**: SSE is a cognitive primitive; it is "todo"; therefore the whole feature ships as a coherent contract or not at all (no partial / asterisked deliverables). | PHILOSOPHY (meta) |

---

## ▶ 4. Sub-fase shape — sequenced execution

Each sub-fase ships independently behind founder sign-off (Fase 28/30/31/32 incremental cadence), but each builds on the prior. The order is topological — Layer 1 unblocks Layer 2 (which unblocks Layer 4); Layer 3 is parallel to Layers 1+2 since it only consumes the same channel surface.

| Sub-phase | Layer | LOC target | Description |
|---|---|---|---|
| **33.a** | spec | doc-only | ✅ SHIPPED 2026-05-12 — This doc + memory entry `project_fase_33_plan.md` + MEMORY.md index update. Founder bloque ratification of D1–D10 locked verbatim ("Ratifico las todas las D-letter. Procede con 33.a"). Diagnostic anchor `axon-rs/tests/fase33_sse_full_body_diagnostic.rs` (commit `bb98347`) captures the v1.23.1 hollow wire shape as the snapshot the cycle rewrites. |
| **33.b** | Layer 1 | ~470 (axon-rs flow_execution_event module incl. 7 unit tests) + ~280 (Python mirror module) + ~145 (shared corpus.json 12 entries) + ~205 (Python drift gate 25 tests) + ~270 (Rust drift gate 7 tests) + ~40 (runner.rs report-population fix) + ~210 (Rust anchor regression 4 tests) | ✅ SHIPPED 2026-05-12 — Closed catalog `FlowExecutionEvent { FlowStart, StepStart, StepToken, StepComplete, FlowComplete, FlowError }` cross-stack (Rust `axon::flow_execution_event` + Python `axon.runtime.flow_execution_event`). Shared corpus at [`tests/fixtures/fase33_flow_execution_event/corpus.json`](../tests/fixtures/fase33_flow_execution_event/corpus.json) (12 entries, D2+D10 anchor) parametrizes both drift gates — Rust serde round-trip + Python `to_json/from_json` round-trip must match byte-for-byte. Helpers `is_terminator()`/`is_step_scoped()`/`kind()` are total over every variant. **Bug fix**: closes the hollow-wire `steps_executed:0` / `step:""` / `token:""` regression — pre-fix `execute_server_flow` ran `execute_stub` but never populated the ReportBuilder for the stub path (CLI did, server didn't). Post-fix the server path mirrors the CLI's report-population pattern (each step records a StepReport with `result: "(stub)"` placeholder); real backend streaming (Fase 33.d) replaces "(stub)" with actual chunk text. **Diagnostic anchor before/after**: pre-33.b wire `{step:"", token:"", steps_executed:0}` → post-33.b wire `{step:"Generate", token:"(stub)", steps_executed:1}` (plus the StreamEmitter's `is_final:true` sentinel terminator). Test surface: 7 Rust lib unit (flow_execution_event::tests) + 7 Rust drift gate (corpus + variants + predicates + serde rejection) + 25 Python drift gate (corpus parametrize + catalog closure + helper totality + receiver-invariant partition) + 4 Rust anchor regression (v1/execute reports nonzero + SSE wire carries step+token + multi-step visible + audit trace correct) = **43 new tests for 33.b**. Zero regressions across the 1454 axon-rs lib + Fase 30/31/32 + 33.l + 33-diagnostic surfaces. The diagnostic anchor [`axon-rs/tests/fase33_sse_full_body_diagnostic.rs`](../axon-rs/tests/fase33_sse_full_body_diagnostic.rs) was the pre-fix snapshot; its assertions remained the same but now observe non-hollow content (axon_token count went 1→2, the second one is the StreamEmitter's sentinel finalizer). |
| **33.c** | Layer 2 | ~430 (axon_server.rs `server_execute_streaming` producer + `execute_sse_handler` refactor) + ~75 (trace_store reserve_id/record_with_id surface incl. 6 unit tests) + ~440 (Rust integration tests 10) | ✅ SHIPPED 2026-05-12 — `execute_sse_handler` now consumes a `tokio::sync::mpsc::UnboundedReceiver<FlowExecutionEvent>` from new producer `server_execute_streaming` and projects each event onto the SSE wire AS IT ARRIVES rather than after the synchronous executor returns. Closed-catalog mapping: `FlowStart`/`StepStart`/`StepComplete` are consumed silently (preserves byte-identical wire body per D9 — Fase 30+31+32 contracts unchanged); `StepToken` → `axon.token` wire event; `FlowComplete` → `axon.complete`; `FlowError` → `axon.error`. trace_id allocated up front via new `trace_store.reserve_id()` so every wire event carries the same trace_id from the first token onward (adopter audit replay surface `/v1/replay/<id>` bindable from event 1). Trace entry persisted via new `trace_store.record_with_id(entry, reserved_id)` once the producer channel closes — full audit-parity with the JSON `/v1/execute` path preserved. Cancel-safety baseline: SSE `tx.send(...).ok()` swallows client-disconnect errors but the consumer KEEPS draining `event_rx` so the executor completes cleanly (Fase 33.f formalizes the abort-within-100ms invariant). Defense-in-depth terminator-missing handler: if the producer drops without emitting `FlowComplete` or `FlowError`, the consumer fabricates an `axon.error` so the wire is always well-formed. Test surface: 10 integration tests (`fase33_c_live_event_forwarding.rs` — single-step + multi-step wire shape + trace_id correlation + event-id monotonicity + first-event invariant + last-event invariant + not-deployed path + trace audit parity + catalog-closure pin + runtime-surface importability) + 6 trace_store unit tests (`reserve_id_monotonic_and_consumes_next_id` + `reserve_id_disabled_store_returns_zero` + `record_with_id_persists_under_reserved_id` + `record_with_id_does_not_advance_next_id` + `record_with_id_disabled_store_is_noop` + `reserve_then_record_preserves_audit_correlation`) = **16 new tests for 33.c**. Zero regressions across the 26 Fase 33-family + 117 Fase 32 + 47 Fase 30/31 SSE + 1453 axon-rs lib unit tests (pre-existing intermittent jwt_verifier env-var race confirmed independent — passes on serial runs). What 33.c proves architecturally: the producer/consumer split is in place and the wire body is byte-identical with the post-33.b shape; what 33.c does not yet prove (deferred to 33.d): real per-token wall-clock incrementality (the stub backend produces output synchronously; once `Backend::stream()` is real per-provider, the same handler delivers each chunk as the network bytes arrive — NO further handler changes needed). |
| **33.d** | Layer 3 | ~1200 | Per-provider `Backend::stream()` impls: Anthropic (SSE), OpenAI (SSE), Gemini (JSON-stream), Kimi (OpenAI-compat), GLM (SSE), Ollama (JSON-stream), OpenRouter (OpenAI-compat). Each provider: ~150 LOC + ~30 LOC of unit tests (parse-chunk + error-mid-stream + completion + cancellation). |
| **33.e** | Layer 4 | ~500 | Fase 23 effect-handler dispatcher gains a `stream:<policy>` handler that consumes a `Stream<BackendChunk>`, applies the declared backpressure policy (Fase 11.a's 4 from Stream<T>), and forwards to the wire channel. Policy ∈ {drop_oldest, degrade_quality, pause_upstream, fail}; `pause_upstream` degrades gracefully on protocols without backpressure. |
| **33.f** | D6 | ~200 | Cancel-safety: spawn the executor with a cancellation token bound to the SSE response's `Drop`. Verify via integration test that closing the client mid-stream triggers backend stream abort within ~100ms. |
| **33.g** | CI + fuzz | ~250 | New CI lane in `.github/workflows/fase_33_sse_cognitive_primitive.yml`: per-provider streaming verification (stub HTTPS server that mimics each provider's stream protocol; verify the runtime correctly chunks + forwards), live-timing test (real `axum::serve` on `TcpListener` + EventSource client measuring inter-token latency), cancellation timing test (client disconnect → backend abort within deadline), backpressure-policy fuzz (random arrival rates + drain rates verify each policy's invariant). |
| **33.h** | Adopter docs | ~300 | `docs/ADOPTER_STREAMING.md` § "Real-time streaming (Fase 33, v1.24.0+)" — explains the wire-body change (timing only, not format); per-provider streaming notes; migration recipe for clients that depended on the synchronous-burst behavior (none — the wire format is unchanged, only timing). |
| **33.i** | Release | release | Coordinated cross-stack v1.24.0 + axon-enterprise v1.14.0 catch-up. Enterprise vertical layers — banking streaming-audit replay (Fase 11.c integration with per-event token chain), HIPAA streaming-PHI-scrubbed CDS — are the substantive enterprise R&D that earns v1.14.0+ enterprise-only releases. |

---

## ▶ 5. Vertical-grounded relevance

Same four high-profile verticals from Fase 32, now with streaming:

- **Banking** — `POST /loan/decision` with `transport: sse + replay: true` streams risk-explanation narration token-by-token. Auditors retrieve via `GET /v1/replay/<trace_id>` and see the FULL token sequence + final decision. PCI DSS Req 10 audit-defensible because each token is hash-chained.
- **Government** — `POST /benefits/eligibility` streams the eligibility-reasoning narrative. FOIA requests retrieve the live trace.
- **Legal** — `POST /discovery/privilege` streams the privilege-assessment reasoning. FRE 502 waiver-doctrine appeals trace the exact reasoning steps.
- **Medicine** — `POST /clinical/decision-support` streams clinical recommendations to clinician UI token-by-token. The PHI scrubber (Fase 27.g) runs upstream of every chunk. 21 CFR Part 11 §11.10 audit retains the full stream.

Each vertical pattern works today with `Content-Type: text/event-stream` (v1.23.1) but the wire body burst-arrives at end-of-flow. Fase 33 makes the token-by-token delivery real, which is what clinician/banking/legal/government UIs need.

---

## ▶ 6. Founder-framing — why this is "su propio cycle"

The adopter and founder framing converge on the same insight:

> **Adopter**: *"es un piece de arquitectura que necesita su propio cycle"*
> **Founder**: *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto"*

Fase 28 → Fase 32 closed the **wire surface** (transport, declarations, routing, validation, idempotency, auth, replay, audit). v1.23.1 closed the **parser cross-stack parity** for disjunct (a). Each step shipped under a single founder sign-off cadence.

Fase 33 closes the **runtime substrate**. Four layers, each with their own type-system contract, runtime handler, backend protocol, and observable timing. None can be skipped. None can ship in isolation — Layer 1 without Layer 2 doesn't help adopters; Layer 2 without Layer 3 has no chunks to forward; Layer 4 without Layer 3 has no chunks to receive.

The cycle ends when the diagnostic test
[`tests/fase33_sse_full_body_diagnostic.rs`](../axon-rs/tests/fase33_sse_full_body_diagnostic.rs) — which today captures hollow `step:""`, `token:""`, `steps_executed:0` — captures dense, time-spaced, per-backend-chunk `axon.token` events with real content. The same test file rewrites its assertions when each sub-fase ships.

---

## ▶ 7. Bloque ratification — RATIFICADAS 2026-05-12

Founder reviewed §1 (what shipped) + §2 (what didn't) + §3 (D-letters D1–D10) + §4 (sub-fase shape) + §5 (vertical-grounded) + §6 (founder framing) and ratified verbatim:

> **"Ratifico las todas las D-letter. Procede con 33.a (100% robusto)."** — 2026-05-12

D1–D10 are now the locked contract for the Fase 33 cycle. 33.a (this doc + memory entry + diagnostic anchor) is SHIPPED with this ratification commit. 33.b–33.i proceed per the established Fase 28/30/31/32 incremental founder sign-off cadence (`procede con 33.X (100% robusto)` per sub-fase).

The diagnostic test [`axon-rs/tests/fase33_sse_full_body_diagnostic.rs`](../axon-rs/tests/fase33_sse_full_body_diagnostic.rs) (commit `bb98347`) is the snapshot anchor — its current `step:""`, `token:""`, `steps_executed:0` assertions rewrite as each sub-fase lands. When 33.i ships, those assertions read the dense, time-spaced, per-backend-chunk wire the founder principle requires.

---

## ▶ 8. Out of scope (deferred to Fase 34+)

- **Per-event replay binding** (token-by-token replay chain) — Fase 33 keeps Fase 32.h's final-response replay model. Per-event chain requires a per-token signature chain (~Fase 11.c primitive extension) and ships as Fase 34 if/when adopters need it.
- **gRPC streaming binding** — Fase 33 ships SSE only. gRPC bidirectional streams are a future Fase orthogonal to the SSE work.
- **WebSocket upgrade from SSE** — out of scope; SSE is the chosen wire format per Fase 30 D2.
- **Mid-stream tool calling** — when a flow's stream emits a request for a side-effectful tool call mid-stream (function calling), the tool result is interleaved into the stream. Out of scope for 33; tracked separately as Fase 33-followon.
- **Tokenizer-aware chunking when backend doesn't ship chunk granularity** — for backends that return final text only (no stream API), Fase 33 keeps the synthetic 3-word rechunking but adds a runtime warning `axon-W002` so adopters know they're seeing simulated streaming. Real per-provider streaming ships in 33.d.

---

## ▶ 9. Test surface target (~600 new tests)

| Surface | Test count | Module(s) |
|---|---|---|
| Layer 1 — `FlowExecutionEvent` enum + cross-stack drift | 50 | Python + Rust |
| Layer 1 — `runner.rs` emits events instead of strings | 80 | Rust |
| Layer 1 — `server_execute_full` returns event stream | 40 | Rust |
| Layer 2 — `execute_sse_handler` live forwarding | 60 | Rust (incl. `tokio::test` w/ real TcpListener) |
| Layer 2 — Inter-token timing < 100ms when backend streams at 50 tokens/sec | 20 | Rust integration |
| Layer 3 — Anthropic SSE parser + chunk handling | 30 | Rust |
| Layer 3 — OpenAI SSE parser + `[DONE]` terminator | 30 | Rust |
| Layer 3 — Gemini JSON-stream parser | 30 | Rust |
| Layer 3 — Kimi OpenAI-compat | 20 | Rust |
| Layer 3 — GLM SSE | 20 | Rust |
| Layer 3 — Ollama JSON-stream | 30 | Rust |
| Layer 3 — OpenRouter OpenAI-compat | 20 | Rust |
| Layer 4 — `<stream:drop_oldest>` policy honored | 30 | Rust |
| Layer 4 — `<stream:degrade_quality>` policy | 25 | Rust |
| Layer 4 — `<stream:pause_upstream>` policy (+ degrade warning) | 25 | Rust |
| Layer 4 — `<stream:fail>` policy | 15 | Rust |
| D6 — Cancel-safety: client disconnect → backend abort | 15 | Rust |
| D7 — Backpressure fuzz across all 4 policies × arrival/drain rates | 60 | Rust |
| D9 — Wire-format byte-identical to v1.23.1 except timing | 10 | Rust |
| Vertical canonical patterns w/ real streaming | 20 | Rust |

---

## ▶ 10. Versioning + release plan

**Target**: axon-lang v1.24.0 (minor — wire body changes in timing semantics but format-byte-identical; D9 keeps adopters who consume the burst working unchanged). Per SemVer + founder versioning discipline.

**axon-frontend bump**: 0.11.x → 0.12.0 if the AST adds new fields to capture per-step event emission (TBD per 33.b implementation choice).

**axon-enterprise catch-up**: v1.14.0 (lean catch-up consuming axon-lang ≥ 1.24.0) PLUS substantive vertical layers (banking streaming-audit + HIPAA streaming-PHI-scrubbed CDS + legal streaming-privilege-review-trace).

---

## ▶ 11. Founder-principle reinforcement

> *"Hacer que una aplicación AI sea determinista y fundada en nuestros cuatro pilares como lenguaje es el aporte a la humanidad por el que estamos trabajando"* (2026-05-11, Fase 32 trigger).
>
> *"SSE es una primitiva cognitiva, eso en axon lo es todo y debe funcionar perfecto"* (2026-05-12, Fase 33 trigger).

Fase 32 made `axon` honor REST declarations. Fase 33 makes `axon` honor STREAM declarations. After Fase 33, when an adopter writes `step S { output: Stream<Token> }` in their `.axon` source, every single token from the underlying LLM backend reaches the adopter's EventSource client as a discrete `axon.token` SSE event with the backend's actual chunk granularity, with the declared backpressure policy honored, with the declared `replay: true` recording each event, with the declared `requires: [cap]` gating the connection — every layer of the language wires into the wire.

That's the axon-shaped contribution to humanity's ability to deploy regulated, audit-defensible, real-time AI.

---

## ▶ 12. How adopters consume this (post-shipping)

After Fase 33 ships in v1.24.0, the adopter's canonical Kivi-shape source — **unchanged** from v1.23.0 — produces:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
X-Axon-Trace-Id: f47ac10b-58cc-4372-a567-0e02b2c3d479

retry: 5000

event: axon.token
id: 1
data: {"step":"Generate","trace_id":...,"token":"Hello"}

[~20ms later]

event: axon.token
id: 2
data: {"step":"Generate","trace_id":...,"token":" world"}

[~20ms later]

event: axon.token
id: 3
data: {"step":"Generate","trace_id":...,"token":"."}

...

event: axon.complete
id: 47
data: {"flow":"Chat","steps_executed":1,"tokens_output":46,"backend":"anthropic","success":true,...}
```

Each `axon.token` event arrives token-by-token from the underlying LLM streaming API, with the backend's actual chunk granularity (not synthetic 3-word groups), with backpressure honored, with the underlying flow's audit/replay/auth surfaces unchanged from Fase 32.

This is the "cable" the adopter trail pointed at. Fase 33 is the architectural cycle that soldiers it.

---

*This document is part of the axon-lang internal plan-vivo surface. Bloque ratification awaited 2026-05-12.*
