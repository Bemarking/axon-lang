"""
AXON Runtime — Stateful PEM (§λ-L-E Fase 11.d).

Python mirror of ``axon-rs/src/pem/``. Enables a reconnecting
WebSocket client to resume its exact cognitive posture (density
matrix, belief state, short-term memory) without restart.

Composition:

- ``CognitiveState`` encodes floats as Q32.32 so N serialise/
  deserialise cycles yield bit-identical matrices.
- ``ContinuityTokenSigner`` mints HMAC-signed reconnect handshakes
  so a sniffed session_id alone does NOT grant mid-flow takeover.
- ``PersistenceBackend`` is the abstract storage contract;
  :class:`InMemoryBackend` ships here for dev/tests, production
  uses ``axon_enterprise.cognitive_states`` (Postgres + envelope).
"""

from axon.runtime.pem.backend import (
    InMemoryBackend,
    PersistenceBackend,
    PersistenceError,
)
from axon.runtime.pem.continuity_token import (
    ContinuityToken,
    ContinuityTokenError,
    ContinuityTokenSigner,
)
from axon.runtime.pem.state import (
    Q32_32_SCALE,
    CognitiveState,
    FixedPoint,
    MemoryEntry,
    StateDecodeError,
)

__all__ = [
    "CognitiveState",
    "ContinuityToken",
    "ContinuityTokenError",
    "ContinuityTokenSigner",
    "FixedPoint",
    "InMemoryBackend",
    "MemoryEntry",
    "PersistenceBackend",
    "PersistenceError",
    "Q32_32_SCALE",
    "StateDecodeError",
]
