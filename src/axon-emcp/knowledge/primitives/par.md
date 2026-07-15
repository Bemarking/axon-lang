---
name: par
summary: "Concurrent fan-out — executes its branches in parallel (a real `join_all`, §65) and joins their results; branch tool calls ride the §114.e channel semaphore."
category: cognition
top_level: false
since: "pre-§65; real fan-out Fase 65"
grammar: |
  par {
      <branch-steps>
  }
---

# `par`

`par` is **concurrent fan-out**: its branches execute in parallel and
their results join.

## What the runtime actually does (§65)

A real `futures::join_all` over the lowered branches
(`parallel::run_par`) — not sequential execution wearing a concurrent
keyword. Branch tool calls ride the §114.e channel semaphore, so a
`resource { capacity: N }` bound holds ACROSS a fan-out.

## Honest limits

Static branches only: `par over <collection>` (dynamic fan-out) does
not exist in the grammar today, which is also why `par` needs no
concurrency backstop of its own — the author writes each branch.

## See also

- `axon://primitives/tool` — calls inside branches stay governed.
