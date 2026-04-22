"""Stateful PEM — §Fase 11.d.

Postgres + envelope-encrypted persistence for the ``CognitiveState``
primitive defined in ``axon.runtime.pem``. Survives WebSocket
disconnects, 10.l residency enforcement, 10.l SAR + erasure.

Flow:

1. Client opens WebSocket → agent runs → periodic snapshots go
   through :class:`CognitiveStateService.persist`.
2. Disconnect → ``ContinuityTokenSigner.sign`` mints a token the
   client must present on reconnect. Payload stays in Postgres
   under AES-256-GCM (wrapped DEK) keyed to the tenant's envelope.
3. Reconnect with valid token → :class:`CognitiveStateService.restore`
   decrypts, re-hydrates agent state. Audit trail:
   ``pem:state_restored``.
4. TTL elapses before reconnect → eviction worker cryptoshreds the
   envelope key during the nightly sweep. Row + its key die together.
"""

from axon_enterprise.cognitive_states.errors import (
    CognitiveStateExpired,
    CognitiveStateNotFound,
    CognitiveStateServiceError,
)
from axon_enterprise.cognitive_states.models import CognitiveStateSnapshot
from axon_enterprise.cognitive_states.service import CognitiveStateService
from axon_enterprise.cognitive_states.worker import CognitiveStateEvictionWorker

__all__ = [
    "CognitiveStateEvictionWorker",
    "CognitiveStateExpired",
    "CognitiveStateNotFound",
    "CognitiveStateService",
    "CognitiveStateServiceError",
    "CognitiveStateSnapshot",
]
