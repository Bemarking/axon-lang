---
name: composition
title: Composition & nesting rules
summary: How AXON constructs compose — what may nest inside what, how cross-construct references resolve, and why the language is intentionally flat at the top level.
---

# Composition & nesting rules

AXON is **deliberately flat at the top level**. A program is a
sequence of declarations (`persona`, `flow`, `anchor`, `tool`,
`type`, `axonendpoint`, `socket`, `session`, `axonstore`, …) and
exactly one optional `run` binding (zero or more in some adopter
modes). Everything else is composition by *reference*, not by
nesting.

This page is the reasoning behind that design. For the raw "what
may go where" table, see `axon://grammar/top_level`.

## The four composition operators

AXON has four ways to compose declarations. They are deliberately
small in number so an agent can pick the right one without
searching.

### 1. **Reference by name** — the default

Most composition happens through bare identifier references.

```axon
persona LegalExpert { … }
anchor NoHallucination { … }
flow AnalyzeContract(doc: Document) -> ContractAnalysis { … }

run AnalyzeContract(myContract)
    as LegalExpert                  # reference, not nesting
    constrained_by [NoHallucination] # reference, not nesting
```

The compiler resolves `LegalExpert` and `NoHallucination` against
the module's symbol table at parse time. There is no scoping
nuance: declarations are visible everywhere in the module they
appear.

### 2. **`apply` — flow-to-flow composition**

When one flow's step needs to invoke another flow, it does so via
the `apply:` field on a step. This is the *only* way flows compose.

```axon
flow EnrichWithLegalContext(entities: EntityMap) -> EnrichedEntityMap { … }

flow AnalyzeContract(doc: Document) -> ContractAnalysis {
    step Extract {
        given: doc
        ask: "Extract parties, obligations, dates"
        output: EntityMap
    }
    step Enrich {
        given: Extract.output
        apply: EnrichWithLegalContext  # ← composition, not nesting
        output: EnrichedEntityMap
    }
}
```

There is **no anonymous or inline flow grammar**. A sub-flow must
be a declared top-level `flow`. This keeps the audit trail clean:
every flow has a name, a signature, and a deployment-time identity.

### 3. **Carrier binding — wire-to-cognition**

The session-types layer composes by binding a top-level transport
declaration to a top-level protocol declaration.

```axon
session Chat { client: [...], server: [...] }

socket ChatWS {
    protocol: Chat              # ← reference to the session
    backpressure: credit(8)
}
```

The `socket` does not *contain* the `session`; it binds to it.
Equally:

```axon
axonendpoint AnalyzeContractAPI {
    flow: AnalyzeContract       # ← reference to the flow
    method: POST
    route: "/v1/contracts/analyze"
}
```

### 4. **Nesting — only where the grammar demands it**

A handful of constructs are syntactically nested because they have
no meaningful identity outside their parent:

| Nested construct | Parent | Why nested |
|---|---|---|
| `step` | `flow` | A step is an *operation* — its identity is its position within the flow body. |
| `reason`, `probe`, `weave`, `refine`, `validate` | `flow` (sibling of `step`) | Same reasoning: these are operations, not declarations. |
| `use`, `given`, `ask`, `output`, `apply`, `confidence_floor`, `navigate` | `step` body | Step-internal fields. |
| `listen` | `flow` or `daemon` body | A listener is a *behaviour*, not a top-level subject. |
| `if`, `for`, `let`, `return`, `break`, `continue` | `flow` body | Control flow + bindings. |

For everything else, the answer is **declare it top-level and
reference it by name**.

## The "no anonymous declarations" rule

AXON does not have:

- Anonymous personas (`as { tone: precise, ... }`)
- Inline anchors (`constrained_by [{ require: source_citation }]`)
- Inline flows (`step Run { apply: { step Sub { ... } } }`)
- Inline tools, sessions, sockets, …

Every declaration is named. The trade-off is intentional:

- **Audit trail** — every emitted token can be traced to a named
  declaration, not to an inline-anonymous one whose meaning
  depends on the surrounding context.
- **Re-use** — a single `LegalExpert` persona can be referenced
  from a dozen `run`s; an inline persona is repeated text.
- **Diff-reviewability** — declarations are top-level so a code
  review can see every persona/anchor/flow as a discrete unit.

When an adopter wants "one-off" declarations, the idiom is to
declare them locally inside the module that uses them — they are
still named, still top-level, just not exported.

## Cross-module references

Modules import named declarations from other modules via the
`import` statement:

```axon
import legal_personas { LegalExpert, MedicalEthicist }
import shared_anchors { NoHallucination, NoPHI }
```

The compiler treats `import`ed names as if they were declared in
the local module's symbol table. Composition rules don't change
across module boundaries.

## What the compiler actually checks

At parse time:

1. Every reference (`as <X>`, `constrained_by [<Y>]`, `apply: <Z>`,
   `protocol: <P>`, …) is resolved against the module's symbol
   table.
2. Unknown references emit a structured `unknown_<kind>: <name>`
   diagnostic at the reference site.
3. Cyclic references — `flow A` whose body's `apply:` chain leads
   back to `A` — are accepted *structurally* (since the cycle can
   only happen at runtime, not at parse time) but flagged by the
   `--strict` linter when `axon check --strict` runs.

At type-check time:

4. Every reference's *signature* is checked: a `step` whose
   `apply: <Sub>` invokes a sub-flow must have a `given:`
   compatible with the sub-flow's parameter type and an `output:`
   compatible with its return type.

This is the entire composition model. There is nothing else to
learn — when an agent is unsure how to combine two primitives, the
answer is either "declare it top-level and reference it" or "look
at the four operators above".
