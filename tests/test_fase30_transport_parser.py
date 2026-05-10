"""§Fase 30.b — Parser test pack for `transport` + `keepalive` fields.

D1–D8 ratified 2026-05-10. Covers:

  * Defaults (D1: transport = "json" when field absent)
  * Closed transport enum (D2): {json, sse, ndjson} accepted; everything
    else rejected with smart-suggest hint (Fase 28.e)
  * Closed keepalive enum (D6): {5s, 15s, 30s, 60s} accepted; everything
    else rejected with smart-suggest hint
  * Cross-stack drift gate (D7) parametrized over the shared fixture
    corpus at `tests/fixtures/fase30_transport/corpus.json` — the Rust
    integration test `axon-frontend/tests/fase30_drift_gate.rs` reads
    the same JSON and asserts byte-identical parse on every entry

The mirror test on the Rust side parametrizes over the same JSON;
if the two stacks ever disagree on what input X produces, exactly
one of the two test packs fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.ast_nodes import AxonEndpointDefinition
from axon.compiler.errors import AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "fase30_transport" / "corpus.json"
)


def _load_corpus() -> list[dict]:
    """Read the shared cross-stack corpus.

    Same JSON file read by `axon-frontend/tests/fase30_drift_gate.rs`.
    Each entry pins (source, expected_parse_ok, [expected_transport,
    expected_keepalive] | expected_error_contains).
    """
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CORPUS: list[dict] = _load_corpus()


def _parse_axonendpoint(src: str) -> AxonEndpointDefinition:
    """Parse a single-axonendpoint program and return the
    `AxonEndpointDefinition` node. Raises `AxonParseError` on
    parse failure (negative-test path)."""
    tokens = Lexer(src).tokenize()
    program = Parser(tokens).parse()
    node = program.declarations[0]
    assert isinstance(node, AxonEndpointDefinition), (
        f"expected AxonEndpointDefinition, got {type(node).__name__}"
    )
    return node


# ──────────────────────────────────────────────────────────────────
# TestCorpusFixtureIntegrity
# ──────────────────────────────────────────────────────────────────


class TestCorpusFixtureIntegrity:
    """Fail fast if the shared fixture is malformed before any
    contract assertion runs."""

    def test_corpus_loads(self):
        assert isinstance(CORPUS, list)
        assert len(CORPUS) >= 10

    def test_required_fields_present(self):
        for entry in CORPUS:
            assert "name" in entry
            assert "source" in entry
            assert "expected_parse_ok" in entry
            if entry["expected_parse_ok"]:
                assert "expected_transport" in entry
                assert "expected_keepalive" in entry
            else:
                assert "expected_error_contains" in entry

    def test_names_unique(self):
        names = [e["name"] for e in CORPUS]
        assert len(names) == len(set(names))

    def test_canonical_path(self):
        # The Rust integration test resolves this path relative to
        # the axon-lang repo root; lock the layout.
        assert CORPUS_PATH.is_file()
        assert CORPUS_PATH.parts[-3:] == (
            "fixtures",
            "fase30_transport",
            "corpus.json",
        )


# ──────────────────────────────────────────────────────────────────
# TestPythonAgainstCorpus — Python parser honors the golden contract
# ──────────────────────────────────────────────────────────────────


class TestPythonAgainstCorpus:
    @pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e["name"])
    def test_corpus_entry(self, entry: dict):
        src = entry["source"]
        if entry["expected_parse_ok"]:
            node = _parse_axonendpoint(src)
            assert node.transport == entry["expected_transport"], (
                f"{entry['name']}: transport={node.transport!r} "
                f"!= expected={entry['expected_transport']!r}"
            )
            assert node.keepalive == entry["expected_keepalive"], (
                f"{entry['name']}: keepalive={node.keepalive!r} "
                f"!= expected={entry['expected_keepalive']!r}"
            )
        else:
            with pytest.raises(AxonParseError) as ei:
                _parse_axonendpoint(src)
            assert entry["expected_error_contains"] in str(ei.value), (
                f"{entry['name']}: error message did not contain "
                f"{entry['expected_error_contains']!r}\n"
                f"  got: {ei.value}"
            )


# ──────────────────────────────────────────────────────────────────
# TestDefaults — D1 backwards-compat preserved
# ──────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_no_transport_field_yields_json_default(self):
        # D1: absent transport → "json"
        node = _parse_axonendpoint(
            "axonendpoint Plain { method: POST execute: F }"
        )
        assert node.transport == "json"
        assert node.keepalive == ""

    def test_default_preserved_with_other_fields(self):
        # Setting other fields doesn't disturb the transport default.
        node = _parse_axonendpoint(
            'axonendpoint X { method: POST path: "/x" execute: F '
            "shield: S retries: 3 timeout: 5s }"
        )
        assert node.transport == "json"
        assert node.keepalive == ""

    def test_explicit_json_equals_default(self):
        # `transport: json` explicit is observationally identical
        # to absence. Adopters who want to be explicit (audit
        # documentation) can write it; the AST shape matches.
        node_implicit = _parse_axonendpoint(
            "axonendpoint A { execute: F }"
        )
        node_explicit = _parse_axonendpoint(
            "axonendpoint A { execute: F transport: json }"
        )
        assert node_implicit.transport == node_explicit.transport == "json"


# ──────────────────────────────────────────────────────────────────
# TestTransportEnum — D2 closed enum {json, sse, ndjson}
# ──────────────────────────────────────────────────────────────────


class TestTransportEnum:
    @pytest.mark.parametrize("val", ["json", "sse", "ndjson"])
    def test_valid_transport_values_accepted(self, val: str):
        node = _parse_axonendpoint(
            f"axonendpoint X {{ execute: F transport: {val} }}"
        )
        assert node.transport == val

    def test_invalid_transport_typo_triggers_smart_suggest(self):
        # `sssee` is dist=1 from `sse` → smart-suggest fires.
        with pytest.raises(AxonParseError) as ei:
            _parse_axonendpoint(
                "axonendpoint X { execute: F transport: sssee }"
            )
        msg = str(ei.value)
        assert "Invalid transport 'sssee'" in msg
        assert "Did you mean `sse`?" in msg

    def test_invalid_transport_far_no_suggest(self):
        # `qwerty` is too far from any enum value (>2 edits).
        # No suggest hint appended — message is honest about the
        # rejection without misleading.
        with pytest.raises(AxonParseError) as ei:
            _parse_axonendpoint(
                "axonendpoint X { execute: F transport: qwerty }"
            )
        msg = str(ei.value)
        assert "Invalid transport 'qwerty'" in msg
        assert "Did you mean" not in msg

    def test_invalid_transport_unsupported_protocol(self):
        # Adopter writes `transport: websocket` thinking it's
        # supported; reject with smart-suggest (websocket is too
        # far from any of {json, sse, ndjson} → no hint, just
        # honest rejection).
        with pytest.raises(AxonParseError) as ei:
            _parse_axonendpoint(
                "axonendpoint X { execute: F transport: websocket }"
            )
        assert "Invalid transport 'websocket'" in str(ei.value)


# ──────────────────────────────────────────────────────────────────
# TestKeepaliveEnum — D6 closed enum {5s, 15s, 30s, 60s}
# ──────────────────────────────────────────────────────────────────


class TestKeepaliveEnum:
    @pytest.mark.parametrize("val", ["5s", "15s", "30s", "60s"])
    def test_valid_keepalive_values_accepted(self, val: str):
        node = _parse_axonendpoint(
            f"axonendpoint X {{ execute: F transport: sse keepalive: {val} }}"
        )
        assert node.keepalive == val

    def test_invalid_keepalive_no_unit(self):
        # Adopter typo: `keepalive: 15` (missing seconds suffix).
        with pytest.raises(AxonParseError) as ei:
            _parse_axonendpoint(
                "axonendpoint X { execute: F transport: sse keepalive: 15 }"
            )
        assert "Invalid keepalive" in str(ei.value)

    def test_invalid_keepalive_too_sparse(self):
        # `90s` would let AWS ALB 60s timeout fire — closed enum
        # prevents the adopter from shooting themselves in the foot.
        with pytest.raises(AxonParseError) as ei:
            _parse_axonendpoint(
                "axonendpoint X { execute: F transport: sse keepalive: 90s }"
            )
        assert "Invalid keepalive '90s'" in str(ei.value)


# ──────────────────────────────────────────────────────────────────
# TestFieldOrderIndependence
# ──────────────────────────────────────────────────────────────────


class TestFieldOrderIndependence:
    def test_transport_first(self):
        node = _parse_axonendpoint(
            'axonendpoint X { transport: sse method: POST execute: F path: "/x" }'
        )
        assert node.transport == "sse"
        assert node.method == "POST"

    def test_keepalive_before_transport(self):
        # Order doesn't matter; the parser builds the AST node
        # incrementally. (Type-checker 30.c will assert keepalive
        # is meaningful only when transport == sse; that's a
        # semantic check not a parse-order check.)
        node = _parse_axonendpoint(
            "axonendpoint X { keepalive: 15s transport: sse execute: F }"
        )
        assert node.keepalive == "15s"
        assert node.transport == "sse"


# ──────────────────────────────────────────────────────────────────
# TestUnknownFieldsStillSkipped — D9 backwards-compat
# ──────────────────────────────────────────────────────────────────


class TestUnknownFieldsStillSkipped:
    def test_unknown_field_does_not_break_parse(self):
        # The catch-all `_skip_value()` arm is preserved; new fields
        # never registered before still skip cleanly. Adopters who
        # land on a v1.20.0 client against a v1.21.0+ server (or
        # vice versa) don't trip on an unknown field.
        node = _parse_axonendpoint(
            "axonendpoint X { execute: F transport: sse "
            "future_field: some_value keepalive: 15s }"
        )
        assert node.transport == "sse"
        assert node.keepalive == "15s"
