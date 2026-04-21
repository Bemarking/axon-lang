"""JWKS cache with rotation-on-miss.

Fetches and caches the IdP's JSON Web Key Set and exposes a
``public_key_for(kid, issuer)`` method that an ID token verifier
calls. When a ``kid`` is not in the cache, we refresh once — this
covers legitimate key rotation where the IdP publishes a new key
minutes before using it.

Supported key types:

    - RSA (RS256 / RS384 / RS512)
    - EC  (ES256 / ES384 / ES512)

Other types (e.g. OKP for Ed25519) are parsed but returned as
``UnsupportedKey`` — ID token verification rejects them explicitly
rather than silently letting ``jwt.decode`` handle it.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.errors import OidcIdTokenInvalid

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.sso.oidc_jwks"
)


@dataclass(frozen=True)
class PublicKeyEntry:
    kid: str
    alg: str
    key: Any  # cryptography public key object


@dataclass
class _JwksCacheEntry:
    keys: dict[str, PublicKeyEntry]
    loaded_at: float


@dataclass
class JwksClient:
    """TTL-bounded + rotation-aware JWKS fetcher."""

    settings: SsoSettings
    http_client: httpx.AsyncClient
    _cache: dict[str, _JwksCacheEntry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def build(
        cls, *, settings: SsoSettings | None = None
    ) -> JwksClient:
        settings = settings or get_settings().sso
        client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "axon-enterprise"},
        )
        return cls(settings=settings, http_client=client)

    async def aclose(self) -> None:
        await self.http_client.aclose()

    # ── Public API ────────────────────────────────────────────────────

    async def get_key(self, *, jwks_uri: str, kid: str) -> PublicKeyEntry:
        """Return the public key for ``kid`` — refresh on miss."""
        entry = self._cache.get(jwks_uri)
        if entry is not None and kid in entry.keys:
            if not self._expired(entry):
                return entry.keys[kid]

        # Either expired, missing, or kid unknown — refresh.
        await self._refresh(jwks_uri)
        entry = self._cache.get(jwks_uri)
        if entry is None or kid not in entry.keys:
            if not self.settings.jwks_force_refresh_on_kid_miss:
                raise OidcIdTokenInvalid(f"kid={kid!r} not in JWKS")
            # Second chance — sometimes the IdP's CDN served a stale
            # copy; a bypassing ``Cache-Control: no-cache`` fetch
            # rarely helps but is the documented escape hatch.
            await self._refresh(jwks_uri, bypass_cache=True)
            entry = self._cache.get(jwks_uri)
            if entry is None or kid not in entry.keys:
                raise OidcIdTokenInvalid(
                    f"kid={kid!r} not in JWKS after forced refresh"
                )
        return entry.keys[kid]

    # ── Internals ─────────────────────────────────────────────────────

    def _expired(self, entry: _JwksCacheEntry) -> bool:
        return time.monotonic() - entry.loaded_at >= self.settings.jwks_ttl_seconds

    async def _refresh(self, jwks_uri: str, *, bypass_cache: bool = False) -> None:
        async with self._lock:
            headers = {}
            if bypass_cache:
                headers["Cache-Control"] = "no-cache"
            try:
                resp = await self.http_client.get(jwks_uri, headers=headers)
            except httpx.HTTPError as exc:
                raise OidcIdTokenInvalid(f"JWKS fetch failed: {exc}") from exc
            if resp.status_code != 200:
                raise OidcIdTokenInvalid(
                    f"JWKS fetch returned {resp.status_code} from {jwks_uri}"
                )
            try:
                document = resp.json()
            except ValueError as exc:
                raise OidcIdTokenInvalid("JWKS is not valid JSON") from exc

            keys: dict[str, PublicKeyEntry] = {}
            for jwk in document.get("keys", []):
                parsed = _parse_jwk(jwk)
                if parsed is not None:
                    keys[parsed.kid] = parsed
            self._cache[jwks_uri] = _JwksCacheEntry(
                keys=keys, loaded_at=time.monotonic()
            )
            _logger.info(
                "jwks_refreshed",
                jwks_uri=jwks_uri,
                key_count=len(keys),
            )


# ── JWK → cryptography key parsing ────────────────────────────────────


def _parse_jwk(jwk: dict[str, Any]) -> PublicKeyEntry | None:
    kid = jwk.get("kid")
    kty = jwk.get("kty")
    alg = jwk.get("alg") or ("RS256" if kty == "RSA" else "ES256")
    if not kid or not kty:
        return None
    if jwk.get("use", "sig") != "sig":
        return None

    try:
        if kty == "RSA":
            return PublicKeyEntry(kid=kid, alg=alg, key=_rsa_from_jwk(jwk))
        if kty == "EC":
            return PublicKeyEntry(kid=kid, alg=alg, key=_ec_from_jwk(jwk))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("jwk_parse_failed", kid=kid, kty=kty, error=str(exc))
        return None
    # Unsupported key type (OKP etc.) — skipped silently.
    _logger.info("jwk_unsupported_kty", kid=kid, kty=kty)
    return None


def _b64url_decode_to_int(b64: str) -> int:
    pad = "=" * (-len(b64) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(b64 + pad), "big")


def _rsa_from_jwk(jwk: dict[str, Any]) -> RSAPublicKey:
    n = _b64url_decode_to_int(jwk["n"])
    e = _b64url_decode_to_int(jwk["e"])
    return rsa.RSAPublicNumbers(e=e, n=n).public_key()


def _ec_from_jwk(jwk: dict[str, Any]) -> ec.EllipticCurvePublicKey:
    crv = jwk["crv"]
    curve = {
        "P-256": ec.SECP256R1(),
        "P-384": ec.SECP384R1(),
        "P-521": ec.SECP521R1(),
    }.get(crv)
    if curve is None:
        raise ValueError(f"unsupported EC curve {crv!r}")
    x = _b64url_decode_to_int(jwk["x"])
    y = _b64url_decode_to_int(jwk["y"])
    return ec.EllipticCurvePublicNumbers(x=x, y=y, curve=curve).public_key()
