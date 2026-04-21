"""OIDC discovery — ``/.well-known/openid-configuration`` fetch + cache.

TTL-bounded, thread-safe, with concurrent-fetch deduplication. Cache
is keyed by ``issuer`` URL so the same process can hold metadata for
many different IdPs simultaneously.

No ambient settings inside the discoverer itself — callers inject an
``httpx.AsyncClient`` (test swap is one line). The module-level
``default_discoverer()`` wires the production client.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.errors import OidcDiscoveryError

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.sso.oidc_discovery"
)

_REQUIRED_FIELDS = frozenset(
    {
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
    }
)


@dataclass(frozen=True)
class OidcMetadata:
    """Parsed + validated OIDC provider metadata."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    end_session_endpoint: str | None
    id_token_signing_alg_values_supported: list[str]
    raw: dict[str, Any]


@dataclass
class _Entry:
    metadata: OidcMetadata
    loaded_at: float


@dataclass
class OidcDiscoverer:
    """TTL-bounded cache of OIDC metadata documents."""

    settings: SsoSettings
    http_client: httpx.AsyncClient
    _cache: dict[str, _Entry] = field(default_factory=dict)
    _inflight: dict[str, asyncio.Future[OidcMetadata]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def build(cls, *, settings: SsoSettings | None = None) -> OidcDiscoverer:
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

    async def metadata(self, issuer: str, *, force_refresh: bool = False) -> OidcMetadata:
        """Return cached or freshly-fetched metadata for ``issuer``.

        Dedups concurrent fetches: when two coroutines call for the
        same issuer simultaneously, only one HTTP round-trip happens
        and both get the same result (or the same error).
        """
        issuer = issuer.rstrip("/")
        now = time.monotonic()

        if not force_refresh:
            cached = self._cache.get(issuer)
            if cached is not None and now - cached.loaded_at < self.settings.discovery_ttl_seconds:
                return cached.metadata

        async with self._lock:
            # Re-check inside the lock to collapse stampedes.
            cached = self._cache.get(issuer)
            if (
                not force_refresh
                and cached is not None
                and time.monotonic() - cached.loaded_at < self.settings.discovery_ttl_seconds
            ):
                return cached.metadata

            fut = self._inflight.get(issuer)
            if fut is None:
                fut = asyncio.get_event_loop().create_future()
                self._inflight[issuer] = fut
                # Kick off the actual fetch outside the lock.
                asyncio.create_task(self._fetch_and_store(issuer, fut))
            else:
                # Another coroutine is already fetching.
                pass

        try:
            return await fut
        finally:
            self._inflight.pop(issuer, None)

    async def _fetch_and_store(
        self, issuer: str, fut: asyncio.Future[OidcMetadata]
    ) -> None:
        url = f"{issuer}/.well-known/openid-configuration"
        try:
            meta = await self._fetch(url)
            self._cache[issuer] = _Entry(metadata=meta, loaded_at=time.monotonic())
            fut.set_result(meta)
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)

    async def _fetch(self, url: str) -> OidcMetadata:
        tries = self.settings.http_retries + 1
        last_exc: Exception | None = None
        for attempt in range(tries):
            try:
                resp = await self.http_client.get(url)
            except httpx.HTTPError as exc:
                last_exc = exc
                _logger.warning(
                    "oidc_discovery_transport_error",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )
                continue

            if resp.status_code != 200:
                last_exc = OidcDiscoveryError(
                    f"{url} returned HTTP {resp.status_code}"
                )
                _logger.warning(
                    "oidc_discovery_bad_status",
                    url=url,
                    status=resp.status_code,
                )
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                last_exc = OidcDiscoveryError(f"non-JSON response from {url}")
                _logger.warning("oidc_discovery_bad_json", url=url, error=str(exc))
                continue
            return _parse(data)

        assert last_exc is not None  # tries >= 1
        raise OidcDiscoveryError(f"discovery failed for {url}: {last_exc}")


def _parse(data: dict[str, Any]) -> OidcMetadata:
    missing = _REQUIRED_FIELDS.difference(data.keys())
    if missing:
        raise OidcDiscoveryError(
            f"metadata missing required fields: {sorted(missing)}"
        )
    algs = data.get("id_token_signing_alg_values_supported") or ["RS256"]
    return OidcMetadata(
        issuer=data["issuer"],
        authorization_endpoint=data["authorization_endpoint"],
        token_endpoint=data["token_endpoint"],
        jwks_uri=data["jwks_uri"],
        userinfo_endpoint=data.get("userinfo_endpoint"),
        end_session_endpoint=data.get("end_session_endpoint"),
        id_token_signing_alg_values_supported=list(algs),
        raw=dict(data),
    )
