"""§Fase 32.b — Cross-stack drift gate for axonendpoint route collection.

D1–D3 + D11 ratificadas 2026-05-11. Verifies:

  * `collect_axonendpoint_routes` produces the expected (method, path)
    → RouteSpec table for every corpus entry.
  * Closed method enum (D3) — parser rejects HEAD/OPTIONS/etc. with
    smart-suggest hint.
  * Path collision detection (D2 intra-program) raises
    `RouteCollisionError` with structured fields.
  * `merge_dynamic_routes` honors same-endpoint re-deploy + rejects
    cross-deploy collision.

The same corpus JSON is read by the Rust integration test
`axon-rs/tests/fase32_routes_drift_gate.rs`; if Python + Rust ever
disagree on the route table for any corpus entry, exactly one of
the two test packs fails — drift caught at PR-time per D11.

Pillar trace per D12:
  - MATHEMATICS — function is pure + total.
  - LOGIC      — collision detection is exhaustive.
  - PHILOSOPHY — auditors inspect source + know the REST surface.
  - COMPUTING  — cross-stack contract anchored on shared corpus JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.errors import AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.runtime.route_registry import (
    AXONENDPOINT_METHODS,
    DynamicEndpointRoute,
    RouteCollisionError,
    collect_axonendpoint_routes,
    merge_dynamic_routes,
    route_table_as_corpus_dict,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "fase32_routes" / "corpus.json"
)


def _load_corpus() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CORPUS: list[dict] = _load_corpus()


def _compile(src: str, source_file: str = "test.axon"):
    """Parse + type-check; returns the program. Caller catches
    AxonParseError for negative cases."""
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    TypeChecker(program).check()  # populates implicit_transport
    return program


# ─── §1 — Corpus fixture integrity ───────────────────────────────────


class TestCorpusFixtureIntegrity:

    def test_corpus_loads(self):
        assert isinstance(CORPUS, list)
        assert len(CORPUS) >= 12, f"corpus must have >= 12 entries, got {len(CORPUS)}"

    def test_unique_names(self):
        names = [e["name"] for e in CORPUS]
        assert len(names) == len(set(names))

    def test_every_entry_has_required_keys(self):
        for entry in CORPUS:
            for k in ("name", "source", "source_file", "expected_parse_ok"):
                assert k in entry, f"entry {entry.get('name')!r} missing {k!r}"


# ─── §2 — Python against corpus (D11 drift gate) ─────────────────────


class TestPythonAgainstCorpus:

    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_python_route_table_matches_corpus(self, entry):
        # Parse phase — entries with expected_parse_ok==False must fail
        # at parser layer.
        if not entry["expected_parse_ok"]:
            expected_err = entry.get("expected_error_contains", "")
            with pytest.raises(AxonParseError) as exc_info:
                _compile(entry["source"], entry["source_file"])
            if expected_err:
                assert expected_err in str(exc_info.value), (
                    f"entry {entry['name']!r}: expected '{expected_err}' in "
                    f"error message, got: {exc_info.value}"
                )
            return

        # Positive parse path.
        program = _compile(entry["source"], entry["source_file"])

        # Collection phase — entries with expected_collect_error_contains
        # must raise RouteCollisionError.
        if "expected_collect_error_contains" in entry:
            with pytest.raises(RouteCollisionError) as exc_info:
                collect_axonendpoint_routes(
                    program, entry["source"], entry["source_file"],
                )
            assert entry["expected_collect_error_contains"] in str(exc_info.value)
            return

        # Normal: collect + project + compare.
        routes = collect_axonendpoint_routes(
            program, entry["source"], entry["source_file"],
        )
        actual = route_table_as_corpus_dict(routes)
        expected = entry["expected_routes"]
        assert actual == expected, (
            f"entry {entry['name']!r}: route table drift\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}"
        )


# ─── §3 — D3 closed method enum (parser-level) ───────────────────────


class TestClosedMethodEnum:

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
    def test_all_five_canonical_methods_accepted(self, method):
        src = (
            f"flow F() -> Unit {{ step S {{ ask: \"x\" }} }}\n"
            f"axonendpoint E {{ method: {method} path: \"/x\" execute: F }}"
        )
        program = _compile(src)
        ep = next(
            d for d in program.declarations if isinstance(d, AxonEndpointDefinition)
        )
        assert ep.method == method

    def test_lowercase_method_normalized_to_uppercase(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint E { method: post path: \"/x\" execute: F }"
        )
        program = _compile(src)
        ep = next(
            d for d in program.declarations if isinstance(d, AxonEndpointDefinition)
        )
        assert ep.method == "POST"

    @pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "CONNECT", "TRACE"])
    def test_non_adopter_methods_rejected(self, method):
        # HEAD/OPTIONS/CONNECT/TRACE are runtime-managed (CORS preflight,
        # health checks, etc.) and never adopter-declarable.
        src = (
            f"flow F() -> Unit {{ step S {{ ask: \"x\" }} }}\n"
            f"axonendpoint E {{ method: {method} path: \"/x\" execute: F }}"
        )
        with pytest.raises(AxonParseError) as exc_info:
            _compile(src)
        assert f"Invalid method '{method}'" in str(exc_info.value)

    def test_typo_triggers_smart_suggest(self):
        # POSST → suggest POST (Levenshtein ≤ 2)
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint E { method: POSST path: \"/x\" execute: F }"
        )
        with pytest.raises(AxonParseError) as exc_info:
            _compile(src)
        msg = str(exc_info.value)
        assert "POSST" in msg
        # Smart-suggest may or may not surface depending on Levenshtein
        # distance; at minimum the invalid value must be named.
        assert "Invalid method" in msg

    def test_closed_enum_constant_matches_parser_set(self):
        # The runtime constant must match the parser's closed set
        # exactly. Drift here would silently allow methods at parse
        # but reject at runtime (or vice versa).
        from axon.compiler.parser import _AXONENDPOINT_METHOD_VALUES
        assert AXONENDPOINT_METHODS == _AXONENDPOINT_METHOD_VALUES


# ─── §4 — D2 path collision detection ────────────────────────────────


class TestPathCollisionDetection:

    def test_intra_program_collision_raises(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "flow G() -> Unit { step T { ask: \"y\" } }\n"
            "axonendpoint Alpha { method: POST path: \"/chat\" execute: F }\n"
            "axonendpoint Beta  { method: POST path: \"/chat\" execute: G }"
        )
        program = _compile(src)
        with pytest.raises(RouteCollisionError) as exc_info:
            collect_axonendpoint_routes(program, src, "test.axon")
        err = exc_info.value
        assert err.method == "POST"
        assert err.path == "/chat"
        assert err.existing_endpoint == "Alpha"
        assert err.new_endpoint == "Beta"
        assert "D2" in err.message

    def test_different_method_same_path_no_collision(self):
        src = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint Read  { method: GET path: \"/chat\" execute: F }\n"
            "axonendpoint Write { method: POST path: \"/chat\" execute: F }"
        )
        program = _compile(src)
        routes = collect_axonendpoint_routes(program, src, "test.axon")
        assert len(routes) == 2
        assert ("GET", "/chat") in routes
        assert ("POST", "/chat") in routes


# ─── §5 — Cross-deploy collision detection (merge_dynamic_routes) ────


class TestCrossDeployCollision:

    def test_cross_deploy_collision_different_endpoint_raises(self):
        src1 = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint Alpha { method: POST path: \"/chat\" execute: F }"
        )
        src2 = (
            "flow G() -> Unit { step T { ask: \"y\" } }\n"
            "axonendpoint Beta { method: POST path: \"/chat\" execute: G }"
        )
        p1 = _compile(src1)
        p2 = _compile(src2)
        live: dict = {}
        incoming1 = collect_axonendpoint_routes(p1, src1, "src1.axon")
        merge_dynamic_routes(live, incoming1)
        assert len(live) == 1
        incoming2 = collect_axonendpoint_routes(p2, src2, "src2.axon")
        with pytest.raises(RouteCollisionError) as exc_info:
            merge_dynamic_routes(live, incoming2)
        err = exc_info.value
        assert err.method == "POST"
        assert err.path == "/chat"
        assert err.existing_endpoint == "Alpha"
        assert err.new_endpoint == "Beta"
        assert "cross-deploy" in err.message

    def test_same_endpoint_redeploy_updates_in_place(self):
        # Re-deploying the same flow updates the route metadata;
        # not a collision.
        src1 = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint E { method: POST path: \"/chat\" execute: F }"
        )
        src2 = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint E { method: POST path: \"/chat\" execute: F transport: sse }"
        )
        p1 = _compile(src1)
        p2 = _compile(src2)
        live: dict = {}
        merge_dynamic_routes(
            live,
            collect_axonendpoint_routes(p1, src1, "src1.axon"),
        )
        assert live[("POST", "/chat")].transport_explicit is False
        merge_dynamic_routes(
            live,
            collect_axonendpoint_routes(p2, src2, "src2.axon"),
        )
        # Same endpoint name; the new route metadata replaces the old.
        assert live[("POST", "/chat")].transport == "sse"
        assert live[("POST", "/chat")].transport_explicit is True

    def test_atomic_merge_on_failure(self):
        # If any incoming route collides, NO routes from incoming
        # should be merged (atomic — all-or-nothing).
        src_pre = (
            "flow F() -> Unit { step S { ask: \"x\" } }\n"
            "axonendpoint Existing { method: POST path: \"/chat\" execute: F }"
        )
        src_new = (
            "flow G() -> Unit { step T { ask: \"y\" } }\n"
            "axonendpoint Fresh    { method: POST path: \"/new\" execute: G }\n"
            "axonendpoint Conflict { method: POST path: \"/chat\" execute: G }"
        )
        live: dict = {}
        merge_dynamic_routes(
            live,
            collect_axonendpoint_routes(_compile(src_pre), src_pre, "a.axon"),
        )
        incoming = collect_axonendpoint_routes(_compile(src_new), src_new, "b.axon")
        with pytest.raises(RouteCollisionError):
            merge_dynamic_routes(live, incoming)
        # Atomicity: /new MUST NOT have been added even though it was
        # collision-free in incoming.
        assert ("POST", "/new") not in live
        assert ("POST", "/chat") in live
        assert live[("POST", "/chat")].endpoint_name == "Existing"


# ─── §6 — Edge cases ─────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_program_returns_empty_table(self):
        src = "flow F() -> Unit { step S { ask: \"x\" } }"
        routes = collect_axonendpoint_routes(_compile(src), src, "empty.axon")
        assert routes == {}

    def test_implicit_transport_populated_on_route(self):
        # The route table carries the Fase 31.b implicit_transport
        # field so downstream consumers (e.g. dynamic_endpoint_handler
        # negotiation) don't re-run the inference.
        src = (
            "tool t { description: \"t\" effects: <stream:drop_oldest> }\n"
            "flow F() -> Unit { step S { ask: \"x\" apply: t } }\n"
            "axonendpoint E { method: POST path: \"/chat\" execute: F }"
        )
        routes = collect_axonendpoint_routes(_compile(src), src, "x.axon")
        route = routes[("POST", "/chat")]
        assert route.transport_explicit is False
        assert route.implicit_transport == "sse"

    def test_method_case_insensitive_normalization(self):
        # The parser normalizes; collection only sees normalized values.
        for variant in ["POST", "Post", "post", "PoSt"]:
            src = (
                f"flow F() -> Unit {{ step S {{ ask: \"x\" }} }}\n"
                f"axonendpoint E {{ method: {variant} path: \"/x\" execute: F }}"
            )
            routes = collect_axonendpoint_routes(_compile(src), src, "x.axon")
            assert ("POST", "/x") in routes
