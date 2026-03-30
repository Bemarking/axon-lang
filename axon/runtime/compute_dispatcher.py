"""
AXON Runtime — Native Compute Dispatcher
==========================================
Deterministic Fast-Path execution engine for compute primitives.

The NativeComputeDispatcher is the "muscle" of the AXON runtime:
it evaluates compute logic blocks without invoking any LLM,
executing deterministic transformations directly in Python.

Architecture:
  1. Receives a compute application (metadata) + context
  2. Resolves input arguments from context or literal values
  3. Evaluates the logic DSL (let bindings, arithmetic, return)
  4. Returns the result as a Python value

Future roadmap:
  - Transpile DSL logic → Rust source
  - Compile Rust → shared library (.so/.dll) via rustc
  - Load via CFFI for zero-copy execution on MEK buffers
  - Currently: interpreted Python Fast-Path (still no LLM)
"""

from __future__ import annotations

import operator
import re
from typing import Any


class NativeComputeDispatcher:
    """Fast-Path deterministic executor — runs compute without LLM."""

    # Supported binary operators for arithmetic expressions
    _OPS: dict[str, Any] = {
        "+": operator.add,
        "-": operator.sub,
        "*": operator.mul,
        "/": operator.truediv,
    }

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
            A dict with 'output_name' and 'result' keys.
        """
        compute_def = compute_meta.get("compute_definition", {})
        arguments = compute_meta.get("arguments", [])
        output_name = compute_meta.get("output_name", "")
        inputs = compute_def.get("inputs", [])
        logic_source = compute_def.get("logic_source", "")

        # Bind arguments to input parameter names
        env: dict[str, Any] = {}
        for i, param in enumerate(inputs):
            if i < len(arguments):
                env[param["name"]] = self._resolve_argument(
                    arguments[i], context,
                )

        # Evaluate the logic DSL
        result = self._evaluate_logic(logic_source, env)

        return {
            "output_name": output_name,
            "result": result,
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
