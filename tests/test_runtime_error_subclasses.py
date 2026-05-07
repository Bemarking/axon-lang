"""Tests for v1.15.1 hot-fix — runtime error subclass discipline.

Background: v1.15.0 had a silent regression where 5 call sites in
``axon/runtime/executor.py`` constructed ``AxonRuntimeError`` with an
``error_type=`` keyword argument that the class signature did not
accept. The paths only triggered on rare error conditions (tool
dispatcher missing, tool execution failure, unknown data_science
operation, data_science execution failure, axonstore execution
failure), so happy-path CI never hit them — they crashed with
``TypeError`` in production at the worst possible moment.

This test file ships three layers of defence:

1. **Construction smoke** — every concrete ``AxonRuntimeError``
   subclass can be built with ``message=`` + ``context=`` and
   serialised via ``to_dict()`` without raising. The 4 new subclasses
   added in v1.15.1 (``ToolDispatchError``, ``ToolExecutionError``,
   ``DataScienceError``, ``AxonStoreError``) are exercised directly.

2. **Subclass smoke registry (bonus)** — discovers every subclass of
   ``AxonRuntimeError`` reachable from runtime imports and asserts
   each is constructible. Catches new subclass-without-test drift
   automatically — no orphan subclasses survive a full test run.

3. **AST kwarg gate (bonus)** — statically parses every ``.py`` file
   under ``axon/`` and ``tests/`` looking for ``raise <X>(...)``
   constructs where ``X`` is a known runtime-error class. Asserts
   that every kwarg passed appears in that class's actual
   ``__init__`` signature. Catches THE EXACT regression class that
   produced the v1.15.1 bug — and any future variant of it.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from axon.runtime.runtime_errors import (
    AgentBudgetExhaustedError,
    AgentStuckError,
    AnchorBreachError,
    AxonRuntimeError,
    AxonStoreError,
    CapabilityViolationError,
    ConfidenceError,
    DataScienceError,
    EpistemicDegradationError,
    ErrorContext,
    ExecutionTimeoutError,
    MandateViolationError,
    ModelCallError,
    RefineExhaustedError,
    ShieldBreachError,
    TaintViolationError,
    ToolDispatchError,
    ToolExecutionError,
    ValidationError,
)


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — Construction smoke for the four NEW v1.15.1 subclasses
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "cls,expected_level",
    [
        (ToolDispatchError, 5),
        (ToolExecutionError, 5),
        (DataScienceError, 5),
        (AxonStoreError, 5),
    ],
)
def test_v1151_new_subclasses_construct_cleanly(cls, expected_level) -> None:
    """The 4 subclasses introduced in v1.15.1 must accept the same
    (message, context) signature as their parent and report the
    correct severity level + class-name-derived error_type."""
    err = cls(
        message=f"{cls.__name__} smoke test",
        context=ErrorContext(step_name="probe", flow_name="smoke"),
    )
    assert isinstance(err, AxonRuntimeError)
    assert err.level == expected_level
    payload = err.to_dict()
    assert payload["error_type"] == cls.__name__
    assert payload["level"] == expected_level
    assert payload["message"] == f"{cls.__name__} smoke test"
    assert payload["context"]["step_name"] == "probe"
    assert payload["context"]["flow_name"] == "smoke"


def test_v1151_subclasses_reject_legacy_error_type_kwarg() -> None:
    """Pinning the regression: if someone re-introduces the
    ``error_type=`` kwarg to ``AxonRuntimeError.__init__``, it would
    be a silent semantic change (the class-name-derived error_type
    would compete with an explicit override). This test fails loudly
    if the parent signature ever grows that kwarg without an explicit
    decision."""
    sig = inspect.signature(AxonRuntimeError.__init__)
    assert "error_type" not in sig.parameters, (
        "AxonRuntimeError.__init__ must NOT accept error_type kwarg. "
        "If you intentionally added it, update this test + the v1.15.1 "
        "regression notes in axon/runtime/runtime_errors.py docstring."
    )


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — Subclass smoke registry (bonus 1)
# ═══════════════════════════════════════════════════════════════════


def _all_runtime_error_subclasses() -> list[type]:
    """Return every concrete subclass of ``AxonRuntimeError`` reachable
    from already-imported modules. Excludes ``AxonRuntimeError`` itself."""
    seen: set[type] = set()
    stack: list[type] = list(AxonRuntimeError.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
    return sorted(seen, key=lambda c: c.__name__)


def test_every_subclass_is_constructible_and_serialisable() -> None:
    """Discovered ``AxonRuntimeError`` subclasses must all accept the
    base signature + serialise without errors. Catches an orphan
    subclass that someone added with a custom ``__init__`` not aligned
    with the base contract — a different shape of the same drift bug
    that produced v1.15.1."""
    subclasses = _all_runtime_error_subclasses()
    assert len(subclasses) >= 12, (
        f"Expected at least 12 runtime-error subclasses, got "
        f"{len(subclasses)} — has runtime_errors.py shrunk?"
    )

    failures: list[str] = []
    for cls in subclasses:
        try:
            err = cls(
                message=f"{cls.__name__} registry smoke",
                context=ErrorContext(step_name="probe"),
            )
            payload = err.to_dict()
            assert payload["error_type"] == cls.__name__
            assert isinstance(payload["level"], int)
            assert isinstance(payload["context"], dict)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{cls.__name__}: {type(exc).__name__}: {exc}")
    assert not failures, (
        "Subclass registry smoke detected drift — these subclasses "
        "violate the (message, context) constructor contract:\n  "
        + "\n  ".join(failures)
    )


def test_v1151_required_subclasses_present() -> None:
    """Pin the four v1.15.1 additions in the discovered registry so a
    rebase that reverts the runtime_errors.py changes fails loudly."""
    discovered = {c.__name__ for c in _all_runtime_error_subclasses()}
    for required in (
        "ToolDispatchError",
        "ToolExecutionError",
        "DataScienceError",
        "AxonStoreError",
    ):
        assert required in discovered, (
            f"v1.15.1 subclass {required!r} is missing — "
            "did the runtime_errors.py change get reverted?"
        )


# ═══════════════════════════════════════════════════════════════════
#  Layer 3 — AST kwarg gate (bonus 2 — catches the entire class)
# ═══════════════════════════════════════════════════════════════════


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _runtime_error_init_signatures() -> dict[str, set[str]]:
    """Map runtime-error class name → its ``__init__`` parameter names
    (excluding ``self``). Used by the AST gate to verify call sites
    pass only kwargs the class actually accepts."""
    sigs: dict[str, set[str]] = {}
    for cls in [AxonRuntimeError, *_all_runtime_error_subclasses()]:
        params = set(inspect.signature(cls.__init__).parameters.keys())
        params.discard("self")
        params.discard("args")
        params.discard("kwargs")
        sigs[cls.__name__] = params
    return sigs


def _scan_python_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            # Skip generated / vendored / cache dirs.
            parts = set(path.parts)
            if parts & {"__pycache__", "target", ".pytest_cache", "build", "dist"}:
                continue
            files.append(path)
    return files


def test_ast_kwarg_gate_no_unknown_kwargs() -> None:
    """Static-analysis gate: every ``raise <X>(...)`` in axon/ + tests/
    where ``X`` is a runtime-error class must pass only kwargs that
    appear in that class's actual ``__init__`` signature.

    This is the gate that would have caught the v1.15.1 bug in CI.
    The 5 broken call sites in ``executor.py`` passed
    ``error_type=`` to ``AxonRuntimeError(...)``; that kwarg was not
    in the signature; the AST walk would have failed on each.
    """
    sigs = _runtime_error_init_signatures()
    known_classes = set(sigs.keys())

    violations: list[str] = []

    for path in _scan_python_files((_REPO_ROOT / "axon", _REPO_ROOT / "tests")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            # Skip files that don't parse (e.g., intentional bad-syntax test
            # fixtures); CI's main test suite catches those separately.
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc
            if not isinstance(call, ast.Call):
                continue
            cls_name = _resolve_call_class_name(call.func)
            if cls_name is None or cls_name not in known_classes:
                continue
            allowed = sigs[cls_name]
            for kw in call.keywords:
                if kw.arg is None:
                    # **kwargs unpacking — skip; can't statically verify.
                    continue
                if kw.arg not in allowed:
                    rel = path.relative_to(_REPO_ROOT)
                    violations.append(
                        f"{rel}:{node.lineno}: raise {cls_name}(...) passes "
                        f"unknown kwarg {kw.arg!r}; allowed: "
                        f"{sorted(allowed)}"
                    )

    assert not violations, (
        "AST kwarg gate caught runtime-error constructor drift "
        "(this is exactly the v1.15.1 bug class):\n  "
        + "\n  ".join(violations)
    )


def _resolve_call_class_name(func_node: ast.expr) -> str | None:
    """Resolve a ``Call.func`` node to a bare class name, if possible.

    Handles ``ToolDispatchError(...)`` (Name) and
    ``runtime_errors.ToolDispatchError(...)`` (Attribute). Returns
    ``None`` for shapes the gate can't statically analyse (calls
    against return values, dynamic attribute lookup, etc.) — those
    fall outside the gate's scope by design.
    """
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None


# ═══════════════════════════════════════════════════════════════════
#  Layer 3.b — Belt-and-braces: regex-grep for the exact bad pattern
# ═══════════════════════════════════════════════════════════════════


def test_no_error_type_kwarg_in_runtime_error_calls() -> None:
    """Belt-and-braces complement to the AST gate: simple grep for
    any ``error_type=`` kwarg in the same neighbourhood as a
    runtime-error constructor call. Catches the v1.15.1 bug pattern
    even if the AST resolver misses an exotic call shape."""
    pattern = re.compile(
        r"raise\s+\w*Error\([^)]{0,400}error_type\s*=",
        re.DOTALL,
    )
    violations: list[str] = []
    for path in _scan_python_files((_REPO_ROOT / "axon",)):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            rel = path.relative_to(_REPO_ROOT)
            violations.append(
                f"{rel}:{line_no}: raise <Error>(...) appears to pass "
                f"error_type= kwarg — that's the v1.15.1 regression pattern."
            )
    assert not violations, "\n  ".join(violations)
