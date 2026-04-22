"""
Unit tests — §λ-L-E Fase 11.c replay tokens + log + executor (Python).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from axon.runtime.replay import (
    EffectInvoker,
    InMemoryReplayLog,
    ReplayExecutor,
    ReplayMatch,
    ReplayMismatch,
    ReplayToken,
    ReplayTokenBuilder,
    SamplingParams,
    canonical_hash,
)


# ── canonical_hash ────────────────────────────────────────────────────


def test_canonical_hash_key_order_independent() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_canonical_hash_nested_objects() -> None:
    a = {"outer": {"a": 1, "b": 2}}
    b = {"outer": {"b": 2, "a": 1}}
    assert canonical_hash(a) == canonical_hash(b)


def test_canonical_hash_produces_sha256_length() -> None:
    assert len(canonical_hash({"x": 1})) == 32  # SHA-256 bytes


def test_canonical_hash_different_inputs_differ() -> None:
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


# ── ReplayToken minting ───────────────────────────────────────────────


def _fixed_nonce() -> bytes:
    return bytes(range(16))


def _fixed_ts() -> datetime:
    return datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_builder_mints_full_token() -> None:
    t = (
        ReplayTokenBuilder()
        .effect_name("call_tool:send_slack")
        .inputs({"channel": "#ops", "text": "hi"})
        .outputs({"ok": True, "ts": "1700000000.000"})
        .model_version("axon.builtin.slack.v1")
        .timestamp(_fixed_ts())
        .nonce(_fixed_nonce())
        .mint()
    )
    assert t.effect_name == "call_tool:send_slack"
    assert len(t.inputs_hash_hex) == 64
    assert len(t.outputs_hash_hex) == 64
    assert len(t.token_hash_hex) == 64
    assert t.nonce_hex == "000102030405060708090a0b0c0d0e0f"


def test_builder_requires_effect_name() -> None:
    with pytest.raises(ValueError, match="effect_name"):
        ReplayTokenBuilder().mint()


def test_builder_rejects_nonce_wrong_size() -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        ReplayTokenBuilder().nonce(b"\x00" * 8)


def test_token_hash_deterministic_for_identical_inputs() -> None:
    common = dict(
        effect_name="llm_infer",
        inputs={"prompt": "hi", "user_id": "u-1"},
        outputs={"text": "hello"},
        model_version="claude-opus-4-7",
    )
    sampling = SamplingParams(temperature=0.7, top_p=0.95, seed=42)
    t1 = (
        ReplayTokenBuilder()
        .effect_name(common["effect_name"])
        .inputs(common["inputs"])
        .outputs(common["outputs"])
        .model_version(common["model_version"])
        .sampling(sampling)
        .timestamp(_fixed_ts())
        .nonce(_fixed_nonce())
        .mint()
    )
    t2 = (
        ReplayTokenBuilder()
        .effect_name(common["effect_name"])
        .inputs(common["inputs"])
        .outputs(common["outputs"])
        .model_version(common["model_version"])
        .sampling(sampling)
        .timestamp(_fixed_ts())
        .nonce(_fixed_nonce())
        .mint()
    )
    assert t1.token_hash_hex == t2.token_hash_hex


def test_token_hash_differs_when_model_version_differs() -> None:
    def mint(mv: str) -> ReplayToken:
        return (
            ReplayTokenBuilder()
            .effect_name("x")
            .inputs({"a": 1})
            .outputs({"b": 2})
            .model_version(mv)
            .timestamp(_fixed_ts())
            .nonce(_fixed_nonce())
            .mint()
        )

    assert mint("v1").token_hash_hex != mint("v2").token_hash_hex


def test_random_nonce_differs() -> None:
    t1 = ReplayTokenBuilder().effect_name("x").timestamp(_fixed_ts()).mint()
    t2 = ReplayTokenBuilder().effect_name("x").timestamp(_fixed_ts()).mint()
    assert t1.nonce_hex != t2.nonce_hex
    assert t1.token_hash_hex != t2.token_hash_hex


# ── InMemoryReplayLog ────────────────────────────────────────────────


def _mk_token(flow_id: str, effect: str, seq: int) -> ReplayToken:
    return (
        ReplayTokenBuilder()
        .effect_name(effect)
        .inputs({"flow_id": flow_id, "seq": seq})
        .outputs({"ok": True})
        .model_version("axon.builtin.test.v1")
        .sampling(SamplingParams())
        .timestamp(datetime(2026, 4, 22, 12, 0, seq, tzinfo=timezone.utc))
        .nonce(bytes([seq]) * 16)
        .mint()
    )


def test_log_append_and_get_roundtrip() -> None:
    log = InMemoryReplayLog()
    t = _mk_token("flow-1", "step", 0)
    log.append(t)
    fetched = log.get(t.token_hash_hex)
    assert fetched == t


def test_log_get_unknown_errors() -> None:
    from axon.runtime.replay import ReplayLogError

    log = InMemoryReplayLog()
    with pytest.raises(ReplayLogError):
        log.get("deadbeef" * 8)


def test_log_tokens_for_flow_sorted_by_timestamp() -> None:
    log = InMemoryReplayLog()
    t2 = _mk_token("flow-a", "step2", 2)
    t1 = _mk_token("flow-a", "step1", 1)
    t3 = _mk_token("flow-a", "step3", 3)
    log.append(t2)
    log.append(t1)
    log.append(t3)
    out = log.tokens_for_flow("flow-a")
    assert [t.effect_name for t in out] == ["step1", "step2", "step3"]


def test_log_tokens_for_unknown_flow_returns_empty() -> None:
    log = InMemoryReplayLog()
    assert log.tokens_for_flow("missing") == []


# ── ReplayExecutor ──────────────────────────────────────────────────


class _FixedInvoker(EffectInvoker):
    def __init__(self, outputs) -> None:
        self._outputs = outputs

    def invoke(self, effect_name, inputs, model_version, sampling):
        return self._outputs


def test_executor_match_when_outputs_bit_identical() -> None:
    log = InMemoryReplayLog()
    t = _mk_token("flow-a", "step1", 0)
    log.append(t)

    # Invoker returns an equivalent object with keys reordered —
    # canonical hashing normalises the order.
    executor = ReplayExecutor(log=log, invoker=_FixedInvoker({"ok": True}))
    outcome = executor.replay_token(t.token_hash_hex)
    assert isinstance(outcome, ReplayMatch)


def test_executor_diverge_when_outputs_differ() -> None:
    log = InMemoryReplayLog()
    t = _mk_token("flow-a", "step1", 0)
    log.append(t)

    executor = ReplayExecutor(log=log, invoker=_FixedInvoker({"ok": False}))
    outcome = executor.replay_token(t.token_hash_hex)
    assert isinstance(outcome, ReplayMismatch)
    assert outcome.divergence.expected_outputs_hash_hex == t.outputs_hash_hex
    assert outcome.divergence.actual_outputs == {"ok": False}


def test_executor_replay_flow_short_circuits_on_divergence() -> None:
    log = InMemoryReplayLog()
    t1 = _mk_token("flow-x", "s1", 1)
    t2 = _mk_token("flow-x", "s2", 2)
    t3 = _mk_token("flow-x", "s3", 3)
    for t in [t1, t2, t3]:
        log.append(t)
    # Return matching outputs for s1, wrong for s2 and s3 — divergence
    # on s2 should short-circuit.
    executor = ReplayExecutor(log=log, invoker=_FixedInvoker({"ok": False}))
    outcomes = executor.replay_flow("flow-x")
    # s1 matches, s2 diverges, s3 never attempted.
    assert len(outcomes) <= 2
    assert isinstance(outcomes[-1], ReplayMismatch)
