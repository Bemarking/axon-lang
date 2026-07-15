---
name: extension
summary: "The closed-catalog extension mechanism (#15→§53) — an internal composition mechanism, deliberately not advertised as a primitive."
category: operators
top_level: true
since: Brief #15 → Fase 53
grammar: |
  extension <Name> {
      category: <scan|...>
      # closed-catalog extension members
  }
---

# `extension`

`extension` is the **closed-catalog extension mechanism** (#15 → §53):
it lets a deployment introduce members into designated closed catalogs
(e.g. shield scan categories) without forking the language.

## Deliberately NOT advertised

`is_advertised: false` in the registry: this is an internal composition
MECHANISM, not a promised cognitive primitive. Its safety law is §53.e
**no phantom guardrails**: an extension-introduced scan category used by
a shield with no registered scanner refuses to BOOT (fail loud) —
serving it as a silent no-op would be a false sense of security.

## Proof

`fase53_a/b/c_extension_*.rs` (grammar/IR/typecheck) +
`shield_registry::check_extension_scan_coverage` (the §53.e boot gate).

## See also

- `axon://primitives/shield` — the main catalog extensions target.
