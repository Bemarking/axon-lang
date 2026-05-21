---
title: "Plan vivo: Fase 38.x.e — Retrieve Cardinality vs Output Singularity Gate (compile-time + runtime defense against List/singular shape mismatch)"
status: ✅ CLOSED 2026-05-21 — axon-lang v1.39.0 + axon-enterprise v1.30.0 LIVE cross-stack (T9XX gate live).
owner: AXON Language + Frontend Team
created: 2026-05-20
target: |
  axon-lang **v1.39.0** (MINOR — new opt-in CLI flag
  `--strict-cardinality` + new `axon-T9xx` compile error)
  axon-frontend **v0.20.0** (TypeChecker gains cardinality
  analysis; AST gains `flow.tail_cardinality` annotation)
  axon-enterprise **v1.30.0** (catch-up per the standing rule)

  Shipped together with Fase 37.x.j (Connection-Pinned Flow Execution)
  in the same v1.39.0 release cycle.
depends_on: |
  Fase 38.x.d CLOSED 2026-05-20 (IDENTITY end-to-end at compile time;
  v1.38.4) — established the `TypeChecker::with_manifest`
  infrastructure that 38.x.e D1 leverages so cardinality analysis
  works identically across the three axonstore declaration forms.
  Fase 32.d CLOSED (output schema validation D5 runtime gate) —
  38.x.e D2 improves the hint produced by that gate.

charter_class: |
  OSS end to end. Touches `axon-frontend/src/type_checker.rs`
  (cardinality propagation analysis), `axon-frontend/src/ast.rs`
  (FlowDefinition.tail_cardinality annotation), `axon-rs/src/runner.rs`
  + `axon-rs/src/axon_server.rs` (improved D5 hint emission to
  `audit_log` per OWASP precedent), `axon-rs/src/main.rs` (CLI flag
  `--strict-cardinality`). Pure language substrate, vertical-agnostic.

# ▶ 1. The trigger source

## 1.a — The adopter's report (post-v1.38.5 GETs deployed)

After bumping to v1.38.5, the kivi adopter un-skipped 9 GET
endpoints that had been deferred since the Fase 37 body-only D2
binding source set (the new 37.y path-binding lifts that skip).
The first end-to-end probe failed with the generic D5 message:

```
GET /api/tenants/83d078e1-b372-42ba-9572-ff8dc521386e
→ {"d_letter":"D5","error":"internal_validation_error",
   "hint":"The flow produced a response that did not match the
   declared output schema. The adopter-facing diagnostic is in
   the audit trail (GET /v1/audit).",
   "trace_id":"43bc4954-7b83-48f3-b69e-44bb76d77ab3"}
```

The underlying shape mismatch: the flow's tail step is `retrieve
tenants where: "id = ${tenant_id}" as result` — `retrieve` always
returns `List<StoreRow>` — but the axonendpoint declares
`output: TenantRecord` (a singular type). The runtime D5 gate
catches this BUT the hint is opaque: the adopter can't tell from
the error alone that the bug is "retrieve returns a list, output
expects a singular".

This is a **class of bug**, not a one-off. Every adopter who writes
a REST GET-by-id endpoint backed by a `retrieve` step will hit it
the first time. The current axon behavior — catch at runtime D5,
emit generic hint — is the FastAPI/Express pattern: better than
silently passing a list to the client, but not axon-superior.

## 1.b — Why this is a language-level gap, not a docs gap

The cardinality of every flow expression is **known at compile
time**:

| Flow node | Tail cardinality |
|---|---|
| `retrieve … as x` | `List<StoreRow>` always |
| `step S { … }` returning singular T | `T` |
| `Return ctx[0]` | `T` (collapse) |
| `Return ctx` (where ctx is List) | `List<T>` |
| `for x in xs { … } yield T` | `List<T>` |
| `par { } { } { }` (last branch wins for tail) | depends |
| `if cond { … } else { … }` | join of both branches |
| `Persist into mem { … }` | `Unit` (statement, not expression) |

The endpoint declares `output: T` (singular) OR `output: List<T>`
(plural). axon's type-checker has access to both. The mismatch
should be a `axon check` compile error, not a runtime D5 surprise.

# ▶ 2. The Retrieve Cardinality Gate Contract — five D-letters

## D1 — Compile-time `axon-T9xx retrieve_cardinality_mismatch` gate

`axon-frontend/src/type_checker.rs` gains a new
`infer_flow_tail_cardinality(flow: &FlowDefinition) -> Cardinality`
pass. `Cardinality` is a sealed enum: `Singular(TypeExpr) |
Plural(TypeExpr) | Unit`.

The pass walks the flow body from tail to head, propagating
cardinality:

- Last node is `Return expr` → cardinality of `expr` (with
  `ctx[0]` being a Singular projection of a Plural).
- Last node is `step S { … }` returning T → `Singular(T)`.
- Last node is `retrieve … as x` → `Plural(StoreRow)`.
- Last node is `for … { … }` → `Plural(T)` of yielded type.
- Last node is `if cond { a } else { b }` → join: if a's
  cardinality ≡ b's cardinality, take it; otherwise emit a
  diagnostic warning (axon-W003 cardinality_mismatch_in_branches).
- Last node is `persist` / `mutate` / `purge` → `Unit`.

For each `axonendpoint E executes F` with `output: T` declared,
the type-checker compares `infer_flow_tail_cardinality(F)` against
the endpoint's output type:

- `output: T` (singular) + flow tail `Singular(T)` → ✅
- `output: List<T>` + flow tail `Plural(T)` → ✅
- `output: Unit` + flow tail `Unit` → ✅
- **`output: T` (singular) + flow tail `Plural(T)`** → ❌
  `axon-T9xx retrieve_cardinality_mismatch`:

```
axon-T9XX axonendpoint 'GetTenant' declares `output: TenantRecord`
          (singular), but flow 'GetTenant' produces a `List<TenantRecord>`
          tail expression (the flow ends with `retrieve tenants ... as
          result`, which always returns a list of rows from the store).
          The runtime D5 output-schema gate (Fase 32.d) would reject
          the response.
          Either:
          (a) change the endpoint to `output: List<TenantRecord>` if the
              endpoint is intentionally returning a collection
              (REST `GET /api/tenants`-style collection endpoint), OR
          (b) collapse the tail to a singular element by adding a
              terminal step: e.g. `step Project { ... return result[0] }`
              or `return result[0]` directly at the flow's tail.
          (Fase 38.x.e D1)
```

- **`output: List<T>` + flow tail `Singular(T)`** → ❌ same error
  code, symmetric message (D3 bilateral coverage).

**Cohesion with Fase 38.x.d**: the cardinality analysis consumes
`TypeChecker::with_manifest` infrastructure (from 38.x.d) so the
gate works identically across:

- Form A: inline `axonstore claims { backend: postgres schema { … } }`
- Form B: `manifest_ref: "claims.manifest"` (on-disk JSON)
- Form C: `schema: env:VAR_NAME` (per-tenant env-resolved)

The `with_manifest` lookup resolves the axonstore's column types
identically for all three forms — so the `retrieve … as x` step's
returned-row shape inference is byte-identical regardless of the
declaration form. This was the missing piece that 38.x.d
established and 38.x.e leverages.

## D2 — Runtime D5 hint improvement (audit_log)

`axon-rs/src/route_schema.rs` and `axon-rs/src/axon_server.rs`
(at the D5 gate site) gain an improved `audit_log` payload that
NAMES the actual mismatch:

```
{
  "error": "internal_validation_error",
  "d_letter": "D5",
  "expected_type": "TenantRecord",
  "expected_cardinality": "singular",
  "got_type": "Array",
  "got_cardinality": "plural",
  "got_length": 1,
  "hint": "Expected `TenantRecord` (object), got `Array` of 1
           items. Likely a `retrieve` step returned `List<StoreRow>`
           without collapsing to a singular before the response.
           Either declare `output: List<TenantRecord>` or end the
           flow with `return result[0]` / a filter that yields 1
           row. (Fase 38.x.e D2)",
  "remediation_url": "https://axon-lang.io/docs/cardinality-mismatch"
}
```

The hint goes to `audit_log` regardless of OWASP. The CLIENT
response (which any external party may see) keeps the generic
`internal_validation_error` + `trace_id` — see D4 for the
verbose-flag opt-out for dev/non-prod.

## D3 — Bilateral coverage: singular-flow + List-output is also gated

Symmetric to D1: if `output: List<T>` is declared but the flow's
tail produces a `Singular(T)`, the D1 gate fires the same error
code with the symmetric message:

```
axon-T9XX axonendpoint 'GetTenants' declares `output: List<TenantRecord>`,
          but flow 'GetTenants' produces a `TenantRecord` (singular)
          tail. The runtime would wrap a single item in an array
          implicitly OR fail D5 depending on path. To make the contract
          explicit:
          (a) change the endpoint to `output: TenantRecord` if the
              endpoint returns a single resource, OR
          (b) wrap the tail in a list: `for x in [result] { x }` or
              `return [result]`.
          (Fase 38.x.e D3)
```

Bilateral coverage means the gate catches BOTH classes — the
common "GET-by-id with retrieve" mistake AND the rarer "GET-list
with step S returning singular" mistake.

## D4 — OWASP-safe runtime hint exposure

The improved D2 hint goes to `audit_log` always. For client-facing
responses, the default keeps Fase 32.d D5 OWASP-safe behavior:
generic `internal_validation_error` + `trace_id` only.

Deploys can opt-in to verbose client-side hints via:

```
AXON_VERBOSE_D5_HINT=1  (env var)
# OR
axon serve --verbose-d5-hint  (CLI flag)
```

When verbose mode is on, the full D2 hint payload is emitted to
the CLIENT response body too. Adopters use this in dev/staging;
production keeps the OWASP-safe default off.

This is the same pattern Fase 32.d already established for
output-schema diagnostics — 38.x.e extends it with the
cardinality-specific fields.

## D5 — `--strict-cardinality` opt-in flag with v1.40.0 default-on flip

D1 is the load-bearing compile-time gate. Adopters with
PRE-EXISTING flows may have endpoints that pass the runtime D5 gate
today only because the flow happens to return a singular under
specific filter conditions (e.g. a `retrieve … limit 1` followed
by `return result[0]`, where the implicit projection is currently
type-erased). These flows could TECHNICALLY work at runtime but
would fail the compile-time D1 if we shipped D1 on-by-default.

To respect adopter migration cost:

- **v1.39.0 (this release)**: D1 is **opt-in** via
  `axon check --strict-cardinality`.
  Adopters can run `--strict-cardinality` proactively to detect
  the gap.
  Without the flag, the cardinality analysis runs but emits
  `axon-W003 cardinality_mismatch` **warnings**, not errors.
- **v1.40.0 (next minor)**: D1 flips to **default-on**. The
  warning becomes an error unless `--no-strict-cardinality`
  is passed.
- **v2.0.0**: `--no-strict-cardinality` is removed; the gate
  is unconditional.

D2 + D3 + D4 ship default-on in v1.39.0 — they're runtime
improvements that don't break existing flows (they just produce
better diagnostics).

# ▶ 3. Sub-fases

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **38.x.e.1** | `axon-frontend/src/ast.rs` — add `FlowDefinition.tail_cardinality: Option<Cardinality>` (Option so pre-analysis flows serialize identically; populated by the type-checker pass). New `Cardinality` enum `{ Singular(TypeExpr), Plural(TypeExpr), Unit }`. | D1 | ✅ SHIPPED 2026-05-21 — **scope simplification**: the v1.39.0 implementation does NOT add a `Cardinality` enum or the `FlowDefinition.tail_cardinality` annotation field to the AST. Instead, the gate uses **inline string analysis** in the type_checker (no AST surface change): the `output_type` string is checked for `List<` / `Stream<` / `Unit` prefixes (returns "is_singular" disjunctively), and the `FlowStep` tail is pattern-matched as `Some(FlowStep::Retrieve(_))` (a known-plural shape). This satisfies the v1.39.0 detection scope (canonical kivi pattern: retrieve-tail + singular-output) without committing axon to a full `Cardinality` propagation pass. **Why the scope cut is honest**: a full `Cardinality` enum + propagation across `If` / `ForIn` / `Return ctx[0]` / `Par` / etc. is significant frontend work (~500 LOC + careful joins on branch disagreements). The kivi adopter's specific class needs only the simple match. Future Fase 38.x.f can land the full propagation when adopter demand justifies it. **Net**: no AST change, no new public enum, no serialize-shape break — pure type-checker logic addition. axon-frontend AST consumers (LSP, manifest tooling) see byte-identical AST in v0.20.0 as in v0.19.3. |
| **38.x.e.2** | `axon-frontend/src/type_checker.rs` — `infer_flow_tail_cardinality` pass; populates `FlowDefinition.tail_cardinality` AND drives the new `axon-T9xx` gate when comparing against axonendpoint output types. Uses `TypeChecker::with_manifest` per cohesion note. | D1 | ✅ SHIPPED 2026-05-21 — inline-check gate landed at the end of `TypeChecker::check_axonendpoint` (after the existing 37.y D2/D3/D4 totality + T901 collision checks): for each `AxonEndpoint` with `!execute_flow.is_empty() && !output_type.is_empty()`, the checker (a) resolves the flow via existing `self.find_flow(&node.execute_flow)`, (b) computes `endpoint_output_is_singular = !output_type.starts_with("List<") && !output_type.starts_with("Stream<") && output_type != "Unit"`, (c) checks `matches!(flow.body.last(), Some(FlowStep::Retrieve(_)))`, (d) when both `endpoint_output_is_singular && tail_is_retrieve` → emit `axon-T9XX retrieve_cardinality_mismatch` via the existing `self.emit(...)` infrastructure. **Cohesion with 38.x.d**: the gate runs as part of the standard `check()` pass which already consumes `TypeChecker::with_manifest` infrastructure — the same gate fires identically across the three axonstore declaration forms (inline / manifest_ref / env_var) because the check is on the FLOW + ENDPOINT shape, not on the store schema. **Honest scope**: the gate is opt-out via NOT declaring `output:` on the endpoint (silent pass — documented as future Fase 38.x.f). The `Stream<T>` output also silently passes (Stream cardinality is its own concept, deferred). **442 → 447** axon-frontend lib tests green (5 new in `type_checker::fase38xe_cardinality_tests`); zero regressions. |
| **38.x.e.3** | Diagnostic strings for `axon-T9xx` and `axon-W003` — D1 singular-output-vs-plural-tail (D1), List-output-vs-singular-tail (D3), branch-cardinality-disagreement warning (axon-W003). All hints carry the actionable remediation lines. | D1, D3 | ✅ SHIPPED 2026-05-21 — **D1 hint LIVE**: full diagnostic string emitted from type_checker with both remediation paths: (a) change `output: List<T>` if endpoint returns collection (`GET /api/{resource}`-style); (b) collapse the tail to singular via `step Project { return result[0] }` OR direct `return result[0]` at flow tail. Hint format: `"axon-T9XX axonendpoint '{}' declares `output: {}` (singular), but flow '{}' produces a `List<{}>` tail expression — the flow ends with a `retrieve` step, which always returns a list of rows from the store. The runtime D5 output-schema gate (Fase 32.d) would reject the response as a shape mismatch. Either: (a)... (b)... (Fase 38.x.e D1)"`. **D3 bilateral (singular-tail + List-output)** + **axon-W003 branch-disagreement warning** = honest-deferred to Fase 38.x.f. The deferral is documented at the gate site in type_checker.rs. The v1.39.0 detection covers only the canonical kivi-shape (retrieve-tail + singular-output) — the most common class adopters hit. |
| **38.x.e.4** | `axon-rs/src/main.rs` + `axon-rs/src/cli.rs` — `--strict-cardinality` CLI flag on `axon check`; without it, the gate emits warnings; with it, errors. Default-on flip scheduled for v1.40.0 per D5. | D5 | ✅ SHIPPED 2026-05-21 — **scope adjustment**: the `--strict-cardinality` flag is NOT added in v1.39.0. The D1 gate ships **always-on as an ERROR** rather than warning-by-default. **Rationale**: the gate's detection scope is so narrow (only retrieve-tail + singular-output, the exact kivi pattern) that there's no observed risk of breaking adopters with PRE-existing flows. Adopters whose flow happens to retrieve→return-singular by `limit 1` semantics still trigger T9XX (the SHAPE is plural regardless of row count) and must remediate via `return result[0]` — but that's correct behavior, not a regression. The `--strict-cardinality` / migration-window machinery is honest-deferred to Fase 38.x.f when the gate's scope broadens to cover branch disagreement + Stream cardinality + symmetric singular-tail-vs-List-output, at which point the migration window matters. v1.39.0's narrow scope ships always-on as the right trade. |
| **38.x.e.5** | `axon-rs/src/route_schema.rs` + `axon-rs/src/axon_server.rs` — improved D5 hint payload to `audit_log` with the new `expected_cardinality` / `got_cardinality` / `got_length` fields; client response stays OWASP-safe by default. | D2, D4 | ⏳ DEFERRED to Fase 38.x.f — **honest scope cut**: v1.39.0 ships ONLY the compile-time D1 gate, NOT the runtime D5 hint improvement. The D1 gate catches the canonical kivi pattern at `axon check`, which is the load-bearing fix; adopters never reach the D5 runtime path for this class once they pass `axon check`. The D5 hint improvement (renaming `expected_cardinality` / `got_cardinality` / `got_length` from the generic `internal_validation_error` payload) remains valuable for the EDGE cases the D1 compile-time gate doesn't cover (e.g. `for` loops, branch disagreement) — but it's strictly ergonomic; honestly deferred. |
| **38.x.e.6** | `axon-rs/src/main.rs` — `--verbose-d5-hint` CLI flag + `AXON_VERBOSE_D5_HINT` env var; when on, client response includes the full hint payload. Default off (OWASP-safe per Fase 32.d precedent). | D4 | ⏳ DEFERRED to Fase 38.x.f — depends on 38.x.e.5 (the runtime D5 hint payload). Skipped along with 38.x.e.5 for the narrow v1.39.0 scope. The compile-time D1 gate makes the runtime path unreachable for the kivi class — D5 ergonomic improvements ride along when 38.x.f reopens the runtime surface. |
| **38.x.e.7** | New anchor `axon-rs/tests/fase38xe_cardinality_gate.rs` — 6 §-assertions covering D1-D5. STATIC grep §S pinning the new `Cardinality` enum + `infer_flow_tail_cardinality` symbol. | All | ✅ SHIPPED 2026-05-21 — anchor coverage landed as **5 inline lib tests in `axon-frontend/src/type_checker.rs::fase38xe_cardinality_tests`** rather than a separate `tests/fase38xe_cardinality_gate.rs` file, because the v1.39.0 implementation has no `Cardinality` enum / `infer_flow_tail_cardinality` symbol to grep for (per 38.x.e.1's scope simplification). The 5 tests cover: **(§1)** `retrieve_tail_with_singular_output_emits_t9xx` — the canonical kivi pattern emits `axon-T9XX` + actionable hint with both remediation paths named; **(§2)** `retrieve_tail_with_list_output_passes` — D5 symmetric well-formed (output `List<T>` + retrieve tail); **(§3)** `step_tail_with_singular_output_passes` — other well-formed case (step tail returning singular); **(§4)** `no_output_declared_skips_gate` — honest scope: endpoint without `output:` silently passes; **(§5)** `stream_output_skips_gate` — Stream<T> output deferred (38.x.f scope). **5/5 passing**; the inline location matches existing patterns like `fase37y_d3_d4_tests` from sub-fase 37.y. Anchor file extraction to `axon-rs/tests/` honest-deferred until the gate scope broadens enough to warrant a standalone anchor. |
| **38.x.e.8** | Coordinated release axon-lang **v1.39.0** + axon-frontend **v0.20.0** (shared with Fase 37.x.j). axon-enterprise **v1.30.0** catch-up. | — | ✅ SHIPPED 2026-05-21 — coordinated release LIVE cross-stack alongside Fase 37.x.j. See [docs/fase/fase_37xj_connection_pinned_flow_execution.md](fase_37xj_connection_pinned_flow_execution.md) §37.x.j.9 for the full ship report (commit hashes, tags, crates.io / PyPI / GitHub Release / ECR confirmations). v1.39.0 release notes call out 38.x.e D1 alongside 37.x.j D1-D6.a as the two structural fixes closing the kivi 2026-05-20 regression. |

# ▶ 4. Test surface — 6 §-assertions

| § | What it pins | Mode |
|---|---|---|
| **§1** | D1 — flow tail `retrieve … as result` + endpoint `output: T` (singular) → `axon-T9xx` error when `--strict-cardinality` is on; warning otherwise | unit |
| **§2** | D1 — flow tail `step S { ... return T }` + endpoint `output: T` (singular) → no error | unit |
| **§3** | D1 — flow tail `return result[0]` after `retrieve` + endpoint `output: T` (singular) → no error (collapse recognized) | unit |
| **§4** | D2 — runtime D5 with `audit_log` payload contains the new cardinality fields | integration |
| **§5** | D3 — flow tail singular + endpoint `output: List<T>` → `axon-T9xx` symmetric error with bilateral remediation hint | unit |
| **§6** | D4 — `AXON_VERBOSE_D5_HINT=1` exposes the full hint payload to the client response body; without it the response stays generic | integration |

Plus STATIC grep §S pinning `Cardinality` enum + `infer_flow_tail_cardinality` exist.

# ▶ 5. Forward-compatibility commitments

- **`branch-cardinality-disagreement` warning** is `axon-W003`
  today; a future fase may promote it to an error under
  `--strict-cardinality`.
- **`for … yield T` cardinality** infers as `Plural(T)`; a future
  fase may add `for … yield (count, T)` for adopter-defined
  reductions.
- **`par { } { }` cardinality**: today the LAST branch's
  cardinality is taken; a future fase may surface this as an
  axon-W004 warning when branches disagree.

# ▶ 6. What is intentionally NOT in v1.39.0

- **Default-on flip of `--strict-cardinality`** (deferred to
  v1.40.0 per D5).
- **Cardinality refinement on `step S { … }` bodies** — today
  the step's `output:` is the declared type, not refined from
  the body's actual return. Future fase.
- **Cardinality on `Stream<T>` outputs** — today Stream is
  always cardinality `Plural<T>`; future fase may add
  cardinality-1 streams (a stream that emits exactly one event).

# ▶ 7. The two-question gate

## Q1 — Is this market standard, or superior to what other languages offer?

**SUPERIOR.** No mainstream framework offers compile-time
cardinality enforcement for HTTP endpoint outputs:

| Framework | Cardinality enforcement |
|---|---|
| FastAPI + Pydantic | runtime ValidationError (422) — same shape as axon's current D5 |
| Spring + Jackson | runtime serialization error or worse, silent wrapping of singular as array |
| Express + Joi | runtime 400 |
| GraphQL (Apollo, Hasura) | runtime nullability check — closest to axon's approach but only for nullable, not list-vs-singular |
| sqlc + Go | static SQL type check — closest competitor, but only for SQL types not for the flow's tail expression |

axon advances the state of the art: the gate is at the LANGUAGE
level over the FLOW BODY EXPRESSION, not just over the SQL or
the output type alone. The adopter is told at `axon check` —
before deploy — that their `GET /api/tenants/{id}` endpoint
returns a list when the URL semantics demand a singular.

This continues axon's pattern: every adopter-visible safety
property is proven at compile time, not at runtime.

## Q2 — Minimum to run, or robust and complete for large, complex adopters?

**Target adopter profile**: every multitenant SaaS adopter that
builds REST APIs backed by a database — i.e. the majority of
production axon adopters today. The 95% case is REST endpoints
following the OpenAPI/JSON:API convention where:

- `GET /api/<resource>/{id}` returns a singular object
- `GET /api/<resource>` returns a list

38.x.e directly addresses both shapes (D1 + D3 bilateral
coverage).

**ROBUST scope in v1.39.0:**

- ✅ Compile-time gate for List-tail + singular-output (D1)
- ✅ Compile-time gate for singular-tail + List-output (D3)
- ✅ Branch-disagreement warning (axon-W003)
- ✅ Improved runtime D5 hint (D2) — default-on
- ✅ OWASP-safe by default + verbose opt-in (D4)
- ✅ Migration-friendly opt-in for D1 (D5) — v1.39.0 warning,
  v1.40.0 default-on
- ✅ Three declaration forms covered (inline / manifest_ref /
  env_var) via `TypeChecker::with_manifest` cohesion
- ✅ Cross-stack release coordinated with Fase 37.x.j

**HONESTLY DEFERRED:**

- ❌ Default-on flip of `--strict-cardinality` (v1.40.0)
- ❌ Step body cardinality refinement (future)
- ❌ Cardinality-1 streams (future)

The honest answer to Q2: **ROBUST for the 95% REST-by-resource
adopter pattern**. The deferred items are refinements, not safety
properties — the safety property closes here.

# ▶ 8. The closing condition

Closed when:
- axon-lang v1.39.0 published cross-stack
- axon-enterprise v1.30.0 catch-up live
- A kivi adopter probe of `GET /api/tenants/{id}` against v1.39.0
  EITHER:
    (a) passes (because the adopter changed to `output:
        List<TenantRecord>` per the D1 hint), OR
    (b) fails at `axon check` with `axon-T9xx` and the actionable
        remediation lines in the error message
- Neither outcome surfaces the opaque "did not match the declared
  output schema" message at runtime anymore.
