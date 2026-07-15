---
name: drill
summary: "Subtree descent under a prior navigate — real navigation when a source is in scope; degrades to a placeholder otherwise (§111)."
category: data_plane
top_level: false
since: Fases 62–65 (PIX·MDN program)
grammar: |
  drill <target>
---

# `drill`

`drill` descends into a subtree surfaced by a prior `navigate`.

## Honest scope (§111)

Real subtree navigation **when a source is in scope**; degrades to a
placeholder string otherwise. Same discipline as `navigate`: the
deterministic engines are real, the sourceless path is not evidence.

## See also

- `axon://primitives/navigate` — the entry verb + the F11 warning.
