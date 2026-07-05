---
name: tool
summary: A declarative binding for an external capability (search, web fetch, code interpreter, …) callable from within a flow.
category: cognition
top_level: true
since: v0.1.0 (initial language)
grammar: |
  tool <Name> {
      provider: <ident>               # required — provider slug (http, mcp, brave, code_interpreter, ...)
      parameters: { k: Type, ... }    # optional (§Fase 58) — typed INPUT schema (the call contract)
      output_type: <Type>             # optional (§Fase 58) — declared OUTPUT type of the tool result
      max_results: <integer>          # optional — cap on returned items
      filter: <expr>                  # optional — server-side filter expression
      timeout: <duration>             # optional — wall-clock budget (e.g. 10s, 500ms)
      runtime: <ident>                # optional — runtime hint / endpoint slug (native | sandboxed | <slug>)
      sandbox: <true|false>           # optional — force-execute inside a sandboxed worker
      effects: <effect-row>           # optional — declared effects (<network>, <io>, ...)
      target: <SocketRef>             # optional (§Fase 84) — dispatch over this socket (Remote Hands)
      risk: safe | destructive        # optional (§Fase 84) — technician-command risk class
      argv: [<token>, ...]            # required with target:+bash (§Fase 84) — the argv template
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

Common slugs: `http` (REST endpoint dispatch), `mcp` (ℰMCP
JSON-RPC transducer), `brave`, `tavily`, `exa`, `serper`, `bing`,
`google_cse`, `code_interpreter`, `python_repl`, `bash`,
`http_fetch`, `sql`, `vector_search`, `wikidata`. The `http` and
`mcp` providers dispatch a **real** call to the tool-server (see
*Calling a tool* below); other slugs that the runtime registry
does not handle locally fall through to the model's tool-use
surface.

### `parameters:` (optional, §Fase 58)

The tool's **typed input schema** — the call contract. A
brace-delimited list of `name: Type` pairs:

```axon
parameters: { company: String, max_results: Int, active: Bool }
```

The schema reuses the full type-expression grammar (generics like
`List<T>`, `?`-optionals); a parameter whose type ends in `?` is
**optional**, every other parameter is **required**. The schema is
the signature the type-checker validates a `use <Tool>(k = v, …)`
call against (§58.d) — an unknown argument name, a duplicate, a
missing required parameter, or a literal type mismatch is a
**compile-time CALLER error** (CT-2 blame), surfaced *before* any
dispatch. A tool with **no** `parameters:` is schema-less: it
accepts the legacy single-argument `use <Tool> on <arg>` form and
its calls are not arg-validated (§58 D5 back-compat).

### `output_type:` (optional, §Fase 58)

The tool's **declared output type**. After a real dispatch, the
result is bound for downstream reference (the tool-step's typed
output), so the declared type participates in the semantic type
system rather than being an opaque blob.

```axon
output_type: CrmReport
```

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

### `target:` / `risk:` / `argv:` (optional, §Fase 84 — Remote Hands)

These three fields turn a `tool` into a **technician command**: a
typed, template-locked operation an agent can run on a **real
end-user machine** (a "PC technician" agent), dispatched over a
declared `socket` a local agent dials into.

```axon
session TechConfirm {
    server: [ send Command,
              select { approved: [receive CommandResult, end],
                       denied:   [receive DenyReason, end] } ]
    client: [ receive Command,
              branch { approved: [send CommandResult, end],
                       denied:   [send DenyReason, end] } ]
}
socket TechConfirmWS { protocol: TechConfirm }

tool DeleteFile {
    provider: bash
    target: TechConfirmWS
    risk: destructive
    parameters: { path: String }
    argv: ["rm", "${path}"]
    output_type: CommandResult
}
```

- **`target:`** names the `socket` this call dispatches over. Omit
  it and the tool behaves exactly as before (§84 is inert). With
  it, the tool is duality-checked against that socket's session
  (`axon-T861`).
- **`risk:`** is the closed catalog `safe | destructive`
  (`axon-T862`). A `destructive` tool's bound session MUST contain a
  reachable `branch{ approved / denied }` — a human confirm/deny exit
  visible in the protocol's own shape — or it is a **compile error**
  (`axon-T860`).
- **`argv:`** is the **argv template**: a list where each element is
  a literal (`"rm"`) or a *whole-element* `${param}` placeholder
  (`"${path}"`). This is the injection-safety keystone: a `${param}`
  is substituted as **exactly one argument**, opaquely, and is
  **never re-parsed by a shell** — the same discipline
  `retrieve.where:` uses for SQL parameters (§76.b). A placeholder
  fused with other text (`"${path}.bak"`) or unbound to a
  `parameters:` entry is a compile error (`axon-T859`); a
  `target:`-bound `provider: bash` tool with no `argv:` is
  `axon-T858`. The market's free command STRING is deliberately not
  offered — a string would let an argument break out into new shell
  syntax; the argv model makes that structurally impossible.

Unknown fields inside a `target:`-bound tool are a **hard error**
(§84 D84.13) — a typo'd safety field can never silently disable a
guard. (A legacy schema-less tool keeps its lenient skip.)

The enterprise data plane adds separation of duties (proposing and
approving a destructive command are distinct capabilities —
`tech:dispatch` vs `tech:approve`), a confirmation bound to the exact
rendered command's hash (a swapped command after approval is
refused), and fail-closed audit of every action. The local agent
runs only argv-templates whose hash it was enrolled with, without a
shell, least-privilege.

## Calling a tool

There are two ways a declared tool is invoked.

### 1. Explicit dispatch (§Fase 58) — the typed, real-dispatch path

A **flow-level** `use <Tool>(…)` statement dispatches a real call
to the tool-server and binds the typed result. Two surface forms:

```axon
# Structured, multi-field — the canonical form for typed args.
# Each named arg is validated against the tool's `parameters:`
# schema at compile time; the runtime assembles a typed JSON body
# ({"company":"Acme","max_results":5,"active":true}) and POSTs it.
use CrmRadar(company = "Acme", max_results = 5, active = true)

# Legacy single-argument (§Fase 54.b, D5 back-compat). `on
# "${param}"` interpolates a bound request/flow parameter; the
# body is wrapped as {"input": <arg>}.
use WebSearch on "${query}"
```

Both are **flow-level**: a `use` written inside a `step { }` body
is a parse error (§54.a) — it would silently degrade to an
unconstrained LLM step. The in-step equivalent is `apply: <Tool>`
on a step (run the tool as that step's backend).

The dispatch is real on **both** transports: the synchronous
endpoint path (`execute_server_flow`) and the SSE / streaming path
(`server_execute_streaming`). For the `http` / `mcp` providers the
runtime POSTs to the tool's resolved endpoint and binds the
response under `<ToolName>_result`; a provider the registry does
not handle locally falls through to the model (form 2).

### 2. Implicit tool-use surface

The backend's native tool-use surface (OpenAI tools, Anthropic
tools, JSON-RPC tool calls) also makes declared tools available to
the model while the surrounding step runs. The step author biases
towards a tool via the prompt (e.g. *"Search the web for recent
rulings on …"*), and the runtime exposes the declared `tool`s as
candidates. In strict-tool mode (`run … effort: strict`), the
runtime restricts the model to ONLY the tools declared at module
level; non-declared tool calls are rejected as protocol
violations.

## Wiring the endpoint (§Fase 58.g)

For the URL-dispatched providers (`http` / `mcp`), the call
endpoint is **config-driven**, so the same source runs against any
tool-server without edits:

- A tool whose `runtime:` is an absolute `http(s)://…` URL is used
  verbatim (the program pinned it).
- Otherwise the `runtime:` slug (or, when omitted, the tool name)
  is resolved against a **base URL**: `{base}/{slug}`. The base is
  the `AXON_TOOL_BASE_URL` env on the OSS server, or — on the
  enterprise multi-tenant server — the per-tenant `tool.base_url`
  config key (which overrides the env). Resolution is per-request,
  so concurrent tenants never share endpoints.

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
  produces an audited side effect. As of §Fase 58, an
  explicitly-dispatched tool (`use <Tool>(…)`) DOES bind a typed
  result — declare `output_type:` to give it a type, and the
  runtime binds the response under `<ToolName>_result` for a
  subsequent step to consume. (The implicit model-tool-use surface,
  by contrast, still folds tool calls into the surrounding step's
  generation rather than producing a standalone value.)
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
