# Fortalecimiento del Sistema de Tools de AXON

> **Análisis técnico y propuestas concretas para llevar el sistema de herramientas
> de AXON al siguiente nivel, aplicando los principios de optimización matemática
> de prompts descubiertos en la investigación.**

---

## 1. Diagnóstico del Estado Actual

### 1.1 Arquitectura Existente

```
IRToolSpec (compile-time)
    ↓
ToolDispatcher (bridge)
    ↓
RuntimeToolRegistry (look-up + cache)
    ↓
BaseTool.execute() (async)
    ↓
ToolResult (standardized output)
```

**Fortalezas:**
- Separación clara compile-time (IR) vs runtime (BaseTool)
- Registry instance-based → tests aislados
- Patrón stub/real/hybrid bien ejecutado
- Async desde el diseño (no retrofitted)

**Debilidades identificadas:**

| # | Debilidad | Severidad | Impacto |
|---|---|---|---|
| W1 | `IRUseTool` es extremadamente primitivo (solo `tool_name` + `argument`) | **Alta** | No permite parámetros tipados, múltiples inputs, ni output typing |
| W2 | Sin schema de validación de inputs/outputs en tools | **Alta** | No hay contrato formal entre el caller y la tool |
| W3 | Sin métricas de calidad ni trazabilidad de resultados | **Media** | No se puede medir information density del tool result |
| W4 | Sin composición de tools (tool chains) | **Media** | Cada tool opera aislada, sin pipeline capability |
| W5 | `ToolResult.data` es `Any` → sin type safety | **Media** | El resultado no se valida contra el tipo esperado del step |
| W6 | Sin retry/refinement en tool level | **Media** | Si un tool falla, el error se propaga sin self-healing |
| W7 | No hay feedback loop de calidad | **Baja** | No se aprende de ejecuciones anteriores |
| W8 | Sin soporte para tools paralelos | **Baja** | Un par block con tools las ejecuta secuencialmente |
| W9 | PDFExtractor, ImageAnalyzer, APICall son solo stubs | **Media** | 3 de 8 tools no tienen backend real |

---

## 2. Propuestas de Fortalecimiento

### 2.1 — Tool Schema Formal (ataca W1, W2, W5)

> **Principio matemático:** Satisfacción de Restricciones (§5.3 de la investigación).
> Tratar cada tool como un CSP con inputs/outputs tipados.

**Propuesta:** Añadir `ToolSchema` como contrato formal.

```python
@dataclass(frozen=True)
class ToolParameter:
    """Typed parameter for a tool invocation."""
    name: str
    type_name: str          # "string" | "int" | "float" | "list" | "dict"
    required: bool = True
    default: Any = None
    description: str = ""
    validation: str = ""     # regex or range expression

@dataclass(frozen=True)
class ToolSchema:
    """Formal contract for a tool's interface."""
    name: str
    description: str
    input_params: tuple[ToolParameter, ...]
    output_type: str         # semantic type from AXON type system
    output_schema: dict[str, str] = field(default_factory=dict)
    constraints: tuple[str, ...] = ()   # anchor names to validate output
    timeout_default: float = 30.0
    retry_policy: str = "none"          # none | linear | exponential
    max_retries: int = 0
```

**Impacto:** El compilador puede verificar en compile-time que los argumentos
pasados a `use WebSearch("query")` matchean el schema de WebSearch. Errores
de invocación se atrapan antes de ejecutar.

**Cambios requeridos:**
- `IRUseTool` → expandir con `parameters: dict[str, Any]` y `expected_output_type: str`
- `BaseTool` → añadir `SCHEMA: ClassVar[ToolSchema]`
- `ToolDispatcher` → validar inputs contra schema antes de ejecutar

---

### 2.2 — Tool Result Typing (ataca W5)

> **Principio matemático:** Lattice epistémico (§5.1). El resultado de un tool
> debe tener un tipo semántico que participe en el retículo de tipos de AXON.

```python
@dataclass
class TypedToolResult(ToolResult):
    """ToolResult with semantic type information."""
    semantic_type: str = ""          # e.g., "SearchResults", "FileContent"
    confidence: float = 1.0          # confidence in result correctness
    epistemic_mode: str = "know"     # inherited from calling context
    provenance: str = ""             # data lineage/origin

    def to_epistemic_type(self) -> str:
        """Map result to AXON's epistemic lattice.

        If confidence < threshold → Uncertainty taint propagation.
        """
        if self.confidence < 0.5:
            return "Uncertainty"
        if self.confidence < 0.75:
            return "Speculation"
        if self.epistemic_mode == "know" and self.provenance:
            return "CitedFact"
        return "FactualClaim"
```

**Impacto:** Los resultados de tools participan en el type checker epistémico.
Si un tool retorna con baja confianza, el taint de `Uncertainty` se propaga
automáticamente a los steps que consuman ese resultado.

---

### 2.3 — Tool Chains / Composición (ataca W4)

> **Principio matemático:** Composición funcional. Si tool₁: A → B y tool₂: B → C,
> entonces tool₁ ∘ tool₂: A → C con type safety en cada eslabón.

```python
@dataclass
class ToolChain:
    """Composable pipeline of tools with typed data flow."""
    steps: list[tuple[str, dict[str, str]]]  # [(tool_name, param_map)]

    async def execute(
        self,
        dispatcher: ToolDispatcher,
        initial_input: str,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute chain sequentially, piping output → input."""
        current = initial_input
        accumulated_metadata = {}

        for tool_name, param_map in self.steps:
            ir_use = IRUseTool(tool_name=tool_name, argument=current)
            result = await dispatcher.dispatch(ir_use, context=context)

            if not result.success:
                return result  # Fail-fast on error

            # Pipe output to next step
            current = str(result.data)
            accumulated_metadata[tool_name] = result.metadata

        return ToolResult(
            success=True,
            data=current,
            metadata=accumulated_metadata,
        )
```

**Ejemplo en AXON:**
```axon
step Research {
    use WebSearch("quantum computing 2026")
    pipe_to FileReader("summary.txt")  // chained
    pipe_to CodeExecutor("python analyze.py")
    output: AnalysisReport
}
```

---

### 2.4 — Tool-Level Self-Healing (ataca W6)

> **Principio matemático:** Controlador PID de §6.2 aplicado a nivel de tool.
> El RetryEngine ya existe para steps; extenderlo a tools.

```python
class ResilientToolDispatcher(ToolDispatcher):
    """Dispatcher with built-in retry and self-healing."""

    async def dispatch_with_retry(
        self,
        ir_use_tool: IRUseTool,
        *,
        max_retries: int = 3,
        backoff: str = "exponential",
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Dispatch with PID-guided retry logic."""
        for attempt in range(max_retries + 1):
            result = await self.dispatch(ir_use_tool, context=context)

            if result.success:
                result.metadata["attempt"] = attempt + 1
                return result

            # Inject failure context for next attempt
            if context is None:
                context = {}
            context["_failure_context"] = (
                f"Attempt {attempt + 1} failed: {result.error}. "
                f"Adjust approach."
            )

            # Exponential backoff
            if backoff == "exponential":
                import asyncio
                await asyncio.sleep(2 ** attempt * 0.5)

        return result  # Return last failure
```

---

### 2.5 — Quality Metrics & Observability (ataca W3, W7)

> **Principio matemático:** Information density ρ(p) = I(P;R)/|p| de §4.3
> aplicado a resultados de tools.

```python
@dataclass
class ToolMetrics:
    """Information-theoretic metrics for tool execution."""
    tool_name: str
    execution_time_ms: float
    result_entropy: float       # H(result) — information richness
    information_density: float  # quality / tokens
    compression_ratio: float   # vs naive approach
    cost_tokens: int            # tokens consumed
    quality_score: float        # [0, 1] assessment

    @property
    def efficiency(self) -> float:
        """Quality per millisecond — throughput metric."""
        if self.execution_time_ms <= 0:
            return 0.0
        return self.quality_score / (self.execution_time_ms / 1000)
```

**Impacto:** Cada ejecución de tool se instrumenta con métricas cuantitativas
que alimentan el sistema de feedback. Con suficientes datos, se puede:
1. Predecir qué tool es óptimo para cada tipo de consulta (GP surrogate)
2. Detectar degradación de calidad (PID integral accumulation)
3. Seleccionar dinámicamente entre stub/real/cache

---

### 2.6 — Parallel Tool Dispatch (ataca W8)

> **Principio matemático:** DAG Scheduling de §I del README.
> `par` blocks ya garantizan independencia en compile-time.

```python
class ParallelToolDispatcher(ToolDispatcher):
    """Dispatches independent tools concurrently via asyncio.gather."""

    async def dispatch_parallel(
        self,
        tool_invocations: list[IRUseTool],
        *,
        context: dict[str, Any] | None = None,
    ) -> list[ToolResult]:
        """Execute N tools concurrently.

        Achieves O(max(tᵢ)) latency instead of O(Σtᵢ).
        Pre-condition: all invocations are verified independent at compile-time.
        """
        import asyncio
        tasks = [
            self.dispatch(inv, context=context)
            for inv in tool_invocations
        ]
        return list(await asyncio.gather(*tasks))
```

---

### 2.7 — Production Backends Faltantes (ataca W9)

| Tool | Backend Propuesto | Tecnología | Prioridad |
|---|---|---|---|
| **PDFExtractor** | `PDFExtractorPyMuPDF` | PyMuPDF (fitz) | 🔴 Alta |
| **ImageAnalyzer** | `ImageAnalyzerVision` | OpenAI Vision API / Gemini Vision | 🟡 Media |
| **APICall** | `APICallHTTPX` | httpx async client | 🔴 Alta |

**Diseño para PDFExtractorPyMuPDF:**
```python
class PDFExtractorPyMuPDF(BaseTool):
    TOOL_NAME = "PDFExtractor"
    IS_STUB = False
    DEFAULT_TIMEOUT = 60.0

    def validate_config(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            raise ValueError("PyMuPDF required: pip install PyMuPDF")

    async def execute(self, query: str, **kwargs) -> ToolResult:
        import fitz
        path = query.strip()
        max_pages = kwargs.get("max_pages", 50)

        doc = fitz.open(path)
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append({
                "page": i + 1,
                "text": page.get_text(),
                "tables": len(page.find_tables()),
            })

        return ToolResult(
            success=True,
            data={"pages": pages, "total_pages": len(doc)},
            metadata={"path": path, "pages_extracted": len(pages)},
        )
```

---

## 3. Roadmap de Implementación

| Fase | Cambio | Archivos | Effort | Tests | Prioridad |
|---|---|---|---|---|---|
| 1 | Tool Schema formal | `ir_nodes.py`, `base_tool.py`, `dispatcher.py` | 2 días | 30+ | 🔴 |
| 2 | TypedToolResult + epistemic taint | `base_tool.py`, `semantic_validator.py` | 1 día | 15+ | 🔴 |
| 3 | ResilientToolDispatcher | `dispatcher.py` | 1 día | 20+ | 🟡 |
| 4 | ToolMetrics observability | `base_tool.py`, `tracer.py` | 1 día | 10+ | 🟡 |
| 5 | ParallelToolDispatcher | `dispatcher.py`, `executor.py` | 1 día | 15+ | 🟡 |
| 6 | Tool chains / composition | `dispatcher.py`, parser grammar | 2 días | 25+ | 🟢 |
| 7 | Production backends (PDF, API) | `backends/` | 2 días | 20+ | 🔴 |

**Total estimado:** ~10 días de desarrollo, ~135+ tests nuevos.

---

## 4. Conexión con la Optimización Matemática

Cada mejora propuesta se ancla en los principios formales de la investigación:

```
Investigación (§)          →  Mejora en Tools
──────────────────────────────────────────────
§2 (Information Theory)    →  ToolMetrics: medir rho(p), H(result)
§3 (Bayesian Optimization) → GP surrogate para tool selection
§4 (Kolmogorov/MDL)        →  Compression ratio en results
§5 (Lattice/CSP)           →  ToolSchema como CSP formal
§6 (Control Theory/PID)    →  ResilientToolDispatcher
§7 (Pareto)                →  Multi-objective tool ranking
§8 (Best-of-N)             →  Parallel dispatch + consensus
```

**El sistema de tools de AXON se convierte en un pipeline matemáticamente
optimizable** — no solo ejecuta herramientas, sino que mide, predice,
verifica y se auto-corrige.
