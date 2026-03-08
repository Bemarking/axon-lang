<p align="center">
  <strong>AXON</strong><br>
  A programming language whose primitives are cognitive primitives of AI.
</p>

<p align="center">
  <code>persona</code> · <code>intent</code> · <code>flow</code> · <code>reason</code> · <code>anchor</code> · <code>refine</code> · <code>memory</code> · <code>tool</code> · <code>probe</code> · <code>weave</code> · <code>validate</code> · <code>context</code><br>
  <code>know</code> · <code>believe</code> · <code>speculate</code> · <code>doubt</code> · <code>par</code> · <code>hibernate</code><br>
  <code>dataspace</code> · <code>ingest</code> · <code>focus</code> · <code>associate</code> · <code>aggregate</code> · <code>explore</code><br>
  <code>deliberate</code> · <code>consensus</code>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: Alpha">
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-980%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/paradigms-5%20shifts-blueviolet" alt="Paradigm Shifts">
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

### 26 Cognitive Primitives

| Primitive  | Keyword      | What it represents                             |
| ---------- | ------------ | ---------------------------------------------- |
| Persona    | `persona`    | Cognitive identity of the model                |
| Context    | `context`    | Working memory / session config                |
| Intent     | `intent`     | Atomic semantic instruction                    |
| Flow       | `flow`       | Composable pipeline of cognitive steps         |
| Reason     | `reason`     | Explicit chain-of-thought                      |
| Anchor     | `anchor`     | Hard constraint (never violable)               |
| Validate   | `validate`   | Semantic validation gate                       |
| Refine     | `refine`     | Adaptive retry with failure context            |
| Memory     | `memory`     | Persistent semantic storage                    |
| Tool       | `tool`       | External invocable capability                  |
| Probe      | `probe`      | Directed information extraction                |
| Weave      | `weave`      | Semantic synthesis of multiple outputs         |
| Know       | `know`       | Epistemic scope — maximum factual rigor        |
| Believe    | `believe`    | Epistemic scope — moderate confidence          |
| Speculate  | `speculate`  | Epistemic scope — creative freedom             |
| Doubt      | `doubt`      | Epistemic scope — adversarial validation       |
| Par        | `par`        | Parallel cognitive dispatch                    |
| Hibernate  | `hibernate`  | Dynamic state yielding / CPS checkpoint        |
| DataSpace  | `dataspace`  | In-memory associative data container           |
| Ingest     | `ingest`     | Load external data into a DataSpace            |
| Focus      | `focus`      | Select data — propagate associations           |
| Associate  | `associate`  | Link tables via shared fields                  |
| Aggregate  | `aggregate`  | Group-by aggregation on selections             |
| Explore    | `explore`    | Snapshot current associative state             |
| Deliberate | `deliberate` | Compute budget control (tokens/depth/strategy) |
| Consensus  | `consensus`  | Best-of-N parallel evaluation & selection      |

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
│   │   └── dataspace.py          # Top-level data container
│   ├── runtime/
│   │   ├── executor.py           # Flow execution engine
│   │   ├── data_dispatcher.py    # Data Science IR → engine bridge
│   │   ├── context_mgr.py        # Mutable state between steps
│   │   ├── semantic_validator.py # Output type validation
│   │   ├── retry_engine.py       # Backoff + failure context
│   │   ├── memory_backend.py     # Abstract + InMemoryBackend
│   │   ├── state_backend.py      # CPS persistence (hibernate/resume)
│   │   ├── tracer.py             # 14 event types, JSON trace
│   │   ├── runtime_errors.py     # 6-level error hierarchy
│   │   └── tools/
│   │       ├── base_tool.py      # BaseTool ABC + ToolResult
│   │       ├── registry.py       # RuntimeToolRegistry (cached)
│   │       ├── dispatcher.py     # IR → runtime tool bridge
│   │       ├── stubs/            # 8 tools (6 stubs + 2 real)
│   │       └── backends/         # 3 production backends
│   └── stdlib/                   # Built-in personas, flows, anchors
└── tests/                        # 947 tests
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
947 passed, 0 failures ✅
```

| Phase | Tests | What's covered                              |
| ----- | ----- | ------------------------------------------- |
| 1     | 83    | Lexer, Parser, AST, Type Checker            |
| 2     | 164   | IR Generator, Compiler Backends             |
| 3     | 115   | Executor, Context, Retry, Tracer, Validator |
| 4     | 88    | Tool infra (53) + Real backends (35)        |
| 7     | 56    | Paradigm Shifts (epistemic, par, hibernate) |
| 8     | 69    | Data Science Engine (core)                  |
| misc  | 372   | Stdlib, integration, edge cases             |

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
Level 1: ValidationError    — output type mismatch
Level 2: ConfidenceError    — confidence below floor
Level 3: AnchorBreachError  — anchor constraint violated
Level 4: RefineExhausted    — max retry attempts exceeded
Level 5: RuntimeError       — model call failed
Level 6: TimeoutError       — execution time limit exceeded
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

---

## Design Principles

1. **Declarative over imperative** — describe _what_, not _how_
2. **Semantic over syntactic** — types carry meaning, not layout
3. **Composable cognition** — blocks compose like neurons
4. **Configurable determinism** — spectrum from exploration to precision
5. **Failure as first-class citizen** — retry, refine, fallback are native

---

## How it Compares

|                          | LangChain | DSPy    | Guidance | **AXON** |
| ------------------------ | --------- | ------- | -------- | -------- |
| Own language + grammar   | ❌        | ❌      | ❌       | ✅       |
| Semantic type system     | ❌        | Partial | ❌       | ✅       |
| Formal anchors           | ❌        | ❌      | ❌       | ✅       |
| Persona as type          | ❌        | ❌      | ❌       | ✅       |
| Reasoning as primitive   | ❌        | Partial | ❌       | ✅       |
| Native multi-model       | Partial   | Partial | ❌       | ✅       |
| Epistemic directives     | ❌        | ❌      | ❌       | ✅       |
| Native parallel dispatch | ❌        | ❌      | ❌       | ✅       |
| State yielding / CPS     | ❌        | ❌      | ❌       | ✅       |
| Compute budget control   | ❌        | ❌      | ❌       | ✅       |
| Best-of-N consensus      | ❌        | ❌      | ❌       | ✅       |

---

## License

MIT

## Authors

Ricardo Velit
