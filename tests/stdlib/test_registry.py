"""
Tests for AXON Standard Library — Registry & Base
====================================================
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_nodes import IRAnchor, IRFlow, IRPersona, IRToolSpec
from axon.stdlib.base import (
    StdlibAnchor,
    StdlibEntry,
    StdlibFlow,
    StdlibPersona,
    StdlibRegistry,
    StdlibTool,
)


# ═══════════════════════════════════════════════════════════════════
#  REGISTRY BASICS
# ═══════════════════════════════════════════════════════════════════


class TestStdlibRegistry:
    """Tests for StdlibRegistry core behaviour."""

    def test_resolve_persona(self):
        """Registry resolves built-in personas to IRPersona nodes."""
        reg = StdlibRegistry()
        ir = reg.resolve("personas", "Analyst")
        assert isinstance(ir, IRPersona)
        assert ir.name == "Analyst"

    def test_resolve_anchor(self):
        """Registry resolves built-in anchors to IRAnchor nodes."""
        reg = StdlibRegistry()
        ir = reg.resolve("anchors", "NoHallucination")
        assert isinstance(ir, IRAnchor)
        assert ir.name == "NoHallucination"

    def test_resolve_flow(self):
        """Registry resolves built-in flows to IRFlow nodes."""
        reg = StdlibRegistry()
        ir = reg.resolve("flows", "Summarize")
        assert isinstance(ir, IRFlow)
        assert ir.name == "Summarize"

    def test_resolve_tool(self):
        """Registry resolves built-in tools to IRToolSpec nodes."""
        reg = StdlibRegistry()
        ir = reg.resolve("tools", "Calculator")
        assert isinstance(ir, IRToolSpec)
        assert ir.name == "Calculator"

    def test_invalid_namespace_raises(self):
        """Invalid namespace raises ValueError."""
        reg = StdlibRegistry()
        with pytest.raises(ValueError, match="Invalid namespace"):
            reg.resolve("widgets", "Foo")

    def test_unknown_name_raises(self):
        """Unknown name raises KeyError."""
        reg = StdlibRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.resolve("personas", "NonExistent")

    def test_list_names_personas(self):
        """list_names returns sorted persona names."""
        reg = StdlibRegistry()
        names = reg.list_names("personas")
        assert len(names) == 8
        assert "Analyst" in names
        assert "Coder" in names
        assert names == sorted(names)  # sorted

    def test_list_names_anchors(self):
        """list_names returns 12 anchor names."""
        reg = StdlibRegistry()
        assert len(reg.list_names("anchors")) == 12

    def test_list_names_flows(self):
        """list_names returns 8 flow names."""
        reg = StdlibRegistry()
        assert len(reg.list_names("flows")) == 8

    def test_list_names_tools(self):
        """list_names returns 8 tool names."""
        reg = StdlibRegistry()
        assert len(reg.list_names("tools")) == 8

    def test_total_count(self):
        """Total count is 36 (12 anchors + 8×3 others)."""
        reg = StdlibRegistry()
        assert reg.total_count == 36

    def test_has_positive(self):
        """has() returns True for registered components."""
        reg = StdlibRegistry()
        assert reg.has("personas", "Coder")
        assert reg.has("anchors", "SafeOutput")
        assert reg.has("flows", "FactCheck")
        assert reg.has("tools", "WebSearch")

    def test_has_negative(self):
        """has() returns False for missing components."""
        reg = StdlibRegistry()
        assert not reg.has("personas", "NonExistent")
        assert not reg.has("invalid_ns", "Anything")

    def test_resolve_entry(self):
        """resolve_entry returns the full wrapper, not just the IR node."""
        reg = StdlibRegistry()
        entry = reg.resolve_entry("personas", "Analyst")
        assert isinstance(entry, StdlibPersona)
        assert entry.description != ""
        assert entry.version == "0.1.0"

    def test_list_all(self):
        """list_all returns StdlibEntry instances."""
        reg = StdlibRegistry()
        entries = reg.list_all("anchors")
        assert len(entries) == 12
        assert all(isinstance(e, StdlibAnchor) for e in entries)

    def test_namespaces_property(self):
        """namespaces property returns the valid set."""
        reg = StdlibRegistry()
        assert reg.namespaces == frozenset(
            {"personas", "anchors", "flows", "tools"}
        )


# ═══════════════════════════════════════════════════════════════════
#  MANUAL REGISTRATION
# ═══════════════════════════════════════════════════════════════════


class TestManualRegistration:
    """Tests for manually registering entries."""

    def test_register_custom_persona(self):
        """Can register a custom persona and resolve it."""
        reg = StdlibRegistry()
        custom = StdlibPersona(
            ir=IRPersona(name="CustomBot", domain=("testing",)),
            description="A test persona.",
        )
        reg.register("personas", custom)
        resolved = reg.resolve("personas", "CustomBot")
        assert resolved.name == "CustomBot"

    def test_register_invalid_namespace(self):
        """Registering to invalid namespace raises ValueError."""
        reg = StdlibRegistry()
        custom = StdlibPersona(
            ir=IRPersona(name="Test"),
            description="test",
        )
        with pytest.raises(ValueError, match="Invalid namespace"):
            reg.register("invalid", custom)


# ═══════════════════════════════════════════════════════════════════
#  LAZY LOADING
# ═══════════════════════════════════════════════════════════════════


class TestLazyLoading:
    """Test that stdlib loads lazily on first access."""

    def test_not_loaded_before_access(self):
        """Registry is not loaded until first resolution."""
        reg = StdlibRegistry()
        assert not reg._loaded

    def test_loaded_after_access(self):
        """Registry is loaded after first resolution."""
        reg = StdlibRegistry()
        reg.resolve("personas", "Analyst")
        assert reg._loaded

    def test_loaded_after_list(self):
        """Registry is loaded after first list_names call."""
        reg = StdlibRegistry()
        reg.list_names("tools")
        assert reg._loaded

    def test_loaded_after_has(self):
        """Registry is loaded after first has() call."""
        reg = StdlibRegistry()
        reg.has("flows", "Summarize")
        assert reg._loaded
