"""AuthMiddleware — JWT verification → ``PrincipalContext`` ContextVar.

Order in the stack:

    ObservabilityMiddleware   (outermost — always records)
    AuthMiddleware            (extracts JWT, sets principal ContextVar)
    TenantExtractor           (from axon-rs equivalent; binds tenant)
    Route handlers            (use @require_permission from 10.c)

Skips authentication for a configurable allow-list of public paths
(``/healthz``, ``/readyz``, ``/.well-known/jwks.json``, configured
``metrics_path``). Every other route requires a valid JWT — absence
or failure raises ``AuthenticationError`` which the error handler
translates to 401.

The middleware uses the 10.e ``JwtVerifier`` (Python side) rather
than the Rust one; both read the same JWKS so signatures are
interchangeable. Python-side verification is needed here because
handler code runs in the Python process.

``impersonation`` claim (``imp``) is passed through — the admin
flow (``/admin/tenants/{id}/impersonate``) mints tokens with
``imp.target_user_id`` and the middleware surfaces it in the
PrincipalContext so handlers can emit ``user:impersonated`` audit
events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import jwt
import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.http.errors import json_error
from axon_enterprise.identity.errors import (
    AuthenticationError,
    SessionExpiredError,
)
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)
from axon_enterprise.tenant import TenantContext, TenantPlan, set_current_tenant

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.auth"
)


_DEFAULT_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/.well-known/jwks.json",
    }
)


class AuthMiddleware:
    """Verifies the inbound JWT and installs identity ContextVars.

    Constructed via Starlette's standard ``add_middleware`` pattern:
    ``app.add_middleware(AuthMiddleware, public_paths=...)``.
    All other fields resolve from ``get_settings()``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        public_paths: frozenset[str] | None = None,
        public_prefixes: tuple[str, ...] = (),
    ) -> None:
        s = get_settings()
        metrics_path = s.observability.metrics_path
        paths = set(public_paths or _DEFAULT_PUBLIC_PATHS)
        paths.add(metrics_path)
        self.app: ASGIApp = app
        self.jwks_url: str = f"{s.jwt.issuer.rstrip('/')}/.well-known/jwks.json"
        self.issuer: str = s.jwt.issuer
        self.audience: str = s.jwt.audience
        self.public_paths: frozenset[str] = frozenset(paths)
        self.public_prefixes: tuple[str, ...] = tuple(public_prefixes)
        self.settings: JwtSettings = s.jwt
        self._jwks: _CachedJwks | None = None

    # ── ASGI ──────────────────────────────────────────────────────────

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        if (
            path in self.public_paths
            or path.startswith("/.well-known/")
            or any(path.startswith(p) for p in self.public_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        token = _extract_bearer(scope)
        if not token:
            await _send_error(
                send, AuthenticationError("Bearer token required")
            )
            return

        try:
            claims = await self._verify(token)
        except Exception as exc:  # noqa: BLE001
            await _send_error(send, exc)
            return

        principal = _principal_from_claims(claims)
        tenant_ctx = TenantContext(
            tenant_id=principal.tenant_id,
            plan=_plan_from_claim(claims.get("plan")),
            request_id=None,
        )

        tenant_token = set_current_tenant(tenant_ctx)
        principal_token = set_current_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_PRINCIPAL.reset(principal_token)
            from axon_enterprise.tenant.context import CURRENT_TENANT

            CURRENT_TENANT.reset(tenant_token)

    # ── Verification ──────────────────────────────────────────────────

    async def _verify(self, token: str) -> dict[str, Any]:
        if self._jwks is None:
            self._jwks = _CachedJwks(url=self.jwks_url)
        try:
            unverified = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise SessionExpiredError("malformed token") from exc
        alg = unverified.get("alg")
        kid = unverified.get("kid")
        if alg not in ("RS256", "RS384", "RS512"):
            raise SessionExpiredError(f"unsupported algorithm {alg!r}")
        if not kid:
            raise SessionExpiredError("missing kid")
        public_key = await self._jwks.get_pem(kid)
        try:
            return jwt.decode(
                token,
                public_key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            )
        except jwt.InvalidTokenError as exc:
            raise SessionExpiredError(str(exc)) from exc


# ── JWKS cache ───────────────────────────────────────────────────────


@dataclass
class _CachedJwks:
    url: str
    ttl_seconds: float = 600.0
    _keys: dict[str, str] = None  # type: ignore[assignment]
    _loaded_at: float = 0.0

    async def get_pem(self, kid: str) -> str:
        if self._keys and kid in self._keys and (time.monotonic() - self._loaded_at) < self.ttl_seconds:
            return self._keys[kid]
        await self._refresh()
        if self._keys is None or kid not in self._keys:
            raise SessionExpiredError(f"kid {kid!r} not in JWKS")
        return self._keys[kid]

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(self.url)
        if resp.status_code != 200:
            raise SessionExpiredError(
                f"JWKS fetch failed: HTTP {resp.status_code}"
            )
        doc = resp.json()
        self._keys = {}
        for jwk in doc.get("keys", []):
            pem = _jwk_to_pem(jwk)
            if pem is not None:
                self._keys[jwk["kid"]] = pem
        self._loaded_at = time.monotonic()


def _jwk_to_pem(jwk: dict[str, Any]) -> str | None:
    if jwk.get("kty") != "RSA":
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:  # pragma: no cover
        return None
    import base64

    def _b64(s: str) -> int:
        pad = "=" * (-len(s) % 4)
        return int.from_bytes(base64.urlsafe_b64decode(s + pad), "big")

    try:
        n = _b64(jwk["n"])
        e = _b64(jwk["e"])
    except Exception:  # noqa: BLE001
        return None
    pub = rsa.RSAPublicNumbers(e=e, n=n).public_key()
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


# ── Helpers ───────────────────────────────────────────────────────────


def _extract_bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"authorization":
            try:
                text = value.decode("ascii")
            except UnicodeDecodeError:
                return None
            if text.lower().startswith("bearer "):
                return text[7:].strip() or None
    return None


def _principal_from_claims(claims: dict[str, Any]) -> PrincipalContext:
    sub = str(claims.get("sub") or "")
    raw_uid = sub.removeprefix("user:") if sub.startswith("user:") else sub
    try:
        user_id = UUID(raw_uid)
    except ValueError as exc:
        raise AuthenticationError("malformed sub claim") from exc
    tenant_id = str(claims.get("tenant_id") or "")
    if not tenant_id:
        raise AuthenticationError("missing tenant_id claim")
    roles = claims.get("roles") or []
    return PrincipalContext(
        user_id=user_id,
        email=str(claims.get("email") or ""),
        tenant_id=tenant_id,
        role_names=frozenset(r for r in roles if isinstance(r, str)),
        session_id=None,
    )


def _plan_from_claim(raw: Any) -> TenantPlan:
    if isinstance(raw, str):
        try:
            return TenantPlan(raw.lower())
        except ValueError:
            pass
    return TenantPlan.ENTERPRISE


async def _send_error(send: Send, exc: Exception) -> None:
    response = json_error(exc)
    body = response.body
    headers = [
        (b"content-type", b"application/json"),
        *[(k.encode("ascii"), v.encode("ascii")) for k, v in response.headers.items() if k.lower() != "content-length"],
    ]
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})
