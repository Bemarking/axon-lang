# AXON Migration Guide — v1.21.x → v1.22.0

> **Scope:** the Fase 31 *Type-Driven Wire Inference* surface
> introduced in v1.22.0. Adopters upgrading from v1.21.x (Fase 30
> HTTP transport) read this doc to decide which migration scenario
> applies to their deployment + execute the recipe.
>
> **TL;DR:** v1.22.0 is **strictly additive** with the new
> `strict_type_driven_transport` flag **off by default**. If you
> don't change anything, nothing changes — your v1.21.x behavior
> is preserved verbatim (D8 backwards-compat). You **may** see a
> new compile-time warning (`axon-W001`) and a new informational
> response header (`X-Axon-Stream-Available`) if your source has
> stream effects and your axonendpoint omits the `transport:`
> declaration. Both are non-fatal hints surfacing the inference
> the language now performs for you.

---

## What changed in v1.22.0

| Surface | v1.21.x | v1.22.0 |
|---|---|---|
| Stream-effect flow + no `transport:` declaration | Compiles silently; HTTP returns JSON (Fase 30 D4 unless `Accept:` set) | Compiles with **`axon-W001` warning** highlighting the inference; HTTP behavior **unchanged** unless strict flag is on |
| Stream-effect flow + no `transport:` + JSON response served | Plain JSON | JSON + **`X-Axon-Stream-Available` header** surfacing the inference |
| `transport: json` explicit + stream-effect flow | JSON (D3 opt-out honored) | **Identical** — D3 opt-out always wins. Header still fires (`reason=declared_json`) so the trade-off is observable to clients |
| `axon serve` (Rust) | — | New CLI flag `--strict-type-driven-transport` + env var `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1` |
| `axon serve` (Python) | — | Same CLI flag + env var (cross-stack D7 contract) |
| Default behavior when flag is **off** (v1.22.x) | — | Fase 30 D4 + D5 + D9 negotiation **byte-identical** |
| Default behavior when flag is **on** | — | Stream-effect flows on `/v1/execute` return SSE regardless of `Accept:` header (D1 inference rules the wire) |
| `transport: sse` declared | SSE (Fase 30 D5) | SSE (unchanged) |

---

## Scenario A — You are the Kivi case 2026-05-11

**Symptom:** your `axonendpoint` executes a flow with `tool ... effects: <stream:...>` AND `apply: <tool_name>` in a step body, but `/v1/execute` returns `Content-Type: application/json` even though you expected SSE streaming.

**Fix (60 seconds):**

```axon
axonendpoint ChatEndpoint {
    method:    POST
    path:      "/chat"
    execute:   Chat
    transport: sse        // ← add this one line
    keepalive: 15s        // optional; defaults to 15s
}
```

Redeploy. Your client receives `Content-Type: text/event-stream` immediately. The fix works on **v1.21.0+** — you do NOT need to upgrade to v1.22.0 for this. v1.22.0's compile warning would have told you about the inference at build time, sparing you the 7-version diagnostic wall — but the fix has been available since v1.21.0.

If you upgrade to v1.22.0 AND don't add `transport: sse`, you'll see:

```
warning[axon-W001]: implicit `transport: sse` inferred from stream effects on
axonendpoint 'ChatEndpoint' (flow 'Chat' produces a stream via step 'Generate'
applies tool 'chat_token_stream' with effects `<stream:drop_oldest>`). Declare
`transport: sse` to silence this warning and lock in SSE behavior, or
`transport: json` to opt out and keep the legacy JSON wire format. When
`strict_type_driven_transport: true`, this endpoint emits SSE on /v1/execute
by default.
```

The warning is your in-IDE / CLI signal. Address it however your team prefers.

---

## Scenario B — You want the new default-SSE behavior everywhere

**Use case:** Every stream-effect flow on your server should emit SSE without your client having to send `Accept: text/event-stream`. The language's type system rules the wire.

**Fix (1 line of config):**

Pick whichever opt-in surface matches your deployment:

### B.1 — CLI flag (k8s / docker / systemd)

```bash
axon serve --strict-type-driven-transport
```

### B.2 — Environment variable (12-factor app)

```bash
export AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1
axon serve
```

Truthy values (case-insensitive): `1`, `true`, `yes`, `on`. The CLI flag wins when both are set.

### B.3 — Verify the flag is on

The Python `axon serve` and Rust `axon-rs` binaries both print the resolved state at startup:

```
⚡ AxonServer starting on 0.0.0.0:8443
  channel: memory
  state:   memory
  auth:    enabled
  strict transport: ENABLED (D1 inference rules wire)
```

After the flag is on, every axonendpoint that omits `transport:` AND whose flow has stream effects returns SSE on `/v1/execute`. Adopters who explicitly declared `transport: json` keep their opt-out (D3 is sacred).

---

## Scenario C — Your stream-effect flow intentionally wraps tokens in JSON

**Use case:** You have a flow that emits stream effects (e.g. `tool ... effects: <stream:drop_oldest>`) BUT you want the HTTP wire to remain JSON. Your client doesn't speak SSE; you synthesize a final answer from streaming tokens server-side.

This is the rare-but-legal D3 opt-out case.

**Fix (1 line of source):**

```axon
axonendpoint LegacyEndpoint {
    method:    POST
    path:      "/legacy"
    execute:   StreamingFlow
    transport: json        // ← explicit opt-out
}
```

After redeploying:

- `/v1/execute` returns `Content-Type: application/json` regardless of `Accept:` header.
- The compile-time `axon-W001` warning is **suppressed** (you explicitly declared your choice).
- The runtime `X-Axon-Stream-Available` header on JSON responses carries `reason=declared_json` so clients see your trade-off.

D3 is sacred — explicit `transport: json` always wins, in both legacy mode and strict mode. The language honors your choice.

---

## Scenario D — Staged rollout across environments

**Use case:** You manage dev / staging / prod environments and want to validate the new behavior tier by tier before flipping production.

**Recipe:**

| Environment | `strict_type_driven_transport` | Notes |
|---|---|---|
| dev | `true` | Surface every implicit-sse site immediately via warning + header |
| staging | `true` | Production-shape clients validate against the strict behavior |
| prod | `false` (default) | Flip last, after staging confirms |

```bash
# dev
AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1 axon serve

# staging — pass via systemd EnvironmentFile or k8s ConfigMap
# (same env var name everywhere — D7 cross-stack contract)

# prod (legacy default — no change)
axon serve
```

After dev + staging validate, flip prod by adding `--strict-type-driven-transport` to the CLI invocation OR setting the env var on the prod service. Rollback is symmetric — remove the flag/env, the server restarts in legacy mode.

---

## What can't go wrong

Per the four-pillar discipline:

1. **D8 — Absolute backwards-compat when flag is off.** v1.21.x adopters who don't change anything see byte-identical behavior on every existing axonendpoint. The Fase 30 D4 + D5 + D9 negotiation matrix is preserved verbatim.

2. **D3 — Explicit `transport: json` always wins.** No flag flip, no strict mode, no inference will ever override an adopter's explicit opt-out. If your source declared json, you get json.

3. **D7 — Cross-stack consistency.** Python `axon serve` and Rust `axon-rs` read the same env var name (`AXON_STRICT_TYPE_DRIVEN_TRANSPORT`), accept the same truthy alphabet (`1`/`true`/`yes`/`on`, case-insensitive, whitespace-trimmed), and produce identical inference verdicts on the same source.

4. **D10 — Every D-letter traces to a pillar.** The migration surface is not opinion — it's the engineering of a soundness invariant. If a behavior here surprises you, file an issue; it's either a documentation gap or a contract violation.

---

## What ships in v2.0.0 (advance notice)

Per **D9 ratified 2026-05-11**, the default of `strict_type_driven_transport` flips from `false` to `true` in v2.0.0 (Fase 35+ candidate). Adopters who want to preserve the legacy behavior will need to either:

- Declare `transport: json` explicitly on every axonendpoint they want to remain JSON, or
- Set `AXON_STRICT_TYPE_DRIVEN_TRANSPORT=0` (or any falsy value) to keep the legacy default.

The full migration window is the v1.22.x + v1.23.x + … series. By the time v2.0.0 ships, the `axon-W001` compile warning will have surfaced every site that needs adopter attention. No silent breakage.

The flag remains accessible in v2.0.0 for emergency rollback.

---

## Troubleshooting checklist

If you're debugging an unexpected response wire format after upgrading to v1.22.0:

1. **What does `axon parse src/your.axon` say?**
   - If it emits `axon-W001` → the inference fired; pick an opt-in from §A/§B or an opt-out from §C.
   - If it emits no warning → your flow does NOT produce a stream by the 3-disjunct predicate (or your `transport:` is already declared). Re-verify your `effects:` syntax against [STREAM_EFFECTS.md](STREAM_EFFECTS.md).

2. **What does the `X-Axon-Stream-Available` response header say?**
   - `reason=flag_off` → flip the flag (§B) OR declare `transport: sse` OR send `Accept: text/event-stream`.
   - `reason=declared_json` → you've explicitly opted out (§C); the language is honoring your choice.
   - Header absent → either the response is already SSE OR your flow has no stream effects.

3. **Is the server actually running with the flag you think it has?**
   - Check the startup banner — both Python and Rust print the resolved `strict transport: ENABLED|disabled` line.
   - `curl -sI http://<server>:8443/v1/health` (no payload check, just verify the server is up).

4. **Did you redeploy after editing the axonendpoint?**
   - The deployed source is cached; `transport:` changes require redeploy.

---

## See also

- [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — Fase 30 streaming surface; v1.22.0 extends the "Type-driven default transport" section.
- [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Pattern 6 documents the `axon-W001` warning shape end-to-end.
- [`STREAM_EFFECTS.md`](STREAM_EFFECTS.md) — Fase 11.a stream effects + 4 backpressure policies (the predicate the inference walks).
- [Fase 31 plan vivo](fase_31_type_driven_wire_inference.md) — internal sub-fase tracker + D1–D10 ratifications.

---

*This document is part of the axon-lang public adopter surface. Migration questions and edge-case reports welcome — file an issue at `axon-lang`.*
