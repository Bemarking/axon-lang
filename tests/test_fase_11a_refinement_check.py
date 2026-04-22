"""
Unit tests — §λ-L-E Fase 11.a Python refinement_check pass.

The pass is the Python mirror of the Rust
``check_refinement_and_stream_contracts`` in type_checker.rs; a
parity test in ``tests/parity/`` asserts that both sides emit the
same diagnostic count on the same AST shape.
"""

from __future__ import annotations

from axon.compiler.refinement_check import (
    check_flow_refinement_and_stream,
    classify_effect,
    effect_carries_backpressure,
    effect_carries_trust_proof,
    is_refinement_type,
    is_stream_type,
    is_trusted_type,
    is_untrusted_type,
    tool_declares_backpressure,
    tool_declares_trust_proof,
)


# ── Classifier helpers ──────────────────────────────────────────────


def test_classify_effect_plain_name() -> None:
    assert classify_effect("io") == ("io", None)


def test_classify_effect_composite() -> None:
    assert classify_effect("stream:drop_oldest") == ("stream", "drop_oldest")
    assert classify_effect("trust:hmac") == ("trust", "hmac")


def test_stream_type_recognition_is_case_sensitive() -> None:
    assert is_stream_type("Stream")
    assert not is_stream_type("stream")
    assert not is_stream_type("Iterator")


def test_refinement_type_recognition() -> None:
    assert is_refinement_type("Trusted")
    assert is_refinement_type("Untrusted")
    assert is_trusted_type("Trusted")
    assert is_untrusted_type("Untrusted")
    assert not is_refinement_type("Option")


def test_effect_carries_backpressure() -> None:
    assert effect_carries_backpressure("stream:drop_oldest")
    assert effect_carries_backpressure("stream:fail")
    assert not effect_carries_backpressure("stream")
    assert not effect_carries_backpressure("stream:retry_forever")
    assert not effect_carries_backpressure("io")


def test_effect_carries_trust_proof() -> None:
    assert effect_carries_trust_proof("trust:hmac")
    assert effect_carries_trust_proof("trust:ed25519")
    assert not effect_carries_trust_proof("trust")
    assert not effect_carries_trust_proof("trust:crc32")


def test_tool_declares_backpressure_aggregate() -> None:
    assert tool_declares_backpressure(["io", "stream:drop_oldest"])
    assert not tool_declares_backpressure(["io", "network"])


def test_tool_declares_trust_proof_aggregate() -> None:
    assert tool_declares_trust_proof(["io", "trust:hmac"])
    assert not tool_declares_trust_proof(["io"])


# ── Flow-level pass ─────────────────────────────────────────────────


def _run(
    *,
    param_types: list[str],
    return_type: str | None = None,
    apply_refs: list[str] | None = None,
    tool_effects: dict[str, list[str]] | None = None,
) -> list[str]:
    diags = check_flow_refinement_and_stream(
        flow_name="Flow",
        flow_loc_line=1,
        flow_loc_column=0,
        param_type_names=param_types,
        return_type_name=return_type,
        apply_refs=apply_refs or [],
        tool_effects_by_name=tool_effects or {},
    )
    return [d.message for d in diags]


def test_flow_without_stream_or_untrusted_has_no_diagnostics() -> None:
    msgs = _run(param_types=["Document"])
    assert msgs == []


def test_stream_parameter_without_matching_tool_errors() -> None:
    msgs = _run(param_types=["Stream"])
    assert any("Stream<T>" in m and "backpressure policy" in m for m in msgs)


def test_stream_parameter_with_tool_passes() -> None:
    msgs = _run(
        param_types=["Stream"],
        apply_refs=["ingest"],
        tool_effects={"ingest": ["stream:drop_oldest"]},
    )
    assert not any("backpressure policy" in m for m in msgs)


def test_stream_return_type_triggers_check() -> None:
    msgs = _run(param_types=[], return_type="Stream")
    assert any("Stream<T>" in m for m in msgs)


def test_untrusted_parameter_without_verifier_errors() -> None:
    msgs = _run(param_types=["Untrusted"])
    assert any("Untrusted<T>" in m and "catalogue verifiers" in m for m in msgs)


def test_untrusted_with_matching_trust_proof_passes() -> None:
    msgs = _run(
        param_types=["Untrusted"],
        apply_refs=["verify"],
        tool_effects={"verify": ["trust:hmac"]},
    )
    assert not any("catalogue verifiers" in m for m in msgs)


def test_both_constraints_emit_two_diagnostics() -> None:
    msgs = _run(param_types=["Stream", "Untrusted"])
    assert len(msgs) == 2
    assert any("Stream<T>" in m for m in msgs)
    assert any("Untrusted<T>" in m for m in msgs)


def test_tool_reference_not_in_tool_map_does_not_count() -> None:
    # An `apply: missing_tool` reference to a tool that doesn't
    # exist in our map leaves both observations unsatisfied.
    msgs = _run(
        param_types=["Stream", "Untrusted"],
        apply_refs=["missing_tool"],
        tool_effects={},
    )
    assert len(msgs) == 2


def test_trusted_parameter_does_not_impose_obligation() -> None:
    # A flow that receives already-Trusted data carries no new
    # verification obligation.
    msgs = _run(param_types=["Trusted"])
    assert msgs == []
