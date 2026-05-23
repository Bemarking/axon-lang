# Migrating to axon-lang v2.3.0 (Fase 41 — WebSocket as a Cognitive Primitive)

> **TL;DR — v2.3.0 is fully backwards-compatible with v2.2.x.** Every
> existing `session` declaration keeps compiling unchanged; the WS
> surface + multiparty primitives are opt-in. Most adopters need to
> change nothing. The recipes below are for adopters who want to
> **adopt** the new primitives — typed-WS dialogue, SSE-as-fragment,
> typed reconnection, multiparty.

See the full reference: [`docs/ADOPTER_SESSION_TYPES.md`](ADOPTER_SESSION_TYPES.md).

---

## Recipe 1 — Adopt the `socket` declaration for a v2.2.x `session`

You already have a `session` declared in v2.2.x source. To expose it
over a real-time WebSocket carrier:

```diff
  session Chat {
      client: [send Utt, receive Tok, end]
      server: [receive Utt, send Tok, end]
  }
+ socket ChatWS {
+     protocol: Chat
+ }
```

The enterprise server (v2.3.0+) automatically mounts
`GET /api/v1/socket/chatws` on boot. No code changes needed in the
client beyond connecting + sending the typed frames.

The pre-`socket` deployment continues to work identically — the v2.2.x
`session` declaration alone has no transport binding, only the static
duality check.

## Recipe 2 — Add credit-refined backpressure

A producer-heavy protocol benefits from an explicit credit window:

```diff
  session TokenStream {
-     server: [loop, send Token, loop]
-     client: [loop, receive Token, loop]
+     server: [loop, send Token, receive Ack, loop]
+     client: [loop, receive Token, send Ack, loop]
  }
+ socket Stream {
+     protocol: TokenStream
+     backpressure: credit(64)
+ }
```

The §41.c Presburger discharge runs at compile time:
- Δ = `#send − #recv` per recurring iteration must be ≤ 0.
- A straight-line send-burst must fit in the window.
- An explicit `!⁰` is rejected as "no rule at n=0".

If the check fails, the diagnostic names the offending step + the
expected window vs. the demanded burst — no runtime surprises.

## Recipe 3 — Enable typed reconnection

For a long-lived dialogue (chat, agent-with-tools), declare resume:

```diff
  socket ChatWS {
      protocol: Chat
      backpressure: credit(8)
+     reconnect: cognitive_state
  }
```

The server now:
1. Returns `X-Axon-Session-Id: <id>` on the upgrade response.
2. Seals the residual cursor + credit window on any mid-protocol
   disconnect (TTL 5 min by default).
3. Accepts `?resume=<id>` on a new connection to the same socket
   path; restores under (tenant, session, flow_id) AAD binding.
4. Evicts the snapshot on clean session-end (replay defence).

**Client-side change**: on `WebSocket` `onclose` mid-protocol, retry
with `?resume=<the_session_id_received_on_upgrade>`:

```js
const ws = new WebSocket(url);
let sessionId = null;
ws.onopen = (e) => {
  // The session id is in the response headers, surfaced by axum.
  sessionId = e.target.protocol /* or fetched via a sibling endpoint */;
};
ws.onclose = (e) => {
  if (e.code !== 1000 && sessionId) {
    // Mid-protocol drop — reconnect with resume.
    const ws2 = new WebSocket(`${url}?resume=${sessionId}`);
    // …continue from where we left off.
  }
};
```

**Server-side resume rejection codes** (HTTP 410 Gone, JSON body):

| Code | Meaning | Client action |
|---|---|---|
| `resume_not_found` | No snapshot for this id. | Start fresh. |
| `resume_expired` | TTL elapsed. | Start fresh. |
| `resume_aad_mismatch` | Wrong tenant / socket / rotated key. | Start fresh. |
| `resume_malformed` | Decrypted envelope didn't parse. | Start fresh + report bug. |
| `resume_schema_drift` | A deploy bumped the protocol. | Start fresh. |

## Recipe 4 — Expose a producer-only `session` as SSE

A pure-producer (single-polarity) protocol works over both WebSocket
*and* W3C Server-Sent Events with **zero code changes**. The client
opts into SSE by setting the `Accept` header:

```diff
  session TokenStream {
      server: [loop, send Token, loop]
      client: [loop, receive Token, loop]
  }
  socket Stream {
      protocol: TokenStream
  }
```

```js
// Client A — WebSocket (full bidirectional):
const ws = new WebSocket("wss://acme.bemarking.com/api/v1/socket/stream");

// Client B — SSE (one-way, simpler client code):
const es = new EventSource("https://acme.bemarking.com/api/v1/socket/stream", {
  // (handled via fetch + ReadableStream in real code — EventSource doesn't
  // support custom headers; use the SDK or a small fetch wrapper)
});
es.addEventListener("axon.send", (e) => { /* one Token per event */ });
es.addEventListener("axon.end", () => es.close());
```

The wire bytes are byte-compatible with Fase 33's SSE machinery
(`event: axon.send`, `data: {…}`, `\n\n`). For non-single-polarity
protocols, SSE returns one `axon.error{code:"non-sse-polarity-schema"}`
event and closes; the WebSocket carrier still works.

## Recipe 5 — Use the multiparty algebra programmatically

For a n-party orchestration (agent + skill + user), build a
`GlobalType` in code, project per role, and feed each projection into a
per-role runtime instance.

```rust
use axon::multiparty::{GlobalType, Role};
use axon::session_runtime::SessionRuntime;

// 1. Declare the global protocol.
let g = GlobalType::message("User", "Agent", "Query",
    GlobalType::message("Agent", "Tool", "SubQuery",
        GlobalType::message("Tool", "Agent", "Result",
            GlobalType::message("Agent", "User", "Reply", GlobalType::End)
        )
    )
);

// 2. Safe-realizability gate.
let projection = g.project_all()
    .expect("the gate is the structural correctness certificate");

// 3. Each role's runtime drives its projected SessionType.
let user_role = Role::new("User");
let user_runtime = SessionRuntime::new(projection[&user_role].clone(), None);
// …repeat for Agent + Tool.
```

The §41.h projection theorem guarantees the three independent runtimes
stay in lock-step. If `project_all` returns `Err(ProjectionError::…)`,
the global protocol is **not** realizable — restructure (typically by
propagating a choice that a non-participant role couldn't observe;
see [`ADOPTER_SESSION_TYPES.md § Multiparty
protocols`](ADOPTER_SESSION_TYPES.md#multiparty-protocols)).

---

## v2.2.x compatibility checklist

If you make **no source changes**, what runs differently after the
v2.3.0 upgrade?

- **Nothing observable.** The §41.b rewire of `check_session_duality`
  accepts every dual pair the v2.2.x positional check accepted; the
  new diagnostics are emitted only on programs that violate the
  algebra-level connection law (which the v2.2.x check would also have
  rejected).
- **Internal**: `SessionType` enum gained `credit: Option<u64>` on
  `Send`/`Recv`. Existing call sites use the smart constructors
  (`SessionType::send` / `recv`), which default `credit = None` — no
  source change. If you matched directly on `SessionType::Send(_, _)`
  (the old tuple variant) you need to update to the struct-variant
  syntax — `SessionType::Send { payload, credit, cont }`. Search your
  codebase for `SessionType::Send(` or `SessionType::Recv(` to find
  these sites.
- **New imports available**: `axon::session_runtime::*`,
  `axon::session::Polarity`, `axon::multiparty::*`. Old paths still
  work.

## Wire compatibility (D8 / Fase 33 byte-compat)

The §41.e SSE driver emits bytes byte-compatible with Fase 33's W3C
SSE framing: same `Content-Type: text/event-stream`, same `event:` +
`data:` + `\n\n` event-terminator, same UTF-8 discipline. The event
**names** are namespaced under `axon.send` / `axon.select` / `axon.end`
/ `axon.error` — distinct from Fase 33's `axon.token` / `axon.complete`
cohort, but the framing rules are identical, so any
standards-compliant SSE consumer (browsers' `EventSource`, the Fase 33
`bytes_stream_to_sse_events` parser) decodes without
axon-version-specific knowledge.

## Enterprise upgrade (axon-enterprise)

The companion enterprise release (v2.X.0 — see the enterprise
changelog) ships:
- The `socket:connect` RBAC capability (granted to `owner` + `admin` +
  `developer` by default; `viewer` excluded).
- Four new `AuditEventType` variants for the WS lifecycle
  (`session:ws_opened` / `_utterance` / `_denied` / `_closed`) +
  three for the typed-reconnection family (`_sealed` / `_resumed` /
  `_resume_rejected`).
- The new route `GET /api/v1/socket/{name}`, protected by the
  existing `require_auth` middleware.
- A new `CognitiveStateRepo` trait + `PgCognitiveStateRepo` adapter
  for the §40.t snapshot store.

No DB migration needed — the existing `axon_control.audit_events`
table's `event_type VARCHAR(64)` accepts the new slugs without a
schema change; the `cognitive_states` table was already migrated as
part of Fase 40.t.

After the enterprise upgrade, sockets are exposed at the standard
control-plane port (8080); no `EXPOSE` change in the Dockerfile.
