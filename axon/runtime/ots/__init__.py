"""
AXON Runtime — Ontological Tool Synthesis binary pipelines (§Fase 11.e).

Python mirror of ``axon-rs/src/ots/``. Same transformer trait +
Dijkstra path search + native mulaw + resample + ffmpeg subprocess
plumbing. Adopters that run their orchestration in Python get the
same pipeline synthesis as the Rust runtime.
"""

from axon.runtime.ots.pipeline import (
    OtsError,
    Pipeline,
    PipelineStep,
    Transformer,
    TransformerBackend,
    TransformerId,
    TransformerRegistry,
)

# Convenience re-exports for the common native paths.
from axon.runtime.ots.native.mulaw import MulawToPcm16, Pcm16ToMulaw
from axon.runtime.ots.native.resample import Resample


#: Closed backend catalogue. Mirror of Rust `OTS_BACKEND_CATALOG`.
OTS_BACKEND_CATALOG: tuple[str, ...] = ("native", "ffmpeg")

#: Effect slugs surfaced to the type checker.
OTS_TRANSFORM_EFFECT_SLUG: str = "ots:transform"
OTS_BACKEND_EFFECT_SLUG: str = "ots:backend"


def _build_global_registry() -> TransformerRegistry:
    reg = TransformerRegistry()
    reg.install(MulawToPcm16())
    reg.install(Pcm16ToMulaw())
    reg.install(Resample(8_000, 16_000))
    reg.install(Resample(16_000, 8_000))
    reg.install(Resample(16_000, 48_000))
    reg.install(Resample(48_000, 16_000))
    return reg


_GLOBAL_REGISTRY: TransformerRegistry | None = None


def global_registry() -> TransformerRegistry:
    """Process-wide registry seeded with the built-in transcoders."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = _build_global_registry()
    return _GLOBAL_REGISTRY


__all__ = [
    "MulawToPcm16",
    "OTS_BACKEND_CATALOG",
    "OTS_BACKEND_EFFECT_SLUG",
    "OTS_TRANSFORM_EFFECT_SLUG",
    "OtsError",
    "Pcm16ToMulaw",
    "Pipeline",
    "PipelineStep",
    "Resample",
    "Transformer",
    "TransformerBackend",
    "TransformerId",
    "TransformerRegistry",
    "global_registry",
]
