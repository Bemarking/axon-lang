---
title: "Plan vivo: Fase 36.x — Mixed-Flow Streaming Integrity (the agent pattern — retrieve context → deliberate → persist — streams cleanly behind exactly one terminator, and is runnable without external infrastructure)"
status: 🟡 MOUNTED 2026-05-17 — D1–D6 PENDING founder bloque ratification. Triggered by the founder's post-v1.34.0 hypothesis (a streaming `axonendpoint` only executes pure-`step` flows, not the real agent pattern that mixes store-ops with a step), investigated 2026-05-17: the path DOES dispatch mixed flows, but the investigation surfaced a real double-terminator wire bug, zero test coverage, and a structural blocker (no in-memory-declarable store → mixed flows cannot run or be tested without a live Postgres). Target axon-lang v1.35.0. Rust-canonical.
owner: AXON Runtime + Streaming Team
created: 2026-05-17
target: axon-lang v1.35.0 (minor — `in_memory` becomes a first-class declarable `axonstore` backend; the streaming producer's exactly-one-terminator wire contract is enforced; the canonical agent flow shape becomes a tested, documented, locally-runnable streaming primitive)
depends_on: Fase 36 SHIPPED (v1.34.0 — the Backend Resolution Contract; `dynamic_endpoint_handler`, `run_streaming_via_dispatcher` with the tool registry wired). Fase 35 SHIPPED (`axonstore` — `retrieve`/`persist`/`mutate` execute on the dispatcher; `StoreRegistry` + `StoreHandle::InMemory`). Fase 33 SHIPPED (the SSE streaming producer; the `FlowExecutionEvent` closed catalog + the "exactly one terminator" contract).
charter_class: OSS — the streaming wire contract, the agent-flow shape, and an in-memory store backend are core language + runtime; adopter-agnostic. The enterprise seam (per-tenant store provisioning, vertical store policy) layers ON TOP and is not gated here. 36.x.h is SPLIT. Per-sub-fase classification in §6.
strategic_direction: Rust-canonical, per the founder directive 2026-05-15 (*"todo encaminado a ser 100% Rust + C, 0 Python"*). The production target is the Rust server (`axon-server serve`). The Python frontend is NOT touched — `in_memory` is added to the Rust `axon-frontend` type-checker catalog only.

pillars: |
  A real AI agent is not a single LLM call. It is a SHAPE:

      retrieve context  →  deliberate (the step)  →  persist the result

  recuperar contexto → deliberar → persistir. That is the canonical
  flow of every agent worth deploying — and in AXON it is a flow that
  MIXES `axonstore` operations with a `step`.

  Fase 36 made the execution backend of a deployed `axonendpoint` a
  declared, resolved, honest property of the program. But the
  investigation that closed Fase 36 surfaced that the one shape that
  matters most — the mixed agent flow behind a streaming endpoint —
  was never tested, could not be run without a live Postgres, and
  emitted a malformed wire on the error path.

  Fase 36.x closes that. It makes the agent pattern a **first-class,
  verified, locally-runnable streaming primitive**:

  - **WIRE INTEGRITY.** The streaming producer emits EXACTLY ONE
    terminator (`FlowComplete` XOR `FlowError`) for every flow, every
    shape, every outcome (D1). A stream that ends twice is a lie about
    where it ended — and AXON does not tell it.
  - **RUNNABLE WITHOUT CEREMONY.** `in_memory` becomes a first-class
    declarable `axonstore` backend (D2). The agent pattern runs — and
    is tested — with zero external infrastructure. A language whose
    canonical shape needs a database server to even execute in a test
    is a language that cannot prove its own thesis.
  - **THE MIXED FLOW IS A PRIMITIVE, NOT AN ACCIDENT.** A
    `retrieve → step → persist` flow behind a streaming `axonendpoint`
    is a tested, documented, supported shape (D3) — store-ops emit
    their wire events, the step streams its tokens, the data flows
    between them (D4).

  The result: an adopter can write the obvious agent flow, deploy it
  behind a streaming route, run it on a laptop, and trust the wire.

# ▶ 1. Trigger

Founder hypothesis, 2026-05-17, immediately after the Fase 36 / axon-
lang v1.34.0 release:

> "ChatFlow es multi-statement: retrieve ×3 + persist + step +
> persist. El test de streaming de axon es un flow de puro step. La
> hipótesis: el path de streaming del axonendpoint solo ejecuta flows
> de puro-step, no flows que mezclan store-ops con el step — que es
> justamente el patrón de un agente real."

Investigated the same day with an empirical diagnostic (deploy a
mixed flow behind `transport: sse`, hit it, observe the wire). The
literal hypothesis is **not the mechanism** — `run_streaming_via_
dispatcher` walks every `IRFlowNode` and the dispatcher has real
`run_retrieve` / `run_persist` handlers, so store-ops are dispatched,
not skipped. But the investigation surfaced three real gaps (§2). The
founder's instinct — *something is wrong with the mixed flow on the
streaming path* — was correct.

6th instance of the "declarable-but-not-verified" defect class
(cf. SSE Fase 30–34, `axonstore` Fase 35, backend resolution Fase 36).

# ▶ 2. Diagnosis — three findings

Verified by empirical diagnostic 2026-05-17:

**Finding A — double terminator on the streaming error path.**
`run_streaming_via_dispatcher` (`axon-rs/src/streaming_via_dispatcher.rs`):
the `Err(e)` arm of the flow-body walk emits `FlowExecutionEvent::
FlowError` then `break`s; §7 (after the loop) then emits
`FlowExecutionEvent::FlowComplete` **unconditionally**. Result: an
errored flow puts BOTH `event: axon.error` AND `event: axon.complete`
on the SSE wire. This violates the Fase 33 closed-catalog contract
("exactly one terminator — `FlowComplete` OR `FlowError` — closes the
stream"). Reproduced directly: a `retrieve` against a store that
could not resolve produced `event: axon.error` + `event:
axon.complete` back-to-back. An SSE client that stops reading at the
first terminator, or that treats a second terminator as a protocol
error, sees a malformed stream. The pure-`step` happy path emits a
single clean `axon.complete` — the bug bites ONLY the error path,
which is exactly the path a real agent flow hits on a transient
store/backend failure.

**Finding B — zero test coverage for mixed flows on the streaming
path.** Confirmed: NOT ONE test in the entire Fase 35 `axonstore`
suite deploys an `axonendpoint` with `transport: sse`. The streaming-
endpoint × store-flow combination — the single most important shape
for a production agent — is completely unexercised. Every axon
streaming test is a pure-`step` flow.

**Finding C — the agent pattern cannot run without a live Postgres.**
A `retrieve` / `persist` from source REQUIRES a declared `axonstore`
(the type-checker rejects an undeclared store: `Undefined axonstore
'X'`). The type-checker's valid store backends are `{postgresql,
mysql, sqlite}` — but the RUNTIME `StoreRegistry` only implements
`postgresql` (`sqlite` / `mysql` type-check but have no runtime
backend; the `StoreHandle::InMemory` key-value path exists but is
reachable ONLY for an *undeclared* store, which the type-checker
forbids from source). Net: every mixed flow — in a test, in local
development, in CI — needs a live Postgres to execute at all. This is
WHY Findings A and B went unseen: the shape was structurally
un-runnable in the test harness.

**Net:** the agent pattern behind a streaming `axonendpoint` is
dispatched correctly, but its wire is malformed on error, it has no
test coverage, and it cannot be exercised without external
infrastructure. Fase 36.x closes all three.

# ▶ 3. The exactly-one-terminator contract (the heart — D1)

Every flow execution on the streaming producer emits, on the
`FlowExecutionEvent` channel, a sequence that ends with **exactly one
terminator**:

  - `FlowComplete` — the flow ran to its end (success OR a clean
    `success:false` with no dispatcher error).
  - `FlowError` — a dispatcher error aborted the flow.

NEVER both. NEVER neither. The terminator is the single, authoritative
statement of how the stream ended. `run_streaming_via_dispatcher`'s
post-loop `FlowComplete` emit is GATED on "no `FlowError` was already
emitted" — the producer tracks whether it terminated via the error
path and skips the redundant `FlowComplete`. The contract is enforced
by a property/fuzz pass (36.x.f) over arbitrary flow shapes.

# ▶ 4. D-letters (D1–D6 — PENDING founder bloque ratification)

| D | Decision |
|---|---|
| **D1** | **Exactly-one-terminator wire contract.** The streaming producer emits exactly one terminator (`FlowComplete` XOR `FlowError`) for every flow, every shape, every outcome. `run_streaming_via_dispatcher`'s unconditional post-loop `FlowComplete` is gated — skipped when the flow already terminated via `FlowError`. Enforced by a property pass over arbitrary shapes. |
| **D2** | **`in_memory` is a first-class declarable `axonstore` backend.** `backend: in_memory` type-checks (added to the `axon-frontend` `VALID_STORE_BACKENDS` catalog) and resolves at runtime to `StoreHandle::InMemory` (the key-value path that already exists). The canonical agent flow becomes runnable + testable with ZERO external infrastructure — no Postgres, no `DATABASE_URL`. `connection:` is optional for an `in_memory` store. |
| **D3** | **The mixed flow is a first-class streaming shape.** A `retrieve → step → persist` flow behind an `axonendpoint transport: sse` is a tested, documented, supported primitive: each store-op emits its `retrieve` / `persist` wire events, the `step` streams its `axon.token`s, the stream closes with one terminator. Dedicated integration coverage, now possible via D2. |
| **D4** | **Data-flow integrity on the streaming path.** The agent pattern's data MUST thread: a `retrieve`'s bound value (`as:` alias) reaches a downstream `step`'s `${interpolation}`; the `step`'s output reaches a downstream `persist`'s field block. 36.x.e audits this end-to-end on the streaming dispatcher path and fixes any divergence from the synchronous path (Fase 35.q interpolation contract is the reference). |
| **D5** | **Backwards compatibility — absolute.** Every v1.34.0 wire is byte-identical for any flow that does not error. The ONLY behavior change is the intended fix: an errored streaming flow emits ONE terminator (`FlowError`) instead of a malformed `FlowError` + `FlowComplete` pair. Pure-`step` flows, `postgresql` stores, the synchronous `/v1/execute` path — all unchanged. `in_memory` is purely additive (a new accepted backend value). |
| **D6** | **The production gate.** A dedicated CI lane: the mixed-flow streaming E2E (deploy `retrieve → step → persist` behind `transport: sse`, hit it, assert the wire), the exactly-one-terminator property/fuzz pass over arbitrary flow shapes, and the D5 backwards-compat corpus. |

# ▶ 5. Sub-fases (36.x.a–36.x.h — topologically ordered)

| Sub-fase | What | Class | D-letters | Status |
|---|---|---|---|---|
| **36.x.a** | Diagnostic anchor — a committed test pinning the v1.34.0 broken state: a mixed flow on the streaming path emits a double-terminator on error; no `in_memory` store is source-declarable. Each later sub-fase inverts a §-assertion. | OSS | — | ⏳ pending |
| **36.x.b** | `in_memory` as a first-class declarable `axonstore` backend — `axon-frontend` `VALID_STORE_BACKENDS` gains `in_memory`; the runtime `StoreRegistry` maps it to `StoreHandle::InMemory` (the handle exists; `classify_backend` + `connection:`-optional wiring). The structural unblocker for everything downstream. | OSS | D2 | ⏳ pending |
| **36.x.c** | Exactly-one-terminator — gate `run_streaming_via_dispatcher`'s post-loop `FlowComplete` emit so an errored flow emits ONLY `FlowError`; audit the `UpstreamCancelled` path for the same. | OSS | D1 | ⏳ pending |
| **36.x.d** | Mixed-flow streaming integration tests — `retrieve → step → persist` behind `axonendpoint transport: sse` executes end-to-end (now runnable via 36.x.b): store-op wire events + the step's tokens + exactly one terminator; happy path + error path. | OSS | D3 | ⏳ pending |
| **36.x.e** | Data-flow integrity audit — verify (and fix if divergent) that on the streaming dispatcher path a `retrieve` alias reaches a downstream `step`'s `${interpolation}` and the `step` output reaches a downstream `persist` field block, matching the synchronous path (Fase 35.q). | OSS | D4 | ⏳ pending |
| **36.x.f** | Exactly-one-terminator property/fuzz pass — a deterministic property test that `run_streaming_via_dispatcher` emits exactly one terminator over arbitrary flow shapes (pure-step, mixed, erroring, cancelled, empty, multi-store). | OSS | D1, D6 | ⏳ pending |
| **36.x.g** | CI lane (`fase_36x_mixed_flow_streaming.yml`) + adopter docs — `docs/ADOPTER_AXONSTORE.md` streaming section + the canonical agent-pattern recipe + `docs/MIGRATION_v1.35.md`. | OSS | D6, D5 | ⏳ pending |
| **36.x.h** | Coordinated release axon-lang v1.35.0 cross-stack (crates.io + PyPI + GitHub Release + binaries) + axon-enterprise catch-up. | SPLIT | — | ⏳ pending |

**Total estimate: ~1 200–1 800 LOC** (the `in_memory` backend wiring + the terminator gate + the mixed-flow + property test packs + the data-flow audit + the CI lane + docs). Smaller than Fase 36 — three concrete gaps, not a new contract. Built Rust-canonical. D5 zero-regression absolute.

# ▶ 6. OSS / ENTERPRISE / SPLIT classification

Fase 36.x is **OSS** end to end — the streaming wire contract, an
in-memory store backend, and the mixed-flow shape are core language +
runtime; adopter-agnostic. The **enterprise seam** is unchanged:
per-tenant store provisioning, vertical store policy, and the
AWS-Secrets-Manager-backed connection vaulting layer ON TOP of the OSS
store registry — none of it gated here. 36.x.h is **SPLIT**:
axon-lang v1.35.0 (OSS) + an axon-enterprise catch-up.

# ▶ 7. Honest scope

- Fase 36.x makes `in_memory` a first-class **declarable** backend. It
  does NOT implement `sqlite` / `mysql` runtime backends — those stay
  type-check-valid-but-runtime-absent (a documented future fase); the
  honest move is to make the ONE in-memory path source-reachable, not
  to half-ship two SQL backends.
- It does NOT change the `postgresql` store path — that is the
  production data plane and is byte-unchanged (D5).
- The double-terminator fix is scoped to `run_streaming_via_
  dispatcher` (the SSE producer). The synchronous `/v1/execute` JSON
  path does not have the event-stream terminator concept and is
  untouched.
- 36.x.e is an AUDIT sub-fase — it verifies the data-flow contract on
  the streaming path and fixes a divergence ONLY if one is found; the
  synchronous-path interpolation (Fase 35.q) is the ratified
  reference, not re-litigated here.
- Python frontend untouched (Rust-canonical — see `strategic_direction`).

# ▶ 8. Why this matters

Fase 36 proved a deployed `axonendpoint` runs a real, resolved,
honest backend. Fase 36.x proves the thing you'd actually deploy
behind it — an agent: retrieve context, deliberate, persist the
result — streams cleanly, ends honestly, and runs on a laptop. A
language whose canonical shape emits a malformed wire on error, has
no test for itself, and needs a database server to execute in a unit
test has not earned the word "production". 36.x earns it.
