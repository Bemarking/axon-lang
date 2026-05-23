---
name: session
summary: Declares the typed bidirectional dialogue protocol a socket carries — §41 algebra (send/receive/select/branch/loop/end).
category: session_types
top_level: true
since: Fase 41.a (v2.3.0)
grammar: |
  session <Name> {
      <role1>: [<SessionStep>, <SessionStep>, ...]
      <role2>: [<SessionStep>, <SessionStep>, ...]
      ...
  }

  # SessionStep ::= send <Type>
  #              | receive <Type>
  #              | select { <label>: [<SessionStep>, ...], ... }
  #              | branch { <label>: [<SessionStep>, ...], ... }
  #              | loop
  #              | end
---

# `session`

`session` declares **the typed bidirectional dialogue protocol**
a `socket` carries. Where `socket` is the transport (RFC 6455
WebSocket), `session` is **the type of the connection** — the
ordered, polarised algebra of utterances the two endpoints
exchange. The compiler verifies the two roles are algebraic
duals at parse time (the §41.a connection law: `peer ≡ self⊥`).

This is the formal heart of Fase 41. A `session` is a closed
algebraic surface — `send`, `receive`, `select`, `branch`,
`loop`, `end` — grounded in Caires-Pfenning session types
(intuitionistic linear propositions). A session declaration is
**proof** that the dialogue cannot deadlock at runtime under
honest peers.

## Surface

`session` is a **top-level declaration**. It is *not* nested
inside another primitive. A `socket` references it via
`protocol: <SessionName>`.

```axon
session Chat {
    client: [
        loop,
        select {
            ask:    [send Utterance, branch {
                        token: [receive Token, loop],
                        done:  [end]
                    }],
            cancel: [end]
        }
    ]
    server: [
        loop,
        branch {
            ask:    [receive Utterance, select {
                        token: [send Token, loop],
                        done:  [end]
                    }],
            cancel: [end]
        }
    ]
}
```

## Anatomy

### `session <Name>` — the head

A **PascalCase identifier**, unique within the module. The
compiler builds a per-module session symbol table; `socket
protocol: <Name>` references resolve here.

### Roles — `<role>: [<steps>]` pairs

Each role is a **named, ordered list of session steps**. The
canonical 2-role shape is `{ client: [...], server: [...] }`
but the grammar accepts arbitrary role names. Multiparty
sessions (3+ roles) trigger the §41.h Honda-Yoshida-Carbone
projection rules; the compiler emits per-role local types and
verifies safe realizability automatically.

### Session steps — the closed algebra

The grammar accepts exactly six step kinds:

| Step | Meaning |
|---|---|
| `send <Type>` | Send a value of `<Type>` to the peer. |
| `receive <Type>` | Receive a value of `<Type>` from the peer. |
| `select { ℓ: [...], ... }` | Internal choice — this role picks a label. |
| `branch { ℓ: [...], ... }` | External choice — this role waits to learn a label. |
| `loop` | Iterate — fold back to the head of the enclosing step list. |
| `end` | Terminate the role. |

`select` and `branch` are syntactic ⊕ / & — the duality
operator `(·)⊥` swaps them (just as it swaps `send` ↔
`receive`).

## Duality — the §41.a connection law

For every `session S { role_a: A, role_b: B }`, the compiler
enforces:

```
B ≡ A⊥        (under regular-coinductive equality)
```

where `(·)⊥` is the dual involution:
- `(send T)⊥ = receive T`
- `(receive T)⊥ = send T`
- `(select { ℓ: S })⊥ = branch { ℓ: S⊥ }`
- `(branch { ℓ: S })⊥ = select { ℓ: S⊥ }`
- `loop⊥ = loop`, `end⊥ = end`
- `μX.S⊥ = μX.S⊥`, `X⊥ = X`

Two session types are equal if their **regular tree
unfoldings** coincide — α-equivalent recursion variables are
accepted. Violations emit a typed
`Session 'X' duality violation: …` diagnostic.

## Multiparty (§41.h)

A session with 3+ roles triggers the Honda-Yoshida-Carbone
projection: the global protocol is projected onto each role's
local type via `G⌐r`, then **safe realizability** is checked
pairwise. The compiler emits per-role projections and the
multi-party projection failure surface (`multiparty_projection_failed
at role 'X'`) when the projection is inconsistent.

## Runtime behaviour

`session` is a **type, not a value** — it has no runtime
existence beyond its appearance as the `protocol:` field on a
`socket`. The runtime threads the session-type cursor through
the socket carrier; every send/receive advances the cursor;
mismatched payloads at runtime become structured WebSocket
closure codes (see `axon://primitives/socket` for the closure
catalogue).

For `socket reconnect: cognitive_state`, the residual session
type at disconnect is AAD-bound into the snapshot — resume
restores the exact cursor position.

## What this primitive is NOT

- **Not a transport.** `session` is the *type* of the
  dialogue; `socket` is the *carrier*. The two are
  declared separately and bound via `socket protocol: <Name>`.
- **Not a state machine.** A session type compiles to a
  state machine, but the declaration is algebraic — the
  type-checker reasons about it as a typed term, not a graph.
- **Not subtyped.** Two sessions are either equal-modulo-α or
  distinct. AXON v2.x has no session subtyping rule (no
  width / depth / variance — out of scope for the Fase 41
  algebra; tracked for a future research line).
- **Not for one-shot RPC.** For request/response with no
  conversation, use `axonendpoint` (HTTP REST). `session` is
  for *dialogue* — repeated exchanges with declared structure.

## See also

- `axon://primitives/socket` — the carrier that binds a session.
- `axon://logic/session_duality` — the §41 algebra rules + the
  four pillars + practical agent recipes.
- `axon://primitives/axonendpoint` — REST endpoint primitive
  for non-dialogue request/response.
- [`docs/papers/paper_websocket_cognitive_primitive.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/papers/paper_websocket_cognitive_primitive.md)
  — the four-pillar paper underpinning Fase 41.
