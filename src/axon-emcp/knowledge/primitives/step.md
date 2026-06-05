---
name: step
summary: A single cognitive operation inside a flow — typed input (given), prompt (ask), and typed output.
category: cognition
top_level: false
since: v0.1.0 (initial language)
grammar: |
  step <Name> [use <Persona>] {
      given: <Expression>             # required — typed input expression
      ask: "<prompt>"                 # required for cognitive steps — natural-language instruction
      output: <Type>                  # required for cognitive steps — output type
      confidence_floor: <0.0..1.0>    # optional — minimum confidence to accept
      navigate: <Graph.Path>          # optional — route through a knowledge graph
      apply: <FlowName>               # optional — invoke a declared flow

      # Reasoning sub-constructs (each its own primitive):
      use <Persona>                   # per-step persona override
      probe <ProbeName>               # diagnostic probe
      reason <Strategy>               # explicit reasoning step (CoT / debate / ...)
      weave <Spec>                    # multi-thread reasoning braid
      stream <Spec>                   # streaming output spec
  }
---

# `step`

A `step` is the **atom of cognition** in AXON. It declares one
typed operation: an input (`given`), an instruction (`ask`), and a
typed output. The compiler enforces that every flow body is a
sequence of `step`s (and control-flow constructs), and that every
data dependency between steps is resolved lexically.

Every other cognitive surface in AXON — `reason`, `weave`,
`probe`, `stream` — appears as a **sub-construct inside a step's
body**, never as a flow-level node of its own.

## Surface

`step` is **nested** — it lives only inside a `flow` body. It is
*not* a top-level declaration.

```axon
flow GreetUser(name: String) -> Greeting {
    step ComposeGreeting use FriendlyAssistant {
        given: name
        ask: "Write a warm, locale-aware greeting"
        output: Greeting
        confidence_floor: 0.7
    }
}
```

## Header

### `step <Name>`

- **`<Name>`** — a `PascalCase` identifier, unique within the
  enclosing flow. The step's outputs are referenced from
  subsequent steps as `<Name>.output`.

### `step <Name> use <Persona>` (optional)

A **per-step persona override**. When present, this step runs
under the named persona instead of the flow-level binding
(`run … as <Persona>`). The override is *lexical*: it does not
propagate to sub-flows invoked via `apply` inside this step.

## Body

### `given:` (required for cognitive steps)

The **typed input expression**. Accepts:

- A flow parameter name (`name`, `doc`).
- A previous step's output (`Extract.output`).
- A bound `let` variable.
- A field projection (`User.email`).
- A literal (numeric / string / list).

The type checker resolves the expression against the lexical
scope and records the inferred type — this becomes the input type
the runtime passes to the backend.

### `ask:` (required for cognitive steps)

A **string literal** containing the natural-language instruction
the model receives. This is the only *unstructured* field on a
step; it is the bridge between the typed surface and the
generative model.

```axon
ask: "Extract all parties, obligations, dates, and penalties"
```

Prompt-engineering best practice (`axon://logic/prompt_design`):
keep `ask:` imperative and outcome-oriented; leave structural
specifications to the `output:` type and to bound anchors.

### `output:` (required for cognitive steps)

The **declared output type**. Accepts the full type-expression
shape (Fase 32.l):

| Form | Example |
|---|---|
| Bare type | `EntityMap` |
| Generic | `List<Risk>`, `Optional<Citation>` |
| Stream (Fase 33) | `Stream<Token>` |
| Nested generic | `FlowEnvelope<List<TenantRecord>>` |
| Optional | `Greeting?`, `Stream<Token>?` |

Streaming output (`Stream<T>`) participates in the algebraic
stream-effect runtime — the step's emissions are materialised as
SSE / WebSocket frames on the declared transport.

### `confidence_floor:` (optional)

A **numeric literal in `[0.0, 1.0]`**. Overrides the persona's
`confidence_threshold` for this step alone. Useful when one step
in a flow is markedly higher-stakes than the others (e.g. a
medical-diagnosis step inside an otherwise informational flow).

### `navigate:` (optional)

A **dotted identifier** referencing a path in a declared
knowledge graph or store. When present, the step's `given:`
expression is routed through the graph before reaching the
model.

```axon
step LookupPatient {
    given: patient_id
    navigate: ClinicalGraph.PatientRecord
    ask: "Summarise the patient's relevant history"
    output: PatientSummary
}
```

### `apply:` (optional)

A **declared-flow name** (flow composition) **or a declared
tool** (run the tool as this step's backend). When present, the
step *invokes* the named flow/tool with the `given:` expression
as its argument, rather than calling the cognitive backend.

```axon
step EnrichWithLegalContext {
    given: extracted_entities
    apply: AnalyzeLegalContext      # compose a sub-flow
    output: EnrichedEntityMap
}
```

For **flow composition**, the applied flow's parameters and return
type are expected to align with `given:` and `output:` (the
intended contract).

> **Enforcement note (§Fase 58).** The type-checked, structured
> way to invoke a **tool** with named, schema-validated arguments
> is the **flow-level** `use <Tool>(k = v, …)` form — the
> type-checker validates the call against the tool's declared
> `parameters:` schema at compile time (CT-2 caller blame, before
> any dispatch). See `axon://primitives/tool`. The step-level
> `apply: <Tool> given: <struct>` splat (auto-mapping a struct's
> fields onto the tool schema) is a planned refinement and is not
> yet compile-validated; until then prefer `use <Tool>(k = v, …)`
> at flow level for typed tool calls.

## Sub-constructs (one per step)

Inside a step body, these reasoning surfaces appear as named
sub-constructs:

| Sub-construct | Purpose | Doc |
|---|---|---|
| `use <Persona>` | Per-step persona override (header form) | `axon://primitives/persona` |
| `probe <Probe>` | Diagnostic / probing prompt | `axon://primitives/probe` |
| `reason <Strategy>` | Explicit reasoning strategy (CoT, debate, …) | `axon://primitives/reason` |
| `weave <Spec>` | Multi-thread reasoning braid | `axon://primitives/weave` |
| `stream <Spec>` | Streaming output spec | `axon://primitives/stream` |

Each sub-construct has its own primitive entry; the step's body
parser dispatches structurally to them.

## What this primitive is NOT

- **Not a top-level declaration.** A `step` only makes sense
  inside a `flow`. The parser rejects top-level `step` nodes.
- **Not a function call.** A step does not "return" in the
  imperative sense; it *produces a typed output value* the
  subsequent steps consume via `<Name>.output`.
- **Not implicitly ordered by data.** The flow body's *textual*
  order is the canonical evaluation order; the runtime may
  reorder data-independent steps, but the audit trail always
  reflects the lexical sequence.
- **Not free-form.** `step` has a closed grammar (the field set
  listed above); unknown fields cause a parse error.

## See also

- `axon://primitives/flow` — the enclosing primitive that
  sequences `step`s.
- `axon://primitives/persona` — what `use <Persona>` binds.
- `axon://primitives/reason` — the explicit-reasoning
  sub-construct.
- `axon://primitives/anchor` — typed grounding constraints that
  shield bind to a step.
- `axon://logic/flow_composition` — when to use `apply:` to
  invoke a sub-flow vs. inlining a step.
