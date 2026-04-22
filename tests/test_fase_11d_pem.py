"""
Unit tests — §λ-L-E Fase 11.d CognitiveState + ContinuityToken + backend.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from axon.runtime.pem import (
    CognitiveState,
    ContinuityToken,
    ContinuityTokenSigner,
    FixedPoint,
    InMemoryBackend,
    MemoryEntry,
    Q32_32_SCALE,
    StateDecodeError,
)
from axon.runtime.pem.backend import ExpiredError, NotFoundError
from axon.runtime.pem.continuity_token import (
    TokenExpired,
    TokenForgedOrRotated,
    TokenMalformed,
    new_token,
)


# ── FixedPoint roundtrip ──────────────────────────────────────────────


def test_fixed_point_scale_constant() -> None:
    assert Q32_32_SCALE == 2**32


def test_fixed_point_roundtrip_is_stable_across_cycles() -> None:
    originals = [0.0, 1e-5, 0.25, 0.5, 0.9999, 1.0]
    for v in originals:
        q1 = FixedPoint.from_f64(v)
        v1 = q1.to_f64()
        q2 = FixedPoint.from_f64(v1)
        assert q1 == q2, f"value {v} drifts between cycles"


def test_fixed_point_saturates_on_infinity() -> None:
    assert FixedPoint.from_f64(float("inf")).value == 2**63 - 1
    assert FixedPoint.from_f64(float("-inf")).value == -(2**63)


def test_fixed_point_vec_helpers() -> None:
    originals = [0.1, 0.25, 0.5]
    q = FixedPoint.vec_from_f64(originals)
    back = FixedPoint.vec_to_f64(q)
    q2 = FixedPoint.vec_from_f64(back)
    assert q == q2


# ── CognitiveState encode/decode ──────────────────────────────────────


def _make_state() -> CognitiveState:
    ts = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
    return CognitiveState(
        session_id="sess-1",
        tenant_id="alpha",
        flow_id="flow-transcribe",
        subject_user_id="usr-42",
        density_matrix=[
            FixedPoint.vec_from_f64([0.1, 0.2, 0.7]),
            FixedPoint.vec_from_f64([0.4, 0.4, 0.2]),
        ],
        belief_state={"confidence": 0.73},
        short_term_memory=[
            MemoryEntry(
                key="last_msg",
                payload={"text": "hi"},
                symbolic_refs=["audio-17"],
                stored_at=ts,
            )
        ],
        created_at=ts,
        last_updated_at=ts,
    )


def test_state_encode_decode_roundtrip() -> None:
    state = _make_state()
    blob = state.encode()
    decoded = CognitiveState.decode(blob)
    assert decoded == state


def test_density_matrix_bit_identical_after_three_cycles() -> None:
    state = _make_state()
    current = state
    for _ in range(3):
        current = CognitiveState.decode(current.encode())
    assert current.density_matrix == state.density_matrix


def test_decode_rejects_garbage() -> None:
    with pytest.raises(StateDecodeError):
        CognitiveState.decode(b"not json")


def test_decode_rejects_missing_required_fields() -> None:
    with pytest.raises(StateDecodeError):
        CognitiveState.decode(b"{}")


def test_encode_is_canonical_bytes() -> None:
    # Two states constructed with different field-insertion order
    # produce identical encoded bytes.
    state = _make_state()
    ts = state.created_at
    same_state = CognitiveState(
        created_at=ts,
        last_updated_at=ts,
        flow_id="flow-transcribe",
        tenant_id="alpha",
        session_id="sess-1",
        subject_user_id="usr-42",
        belief_state={"confidence": 0.73},
        density_matrix=state.density_matrix,
        short_term_memory=state.short_term_memory,
    )
    assert state.encode() == same_state.encode()


# ── ContinuityToken ──────────────────────────────────────────────────


def test_continuity_token_roundtrip() -> None:
    signer = ContinuityTokenSigner(b"\x07" * 32)
    tok = new_token("sess-1", timedelta(minutes=15))
    wire = signer.sign(tok)
    decoded = signer.verify(wire)
    assert decoded.session_id == "sess-1"
    # ms precision preserved.
    assert abs(
        (decoded.expires_at - tok.expires_at).total_seconds()
    ) < 0.001


def test_continuity_token_forgery_rejected() -> None:
    signer_a = ContinuityTokenSigner(b"\x01" * 32)
    signer_b = ContinuityTokenSigner(b"\x02" * 32)
    tok = new_token("sess-1", timedelta(minutes=15))
    wire = signer_a.sign(tok)
    with pytest.raises(TokenForgedOrRotated):
        signer_b.verify(wire)


def test_continuity_token_expired_rejected() -> None:
    signer = ContinuityTokenSigner(b"\x07" * 32)
    tok = ContinuityToken(
        session_id="sess-1",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    wire = signer.sign(tok)
    with pytest.raises(TokenExpired):
        signer.verify(wire)


def test_continuity_token_malformed_base64_rejected() -> None:
    signer = ContinuityTokenSigner(b"\x07" * 32)
    with pytest.raises(TokenMalformed):
        signer.verify("not-valid-base64!@#$")


def test_continuity_token_malformed_field_count_rejected() -> None:
    import base64

    signer = ContinuityTokenSigner(b"\x07" * 32)
    # Only 2 fields instead of 3.
    raw = base64.urlsafe_b64encode(b"sess-1\x1e9999").rstrip(b"=")
    with pytest.raises(TokenMalformed):
        signer.verify(raw.decode("ascii"))


# ── InMemoryBackend ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backend_persist_restore_roundtrip() -> None:
    backend = InMemoryBackend()
    state = _make_state()
    await backend.persist(
        state.session_id, state, timedelta(minutes=15)
    )
    restored = await backend.restore(state.session_id)
    assert restored == state


@pytest.mark.asyncio
async def test_backend_restore_unknown_raises() -> None:
    backend = InMemoryBackend()
    with pytest.raises(NotFoundError):
        await backend.restore("missing")


@pytest.mark.asyncio
async def test_backend_restore_expired_raises() -> None:
    backend = InMemoryBackend()
    state = _make_state()
    await backend.persist(
        state.session_id, state, timedelta(seconds=-5)
    )
    with pytest.raises(ExpiredError):
        await backend.restore(state.session_id)


@pytest.mark.asyncio
async def test_backend_evict_expired_sweeps_only_stale() -> None:
    backend = InMemoryBackend()
    stale = _make_state()
    object.__setattr__(stale, "session_id", "stale")
    fresh = _make_state()
    object.__setattr__(fresh, "session_id", "fresh")

    await backend.persist("stale", stale, timedelta(seconds=-10))
    await backend.persist("fresh", fresh, timedelta(minutes=30))
    removed = await backend.evict_expired(
        datetime.now(timezone.utc)
    )
    assert removed == 1
    with pytest.raises(NotFoundError):
        await backend.restore("stale")
    await backend.restore("fresh")


@pytest.mark.asyncio
async def test_backend_evict_is_idempotent() -> None:
    backend = InMemoryBackend()
    await backend.evict("nothing")
    state = _make_state()
    await backend.persist(
        state.session_id, state, timedelta(minutes=5)
    )
    await backend.evict(state.session_id)
    await backend.evict(state.session_id)
    with pytest.raises(NotFoundError):
        await backend.restore(state.session_id)


# ── End-to-end reconnect scenario ───────────────────────────────────


@pytest.mark.asyncio
async def test_end_to_end_reconnect_flow() -> None:
    signer = ContinuityTokenSigner(b"\x09" * 32)
    backend = InMemoryBackend()

    # 1. Pre-disconnect snapshot.
    state = _make_state()
    await backend.persist(
        state.session_id, state, timedelta(minutes=15)
    )

    # 2. Server mints handshake for the client.
    handshake = new_token(state.session_id, timedelta(minutes=15))
    wire = signer.sign(handshake)

    # 3. Client reconnects with wire token. Server verifies then
    #    restores.
    parsed = signer.verify(wire)
    assert parsed.session_id == state.session_id

    rehydrated = await backend.restore(parsed.session_id)
    assert rehydrated.density_matrix == state.density_matrix
    assert rehydrated.short_term_memory == state.short_term_memory


@pytest.mark.asyncio
async def test_reconnect_with_forged_token_does_not_reach_backend() -> None:
    real_signer = ContinuityTokenSigner(b"\x09" * 32)
    attacker_signer = ContinuityTokenSigner(b"\x99" * 32)
    backend = InMemoryBackend()

    state = _make_state()
    await backend.persist(
        state.session_id, state, timedelta(minutes=15)
    )

    forged_wire = attacker_signer.sign(
        new_token(state.session_id, timedelta(minutes=15))
    )
    with pytest.raises(TokenForgedOrRotated):
        real_signer.verify(forged_wire)
