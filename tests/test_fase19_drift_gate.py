"""
Fase 19.l — Drift gate extension.

Layered on top of the Fase 18.l drift gate (test_ir_runtime_coverage.py)
which already enforces every IRFlowNode variant has a classified
runtime status. Fase 19's contribution closes a different drift class:

  * Fase 18 shipped MVP placeholders for Hibernate/Drill/Trail with
    explicit `_stub: True` markers in the bound payloads. Fase 19.a/b/c
    replaces those with real subsystem integration. The drift gate
    asserts the literal `_stub` marker is GONE from production
    dispatchers — adopters relying on the absence of `_stub` should
    not have it silently re-introduced by a regression.

  * Fase 19 introduces several new runtime modules:
      - axon/runtime/pem/hibernation.py (19.a)
      - axon/runtime/pix_registry.py     (19.b/c)
      - axon/runtime/par_context.py      (19.d)
      - IRBreak / IRContinue + parser/lexer/IR-generator wiring (19.e)
    The gate asserts each is importable and exposes the intended API
    surface — guards against accidental removal during refactors.

  * Fase 19.e adds break/continue keywords. The drift gate asserts the
    parser scope check (loop_depth) is in place — without it, adopters
    could write `break` at flow scope and get arbitrary runtime
    behavior from the LLM fall-through path.

  * The Rust-parity assertion (every WIRED Python primitive has a
    Rust counterpart) is the Tier C deliverable in
    docs/fase/fase_19_production_hardening.md and is tracked separately
    once the Rust dispatchers land. This file marks that gap with a
    deliberately-skipped placeholder so the obligation is not
    forgotten.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════
#  NO MVP STUB MARKERS
# ═══════════════════════════════════════════════════════════════════


def test_executor_no_stub_true_markers():
    """Fase 18.h/j/k shipped placeholder dispatchers that bound
    payloads with literal ``_stub: True`` markers. Fase 19.a/b/c
    replaces them with real subsystem integration; the marker MUST
    NOT survive in `axon/runtime/executor.py`. If it reappears,
    something regressed Drill/Trail/Hibernate back to placeholder
    behavior."""
    src = (_project_root() / "axon" / "runtime" / "executor.py").read_text(encoding="utf-8")
    # Allow the literal in COMMENTS that explain the historical MVP
    # behavior, but no `"_stub": True` payload binding should remain.
    assert '"_stub": True' not in src, (
        "Found `\"_stub\": True` in axon/runtime/executor.py. "
        "Fase 19.a/b/c removed the Fase 18 MVP placeholders — this "
        "marker reappearing means a dispatcher regressed to the stub "
        "shape. Wire it to the real subsystem (see "
        "docs/fase/fase_19_production_hardening.md §19.a–§19.c for the "
        "expected pattern: ContinuityTokenSigner / PixNavigator / "
        "ContextView)."
    )


# ═══════════════════════════════════════════════════════════════════
#  REQUIRED FASE-19 MODULES + API SURFACE
# ═══════════════════════════════════════════════════════════════════


def test_hibernation_module_present_and_complete():
    """19.a: HibernationStore Protocol + InMemoryHibernationStore +
    HibernationSnapshot + parse_timeout must be importable from the
    PEM facade."""
    from axon.runtime.pem import (
        HibernationSnapshot,
        HibernationStore,
        InMemoryHibernationStore,
        parse_timeout,
    )
    # Sanity: API shape.
    assert callable(parse_timeout)
    snap = HibernationSnapshot(session_id="k", flow_name="f")
    assert snap.session_id == "k"
    store = InMemoryHibernationStore()
    store.save("k", snap)
    assert store.load("k") is snap
    # HibernationStore is a Protocol — just check it's importable.
    assert HibernationStore is not None


def test_pix_registry_module_present_and_complete():
    """19.b/c: PixRegistry Protocol + InMemoryPixRegistry must be
    importable. The drill/trail dispatchers depend on it."""
    from axon.runtime.pix_registry import InMemoryPixRegistry, PixRegistry
    reg = InMemoryPixRegistry()
    assert reg.known_refs() == []
    assert PixRegistry is not None


def test_par_context_module_present_and_complete():
    """19.d: ContextView + ParMergeStrategy + merge_par_views +
    ParMergeConflict + parse_merge_strategy must be importable."""
    from axon.runtime.par_context import (
        ContextView,
        ParMergeConflict,
        ParMergeStrategy,
        merge_par_views,
        parse_merge_strategy,
    )
    # All four strategies enumerated.
    assert {s.value for s in ParMergeStrategy} == {
        "last_writer_wins", "first_writer_wins",
        "reject_conflicts", "merge_dicts",
    }
    assert callable(merge_par_views)
    assert callable(parse_merge_strategy)
    assert ContextView is not None
    assert issubclass(ParMergeConflict, Exception)


def test_executor_accepts_fase19_dependencies():
    """Executor.__init__ accepts continuity_signer + hibernation_store
    + pix_registry. Regression check: removing any kwarg breaks the
    contract adopters in production rely on for backend swaps."""
    import inspect

    from axon.runtime.executor import Executor
    sig = inspect.signature(Executor.__init__)
    for required in (
        "continuity_signer",
        "hibernation_store",
        "pix_registry",
    ):
        assert required in sig.parameters, (
            f"Executor.__init__ no longer accepts `{required}` — "
            f"this is a Fase 19 backend-injection contract; adopters "
            f"with custom signers / stores / registries depend on it."
        )


def test_executor_exposes_resume_from_token():
    """19.a public API: Executor.resume_from_token verifies a signed
    token + returns the persisted HibernationSnapshot."""
    from axon.runtime.executor import Executor
    assert hasattr(Executor, "resume_from_token"), (
        "Executor.resume_from_token (Fase 19.a) is missing. This is "
        "the entry point adopters call when a wakeup event arrives "
        "with a signed continuity token."
    )


# ═══════════════════════════════════════════════════════════════════
#  IR / PARSER SCOPE CHECKS
# ═══════════════════════════════════════════════════════════════════


def test_ir_break_continue_present():
    """19.e: IRBreak + IRContinue must be importable from the IR
    nodes module."""
    from axon.compiler.ir_nodes import IRBreak, IRContinue
    assert IRBreak.__dataclass_fields__["node_type"].default == "break"
    assert IRContinue.__dataclass_fields__["node_type"].default == "continue"


def test_break_continue_tokens_registered():
    """19.e: BREAK + CONTINUE token types + keyword map entries."""
    from axon.compiler.tokens import KEYWORDS, TokenType
    assert hasattr(TokenType, "BREAK")
    assert hasattr(TokenType, "CONTINUE")
    assert KEYWORDS.get("break") is TokenType.BREAK
    assert KEYWORDS.get("continue") is TokenType.CONTINUE


def test_parser_loop_depth_scope_check_present():
    """19.e: parser tracks `_loop_depth` and rejects break/continue
    outside a loop body. Without this, adopters could write loop
    control at flow scope and get LLM-fall-through arbitrary
    behavior."""
    from axon.compiler.lexer import Lexer
    from axon.compiler.parser import Parser
    from axon.compiler.errors import AxonParseError

    parser = Parser(Lexer("break").tokenize())
    assert hasattr(parser, "_loop_depth"), (
        "Parser._loop_depth is missing — this is the Fase 19.e scope "
        "check that prevents break/continue outside a for-in body."
    )
    assert parser._loop_depth == 0
    with pytest.raises(AxonParseError):
        parser._parse_break()


def test_break_continue_dispatchers_present_in_executor():
    """19.e: Executor must expose _execute_break_step /
    _execute_continue_step + sentinel exceptions."""
    from axon.runtime.executor import (
        Executor,
        _FlowBreakSignal,
        _FlowContinueSignal,
    )
    assert hasattr(Executor, "_execute_break_step")
    assert hasattr(Executor, "_execute_continue_step")
    assert issubclass(_FlowBreakSignal, Exception)
    assert issubclass(_FlowContinueSignal, Exception)


# ═══════════════════════════════════════════════════════════════════
#  DEFERRED — RUST PARITY
# ═══════════════════════════════════════════════════════════════════


def test_rust_parity_for_wired_primitives():
    """Rust runner must have stub-correct dispatch for every WIRED
    primitive (Tier C of Fase 19 — landed in commits e47d813 / etc.).

    Parses ``axon-rs/src/runner.rs`` for match-arm string literals
    against ``step.step_type`` and asserts the 11 newly-wired
    primitives all appear. The Rust dispatchers are stub-correct
    (they bind placeholders + emit traces), not full integrations —
    that's the explicit ``Out of Scope`` note in the plan. What we
    enforce here is: no Fase-19 WIRED primitive lacks Rust dispatch.
    """
    import re
    runner = (
        _project_root() / "axon-rs" / "src" / "runner.rs"
    ).read_text(encoding="utf-8")
    # Grab arm patterns of shape `"foo" => {` and pipe-or patterns
    # like `"foo" | "bar" => {`. We collect every string-literal
    # arm by extracting all `"<name>"` occurrences from each line
    # that ends in `=> {`.
    arm_re = re.compile(r'^\s*((?:"[a-z_]+"\s*(?:\|\s*)?)+)\s*=>\s*\{', re.MULTILINE)
    string_re = re.compile(r'"([a-z_]+)"')
    found_arms: set[str] = set()
    for arm_pattern in arm_re.findall(runner):
        for name in string_re.findall(arm_pattern):
            found_arms.add(name)

    expected_arms = {
        # Fase 18 primitives newly-wired in 18.b/c/e/d/f/g/h/j/k:
        "conditional", "for_in", "parallel", "return",
        "remember", "recall",
        "hibernate", "drill", "trail",
        # Fase 19.e additions:
        "break", "continue",
    }
    missing = expected_arms - found_arms
    assert not missing, (
        f"axon-rs/src/runner.rs is missing Rust dispatch for the "
        f"following Fase-19 WIRED primitives:\n  {sorted(missing)}\n\n"
        f"Each WIRED Python dispatcher must have a stub-correct "
        f"match arm in `execute_stub`. See "
        f"docs/fase/fase_19_production_hardening.md §19.f/g for the "
        f"contract — the arm should:\n"
        f"  1. Recognize step.step_type.\n"
        f"  2. Bind any adopter-visible placeholders to ExecContext.\n"
        f"  3. Emit a structured TraceEvent with matching event-type."
    )
