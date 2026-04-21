"""JWT forgery resistance — AuthMiddleware adversarial cases.

Attack surface of the middleware (``axon_enterprise/http/auth_middleware.py``):

1. Missing bearer → 401
2. ``alg=none`` token → rejected (unsupported alg list excludes none)
3. ``alg=HS256`` signed with a guessed secret → rejected (we only
   accept RS256/RS384/RS512)
4. Valid RS256 but with a ``kid`` that isn't in our JWKS → rejected
5. Valid signature but ``iss`` / ``aud`` don't match configured
   issuer/audience → rejected
6. Expired token → rejected (pyjwt raises ExpiredSignatureError)

These tests swap the real JWKS fetcher for a stub so we don't need
a live issuer; the middleware's signature verification is pyjwt's
job, which we trust — what we exercise here is the middleware's
own input validation.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.http.auth_middleware import AuthMiddleware
from axon_enterprise.http.errors import install_error_handlers


async def _protected(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _build_app(monkeypatch, *, kid: str, public_pem: str) -> Starlette:
    """Build an app with AuthMiddleware whose JWKS cache returns our key."""
    import axon_enterprise.http.auth_middleware as mod

    class _StaticJwks:
        url = ""

        async def get_pem(self, requested_kid: str) -> str:
            if requested_kid != kid:
                from axon_enterprise.identity.errors import SessionExpiredError

                raise SessionExpiredError(f"kid {requested_kid!r} unknown")
            return public_pem

    # Replace the real cache class with our stub by monkeypatching the
    # lazy init — AuthMiddleware.__init__ leaves _jwks=None; _verify
    # instantiates _CachedJwks on first call. We patch that attribute
    # on each middleware instance instead.

    app = Starlette(routes=[Route("/x", _protected, methods=["GET"])])
    app.add_middleware(AuthMiddleware, public_paths=frozenset())
    install_error_handlers(app)

    # Replace the module's _CachedJwks so instantiation returns our stub.
    monkeypatch.setattr(mod, "_CachedJwks", lambda **kwargs: _StaticJwks())
    return app


def _generate_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return key, pem


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.mark.asyncio
async def test_missing_bearer_returns_401(monkeypatch) -> None:
    key, pem = _generate_key_pair()
    app = _build_app(monkeypatch, kid="k1", public_pem=pem)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/x")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_alg_none_rejected(monkeypatch) -> None:
    key, pem = _generate_key_pair()
    app = _build_app(monkeypatch, kid="k1", public_pem=pem)

    # jwt.encode with algorithm="none" produces a header alg=none.
    unsigned = jwt.encode(
        {"sub": "user:abc", "tenant_id": "alpha", "aud": "any", "iss": "any", "exp": 9_999_999_999, "iat": 0},
        key="",
        algorithm="none",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get(
            "/x", headers={"Authorization": f"Bearer {unsigned}"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_kid_rejected(monkeypatch) -> None:
    key, pem = _generate_key_pair()
    app = _build_app(monkeypatch, kid="k1", public_pem=pem)

    token = jwt.encode(
        {
            "sub": "user:00000000-0000-0000-0000-000000000001",
            "tenant_id": "alpha",
            "aud": "any",
            "iss": "any",
            "exp": 9_999_999_999,
            "iat": 0,
        },
        _private_pem(key),
        algorithm="RS256",
        headers={"kid": "k-unknown"},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get(
            "/x", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_rejected(monkeypatch) -> None:
    from axon_enterprise.config import get_settings

    key, pem = _generate_key_pair()
    app = _build_app(monkeypatch, kid="k1", public_pem=pem)
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "user:00000000-0000-0000-0000-000000000001",
            "tenant_id": "alpha",
            "aud": settings.jwt.audience,
            "iss": "https://malicious.example",
            "exp": 9_999_999_999,
            "iat": 0,
        },
        _private_pem(key),
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get(
            "/x", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(monkeypatch) -> None:
    from axon_enterprise.config import get_settings

    key, pem = _generate_key_pair()
    app = _build_app(monkeypatch, kid="k1", public_pem=pem)
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "user:00000000-0000-0000-0000-000000000001",
            "tenant_id": "alpha",
            "aud": settings.jwt.audience,
            "iss": settings.jwt.issuer,
            "exp": 1,  # 1970
            "iat": 0,
        },
        _private_pem(key),
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get(
            "/x", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 401
