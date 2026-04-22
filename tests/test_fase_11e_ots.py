"""
Unit tests — §λ-L-E Fase 11.e OTS registry + native transformers.
"""

from __future__ import annotations

import pytest

from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer
from axon.runtime.ots import (
    OTS_BACKEND_CATALOG,
    MulawToPcm16,
    Pcm16ToMulaw,
    Pipeline,
    Resample,
    Transformer,
    TransformerBackend,
    TransformerRegistry,
    global_registry,
)
from axon.runtime.ots.pipeline import (
    KindMismatchError,
    NoPathError,
    TransformFailedError,
)


# ── Catalogue invariants ──────────────────────────────────────────────


def test_backend_catalog_contains_native_and_ffmpeg() -> None:
    assert OTS_BACKEND_CATALOG == ("native", "ffmpeg")


def test_transformer_backend_enum_matches_catalog() -> None:
    values = {m.value for m in TransformerBackend}
    assert values == set(OTS_BACKEND_CATALOG)


# ── Registry + Dijkstra ───────────────────────────────────────────────


class _Identity(Transformer):
    def __init__(
        self,
        source: str,
        sink: str,
        cost: int,
        backend: TransformerBackend = TransformerBackend.NATIVE,
    ) -> None:
        self._source = BufferKind(source)
        self._sink = BufferKind(sink)
        self._cost = cost
        self._backend = backend

    def source_kind(self) -> BufferKind:
        return self._source

    def sink_kind(self) -> BufferKind:
        return self._sink

    def backend(self) -> TransformerBackend:
        return self._backend

    def cost_hint(self) -> int:
        return self._cost

    def transform(self, buffer: ZeroCopyBuffer) -> ZeroCopyBuffer:
        return buffer.retag(self._sink)


def test_identity_path_returns_empty() -> None:
    reg = TransformerRegistry()
    path = reg.shortest_path(BufferKind("a"), BufferKind("a"))
    assert path == []


def test_single_edge_path() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    path = reg.shortest_path(BufferKind("a"), BufferKind("b"))
    assert len(path) == 1


def test_multi_hop_picks_lowest_cost() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    reg.install(_Identity("b", "c", cost=1))
    reg.install(
        _Identity("a", "c", cost=10, backend=TransformerBackend.SUBPROCESS)
    )
    path = reg.shortest_path(BufferKind("a"), BufferKind("c"))
    assert len(path) == 2
    assert all(t.backend() is TransformerBackend.NATIVE for t in path)


def test_no_path_raises_typed_error() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    with pytest.raises(NoPathError):
        reg.shortest_path(BufferKind("a"), BufferKind("z"))


def test_has_path_boolean_wrapper() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    assert reg.has_path(BufferKind("a"), BufferKind("b"))
    assert not reg.has_path(BufferKind("a"), BufferKind("z"))


# ── Pipeline execution ────────────────────────────────────────────────


def test_pipeline_execute_runs_every_step() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    reg.install(_Identity("b", "c", cost=1))
    pipeline = Pipeline.from_registry(
        reg, BufferKind("a"), BufferKind("c")
    )
    input = ZeroCopyBuffer(b"\x01\x02\x03", BufferKind("a"))
    out = pipeline.execute(input)
    assert out.kind.slug == "c"
    assert out.as_bytes() == b"\x01\x02\x03"


def test_pipeline_detects_input_kind_mismatch() -> None:
    reg = TransformerRegistry()
    reg.install(_Identity("a", "b", cost=1))
    pipeline = Pipeline.from_registry(
        reg, BufferKind("a"), BufferKind("b")
    )
    wrong = ZeroCopyBuffer(b"\x00", BufferKind("wrong"))
    with pytest.raises(KindMismatchError):
        pipeline.execute(wrong)


def test_pipeline_crosses_process_boundary_flag() -> None:
    reg = TransformerRegistry()
    reg.install(
        _Identity(
            "a", "b", cost=10, backend=TransformerBackend.SUBPROCESS
        )
    )
    pipeline = Pipeline.from_registry(
        reg, BufferKind("a"), BufferKind("b")
    )
    assert pipeline.crosses_process_boundary()


# ── μ-law transcoder ──────────────────────────────────────────────────


def test_mulaw_decode_reference_vectors() -> None:
    transformer = MulawToPcm16()
    input = ZeroCopyBuffer(
        bytes([0xFF, 0x7F, 0x80, 0x00]),
        BufferKind.mulaw8(),
    )
    out = transformer.transform(input)
    assert out.kind == BufferKind.pcm16()
    assert len(out) == 8

    raw = bytes(out.as_memoryview())
    samples = []
    for i in range(0, len(raw), 2):
        s = (raw[i + 1] << 8) | raw[i]
        if s >= 0x8000:
            s -= 0x10000
        samples.append(s)
    # G.711: stored byte inverts all bits before logical decode, so
    # 0xFF stored → logical 0x00 = smallest positive (0),
    # 0x7F stored → logical 0x80 = smallest negative (0),
    # 0x80 stored → logical 0x7F = largest positive (+32_124),
    # 0x00 stored → logical 0xFF = largest negative (-32_124).
    assert samples == [0, 0, 32_124, -32_124]


def test_mulaw_roundtrip_is_lossy_but_bounded() -> None:
    mu = MulawToPcm16()
    pcm = Pcm16ToMulaw()
    # Build a range of PCM samples spaced across the representable range.
    samples: list[int] = list(range(-30_000, 30_001, 512))
    pcm_bytes = bytearray()
    for s in samples:
        if s < 0:
            s += 0x10000
        pcm_bytes += bytes([s & 0xFF, (s >> 8) & 0xFF])
    mulaw_out = pcm.transform(
        ZeroCopyBuffer(bytes(pcm_bytes), BufferKind.pcm16())
    )
    recovered = mu.transform(mulaw_out)
    rec_bytes = bytes(recovered.as_memoryview())

    for i, original in enumerate(samples):
        rec = (rec_bytes[2 * i + 1] << 8) | rec_bytes[2 * i]
        if rec >= 0x8000:
            rec -= 0x10000
        error = abs(original - rec)
        tol = max(abs(original) // 10, 256)
        assert error <= tol, (
            f"pcm={original} → recovered={rec} (err={error}, tol={tol})"
        )


def test_pcm16_to_mulaw_rejects_odd_length() -> None:
    t = Pcm16ToMulaw()
    odd = ZeroCopyBuffer(b"\x00\x01\x02", BufferKind.pcm16())
    with pytest.raises(TransformFailedError):
        t.transform(odd)


# ── Resample ──────────────────────────────────────────────────────────


def test_resample_identity_returns_same_bytes() -> None:
    r = Resample(16_000, 16_000)
    input = ZeroCopyBuffer(b"\x00\x00\xFF\xFF", r.source_kind())
    out = r.transform(input)
    assert out.as_bytes() == b"\x00\x00\xFF\xFF"


def test_resample_upsample_approximately_doubles_length() -> None:
    r = Resample(8_000, 16_000)
    # 100 PCM16 samples at 8 kHz = 200 bytes.
    input = ZeroCopyBuffer(
        bytes(200), r.source_kind()
    )
    out = r.transform(input)
    assert 398 <= len(out) <= 402


def test_resample_downsample_approximately_halves_length() -> None:
    r = Resample(16_000, 8_000)
    input = ZeroCopyBuffer(bytes(400), r.source_kind())
    out = r.transform(input)
    assert 198 <= len(out) <= 202


def test_resample_kind_tags_follow_rate_convention() -> None:
    r = Resample(8_000, 16_000)
    assert r.source_kind().slug == "pcm16_8k"
    assert r.sink_kind().slug == "pcm16_16k"


def test_resample_rejects_odd_length() -> None:
    r = Resample(8_000, 16_000)
    odd = ZeroCopyBuffer(b"\x00\x01\x02", r.source_kind())
    with pytest.raises(TransformFailedError):
        r.transform(odd)


# ── Global registry ───────────────────────────────────────────────────


def test_global_registry_resolves_mulaw_to_pcm16() -> None:
    reg = global_registry()
    pipeline = Pipeline.from_registry(
        reg, BufferKind.mulaw8(), BufferKind.pcm16()
    )
    assert len(pipeline) == 1
    assert not pipeline.crosses_process_boundary()


def test_global_registry_resolves_pcm_rate_ladder() -> None:
    reg = global_registry()
    pipeline = Pipeline.from_registry(
        reg,
        BufferKind("pcm16_8k"),
        BufferKind("pcm16_16k"),
    )
    assert len(pipeline) >= 1
