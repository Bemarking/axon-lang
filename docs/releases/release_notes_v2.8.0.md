# AXON v2.8.0 — Real tool dispatch + structured tool arguments (§Fase 58)

> **Released:** 2026-06-04
> **Type:** minor bump · additive API surface · zero breaking change (D5)
> **Theme:** §Fase 58 closes the brief #22 gap — a program `tool` is no longer
> a documentation-only declaration that silently degrades to an LLM step. It
> gains a **typed input schema** and an **output type**; a flow dispatches it
> for **real** (synchronous AND streaming) with a **structured, type-validated
> JSON body**; the call endpoint is **config-driven per tenant**; and the
> whole contract is an **independently-verifiable Proof-Carrying-Code
> property**.

Carries `axon-frontend` **1.5.0 → 1.6.0** (parser/AST/IR/type-checker) and
`axon-lang` **2.7.0 → 2.8.0**.

---

## What's new

### Typed tool schema + canonical invocation (§58.a–c)

```axon
tool CrmRadar {
    provider: http
    parameters: { company: String, max_results: Int, active: Bool }   # the call contract
    output_type: CrmReport                                            # the typed result
}

flow ScanCrm(company: String) -> CrmReport {
    use CrmRadar(company = company, max_results = 5, active = true)    # structured keyword args
    step Summarize { ask: "Summarize the matches" output: CrmReport }
}
```

- A `tool` declares `parameters: { k: Type, … }` (the input contract) and
  `output_type: <Type>` (the typed result). Both survive losslessly into the
  IR (`IRToolParam` / `IRNamedArg`).
- `use <Tool>(k = v, …)` is the canonical multi-field form; the legacy
  `use <Tool> on "${arg}"` (single positional, §54.b) stays valid (D5).

### Compile-time caller-blame (§58.d, §58.d.2)

The type-checker validates every call against the tool's schema **before any
dispatch** (CT-2 caller blame): unknown argument, duplicate, missing required
parameter, literal type mismatch. This covers BOTH surfaces —
`use Tool(k = v, …)` (§58.d) and the step `apply: <Tool> given: <struct>`
splat, whose struct fields auto-map onto the schema by name (§58.d.2).

### Real dispatch — synchronous AND streaming (§58.e/f/f.2)

`use Tool(k = v, …)` against an `http` / `mcp` (or built-in `native`/`stub`)
provider POSTs a **type-coerced structured JSON body**
(`{"company":"Acme","max_results":5,"active":true}` — a `String` param keeps
its value verbatim, never shape-guessed) and binds the typed response. Real on
both the synchronous endpoint path (`execute_server_flow`) and the SSE /
streaming path (`server_execute_streaming`). Previously every program tool on
the server path silently degraded to an LLM step.

### Config-driven per-tenant tool endpoints (§58.g, D7)

A tool with a relative `runtime:` (or none) resolves its dispatch URL against
a base URL — the `AXON_TOOL_BASE_URL` env on the OSS server. Absolute
`runtime:` URLs are used verbatim (D5). New
`ToolRegistry::resolve_relative_endpoints`; `execute_server_flow` /
`server_execute_streaming` gain an optional `tool_base_url`. The enterprise
product layers per-tenant overrides on top.

### Proof-Carrying Code: ToolCallSoundness (§58.i)

A new `axon::pcc` property class — the §58.d caller-blame check becomes a
machine-checkable proof: the tool's schema rides the proof bundle and an
**independent verifier re-derives** that every `use Tool(k = v, …)` call is
schema-sound, without trusting the compiler (Necula 1997).

### output_type enters the epistemic lattice (§58.i.2, D9)

A tool's declared `output_type` now rides the §55 `EpistemicEnvelope`, so the
`(base, scope, confidence)` ceiling binds to the typed output a downstream
`${Step.output}` inherits. Additive on the wire — the field is elided when
absent, so every pre-§58 flow is byte-identical.

---

## Compatibility

- **Zero breaking change (D5).** The legacy `use <Tool> on "${arg}"` form,
  schema-less tools, and absolute `runtime:` URLs are unchanged. The new
  `EpistemicEnvelope.output_type` is elided when absent — existing
  `epistemic_envelopes[*]` wire bytes are unchanged for flows without an
  `output_type`-declaring tool.
- **Single-stack Rust.** axon-frontend + axon-rs are authoritative; no Python
  parity gate.

## Acceptance

The Kivi skills smoke E2E (`market_research` → `crm_radar` → `web_scout`): a
`use Tool(k = v)` dispatches real to the wired tool-server, receives the
structured JSON body keyed by the schema, and the typed result reaches
`${Step.output}` for the next step.
