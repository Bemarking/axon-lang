"""Admin JWT signing key management — list / register / rotate / retire."""

from __future__ import annotations

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.jwt_issuer import (
    KeyManagementService,
    LocalSigner,
    SigningKeyStatus,
)
from axon_enterprise.rbac.errors import PermissionDenied

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.admin.keys"
)


async def _list_keys(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    km = KeyManagementService()
    async with admin_session() as db:
        keys = await km.list_verifiable(db)
        return JSONResponse(
            {
                "keys": [
                    {
                        "kid": k.kid,
                        "algorithm": k.algorithm,
                        "backend": k.backend,
                        "status": k.status,
                        "activated_at": k.activated_at.isoformat()
                        if k.activated_at
                        else None,
                        "grace_until": k.grace_until.isoformat()
                        if k.grace_until
                        else None,
                    }
                    for k in keys
                ]
            }
        )


async def _register_kms_key(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    body = await request.json()
    arn = str(body.get("kms_key_arn") or "")
    if not arn:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "kms_key_arn required"}},
            status_code=400,
        )
    km = KeyManagementService()
    async with admin_session() as db:
        row = await km.register_kms_key(db, kms_key_arn=arn)
    _logger.info("kms_key_registered", kid=row.kid, kms_arn=arn)
    return JSONResponse(
        {
            "kid": row.kid,
            "algorithm": row.algorithm,
            "status": row.status,
        },
        status_code=201,
    )


async def _rotate_keys(request: Request) -> JSONResponse:
    """Create a fresh key + demote the previous active to grace."""
    _require_admin(require_principal())
    body = await request.json()
    arn = body.get("kms_key_arn")
    km = KeyManagementService()
    async with admin_session() as db:
        if arn:
            row = await km.rotate(db, new_kms_key_arn=str(arn))
        else:
            # Fallback (dev / single-node): generate a new local signer.
            # Production always passes kms_key_arn via the CLI / portal.
            row = await km.rotate(db, new_local_signer=LocalSigner.generate())
    _logger.info("jwt_keys_rotated", new_kid=row.kid)
    return JSONResponse(
        {
            "kid": row.kid,
            "status": row.status,
        }
    )


async def _retire_grace(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    km = KeyManagementService()
    async with admin_session() as db:
        retired = await km.retire_expired_grace_keys(db)
    return JSONResponse({"retired": retired})


def _require_admin(principal) -> None:
    if "owner" not in principal.role_names and principal.tenant_id != "default":
        raise PermissionDenied("jwt keys admin")


def routes() -> list[Route]:
    return [
        Route("/", _list_keys, methods=["GET"]),
        Route("/kms", _register_kms_key, methods=["POST"]),
        Route("/rotate", _rotate_keys, methods=["POST"]),
        Route("/retire-grace", _retire_grace, methods=["POST"]),
    ]
