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
    docs/fase_19_production_hardening.md and is tracked separately
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
        "docs/fase_19_production_hardening.md §19.a–§19.c for the "
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


@pytest.mark.skip(reason=(
    "Tier C 19.f/g (Rust dispatchers for the 9 Fase-18 primitives + "
    "IRBreak/IRContinue Rust mirror) is the next sub-phase per "
    "docs/fase_19_production_hardening.md. Once the Rust runner has a "
    "match arm for each WIRED primitive, this test will assert that "
    "every WIRED Python dispatcher has a Rust counterpart in "
    "axon-rs/src/runner.rs::execute_stub."
))
def test_rust_parity_for_wired_primitives():
    """When unblocked: parse axon-rs/src/runner.rs::execute_stub for
    its match arms; intersect with the Python WIRED-classified
    variants from the Fase 18 matrix; assert no Python WIRED variant
    lacks a Rust arm."""
    raise NotImplementedError("see Tier C deliverable")
