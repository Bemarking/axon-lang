<p align="center">
  <strong>AXON</strong> <em>v0.15.0</em><br>
  A programming language whose primitives are cognitive primitives of AI.
</p>

<p align="center">
  <code>persona</code> · <code>intent</code> · <code>flow</code> · <code>reason</code> · <code>anchor</code> · <code>refine</code> · <code>memory</code> · <code>tool</code> · <code>probe</code> · <code>weave</code> · <code>validate</code> · <code>context</code><br>
  <code>know</code> · <code>believe</code> · <code>speculate</code> · <code>doubt</code> · <code>par</code> · <code>hibernate</code><br>
  <code>dataspace</code> · <code>ingest</code> · <code>focus</code> · <code>associate</code> · <code>aggregate</code> · <code>explore</code><br>
  <code>deliberate</code> · <code>consensus</code> · <code>forge</code> · <code>agent</code> · <code>shield</code><br>
  <code>stream</code> · <code>effects</code> · <code>@contract_tool</code> · <code>@csp_tool</code><br>
  <code>pix</code> · <code>navigate</code> · <code>drill</code> · <code>trail</code>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.15.0-informational" alt="Version">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: Alpha">
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-1513%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/paradigms-10%20shifts-blueviolet" alt="Paradigm Shifts">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
  <img src="https://img.shields.io/badge/pypi-axon--lang-blue" alt="PyPI">
</p>

---

## What is AXON?

AXON is a **compiled language** that targets LLMs instead of CPUs. It has a
formal EBNF grammar, a lexer, parser, AST, intermediate representation, multiple
compiler backends (Anthropic, OpenAI, Gemini, Ollama), and a runtime with
semantic type checking, retry engines, and execution tracing.

It is **not** a Python library, a LangChain wrapper, or a YAML DSL.

```axon
persona LegalExpert {
    domain: ["contract law", "IP", "corporate"]
    tone: precise
    confidence_threshold: 0.85
    refuse_if: [speculation, unverifiable_claim]
}

anchor NoHallucination {
    require: source_citation
    confidence_floor: 0.75
    unknown_response: "Insufficient information"
}

flow AnalyzeContract(doc: Document) -> StructuredReport {
    step Extract {
        probe doc for [parties, obligations, dates, penalties]
        output: EntityMap
    }
    step Assess {
        reason {
            chain_of_thought: enabled
            given: Extract.output
            ask: "Are there ambiguous or risky clauses?"
            depth: 3
        }
        output: RiskAnalysis
    }
    step Check {
        validate Assess.output against: ContractSchema
        if confidence < 0.8 -> refine(max_attempts: 2)
        output: ValidatedAnalysis
    }
    step Report {
        weave [Extract.output, Check.output]
        format: StructuredReport
        include: [summary, risks, recommendations]
    }
}
```

---

## Paradigm Shifts

> AXON v0.7 introduces three compiler-level paradigm shifts that elevate the
> language from prompt compilation to a Cognitive Operating System.

### I. Formal Model — Epistemic Constraint Calculus

Each program `P` in AXON operates over a typed epistemic lattice `(T, ≤)` where
the compiler enforces semantic constraints at compile time. The paradigm shifts
extend this with three new formal mechanisms:

**Epistemic Scoping Function.** Given an epistemic mode
`m ∈ {know, believe,
speculate, doubt}`, the compiler applies a constraint
function `C(m)` that maps to a tuple of LLM parameters and auto-injected
anchors:

```text
C : Mode → (τ, p, A)
where
  τ ∈ [0,1]    — temperature override
  p ∈ [0,1]    — nucleus sampling (top_p)
  A ⊆ Anchors  — auto-injected constraint set

C(know)      = (0.1, 0.3, {RequiresCitation, NoHallucination})
C(believe)   = (0.3, 0.5, {NoHallucination})
C(speculate) = (0.9, 0.95, ∅)
C(doubt)     = (0.2, 0.4, {RequiresCitation, SyllogismChecker})
```

This is calculated **at compile time** — the IR carries the resolved constraint
set, so the executor applies them as zero-cost runtime overrides.

**Parallel DAG Scheduling.** A `par` block `B = {b₁, ..., bₙ}` where `n ≥ 2` is
verified at compile time to have no data dependencies between branches:

```text
∀ bᵢ, bⱼ ∈ B, i ≠ j : deps(bᵢ) ∩ outputs(bⱼ) = ∅
```

At runtime, branches execute via `asyncio.gather`, achieving `O(max(tᵢ))`
latency instead of `O(Σtᵢ)` for sequential chains.

**CPS Continuation Points.** A `hibernate` node generates a deterministic
continuation ID via `SHA-256(flow_name ∥ event_name ∥ source_position)`. The
executor serializes the full `ExecutionState` (call stack, step results, context
variables) and halts. On `resume(continuation_id)`, the state is deserialized
and execution continues from the exact IR node — implementing
Continuation-Passing Style at the language level.

### II. Design Philosophy — Programming Epistemic States

Traditional LLM frameworks treat every model call identically — the same
temperature, the same constraints, the same trust level. This is the equivalent
of asking a human to treat brainstorming and sworn testimony with the same
cognitive rigor.

AXON rejects this flat model. **Epistemic Directives** make the confidence state
of the AI a first-class construct in the language:

```axon
know {
    flow ExtractFacts(doc: Document) -> CitedFact {
        step Verify { ask: "Extract only verifiable facts" output: CitedFact }
    }
}

speculate {
    flow Brainstorm(topic: String) -> Opinion {
        step Imagine { ask: "What could be possible?" output: Opinion }
    }
}
```

The compiler **does not merely label** these blocks — it structurally transforms
them. A `know` block injects citation anchors and drops temperature to 0.1,
making hallucination a compile-time constraint violation. A `speculate` block
removes all constraints and raises temperature to 0.9, liberating the model.

**Parallel Cognitive Dispatch** mirrors how human organizations work: delegate
independent analyses to specialists concurrently, then synthesize.

**Dynamic State Yielding** transforms agents from expensive `while True` loops
into event-driven processes that can sleep for days, weeks, or months — then
resume with full context. The language handles the serialization; the developer
writes `hibernate until "event_name"` and moves on.

### III. Real-World Use Cases

#### Use Case 1: Legal Document Analysis Pipeline

A law firm needs to analyze contracts with maximum factual rigor, while also
exploring creative legal strategies. AXON separates these cognitive modes at the
language level:

```axon
know {
    flow ExtractClauses(contract: Document) -> ClauseMap {
        step Parse { probe contract for [parties, obligations, penalties] output: ClauseMap }
    }
}

flow AnalyzeRisk(contract: Document) -> StructuredReport {
    par {
        step Financial { ask: "Analyze financial exposure" output: RiskScore }
        step Regulatory { ask: "Check regulatory compliance" output: ComplianceReport }
        step Precedent { ask: "Find relevant case law" output: CaseList }
    }
    weave [Financial, Regulatory, Precedent] into Report { format: StructuredReport }
}

speculate {
    flow ExploreStrategies(report: StructuredReport) -> Opinion {
        step Creative { ask: "What unconventional strategies could mitigate these risks?" output: Opinion }
    }
}
```

- `know` guarantees citation-backed extraction (temperature 0.1)
- `par` runs 3 analyses concurrently, reducing latency by ~3x
- `speculate` explicitly relaxes constraints for creative strategy exploration

#### Use Case 2: Multi-Agent Research & Intelligence System

A BI platform deploys autonomous research agents that run for weeks, hibernating
between data collection phases:

```axon
flow MarketIntelligence(sector: String) -> Report {
    know {
        flow GatherData(sector: String) -> DataSet {
            step Collect { ask: "Gather verified market data" output: DataSet }
        }
    }

    par {
        step Trends { ask: "Identify emerging trends" output: TrendAnalysis }
        step Competitors { ask: "Map competitor landscape" output: CompetitorMap }
    }

    hibernate until "quarterly_data_available"

    doubt {
        flow ValidateFindings(data: DataSet) -> ValidatedReport {
            step CrossCheck { ask: "Challenge every assumption with evidence" output: ValidatedReport }
        }
    }

    weave [Trends, Competitors] into Final { format: Report }
}
```

- Agent hibernates after initial analysis, **costing $0 while waiting**
- Resumes automatically when quarterly data arrives (webhook/cron)
- `doubt` mode forces adversarial validation with syllogism checking

#### Use Case 3: Autonomous Customer Support with Escalation

A SaaS platform handles support tickets with different confidence requirements
and automatic escalation via hibernate:

```axon
persona SupportAgent {
    domain: ["product knowledge", "troubleshooting"]
    tone: empathetic
    confidence_threshold: 0.8
}

flow HandleTicket(ticket: String) -> Resolution {
    know {
        flow DiagnoseIssue(ticket: String) -> Diagnosis {
            step Classify { ask: "Classify the issue type and severity" output: Diagnosis }
        }
    }

    believe {
        flow SuggestSolution(diagnosis: Diagnosis) -> Solution {
            step Solve { ask: "Propose a solution based on known patterns" output: Solution }
        }
    }

    if confidence < 0.7 -> hibernate until "human_review_complete"

    step Respond { ask: "Draft customer response" output: Resolution }
}
```

- `know` classifies with strict accuracy (no guessing on severity)
- `believe` suggests solutions with moderate confidence
- Low confidence triggers `hibernate` — agent sleeps until a human reviews
- Zero compute cost during human review; resumes with full context

### IV. Directed Creative Synthesis — the `forge` Primitive

> AXON v0.10 introduces a sixth paradigm shift: **mathematical formalization of
> the creative process** inside LLMs.

The industry suffers from a structural limitation: LLMs can interpolate, but
they struggle to _create_. `forge` addresses this by implementing a
compiler-level **Poincaré pipeline** — the same 4-phase process mathematicians
and scientists use when producing genuinely novel work.

**Poincaré-Hadamard Creative Pipeline.** A `forge` block orchestrates four
sequential phases, each mapped to a distinct LLM configuration:

```text
forge(seed, mode, novelty, depth, branches) → result

Phase 1: PREPARATION   — Expand the seed via context probing
Phase 2: INCUBATION    — Speculative exploration (depth iterations)
Phase 3: ILLUMINATION  — Best-of-N consensus crystallization
Phase 4: VERIFICATION  — Adversarial doubt + anchor validation
```

**Boden Creativity Taxonomy.** The `mode` parameter maps Margaret Boden's three
creativity types to concrete LLM parameter overrides at compile time:

```text
B : Mode → (τ, freedom, rule_flexibility)

B(combinatory)      = (0.9,  0.8, 0.3)   — novel recombination of known ideas
B(exploratory)      = (0.7,  0.6, 0.5)   — structured navigation of possibility spaces
B(transformational) = (1.2,  1.0, 0.9)   — rule-breaking synthesis, new paradigms
```

**Novelty Operator K(x|K).** The `novelty` parameter (0.0–1.0) controls the
Kolmogorov-inspired tradeoff between utility and surprise. It blends into the
effective temperature used during incubation:

```text
τ_eff = τ_base × (0.5 + 0.5 × novelty)

novelty = 0.0 → τ_eff = 0.5 × τ_base  (conservative, high utility)
novelty = 1.0 → τ_eff = 1.0 × τ_base  (maximum divergence, high surprise)
```

**Usage example — Directed Creative Synthesis:**

```axon
anchor GoldenRatio {
    require: aesthetic_harmony
    confidence_floor: 0.70
}

flow CreateVisualConcept(brief: String) -> Visual {
    forge Artwork(seed: "aurora borealis over ancient ruins") -> Visual {
        mode:        transformational
        novelty:     0.85
        constraints: GoldenRatio
        depth:       4
        branches:    7
    }
}

run CreateVisualConcept("Create a visual concept for a film poster")
```

What the compiler does:

1. **Preparation** — expands "aurora borealis over ancient ruins" into a rich
   conceptual foundation via context probing
2. **Incubation** — runs 4 iterations of speculative exploration at
   `τ_eff = 1.2 × 0.925 = 1.11`, pushing beyond obvious associations
3. **Illumination** — launches 7 parallel branches, each crystallizing the
   incubated ideas, then selects the most coherent output (Best-of-N)
4. **Verification** — applies adversarial doubt against the `GoldenRatio`
   anchor, validating that the result is genuinely novel (`K(x|K) > 0`) and
   aesthetically balanced

This is **not** a prompt template. The `forge` primitive compiles to structured
IR metadata that the runtime executes as an orchestrated pipeline — the same
precision AXON applies to every other cognitive primitive.

### V. Autonomous Goal-Seeking — the `agent` Primitive

> AXON v0.12 introduces a seventh paradigm shift: **compiler-verified autonomous
> agents** grounded in the Belief-Desire-Intention (BDI) architecture, epistemic
> logic, and coinductive semantics.

Every existing LLM framework implements agents as Python classes with ad-hoc
while-loops, hidden state machines, and zero formal guarantees. LangChain's
`AgentExecutor` is a runtime artifact — it cannot be statically analyzed, type-
checked, or budget-bounded at compile time. AXON's `agent` primitive makes
autonomous goal-seeking a **first-class compiled construct** with mathematical
semantics.


**BDI Coinductive Semantics.** An `agent` declaration compiles to a coinductive
BDI system — a state machine whose behavior is defined by an infinite
observation/transition pair over the epistemic lattice:

```text
Agent ≅ ν X. (S × (Action → X))

where
  S        = Beliefs × Goals × Plans    — cognitive state
  Action   = Observe | Deliberate | Act | Reflect
  ν        = greatest fixpoint (coinduction — runs indefinitely)
```

The `ν` (nu) operator is the key: unlike inductive data (finite trees), a
coinductive agent is a potentially infinite stream of state transitions,
terminating only when the goal is achieved or a budget is exhausted. This
formalization is not decorative — it determines the compiler's verification
strategy and the executor's loop semantics.

**Epistemic Lattice Convergence.** At each BDI cycle, the agent's epistemic
state is projected onto the same lattice `(T, ≤)` used by epistemic directives.
The deliberation phase produces a state `σ ∈ {know, believe, speculate, doubt}`
and a boolean `goal_achieved`. The convergence criterion is:

```text
Converge(σ, g) = g = true ∧ σ ≥ believe

Diverge(σ, i, n) = σ = doubt ∧ Δσ = 0 ∧ i ≥ n
  where
    Δσ       = σᵢ - σᵢ₋₁   — epistemic progress between cycles
    i        = current iteration
    n        = stuck_window  — consecutive stagnation threshold
```

When `Converge` fires, the agent terminates successfully. When `Diverge` fires,
the `on_stuck` recovery policy activates — `escalate` raises `AgentStuckError`,
`forge` triggers creative re-seeding via the Poincaré pipeline, `retry` resets
and re-attempts.

**Budget Composition.** Budget constraints compose from the IR into the runtime
as a 4-tuple verified at compile time:

```text
B(agent) = (max_iter, max_tokens, max_time, max_cost)

Terminate when: ∃ b ∈ B(agent) : consumed(b) ≥ limit(b)
```

The compiler rejects agents with unbounded budgets (`max_iterations = 0` without
an explicit `on_stuck` policy), preventing runaway execution by construction.

**Strategy Dispatch.** The `strategy` parameter selects the BDI loop variant at
compile time. Each strategy maps to a specific deliberation/action sequence:

```text
Λ : Strategy → CycleShape

Λ(react)            = Deliberate → Act → Observe
Λ(reflexion)        = Deliberate → Act → Observe → Reflect
Λ(plan_and_execute) = Plan → (Act → Observe)* → Verify
Λ(custom)           = user-defined step sequence
```

**Usage example — Autonomous Research Agent:**

```axon
persona ResearchAnalyst {
    domain: ["market research", "competitive analysis"]
    tone: analytical
    confidence_threshold: 0.85
}

tool WebSearch {
    provider: serper
    timeout: 10s
}

tool DataAnalyzer {
    provider: internal
    timeout: 30s
}

agent MarketResearcher {
    goal: "Produce a comprehensive competitive analysis report
           with verified data from at least 5 sources"
    tools: [WebSearch, DataAnalyzer]
    strategy: react
    max_iterations: 15
    max_tokens: 50000
    max_cost: 2.50
    on_stuck: forge
    return: CompetitiveReport
}

flow CompetitiveIntelligence(sector: String) -> CompetitiveReport {
    step Research {
        MarketResearcher(sector)
        output: CompetitiveReport
    }
}

run CompetitiveIntelligence("electric vehicles")
    with ResearchAnalyst
```

What the compiler does:

1. **IR Generation** — the `agent` block compiles to an `IRAgent` node containing
   goal, tools, budget (15 iter / 50k tokens / $2.50), strategy (`react`), and
   recovery policy (`forge`). The `IRAgent` is embedded as a step inside
   `IRFlow`, preserving compositional semantics.
2. **Backend Compilation** — the backend (Anthropic, Gemini) generates a
   `CompiledStep` with `step_name: "agent:MarketResearcher"` and full agent
   metadata in its `metadata["agent"]` dictionary. The system prompt includes
   persona traits, tool availability, and epistemic constraints.
3. **Runtime Execution** — the executor detects `agent:` prefix and dispatches
   to the BDI loop. Each cycle: deliberate (epistemic assessment via JSON),
   act (execute step or invoke tool), observe (update beliefs). The loop
   respects the budget 4-tuple and applies `on_stuck` when `Diverge` fires.
4. **Trace Events** — every BDI cycle emits `STEP_START`, `MODEL_CALL`, and
   `STEP_END` trace events, giving full observability into the agent's
   reasoning trajectory.

**Why this matters:** The agent is not a Python class that wraps `while True`.
It is a **compiled cognitive primitive** — the compiler verifies its budget
boundedness, the type checker validates its return type, the backend generates
strategy-specific prompts, and the runtime executes a formally-defined BDI loop
with epistemic convergence criteria. This is the difference between duct-taping
an LLM into a loop and engineering an autonomous system with mathematical
guarantees.

#### Agent Use Case 1: Autonomous Legal Research Agent

A law firm deploys an agent that autonomously researches case law until it finds
sufficient precedent — or exhausts its budget and escalates to a human attorney:

```axon
agent CaseLawResearcher {
    goal: "Find 3+ relevant precedents for the contract dispute
           with verified court citations"
    tools: [WebSearch, PDFExtractor]
    strategy: reflexion
    max_iterations: 20
    max_cost: 5.00
    on_stuck: escalate
    return: CaseLawReport
}
```

- `reflexion` strategy adds self-critique after each cycle — the agent evaluates
  whether its found precedents are truly relevant, not just keyword matches
- `on_stuck: escalate` means if the agent doubts its findings after 20 cycles,
  it raises `AgentStuckError` with full context, so the human reviews exactly
  where the agent got stuck
- Budget cap of $5.00 prevents runaway API costs — the compiler guarantees
  termination

#### Agent Use Case 2: Multi-Agent Data Pipeline

A BI platform chains two agents: one gathers data, the other analyzes it.
Both execute within the same compiled flow:

```axon
agent DataGatherer {
    goal: "Collect quarterly revenue data from public filings"
    tools: [WebSearch, FileReader]
    strategy: react
    max_iterations: 10
    on_stuck: retry
    return: DataSet
}

agent TrendAnalyzer {
    goal: "Identify year-over-year growth patterns and anomalies"
    tools: [Calculator, DataAnalyzer]
    strategy: plan_and_execute
    max_iterations: 8
    on_stuck: forge
    return: TrendReport
}

flow QuarterlyIntelligence(sector: String) -> TrendReport {
    step Gather { DataGatherer(sector) output: DataSet }
    step Analyze { TrendAnalyzer(Gather.output) output: TrendReport }
}
```

- Two agents, two strategies: `react` for data gathering (fast, tool-heavy),
  `plan_and_execute` for analysis (structured, plan-then-verify)
- Each agent has independent budget tracking — if `DataGatherer` costs $0.50,
  `TrendAnalyzer` still has its full budget
- If `TrendAnalyzer` gets stuck, `forge` triggers creative re-seeding via the
  Poincaré pipeline, generating novel analytical angles

#### Agent Use Case 3: Customer Onboarding Agent with Dynamic Recovery

A SaaS platform uses an agent to guide new customers through a personalized
onboarding flow, adapting when it gets stuck:

```axon
persona OnboardingSpecialist {
    domain: ["product knowledge", "user experience"]
    tone: warm
    confidence_threshold: 0.80
}

agent OnboardingGuide {
    goal: "Complete the customer's onboarding checklist with
           personalized recommendations for their industry"
    tools: [APICall, Calculator]
    strategy: custom
    max_iterations: 12
    max_tokens: 30000
    on_stuck: forge
    return: OnboardingReport

    step Greet { ask: "Welcome the user and assess their goals" }
    step Configure { ask: "Recommend workspace configuration" }
    step Train { ask: "Generate personalized tutorial sequence" }
}
```

- `custom` strategy: the agent follows a user-defined step sequence (Greet →
  Configure → Train), not a generic loop
- `on_stuck: forge` — if the agent can't personalize recommendations (e.g.,
  unknown industry), it triggers creative synthesis to propose novel onboarding
  paths instead of failing
- The `return: OnboardingReport` type is validated by the semantic type checker
  — the agent must produce a structurally valid report, not just free text

### VI. Compile-Time Security — the `shield` Primitive

> AXON v0.13 introduces an eighth paradigm shift: **Information Flow Control
> (IFC) as a first-class compiled construct**, providing compile-time security
> guarantees against LLM-specific attack vectors.

Every LLM framework treats security as an afterthought — runtime guardrails
bolted on top of applications. AXON's `shield` primitive makes security a
**compiler-verified property** of your program, grounded in taint analysis and
Information Flow Control theory.

**Trust Lattice (Denning-style IFC).** The shield system operates over a trust
lattice where data flows from untrusted sources through shield application
points to trusted sinks. The compiler statically verifies that every path from
an untrusted source to a trusted sink passes through at least one shield:

```text
U : DataLabel → TrustLevel

TrustLevel = Untrusted < Scanned < Sanitized < Trusted

∀ path(source, sink) ∈ Flow :
  label(source) = Untrusted ∧ label(sink) = Trusted
  → ∃ shield ∈ path : label(shield.output) ≥ Sanitized
```

**Threat Taxonomy.** The `scan` field declares which threats the shield detects,
drawn from a formal taxonomy of 11 LLM attack categories:

```text
T = { prompt_injection, jailbreak, data_exfil, pii_leak, toxicity,
      bias, hallucination, code_injection, social_engineering,
      model_theft, training_poisoning }
```

**Detection Strategies.** The `strategy` parameter selects the detection
mechanism, each with different cost/accuracy tradeoffs:

```text
Σ : Strategy → (Cost, Accuracy, Latency)

Σ(pattern)     = (low,    medium, fast)     — regex/heuristic scan
Σ(classifier)  = (medium, high,   medium)   — fine-tuned classifier (Llama Guard)
Σ(dual_llm)    = (high,   highest, slow)    — privileged/quarantined model pair
Σ(canary)      = (low,    medium, fast)     — traceable token injection
Σ(perplexity)  = (medium, high,   medium)   — statistical anomaly detection
Σ(ensemble)    = (high,   highest, slow)    — majority voting across multiple strategies
```

**Capability Enforcement.** The compiler statically verifies that agent tool
access is a subset of the shield's allow list — preventing privilege escalation
at compile time:

```text
∀ agent A with shield S :
  tools(A) ⊆ allow_tools(S)    — verified at compile time
  tools(A) ∩ deny_tools(S) = ∅  — also verified
```

**Usage example — LLM Input Shield:**

```axon
shield InputGuard {
    scan: [prompt_injection, jailbreak, pii_leak]
    strategy: dual_llm
    on_breach: halt
    severity: critical
    allow: [web_search, calculator]
    deny: [code_executor]
    sandbox: true
    redact: [email, phone]
    confidence_threshold: 0.85
}

persona SecureAssistant {
    domain: ["customer support"]
    tone: professional
    confidence_threshold: 0.80
}

agent SecureBot {
    goal: "Answer customer queries safely"
    tools: [web_search, calculator]
    shield: InputGuard
    strategy: react
    max_iterations: 10
    return: SafeResponse
}

flow SecureSupport(query: String) -> SafeResponse {
    shield InputGuard on query -> SanitizedQuery
    step Process {
        SecureBot(SanitizedQuery)
        output: SafeResponse
    }
}

run SecureSupport("Help me with my account")
    with SecureAssistant
```

What the compiler does:

1. **Type Checking** — validates all scan categories, strategies, breach
   policies, severity levels, and confidence thresholds. Detects allow/deny
   overlaps and invalid configurations at compile time.
2. **Capability Enforcement** — verifies that `SecureBot` only uses
   `[web_search, calculator]` which are in `InputGuard.allow`, and that
   neither appears in `deny`. If `SecureBot` tried to use `code_executor`,
   the compiler would reject the program.
3. **Taint Analysis** — verifies that `query` (untrusted) passes through
   `shield InputGuard on query` before reaching the agent's trusted context.
4. **Runtime Execution** — the shield step emits `SHIELD_SCAN_START`,
   scans for prompt injection/jailbreak/PII, and either passes
   (`SHIELD_SCAN_PASS`) or raises `ShieldBreachError` (`SHIELD_SCAN_BREACH`).

#### Shield Use Case 1: Financial Data Pipeline with PII Redaction

```axon
shield DataShield {
    scan: [pii_leak, data_exfil]
    strategy: classifier
    on_breach: sanitize_and_retry
    max_retries: 3
    severity: high
    redact: [ssn, credit_card, bank_account]
}

flow ProcessFinancialQuery(input: String) -> Report {
    shield DataShield on input -> CleanInput
    step Analyze {
        given: CleanInput
        ask: "Analyze the financial data"
        output: Report
    }
}
```

- PII fields (SSN, credit card, bank account) are auto-redacted **before** the
  LLM sees the data
- `sanitize_and_retry` means detected threats are cleaned and re-scanned up to
  3 times, not just blocked
- The compiler guarantees the LLM never processes raw PII

#### Shield Use Case 2: Multi-Agent System with Capability Isolation

```axon
shield ResearchShield {
    scan: [data_exfil, model_theft]
    strategy: ensemble
    on_breach: quarantine
    allow: [web_search, file_reader]
    deny: [code_executor, api_call]
    sandbox: true
}

agent Researcher {
    goal: "Gather market intelligence from public sources"
    tools: [web_search, file_reader]
    shield: ResearchShield
    strategy: reflexion
    max_iterations: 15
    return: IntelligenceReport
}
```

- `ensemble` strategy runs multiple detectors with majority voting — highest
  accuracy for sensitive operations
- `sandbox: true` runs tool execution in an isolated environment
- Capability enforcement: the compiler rejects any agent that tries to use
  `code_executor` or `api_call` — preventing privilege escalation by design
- `quarantine` breach policy isolates suspicious data for human review instead
  of blocking operations

### VII. Epistemic Tool Fortification — Streaming, Effects & Blame Semantics

> AXON v0.14 introduces a ninth paradigm shift: **formal epistemic control over
> tool invocations, streaming outputs, and foreign-function interfaces** — backed
> by algebraic effect theory, coinductive stream semantics, and Findler-Felleisen
> blame calculus.

Every LLM framework treats tool calls as black boxes: a function returns a
string, and the framework trusts it unconditionally. Streaming is even worse —
partial tokens arrive without any notion of confidence, reliability, or
epistemic state. AXON v0.14 solves this by making **every interaction with the
external world** subject to formal epistemic tracking.

#### Formal Model — Four Convergence Theorems

**CT-1: Coinductive Semantic Streaming.** A streaming response is a
coinductive process — an infinite observation/transition pair that monotonically
accumulates epistemic confidence as chunks arrive:

```text
Stream(τ) = νX. (StreamChunk × EpistemicState × X)

where
  StreamChunk    = (content: String, index: ℕ, timestamp: ℝ)
  EpistemicState = (level ∈ {doubt, speculate, believe, know}, confidence ∈ [0,1])
  ν              = greatest fixpoint (coinduction — process unfolds indefinitely)

Monotonicity invariant:
  ∀ i < j : gradient(chunkᵢ) ⊑ gradient(chunkⱼ)
  (epistemic level can only rise, never degrade during streaming)
```

Streaming in AXON is **not** "tokens arriving". It is a formal epistemic
process: each chunk carries its position on the lattice, and the system
guarantees that confidence can only increase monotonically until convergence.

**CT-2: Algebraic Effect Rows.** Every tool declares its computational effects
using Plotkin & Pretnar's algebraic effect theory. The compiler statically
verifies effect compatibility:

```text
EffectRow(tool) = ⟨ε₁, ε₂, ..., εₙ, epistemic:level⟩

where
  εᵢ ∈ {pure, io, network, storage, random}
  level ∈ {know, believe, speculate, doubt}

Composition rule:
  EffectRow(A ∘ B) = EffectRow(A) ∪ EffectRow(B)
  epistemic(A ∘ B) = min(epistemic(A), epistemic(B))   — meet on lattice
```

The composition rule means: if you chain a `network + speculate` tool with a
`pure + know` tool, the combined effect is `network + speculate` — the system
automatically tracks the **least trustworthy** component.

**CT-3: Blame Semantics for FFI.** External tool calls are wrapped in
Findler-Felleisen contract monitors that assign blame when pre/postconditions
fail:

```text
ContractMonitor(tool) = (Pre, Post, Blame)

where
  Pre  : Input → Bool         — caller's obligation
  Post : Output → Bool        — server's obligation
  Blame : {CALLER, SERVER}    — who violated the contract

Blame assignment:
  ¬Pre(input)   → Blame = CALLER   (you sent bad data)
  ¬Post(output) → Blame = SERVER   (tool returned bad data)
```

This is not error handling — this is **formal accountability**. When a tool
fails, AXON tells you *who* broke the contract, not just *that* it broke.

**CT-4: Epistemic Inference via CSP.** The `@csp_tool` decorator automatically
infers the epistemic level of any Python function by analyzing its effect
footprint using a constraint-satisfaction heuristic:

```text
Infer(f) : Function → EpistemicLevel

  If ∄ io/network/random ∈ effects(f) → know
  If ∃ network ∈ effects(f)           → speculate
  If ∃ random ∈ effects(f)            → doubt
  Otherwise                           → believe
```

#### What Makes This Revolutionary

No LLM framework in existence tracks **what a tool does to your epistemic
state**. LangChain, CrewAI, AutoGen — they all treat tool results as trusted
strings. This means:

- A web search result (unreliable) gets the same trust as a database query
  (reliable)
- A streaming response's first token gets the same trust as the final,
  validated output
- When a tool fails, you don't know if your input was wrong or the tool was
  broken

AXON solves all three. The compiler **guarantees** that:

1. Every tool call is tagged with its effect signature and epistemic level
2. Streaming outputs start at `doubt` and can only ascend monotonically
3. Tool failures carry blame labels that identify the responsible party
4. Data crossing the FFI boundary is **automatically tainted** — it cannot
   reach `know` level without passing through a shield or anchor

#### Use Case 1: Real-Time Financial Streaming with Epistemic Gradient

A trading desk receives streaming market data and needs to distinguish between
real-time quotes (speculative) and confirmed trades (factual):

```axon
tool MarketFeed {
    provider: bloomberg
    timeout: 5s
    effects: <io, network, epistemic:speculate>
}

flow MonitorMarket(sector: String) -> MarketReport {
    step Stream {
        stream<QuoteData> {
            on_chunk: {
                probe chunk for [symbol, price, volume]
                output: QuoteSnapshot
            }
            on_complete: {
                validate QuoteSnapshot against: MarketSchema
                output: VerifiedQuote
            }
        }
    }
    step Analyze {
        reason {
            given: Stream.output
            ask: "Identify anomalous price movements"
            depth: 2
        }
        output: MarketReport
    }
}
```

- Each streaming chunk starts at `doubt` — the system treats partial data as
  unreliable by default
- `on_complete` handler validates and promotes to `believe` — only complete,
  schema-validated data upgrades
- The `effects: <io, network, epistemic:speculate>` declaration means the
  compiler knows this tool is **never** factual — preventing accidental
  `know`-level assertions from market data

#### Use Case 2: Multi-Tool Research Agent with Blame Tracking

A research agent uses multiple tools with different reliability levels. When
something fails, the system identifies exactly who broke the contract:

```axon
tool WebSearch {
    provider: serper
    timeout: 10s
    effects: <network, epistemic:speculate>
}

tool DatabaseQuery {
    provider: internal
    timeout: 30s
    effects: <io, epistemic:believe>
}

tool Calculator {
    provider: stdlib
    effects: <pure, epistemic:know>
}

flow DeepResearch(question: String) -> ResearchReport {
    par {
        step Web {
            use_tool WebSearch with query: question
            output: WebResults
        }
        step DB {
            use_tool DatabaseQuery with query: question
            output: DBResults
        }
    }
    step Synthesize {
        weave [Web.output, DB.output]
        output: ResearchReport
    }
}
```

- `WebSearch` is `epistemic:speculate` — the compiler knows web results are
  unreliable and automatically taints downstream data
- `DatabaseQuery` is `epistemic:believe` — more reliable, but still not `know`
  because external I/O is involved
- `Calculator` is `pure + epistemic:know` — no side effects, deterministic,
  fully trustworthy
- When `weave` combines them, the result's epistemic level is
  `min(speculate, believe) = speculate` — the weakest link determines trust
- If `WebSearch` returns garbage, the `ContractMonitor` issues
  `Blame = SERVER` with full diagnostic context

#### Use Case 3: Safe External API Integration with @contract_tool

A production system integrates a third-party payment API. The `@contract_tool`
decorator wraps it with pre/postcondition contracts and automatic epistemic
downgrade:

```python
from axon.runtime.tools import contract_tool

@contract_tool(
    pre=lambda amount, currency: amount > 0 and currency in ["USD", "EUR"],
    post=lambda result: "transaction_id" in result,
    effect_row=("network", "io"),
    epistemic_level="speculate"
)
async def process_payment(amount: float, currency: str) -> dict:
    return await stripe_api.charge(amount, currency)
```

```axon
flow ProcessOrder(order: Order) -> Receipt {
    step Charge {
        use_tool process_payment with amount: order.total, currency: "USD"
        output: PaymentResult
    }
    step Verify {
        validate Charge.output against: PaymentSchema
        if confidence < 0.9 -> refine(max_attempts: 2)
        output: Receipt
    }
}
```

- `pre` contract: AXON validates that `amount > 0` and `currency` is valid
  **before** calling Stripe. If violated → `Blame = CALLER`
- `post` contract: AXON validates that the response contains a
  `transaction_id`. If violated → `Blame = SERVER` (Stripe returned bad data)
- All payment results are automatically `tainted = True` — they cannot reach
  `know` level without explicit anchor validation
- The `effects: <network, io>` declaration prevents this tool from being used
  inside a `pure` context — a compile-time error

---

### VIII. Structured Cognitive Retrieval — the `pix` Primitive

> AXON v0.15 introduces a tenth paradigm shift: **intent-driven tree navigation
> as a formally grounded alternative to vector-similarity retrieval (RAG)**,
> built on information foraging theory, bounded rational search, and full
> explainability via reasoning trails.

Every RAG system in existence makes the same assumption: *semantically close
embeddings imply relevance*. This works for keyword-style queries, but fails
catastrophically for structured documents — legal contracts, technical manuals,
medical records — where the answer lives at a specific structural location, not
in the nearest embedding vector.

AXON's `pix` primitive rejects the "embed everything, retrieve by cosine"
paradigm. Instead, it treats documents as **navigable trees** and retrieval as
a **bounded cognitive search** — the same process a human expert uses when
consulting a complex document: start at the table of contents, follow the most
promising branches, prune irrelevant paths, and explain every decision.

#### Formal Model — Rooted Directed Acyclic Tree (DAG→Tree)

**Document Tree.** A PIX-indexed document `D` is a rooted tree:

```text
D = (N, E, n₀)

where
  N  = {n₀, n₁, ..., nₖ}    — nodes (sections, subsections, paragraphs)
  E  ⊆ N × N               — directed edges (parent → child)
  n₀ ∈ N                    — root (document-level summary)

Properties:
  ∀ nᵢ ∈ N \ {n₀} : ∃! nⱼ : (nⱼ, nᵢ) ∈ E    — unique parent
  height(D) = h                                — maximum depth
  |leaves(D)| = content nodes with full text
```

Each node carries a **summary** (generated at index time) and optionally the
full section **content**. Internal nodes hold structure; leaf nodes hold
answers.

**Information Scent Navigation.** Navigation follows Pirolli & Card's
Information Foraging Theory. At each tree level, a scoring function `S`
evaluates the "information scent" of every child relative to the query:

```text
S : (query, title, summary) → [0, 1]

Navigation rule at depth d:
  children_d = {nᵢ : (current, nᵢ) ∈ E}
  scored     = {(nᵢ, S(q, nᵢ.title, nᵢ.summary)) : nᵢ ∈ children_d}
  selected   = top_k(scored, k=max_branch) ∩ {(n, s) : s ≥ threshold}

Fallback (no child meets threshold):
  selected = {argmax(scored)} if max(scored) > 0 else ∅
```

The key insight: **the scorer replaces embedding similarity**. In production it
is an LLM call; in tests a keyword-overlap heuristic suffices. Either way, the
navigator uses the same bounded-search algorithm.

**Bounded Rational Search.** Navigation terminates via a budget 4-tuple
verified at compile time:

```text
Config(pix) = (max_depth, max_branch, threshold, timeout)

Termination:
  depth ≥ max_depth  ∨  node.is_leaf  ∨  elapsed ≥ timeout
  → append to result leaves
```

This prevents unbounded traversal — the same principle behind AXON's agent
budget enforcement.

**Reasoning Trail (Explainability).** Every navigation produces a
`ReasoningPath` — an ordered sequence of `NavigationStep` records documenting
*why* each branch was selected or pruned:

```text
Trail = [Step₁, Step₂, ..., Stepₙ]

Stepᵢ = (node_id, title, score, reasoning, depth)

Properties:
  |Trail| = total nodes evaluated
  depth(Trail) = max(Stepᵢ.depth)
```

This is not logging — it is **formal explainability**. The trail is a
first-class data structure accessible via the `trail` keyword.

#### What Makes PIX Different from RAG

| Property | RAG | PIX |
|----------|-----|-----|
| Index structure | Flat vector store | Hierarchical tree |
| Retrieval method | Cosine similarity | Bounded tree navigation |
| Granularity | Fixed chunks | Structural sections |
| Explainability | None (black-box) | Full reasoning trail |
| Query type | Keyword/semantic | Intent-driven |
| Relevance model | "Closest vector" | "Most scented path" |
| Compile-time verification | ❌ | ✅ (depth, branching bounds) |

**PIX principle:** *"Lo estructuralmente navegado con intención es lo
relevante"* — what matters is not what is semantically close, but what a
rational agent would navigate to when consulting the document with purpose.

#### Usage Example — PIX-Navigated Legal Analysis

```axon
pix ContractIndex {
    source: "contracts/master_agreement.md"
    depth: 4
    branching: 3
    model: "fast"
}

flow AnalyzeContract(question: String) -> LegalAnalysis {
    step Search {
        navigate ContractIndex
            query: question
            trail: enabled
            as: relevant_sections
    }
    step Drill {
        drill ContractIndex
            into "Liabilities"
            query: question
            as: liability_detail
    }
    step Explain {
        trail relevant_sections
    }
    step Synthesize {
        weave [relevant_sections, liability_detail]
        format: LegalAnalysis
        include: [answer, sources, reasoning_trail]
    }
}
```

What the compiler does:

1. **Type Checking** — validates `pix` parameters (depth ≤ 10, branching ≤ 10),
   verifies that `navigate` and `drill` reference a declared `pix` (not a
   `persona` or `flow`), and guarantees output bindings are unique
2. **IR Generation** — compiles to `IRPixSpec`, `IRNavigate`, `IRDrill`, and
   `IRTrail` nodes carrying the full configuration (source, depth, branching,
   model, effects)
3. **Runtime Execution** — the PIX engine indexes the source document into a
   `DocumentTree`, then the navigator performs bounded tree search guided by the
   scoring function, recording every decision in the `ReasoningPath`
4. **Trail Output** — the `trail` step exposes the full reasoning path — every
   node evaluated, its score, and why it was selected or pruned

#### PIX Use Case 1: Medical Document Navigation

A hospital system needs to find specific clinical guidelines within a 200-page
protocol manual. RAG would chunk the document into 512-token fragments and
return the 5 closest embeddings — potentially mixing guidelines from different
sections. PIX navigates structurally:

```axon
pix ClinicalProtocol {
    source: "protocols/surgical_guidelines_v12.md"
    depth: 5
    branching: 2
    model: "precise"
}

flow FindGuideline(procedure: String) -> ClinicalGuideline {
    step Navigate {
        navigate ClinicalProtocol
            query: procedure
            trail: enabled
            as: guideline
    }
    step Verify {
        validate guideline against: ClinicalSchema
        if confidence < 0.9 -> refine(max_attempts: 2)
        output: ClinicalGuideline
    }
}
```

- `depth: 5` allows reaching deeply nested subsections (Chapter → Section →
  Subsection → Paragraph → Note)
- `branching: 2` limits exploration to the 2 most relevant children per level
  — fast, focused retrieval
- The trail documents *exactly* which sections were evaluated and why, which is
  required for medical audit compliance

#### PIX Use Case 2: Technical Documentation Q&A

A developer needs to find the exact API method for a specific task in a large
SDK documentation. RAG returns 5 chunks that all mention the API but none
answer the precise question. PIX drills directly:

```axon
pix SDKDocs {
    source: "docs/sdk_reference_v3.md"
    depth: 6
    branching: 3
}

flow AnswerDevQuestion(question: String) -> DevAnswer {
    step Browse {
        navigate SDKDocs query: question as: overview
    }
    step Deep {
        drill SDKDocs into "API Reference" query: question as: api_detail
    }
    step Respond {
        weave [overview, api_detail]
        format: DevAnswer
        include: [answer, code_examples, see_also]
    }
}
```

- `navigate` finds the general area; `drill` goes directly into "API Reference"
- Combined result gives both context (overview) and precision (api_detail)
- No embedding database needed — the document's own structure is the index

#### PIX Use Case 3: Regulatory Compliance Audit with Full Trail

A compliance team audits whether a company's data practices satisfy GDPR
requirements. The trail provides the auditable decision chain:

```axon
pix GDPRRegulation {
    source: "regulations/gdpr_full_text.md"
    depth: 4
    branching: 3
    model: "precise"
}

know {
    flow AuditCompliance(practice: String) -> ComplianceReport {
        step Find {
            navigate GDPRRegulation
                query: practice
                trail: enabled
                as: articles
        }
        step ShowTrail {
            trail articles
        }
        step Assess {
            reason {
                given: articles
                ask: "Does the practice comply with these articles?"
                depth: 3
            }
            output: ComplianceReport
        }
    }
}
```

- `know` block ensures maximum factual rigor — no speculation about regulations
- The `trail` provides a complete record of which GDPR articles were considered
  and why, satisfying regulatory audit requirements
- No vector database, no embedding model, no chunking strategy to tune — the
  regulation's own hierarchical structure (Part → Chapter → Section → Article)
  is the retrieval mechanism

---

## Architecture

```
.axon source → Lexer → Tokens → Parser → AST
                                           │
                              Type Checker (semantic validation)
                                           │
                              IR Generator → AXON IR (JSON-serializable)
                                           │
                              Backend (Anthropic │ OpenAI │ Gemini │ Ollama)
                                           │
                              Runtime (Executor + Validators + Tracer)
                                           │
                              Typed Output (validated, traced result)
```

### 33 Cognitive Primitives

| Primitive  | Keyword      | What it represents                                   |
| ---------- | ------------ | ---------------------------------------------------- |
| Persona    | `persona`    | Cognitive identity of the model                      |
| Context    | `context`    | Working memory / session config                      |
| Intent     | `intent`     | Atomic semantic instruction                          |
| Flow       | `flow`       | Composable pipeline of cognitive steps               |
| Reason     | `reason`     | Explicit chain-of-thought                            |
| Anchor     | `anchor`     | Hard constraint (never violable)                     |
| Validate   | `validate`   | Semantic validation gate                             |
| Refine     | `refine`     | Adaptive retry with failure context                  |
| Memory     | `memory`     | Persistent semantic storage                          |
| Tool       | `tool`       | External invocable capability                        |
| Probe      | `probe`      | Directed information extraction                      |
| Weave      | `weave`      | Semantic synthesis of multiple outputs               |
| Know       | `know`       | Epistemic scope — maximum factual rigor              |
| Believe    | `believe`    | Epistemic scope — moderate confidence                |
| Speculate  | `speculate`  | Epistemic scope — creative freedom                   |
| Doubt      | `doubt`      | Epistemic scope — adversarial validation             |
| Par        | `par`        | Parallel cognitive dispatch                          |
| Hibernate  | `hibernate`  | Dynamic state yielding / CPS checkpoint              |
| DataSpace  | `dataspace`  | In-memory associative data container                 |
| Ingest     | `ingest`     | Load external data into a DataSpace                  |
| Focus      | `focus`      | Select data — propagate associations                 |
| Associate  | `associate`  | Link tables via shared fields                        |
| Aggregate  | `aggregate`  | Group-by aggregation on selections                   |
| Explore    | `explore`    | Snapshot current associative state                   |
| Deliberate | `deliberate` | Compute budget control (tokens/depth/strategy)       |
| Consensus  | `consensus`  | Best-of-N parallel evaluation & selection            |
| Forge      | `forge`      | Directed creative synthesis (Poincaré pipeline)      |
| Agent      | `agent`      | Autonomous goal-seeking BDI cognitive system         |
| Shield     | `shield`     | Compile-time IFC security (taint + capability)       |
| Stream     | `stream`     | Coinductive semantic streaming with epistemic gradient|
| Effects    | `effects`    | Algebraic effect rows for tool declarations          |
| PIX        | `pix`        | Structured document index (navigable tree)           |
| Navigate   | `navigate`   | Intent-driven tree retrieval with reasoning trail    |
| Drill      | `drill`      | Subtree-scoped navigation for targeted retrieval     |
| Trail      | `trail`      | Explainability path — formal reasoning audit         |

### Epistemic Type System (Partial Order Lattice)

Types represent **meaning** and cognitive state, not just data structures. AXON
implements an epistemic type system based on a partial order lattice (T, ≤),
representing formal subsumption relationships:

```text
⊤ (Any)
    │
    ├── FactualClaim
    │   └── CitedFact
    │       └── HighConfidenceFact
    │
    ├── Opinion
    ├── Uncertainty   ← propagates upwards (taint)
    └── Speculation
⊥ (Never)
```

**Rule of Subsumption:** If T₁ ≤ T₂, then T₁ can be used where T₂ is expected.
For instance, a `CitedFact` can naturally satisfy a `FactualClaim` dependency,
but an `Opinion` **never** can. Furthermore, computations involving
`Uncertainty` structurally taint the result, propagating `Uncertainty` forwards
to guarantee epistemic honesty throughout the execution flow.

```
Content:      Document · Chunk · EntityMap · Summary · Translation
Analysis:     RiskScore(0..1) · ConfidenceScore(0..1) · SentimentScore(-1..1)
Structural:   Party · Obligation · Risk (user-defined)
Compound:     StructuredReport
```

---

## Project Structure

```
axon-constructor/
├── axon/
│   ├── compiler/
│   │   ├── lexer.py              # Source → Token stream
│   │   ├── tokens.py             # Token type enum (48 keywords)
│   │   ├── parser.py             # Tokens → AST (recursive descent)
│   │   ├── ast_nodes.py          # AST node class hierarchy
│   │   ├── type_checker.py       # Semantic type validation
│   │   ├── ir_generator.py       # AST → AXON IR
│   │   └── ir_nodes.py           # IR node definitions
│   ├── backends/
│   │   ├── base_backend.py       # Abstract backend interface
│   │   ├── anthropic.py          # Claude
│   │   ├── openai.py             # GPT
│   │   ├── gemini.py             # Gemini
│   │   └── ollama.py             # Local models
│   ├── engine/                   # In-memory associative data engine
│   │   ├── symbol_table.py       # Dictionary encoding
│   │   ├── data_column.py        # Columnar storage + inverted index
│   │   ├── association_index.py  # Cross-table link graph
│   │   ├── selection_state.py    # Selection propagation engine
│   │   ├── dataspace.py          # Top-level data container
│   │   └── pix/                  # PIX retrieval engine
│   │       ├── document_tree.py  # PixNode + DocumentTree (navigable tree)
│   │       ├── navigator.py      # PixNavigator (bounded tree search)
│   │       └── indexer.py        # PixIndexer (document → tree)
│   ├── runtime/
│   │   ├── executor.py           # Flow execution engine
│   │   ├── data_dispatcher.py    # Data Science IR → engine bridge
│   │   ├── context_mgr.py        # Mutable state between steps
│   │   ├── semantic_validator.py # Output type validation
│   │   ├── retry_engine.py       # Backoff + failure context
│   │   ├── memory_backend.py     # Abstract + InMemoryBackend
│   │   ├── state_backend.py      # CPS persistence (hibernate/resume)
│   │   ├── tracer.py             # 23 event types, JSON trace
│   │   ├── runtime_errors.py     # 11-level error hierarchy
│   │   └── tools/
│   │       ├── base_tool.py      # BaseTool ABC + ToolResult
│   │       ├── registry.py       # RuntimeToolRegistry (cached)
│   │       ├── dispatcher.py     # IR → runtime tool bridge
│   │       ├── contract_tool.py  # @contract_tool FFI decorator
│   │       ├── csp_tool.py       # @csp_tool auto-inference decorator
│   │       ├── blame.py          # Blame semantics (CT-3)
│   │       ├── epistemic_inference.py  # CSP heuristic engine (CT-4)
│   │       ├── stubs/            # 8 tools (6 stubs + 2 real)
│   │       └── backends/         # 3 production backends
│   ├── runtime/
│   │   └── streaming.py          # Coinductive streaming engine (CT-1)
│   └── stdlib/                   # Built-in personas, flows, anchors
└── tests/                        # 1513 tests
```

---

## Installation

```bash
# From PyPI
pip install axon-lang

# With real tool backends (WebSearch, etc.)
pip install axon-lang[tools]

# Verify
axon version
```

### From Source

```bash
git clone https://github.com/bemarking/axon-constructor.git
cd axon-constructor
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[tools,dev]"  # editable install
```

### Required API Keys

| Key                 | For               | Get it at                                               |
| ------------------- | ----------------- | ------------------------------------------------------- |
| `SERPER_API_KEY`    | WebSearch backend | [serper.dev](https://serper.dev/)                       |
| `ANTHROPIC_API_KEY` | Claude backend    | [console.anthropic.com](https://console.anthropic.com/) |
| `OPENAI_API_KEY`    | GPT backend       | [platform.openai.com](https://platform.openai.com/)     |
| `GEMINI_API_KEY`    | Gemini backend    | [aistudio.google.com](https://aistudio.google.com/)     |

None are required for development — stubs work without keys.

---

## CLI Usage

```bash
# Validate syntax: lex + parse + type-check
axon check program.axon

# Compile to IR JSON
axon compile program.axon                     # → program.ir.json
axon compile program.axon --stdout             # pipe to stdout
axon compile program.axon -b openai            # target backend
axon compile program.axon -o custom.json       # custom output path

# Execute end-to-end (requires API key for chosen backend)
axon run program.axon                          # default: anthropic
axon run program.axon -b gemini                # choose backend
axon run program.axon --trace                  # save execution trace
axon run program.axon --tool-mode hybrid       # stub | real | hybrid

# Pretty-print an execution trace
axon trace program.trace.json

# Version
axon version

# Interactive REPL
axon repl

# Introspect stdlib
axon inspect anchors                       # list all anchors
axon inspect personas                      # list all personas
axon inspect NoHallucination               # detail for a component
axon inspect --all                         # list everything
```

### Python API

```python
from axon import Lexer, Parser, TypeChecker, IRGenerator, get_backend

source = open("program.axon").read()
tokens  = Lexer(source).tokenize()
ast     = Parser(tokens).parse()
errors  = TypeChecker(ast).check()
ir      = IRGenerator().generate(ast)
backend = get_backend("anthropic")
result  = backend.compile(ir)
```

---

## Tests

```bash
# Full suite
pytest tests/ -v

# By layer
pytest tests/test_lexer.py tests/test_parser.py         # Phase 1: Language core
pytest tests/test_ir_nodes.py tests/test_backends.py     # Phase 2: Compiler
pytest tests/test_executor.py tests/test_retry.py        # Phase 3: Runtime
pytest tests/test_tool_stubs.py tests/test_tool_backends.py  # Phase 4: Tools
```

### Current Status

```
1513 passed, 0 failures ✅
```

| Phase | Tests | What's covered                              |
| ----- | ----- | ------------------------------------------- |
| 1     | 83    | Lexer, Parser, AST, Type Checker            |
| 2     | 164   | IR Generator, Compiler Backends             |
| 3     | 115   | Executor, Context, Retry, Tracer, Validator |
| 4     | 88    | Tool infra (53) + Real backends (35)        |
| 7     | 56    | Paradigm Shifts (epistemic, par, hibernate) |
| 8     | 69    | Data Science Engine (core)                  |
| 11    | 22    | Forge (creative synthesis pipeline)         |
| 12    | 28    | Agent (BDI pipeline + integration)          |
| 13    | 70    | Shield (compiler + runtime + integration)   |
| 14    | 83    | Streaming, Effects, Contract, CSP (CT-1–4)  |
| 15    | 124   | PIX (engine + compiler + integration)       |
| misc  | 611   | Stdlib, integration, edge cases             |

---

## Tool System

AXON tools bridge compile-time `IRUseTool` nodes with runtime implementations.

### Registry Modes

```python
from axon.runtime.tools import create_default_registry

# Safe for tests — no API calls, no I/O
registry = create_default_registry(mode="stub")

# Real backends where available, stubs elsewhere
registry = create_default_registry(mode="hybrid")

# Only real backends (fails if deps missing)
registry = create_default_registry(mode="real")
```

### Available Backends

| Tool          | Stub | Real Backend         | Requires         |
| ------------- | ---- | -------------------- | ---------------- |
| WebSearch     | ✅   | Serper.dev (httpx)   | `SERPER_API_KEY` |
| FileReader    | ✅   | Local filesystem     | —                |
| CodeExecutor  | ✅   | subprocess + asyncio | —                |
| Calculator    | —    | stdlib (real)        | —                |
| DateTime      | —    | stdlib (real)        | —                |
| PDFExtractor  | ✅   | —                    | —                |
| ImageAnalyzer | ✅   | —                    | —                |
| APICall       | ✅   | —                    | —                |

---

## Error Hierarchy

```
Level  1: ValidationError         — output type mismatch
Level  2: ConfidenceError         — confidence below floor
Level  3: AnchorBreachError       — anchor constraint violated
Level  4: RefineExhausted         — max retry attempts exceeded
Level  5: RuntimeError            — model call failed
Level  6: TimeoutError            — execution time limit exceeded
Level  7: ToolExecutionError      — tool invocation failed
Level  8: AgentStuckError         — agent stagnation detected
Level  9: ShieldBreachError       — shield detected security threat
Level 10: TaintViolationError     — untrusted data reached trusted sink
Level 11: CapabilityViolationError — tool access outside shield allow list
```

---

## Runtime Self-Healing

AXON features a native self-healing mechanism for **L3 Semantic Gates**. When
the LLM output violates a hard constraint (`AnchorBreachError`) or fails
structural semantic validation (`ValidationError`), the AXON `RetryEngine`
automatically intercepts the failure.

Instead of crashing or silently failing, the engine re-injects the exact
`failure_context` (e.g., _"Anchor breach detected: Hedging without citation"_)
back into the LLM's next prompt. This creates a closed feedback loop where the
model adaptively corrects its logic and structurally self-heals in real-time.

**Production Guarantees:**

- **Strict Boundaries:** The correction loop strictly respects the `refine`
  limits explicitly defined in the execution configuration. If the model fails
  to heal within the permitted attempts, AXON deterministically raises a
  `RefineExhaustedError` (containing the last failed state) to escalate the
  failure, preventing infinite execution loops.
- **Anchor Dependency:** The healing capability is directly proportional to the
  precision of the defined Anchors. AXON provides the robust recovery mechanism,
  but ambiguous or poorly defined constraints may cause the model to optimize
  for passing validation syntactically while failing semantically. Clear,
  logical Anchors are required.

### Phase 4: Logic & Epistemic Anchors

AXON includes specialized standard library anchors (Phase 4) explicitly designed
to work with the Self-Healing engine to enforce logical structures and epistemic
honesty:

- `SyllogismChecker`: Enforces explicit logical formats using `Premise:` and
  `Conclusion:` markers to guarantee structurally parseable arguments.
- `ChainOfThoughtValidator`: Requires explicit sequence step markers before
  resolving a prompt.
- `RequiresCitation`: Deep verification enforcing academic-style inline
  citations/URLs blocking unverifiable claims.
- `AgnosticFallback`: Penalizes unwarranted speculation, forcing the model to
  explicitly state a lack of information when sufficient data is unavailable.

---

## Roadmap

| Phase | What                                              | Status  |
| ----- | ------------------------------------------------- | ------- |
| 0     | Spec, grammar, type system                        | ✅ Done |
| 1     | Lexer, Parser, AST, Type Checker                  | ✅ Done |
| 2     | IR Generator, Compiler Backends                   | ✅ Done |
| 3     | Runtime (7 modules)                               | ✅ Done |
| 4     | Standard Library                                  | ✅ Done |
| 5     | CLI, REPL, Inspect                                | ✅ Done |
| 6     | Test Suite, Hardening, Docs                       | ✅ Done |
| 7     | Paradigm Shifts (epistemic/par/hibernate)         | ✅ Done |
| 8     | Data Science Engine + Runtime Integration         | ✅ Done |
| 9     | Executor integration + production backends        | ✅ Done |
| 10    | Compute Budget & Consensus (deliberate/consensus) | ✅ Done |
| 11    | Directed Creative Synthesis (`forge`)             | ✅ Done |
| 12    | Autonomous Agents (`agent` BDI primitive)         | ✅ Done |
| 13    | Security Shields (`shield` IFC primitive)         | ✅ Done |
| 14    | Epistemic Tool Fortification (stream/effects/FFI) | ✅ Done |
| 15    | Structured Cognitive Retrieval (`pix`)            | ✅ Done |

---

## Design Principles

1. **Declarative over imperative** — describe _what_, not _how_
2. **Semantic over syntactic** — types carry meaning, not layout
3. **Composable cognition** — blocks compose like neurons
4. **Configurable determinism** — spectrum from exploration to precision
5. **Failure as first-class citizen** — retry, refine, fallback are native

---

## How it Compares

|                               | LangChain | DSPy    | Guidance | **AXON** |
| ----------------------------- | --------- | ------- | -------- | -------- |
| Own language + grammar        | ❌        | ❌      | ❌       | ✅       |
| Semantic type system          | ❌        | Partial | ❌       | ✅       |
| Formal anchors                | ❌        | ❌      | ❌       | ✅       |
| Persona as type               | ❌        | ❌      | ❌       | ✅       |
| Reasoning as primitive        | ❌        | Partial | ❌       | ✅       |
| Native multi-model            | Partial   | Partial | ❌       | ✅       |
| Epistemic directives          | ❌        | ❌      | ❌       | ✅       |
| Native parallel dispatch      | ❌        | ❌      | ❌       | ✅       |
| State yielding / CPS          | ❌        | ❌      | ❌       | ✅       |
| Compute budget control        | ❌        | ❌      | ❌       | ✅       |
| Best-of-N consensus           | ❌        | ❌      | ❌       | ✅       |
| Creative synthesis engine     | ❌        | ❌      | ❌       | ✅       |
| Compiled autonomous agents    | ❌        | ❌      | ❌       | ✅       |
| Formal BDI convergence        | ❌        | ❌      | ❌       | ✅       |
| Budget-bounded agent loops    | ❌        | ❌      | ❌       | ✅       |
| Compile-time taint analysis   | ❌        | ❌      | ❌       | ✅       |
| Capability enforcement        | ❌        | ❌      | ❌       | ✅       |
| LLM attack surface shielding  | ❌        | ❌      | Partial  | ✅       |
| Algebraic effect rows         | ❌        | ❌      | ❌       | ✅       |
| Coinductive streaming         | ❌        | ❌      | ❌       | ✅       |
| FFI blame semantics           | ❌        | ❌      | ❌       | ✅       |
| Epistemic tool inference      | ❌        | ❌      | ❌       | ✅       |
| Structured tree retrieval     | ❌        | ❌      | ❌       | ✅       |
| Explainable retrieval trail   | ❌        | ❌      | ❌       | ✅       |
| Compile-time retrieval bounds | ❌        | ❌      | ❌       | ✅       |

---

## License

MIT

## Authors

Ricardo Velit
