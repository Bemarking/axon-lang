# Session Types in axon (Fase 41)

> **Status — Fase 41, axon-lang v2.3.0 (May 2026).** This guide is the
> adopter reference for the WebSocket-as-a-cognitive-primitive cycle:
> the binary session-type algebra (`session` + `socket`), the
> credit-refined backpressure index, the SSE-as-fragment unification,
> the typed-reconnection model (`?resume=`), and the multiparty
> projection theorem (`GlobalType` → per-role projection).
>
> If you only need bidirectional real-time chat from the
> v2.0.x enterprise image, jump straight to [§ Quickstart](#quickstart).

## Table of contents

1. [Why session types](#why-session-types)
2. [Quickstart](#quickstart)
3. [The `session` declaration](#the-session-declaration)
4. [The `socket` declaration](#the-socket-declaration)
5. [Credit-refined backpressure (`credit(k)`)](#credit-refined-backpressure)
6. [Running a typed WebSocket dialogue](#running-a-typed-websocket-dialogue)
7. [SSE as the single-polarity fragment](#sse-as-the-single-polarity-fragment)
8. [Typed reconnection (`?resume=`)](#typed-reconnection)
9. [Multiparty protocols](#multiparty-protocols)
10. [Diagnostics + error catalog](#diagnostics)
11. [Migration from v2.2.x](#migration)
12. [The four pillars](#the-four-pillars)

---

## Why session types

Standard real-time stacks (RFC 6455 WebSocket + Socket.IO + tRPC) type
**messages** — every frame on the wire carries a JSON schema. They do
**not** type the **conversation**: the order in which messages arrive,
which side may speak next, when the dialogue terminates. The result is a
familiar set of operational failures:

- *Half-open deadlocks* — both peers wait on each other.
- *Out-of-order replies* — the server sends a `done` while the client is
  still mid-utterance.
- *Backpressure ambiguity* — the producer floods the consumer and the
  carrier-level mitigation (TCP window) is too coarse to attribute.

axon **types the dialogue itself**. A `session` declares the
ordered exchange between two roles — *what* is sent, *who* sends it,
*when* the choice happens, *when* the protocol terminates. The compiler
proves the two roles are dual (Caires–Pfenning Curry-Howard); the
runtime enforces every step. A non-conforming peer is rejected at the
frame; the dialogue stays in lock-step by construction.

```text
                          Static guarantees           Runtime witnesses
  ──────────────────────  ─────────────────────────   ──────────────────────────
  v2.2.x (per-msg JSON):  schema-of-this-message      400 Bad Request
  v2.3.0 (session-typed): order + direction + credit  1002 Protocol Error
                          + termination + duality      + audited utterance row
```

## Quickstart

```axon
# 1. Declare the two-party dialogue
session Chat {
    client: [
        loop,
        select { ask: [send Utt, branch { token: [receive Tok, loop], done: [end] }],
                 cancel: [end] }
    ]
    server: [
        loop,
        branch { ask: [receive Utt, select { token: [send Tok, loop], done: [end] }],
                 cancel: [end] }
    ]
}

# 2. Bind a transport (WebSocket carrier) with a credit window
socket ChatWS {
    protocol: Chat
    backpressure: credit(8)
    reconnect: cognitive_state
    legal_basis: legitimate_interest
}
```

The enterprise server picks this up automatically at boot — the route
`GET /api/v1/socket/chat` upgrades to a session-typed WebSocket bound to
`ChatWS`. Every frame is validated against the cursor; every utterance
flows through the §40.c vertical shield + the §40.o hash-chain audit
log; the connection survives a network blip via `?resume=<session_id>`.

---

## The `session` declaration

A `session` declares a **binary** (two-role) protocol. The grammar
extends the §Fase 4 surface — `send`/`receive`/`loop`/`end` for the
linear fragment, plus §Fase 41.b `select`/`branch` for the choice
fragment.

```axon
session Name {
    role_a: [ step, step, ... ]
    role_b: [ step, step, ... ]
}
```

### Step kinds

| Step | Meaning |
|---|---|
| `send T` | Role emits a value of type `T`; peer must `receive T`. |
| `receive T` | Role consumes a value of type `T`; peer must `send T`. |
| `select { ℓ: [steps], … }` | Role chooses a labelled arm to send. |
| `branch { ℓ: [steps], … }` | Role offers labelled arms; peer chooses. |
| `loop` | Recursion point — jumps back to the role's top. |
| `end` | Terminates the protocol. |

### Duality

`session Name { a: […], b: […] }` is well-formed iff the two roles are
duals under the regular-coinductive equivalence ≡:

```text
   send T  ↔  receive T       select { ℓ: G }  ↔  branch { ℓ: G⊥ }
```

The check is automatic — the §41.b `check_session_duality` lowers each
role into a `SessionType` (with `loop` ↦ `μX.…`) and verifies the
connection law `b ≡ a⊥` via regular-coinductive `equiv`. α-equivalent
recursion variables are accepted.

A duality violation surfaces as a diagnostic with both roles' lowered
session types written out so you can read where they diverge:

```
E0641: Session 'Bad' duality violation: role 'a' has the session type
       `!T.end`, whose dual is `?T.end`, but role 'b' has `!T.end`
       (expected the dual)
```

---

## The `socket` declaration

A `socket` binds a declared `session` to a transport. v2.3.0 ships one
carrier (WebSocket / RFC 6455) but the binding is carrier-agnostic — the
SSE fragment (§41.e) reuses the same declaration when the protocol's
producer side is single-polarity.

```axon
socket Name {
    protocol: SessionName          # required — must reference a declared `session`
    backpressure: credit(k)        # optional — §41.c credit-refined window
    reconnect: cognitive_state     # optional — §41.g typed reconnection
    legal_basis: <basis>           # optional — §40 legal-basis tag
}
```

### Fields

- **`protocol`** *(required)* — the declared `session` name. Must
  reference a session whose two roles are duality-checked; otherwise
  the socket itself is rejected.
- **`backpressure: credit(k)`** *(optional)* — the §41.c credit-refined
  window. `k` must be ≥ 1 (a 0-credit window has no typing rule for
  send). When absent the socket runs in the unbounded fragment.
- **`reconnect: cognitive_state`** *(optional)* — enables §41.g typed
  reconnection. Mid-protocol disconnects seal the residual cursor +
  credit window into an AAD-bound `cognitive_states` ciphertext (TTL
  configurable at deploy; default 5 min).
- **`legal_basis: <basis>`** *(optional)* — §40 legal-basis annotation
  for the dialogue. Propagated into the audit hash-chain so an
  investigator can trace which legal basis covered each utterance.

---

## Credit-refined backpressure

> §Fase 41.c — paper §4.2.

Every `socket { backpressure: credit(k) }` declares a credit window of
size `k`. The static analysis is a **Presburger discharge** running over
the lowered `SessionType`; the runtime enforces the same arithmetic
dynamically.

```text
  Per-step semantics (window k, current count n):
    send T   :  n > 0 required. Post-step: n := n − 1.
    recv T   :  always ok.       Post-step: n := min(n + 1, k).
```

**Static-time verdicts** (compile-time errors):

- *send-at-zero* — the type contains an explicit `!⁰T.S` (unprovable
  by the §4.2 "no rule at n = 0" axiom).
- *burst overflow* — a straight-line send-burst exceeds `k`; the
  protocol demands more credit than the window can absorb.
- *loop unsustainability* — a recursive body has Δ = `#send − #recv >
  0`; the per-iteration drain isn't matched by replenishment, so no
  finite `k` is sufficient for unbounded iteration.

```axon
# OK — Δ = 0 (1 send + 1 recv per iter), sustainable at any k ≥ 1
session PingPong {
    client: [loop, send A, receive Ack, loop]
    server: [loop, receive A, send Ack, loop]
}
socket OK { protocol: PingPong, backpressure: credit(1) }

# REJECTED at compile time — Δ = 2 > 0 (two sends per iter, only one recv)
session Drain {
    client: [loop, send A, send B, receive Ack, loop]
    server: [loop, receive A, receive B, send Ack, loop]
}
socket Drain { protocol: Drain, backpressure: credit(100) }
# E0642: Socket 'Drain' violates the credit-refined backpressure type
#        of session 'Drain' role 'client': recursive body is
#        unsustainable: Δ = 2 - 1 > 0 (no finite credit window keeps
#        unbounded iteration in flight) (D2)
```

**Runtime witnesses** (RFC 6455 `1002 protocol error`):

- A peer's frame demanding a send when the window is 0 closes the
  carrier with code `1002` + reason `credit_exhausted`. The runtime
  emits a typed `axon.error` frame with the offending payload type
  before closing so the peer can diagnose.

---

## Running a typed WebSocket dialogue

The enterprise server mounts `GET /api/v1/socket/:name` automatically
for every declared `socket`. The dialogue uses the typed envelope:

```jsonc
// Outgoing peer-send (client → server or server → client):
{"v":1,"kind":"send","payload_type":"Msg","data":{"text":"hello"}}

// Internal choice (a `select` arm pick):
{"v":1,"kind":"select","label":"ask"}

// Protocol termination:
{"v":1,"kind":"end"}

// Out-of-band protocol error (the server's last frame before close):
{"v":1,"kind":"error","code":"payload_mismatch","detail":"…"}
```

### Connecting

```js
// Client side — pure WebSocket, no SDK needed.
const ws = new WebSocket("wss://acme.bemarking.com/api/v1/socket/chat", [], {
  headers: { "Authorization": `Bearer ${jwt}` }
});
ws.onopen = () => {
  ws.send(JSON.stringify({ v: 1, kind: "send", payload_type: "Utt",
                           data: { text: "Hello!" } }));
};
ws.onmessage = (e) => {
  const f = JSON.parse(e.data);
  if (f.kind === "send" && f.payload_type === "Tok") { /* stream token */ }
  if (f.kind === "end") ws.close();
};
```

The `Sec-WebSocket-Protocol` subprotocol is not negotiated — every
session-typed `socket` runs on the default subprotocol (`""`). The
v2.3.0 release header `X-Axon-Session-Id` carries the session_id the
client should use for `?resume=` (see [§ Typed
reconnection](#typed-reconnection)).

### Carrier closure codes

| Code | Reason | Meaning |
|---|---|---|
| `1000` | `session_end` | Both peers reached `end`. Normal closure. |
| `1002` | `payload_mismatch` | A peer's frame announced the wrong payload type. |
| `1002` | `unexpected_frame` | A peer sent the wrong kind (e.g. `select` where `recv` expected). |
| `1002` | `unknown_label` | A `select`/`branch` label not in the session type. |
| `1002` | `credit_exhausted` | A `send` was attempted at credit n=0. |
| `1002` | `already_complete` | A peer sent more after `end`. |
| `1002` | `malformed_frame` | The envelope didn't parse (bad JSON / unknown `kind`). |
| `1011` | `internal` | Server-side fault. |

---

## SSE as the single-polarity fragment

> §Fase 41.e — paper §4.4.

A `session` whose declared protocol is **single-polarity** (producer
only sends; consumer only receives — no `recv` from producer, no
`branch` for consumer) is provably equivalent to W3C Server-Sent Events:

```text
                  S_SSE = Π_↓(S_WS)
```

The enterprise server detects this at deploy time and exposes the same
declaration over two carriers:

- `GET /api/v1/socket/:name` — WebSocket, full bidirectional.
- `GET /api/v1/socket/:name` with `Accept: text/event-stream` — SSE,
  producer-only.

The wire format adapts but the dialogue is byte-compatible with
Fase 33's existing SSE machinery: every step emits one SSE event
(`event: axon.send` / `axon.select` / `axon.end` / `axon.error`) with
the JSON envelope as the `data:` line. Any standards-compliant SSE
consumer (browser `EventSource`, `curl --no-buffer`, Fase 33's
`bytes_stream_to_sse_events`) decodes the wire without
axon-specific knowledge.

```axon
# A pure-producer protocol — SSE-projectable.
session TokenStream {
    server: [loop, send Token, loop]
    client: [loop, receive Token, loop]
}
```

For a session that is NOT in the single-polarity fragment (any `recv`
on the producer side, any `branch` on the consumer side), `Accept:
text/event-stream` returns a single `axon.error` event with code
`non-sse-polarity-schema` and closes the stream. The full dialogue is
still available over WebSocket.

---

## Typed reconnection

> §Fase 41.g — paper §3.5 + §6.

A mid-protocol disconnect (network blip, page refresh, mobile carrier
switch) does NOT lose the conversation state if the socket declares
`reconnect: cognitive_state`. The server seals the residual session-
type cursor + credit window into a §40.t AAD-bound ciphertext keyed
by `(tenant, session_id, socket_name)`; a reconnecting client presents
the session_id and the runtime resumes from the exact residual.

### The handshake

1. On connect, the server response carries
   `X-Axon-Session-Id: <session_id>` — store this client-side.
2. If the WebSocket drops mid-protocol, the server's
   `run_session_loop` returns `Err(ProtocolError::Transport(...))`,
   seals the residual via `cognitive_states::seal_state(AAD = tenant +
   session_id + socket_name + user_id)`, and persists with the
   declared TTL.
3. The client reconnects with `?resume=<session_id>` query parameter
   on the same socket path:
   ```
   GET /api/v1/socket/chat?resume=ws-19e5298902d-2
   ```
4. The server's pre-upgrade handler restores the snapshot, decrypts
   under the active AAD, validates the sealed schema equals the live
   socket's declared schema, and instantiates the `SessionRuntime`
   from the residual cursor.
5. On clean session-end the snapshot is **evicted** (replay defence —
   a completed dialogue cannot be resumed).

### Resume rejection codes (HTTP 410 Gone)

| Code | Meaning |
|---|---|
| `resume_not_found` | No snapshot for the claimed `session_id`. |
| `resume_expired` | The TTL elapsed. (Checked **before** decryption.) |
| `resume_aad_mismatch` | The §40.k envelope's AAD doesn't match — cross-tenant graft / wrong socket / rotated key. |
| `resume_malformed` | The decrypted envelope didn't parse as a `SealedRuntime`. |
| `resume_schema_drift` | The sealed schema doesn't equal the live socket's — a deploy bumped the protocol. |

Each rejection seals a `session:ws_resume_rejected` audit row with the
reason, so an operator dashboard can distinguish expected expiry from
active tampering.

### TTL guidance

The default for a `socket { reconnect: cognitive_state }` is 5 minutes
— short enough that a stale resume can't replay an outdated decision,
long enough to cover a typical mobile-network blip. For longer
windows, declare explicitly at the socket level (this is a
deployment-time decision exposed via the enterprise control plane).

---

## Multiparty protocols

> §Fase 41.h — paper §5 (Honda–Yoshida–Carbone, POPL'08).

For n-party orchestrations (a multi-skill agent routing between a
user, a tool, and a notification stream), v2.3.0 ships the global-type
algebra + the projection theorem. A `GlobalType` declares the entire
orchestration from above; projection extracts each role's binary
`SessionType` for the runtime.

### Grammar (paper §5.1)

```text
   G ::= end                          terminated protocol
       | p → q : T . G                p sends T to q, then G
       | p → q : { ℓᵢ : Gᵢ }          p selects ℓᵢ for q, branches
       | μX. G                        recursion
       | X                            recursion variable
```

### Example — three-role chat

```rust
use axon::multiparty::{GlobalType, Role};

let g = GlobalType::rec(
    "X",
    GlobalType::message("User", "Agent", "Utterance",
        GlobalType::message("Agent", "Skill", "SubTask",
            GlobalType::message("Skill", "Agent", "Response",
                GlobalType::message("Agent", "User", "Reply",
                    GlobalType::var("X")
                )
            )
        )
    )
);

// Project every role's local session type.
let projection = g.project_all().expect("safely realizable");
// projection[&Role::new("User")]  = rec X. !Utt.?Reply.X
// projection[&Role::new("Agent")] = rec X. ?Utt.!Sub.?Resp.!Reply.X
// projection[&Role::new("Skill")] = rec X. ?Sub.!Resp.X
```

### The safe-realizability gate

`g.project_all()` is the theorem in code. Its `Ok` verdict is the
structural certificate that **independent per-role runtimes
faithfully realise `g`**. The gate fires four typed errors:

| `ProjectionError` | Meaning |
|---|---|
| `SelfMessage { role }` | `from == to` for some message or choice. |
| `EmptyChoice { from, to }` | A choice with zero arms. |
| `MergeFailed { role, labels, … }` | A role uninvolved in a choice saw arms project to non-equivalent local types — it couldn't know which arm `from` chose. |
| `UnboundVariable(var)` | Free recursion variable in the global type. |

The most common gotcha is the merge condition: a choice that needs to
propagate to a non-participant role must be sent explicitly to every
active role. The gate catches real protocol bugs, not just
synthetic ones — if it rejects, restructure the global type to make
the choice visible to every role that branches on it.

---

## Diagnostics

The enterprise server emits structured diagnostics on three surfaces:

1. **Compile-time** — the §40.r tenant diagnostics (visible via
   `GET /api/v1/tenant/diagnostics/recent`): every duality violation,
   credit-conformance error, projection failure surfaces here with the
   exact lowered session/global type so an adopter engineer can see
   where the protocol diverged.

2. **Runtime — WebSocket close codes** — see the table in
   [§ Running a typed WebSocket dialogue](#running-a-typed-websocket-dialogue).

3. **Runtime — audit log** — every utterance + denial + closure + seal
   + resume + resume-rejection lands in the §40.o hash-chain:

   | Event | When |
   |---|---|
   | `session:ws_opened` | Connection upgraded; runtime initialised. |
   | `session:ws_utterance` | One peer-send accepted (post-shield). |
   | `session:ws_denied` | One peer-send rejected (shield or session-type). |
   | `session:ws_closed` | Carrier closed (clean or error). |
   | `session:ws_sealed` | §41.g residual sealed at mid-protocol error. |
   | `session:ws_resumed` | §41.g `?resume=<id>` succeeded. |
   | `session:ws_resume_rejected` | §41.g resume rejected with typed reason. |

   Audit-row content carries the `payload_type` + a SHA-256 hash of
   the payload bytes — **never the bytes themselves** (the hash-chain
   stays PHI-safe by construction). The §40.c vertical shield's
   findings (HIPAA / Legal / AML) are attached as JSON details.

---

## Migration from v2.2.x

See [`docs/MIGRATION_v2.3.md`](MIGRATION_v2.3.md) for scenario-driven
recipes.

In summary:
- v2.2.x `session Name { client: […], server: […] }` declarations
  continue to compile unchanged (D8 backwards-compat). The §41.b
  rewire of `check_session_duality` accepts every v2.2.x dual pair
  the old positional check accepted.
- `socket` is **new** in v2.3.0 — adoption is opt-in (a v2.2.x
  deployment without `socket` declarations runs identically; only
  protocols you choose to bind to a transport get the typed-WS surface).
- The credit-refined backpressure index is opt-in via
  `backpressure: credit(k)` on the `socket`. Sockets without the
  annotation run in the unbounded fragment (the §41.c constraints
  are vacuously satisfied).
- The `cognitive_states` typed-reconnection is opt-in via
  `reconnect: cognitive_state` on the `socket`. Sockets without it
  treat a mid-protocol disconnect as terminal.
- The multiparty algebra (`GlobalType` + `project_all`) is a new
  programmatic surface — no source-level grammar yet (deferred to a
  follow-up). v2.3.0 adopters build `GlobalType` values
  programmatically and use the projection results directly.

---

## The four pillars

The Fase 41 cycle's theoretical grounding lives in
[`paper_websocket_cognitive_primitive.md`](paper_websocket_cognitive_primitive.md) — every D-letter of the plan vivo cross-references it.

| Pillar | Anchor in the cycle |
|---|---|
| **Mathematics** | Caires–Pfenning Curry-Howard isomorphism: session types ARE intuitionistic linear-logic propositions; duality is the involution `(·)⊥`; the regular-coinductive equality decides `μ`-types. |
| **Philosophy** | Lorenzen dialogical logic + Abramsky game semantics: a connection IS a dialogue game; endpoint duality is (Proponent, Opponent). |
| **Logic** | Honda–Yoshida–Carbone multiparty session types: the projection theorem turns the global view into independent per-role local types; Rast credit-refined types lift this to a Presburger-decidable resource discipline. |
| **Computation** | π-channels + tokio: the §41.d runtime realises the algebra over RFC 6455 WebSocket carriers; the §41.e SSE-as-fragment unification reuses the §Fase 33 streaming infrastructure unchanged. |

The cycle's deliverables are the bridge — algebra to wire to
production, every step a typed function with a `Result<_, TypedError>`
shape so the failure case is enumerable.
