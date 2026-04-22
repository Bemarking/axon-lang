"""
Cross-phase integration + adversarial tests — §λ-L-E Fase 11.f.

Each test exercises more than one Fase 11 primitive so a regression
in composition surface (not just a single primitive) is caught here.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as stdlib_hmac
from datetime import datetime, timedelta, timezone

import pytest

from axon.compiler.legal_basis import (
    LEGAL_BASIS_CATALOG,
    Regulation,
    regulation_for,
)
from axon.compiler.legal_basis_check import (
    check_tool_sensitive_coherence,
)
from axon.compiler.refinement_check import (
    check_flow_refinement_and_stream,
)
from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer
from axon.runtime.ffi.symbolic_ptr import SymbolicPtr
from axon.runtime.ots import (
    MulawToPcm16,
    Pipeline,
    Resample,
    TransformerBackend,
    global_registry,
)
from axon.runtime.pem import (
    CognitiveState,
    ContinuityTokenSigner,
    FixedPoint,
    InMemoryBackend,
    MemoryEntry,
)
from axon.runtime.pem.continuity_token import (
    TokenExpired,
    TokenForgedOrRotated,
    new_token,
)
from axon.runtime.replay import (
    InMemoryReplayLog,
    ReplayExecutor,
    ReplayMatch,
    ReplayMismatch,
    ReplayTokenBuilder,
    SamplingParams,
    canonical_hash,
)
from axon.runtime.replay.executor import EffectInvoker
from axon.runtime.stream_primitive import (
    Stream,
    parse_backpressure_annotation,
)
from axon.runtime.trust import (
    TrustError,
    TrustProof,
    Trusted,
    assert_trusted,
    verify_hmac_sha256,
)


# ── Cross-phase integration: full audio stack ────────────────────────


@pytest.mark.asyncio
async def test_full_audio_stack_composes_across_every_primitive() -> None:
    # 1. INGRESS — HMAC-signed μ-law audio payload.
    key = b"webhook-signer"
    audio = bytes((i * 3) & 0xFF for i in range(200))
    tag = stdlib_hmac.new(key, audio, hashlib.sha256).digest()
    trusted = verify_hmac_sha256(audio, tag, key, key_id="webhook-v1")
    assert isinstance(trusted, Trusted)
    assert trusted.proof.proof is TrustProof.HMAC

    # 2. ZEROCOPY BUFFER with tenant tag.
    mulaw_buf = ZeroCopyBuffer(
        trusted.value, BufferKind.mulaw8()
    ).with_tenant("alpha")
    assert mulaw_buf.kind == BufferKind.mulaw8()

    # 3. OTS pipeline synthesis μ-law → PCM16 → 16k.
    reg = global_registry()
    step1 = Pipeline.from_registry(
        reg, BufferKind.mulaw8(), BufferKind.pcm16()
    )
    assert not step1.crosses_process_boundary()
    pcm_buf = step1.execute(mulaw_buf)
    assert pcm_buf.kind == BufferKind.pcm16()
    assert pcm_buf.tenant_id == "alpha"
    assert len(pcm_buf) == 400  # 2× width

    # 4. Stream<T> with backpressure, carrying the PCM buffer into a
    #    (simulated) transcriber.
    ann = parse_backpressure_annotation("drop_oldest")
    assert ann is not None
    stream: Stream[ZeroCopyBuffer] = Stream.new(capacity=4, annotation=ann)
    await stream.push(pcm_buf)
    received = await stream.pop()
    assert received is not None
    assert received.kind == pcm_buf.kind

    # 5. ReplayToken for the transcription effect.
    replay_log = InMemoryReplayLog()
    token = (
        ReplayTokenBuilder()
        .effect_name("llm_infer:whisper")
        .inputs(
            {
                "flow_id": "transcribe-flow-1",
                "audio_sha256": received.sha256().hex(),
            }
        )
        .outputs({"transcript": "hello world"})
        .model_version("openai/whisper-large-v3")
        .sampling(SamplingParams(temperature=0.0, seed=42))
        .timestamp(datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc))
        .nonce(bytes([5] * 16))
        .mint()
    )
    replay_log.append(token)
    assert replay_log.get(token.token_hash_hex).token_hash_hex == token.token_hash_hex

    # 6. SymbolicPtr fan-out — two consumers of the trusted buffer
    #    without any byte copy.
    origin = SymbolicPtr(pcm_buf)
    a = origin.clone()
    b = origin.clone()
    assert origin.refcount == 3
    assert a.deref() is pcm_buf
    assert b.deref() is pcm_buf

    # 7. CognitiveState snapshot — the flow saves its posture.
    backend = InMemoryBackend()
    state = CognitiveState(
        session_id="sess-integration-1",
        tenant_id="alpha",
        flow_id="transcribe-flow-1",
        subject_user_id="usr-42",
        density_matrix=[FixedPoint.vec_from_f64([0.2, 0.8])],
        belief_state={
            "last_transcript_confidence": 0.92,
            "transcribed_so_far": 1,
        },
        short_term_memory=[
            MemoryEntry(
                key="last_replay_token",
                payload={"hash": token.token_hash_hex},
                symbolic_refs=[],
                stored_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
            )
        ],
        created_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        last_updated_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
    )
    await backend.persist(state.session_id, state, timedelta(minutes=15))

    # 8. Continuity token + reconnect — no drift.
    signer = ContinuityTokenSigner(b"\x0B" * 32)
    wire = signer.sign(new_token(state.session_id, timedelta(minutes=15)))
    parsed = signer.verify(wire)
    assert parsed.session_id == state.session_id
    rehydrated = await backend.restore(parsed.session_id)
    assert rehydrated.density_matrix == state.density_matrix
    assert rehydrated.short_term_memory == state.short_term_memory


# ── Adversarial T-11-01 Replay poisoning ────────────────────────────


def test_t_11_01_canonical_hash_rejects_key_reorder_as_different() -> None:
    # Positive control: same logical content → same hash regardless
    # of field order. Any tool that relies on canonical hash for
    # tamper detection gets this for free.
    a = canonical_hash({"x": 1, "y": 2})
    b = canonical_hash({"y": 2, "x": 1})
    assert a == b


def test_t_11_01_canonical_hash_differs_when_content_differs() -> None:
    a = canonical_hash({"result": "expected"})
    b = canonical_hash({"result": "tampered"})
    assert a != b


# ── Adversarial T-11-02 Legal-basis bypass ──────────────────────────


def test_t_11_02_sensitive_without_legal_errors_python() -> None:
    diagnostics = check_tool_sensitive_coherence(
        tool_name="handle_phi",
        tool_line=1,
        tool_column=0,
        effects=["sensitive:phi"],
    )
    assert any(
        "no 'legal:<basis>' effect" in d.message for d in diagnostics
    )


def test_t_11_02_unknown_basis_erases_authorization() -> None:
    diagnostics = check_tool_sensitive_coherence(
        tool_name="handle_phi",
        tool_line=1,
        tool_column=0,
        effects=["sensitive:phi", "legal:GDPR.MadeUp"],
    )
    # Two errors: unknown basis AND no valid legal basis.
    assert any("Unknown legal basis" in d.message for d in diagnostics)
    assert any("no 'legal:<basis>'" in d.message for d in diagnostics)


# ── Adversarial T-11-04 Continuity-token phishing ──────────────────


def test_t_11_04_attacker_key_cannot_mint_valid_handshake() -> None:
    server = ContinuityTokenSigner(b"\x07" * 32)
    attacker = ContinuityTokenSigner(b"\x09" * 32)
    forged_wire = attacker.sign(new_token("sess-victim", timedelta(minutes=15)))
    with pytest.raises(TokenForgedOrRotated):
        server.verify(forged_wire)


def test_t_11_04_expired_token_cannot_be_replayed() -> None:
    signer = ContinuityTokenSigner(b"\x07" * 32)
    expired = signer.sign(new_token("sess-1", timedelta(seconds=-1)))
    with pytest.raises(TokenExpired):
        signer.verify(expired)


# ── Adversarial T-11-05 Buffer isolation bleed ─────────────────────


def test_t_11_05_retag_preserves_tenant_tag() -> None:
    buf = ZeroCopyBuffer(b"\x00" * 32, "raw").with_tenant("tenant-a")
    retagged = buf.retag("jpeg")
    assert retagged.tenant_id == "tenant-a"


def test_t_11_05_assert_trusted_rejects_raw_bytes() -> None:
    with pytest.raises(TrustError):
        assert_trusted(b"raw bytes, never refined")


# ── Adversarial T-11-07 Backpressure erasure ────────────────────────


def test_t_11_07_flow_with_stream_and_no_backpressure_tool_errors() -> None:
    diagnostics = check_flow_refinement_and_stream(
        flow_name="Transcribe",
        flow_loc_line=1,
        flow_loc_column=0,
        param_type_names=["Stream"],
        return_type_name=None,
        apply_refs=[],
        tool_effects_by_name={},
    )
    assert any(
        "Stream<T>" in d.message and "backpressure" in d.message
        for d in diagnostics
    )


# ── Cross-phase: ReplayExecutor against a Trusted-gated effect ──────


class _DeterministicInvoker(EffectInvoker):
    """Adopter's effect dispatcher stand-in for the replay harness."""

    def __init__(self, outputs):
        self._outputs = outputs

    def invoke(self, effect_name, inputs, model_version, sampling):
        return self._outputs


def test_replay_executor_confirms_match_for_deterministic_effect() -> None:
    log = InMemoryReplayLog()
    token = (
        ReplayTokenBuilder()
        .effect_name("call_tool:db_read")
        .inputs({"flow_id": "f1", "where": {"id": 1}})
        .outputs({"name": "Acme"})
        .model_version("axon.builtin.db_read.v1")
        .timestamp(datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc))
        .nonce(bytes([7] * 16))
        .mint()
    )
    log.append(token)
    executor = ReplayExecutor(
        log=log, invoker=_DeterministicInvoker({"name": "Acme"})
    )
    outcome = executor.replay_token(token.token_hash_hex)
    assert isinstance(outcome, ReplayMatch)


def test_replay_executor_detects_provider_drift_as_divergence() -> None:
    # Same inputs, different output — simulates an upstream model
    # upgrade slipping through without a new token.
    log = InMemoryReplayLog()
    token = (
        ReplayTokenBuilder()
        .effect_name("llm_infer")
        .inputs({"flow_id": "f1", "prompt": "hi"})
        .outputs({"text": "hello"})
        .model_version("old-model")
        .timestamp(datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc))
        .nonce(bytes([1] * 16))
        .mint()
    )
    log.append(token)
    executor = ReplayExecutor(
        log=log,
        invoker=_DeterministicInvoker({"text": "new model output"}),
    )
    outcome = executor.replay_token(token.token_hash_hex)
    assert isinstance(outcome, ReplayMismatch)


# ── Composition: LegalBasis catalog ↔ regulation families ──────────


def test_legal_basis_catalog_covers_every_regulation() -> None:
    covered = {regulation_for(slug) for slug in LEGAL_BASIS_CATALOG}
    covered.discard(None)
    assert set(Regulation) <= covered


# ── OTS composition: pipeline threads through tenant + kind tag ─────


def test_ots_pipeline_preserves_tenant_and_updates_kind() -> None:
    reg = global_registry()
    pipeline = Pipeline.from_registry(
        reg, BufferKind.mulaw8(), BufferKind.pcm16()
    )
    input_buf = ZeroCopyBuffer(
        bytes([0xFF, 0x80, 0x00, 0x7F]), BufferKind.mulaw8()
    ).with_tenant("alpha")
    output = pipeline.execute(input_buf)
    assert output.tenant_id == "alpha"
    assert output.kind == BufferKind.pcm16()
    for step in pipeline.steps():
        assert step.backend is TransformerBackend.NATIVE
