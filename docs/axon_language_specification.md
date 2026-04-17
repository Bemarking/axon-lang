# AXON Language Specification

**Version:** 1.0
**Status:** Complete (47/47 primitives wired and cross-validated)
**Date:** 2026-04-14

---

## 1. Overview

AXON is the first formal cognitive language for AI. It provides 47 cognitive primitives organized into 4 categories that enable AI systems to declare cognitive identity, manage epistemic state, execute reasoning workflows, and navigate knowledge structures.

AXON programs are compiled through a lex-parse-typecheck-IR pipeline and executed on the AXON runtime server, which exposes all primitives as HTTP endpoints and MCP (Model Context Protocol) tools/resources/prompts.

### 1.1 Design Principles

- **Epistemic rigor**: Every operation carries a formal epistemic envelope ψ = ⟨T, V, E⟩ (ΛD — Lambda Data)
- **Theorem 5.1**: Only raw data may carry certainty c=1.0; all derived operations are capped at c≤0.99
- **Blame calculus**: Errors carry Findler-Felleisen blame attribution (CT-2 caller, CT-3 server)
- **CSP constraints**: Tools are modeled as Constraint Satisfaction Problems (§5.3)
- **Effect rows**: Operations declare their side effects: `<io, network?, epistemic:X>`

### 1.2 Epistemic Lattice

```
know (c=1.0)          ← raw data, ground truth
  ↑
believe (c∈[0.85,0.99]) ← high-confidence derived
  ↑
speculate (c∈[0.5,0.85)) ← moderate confidence
  ↑
doubt (c∈(0,0.5))       ← low confidence
  ↑
⊥ (c=0.0)              ← no information / void
```

---

## 2. Primitive Categories

| Category | Count | Purpose |
|----------|-------|---------|
| Declarations | 20 | Define cognitive structures and resources |
| Epistemic | 4 | Classify certainty levels |
| Execution | 14 | Perform reasoning and transformation |
| Navigation | 9 | Traverse and explore knowledge structures |

---

## 3. Declarations (20)

### 3.1 `persona`
Declares a cognitive identity with domain expertise, communication tone, and confidence threshold.
```
persona researcher {
    domain: ["machine_learning", "nlp"]
    tone: "academic"
    confidence: 0.8
    description: "ML research specialist"
}
```
**Runtime:** MCP prompts/list + prompts/get | **ΛD:** c=0.95, δ=derived (prompt enrichment)

### 3.2 `context`
Declares an enrichment context that augments persona behavior.
```
context deep {
    scope: "research"
    depth: "comprehensive"
    max_tokens: 4096
    temperature: 0.7
}
```
**Runtime:** MCP prompts/get (system prompt enrichment) | **ΛD:** c=0.95, δ=derived

### 3.3 `flow`
Declares a cognitive workflow containing steps, anchors, and declarations.
```
flow analyze {
    persona researcher { ... }
    anchor quality_gate { min_confidence: 0.8 }
    step reason { prompt: "Analyze the input" }
    step validate { check: "quality_gate" }
}
```
**Runtime:** /v1/deploy + /v1/execute + /v1/inspect | **ΛD:** c varies by execution

### 3.4 `anchor`
Declares a constraint gate that validates step outputs.
```
anchor quality_gate {
    min_confidence: 0.8
    max_hallucination: 0.1
}
```
**Runtime:** /v1/execute (anchor_checks, anchor_breaches) | **ΛD:** c=1.0 check, c≤0.99 breach

### 3.5 `tool`
Declares an external capability available to execution steps.
```
tool search {
    description: "Web search capability"
    parameters: { query: "string" }
}
```
**Runtime:** /v1/tools/* (registry, dispatch, CSP §5.3) | **ΛD:** CSP constraints

### 3.6 `memory`
Declares a session memory store for key-value persistence during execution.
**Runtime:** /v1/session/remember + /v1/session/recall | **ΛD:** c=1.0 store, c≤0.99 recall

### 3.7 `type`
Declares type constraints in the IR type system.
**Runtime:** IR type system (lex → parse → type check) | **ΛD:** c=1.0, deterministic

### 3.8 `agent`
Declares a multi-flow orchestration pipeline.
**Runtime:** /v1/execute/pipeline (multi-flow orchestration) | **ΛD:** c varies

### 3.9 `shield`
Declares input/output guardrails with deny lists, pattern matching, PII detection, and length limits.
```
shield toxicity {
    mode: "output"
    rules: [
        { id: "block_harmful", kind: "deny_list", value: "harmful", action: "block" }
        { id: "detect_email", kind: "pii", value: "email", action: "redact" }
    ]
}
```
**Runtime:** /v1/shields/* + MCP tools/call | **ΛD:** c=0.85–0.95, δ=derived (pattern matching is approximate)
**Rule kinds:** deny_list, pattern, pii (email/phone/ssn), length
**Actions:** block, warn, redact

### 3.10 `pix`
Declares a visual reasoning session with image registration and annotation.
**Runtime:** /v1/pix/* (image/annotate with bbox) | **ΛD:** raw metadata (c=1.0), derived annotations (c=0.99)
**Annotation categories:** object, text, region, feature
**Bbox:** normalized [x, y, width, height] in [0.0, 1.0]

### 3.11 `psyche`
Declares a metacognitive self-reflection session.
**Runtime:** /v1/psyche/* (insight/complete with self-awareness scoring) | **ΛD:** c=awareness×0.99, δ=derived
**Insight categories:** knowledge_gap, uncertainty, bias, strength, recommendation
**Severity levels:** info, warning, critical
**Self-awareness score:** diversity×0.7 + avg_confidence×0.3 − critical_penalty

### 3.12 `corpus`
Declares a document corpus with search and citation capabilities.
**Runtime:** /v1/corpus/* + MCP tools/call | **ΛD:** raw ingest (c=1.0), derived search/cite (c=0.99)
**Search:** TF-based keyword relevance with title 3x boost
**Citation:** passage extraction with safe UTF-8 boundaries

### 3.13 `dataspace`
Declares a cognitive data navigation container.
**Runtime:** /v1/dataspace/* + MCP tools/call + MCP resources | **ΛD:** raw ingest, derived operations

### 3.14 `ots`
Declares a one-time-secret for ephemeral credential exchange.
**Runtime:** /v1/ots/* | **ΛD:** c=1.0 raw (available), c=0.0 void (consumed/expired)
**Security:** value cleared from memory after single retrieval, TTL-based expiry

### 3.15 `mandate`
Declares an authorization policy with priority-ordered rules.
**Runtime:** /v1/mandates/* + MCP tools/call | **ΛD:** c=1.0 explicit match, c=0.99 default deny
**Evaluation:** first-match-wins with priority ordering
**Matching:** subject (exact/*), action (exact/*), resource (exact/prefix/*)

### 3.16 `compute`
Declares a numeric/symbolic computation.
**Runtime:** /v1/compute/* + MCP tools/call | **ΛD:** c=1.0 exact integer, c=0.99 approximate
**Operators:** +, -, *, /, %, ^ (power)
**Functions:** sqrt, abs, sin, cos, log, exp, ceil, floor, round
**Constants:** pi, e, tau
**Variables:** named substitution via HashMap

### 3.17 `daemon`
Declares a long-running supervised process.
**Runtime:** /v1/daemons/* (lifecycle, supervisor) | **ΛD:** c varies

### 3.18 `axonstore`
Declares a durable cognitive persistence store with ΛD envelopes per entry.
**Runtime:** /v1/axonstore/* + MCP tools/call | **ΛD:** c=1.0 persist (raw), c=0.99 mutate (derived, Theorem 5.1)
**Operations:** persist, retrieve, mutate, purge, transact (atomic batch)

### 3.19 `axonendpoint`
Declares an external API endpoint binding.
**Runtime:** /v1/endpoints/* | **ΛD:** c=0.99, δ=derived (external trust boundary)
**URL templates:** `{param}` placeholder substitution
**Auth types:** none, bearer, api_key, basic
**Effect row:** `<io, network, epistemic:speculate>`

### 3.20 `lambda`
Declares functional expressions in the IR.
**Runtime:** IR lambda expressions in compiler | **ΛD:** c=1.0, deterministic

---

## 4. Epistemic Primitives (4)

### 4.1 `know`
Lattice position: ⊤ (top). Certainty c=1.0. Only applicable to raw, unprocessed data.

### 4.2 `believe`
Lattice position: high confidence. Certainty c∈[0.85, 0.99]. Applicable to high-quality derived results.

### 4.3 `speculate`
Lattice position: moderate confidence. Certainty c∈[0.5, 0.85). Applicable to exploratory or pattern-matched results.

### 4.4 `doubt`
Lattice position: low confidence. Certainty c∈(0, 0.5). Applicable to contradicted claims or weak evidence.

---

## 5. Execution Primitives (14)

### 5.1 `step`
A single execution unit within a flow.
**Runtime:** /v1/execute (step_results, steps_executed) | **ΛD:** c varies

### 5.2 `reason`
An LLM reasoning step that sends prompts to backends.
**Runtime:** runner.rs execute_real | **ΛD:** c≤0.99, δ=derived

### 5.3 `validate`
Checks step output against anchor constraints.
**Runtime:** /v1/flows/{name}/validate | **ΛD:** c=1.0, deterministic

### 5.4 `refine`
Iterative output improvement with convergence tracking.
**Runtime:** /v1/refine/* | **ΛD:** c = 0.5 + quality×0.49, capped at 0.99
**Convergence:** quality ≥ target OR |delta| < threshold

### 5.5 `weave`
Multi-source content synthesis with weighted strands and attribution.
**Runtime:** /v1/weaves/* | **ΛD:** weighted average of strand certainties, capped at 0.99
**Output:** `[source] content` attribution markers

### 5.6 `probe`
Exploratory information gathering across multiple sources.
**Runtime:** /v1/probes/* | **ΛD:** c = relevance×0.99, capped at 0.99
**Aggregation:** top_findings (sorted by relevance), findings_per_source, aggregate_certainty

### 5.7 `use`
Tool dispatch within a flow step.
**Runtime:** tool dispatch in runner | **ΛD:** c varies

### 5.8 `remember`
Persist a key-value pair to session memory.
**Runtime:** /v1/session/remember | **ΛD:** c=1.0, raw

### 5.9 `recall`
Retrieve a value from session memory.
**Runtime:** /v1/session/recall | **ΛD:** c≤0.99, derived

### 5.10 `par`
Execute multiple steps in parallel.
**Runtime:** runner.rs parallel step execution | **ΛD:** c varies

### 5.11 `hibernate`
Suspend and resume long-running operations with state checkpoints.
**Runtime:** /v1/hibernate/* | **ΛD:** checkpoint c=1.0 (raw), resume c=0.99 (derived)
**Lifecycle:** active → suspended → resumed → completed

### 5.12 `deliberate`
Structured decision-making with option evaluation and backtracking.
**Runtime:** /v1/deliberate/* | **ΛD:** certainty = margin×0.99 (margin = best−second_best)
**Operations:** add_option, evaluate (pros/cons), eliminate (backtrack), decide

### 5.13 `consensus`
Multi-agent agreement through confidence-weighted voting.
**Runtime:** /v1/consensus/* | **ΛD:** certainty = agreement×0.99 (agreement = winner_score/total_score)
**Quorum:** minimum vote count before resolution

### 5.14 `forge`
Template-based artifact generation with variable substitution.
**Runtime:** /v1/forges/* + MCP tools/call | **ΛD:** c=0.99, δ=derived
**Templates:** `{{variable}}` placeholder extraction and substitution

---

## 6. Navigation Primitives (9)

### 6.1 `stream`
SSE streaming execution with real-time token events.
**Runtime:** /v1/execute/stream | **ΛD:** c varies

### 6.2 `navigate`
Combined focus + explore pattern for dataspace traversal.
**Runtime:** dataspace focus + explore | **ΛD:** c≤0.99, derived

### 6.3 `drill`
Depth-limited recursive exploration with tree-structured questions.
**Runtime:** /v1/drills/* | **ΛD:** c = (1.0 − depth×0.05), clamped to [0.5, 0.99]
**Node IDs:** path-based (root.0.1)

### 6.4 `trail`
Execution path recording with step-by-step trace capture.
**Runtime:** /v1/trails/* | **ΛD:** completed c=1.0 (raw observation), in-progress c=0.95
**Immutability:** steps cannot be added after completion

### 6.5 `corroborate`
Cross-source claim verification with agreement scoring.
**Runtime:** /v1/corroborate/* | **ΛD:** certainty = |agreement|×0.99
**Agreement:** (Σsupporting − Σcontradicting) / Σtotal → [-1, 1]
**Verdicts:** corroborated (>0.5), disputed (<-0.5), inconclusive

### 6.6 `focus`
Filter dataspace entries by ontology and/or tags.
**Runtime:** /v1/dataspace/{name}/focus + MCP tools/call | **ΛD:** c=0.99, derived

### 6.7 `associate`
Create typed relationships between dataspace entries.
**Runtime:** /v1/dataspace/{name}/associate | **ΛD:** c=0.99, derived

### 6.8 `aggregate`
Compute aggregates (count/sum/avg/min/max) over dataspace entries.
**Runtime:** /v1/dataspace/{name}/aggregate + MCP tools/call | **ΛD:** c=0.99, derived

### 6.9 `explore`
Introspect dataspace structure: ontology distribution, tag frequency, certainty statistics.
**Runtime:** /v1/dataspace/{name}/explore | **ΛD:** c=0.99, derived

---

## 7. Formal Alignment

### 7.1 ΛD (Lambda Data) — Epistemic State Vectors

Every AXON operation produces output carrying ψ = ⟨T, V, E⟩:
- **T** (type): ontological classification
- **V** (value): the payload data
- **E** (envelope): ⟨c, τ, ρ, δ⟩
  - **c** (certainty): [0.0, 1.0]
  - **τ** (temporal): start/end temporal frames
  - **ρ** (provenance): source attribution chain
  - **δ** (derivation): "raw" or "derived"

### 7.2 Theorem 5.1 — Epistemic Degradation

> Only raw data may carry c=1.0. All derived operations clamp certainty to c≤0.99.

Enforced by `EpistemicEnvelope::validate()` across all 47 primitives.

### 7.3 CSP §5.3 — Tool Constraints

MCP tools carry `_axon_csp` schemas:
```json
{
    "constraints": ["ontology ∈ domain", "Theorem 5.1: derived"],
    "effect_row": "<io, epistemic:speculate>",
    "output_taint": "Uncertainty"
}
```

### 7.4 Blame Calculus (Findler-Felleisen)

- **CT-2 (caller):** invalid parameters, non-existent resources, missing variables
- **CT-3 (server):** internal execution errors, backend failures
- **Network:** external API failures (axonendpoint)

### 7.5 Effect Rows

Operations declare side effects:
- `<io>` — I/O operations
- `<network>` — external network calls (axonendpoint)
- `<compute>` — pure computation
- `<epistemic:know|believe|speculate|doubt>` — epistemic effect

---

## 8. Runtime Surface

| Surface | Count |
|---------|-------|
| HTTP API routes | 282 |
| MCP tool types | 8 |
| MCP resource types | 10 |
| MCP workflow prompts | 5 |
| Public structs | 179 |
| Integration tests | 726 |

---

*AXON Language Specification v1.0 — 2026-04-14*
*47 cognitive primitives. 100% wired. 100% cross-validated.*
*The first formal cognitive language for AI.*
