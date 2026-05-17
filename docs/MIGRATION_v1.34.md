# AXON Migration Guide — v1.33.x → v1.34.0

> **Scope:** the Fase 36 *Axonendpoint Production Execution* cycle
> introduced in v1.34.0. Adopters upgrading from v1.33.x read this
> doc to decide which migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.34.0 makes the execution backend a **declared,
> compiled, deterministically-resolved property** of an `axonendpoint`
> (see `docs/ADOPTER_BACKENDS.md`). It is **backwards-compatible by
> design (D9)** with exactly ONE intended behavior change: a deployed
> endpoint can no longer *silently* execute the no-op `stub`. If a real
> backend was reachable before, it runs now too — and if none is
> reachable, the request fails loudly instead of returning a hollow
> `success:false`.

---

## What changed in v1.34.0

| Surface | v1.33.x | v1.34.0 |
|---|---|---|
| `axonendpoint` backend selection | None — every deployed route's `dynamic_endpoint_handler` hardcoded `backend: "auto"`, which dead-ended at `stub` | A 5-rung **Backend Resolution Contract** (D1) resolves it deterministically |
| `axonendpoint backend:` field | Did not exist | Optional, type-checked against a closed catalog (D2) |
| `axon serve --backend` / `AXON_DEFAULT_BACKEND` | Did not exist | Server-wide default — rung 3 (D7) |
| No resolvable backend | Silent `stub` no-op — `success:false`, `steps_executed:0`, no error | Structured **HTTP 503** / `axon.error` SSE event (D5) |
| "Why this model?" | Unanswerable | `X-Axon-Backend` header + `backend_resolution` body (D8) |
| `axon check` on an undeclared-backend endpoint | Silent | `axon-W003` warning (D10) |
| `POST /v1/deploy` | No backend signalling | `warnings` array for unresolvable routes (D10) |
| Declared streaming-tool `provider:` | Ignored at execution (dead code) | Executed — the streaming-tool dispatch path is live (D4) |
| `/v1/execute` wire + every Fase 30–35 wire | Established | **Byte-identical** (D9) |

---

## The one intended behavior change

In v1.33.x a deployed `axonendpoint` routed and streamed correctly but
its flow executed against `backend: stub` — the no-op — because
`dynamic_endpoint_handler` hardcoded `"auto"` and `auto` never
consulted the provider keys in the environment. The result was a
silent `{ success: false, steps_executed: 0, tokens_output: 0 }`.

v1.34.0 fixes exactly this:

- If a real backend **is** reachable (a provider key in the
  environment, an operator-tuned registry entry, or a server
  default), the endpoint now runs **that backend** — with **zero
  source change**.
- If **no** real backend is reachable, the request fails with a
  **structured HTTP 503** (`error: "no_backend_available"`) instead
  of returning a hollow `success:false`. The failure names exactly
  what to fix.

No adopter who had a working setup regresses. The change converts a
silent lie into either correct execution or a loud, honest error.

---

## Migration scenarios

### Scenario A — you run with a provider API key in the environment

**Pre-36:** the endpoint silently ran `stub` regardless of your key.
**v1.34.0:** the endpoint runs your provider.

**Action:** none required. Verify with the `X-Axon-Backend` response
header — it now reads e.g. `anthropic; reason=environment_available`
instead of dead-ending at `stub`. Optionally pin the model explicitly
(Scenario C) so the choice is in the source, not the environment.

### Scenario B — you run with NO provider key and NO declared backend

**Pre-36:** the endpoint silently returned `success:false` no-ops.
**v1.34.0:** the endpoint returns a structured **HTTP 503**
(`no_backend_available`).

**Action — pick one:**

```axon
axonendpoint E { ... backend: anthropic }   # 1. pin a provider
```
```sh
export ANTHROPIC_API_KEY=sk-...             # 2. give the env a key
axon serve --backend anthropic              # 3. set a server default
```
```axon
axonendpoint E { ... backend: stub }        # 4. opt into the no-op
```

Option 4 (`backend: stub`) preserves the *old* behavior verbatim — but
now it is **explicit and visible in the source**, not a silent
surprise. Recommended only for local development and tests.

### Scenario C — pin a model per route (recommended)

```axon
axonendpoint ChatRoute {
    method: POST  path: "/api/chat"  execute: Chat
    backend: anthropic
}
```

The declared backend is type-checked at compile time and recorded on
every response. This is the most auditable setup — anyone can read the
`.axon` and know what each route runs.

### Scenario D — set a fleet-wide default

```sh
axon serve --backend anthropic
# or
AXON_DEFAULT_BACKEND=anthropic axon serve
```

Every endpoint that declares no `backend:` of its own inherits this.
A route's own `backend:` always outranks the server default.

### Scenario E — `axon check` now warns (`axon-W003`)

```
$ axon check api.axon
⚠ api.axon  … 0 errors · 1 warning(s)
  warning [line 7]: warning[axon-W003]: axonendpoint 'ChatRoute'
  declares no `backend:` — its execution backend is resolved at
  request time down the Fase 36 precedence ladder …
```

**Action:** declare `backend: <provider>` to pin the model, or
`backend: auto` to make the reliance on ladder resolution **explicit**
and silence the warning. Under `axon check --strict` the warning is
promoted to an error — declare a `backend:` on every endpoint.

### Scenario F — you depend on streaming tools (`apply:`)

If a flow has `step S { apply: T }` where `tool T` declares
`effects: <stream:<policy>>`, v1.33.x **silently ignored** the tool's
declared `provider:` and stream effect (the streaming-tool dispatch
path had no production caller). v1.34.0 wires it: the step now
executes against the tool's `provider:` with the `<stream:policy>`
effect honored.

**Action:** verify the tool's `provider:` and `runtime:` are correct —
they are now load-bearing. A non-streaming `apply:` tool is unchanged.

---

## What does NOT change (D9)

- `POST /v1/execute` with an explicit `backend` — byte-identical.
- `ExecuteRequest.backend` still defaults to `"stub"`.
- Every Fase 30–35 SSE / REST wire body — byte-identical.
- A pre-36 `.axon` (no `backend:` field anywhere) still parses and
  type-checks with zero errors — the field is optional.
- An `axonendpoint` with no `backend:` still deploys — the deploy-time
  resolution check is non-blocking (it only adds a `warnings` entry).
- Non-streaming `apply:` tools — unchanged legacy path.

> One internal default changed without adopter-visible effect:
> `DeployRequest.backend` (the `POST /v1/deploy` field) now defaults to
> `"auto"` instead of `"anthropic"`. The dynamic-route execution path
> never consulted this field pre-36, so the change is regression-free
> — `"auto"` is simply the honest default.

---

## Upgrade checklist

- [ ] Upgrade to `axon-lang` v1.34.0 (`pip` / `cargo`).
- [ ] Run `axon check` on your `.axon` sources — address any
      `axon-W003` warnings (declare `backend:` or `backend: auto`).
- [ ] Ensure each production endpoint can resolve a real backend:
      a declared `backend:`, a provider key in the environment, or a
      `--backend` server default.
- [ ] Re-deploy; inspect the `POST /v1/deploy` response `warnings`
      array — resolve any `no_resolvable_backend` entries.
- [ ] Smoke-test each route; confirm the `X-Axon-Backend` header
      names the model you expect.
- [ ] If you relied on `stub` for any non-dev route, declare
      `backend: stub` explicitly (or wire a real backend).

---

*Fase 36 — Axonendpoint Production Execution. D1–D12 ratified
2026-05-17. Full reference: `docs/ADOPTER_BACKENDS.md`.*
