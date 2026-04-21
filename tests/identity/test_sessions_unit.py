"""Unit tests for the token-handling helpers in ``SessionService``.

DB-level tests live in ``tests/identity/test_auth_integration.py``.
"""

from __future__ import annotations

import hashlib

from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.sessions import SessionService


def test_hash_token_is_sha256() -> None:
    raw = "refresh-token-abc"
    expected = hashlib.sha256(raw.encode()).digest()
    assert SessionService.hash_token(raw) == expected
    assert len(SessionService.hash_token(raw)) == 32


def test_hash_token_is_deterministic() -> None:
    raw = "same-token"
    assert SessionService.hash_token(raw) == SessionService.hash_token(raw)


def test_mint_raw_token_is_urlsafe_and_sufficiently_long() -> None:
    svc = SessionService(settings=IdentitySettings(session_refresh_token_bytes=64))
    token = svc._mint_raw_token()
    # base64url: 4 chars per 3 bytes → 64 bytes → at least 86 chars.
    assert len(token) >= 86
    # No padding expected from token_urlsafe.
    assert "=" not in token
