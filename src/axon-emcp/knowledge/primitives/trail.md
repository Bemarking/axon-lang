---
name: trail
summary: "Reads the breadcrumb a navigate seeded — a real provenance trail when navigation was deterministic; inherits §111 F11 on the LLM fallback path."
category: data_plane
top_level: false
since: Fases 62–65 (PIX·MDN program)
grammar: |
  trail <navigate-binding>
---

# `trail`

`trail` reads the breadcrumb a prior `navigate` seeded — the
provenance record of the walk.

## Honest scope (§111)

The breadcrumb is REAL when navigation ran a deterministic engine.
⚠️ It **inherits F11**: a trail harvested from the LLM fallback is a
fabricated audit. A trail is only as trustworthy as the walk that
seeded it.

## See also

- `axon://primitives/navigate` — the seeding verb + the F11 warning.
