"""Cognitive-state error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class CognitiveStateServiceError(IdentityError):
    """Base for cognitive-state persistence errors."""

    code = "pem.error"


class CognitiveStateNotFound(CognitiveStateServiceError):
    code = "pem.state_not_found"
    reveal_to_client = True


class CognitiveStateExpired(CognitiveStateServiceError):
    """State exists but its TTL elapsed — the client must open a
    fresh session. Reveal to client so UX can react."""

    code = "pem.state_expired"
    reveal_to_client = True


class CognitiveStateReconnectDenied(CognitiveStateServiceError):
    """Continuity token failed HMAC / expiry / session-binding
    check. Surfaces as 401; 403 would leak existence."""

    code = "pem.reconnect_denied"
    reveal_to_client = True
