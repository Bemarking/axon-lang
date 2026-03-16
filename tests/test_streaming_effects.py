"""
Tests for AXON v0.14.0 P0 Features — Convergence Theorems 1-4
================================================================
Comprehensive test suite covering:
  1. Semantic Streaming with Epistemic Gradient (CT-1)
  2. Tool Effects with Epistemic Row Types (CT-2) — via tokens/AST/IR
  3. @contract_tool FFI with Blame Semantics (CT-3)
  4. @csp_tool CSP Generator Decorator (CT-4)
"""

import asyncio
import pytest
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  FEATURE 1: STREAMING — Epistemic Gradient & Coinductive Eval
# ═══════════════════════════════════════════════════════════════════

class TestEpistemicLevel:
    """Tests for the EpistemicLevel enum and lattice ordering."""

    def test_ordering(self):
        from axon.runtime.streaming import EpistemicLevel
        assert EpistemicLevel.BOTTOM < EpistemicLevel.DOUBT
        assert EpistemicLevel.DOUBT < EpistemicLevel.SPECULATE
        assert EpistemicLevel.SPECULATE < EpistemicLevel.BELIEVE
        assert EpistemicLevel.BELIEVE < EpistemicLevel.KNOW

    def test_parse_valid(self):
        from axon.runtime.streaming import EpistemicLevel, parse_epistemic_level
        assert parse_epistemic_level("doubt") == EpistemicLevel.DOUBT
        assert parse_epistemic_level("KNOW") == EpistemicLevel.KNOW
        assert parse_epistemic_level("Speculate") == EpistemicLevel.SPECULATE

    def test_parse_invalid(self):
        from axon.runtime.streaming import parse_epistemic_level
        with pytest.raises(ValueError, match="Invalid epistemic level"):
            parse_epistemic_level("invalid")


class TestEpistemicGradient:
    """Tests for monotonic gradient tracking."""

    def test_initial_state(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        assert g.current == EpistemicLevel.BOTTOM
        assert not g.is_converged

    def test_monotonic_ascent(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.DOUBT)
        g.advance(EpistemicLevel.SPECULATE)
        g.advance(EpistemicLevel.BELIEVE)
        assert g.current == EpistemicLevel.BELIEVE

    def test_descent_violation(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel, GradientViolation
        g = EpistemicGradient()
        g.advance(EpistemicLevel.BELIEVE)
        with pytest.raises(GradientViolation, match="Monotonicity violation"):
            g.advance(EpistemicLevel.DOUBT)

    def test_same_level_ok(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.SPECULATE)
        g.advance(EpistemicLevel.SPECULATE)  # Same level OK
        assert g.current == EpistemicLevel.SPECULATE

    def test_convergence_to_know(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.KNOW)
        assert g.is_converged

    def test_history_tracking(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.DOUBT)
        g.advance(EpistemicLevel.BELIEVE)
        history = g.history
        assert len(history) == 3  # BOTTOM, DOUBT, BELIEVE
        assert history[0][1] == EpistemicLevel.BOTTOM
        assert history[1][1] == EpistemicLevel.DOUBT
        assert history[2][1] == EpistemicLevel.BELIEVE

    def test_can_promote_to_know(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.BELIEVE)
        assert g.can_promote_to_know(
            stream_complete=True,
            anchor_valid=True,
            contracts_satisfied=True,
        )
        assert not g.can_promote_to_know(
            stream_complete=True,
            anchor_valid=False,
            contracts_satisfied=True,
        )

    def test_cannot_promote_from_speculate(self):
        from axon.runtime.streaming import EpistemicGradient, EpistemicLevel
        g = EpistemicGradient()
        g.advance(EpistemicLevel.SPECULATE)
        assert not g.can_promote_to_know(
            stream_complete=True,
            anchor_valid=True,
            contracts_satisfied=True,
        )


class TestStreamChunk:
    """Tests for StreamChunk data structure."""

    def test_safe_chunk(self):
        from axon.runtime.streaming import StreamChunk
        chunk = StreamChunk(data="hello", index=0, shield_passed=True, tainted=False)
        assert chunk.is_safe

    def test_tainted_chunk_unsafe(self):
        from axon.runtime.streaming import StreamChunk
        chunk = StreamChunk(data="hello", tainted=True)
        assert not chunk.is_safe

    def test_shield_failed_unsafe(self):
        from axon.runtime.streaming import StreamChunk
        chunk = StreamChunk(data="hello", shield_passed=False)
        assert not chunk.is_safe


class TestCoinductiveEvaluator:
    """Tests for the co-inductive shield evaluator."""

    def test_evaluate_chunk_passes(self):
        from axon.runtime.streaming import CoinductiveEvaluator, StreamChunk
        evaluator = CoinductiveEvaluator(shield_name="Guard")
        chunk = StreamChunk(data="clean text", index=0)
        result = evaluator.evaluate_chunk(chunk)
        assert result.shield_passed
        assert evaluator.chunk_count == 1
        assert not evaluator.has_violations

    def test_accumulates_text(self):
        from axon.runtime.streaming import CoinductiveEvaluator, StreamChunk
        evaluator = CoinductiveEvaluator(shield_name="Guard")
        evaluator.evaluate_chunk(StreamChunk(data="part1 ", index=0))
        evaluator.evaluate_chunk(StreamChunk(data="part2", index=1))
        assert evaluator.accumulated_text == "part1 part2"
        assert evaluator.chunk_count == 2

    def test_finalize_summary(self):
        from axon.runtime.streaming import CoinductiveEvaluator, StreamChunk
        evaluator = CoinductiveEvaluator(shield_name="Guard")
        evaluator.evaluate_chunk(StreamChunk(data="test", index=0))
        summary = evaluator.finalize()
        assert summary["shield"] == "Guard"
        assert summary["chunks_evaluated"] == 1
        assert summary["verdict"] == "pass"


class TestSemanticStream:
    """Tests for the async semantic stream."""

    @pytest.mark.asyncio
    async def test_basic_streaming(self):
        from axon.runtime.streaming import SemanticStream, EpistemicLevel

        async def fake_source():
            for word in ["Hello", " ", "World"]:
                yield word

        async with SemanticStream(source=fake_source()) as stream:
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        assert len(chunks) == 3
        assert stream.accumulated_data == "Hello World"
        assert stream.is_complete

    @pytest.mark.asyncio
    async def test_gradient_progression(self):
        from axon.runtime.streaming import SemanticStream, EpistemicLevel

        async def fake_source():
            for i in range(5):
                yield f"chunk{i}"

        async with SemanticStream(source=fake_source()) as stream:
            states = []
            async for chunk in stream:
                states.append(chunk.epistemic_state)

        # Gradient: DOUBT → SPECULATE → SPECULATE → BELIEVE → BELIEVE
        assert states[0] == EpistemicLevel.DOUBT
        assert states[1] == EpistemicLevel.SPECULATE
        assert states[2] == EpistemicLevel.SPECULATE
        assert states[3] == EpistemicLevel.BELIEVE

    @pytest.mark.asyncio
    async def test_budget_backpressure(self):
        from axon.runtime.streaming import SemanticStream

        async def fake_source():
            for i in range(100):
                yield f"chunk{i}"

        async with SemanticStream(source=fake_source(), budget=3) as stream:
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        assert len(chunks) == 3  # Budget limited
        assert stream.budget_remaining == 0

    @pytest.mark.asyncio
    async def test_promotion_after_complete(self):
        from axon.runtime.streaming import SemanticStream, EpistemicLevel

        async def fake_source():
            for i in range(5):
                yield f"chunk{i}"

        async with SemanticStream(source=fake_source()) as stream:
            async for _ in stream:
                pass

        assert stream.can_promote_to_know(
            anchor_valid=True, contracts_satisfied=True
        )
        level = stream.promote()
        assert level == EpistemicLevel.KNOW

    @pytest.mark.asyncio
    async def test_summary_generation(self):
        from axon.runtime.streaming import SemanticStream

        async def fake_source():
            yield "test"

        async with SemanticStream(source=fake_source()) as stream:
            async for _ in stream:
                pass

        summary = stream.to_summary()
        assert summary["chunks_total"] == 1
        assert summary["complete"]
        assert "shield_evaluation" in summary


# ═══════════════════════════════════════════════════════════════════
#  FEATURE 2: TOKENS & AST — Effect Row Keywords
# ═══════════════════════════════════════════════════════════════════

class TestStreamingTokens:
    """Tests for new streaming and effect keywords in the lexer."""

    def test_stream_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "stream" in KEYWORDS
        assert KEYWORDS["stream"] == TokenType.STREAM

    def test_on_chunk_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "on_chunk" in KEYWORDS
        assert KEYWORDS["on_chunk"] == TokenType.ON_CHUNK

    def test_on_complete_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "on_complete" in KEYWORDS
        assert KEYWORDS["on_complete"] == TokenType.ON_COMPLETE

    def test_effects_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "effects" in KEYWORDS
        assert KEYWORDS["effects"] == TokenType.EFFECTS

    def test_pure_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "pure" in KEYWORDS
        assert KEYWORDS["pure"] == TokenType.PURE

    def test_network_keyword(self):
        from axon.compiler.tokens import TokenType, KEYWORDS
        assert "network" in KEYWORDS
        assert KEYWORDS["network"] == TokenType.NETWORK


class TestStreamingASTNodes:
    """Tests for new AST nodes for streaming and effects."""

    def test_effect_row_node(self):
        from axon.compiler.ast_nodes import EffectRowNode
        node = EffectRowNode(effects=["io", "network"], epistemic_level="speculate")
        assert node.effects == ["io", "network"]
        assert node.epistemic_level == "speculate"

    def test_stream_handler_node(self):
        from axon.compiler.ast_nodes import StreamHandlerNode
        node = StreamHandlerNode(handler_type="on_chunk", param_name="chunk")
        assert node.handler_type == "on_chunk"
        assert node.param_name == "chunk"

    def test_stream_definition(self):
        from axon.compiler.ast_nodes import StreamDefinition
        node = StreamDefinition(
            name="Diagnosis",
            epistemic_gradient=["doubt", "speculate", "believe", "know"],
        )
        assert node.name == "Diagnosis"
        assert len(node.epistemic_gradient) == 4

    def test_tool_definition_effects(self):
        from axon.compiler.ast_nodes import ToolDefinition, EffectRowNode
        effects = EffectRowNode(effects=["io", "network"], epistemic_level="speculate")
        tool = ToolDefinition(name="WebSearch", effects=effects)
        assert tool.effects is not None
        assert tool.effects.epistemic_level == "speculate"


class TestStreamingIRNodes:
    """Tests for new IR nodes for streaming and effects."""

    def test_ir_effect_row(self):
        from axon.compiler.ir_nodes import IREffectRow
        node = IREffectRow(effects=("io", "network"), epistemic_level="speculate")
        assert node.effects == ("io", "network")
        assert node.node_type == "effect_row"

    def test_ir_stream_spec(self):
        from axon.compiler.ir_nodes import IRStreamSpec
        node = IRStreamSpec(
            name="Diagnosis",
            element_type="str",
            epistemic_gradient=("doubt", "speculate", "believe", "know"),
            shield_ref="InputGuard",
        )
        assert node.name == "Diagnosis"
        assert len(node.epistemic_gradient) == 4
        assert node.shield_ref == "InputGuard"

    def test_ir_tool_spec_effect_row(self):
        from axon.compiler.ir_nodes import IRToolSpec, IREffectRow
        effect = IREffectRow(effects=("io",), epistemic_level="believe")
        tool = IRToolSpec(name="TestTool", effect_row=effect)
        assert tool.effect_row is not None
        assert tool.effect_row.epistemic_level == "believe"


# ═══════════════════════════════════════════════════════════════════
#  FEATURE 3: BLAME SEMANTICS & @contract_tool
# ═══════════════════════════════════════════════════════════════════

class TestBlameLabel:
    """Tests for blame attribution labels."""

    def test_blame_values(self):
        from axon.runtime.tools.blame import BlameLabel
        assert BlameLabel.CALLER.value == "caller"
        assert BlameLabel.SERVER.value == "server"


class TestBlameFault:
    """Tests for structured fault records."""

    def test_fault_creation(self):
        from axon.runtime.tools.blame import BlameLabel, BlameFault
        fault = BlameFault(
            label=BlameLabel.SERVER,
            boundary="postcondition",
            tool_name="WebSearch",
            expected_type="list[dict]",
            actual_type="str",
            message="Type mismatch",
        )
        assert fault.label == BlameLabel.SERVER
        assert fault.boundary == "postcondition"

    def test_fault_serialization(self):
        from axon.runtime.tools.blame import BlameLabel, BlameFault
        fault = BlameFault(
            label=BlameLabel.CALLER,
            boundary="precondition",
            tool_name="Search",
            message="Missing required param",
        )
        d = fault.to_dict()
        assert d["blame"] == "caller"
        assert d["boundary"] == "precondition"
        assert d["tool"] == "Search"


class TestContractMonitor:
    """Tests for the ContractMonitor with Indy blame semantics."""

    def _make_schema(self):
        from axon.runtime.tools.tool_schema import ToolSchema, ToolParameter
        return ToolSchema(
            name="TestTool",
            description="Test tool",
            input_params=[
                ToolParameter(name="query", type_name="str", required=True),
                ToolParameter(name="limit", type_name="int", required=False, default=5),
            ],
            output_type="list",
        )

    def test_precondition_valid(self):
        from axon.runtime.tools.blame import ContractMonitor
        monitor = ContractMonitor()
        schema = self._make_schema()
        fault = monitor.check_precondition(schema, {"query": "test"})
        assert fault is None
        assert not monitor.has_faults

    def test_precondition_invalid(self):
        from axon.runtime.tools.blame import ContractMonitor, BlameLabel
        monitor = ContractMonitor()
        schema = self._make_schema()
        fault = monitor.check_precondition(schema, {})  # missing required 'query'
        assert fault is not None
        assert fault.label == BlameLabel.CALLER
        assert monitor.has_faults

    def test_postcondition_valid(self):
        from axon.runtime.tools.blame import ContractMonitor
        monitor = ContractMonitor()
        schema = self._make_schema()
        fault = monitor.check_postcondition(schema, ["result1", "result2"])
        assert fault is None

    def test_postcondition_invalid(self):
        from axon.runtime.tools.blame import ContractMonitor, BlameLabel
        monitor = ContractMonitor()
        schema = self._make_schema()
        fault = monitor.check_postcondition(schema, "not_a_list")  # wrong type
        assert fault is not None
        assert fault.label == BlameLabel.SERVER

    def test_epistemic_downgrade(self):
        from axon.runtime.tools.blame import ContractMonitor
        monitor = ContractMonitor()
        result = {"data": "test"}
        result = monitor.apply_epistemic_downgrade(result)
        assert result["_tainted"] is True
        assert result["_epistemic_level"] == "believe"
        assert result["_ffi_boundary"] is True

    def test_summary(self):
        from axon.runtime.tools.blame import ContractMonitor
        monitor = ContractMonitor()
        schema = self._make_schema()
        monitor.check_precondition(schema, {"query": "ok"})
        summary = monitor.summary()
        assert summary["total_invocations"] == 1
        assert summary["verdict"] == "clean"


class TestContractTool:
    """Tests for the @contract_tool decorator."""

    def test_basic_decoration(self):
        from axon.runtime.tools.contract_tool import contract_tool

        @contract_tool(name="Add", description="Add numbers", epistemic="know", effects=("pure",))
        async def add(a: int, b: int) -> int:
            return a + b

        assert add.tool_name == "Add"
        assert add.epistemic_level == "know"
        assert add.effect_row == ("pure",)
        assert add.schema.name == "Add"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        from axon.runtime.tools.contract_tool import contract_tool

        @contract_tool(name="Multiply")
        async def multiply(x: int, y: int) -> int:
            return x * y

        result = await multiply.execute(x=3, y=4)
        assert result.success
        assert result.data == 12
        assert result.tainted is True  # FFI boundary
        assert result.epistemic_mode == "believe"  # default

    @pytest.mark.asyncio
    async def test_execute_with_exception(self):
        from axon.runtime.tools.contract_tool import contract_tool

        @contract_tool(name="Fail")
        async def fail_tool(x: int) -> int:
            raise ValueError("boom")

        result = await fail_tool.execute(x=1)
        assert not result.success
        assert "boom" in result.error

    def test_repr(self):
        from axon.runtime.tools.contract_tool import contract_tool

        @contract_tool(name="Demo", effects=("io", "network"))
        async def demo(q: str) -> str:
            return q

        r = repr(demo)
        assert "@contract_tool" in r
        assert "Demo" in r
        assert "io" in r


# ═══════════════════════════════════════════════════════════════════
#  FEATURE 4: @csp_tool & EPISTEMIC INFERENCE
# ═══════════════════════════════════════════════════════════════════

class TestEpistemicInference:
    """Tests for automatic epistemic level inference."""

    def test_infer_pure_function(self):
        from axon.runtime.tools.epistemic_inference import infer_epistemic_level

        def compute_sum(a: int, b: int) -> int:
            return a + b

        assert infer_epistemic_level(compute_sum) == "know"

    def test_infer_network_function(self):
        from axon.runtime.tools.epistemic_inference import infer_epistemic_level

        async def fetch_url(url: str) -> str:
            return ""

        assert infer_epistemic_level(fetch_url) == "speculate"

    def test_infer_random_function(self):
        from axon.runtime.tools.epistemic_inference import infer_epistemic_level

        def generate_random_text(seed: int, temperature: float) -> str:
            return ""

        assert infer_epistemic_level(generate_random_text) == "doubt"

    def test_infer_async_default(self):
        from axon.runtime.tools.epistemic_inference import infer_epistemic_level

        async def process_data(data: dict) -> dict:
            return data

        assert infer_epistemic_level(process_data) == "believe"


class TestEffectRowInference:
    """Tests for automatic effect row inference."""

    def test_infer_pure_effects(self):
        from axon.runtime.tools.epistemic_inference import infer_effect_row

        def calculate(x: int) -> int:
            return x

        effects = infer_effect_row(calculate)
        assert "pure" in effects

    def test_infer_network_effects(self):
        from axon.runtime.tools.epistemic_inference import infer_effect_row

        async def fetch_url(url: str) -> str:
            return ""

        effects = infer_effect_row(fetch_url)
        assert "io" in effects
        assert "network" in effects


class TestCspTool:
    """Tests for the @csp_tool decorator."""

    def test_bare_decorator(self):
        from axon.runtime.tools.csp_tool import csp_tool

        @csp_tool
        def compute_hash(data: str) -> str:
            """Hash some data."""
            return ""

        assert compute_hash.tool_name == "compute_hash"
        # Pure computation → should infer "know"
        assert compute_hash.epistemic_level == "know"

    def test_parameterized_decorator(self):
        from axon.runtime.tools.csp_tool import csp_tool

        @csp_tool(name="CustomSearch", description="Search things")
        async def search_api(url: str, query: str) -> list:
            return []

        assert search_api.tool_name == "CustomSearch"
        # Has 'url' param → infer "speculate"
        assert search_api.epistemic_level == "speculate"
        assert "network" in search_api.effect_row

    @pytest.mark.asyncio
    async def test_csp_tool_execution(self):
        from axon.runtime.tools.csp_tool import csp_tool

        @csp_tool
        async def transform_data(data: str) -> str:
            return data.upper()

        result = await transform_data.execute(data="hello")
        assert result.success
        assert result.data == "HELLO"
        assert result.tainted is True  # FFI boundary


# ═══════════════════════════════════════════════════════════════════
#  BASE TOOL EXTENSIONS
# ═══════════════════════════════════════════════════════════════════

class TestBaseToolEffectExtensions:
    """Tests for the effect row extensions on BaseTool."""

    def test_typed_result_taint_field(self):
        from axon.runtime.tools.base_tool import TypedToolResult
        result = TypedToolResult(success=True, data="test", tainted=True, epistemic_source="speculate")
        assert result.tainted is True
        assert result.epistemic_source == "speculate"

    def test_base_tool_effect_row_classvar(self):
        from axon.runtime.tools.base_tool import BaseTool
        assert hasattr(BaseTool, "EFFECT_ROW")
        assert hasattr(BaseTool, "EPISTEMIC_LEVEL")
        assert BaseTool.EPISTEMIC_LEVEL == "believe"
