"""Replay error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class ReplayTokenServiceError(IdentityError):
    """Base for replay-token persistence errors."""

    code = "replay.error"


class ReplayTokenNotFound(ReplayTokenServiceError):
    """Caller asked for a token that doesn't exist in this tenant."""

    code = "replay.token_not_found"
    reveal_to_client = True


class ReplayTokenMalformed(ReplayTokenServiceError):
    """Submitted token failed canonical-hash verification."""

    code = "replay.token_malformed"
    reveal_to_client = False
