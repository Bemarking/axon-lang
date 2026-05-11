"""§Fase 31.b — Test pack for the Type-Driven Wire Inference predicate.

D1 ratified 2026-05-11 verbatim. Covers:

  * `_implicit_transport(endpoint, flow, symbol_lookup)` — the pure
    inference function.
  * `_compute_implicit_transports(program, symbol_lookup)` — the AST
    mutation walker invoked from `TypeChecker.check()`.
  * Cross-stack drift gate parametrized over the shared fixture
    corpus at `tests/fixtures/fase31_implicit_transport/corpus.json` —
    the Rust integration test
    `axon-frontend/tests/fase31_drift_gate.rs` reads the same JSON
    and asserts byte-identical inference on every entry (D7).

Four-pillar trace per D10:
  - MATHEMATICS — the function is total + deterministic.
  - LOGIC       — disjunction of three formal predicates (a, b, c).
  - PHILOSOPHY  — the language is the wire's source of truth.
  - COMPUTING   — explicit `transport: json` honors backwards-compat
                   (D3 opt-out preserved).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "fase31_implicit_transport" / "corpus.json"
)


def _load_corpus() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CORPUS: list[dict] = _load_corpus()


def _compile_and_get_endpoint(src: str, name: str) -> AxonEndpointDefinition:
    """Parse + type-check + return the named endpoint with
    `implicit_transport` attached."""
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    TypeChecker(program).check()
    for d in program.declarations:
        if isinstance(d, AxonEndpointDefinition) and d.name == name:
            return d
    raise AssertionError(f"axonendpoint {name!r} not found in program")


# ─── 1. Corpus integrity ────────────────────────────────────────────────


class TestCorpusFixtureIntegrity:
    """Fail fast if the shared corpus is malformed before any
    contract assertion runs."""

    def test_corpus_loads(self):
        assert isinstance(CORPUS, list)
        assert len(CORPUS) >= 20, (
            f"corpus must have >= 20 entries for meaningful coverage, got {len(CORPUS)}"
        )

    def test_every_entry_has_required_keys(self):
        for entry in CORPUS:
            for k in ("name", "source", "endpoint", "expected_implicit_transport"):
                assert k in entry, f"corpus entry {entry.get('name')!r} missing key {k!r}"

    def test_every_entry_name_unique(self):
        names = [e["name"] for e in CORPUS]
        assert len(names) == len(set(names)), "corpus entry names must be unique"

    def test_expected_values_in_closed_set(self):
        for e in CORPUS:
            v = e["expected_implicit_transport"]
            assert v in (None, "sse", "json"), (
                f"corpus entry {e['name']!r}: expected_implicit_transport "
                f"must be one of [null, 'sse', 'json'], got {v!r}"
            )


# ─── 2. Python against corpus (D7 drift gate) ──────────────────────────


class TestPythonAgainstCorpus:
    """Parametrized over the shared corpus — every entry's expected
    inference must match the Python type-checker's output. This is
    the D7 cross-stack contract; the Rust mirror reads the same JSON."""

    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_python_implicit_transport_matches_corpus(self, entry):
        expected = entry["expected_implicit_transport"]
        endpoint_name = entry["endpoint"]
        if endpoint_name is None or expected is None:
            # Sentinel rows that exercise the fixture walker only.
            return
        ep = _compile_and_get_endpoint(entry["source"], endpoint_name)
        assert ep.implicit_transport == expected, (
            f"drift on {entry['name']!r}: expected implicit_transport="
            f"{expected!r}, got {ep.implicit_transport!r}"
        )


# ─── 3. The three disjuncts of produces_stream — positive ──────────────


class TestDisjunctATypeLevel:
    """Disjunct (a) — step with `output: Stream<T>` triggers
    implicit sse on its hosting axonendpoint."""

    def test_disjunct_a_fires(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" output: Stream<Token> } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "sse"

    def test_stream_with_complex_inner_type(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" output: Stream<CustomT> } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "sse"


class TestDisjunctBEffectLevel:
    """Disjunct (b) — `apply: tool_name` (or `use tool()`) where
    tool declares `effects: <stream:<policy>>`."""

    @pytest.mark.parametrize(
        "policy", ["drop_oldest", "degrade_quality", "pause_upstream", "fail"]
    )
    def test_apply_ref_each_policy(self, policy):
        src = (
            f"tool t {{ description: \"t\" effects: <stream:{policy}> }}\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "sse", (
            f"policy={policy} expected sse, got {ep.implicit_transport!r}"
        )

    def test_apply_ref_unknown_name_falls_through(self):
        # apply: references a name that doesn't resolve to any tool
        # → no inference fires.
        src = (
            "flow F() -> Unit { step S { ask: \"x\" apply: ghost_tool } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "json"


# ─── 4. Negative space ─────────────────────────────────────────────────


class TestNoStreamNoImplicit:
    """No stream effect → no inference fires → default json."""

    def test_simple_flow_returns_json(self):
        src = (
            "flow F() -> Int { step S { ask: \"x\" output: Int } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "json"

    def test_tool_with_non_stream_effect_doesnt_trigger(self):
        src = (
            "tool t { description: \"t\" effects: <network> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "json"


# ─── 5. Explicit declaration wins (D3 + D1 declared path) ──────────────


class TestExplicitDeclarationWins:
    """When `transport:` is declared, the inference returns the
    declared value verbatim (sse) or applies D3 opt-out (json)."""

    def test_declared_sse_matches(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: sse }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "sse"
        assert ep.transport_explicit is True

    def test_declared_json_overrides_implicit(self):
        # Stream effects present but adopter opted out (D3).
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: json }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "json"
        assert ep.transport_explicit is True

    def test_declared_ndjson_becomes_sse(self):
        # D2 — ndjson namespace reserved; inferred as sse today.
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: ndjson }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "sse"


# ─── 6. transport_explicit flag (parser sets correctly) ────────────────


class TestTransportExplicitFlag:
    """The parser sets `transport_explicit` to True only when the
    source declares the field. This is the gate the inference uses."""

    def test_no_declaration_means_explicit_false(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.transport_explicit is False
        assert ep.transport == "json", (
            f"Dataclass D1 default preserved when field omitted, "
            f"got transport={ep.transport!r}"
        )

    def test_explicit_json_sets_flag_true(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: json }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.transport_explicit is True
        assert ep.transport == "json"

    def test_explicit_sse_sets_flag_true(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F transport: sse }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.transport_explicit is True
        assert ep.transport == "sse"


# ─── 7. Edge cases + defensive behavior ────────────────────────────────


class TestEdgeCases:
    """Defensive behavior — the inference must NEVER crash, and must
    converge to a deterministic value on every input shape."""

    def test_endpoint_with_unresolvable_execute_flow(self):
        src = "axonendpoint Orphan { method: POST path: \"/o\" execute: Ghost }"
        ep = _compile_and_get_endpoint(src, "Orphan")
        assert ep.implicit_transport == "json"

    def test_endpoint_without_execute_field(self):
        src = "axonendpoint Lonely { method: POST path: \"/l\" }"
        ep = _compile_and_get_endpoint(src, "Lonely")
        assert ep.implicit_transport == "json"

    def test_string_literal_with_stream_pattern_doesnt_trigger(self):
        # The AST-level predicate is precise; source-text patterns
        # inside string literals do NOT count.
        src = (
            "flow F() -> Unit { step S { ask: \"the keyword stream:fail must not match\" } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        ep = _compile_and_get_endpoint(src, "F")
        assert ep.implicit_transport == "json"


# ─── 8. Multi-axonendpoint same-flow isolation ─────────────────────────


class TestMultiAxonendpointIsolation:
    """Each axonendpoint's inference is independent — a sibling
    endpoint's explicit opt-out doesn't affect another's implicit
    inference."""

    def test_sibling_opt_out_doesnt_leak(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint E1 { method: POST path: \"/e1\" execute: F }\n"
            "axonendpoint E2 { method: POST path: \"/e2\" execute: F transport: json }"
        )
        tokens = Lexer(src).tokenize()
        program = Parser(tokens).parse()
        TypeChecker(program).check()
        endpoints = {
            d.name: d
            for d in program.declarations
            if isinstance(d, AxonEndpointDefinition)
        }
        assert endpoints["E1"].implicit_transport == "sse"
        assert endpoints["E2"].implicit_transport == "json"


# ─── 9. Idempotence of compute_implicit_transports ─────────────────────


class TestIdempotence:
    """Re-running the type-checker pass must not change the
    inference result (mathematical property: f(f(x)) == f(x))."""

    def test_double_check_pass_stable(self):
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint F { method: POST path: \"/f\" execute: F }"
        )
        tokens = Lexer(src).tokenize()
        program = Parser(tokens).parse()
        TypeChecker(program).check()
        first = next(
            d for d in program.declarations if isinstance(d, AxonEndpointDefinition)
        ).implicit_transport
        TypeChecker(program).check()
        second = next(
            d for d in program.declarations if isinstance(d, AxonEndpointDefinition)
        ).implicit_transport
        assert first == second == "sse"
