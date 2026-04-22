"""
AXON Runtime — Deterministic replay tokens (§λ-L-E Fase 11.c).

Distinct from :mod:`axon.runtime.tracer` (execution trace for
debugging). The :class:`ReplayToken` machinery here is the
regulatory-grade audit-replay path — every token is hash-anchored
to the :mod:`axon_enterprise` audit chain so an auditor can re-run
any sensitive effect from its recorded token and detect bit-level
divergence.
"""

from axon.runtime.replay.executor import (
    EffectInvoker,
    EffectInvokerError,
    ReplayDivergence,
    ReplayExecutor,
    ReplayExecutorError,
    ReplayMatch,
    ReplayMismatch,
    ReplayOutcome,
)
from axon.runtime.replay.log import (
    InMemoryReplayLog,
    ReplayLog,
    ReplayLogError,
)
from axon.runtime.replay.token import (
    ReplayToken,
    ReplayTokenBuilder,
    SamplingParams,
    canonical_hash,
)

__all__ = [
    "EffectInvoker",
    "EffectInvokerError",
    "InMemoryReplayLog",
    "ReplayDivergence",
    "ReplayExecutor",
    "ReplayExecutorError",
    "ReplayLog",
    "ReplayLogError",
    "ReplayMatch",
    "ReplayMismatch",
    "ReplayOutcome",
    "ReplayToken",
    "ReplayTokenBuilder",
    "SamplingParams",
    "canonical_hash",
]
