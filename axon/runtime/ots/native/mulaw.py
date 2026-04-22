"""
μ-law ↔ PCM16 transcoders per ITU-T G.711.

Python mirror of ``axon-rs/src/ots/native/mulaw.rs``. Identical
arithmetic so cross-language parity holds on reference vectors.
"""

from __future__ import annotations

from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer
from axon.runtime.ots.pipeline import (
    TransformFailedError,
    Transformer,
    TransformerBackend,
)


_MULAW_BIAS = 0x84
_MULAW_CLIP = 32_635


def _decode_mulaw_byte(byte: int) -> int:
    byte = (~byte) & 0xFF
    sign = (byte & 0x80) != 0
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    magnitude = (((mantissa << 3) + 0x84) << exponent) - 0x84
    sample = -magnitude if sign else magnitude
    # Clamp to signed-i16 range (matches Rust's `as i16` truncation
    # of the already-bounded magnitude arithmetic).
    if sample > 32767:
        sample = 32767
    elif sample < -32768:
        sample = -32768
    return sample


def _encode_pcm_sample(sample: int) -> int:
    pcm = sample
    if pcm < 0:
        pcm = -pcm
        sign = 0x80
    else:
        sign = 0x00
    if pcm > _MULAW_CLIP:
        pcm = _MULAW_CLIP
    pcm += _MULAW_BIAS

    exponent = 7
    mask = 0x4000
    while exponent > 0 and (pcm & mask) == 0:
        exponent -= 1
        mask >>= 1
    mantissa = (pcm >> (exponent + 3)) & 0x0F
    byte = (~(sign | ((exponent << 4) & 0xFF) | (mantissa & 0xFF))) & 0xFF
    return byte


class MulawToPcm16(Transformer):
    def source_kind(self) -> BufferKind:
        return BufferKind.mulaw8()

    def sink_kind(self) -> BufferKind:
        return BufferKind.pcm16()

    def backend(self) -> TransformerBackend:
        return TransformerBackend.NATIVE

    def cost_hint(self) -> int:
        return 1

    def transform(self, buffer: ZeroCopyBuffer) -> ZeroCopyBuffer:
        src = bytes(buffer.as_memoryview())
        out = bytearray(len(src) * 2)
        for i, byte in enumerate(src):
            sample = _decode_mulaw_byte(byte)
            out[2 * i] = sample & 0xFF
            out[2 * i + 1] = (sample >> 8) & 0xFF
        result = ZeroCopyBuffer(bytes(out), BufferKind.pcm16())
        if buffer.tenant_id is not None:
            result = result.with_tenant(buffer.tenant_id)
        return result


class Pcm16ToMulaw(Transformer):
    def source_kind(self) -> BufferKind:
        return BufferKind.pcm16()

    def sink_kind(self) -> BufferKind:
        return BufferKind.mulaw8()

    def backend(self) -> TransformerBackend:
        return TransformerBackend.NATIVE

    def cost_hint(self) -> int:
        return 1

    def transform(self, buffer: ZeroCopyBuffer) -> ZeroCopyBuffer:
        src = bytes(buffer.as_memoryview())
        if len(src) % 2 != 0:
            raise TransformFailedError(
                f"PCM16 input must be a multiple of 2 bytes, got {len(src)}"
            )
        out = bytearray(len(src) // 2)
        for i in range(0, len(src), 2):
            # Sign-extend the little-endian 16-bit sample.
            lo = src[i]
            hi = src[i + 1]
            raw = (hi << 8) | lo
            if raw >= 0x8000:
                raw -= 0x10000
            out[i // 2] = _encode_pcm_sample(raw)
        result = ZeroCopyBuffer(bytes(out), BufferKind.mulaw8())
        if buffer.tenant_id is not None:
            result = result.with_tenant(buffer.tenant_id)
        return result


__all__ = ["MulawToPcm16", "Pcm16ToMulaw"]
