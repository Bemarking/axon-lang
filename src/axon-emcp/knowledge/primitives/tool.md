---
name: tool
summary: A declarative binding for an external capability (search, web fetch, code interpreter, …) callable from within a flow.
category: cognition
top_level: true
since: v0.1.0 (initial language)
grammar: |
  tool <Name> {
      provider: <ident>               # required — provider slug (brave, tavily, exa, code_interpreter, ...)
      max_results: <integer>          # optional — cap on returned items
      filter: <expr>                  # optional — server-side filter expression
      timeout: <duration>             # optional — wall-clock budget (e.g. 10s, 500ms)
      runtime: <ident>                # optional — runtime hint (e.g. native | sandboxed)
      sandbox: <true|false>           # optional — force-execute inside a sandboxed worker
      effects: <effect-row>           # optional — declared effects (<net:egress>, <io:read>, ...)
  }
---

# `tool`

A `tool` declares an **external capability** the cognition layer
can call — a web search, a code interpreter, an HTTP fetch, a
database query, a vector retriever. The declaration is purely
descriptive: it binds a provider, declares its effects, and sets
operational limits. The runtime resolves the provider at execute
time against the backend's tool-binding registry.

A tool is referenced from a `step` by passing it in the persona
or by composing it into the model's tool-use surface (the
runtime forwards the declared `effects:` row into the audit
trail).

## Surface

`tool` is a **top-level declaration**. It is *not* nested inside
a flow, a step, or a persona.

```axon
tool WebSearch {
    provider: brave
    max_results: 5
    timeout: 10s
    effects: <network, io>
}

tool CodeInterpreter {
    provider: code_interpreter
    runtime: sandboxed
    sandbox: true
    timeout: 30s
    effects: <io, network, epistemic:speculate>
}
```

## Fields

### `provider:` (required)

A **single identifier** naming the provider slug. The runtime
keeps a closed catalog (registered via the backend's
`tool_registry` extension point); compile time validates that
the slug parses as an identifier but does NOT validate it
against the catalog — the binding is deployment-time so the
same axon source can target multiple backends.

Common slugs: `brave`, `tavily`, `exa`, `serper`, `bing`,
`google_cse`, `code_interpreter`, `python_repl`, `bash`,
`http_fetch`, `sql`, `vector_search`, `wikidata`.

### `max_results:` (optional)

A **non-negative integer literal**. Caps the number of results
the tool may return. The runtime trims the provider's response
to this length before passing it to the model; the audit row
records both the requested and the served counts.

### `filter:` (optional)

A **filter expression** — an identifier optionally followed by
a parenthesised argument list:

```axon
filter: lang(en)
filter: domain(example.com)
filter: published_after(2024-01-01)
```

The expression is forwarded to the provider verbatim; semantics
are provider-defined. Compile time validates only the shape.

### `timeout:` (optional)

A **duration literal** (`100ms`, `5s`, `2m`, …). Bounds the
tool's wall-clock budget. The runtime cancels the call on
expiry; the step that invoked the tool sees a structured
`tool_timeout` diagnostic and may compose a fallback via its
`reason` sub-construct.

### `runtime:` (optional)

A **single identifier** hinting the execution surface. Canonical
values:

| Value | Meaning |
|---|---|
| `native` | Run inline in the host process (e.g. an in-proc HTTP client). |
| `sandboxed` | Run inside a sandboxed worker / container. |
| `remote` | Dispatch to a registered remote service. |

### `sandbox:` (optional)

A **boolean literal**. When `true`, the runtime is required to
execute the tool inside a sandboxed worker (network egress
restricted, filesystem mounted read-only by default, no parent
process inheritance). Independent of `runtime:` — a `native`
runtime can still be sandboxed by the supervisor (§Fase 16).

### `effects:` (optional)

The **declared effect row** for this tool. Lists the effects
the model may produce by invoking it. Effect names are drawn
from the **closed catalog**
(`axon-frontend::type_checker::VALID_EFFECTS`):

| Effect | Meaning |
|---|---|
| `io` | Generic I/O (filesystem reads/writes). |
| `network` | Network egress (HTTP, DNS, …). |
| `storage` | Backed by an `axonstore` / data plane. |
| `pure` | Strictly deterministic, no observable side effects. |
| `random` | Consumes randomness (must be reproducible per-trace via the runtime seed). |
| `stream` | Emits a stream (paired with `Stream<T>` outputs, §Fase 33). |
| `trust` | Carries a §11.c trust proof obligation. |
| `sensitive` | Touches a sensitive data category (PII / PHI / financial). |
| `legal` | Carries a §40 legal-basis tag (mandatory qualifier from the closed legal-basis catalog). |
| `ots` | One-shot transform (mandatory `transform:<from>:<to>` or `backend:<native\|ffmpeg>` qualifier). |

Each effect may carry a **qualifier** after `:` (dotted-slug
grammar, §Fase 11.c / 11.e):

```axon
effects: <network, io>
effects: <io, sensitive, legal:HIPAA.164_502>
effects: <stream, network, epistemic:speculate>
effects: <ots:transform:mulaw8:pcm16, io>
```

The **`epistemic:` qualifier** is special: it occupies its own
field on the effect row and accepts the closed level catalog
(`believe`, `doubt`, `know`, `speculate`) — see
`axon://compliance/epistemic_levels`.

The type checker propagates the row through the flow's
algebraic-effect signature (`§Fase 23`). At runtime, every
invocation lands in the audit hash-chain with the row attached.

## Calling a tool

A tool is not invoked by a literal `call <Tool>` statement; the
backend's tool-use surface (OpenAI tools, Anthropic tools,
JSON-RPC tool calls) makes them available to the model
implicitly while the surrounding step runs. The step author
biases towards a tool via the prompt (e.g. *"Search the web for
recent rulings on …"*), and the runtime exposes the declared
`tool`s as candidates.

In strict-tool mode (`run … effort: strict`), the runtime
restricts the model to ONLY the tools declared at module level;
non-declared tool calls are rejected as protocol violations.

## What this primitive is NOT

- **Not the implementation of the capability.** A `tool` is the
  *declaration*; the implementation lives in the host runtime's
  tool registry (Rust trait impl, Python plugin). The compiler
  never executes a tool.
- **Not a shell command.** A tool with `provider: bash` is
  still subject to `sandbox:` and `effects:` controls; the
  compiler will reject a bash binding without an explicit
  `effects:` row in strict-policy modules.
- **Not a function in the host language.** Calling a tool
  produces an audited side effect, not a typed return value
  the next step can reference via `<Tool>.output` — for typed
  composition use `apply` on a flow that wraps the tool.
- **Not nested inside a flow.** Tools are declared at module
  scope and referenced implicitly by the runtime; there is no
  inline tool grammar.

## See also

- `axon://primitives/flow` — the orchestration primitive that
  exposes the declared tool set to its steps.
- `axon://primitives/shield` — composes with tools to gate
  effects (e.g. PHI scrubbing on `io:read`).
- `axon://compliance/effect_catalog` — the closed effect row
  vocabulary `effects:` draws from.
- `axon://logic/strict_tool_mode` — when to use `effort:
  strict` to lock the tool surface.
