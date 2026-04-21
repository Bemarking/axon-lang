"""RFC 7636 Proof Key for Code Exchange (PKCE) — S256 only.

We emit **only** the ``S256`` challenge method. ``plain`` is a
downgrade attack vector and not accepted by this module.

Usage::

    verifier = generate_code_verifier()                     # keep server-side
    challenge = compute_code_challenge(verifier)            # send in auth URL
    # ... user returns with auth code ...
    # on token exchange, POST verifier to the token endpoint
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from axon_enterprise.sso.errors import OidcPkceMismatch


def generate_code_verifier(length: int = 64) -> str:
    """Return an RFC 7636 ``code_verifier`` — 43..128 URL-safe chars."""
    if not 32 <= length <= 96:
        raise ValueError("length must be between 32 and 96 pre-encoding bytes")
    return secrets.token_urlsafe(length)[:128]


def compute_code_challenge(verifier: str) -> str:
    """Return the ``S256`` code_challenge for ``verifier``.

    ``BASE64URL(SHA256(verifier))`` with padding stripped, per RFC 7636 §4.2.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pair(verifier: str, challenge: str) -> None:
    """Raise ``OidcPkceMismatch`` when ``challenge`` was not derived from ``verifier``.

    Mostly a belt-and-suspenders check for tests — in production the
    IdP itself enforces this at the token endpoint.
    """
    if compute_code_challenge(verifier) != challenge:
        raise OidcPkceMismatch("PKCE verifier does not match stored challenge")
