---
title: "Plan vivo: Fase 36 — Axonendpoint Production Execution (the backend is a declared, compiled, deterministically-resolved property of the program)"
status: 🚀 PROPOSED 2026-05-17 — D1–D12 PENDING founder bloque ratification. Triggered by the kivi-enterprise gap report 2026-05-17 (axonendpoint SSE executes against the no-op `stub` backend; no way to wire a real LLM), verified true and deeper than reported. Target axon-lang v1.34.0. Rust-canonical.
owner: AXON Runtime + Backends Team
created: 2026-05-17
target: axon-lang v1.34.0 (minor — backend selection becomes a first-class, declared, type-checked, deterministically-resolved property of an `axonendpoint`; the production execution path of a deployed endpoint stops silently degrading to a no-op)
depends_on: Fase 30–34 SHIPPED (the SSE wire + the per-IRFlowNode async dispatcher — `run_streaming_via_dispatcher` is the streaming hot path). Fase 32 SHIPPED (`axonendpoint` as a first-class HTTP REST primitive — `DynamicEndpointRoute`, `dynamic_endpoint_handler`). Fase 34 SHIPPED (`Backend::stream()` + the streaming-tool branch `run_step_streaming_tool`, today unreachable on the server). Fase 35 SHIPPED (`axonstore` — `retrieve`/`persist`/`mutate` execute on the dispatcher).
charter_class: OSS — backend resolution, the precedence contract, observability, and honest-failure are core language + runtime, adopter-agnostic. The enterprise seam is multi-tenant backend provisioning (per-tenant key vaulting via AWS Secrets Manager already layered in `resolve_backend_key`, per-tenant routing policy) — tracked on the axon-enterprise vertical track, not gated here. Per-sub-fase classification in §6.
strategic_direction: Rust-canonical, per the founder directive 2026-05-15 (*"todo encaminado a ser 100% Rust + C, 0 Python"*). The production target for `axonendpoint` is the Rust server (`axon-server serve`); the adopter is migrating Python→Rust server. The `axonendpoint` declaration is parsed by the shared Rust `axon-frontend` crate. The Python frontend (`axon/compiler/`) is NOT touched — the Python server is the deprecating reference implementation, not the production endpoint target.

pillars: |
  Every LLM framework on the market — LangServe, FastAPI wrappers, the
  Python-glue-per-route pattern — treats "which model does this route
  run" as IMPERATIVE RUNTIME GLUE: a line of host code, invisible to
  any type system, absent from any compiled artifact, unrecorded in any
  audit log, and free to fail silently. You cannot read a deployment
  and know what it runs.

  AXON refuses that. Fase 36 makes the execution backend a **declared,
  compiled, type-checked, deterministically-resolved, audit-grounded
  property of the program** — the same four-pillar discipline axon
  already applies to epistemics, persistence, and streaming, now
  applied to model selection:

  - **DETERMINISM.** A given `.axon` artifact + a given environment
    resolves to EXACTLY ONE backend per step, by a single published
    precedence contract (D1). There is no hidden glue, no per-deploy
    surprise. The same inputs always pick the same model.
  - **EPISTEMIC HONESTY.** The runtime can NEVER silently degrade to
    the no-op `stub` (D5). If no real backend can be resolved the
    request fails LOUDLY, naming exactly what to fix. A `success:false`
    response with empty tokens is a lie axon will not tell.
  - **AUDITABILITY.** The resolved backend AND the precedence rung that
    chose it are recorded on the wire, in the trace, and in a response
    header (D8). An operator can always answer "why this model?".
  - **DECLARED INTENT, HONORED.** The flow already declares
    `tool { provider: gemini }`; the runtime must execute it (D4). A
    declaration the runtime ignores is a bug, not a detail.

  The result: you can read a deployed `.axon`, know precisely which
  model every step runs against, have the compiler reject an
  impossible choice, and trust that production never quietly runs
  nothing. No framework in the market offers this.

# ▶ 1. Trigger

kivi-enterprise gap report 2026-05-17. A deployed `axonendpoint`
(`POST /api/chat`) promotes to SSE correctly (Fase 30–34 — confirmed
live by the adopter) but the `axon_metadata` reveals the flow executed
against `backend: stub` — the no-op backend — with `steps_executed: 0`,
`success: false`, `tokens_output: 0`. The endpoint routes and streams
perfectly; the execution behind it runs nothing real. This is the last
link blocking the adopter from running production on the Rust server.

5th instance of the declarable-but-not-wired defect class (cf. SSE
Fase 30–34, `axonstore` Fase 35, `persist`/`mutate` 35.o/p,
interpolation 35.q) — a capacity the language exposes that the runtime
does not honor.

# ▶ 2. Diagnosis — three conspiring breaks + one piece of dead code

Verified against the source (research 2026-05-17):

**Break A — `auto` never consults the environment.** A deployed
endpoint executes via `dynamic_endpoint_handler`, which hardcodes
`backend: "auto"` (`axon_server.rs:20211-20256`, both the SSE and JSON
branches). `"auto"` resolves through `compute_backend_scores`
(`axon_server.rs:12618`), which scores **only** `state.backend_registry`
— and the registry is `HashMap::new()` at startup
(`axon_server.rs:922`), populated **only** by an explicit
`PUT /v1/backends/{name}` call. There is no startup population from the
provider API keys in the environment. So a server started with
`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `KIMI_API_KEY` set — the
obvious production setup — has an empty registry → `compute_backend_
scores` returns `[]` → `server_execute_streaming`'s `auto` branch
(`axon_server.rs:18381-18392`) does `.first().map(...).unwrap_or_else(||
"stub")` → **`stub`**. The env-var → provider table already exists
(`provider_spec`, `backend.rs:62-108`; `CANONICAL_PROVIDERS`,
`backends/mod.rs:482-490`) — `auto` simply never looks at it.

**Break B — the deploy backend is discarded.** `DeployRequest.backend`
(default `"anthropic"`) is dropped by `deploy_handler`;
`DynamicEndpointRoute` (`axon_server.rs:19639`) has no `backend` field.
The endpoint cannot inherit a backend from the deploy.

**Break C — `axonendpoint` has no `backend:` declaration.** The AST
`AxonEndpointDefinition` (`ast.rs:744`) has 18 fields — none names a
backend. There is no declarative way for a route to say which model it
runs. And `ServerConfig` / `axon serve` have no `--backend` flag
either. The ONLY input to backend selection is the heuristic `auto`.

**Dead code — the streaming dispatcher never wires a `ToolRegistry`.**
`DispatchCtx::with_tool_registry` (`flow_dispatcher/mod.rs:370`) is
defined but has **zero call sites in any production path**.
`run_streaming_via_dispatcher` builds the ctx with
`with_external_side_channels` + `with_store_registry` only. So
`run_step`'s streaming-tool branch (`pure_shape.rs:154-162`) — which
requires `ctx.tool_registry == Some` — can NEVER fire. A
`step GenerateResponse { apply: llm_stream }` where `tool llm_stream`
declares `provider: gemini, effects: <stream:drop_oldest>` falls
through to the plain-LLM path: the declared provider AND the declared
stream effect are ignored at execution.

**Net:** the endpoint executes against `stub` (Breaks A+B+C), and even
with a real backend the declared streaming tool would be ignored (the
dead-code break). `steps_executed: 0` (the report's Q2) is downstream:
the dispatcher's counter is correct, so `0` means the loop produced no
`Completed` outcome — the flow erred before completing any node, and
the silent-stub masked the error. Fase 36's honest-failure pillar
surfaces it.

# ▶ 3. The Backend Resolution Contract (the heart — D1)

For ANY flow execution behind an `axonendpoint` route or `/v1/execute`,
the **flow-level backend** is resolved by this deterministic, total,
documented precedence ladder. The first rung that yields a usable
backend wins:

  1. **Request-explicit** — an `ExecuteRequest.backend` / wire request
     that names a concrete backend (not `"auto"`). The operator
     override; highest precedence.
  2. **`axonendpoint backend:`** — the route's declared backend (D2).
     A deployed route's own choice.
  3. **Server default** — `axon serve --backend <name>` /
     `AXON_DEFAULT_BACKEND` env / `ServerConfig.default_backend` (D7).
  4. **Environment-available `auto`** (D6) — if the `backend_registry`
     has scored entries, the top score; ELSE the first
     `CANONICAL_PROVIDERS` entry whose API key is present in the
     environment, in a fixed deterministic priority order.
  5. **Honest failure** (D5) — if rungs 1–4 all yield nothing, the
     request FAILS with a structured diagnostic naming the fix. The
     ladder NEVER falls through to `stub`.

`stub` is reachable on rung 1 or 2 ONLY — by an explicit, written
`backend: stub` / `backend=stub`. It is never a silent fallback.

Orthogonally, the **per-step backend**: a `step` that `apply:`s a
`tool` with a `provider:` executes that step against the tool's
provider (D4). Steps with no applied tool use the flow-level backend.
The resolution of every step is deterministic and recorded (D8).

# ▶ 4. D-letters (D1–D12 — PENDING founder bloque ratification)

| D | Decision |
|---|---|
| **D1** | **The Backend Resolution Contract.** The §3 precedence ladder is the single, published, deterministic resolver for the flow-level backend. Implemented as a pure, total `resolve_backend(inputs) -> BackendResolution { backend, reason }` function — no I/O, exhaustively unit-testable, the closed catalog of `reason` rungs. |
| **D2** | **`axonendpoint backend:` declaration.** A new optional `backend:` field on the `axonendpoint` declaration — AST + parser + type-checker in `axon-frontend`. Type-checked against the closed catalog (`CANONICAL_PROVIDERS` ∪ `{stub, auto}`); an unknown backend is a **compile error** (`axon check` fails). Follows the Fase 32 pattern — collected into `DynamicEndpointRoute` from source at deploy, not necessarily carried in the narrow `IRAxonEndpoint`. |
| **D3** | **The route carries its backend.** `DynamicEndpointRoute` gains a `backend: Option<String>` field; `collect_axonendpoint_routes` populates it from the declaration; `dynamic_endpoint_handler` passes the **resolved** backend (D1 ladder) instead of the hardcoded `"auto"`. `deploy_handler` stops discarding the choice. |
| **D4** | **Declared tool provider, executed.** `run_streaming_via_dispatcher` builds a `ToolRegistry` from the IR's `tools` and attaches it via `with_tool_registry` (making the dead builder live). A `step` that `apply:`s a streaming `tool` reaches `run_step_streaming_tool`, and that step executes against the **tool's `provider:`** — the `<stream:policy>` effect honored. Per-step backend overrides the flow-level backend for that step. |
| **D5** | **No silent stub — honest failure.** When the D1 ladder resolves nothing real and `stub` was not explicitly chosen, the request fails with a **structured** diagnostic — HTTP 503 on the JSON path, a structured `axon.error` SSE event on the streaming path — naming exactly what to fix (declare `backend:`, set a provider key, or pass `backend=stub`). The `stub` backend executes ONLY when explicitly named. A silent `success:false` no-op is forbidden. |
| **D6** | **Environment-aware `auto`.** `auto` resolution, when `compute_backend_scores` is empty, falls back to `CANONICAL_PROVIDERS` filtered by "API key present in the environment" (`provider_spec` / `get_api_key`), picking the first in a fixed, documented priority order. A server with one provider key set "just works" — no `PUT /v1/backends` ceremony required. The registry, when populated, still wins (operator-tuned scores). |
| **D7** | **Server default backend.** `axon serve --backend <name>` CLI flag + `AXON_DEFAULT_BACKEND` env var (D7-cross-stack: same truthy/name discipline) + `ServerConfig.default_backend: Option<String>`. Rung 3 of the ladder. Lets an operator pin a fleet-wide default without editing every `.axon`. |
| **D8** | **Resolution observability.** The resolved backend AND the precedence rung that chose it (the `BackendResolution.reason`) surface in three places: the `axon_metadata` / `axon.complete` wire body, the execution trace, and an `X-Axon-Backend` response header (`<backend>; reason=<rung>`). "Why this model?" is always answerable post-hoc. |
| **D9** | **Backwards compatibility — absolute.** A flow with no `backend:` declaration keeps working — it resolves down the ladder (server default → env auto). `/v1/execute` with an explicit `backend` is byte-unchanged. The ONLY behavior change is the intended fix: an endpoint that today silently runs `stub` (because a provider key IS in the environment) now runs that real provider with zero source change; an endpoint with genuinely no backend available flips from a silent no-op to a loud, honest D5 error. No adopter who had a working setup regresses. |
| **D10** | **Deploy-time + compile-time signalling.** `axon check` emits a new `axon-Wnnn` warning when an `axonendpoint` declares no `backend:` and would rely on `auto`. `deploy_handler` runs the D1 ladder at deploy time and rejects / warns on an endpoint whose backend cannot be resolved — the adopter learns at deploy, not at the first production 503. |
| **D11** | **`steps_executed` honesty (closes the report's Q2).** Audit the dispatcher's execution accounting end-to-end: a step that errors surfaces a structured per-step error on the wire and in the audit record; `steps_executed` reflects reality; `axon_metadata` never reports a misleading `0` without an accompanying error. Honesty over a clean-looking number. |
| **D12** | **The production gate.** A dedicated CI lane that deploys an `axonendpoint`, hits it over HTTP, and asserts it executes against a **real backend** (a local mock-LLM server) end-to-end — the gap the research found (no such test exists). Plus: exhaustive unit tests of the D1 resolver, a property/fuzz pass over `resolve_backend` (total + deterministic + never-`stub`-unless-asked over arbitrary inputs), and the D9 backwards-compat corpus. |

# ▶ 5. Sub-fases (36.a–36.m — topologically ordered)

| Sub-fase | What | Class | D-letters |
|---|---|---|---|
| **36.a** | Diagnostic anchor — a test that pins the v1.33.0 broken state (deployed `axonendpoint` → `stub`, declared tool provider ignored, `with_tool_registry` dead). Each later sub-fase inverts a §-assertion. | OSS | — |
| **36.b** | The Backend Resolution Contract — pure, total `resolve_backend(inputs) -> BackendResolution`; closed `reason` catalog; exhaustive unit tests. | OSS | D1 |
| **36.c** | Environment-aware `auto` — `CANONICAL_PROVIDERS` filtered by env-key presence, fixed priority; registry still wins when populated. | OSS | D6 |
| **36.d** | `axonendpoint backend:` field — `axon-frontend` AST + parser + type-checker; closed-catalog validation, unknown backend = compile error. | OSS | D2 |
| **36.e** | `DynamicEndpointRoute.backend` + `collect_axonendpoint_routes` populates it + `deploy_handler` stops discarding `DeployRequest.backend`. | OSS | D3 |
| **36.f** | `dynamic_endpoint_handler` resolves via the D1 ladder + passes the resolved backend (retire the hardcoded `"auto"`), both SSE and JSON branches. | OSS | D1, D3 |
| **36.g** | Server default backend — `--backend` CLI flag + `AXON_DEFAULT_BACKEND` + `ServerConfig.default_backend`. | OSS | D7 |
| **36.h** | No-silent-stub honest failure — the deploy-time + request-time guard; structured 503 / `axon.error`; `stub` only when explicitly named. | OSS | D5 |
| **36.i** | Tool registry wired into `run_streaming_via_dispatcher` (`with_tool_registry` becomes live) + per-step tool-`provider` execution; the `<stream:policy>` effect honored end-to-end. | OSS | D4 |
| **36.j** | Resolution observability — `BackendResolution.reason` into `axon_metadata` + the trace + the `X-Axon-Backend` header. | OSS | D8 |
| **36.k** | `steps_executed` honesty + `axon check` `axon-Wnnn` no-backend warning + deploy-time resolution check. | OSS | D10, D11 |
| **36.l** | Real-backend E2E CI lane (deploy + hit + assert real execution vs a mock-LLM server) + `resolve_backend` fuzz/property pass + D9 backwards-compat corpus + adopter docs (`docs/ADOPTER_BACKENDS.md` + `docs/MIGRATION_v1.34.md`). | OSS | D12, D9 |
| **36.m** | Coordinated release axon-lang v1.34.0 cross-stack (crates.io + PyPI + GitHub Release + binaries) + axon-enterprise catch-up. | SPLIT | — |

**Total estimate: ~3 500–4 500 LOC** (frontend field + resolver + handler rewiring + tool-registry wiring + observability + honest-failure + the E2E harness). Built Rust-canonical. D9 zero-regression absolute.

# ▶ 6. OSS / ENTERPRISE / SPLIT classification

Fase 36 is **OSS** end to end — backend selection, the resolution
contract, honest failure, and observability are core language +
runtime; an adopter-agnostic primitive. A `.axon` that could not
deterministically resolve its own backend would be a language
contradicting its own declarative thesis.

The **enterprise seam** is multi-tenant backend operations: per-tenant
API-key vaulting (the AWS-Secrets-Manager layer already present in
`resolve_backend_key`), per-tenant routing policy, per-tenant cost
governance, fleet-wide backend health/failover orchestration. Those
layer ON TOP of the OSS resolution contract — they do not gate it —
and ship on the axon-enterprise vertical track. 36.m is **SPLIT**:
axon-lang v1.34.0 (OSS) + an axon-enterprise catch-up.

# ▶ 7. Honest scope

- Fase 36 makes the **flow-level** and **per-applied-tool** backend
  declared + deterministically resolved. It does NOT introduce
  per-step `backend:` syntax on a bare `step` (a step's backend is
  the flow-level one unless it `apply:`s a tool — that is the coherent
  surface; bare-step backend override is a considered-and-deferred
  option, not in v1.34.0).
- It does NOT add a `flow`-level `backend:` declaration — a `flow` is
  reusable across endpoints; the route (`axonendpoint`) is the correct
  home for a route-level backend. Considered, deferred.
- The `run` declaration is not extended with a backend — the
  `axonendpoint` `execute:` + `backend:` is the production surface.
- Real-provider integration tests gate against a **local mock-LLM
  server** (deterministic, no API keys, no network) — the same
  discipline as Fase 33's mock axum servers. Live-provider smoke
  against real keys stays an adopter-side concern.
- Python frontend untouched (Rust-canonical — see `strategic_direction`).

# ▶ 8. Why this is "more powerful than the standard"

The market ships model selection as host-language glue: invisible,
imperative, unaudited, silently-failing. Fase 36 ships it as a
**property of the compiled program**: declared in the `.axon`,
rejected by the compiler if impossible, resolved by ONE published
deterministic contract, recorded in the audit trail with its reason,
and structurally incapable of silently degrading to a no-op. A
deployed `axonendpoint` becomes something you can *read and trust*:
this route runs this model, the compiler proved it could, the trace
records that it did. That is the four-pillar discipline — determinism,
epistemic honesty, auditability, declared-intent — applied to the one
axis every other framework leaves as a loose wire.
