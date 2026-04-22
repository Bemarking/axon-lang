"""
ContinuityTokenSigner — HMAC-signed reconnect handshake (Python mirror).
"""

from __future__ import annotations

import base64
import hashlib
import hmac as stdlib_hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class ContinuityTokenError(Exception):
    """Raised when a token fails decode, HMAC check, or has expired."""


class TokenMalformed(ContinuityTokenError):
    """Base64 / structure / encoding problem."""


class TokenForgedOrRotated(ContinuityTokenError):
    """HMAC verification failed."""


class TokenExpired(ContinuityTokenError):
    """Token was well-formed but past its expiry."""


@dataclass(frozen=True, slots=True)
class ContinuityToken:
    session_id: str
    expires_at: datetime


class ContinuityTokenSigner:
    """Adopter-supplied secret → sign / verify. Constant-time HMAC
    comparison via :func:`hmac.compare_digest`."""

    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        self._key = bytes(key)

    def sign(self, token: ContinuityToken) -> str:
        expiry_ms = int(token.expires_at.timestamp() * 1000)
        body = f"{token.session_id}\x1e{expiry_ms}".encode("utf-8")
        mac = stdlib_hmac.new(self._key, body, hashlib.sha256).hexdigest()
        encoded = body + b"\x1e" + mac.encode("ascii")
        return (
            base64.urlsafe_b64encode(encoded)
            .rstrip(b"=")
            .decode("ascii")
        )

    def verify(self, raw: str) -> ContinuityToken:
        # Re-pad for base64url decoding.
        padded = raw + "=" * (-len(raw) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenMalformed(f"base64: {exc}") from exc

        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TokenMalformed(f"utf8: {exc}") from exc

        parts = text.split("\x1e")
        if len(parts) != 3:
            raise TokenMalformed(
                f"expected 3 fields, got {len(parts)}"
            )

        session_id, expiry_str, given_mac_hex = parts
        try:
            expiry_ms = int(expiry_str)
        except ValueError as exc:
            raise TokenMalformed(f"expiry: {exc}") from exc

        body = f"{session_id}\x1e{expiry_ms}".encode("utf-8")
        expected_mac = stdlib_hmac.new(
            self._key, body, hashlib.sha256
        ).hexdigest()
        if not stdlib_hmac.compare_digest(expected_mac, given_mac_hex):
            raise TokenForgedOrRotated(
                "HMAC verification failed (forged or signer key rotated)"
            )

        expires_at = datetime.fromtimestamp(
            expiry_ms / 1000, tz=timezone.utc
        )
        if expires_at <= datetime.now(timezone.utc):
            raise TokenExpired(f"expired at {expires_at.isoformat()}")

        return ContinuityToken(
            session_id=session_id,
            expires_at=expires_at,
        )


def new_token(session_id: str, ttl: timedelta) -> ContinuityToken:
    """Convenience: build a fresh token body."""
    return ContinuityToken(
        session_id=session_id,
        expires_at=datetime.now(timezone.utc) + ttl,
    )


__all__ = [
    "ContinuityToken",
    "ContinuityTokenError",
    "ContinuityTokenSigner",
    "TokenExpired",
    "TokenForgedOrRotated",
    "TokenMalformed",
    "new_token",
]
