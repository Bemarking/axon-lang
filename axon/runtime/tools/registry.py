"""
AXON Runtime — Tool Registry
==============================
Instance-based registry for runtime tool implementations.

The registry maps tool names (matching ``IRToolSpec.name``) to
``BaseTool`` subclasses.  Tool instances are cached by name+config
so repeated look-ups reuse the same object.

Key design decisions:

* **Instance-based** (not class-level) — each ``Executor`` can have
  its own registry, making tests fully isolated.
* **Replaceable** — call ``replace()`` to swap a stub for a real
  backend without touching any other code.
* **No temp-instantiation** — ``list_tools()`` reads ``IS_STUB``
  from the *class*, not from a throwaway instance.
"""

from __future__ import annotations

import logging
from typing import Any

from axon.runtime.tools.base_tool import BaseTool

# Optionally import decorator tool types for registration
try:
    from axon.runtime.tools.contract_tool import AxonToolWrapper
    _HAS_DECORATOR_TOOLS = True
except ImportError:
    _HAS_DECORATOR_TOOLS = False

logger = logging.getLogger(__name__)


class RuntimeToolRegistry:
    """Registry of available ``BaseTool`` implementations.

    Usage::

        registry = RuntimeToolRegistry()
        registry.register(WebSearchStub)
        registry.register(CalculatorTool)

        tool = registry.get("WebSearch")
        result = await tool.execute("quantum computing 2026")
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseTool]] = {}
        self._instances: dict[str, BaseTool] = {}

    # ── Registration ─────────────────────────────────────────────

    def register(self, tool_class: type[BaseTool]) -> None:
        """Register a ``BaseTool`` subclass.

        The class is stored by its ``TOOL_NAME``.  If a tool with the
        same name is already registered it is silently replaced (use
        ``replace()`` for an explicit swap with cache invalidation).

        Args:
            tool_class: A subclass of ``BaseTool`` with ``TOOL_NAME`` set.

        Raises:
            ValueError: If ``TOOL_NAME`` is empty.
        """
        name = tool_class.TOOL_NAME
        if not name:
            raise ValueError(
                f"{tool_class.__name__} has no TOOL_NAME set."
            )
        self._classes[name] = tool_class
        logger.debug("Registered tool: %s (%s)", name, tool_class.__name__)

    # ── Look-up ──────────────────────────────────────────────────

    def get(
        self,
        name: str,
        config: dict[str, Any] | None = None,
    ) -> BaseTool:
        """Get a tool instance, creating and caching it if needed.

        Args:
            name:   Tool name (must match a registered ``TOOL_NAME``).
            config: Optional config dict passed to the constructor.

        Returns:
            A cached or freshly created ``BaseTool`` instance.

        Raises:
            KeyError: If no tool is registered under *name*.
        """
        if name not in self._classes:
            available = sorted(self._classes.keys()) or ["(none)"]
            raise KeyError(
                f"Tool '{name}' not registered. "
                f"Available: {', '.join(available)}"
            )

        # Cache key includes config so different configs get different instances
        config = config or {}
        cache_key = f"{name}:{_config_hash(config)}"

        if cache_key not in self._instances:
            tool_class = self._classes[name]
            self._instances[cache_key] = tool_class(config)

        return self._instances[cache_key]

    # ── Replacement ──────────────────────────────────────────────

    def replace(self, name: str, new_class: type[BaseTool]) -> None:
        """Replace a registered tool class and clear cached instances.

        Useful for the Phase 4 → Phase 5 transition::

            registry.replace("WebSearch", WebSearchBrave)

        Args:
            name:      Tool name to replace.
            new_class: The new ``BaseTool`` subclass.

        Raises:
            KeyError: If *name* is not currently registered.
        """
        if name not in self._classes:
            raise KeyError(
                f"Cannot replace '{name}': not registered."
            )
        old_class = self._classes[name]
        self._classes[name] = new_class

        # Evict cached instances for this tool
        self._instances = {
            k: v for k, v in self._instances.items()
            if not k.startswith(f"{name}:")
        }

        logger.info(
            "Replaced tool '%s': %s → %s",
            name,
            old_class.__name__,
            new_class.__name__,
        )

    # ── Introspection ────────────────────────────────────────────

    def list_tools(self) -> dict[str, bool]:
        """Return ``{tool_name: is_stub}`` for every registered tool.

        Reads ``IS_STUB`` from the class — no instantiation needed.
        """
        return {
            name: cls.IS_STUB
            for name, cls in sorted(self._classes.items())
        }

    def has(self, name: str) -> bool:
        """Check if a tool name is registered."""
        return name in self._classes

    @property
    def tool_names(self) -> list[str]:
        """Sorted list of all registered tool names."""
        return sorted(self._classes.keys())

    @property
    def count(self) -> int:
        """Number of registered tools."""
        return len(self._classes)

    def clear(self) -> None:
        """Remove all registrations and cached instances."""
        self._classes.clear()
        self._instances.clear()

    def __repr__(self) -> str:
        stubs = sum(1 for c in self._classes.values() if c.IS_STUB)
        real = len(self._classes) - stubs
        decorators = len(self._decorator_tools) if hasattr(self, '_decorator_tools') else 0
        return (
            f"<RuntimeToolRegistry "
            f"tools={len(self._classes) + decorators} "
            f"(real={real}, stubs={stubs}, decorators={decorators})>"
        )

    # ── Decorator tool registration (v0.14.0 — CT-3/CT-4) ────

    def register_decorator_tool(self, wrapper: Any) -> None:
        """Register a tool created via ``@contract_tool`` or ``@csp_tool``.

        These tools have a different interface from ``BaseTool`` subclasses:
        they are ``AxonToolWrapper`` instances, not class-based.

        Args:
            wrapper: An ``AxonToolWrapper`` from ``@contract_tool`` or ``@csp_tool``.

        Raises:
            ValueError: If the wrapper has no ``tool_name``.
        """
        if not hasattr(self, '_decorator_tools'):
            self._decorator_tools: dict[str, Any] = {}

        name = getattr(wrapper, 'tool_name', '')
        if not name:
            raise ValueError("Decorator tool has no tool_name set.")

        if name in self._classes:
            logger.warning(
                "Decorator tool '%s' shadows a registered BaseTool class", name
            )

        self._decorator_tools[name] = wrapper
        logger.debug(
            "Registered decorator tool: %s (epistemic=%s, effects=%s)",
            name,
            getattr(wrapper, 'epistemic_level', 'unknown'),
            getattr(wrapper, 'effect_row', ()),
        )

    def get_decorator_tool(self, name: str) -> Any:
        """Get a registered decorator tool by name.

        Raises:
            KeyError: If no decorator tool is registered under *name*.
        """
        if not hasattr(self, '_decorator_tools'):
            self._decorator_tools = {}
        if name not in self._decorator_tools:
            raise KeyError(f"Decorator tool '{name}' not registered.")
        return self._decorator_tools[name]

    def list_epistemic_tools(self) -> dict[str, str]:
        """Return ``{tool_name: epistemic_level}`` for all tools.

        Includes both BaseTool and decorator tools.
        """
        result: dict[str, str] = {}
        for name, cls in self._classes.items():
            result[name] = getattr(cls, 'EPISTEMIC_LEVEL', 'believe')
        if hasattr(self, '_decorator_tools'):
            for name, wrapper in self._decorator_tools.items():
                result[name] = getattr(wrapper, 'epistemic_level', 'believe')
        return result


# ── Helpers ──────────────────────────────────────────────────────


def _config_hash(config: dict[str, Any]) -> str:
    """Deterministic hash for a config dict (used as cache key)."""
    if not config:
        return "empty"
    # Sort keys for determinism; stringify for hashability
    items = sorted(config.items(), key=lambda kv: kv[0])
    return str(hash(tuple((k, str(v)) for k, v in items)))
