---
name: listen
summary: A flow/daemon-body listener — binds to an event source and dispatches typed messages downstream.
category: wire
top_level: false
since: Fase 16
grammar: |
  # Flow-body / daemon-body form:
  listen <ChannelRef|"<topic-string>"> [as <alias>] [{ ... }]
---

# `listen`

`listen` declares **a subscription to an event source** inside a
flow body or a daemon body. It binds either a **typed channel
reference** (the canonical Fase 13.g+ form) or a **string topic**
(the pre-Fase 13 legacy form, deprecated but still parsed), and
optionally aliases the incoming payload to a name visible in the
listener's body.

Inside a flow, a `listen` is a **one-shot subscription** that
runs until the listener body completes. Inside a daemon, a
`listen` declaration is **persistent** — the daemon subscribes
at startup and routes every arrival to the handler logic for
the daemon's lifetime.

## Surface

`listen` is **nested** — it appears in two places:

1. As a **flow-body step** alongside `step`, `if`, `for`, …
2. As a **daemon-body declaration** alongside `goal:`,
   `tools:`, … (and one daemon may stack multiple `listen`s).

```axon
# Inside a flow — single subscription, runs until handler returns.
flow ProcessIncoming(channel: Channel<TicketEvent>) -> Receipt {
    listen channel as event {
        step Triage {
            given: event
            ask: "Assign the right SLA queue."
            output: Receipt
        }
    }
}

# Inside a daemon — persistent subscription across daemon lifetime.
daemon TicketRouter {
    goal: "Route inbound tickets."
    tools: [TicketDB]

    listen TicketChannel as event
    listen "tickets.urgent" as urgent_msg
}
```

## Anatomy

### Source — channel reference OR string topic

The first token after `listen` distinguishes the two forms:

| Form | Token | Semantic |
|---|---|---|
| **Typed channel** | identifier | References a declared `channel` (Fase 13). Type-checked. **Canonical.** |
| **String topic** | string literal | Legacy free-form topic. No type check. Deprecated since Fase 13. |

The typed form is **strongly preferred** in new code — it gives
the type checker visibility into the event payload shape and
the §13 mobility analysis can reason about capability extrusion.

### `as <alias>` (optional)

A **single identifier** binding the event payload to a name
inside the listener body. Without `as`, the payload is only
referenceable via positional defaults (the runtime exposes
`event`).

### Body `{ ... }` (optional)

A braced block. **In flows**, the body is the handler — the
flow steps that run for each arrival. **In daemons**, the
body is currently skipped structurally (the daemon's
top-level fields take over).

## Runtime behaviour

For a **flow-body listen**: the runtime mounts a subscription
when the step is reached, blocks until an event arrives, runs
the body with the alias bound, then returns control to the
flow. The flow's audit row carries `(channel, event_id,
handler_outcome)`.

For a **daemon-body listen**: the supervisor mounts the
subscription at startup, dispatches each arrival as an
isolated handler invocation, and audits per-event under
`daemon:<name>:<channel>:<event_id>`.

For **typed-channel listens**, the type checker enforces:
- The bound channel's declared payload type matches the
  alias's downstream consumers.
- Capability extrusion (Fase 13.f) — sending the channel out
  of scope is rejected unless the receiver carries the same
  capability.

## What this primitive is NOT

- **Not a top-level declaration.** Outside a flow / daemon
  body the parser rejects `listen` as an unexpected token.
- **Not a `channel`.** A channel is the declared event
  **source** (Fase 13.g — typed mobile channels); listen is
  the declared **subscription** to a channel.
- **Not a webhook handler.** For HTTP-incoming events,
  declare an `axonendpoint`. `listen` is for the
  push/pubsub layer (Kafka, NATS, in-process channels).
- **Not free of capability checks.** A typed-channel listen
  carries the channel's required capability; the §13 mobility
  analysis enforces extrusion soundness.

## See also

- `axon://primitives/daemon` — the most common context for
  persistent `listen` subscriptions.
- `axon://primitives/flow` — flow-body `listen` for one-shot
  subscriptions.
- `axon://primitives/channel` — the typed channel primitive
  (Fase 13.g).
- `axon://primitives/axonendpoint` — HTTP counterpart for
  request-driven events.
