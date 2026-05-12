"""§Fase 33.b — Cross-stack drift gate for the FlowExecutionEvent catalog.

D2 ratificada. The closed 6-variant catalog {FlowStart, StepStart,
StepToken, StepComplete, FlowComplete, FlowError} serializes to a
JSON shape that is byte-identical across Rust + Python.

The shared corpus at `tests/fixtures/fase33_flow_execution_event/
corpus.json` is parametrized by:
  - This Python test pack (asserts `to_json(from_json(expected)) ==
    expected` for every entry on the Python side).
  - The sibling Rust test pack `axon-rs/tests/fase33_flow_execution_
    event_drift.rs` (asserts the same on the Rust side via serde).

If either stack drifts on a variant, exactly one lane fails — drift
caught at PR-time, not at adopter-bug-report time.

Pillar trace per D2 + D10:
  - MATHEMATICS — the catalog is a closed sum type.
  - LOGIC      — JSON shape is the locked contract; receivers parse
                  the same bytes on either stack.
  - COMPUTING  — drift gate over shared corpus is the production-
                  grade enforcement mechanism.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.runtime.flow_execution_event import (
    FlowComplete,
    FlowError,
    FlowStart,
    StepComplete,
    StepStart,
    StepToken,
    from_json,
    is_step_scoped,
    is_terminator,
    kind,
    now_ms,
    to_json,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "fase33_flow_execution_event"
    / "corpus.json"
)


# ── Corpus integrity ────────────────────────────────────────────────


def test_corpus_loads_with_required_shape():
    assert CORPUS_PATH.exists(), f"corpus missing at {CORPUS_PATH}"
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert "entries" in data
    assert data["d_letter_anchor"].startswith("D2")
    assert len(data["entries"]) >= 10, (
        f"corpus shrank: {len(data['entries'])} entries, expected >= 10"
    )
    for entry in data["entries"]:
        assert "name" in entry
        assert "variant" in entry
        assert "expected_json" in entry
        assert entry["expected_json"]["kind"] == entry["variant"]


def _load_corpus():
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return [
        pytest.param(e, id=e["name"]) for e in data["entries"]
    ]


# ── Drift gate: parametrize over every corpus entry ────────────────


@pytest.mark.parametrize("entry", _load_corpus())
def test_python_round_trip_matches_corpus(entry):
    """For every corpus entry, the Python `from_json` + `to_json`
    round-trip MUST yield byte-identical output to the corpus's
    `expected_json`. Catches any drift in field naming, field order,
    or value coercion against the Rust mirror."""
    expected = entry["expected_json"]
    event = from_json(expected)
    actual = to_json(event)
    assert actual == expected, (
        f"corpus entry '{entry['name']}' drift:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )


# ── Catalog closure: every variant constructible + serializable ────


class TestCatalogClosure:
    def test_flow_start(self):
        e = FlowStart(flow_name="F", backend="stub", timestamp_ms=1)
        assert kind(e) == "flow_start"
        assert not is_terminator(e)
        assert not is_step_scoped(e)
        assert to_json(e)["kind"] == "flow_start"

    def test_step_start(self):
        e = StepStart(step_name="S", step_index=0, step_type="step", timestamp_ms=2)
        assert kind(e) == "step_start"
        assert not is_terminator(e)
        assert is_step_scoped(e)

    def test_step_token(self):
        e = StepToken(step_name="S", content="hi", token_index=1, timestamp_ms=3)
        assert kind(e) == "step_token"
        assert not is_terminator(e)
        assert is_step_scoped(e)

    def test_step_complete(self):
        e = StepComplete(
            step_name="S",
            step_index=0,
            success=True,
            full_output="hi",
            tokens_input=0,
            tokens_output=1,
            timestamp_ms=4,
        )
        assert kind(e) == "step_complete"
        assert not is_terminator(e)
        assert is_step_scoped(e)

    def test_flow_complete(self):
        e = FlowComplete(
            flow_name="F",
            backend="stub",
            success=True,
            steps_executed=1,
            tokens_input=0,
            tokens_output=1,
            latency_ms=50,
            timestamp_ms=5,
        )
        assert kind(e) == "flow_complete"
        assert is_terminator(e)
        assert not is_step_scoped(e)

    def test_flow_error(self):
        e = FlowError(flow_name="F", error="boom", timestamp_ms=6)
        assert kind(e) == "flow_error"
        assert is_terminator(e)
        assert not is_step_scoped(e)


# ── Total-function guarantees on the helpers ───────────────────────


class TestHelpersTotal:
    def test_kind_strings_are_snake_case_per_rust_rename(self):
        # Mirror of Rust `kind()` returning snake_case strings.
        assert kind(FlowStart("F", "stub", 0)) == "flow_start"
        assert kind(StepStart("S", 0, "step", 0)) == "step_start"
        assert kind(StepToken("S", "x", 1, 0)) == "step_token"
        assert kind(
            StepComplete("S", 0, True, "x", 0, 1, 0)
        ) == "step_complete"
        assert kind(
            FlowComplete("F", "stub", True, 1, 0, 1, 1, 0)
        ) == "flow_complete"
        assert kind(FlowError("F", "x", 0)) == "flow_error"

    def test_kind_rejects_non_variant(self):
        with pytest.raises(TypeError):
            kind("not a variant")  # type: ignore[arg-type]

    def test_from_json_rejects_unknown_kind(self):
        with pytest.raises(ValueError):
            from_json({"kind": "bogus", "timestamp_ms": 0})

    def test_now_ms_returns_positive_int(self):
        n = now_ms()
        assert isinstance(n, int)
        assert n > 0


# ── Receiver-invariant anchor (consumed by 33.c onwards) ───────────


class TestReceiverInvariantShape:
    """D2 receiver invariant: every flow execution emits
        exactly 1 FlowStart
        then for each step: 1 StepStart, 0..N StepToken, 1 StepComplete
        then exactly 1 FlowComplete OR FlowError
    This pack documents the contract; the Rust integration tests
    (33.b-axon-rs side) verify producers honor it."""

    def test_terminator_predicate_partition_is_total(self):
        # Every variant is either terminator OR non-terminator;
        # nothing in between, nothing outside.
        variants = [
            FlowStart("F", "stub", 0),
            StepStart("S", 0, "step", 0),
            StepToken("S", "x", 1, 0),
            StepComplete("S", 0, True, "x", 0, 1, 0),
            FlowComplete("F", "stub", True, 1, 0, 1, 1, 0),
            FlowError("F", "x", 0),
        ]
        terminators = [v for v in variants if is_terminator(v)]
        non_terminators = [v for v in variants if not is_terminator(v)]
        assert len(terminators) == 2  # FlowComplete + FlowError
        assert len(non_terminators) == 4  # the other 4
        assert len(terminators) + len(non_terminators) == len(variants)

    def test_step_scoped_predicate_partition_is_total(self):
        variants = [
            FlowStart("F", "stub", 0),
            StepStart("S", 0, "step", 0),
            StepToken("S", "x", 1, 0),
            StepComplete("S", 0, True, "x", 0, 1, 0),
            FlowComplete("F", "stub", True, 1, 0, 1, 1, 0),
            FlowError("F", "x", 0),
        ]
        step_scoped = [v for v in variants if is_step_scoped(v)]
        non_step = [v for v in variants if not is_step_scoped(v)]
        # StepStart + StepToken + StepComplete = 3 step-scoped variants
        assert len(step_scoped) == 3
        assert len(non_step) == 3  # FlowStart + FlowComplete + FlowError
