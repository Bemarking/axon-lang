"""Fase 23.g — `stream<τ>` algebraic-effects desugar tests.

Verifies that every `stream<T> { on_chunk(c) {...} on_complete(r) {...} }`
declaration ALSO produces a synthetic `IRHandlerFrame` representing the
equivalent algebraic-effects handler:

    handle _StreamBuiltin<T> {
        Chunk(c)    -> { ...on_chunk body...; resume }
        Complete(r) -> { ...on_complete body...; abort }
    } in { /* upstream subscription, driven by host */ }

The legacy `IRStreamSpec` shape (on_chunk_body / on_complete_body) is
preserved alongside the new `desugared_handler` field — D8 backward
compat 100%. Adopters' source `.axon` files do not change.

Post-23.g, the footnote in `docs/algebraic_effects_streaming.md`
("Integrado nativamente en la primitiva `stream` de Axon-lang") is
factually true: `stream<τ>` IS an algebraic-effects handler at the IR
level, and the Rust runtime in `axon-rs/src/effects/` (Fase 23.f)
dispatches it as such.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import ProgramNode
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRAbort,
    IRHandlerClause,
    IRHandlerFrame,
    IRProgram,
    IRResume,
    IRStreamSpec,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# ──────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────


def _ir(source: str) -> IRProgram:
    return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())


def _stream_in(ir: IRProgram) -> IRStreamSpec:
    """Extract the first IRStreamSpec from the first flow's first step."""
    flow = ir.flows[0]
    step = flow.steps[0]
    for node in step.body:
        if isinstance(node, IRStreamSpec):
            return node
    raise AssertionError("no IRStreamSpec in the first step's body")


# ──────────────────────────────────────────────────────────────────────
#  TestStreamSpecBackwardCompat — legacy shape preserved
# ──────────────────────────────────────────────────────────────────────


class TestStreamSpecBackwardCompat:
    """The pre-23.g IRStreamSpec contract is preserved (D8)."""

    def test_legacy_fields_still_populated(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        spec = _stream_in(ir)
        assert spec.element_type == "Document"
        assert spec.initial_gradient == "doubt"
        assert len(spec.on_chunk_body) == 1
        assert len(spec.on_complete_body) == 1

    def test_stream_without_handlers_still_compiles(self) -> None:
        """A bare `stream<T>` (no body) keeps the pre-23.g semantics."""
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Token>\n"
            "  }\n"
            "}"
        )
        spec = _stream_in(ir)
        assert spec.element_type == "Token"
        assert spec.on_chunk_body == ()
        assert spec.on_complete_body == ()


# ──────────────────────────────────────────────────────────────────────
#  TestDesugarPresence — new field appears + has correct shape
# ──────────────────────────────────────────────────────────────────────


class TestDesugarPresence:
    """`desugared_handler` is always populated (Fase 23.g)."""

    def test_desugared_handler_always_present(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        spec = _stream_in(ir)
        assert spec.desugared_handler is not None
        assert isinstance(spec.desugared_handler, IRHandlerFrame)

    def test_desugared_handler_uses_stream_builtin_effect(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        assert handler.effect_names == ("_StreamBuiltin",)

    def test_desugared_handler_has_chunk_and_complete_clauses(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        op_names = tuple(c.operation_name for c in handler.clauses)
        assert op_names == ("Chunk", "Complete")
        for clause in handler.clauses:
            assert isinstance(clause, IRHandlerClause)

    def test_desugared_handler_body_is_empty_no_inline_perform(self) -> None:
        """`stream<τ>` is a passive consumer — its `in { body }` is empty.

        Perform sites are driven externally by the host (the network
        layer feeding chunks), not by inline program code. The Rust
        runtime treats this as the canonical "subscribe + dispatch"
        pattern.
        """
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        assert handler.body == ()


# ──────────────────────────────────────────────────────────────────────
#  TestClauseSemantics — Chunk resumes, Complete aborts
# ──────────────────────────────────────────────────────────────────────


class TestClauseSemantics:
    """`Chunk` clause ends in `resume`; `Complete` clause ends in `abort`."""

    def test_chunk_clause_ends_with_resume(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        chunk = handler.clauses[0]
        assert chunk.operation_name == "Chunk"
        assert chunk.parameter_names == ("chunk",)
        # Body = original on_chunk body + synthetic resume.
        assert len(chunk.body) == 2
        assert isinstance(chunk.body[-1], IRResume)
        # The synthetic resume targets the synthetic frame.
        assert chunk.body[-1].frame_id == handler.frame_id

    def test_complete_clause_ends_with_abort(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        complete = handler.clauses[1]
        assert complete.operation_name == "Complete"
        assert complete.parameter_names == ("response",)
        # Body = original on_complete body + synthetic abort.
        assert len(complete.body) == 2
        assert isinstance(complete.body[-1], IRAbort)
        assert complete.body[-1].frame_id == handler.frame_id

    def test_empty_handlers_still_get_resume_abort(self) -> None:
        """A `stream<T>` with no on_chunk / on_complete still gets the
        synthetic resume + abort terminators (the clauses are well-typed
        even when empty of user code)."""
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Token>\n"
            "  }\n"
            "}"
        )
        handler = _stream_in(ir).desugared_handler
        assert isinstance(handler.clauses[0].body[0], IRResume)
        assert isinstance(handler.clauses[1].body[0], IRAbort)


# ──────────────────────────────────────────────────────────────────────
#  TestCPSIntegration — frame_id allocated from per-flow CPS counter
# ──────────────────────────────────────────────────────────────────────


class TestCPSIntegration:
    """Synthetic stream frames share the per-flow CPS namespace."""

    def test_two_streams_in_same_flow_get_distinct_frame_ids(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S1 { stream<Token> }\n"
            "  step S2 { stream<Token> }\n"
            "}"
        )
        flow = ir.flows[0]
        frames = []
        for st in flow.steps:
            for n in st.body:
                if isinstance(n, IRStreamSpec):
                    frames.append(n.desugared_handler.frame_id)
        assert len(frames) == 2
        assert frames[0] != frames[1]

    def test_stream_frame_id_does_not_collide_with_user_handler(self) -> None:
        """A `stream<τ>` and a user-written `handle E { ... } in {}` in
        the same flow get distinct frame_ids (both pull from the same
        per-flow counter via `_next_frame_id`)."""
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "    stream<Token>\n"
            "  }\n"
            "}"
        )
        flow = ir.flows[0]
        step = flow.steps[0]
        ids = []
        for n in step.body:
            if isinstance(n, IRHandlerFrame):
                ids.append(n.frame_id)
            elif isinstance(n, IRStreamSpec):
                ids.append(n.desugared_handler.frame_id)
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_per_flow_counter_resets_for_streams(self) -> None:
        """Each flow gets its own frame_id namespace — two flows each
        with one stream both start at the same baseline."""
        ir = _ir(
            "flow F1() -> Unit { step S { stream<Token> } }\n"
            "flow F2() -> Unit { step S { stream<Token> } }"
        )
        # Both flows start fresh (frame_id=0 for the synthetic stream).
        for flow in ir.flows:
            stream = next(
                n for n in flow.steps[0].body if isinstance(n, IRStreamSpec)
            )
            assert stream.desugared_handler.frame_id == 0


# ──────────────────────────────────────────────────────────────────────
#  TestSerialization — IR shape serialises for cross-stack contract
# ──────────────────────────────────────────────────────────────────────


class TestSerialization:
    """The desugared field serialises cleanly to JSON IR."""

    def test_desugared_handler_serialises_with_correct_node_type(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        spec_dict = _stream_in(ir).to_dict()
        assert spec_dict["node_type"] == "stream_spec"
        assert "desugared_handler" in spec_dict
        handler_dict = spec_dict["desugared_handler"]
        assert handler_dict["node_type"] == "handler_frame"
        assert handler_dict["effect_names"] == ("_StreamBuiltin",)

    def test_desugared_clauses_serialise_with_chunk_complete_names(self) -> None:
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        spec_dict = _stream_in(ir).to_dict()
        clauses = spec_dict["desugared_handler"]["clauses"]
        names = tuple(c["operation_name"] for c in clauses)
        assert names == ("Chunk", "Complete")
        # Each clause's body has the synthetic resume / abort
        # serialised so the Rust runtime can dispatch them.
        chunk_body = clauses[0]["body"]
        complete_body = clauses[1]["body"]
        assert chunk_body[-1]["node_type"] == "resume"
        assert complete_body[-1]["node_type"] == "abort"

    def test_old_consumers_can_ignore_new_field(self) -> None:
        """A consumer that only reads the legacy fields still works
        (D8 — the new field is additive, not breaking)."""
        ir = _ir(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    stream<Document> {\n"
            "      on_chunk: { reason about a { depth: 1 } }\n"
            "      on_complete: { reason about b { depth: 1 } }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        spec_dict = _stream_in(ir).to_dict()
        # Legacy fields all present + sensible values.
        assert spec_dict["element_type"] == "Document"
        assert spec_dict["initial_gradient"] == "doubt"
        assert len(spec_dict["on_chunk_body"]) == 1
        assert len(spec_dict["on_complete_body"]) == 1
