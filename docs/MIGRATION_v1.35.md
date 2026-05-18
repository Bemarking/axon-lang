# AXON Migration Guide — v1.34.x → v1.35.0

> **Scope:** the Fase 36.x *Mixed-Flow Streaming Integrity* cycle
> introduced in v1.35.0. Adopters upgrading from v1.34.x read this
> doc to decide which migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.35.0 makes the **agent pattern** — `retrieve context →
> deliberate (a step) → persist the result` — a first-class, verified,
> locally-runnable streaming primitive (see
> `docs/ADOPTER_AXONSTORE.md` §16). It is **backwards-compatible by
> design (D5)** with exactly ONE intended behavior change: a streaming
> flow that *errors* now emits exactly ONE terminator on the SSE wire
> (`axon.error`) instead of a malformed `axon.error` + `axon.complete`
> pair. Every flow that does not error is **byte-identical**.

---

## What changed in v1.35.0

| Surface | v1.34.x | v1.35.0 |
|---|---|---|
| Streaming error wire | An errored streaming flow emitted BOTH `axon.error` AND `axon.complete` — a malformed double terminator | Exactly ONE terminator — `FlowComplete` XOR `FlowError` — for every flow, every shape, every outcome (D1) |
| `axonstore backend: in_memory` | Not source-declarable — the type-checker rejected it; the only runnable store was `postgresql` (needs a live DB) | First-class declarable backend — type-checks, resolves to the in-memory key-value path, `connection:` optional (D2) |
| The mixed agent flow behind `transport: sse` | Dispatched, but untested + un-runnable without a Postgres + malformed on error | A tested, documented, supported streaming primitive (D3) |
| Streaming-path `${interpolation}` | `step.ask` was sent verbatim; a step's output was never bound — data did not thread on the streaming path | A `retrieve` alias reaches a downstream `step`'s `${interpolation}`; a `step` output reaches a downstream `persist` (D4) |
| Streaming-tool `enforcement_summary` | Empty on `axon.complete` for an `apply:`-streaming-tool step (Fase 36.i re-routing fallout) | Surfaced — parity with the LLM-side path (36.x.e.2) |
| `/v1/execute` wire + every non-erroring Fase 30–36 wire | Established | **Byte-identical** (D5) |

---

## The one intended behavior change

In v1.34.x `run_streaming_via_dispatcher` (the SSE producer) emitted
`FlowExecutionEvent::FlowError` on the error path, then `break`d — and
§7 (after the loop) emitted `FlowExecutionEvent::FlowComplete`
**unconditionally**. An errored streaming flow therefore put BOTH
`event: axon.error` AND `event: axon.complete` back-to-back on the SSE
wire — a malformed double terminator that violates the Fase 33
closed-catalog contract ("exactly one terminator closes the stream").

v1.35.0 fixes exactly this: the post-loop `FlowComplete` emit is gated
on "no `FlowError` was already emitted". An errored streaming flow now
emits exactly ONE terminator — `axon.error` — and nothing follows it.

This bites ONLY the error path. The pure-`step` happy path always
emitted a single clean `axon.complete` and is byte-unchanged. An SSE
client that stops reading at the first terminator, or that treats a
second terminator as a protocol error, was the only thing affected —
and it is now correct.

---

## Migration scenarios

### Scenario A — your streaming endpoints only ever succeed

**Pre-36.x:** a clean `axon.complete` closed every stream.
**v1.35.0:** unchanged — byte-identical.

**Action:** none required. The terminator fix is invisible to any
flow that does not error.

### Scenario B — your SSE client handles the error path

If your client reads the SSE stream and an upstream flow can error
(a transient store/backend failure, a registry-build rejection), it
previously saw `axon.error` immediately followed by `axon.complete`.

**v1.35.0:** it now sees `axon.error` alone — the stream ends there.

**Action:** if your client had a workaround for the spurious trailing
`axon.complete` (e.g. ignoring a terminator after an error, or
tolerating a "stream ended twice" protocol event), you can remove it.
A client that already stopped at the first terminator needs no change.

### Scenario C — you want to run the agent pattern locally / in tests

**Pre-36.x:** a `retrieve` / `persist` flow needed a declared
`axonstore`, and the only backend with a runtime was `postgresql` —
so the canonical agent shape could not execute without a live
database (not on a laptop, not in CI, not in a unit test).

**v1.35.0:** declare `backend: in_memory`:

```axon
axonstore mem { backend: in_memory }

flow Chat() -> Unit {
    retrieve mem { where: "session = 'abc'" as: history }
    step Deliberate {
        ask: "History: ${history}. Continue the conversation."
        output: Stream<Token>
    }
    persist into mem { session: "abc" content: "${Deliberate}" }
}

axonendpoint Chat { method: POST path: "/api/chat"
                    execute: Chat transport: sse }
```

**Action:** add `backend: in_memory` to an `axonstore` for any flow
you want to run with zero external infrastructure. `connection:` is
optional for an `in_memory` store. The store is process-local and
non-persistent — see the next scenario for the production move.

### Scenario D — `in_memory` is for development, not production data

`in_memory` is a real, first-class backend — but its data lives in
the server process and does not survive a restart. It is the right
choice for local development, tests, CI, demos, and ephemeral /
per-request scratch state.

**Action:** for durable production data, keep `backend: postgresql`
(unchanged — the production data plane is byte-identical, D5). Swap
`in_memory` ↔ `postgresql` by editing one field; the flow body, the
`retrieve` / `persist` statements, and the streaming endpoint do not
change.

### Scenario E — you depend on streaming tools (`apply:`)

If a flow has `step S { apply: T }` where `tool T` declares
`effects: <stream:<policy>>`, v1.34.x left `enforcement_summary` empty
on the `axon.complete` for that step (a Fase 36.i re-routing fallout —
the tool-registry path did not surface it the way the LLM-side path
does).

**v1.35.0:** the streaming-tool path surfaces the enforcement summary
— parity with the LLM-side path.

**Action:** none required. If you inspected `enforcement_summary` for
an `apply:`-streaming-tool step and found it empty, it is now
populated. Additionally, a `<stream:…>` tool with an empty `provider:`
now resolves to the stub stream (a graceful default) instead of
erroring — verify your tools' `provider:` is set if you expect a real
backend.

---

## What does NOT change (D5)

- Every streaming flow that does not error — byte-identical wire.
- The pure-`step` happy path — always emitted one `axon.complete`,
  unchanged.
- `POST /v1/execute` (the synchronous JSON path) — it has no
  event-stream terminator concept; entirely untouched.
- The `postgresql` store path — the production data plane is
  byte-unchanged.
- Every Fase 30–36 SSE / REST wire body for a non-erroring flow —
  byte-identical.
- A pre-36.x `.axon` (no `in_memory` store anywhere) still parses,
  type-checks, and runs identically — `in_memory` is purely additive
  (a new accepted backend value).
- `sqlite` / `mysql` still type-check; they still have no runtime
  backend (a documented future fase) — v1.35.0 does not change that.

---

## Upgrade checklist

- [ ] Upgrade to `axon-lang` v1.35.0 (`pip` / `cargo`).
- [ ] If an SSE client had a workaround for the spurious trailing
      `axon.complete` after an error, remove it (Scenario B).
- [ ] To run the agent pattern locally / in CI, declare an
      `axonstore` with `backend: in_memory` (Scenario C).
- [ ] Keep `backend: postgresql` for durable production data
      (Scenario D) — `in_memory` is process-local + non-persistent.
- [ ] If you inspect `enforcement_summary` for an `apply:`-streaming-
      tool step, confirm it is now populated; verify each streaming
      tool's `provider:` is set (Scenario E).
- [ ] Re-run `axon check` on your sources — no new warnings are
      introduced by this cycle.

---

*Fase 36.x — Mixed-Flow Streaming Integrity. D1–D6 ratified
2026-05-17. Full reference: `docs/ADOPTER_AXONSTORE.md` §16.*
