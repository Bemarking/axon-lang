---
title: "Plan vivo: Fase 37 — The Request Binding Contract (the typed request body of an axonendpoint populates the parameters of the flow it executes — a binding the compiler proves TOTAL, the runtime delivers on both transports, and the epistemic type system treats as Untrusted by birth so it can never reach a store as anything but a bound parameter)"
status: 🟢 IN PROGRESS 2026-05-18 — D1–D7 RATIFIED (founder bloque, 2026-05-18). 37.a–37.h ✅ SHIPPED; 37.i (the v1.36.0 release) ⏳ pending. Triggered by an adopter report 2026-05-18 (post-v1.35.0): a parameterised agent flow deployed behind a streaming `axonendpoint` with a declared `body: T` runs with an EMPTY binding map — `${tenant_id}` and every other flow parameter interpolate to the literal, a `retrieve` `where:` clause queries for the literal string and returns zero rows for a tenant that exists, and the flow dies with a hollow `axon.error`. Investigated the same day: the request body is parsed (schema validation, idempotency hash, replay capture) and then DISCARDED — `dynamic_endpoint_handler` builds the execution request from `flow_name + backend` only, on BOTH the SSE and JSON transports; nothing seeds `DispatchCtx.let_bindings` with the flow's arguments. Target axon-lang v1.36.0. Rust-canonical.
owner: AXON Language + Runtime Team
created: 2026-05-18
target: axon-lang v1.36.0 (minor — the declared `body: T` of an `axonendpoint` becomes a compile-time-proven, runtime-delivered, epistemically-typed binding to the parameters of its `execute: F` flow; an errored streaming flow's `axon.error` carries the diagnostic)
depends_on: Fase 36.x SHIPPED (v1.35.0 — the mixed agent flow streams; `run_streaming_via_dispatcher` walks every `IRFlowNode`; `${interpolation}` threads on the streaming path). Fase 36 SHIPPED (v1.34.0 — the Backend Resolution Contract; `dynamic_endpoint_handler`; honest 503 failure). Fase 35 SHIPPED (`axonstore` — the parameterised SQL filter compiler; `retrieve`/`persist`/`mutate` `where:` clauses; the endpoint→flow→store-capability compile-time compositional check — Pillar IV). Fase 32 SHIPPED (`axonendpoint` `body: T` declaration; `route_schema::validate_body`; dynamic routes).
charter_class: OSS — the request-binding contract, the compile-time totality check, the epistemic treatment of request-origin values, and the structured streaming error are core language + runtime; adopter-agnostic. The enterprise seam (per-tenant body-field policy, vertical request validation, PII-class field tagging) layers ON TOP and is not gated here. 37.i is SPLIT. Per-sub-fase classification in §6.
strategic_direction: Rust-canonical, per the founder directive 2026-05-15 (*"todo encaminado a ser 100% Rust + C, 0 Python"*). The production target is the Rust server (`axon-server serve`). The Python frontend is NOT touched — the totality check is added to the Rust `axon-frontend` type-checker only.

pillars: |
  An AI agent is a function of its input. The canonical agent flow —
  retrieve context → deliberate → persist — is PARAMETRIC: it takes a
  message, a session, a tenant, a channel. Those parameters arrive
  from the outside world, across the network, in an HTTP request body.

  Fase 36.x proved the agent flow STREAMS. Fase 37 proves the agent
  flow can SEE ITS INPUT — and sees it the way no language in the
  market offers:

  - TYPED & PROVEN-TOTAL. An `axonendpoint` declares `body: T` and
    `execute: F`. The industry standard — FastAPI, Spring `@RequestBody`,
    NestJS DTOs — binds a typed body to one function and discovers a
    missing parameter at RUNTIME: a `KeyError`, an `undefined`, an
    empty string — exactly the bug this fase closes. AXON makes the
    binding a COMPILE-TIME THEOREM: the type-checker proves every
    parameter of F is covered by a field of T. An endpoint whose flow
    asks for a parameter the body cannot supply does not deploy. The
    failure moves from production to `axon check`.

  - EPISTEMICALLY HONEST. A value that crossed the network boundary is
    `Untrusted` — and the language never forgets it. The #1 class of
    production vulnerability is injection: untrusted request data
    spliced into a query. AXON closes it BY CONSTRUCTION — a
    request-bound `${param}` reaching a store `where:` clause is a
    FILTER PARAMETER, compiled to a placeholder, never concatenated
    into filter source. The type system closes OWASP A03, not
    developer discipline.

  - ONE CONTRACT, HONEST FAILURE. The body binds identically on the
    SSE and JSON transports. And when a flow fails mid-stream, the
    `axon.error` event carries the diagnostic — error class, message,
    the failing node, the trace_id — and the server logs it. Fase 36
    made backend failure honest; Fase 37 makes flow-execution failure
    on the wire honest. A stream that dies says why.

  The result: an adopter writes the obvious parameterised agent flow,
  declares the typed body, deploys behind a streaming route — and the
  compiler guarantees the flow will receive every argument it asks
  for, the runtime delivers them on every transport, and a malicious
  argument cannot reach the database as anything but a bound parameter.

# ▶ 1. Trigger

Adopter report, 2026-05-18, immediately after the Fase 36.x / axon-
lang v1.35.0 release. Fase 36.x resolved the mixed-flow EXECUTION —
`ChatFlow` now runs, the first `retrieve` issues a real SQL query —
but the adopter pinpointed the next gap with a precise diagnostic:

> "Smoke `POST /api/chat` con `tenant_id` = `83d078e1-…` (un tenant
> que SÍ existe). La traza: `SELECT * FROM "tenants" WHERE "id" = $1`
> → `rows_returned: 0`. `$1` no es el UUID — `${tenant_id}` del
> where-clause NO se interpola. Y `${tenant_id}` es un PARÁMETRO del
> flow que viene del request body. El handler de streaming del
> axonendpoint no bindea los campos del request body a los
> parámetros del flow."

Plus a secondary observability finding:

> "El flow erroreó (`terminal_reason: error`) y el adopter no recibió
> NINGÚN detalle: ni mensaje en el stream SSE, ni log de error. La
> causa solo se halló cruzando `sqlx=debug` con una verificación
> externa de la tabla."

Investigated the same day. The literal mechanism: `dynamic_endpoint_
handler` receives, parses, and validates the request body — then
DISCARDS it. The execution request is built from `flow_name + backend`
ONLY. Confirmed (§2). The adopter's instinct — *the flow never
receives its arguments* — is exactly correct.

7th instance of the "declarable-but-not-verified" defect class
(cf. SSE Fase 30–34, `axonstore` Fase 35, backend resolution Fase 36,
mixed-flow streaming Fase 36.x). The pattern: a surface is DECLARED in
the grammar and TYPE-CHECKED, but the runtime never honours the
declaration. Here: `axonendpoint … body: T … execute: F` type-checks,
`body: T` is validated against the request — and then the typed body
is dropped on the floor and `F`'s parameters are never bound.

Founder framing 2026-05-18: these gaps are not adopter-specific
patches — they are symptoms of what AXON the LANGUAGE must resolve,
because they are the real life of any adopter building agents or
applications in axon. And the standing principle: *"¿esto es el
estándar de la industria? ¿o podemos construir algo mucho mejor que
nadie ofrece en el mercado?"* — Fase 37 is built to the second answer.

# ▶ 2. Diagnosis — two findings

Verified by source inspection 2026-05-18.

**Finding A — the `body:` ↔ flow-parameter binding is type-checked but
never executed.** An `axonendpoint` declares two things the type-
checker links: `body: <Type>` (the typed request body) and
`execute: <Flow>` (the flow, which carries `IRFlow.parameters`). The
semantics of `body: T` on an endpoint executing a parameterised flow
is a promise: *the request body's fields populate the flow's
parameters*. AXON type-checks the promise and breaks it at runtime:

  - `dynamic_endpoint_handler` (`axon-rs/src/axon_server.rs:20216`)
    receives `body: axum::body::Bytes`, parses it to `parsed`, and
    uses it for THREE things — body-schema validation (§32.c),
    idempotency body-hash (§32.f), replay capture (§33.x.f). Then it
    is discarded.
  - The SSE branch (`axon_server.rs:20619`) builds
    `StreamExecuteRequest { flow_name, backend }`. No body.
  - The JSON branch (`axon_server.rs:20662`) builds
    `ExecuteRequest { flow, backend }`. No body. **The gap is on BOTH
    transports — not SSE-only.**
  - `server_execute_streaming` (`axon_server.rs:18427`) and
    `run_streaming_via_dispatcher` (`streaming_via_dispatcher.rs:118`)
    have NO parameter for flow arguments.
  - `DispatchCtx.let_bindings` (`flow_dispatcher/mod.rs:253`) — the
    `HashMap<String,String>` against which `${name}` interpolates —
    is born EMPTY (`mod.rs:336`) and nothing seeds it from
    `IRFlow.parameters` (`axon-frontend/src/ir_nodes.rs:647`).

Net: a `retrieve tenants { where: "id == '${tenant_id}'" }` queries
for the literal `${tenant_id}` (or empty) because `tenant_id` is a
flow parameter, the flow never receives its arguments, `let_bindings`
is empty, and `exec_context::interpolate_vars` leaves an unknown var
literal. This bites EVERY axon app or agent that takes input from an
HTTP request — i.e. essentially every real deployment. The Python
server patched the symptom locally with `_patch_endpoint_payload_
binding`; the language needs the native binding in the Rust path.

**Finding B — an errored streaming flow emits a hollow terminator.**
`FlowExecutionEvent::FlowError` DOES carry an `error: String` field
and `run_streaming_via_dispatcher` populates it
(`streaming_via_dispatcher.rs:389` — `format!("dispatcher error:
{e:?}")`). The loss is in the wire layer: the SSE consumer / dialect
adapter that translates `FlowError` → the `axon.error` event drops
the `error` payload, and there is no server-side error log. A flow
that fails silently is undebuggable — the adopter had to cross-
reference `sqlx=debug` query logs with an external table check to
find the cause. The error detail must reach the `axon.error` event
body AND a structured server log line.

**The three pre-report questions, answered.**
  1. *Does the streaming path support multi-statement flows?* — YES,
     since Fase 36.x. `run_streaming_via_dispatcher` walks every
     `IRFlowNode` in `flow.steps` (including `Retrieve`/`Persist`).
  2. *Should `build_plan_from_ir` include the `step` of a flow that
     also has store nodes?* — The streaming path no longer uses the
     plan; it walks `flow.steps` directly via `dispatch_node`. An
     empty `plan.steps` is a legacy plan-builder concern, NOT on the
     streaming hot path — out of Fase 37 scope.
  3. *Does the flow's `-> String` return type affect plan
     construction?* — No. The dispatcher walks `flow.steps`
     regardless of `return_type_name`.

# ▶ 3. The Request Binding Contract (the heart — D1+D2+D3)

For an `axonendpoint E { body: T, execute: F, … }`:

**DEPLOY TIME (D2 — totality).** The compiler proves the binding is a
total function `bind : params(F) → fields(T)`: for every parameter
`p ∈ params(F)` there is a field `f ∈ fields(T)` with `name(f) =
name(p)` and `type(f)` compatible with `type(p)`. A REQUIRED parameter
with no covering field is a compile error (the endpoint-binding-
totality error — modelled on the Fase 35 Pillar IV capability-gate
error). An OPTIONAL parameter (`IRParameter.optional`) may be
uncovered. The check runs at `axon check` and `POST /v1/deploy`.

**REQUEST TIME (D1 — delivery).** The runtime parses the body once.
For each `p ∈ params(F)` it reads field `name(p)` from the parsed
body, binds the value, and seeds `DispatchCtx.let_bindings[name(p)]`
BEFORE the flow body walk begins. Every `${p}` — in a `retrieve` /
`mutate` / `purge` `where:` clause, a `step` `ask:` prompt, a
`persist` / `mutate` field block — interpolates against the bound
value. SSE and JSON dynamic routes bind IDENTICALLY.

**TRUST (D3 — epistemic honesty).** A bound value crossed the network
boundary; it is `Untrusted` input. Where it reaches a store `where:`
clause it is handed to the Fase 35 filter compiler as a PARAMETER
(compiled to a placeholder `$N`), NEVER string-spliced into the filter
source before parsing. Request data cannot become SQL by
concatenation — injection is closed by construction.

**The contract in one line:** `body: T` + `execute: F` is a promise
the compiler proves total, the runtime delivers on every transport,
and the type system guards as `Untrusted`.

# ▶ 4. D-letters (D1–D7 — RATIFIED founder bloque 2026-05-18)

| D | Decision |
|---|---|
| **D1** | **The Request Binding Contract — runtime delivery.** An `axonendpoint`'s declared `body: T` populates the parameters of its `execute: F` flow, by NAME (body field `x` → flow parameter `x`). The runtime parses the body once, binds each flow parameter from its matching field, and seeds `DispatchCtx.let_bindings` BEFORE the flow body walk — so `${param}` interpolates in `where:` clauses, step `ask:` prompts, and `persist`/`mutate` field blocks. Both transports — SSE and JSON dynamic routes — bind identically. The body is parsed once and threaded; no double-parse. |
| **D2** | **Compile-time totality — the binding is a proven total function.** The frontend type-checker verifies every REQUIRED parameter of `execute: F` is satisfiable from a field of `body: T` — by name, type-compatible. An uncovered required parameter is a COMPILE ERROR (the endpoint-binding-totality error code, assigned in 37.c, surfaced at `axon check` + `POST /v1/deploy`). An optional parameter may be uncovered. The endpoint→flow→parameter compositional check — the sibling of Fase 35 Pillar IV's endpoint→flow→store-capability check. You cannot deploy an endpoint that will fail at runtime for a missing argument. |
| **D3** | **Epistemic provenance — request values are `Untrusted` and reach a store filter only as a bound parameter.** A value bound from the request body crossed the network trust boundary; the language treats it as `Untrusted` input. The enforceable guarantee: a `${param}` interpolated into a store `where:` clause binds as a FILTER PARAMETER (compiled to a placeholder), never string-spliced into the filter source before parsing. 37.d audits the `${param}`→`where:` path and fixes any pre-parse splice. Injection (OWASP A03) is closed by construction, not by developer discipline. |
| **D4** | **Only declared flow parameters bind — the contract stays tight.** A body field is bound ONLY when it matches a DECLARED flow parameter of `execute: F`. An undeclared body field is NOT silently injected into `let_bindings`. This keeps D2's totality check meaningful: every `${x}` in a flow body must resolve to a declared, type-checked parameter (or a `let`/step binding) — never to a silently-empty typo. A flow that wants a body field declares it as a parameter. Scalar fields (String/Int/Float/Bool) bind as their string form; a nested-object parameter is honest future scope (§7). |
| **D5** | **Backwards compatibility — absolute.** A flow with NO parameters behind an endpoint with NO `body:` is byte-identical. The legacy `/v1/execute` RPC path is unchanged. Every Fase 30–36 wire for a non-erroring flow is byte-identical. The ONLY behavior changes are intended: (a) a parameterised flow now RECEIVES its arguments instead of empty strings; (b) an endpoint whose flow has an uncovered required parameter now fails at COMPILE time instead of silently at runtime; (c) an errored streaming flow's `axon.error` now carries the diagnostic. |
| **D6** | **Honest streaming failure (Finding B).** A streaming flow that errors emits an `axon.error` event carrying the structured diagnostic — error class, message, the failing node's name, the trace_id — and the server logs a structured error line. `FlowExecutionEvent::FlowError` already carries `error`; the wire adapter stops dropping it. The "honest failure" principle of Fase 36 (backend resolution → structured 503) extended to flow execution on the streaming wire. The failure terminator is never hollow. |
| **D7** | **The production gate.** A dedicated CI lane: the end-to-end agent-flow binding E2E (deploy a parameterised `retrieve → step → persist` flow behind an `axonendpoint body: T`, hit it with a real body, assert `${param}` resolved + the correct rows returned), the compile-time totality cross-stack drift gate, the injection-resistance property/fuzz pass, the structured-error wire assertion, and the D5 backwards-compat corpus. |

# ▶ 5. Sub-fases (37.a–37.i — topologically ordered)

| Sub-fase | What | Class | D-letters | Status |
|---|---|---|---|---|
| **37.a** | Diagnostic anchor — a committed test pinning the v1.35.0 broken state: a parameterised flow behind an `axonendpoint body: T` runs with an EMPTY `let_bindings` map (`${param}` interpolates to the literal); a `retrieve` `where:` with a `${param}` queries for the literal string; an errored streaming flow emits a hollow `axon.error` (no detail). Each later sub-fase inverts a §-assertion. | OSS | — | ✅ SHIPPED — `axon-rs/tests/fase37_a_request_binding_diagnostic.rs` (3 tests, deterministic + infra-free). §1 pins FINDING A: a parameterised `EchoFlow(message)` behind `axonendpoint EchoE { body: EchoBody execute: EchoFlow transport: sse }`, hit with `{"message":"SENTINEL_BODY_VALUE_37A"}` via a `stub_stream` echo tool — the wire does NOT contain the sentinel and the literal `${message}` survives un-interpolated (the request body is parsed for schema validation then discarded; nothing seeds `DispatchCtx.let_bindings` from `IRFlow.parameters`). §2 is the positive control: a flow-body `let` binding DOES interpolate through the SAME echo-tool harness — isolating the defect to request-body params, not a broken observation harness (this test is a permanent regression guard, never inverted). §3 pins FINDING B: a `sqlite`-store registry-build failure behind `transport: sse(openai)` — the wire signals `terminal_reason: error` + terminates with `[DONE]` but the `FlowError.error` string (`axonstore registry: …`) is DROPPED by the openai dialect's `FlowError` arm (`wire_format/openai_dialect.rs:390`). Confirmed: the `axon` dialect's `build_error_event` DOES carry `error` — the loss is openai/kimi/glm-specific. 3/3 green. 37.b inverts §1, 37.e inverts §3. |
| **37.b** | The runtime binding (D1, D4) — thread the parsed request body from `dynamic_endpoint_handler` through `server_execute_streaming` + `run_streaming_via_dispatcher` (and the symmetric JSON `execute_handler` path); after the flow resolves from IR, bind each declared `IRFlow.parameter` from its matching body field and seed `DispatchCtx.let_bindings` before the body walk. The structural core — everything downstream depends on it. | OSS | D1, D4 | ✅ SHIPPED — new `axon-rs/src/request_binding.rs`: `bind_request_body(flow, body) -> Vec<(String,String)>` binds each declared `IRFlow.parameter` from its same-named body field (D1, by name), ignores undeclared body fields (D4), stringifies scalars (string→raw, number/bool→canonical JSON, null→empty); 6 module unit tests. **Streaming path**: `run_streaming_via_dispatcher` gains a `request_body: Option<serde_json::Value>` param + seeds `ctx.let_bindings` from `bind_request_body` AFTER `DispatchCtx` construction, BEFORE the §6 walk; threaded through `server_execute_streaming` + `StreamExecuteRequest.request_body` (`#[serde(default)]`) + `execute_sse_handler_inner`. **JSON path**: `ExecuteRequest.request_body` (`#[serde(default)]`) threaded `execute_handler` → `execute_with_fallback` → `server_execute` → `runner::execute_server_flow`, which computes `param_bindings` on each `ExecutionUnit` and seeds every `ExecContext` (stub + real run loop) before the step walk. `dynamic_endpoint_handler` parses the body ONCE and sets it on both request structs. `server_execute_full` + its 16 callers UNTOUCHED — it passes `None`. 37.a §1 inverted in place → green regression guard. New `axon-rs/tests/fase37_b_request_binding.rs` (5 tests): §1 multi-param bind-by-name into a step `ask:`; §2 the body param threads through the full mixed agent flow (retrieve→step→persist); §3 D4 undeclared field not bound; §4 D5 parameter-less flow byte-clean; §5 D1 holds on the JSON transport. Regression: lib 2035 + fase36x_d/e/f + fase33z_d parity + fase33z_production_fuzz + fase33_b + fase33z_c + integration — all green (every non-dynamic-route caller threads `None` ⇒ empty bindings ⇒ byte-identical; D5 by construction). |
| **37.c** | Compile-time totality (D2) — the frontend type-checker proves `params(F) ⊆ fields(T)` by name + compatible type for every REQUIRED parameter; an uncovered required parameter is a named compile error (code assigned here, modelled on the Fase 35 Pillar IV capability-gate error); surfaced at `axon check` + `POST /v1/deploy`. Rust-canonical (`axon-frontend` type-checker). | OSS | D2 | ✅ SHIPPED — `axon-frontend` type-checker: `check_axonendpoint` gains the totality check — when the endpoint declares `body: T`, for every REQUIRED parameter of `execute: F` (an OPTIONAL parameter is skipped) it resolves a same-named field of `T` (`find_type_by_name`) and verifies type-compatibility (exact `name` + `generic_param`). An uncovered required parameter → compile error ("no matching field in body type"); a covering field of the wrong type → compile error ("the types must match"). New `fmt_type_expr` diagnostic helper. The check runs ONLY when `body: T` resolves to a declared struct type — a primitive/undeclared `body:` has no fields and the runtime binding is then untyped/best-effort (honest scope). Sibling of the Fase 35.j Pillar IV endpoint→flow→store-capability check; surfaces at `axon check` + `POST /v1/deploy` via the normal type-error channel. New `axon-frontend/tests/fase37_c_binding_totality.rs` (7 tests): §1 uncovered required param → error; §2 covered → clean; §3 type mismatch → error naming both types; §4 optional param need not be covered; §5 no `body:` → D2 silent; §6 multi-param agent shape fully covered → clean; §7 partial coverage names exactly the uncovered param. Regression: axon-frontend full suite 262 + fase32 body/route/transport/auth/output (72) + fase37_a/b — all green, zero regressions (existing endpoints use parameter-less flows). Rust-canonical — Python frontend untouched. |
| **37.d** | Injection-safe filter binding (D3) — audit the `${param}` → store `where:`-clause path; guarantee a request-bound value reaches the Fase 35 filter compiler as a PARAMETER (placeholder `$N`), never string-spliced into the filter source before parsing. Fix any pre-parse splice found. The enforceable form of the epistemic `Untrusted` contract. | OSS | D3 | ✅ SHIPPED — **audit found**: the synchronous runner string-spliced the `where:` clause (`ctx.interpolate(raw_expr)` pre-parse — a request value carrying a `'` could break a string-literal boundary and inject filter logic); the streaming dispatcher did not interpolate `${name}` in a `where:` at all. **Fix** — the filter compiler (`store::filter`) now resolves `${name}` SAFELY: `parse_filter`/`build_pg_where` gain a `bindings` param; the `where` expression is tokenized FIRST (raw — every string-literal boundary fixed before substitution), THEN each `Token::Str`'s content is interpolated (`interpolate_vars`) against the bindings. A resolved value lives only inside an already-delimited string token → rendered as a `$N` bind placeholder by the unchanged `build_pg_where` → a value carrying `'`/`;`/`--`/`OR '1'='1'` cannot move a boundary or inject syntax. Injection (OWASP A03) closed by construction. Bindings threaded: `build_select_sql`/`build_delete_sql`/`build_update_sql` + `PostgresStoreBackend::{query,mutate,purge}` + `row_stream::stream_retrieve` + `run_retrieve`/`run_mutate`/`run_purge` (streaming, `&ctx.let_bindings`) + the sync runner (`execute_sql_store_step` takes the RAW `store:where` + `ctx.vars()`, no pre-splice; new `ExecContext::vars()`). New `axon-rs/tests/fase37_d_filter_injection.rs` (9 tests, pure + infra-free): §1 `${name}`→`$N`; §2 a `DROP TABLE` payload is an inert bind param; §3 an `OR '1'='1'` payload adds no condition; §4 the boundary theorem — a `'` in the value cannot escape the literal; §5 `${name}` embedded in a LIKE pattern; §6 multiple placeholders in order; §7 unbound placeholder stays literal+inert; §8 D5 empty-bindings backwards-compat; §9 the `$name` brace-less form. Regression: lib 2035 + fase35_fuzz + fase36x_d/e + fase37_b — all green. Rust-canonical. |
| **37.e** | Honest streaming failure (D6) — `FlowExecutionEvent::FlowError` → `axon.error` event carries error class + message + failing-node name + trace_id; the SSE consumer / dialect adapter stops dropping `FlowError.error`; the server logs a structured error line. | OSS | D6 | ✅ SHIPPED — the adopter's Finding B closed. `FlowExecutionEvent::FlowError` already carries an `error` diagnostic; the loss was dialect-specific — the `axon` dialect surfaced it (`build_error_event`), but `openai` (→ `kimi`/`glm`, which `select_adapter` maps to the OpenAI adapter) and `anthropic` DROPPED it, emitting a hollow `terminal_reason: error`. Fix: the openai + anthropic adapters gain an `error_detail: Option<String>` field, stash it in the `FlowError` translate arm, and surface it as the `axon_metadata` / `axon.metadata` frame's `error` field (elided on a non-erroring flow). Producer (`run_streaming_via_dispatcher`): every `FlowError` emit (§2 compile / §2.5 registry / §3 flow-not-found / §6 dispatch loop) now logs a structured `tracing::error!` line; the §6 dispatch-loop diagnostic NAMES the failing node — `flow 'F' failed at <step '…' | retrieve from '…' | persist into '…' | mutate '…' | purge '…' | node #N>: <cause>`. New `axon-rs/tests/fase37_e_honest_streaming_error.rs` (5 tests): §1 openai surfaces the error; §2 axon surfaces it; §3 anthropic surfaces it; §4 the failing node is named (a mid-walk `postgresql`-connect failure → `retrieve from 'pg'`); §5 D5 — a successful flow's wire carries NO `error` field. 37.a §3 inverted in place → green regression guard. Regression: lib 2035 + fase33z_k_h + fase34_a + fase33z_c/b/e + fase36x_d — all green. Rust-canonical. |
| **37.f** | Integration tests (D1, D3, D5) — the full agent flow end-to-end behind a streaming `axonendpoint` with a real request body: `${tenant_id}` resolves, the `retrieve` returns the correct rows, the `step` prompt interpolates the bound message, the `persist` field block writes the bound values. Happy path + error path + the JSON-transport mirror. All `in_memory` — zero infra (Fase 36.x.b). | OSS | D1, D3, D5 | ✅ SHIPPED — new `axon-rs/tests/fase37_f_agent_flow_e2e.rs` (6 tests, all `in_memory` — zero infra) — the Request Binding Contract proven end-to-end on the canonical agent flow through the real HTTP surface: §1 the founder's `ChatFlow` shape (retrieve ×3 → step → persist), parameterised, behind `transport: sse` — every body parameter threads to the `step` deliberation, the mixed flow streams to a clean terminator; §2 the data round-trips — a body parameter `persist`ed into an `in_memory` store and `retrieve`d back (by binding-name) into a downstream step (`loaded=ROUNDTRIP_F2`); §3 the error path stays honest — an errored agent flow names WHY on the wire (`axon.error` + `axonstore registry`), exactly one terminator (ties 37.e); §4 the JSON transport mirror — the agent flow runs on `transport: json` with the body bound, `steps_executed == 3`; §5 D3 — an adversarial body value (`'; DROP TABLE x; -- ${nested}`) flows through INERT: interpolated once, echoed verbatim, the nested `${...}` never re-interpreted, the flow does not break; §6 D5 — a parameter-less flow behind a no-`body:` endpoint streams byte-clean. Test-only sub-fase — no production change; 6/6 green. |
| **37.g** | Property/fuzz pass (D2, D3, D7) — a deterministic property test that the binding is total + injection-resistant over arbitrary body / parameter shapes (covered params, uncovered required params, optional params, adversarial values containing filter syntax / SQL meta-characters / interpolation tokens). | OSS | D2, D3, D7 | ✅ SHIPPED — two deterministic LCG-driven fuzz packs (hand-rolled PRNG, no external dep). **`axon-rs/tests/fase37_g_request_binding_fuzz.rs`** (3 tests): Surface A — `bind_request_body` over 2 000 arbitrary `(flow parameters, request body)` shapes (object/scalar/array/null/absent bodies; scalar/null/nested/adversarial values): total (never panics), D4 (the bound set is EXACTLY {declared params} ∩ {body fields}, in declaration order), deterministic. Surface B — `build_pg_where` with `${name}` resolution over 2 000 arbitrary `where` templates × adversarial binding values (`'; DROP TABLE`, `' OR '1'='1`, `\'; DELETE`, `UNION SELECT`, nested `${...}`): total; the STRUCTURE is template-determined (a K-condition template → exactly K `$N` placeholders + K bind params, regardless of the values — an adversarial value cannot add a condition); NO VALUE LEAK (no resolved value's text appears in the rendered SQL clause); + 500 iters over unbound/empty-bindings paths. **`axon-frontend/tests/fase37_g_totality_fuzz.rs`** (1 test, 800 iters): the D2 compile-time totality verdict is cross-checked against an independently-computed predicate (`violations = #{required param uncovered-or-type-mismatched}`) over every covered/uncovered/optional/mismatched parameter shape — the type-checker emits EXACTLY one D2 error per violated required parameter. Test-only sub-fase — no production change; ~5 300 fuzz iterations, all green. |
| **37.h** | CI lane (`fase_37_request_binding_contract.yml`) + adopter docs — the binding-contract guide in `docs/ADOPTER_REST.md` / `docs/ADOPTER_AXONSTORE.md` + the canonical parameterised-agent recipe + `docs/MIGRATION_v1.36.md`. | OSS | D7, D5 | ✅ SHIPPED — new `.github/workflows/fase_37_request_binding_contract.yml` (4 parallel lanes: `rust-frontend` = the D2 compile-time totality `fase37_c` + the D2 totality fuzz `fase37_g`; `rust-runtime` = the full runtime surface `fase37_a/b/d/e/f` + the `request_binding` lib pack; `fuzz-d3` = `fase37_g` injection-resistance ~4 800 iters; `regression` = D5 — Fase 35 axonstore filter/store + Fase 33/34 streaming + Fase 36/36.x dynamic routes must not regress). Adopter docs: `docs/ADOPTER_REST.md` gained §5 "The Request Binding Contract (v1.36.0)" — the parameterised-agent recipe + the four guarantees (D1 bind-by-name on both transports, D2 compile-time totality with the better-than-FastAPI/Spring/NestJS framing, D3 `Untrusted`-by-birth → `$N` bind param, D4 only-declared-params-bind), TOC renumbered 5→19. New `docs/MIGRATION_v1.36.md` (v1.35.x → v1.36.0 — 5-row change table, the 3 intended behavior changes, 5 migration scenarios A–E incl. the `axon check` totality-error recipe, the D5 "what does NOT change" list, an upgrade checklist). Doc/CI-only sub-fase — no production change. |
| **37.i** | Coordinated release axon-lang v1.36.0 cross-stack (crates.io + PyPI + GitHub Release + binaries) + axon-frontend bump (0.17.0 → 0.18.0 — the totality check is a frontend change) + axon-enterprise catch-up (v1.26.0 → v1.27.0). | SPLIT | — | ⏳ pending |

**Total estimate: ~2 000–2 800 LOC** (the runtime body-threading + the type-checker totality check + the filter-binding audit + the structured-error wire change + the integration + property test packs + the CI lane + docs). Comparable to Fase 36.x — one contract with a compile-time and a runtime half, plus an observability fix. Built Rust-canonical. D5 zero-regression absolute.

# ▶ 6. OSS / ENTERPRISE / SPLIT classification

Fase 37 is **OSS** end to end — the request-binding contract, the
compile-time totality check, the epistemic treatment of request-origin
values, and the structured streaming error are core language +
runtime; adopter-agnostic. The **enterprise seam** is unchanged:
per-tenant body-field policy, vertical request validation, PII-class
field tagging (HIPAA Safe Harbor field classification on the request
body), and per-tenant rate/shape limits layer ON TOP of the OSS
binding contract — none of it gated here. 37.i is **SPLIT**: axon-lang
v1.36.0 (OSS) + an axon-enterprise catch-up (v1.27.0).

# ▶ 7. Honest scope

- Fase 37 closes the binding of the declared **`body: T`** request
  input. Path parameters and query parameters do NOT have a declared
  type surface in axon today — the router is exact-match on
  `(method, path)` (Fase 32.b) with no `:segment` capture. Binding
  path/query inputs is a future fase; the honest move is to fully
  close the ONE typed request surface that exists, not to half-ship a
  path-param grammar.
- D3 delivers the epistemic `Untrusted` principle in its first
  ENFORCEABLE form — request data reaches a store filter only as a
  bound parameter. A full trust-type DIMENSION carried on every
  runtime binding (every `let_bindings` value tagged with its trust
  level + provenance, propagated through interpolation) is a larger
  effort and is NOT half-shipped here; D3 ships the concrete
  injection-closure that matters most. The trust-dimension on runtime
  bindings is a candidate follow-on fase.
- D4 binds SCALAR body fields (String / Int / Float / Bool) as their
  string form into the `HashMap<String,String>` binding map. A
  nested-object or list-typed flow parameter is honest future scope —
  37.c's totality check will name it explicitly rather than bind it
  silently.
- D5 absolute backwards-compat — every non-erroring Fase 30–36 wire
  is byte-identical; the legacy `/v1/execute` RPC path is untouched.
- Python frontend untouched (Rust-canonical — see `strategic_direction`).

# ▶ 8. Why this matters

Fase 36 proved a deployed `axonendpoint` runs a real, resolved,
honest backend. Fase 36.x proved the agent flow behind it — retrieve,
deliberate, persist — streams cleanly and ends honestly. Fase 37
proves the agent flow can SEE ITS INPUT.

An agent that cannot read its request is not an agent. And the
industry's answer to "bind the request to the handler" is to bind it
and hope — discovering a missing field as a runtime `KeyError` in
production. AXON's answer is a compile-time theorem: the binding is
proven total before the endpoint can deploy, the runtime delivers it
on every transport, and the type system remembers that the value came
from the network — so it can never reach the database as anything but
a bound parameter. That is not the industry standard. That is the
four-pillar difference, and it is what an adopter building a real
agent on axon should be able to take for granted.
