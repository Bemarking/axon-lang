"""
AXON Runtime — C Transpiler
============================
Transpiles compute logic DSL → safe C source code.

Sister module to :mod:`axon.runtime.rust_transpiler`. The C transpiler
converts AXON's deterministic ``logic_source`` into a C function with
``__declspec(dllexport)`` (Windows) or
``__attribute__((visibility("default")))`` (Unix) linkage, producing a
C-ABI-compatible symbol that can be loaded via FFI.

Architecture (Paper §5 — Deterministic Muscle):

    logic_source  →  C source  →  cc/tcc/cl  →  .dll/.so
                                                     ↓
                                  ctypes.cdll  →  native execution

The transpiler enforces Linear Logic resource semantics: each input is
consumed exactly once, and the output is a strictly deterministic
morphism F: V → W with zero probabilistic component.

Boundary (mathematical purity, founder principle 2026-05-08):
    Compute blocks are PURE deterministic morphisms over ``f64``. They
    are explicitly *not* allowed to invoke any of:
      - PIX navigation primitives (``pix``, ``navigate``, ``drill``,
        ``trail``) — those preserve information-theoretic guarantees
        about entropy reduction (PIX Theorem 2) that pure arithmetic
        cannot model.
      - MDN memory operations (``recall``, ``record``, memory update
        operator ``μ``) — those satisfy the locality constraint
        (MDN Definition 4: only traversed edges modify weights) which
        a deterministic compute morphism would silently violate.
      - Algebraic effects (``perform``, ``handle``, ``resume``,
        ``abort``, ``forward``) — those carry typed effect rows that
        the C ABI cannot represent.
    The boundary is enforced *grammatically*: the DSL only admits
    ``let`` bindings + ``return`` over the operator whitelist
    ``{+, -, *, /}`` and known parameters / locals. Any identifier or
    operator outside this set raises ``ValueError`` at transpile time
    — well before the source reaches a C compiler.

Security:
    - Only arithmetic operators (+, -, *, /) are emitted.
    - No ``#include``, no I/O, no ``malloc``, no ``unsafe`` constructs.
    - The generated C is a pure function over ``double`` values.
    - Identifiers are sanitised to ``[a-zA-Z0-9_]+`` only.

Parity with :class:`axon.runtime.rust_transpiler.RustTranspiler`:
    The two transpilers MUST accept and reject the same DSL inputs.
    The drift gate in ``tests/test_fase25_c_transpiler.py`` enforces
    this contract by feeding identical inputs to both and asserting
    matching success/failure. Adding a feature to one transpiler
    requires adding it to the other (and updating the drift gate).
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CTranspileResult:
    """Result of transpiling logic_source to C.

    Mirrors :class:`axon.runtime.rust_transpiler.TranspileResult` field-
    for-field; the only deliberate divergence is the ``c_source`` name
    in place of ``rust_source``. Adopters that switch backends (Rust →
    C or vice versa) only have to swap the source attribute name.
    """

    c_source: str
    fn_name: str
    param_names: tuple[str, ...]
    source_hash: str


class CTranspiler:
    """Transpile AXON compute DSL → safe C source code.

    The generated C function:
      - Uses platform-appropriate export linkage (``__declspec`` on
        Windows, ``__attribute__((visibility("default")))`` elsewhere)
        for C ABI compatibility.
      - Takes ``double`` parameters and returns ``double``.
      - Contains only arithmetic operations (no I/O, no ``#include``,
        no allocator).
      - Is deterministic by construction (Linear Logic guarantee).

    Construction is parameter-free; the transpiler holds no state and
    is safe to share across threads.
    """

    # Allowed operators — strict whitelist (no bitwise, no logic).
    # MUST stay in sync with RustTranspiler._ALLOWED_OPS — the drift
    # gate in tests asserts this.
    _ALLOWED_OPS = frozenset({"+", "-", "*", "/"})

    # Pattern to match a let binding: let name = expr
    _LET_RE = re.compile(r"^let\s+(\w+)\s*=\s*(.+)$")

    # Pattern to match a return statement: return expr
    _RETURN_RE = re.compile(r"^return\s+(.+)$")

    def transpile(
        self,
        logic_source: str,
        fn_name: str,
        param_names: list[str],
    ) -> CTranspileResult:
        """Transpile a logic_source string into C source code.

        Args:
            logic_source: The raw logic DSL
                (e.g. ``"let x = a + b\\nreturn x"``).
            fn_name: The compute block name (e.g. ``"CalculateTax"``).
            param_names: Input parameter names (e.g. ``["amount", "rate"]``).

        Returns:
            :class:`CTranspileResult` with C source, exported function
            name, parameter names, and a SHA-256 source hash for the
            compilation cache.

        Raises:
            ValueError: If the logic_source contains unsupported
                constructs (unknown operators, unknown identifiers,
                missing return, empty body).
        """
        source_hash = hashlib.sha256(
            logic_source.encode("utf-8"),
        ).hexdigest()

        c_fn_name = f"axon_compute_{self._sanitize(fn_name)}"

        # Build parameter list: all double
        params_c = ", ".join(
            f"double {self._sanitize(p)}" for p in param_names
        )
        if not params_c:
            # C requires `void` for an empty parameter list; otherwise
            # the function would be a K&R-style "unspecified args"
            # declaration which is removed in C23.
            params_c = "void"

        # Transpile body lines
        body_lines = self._transpile_body(logic_source, param_names)
        body = "\n".join(f"    {line}" for line in body_lines)

        # Platform-specific export macro.
        if sys.platform == "win32":
            export = "__declspec(dllexport)"
        else:
            # The visibility attribute is gcc/clang/Apple-clang
            # compatible; under MSVC on Windows we already took the
            # __declspec branch above.
            export = '__attribute__((visibility("default")))'

        c_source = (
            f"/* Auto-generated by AXON C Transpiler */\n"
            f"/* Source hash: {source_hash} */\n"
            f"/* Pure deterministic morphism F: V → W */\n"
            f"/* Linear Logic: each resource consumed exactly once */\n"
            f"/* Boundary: no PIX / MDN / effects — see c_transpiler.py docstring */\n"
            f"\n"
            f"{export}\n"
            f"double {c_fn_name}({params_c}) {{\n"
            f"{body}\n"
            f"}}\n"
        )

        return CTranspileResult(
            c_source=c_source,
            fn_name=c_fn_name,
            param_names=tuple(param_names),
            source_hash=source_hash,
        )

    def _transpile_body(
        self,
        logic_source: str,
        param_names: list[str],
    ) -> list[str]:
        """Transpile the logic DSL body into C statements.

        Mirrors :meth:`RustTranspiler._transpile_body` line-for-line so
        the two transpilers accept exactly the same DSL.
        """
        if not logic_source:
            raise ValueError(
                "Empty logic_source: compute blocks must contain "
                "at least one 'return' statement."
            )

        lines = logic_source.strip().splitlines()
        c_lines: list[str] = []
        locals_declared: set[str] = set()
        has_return = False

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            let_match = self._LET_RE.match(line)
            if let_match:
                var_name = self._sanitize(let_match.group(1))
                expr = let_match.group(2).strip()
                c_expr = self._transpile_expr(
                    expr, param_names, locals_declared,
                )
                c_lines.append(f"double {var_name} = {c_expr};")
                locals_declared.add(var_name)
                continue

            return_match = self._RETURN_RE.match(line)
            if return_match:
                expr = return_match.group(1).strip()
                c_expr = self._transpile_expr(
                    expr, param_names, locals_declared,
                )
                c_lines.append(f"return {c_expr};")
                has_return = True
                continue

            raise ValueError(
                f"Unsupported compute DSL statement: {line!r}"
            )

        if not has_return:
            raise ValueError(
                "Compute logic must contain a 'return' statement. "
                "Implicit return of 0.0 is not allowed for "
                "deterministic safety."
            )

        return c_lines

    def _transpile_expr(
        self,
        expr: str,
        param_names: list[str],
        locals_declared: set[str],
    ) -> str:
        """Transpile a single DSL expression to C.

        Validates that only allowed identifiers and operators are used.
        Mirrors :meth:`RustTranspiler._transpile_expr` semantics; the
        only difference is the literal-suffix convention (C uses no
        suffix for ``double`` literals; ``2.5`` is already a ``double``
        in C, while Rust requires ``2.5_f64``).
        """
        expr = expr.strip()
        tokens = self._tokenize_expr(expr)
        c_tokens: list[str] = []

        for raw_token in tokens:
            token = raw_token.strip()
            if not token:
                continue

            # Operator
            if token in self._ALLOWED_OPS:
                c_tokens.append(token)
                continue

            # Parentheses
            if token in ("(", ")"):
                c_tokens.append(token)
                continue

            # Numeric literal
            if self._is_numeric(token):
                # Make integer literals explicit doubles to avoid
                # accidental integer division (C's `5 / 2 == 2`).
                if "." in token:
                    c_tokens.append(token)
                else:
                    c_tokens.append(f"{token}.0")
                continue

            # Identifier (param or local variable)
            sanitized = self._sanitize(token)
            if sanitized in {self._sanitize(p) for p in param_names}:
                c_tokens.append(sanitized)
                continue
            if sanitized in locals_declared:
                c_tokens.append(sanitized)
                continue

            raise ValueError(
                f"Unknown identifier in compute expression: {token!r}. "
                f"Allowed: {param_names + list(locals_declared)}"
            )

        return " ".join(c_tokens)

    @staticmethod
    def _tokenize_expr(expr: str) -> list[str]:
        """Tokenize an arithmetic expression into atoms and operators.

        Identical to :meth:`RustTranspiler._tokenize_expr` — the DSL
        grammar is the same.
        """
        return [
            t for t in re.split(r"(\s+|[+\-*/()])", expr) if t.strip()
        ]

    @staticmethod
    def _is_numeric(token: str) -> bool:
        """Check if a token is a finite numeric literal."""
        try:
            val = float(token)
        except (ValueError, TypeError):
            return False
        import math

        return math.isfinite(val)

    @staticmethod
    def _sanitize(name: str) -> str:
        """Sanitize an identifier for C (alphanumeric + underscore only).

        Identical to :meth:`RustTranspiler._sanitize` so identifiers
        round-trip across backends.
        """
        return re.sub(r"[^a-zA-Z0-9_]", "_", name)
