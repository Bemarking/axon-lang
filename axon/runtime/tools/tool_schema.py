"""
AXON Runtime — Tool Schema (v0.11.0)
======================================
Formal contracts for tool interfaces based on Constraint
Satisfaction Programming (CSP) from §5.3 of the mathematical
prompt optimization research.

A ``ToolSchema`` declares the inputs a tool accepts, their types
and constraints, and the expected output type.  The dispatcher
validates arguments against the schema *before* execution,
catching misconfiguration early.

    >>> schema = ToolSchema(
    ...     name="WebSearch",
    ...     description="Search the web for a query",
    ...     input_params=[
    ...         ToolParameter("query", "str", required=True,
    ...                       description="Search query"),
    ...         ToolParameter("max_results", "int", required=False,
    ...                       default=5, description="Max results"),
    ...     ],
    ...     output_type="list[dict]",
    ... )
    >>> valid, errors = schema.validate_input({"query": "AXON lang"})
    >>> assert valid and not errors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  ToolParameter — single parameter specification
# ═══════════════════════════════════════════════════════════════════

# Canonical type names understood by the schema engine.
# These are *logical* types — no Python runtime type-checking is
# enforced, but the dispatcher and chain validator inspect them.
CANONICAL_TYPES: frozenset[str] = frozenset({
    "str", "int", "float", "bool", "list", "dict",
    "list[str]", "list[int]", "list[dict]",
    "dict[str,str]", "dict[str,Any]",
    "Any",
})

_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class ToolParameter:
    """Specification for a single tool input parameter.

    Attributes:
        name:        Parameter name (identifier).
        type_name:   Logical type string (e.g. ``"str"``, ``"int"``).
        required:    Whether the parameter *must* be provided.
        default:     Default value when omitted (``_SENTINEL`` = no default).
        description: Human-readable description for documentation.
        constraints: Optional list of constraint expressions (future CSP).
    """

    name: str
    type_name: str = "str"
    required: bool = True
    default: Any = _SENTINEL
    description: str = ""
    constraints: tuple[str, ...] = ()

    # ── helpers ───────────────────────────────────────────────

    @property
    def has_default(self) -> bool:
        return self.default is not _SENTINEL

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "required": self.required,
            "description": self.description,
        }
        if self.has_default:
            d["default"] = self.default
        if self.constraints:
            d["constraints"] = list(self.constraints)
        return d

    def __repr__(self) -> str:
        opt = "" if self.required else "?"
        default_str = f"={self.default!r}" if self.has_default else ""
        return f"ToolParameter({self.name}{opt}: {self.type_name}{default_str})"


# ═══════════════════════════════════════════════════════════════════
#  ToolSchema — full tool contract
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """Formal contract for a tool's interface.

    Provides compile-time-like guarantees at runtime:
    - Required parameters are present
    - Optional parameters get defaults
    - Type names are recorded for chain validation

    *Inspired by §5.3 (CSP) and §5 (Lattice Theory) of the
    mathematical prompt optimization research.*

    Attributes:
        name:            Tool name (matches ``BaseTool.TOOL_NAME``).
        description:     What the tool does.
        input_params:    Ordered list of input parameters.
        output_type:     Logical type of the output data.
        constraints:     Global constraints (future CSP solver).
        timeout_default: Default timeout in seconds.
        retry_policy:    Retry strategy name (``"exponential"``, ``"fixed"``).
        max_retries:     Maximum retry attempts.
    """

    name: str
    description: str = ""
    input_params: tuple[ToolParameter, ...] = ()
    output_type: str = "Any"
    constraints: tuple[str, ...] = ()
    timeout_default: float = 30.0
    retry_policy: str = "exponential"
    max_retries: int = 2

    # ── validation ────────────────────────────────────────────

    def validate_input(
        self,
        args: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate *args* against the schema's input parameters.

        Returns:
            A ``(valid, errors)`` tuple.  When ``valid`` is ``True``,
            ``errors`` is empty.
        """
        errors: list[str] = []

        # Track seen params to detect unexpected arguments
        known_names = {p.name for p in self.input_params}
        unexpected = set(args.keys()) - known_names
        for u in sorted(unexpected):
            errors.append(f"Unexpected parameter: '{u}'")

        for param in self.input_params:
            if param.name in args:
                value = args[param.name]
                # Type checking (soft — based on canonical names)
                if not self._check_type(value, param.type_name):
                    errors.append(
                        f"Parameter '{param.name}' expected type "
                        f"'{param.type_name}', got "
                        f"'{type(value).__name__}'"
                    )
            elif param.required:
                errors.append(
                    f"Missing required parameter: '{param.name}'"
                )
            # Optional + missing → will be filled from default by caller

        return (len(errors) == 0, errors)

    def apply_defaults(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of *args* with defaults applied for missing optional params."""
        result = dict(args)
        for param in self.input_params:
            if param.name not in result and param.has_default:
                result[param.name] = param.default
        return result

    # ── serialization ─────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_params": [p.to_dict() for p in self.input_params],
            "output_type": self.output_type,
            "timeout_default": self.timeout_default,
            "retry_policy": self.retry_policy,
            "max_retries": self.max_retries,
        }
        if self.constraints:
            d["constraints"] = list(self.constraints)
        return d

    # ── internals ─────────────────────────────────────────────

    @staticmethod
    def _check_type(value: Any, type_name: str) -> bool:
        """Soft type check: returns ``True`` if *value* is compatible
        with *type_name*.  ``"Any"`` always matches."""
        if type_name == "Any":
            return True

        type_map: dict[str, type | tuple[type, ...]] = {
            "str": str,
            "int": (int,),
            "float": (int, float),
            "bool": bool,
            "list": list,
            "dict": dict,
        }

        # Handle parameterized types like list[str], list[dict]
        if type_name.startswith("list["):
            return isinstance(value, list)
        if type_name.startswith("dict["):
            return isinstance(value, dict)

        expected = type_map.get(type_name)
        if expected is None:
            return True  # Unknown type → pass (permissive)

        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)

    def __repr__(self) -> str:
        params_str = ", ".join(p.name for p in self.input_params)
        return f"ToolSchema({self.name}({params_str}) → {self.output_type})"
