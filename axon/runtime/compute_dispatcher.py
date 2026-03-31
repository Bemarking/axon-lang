"""
AXON Runtime — Native Compute Dispatcher
==========================================
Deterministic Fast-Path execution engine for compute primitives.

The NativeComputeDispatcher is the "muscle" of the AXON runtime:
it evaluates compute logic blocks without invoking any LLM,
executing deterministic transformations at native speed.

3-Tier Execution Architecture (Paper §5):
  Tier 1 — Rust:  logic → RustTranspiler → rustc cdylib → ctypes FFI
  Tier 2 — C:     logic → C transpiler → gcc/tcc → ctypes FFI
  Tier 3 — Python: interpreted Fast-Path (always-available fallback)

Each tier produces the same deterministic result; the only difference
is execution speed.  The dispatcher auto-detects available compilers
and selects the best tier at runtime.
"""

from __future__ import annotations

import logging
import operator
import re
from typing import Any

logger = logging.getLogger(__name__)


class NativeComputeDispatcher:
    """Fast-Path deterministic executor — runs compute without LLM.

    On first call the dispatcher lazily initialises the native compile
    pipeline (Rust → C → Python fallback).  Compiled libraries are
    cached by source hash across calls.
    """

    # Supported binary operators for arithmetic expressions
    _OPS: dict[str, Any] = {
        "+": operator.add,
        "-": operator.sub,
        "*": operator.mul,
        "/": operator.truediv,
    }

    def __init__(self) -> None:
        self._native_compiler: Any = None
        self._ffi_bridge: Any = None
        self._native_init_done = False

    def _ensure_native_pipeline(self) -> None:
        """Lazily initialise the native compilation pipeline."""
        if self._native_init_done:
            return
        self._native_init_done = True
        try:
            from axon.runtime.native_compiler import NativeCompiler
            from axon.runtime.ffi_bridge import FFIBridge

            self._native_compiler = NativeCompiler()
            self._ffi_bridge = FFIBridge()
            tier = self._native_compiler.available_tier
            logger.info("AXON compute native tier: %s", tier)
        except Exception:
            logger.debug(
                "Native compile pipeline unavailable — using Python fallback",
            )
            self._native_compiler = None
            self._ffi_bridge = None

    async def dispatch(
        self,
        compute_meta: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a compute block deterministically.

        Args:
            compute_meta: The compute metadata from CompiledStep,
                containing compute_name, arguments, output_name,
                and compute_definition.
            context: The current execution context (step outputs).

        Returns:
            A dict with 'output_name', 'result', and 'tier' keys.
        """
        compute_def = compute_meta.get("compute_definition", {})
        arguments = compute_meta.get("arguments", [])
        output_name = compute_meta.get("output_name", "")
        compute_name = compute_meta.get("compute_name", "compute")
        inputs = compute_def.get("inputs", [])
        logic_source = compute_def.get("logic_source", "")

        # Bind arguments to input parameter names
        env: dict[str, Any] = {}
        param_names: list[str] = []
        arg_values: list[float] = []
        for i, param in enumerate(inputs):
            if i < len(arguments):
                val = self._resolve_argument(arguments[i], context)
                env[param["name"]] = val
                param_names.append(param["name"])
                try:
                    arg_values.append(float(val))
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Compute argument '{arguments[i]}' resolved to "
                        f"non-numeric value: {val!r}. All compute inputs "
                        f"must be numeric (f64)."
                    )

        # --- 3-Tier Execution Pipeline ---
        self._ensure_native_pipeline()

        tier = "python"
        result = None

        # Tier 1 & 2: Try native compilation (Rust / C)
        if self._native_compiler is not None and logic_source:
            try:
                cr = self._native_compiler.compile(
                    logic_source, compute_name, param_names,
                )
                if cr.tier in ("rust", "c"):
                    result = self._ffi_bridge.call(
                        str(cr.lib_path), cr.fn_name, arg_values,
                    )
                    tier = cr.tier
            except Exception:
                logger.debug(
                    "Native execution failed — falling back to Python",
                    exc_info=True,
                )

        # Tier 3: Python fallback
        if result is None:
            result = self._evaluate_logic(logic_source, env)
            tier = "python"

        return {
            "output_name": output_name,
            "result": result,
            "tier": tier,
        }

    def _resolve_argument(
        self, arg: str, context: dict[str, Any],
    ) -> Any:
        """Resolve an argument: literal number, string, or context path."""
        # Try numeric literal
        try:
            if "." in arg:
                return float(arg)
            return int(arg)
        except (ValueError, TypeError):
            pass

        # Try dotted path resolution from context
        if "." in arg:
            parts = arg.split(".")
            current = context
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part, arg)
                else:
                    return arg
            return current

        # Plain identifier — look up in context
        return context.get(arg, arg)

    def _evaluate_logic(
        self, logic_source: str, env: dict[str, Any],
    ) -> Any:
        """Evaluate the logic DSL source with the given environment.

        Supports:
          - let bindings: let x = expr
          - return statements: return expr
          - arithmetic: +, -, *, /
          - parenthesized expressions
          - variable references
        """
        if not logic_source:
            return None

        lines = logic_source.strip().splitlines()
        result = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("let "):
                # let identifier = expression
                match = re.match(r"let\s+(\w+)\s*=\s*(.+)", line)
                if match:
                    name = match.group(1)
                    expr = match.group(2)
                    env[name] = self._eval_expr(expr, env)

            elif line.startswith("return "):
                expr = line[len("return "):]
                result = self._eval_expr(expr, env)

        return result

    def _eval_expr(self, expr: str, env: dict[str, Any]) -> Any:
        """Evaluate a single expression within the compute DSL.

        Handles: numbers, variable refs, binary ops (+, -, *, /),
        and parenthesized sub-expressions.
        """
        expr = expr.strip()

        # Parenthesized expression
        if expr.startswith("(") and expr.endswith(")"):
            return self._eval_expr(expr[1:-1], env)

        # Try to find a binary operator (respecting precedence: + - first, then * /)
        # Use a simple left-to-right parse for top-level operators
        result = self._eval_additive(expr, env)
        return result

    def _eval_additive(self, expr: str, env: dict[str, Any]) -> Any:
        """Parse additive expressions: term (('+' | '-') term)*"""
        parts = self._split_at_operators(expr, ["+", "-"])
        if len(parts) == 1:
            return self._eval_multiplicative(parts[0], env)

        result = self._eval_multiplicative(parts[0], env)
        i = 1
        while i < len(parts):
            op_str = parts[i]
            operand = self._eval_multiplicative(parts[i + 1], env)
            result = self._OPS[op_str](result, operand)
            i += 2
        return result

    def _eval_multiplicative(self, expr: str, env: dict[str, Any]) -> Any:
        """Parse multiplicative expressions: atom (('*' | '/') atom)*"""
        parts = self._split_at_operators(expr, ["*", "/"])
        if len(parts) == 1:
            return self._eval_atom(parts[0], env)

        result = self._eval_atom(parts[0], env)
        i = 1
        while i < len(parts):
            op_str = parts[i]
            operand = self._eval_atom(parts[i + 1], env)
            if op_str == "/" and operand == 0:
                raise ZeroDivisionError(
                    "Division by zero in compute logic"
                )
            result = self._OPS[op_str](result, operand)
            i += 2
        return result

    def _eval_atom(self, expr: str, env: dict[str, Any]) -> Any:
        """Evaluate an atomic expression: number, variable, or parens."""
        expr = expr.strip()

        if not expr:
            return 0

        # Parenthesized
        if expr.startswith("(") and expr.endswith(")"):
            return self._eval_additive(expr[1:-1], env)

        # Numeric literal
        try:
            if "." in expr:
                return float(expr)
            return int(expr)
        except (ValueError, TypeError):
            pass

        # Variable reference
        if expr in env:
            return env[expr]

        # Fallback: return as string
        return expr

    @staticmethod
    def _split_at_operators(
        expr: str, ops: list[str],
    ) -> list[str]:
        """Split an expression at top-level operators (outside parens).

        Returns alternating [operand, op, operand, op, ...] list.
        """
        expr = expr.strip()
        parts: list[str] = []
        current: list[str] = []
        depth = 0

        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif depth == 0 and ch in ops:
                # Check it's not part of a negative number after an operator
                token = "".join(current).strip()
                if token:  # Only split if we have a preceding operand
                    parts.append(token)
                    parts.append(ch)
                    current = []
                else:
                    current.append(ch)
            else:
                current.append(ch)
            i += 1

        remaining = "".join(current).strip()
        if remaining:
            parts.append(remaining)

        return parts if len(parts) > 1 else [expr]
