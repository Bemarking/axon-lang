# AXON Migration Guide — v1.27.0 → v1.28.0

> **Scope:** the Fase 33.z.k *Wire-format adapter* cycle — the closed-
> catalog 5-dialect surface for SSE wire format `{axon, openai, kimi,
> glm, anthropic}`. v1.28.0 ships the language-level capability for
> adopter SDKs (litellm, langchain, vercel/ai, instructor, llama_index,
> anthropic-sdk, openai-sdk, moonshotai/kimi, zhipu/glm) to consume
> axon's streaming output **verbatim, with zero axon-specific
> awareness**. The founder principle: *"los algebraics effects SSE
> deben funcionar perfectamente y cumplir la promesa del paper... una
> primitiva cognitiva que supera lo que hoy ofrece el mercado en ese
> sentido."*
>
> **TL;DR:** v1.28.0 is **adopter-visible on the wire** for flows that
> declare `effects: <stream:<policy>>` on a tool — those flows now
> default to the **openai dialect** (`data: {"choices":[...]}` chunks
> + `data: [DONE]` sentinel) instead of the W3C-named axon dialect
> (`event: axon.token` + `event: axon.complete`). Flows with only
> `output: Stream<T>` type annotation continue to default to the
> **axon dialect** byte-identical to v1.27.0 (D6 backwards-compat
> indefinite). Adopters who want to FORCE the axon dialect on
> algebraic-effect flows declare `transport: sse(axon)` explicitly
> — Q5 escape valve. New `axon_metadata` (openai) / `event:
> axon.metadata` (anthropic) extension frames surface every
> algebraic-policy side-channel (enforcement_summary,
> runtime_warnings, step_audit, stream_policies) verbatim on the
> non-axon dialects — vertical-regulator audit data
> (PCI DSS Req 10 / FedRAMP AU-2 / FRE 502 / 21 CFR Part 11 §11.10)
> uniformly available across all 5 dialects.

---

## What changed in v1.28.0

| Surface | v1.27.0 | v1.28.0 |
|---|---|---|
| Dialect catalog | (no dialect concept) — all SSE used W3C-named events | **Closed 5-dialect catalog** `{axon, openai, kimi, glm, anthropic}` (Q3 revision 2026-05-14) |
| Default wire for algebraic-effect flows (`tool T { effects: <stream:<policy>> }` + `step S { apply: T }`) | W3C-named axon events (`event: axon.token` + `event: axon.complete`) | **OpenAI Chat Completions streaming wire** (`data: {"object":"chat.completion.chunk","choices":[...]}` + `data: [DONE]`) per the **Q1 ratification** (algebraic-effect-driven default — the strongest semantic commitment maps to the LLM ecosystem's de-facto wire) |
| Default wire for type-annotation-only flows (`step S { output: Stream<Token> }` without an algebraic-effect tool) | W3C-named axon events | **Byte-identical** — axon dialect (Q1 Rule 3: type-annotation-only stays W3C-correct) |
| Grammar for explicit dialect choice | `transport: sse` (bare — opt into SSE, dialect implicit) | **Parametrized** — `transport: sse(<dialect>)` where `<dialect> ∈ {axon, openai, kimi, glm, anthropic}`. Bare `transport: sse` resolves at runtime per the Q1 algebraic-effect predicate (Q2 ratification) |
| Adopter SDK consumption (litellm / langchain / vercel-ai / instructor / llama_index / openai-sdk) | Required `EventSource`-based parsing of `event: axon.token` named events — incompatible with off-the-shelf SDKs (adopters wrote custom parsers) | **Native consumption** — adopter SDKs that hard-code OpenAI Chat Completions streaming parse the response verbatim with zero axon-specific awareness |
| Adopter SDK consumption (anthropic-sdk-typescript / python-anthropic / vercel-ai anthropic-provider) | Same — custom parser needed | **Native consumption via `transport: sse(anthropic)`** — adopter SDK parses `event: message_start` / `content_block_delta` / `message_stop` verbatim |
| Adopter SDK consumption (Moonshot Kimi K2.x / Zhipu ChatGLM-4.x) | Same — custom parser needed | **Native consumption via `transport: sse(kimi)` or `transport: sse(glm)`** — Kimi + GLM ship OpenAI-compatible Chat Completions wire verbatim; both dispatch to OpenAIDialectAdapter byte-identically per the **Q3 revision 2026-05-14** |
| Q7 algebraic-policy preservation channel on openai dialect | (no openai dialect existed) | **`axon_metadata` extension frame** emitted BEFORE `data: [DONE]` — carries `{trace_id, flow, backend, success, steps_executed, tokens_input, tokens_output, latency_ms, stream_policies?, enforcement_summary?, runtime_warnings?, step_audit?, terminal_reason}`. Empty fields elided per D4 byte-compat |
| Q7 algebraic-policy preservation channel on anthropic dialect | (no anthropic dialect existed) | **`event: axon.metadata` extension frame** emitted BEFORE `event: message_stop` — same payload shape as openai's `axon_metadata` (cross-dialect D3 + D4 parity) |
| `axon.complete.enforcement_summary` / `axon.complete.warnings` / `axon.complete.stream_policies` on axon dialect | Populated per v1.27.0 | **Byte-identical** (D6 indefinite — explicit `transport: sse(axon)` always retains the W3C envelope) |
| Tool-call SSE wire surface — per-dialect interleaving (D11) | `event: axon.tool_call` only (v1.27.0 shipped this) | **Per-dialect**: axon → `event: axon.tool_call` (unchanged); openai → inline `delta: {"tool_calls": [...]}` in the chunk frame; anthropic → 3-frame `tool_use` block triad (`content_block_start{type: tool_use}` + `content_block_delta{input_json_delta}` + `content_block_stop`); mid-text-block tool-use closes the open text block first (4-frame burst) |
| Adopter declarative override path | (none — wire was fixed) | **`transport: sse(<dialect>)` explicit** always wins over the Q1 defaults — Q5 escape valve. `transport: json` STILL wins over everything (D3 sacred) |
| Defense-in-depth — anthropic dialect on malformed input streams | (not applicable) | **`AnthropicDialectAdapter::flush_terminator` defensively closes any orphan `content_block`** — Anthropic spec requires every `content_block_start` balanced by `content_block_stop`. Production producer guarantees this via `translate(FlowComplete/FlowError)`; the defensive close protects test harnesses + future producers + direct library integrations |
| Producer side-channel access | `step_audit_records` read by producer ONLY when `replay_ctx.is_some()` (gated by `axonendpoint ... replay: true`) | **Always read** — `CompleteEnvelope` carries `step_audit_records` unconditionally so the non-axon dialect adapters can surface them on `axon_metadata` even when replay is disabled. Replay-log write reuses the already-read vec (no double-locking) |
| 33.z.k dedicated CI workflow | (none) | **New** — `.github/workflows/fase_33z_k_wire_format_adapter.yml` (33.z.k.k; 7 parallel test lanes + summary aggregator) running on every push/PR |
| 33.z.k cross-stack drift gate | (none) | **New** — `axon-rs/tests/fase33z_k_i_dialect_catalog_drift_gate.rs` + `tests/test_fase33z_k_i_dialect_catalog_drift_gate.py` (38 tests) lock the 5-dialect catalog membership Python↔Rust |
| 33.z.k D12 production-grade fuzz | (none) | **New** — `axon-rs/tests/fase33z_k_j_dialect_fuzz.rs` ships ~3 350 deterministic LCG iters across 18 tests / 9 invariant sections |

Every NEW behavior is **observable at the wire layer** for adopters
whose flows declare algebraic effects OR declare an explicit dialect.
**Most adopter `.axon` sources keep compiling unchanged**; the wire
flip for algebraic-effect flows is the one place where the surface
changes — Scenario A below covers the recipe.

---

## The architectural arc — why this release matters

Pre-v1.28.0, axon's SSE wire format was W3C-correct but un-pluggable:
every flow emitted `event: axon.token` + `event: axon.complete` named
events. This is structurally sound (every SSE parser handles it
correctly per the W3C SSE spec), but it created an adopter-friction
mismatch — the LLM-streaming ecosystem's SDKs (litellm / langchain /
vercel-ai / instructor / llama_index for the OpenAI side;
anthropic-sdk-typescript / python-anthropic for the Anthropic side;
Moonshot Kimi + Zhipu GLM client libraries for the Chinese-AI side)
hard-code their respective providers' wire format. Adopters consuming
axon's output through these SDKs had to write a custom parser shim
that translated axon's named events into the SDK's expected shape.

The founder's directive 2026-05-13 closed this gap:

> *"adopters never adapt to axon's wire format; axon adapts to
> adopter clients OR provides a declarative way to choose the wire
> format upstream of HTTP."*

The Fase 33.z.k cycle (v1.28.0) ships **both halves**: (1) a closed-
catalog 5-dialect surface so adopters declare their target SDK
ecosystem in source (`transport: sse(openai)` / `transport: sse(kimi)`
/ etc.); (2) an **algebraic-effect-driven default** so flows that
already commit to streaming via `effects: <stream:<policy>>` on a
tool transparently emit the LLM-ecosystem-default wire (openai) —
adopters who write idiomatic algebraic-effect axon source get the
ecosystem-default wire without any extra declaration.

The Q5 escape valve ensures **D6 backwards-compat indefinite**:
explicit `transport: sse(axon)` always wins — adopters who built
W3C-EventSource clients consuming `event: axon.token` continue to
work without any change.

The Q7 algebraic-policy preservation channel surfaces every
vertical-regulator audit data point (enforcement_summary,
runtime_warnings, step_audit, stream_policies) **uniformly across
all 5 dialects** via the new `axon_metadata` / `event: axon.metadata`
extension frames. Adopters on openai/anthropic wires now satisfy
PCI DSS Req 10 / FedRAMP AU-2 / FRE 502 / 21 CFR Part 11 §11.10
per-step provenance requirements with the same data they had on
the axon dialect via `axon.complete.enforcement_summary`.

This is the founder principle honored end-to-end. Per *"SSE es una
primitiva cognitiva, eso en axon lo es todo y debe funcionar
perfecto"*, the algebraic-effect SSE primitive now ships in the
wire format every adopter SDK ecosystem natively parses.

---

## Scenario A — Your flow uses `effects: <stream:<policy>>` and you want adopter SDK compatibility

**Symptom:** You declared a tool with an algebraic stream effect:

```axon
tool chat_token_stream {
    description: "Stream LLM tokens"
    effects: <stream:drop_oldest>
}

flow Chat() -> Unit {
    step Generate { ask: "hi" apply: chat_token_stream output: Stream<Token> }
}

axonendpoint ChatEndpoint {
    method: POST
    path: "/chat"
    execute: Chat
}
```

**What you observe in v1.28.0:**

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
X-Axon-Trace-Id: 550e8400-e29b-41d4-a716-446655440000

retry: 5000

data: {"id":"chatcmpl-axon-1234abcd","object":"chat.completion.chunk","created":1715648400,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-axon-1234abcd","object":"chat.completion.chunk","created":1715648400,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hola"},"finish_reason":null}]}

data: {"id":"chatcmpl-axon-1234abcd","object":"chat.completion.chunk","created":1715648400,"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: {"axon_metadata":{"trace_id":12345,"flow":"Chat","backend":"gpt-4o","success":true,"steps_executed":1,"tokens_input":0,"tokens_output":1,"latency_ms":42,"stream_policies":[{"step":"Generate","policy":"drop_oldest"}],"enforcement_summary":{"Generate":{"policy_slug":"drop_oldest","chunks_pushed":1,"chunks_delivered":1,"drop_oldest_hits":0,"degrade_quality_hits":0,"pause_upstream_blocks":0,"fail_overflows":0,"failed":false}},"step_audit":[{"step_name":"Generate","step_index":0,"success":true,"tokens_emitted":1,"output_hash_hex":"...","effect_policy_applied":"drop_oldest","chunks_dropped":0,"chunks_degraded":0,"timestamp_ms":1715648400500}],"terminal_reason":"stop"}}

data: [DONE]

```

(Field order in JSON is alphabetical per `serde_json` default; adopter
SDKs parse the shape, not byte order — per JSON spec.)

**Recipe (litellm Python client — adopter SDK consumes verbatim):**

```python
import litellm

# axon-served route is openai-compatible; litellm parses it natively.
response = litellm.completion(
    model="openai/gpt-4o",
    api_base="https://axon.example.com",
    base_url="https://axon.example.com",
    messages=[{"role": "user", "content": "hi"}],
    stream=True,
    # axon's dynamic-route endpoint replaces /v1/chat/completions:
    api_version="custom",
    extra_body={"path_override": "/chat"},
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
    elif chunk.choices[0].finish_reason == "stop":
        print("\n(done)")
```

**Recipe (vercel/ai TypeScript client):**

```typescript
import { createOpenAI } from '@ai-sdk/openai';
import { streamText } from 'ai';

const axon = createOpenAI({ baseURL: 'https://axon.example.com/chat' });

const result = await streamText({
  model: axon('gpt-4o'),
  prompt: 'hi',
});

for await (const chunk of result.textStream) {
  process.stdout.write(chunk);
}
```

**Recipe (instructor for structured output):**

```python
import instructor
from openai import OpenAI
from pydantic import BaseModel

class Reply(BaseModel):
    content: str

client = instructor.from_openai(
    OpenAI(base_url="https://axon.example.com/chat", api_key="not-used"),
    mode=instructor.Mode.JSON,
)

reply: Reply = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "hi"}],
    response_model=Reply,
    stream=True,
)
```

No custom parser shim. No EventSource adapter. The adopter SDK
ecosystem consumes axon's output verbatim.

**Verification:**

```bash
# Confirm the wire flip lands as expected:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_g_e2e_openai_wire
# Expected: 4 passed (including the load-bearing
# kivi_shape_emits_openai_wire_bytes_end_to_end).
```

---

## Scenario B — You want to FORCE the W3C-named axon dialect on an algebraic-effect flow

**Symptom:** Your flow declares an algebraic effect (so Q1 defaults to
openai dialect), but you have an existing EventSource client that
parses `event: axon.token` events — you don't want to change the
client.

**What v1.28.0 ships:** explicit `transport: sse(axon)` overrides
the Q1 default. The Q5 escape valve. This is documented as the **D6
backwards-compat indefinite** invariant — adopters who declare
`sse(axon)` explicitly observe the W3C-named wire on every release
indefinitely.

**Recipe:**

```axon
tool chat_token_stream {
    description: "Stream LLM tokens"
    effects: <stream:drop_oldest>
}

flow Chat() -> Unit {
    step Generate { ask: "hi" apply: chat_token_stream output: Stream<Token> }
}

axonendpoint ChatEndpoint {
    method: POST
    path: "/chat"
    execute: Chat
    transport: sse(axon)    // ← explicit dialect declaration; Q5 escape valve
}
```

**What you observe:**

```
event: axon.token
id: 1
data: {"step":"Generate","trace_id":12345,"token":"Hola","timestamp_ms":1715648400500}

event: axon.complete
id: 2
data: {"trace_id":12345,"flow":"Chat","backend":"gpt-4o","success":true,"steps_executed":1,"tokens_input":0,"tokens_output":1,"latency_ms":42,"stream_policies":[{"step":"Generate","policy":"drop_oldest"}],"enforcement_summary":{"Generate":{"policy_slug":"drop_oldest","chunks_pushed":1,"chunks_delivered":1,"drop_oldest_hits":0,"degrade_quality_hits":0,"pause_upstream_blocks":0,"fail_overflows":0,"failed":false}}}

```

Byte-identical to v1.27.0's algebraic-effect wire body. Your existing
EventSource client keeps working without any change.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_g_e2e_axon_byte_compat
# Expected: 3 passed (bare sse + explicit sse(axon) byte-identical
# for type-annotation flows; Q5 escape valve for algebraic-effect
# flows verified).
```

---

## Scenario C — You target Anthropic Claude and want native Anthropic-SDK consumption

**Symptom:** Your adopter pipeline targets Claude via the official
`anthropic-sdk-typescript` (or `python-anthropic` / `vercel/ai`
anthropic-provider) — those SDKs hard-code the Anthropic Messages
streaming wire format.

**What v1.28.0 ships:** explicit `transport: sse(anthropic)` emits
the Anthropic Messages streaming wire verbatim per
https://docs.anthropic.com/en/api/messages-streaming —
`event: message_start` → `event: content_block_start` →
`event: content_block_delta` → `event: content_block_stop` →
`event: message_delta` → `event: axon.metadata` → `event: message_stop`.

**Recipe:**

```axon
tool clinical_reasoning {
    description: "Differential diagnosis reasoning"
    effects: <stream:drop_oldest>
}

shield PHIShield {
    scan: [pii_leak]
    on_breach: quarantine
    severity: critical
    compliance: [HIPAA]
}

flow CDSAssessment() -> Unit {
    step Triage { ask: "vitals" output: Stream<Token> }
    step Differential { ask: "diagnosis" apply: clinical_reasoning }
    shield PHIShield on response -> SanitizedResponse
}

axonendpoint CDS {
    method: POST
    path: "/cds"
    execute: CDSAssessment
    transport: sse(anthropic)
}
```

**Recipe (Python anthropic-sdk client):**

```python
import anthropic

client = anthropic.Anthropic(
    base_url="https://axon.example.com/cds",
    api_key="not-used-but-required",
)

with client.messages.stream(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "vitals: HR 110, BP 90/60"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
    final_message = stream.get_final_message()
    print(f"\nstop_reason: {final_message.stop_reason}")
```

The `anthropic.Anthropic` client parses the wire verbatim — no shim.
The Q7 `event: axon.metadata` frame is silently ignored by the SDK
per the Anthropic spec §"Other events" ("any event-type your client
doesn't recognize should be silently dropped"); adopters who DO want
the algebraic-policy data subscribe to the event name explicitly.

**Tool-call interleaving:** when the flow's tool emits a
`ToolCall` event (real backend signals `FinishReason::ToolUse`),
the anthropic dialect emits a 3-frame `tool_use` block triad:

```
event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_axon_1234abcd_1","name":"search","input":{}}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"query\":\"axon\"}"}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}
```

Anthropic SDK consumers parse the `tool_use` block natively. When the
tool_use arrives mid-text-block, the open text block closes first
(4-frame burst total) — Anthropic spec invariant.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_g_e2e_anthropic_wire \
  --test fase33z_k_g_3_tool_call_interleaving
# Expected: 13 passed.
```

---

## Scenario D — You target Moonshot Kimi K2.x or Zhipu ChatGLM-4.x

**Symptom:** Your adopter pipeline routes through Moonshot Kimi K2.x
or Zhipu ChatGLM-4.x. Both providers publish OpenAI-compatible Chat
Completions APIs — their client SDKs are openai-sdk-compatible.

**What v1.28.0 ships (Q3 revision 2026-05-14):** explicit
`transport: sse(kimi)` and `transport: sse(glm)` emit canonical
OpenAI Chat Completions wire bytes — byte-identical to
`transport: sse(openai)`. The distinct dialect declaration is for
**adopter intent observability** (the underlying audit / metrics /
observability surfaces correlate adopter intent against the
upstream provider); at the wire layer all three dispatch to
`OpenAIDialectAdapter`.

**Recipe (Kimi):**

```axon
tool kimi_reasoning {
    description: "Long-context reasoning via Kimi K2.x"
    effects: <stream:drop_oldest>
}

flow Research() -> Unit {
    step Reason { ask: "synthesis prompt" apply: kimi_reasoning output: Stream<Token> }
}

axonendpoint Research {
    method: POST
    path: "/research"
    execute: Research
    transport: sse(kimi)
}
```

**Recipe (Python client via openai-sdk):**

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://axon.example.com/research",
    api_key="not-used",
)

stream = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[{"role": "user", "content": "synthesis prompt"}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

The Moonshot + Zhipu provider SDKs are openai-sdk-compatible by
construction; they parse the wire verbatim.

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_g_e2e_kimi_glm_dispatch
# Expected: 3 passed (s5 verifies kimi/glm/openai dialects produce
# byte-identical wire modulo `created`/`id`).
```

---

## Scenario E — You consume the new Q7 `axon_metadata` extension frame for vertical-regulator audit

**Symptom:** Your adopter compliance pipeline needs per-step
enforcement counters / per-step provenance / runtime warning records
for vertical-regulator audit (PCI DSS Req 10 / FedRAMP AU-2 / FRE
502 waiver-doctrine / 21 CFR Part 11 §11.10). In v1.27.0 this data
was only available on the axon dialect via
`axon.complete.enforcement_summary` + `axon.complete.step_audit`.

**What v1.28.0 ships:** the **Q7 algebraic-policy preservation
channel** surfaces the same data on every dialect:

| Dialect | Where the metadata lives |
|---|---|
| `axon` | Embedded on the `axon.complete` event (v1.27.0 surface — preserved byte-identical for D6 backwards-compat) |
| `openai` | Custom `data: {"axon_metadata": {...}}` frame emitted BEFORE `data: [DONE]` sentinel — adopter openai-compat SDKs ignore unknown top-level keys per their permissive JSON parsing; SDK-free clients consume directly |
| `anthropic` | Custom `event: axon.metadata` frame emitted BEFORE `event: message_stop` — anthropic-compat clients ignore unknown event names per Anthropic spec §"Other events" |
| `kimi` / `glm` | Same as `openai` (dispatch to `OpenAIDialectAdapter`) |

**Payload shape (every dialect):**

```json
{
  "trace_id": 12345,
  "flow": "AmlInvestigation",
  "backend": "gpt-4o",
  "success": true,
  "steps_executed": 3,
  "tokens_input": 250,
  "tokens_output": 480,
  "latency_ms": 1234,
  "stream_policies": [
    {"step": "ScreenSanctions", "policy": "drop_oldest"},
    {"step": "AnalyzeFlow", "policy": "fail"}
  ],
  "enforcement_summary": {
    "ScreenSanctions": {
      "policy_slug": "drop_oldest",
      "chunks_pushed": 12,
      "chunks_delivered": 10,
      "drop_oldest_hits": 2,
      "degrade_quality_hits": 0,
      "pause_upstream_blocks": 0,
      "fail_overflows": 0,
      "failed": false
    }
  },
  "runtime_warnings": [],
  "step_audit": [
    {
      "step_name": "ScreenSanctions",
      "step_index": 0,
      "success": true,
      "tokens_emitted": 10,
      "output_hash_hex": "0123abcd...64hex chars total",
      "effect_policy_applied": "drop_oldest",
      "chunks_dropped": 2,
      "chunks_degraded": 0,
      "timestamp_ms": 1715648400500
    }
  ],
  "terminal_reason": "stop"
}
```

Empty fields (`stream_policies` / `enforcement_summary` /
`runtime_warnings` / `step_audit`) are **elided** when the source
flow has no algebraic effects + no warnings + no per-step audit
data (D4 byte-compat with the placeholder-shape of v1.28.0 pre-
release alphas).

`terminal_reason` is always present: `"stop"` / `"error"` / `"none"`
(the last surfaces only when `flush_terminator` fires without a
preceding `FlowComplete` / `FlowError` — defensive backwards-compat
for malformed input streams).

**Recipe (Python audit consumer — openai dialect):**

```python
import httpx, json

async with httpx.AsyncClient(timeout=None) as client:
    async with client.stream("POST", "https://axon.example.com/aml") as resp:
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                break
            try:
                frame = json.loads(payload)
            except json.JSONDecodeError:
                continue
            # Q7 axon_metadata extension frame — present BEFORE [DONE].
            if "axon_metadata" in frame:
                meta = frame["axon_metadata"]
                for entry in meta.get("step_audit", []):
                    print(
                        f"step={entry['step_name']} "
                        f"policy={entry['effect_policy_applied']} "
                        f"tokens={entry['tokens_emitted']} "
                        f"hash={entry['output_hash_hex'][:16]}..."
                    )
                for step_name, summary in meta.get("enforcement_summary", {}).items():
                    if summary["drop_oldest_hits"] > 0:
                        log_audit_event(
                            kind="enforcement",
                            step=step_name,
                            policy=summary["policy_slug"],
                            counters=summary,
                        )
                continue
            # Regular chat.completion.chunk frame — consume normally.
            if "choices" in frame:
                delta = frame["choices"][0]["delta"]
                if "content" in delta:
                    print(delta["content"], end="", flush=True)
```

**Recipe (Python audit consumer — anthropic dialect):**

```python
import httpx, json

async with httpx.AsyncClient(timeout=None) as client:
    async with client.stream("POST", "https://axon.example.com/cds") as resp:
        cur_event = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                cur_event = line[len("event: "):].strip()
                continue
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            try:
                frame = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if cur_event == "axon.metadata":
                meta = frame["axon_metadata"]
                # ... same processing as openai dialect ...
            elif cur_event == "content_block_delta":
                delta = frame.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta["text"], end="", flush=True)
```

**Vertical-regulator audit unlock:**

| Vertical | Compliance requirement | What `axon_metadata` enables |
|---|---|---|
| **Banking** | PCI DSS Req 10 — per-step LLM call provenance for the multi-step decision flow | `step_audit[*]` carries `step_name + tokens_emitted + output_hash_hex + effect_policy_applied + chunks_dropped + chunks_degraded` per dispatched step — auditors reconstruct the FULL multi-step decision chain |
| **Government** | FedRAMP AU-2 — FOIA-eligible per-step reasoning chain | Same `step_audit[*]` array surfaces every step's audit row; auditors retrieve the per-step provenance via the `axon_metadata` frame on the wire OR via `GET /v1/replay/<trace_id>` (Fase 32.h) |
| **Legal** | FRE 502 waiver-doctrine — appellate review of per-step privilege assessment | Per-step audit retains the privilege-assessment reasoning chain; the `enforcement_summary` surface documents which shield policies fired |
| **Medicine** | 21 CFR Part 11 §11.10(e) — CDS clinician trail of per-step recommendation provenance | Per-step `step_audit[*]` + `enforcement_summary` for HIPAA shield activations + selected branch path (via the replay row's `branch_path`) — clinicians reconstruct the FULL diagnostic reasoning chain |

**Verification:**

```bash
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_h_metadata_population
# Expected: 12 passed (including 3 E2E HTTP POST tests verifying
# cross-dialect parity on enforcement_summary + stream_policies +
# step_audit byte-equivalence modulo framing).
```

---

## Scenario F — You ship a downstream crate that consumes axon's wire-format adapter API directly

**Symptom:** You write Rust code that calls
`axon::wire_format::select_adapter` and drives a `WireFormatAdapter`
directly (for example: a custom transport layer that emits SSE from
a non-HTTP source).

**What v1.28.0 ships:** the trait surface
`axon::wire_format::WireFormatAdapter` is the stable contract:

```rust
pub trait WireFormatAdapter: Send {
    fn dialect(&self) -> &'static str;
    fn translate(&mut self, event: &FlowExecutionEvent) -> Vec<Event>;
    fn build_complete_envelope_event(
        &mut self,
        envelope: &CompleteEnvelope,
    ) -> Vec<Event>;
    fn flush_terminator(&mut self) -> Vec<Event>;
}

pub fn select_adapter(
    dialect: &str,
    trace_id: u64,
) -> Box<dyn WireFormatAdapter>;
```

`CompleteEnvelope` is a public struct carrying the full algebraic-
policy envelope:

```rust
pub struct CompleteEnvelope {
    pub trace_id: u64,
    pub flow_name: String,
    pub backend: String,
    pub success: bool,
    pub steps_executed: usize,
    pub tokens_input: u64,
    pub tokens_output: u64,
    pub latency_ms: u64,
    pub effect_policies: Vec<(String, String)>,
    pub enforcement_summaries: Vec<(String, EnforcementSummaryWire)>,
    pub runtime_warnings: Vec<RuntimeWarning>,
    pub step_audit_records: Vec<StepAuditRecord>,
}
```

**Recipe — minimal SSE producer using the adapter API:**

```rust
use axon::flow_execution_event::FlowExecutionEvent;
use axon::wire_format::{select_adapter, CompleteEnvelope};

pub async fn drive_my_custom_sse_producer(
    dialect: &str,
    trace_id: u64,
    events: Vec<FlowExecutionEvent>,
    envelope: CompleteEnvelope,
    tx: tokio::sync::mpsc::Sender<axum::response::sse::Event>,
) {
    let mut adapter = select_adapter(dialect, trace_id);
    for event in &events {
        let frames = if matches!(event, FlowExecutionEvent::FlowComplete { .. }) {
            adapter.build_complete_envelope_event(&envelope)
        } else {
            adapter.translate(event)
        };
        for wire_event in frames {
            if tx.send(wire_event).await.is_err() {
                return; // Consumer disconnected.
            }
        }
    }
    for terminator_frame in adapter.flush_terminator() {
        let _ = tx.send(terminator_frame).await;
    }
}
```

The trait is `Send` so the producer can move the adapter across the
spawn boundary. Each adapter is stateful — construct via
`select_adapter` per request. The closed catalog
`{axon, openai, kimi, glm, anthropic}` is enforced at the dispatch
layer (unknown strings fall through to `AxonDialectAdapter`
defensively).

**Cross-stack contract:** the dialect catalog is pinned identically
in Python (`axon.compiler.parser._AXONENDPOINT_TRANSPORT_DIALECTS`)
and Rust (`axon_frontend::parser::AXONENDPOINT_TRANSPORT_DIALECTS`).
The 33.z.k.i drift gate fires loudly on any drift between the two
stacks. If you fork axon to add a 6th dialect, you must update:

1. `axon/compiler/parser.py` — `_AXONENDPOINT_TRANSPORT_DIALECTS` frozenset
2. `axon-frontend/src/parser.rs` — `AXONENDPOINT_TRANSPORT_DIALECTS` const
3. `axon-rs/src/wire_format/mod.rs` — `select_adapter` match arm
4. Implement the new dialect's adapter OR dispatch to an existing one
5. `axon/compiler/type_checker.py` `resolve_effective_dialect` — if the
   new dialect should default for some input class
6. `axon-rs/tests/fase33z_k_i_dialect_catalog_drift_gate.rs` —
   `CANONICAL_DIALECT_SNAPSHOT` + dispatch table
7. `tests/test_fase33z_k_i_dialect_catalog_drift_gate.py` — same
8. E2E test pinning the new dialect's wire bytes
9. Plan vivo + adopter docs (this file)

**Verification:**

```bash
# Run the drift gate to confirm closed-catalog discipline:
cargo test --manifest-path axon-rs/Cargo.toml \
  --test fase33z_k_i_dialect_catalog_drift_gate

# Cross-stack mirror:
python -m pytest tests/test_fase33z_k_i_dialect_catalog_drift_gate.py
```

---

## Backwards compatibility matrix

| Surface | Behavior in v1.28.0 |
|---|---|
| Existing adopter `.axon` source with bare `transport: sse` + type-annotation-only Stream | **Byte-identical wire** — axon dialect (Q1 Rule 3) |
| Existing adopter `.axon` source with bare `transport: sse` + algebraic-effect tool | **WIRE FLIPS** to openai dialect (Q1 Rule 2) — adopters needing W3C-named events declare `transport: sse(axon)` explicitly (Q5 escape valve, Scenario B) |
| Existing adopter `.axon` source with `transport: json` | **Byte-identical** — D3 sacred, JSON wire always wins over dialect choice |
| Existing adopter EventSource client parsing `event: axon.token` named events | **Works unchanged for axon-dialect routes** — declare `transport: sse(axon)` explicitly on flows where you want to keep the W3C wire |
| Existing adopter audit consumer parsing `axon.complete.enforcement_summary` | **Works unchanged on axon dialect** — same field, same shape; non-axon dialects surface the same data on the `axon_metadata` extension frame (Scenario E) |
| `axonendpoint` `replay: true` flag | **Works unchanged** — replay row's `step_audit` populated per v1.27.0 surface; reads the same side-channel the metadata frame reads |
| `flow_execution_event::FlowExecutionEvent` public enum | **No new variants** — 6-variant closed catalog preserved (FlowStart / StepStart / StepToken / StepComplete / ToolCall / FlowComplete / FlowError) |
| `axon::wire_format::CompleteEnvelope` public struct | **New field added** — `step_audit_records: Vec<StepAuditRecord>`. Adopters constructing `CompleteEnvelope` directly need to populate it. The `..CompleteEnvelope::default()` pattern doesn't work because the type doesn't impl `Default` — but every field is required so the compiler catches missing initializations explicitly |
| `axon::wire_format::WireFormatAdapter` public trait | **No method removals** — `build_complete_envelope_event` had a default impl in v1.27.x (test pre-releases); v1.28.0 overrides it explicitly in `OpenAIDialectAdapter` + `AnthropicDialectAdapter` to stash the envelope. Downstream impls of the trait keep working |
| 9 retired symbols from v1.27.0 (LegacyOrchestrationRequired etc.) | **Still deleted** — v1.28.0 preserves the 33.z.e parity gate; no regression |
| `axon-frontend::type_checker::resolve_effective_dialect` | **New public function** — pure 2-input total function `(transport_dialect: &str, has_algebraic_stream_effect: bool) -> String`. Always returns a catalog member. Adopters who construct their own wire dispatch can reuse this resolver |

---

## What this release does NOT change

- The `Content-Type: text/event-stream` response header (per W3C SSE
  spec) — every dialect emits SSE-framed responses.
- The `X-Axon-Trace-Id: <uuid>` correlation header (Fase 32.h) — every
  response carries it regardless of dialect.
- The `GET /v1/replay/<trace_id>` audit retrieval endpoint
  (Fase 32.h + 33.x.f) — works unchanged for all dialects.
- The `keepalive:` directive interval (Fase 30.f) — every dialect
  honors it.
- The `transport: json` explicit opt-out (D3 sacred) — JSON responses
  unchanged + still win over dialect choices for non-streaming flows.
- The dispatcher production path (Fase 33.z) — the dispatcher
  (`run_streaming_via_dispatcher`) is unchanged; v1.28.0 only changes
  the WIRE-FORMAT projection layer above it.
- The 45-IRFlowNode catalog (Fase 33.y) — unchanged.
- The cross-stack Python+Rust contract for parser / type-checker /
  IR — v1.28.0 extends the contract (adds the dialect catalog) but
  doesn't redefine existing surfaces.
- The real-provider lane (`fase_33x_real_provider.yml`) — opt-in,
  gated separately. Adopters running against real upstreams
  (OpenAI / Anthropic / Kimi / GLM / Gemini / Ollama / OpenRouter)
  observe the SAME wire as the stub backend, modulo per-upstream
  chunk granularity (Fase 33.x.b through-line).

---

## Where to file bugs

| Symptom | Where |
|---|---|
| Wire format unexpectedly W3C-named on a flow with `effects: <stream:<policy>>` | Issue tag `fase-33.z.k.g.2` — consumer-loop refactor regression |
| `axon_metadata` / `event: axon.metadata` frame absent from non-axon dialect terminator | Issue tag `fase-33.z.k.h` — algebraic-policy preservation regression |
| `axon_metadata.enforcement_summary` empty when the flow declares `effects: <stream:<policy>>` on a tool | Issue tag `fase-33.x.d` (root cause is the enforcer side-channel; the wire-format layer faithfully surfaces whatever's in the envelope) |
| `axon_metadata.step_audit` empty when the flow has Step children | Issue tag `fase-33.x.f` (root cause is the step_audit side-channel; same as above) |
| `transport: sse(unknown_dialect)` accepted at parse time | Issue tag `fase-33.z.k.b` — parser closed-catalog regression. The closed catalog is enforced at parse time per `_AXONENDPOINT_TRANSPORT_DIALECTS` |
| `transport: sse(axon)` not preserving W3C named events on algebraic-effect flow | Issue tag `fase-33.z.k.c` — resolver Rule 1 (explicit-wins) regression |
| Kimi or GLM dialect wire NOT byte-identical to canonical openai (modulo `created`/`id`) | Issue tag `fase-33.z.k.g` — Q3 revision dispatch regression |
| Anthropic dialect orphan `content_block` after `event: message_stop` | Issue tag `fase-33.z.k.j-defensive-close` (the 33.z.k.j fuzz pack pinned this defense-in-depth; regression would surface there first) |
| Wire format documentation drift between this file + `ADOPTER_STREAMING.md` § Multi-dialect wire format | Issue tag `fase-33.z.k.l` |

---

## See also

- [`docs/ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) §"Multi-dialect
  wire format (Fase 33.z.k, v1.28.0+)" — the full adopter reference
  for the 5-dialect surface, including per-dialect wire shape +
  decision tree + canonical adopter recipes per vertical.
- [`docs/MIGRATION_v1.27.md`](MIGRATION_v1.27.md) — the prior cycle
  (33.z production-wiring lift). v1.27.0 is the baseline this guide
  assumes.
- [`fase/fase_33z_k_wire_format_adapter.md`](fase_33z_k_wire_format_adapter.md)
  — the plan vivo for the 33.z.k cycle. Source of truth for Q1-Q7
  ratifications + D1-D12 invariant text + per-sub-fase landing
  status.
- `.github/workflows/fase_33z_k_wire_format_adapter.yml` — CI
  workflow (8 jobs: 7 parallel lanes + summary) running on every
  push / PR to master.
- The 173 dedicated 33.z.k tests across 14 test files — every adopter-
  observable behavior in this guide is pinned by at least one test;
  reproduce locally with the `cargo test` / `python -m pytest`
  commands listed throughout the scenarios.
