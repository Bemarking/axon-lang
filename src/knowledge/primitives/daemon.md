---
name: daemon
summary: A long-lived, supervised cognitive process — reacts to events on declared listeners with structured restart semantics.
category: wire
top_level: true
since: Fase 16
grammar: |
  daemon <Name> [(<params>)] [-> <ReturnType>] {
      goal: "<string>"                                    # optional
      tools: [<Tool1>, ...]                               # optional
      memory: <MemoryRef>                                  # optional
      strategy: <react|plan_and_execute|reflexion|custom>  # optional
      on_stuck: <escalate|forge|hibernate|retry>           # optional
      shield: <ShieldRef>                                  # optional
      max_tokens: <integer>                                # optional
      max_time: <duration>                                 # optional
      max_cost: <number>                                   # optional
      listen <channel-ref|"<topic>"> [as <alias>] [{...}] # optional, repeatable — event listeners
  }
---

# `daemon`

`daemon` declares **a long-lived, supervised cognitive process**.
Where `flow` runs once per `run` and `agent` runs an iterative
goal-directed loop on demand, `daemon` runs **continuously** —
waiting for events on declared listeners and dispatching typed
messages to its handler logic.

This is AXON's actor surface. A daemon is the closest the
language gets to a "service" in the operational sense: it has
identity, lifecycle, supervised restarts, and an event surface.
The Fase 16 supervisor handles restart policies + crash
containment; daemons are sandboxed by construction.

## Surface

`daemon` is a **top-level declaration**. It is *not* nested
inside another primitive.

```axon
daemon TicketRouter {
    goal:       "Route inbound tickets to the right SLA queue."
    tools:      [TicketDB, SlackNotifier]
    memory:     RouterState
    strategy:   react
    on_stuck:   retry
    shield:     CustomerDataShield
    max_tokens: 16000
    max_time:   30m

    listen "tickets.inbound" as msg
    listen TicketChannel as event
}
```

## Fields

### `goal:` (optional)

A **string literal** declaring the daemon's persistent
objective. Surfaces in the audit chain on every event dispatch.

### `tools:` / `memory:` / `strategy:` / `on_stuck:` / `shield:` (optional)

Mirror the `agent` primitive's fields exactly:

- `tools:` — bracketed list of declared tools the daemon may
  call.
- `memory:` — bound memory store for cross-event state.
- `strategy:` — closed catalogue: `react`,
  `plan_and_execute`, `reflexion`, `custom`.
- `on_stuck:` — closed catalogue: `escalate`, `forge`,
  `hibernate`, `retry`.
- `shield:` — defence layer wrapping every event handler.

### `max_tokens:` / `max_time:` / `max_cost:` (optional)

Per-event budgets. Reaching any budget triggers `on_stuck:`.
The supervisor tracks across the daemon's lifetime — sustained
budget breaches are an operational signal, not a one-shot
failure.

### `listen <channel-ref|"<topic>"> [as <alias>] [{...}]` (optional, repeatable)

The daemon's **event surface**. Each `listen` line binds an
incoming event source. Two forms:

1. **Channel reference** (canonical since Fase 13.g — typed
   channels): `listen TicketChannel as event`.
2. **String topic** (legacy, pre-Fase 13): `listen
   "tickets.inbound" as msg`.

Multiple `listen` lines stack — the daemon multiplexes across
all bound sources. The optional `as <alias>` binds the event
payload to a named variable visible inside the (today
structurally-skipped) listener body.

## Runtime behaviour

`daemon` lowers to a `DaemonDefinition` IR node carrying its
declared listeners. At deploy time, the Fase 16 supervisor:

1. Mounts the daemon as a supervised process under the
   declared budgets.
2. Subscribes to every `listen` source.
3. Spins up an event-handler instance per arrival.
4. On crash → restart per the supervisor's policy (exponential
   backoff, max_restarts, escalation channel).

Every event dispatch emits `daemon:<name>:<event_id>` audit
rows carrying `(channel, payload_hash, handler_outcome,
duration)`.

## What this primitive is NOT

- **Not an `agent`.** An agent is goal-directed for one
  invocation; a daemon is persistent and event-driven. The
  two compose: a daemon can spawn agents per event.
- **Not a microservice.** A daemon lives within the AXON
  runtime's supervised process tree, not as a separate
  container. For multi-container deployments, declare
  multiple manifests; each can host one daemon.
- **Not unsupervised.** Production daemons declare `shield:`
  AND budgets. The Fase 16 supervisor refuses to mount a
  shield-less daemon in regulated environments.
- **Not the same as `listen` (the flow-step)**. The
  flow-body `listen` is a one-shot subscription inside a
  flow's execution. A daemon's `listen` lines are persistent
  subscriptions across the daemon's lifetime.

## See also

- `axon://primitives/agent` — single-invocation iterative
  cognitive entity.
- `axon://primitives/listen` — the flow-body counterpart.
- `axon://primitives/shield` — required defence wrapper.
- `axon://primitives/memory` — bound state across events.
