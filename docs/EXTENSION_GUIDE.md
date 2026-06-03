# The `extension` declaration — extending closed catalogs (§Fase 53)

Axon's effect rows and shield scan categories are **closed catalogs**: the
type-checker and the Proof-Carrying Code (PCC) verifier reject any base or
category they don't recognize. That keeps the four pillars sound — but it also
means a domain-specific vocabulary (a confidence axis, a compliance scan
taxonomy) has nowhere to live without either stripping the semantics or coupling
to the canonical catalog.

The `extension` declaration closes that gap. It lets you declare domain-specific
**provenance** members **up front, in source** — auditable and gateable — so the
type-checker, PCC, and shield treat them as first-class, *without* touching the
canonical catalog and *without* weakening any guarantee.

## Syntax

```axon
extension <name> {
  category: effects | scan
  members: [
    "<member>" : { semantics: "<text>", default_confidence: <0.0..1.0> },
    "<member>",
    ...
  ]
}
```

- **`category: effects`** — declares provenance effect-row members (e.g. a
  confidence/provenance axis). A member is typically `axis:value`
  (`"risk:elevated"`). Optional metadata: `semantics` (free text) and
  `default_confidence` (a number in `[0.0, 1.0]`).
- **`category: scan`** — declares shield scan categories (e.g. a domain
  compliance taxonomy). Members are bare category names (`"dunning_pressure"`).

### Example

```axon
extension risk_axis {
  category: effects
  members: [
    "risk:elevated" : { semantics: "external, partially-trusted source", default_confidence: 0.80 },
    "risk:high"     : { semantics: "untrusted source",                   default_confidence: 0.95 }
  ]
}

extension collections_scans {
  category: scan
  members: [ "dunning_pressure", "promise_to_pay_coercion" ]
}

tool LookupCustomer { effects: <network, risk:elevated> }      # accepted

shield CollectionsGuard {
  scan: [dunning_pressure]                                     # accepted
  strategy: pattern
  on_breach: halt
}
```

## The rules (and why)

The mechanism is deliberately constrained so it can never be used to weaken the
language's guarantees:

1. **Provenance-class only — you cannot extend the *enforceable* effect set.**
   An `effects` member whose base is a canonical enforceable base
   (`io`, `network`, `storage`, `stream`, `trust`, `sensitive`, …) is a
   **compile error**. Extension members are annotations over provenance + certainty
   (`ρ`, `c`); they carry **no runtime capability**. This is what stops a flow
   declaring `extension { members: ["io:bypass_shield"] }` to smuggle an
   unenforceable privileged effect under a custom name.

2. **No shadowing.** An `effects` member may not redefine a canonical base; a
   `scan` member may not redefine a canonical scan category. Shadowing is a
   compile error.

3. **`default_confidence` is a ceiling, not a floor.** A declared
   `default_confidence` is the *most* certainty a member announces; runtime
   uncertainty always wins (`c_out = min(default_confidence, c_in)`). A
   doubtful input is never laundered up to the declared ceiling.

4. **No phantom guardrails.** A shield that *uses* an extension-declared `scan`
   category **must** have a concrete scanner registered for it. If none is
   registered, the server **refuses to boot** (fail loud) rather than silently
   pass the content through — an undeclared guardrail would be a false sense of
   security. (Canonical categories are exempt: their identity passthrough is the
   documented default.)

## Why it stays sound (PCC)

Extensions are part of the compiled artifact (they ride in the IR). The PCC
verifier re-derives the set of honored provenance members **from the artifact's
own extensions** — it never consults an external registry and never trusts the
compiler. So a proof is self-contained: an independent `axon pcc verify` against
the same artifact reaches the same verdict. A tool using an extension-declared
member verifies; a member no extension declares still refutes; a member
shadowing an enforceable base is excluded from the provenance set by the
verifier itself.

## Audit + gating

Because extensions are declared in source, they are visible to the deploy gate
and the audit log. An operator can inspect exactly which provenance vocabularies
a flow introduces, and (enterprise) allow/deny specific extensions per tenant.
An extension is never implicit.
