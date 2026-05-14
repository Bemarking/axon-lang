# §Fase 33.z.k — Wire-format adapter cycle (v1.28.0 SHIPPED)

> **Status:** ✅ **CLOSED 2026-05-14** — all 15 sub-fases shipped.
> axon-lang v1.28.0 live cross-stack (crates.io + PyPI auto-publishing +
> GitHub Release published). axon-frontend v0.12.0 live on crates.io.
> The cycle's core promise delivered: algebraic-effect SSE is now
> a market-surpassing language primitive that adopter SDKs (litellm,
> langchain, vercel/ai, instructor, llama_index, anthropic-sdk,
> Moonshot Kimi, Zhipu GLM client libraries) consume verbatim with
> zero axon-specific awareness. Founder principle honored end-to-end:
> *"los algebraics effects SSE deben funcionar perfectamente y cumplir
> la promesa del paper... una primitiva cognitiva que supera lo que
> hoy ofrece el mercado en ese sentido."*
>
> **Sub-fases (15):** a, b, c, d, e, f, g.1, g.2, g.3, h, i, j, k, l, m
> **Test inventory:** 173 dedicated 33.z.k tests (135 Rust + 38 Python)
> across 14 test files + dedicated CI workflow.
> **D-letters:** D1-D12 ratificadas. **Q-letters:** Q1-Q7 ratificadas
> bloque ("Si") 2026-05-13 + Q3 catalog revision 2026-05-14
> (axon/openai/anthropic → axon/openai/kimi/glm/anthropic).
>
> **Follow-up:** axon-enterprise v1.19.0 catch-up release pending
> (lean — dep pin bump `axon-lang>=1.27.0` → `>=1.28.0`).
> **Cycle core promise delivered 2026-05-14 via 33.z.k.g.2** —
> algebraic-effect flows now emit OpenAI Chat Completions streaming
> bytes verbatim when POSTed against the dynamic-route handler. The
> founder's principle *"adopters never adapt to axon's wire; axon
> delivers the wire format their SDK ecosystem already parses"* is
> honored end-to-end. Adopter SDKs (litellm, langchain, vercel/ai,
> instructor, llama_index) parse the response verbatim with zero
> axon-awareness.
> Founder Q3 revision 2026-05-14: catalog expanded 3→5 (added kimi +
> glm as first-class entries — Bemarking AI's primary adopter
> pipelines through Moonshot Kimi K2.x + Zhipu ChatGLM-4.x).

---

## ⚠️ TIP — BRIEFING FOR NEXT SESSION (READ FIRST)

> If you are an agent resuming this cycle in a fresh session, READ
> THIS BEFORE TOUCHING ANY CODE. Every line below is a load-bearing
> constraint captured from the founder's intent + the cycle's
> architectural decisions already in production.

### Why this cycle exists

The user's adopter (Bemarking AI's Kivi product) reported on
2026-05-13 that **algebraic effects declared on tools** (the paper's
core promise) were emitting `Content-Type: application/json` instead
of streaming SSE. v1.27.1 (commit cb47879 ancestor) closed the
**route classifier** gap via D11 algebraic-effect override. But the
**wire FORMAT** the SSE producer emits is still `event: axon.token` +
`data: {step,token,...}` (W3C named events). Adopters expecting
OpenAI-style framing (`data: {"choices":[{"delta":{"content":...}}]}`
+ `data: [DONE]`) and Anthropic-style framing
(`event: content_block_delta` + `event: message_stop`) still face a
format mismatch.

The founder principle is non-negotiable:
> *"los algebraics effects SSE, deben funcionar perfectametne y
> cumplir la promesa del paper... una primitiva cognitiva que
> supera lo que hoy ofrece el mercado en ese sentido."*

This means: **adopters never adapt to axon's wire; axon delivers
the wire format their SDK ecosystem already parses.** The work is
NOT to satisfy one adopter — it is to make algebraic-effect SSE a
language primitive that surpasses what the market offers today.

### The critical bytes (33.z.k.g.2 is THE focus)

The remaining producer-loop refactor in `axon-rs/src/axon_server.rs`
is the LOAD-BEARING work. Lines of interest:

- **`execute_sse_handler_inner`** at `axon-rs/src/axon_server.rs:18687`
  is the SSE producer. It receives `wire_dialect: String` (added in
  33.z.k.g.1 but `#[allow(unused_variables)]` because the consumer
  loop doesn't dispatch on it yet).
- The **spawned consumer task** starts at `axon-rs/src/axon_server.rs:18766`
  (`tokio::spawn(async move { ... })`). The dialect is cloned into
  the closure via `wire_dialect_for_task` at line ~18761.
- The **consumer loop** runs from `axon-rs/src/axon_server.rs:18822`
  with `while let Some(event) = event_rx.recv().await`. Inside it,
  inline calls to `build_token_event` (~18839), `build_complete_event`
  (~19005), `build_error_event` (~19014, ~19068), `build_tool_call_event`
  (~19045) emit axon-named events directly.

**The refactor must:**

1. Construct the dialect adapter just before the loop:
   ```rust
   let mut wire_adapter =
       crate::wire_format::select_adapter(&wire_dialect_for_task, trace_id);
   ```

2. Replace each inline `tx.send(Ok(build_X_event(...)))` with an
   adapter dispatch loop:
   ```rust
   for wire_event in wire_adapter.translate(&event) {
       if tx.send(Ok(wire_event)).await.is_err() {
           cancel.cancel();
           break_to_outer_loop = true;
           break;
       }
   }
   ```
   Special-case `FlowComplete`: build a `CompleteEnvelope` from the
   accumulated state + call `wire_adapter.build_complete_envelope_event(&envelope)`
   instead of `translate(FlowComplete)`. This is how
   `enforcement_summaries` / `runtime_warnings` / `effect_policies`
   reach the wire byte-identical to v1.27.1 for axon dialect.

3. After the loop terminates, emit the dialect-specific terminator:
   ```rust
   for wire_event in wire_adapter.flush_terminator() {
       let _ = tx.send(Ok(wire_event)).await;
   }
   ```
   - axon: empty (terminator in-line with axon.complete)
   - openai: 1 axon_metadata frame + `data: [DONE]`
   - anthropic: 1 axon.metadata frame + `event: message_stop`

4. The "executor channel closed without terminator" defensive
   fallback at ~19063 must also route through the adapter (synthesize
   a `FlowExecutionEvent::FlowError` and call `adapter.translate(&event)`).

### What MUST stay green during the refactor

The axon-dialect MUST emit byte-identical output to v1.27.1. These
test files pin that invariant — they're your safety net:

- `axon-rs/tests/fase33z_k_a_diagnostic_anchor.rs` — 4 tests
  pinning canonical Step + stub → 1 axon.token + 1 axon.complete
  + W3C named-events catalog of 4 events
- `axon-rs/tests/fase33z_d_parity_corpus.rs` — 50-fixture sync↔async
  parity drift gate
- `axon-rs/tests/fase33x_real_streaming_diagnostic.rs` — checks
  `axon.complete.enforcement_summary` + `step_audit` populate
- `axon-rs/tests/fase33z_c_default_on_and_tool_call.rs` — 16 tests
  including canonical Step byte-compat + tool_call SSE wire emission
- `axon-rs/tests/fase33z_e_parity_gate.rs` — 10 tests grep-gating
  the 9 retired symbols (don't re-introduce any)
- `axon-rs/tests/fase33z_production_fuzz.rs` — ~5,100 LCG iters
- `axon-rs/tests/fase33z_k_1_algebraic_override.rs` — 5 tests
  pinning the D11 override behavior
- `axon-rs/tests/fase33z_k_e_openai_dialect_adapter.rs` — 11 byte-
  exact tests against OpenAI spec (will continue passing because
  the adapter unit tests are isolated)
- `axon-rs/tests/fase33z_k_f_anthropic_dialect_adapter.rs` — 11 byte-
  exact tests against Anthropic spec

After the refactor, add NEW integration tests that drive each
dialect through a real HTTP POST and verify the wire bytes:

- `axon-rs/tests/fase33z_k_g_e2e_openai_wire.rs` — POST to a route
  declared with `transport: sse(openai)`; assert response body
  contains `data: [DONE]` + at least one `data: {...,"choices":[{"delta":{"content":"..."}}]}`
  frame; assert no `event: axon.token` lines.
- `axon-rs/tests/fase33z_k_g_e2e_anthropic_wire.rs` — POST to a
  route declared with `transport: sse(anthropic)`; assert body
  contains `event: message_start` + `event: content_block_delta` +
  `event: message_stop`; assert no `data: [DONE]` sentinel.
- `axon-rs/tests/fase33z_k_g_e2e_axon_byte_compat.rs` — POST to a
  route with `transport: sse(axon)` AND a route with bare
  `transport: sse` for a type-annotation-only flow; assert byte-
  identical output (D6 invariant).
- `axon-rs/tests/fase33z_k_g_e2e_kimi_glm_dispatch.rs` — POST to
  routes declared with `transport: sse(kimi)` and `transport: sse(glm)`;
  assert the wire is canonical-OpenAI-bytes (same shape as `sse(openai)`).

### Decision-density landmines to avoid

1. **`event_id` confusion**: the old inline helpers took `event_id`
   from the outer scope. AxonDialectAdapter has its OWN internal
   counter starting at 1. After the refactor, drop the outer
   `event_id` variable entirely — the adapter owns IDs.

2. **`ServerExecutionResult` vs `CompleteEnvelope`**: the old code
   built a `ServerExecutionResult` struct just before calling
   `build_complete_event`. The new adapter takes a `CompleteEnvelope`
   defined in `axon-rs/src/wire_format/mod.rs`. They have the same
   FIELDS but different types. Build a `CompleteEnvelope` from the
   accumulated state at FlowComplete time.

3. **Side-channel timing**: `enforcement_summaries`, `runtime_warnings`,
   and the (Fase 33.e) `effect_policies` resolved at flow-spawn time
   are read AT FlowComplete from `Arc<Mutex<...>>` shared with the
   dispatcher. Keep that order intact — read AFTER FlowComplete,
   BEFORE building CompleteEnvelope.

4. **Cancel-on-disconnect semantics** (D3 invariant): the current
   StepToken match arm catches `tx.send(...).await.is_err()` and
   calls `cancel.cancel()` then `break;`. After the refactor, EVERY
   adapter-emitted frame's `.send()` call must respect this — if
   `.send()` fails, fire cancel + break. The OpenAI adapter emits
   MULTIPLE frames for some events (e.g. role-marker + content
   delta on first FlowStart+StepToken sequence) — each one needs
   the cancel-on-err check.

5. **Defense-in-depth terminator** (~19063): when the executor
   channel closes without a FlowComplete, the current code emits
   `build_error_event` directly. The refactor synthesizes a
   `FlowError` and dispatches via the adapter — different dialects
   handle FlowError differently (anthropic emits message_delta;
   openai emits final chunk with finish_reason).

### Architectural decisions LOCKED IN (do not relitigate)

From the Q1-Q7 ratifications (founder bloque "Si" 2026-05-13):

- **Q1**: Algebraic-effect-driven default. `effects: <stream:...>`
  on a tool → openai default. Type-annotation only → axon default.
  D3 `transport: json` explicit opt-out STILL wins.
- **Q2**: Parametrized grammar `transport: sse(<dialect>)`. NOT
  a new `wire_format:` field. Reuses the existing axonendpoint
  field's value-parsing path.
- **Q3 (revised 2026-05-14)**: 5 dialects {axon, openai, kimi, glm,
  anthropic}. Kimi + GLM dispatch to `OpenAIDialectAdapter` (shared
  wire). NO open-set pluggability.
- **Q4**: Per-dialect native terminators. NO unified terminator.
- **Q5**: Axon dialect backwards-compat is INDEFINITE. Never
  deprecate it. It's the W3C-correct baseline.
- **Q6**: Per-dialect tool-call interleaving. Already implemented
  in each adapter's `translate(FlowExecutionEvent::ToolCall)` arm
  — OpenAI inlines `tool_calls[]` in the chunk delta; Anthropic
  emits a 3-frame tool_use block triad.
- **Q7**: Algebraic-policy preservation channel — axon embeds on
  `axon.complete`; openai emits `data: {"axon_metadata":{...}}`
  BEFORE `data: [DONE]`; anthropic emits `event: axon.metadata`
  BEFORE `event: message_stop`. 33.z.k.h will populate the actual
  data (today the openai/anthropic adapters emit empty placeholders).

### Current production state (after commits 7ff1985 → cb47879)

- `transport: sse(<dialect>)` grammar accepts {axon, openai, kimi,
  glm, anthropic} cross-stack at parse time.
- `resolve_effective_dialect(transport_dialect, has_algebraic_stream_effect)`
  returns the right dialect (Q1 default rules).
- `WireFormatAdapter` trait + 3 adapters (axon/openai/anthropic)
  pass byte-exact unit tests against their respective wire specs.
- `select_adapter()` dispatches all 5 dialect strings correctly
  (kimi + glm → OpenAIDialectAdapter; canonical openai → same).
- `DynamicEndpointRoute` carries `transport_dialect` field.
- `execute_sse_handler_inner` has `wire_dialect` parameter threaded
  but NOT YET CONSUMED inside the consumer loop.
- The wire emitted by the SSE producer is still axon-named events
  for all dialects (because the inline `build_*_event` helpers
  remain). This is the gap 33.z.k.g.2 closes.

### Suggested execution order for next session

1. ~~**33.z.k.g.2**: Consumer-loop refactor~~ ✅ SHIPPED 2026-05-14.
2. ~~**33.z.k.g.3**: tool-call interleaving wire-byte verification~~
   ✅ SHIPPED 2026-05-14 (10 new tests in
   `fase33z_k_g_3_tool_call_interleaving.rs` + helper hardening for
   UTF-8 multibyte payloads).
3. ~~**33.z.k.h**: Wire the side-channels (enforcement_summaries /
   runtime_warnings / step_audit) into OpenAI's axon_metadata frame
   + Anthropic's axon.metadata frame~~ ✅ SHIPPED 2026-05-14 (12 new
   tests in `fase33z_k_h_metadata_population.rs` + envelope stash in
   both adapters + terminal_reason discriminator + cross-dialect
   parity E2E).
4. ~~**33.z.k.i**: Drift gate across the dialect catalog~~ ✅ SHIPPED
   2026-05-14 (38 tests across Rust + Python cross-stack mirror;
   10 closure decisions pinned; snapshot-driven drift detection).
5. ~~**33.z.k.j**: D12 production-grade fuzz × dialects~~ ✅ SHIPPED
   2026-05-14 (18 tests, ~3 350 LCG iters, 9 invariant sections;
   collateral defensive hardening on anthropic flush_terminator).
6. ~~**33.z.k.k**: CI workflow~~ ✅ SHIPPED 2026-05-14
   (`.github/workflows/fase_33z_k_wire_format_adapter.yml` — 7
   parallel test lanes + summary aggregator locking the full
   Q1-Q7 + D1-D12 contract at PR time).
7. ~~**33.z.k.l**: Adopter docs MIGRATION_v1.28 + ADOPTER_STREAMING
   §dialects~~ ✅ SHIPPED 2026-05-14 (`MIGRATION_v1.28.md` 834 LOC
   + 6 scenarios A-F + `ADOPTER_STREAMING.md` +435 LOC new
   §Multi-dialect wire format section).
8. ~~**33.z.k.m**: Coordinated release v1.28.0 cross-stack~~ ✅ SHIPPED
   2026-05-14 — axon-frontend 0.12.0 + axon-lang 1.28.0 live on
   crates.io + GitHub Release published + PyPI auto-publish workflow
   fired. axon-enterprise v1.19.0 catch-up tracked separately as a
   lean follow-up.

**Cycle CLOSED 2026-05-14.** All 15 sub-fases SHIPPED end-to-end.

### Commit reference (in order, all on origin/master)

| Commit | Sub-fase |
|---|---|
| `7ff1985` | 33.z.k.a anchor + Q1-Q7 ratification |
| `419ce16` | 33.z.k.b grammar cross-stack |
| `c55d1d8` | 33.z.k.c resolver |
| `92fa44a` | 33.z.k.d trait + AxonDialectAdapter |
| `02c1c11` | 33.z.k.e OpenAIDialectAdapter |
| `021004a` | 33.z.k.f AnthropicDialectAdapter |
| `cb47879` | 33.z.k.g.1 producer-signature scaffold |
| `373dc07` | Q3 revision: kimi + glm added |
| `39befa4` | 33.z.k.g.2 consumer-loop refactor + 4 E2E test packs |
| `a46f0e0` | 33.z.k.g.3 D11 tool-call interleaving wire-byte verification |
| `a7844f8` | 33.z.k.h algebraic-policy surfacing per dialect (populated metadata frames) |
| `c76ad34` | 33.z.k.i dialect catalog drift gate (Rust + Python cross-stack mirror) |
| `2594d77` | 33.z.k.j D12 production-grade fuzz × dialects + anthropic defensive close |
| `7dcd689` | 33.z.k.k dedicated CI workflow (7 parallel lanes + summary) |
| `baf9f30` | 33.z.k.l adopter docs MIGRATION_v1.28.md + ADOPTER_STREAMING §Multi-dialect wire format |
| `b65edab` + `bde6e52` | 33.z.k.m axon-frontend v0.12.0 release (Cargo.toml + dep pin + Cargo.lock) |
| `96e213a` | 33.z.k.m coordinated cross-stack bump v1.27.1 → v1.28.0 (bump-my-version minor) |
| `488c786` | 33.z.k.m axon-rs/Cargo.lock refresh to 1.28.0 |
| _(this commit)_ | 33.z.k.m close-out — plan vivo + memory snapshot |

### The single test that proves everything works end-to-end

After 33.z.k.g.2 lands, this is the test that will close the cycle's
core promise. Write it in `axon-rs/tests/fase33z_k_g_e2e_openai_wire.rs`:

```rust
#[tokio::test]
async fn kivi_shape_emits_openai_wire_bytes_end_to_end() {
    let src = "tool chat_token_stream { description: \"S\" \
               effects: <stream:drop_oldest> }\n\
        flow Chat() -> Unit {\n\
            step Generate { ask: \"hi\" apply: chat_token_stream output: Stream<Token> }\n\
        }\n\
        axonendpoint ChatEndpoint { method: POST path: \"/chat\" execute: Chat }";
    let app = build_router(server_cfg());
    assert_eq!(deploy(app.clone(), src).await, StatusCode::OK);
    let (status, ct, body) = post_no_accept(app, "/chat").await;
    assert_eq!(status, StatusCode::OK);
    assert!(ct.contains("text/event-stream"));
    // The wire is OpenAI-style (Q1 default for algebraic-effect flows).
    assert!(body.contains("\"object\":\"chat.completion.chunk\""));
    assert!(body.contains("\"delta\":{\"role\":\"assistant\"}"));
    assert!(body.contains("\"content\":\""));
    assert!(body.contains("\"finish_reason\":\"stop\""));
    assert!(body.contains("data: [DONE]"));
    // And NO axon-named events (the wire is now OpenAI-style).
    assert!(!body.contains("event: axon.token"));
}
```

When THAT test passes, the paper's promise of algebraic-effect SSE
as a market-surpassing language primitive is delivered.

---
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
| **33.z.k.g.2** | consumer-loop refactor — replace inline `build_*_event` with `adapter.translate()` + `build_complete_envelope_event()` + `flush_terminator()` | ~520 LOC | ✅ SHIPPED 2026-05-14 — surgical refactor in `axon-rs/src/axon_server.rs` `execute_sse_handler_inner`. The producer's spawned consumer loop now constructs `wire_adapter = wire_format::select_adapter(&wire_dialect_for_task, trace_id)` once per request + dispatches every `FlowExecutionEvent` through `adapter.translate()` (StepToken / FlowStart / StepStart / StepComplete / FlowError / ToolCall) or `adapter.build_complete_envelope_event(&envelope)` (FlowComplete). After the loop terminates, `adapter.flush_terminator()` emits per-dialect terminator frames (axon: empty; openai: Q7 axon_metadata + `data: [DONE]`; anthropic: Q7 axon.metadata + `event: message_stop`). The defense-in-depth "executor channel closed without terminator" fallback synthesizes a `FlowError` + dispatches through the same adapter so every dialect surfaces a well-formed terminator. Cancel-on-disconnect (D3) preserved per-frame: each adapter-emitted wire event's `.send().await.is_err()` check cancels the producer + breaks the loop. The `None` arm (flow-not-deployed) also routes through the adapter for dialect consistency. Retired 4 inline helpers (`build_token_event` / `build_complete_event` / `build_tool_call_event` / `build_error_event`) — closed-catalog wire emission now LIVES in `axon-rs/src/wire_format/`. **+13 new E2E integration tests** across 4 new packs: `fase33z_k_g_e2e_openai_wire` (4 tests pinning Kivi-shape → OpenAI Chat Completions wire bytes verbatim + Q7 axon_metadata precedence + closed-catalog mutex) + `fase33z_k_g_e2e_anthropic_wire` (3 tests pinning `transport: sse(anthropic)` → Anthropic Messages streaming wire + Q7 axon.metadata → message_stop ordering + openai-shape mutex) + `fase33z_k_g_e2e_axon_byte_compat` (3 tests pinning D6 byte-equivalence between bare `transport: sse` + explicit `transport: sse(axon)` for type-annotation flows + Q5 escape valve for algebraic-effect flows) + `fase33z_k_g_e2e_kimi_glm_dispatch` (3 tests pinning Q3 revision: `sse(kimi)` + `sse(glm)` both dispatch to `OpenAIDialectAdapter` byte-identically to canonical `sse(openai)`). Inverted 2 anchor tests in lockstep: `fase33z_k_a_diagnostic_anchor::s2` (now `s2_algebraic_effect_emits_openai_wire_post_33_z_k_g_2`) + `fase33z_k_1_algebraic_override::s2` (now `s2_kivi_shape_wire_body_emits_openai_chunks_and_done_sentinel`). Updated 6 algebraic-effect test fixtures to use `transport: sse(axon)` explicit so 33.x.b / 33.x.d / 33.x_real_streaming_diagnostic / 33.z.c verticals / 33.e / 33.sse_full_body_diagnostic continue to surface axon-named-event wire shape (Q5 escape valve). **Zero regressions** across full test corpus: 1743 axon-rs lib tests + ~700 integration tests + 13 new E2E tests all green. **The single test that proves everything** (per the TIP's load-bearing anchor): `kivi_shape_emits_openai_wire_bytes_end_to_end` PASSES — the canonical Kivi-shape (tool with `effects: <stream:drop_oldest>` + bare axonendpoint) POSTed against `/chat` returns `Content-Type: text/event-stream` with body containing `"object":"chat.completion.chunk"` + `"delta":{"role":"assistant"}` + `"content":"(stub)"` + `"finish_reason":"stop"` + `data: [DONE]` and NO `event: axon.token` line — the paper's promise of algebraic-effect SSE as a market-surpassing language primitive is delivered. |
| **33.z.k.g.3** | tool-call interleaving per dialect (D11) wire-byte verification | ~870 LOC | ✅ SHIPPED 2026-05-14 — new `axon-rs/tests/fase33z_k_g_3_tool_call_interleaving.rs` pins the D11 arrival-order invariant byte-exact across all 3 dialect adapters. Drives each adapter with a canonical agentic-AI event stream (`StepToken("Pensando...") → ToolCall(search, args) → StepToken("Encontré ") → StepToken("resultados.")`) + asserts per-dialect frame counts + names + payload contents + closed-catalog mutex. **10 new tests** across 6 sections: §1 axon arrival-order interleaving + back-to-back ToolCalls (2 tests); §2 openai inline `tool_calls` delta + monotonic synthesized `call_<trace_hex>_<N>` IDs (2 tests); §3 anthropic 3-frame tool_use triad mid-text-block closes text block first (4-frame burst) + content_block index monotonicity (0/text → 1/tool_use → 2/text) + back-to-back ToolCalls each get own triad (3 tests); §4 cross-dialect arrival-order signature invariant (T-X-T-T projects byte-equivalently onto all 3 dialects modulo framing); §5 Q3 kimi/glm/openai byte-identity for tool-call wire; §6 closed-catalog mutex (no dialect's tool-call surface leaks into another). Helper hardening: `event_data` now decodes Rust byte-string literal `\xHH` escapes so multibyte UTF-8 tokens round-trip faithfully (the existing 33.z.k.{d,e,f} unit packs assumed ASCII-only payloads — this pack tests with "Encontré" to exercise the path). Stub backend hermeticity preserved: tests drive adapters directly because production `stub` backend signals `FinishReason::Stop` unconditionally (never emits `FlowExecutionEvent::ToolCall`); real-upstream E2E lives in the opt-in `AXON_RUN_REAL_PROVIDER_TEST` lane (33.x.j precedent). Zero regressions across 83 test binaries. |
| **33.z.k.h** | algebraic-policy surfacing per dialect (D4 — counters, warnings, audit) | ~890 LOC | ✅ SHIPPED 2026-05-14 — closes Q7's "populated metadata frame" promise across both non-axon dialects. Pre-33.z.k.h, openai's `axon_metadata` + anthropic's `event: axon.metadata` emitted EMPTY placeholders (`enforcement_summary: {}`, `runtime_warnings: []`, `step_audit: []`) regardless of how the flow ran; sub-fase 33.z.k.h wires the algebraic-policy side-channels through. **Changes:** (1) `CompleteEnvelope` gains a `step_audit_records: Vec<StepAuditRecord>` field; (2) producer in `axon_server.rs` reads `step_audit_records_for_consumer` UNCONDITIONALLY (was previously gated behind `replay_ctx.is_some()`) so the envelope always has the data, replay-log write reuses the already-read vec; (3) `OpenAIDialectAdapter` + `AnthropicDialectAdapter` both override `build_complete_envelope_event` to **stash the envelope** into adapter state (new `stashed_envelope: Option<CompleteEnvelope>` field); (4) `flush_terminator()` calls `self.build_axon_metadata_frame()` which reads the stashed envelope + emits a populated payload with `{trace_id, flow, backend, success, steps_executed, tokens_input, tokens_output, latency_ms, stream_policies, enforcement_summary, runtime_warnings, step_audit, terminal_reason}`; (5) D4 byte-compat preserved — empty algebraic-policy fields elided per the same pattern as the axon adapter; (6) new `TerminalReason` enum on anthropic adapter (parallel to openai) — `terminal_reason: "stop" \| "error" \| "none"` discriminator on every metadata frame so adopters can detect aborted streams. **Test coverage** (`fase33z_k_h_metadata_population.rs`, 12 tests): §1 openai full-envelope projection byte-exact + §2 anthropic same coverage + `type: axon.metadata` wrapper + §3 empty-fields elision (D4) for both dialects + §4 default path (no envelope stashed → terminal_reason only) + §5 terminal_reason discriminator covers stop/error/none + §6 E2E HTTP POST surfaces populated `enforcement_summary` + `stream_policies` + `step_audit` on openai wire + §7 same coverage via `transport: sse(anthropic)` + §8 cross-dialect parity (openai + anthropic surface byte-equivalent algebraic-policy data modulo framing). **Vertical-regulator audit unlock**: adopters on openai/anthropic wires now have a uniform surface satisfying Banking PCI DSS Req 10 / Government FedRAMP AU-2 / Legal FRE 502 / Medicine 21 CFR Part 11 §11.10 per-step provenance requirements — previously available only on the axon dialect via `axon.complete.enforcement_summary`. **Fixture update**: `fase33z_k_g_e2e_kimi_glm_dispatch::kimi_glm_openai_dialects_dispatch_to_same_adapter` strip helper extended to also strip `latency_ms` + per-step `timestamp_ms` (now part of the populated metadata frame). Zero regressions across full suite. |
| **33.z.k.i** | drift gate over the dialect catalog | ~770 LOC | ✅ SHIPPED 2026-05-14 — closed-catalog invariant test pack fires loudly on any drift in the 5-entry dialect catalog `{axon, openai, kimi, glm, anthropic}`. **38 tests across 2 files** (cross-stack mirror): `axon-rs/tests/fase33z_k_i_dialect_catalog_drift_gate.rs` (19 Rust tests) + `tests/test_fase33z_k_i_dialect_catalog_drift_gate.py` (19 Python tests). Both files hardcode the same founder-ratified Q3 snapshot as a `CANONICAL_DIALECT_SNAPSHOT` constant; any drift in EITHER stack's catalog fails the corresponding gate. **Pinned invariants** (10 closure decisions): (1) cardinality exactly 5; (2) membership matches snapshot verbatim; (3) no duplicates; (4) cross-stack equality Python↔Rust; (5) `select_adapter` totality over catalog (no panic + no defensive-axon-fallback for legit members); (6) defensive fallthrough to axon for unknown strings; (7) explicit dispatch table `axon→axon, openai→openai, kimi→openai, glm→openai, anthropic→anthropic` (Q3 dispatch invariant); (8) exactly 3 distinct adapter implementations (kimi+glm dispatch to OpenAIDialectAdapter); (9) every adapter's `dialect()` return is a catalog member; (10) `resolve_effective_dialect` totality + Q1 Rule 2/Rule 3 pinned. Plus: per-dialect mutual-exclusion wire signatures (axon W3C named events; openai chat.completion.chunk + [DONE]; anthropic message_start/content_block_*/message_stop) — no signature leaks across dialects. Plus: `flush_terminator` frame counts pinned per dialect (axon=0, openai=2, anthropic=2). Plus: `CompleteEnvelope` field-set lock (compile-time pin via constructor-with-every-field at the test site). Plus: parametric coverage `5 dialects × 2 algebraic booleans = 10 explicit-wins assertions` on Python side. Adding a 6th dialect requires updating the snapshot in BOTH files plus 9 downstream sites enumerated in the snapshot comment block. Zero regressions across full Rust + Python suite. |
| **33.z.k.j** | D12 production-grade fuzz × dialects | ~970 LOC | ✅ SHIPPED 2026-05-14 — stochastic coverage layer above the deterministic 33.z.k.{d,e,f,g.3,h,i} pin-tests. New `axon-rs/tests/fase33z_k_j_dialect_fuzz.rs` ships **~3 350 deterministic LCG iters across 18 tests in 9 sections**, hand-rolled LCG (Knuth/MMIX constants, mirror of `fase33z_production_fuzz.rs` idiom — zero external deps). Sections: §1 adapter totality across 3 dialects × 200 iters (random 1-30 length event streams; every frame parses as JSON OR is the `[DONE]` sentinel); §2 closed-catalog event-name vocabulary per dialect (axon: 4-entry `{axon.token, axon.complete, axon.tool_call, axon.error}`; openai: empty — all frames are `data:`-only; anthropic: 7-entry `{message_*, content_block_*, axon.metadata}`); §3 cross-dialect arrival-order signature invariant (300 iters of random T-X-T-X... sequences project byte-equivalently onto all 3 dialects modulo framing); §4 anthropic content_block lifecycle (300 iters — every start has matching stop, indices monotonic, no orphan blocks); §5 OpenAI tool_call_id monotonicity (200 iters — `call_<trace_hex>_<N>` IDs strictly increasing per request); §6 CompleteEnvelope round-trip projection (3 dialects × 300 iters = 900 iters — random envelopes with 4 independent algebraic-policy fields populated/empty round-trip byte-exact onto metadata frames with D4 elision); §7 determinism across repeats (3 dialects × 200 iters × 3 repeats — same input → same wire bytes modulo timestamps/created/message.id); §8 iter-count meta-pin (prevents accidental fuzz shrinkage); §9 anthropic flush_terminator defensive close on orphan text block. **Collateral hardening:** `AnthropicDialectAdapter::flush_terminator` now defensively closes any orphan text block before emitting the terminator — Anthropic spec requires every `content_block_start` balanced by `content_block_stop`; in production the producer guarantees a terminal event closes blocks, but library users driving the adapter directly (test harnesses, future producers, direct integrations) can't be assumed to respect that contract. The defensive close is a no-op on well-formed inputs (frame count stays exactly 2). **Generator honesty:** `gen_random_event_stream` always appends a terminal event when the random loop didn't emit one — matches the producer contract `server_execute_streaming` guarantees in production. Zero regressions across full Rust suite. |
| **33.z.k.k** | dedicated CI workflow extension | ~260 LOC | ✅ SHIPPED 2026-05-14 — new `.github/workflows/fase_33z_k_wire_format_adapter.yml`. **8 jobs (7 parallel test lanes + 1 summary aggregator)** locking every sub-fase's contract at PR time so adopter-facing regressions surface BEFORE a release ever ships. Lane structure: (1) `anchors-and-overrides` — 33.z.k.a forensic anchor + 33.z.k.1 algebraic-effect override; (2) `cross-stack-rust` — 33.z.k.b grammar + 33.z.k.c resolver (axon-frontend workspace) + 33.z.k.i drift gate (axon-rs); (3) `cross-stack-python` — 33.z.k.b + 33.z.k.c + 33.z.k.i Python mirrors (pytest); (4) `dialect-adapters` — 33.z.k.{d,e,f} adapter unit tests (38 byte-exact translation tests); (5) `wire-e2e` — 33.z.k.g 4 dialect E2E packs + 33.z.k.g.3 tool-call interleaving (23 tests); (6) `metadata-population` — 33.z.k.h algebraic-policy surfacing (12 tests including 3 HTTP E2E cross-dialect parity); (7) `dialect-fuzz` — 33.z.k.j D12 ~3 350 LCG iters across 18 tests / 9 invariant sections; (8) `summary` — aggregates all lanes via `needs:` so the master CI status check is single-source-of-truth for the cycle's contract. **Test inventory locked**: 135 Rust + 38 Python = 173 dedicated 33.z.k tests across 14 test files + 1 CI workflow. Setup: `dtolnay/rust-toolchain@stable` + `Swatinem/rust-cache@v2` per Rust lane; `actions/setup-python@v5` with python 3.12 for Python lane. Triggers: `push: master` + `pull_request: master` + `workflow_dispatch`. `permissions: contents: read` (no write access — read-only CI). YAML syntax validated via `yaml.safe_load`. Every test path referenced in the workflow exists on disk (18/18 verified). Summary lane prints the full Q1-Q7 + D1-D12 contract honored + test inventory + founder principle verbatim. |
| **33.z.k.l** | adopter docs — `MIGRATION_v1.28.md` + `ADOPTER_STREAMING.md` § dialects | ~1180 LOC | ✅ SHIPPED 2026-05-14 — **new `docs/MIGRATION_v1.28.md`** (834 LOC, 12 H2 sections): TL;DR explicit-about-wire-flip + "what changed" matrix (28 rows comparing v1.27.0 vs v1.28.0 across every surface) + architectural arc (founder principle verbatim + the open-set vs closed-catalog trade-off + Q5 escape valve rationale) + **6 worked scenarios A-F**: (A) algebraic-effect flow + adopter SDK consumption with litellm/vercel-ai/instructor recipes; (B) preserving W3C-named axon dialect via `transport: sse(axon)` Q5 escape valve; (C) Anthropic Claude target via `sse(anthropic)` with python-anthropic recipe + tool-call interleaving (3-frame triad); (D) Moonshot Kimi K2.x + Zhipu ChatGLM-4.x targets via `sse(kimi)`/`sse(glm)` with openai-sdk recipe; (E) consuming Q7 `axon_metadata` extension frame for vertical-regulator audit with Python `httpx` recipes for both openai + anthropic dialects + 4-vertical audit-unlock mapping; (F) downstream crate integration with the public `WireFormatAdapter` trait API including a minimal-SSE-producer example + 9-site-update checklist for adding a 6th dialect. Backwards compatibility matrix (12 surfaces). What this release does NOT change (10 surfaces). Where to file bugs per-symptom (8 routing entries). See-also pointers to ADOPTER_STREAMING + plan vivo + CI workflow. **Updated `docs/ADOPTER_STREAMING.md`** (+435 LOC, new `## Multi-dialect wire format (Fase 33.z.k, v1.28.0+)` section inserted before `## Where to file bugs`): Q1-Q7 ratification table mapped 1:1 to adopter-observable behavior; per-dialect wire shape reference (axon + openai + anthropic verbatim wire bodies with byte-exact illustrative examples); decision tree (which dialect for which adopter SDK target); 4 canonical adopter recipes per regulated vertical (Banking PCI DSS / Government FedRAMP / Legal FRE 502 / Medicine HIPAA + 21 CFR Part 11) with full `.axon` source + the corresponding `axon_metadata` audit hook explanation; tool-call interleaving across dialects (canonical T → X → T → T sequence shown verbatim in all 3 dialects' wire); closed-catalog mutex (D11 final invariant); D-letters mapped to adopter-observable behavior (D1-D12 table with test pack citations); public adapter API reference (`WireFormatAdapter` trait + `select_adapter` factory + `CompleteEnvelope` struct); migration scenarios pointer to MIGRATION_v1.28.md. Both docs cross-reference each other + the plan vivo + the CI workflow + the 173 dedicated 33.z.k tests. Honest about the wire-flip risk + 100% explicit about Q5 escape valve. |
| **33.z.k.m** | coordinated release v1.28.0 cross-stack | release | ✅ SHIPPED 2026-05-14 — **axon-lang v1.28.0 live end-to-end**: (1) axon-frontend 0.11.2 → **0.12.0** on crates.io (new public surface: `AXONENDPOINT_TRANSPORT_DIALECTS` const + `resolve_effective_dialect` function + `AxonEndpointDefinition.transport_dialect` AST field — commits `b65edab` + `bde6e52` + tag `axon-frontend-v0.12.0`); (2) axon-lang Python 1.27.1 → **1.28.0** via `bump-my-version bump minor` (cross-stack atomic update: pyproject.toml + axon/__init__.py + axon-rs/Cargo.toml + tests/test_cli_mvp_smoke.py + tests/test_frontend_contract_golden.py — commit `96e213a`); (3) axon-rs/Cargo.lock refreshed to 1.28.0 (commit `488c786`); (4) axon-lang dep pin `axon-frontend = "=0.11.2"` → `"=0.12.0"` lockstep with the frontend bump; (5) tags `v1.28.0` + `rust-v1.28.0` + `axon-frontend-v0.12.0` pushed to origin/master; (6) **cargo publish axon-frontend 0.12.0** on crates.io (Packaged 31 files, 828.6KiB compressed to 148.3KiB, Uploaded + Verified + Published); (7) **cargo publish axon-lang 1.28.0** on crates.io (Uploaded + Published); (8) **GitHub Release v1.28.0** published with content-first notes (~270-line release notes covering Q1-Q7 ratifications + per-dialect wire shape + adopter SDK consumption recipes + Q7 vertical-regulator audit unlock table + Q5 escape valve + cycle-status sub-fase table + honest scope statement); (9) **PyPI Publish workflow auto-fired** on `release:published` event (queued + completed without manual draft-toggle recovery this cycle). axon-enterprise v1.19.0 catch-up tracked separately (lean — `axon-lang>=1.27.0` → `>=1.28.0` dep pin bump on enterprise repo). |

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
