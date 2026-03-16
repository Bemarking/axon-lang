"""
AXON Integration Tests — P0 Feature Wiring (v0.14.0)
=====================================================
Tests that the P0 core modules (streaming, blame, contract_tool, csp_tool)
are correctly wired into the existing pipeline (dispatcher, registry,
tool_schema).

These tests verify the end-to-end integration, not the individual modules
(which are tested in test_streaming_effects.py).
"""

from __future__ import annotations

import asyncio
import pytest
from typing import Any

# ── Registry integration ────────────────────────────────────────

from axon.runtime.tools.registry import RuntimeToolRegistry
from axon.runtime.tools.base_tool import BaseTool, ToolResult, TypedToolResult
from axon.runtime.tools.tool_schema import ToolSchema, ToolParameter
from axon.runtime.tools.contract_tool import contract_tool
from axon.runtime.tools.csp_tool import csp_tool
from axon.runtime.tools.blame import BlameLabel, ContractMonitor


# ═══════════════════════════════════════════════════════════════════
#  1. Registry — decorator tool registration
# ═══════════════════════════════════════════════════════════════════

class TestRegistryDecoratorTools:
    """Test RuntimeToolRegistry.register_decorator_tool()."""

    def test_register_contract_tool(self) -> None:
        """@contract_tool wraps can be registered and retrieved."""
        @contract_tool(epistemic="speculate", effects=("io", "network"))
        def fetch_data(url: str) -> dict:
            """Fetch data from a URL."""
            return {"url": url}

        registry = RuntimeToolRegistry()
        registry.register_decorator_tool(fetch_data)

        wrapper = registry.get_decorator_tool("fetch_data")
        assert wrapper.tool_name == "fetch_data"
        assert wrapper.epistemic_level == "speculate"
        assert wrapper.effect_row == ("io", "network")

    def test_register_csp_tool(self) -> None:
        """@csp_tool wraps can be registered."""
        @csp_tool
        def compute_sum(a: int, b: int) -> int:
            """Compute the sum of two numbers."""
            return a + b

        registry = RuntimeToolRegistry()
        registry.register_decorator_tool(compute_sum)

        wrapper = registry.get_decorator_tool("compute_sum")
        assert wrapper.tool_name == "compute_sum"

    def test_decorator_tool_not_found(self) -> None:
        """KeyError when decorator tool doesn't exist."""
        registry = RuntimeToolRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get_decorator_tool("nonexistent")

    def test_decorator_tool_no_name(self) -> None:
        """ValueError when wrapper has no tool_name."""
        registry = RuntimeToolRegistry()

        class FakeWrapper:
            tool_name = ""

        with pytest.raises(ValueError, match="no tool_name"):
            registry.register_decorator_tool(FakeWrapper())

    def test_list_epistemic_tools(self) -> None:
        """list_epistemic_tools includes both BaseTool and decorator tools."""

        class PureTool(BaseTool):
            TOOL_NAME = "PureMath"
            EPISTEMIC_LEVEL = "know"
            async def execute(self, query: str, **kwargs: Any) -> ToolResult:
                return ToolResult(success=True, data=42)

        @contract_tool(epistemic="doubt")
        def llm_call(prompt: str) -> str:
            return "response"

        registry = RuntimeToolRegistry()
        registry.register(PureTool)
        registry.register_decorator_tool(llm_call)

        levels = registry.list_epistemic_tools()
        assert levels["PureMath"] == "know"
        assert levels["llm_call"] == "doubt"

    def test_repr_includes_decorators(self) -> None:
        """Registry repr shows decorator tool count."""
        @csp_tool
        def some_tool(x: int) -> int:
            return x

        registry = RuntimeToolRegistry()
        registry.register_decorator_tool(some_tool)

        assert "decorators=1" in repr(registry)


# ═══════════════════════════════════════════════════════════════════
#  2. ToolSchema — effect_row and validate_output
# ═══════════════════════════════════════════════════════════════════

class TestToolSchemaExtensions:
    """Test v0.14.0 ToolSchema extensions."""

    def test_effect_row_field(self) -> None:
        """ToolSchema accepts and stores effect_row."""
        schema = ToolSchema(
            name="WebSearch",
            effect_row=("io", "network"),
            epistemic_level="speculate",
        )
        assert schema.effect_row == ("io", "network")
        assert schema.epistemic_level == "speculate"

    def test_effect_row_in_dict(self) -> None:
        """to_dict() includes effect_row and epistemic_level."""
        schema = ToolSchema(
            name="Calculator",
            effect_row=("pure",),
            epistemic_level="know",
        )
        d = schema.to_dict()
        assert d["effect_row"] == ["pure"]
        assert d["epistemic_level"] == "know"

    def test_empty_effect_row_not_in_dict(self) -> None:
        """to_dict() omits effect_row when empty."""
        schema = ToolSchema(name="Basic")
        d = schema.to_dict()
        assert "effect_row" not in d
        assert "epistemic_level" not in d

    def test_validate_output_success(self) -> None:
        """validate_output passes for correct types."""
        schema = ToolSchema(name="T", output_type="str")
        valid, errors = schema.validate_output("hello")
        assert valid
        assert not errors

    def test_validate_output_failure(self) -> None:
        """validate_output fails for wrong types."""
        schema = ToolSchema(name="T", output_type="int")
        valid, errors = schema.validate_output("not_an_int")
        assert not valid
        assert "int" in errors[0]

    def test_validate_output_any(self) -> None:
        """validate_output always passes for 'Any' type."""
        schema = ToolSchema(name="T", output_type="Any")
        valid, errors = schema.validate_output(42)
        assert valid

    def test_validate_output_list_type(self) -> None:
        """validate_output works with parameterized types."""
        schema = ToolSchema(name="T", output_type="list[str]")
        valid, _ = schema.validate_output(["a", "b"])
        assert valid
        valid2, errors2 = schema.validate_output("not a list")
        assert not valid2


# ═══════════════════════════════════════════════════════════════════
#  3. Dispatcher — epistemic downgrade and handler_mode
# ═══════════════════════════════════════════════════════════════════

class TestDispatcherIntegration:
    """Test ToolDispatcher v0.14.0 integration features."""

    def _make_dispatcher(
        self, handler_mode: str = "direct"
    ) -> tuple:
        """Create a dispatcher with a simple stub tool."""
        from axon.runtime.tools.dispatcher import ToolDispatcher
        from axon.compiler.ir_nodes import IRUseTool

        class SimpleTool(BaseTool):
            TOOL_NAME = "SimpleTool"
            EPISTEMIC_LEVEL = "speculate"
            EFFECT_ROW = ("io",)

            def validate_config(self) -> list[str]:
                return []

            async def execute(self, query: str, **kwargs: Any) -> ToolResult:
                return ToolResult(
                    success=True,
                    data={"result": query.upper()},
                )

        registry = RuntimeToolRegistry()
        registry.register(SimpleTool)
        dispatcher = ToolDispatcher(
            registry, handler_mode=handler_mode
        )

        ir_node = IRUseTool(
            tool_name="SimpleTool",
            argument="hello",
        )
        return dispatcher, ir_node

    @pytest.mark.asyncio
    async def test_dispatch_epistemic_downgrade(self) -> None:
        """All dispatched results get tainted=True + epistemic_source."""
        dispatcher, ir_node = self._make_dispatcher()
        result = await dispatcher.dispatch(ir_node)

        assert result.success
        assert isinstance(result, TypedToolResult)
        assert result.tainted is True
        assert result.epistemic_source == "speculate"

    @pytest.mark.asyncio
    async def test_dispatch_handler_mode_direct(self) -> None:
        """handler_mode='direct' executes the tool normally."""
        dispatcher, ir_node = self._make_dispatcher("direct")
        result = await dispatcher.dispatch(ir_node)
        assert result.success
        assert result.data == {"result": "HELLO"}

    @pytest.mark.asyncio
    async def test_dispatch_has_contract_monitor(self) -> None:
        """Dispatcher creates a ContractMonitor."""
        dispatcher, _ = self._make_dispatcher()
        assert hasattr(dispatcher, "_contract_monitor")
        assert isinstance(dispatcher._contract_monitor, ContractMonitor)


# ═══════════════════════════════════════════════════════════════════
#  4. Package exports — __init__.py
# ═══════════════════════════════════════════════════════════════════

class TestPackageExports:
    """Test that v0.14.0 types are exportable from the tools package."""

    def test_import_blame_label(self) -> None:
        from axon.runtime.tools import BlameLabel
        assert BlameLabel.CALLER.value == "caller"

    def test_import_contract_monitor(self) -> None:
        from axon.runtime.tools import ContractMonitor
        assert ContractMonitor is not None

    def test_import_contract_tool_decorator(self) -> None:
        from axon.runtime.tools import contract_tool
        assert callable(contract_tool)

    def test_import_csp_tool_decorator(self) -> None:
        from axon.runtime.tools import csp_tool
        assert callable(csp_tool)

    def test_all_exports(self) -> None:
        from axon.runtime.tools import __all__
        assert "BlameLabel" in __all__
        assert "ContractMonitor" in __all__
        assert "contract_tool" in __all__
        assert "csp_tool" in __all__


# ═══════════════════════════════════════════════════════════════════
#  5. End-to-end: @contract_tool → Registry → Dispatch
# ═══════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """Full integration test: decorator → registry → execution."""

    def test_contract_tool_execution(self) -> None:
        """A @contract_tool function can be called and obeys contracts."""
        @contract_tool(epistemic="believe", effects=("io",))
        def weather(city: str) -> str:
            """Get weather for a city."""
            return f"Sunny in {city}"

        # Direct execution
        result = weather("London")
        assert result == "Sunny in {city}" or "London" in result

        # Schema introspection
        assert weather.tool_name == "weather"
        assert weather.epistemic_level == "believe"
        assert weather.effect_row == ("io",)
        assert weather.schema is not None

    def test_csp_tool_auto_inference(self) -> None:
        """A @csp_tool auto-infers epistemic level and effects."""
        @csp_tool
        def compute_area(width: float, height: float) -> float:
            """Compute area of a rectangle."""
            return width * height

        # Inferred epistemic level should be 'know' (pure computation)
        assert compute_area.epistemic_level == "know"
        assert "pure" in compute_area.effect_row

        # Direct execution still works
        result = compute_area(3.0, 4.0)
        assert result == 12.0

    def test_contract_tool_with_registry(self) -> None:
        """Contract tool can be registered and introspected."""
        @contract_tool(epistemic="doubt", effects=("io",))
        def model_predict(prompt: str) -> str:
            return "prediction"

        registry = RuntimeToolRegistry()
        registry.register_decorator_tool(model_predict)

        # Introspection
        levels = registry.list_epistemic_tools()
        assert levels["model_predict"] == "doubt"

        # Retrieval
        wrapper = registry.get_decorator_tool("model_predict")
        assert wrapper.epistemic_level == "doubt"
