"""§Fase 33.z.k.b (v1.28.0) — Python parser grammar tests for the
parametrized SSE wire-format dialect grammar `transport: sse(<dialect>)`.

Mirrors `axon-frontend/tests/fase33z_k_b_dialect_grammar.rs` byte-for-
byte (D7 cross-stack contract). Same 7 test cells; same expected
outcomes."""

from __future__ import annotations

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import (
    AxonParseError,
    Parser,
    _AXONENDPOINT_TRANSPORT_DIALECTS,
)


def _parse(src: str):
    tokens = Lexer(src).tokenize()
    return Parser(tokens).parse()


def _endpoint(prog, name: str):
    from axon.compiler.ast_nodes import AxonEndpointDefinition

    for decl in prog.declarations:
        if isinstance(decl, AxonEndpointDefinition) and decl.name == name:
            return decl
    raise AssertionError(f"axonendpoint {name} not found")


# ─── §1 — Bare `transport: sse` parses with empty dialect ──────────


def test_s1_bare_transport_sse_parses_with_empty_dialect_d6():
    src = (
        'flow F() -> Unit { step S { ask: "x" output: Stream<Token> } }\n'
        'axonendpoint E { method: POST path: "/x" execute: F transport: sse }'
    )
    prog = _parse(src)
    ae = _endpoint(prog, "E")
    assert ae.transport == "sse"
    assert ae.transport_explicit is True
    assert ae.transport_dialect == "", (
        "33.z.k.b: bare `transport: sse` resolves dialect at runtime per "
        "the algebraic-effect predicate; parser leaves transport_dialect empty"
    )


# ─── §2 — `transport: sse(<dialect>)` parses dialect into AST ──────


@pytest.mark.parametrize("dialect", ["axon", "openai", "anthropic"])
def test_s2_transport_sse_dialect_parses(dialect: str) -> None:
    src = (
        'flow F() -> Unit { step S { ask: "x" output: Stream<Token> } }\n'
        f'axonendpoint E {{ method: POST path: "/x" execute: F transport: sse({dialect}) }}'
    )
    prog = _parse(src)
    ae = _endpoint(prog, "E")
    assert ae.transport == "sse"
    assert ae.transport_dialect == dialect


# ─── §3 — Unknown dialect errors with smart-suggest ────────────────


def test_s3_unknown_dialect_errors_with_smart_suggest():
    src = (
        'flow F() -> Unit { step S { ask: "x" output: Stream<Token> } }\n'
        'axonendpoint E { method: POST path: "/x" execute: F transport: sse(opennai) }'
    )
    with pytest.raises(AxonParseError) as excinfo:
        _parse(src)
    msg = str(excinfo.value).lower()
    assert "invalid sse dialect" in msg and "opennai" in msg


# ─── §4 — `json(<dialect>)` errors — only sse takes parametrization ─


def test_s4_json_dialect_param_errors():
    src = (
        'flow F() -> Unit { step S { ask: "x" } }\n'
        'axonendpoint E { method: POST path: "/x" execute: F transport: json(openai) }'
    )
    with pytest.raises(AxonParseError) as excinfo:
        _parse(src)
    assert "only valid for `sse`" in str(excinfo.value) or "json" in str(excinfo.value).lower()


# ─── §5 — `ndjson(<dialect>)` errors — same rule ───────────────────


def test_s5_ndjson_dialect_param_errors():
    src = (
        'flow F() -> Unit { step S { ask: "x" output: Stream<Token> } }\n'
        'axonendpoint E { method: POST path: "/x" execute: F transport: ndjson(axon) }'
    )
    with pytest.raises(AxonParseError) as excinfo:
        _parse(src)
    msg = str(excinfo.value).lower()
    assert "only valid for `sse`" in msg or "ndjson" in msg


# ─── §6 — Missing closing paren errors ─────────────────────────────


def test_s6_missing_rparen_errors():
    src = (
        'flow F() -> Unit { step S { ask: "x" output: Stream<Token> } }\n'
        'axonendpoint E { method: POST path: "/x" execute: F transport: sse(openai }'
    )
    with pytest.raises(AxonParseError) as excinfo:
        _parse(src)
    msg = str(excinfo.value).lower()
    assert ")" in msg or "paren" in msg or "expected" in msg


# ─── §7 — Closed-catalog cardinality pin ───────────────────────────


def test_s7_dialect_catalog_exact_three():
    assert len(_AXONENDPOINT_TRANSPORT_DIALECTS) == 3, (
        "33.z.k.b Q3 ratification: vertical-grounded scope = exactly 3 "
        "dialects {axon, openai, anthropic}. Adding a 4th requires a "
        "deliberate sub-fase + cross-stack drift gate update."
    )
    assert _AXONENDPOINT_TRANSPORT_DIALECTS == frozenset({"axon", "openai", "anthropic"}), (
        "33.z.k.b: cross-stack drift — Python catalog must match the "
        "Rust frontend's AXONENDPOINT_TRANSPORT_DIALECTS verbatim"
    )
