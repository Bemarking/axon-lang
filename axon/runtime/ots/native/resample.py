"""
Linear resampler for PCM16 audio — Python mirror.

Tracks `axon-rs/src/ots/native/resample.rs`. Same output samples
for the same inputs so cross-language parity holds.
"""

from __future__ import annotations

from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer
from axon.runtime.ots.pipeline import (
    TransformFailedError,
    Transformer,
    TransformerBackend,
)


def _resample_linear(
    samples: list[int], from_hz: int, to_hz: int
) -> list[int]:
    if not samples or from_hz == to_hz:
        return list(samples)
    # Integer-scaled length — matches Rust's u64 arithmetic exactly
    # for positive inputs.
    output_len = max((len(samples) * to_hz) // from_hz, 1)
    out: list[int] = []
    for i in range(output_len):
        # Project output index into the input timeline.
        src_pos = (i * from_hz) / to_hz
        src_idx = int(src_pos)
        frac = src_pos - src_idx
        if src_idx + 1 >= len(samples):
            out.append(samples[-1])
        else:
            a = samples[src_idx]
            b = samples[src_idx + 1]
            interp = a + (b - a) * frac
            # Match Rust's `round as i16` truncation path.
            out.append(int(round(interp)))
    return out


class Resample(Transformer):
    def __init__(self, from_hz: int, to_hz: int) -> None:
        if from_hz <= 0 or to_hz <= 0:
            raise ValueError("rates must be positive")
        self.from_hz = from_hz
        self.to_hz = to_hz

    def _source_slug(self) -> str:
        return f"pcm16_{self.from_hz // 1000}k"

    def _sink_slug(self) -> str:
        return f"pcm16_{self.to_hz // 1000}k"

    def source_kind(self) -> BufferKind:
        return BufferKind(self._source_slug())

    def sink_kind(self) -> BufferKind:
        return BufferKind(self._sink_slug())

    def backend(self) -> TransformerBackend:
        return TransformerBackend.NATIVE

    def cost_hint(self) -> int:
        return 1

    def transform(self, buffer: ZeroCopyBuffer) -> ZeroCopyBuffer:
        src = bytes(buffer.as_memoryview())
        if len(src) % 2 != 0:
            raise TransformFailedError(
                f"PCM16 input must be even-length, got {len(src)}"
            )
        samples = []
        for i in range(0, len(src), 2):
            raw = (src[i + 1] << 8) | src[i]
            if raw >= 0x8000:
                raw -= 0x10000
            samples.append(raw)
        resampled = _resample_linear(samples, self.from_hz, self.to_hz)
        out = bytearray(len(resampled) * 2)
        for i, sample in enumerate(resampled):
            if sample > 32767:
                sample = 32767
            elif sample < -32768:
                sample = -32768
            if sample < 0:
                sample += 0x10000
            out[2 * i] = sample & 0xFF
            out[2 * i + 1] = (sample >> 8) & 0xFF
        result = ZeroCopyBuffer(bytes(out), self.sink_kind())
        if buffer.tenant_id is not None:
            result = result.with_tenant(buffer.tenant_id)
        return result


__all__ = ["Resample"]
