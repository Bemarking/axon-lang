# §Fase 33.z.k — Wire-format adapter cycle (target v1.28.0)

> **Status:** ⏳ DRAFT 2026-05-13 — awaiting founder bloque
> ratification of D-letter set + sub-fase sequencing.
>
> **Trigger:** adopter pain 2026-05-13 — after v1.27.1's
> algebraic-effect override fired SSE wire correctly on the
> Kivi-shape, the adopter STILL reported "los algebraics effects
> SSE no se ofrecen" because they expected OpenAI-style framing
> (`data: {"chunk": "..."}` + `data: [DONE]`) instead of axon's
> W3C named-event framing
> (`event: axon.token` + `data: {"step": "...", "token": "..."}`).
> Two layers of the same adopter complaint: the route classifier
> (closed in v1.27.1) and the wire format (this cycle).
>
> **Founder principle to honor:** *adopters never adapt to axon's
> wire format; axon adapts to adopter clients OR provides a
> declarative way to choose the wire format upstream of HTTP.*
> The current named-event format is W3C-correct but un-pluggable.

---

## ▶ 1. The conversation this cycle opens

The 33.z.k.1 patch closed the route-classification gap: tools
with `effects: <stream:<policy>>` produce `Content-Type:
text/event-stream` unconditionally. But the wire BODY adopters
receive is:

```
event: axon.token
id: 1
data: {"step":"Generate","token":"Hola","timestamp_ms":1715648400123}

event: axon.token
id: 2
data: {"step":"Generate","token":", ¿","timestamp_ms":1715648400125}

event: axon.complete
id: 3
data: {...}
```

What the adopter expected:

```
data: {"chunk": "Hola"}

data: {"chunk": ", ¿"}

data: [DONE]
```

The expected format is **OpenAI-style streaming** (no `event:`
line, `chunk` field in data, `[DONE]` sentinel). It's the de-
facto wire format adopters consuming LLM streams already know.
Other competing formats exist (Anthropic SSE with different
event names; bare NDJSON; gRPC streaming response; WebSocket
frames).

The axon language already has a typed primitive for wire
format: `transport: {json,sse,ndjson}` on axonendpoint. The
cycle's job is to **extend that primitive** so adopters can
declare which dialect of SSE they want, with one or more
adapters wired into the SSE producer.

---

## ▶ 2. Open design questions (require founder ratification)

### Q1 — Default dialect

Three options:

- **(a)** Keep `axon.token/axon.complete` as default; OpenAI-
  style available via opt-in declaration. Most W3C-correct;
  least adopter-friendly out of the box.
- **(b)** Flip default to OpenAI-style for tool-streaming flows
  (algebraic-effect signal); keep axon-named events for
  type-annotation-only stream flows. Honest signal: the tool
  declared a stream effect → ship it in the format most LLM
  adopters expect.
- **(c)** Flip default to OpenAI-style for ALL SSE flows in
  v1.28.0. Most adopter-friendly; breaks any existing client
  parsing `event: axon.token`. Major-version-shape change.

### Q2 — Declaration grammar

Options:

- `transport: sse(openai)` / `transport: sse(anthropic)` /
  `transport: sse(axon)` — parametrized transport.
- New `wire_format:` field — orthogonal to `transport:`.
  Cleaner separation of concerns; bigger surface change.
- Per-tool `effects: <stream:drop_oldest, wire: openai>` —
  declare wire format with the effect, since that's where the
  semantic commitment lives.

### Q3 — Adapter set scope

How many dialects ship in v1.28.0?

- **Minimal**: axon (current) + openai. Two dialects covers
  the dominant LLM-streaming adopter pattern.
- **Vertical-grounded**: axon + openai + anthropic. Anthropic
  has a distinct SSE shape (`event: content_block_delta` etc.)
  that some enterprise adopters need verbatim.
- **Full mesh**: axon + openai + anthropic + ndjson +
  gRPC-streaming + WebSocket frames. Way too much surface for
  one cycle.

### Q4 — `[DONE]` sentinel + terminator semantics

OpenAI's `data: [DONE]` is a non-JSON sentinel that some
clients hard-code as the stream terminator. Anthropic uses
`event: message_stop` without a sentinel. Axon's current
format uses `event: axon.complete`. The adapter must reconcile.

### Q5 — Wire byte-compat across the cycle

Adopters consuming the current `event: axon.token` format
(maybe none today, maybe some downstream crates of
`flow_dispatcher`) will see a behavior change if the default
flips. Need a deprecation window OR a per-endpoint declaration
forcing the axon dialect.

### Q6 — Tool-call event family

The `event: axon.tool_call` family (shipped in v1.27.0) is
specific to axon's wire. OpenAI streaming for tool-using
completions interleaves `tool_calls` fields inside the same
`data: {chunk}` frame. The adapter must map between these
shapes.

### Q7 — Algebraic policy preservation

`effects: <stream:drop_oldest>` declares back-pressure
semantics. The current `StreamPolicyEnforcer` populates
`enforcement_summary` counters on `axon.complete`. If the
wire flips to OpenAI-style, where do these counters go?
Options: HTTP trailer headers, custom `data: {...}` frame
before `[DONE]`, dropped entirely. Each has tradeoffs.

---

## ▶ 3. Sketched D-letters (12 proposed, awaiting ratification)

- **D1 — closed-catalog wire formats**: the set of dialects
  is closed; adding a new one requires a deliberate sub-fase.
  Open-set adapter pluggability is a different cycle.
- **D2 — declarative wire choice**: adopters select wire
  format declaratively in source (not via HTTP headers or
  runtime flags); the language is single-source-of-truth.
- **D3 — semantic equivalence across dialects**: per-token
  content + step-name + arrival ordering are byte-identical
  across dialects. Only framing differs.
- **D4 — algebraic-policy preservation**: enforcement
  summaries, runtime warnings, and step audit records reach
  the adopter REGARDLESS of dialect. Each dialect declares
  where it surfaces them.
- **D5 — `[DONE]` sentinel handling**: each dialect's
  terminator is specified explicitly + tested per-adapter.
- **D6 — backwards-compat for axon dialect**: existing
  consumers of `event: axon.token` keep working through at
  least one minor release. Deprecation window + adopter
  migration recipe.
- **D7 — cross-stack contract**: Python and Rust frontends
  agree on dialect parsing; runtime adapters live in axon-rs
  but the type-checker validates dialect declarations.
- **D8 — type-driven dialect inference**: when an adopter
  declares `effects: <stream:drop_oldest, wire: openai>` on a
  tool, the endpoint inherits the wire choice transitively
  (similar to 31.b's `implicit_transport`).
- **D9 — wire byte-compat for canonical Step**: the canonical
  `step S { ask: "..." output: Stream<Token> }` + stub backend
  emits exactly 1 token + 1 terminator in the chosen dialect.
- **D10 — four-pillar trace**: MATH (adapter is a pure
  function) + LOGIC (closed catalog, total dispatch) +
  PHILOSOPHY (adopter chooses; language doesn't impose) +
  COMPUTING (per-dialect byte-byte-correct round-trip tests).
- **D11 — tool-call interleaving**: each dialect specifies
  how tool-call events surface (OpenAI: inline `tool_calls`
  in chunk; axon: separate `event: axon.tool_call`;
  Anthropic: `event: content_block_start` with type tool_use).
- **D12 — fuzz coverage**: production-grade LCG fuzz across
  every dialect × every architectural-group shape (45×N iters).

---

## ▶ 4. Sketched sub-fases (13 proposed, awaiting ratification)

| Sub-phase | Scope | LOC | Status |
|---|---|---|---|
| **33.z.k.a** | spec + diagnostic anchor over the current wire surface | ~600 | ⏳ pending |
| **33.z.k.b** | dialect AST + parser grammar (`transport: sse(<dialect>)` or `wire_format:`) | ~800 | ⏳ pending |
| **33.z.k.c** | type-checker — closed-catalog enum + cross-disjunct inference (D8) | ~500 | ⏳ pending |
| **33.z.k.d** | axon dialect (current wire) — extracted into a named adapter for D6 backwards-compat | ~400 | ⏳ pending |
| **33.z.k.e** | openai dialect — `data: {"chunk": "..."}` + `data: [DONE]` adapter | ~600 | ⏳ pending |
| **33.z.k.f** | anthropic dialect — `event: content_block_delta` etc. adapter | ~700 | ⏳ pending |
| **33.z.k.g** | tool-call interleaving per dialect (D11) | ~500 | ⏳ pending |
| **33.z.k.h** | algebraic-policy surfacing per dialect (D4 — counters, warnings, audit) | ~400 | ⏳ pending |
| **33.z.k.i** | drift gate over the dialect catalog | ~350 | ⏳ pending |
| **33.z.k.j** | D12 production-grade fuzz × dialects | ~700 | ⏳ pending |
| **33.z.k.k** | dedicated CI workflow extension | ~250 | ⏳ pending |
| **33.z.k.l** | adopter docs — `MIGRATION_v1.28.md` + `ADOPTER_STREAMING.md` § dialects | ~900 | ⏳ pending |
| **33.z.k.m** | release v1.28.0 + axon-enterprise v1.19.0 catch-up | release | ⏳ pending |

**Total target:** ~6 700 LOC + ~80 new tests + dialect-cross-
product fuzz + dedicated CI lanes.

---

## ▶ 5. What this cycle does NOT do

- Does NOT introduce open-set adapter pluggability (downstream
  crates registering custom dialects). Closed catalog only.
- Does NOT change the HTTP transport choice (`json` / `sse` /
  `ndjson` stays as-is). The wire FORMAT is a different
  primitive from the wire SHAPE.
- Does NOT change non-SSE behavior. JSON responses, idempotency,
  replay, auth, audit — all unchanged.
- Does NOT change the algebraic-effect override from 33.z.k.1.
  That stays as the route classifier's responsibility.

---

## ▶ 6. Founder ratification needed

Before sub-fase 33.z.k.a starts, please ratify:

1. **Q1** — default dialect choice (a/b/c)
2. **Q2** — declaration grammar (parametrized transport vs new
   field vs per-effect)
3. **Q3** — adapter set scope (minimal/vertical-grounded/full)
4. **Q4** — terminator semantics
5. **Q5** — backwards-compat window for axon dialect
6. **Q6** — tool-call interleaving strategy per dialect
7. **Q7** — algebraic-policy preservation channel

Once ratified, the plan vivo flips from DRAFT to IN PROGRESS
and 33.z.k.a kicks off.
