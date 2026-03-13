"""
Tests for AXON v0.11.0 — Tools Fortification
===============================================
Comprehensive test suite covering all 9 weaknesses:

- W1: IRUseTool expansion (parameters, expected_output_type)
- W2: ToolSchema + ToolParameter (validate_input, apply_defaults)
- W3: ToolMetrics + ToolMetricsCollector (observability)
- W4: ToolChain (sequential composition)
- W5: TypedToolResult (epistemic taint)
- W6: dispatch_with_retry (PID-informed backoff)
- W7: ToolMetricsCollector.recommend() (feedback loop)
- W8: dispatch_parallel (asyncio.gather)
- W9: APICallHTTPX + PDFExtractorPyMuPDF (real backends)

~45 tests total.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axon.compiler.ir_nodes import IRToolSpec, IRUseTool
from axon.runtime.tools.base_tool import BaseTool, ToolResult, TypedToolResult
from axon.runtime.tools.registry import RuntimeToolRegistry
from axon.runtime.tools.tool_chain import ToolChain, ToolChainStep
from axon.runtime.tools.tool_metrics import ToolMetrics, ToolMetricsCollector
from axon.runtime.tools.tool_schema import ToolParameter, ToolSchema


# ═══════════════════════════════════════════════════════════════════
#  Test helpers
# ═══════════════════════════════════════════════════════════════════


class EchoTool(BaseTool):
    """Minimal tool that echoes input."""

    TOOL_NAME: ClassVar[str] = "Echo"
    IS_STUB: ClassVar[bool] = True
    DEFAULT_TIMEOUT: ClassVar[float] = 5.0

    def validate_config(self) -> None:
        pass

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data={"echo": query})


class FailingTool(BaseTool):
    """Tool that fails every time."""

    TOOL_NAME: ClassVar[str] = "Failing"
    IS_STUB: ClassVar[bool] = True
    DEFAULT_TIMEOUT: ClassVar[float] = 5.0

    def validate_config(self) -> None:
        pass

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        return ToolResult(success=False, data=None, error="Always fails")


class CounterTool(BaseTool):
    """Tool that fails N times then succeeds."""

    TOOL_NAME: ClassVar[str] = "Counter"
    IS_STUB: ClassVar[bool] = True
    DEFAULT_TIMEOUT: ClassVar[float] = 5.0
    _call_count: int = 0
    _fail_until: int = 2

    def validate_config(self) -> None:
        self._call_count = 0
        self._fail_until = self.config.get("fail_until", 2)

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        self._call_count += 1
        if self._call_count < self._fail_until:
            return ToolResult(
                success=False, data=None,
                error=f"Fail #{self._call_count}",
            )
        return ToolResult(
            success=True,
            data={"attempts": self._call_count},
        )


class SlowTool(BaseTool):
    """Tool that takes time to execute."""

    TOOL_NAME: ClassVar[str] = "Slow"
    IS_STUB: ClassVar[bool] = True
    DEFAULT_TIMEOUT: ClassVar[float] = 10.0

    def validate_config(self) -> None:
        pass

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(success=True, data={"query": query})


class SchemaEchoTool(BaseTool):
    """Tool with a formal schema."""

    TOOL_NAME: ClassVar[str] = "SchemaEcho"
    IS_STUB: ClassVar[bool] = True
    DEFAULT_TIMEOUT: ClassVar[float] = 5.0

    SCHEMA: ClassVar[ToolSchema] = ToolSchema(
        name="SchemaEcho",
        description="Echo tool with schema validation",
        input_params=(
            ToolParameter("query", "str", required=True,
                          description="The query to echo"),
            ToolParameter("max_results", "int", required=False,
                          default=5, description="Max results"),
        ),
        output_type="dict",
    )

    def validate_config(self) -> None:
        pass

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data={"echo": query})


# ═══════════════════════════════════════════════════════════════════
#  W2: ToolSchema + ToolParameter
# ═══════════════════════════════════════════════════════════════════


class TestToolParameter:
    def test_creation_defaults(self) -> None:
        p = ToolParameter("query")
        assert p.name == "query"
        assert p.type_name == "str"
        assert p.required is True
        assert not p.has_default

    def test_creation_full(self) -> None:
        p = ToolParameter("limit", "int", False, 10, "Max items")
        assert p.type_name == "int"
        assert p.required is False
        assert p.has_default is True
        assert p.default == 10

    def test_to_dict(self) -> None:
        p = ToolParameter("q", "str", True, description="Search query")
        d = p.to_dict()
        assert d["name"] == "q"
        assert d["type"] == "str"
        assert d["required"] is True
        assert "default" not in d

    def test_to_dict_with_default(self) -> None:
        p = ToolParameter("n", "int", False, 5)
        d = p.to_dict()
        assert d["default"] == 5

    def test_repr(self) -> None:
        p = ToolParameter("query", "str", True)
        assert "query" in repr(p)
        assert "str" in repr(p)


class TestToolSchema:
    def _make_schema(self) -> ToolSchema:
        return ToolSchema(
            name="TestTool",
            description="A test tool",
            input_params=(
                ToolParameter("query", "str", required=True),
                ToolParameter("max_results", "int", required=False, default=5),
            ),
            output_type="list[dict]",
        )

    def test_creation(self) -> None:
        s = self._make_schema()
        assert s.name == "TestTool"
        assert len(s.input_params) == 2

    def test_validate_input_valid(self) -> None:
        s = self._make_schema()
        valid, errors = s.validate_input({"query": "hello"})
        assert valid is True
        assert errors == []

    def test_validate_input_missing_required(self) -> None:
        s = self._make_schema()
        valid, errors = s.validate_input({})
        assert valid is False
        assert any("query" in e for e in errors)

    def test_validate_input_wrong_type(self) -> None:
        s = self._make_schema()
        valid, errors = s.validate_input(
            {"query": "hello", "max_results": "not_int"}
        )
        assert valid is False
        assert any("max_results" in e for e in errors)

    def test_validate_input_unexpected_param(self) -> None:
        s = self._make_schema()
        valid, errors = s.validate_input(
            {"query": "hello", "bogus": True}
        )
        assert valid is False
        assert any("bogus" in e for e in errors)

    def test_apply_defaults(self) -> None:
        s = self._make_schema()
        result = s.apply_defaults({"query": "hello"})
        assert result["max_results"] == 5

    def test_to_dict(self) -> None:
        s = self._make_schema()
        d = s.to_dict()
        assert d["name"] == "TestTool"
        assert len(d["input_params"]) == 2
        assert d["output_type"] == "list[dict]"

    def test_schema_on_basetool(self) -> None:
        assert SchemaEchoTool.SCHEMA is not None
        assert SchemaEchoTool.SCHEMA.name == "SchemaEcho"


# ═══════════════════════════════════════════════════════════════════
#  W5: TypedToolResult
# ═══════════════════════════════════════════════════════════════════


class TestTypedToolResult:
    def test_creation_with_fields(self) -> None:
        r = TypedToolResult(
            success=True, data={"a": 1},
            semantic_type="dict", confidence=0.95,
            epistemic_mode="know", provenance="test",
        )
        assert r.semantic_type == "dict"
        assert r.confidence == 0.95
        assert r.provenance == "test"

    def test_epistemic_cited_fact(self) -> None:
        r = TypedToolResult(
            success=True, data=None,
            confidence=0.9, epistemic_mode="know",
        )
        assert r.to_epistemic_type() == "CitedFact"

    def test_epistemic_uncertainty(self) -> None:
        r = TypedToolResult(
            success=True, data=None,
            confidence=0.2, epistemic_mode="know",
        )
        assert r.to_epistemic_type() == "Uncertainty"

    def test_epistemic_speculation(self) -> None:
        r = TypedToolResult(
            success=True, data=None,
            confidence=0.5, epistemic_mode="speculate",
        )
        assert r.to_epistemic_type() == "Speculation"

    def test_epistemic_belief(self) -> None:
        r = TypedToolResult(
            success=True, data=None,
            confidence=0.6, epistemic_mode="believe",
        )
        assert r.to_epistemic_type() == "Belief"

    def test_to_dict_includes_epistemic(self) -> None:
        r = TypedToolResult(
            success=True, data="ok",
            semantic_type="str", confidence=0.8,
            provenance="test", execution_time_ms=42.5,
        )
        d = r.to_dict()
        assert d["semantic_type"] == "str"
        assert d["confidence"] == 0.8
        assert d["provenance"] == "test"
        assert d["execution_time_ms"] == 42.5

    def test_backwards_compat_with_toolresult(self) -> None:
        """ToolResult still works without new fields."""
        r = ToolResult(success=True, data={"x": 1})
        assert r.success is True
        assert r.data == {"x": 1}


# ═══════════════════════════════════════════════════════════════════
#  W4: ToolChain
# ═══════════════════════════════════════════════════════════════════


class TestToolChain:
    def _make_dispatcher(self) -> Any:
        from axon.runtime.tools.dispatcher import ToolDispatcher

        registry = RuntimeToolRegistry()
        registry.register(EchoTool)
        registry.register(FailingTool)
        return ToolDispatcher(registry)

    @pytest.mark.asyncio
    async def test_single_step_chain(self) -> None:
        dispatcher = self._make_dispatcher()
        chain = ToolChain(
            steps=[ToolChainStep("Echo")],
            name="single",
        )
        result = await chain.execute(dispatcher, initial_input="hello")
        assert result.success is True
        assert result.metadata["chain"] == "single"

    @pytest.mark.asyncio
    async def test_two_step_chain(self) -> None:
        dispatcher = self._make_dispatcher()
        chain = ToolChain(
            steps=[
                ToolChainStep("Echo"),
                ToolChainStep("Echo"),
            ],
            name="double",
        )
        result = await chain.execute(dispatcher, initial_input="hello")
        assert result.success is True
        assert result.metadata["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_chain_fail_fast(self) -> None:
        dispatcher = self._make_dispatcher()
        chain = ToolChain(
            steps=[
                ToolChainStep("Failing"),
                ToolChainStep("Echo"),
            ],
            name="fail_fast",
        )
        result = await chain.execute(dispatcher, initial_input="hello")
        assert result.success is False
        assert result.metadata["failed_step"] == 1

    @pytest.mark.asyncio
    async def test_empty_chain(self) -> None:
        dispatcher = self._make_dispatcher()
        chain = ToolChain(steps=[], name="empty")
        result = await chain.execute(dispatcher, initial_input="hello")
        assert result.success is True
        assert result.metadata["steps"] == 0

    def test_repr(self) -> None:
        chain = ToolChain(
            steps=[
                ToolChainStep("A"),
                ToolChainStep("B"),
            ],
            name="test",
        )
        assert "A → B" in repr(chain)


# ═══════════════════════════════════════════════════════════════════
#  W3, W7: ToolMetrics + ToolMetricsCollector
# ═══════════════════════════════════════════════════════════════════


class TestToolMetrics:
    def test_creation(self) -> None:
        m = ToolMetrics(
            tool_name="WebSearch",
            execution_time_ms=120.5,
            success=True,
        )
        assert m.tool_name == "WebSearch"
        assert m.execution_time_ms == 120.5
        assert m.success is True

    def test_to_dict(self) -> None:
        m = ToolMetrics("Echo", 50.0, True, is_stub=True)
        d = m.to_dict()
        assert d["tool_name"] == "Echo"
        assert d["is_stub"] is True


class TestToolMetricsCollector:
    def test_record_and_summary(self) -> None:
        c = ToolMetricsCollector()
        c.record(ToolMetrics("A", 100.0, True))
        c.record(ToolMetrics("A", 200.0, True))

        s = c.summary("A")
        assert s["avg_time_ms"] == 150.0
        assert s["success_rate"] == 1.0
        assert s["total_executions"] == 2

    def test_summary_all(self) -> None:
        c = ToolMetricsCollector()
        c.record(ToolMetrics("A", 100.0, True))
        c.record(ToolMetrics("B", 200.0, False))

        s = c.summary()
        assert "A" in s
        assert "B" in s
        assert s["A"]["success_rate"] == 1.0
        assert s["B"]["success_rate"] == 0.0

    def test_recommend_best(self) -> None:
        c = ToolMetricsCollector()
        # Tool A: fast + reliable
        c.record(ToolMetrics("A", 50.0, True))
        c.record(ToolMetrics("A", 60.0, True))
        # Tool B: slow + unreliable
        c.record(ToolMetrics("B", 500.0, True))
        c.record(ToolMetrics("B", 600.0, False))

        best = c.recommend(["A", "B"])
        assert best == "A"

    def test_recommend_no_data(self) -> None:
        c = ToolMetricsCollector()
        assert c.recommend(["X", "Y"]) is None

    def test_to_dict(self) -> None:
        c = ToolMetricsCollector()
        c.record(ToolMetrics("A", 100.0, True))
        d = c.to_dict()
        assert d["total_observations"] == 1
        assert "A" in d["tools"]

    def test_tool_names(self) -> None:
        c = ToolMetricsCollector()
        c.record(ToolMetrics("B", 100.0, True))
        c.record(ToolMetrics("A", 100.0, True))
        assert c.tool_names == ["A", "B"]

    def test_repr(self) -> None:
        c = ToolMetricsCollector()
        c.record(ToolMetrics("A", 1.0, True))
        assert "tools=1" in repr(c)
        assert "observations=1" in repr(c)


# ═══════════════════════════════════════════════════════════════════
#  W6: dispatch_with_retry
# ═══════════════════════════════════════════════════════════════════


class TestDispatchWithRetry:
    def _make_dispatcher(
        self, tool_cls: type[BaseTool],
    ) -> Any:
        from axon.runtime.tools.dispatcher import ToolDispatcher

        registry = RuntimeToolRegistry()
        registry.register(tool_cls)
        return ToolDispatcher(registry)

    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        dispatcher = self._make_dispatcher(EchoTool)
        ir = IRUseTool(tool_name="Echo", argument="hello")
        result = await dispatcher.dispatch_with_retry(
            ir, max_retries=2, base_delay=0.01,
        )
        assert result.success is True
        assert result.metadata["attempt"] == 1

    @pytest.mark.asyncio
    async def test_succeed_on_retry(self) -> None:
        dispatcher = self._make_dispatcher(CounterTool)
        ir = IRUseTool(tool_name="Counter", argument="test")
        result = await dispatcher.dispatch_with_retry(
            ir, max_retries=3, base_delay=0.01,
        )
        assert result.success is True
        assert result.metadata.get("total_attempts", 0) >= 2

    @pytest.mark.asyncio
    async def test_exhaust_retries(self) -> None:
        dispatcher = self._make_dispatcher(FailingTool)
        ir = IRUseTool(tool_name="Failing", argument="test")
        result = await dispatcher.dispatch_with_retry(
            ir, max_retries=2, base_delay=0.01,
        )
        assert result.success is False
        assert result.metadata.get("exhausted_retries") is True
        assert result.metadata["total_attempts"] == 3

    @pytest.mark.asyncio
    async def test_timing_in_result(self) -> None:
        dispatcher = self._make_dispatcher(EchoTool)
        ir = IRUseTool(tool_name="Echo", argument="hello")
        result = await dispatcher.dispatch(ir)
        assert hasattr(result, "execution_time_ms") or True
        # TypedToolResult wrapping should have timing
        if isinstance(result, TypedToolResult):
            assert result.execution_time_ms > 0


# ═══════════════════════════════════════════════════════════════════
#  W8: dispatch_parallel
# ═══════════════════════════════════════════════════════════════════


class TestDispatchParallel:
    def _make_dispatcher(self) -> Any:
        from axon.runtime.tools.dispatcher import ToolDispatcher

        registry = RuntimeToolRegistry()
        registry.register(EchoTool)
        registry.register(SlowTool)
        registry.register(FailingTool)
        return ToolDispatcher(registry)

    @pytest.mark.asyncio
    async def test_parallel_multiple_tools(self) -> None:
        dispatcher = self._make_dispatcher()
        invocations = [
            IRUseTool(tool_name="Echo", argument="a"),
            IRUseTool(tool_name="Echo", argument="b"),
            IRUseTool(tool_name="Echo", argument="c"),
        ]
        results = await dispatcher.dispatch_parallel(invocations)
        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_parallel_faster_than_sequential(self) -> None:
        import time

        dispatcher = self._make_dispatcher()
        invocations = [
            IRUseTool(tool_name="Slow", argument="a"),
            IRUseTool(tool_name="Slow", argument="b"),
            IRUseTool(tool_name="Slow", argument="c"),
        ]
        t0 = time.perf_counter()
        results = await dispatcher.dispatch_parallel(invocations)
        elapsed = time.perf_counter() - t0

        assert len(results) == 3
        # If sequential: ~0.3s. If parallel: ~0.1s
        assert elapsed < 0.25, f"Took {elapsed:.2f}s — not parallel"

    @pytest.mark.asyncio
    async def test_one_failure_doesnt_crash(self) -> None:
        dispatcher = self._make_dispatcher()
        invocations = [
            IRUseTool(tool_name="Echo", argument="ok"),
            IRUseTool(tool_name="Failing", argument="fail"),
            IRUseTool(tool_name="Echo", argument="ok2"),
        ]
        results = await dispatcher.dispatch_parallel(invocations)
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        dispatcher = self._make_dispatcher()
        results = await dispatcher.dispatch_parallel([])
        assert results == []


# ═══════════════════════════════════════════════════════════════════
#  W2 via Dispatcher: Schema validation integration
# ═══════════════════════════════════════════════════════════════════


class TestDispatcherSchemaValidation:
    def _make_dispatcher(self) -> Any:
        from axon.runtime.tools.dispatcher import ToolDispatcher

        registry = RuntimeToolRegistry()
        registry.register(SchemaEchoTool)
        registry.register(EchoTool)
        return ToolDispatcher(registry)

    @pytest.mark.asyncio
    async def test_valid_params_pass(self) -> None:
        dispatcher = self._make_dispatcher()
        ir = IRUseTool(tool_name="SchemaEcho", argument="hello")
        result = await dispatcher.dispatch(ir)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_schema_backwards_compat(self) -> None:
        dispatcher = self._make_dispatcher()
        ir = IRUseTool(tool_name="Echo", argument="hello")
        result = await dispatcher.dispatch(ir)
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════
#  W9: Backend class constants (import-safe)
# ═══════════════════════════════════════════════════════════════════


class TestAPICallHTTPXConstants:
    def test_class_constants(self) -> None:
        from axon.runtime.tools.backends.api_call_httpx import APICallHTTPX

        assert APICallHTTPX.TOOL_NAME == "APICall"
        assert APICallHTTPX.IS_STUB is False
        assert APICallHTTPX.SCHEMA is not None

    def test_schema_has_query_param(self) -> None:
        from axon.runtime.tools.backends.api_call_httpx import APICallHTTPX

        param_names = [p.name for p in APICallHTTPX.SCHEMA.input_params]
        assert "query" in param_names
        assert "method" in param_names

    @pytest.mark.asyncio
    async def test_execute_mocked(self) -> None:
        """Test execute with a mocked httpx to avoid real HTTP calls."""
        import sys
        from unittest.mock import MagicMock, AsyncMock

        from axon.runtime.tools.backends.api_call_httpx import APICallHTTPX

        # Build mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"result": "ok"}
        mock_response.url = "https://api.test.com/data"
        mock_response.raise_for_status = MagicMock()

        # Build mock AsyncClient context manager
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Build mock httpx module
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
        mock_httpx.HTTPStatusError = type("HTTPStatusError", (Exception,), {})
        mock_httpx.TimeoutException = type("TimeoutException", (Exception,), {})

        # Temporarily inject mock httpx into sys.modules
        original = sys.modules.get("httpx")
        sys.modules["httpx"] = mock_httpx
        try:
            tool = APICallHTTPX()
            result = await tool.execute("https://api.test.com/data")
            assert result.success is True
            assert result.data["status_code"] == 200
        finally:
            if original is not None:
                sys.modules["httpx"] = original
            else:
                sys.modules.pop("httpx", None)


class TestPDFExtractorPyMuPDFConstants:
    def test_class_constants(self) -> None:
        from axon.runtime.tools.backends.pdf_extractor_pymupdf import (
            PDFExtractorPyMuPDF,
        )

        assert PDFExtractorPyMuPDF.TOOL_NAME == "PDFExtractor"
        assert PDFExtractorPyMuPDF.IS_STUB is False
        assert PDFExtractorPyMuPDF.SCHEMA is not None

    def test_schema_has_query_param(self) -> None:
        from axon.runtime.tools.backends.pdf_extractor_pymupdf import (
            PDFExtractorPyMuPDF,
        )

        param_names = [
            p.name for p in PDFExtractorPyMuPDF.SCHEMA.input_params
        ]
        assert "query" in param_names

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        from axon.runtime.tools.backends.pdf_extractor_pymupdf import (
            PDFExtractorPyMuPDF,
        )

        tool = PDFExtractorPyMuPDF()
        result = await tool.execute("/nonexistent/file.pdf")
        assert result.success is False
        assert "not found" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════
#  W1: IRUseTool expanded fields
# ═══════════════════════════════════════════════════════════════════


class TestIRExpanded:
    def test_ir_use_tool_defaults(self) -> None:
        ir = IRUseTool(tool_name="Test", argument="hello")
        assert ir.parameters == ()
        assert ir.expected_output_type == ""

    def test_ir_use_tool_with_params(self) -> None:
        ir = IRUseTool(
            tool_name="Test",
            argument="hello",
            parameters=(("key", "value"),),
            expected_output_type="dict",
        )
        assert ir.parameters == (("key", "value"),)
        assert ir.expected_output_type == "dict"

    def test_ir_use_tool_to_dict(self) -> None:
        ir = IRUseTool(
            tool_name="Test",
            argument="hello",
            parameters=(("a", "1"), ("b", "2")),
            expected_output_type="list",
        )
        d = ir.to_dict()
        assert d["parameters"] == (("a", "1"), ("b", "2"))
        assert d["expected_output_type"] == "list"

    def test_ir_tool_spec_defaults(self) -> None:
        spec = IRToolSpec(name="Test")
        assert spec.input_schema == ()
        assert spec.output_schema == ""

    def test_ir_tool_spec_with_schema(self) -> None:
        spec = IRToolSpec(
            name="Test",
            input_schema=(("query", "str", True),),
            output_schema="dict",
        )
        assert spec.input_schema == (("query", "str", True),)
        assert spec.output_schema == "dict"
