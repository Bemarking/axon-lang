<p align="center">
  <strong>AXON</strong><br>
  A programming language whose primitives are cognitive primitives of AI.
</p>

<p align="center">
  <code>persona</code> · <code>intent</code> · <code>flow</code> · <code>reason</code> · <code>anchor</code> · <code>refine</code> · <code>memory</code> · <code>tool</code> · <code>probe</code> · <code>weave</code> · <code>validate</code> · <code>context</code>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: Alpha">
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/tests-731%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
  <img src="https://img.shields.io/pypi/v/axon-lang" alt="PyPI">
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

### 12 Cognitive Primitives

| Primitive | Keyword    | What it represents                     |
| --------- | ---------- | -------------------------------------- |
| Persona   | `persona`  | Cognitive identity of the model        |
| Context   | `context`  | Working memory / session config        |
| Intent    | `intent`   | Atomic semantic instruction            |
| Flow      | `flow`     | Composable pipeline of cognitive steps |
| Reason    | `reason`   | Explicit chain-of-thought              |
| Anchor    | `anchor`   | Hard constraint (never violable)       |
| Validate  | `validate` | Semantic validation gate               |
| Refine    | `refine`   | Adaptive retry with failure context    |
| Memory    | `memory`   | Persistent semantic storage            |
| Tool      | `tool`     | External invocable capability          |
| Probe     | `probe`    | Directed information extraction        |
| Weave     | `weave`    | Semantic synthesis of multiple outputs |

### Semantic Type System

Types represent **meaning**, not data structures:

```
Epistemic:    FactualClaim · Opinion · Uncertainty · Speculation
Content:      Document · Chunk · EntityMap · Summary · Translation
Analysis:     RiskScore(0..1) · ConfidenceScore(0..1) · SentimentScore(-1..1)
Structural:   Party · Obligation · Risk (user-defined)
Compound:     StructuredReport
```

`Opinion` can **never** satisfy a `FactualClaim` slot. `Uncertainty` propagates
— any computation with `Uncertainty` produces `Uncertainty`.

---

## Project Structure

```
axon-constructor/
├── axon/
│   ├── compiler/
│   │   ├── lexer.py              # Source → Token stream
│   │   ├── tokens.py             # Token type enum
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
│   ├── runtime/
│   │   ├── executor.py           # Flow execution engine
│   │   ├── context_mgr.py        # Mutable state between steps
│   │   ├── semantic_validator.py # Output type validation
│   │   ├── retry_engine.py       # Backoff + failure context
│   │   ├── memory_backend.py     # Abstract + InMemoryBackend
│   │   ├── tracer.py             # 14 event types, JSON trace
│   │   ├── runtime_errors.py     # 6-level error hierarchy
│   │   └── tools/
│   │       ├── base_tool.py      # BaseTool ABC + ToolResult
│   │       ├── registry.py       # RuntimeToolRegistry (cached)
│   │       ├── dispatcher.py     # IR → runtime tool bridge
│   │       ├── stubs/            # 8 tools (6 stubs + 2 real)
│   │       └── backends/         # 3 production backends
│   └── stdlib/                   # Built-in personas, flows, anchors
└── tests/                        # 731 tests
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
731 passed, 2 known failures (IR serialization edge cases)
```

| Phase | Tests | What's covered                              |
| ----- | ----- | ------------------------------------------- |
| 1     | 83    | Lexer, Parser, AST, Type Checker            |
| 2     | 164   | IR Generator, Compiler Backends             |
| 3     | 115   | Executor, Context, Retry, Tracer, Validator |
| 4     | 88    | Tool infra (53) + Real backends (35)        |
| misc  | 281   | Stdlib, integration, edge cases             |

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

---

## Roadmap

| Phase | What                             | Status         |
| ----- | -------------------------------- | -------------- |
| 0     | Spec, grammar, type system       | ✅ Done        |
| 1     | Lexer, Parser, AST, Type Checker | ✅ Done        |
| 2     | IR Generator, Compiler Backends  | ✅ Done        |
| 3     | Runtime (7 modules)              | ✅ Done        |
| 4     | Standard Library                 | 🔧 In progress |
| 5     | CLI, REPL, VSCode Extension      | 🔧 In progress |
| 6     | Test Suite, Hardening, Docs      | ⬜ Planned     |

---

## Design Principles

1. **Declarative over imperative** — describe _what_, not _how_
2. **Semantic over syntactic** — types carry meaning, not layout
3. **Composable cognition** — blocks compose like neurons
4. **Configurable determinism** — spectrum from exploration to precision
5. **Failure as first-class citizen** — retry, refine, fallback are native

---

## How it Compares

|                        | LangChain | DSPy    | Guidance | **AXON** |
| ---------------------- | --------- | ------- | -------- | -------- |
| Own language + grammar | ❌        | ❌      | ❌       | ✅       |
| Semantic type system   | ❌        | Partial | ❌       | ✅       |
| Formal anchors         | ❌        | ❌      | ❌       | ✅       |
| Persona as type        | ❌        | ❌      | ❌       | ✅       |
| Reasoning as primitive | ❌        | Partial | ❌       | ✅       |
| Native multi-model     | Partial   | Partial | ❌       | ✅       |

---

## License

MIT

## Authors

Ricardo Velit
