# §Fase 33.z.k.1 — Algebraic-effect override on dynamic routes (v1.27.1)

> **Status:** ✅ SHIPPED 2026-05-13 as axon-lang v1.27.1
>
> **Trigger:** adopter report 2026-05-13 — after the Fase 33.z cycle
> shipped v1.27.0 with the dispatcher unified into the production
> SSE producer, the wire response for a flow whose step applied a
> tool with `effects: <stream:drop_oldest>` was STILL
> `Content-Type: application/json`. The user expected per-token SSE
> chunks (the entire premise of the algebraic-effects paper) and
> got a single JSON blob with a `X-Axon-Stream-Available` header
> instead.
>
> **Founder principle honored:** *"el valor del paper debe
> entregarse"* — an algebraic effect declared on a tool is a
> language-level commitment to streaming, not a client preference.
> The wire MUST honor it without requiring `Accept:` cooperation
> or a server-side strict-mode flag.

---

## ▶ 1. The bug 33.z.k.1 closes

Pre-33.z.k.1, the runtime classifier
`axon_server::classify_dynamic_route_wire` applied a single
8-cell truth table over `(transport, transport_explicit,
implicit_transport, client_wants_sse, strict_mode)`. The
critical row was:

| explicit | transport | implicit | strict | accept_sse | wire |
|----------|-----------|----------|--------|------------|------|
| false    | (n/a)     | sse      | false  | false      | **JSON** ← D9 backwards-compat |

This row applied uniformly to **both** disjuncts of
`produces_stream(F)`:

- **(a)** flow has a step with `output: Stream<T>` (type annotation)
- **(b)** flow has a step with `apply: <tool>` where the tool
  declares `effects: <stream:<policy>>` (algebraic effect)

But disjunct (b) is **architecturally distinct**:

- **(a) Type annotation** declares *the shape* of the flow's
  output. It's a structural contract. The D6 backwards-compat
  default (require `Accept:` or strict_mode) makes sense here:
  adopters might have clients consuming the JSON projection of
  the stream and don't want to break them on upgrade.

- **(b) Algebraic effect** declares *a runtime behavior of the
  tool* as part of the type system. The compiler typed the
  tool's `effects` row; the runtime committed to producing
  chunked output. Requiring client cooperation to honor this
  commitment is incoherent — the language already promised it.

The 33.z cycle shipped the structurally-complete dispatcher
production wiring (v1.27.0). But the v1.22.0 D6 gate stayed
above the dispatcher, so the algebraic-effect commitment never
reached the wire for adopters who didn't send `Accept:` headers
or set `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1`. The dispatcher
itself never even ran for these requests — the route classified
as JSON before dispatch.

---

## ▶ 2. The override

33.z.k.1 introduces an algebraic-effect override that fires
**above** the D6 backwards-compat gate but **below** the D3
sacred explicit-`transport: json` opt-out.

New 6-input truth table:

| explicit | transport | **algebraic** | implicit | strict | accept_sse | wire |
|----------|-----------|---------------|----------|--------|------------|------|
| true     | sse       | *             | *        | *      | *          | SSE  |
| true     | ndjson    | *             | *        | *      | *          | SSE  |
| true     | json      | *             | *        | *      | *          | JSON ← D3 sacred opt-out |
| false    | (n/a)     | **true**      | *        | *      | *          | **SSE** ← **D11 algebraic-effect override (v1.27.1)** |
| false    | (n/a)     | false         | sse      | true   | *          | SSE  ← D1 inference fires |
| false    | (n/a)     | false         | sse      | false  | true       | SSE  ← D4 Accept-fallback |
| false    | (n/a)     | false         | sse      | false  | false      | JSON ← D9 backwards-compat |
| false    | (n/a)     | false         | json     | *      | *          | JSON |
| false    | (n/a)     | false         | ""       | *      | *          | JSON |

**Precedence:** D3 (`transport: json` explicit) > D11 (algebraic
override) > D1 (strict mode) > D4 (Accept fallback) > D9
(backwards-compat default).

**The override is surgical** — it ONLY fires when disjunct (b)
holds. Disjunct (a) (type-annotation only) preserves v1.22.0
behavior exactly. Adopters who depended on the JSON projection
of `output: Stream<T>` flows without `Accept:` cooperation see
NO change at v1.27.0 → v1.27.1.

---

## ▶ 3. D-letters

- **D11 (new, 33.z.k.1)** — Algebraic effects on tools drive
  the wire unconditionally (D3 still wins above). Encoded as
  the `has_algebraic_stream_effect` boolean on
  `AxonEndpointDefinition` + `DynamicEndpointRoute`. The
  predicate is `flow_uses_streaming_tool(execute_flow, program)`
  — a tool referenced via `step.apply_ref` OR a top-level
  `UseTool` step that declares `effects: <stream:<policy>>`.
- **D3 preserved** — explicit `transport: json` on the endpoint
  remains the only escape valve from the override. Adopters who
  WANT JSON for a stream-effect flow declare it explicitly.
- **D4 + D6 + D9 preserved for disjunct (a)** — the type-
  annotation-only path is unchanged. v1.22.0 contract honored
  for every shape the override doesn't touch.
- **D10 (four-pillar trace)** —
  - MATHEMATICS: the override is a pure predicate over the AST;
    the classifier is a total function over 6 inputs.
  - LOGIC: the override fires iff the algebraic predicate is
    true AND the endpoint doesn't explicitly declare json.
  - PHILOSOPHY: the language honors what it typed; the type
    system's algebraic-effect row IS the wire commitment.
  - COMPUTING: 6-input truth table verified by 8 dedicated
    truth-table tests + 5 end-to-end integration tests + the
    existing 100-iter LCG fuzz updated to 6 inputs.

---

## ▶ 4. Surface deltas (v1.27.0 → v1.27.1)

### Rust frontend (`axon-frontend`)

- `type_checker::flow_uses_streaming_tool` — visibility raised
  from private to `pub`. The predicate is the algebraic-effect
  signal. Existing callers (`produces_stream`) unaffected.
- `AxonEndpointDefinition` — new field
  `has_algebraic_stream_effect: bool` (default false). D9
  backwards-compat: old AST consumers see the default.
- `parser::parse_axonendpoint` — initializes the field to false.
- `type_checker::compute_implicit_transports` — extended to
  populate the new field in lockstep with `implicit_transport`.

### Rust runtime (`axon-rs`)

- `DynamicEndpointRoute` — new field
  `has_algebraic_stream_effect: bool`. Copied verbatim from
  `ae.has_algebraic_stream_effect` at route construction.
- `classify_dynamic_route_wire` — signature extends from 5 to
  6 inputs; new override branch fires when
  `has_algebraic_stream_effect == true` AND
  `!transport_explicit || transport != "json"`.
- Call site at `axon_server.rs:20095` — passes
  `route.has_algebraic_stream_effect` as the new arg.

### Python frontend (`axon/compiler`)

- `ast_nodes.AxonEndpointDefinition` — new field
  `has_algebraic_stream_effect: bool = False`. Cross-stack
  parity with the Rust AST.
- `type_checker._compute_implicit_transports` — extended to
  populate the new field via `_flow_uses_streaming_tool`.

### Tests

- `axon-rs/src/axon_server.rs` truth-table tests — updated 8
  existing assertions to 6-input signature + added 4 new
  assertions covering the algebraic-effect override.
- `axon-rs/tests/fase32_fuzz.rs` — fuzz extended to 6 inputs
  with `algebraic = rng.bool()`.
- `axon-rs/tests/fase33z_k_1_algebraic_override.rs` — NEW
  integration test pack (5 tests):
  - §1 Kivi-shape end-to-end (POST without Accept → SSE)
  - §2 Wire body carries `event: axon.token` +
    `event: axon.complete`
  - §3 D3 `transport: json` explicit opt-out still wins
  - §4 Type-annotation-only still respects D6
  - §5 Override fires across POST/PUT/PATCH methods

---

## ▶ 5. Vertical-grounded relevance

The override unblocks adopters whose canonical patterns
declare algebraic stream effects:

| Vertical | Canonical pattern | Pre-33.z.k.1 | Post-33.z.k.1 |
|---|---|---|---|
| Banking AML | `tool aml_score { effects: <stream:drop_oldest> }` + `step Score { apply: aml_score }` | application/json (silent W001) | text/event-stream |
| Healthcare CDS | `tool cds_engine { effects: <stream:fail_on_overflow> }` + `step Adjudicate { apply: cds_engine }` | application/json | text/event-stream |
| Legal Privilege | `tool privilege_scanner { effects: <stream:degrade_quality> }` + `step Review { apply: privilege_scanner }` | application/json | text/event-stream |
| Government Audit | `tool audit_log { effects: <stream:drop_newest> }` + `step Record { apply: audit_log }` | application/json | text/event-stream |

The 4 verticals share a structural pattern: their tools encode
domain-specific streaming policies (drop_oldest for AML
back-pressure tolerance; fail_on_overflow for CDS safety;
degrade_quality for legal review under heavy load; drop_newest
for audit immutability). The override means each vertical's
canonical pattern works wire-correctly without per-endpoint
declaration churn.

---

## ▶ 6. Honest scope statement

- The override is **surgical to the algebraic-effect disjunct**.
  Flows with `output: Stream<T>` type annotations but NO tool
  effects do NOT change behavior at v1.27.0 → v1.27.1. The
  v1.22.0 D6 backwards-compat default remains active for that
  disjunct. Flipping THAT default to also-fire-by-default is a
  separate v2.0.0 conversation (per the original Fase 31 D9
  trajectory).
- The wire format the SSE producer emits is still
  `event: axon.token` + `data: {"step": ..., "token": "...",
  ...}` (W3C SSE with named events), NOT
  `data: {"chunk": "..."}` + `data: [DONE]` (OpenAI-style).
  Adopters expecting OpenAI-style wire bodies still face a
  format mismatch. That conversation is the Fase 33.z.k wire-
  format adapter cycle scoped in
  [`docs/fase/fase_33z_k_wire_format_adapter.md`](fase_33z_k_wire_format_adapter.md)
  and tracked toward v1.28.0.
- This is a PATCH release (v1.27.0 → v1.27.1). No semver
  conflicts; no removal of public surface. Pure additive:
  one new field on two AST nodes + one new input to one
  public function.

---

## ▶ 7. Cross-stack regression

- Rust lib: **1743 passed / 0 fail** (+4 truth-table tests over
  v1.27.0)
- Rust integration: **5 new tests verde** in
  `fase33z_k_1_algebraic_override.rs`
- Rust 33.z lanes all still green: 33.z.a 10/10 · 33.z.c 16/16
  · 33.z.d 2/2 · 33.z.e 10/10 · 33.z.g 16/16 · 33.z.k.1 5/5
- Python cross-stack drift gate: **314 passed** including the
  existing Fase 31 implicit-transport corpus
  (`disjunct_b_implicit_sse_via_apply` confirms the cross-stack
  signal agrees)
- Zero regressions

---

## ▶ 8. Release coordination

- **axon-lang v1.27.1**: bump-my-version patch across 6 files;
  PyPI + crates.io + GitHub Release.
- **axon-rs v1.27.1**: workspace lockstep.
- **axon-frontend** stays at **0.11.1** — the AST field
  addition uses the same compatible-extension pattern as 33.z
  did for `DynamicEndpointRoute` (additive field with
  sensible default).
- **axon-enterprise v1.18.1**: lean catch-up with dep pin
  `axon-lang>=1.27.0` → `>=1.27.1`. Vertical-inheritance notes:
  the 4 regulated verticals immediately observe SSE wire output
  for their canonical algebraic-effect patterns without any
  per-tenant code change.
