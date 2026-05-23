---
name: session_duality
title: Session duality — the §Fase 41 algebra rules
summary: Caires-Pfenning + Honda-Yoshida duality rules for AXON sessions. Regular-coinductive equality, credit-refined backpressure, multiparty projection — the actual rules the §41 type checker discharges.
---

# Session duality — §Fase 41 algebra rules

A `socket` binds a top-level `session` declaration to a WebSocket
carrier (RFC 6455). The compiler does not just check that two
endpoints exist; it verifies — at parse + type-check time — that
the two roles of the bound session are **algebraic duals** under
the Caires-Pfenning session-types calculus.

This page is the reference for the rules. The implementation lives
in [`axon-frontend/src/session.rs`](https://github.com/Bemarking/axon-lang/blob/master/axon-frontend/src/session.rs)
and [`axon-frontend/src/multiparty.rs`](https://github.com/Bemarking/axon-lang/blob/master/axon-frontend/src/multiparty.rs);
the math is in
[`docs/papers/paper_websocket_cognitive_primitive.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/papers/paper_websocket_cognitive_primitive.md).

## The four-pillar §41 algebra

The §Fase 41 system rests on four pillars. Each is enforced by the
compiler; each emits structured diagnostics if violated.

### Pillar 1 — Duality (§41.a)

For every `session S { client: C, server: S }`, the connection
law is:

```
S ≡ C⊥
```

where `⊥` is the dual operator:

| Action | Dual |
|---|---|
| `send T`            | `receive T`     |
| `receive T`         | `send T`        |
| `select { a:S₁ }`   | `branch { a:S₁⊥ }` |
| `branch { a:S₁ }`   | `select { a:S₁⊥ }` |
| `loop, X`           | `loop, X`       |
| `end`               | `end`           |
| `μX.S`              | `μX.S⊥`         |
| `X`                 | `X`             |

**Regular-coinductive equality.** Two session types are equal if
their *regular tree unfoldings* coincide. This means `μX.send T,
X` and `μY.send T, Y` are equal (α-equivalent recursion variables
are accepted).

The compiler computes both sides' dual normal forms and tests
syntactic equality on the canonical tree.

Violation diagnostic: `Session 'X' duality violation: …`.

### Pillar 2 — Linearity (§41.a)

A typing context `Δ` is **linear**: each channel `x: S ∈ Δ` is
used exactly once along every path. The branching rules `select`
and `branch` recover the context per branch:

```
Δ ⊢ x: select { lᵢ:Sᵢ }
———————————————————————
Δ, x: Sᵢ ⊢ branch_arm_i
```

Linearity prevents accidental fanout of session-typed channels
(only `socket` carriers may multiplex; `session`-typed values
themselves are single-owner).

### Pillar 3 — Credit-refined backpressure (§41.c)

When a `socket` declares `backpressure: credit(n)`, every `send`
in the session type carries a **credit index**: `!ⁿT.S` (paper
§4.2). The well-formedness conditions are decidable in **Presburger
arithmetic**:

| Verdict | Condition | Diagnostic |
|---|---|---|
| `SendAtZero` | the type contains `!⁰T.S` | "send `T` at credit n=0 has no typing rule" |
| `BurstOverflow` | a straight-line send-burst > n | "the protocol requires a send-burst of N but `credit(n)` cannot absorb it" |
| `LoopUnsustainable` | recursive body has Δ = #send − #recv > 0 | "recursive body is unsustainable: Δ = … > 0" |

`n` must be `≥ 1`. A zero-credit window has no typing rule for any
send.

### Pillar 4 — Multiparty projection (§41.h)

For multi-role protocols (3+ participants, e.g. client / server /
auditor), the §41.h Honda-Yoshida-Carbone projection rule
*projects* a global type onto each role's local type, then checks
**safe realizability**: every projected pair is dual.

```
G = msg(client → server, Request);
    msg(server → auditor, AuditEntry);
    msg(server → client, Response);
    end
```

projects to:

```
G ↾ client  = send Request, receive Response, end
G ↾ server  = receive Request, send AuditEntry, send Response, end
G ↾ auditor = receive AuditEntry, end
```

The compiler verifies that every pairwise dual holds. The
**non-participation rule** (a role that the body never mentions
projects to `end`) is built into the projector to avoid spurious
diagnostics.

Implementation: `axon-frontend::multiparty::project_all`.

## The cognitive-state hook

A `socket` declared with `reconnect: cognitive_state` seals the
**residual session-type cursor** plus the live credit window into an
AAD-bound snapshot on disconnect. The resume protocol decrypts the
residual and restores both pillars 1 + 3 at the exact same point.

This is not a separate algebra; it is the same §41 rules applied to
the residual. The AAD binding (paper §5.3) prevents a client from
resuming someone else's session.

## Practical agent recipes

### A. Writing a duality-correct session

When declaring a session, write the **client** role end-to-end,
then mechanically dualise to get the **server** role. The compiler
will catch any deviation:

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

Every `send` ↔ `receive`, every `select` ↔ `branch`, every label
appears in both arms.

### B. Picking a credit window

The §41.c discipline:

- **n = 1** — turn-taking dialogue (chat). Producer sends one
  utterance, waits for ack/response.
- **n = 4–8** — typical conversational SSE-like streaming. Buffers
  bursts but stays bounded.
- **n ≥ 16** — bulk transfer / pipelining patterns. Verify with the
  Presburger checker that the recursive body's Δ ≤ 0.

The compiler rejects `credit(0)` and any send-burst exceeding `n`.

### C. Multiparty: client / server / auditor

The §41.h projection rule is exposed when you declare a session
with 3+ roles. The agent does not declare projections manually —
the compiler projects + checks safe realizability automatically.
The error surface tells the agent which role's projection failed:

```
multiparty_projection_failed: at role 'auditor' — the projected
type expects `receive Decision` but the global type does not emit
one to this role.
```

## What is NOT in this algebra

- **Subtyping.** AXON session types are not subtyped (no `S ≤ T`
  rule). Two sessions are either equal-modulo-α or distinct.
- **Higher-order session passing.** `send T.S` where T is itself a
  session type is **not** supported in v2.x. This is a known
  extension under research; the §Fase 13 mobile typed channels
  cover the practical use cases via a different mechanism.
- **Synchronous duality across multiple sockets.** Each `socket` is
  its own duality boundary. To make a multi-socket dance type-safe,
  declare a single multiparty session and project — do not stack
  sockets.

For the proofs, see the paper. For the implementation, see the
linked source. For the *intent* — write protocols that don't
deadlock — apply the four pillars above.
