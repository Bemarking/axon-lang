"""``/api/v1/auth/*`` — password login, refresh, logout, invite accept.

Public routes (no bearer required): login, refresh, accept invite.
Other services (SSO callback, password reset) live in companion
modules. JWT minting uses the 10.e ``JwtIssuer``.

These routes are added to the AuthMiddleware's public_paths so the
middleware does NOT require a valid bearer to reach them.
"""

from __future__ import annotations

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.identity import (
    AuthService,
    InvalidCredentialsError,
    SessionService,
)
from axon_enterprise.identity.principal import PrincipalContext
from axon_enterprise.invitations import InvitationService
from axon_enterprise.jwt_issuer import JwtIssuer

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.api.auth"
)


async def _login(request: Request) -> JSONResponse:
    """Password + TOTP login → access token + refresh token."""
    body = await request.json()
    email = str(body.get("email") or "").strip()
    password = str(body.get("password") or "")
    tenant_id = str(body.get("tenant_id") or "").strip()
    totp_code = body.get("totp_code")

    if not email or not password or not tenant_id:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "message": "email, password, tenant_id required",
                }
            },
            status_code=400,
        )

    auth = AuthService.default()
    issuer = JwtIssuer.default()
    async with admin_session() as db:
        result = await auth.authenticate(
            db,
            email=email,
            password=password,
            tenant_id=tenant_id,
            totp_code=str(totp_code) if totp_code is not None else None,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        principal = PrincipalContext(
            user_id=result.user.user_id,
            email=result.user.email,
            tenant_id=tenant_id,
            role_names=frozenset(),  # coarse — fine-grained per-call
            session_id=result.session.session.session_id,
        )
        issued_jwt = await issuer.mint(db, principal=principal)

    return JSONResponse(
        {
            "access_token": issued_jwt.token,
            "expires_at": issued_jwt.expires_at.isoformat(),
            "refresh_token": result.session.raw_refresh_token,
            "user": {
                "user_id": str(result.user.user_id),
                "email": result.user.email,
                "display_name": result.user.display_name,
            },
            "tenant_id": tenant_id,
        }
    )


async def _refresh(request: Request) -> JSONResponse:
    """Rotate a refresh token + mint a new access JWT."""
    body = await request.json()
    raw_refresh = str(body.get("refresh_token") or "")
    if not raw_refresh:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_input",
                    "message": "refresh_token required",
                }
            },
            status_code=400,
        )

    sessions = SessionService.default()
    issuer = JwtIssuer.default()
    async with admin_session() as db:
        rotated = await sessions.verify_and_rotate(
            db,
            raw_refresh_token=raw_refresh,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        principal = PrincipalContext(
            user_id=rotated.session.user_id,
            email="",
            tenant_id=rotated.session.tenant_id,
            role_names=frozenset(),
            session_id=rotated.session.session_id,
        )
        access = await issuer.mint(db, principal=principal)

    return JSONResponse(
        {
            "access_token": access.token,
            "expires_at": access.expires_at.isoformat(),
            "refresh_token": rotated.raw_refresh_token,
        }
    )


async def _logout(request: Request) -> JSONResponse:
    """Revoke the supplied refresh token."""
    body = await request.json() if await request.body() else {}
    raw_refresh = str(body.get("refresh_token") or "")
    if not raw_refresh:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    sessions = SessionService.default()
    from axon_enterprise.identity.models import Session

    async with admin_session() as db:
        hashed = sessions.hash_token(raw_refresh)
        row = await db.scalar(
            __import__("sqlalchemy").select(Session).where(
                Session.refresh_token_hash == hashed
            )
        )
        if row is not None and row.revoked_at is None:
            await sessions.revoke(
                db, session_id=row.session_id, reason="user_logout"
            )
    return JSONResponse({"status": "ok"})


async def _accept_invite(request: Request) -> JSONResponse:
    """Consume a magic-link invitation token + mint an access JWT."""
    body = await request.json()
    raw_token = str(body.get("token") or "")
    if not raw_token:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    invitations = InvitationService()
    sessions = SessionService.default()
    issuer = JwtIssuer.default()
    async with admin_session() as db:
        membership = await invitations.accept(db, raw_token=raw_token)
        issued_session = await sessions.create(
            db,
            user_id=membership.user_id,
            tenant_id=membership.tenant_id,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        principal = PrincipalContext(
            user_id=membership.user_id,
            email="",
            tenant_id=membership.tenant_id,
            role_names=frozenset(),
            session_id=issued_session.session.session_id,
        )
        access = await issuer.mint(db, principal=principal)

    return JSONResponse(
        {
            "access_token": access.token,
            "expires_at": access.expires_at.isoformat(),
            "refresh_token": issued_session.raw_refresh_token,
            "tenant_id": membership.tenant_id,
        }
    )


def routes() -> list[Route]:
    return [
        Route("/login", _login, methods=["POST"]),
        Route("/refresh", _refresh, methods=["POST"]),
        Route("/logout", _logout, methods=["POST"]),
        Route("/invite/accept", _accept_invite, methods=["POST"]),
    ]
