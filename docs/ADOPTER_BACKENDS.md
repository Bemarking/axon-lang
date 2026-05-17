# AXON Adopter Guide — Execution Backends

> **Scope:** how an `axonendpoint` chooses *which model* runs its
> flow. Introduced as a first-class language property in **v1.34.0**
> (Fase 36 — *Axonendpoint Production Execution*).
>
> **TL;DR:** the execution backend of a deployed endpoint is now a
> **declared, compiled, type-checked, deterministically-resolved,
> audit-grounded property of the program** — not invisible host glue.
> One published precedence ladder resolves it; the compiler rejects an
> impossible choice; the runtime can never silently degrade to a
> no-op; and every response tells you which model ran and why.

---

## 1. Why this exists

Every LLM framework on the market treats "which model does this route
run" as imperative runtime glue — a line of host code, invisible to
any type system, absent from any compiled artifact, free to fail
silently. You cannot read a deployment and know what it runs.

AXON refuses that. In v1.34.0 the execution backend becomes a property
of the compiled program, held to the same four-pillar discipline as
epistemics, persistence, and streaming:

- **Determinism** — a given `.axon` + a given environment resolves to
  exactly one backend, by one published contract.
- **Epistemic honesty** — the runtime NEVER silently runs the no-op
  `stub`. If no real backend resolves, the request fails loudly.
- **Auditability** — the resolved backend and the rung that chose it
  are on the wire, in the body, and in a response header.
- **Declared intent, honored** — a declared backend is executed.

---

## 2. The Backend Resolution Contract

For any flow execution behind an `axonendpoint` route, the flow-level
backend is resolved by ONE deterministic, total, published precedence
ladder. **The first rung that yields a usable concrete backend wins:**

| Rung | Source | `reason` slug |
|---|---|---|
| 1 | **Request-explicit** — a concrete backend named on the request | `request_explicit` |
| 2 | **`axonendpoint backend:`** — the route's declared backend | `endpoint_declared` |
| 3 | **Server default** — `axon serve --backend` / `AXON_DEFAULT_BACKEND` | `server_default` |
| 4a | **Registry-ranked `auto`** — the operator-tuned `PUT /v1/backends` scores | `registry_ranked` |
| 4b | **Environment-available `auto`** — the first canonical provider with an API key in the environment | `environment_available` |
| 5 | **Honest failure** — `HTTP 503` / `axon.error`; **never** a silent `stub` | — |

A rung carrying `"auto"` or an empty value is *transparent* — it does
not fire; resolution falls through to the next rung. The resolver is
**pure and total** — the same inputs always produce the same result.

---

## 3. Declaring a backend — the `backend:` field

Add an optional `backend:` field to any `axonendpoint`:

```axon
flow Chat() -> Unit { step Generate { ask: "..." } }

axonendpoint ChatRoute {
    method:  POST
    path:    "/api/chat"
    execute: Chat
    backend: anthropic     # ← rung 2: this route runs Claude
}
```

The declared backend is **type-checked at compile time**. An unknown
name is a compile error (`axon check` fails):

```
$ axon check chat.axon
X chat.axon  1 error(s)
  error [line 4]: Unknown backend 'anthropi' in axonendpoint
  'ChatRoute'. Valid: anthropic, auto, gemini, glm, kimi, ollama,
  openai, openrouter, stub
```

### The closed catalog

`backend:` accepts exactly these values:

| Value | Meaning |
|---|---|
| `anthropic` `openai` `gemini` `kimi` `glm` `ollama` `openrouter` | The seven canonical LLM providers. |
| `auto` | Transparent — equivalent to omitting `backend:`. Declare it to make reliance on ladder resolution **explicit** (and silence the `axon-W003` warning, §8). |
| `stub` | The no-op backend. Reachable ONLY by this explicit declaration — see §7. |

---

## 4. The server default — `--backend` / `AXON_DEFAULT_BACKEND`

Pin a fleet-wide default (rung 3) without editing a single `.axon`:

```sh
axon serve --backend anthropic
# or, 12-factor style:
AXON_DEFAULT_BACKEND=anthropic axon serve
```

The CLI flag wins when both are set. The value is validated against
the closed catalog **at server startup** — a fat-fingered provider
name aborts the boot with exit code 1, before the first request:

```
$ axon serve --backend anthropi
axon serve: invalid server default backend 'anthropi' (from
--backend or AXON_DEFAULT_BACKEND). Valid: anthropic, auto, gemini,
glm, kimi, ollama, openai, openrouter, stub
```

An endpoint that declares its own `backend:` (rung 2) always
outranks the server default (rung 3).

---

## 5. Environment-available `auto`

When no rung 1–3 value fires, `auto` resolution consults the
environment. If the operator-tuned backend registry (`PUT
/v1/backends/{name}`) has scored entries, the top score wins (rung
4a). Otherwise the runtime scans for provider API keys in the
environment and picks the first canonical provider whose key is
present, in canonical priority order (rung 4b):

```
ANTHROPIC_API_KEY · OPENAI_API_KEY · GEMINI_API_KEY · KIMI_API_KEY ·
GLM_API_KEY · OPENROUTER_API_KEY · OLLAMA_API_KEY
```

A server started with one provider key set **just works** — no `PUT
/v1/backends` ceremony required. `auto` resolution **never** lands on
`stub` (D5): `stub` is filtered out of both the registry and the
environment lists.

---

## 6. Per-step tool providers

A `step` that `apply:`s a `tool` declaring a streaming effect executes
against the **tool's own `provider:`** — the per-step backend
overrides the flow-level backend for that step:

```axon
tool LiveSearch {
    provider: http
    runtime:  "https://search.internal/stream"
    effects:  <stream:drop_oldest>
}

flow Research() -> Unit {
    step Search { ask: "latest filings" apply: LiveSearch }
}
```

`step Search` streams from `LiveSearch`'s provider; any non-`apply:`
step in the same flow uses the flow-level backend.

---

## 7. Honest failure — no silent `stub`

When the ladder resolves nothing real (no request backend, no
`backend:`, no server default, empty registry, no provider key) and
`stub` was not explicitly named, the request **fails loudly**:

- **JSON route** → `HTTP 503` with a structured body:
  ```json
  {
    "error": "no_backend_available",
    "message": "no execution backend available — axon will not silently run the no-op `stub`. Fix one of: ...",
    "endpoint": "ChatRoute", "flow": "Chat",
    "trace_id": "…", "d_letter": "D5"
  }
  ```
- **SSE route** → `HTTP 200 text/event-stream` carrying a single
  dialect-correct `axon.error` event, then the terminator.

`stub` — the no-op backend that returns synthetic `(stub)` tokens — is
reachable **only** by an explicit, written `backend: stub` (or
`backend=stub` on a request). It is never a silent fallback. Declaring
it is a legitimate opt-in for local development and tests:

```axon
axonendpoint DevRoute {
    method: POST  path: "/dev/chat"  execute: Chat
    backend: stub          # explicit opt-in to the no-op
}
```

---

## 8. Observability — answering "why this model?"

Every dynamic-route response carries the resolution on two surfaces:

- **`X-Axon-Backend` response header** — `<backend>; reason=<rung>`,
  e.g. `X-Axon-Backend: anthropic; reason=endpoint_declared`. Uniform
  across the JSON and SSE wires. The honest failure reports
  `none; reason=no_backend_available`.
- **`backend_resolution` body object** — injected into every 2xx
  `application/json` response:
  ```json
  { "...flow result...": "...",
    "backend_resolution": { "backend": "anthropic", "reason": "endpoint_declared" } }
  ```
  For a replay-enabled route this injected body is what the replay log
  persists, so `GET /v1/replay/<trace_id>` carries the resolution into
  the audit trail.

---

## 9. Compile-time + deploy-time signalling

- **`axon-W003`** — `axon check` emits a warning for every
  `axonendpoint` that declares no `backend:` (it relies on ladder
  resolution). Declare `backend: <provider>` to pin it, or
  `backend: auto` to make the reliance explicit and silence the
  warning. Under `axon check --strict` the warning is an error.
- **Deploy-time check** — `POST /v1/deploy` runs the resolution
  ladder for every route against the server's current environment.
  A route whose backend cannot be resolved is surfaced in the deploy
  response `warnings` array (`code: "no_resolvable_backend"`). The
  check is **non-blocking** — the deploy still succeeds; the operator
  may set a key or populate the registry afterwards.

---

## 10. Quick reference

| I want… | Do this |
|---|---|
| This route always runs Claude | `backend: anthropic` on the `axonendpoint` |
| A fleet-wide default | `axon serve --backend <name>` or `AXON_DEFAULT_BACKEND` |
| "Use whatever key is in the env" | omit `backend:`, or declare `backend: auto` |
| A deterministic local no-op | `backend: stub` (explicit) |
| To know which model ran | read the `X-Axon-Backend` header / `backend_resolution` body |
| To catch unwired routes early | `axon check` (`axon-W003`) + the deploy `warnings` array |

---

*Fase 36 — Axonendpoint Production Execution. D1–D12 ratified
2026-05-17. See `docs/MIGRATION_v1.34.md` for upgrade scenarios.*
