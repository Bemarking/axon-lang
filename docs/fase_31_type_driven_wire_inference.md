---
title: "Plan vivo: Fase 31 — Type-Driven Wire Inference for Algebraic Stream Effects"
status: DRAFTED 2026-05-11 — D-letter ratification PENDIENTE (D1–D10 propuestos en §4); 31.a engineering spec este doc; 31.b–31.i execution per incremental founder sign-off cadence
owner: AXON Compiler + Runtime Team
created: 2026-05-11
target: axon-lang — next available minor release after v1.21.1 (cadence determined by preceding patches; expected v1.22.0 if no v1.21.x patches intervene). Cross-stack Python + Rust. axon-enterprise catch-up follows the same shape as v1.11.0 / v1.12.0 (Fase 28 + Fase 30 cascade pattern)
depends_on: Fase 11.a SHIPPED (Stream<T> algebraic effect + 4-policy backpressure catalog); Fase 23 SHIPPED (algebraic effects runtime); Fase 28 SHIPPED (adopter diagnostic robustness — Fase 31 inherits the smart-suggest engine + source-context block surface); Fase 30 SHIPPED v1.21.0/v1.21.1 (HTTP transport surface — Fase 31 closes the philosophical gap that Fase 30 left open by D-letter design)
charter_class: OSS — every adopter benefits transitively. axon-enterprise gets the surface via catch-up release after axon-lang ships
pillars: MATHEMATICS — type system computes the wire shape; LOGIC — inference rule `produces_stream(F) ∧ ¬declared(transport, E) ⟹ implicit_transport(E) = sse` is sound + complete; PHILOSOPHY — language is the source of truth; the wire honors the type, not the other way round; COMPUTING — backwards-compat handled via flag-gated rollout + explicit opt-out, not by silent breakage
---

> **Sibling adopter-facing docs:**
> - [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — Fase 30 adopter guide; extended in 31.h with a new "§ Type-driven default transport" section + corresponding migration block.
> - [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Fase 28 adopter-facing diagnostic guide; extended in 31.h with new Pattern 6 (implicit-transport compile warning + diagnostic header).
> - [`STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — Fase 11.a doc; the algebraic-effect surface that this Fase routes onto the wire by default.

---

## ▶ Status snapshot (2026-05-11 — DRAFTED, D1–D10 propuestos)

> **Founder directive 2026-05-11 (verbatim trigger):**
>
> *"axon no es un lenguaje de programación normal, es el siguiente paso histórico en el desarrollo de software sobre LLM's. Todo debe ser como indican nuestros cuatro pilares. Vamos a revisar qué nos falta para que la promesa de algebraic effects funcione a todos nuestros adopters de forma real, completa, robusta, con soporte, y ayuda para resolución de fix, además de que promueva nuestro concepto lambda."*
>
> **MATHEMATICS** + **LOGIC** + **PHILOSOPHY** + **COMPUTING**. Cada decisión de esta Fase debe trazar de vuelta a al menos uno de los cuatro pilares; las que no, se reformulan o se cortan.

Fase 11.a closed the algebraic effect surface in 2026-Q1. Fase 23 closed the runtime in 2026-05-08. Fase 30 closed the HTTP wire format in 2026-05-10. After Fase 30 shipped (v1.21.0 + v1.21.1), the Kivi enterprise adopter reported on 2026-05-11:

> *"axon-lang 1.21.1 instaló OK, bootstrap OK, chat funciona en 5s — pero sigue siendo JSON único, no SSE. Mismo Content-Type: application/json, mismo wrapper. Hemos hecho ya 7 iteraciones en sintaxis y bumps tratando de cablear SSE. La sintaxis del flow es la canónica del doc (tool + effects: <> + apply:), el parser la acepta, los flows compilan, pero el axonendpoint output no se promueve a SSE wire format."*

Diagnosis 2026-05-11 (verified by code inspection of `execute_handler_with_negotiation` in [`axon-rs/src/axon_server.rs`](../axon-rs/src/axon_server.rs)):

  - The Fase 30.e classifier **correctly detects** the stream effect in the adopter's source (the source-text predicate matches `stream:drop_oldest`/`degrade_quality`/`pause_upstream`/`fail`). Internal verdict is `PromoteToSse`.
  - The final gate `has_force_decl || client_wants_sse` evaluates to `false || false`:
      - `has_force_decl = false` — the adopter has NOT declared `transport: sse` on the axonendpoint.
      - `client_wants_sse = false` — the client is NOT sending `Accept: text/event-stream`.
  - The handler falls through to the legacy JSON handler.
  - This is **by design** per Fase 30 D4 (content-negotiation requires `Accept:`) + D9 (absolute backwards-compat with v1.20.x).

After 7 version iterations the adopter found neither path. The empirical evidence is that **the default is backwards**: the language requires the adopter to re-state in the axonendpoint what the flow already declares in its type. This violates the **philosophy** pillar — the language should be the source of truth.

**Charter — what Fase 31 ships:** the type system becomes the authoritative source for the HTTP wire shape. A flow with stream effects implies SSE wire on every axonendpoint that executes it, unless the adopter explicitly opts out via `transport: json`. The Fase 30 D4 fallback survives as an extra safety net. Adopters who declared `transport: sse` (Fase 30 D5) continue to work unchanged.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 31.a Engineering spec + D-letter ratification | ⏳ DRAFTED (awaiting "aprobadas todas D-letters" bloque) | doc-only | — | This doc + memory entry `project_fase_31_plan.md` + MEMORY.md index update. Founder principle reinforced: every D-letter traces to one or more of the four pillars |
| 31.b Type-checker — implicit_transport(E) inference | ⏳ pending | ~140 (Python) + ~140 (Rust mirror) + ~250 (tests) | Python + Rust | New `_implicit_transport(axonendpoint, flow, symbol_lookup) -> Literal["sse","json"]` in `axon/compiler/type_checker.py` (canonical) + `axon-frontend/src/type_checker.rs` (Rust mirror per D7 cross-stack drift contract). Inference rule: `produces_stream(F) ∧ ¬declared(transport, E) ⟹ implicit_transport(E) = sse` (D1). `_flow_produces_stream` predicate from Fase 30.c is reused verbatim. Result threaded into the AxonEndpoint runtime metadata so the runtime classifier can consult the inferred value alongside the declared one. **Math + Logic**: the predicate is the disjunction of the 3 disjuncts from Fase 30.c; soundness + completeness invariants preserved verbatim |
| 31.c Compile-time warning emission for implicit transport (rolling-out diagnostic) | ⏳ pending | ~80 (Python warn shape) + ~80 (Rust mirror) + ~150 (tests) | Python + Rust | When `implicit_transport(E) == "sse"` AND the axonendpoint omits `transport:` declaration, the compiler emits a **WARNING** (not error) of the shape: *"axonendpoint 'X' executes flow 'Y' which produces a stream — implicit transport is `sse`. Declare `transport: sse` to make this explicit and silence this warning, or `transport: json` to opt out and keep the legacy JSON wire format."*. Warning is rate-limited (one per axonendpoint, not per occurrence) and rendered via the Fase 28.d source-context block for adopter ergonomics. **Philosophy**: the language MUST be honest about its inferences; a silent default is a contract the adopter can't reason about |
| 31.d Runtime — type-driven default behind feature flag | ⏳ pending | ~120 (Rust runtime change) + ~280 (tests) | Rust | The negotiation classifier (`execute_handler_with_negotiation` in `axon-rs/src/axon_server.rs`) is extended: when `axon.strict_type_driven_transport: true` AND the deployed flow has stream effects AND no explicit `transport:` declaration AND no explicit `transport: json` opt-out → response is SSE regardless of `Accept:` header. Flag defaults to **false** in v1.22.0 (opt-in for early adopters), flips to **true** in v2.0.0 (Fase 35+ candidate). Existing Fase 30 negotiation matrix preserved when flag is false. **Computing**: backwards-compat handled by config gate, not by silent breakage |
| 31.e Runtime — diagnostic response header `X-Axon-Stream-Available` | ⏳ pending | ~40 (Rust handler change) + ~80 (tests) | Rust | When the legacy JSON handler serves a response for a stream-effect flow that was NOT promoted (because the flag is off OR `transport: json` is declared explicitly), the response carries the header `X-Axon-Stream-Available: 1; reason=<flag_off\|declared_json>; opt_in=transport:sse,Accept:text/event-stream`. Adopters debugging "why am I getting JSON" see the hint in their client logs without having to spelunk the source. Header is informational only — no behavioral effect on the response body. **Philosophy** + **Computing**: surfacing the language's inference makes the contract observable |
| 31.f CLI flag + server config surface | ⏳ pending | ~60 (Python CLI) + ~60 (Rust runtime parse) + ~80 (tests) | Python + Rust | `axon serve --strict-type-driven-transport` CLI flag + `[server] strict_type_driven_transport = true` config key + `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1` env var. All three paths converge on the same ServerConfig field consumed by 31.d. Cross-stack: Python `axon serve` and Rust `axon-rs` both read the same env-var name verbatim (D7 cross-stack consistency extended) |
| 31.g CI matrix + cross-stack drift gate + 100-iter behavior fuzz | ⏳ pending | ~150 (YAML) + ~250 (Py drift tests) + ~250 (Rust drift tests) + ~200 (fuzz packs) | YAML + Python + Rust | New `.github/workflows/fase_31_type_driven_transport.yml` with 4 parallel lanes: (1) python-type-checker (3.12 × 3.13 matrix; runs 31.b inference tests + 31.c warning tests); (2) rust-frontend-mirror (ubuntu × macos × windows; runs Rust mirror tests + D7 drift gate); (3) rust-runtime (ubuntu; runs 31.d runtime behavior + 31.e header + 31.f flag tests under all 4 flag states); (4) cross-stack-drift (explicit D7 parity over shared corpus). D12-style 100-bucket × 10-iter deterministic fuzz of the inference predicate confirms `_implicit_transport` never panics on any byte-mutated source. **Math + Logic + Computing**: the math is locked in CI; drift is impossible to ship |
| 31.h Adopter documentation surface | ⏳ pending | ~400 (`ADOPTER_STREAMING.md` extension — Type-driven default section + migration block) + ~80 (`ADOPTER_DIAGNOSTICS.md` Pattern 6) + ~120 (new `MIGRATION_v1.22.md`) + ~50 (Fase 30 plan vivo back-link) | Docs | Extends `docs/ADOPTER_STREAMING.md` with new "§ Type-driven default transport" section explaining D1-D10, with worked-example showing the Kivi-shape source → inferred SSE wire. New Pattern 6 in `docs/ADOPTER_DIAGNOSTICS.md` for the compile warning + diagnostic header (so adopters debugging "implicit transport" find their way to the migration guide). New top-level `docs/MIGRATION_v1.22.md` documenting how to flip the flag, what to expect, how to roll back. Cross-link from Fase 30 plan vivo's §Status with "see Fase 31 for the philosophical extension". **Philosophy**: the docs are part of the language surface; an adopter who can't find the right page hasn't gotten the language |
| 31.i Coordinated cross-stack release v1.22.0 | ⏳ pending | release | All stacks | bump-my-version minor bump from then-current axon-lang version (v1.21.x → v1.22.0); commit + tag via the existing `coordinated-release.yml`; cargo publish axon-frontend + axon-lang; GitHub Release with content-first notes describing the inference surface + flag-gated rollout + migration guide. axon-enterprise catch-up follows the v1.12.0 shape (lean bump + dep pin) |

---

## ▶ Why this matters — the four-pillar framing

### **MATHEMATICS** — the inference is a function on the type system

Given the type signature of a flow `F` and the declarations on an axonendpoint `E` that executes `F`, the wire transport is a **pure function** of `(F, E)`:

```
implicit_transport : (Flow, AxonEndpoint) → Transport ∈ {sse, json}

implicit_transport(F, E) =
    declared_transport(E)                                  if declared(transport, E)
    "sse"                                                  if produces_stream(F) ∧ ¬declared(transport, E)
    "json"                                                 otherwise
```

The function is **total** (every input has a defined output), **deterministic** (no hidden state), and **referentially transparent** (same input → same output across both stacks — D7 contract).

### **LOGIC** — the inference rule is sound and complete

Per Fase 30.c, `produces_stream(F)` is the disjunction of three formal predicates over the flow body:

```
produces_stream(F) ≡
    ∃ step ∈ F.body. type-level disjunct (a):
        step.output_type matches Stream<T> for some T
    ∨
    ∃ step ∈ F.body. effect-level disjunct (b):
        ∃ tool ∈ step.applied_tools. ∃ effect ∈ tool.effects.
            effect matches <stream:<policy>>
    ∨
    ∃ step ∈ F.body. operational disjunct (c):
        ∃ expr ∈ step.body. expr matches `perform Stream.Yield(...)`
```

Fase 31 reuses this predicate verbatim. The new rule from D1 is:

```
∀ F, E.   produces_stream(F) ∧ axonendpoint(E).execute_flow == F.name ∧ ¬declared(transport, E)
    ⟹   implicit_transport(E) = "sse"
```

**Soundness**: every endpoint that gets implicit SSE has a flow that genuinely produces stream tokens. The runtime SSE handler can faithfully emit those tokens — no false promotions.

**Completeness**: every endpoint whose flow produces stream tokens AND that hasn't declared explicit JSON gets the SSE wire — no false demotions.

### **PHILOSOPHY** — the language is the source of truth

Fase 30 D9 made backwards-compat absolute: *adopters never see behavior change without opting in*. That was correct for the Fase 30 timeline (Kivi was the only adopter; we didn't yet have evidence about default-correctness). After v1.21.1, the evidence is in:

  - The adopter wrote correct stream-effect syntax (3 disjuncts available, they used one).
  - The language internally inferred the right answer (`PromoteToSse`).
  - The language then **second-guessed itself** because the adopter hadn't repeated the inference in the axonendpoint.
  - The adopter spent 7 versions believing the language was broken.

**The language was right; its default was wrong.** Fase 31 makes the default match the inference. Adopters who want to override the default do so explicitly. The language no longer disagrees with itself.

This is the lambda-calculus discipline applied at the wire layer: the type IS the contract. `Chat -> Stream<Token>` SHOULD mean SSE the way `Int -> Int` means a numeric function. Anything else is leakage between the language and its embodiment.

### **COMPUTING** — backwards-compat is a real constraint, handled explicitly

The behavior change is materially observable: v1.21.x adopters whose stream-effect flows currently return JSON via `/v1/execute` would receive SSE in a strict-default v1.22+. Two possibilities for those adopters:

  - **(probable, common)** They were silently broken — their JSON response was a single string containing all stream tokens concatenated, with no streaming semantics on the wire. Their client was waiting for the full response before rendering. The flow's intent was streaming; the runtime delivered batched. v1.22.0 default-on would FIX their broken-but-works state; their client may need a small wire-format change.
  - **(possible, rare)** They intentionally wanted JSON wrapping of a stream-effect flow (e.g. for retro-fit of an LLM chat that synthesizes a final answer from streaming tokens). They want axon to keep returning JSON; they have NOT declared `transport: json`.

Fase 31 serves both cases by:
  1. Default flag OFF in v1.22.0 (the new behavior is opt-in; nothing breaks silently).
  2. Compile-time warning fires for every implicit promotion site so adopters see the inference at build time.
  3. Diagnostic header on JSON responses for stream-effect flows so adopters see the hint at runtime.
  4. One-line opt-out (`transport: json` on the axonendpoint) for case 2.
  5. One-line opt-in (`axon.strict_type_driven_transport: true`) for case 1 / general best-practice.
  6. Flag flips to default ON in v2.0.0 (Fase 35+ candidate) — adopters have v1.22.x + v1.23.x + … to migrate.

---

## ▶ 4. D-letter proposals (D1–D10)

| # | Statement | Pillar(s) |
|---|---|---|
| **D1** | **Implicit transport inference**: `produces_stream(F) ∧ ¬declared(transport, E) ⟹ implicit_transport(E) = sse`. The type system computes the wire shape from the flow type when the axonendpoint omits the declaration | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D2** | **Closed implicit-enum**: `implicit_transport(E) ∈ {sse, json}` only. The `ndjson` namespace remains reserved per Fase 30 D2 but is never inferred; adopters who want ndjson declare it explicitly | LOGIC |
| **D3** | **Explicit `transport: json` always wins**: when the axonendpoint declares `transport: json`, the response is JSON regardless of any stream-effect inference. Adopters keep the right to opt out | LOGIC + PHILOSOPHY + COMPUTING |
| **D4** | **Compile-time warning when transport is implicit AND flag is rolling out**: the type-checker emits a structured warning (severity: warn, NOT error) for every axonendpoint where `implicit_transport(E) = sse` AND no explicit declaration. Rate-limited per-endpoint, Fase 28.d source-context formatted, smart-suggest-compatible (Fase 28.e). Warning suppressed when either explicit `transport: sse` OR `transport: json` is declared | PHILOSOPHY |
| **D5** | **Runtime diagnostic header on JSON-served stream-effect responses**: when a legacy JSON response is served for a stream-effect flow (because flag is off OR `transport: json` is declared), the response carries `X-Axon-Stream-Available: 1; reason=<flag_off\|declared_json>; opt_in=transport:sse,Accept:text/event-stream`. Informational only — never affects the body | PHILOSOPHY + COMPUTING |
| **D6** | **Flag-gated rollout**: server config `strict_type_driven_transport` (boolean, default `false` in v1.22.x, default `true` in v2.0.0). When `false`, Fase 30 D4 + D5 negotiation behavior is preserved verbatim (no behavior change). When `true`, the D1 inference applies on every request | COMPUTING |
| **D7** | **Cross-stack consistency (extends Fase 28 D7 + Fase 30 D7)**: `implicit_transport(E)` is computed byte-identically by the Python type-checker (`axon/compiler/type_checker.py`) and the Rust mirror (`axon-frontend/src/type_checker.rs`). Drift gate over a shared 25-entry corpus locks parity in CI | MATHEMATICS + COMPUTING |
| **D8** | **Fase 30 D8 + D9 preserved when flag is off**: two-stage `/v1/execute/stream` + `/v1/events/stream` pattern unchanged; absolute backwards-compat with v1.20.x preserved verbatim when `strict_type_driven_transport: false`. Fase 31 is strictly additive when the flag is off | COMPUTING |
| **D9** | **Flag flip to ON in v2.0.0 — documented behavior change**: at v2.0.0 (Fase 35+ candidate), `strict_type_driven_transport` defaults to `true`. Adopters who relied on the legacy JSON-wrapping of stream-effect flows must declare `transport: json` explicitly to preserve behavior. The flag remains accessible for emergency rollback | COMPUTING |
| **D10** | **Four-pillar trace requirement**: every Fase 31 D-letter MUST map to ≥ 1 of {MATHEMATICS, LOGIC, PHILOSOPHY, COMPUTING}. D-letters that fail the trace get rewritten or cut. This locks the philosophical discipline into the engineering process | PHILOSOPHY (meta) |

**Bloque ratification request 2026-05-11**: founder reviews § Status + § Why this matters + this table, then approves bloque ("aprobadas todas D-letters" or selective). Same cadence as Fase 30. Until ratification, this doc is the spec; no code changes ship.

---

## ▶ 5. Cross-stack contract (Python ↔ Rust)

The Python axon-lang frontend is the **reference implementation** of the type-checker. The Rust axon-frontend is the **mirror** consumed by axon-rs + axon-lsp. Both must compute `implicit_transport(E)` identically on any input.

| Input shape | Python verdict | Rust verdict | Drift-gate corpus entry |
|---|---|---|---|
| Flow with `output: Stream<T>` step + axonendpoint without `transport:` | `sse` | `sse` | `disjunct_a_implicit_sse` |
| Flow with tool `effects: <stream:drop_oldest>` + `apply: tool` + axonendpoint without `transport:` | `sse` | `sse` | `disjunct_b_implicit_sse` |
| Flow with `perform Stream.Yield(...)` + axonendpoint without `transport:` | `sse` | `sse` | `disjunct_c_implicit_sse` |
| Flow with stream effects + axonendpoint with explicit `transport: sse` | `sse` (declared) | `sse` (declared) | `declared_sse_wins` |
| Flow with stream effects + axonendpoint with explicit `transport: json` | `json` (D3 opt-out) | `json` (D3 opt-out) | `declared_json_overrides_implicit` |
| Flow without stream effects + axonendpoint without `transport:` | `json` (no inference fires) | `json` (no inference fires) | `no_stream_no_implicit` |
| Flow without stream effects + axonendpoint with explicit `transport: sse` (Fase 30.c rejects this at compile time) | compile error | compile error | `non_stream_with_sse_rejected` (already in Fase 30 corpus — reused) |

Corpus lives at `tests/fixtures/fase31_implicit_transport/corpus.json`. Same shape as Fase 30's drift-gate corpus — JSON list of `{name, source, expected_implicit_transport, expected_warning_count}`. Both stacks parametrize over the same JSON.

### Predicate semantics across stacks

Python: `_implicit_transport(axonendpoint: AxonEndpointDefinition, flow: FlowDefinition, symbol_lookup: SymbolTable) -> Literal["sse", "json"]` in `axon/compiler/type_checker.py`.

Rust: `implicit_transport(endpoint: &AxonEndpoint, flow: &FlowDefinition, symbol_lookup: &SymbolTable) -> &'static str` in `axon-frontend/src/type_checker.rs`.

Both share the same control flow:
1. If `endpoint.transport == "sse" || endpoint.transport == "ndjson"` → return `"sse"` (declared wins).
2. If `endpoint.transport == "json"` → return `"json"` (D3 explicit opt-out wins).
3. If `endpoint.transport == ""` (absent) AND `produces_stream(flow)` (Fase 30.c predicate) → return `"sse"` (D1 implicit).
4. Else → return `"json"` (no inference fires).

The result is attached to the parsed AxonEndpoint AST node as a new field `implicit_transport: str` (Python) / `pub implicit_transport: String` (Rust). The runtime classifier consults this field instead of recomputing the predicate per-request.

---

## ▶ 6. Compile-time semantics

### 6.1 Inference site

`_implicit_transport` is called from `_check_axonendpoint` in `axon/compiler/type_checker.py` AFTER the Fase 30.c soundness check. The order matters:
  1. Fase 30.c: if `transport: sse|ndjson` declared but flow doesn't produce a stream → COMPILE ERROR.
  2. Fase 31.b: compute `implicit_transport` and attach to AST.
  3. Fase 31.c: if `implicit_transport == "sse"` AND `transport` was not declared → COMPILE WARNING.

### 6.2 Warning shape (D4)

```
warning[axon-W001]: implicit `transport: sse` inferred from stream effects

  --> src/chat.axon:42:1
   |
42 | axonendpoint ChatEndpoint {
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^ axonendpoint declares no transport
...
47 |     execute: Chat
   |     -------- executes flow 'Chat' which produces a stream via
   |              `effects: <stream:drop_oldest>` on tool 'chat_token_stream'

  = note: when `strict_type_driven_transport: true`, this endpoint will emit
          SSE on /v1/execute. Declare `transport: sse` to make this explicit
          and silence the warning, or `transport: json` to opt out and keep
          the legacy JSON wire format.
  = help: add `transport: sse` to silence this warning + lock in SSE behavior.
```

Warning code `axon-W001` is the first entry in the new `axon-Wnnn` namespace (warnings get `W` prefix; errors keep `E` prefix from Fase 28 + Fase 30). Rate-limited: max one warning per axonendpoint per compile pass.

### 6.3 Warning vs. error decision

D4 ratifies WARNING (not error) for v1.22.0 specifically because:
- A warning honors backwards-compat (existing source compiles unchanged).
- A warning is loud enough to drive adopter awareness (Pattern 6 in ADOPTER_DIAGNOSTICS.md tells them what to do).
- A future Fase can promote warning → error if adopter feedback shows the warning is being routinely ignored.

When `--strict` mode is on (Fase 28.h opt-in), the warning becomes an error per Fase 28 strict semantics. Adopters who run their CI with `--strict` get the strongest signal possible.

### 6.4 Suppression

The warning is suppressed when:
- The axonendpoint declares `transport: sse` explicitly (warning is redundant — adopter already opted in).
- The axonendpoint declares `transport: json` explicitly (warning is moot — adopter opted out).
- The flow does not produce a stream (the predicate is false; no inference fires).

---

## ▶ 7. Runtime semantics

### 7.1 Negotiation classifier change (31.d)

Pseudocode for the Fase 31 classifier (extends Fase 30.e):

```rust
let strict_mode = config.strict_type_driven_transport;
let endpoint_decl = parse_endpoint_declared_transport(&source, &flow_name);
let flow_produces_stream = flow_produces_stream_predicate(&source, &flow_name);

let promote_sse = match (strict_mode, endpoint_decl, flow_produces_stream, client_wants_sse) {
    // D3 — explicit opt-out always wins (Fase 30 D5 preserved).
    (_, Some("json"), _, _)               => false,
    // Fase 30 D5 — explicit opt-in always wins.
    (_, Some("sse"), _, _) | (_, Some("ndjson"), _, _) => true,
    // D1 — strict-mode implicit inference (Fase 31 new behavior).
    (true, None, true, _)                 => true,
    // Fase 30 D4 — content-negotiation fallback (preserved as safety net).
    (false, None, true, true)             => true,
    // Default — JSON.
    _                                     => false,
};
```

When `strict_mode == false` (v1.22.0 default), the only added effect of Fase 31 is the diagnostic header (31.e) — behavior is otherwise byte-identical to Fase 30.

When `strict_mode == true`, the D1 inference rule kicks in: any stream-effect flow served via `/v1/execute` returns SSE, regardless of `Accept` header.

### 7.2 Diagnostic response header (31.e — D5)

When the legacy JSON handler serves a response for a stream-effect flow that was NOT promoted, the response carries:

```
X-Axon-Stream-Available: 1; reason=<flag_off|declared_json>; opt_in=transport:sse,Accept:text/event-stream
```

Where `reason` is:
- `flag_off` — `strict_type_driven_transport: false` and adopter sent no `Accept: text/event-stream`. The opt-in path is to flip the flag, declare `transport: sse`, or send the Accept header.
- `declared_json` — adopter explicitly declared `transport: json`; the language honors the opt-out. Header is still sent so adopters who later change their mind see the diagnostic.

The header is **never** sent on:
- SSE responses (the wire format is already streaming).
- JSON responses for non-stream-effect flows (no inference fired; nothing to surface).

### 7.3 Why a header and not a body field

A header is observable from the client side without parsing the body. Adopters with curl-style debugging see it immediately. A body field would require parsing logic for JSON responses, would conflict with adopters who treat the body as opaque (e.g. forwarding it to a downstream service), and would change the JSON schema (a breaking change). The header is the minimum-invasion mechanism.

---

## ▶ 8. Backwards-compat surface

| Adopter shape pre-v1.22.0 | After upgrade with default flag (`strict_type_driven_transport: false`) | After upgrade with flag opt-in (`strict_type_driven_transport: true`) |
|---|---|---|
| Stream-effect flow + axonendpoint w/o `transport:` + client w/o `Accept:` | JSON response + `X-Axon-Stream-Available` header (NEW informational) | SSE response (NEW behavior) |
| Stream-effect flow + axonendpoint w/o `transport:` + client w/ `Accept: text/event-stream` | SSE response (Fase 30 D4 unchanged) | SSE response (D1 wins same way) |
| Stream-effect flow + axonendpoint w/ `transport: sse` | SSE response (Fase 30 D5 unchanged) | SSE response (Fase 30 D5 unchanged) |
| Stream-effect flow + axonendpoint w/ `transport: json` (Fase 31 NEW opt-out) | JSON response + `X-Axon-Stream-Available` header | JSON response + `X-Axon-Stream-Available` header |
| Non-stream flow + any axonendpoint state | JSON response (no inference fires) | JSON response (no inference fires) |
| Compile-time, every source file with at least one stream-effect flow + axonendpoint w/o `transport:` declaration | Compiler emits `axon-W001` warning (NEW) | Same warning + flag is hot |

**The only behavior change for v1.21.x sources at default flag**: the new `X-Axon-Stream-Available` header on JSON responses for stream-effect flows. Header is informational; clients that don't read it see no change.

**The only behavior change at flag opt-in**: stream-effect flows with no explicit declaration return SSE regardless of `Accept` header. Clients that were already parsing the legacy JSON wrapping will fail to parse SSE — same as if they had declared `transport: sse`. Adopters opt in deliberately when they've upgraded their client.

---

## ▶ 9. Migration path (31.h — new `docs/MIGRATION_v1.22.md`)

The migration doc walks adopters through 4 scenarios in order of urgency:

**Scenario A — adopter currently broken (Kivi case)**: stream-effect flow returning JSON; client expected streaming. Fix in 60 seconds:
1. Add `transport: sse` to the axonendpoint.
2. Redeploy.
3. Client receives SSE; problem solved.

**Scenario B — adopter wants the new behavior on every endpoint**: opt into the flag.
1. Set `[server] strict_type_driven_transport = true` in axon config.
2. Restart `axon serve`.
3. All stream-effect flows now emit SSE by default.

**Scenario C — adopter has working JSON-wrapping (rare)**: keep current behavior.
1. Add `transport: json` to every axonendpoint that intentionally wraps stream-effect output.
2. The compile-time warning silences.
3. The diagnostic header still fires (clients see the hint; behavior preserved).

**Scenario D — adopter is staging the migration**: turn the flag on per-environment.
1. Start with dev env flag on; staging flag on; production flag off.
2. Validate client behavior in each tier.
3. Flip production flag last.

---

## ▶ 10. Tests target

~360 new tests across the cross-stack surface:

| Surface | Test count | Module(s) |
|---|---|---|
| Python `_implicit_transport` inference (positive: all 3 disjuncts → sse) | 9 | `tests/test_fase31_implicit_transport.py` |
| Python inference (negative: no stream → json; declared-wins) | 6 | same |
| Python warning emission (positive: warning fires; rate-limit; suppression) | 12 | `tests/test_fase31_implicit_transport_warning.py` |
| Python cross-flow / multi-axonendpoint per-pass dedup | 5 | same |
| Rust mirror inference (3 disjuncts + negative + declared-wins) | 15 | `axon-frontend/src/type_checker.rs::fase31_tests` |
| Rust mirror warning emission | 8 | same |
| Cross-stack drift gate (25-entry corpus × 4 assertions) | 100 | `tests/test_fase31_drift_gate.py` + `axon-frontend/tests/fase31_drift_gate.rs` |
| Rust runtime negotiation matrix (16-cell: flag × endpoint × stream × Accept) | 16 | `axon-rs/tests/fase31_strict_mode.rs` |
| Rust runtime diagnostic header (4 trigger conditions × 2 reasons) | 8 | `axon-rs/tests/fase31_diagnostic_header.rs` |
| Rust runtime config flag surface (CLI + env + config file) | 12 | `axon-rs/tests/fase31_flag_surface.rs` |
| D12-style 100-iter deterministic fuzz of `_implicit_transport` (never panics) | 100 (Py) + 100 (Rust mirror) | `tests/test_fase31_implicit_fuzz.py` + `axon-frontend/tests/fase31_implicit_fuzz.rs` |
| Integration test — Kivi-shape source end-to-end | 6 | `axon-rs/tests/fase31_integration_kivi_shape.rs` |
| Backwards-compat regression — every Fase 30 test still passes when flag is off | re-runs existing 45 Fase 30 tests | (regression) |

Plus extension of the Fase 30 drift gate to confirm v1.22.0 doesn't regress v1.21.x behavior.

---

## ▶ 11. Out of scope (deferred to future fases)

- **ndjson wire format implementation** — namespace reserved per Fase 30 D2; `implicit_transport` never returns `"ndjson"`. Future fase ships ndjson-specific runtime semantics.
- **Per-request override headers** — e.g. `X-Axon-Force-Transport: json`. Adopters opt out at the axonendpoint level, not the per-request level. Future fase if adoption demands.
- **Type-level `transport:` inference from richer flow type signatures** — e.g. `Chat() -> AsyncIterator<Token>` or higher-kinded types. Fase 31 stays with the Fase 30.c 3-disjunct predicate.
- **Inference for non-axonendpoint declarations** — e.g. webhooks, scheduled tasks. Fase 31 scope is `axonendpoint` only.
- **Browser-side type checker (wasm)** — the Fase 30.g wasm artefact is the compiler infrastructure surface; Fase 31 doesn't ship an in-browser inference demo. Future fase.

---

## ▶ 12. Versioning + release plan

**Target**: next available minor release after v1.21.1 (expected v1.22.0 if no v1.21.x patches intervene before the Fase 31 release commit lands). Per versioning discipline: SemVer strict, secuencial sin saltos, version ≠ Fase.

**Why minor (not major)**:
- Strictly additive when flag is off (default in v1.22.x).
- Behavior change is opt-in via flag.
- Major bump (v2.0.0) reserved for the flag flip to default-on (Fase 35+ candidate).

**Cargo + PyPI release**: same `coordinated-release.yml` workflow as Fase 30. `axon-csys` does not bump (no C kernel changes). `axon-frontend` bumps (mirror inference + warning), expected `0.9.0 → 0.10.0`.

**axon-enterprise catch-up**: standalone bump release (PR-merged, same shape as v1.11.0 / v1.12.0) consuming the new axon-lang version. No enterprise-only Fase 31 surface.

---

## ▶ 13. Sub-fase execution order + dependencies

Topological order (each sub-fase depends only on those above it):

```
31.a (this doc + D-letter ratification)
  └─ 31.b (Python type-checker + Rust mirror — inference function)
       ├─ 31.c (compile-time warning)
       │    └─ 31.h (adopter docs reference 31.c warning shape)
       ├─ 31.d (runtime flag-gated behavior)
       │    └─ 31.e (runtime diagnostic header)
       │         └─ 31.f (CLI flag + config surface)
       └─ 31.g (CI matrix + drift gate + fuzz — depends on 31.b/c/d/e/f all stable)
            └─ 31.i (release v1.22.0)
```

Per Fase 30 cadence: founder approves D-letters bloque → sub-fases ship one-per-PR-equivalent with explicit sign-off (`procede con 31.b`, `procede con 31.c`, …).

---

## ▶ 14. Founder principle reinforcement

> *"axon no es un lenguaje de programación normal, es el siguiente paso histórico en el desarrollo de software sobre LLM's"* (2026-05-11)

Fase 31 is the moment where the language graduates from *describing* algebraic effects to *enforcing* their wire-level semantics. After Fase 31, an adopter cannot accidentally lose the streaming contract by forgetting one declaration — the language detects, warns, and (under the strict flag) corrects.

The four pillars are not decoration. They are the engineering discipline:

- **MATHEMATICS** says the type of the function determines its observable behavior.
- **LOGIC** says the inference rule must be sound, complete, and decidable.
- **PHILOSOPHY** says the language is the source of truth; the wire is the projection of the type.
- **COMPUTING** says we honor the constraints of the deployed world: flags, headers, backwards-compat, drift gates.

Every D-letter in §4 traces to ≥ 1 pillar (D10 — meta). Future D-letters that fail the trace are not D-letters; they are wishlists. The discipline is the moat.

---

## ▶ 15. How to apply (post-shipping troubleshooting checklist)

When shipped, if an adopter reports *"streaming flow returns JSON"*, walk this checklist:

1. **What does `axon parse src/your.axon` say?**
   - If it emits `axon-W001` warning → the inference fired; adopter just needs to declare `transport: sse` or flip the flag.
   - If it emits no warning → the flow does NOT produce a stream by the 3-disjunct predicate. The adopter's syntax may be off — point them at `docs/STREAM_EFFECTS.md`.
2. **What does the `X-Axon-Stream-Available` header say?**
   - `reason=flag_off` → the server isn't running with the strict flag AND the client isn't sending Accept. One of the three opt-ins is required.
   - `reason=declared_json` → the adopter explicitly opted out. Their choice was honored.
   - Header absent → either the response is already SSE, OR the flow is genuinely non-streaming.
3. **Is the server config flag what the adopter thinks it is?**
   - `curl http://localhost:8443/v1/config | jq .strict_type_driven_transport` → returns boolean.
4. **Does the client send `Accept: text/event-stream`?**
   - Fase 30 D4 still works as a safety net when the flag is off.

This checklist is the post-Kivi-incident SOP. After Fase 31 ships, no adopter should reach 7 version iterations on this question.

---

*This document is part of the axon-lang internal plan-vivo surface. Sibling adopter-facing docs ship in 31.h.*
