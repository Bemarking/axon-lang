"""
AXON Runtime — Trust types + closed verifier catalogue (§λ-L-E Fase 11.a).
==========================================================================

Python reference implementation of the Rust Trust Catalog in
``axon-rs/src/refinement.rs`` + ``axon-rs/src/trust_verifiers.rs``.

The runtime mirror exists because the Axon reference compiler and
interpreter both run in Python; Rust is the production backend. Every
check that ``axon-rs`` does against the closed catalogue, this module
does in Python, and the two MUST stay in sync. Keeping them byte-
identical is the contract the parity test suite enforces.

Adopters import the verifiers directly:

>>> from axon.runtime.trust import verify_hmac_sha256
>>> payload = verify_hmac_sha256(body, signature, key, key_id="webhook-v1")

The compiler recognises exactly the functions in ``TRUST_VERIFIERS``
as being capable of producing a ``Trusted[T]`` from an ``Untrusted[T]``.
Any other verification function — however correct — is rejected
statically, because audit-reviewing N custom verifiers is strictly
worse than reviewing these four once.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar

# ── Closed Trust Catalogue ────────────────────────────────────────────


class TrustProof(str, Enum):
    """Canonical identifier of a verifier. Closed enum — mirror of
    ``axon::refinement::TrustProof`` in Rust."""

    HMAC = "hmac"
    JWT_SIG = "jwt_sig"
    OAUTH_CODE_EXCHANGE = "oauth_code_exchange"
    ED25519 = "ed25519"


#: Every slug. Stable string order — must match ``TRUST_CATALOG`` in Rust.
TRUST_CATALOG: tuple[str, ...] = (
    TrustProof.HMAC.value,
    TrustProof.JWT_SIG.value,
    TrustProof.OAUTH_CODE_EXCHANGE.value,
    TrustProof.ED25519.value,
)


def is_trust_proof(slug: str) -> bool:
    """True when ``slug`` names a verifier in the closed catalogue."""
    return slug in TRUST_CATALOG


# ── Refinement type wrappers ──────────────────────────────────────────

T = TypeVar("T")


class Untrusted(Generic[T]):
    """Marker wrapper for a value that has NOT passed a verifier.

    The type checker propagates this tag through the program.
    ``Untrusted[T]`` can be unwrapped via ``.value`` for logging /
    debugging, but it MUST NOT be passed to an effect expecting
    ``Trusted[T]``. The rule is enforced statically by
    ``axon-rs::type_checker`` and dynamically by
    :func:`assert_trusted` at runtime.
    """

    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        self._value = value

    @property
    def value(self) -> T:
        return self._value

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"Untrusted({type(self._value).__name__})"


@dataclass(frozen=True, slots=True)
class VerifiedPayload:
    """Proof tag attached to a successfully refined payload.

    Mirror of ``axon::trust_verifiers::VerifiedPayload`` in Rust.
    The ``proof`` identifies which verifier stamped the payload;
    ``key_id`` is the opaque identifier of the key/secret used —
    never the raw secret.
    """

    proof: TrustProof
    key_id: str


class Trusted(Generic[T]):
    """Marker wrapper for a value that HAS passed a catalogue verifier.

    Constructed exclusively by the verifiers in this module. Instances
    built any other way are rejected: they carry no ``VerifiedPayload``
    and :func:`assert_trusted` raises on them.
    """

    __slots__ = ("_value", "_proof")

    def __init__(self, value: T, proof: VerifiedPayload) -> None:
        self._value = value
        self._proof = proof

    @property
    def value(self) -> T:
        return self._value

    @property
    def proof(self) -> VerifiedPayload:
        return self._proof

    def __repr__(self) -> str:  # pragma: no cover
        return f"Trusted({type(self._value).__name__}, via={self._proof.proof.value})"


class TrustError(Exception):
    """Raised by verifiers on any rejection path. Adopters catch and
    surface as HTTP 401/403; the runtime never silently passes through."""


def assert_trusted(value: object) -> None:
    """Runtime companion to the static trust check.

    Raises :class:`TrustError` if ``value`` is not a
    :class:`Trusted` instance. Effects that consume ``Trusted[T]``
    call this defensively at the FFI boundary so a malformed Python
    adopter cannot forge trust via duck typing.
    """
    if not isinstance(value, Trusted):
        raise TrustError(
            f"expected Trusted<T>, got {type(value).__name__!r}; "
            f"pass the payload through one of the catalogue verifiers: "
            f"{', '.join(TRUST_CATALOG)}"
        )


# ── Verifier #1 — HMAC-SHA256 ─────────────────────────────────────────


def verify_hmac_sha256(
    payload: bytes,
    tag: bytes,
    key: bytes,
    *,
    key_id: str,
) -> Trusted[bytes]:
    """Verify an HMAC-SHA256 tag over ``payload`` using ``key``.

    Raises :class:`TrustError` on mismatch. Uses
    :func:`hmac.compare_digest` internally — that's Python's
    constant-time comparator; never replace with ``==``.
    """
    if len(tag) != 32:
        raise TrustError("HMAC-SHA256 tag must be exactly 32 bytes")
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise TrustError("HMAC-SHA256 signature mismatch")
    return Trusted(
        payload,
        VerifiedPayload(proof=TrustProof.HMAC, key_id=key_id),
    )


def verify_hmac_sha256_hex(
    payload: bytes,
    tag_hex: str,
    key: bytes,
    *,
    key_id: str,
) -> Trusted[bytes]:
    """HMAC-SHA256 with hex-encoded tag (GitHub ``X-Hub-Signature-256`` style).

    The ``sha256=`` prefix is accepted and stripped. Delegates the
    constant-time compare to :func:`verify_hmac_sha256`.
    """
    normalised = tag_hex.removeprefix("sha256=")
    try:
        tag = bytes.fromhex(normalised)
    except ValueError as exc:
        raise TrustError("HMAC-SHA256 hex tag failed to decode") from exc
    return verify_hmac_sha256(payload, tag, key, key_id=key_id)


# ── Verifier #2 — Ed25519 ─────────────────────────────────────────────


def verify_ed25519(
    payload: bytes,
    signature: bytes,
    public_key: bytes,
    *,
    key_id: str,
) -> Trusted[bytes]:
    """Verify an Ed25519 detached signature (RFC 8032).

    Implementation defers to ``cryptography`` (pre-existing adopter
    dep). The function signature matches the Rust catalogue entry so
    code generated by the compiler can target either backend.

    Raises :class:`TrustError` on any decode / verify failure.
    """
    if len(public_key) != 32:
        raise TrustError("Ed25519 public key must be 32 bytes")
    if len(signature) != 64:
        raise TrustError("Ed25519 signature must be 64 bytes")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover — adopter env issue
        raise TrustError(
            "cryptography>=42 required for Ed25519 verification; "
            "install with `pip install cryptography`"
        ) from exc
    try:
        pk = Ed25519PublicKey.from_public_bytes(public_key)
        pk.verify(signature, payload)
    except InvalidSignature as exc:
        raise TrustError("Ed25519 signature mismatch") from exc
    except Exception as exc:  # malformed key / sig
        raise TrustError(f"Ed25519 verify failed: {exc}") from exc
    return Trusted(
        payload,
        VerifiedPayload(proof=TrustProof.ED25519, key_id=key_id),
    )


# ── Verifier #3 — JWT signature (delegates to existing 10.e verifier) ─


def verify_jwt_signature(
    token: str,
    *,
    verifier,
) -> Trusted[dict]:
    """Verify a JWT via the 10.e issuer + return the claims as Trusted.

    ``verifier`` is an instance of the 10.e ``JwtIssuer``-compatible
    verifier (duck-typed to expose ``.verify(token) -> claims_dict``).
    We keep the dependency loose because ``axon`` itself doesn't pin
    the jwt_issuer package version — the adopter provides the
    configured verifier.

    Raises :class:`TrustError` on any verification failure.
    """
    try:
        claims = verifier.verify(token)
    except Exception as exc:
        raise TrustError(f"JWT verification failed: {exc}") from exc
    key_id = claims.get("jti") or claims.get("sub") or "<anonymous>"
    return Trusted(
        claims,
        VerifiedPayload(proof=TrustProof.JWT_SIG, key_id=str(key_id)),
    )


# ── Verifier #4 — OAuth2 PKCE S256 code exchange ──────────────────────


@dataclass(frozen=True, slots=True)
class OAuthCodeExchangeRequest:
    """Inputs for the authorization-code flow with PKCE S256."""

    token_endpoint: str
    client_id: str
    redirect_uri: str
    code: str
    code_verifier: str
    client_secret: Optional[str] = None


@dataclass(frozen=True, slots=True)
class OAuthTokenResponse:
    """RFC 6749 §5.1 response body fields."""

    access_token: str
    token_type: str
    expires_in: Optional[int]
    refresh_token: Optional[str]
    scope: Optional[str]
    id_token: Optional[str]


def verify_oauth_code_exchange(
    req: OAuthCodeExchangeRequest,
    *,
    http_post,
) -> tuple[Trusted[OAuthTokenResponse], OAuthTokenResponse]:
    """Perform the PKCE exchange + return a Trusted access token.

    ``http_post`` is a caller-provided callable with the signature
    ``(url: str, form: dict[str, str]) -> dict`` — we inject it so
    adopters can use their own HTTP client (httpx / requests / aiohttp)
    instead of pulling another dep.

    Raises :class:`TrustError` on any HTTP / decode failure.
    """
    form = {
        "grant_type": "authorization_code",
        "code": req.code,
        "redirect_uri": req.redirect_uri,
        "client_id": req.client_id,
        "code_verifier": req.code_verifier,
    }
    if req.client_secret:
        form["client_secret"] = req.client_secret

    try:
        body = http_post(req.token_endpoint, form)
    except Exception as exc:
        raise TrustError(f"OAuth2 exchange failed: {exc}") from exc

    try:
        response = OAuthTokenResponse(
            access_token=str(body["access_token"]),
            token_type=str(body.get("token_type") or ""),
            expires_in=int(body["expires_in"]) if body.get("expires_in") else None,
            refresh_token=body.get("refresh_token"),
            scope=body.get("scope"),
            id_token=body.get("id_token"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustError(f"OAuth2 response malformed: {exc}") from exc

    trusted = Trusted(
        response,
        VerifiedPayload(
            proof=TrustProof.OAUTH_CODE_EXCHANGE,
            key_id=req.client_id,
        ),
    )
    return trusted, response


# ── Compiler-visible verifier registry ────────────────────────────────
#
# The table below is consulted by `axon/compiler/refinement_check.py`.
# A function name must appear here to be accepted as a refinement
# transition `Untrusted[T] -> Trusted[T]`. Adding a verifier means
# adding a row here AND a Rust counterpart in
# `axon-rs/src/trust_verifiers.rs`; both additions require a security
# review in the PR.

TRUST_VERIFIERS: dict[str, TrustProof] = {
    "verify_hmac_sha256": TrustProof.HMAC,
    "verify_hmac_sha256_hex": TrustProof.HMAC,
    "verify_ed25519": TrustProof.ED25519,
    "verify_jwt_signature": TrustProof.JWT_SIG,
    "verify_oauth_code_exchange": TrustProof.OAUTH_CODE_EXCHANGE,
}


__all__ = [
    "OAuthCodeExchangeRequest",
    "OAuthTokenResponse",
    "TRUST_CATALOG",
    "TRUST_VERIFIERS",
    "Trusted",
    "TrustError",
    "TrustProof",
    "Untrusted",
    "VerifiedPayload",
    "assert_trusted",
    "is_trust_proof",
    "verify_ed25519",
    "verify_hmac_sha256",
    "verify_hmac_sha256_hex",
    "verify_jwt_signature",
    "verify_oauth_code_exchange",
]
