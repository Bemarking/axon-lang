---
name: flow_design
title: Design an AXON flow
summary: Guided walkthrough — turn a natural-language flow intent into a typed, anchored, optionally-streaming AXON program. Drives the agent through compose → primitive_doc → check.
arguments:
  - name: intent
    description: One-sentence description of what the flow should do (e.g. "summarise a patient record and propose ICD-10 codes").
    required: true
  - name: domain
    description: Optional explicit domain (healthcare | banking | government | legal | chat | retrieval | multi_agent | generic). When absent the classifier picks.
    required: false
  - name: streaming
    description: "Set to `yes` if the flow should emit Stream<T> output; `no` (default) for batch."
    required: false
  - name: compliance
    description: Comma-separated extra compliance tags the adopter needs (HIPAA, GDPR, PCI_DSS, SOX, SOC2, …). The domain's defaults are layered on top.
    required: false
---

You are about to design an AXON **flow** for the following intent:

> {{intent}}

Domain hint: **{{domain}}**. Streaming output requested: **{{streaming}}**.
Additional compliance tags: **{{compliance}}**.

Follow this loop. Do not skip steps; the discipline is the value.

### 1. Ground yourself in the available primitives

Call `axon.primitives()` once (no arguments) to see every primitive
the language ships. Then call `axon.primitive_doc("flow")`,
`axon.primitive_doc("step")`, `axon.primitive_doc("persona")`, and
`axon.primitive_doc("anchor")` to read each primitive's grammar +
semantic constraints **before writing any code**.

### 2. Get a typed starter scaffold

Call `axon.compose({ intent: "{{intent}}", domain: "{{domain}}" })`.
The tool will:

- Classify the intent (or honour your explicit `domain`).
- Return a `.axon` scaffold that compiles end-to-end through the
  live `axon-frontend` pipeline.
- Surface a `next_steps` checklist the human will need.

**Quote the `axon_check_verdict`** in your reply so the user knows
the scaffold is verified — and remember that the scaffold is a
starting point, not a finished program. Treat the `next_steps`
checklist as your refinement queue.

### 3. Adapt the scaffold to the intent

Rename identifiers (`MyFlow`, `Input`, `Output`, etc.) to match the
adopter's vocabulary. Refine the `step` bodies' `ask:` prompts so
they are imperative + outcome-oriented. Keep the typed structure
intact — never strip the `FlowEnvelope<T>` wrapper from JSON-wire
endpoints, and keep the `Request Binding Contract` honoured (body-
type field names must match flow parameter names).

If `streaming` is `yes`, confirm the flow's final step's output is
`Stream<T>` AND a declared `tool` reaches it through `apply:` with a
`stream:<policy>` effect (see `axon://primitives/tool`).

### 4. Add the right anchors

Read `axon.primitive_doc("anchor")`. The flow should declare at
least one anchor with a `require:` value from the closed catalogue
(`source_citation`, `evidence_backed`, `cross_referenced`,
`deterministic`, `legal_basis_present`, `confidence_floor`). Pick
the rule that matches the intent's truth discipline.

For the additional compliance tags in **{{compliance}}**, consult
`axon://compliance/<framework>` for each — the resource tells you
which annotations to put where + which still need manual attestation.

### 5. Validate every iteration through `axon.check`

After each substantive edit, call
`axon.check({ source: "<your current draft>" })`. The verdict is
binary: `ok: true` means the program parses + type-checks. Anything
else is a structured diagnostic with line + column the agent should
address before continuing.

Never declare the program finished until `axon.check` returns
`ok: true`.

### 6. Surface the deliverable

When the loop is complete:

- Quote the final program as a fenced ```axon block.
- Quote the `axon.check` verdict (`well-formed`, zero errors,
  warnings if any).
- List which `axon://compliance/<framework>` resources the user
  should read to attest the manual obligations.
- Recommend the smallest next phase: typically wrapping the flow
  in an `axonendpoint` or `socket` for the wire layer.
