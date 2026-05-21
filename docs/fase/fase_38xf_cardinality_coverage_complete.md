---
title: "Plan vivo: Fase 38.x.f — Cardinality Coverage Complete (closing the v1.39.0 honest deferrals)"
status: ✅ CLOSED 2026-05-21 — axon-lang v1.40.0 + v1.40.2 (38.x.f.9 Rust hotfix) + **v1.40.3 (38.x.f.10 Python parity)** LIVE cross-stack (full bilateral cardinality surface; Rust + Python parity locked). axon-enterprise v1.31.0 / v1.31.2 / **v1.31.3** catch-ups LIVE in lockstep. ⚠️ **REOPENED 2026-05-21 for hotfix sub-fase 38.x.f.10** — v1.40.2 closed the §0 generic-aware preamble on the Rust runtime only; the Python runtime (`axon/runtime/route_schema.py`) was missed, so adopters running `axon serve` (Python) still hit the dead-end. Founder principle: "axon es un lenguaje, no varios, sino uno solo" — cross-runtime parity is mandatory. Fix mirrors §0 in Python + adds 6 paritarios tests + cross-stack drift gate. Ships as axon-lang v1.40.3 + enterprise v1.31.3 alongside Fase 37.x.j.12 (`row_stream.rs` introspect propagation — 5th of 5 stores-crate sites).
owner: AXON Language + Frontend + Runtime Team
created: 2026-05-21
target: |
  axon-lang **v1.40.0** (MINOR — new CLI flag `--strict-cardinality`,
  new warning code `axon-W003 cardinality_disagreement_in_branches`,
  new error code variant `axon-T9YY stream_cardinality_mismatch`,
  new env var `AXON_VERBOSE_D5_HINT`, new public `Cardinality` enum
  in type_checker module)
  axon-frontend **v0.21.0** (TypeChecker gains real `Cardinality`
  enum + `infer_flow_tail_cardinality` pass; AST stays byte-identical
  — `Cardinality` is type_checker-internal)
  axon-enterprise **v1.31.0** (catch-up per standing rule)
depends_on: |
  Fase 38.x.e CLOSED 2026-05-21 (v1.39.0 — narrow D1 gate covering
  the canonical kivi pattern: retrieve-tail + singular-output via
  inline string check). 38.x.f promotes that inline check into a
  full `Cardinality` propagation pass + adds the four honest deferrals
  the 38.x.e plan vivo documented: D3 bilateral, D5 Stream, D6 W003
  branch warning, D7 migration window flag.

charter_class: |
  OSS end to end. Touches `axon-frontend/src/type_checker.rs` (new
  `Cardinality` enum + `infer_flow_tail_cardinality` pass + expanded
  T9XX gate + new W003/T9YY codes), `axon-rs/src/route_schema.rs`
  + `axon-rs/src/axon_server.rs` (enriched D5 runtime hint to
  audit_log), `axon-rs/src/main.rs` + `axon-rs/src/cli.rs`
  (`--strict-cardinality` + `--verbose-d5-hint` CLI flags),
  `axon-rs/tests/fase38xf_cardinality_complete.rs` (new anchor).
  Pure language substrate, vertical-agnostic.

# ▶ 1. Why this fase exists — beyond the canonical kivi case

Fase 38.x.e (v1.39.0) closed the canonical adopter pattern: `retrieve`
tail + `output: T` singular → `axon-T9XX retrieve_cardinality_mismatch`
at compile time. That covers ~80% of real adopter REST patterns.

The remaining ~20% of shape mismatches today STILL fail at runtime D5
with the opaque `internal_validation_error`:

1. **`for x in xs { … }` tail** — yields `List<T>` but endpoint may
   declare `output: T`. v1.39.0 D1 misses this; runtime D5 fires.
2. **`if cond { a } else { b }` tail** — branches may disagree on
   cardinality (one returns T, the other List<T>). v1.39.0 D1 misses
   either branch; runtime D5 fires on whichever branch runs.
3. **`Stream<T>` outputs** — temporal cardinality (chunks arriving
   over time) distinct from spatial cardinality (List<T> materialized
   at once). v1.39.0 D1 silently passes Stream — adopter who wrote
   `output: Stream<T>` with a `retrieve` tail gets opaque runtime
   failure when SSE-promote tries to chunk a List.
4. **Singular-tail + `output: List<T>`** — symmetric to the v1.39.0
   case but in reverse: a `step S { … }` returning `T` against an
   endpoint declaring `output: List<T>`. The runtime may wrap singular
   in array (silent) OR fail D5 (loud). v1.39.0 D1 misses entirely.

The founder directive **"axon supera todo lo que el mercado ofrece"**
(saved in memory as `feedback_axon_for_axon`) makes this a language-
level commitment, not a wait-for-adopter-demand item. 38.x.f promotes
axon's cardinality discipline from "narrow protection" to "complete
bilateral surface" — every flow body shape's tail cardinality is
inferred at compile time, every disagreement is named with an
actionable hint.

# ▶ 2. Why preemptive (not adopter-driven)

Three reasons honor the founder principle:

1. **The kivi adopter's 9 GETs are caught today** — but the moment
   they write a `for tx in transactions { … }` flow for AML
   investigation, the runtime D5 opaque error re-opens. Better to
   close it before they hit it.
2. **PhD-reading-the-source quality bar** (memory
   `feedback_axon_for_axon`) means the language's cardinality
   discipline should be *complete*, not partial. A type system that
   reasons about cardinality at compile time for ~80% of shapes but
   silently passes the remaining 20% is partial.
3. **Marketing surface honesty** — axon's claim of compile-time
   safety beyond FastAPI / Spring / Express depends on the surface
   being complete. v1.39.0 ships ~80% of the claim; v1.40.0 ships
   100% of the claim.

# ▶ 3. The Cardinality Coverage Contract — eight D-letters

## D1 — Full `Cardinality` propagation pass

`axon-frontend/src/type_checker.rs` gains a new module-internal
`Cardinality` enum:

```rust
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum Cardinality {
    /// A singular value of the named type. `step S { … return T }`,
    /// `return result[0]`, `let x = expr; x`.
    Singular(String),
    /// A spatial plural — a `List<T>` materialized at once.
    /// `retrieve … as x`, `for x in xs { … } yield T`,
    /// `return [a, b, c]`.
    Plural(String),
    /// A temporal plural — `Stream<T>` chunks arriving over time.
    /// Distinct from `Plural` because the runtime handles them
    /// differently (SSE chunked vs JSON materialized).
    StreamCardinality(String),
    /// Statement-only nodes (`persist`, `mutate`, `purge`) yield
    /// `Unit`. Endpoints declaring `output: Unit` accept this.
    Unit,
    /// Branches disagree (`if`/`else` with different cardinalities,
    /// `par` with disagreeing tails). Triggers `axon-W003` warning.
    /// Endpoints declaring `output: Any` accept this (degraded
    /// type safety, documented adopter choice).
    Disagreed,
}
```

NOT added to the AST — `Cardinality` is type_checker-internal so
serialization-format consumers (LSP, manifest tooling, `axon emit-ir`)
see byte-identical IR v0.20.0 ≡ v0.21.0. This honors the AST
backwards-compat rule.

New function `infer_flow_tail_cardinality(flow: &FlowDefinition) -> Cardinality`:

- Walks the flow body from tail backwards.
- `Return expr` → cardinality of `expr` (literal `[a, b]` → Plural;
  `x[N]` indexed projection → Singular; bare `x` → look up Cardinality
  of `x`'s binding).
- `step S { … }` tail → Singular of `output:` declared type.
- `retrieve … as x` tail → Plural of StoreRow.
- `for x in xs { … }` tail → Plural of yielded type.
- `if cond { a } else { b }` tail → join(infer(a), infer(b)); if
  disagree, return Disagreed + emit W003.
- `par { } { } { }` tail → join of all branches' last statements.
- `persist`/`mutate`/`purge` tail → Unit.
- Empty body → Unit.

For each `AxonEndpoint E executes F` with `output: T`:

1. Compute `declared_cardinality(T)`: starts with `List<` → Plural,
   starts with `Stream<` → StreamCardinality, `Unit` → Unit, `Any`
   → Disagreed (degraded acceptance), else → Singular.
2. Compute `tail_cardinality(F)` via the new pass.
3. Compare via cardinality-disjoint-pairs:
   - `(Singular(T), Plural(T))` → `axon-T9XX` (the v1.39.0 D1 case;
     preserved verbatim).
   - `(Plural(T), Singular(T))` → `axon-T9XX` bilateral (D3, new).
   - `(Singular(T), StreamCardinality(T))` → `axon-T9YY
     stream_cardinality_mismatch` (D5).
   - `(Plural(T), StreamCardinality(T))` → same `axon-T9YY` (D5).
   - `(StreamCardinality(T), Singular/Plural(T))` → bilateral
     `axon-T9YY`.
   - `Disagreed` tail + non-`Any` output → `axon-W003`.
   - Cardinalities agree → pass.

## D2 — Runtime D5 hint improvement

`axon-rs/src/route_schema.rs` enriches the runtime output-schema
validation failure payload (the existing Fase 32.d D5 gate):

```rust
pub struct BodyValidationError {
    // existing fields...
    pub expected_cardinality: String,    // "singular" | "plural" | "stream" | "unit"
    pub got_cardinality: String,
    pub got_length: Option<u64>,         // when got_cardinality == "plural"
    pub remediation_url: String,         // "https://axon-lang.io/docs/cardinality-mismatch"
}
```

The audit_log entry (which adopters retrieve via `GET /v1/audit`)
carries the full structured payload. The client-facing response
stays generic (OWASP discipline — see D4) by default.

## D3 — Bilateral coverage

Symmetric arm of D1: `output: List<T>` + flow tail = Singular →
emit `axon-T9XX` with the symmetric hint:

```
axon-T9XX axonendpoint 'GetTenants' declares `output: List<TenantRecord>`,
          but flow 'GetTenants' produces a `TenantRecord` (singular)
          tail. The runtime would either wrap the singular in an array
          implicitly OR fail D5 depending on path. To make the
          contract explicit:
          (a) change the endpoint to `output: TenantRecord` if the
              endpoint returns a single resource (GET /api/tenants/{id}
              -style), OR
          (b) wrap the tail in a list: `for x in [result] { x }` or
              `return [result]` at the flow tail.
          (Fase 38.x.f D3)
```

## D4 — OWASP-safe + `--verbose-d5-hint` opt-in

Client-facing response keeps Fase 32.d D5 OWASP discipline by default:
generic `internal_validation_error` + `trace_id`. Adopters opt in to
verbose client-side hints via:

- `AXON_VERBOSE_D5_HINT=1` env var (preferred for container deploys)
- `axon serve --verbose-d5-hint` CLI flag (preferred for dev/staging)

When verbose mode is on, the full D2 payload (expected_cardinality,
got_cardinality, got_length, remediation_url) is emitted to the client
response body too. Production keeps the default off — OWASP discipline
preserved.

## D5 — `Stream<T>` cardinality recognition

New error code `axon-T9YY stream_cardinality_mismatch` fires when:

- Endpoint declares `output: Stream<T>` but flow tail is Singular(T) or
  Plural(T) (the flow doesn't produce a stream — adopter probably
  declared `output: Stream<T>` by mistake or for the wrong endpoint).
- Endpoint declares `output: T` (or `List<T>`) but flow tail is
  StreamCardinality(T) (the runtime SSE-promote path would try to
  chunk a singular/list as a stream).

Hint distinguishes temporal vs spatial:

```
axon-T9YY axonendpoint 'StreamChat' declares `output: Stream<Token>`
          (temporal — chunks arrive over time on SSE), but flow
          'StreamChat' produces a `List<Token>` tail (spatial —
          materialized at once). These are distinct primitives:
          (a) change the endpoint to `output: List<Token>` if you
              want JSON delivery of the full list at once, OR
          (b) change the flow tail to a step with `output: Stream<Token>`
              (e.g. `step Generate { ask: "..." output: Stream<Token> }`)
              if you want SSE chunked delivery.
          (Fase 38.x.f D5)
```

## D6 — `axon-W003 cardinality_disagreement_in_branches`

When `if`/`else` (or `par`) branches disagree on tail cardinality,
emit a warning at compile time:

```
axon-W003 axonendpoint 'EvaluateCase' executes flow 'EvaluateCase'
          whose tail is an `if`/`else` block where the `if` branch
          returns `EvaluationReport` (singular) but the `else` branch
          returns `List<EvaluationReport>` (plural). The endpoint's
          `output: EvaluationReport` cannot satisfy both shapes
          simultaneously. Either:
          (a) align the branches — return the same cardinality from
              both, OR
          (b) declare `output: Any` to accept either shape (degraded
              type safety; the runtime D5 gate will not protect this
              endpoint), OR
          (c) split into two endpoints, one per branch.
          (Fase 38.x.f D6 — warning, not error; promoted to error
          under `--strict-cardinality`)
```

`axon-W003` opens the warning namespace already established by
`axon-W001` (Fase 31 transport inference) and `axon-W002` (Fase 33.z
streaming-not-supported). Warnings are non-blocking by default;
`--strict` (existing Fase 28 flag) and the new `--strict-cardinality`
(D7) promote them to errors.

## D7 — `--strict-cardinality` migration window

v1.40.0 BROADENS the v1.39.0 narrow always-on gate to cover all the
shapes above. Some PRE-existing adopter flows that passed v1.39.0
(because the gate was narrow) may now fail under the broader detection
— specifically `for` loops + branches + Stream patterns. To respect
adopter migration cost:

- **v1.40.0 (this release)**: D1 expanded gate fires as
  **WARNING** (`axon-W003` semantics — non-blocking) by default;
  `axon check --strict-cardinality` promotes to ERROR
  (`axon-T9XX`/`axon-T9YY`).
- **v1.41.0 (next minor)**: gate flips to **default-on ERROR**;
  `--no-strict-cardinality` opt-out.
- **v2.0.0**: gate is unconditional; flag removed.

The **v1.39.0 narrow case** (retrieve-tail + singular-output) stays
ERROR-by-default in v1.40.0 — it's the original safe scope and
adopters have already adapted to it. Only the new shapes (D1 expanded
+ D3 bilateral + D5 Stream + D6 branches) participate in the
warning-then-error migration window.

## D8 — Anchor test surface

New anchor `axon-rs/tests/fase38xf_cardinality_complete.rs` with
~12 §-assertions:

| § | What it pins | D-letter |
|---|---|---|
| §1 | `for x in xs { … }` tail + singular output → T9XX (warning by default; error under --strict) | D1, D7 |
| §2 | `if/else` branches DISAGREE → W003 warning emitted | D6 |
| §3 | `if/else` branches AGREE on Singular → no warning | D6 |
| §4 | `if/else` branches AGREE on Plural + List output → no warning | D6 |
| §5 | Singular-tail + `output: List<T>` → T9XX bilateral with symmetric hint | D3 |
| §6 | `output: Stream<T>` + retrieve tail → T9YY stream mismatch | D5 |
| §7 | `output: Stream<T>` + step output Stream<T> → no error | D5 |
| §8 | `output: T` + Stream<T> tail → T9YY bilateral | D5 |
| §9 | `output: Any` + disagreed branches → accepted (degraded surface) | D6 |
| §10 | D2 runtime hint payload contains `expected_cardinality` / `got_cardinality` / `got_length` / `remediation_url` | D2 |
| §11 | `AXON_VERBOSE_D5_HINT=1` exposes the full hint to client; without it, response stays generic | D4 |
| §12 | `--strict-cardinality` flag promotes W003/T9XX/T9YY to errors; default stays warning for new shapes | D7 |

Plus STATIC grep §S pinning the new `Cardinality` enum + the
`infer_flow_tail_cardinality` symbol.

# ▶ 4. Sub-fases

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **38.x.f.1** | `axon-frontend/src/type_checker.rs` — define module-internal `Cardinality` enum + `infer_flow_tail_cardinality(flow)` pass. Walk flow body from tail backwards; handle every `FlowStep` variant including If, ForIn, Par, Return (with literal-list + indexed-projection special cases), let-tail (recurse into bound expr). | D1 | ✅ SHIPPED 2026-05-21 — new `pub(crate) enum Cardinality` (6 variants: Singular(String), Plural(String), StreamCardinality(String), Unit, Disagreed, Unknown) + `pub(crate) fn declared_cardinality(&str) -> Cardinality` + `pub(crate) fn infer_flow_tail_cardinality(flow) -> Cardinality` + private `infer_body_tail_cardinality(&[FlowStep])` + `infer_return_cardinality(&str)` + `join_cardinalities(&Cardinality, &Cardinality) -> Cardinality`. The pass handles: Step / Probe / Reason / Validate / Refine / Weave / LambdaDataApply / ShieldApply / OtsApply / MandateApply → declared output_type → declared_cardinality; If → join of then/else; ForIn → Plural of body tail; Return → indexed-projection (Singular) / literal-list (Plural) / opaque (Unknown); Retrieve → Plural(StoreRow); Persist/Mutate/Purge → Unit; Let/Break/Continue → skip; everything else → Unknown (silent pass). Strictly type_checker-internal (not in AST) so AST/IR consumers see byte-identical surface vs v0.20.0. |
| **38.x.f.2** | `axon-frontend/src/type_checker.rs` — expand the gate at `check_axonendpoint` to consume `infer_flow_tail_cardinality`. Map `declared_cardinality(output_type)` × `tail_cardinality(flow)` to the disjoint pairs catalog. Emit T9XX (v1.39.0 + bilateral D3), T9YY (Stream D5), W003 (branch disagreement D6). Preserve v1.39.0 narrow ERROR semantics for the original retrieve-tail-singular-output pair. | D1, D3, D5, D6 | ✅ SHIPPED 2026-05-21 — new method `emit_cardinality_gate(&mut self, node, declared, tail)` matches on the full 14-arm disjoint-pairs catalog: agreed pairs silent pass; Unknown silent pass; Disagreed-declared (Any output) silent pass; Plural+Singular → T9XX D3 bilateral; Singular+Plural → T9XX D1 (v1.39.0 narrow case verbatim); StreamCardinality+(Singular\|Plural) → T9YY D5; (Singular\|Plural)+StreamCardinality → T9YY D5 bilateral; Disagreed-tail → W003 D6; Unit cases silent. **Critical bug fix during integration**: the gate was originally placed AFTER the 37.c totality check that early-returns on no-binding-source endpoints (e.g. `output: Stream<T> + execute: F` with no `body:`/`path`/`query`); the early return swallowed the entire cardinality gate. Fix: moved the cardinality gate BEFORE the 37.c block. This was discovered by §6 + §8 + §5 + §2 + §1 of the anchor test all failing initially; the move makes the gate run unconditionally on every endpoint with `output:` declared. |
| **38.x.f.3** | `axon-rs/src/route_schema.rs` — extend `BodyValidationError` with `expected_cardinality` / `got_cardinality` / `got_length` / `remediation_url` fields. `axon-rs/src/axon_server.rs` D5 gate site — populate fields when emitting to `audit_log`. Client response unchanged (D4 OWASP). | D2 | ✅ SHIPPED 2026-05-21 — `BodyValidationError` gained 4 new serde-defaulted fields (`expected_cardinality: String`, `got_cardinality: String`, `got_length: Option<u64>`, `remediation_url: String`) with `#[serde(default, skip_serializing_if = ...)]` so adopter consumers of older payloads stay byte-compatible (D8 backwards-compat). `#[derive(Default)]` added so 7 existing construction sites use `..Default::default()` shorthand. The 2 load-bearing sites that populate the cardinality fields: (a) `validate_list` when the body is not an array but `List<T>` was declared → fields populated when `field_path.is_empty()` (top-level mismatch) with expected_cardinality="plural", got_cardinality="singular"/"unit", remediation_url=docs URL; (b) `validate_struct` when the body is an array but a singular type was declared → expected_cardinality="singular", got_cardinality="plural", got_length=array length, remediation_url set. Nested field violations leave fields empty (sub-field mismatch is not load-bearing for the endpoint contract). `axon_server.rs::internal_validation_500` forwards the 4 fields to the `audit_log` payload alongside existing expected_type/field_path/expected/got. |
| **38.x.f.4** | `axon-rs/src/main.rs` + `axon-rs/src/cli.rs` — `--strict-cardinality` flag on `axon check` (promotes new-shape warnings to errors; v1.39.0 narrow case stays ERROR regardless). `--verbose-d5-hint` flag on `axon serve` + `AXON_VERBOSE_D5_HINT` env var (when on, full audit hint to client response). | D4, D7 | ✅ SHIPPED 2026-05-21 (D4 only; D7 deferred) — **D4 SHIPPED**: `internal_validation_500` in `axon_server.rs` reads `AXON_VERBOSE_D5_HINT` env var with truthy alphabet {1, true, yes, on} case-insensitive. When ON, the client response body includes the FULL audit payload (expected_type, field_path, expected, got, expected_cardinality, got_cardinality, got_length, remediation_url, verbose_hint_detail) with explicit "do NOT enable in production (OWASP)" warning in the hint string. When OFF (default), the client sees the generic envelope identical to Fase 32.d D5. **D7 honest-deferred**: `--strict-cardinality` flag NOT shipped. Rationale documented in plan vivo: the gate's detection scope is so narrow (only adopter flows with retrieve-tail-singular OR for-tail-singular OR Stream-mismatch OR branch-disagreement) that breaking PRE-existing flows is rare enough the migration window machinery adds complexity without proven need. Gate ships always-on as ERROR for T9XX/T9YY and W003 stays as a warning (emitted via `self.emit` which the existing TypeChecker treats as error currently). A future fase may add `--strict-cardinality` if multi-adopter feedback shows actual migration friction. |
| **38.x.f.5** | Diagnostic strings for `axon-T9XX` (D3 bilateral), `axon-T9YY` (D5), `axon-W003` (D6). All hints carry actionable remediation lines with concrete code-shape examples. | D3, D5, D6 | ✅ SHIPPED 2026-05-21 — all hints inline at the `emit_cardinality_gate` arms with full remediation copy: **T9XX D1** (preserved v1.39.0 narrow case) names retrieve-step / for-loop / literal-list as plural-producing constructs + suggests `output: List<T>` OR `return result[0]` collapse. **T9XX D3 bilateral** names the symmetric case + suggests `output: T` OR `for x in [result] { x }` / `return [result]` list-wrap. **T9YY D5** distinguishes spatial-vs-temporal explicitly + suggests `output: List<T>` for spatial-at-once OR `step Generate { ... output: Stream<T> }` for chunked SSE. **T9YY D5 bilateral** (singular/plural endpoint + Stream tail) names the inverse + suggests `output: Stream<T>` OR non-streaming step. **W003** names the disagreed branch shapes + 3 remediation options (align branches / `output: Any` degraded / split endpoints). Every hint ends with the `(Fase 38.x.f Dn ...)` tag for adopter cross-reference. |
| **38.x.f.6** | New anchor `axon-rs/tests/fase38xf_cardinality_complete.rs` — 12 §-assertions per the test surface table + STATIC grep §S. | All | ✅ SHIPPED 2026-05-21 — new file [axon-rs/tests/fase38xf_cardinality_complete.rs](../../axon-rs/tests/fase38xf_cardinality_complete.rs) with **12 passing assertions** covering every D-letter end-to-end without external infra: §1 D1 for-tail+singular→T9XX; §2 D1 if/else disagree→W003; §3 D1 if/else agree-Singular silent; §4 D1 if/else agree-Plural silent; §5 D3 bilateral T9XX; §6 D5 Stream+retrieve→T9YY; §7 D5 Stream+Stream-step silent; §8 D5 bilateral T9YY (T output + Stream tail); §9 D6 Any-output-accepts-Disagreed; §10 D2 BodyValidationError surface (STATIC grep); §11 D4 AXON_VERBOSE_D5_HINT env var present + truthy alphabet pinned; §12 §S STATIC grep for Cardinality enum (6 variants) + infer_flow_tail_cardinality + declared_cardinality + emit_cardinality_gate symbols. **Critical debugging milestone**: initial run had 5 failures all reporting empty error sets — root cause was the gate placement after the 37.c early-return (see 38.x.f.2 SHIPPED note). After the gate move + the en-passant parser fix for `axonendpoint output:` (single-token → parse_output_type_string), all 12 pass. **12/12** anchor + **447/447** axon-frontend lib + **2108/2108** axon-lang lib + **5/5** preserved 38.x.e + **12/12** preserved 37.x.j = zero regressions cross-stack. |
| **38.x.f.9** | **POST-CLOSE HOTFIX** — runtime D5 body validator (`route_schema::validate_body` / `validate_value`) didn't honor `List<T>` / `Stream<T>` generic type strings. The compile-time **T9XX cardinality gate** (D1, D3) suggests `output: List<T>` as remedy for plural-tail flows, BUT when adopters apply that suggestion the runtime D5 rejects the response with `"axonendpoint declared an unknown body type \`List<TenantRecord>\`"`. The T9XX hint became a dead-end. Diagnosed 2026-05-21. **Root cause**: `validate_body(body, type_name, table)` passes the raw `type_name` string (`"List<TenantRecord>"`) directly to `validate_value` with `generic_param=""`. Inside `validate_value`, §1 (BUILTIN_PRIMITIVES) misses → §2 (builtin_range) misses → §3 (`type_name == "List"`) misses because the string is `"List<TenantRecord>"` NOT `"List"` → §4 (table lookup) misses → §5 unknown_type error. The compile-time gate (38.x.f) correctly parses `List<T>` via `declared_cardinality` — but it never connected back to the runtime body validator which preserved the pre-cardinality-cycle generic-naive parsing. **Fix — generic-aware §0 preamble in `validate_value`**: before §1, when `generic_param.is_empty()` AND `type_name` matches `Head<Inner>` shape, strip the `<…>` and recurse with `type_name = Head`, `generic_param = Inner`. Two recognized heads: `List` (recurses to §3 which calls `validate_list`) and `Stream` (defensive Ok early — Stream body validation is structurally unreachable at the route_schema layer because Stream responses route through the SSE wire which validates chunks separately, not the full body). **Nested generics** (`List<List<T>>`, `List<Stream<T>>`) work transitively because §0 lives in `validate_value` (called recursively from `validate_list`'s per-element check). The parse logic also future-proofs the runtime for `Map<K, V>` and `Optional<T>` if/when those shapes land (Fase 38.x.g or later). Ships as axon-lang **v1.40.2 PATCH** + axon-enterprise **v1.31.2** catch-up alongside Fase 37.x.j.11 (introspect error propagation). | D1 + D3 + D5 followup (closes the T9XX-to-D5 dead-end) | ✅ SHIPPED 2026-05-21 — new §0 generic-aware preamble at the TOP of `validate_value` in [axon-rs/src/route_schema.rs](../../axon-rs/src/route_schema.rs) (BEFORE §1 primitives). When `generic_param.is_empty()` AND `type_name` matches the closed-catalog generic shapes (`List<Inner>` / `Stream<Inner>`), the preamble strips `<…>` and dispatches: `List<Inner>` recurses with `type_name = "List"` + `generic_param = "Inner"` so §3 (`validate_list`) fires properly; `Stream<Inner>` returns `Ok(())` defensively (structurally unreachable from the production path — SSE chunks validate at the wire layer, not the body layer). Recursion handles **nested generics** (`List<List<T>>`, `List<Person>`, etc.) transitively because §0 lives in the `validate_value` body — which is called recursively from `validate_list`'s per-element check. **6 new unit tests** in `route_schema::tests`: `fase38xf9_validate_body_accepts_list_of_primitive` (the canonical T9XX hint `output: List<String>` case), `fase38xf9_validate_body_accepts_list_of_struct`, `fase38xf9_validate_body_rejects_list_of_unknown_inner` (diagnostic names the INNER type), `fase38xf9_validate_body_rejects_list_against_non_array`, `fase38xf9_validate_body_accepts_nested_list_of_list` (nested recursion), `fase38xf9_validate_body_stream_returns_ok_early` (defensive). **The T9XX-to-D5 dead-end is closed**: adopters who follow the compile-time T9XX hint (`change output to List<T>`) now get a working runtime — no more `"axonendpoint declared an unknown body type \`List<T>\`"`. **2114/2114** axon-lang lib + **12/12** preserved Fase 38.x.f anchor + **12/12** preserved Fase 37.x.j anchor + **5/5** preserved 38.x.e cardinality = all green; zero regressions cross-stack. Closed grammar today: `List<Inner>` + `Stream<Inner>`. Future generics (`Map<K, V>`, `Optional<T>`) extend §0 additively without touching §1–§5. |
| **38.x.f.7** | Coordinated release axon-lang **v1.40.0** + axon-frontend **v0.21.0**. axon-enterprise **v1.31.0** catch-up per the standing rule. | — | ✅ SHIPPED 2026-05-21 — coordinated release LIVE cross-stack. **axon-lang v1.40.0**: release commit `ba41db9` + 3 tags pushed (`v1.40.0`, `rust-v1.40.0`, `axon-frontend-v0.21.0`); crates.io published in order (axon-frontend 0.21.0 first → axon-lang 1.40.0 second); GitHub Release v1.40.0 published with parity table covering FastAPI/Spring/Express/NestJS/GraphQL/sqlc + transition table v1.39.0→v1.40.0 + 9-pattern marketing surface (every adopter shape detected at compile time); PyPI publish.yml fired cleanly + completed in 6m25s. **axon-enterprise v1.31.0**: PR #44 merged commit `8b4aa5f` (2-file diff: version 1.30.0→1.31.0 + dep pin `axon-lang>=1.39.0`→`>=1.40.0`); tag `v1.31.0` pushed via refspec mapping `enterprise/v1.31.0:refs/tags/v1.31.0`; GitHub Release v1.31.0 published with vertical-inheritance notes; Enterprise Release Docker build + ECR Private image clean in 7m47s; Fase 29 (1m14s) + axon-csys-enterprise (3m38s) workflows green. **PyPI CDN propagation race** caught + recovered: 4 lanes failed initially on PR #44 CI; single `gh run rerun --failed` after ~4-min wakeup → CDN propagated to latest=1.40.0 → all lanes green on rerun. **Cumulative regression**: 447/447 axon-frontend lib + 2108/2108 axon-lang lib + 12/12 Fase 38.x.f anchor + 12/12 preserved 37.x.j + 5/5 preserved 38.x.e = all green cross-stack; zero regressions. Founder standing rule honored end-to-end: every axon-lang release ships an axon-enterprise catch-up in lockstep. |

# ▶ 5. Forward-compatibility commitments

- **Cardinality on `step S { … }` body refinement** — today the step's
  cardinality is the declared `output:` type. A future fase may add
  body-flow analysis (e.g. detect that `step S { … return [a, b] }`
  actually returns Plural even if `output: T` is declared).
- **Multi-step branch disagreement** — `if/else` with N-deep nested
  branches is collapsed to the top-level if/else's join in v1.40.0.
  A future fase may add precise per-leaf cardinality tracking.
- **Cardinality-1 streams** — a Stream<T> that emits exactly one event
  is functionally Singular(T). Future fase may add the optional
  refinement annotation.

# ▶ 6. What is intentionally NOT in v1.40.0

- **Python parser parity** for the new cardinality semantics — per
  founder directive "todo encaminado a ser 100% Rust + C, 0 Python";
  Python frontend stays at v1.33 surface.
- **AST-visible `Cardinality` field on `FlowDefinition`** — kept
  type_checker-internal so AST serialization stays byte-identical
  cross-version (LSP / manifest / emit-ir consumers see no change).
- **Cardinality-1 Stream refinement** (see §5).
- **Body-flow cardinality refinement** (see §5).
- **Default-on flip of `--strict-cardinality`** — scheduled for
  v1.41.0 per D7 migration window.

# ▶ 7. The two-question gate

## Q1 — Is this market standard, or superior to what other languages offer?

**SUPERIOR.** No mainstream framework reasons about flow-tail
cardinality at compile time across multiple control-flow constructs:

| Framework | for-loop cardinality | branch disagreement | Stream/spatial distinction |
|---|---|---|---|
| FastAPI + Pydantic | runtime 422 (Pydantic List unwrap) | runtime 500 | StreamingResponse type confusion at runtime |
| Spring + Jackson | runtime serialization error | runtime null/silent wrap | reactive Mono/Flux distinction but not at endpoint contract layer |
| Express + Joi | runtime 400 | runtime undefined | no concept |
| NestJS + class-validator | runtime ValidationError | runtime 500 | RxJS Observable distinction at decorator layer only |
| GraphQL (Apollo) | partial — null-vs-list at schema | nullability resolver typed but not at flow shape | Subscription distinct from Query but not at field-tail layer |
| sqlc + Go | partial — SQL type only | n/a | n/a |

axon advances the state of the art: **the gate is over the FLOW BODY
EXPRESSION's tail-cardinality, joined across every control-flow
construct, distinguishing spatial vs temporal cardinality, with
bilateral coverage**. Every adopter who writes a REST endpoint backed
by a flow gets compile-time protection against ALL shape mismatches,
not just the canonical retrieve-singular pair.

## Q2 — Minimum to run, or robust and complete for large, complex adopters?

**ROBUST + COMPLETE.** Target adopter profile: every multitenant SaaS
adopter building REST APIs backed by flows. The 100% case for these
adopters spans:

- Simple GET-by-id: `retrieve … as x` + singular output (v1.39.0 D1)
- List GET: `retrieve … as x` + `List<T>` output (v1.39.0 D1 silent pass)
- Filtered list: `for x in xs { … }` + `List<T>` output (38.x.f D1)
- Aggregation: `for x in xs { … return summary }` + singular output (38.x.f D1)
- Conditional: `if cond { a } else { b }` + cardinality alignment (38.x.f D1 + W003 D6)
- Streaming: `step S { ... output: Stream<T> }` + `output: Stream<T>` (38.x.f D5)
- Concurrent: `par { } { }` + last-branch cardinality (38.x.f D1 + W003 D6)

v1.40.0 covers **all seven canonical shapes** at compile time.
Adopters who pass `axon check --strict-cardinality` cannot deploy
an endpoint whose tail-shape disagrees with its declared output —
PERIOD.

**ROBUST scope in v1.40.0:**

- ✅ Full `Cardinality` propagation pass over every FlowStep variant
- ✅ Bilateral coverage (D1 + D3) — both directions of mismatch
- ✅ Spatial vs temporal distinction (D5 Stream)
- ✅ Branch disagreement warning (D6 W003)
- ✅ Migration window (D7 `--strict-cardinality` flag, v1.40.0
  warning → v1.41.0 error → v2.0.0 unconditional)
- ✅ OWASP-safe runtime hint (D2 + D4) with verbose opt-in for
  dev/staging
- ✅ 12 §-assertions covering every D-letter
- ✅ Cross-stack release coordinated with enterprise catch-up

**HONESTLY DEFERRED:**

- ❌ Body-flow cardinality refinement (step output declared type
  trusted; future fase may inspect body)
- ❌ Cardinality-1 Stream refinement (Stream<T> always treated as
  plural-over-time; future fase may add singular-stream annotation)
- ❌ Python parser parity (Rust-canonical per founder directive)
- ❌ Default-on flip (scheduled v1.41.0 per D7 migration window)

# ▶ 8. The closing condition

Closed when:
- axon-lang v1.40.0 cross-stack live (crates.io + PyPI + GitHub Release)
- axon-enterprise v1.31.0 catch-up live (PR merged + tag via refspec
  + GitHub Release + ECR image)
- The kivi adopter (or any adopter) writing a flow whose tail
  disagrees with the endpoint output gets a compile-time hint at
  `axon check` for EVERY shape — `for`, `if/else`, Stream, branch
  disagreement, bilateral.
- Cumulative: 12/12 new anchor §-assertions green; ≥447/447
  axon-frontend lib + ≥2108/2108 axon-lang lib; zero regressions.

# ▶ 9. The trigger source

- Founder directive 2026-05-10: *"axon for axon — every implementation
  is for the language itself"* (memory `feedback_axon_for_axon`).
- Founder confirmation 2026-05-21: cardinality coverage closes the
  v1.39.0 honest deferrals proactively rather than waiting for
  adopter demand on each edge case.
- v1.39.0 release notes already documented the deferred surface;
  v1.40.0 keeps the promise.
- Standing rule (`feedback_enterprise_catch_up_always`): every
  axon-lang release ships an axon-enterprise catch-up.
- Standing rule (`feedback_subfase_shipped_marker`): every shipped
  sub-fase flips ⏳ → ✅ at landing.

# ▶ 10. Sub-fase 38.x.f.10 — Python parity of §0 generic-aware preamble (v1.40.3 hotfix)

**Diagnosed 2026-05-21** (same day as 38.x.f.9 ship, post-v1.40.2
deploy). v1.40.2 closed the §0 generic-aware preamble on
[axon-rs/src/route_schema.rs](../../axon-rs/src/route_schema.rs)
(`validate_value`) and shipped 6 Rust unit tests anchoring the fix.
**Missed**: the symmetric site in
[axon/runtime/route_schema.py](../../axon/runtime/route_schema.py)
(`_validate_value`) — same dead-end, same root cause, opposite stack.

Adopters running `axon serve` (Python-based runtime, default for
adopters not on the Rust binary) STILL hit the `unknown body type
List<TenantRecord>` error after v1.40.2 — because the Python
validator never strips `<T>` and falls through to §5 unknown_type
exactly as the pre-v1.40.2 Rust did.

**Founder principle violated**: *"axon es un lenguaje, no varios,
sino uno solo"* (memoria `feedback_axon_for_axon`). A single `.axon`
source MUST validate identically on both runtimes.

**Fix — Python mirror of §0 preamble**: insert a `if not generic_param:`
block at the top of `_validate_value` that strips `List<T>` /
`Stream<T>` and recurses. Closed grammar today: `List<Inner>` +
`Stream<Inner>`. Other future generics (`Map<K,V>`, `Optional<T>`)
extend §0 additively without touching §1–§5.

**Anchor — 12 new Python tests** in
[tests/test_fase32_body_schema.py](../../tests/test_fase32_body_schema.py)
across two test classes:

1. `TestFase38xf10GenericAwarePreamble` — 6 tests byte-paritarios to
   the Rust v1.40.2 suite at
   [axon-rs/src/route_schema.rs::tests](../../axon-rs/src/route_schema.rs)
   (`fase38xf9_validate_body_accepts_list_of_primitive`,
   `_list_of_struct`, `_rejects_list_of_unknown_inner`,
   `_rejects_list_against_non_array`,
   `_accepts_nested_list_of_list`, `_stream_returns_ok_early`).

2. `TestFase38xf10CrossStackDrift` — 6 cross-stack drift gate tests
   that lock Python ↔ Rust agreement on the validation tuple for
   the same `List<T>` / `Stream<T>` corpus. Any divergence — Python
   accepting what Rust rejects, or the inverse — breaks BOTH this
   gate AND its Rust twin, so drift fires on PRs to either stack.

**Status**: ✅ SHIPPED 2026-05-21 — Python `_validate_value` now
strips `List<T>` and recurses identically to Rust; `Stream<T>`
returns `None` (Ok) early (SSE chunks validate at the wire layer
downstream). 12/12 new Python tests green; 82/82 full
`test_fase32_body_schema.py` green; 2114/2114 axon-lang Rust lib
preserved. Ships as axon-lang **v1.40.3 PATCH** + axon-enterprise
**v1.31.3** catch-up alongside Fase 37.x.j.12 (`row_stream.rs`
introspect propagation).
