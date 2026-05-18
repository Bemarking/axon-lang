# AXON Migration Guide — v1.35.x → v1.36.0

> **Scope:** the Fase 37 *Request Binding Contract* cycle introduced
> in v1.36.0. Adopters upgrading from v1.35.x read this doc to decide
> which migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.36.0 makes the typed request body of an `axonendpoint`
> **populate the parameters of the flow it executes** — a binding the
> compiler proves TOTAL, the runtime delivers on both transports, and
> the type system treats as `Untrusted` so a request value reaches a
> store only as a bound parameter (see `docs/ADOPTER_REST.md` §"The
> Request Binding Contract"). It is **backwards-compatible by design
> (D5)** with intended behavior changes scoped exactly to the bug it
> closes: a parameterised flow that silently never received its
> arguments now receives them — and an endpoint that would have failed
> at request time for a missing parameter now fails at `axon check`.

---

## What changed in v1.36.0

| Surface | v1.35.x | v1.36.0 |
|---|---|---|
| `axonendpoint body: T` ↔ `execute: F` parameters | The body was parsed, schema-validated, then DISCARDED — the flow's parameters were never bound; `${param}` interpolated to the literal | The request body's fields **populate F's parameters by name** (D1) — `${param}` interpolates in `where:` clauses, step `ask:` prompts, `persist`/`mutate` field blocks, on the SSE **and** JSON transports |
| A flow parameter the body type cannot supply | Silent — discovered as an empty `${param}` at request time | **Compile error** at `axon check` / `POST /v1/deploy` (D2) — the binding is proven total before the endpoint can deploy |
| A request value reaching a store `where:` clause | (the binding did not work at all) | Bound as a `$N` **filter parameter** (D3) — never string-spliced; injection closed by construction |
| An errored streaming flow's `axon.error` | A hollow `terminal_reason: error` — no detail (`openai`/`kimi`/`glm`/`anthropic` dialects dropped it) | Carries the diagnostic — error message + the **failing node's name** + `trace_id` — on every dialect, plus a structured server log (D6) |
| `/v1/execute` + every non-erroring Fase 30–36 wire | Established | **Byte-identical** (D5) |

---

## The intended behavior changes

Three, each a direct consequence of closing the gap:

1. **A parameterised flow now receives its arguments.** In v1.35.x a
   flow `Chat(message, tenant_id, …)` deployed behind an
   `axonendpoint body: ChatRequest` ran with an empty binding map —
   every `${param}` interpolated to the literal `${param}`, a
   `retrieve` `where:` queried for the literal string, and the flow
   produced wrong results. v1.36.0 binds each parameter from its
   same-named body field. **If your flow has parameters, it now sees
   real values where it saw empty strings before.**

2. **An uncovered required parameter is a compile error.** If
   `execute: F` declares a required parameter with no same-named,
   type-compatible field in `body: T`, that is now a compile error at
   `axon check` and `POST /v1/deploy` — the binding is a proven total
   function. **The failure moved from a production request to compile
   time.**

3. **An errored streaming flow says why.** A streaming flow that errors
   now emits an `axon.error` carrying the diagnostic (and naming the
   failing node) on every wire dialect, instead of a hollow
   `terminal_reason: error`.

No adopter with a *working* v1.35.x setup regresses: a flow with no
parameters, an endpoint with no `body:`, and `/v1/execute` are all
byte-unchanged. The changes convert silent wrong-results into either
correct execution or a loud, honest compile error.

---

## Migration scenarios

### Scenario A — your flows have no parameters

**v1.36.0:** nothing changes. The Request Binding Contract is inert
when there is nothing to bind.

**Action:** none.

### Scenario B — you have a parameterised flow behind `body: T`

**Pre-37:** the flow ran with empty `${param}` values — likely
producing wrong results you may have worked around.

**v1.36.0:** the flow receives its arguments from the body's
same-named fields.

**Action:** verify each flow parameter has a same-named field in the
declared `body:` type — `axon check` now tells you if one is missing
(Scenario C). Remove any client-side or flow-side workaround that
compensated for the empty values.

### Scenario C — `axon check` now reports a binding-totality error

```
$ axon check api.axon
✗ api.axon  … 1 error
  error [line 9]: axonendpoint 'ChatRoute' executes flow 'ChatFlow'
  whose required parameter 'tenant_id: String' has no matching field
  in body type 'ChatRequest'. The Request Binding Contract binds a
  flow parameter from the same-named body field — add a field
  'tenant_id: String' to 'ChatRequest', or make the parameter
  optional (Fase 37 D2).
```

**Action — pick one:**

- Add the missing field to the `body:` type (same name, compatible
  type).
- Make the flow parameter optional (`tenant_id: String?`) if the flow
  tolerates its absence.
- A type mismatch (`amount: Float` parameter vs `amount: String`
  field) is the same error — align the types.

This error means v1.35.x would have run that flow with an empty value
for that parameter. The compile error is the bug surfacing early.

### Scenario D — you depend on the SSE error wire

If your SSE client consumed `axon.error` and found only
`terminal_reason: error` with no detail, v1.36.0 now carries the
diagnostic — the error message, the failing node, and the `trace_id`
— in the dialect's error/metadata frame.

**Action:** none required; the extra detail is additive. If you had a
workaround logging "stream failed, cause unknown", you can now read
the cause off the wire.

### Scenario E — you use the JSON transport for a parameterised flow

The binding holds identically on `transport: json` — the body is
threaded through the synchronous runner.

**Action:** none; the JSON dynamic route binds the same way the SSE
route does.

---

## What does NOT change (D5)

- A flow with no parameters behind an endpoint with no `body:` —
  byte-identical.
- `POST /v1/execute` (the legacy RPC path) — unchanged; it never
  carried a request-body-to-parameter binding and still does not.
- Every non-erroring Fase 30–36 SSE / REST wire body — byte-identical.
- The `postgresql` store path and the filter compiler's output for a
  literal `where:` clause — byte-unchanged; `${name}` resolution is
  additive (an empty bindings map leaves a `${name}` literal).
- Body **schema validation** (`body: T`, Fase 32) — unchanged; the
  Request Binding Contract layers the parameter binding ON TOP of the
  existing validation.
- Only DECLARED flow parameters bind (D4) — an undeclared body field
  is never silently injected into the interpolation scope.

> Honest scope: path parameters and query parameters have no declared
> type surface in axon yet (the router is exact-match on
> `(method, path)`) — binding them is a future fase. v1.36.0 closes
> the binding of the one typed request surface that exists: `body: T`.

---

## Upgrade checklist

- [ ] Upgrade to `axon-lang` v1.36.0 (`pip` / `cargo`).
- [ ] Run `axon check` on every `.axon` source — resolve any
      binding-totality error (Scenario C): add the field, fix the
      type, or make the parameter optional.
- [ ] For each parameterised flow behind a `body:` endpoint, confirm
      it now receives real argument values (it saw empty strings
      before) — and drop any workaround that compensated.
- [ ] Re-deploy; smoke-test each route with a representative body.
- [ ] If an SSE client logged "stream failed, cause unknown", switch
      it to read the cause from the `axon.error` diagnostic.

---

*Fase 37 — The Request Binding Contract. D1–D7 ratified 2026-05-18.
Full reference: `docs/ADOPTER_REST.md` §"The Request Binding Contract".*
