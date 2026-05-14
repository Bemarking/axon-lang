# §Fase 33.z.k — Wire-format adapter cycle (target v1.28.0)

> **Status:** 🚀 IN PROGRESS 2026-05-13 — founder ratification
> received ("Si"); auto-ratified Q1-Q7 design questions per the
> Axon-for-Axon discipline (documented in §2 below); sub-fases
> 33.z.k.a-m sequenced for v1.28.0.
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

## ▶ 2. Ratified design questions (2026-05-13)

The 7 open questions below received founder bloque ratification
("Si") under the autonomous-option discipline. Reasoning grounded
in: (a) "Axon for Axon — every implementation is for the language
itself"; (b) "el valor del paper debe entregarse"; (c) "axon ships
language primitives, not adopter patches".

### Q1 — Default dialect: **(b) algebraic-effect-driven default**

When the flow declares an **algebraic effect** (the stronger
semantic commitment — disjunct b of `produces_stream`), the
default dialect is **openai**. When the flow uses **type-
annotation only** (`output: Stream<T>` without a tool effect —
disjunct a, the structural commitment), the default dialect is
**axon** (W3C named events).

**Reasoning:** the algebraic-effect declaration is the language's
strongest commitment to streaming; defaulting to the dialect the
LLM-streaming ecosystem expects honors the four-pillar paper's
COMPUTING pillar (adopters get what they expect on the first
request, no Accept-header gymnastics). The type-annotation-only
case is more abstract (`Stream<T>` is structural, not tied to a
specific LLM); keeping W3C named events preserves correctness +
backwards-compat for any adopter consuming the existing axon
wire shape.

**D3 escape valve preserved:** explicit `transport: sse(axon)`
forces the W3C-named dialect even on algebraic-effect flows;
explicit `transport: sse(openai)` forces OpenAI-style even on
type-annotation-only flows.

### Q2 — Declaration grammar: **`transport: sse(<dialect>)` parametrized**

The existing `transport:` field gains a parenthesized parameter
selecting the dialect. The closed-catalog dialect set is
`{axon, openai, anthropic}` (per Q3). Bare `transport: sse`
remains valid and resolves to the Q1 default per the flow's
algebraic-effect predicate.

**Reasoning:** reuses the existing axonendpoint field (no new
field surface); compact + symmetrical with the `<stream:policy>`
parametrized syntax already used on tool effects; parser changes
localize to the existing transport-value-parsing path. The
`wire_format:` orthogonal-field alternative was rejected as
unnecessary surface bloat — the dialect IS the wire's transport
concern.

### Q3 — Adapter set scope: **vertical-grounded — 3 dialects**

`axon` (W3C named events, current) + `openai` (data:{chunk} +
[DONE] sentinel) + `anthropic` (event: content_block_delta).

**Reasoning:** the 4 high-profile regulated verticals consume
LLM streams from providers whose adopter SDKs hard-code either
OpenAI-compat (OpenAI / Kimi / GLM / Ollama / OpenRouter all
use OpenAI-style SSE) or Anthropic SSE (HIPAA clinical reasoning
uses Anthropic Claude for FDA-cleared reasoning models in many
deployments). Three dialects cover ~95% of adopter expectations.
Open-set pluggability (downstream crates registering custom
dialects) is explicitly out of scope — closed catalog stays
within the Axon-for-Axon discipline.

### Q4 — Terminator semantics: **per-dialect native**

Each dialect ships its native terminator:
- **axon** → `event: axon.complete` + `data: {success, ...}`
- **openai** → `data: [DONE]` (literal — non-JSON sentinel)
- **anthropic** → `event: message_stop` + `data: {...}`

**Reasoning:** terminators are part of the dialect's wire
contract; adopter SDKs hard-code them. Forcing a unified
terminator across dialects would break compatibility with the
adopter SDKs that motivated the cycle.

### Q5 — Backwards-compat window for axon dialect: **indefinite**

The axon W3C-named dialect remains a first-class option
indefinitely. `transport: sse(axon)` always works. The default
for type-annotation-only flows stays axon (per Q1). No
deprecation timeline.

**Reasoning:** the axon dialect is the W3C-correct baseline; it
satisfies the COMPUTING + LOGIC pillars from the four-pillar
paper. Adopters who built EventSource clients parsing named
events continue to work unchanged.

### Q6 — Tool-call interleaving per dialect

Per-dialect implementation detail; each adapter handles the
mapping internally:
- **axon** → separate `event: axon.tool_call` (shipped v1.27.0)
- **openai** → inline `tool_calls: [{...}]` field inside the
  `data: {chunk}` frame at the moment of the tool-call request
- **anthropic** → `event: content_block_start` with
  `data: {type: "tool_use", ...}`

**Reasoning:** matches each dialect's adopter-SDK expectation
exactly. No founder-level policy needed; the adapter's per-
dialect tests pin the mapping.

### Q7 — Algebraic-policy preservation channel

The `enforcement_summary` + `runtime_warnings` + `step_audit`
side-channels surface per dialect:
- **axon** → fields on the `axon.complete` final frame (current)
- **openai** → custom `data: {"axon_metadata": {enforcement_summary:..., runtime_warnings:..., step_audit:...}}` frame
  EMITTED BEFORE `data: [DONE]`
- **anthropic** → `event: axon.metadata` frame emitted BEFORE
  `event: message_stop`

**Reasoning:** D4 wire byte-compat for the axon dialect is
preserved (no field movement). The other two dialects gain a
named extension surface that adopter SDKs ignore by default
(they don't know about `axon_metadata` / `axon.metadata`); SDK-
free clients that need the compliance data can opt-in via direct
SSE parsing. Vertical regulatory requirements (HIPAA audit /
PCI DSS Req 10 / FRE 502) preserved across every dialect.

---

## ▶ 2.1. Original open-questions catalog (now ratified)

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
| **33.z.k.a** | spec + diagnostic anchor over the current wire surface | ~600 | ✅ SHIPPED 2026-05-13 — commit 7ff1985; 4 tests verde forensic baseline |
| **33.z.k.b** | dialect AST + parser grammar `transport: sse(<dialect>)` + closed enum | ~600 | ✅ SHIPPED 2026-05-13 — closed-catalog `AXONENDPOINT_TRANSPORT_DIALECTS = {axon, openai, anthropic}` cross-stack; parser grammar extends `transport: sse` to `transport: sse(<dialect>)` with smart-suggest on unknown dialect + error on `json(<x>)`/`ndjson(<x>)` (only sse is parametrizable); 9 Rust frontend tests + 9 Python tests (cross-stack parity); 293 regression tests verde (Fase 31 corpus + frontend contract + 33.z.f drift gate) |
| **33.z.k.c** | effective-dialect resolver + Q1 default rules cross-stack | ~270 | ✅ SHIPPED 2026-05-14 — `resolve_effective_dialect(transport_dialect, has_algebraic_stream_effect)` pure 2-input total function cross-stack; closed-catalog output `{axon, openai, anthropic}`; Rule 1 explicit dialect wins; Rule 2 algebraic-effect → openai (Q1 default); Rule 3 type-annotation → axon (Q1 default); 7 Rust tests + 10 Python tests (parametric) all verde |
| **33.z.k.d** | WireFormatAdapter trait + AxonDialectAdapter (D6 backwards-compat baseline) | ~500 LOC | ✅ SHIPPED 2026-05-14 — new `axon-rs/src/wire_format/{mod,axon_dialect}.rs` ships the trait `WireFormatAdapter { dialect(), translate(&FlowExecutionEvent), flush_terminator() }` + closed-catalog factory `select_adapter(dialect, trace_id) -> Box<dyn WireFormatAdapter>` + the named `AxonDialectAdapter` that reproduces v1.27.1's inline `build_token_event` / `build_complete_event` / `build_tool_call_event` / `build_error_event` byte-identical (D6 anchor). FlowStart / StepStart / StepComplete silently consumed (preserved from v1.27.1 producer); StepToken/ToolCall/FlowComplete/FlowError translate to 1 wire event each. `flush_terminator()` returns empty (axon's terminator is in-line with FlowComplete). Pre-33.z.k.e/f, `select_adapter("openai" | "anthropic" | <unknown>)` defensively falls through to `AxonDialectAdapter` — the openai/anthropic arms flip in their sub-fases. 14 unit tests verde + 33.z lane regression sweep clean (33.z.k.a 4/4 + 33.z.k.1 5/5 + 33.z.c 16/16 + 33.z.d 2/2 + 33.z.e 10/10 + 33.z.g fuzz 16/16). |
| **33.z.k.e** | OpenAIDialectAdapter — Chat Completions streaming wire | ~590 LOC | ✅ SHIPPED 2026-05-14 — new `axon-rs/src/wire_format/openai_dialect.rs` matches OpenAI Chat Completions streaming wire verbatim per https://platform.openai.com/docs/api-reference/chat/streaming. Every frame is `data: {...}` (no `event:`), payload carries `{id, object: "chat.completion.chunk", created, model, choices: [{index, delta, finish_reason}]}`. axon → openai event mapping: FlowStart → role-marker `delta: {"role": "assistant"}`; StepStart/Complete silently consumed (no multi-step concept in OpenAI); StepToken → `delta: {"content": "<token>"}`; ToolCall → `delta: {"tool_calls": [{index, id, type: "function", function: {name, arguments}}]}` with synthesized stable call_id; FlowComplete → final chunk `delta: {}` + `finish_reason: "stop"`; FlowError → same with stop (OpenAI has no error finish_reason); flush_terminator emits Q7 axon_metadata frame + literal `data: [DONE]` sentinel. Response id stable across stream (`chatcmpl-axon-<trace_id_hex>`); model identifier captured from FlowStart.backend. **11 byte-exact tests verde** citing OpenAI spec verbatim per assertion: §1 dispatch, §2 role-marker, §3 content-delta, §4 silently-consumed multi-step, §5 finish_reason=stop, §6 axon_metadata+[DONE], §7 tool_calls.function shape, §8 canonical sequence emits 5 frames total, §9 id stable across stream, §10 model captured from backend. Pre-33.z.k.g this adapter doesn't yet reach the production SSE producer — 33.z.k.g wires `axon_server::execute_sse_handler` to use `select_adapter()` + adapter.translate() in the consumer loop. |
| **33.z.k.f** | AnthropicDialectAdapter — Messages streaming wire | ~570 LOC | ✅ SHIPPED 2026-05-14 — new `axon-rs/src/wire_format/anthropic_dialect.rs` matches Anthropic Messages streaming spec verbatim per https://docs.anthropic.com/en/api/messages-streaming. Structured W3C SSE with named events: `message_start` (announces msg id + role: assistant + model + initial usage) / `content_block_start` (per-block type: text or tool_use + index 0+) / `content_block_delta` (text_delta or input_json_delta) / `content_block_stop` / `message_delta` (final stop_reason + usage) / `message_stop` (terminator). axon → anthropic event mapping uses on-demand text-block management: text block lazy-opens on first StepToken, closes on StepComplete OR when ToolCall interleaves a tool_use block. Tool-use blocks emit 3-frame triad (start + input_json_delta + stop) per Anthropic spec. ToolCall mid-text-block closes the text block first (4-frame burst). FlowComplete emits message_delta only; message_stop emits from flush_terminator so Q7 axon.metadata can interpose. **11 byte-exact tests verde**: §1 dispatch, §2 message_start shape (role+model), §3 StepStart silently consumed (lazy block), §4 first StepToken opens text block + delta, §5 subsequent StepToken reuses block, §6 StepComplete closes block, §7 ToolCall standalone 3-frame triad, §8 ToolCall mid-text-block 4-frame burst, §9 FlowComplete emits message_delta NOT message_stop, §10 flush_terminator emits axon.metadata + message_stop in order, §11 block indices monotonic across stream. 33.z.k.d defensive-fallthrough assertion for `anthropic` flipped to assert new behavior. |
| **33.z.k.g.1** | producer-signature dialect threading scaffold | ~120 LOC | ✅ SHIPPED 2026-05-14 — `execute_sse_handler_inner` takes new `wire_dialect: String` parameter; `DynamicEndpointRoute` gains `transport_dialect: String` field (copied from AST); dynamic-route call site computes dialect via `resolve_effective_dialect(transport_dialect, has_algebraic_stream_effect)` + passes to handler; `/v1/execute/sse` legacy entrypoint passes "axon" (D6); spawned producer task clones dialect into closure. Adapter NOT YET constructed inside producer; consumer-loop refactor (replace inline `build_*_event` with `adapter.translate()`) deferred to 33.z.k.g.2. Compiles + all 33.z lanes regression-clean (33.z.k.a 4/4 + 33.z.k.d 14/14 + 33.z.k.e 11/11 + 33.z.k.f 11/11 + 33.z.k.1 5/5 + 33.z.c 16/16 + 33.z.d 2/2 + 33.z.e 10/10). |
| **33.z.k.g.2** | consumer-loop refactor — replace inline `build_*_event` with `adapter.translate()` + `build_complete_envelope_event()` + `flush_terminator()` | ~400 LOC | ⏳ pending — surgical refactor in `axon_server.rs` consumer loop (~250 LOC of inline emission to replace); must preserve byte-compat for axon dialect (33.z.k.a anchor + existing 33.z.d/c/e tests pin); add per-dialect integration tests verifying OpenAI/Anthropic wire bytes end-to-end via HTTP POST |
| **33.z.k.g.3** | tool-call interleaving per dialect (D11) wire-byte verification | ~200 LOC | ⏳ pending |
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
