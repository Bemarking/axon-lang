"""``/api/v1/sso/*`` — OIDC + SAML HTTP routes.

Delegates to the ``SsoService`` from 10.d. This module is the thin
Starlette adapter that translates HTTP inputs into ``initiate`` /
``complete`` calls + serialises the result.

Supported flows:

    POST /sso/oidc/initiate                   returns {"authorization_url"}
    GET  /sso/oidc/callback?state=&code=      completes the flow, returns
                                              access + refresh tokens
    GET  /sso/saml/{tenant}/metadata.xml      SP metadata for IdP config
    POST /sso/saml/{tenant}/acs               SAML ACS endpoint (HTTP-POST)
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.identity import SessionService
from axon_enterprise.identity.principal import PrincipalContext
from axon_enterprise.jwt_issuer import JwtIssuer
from axon_enterprise.sso import (
    SpMetadataInput,
    SsoConfigurationService,
    SsoProviderType,
    SsoService,
    build_sp_metadata_xml,
)


async def _oidc_initiate(request: Request) -> JSONResponse:
    body = await request.json()
    tenant_id = str(body.get("tenant_id") or "").strip()
    return_url = body.get("return_url")
    if not tenant_id:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    svc = SsoService.build()
    try:
        async with admin_session() as db:
            url = await svc.initiate_oidc(
                db, tenant_id=tenant_id, return_url=return_url
            )
    finally:
        await svc.aclose()
    return JSONResponse({"authorization_url": url})


async def _oidc_callback(request: Request) -> JSONResponse:
    params = request.query_params
    tenant_id = params.get("tenant_id") or ""
    state = params.get("state") or ""
    code = params.get("code") or ""
    if not tenant_id or not state or not code:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    svc = SsoService.build()
    issuer = JwtIssuer.default()
    try:
        async with admin_session() as db:
            result = await svc.complete_oidc(
                db,
                tenant_id=tenant_id,
                state=state,
                code=code,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
            principal = PrincipalContext(
                user_id=result.user.user_id,
                email=result.user.email,
                tenant_id=tenant_id,
                role_names=frozenset(),
                session_id=result.session.session.session_id,
            )
            access = await issuer.mint(db, principal=principal)
    finally:
        await svc.aclose()

    return JSONResponse(
        {
            "access_token": access.token,
            "refresh_token": result.session.raw_refresh_token,
            "tenant_id": tenant_id,
            "is_new_user": result.is_new_user,
        }
    )


async def _saml_metadata(request: Request) -> PlainTextResponse:
    tenant_id = request.path_params["tenant_id"]
    config_svc = SsoConfigurationService.default()
    async with admin_session() as db:
        resolved = await config_svc.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.SAML
        )
    xml = build_sp_metadata_xml(
        SpMetadataInput(
            entity_id=resolved.payload["sp_entity_id"],
            acs_url=resolved.payload["sp_acs_url"],
            slo_url=resolved.payload.get("sp_slo_url"),
            x509_cert_pem=resolved.payload.get("sp_x509_cert"),
        )
    )
    return PlainTextResponse(xml, media_type="application/samlmetadata+xml")


async def _saml_acs(request: Request) -> JSONResponse:
    tenant_id = request.path_params["tenant_id"]
    form = await request.form()
    saml_response = str(form.get("SAMLResponse") or "")
    relay_state = str(form.get("RelayState") or "")
    if not saml_response or not relay_state:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    svc = SsoService.build()
    issuer = JwtIssuer.default()
    try:
        async with admin_session() as db:
            result = await svc.complete_saml(
                db,
                tenant_id=tenant_id,
                saml_response_b64=saml_response,
                relay_state=relay_state,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
            principal = PrincipalContext(
                user_id=result.user.user_id,
                email=result.user.email,
                tenant_id=tenant_id,
                role_names=frozenset(),
                session_id=result.session.session.session_id,
            )
            access = await issuer.mint(db, principal=principal)
    finally:
        await svc.aclose()

    return JSONResponse(
        {
            "access_token": access.token,
            "refresh_token": result.session.raw_refresh_token,
            "tenant_id": tenant_id,
            "is_new_user": result.is_new_user,
        }
    )


def routes() -> list[Route]:
    return [
        Route("/oidc/initiate", _oidc_initiate, methods=["POST"]),
        Route("/oidc/callback", _oidc_callback, methods=["GET"]),
        Route(
            "/saml/{tenant_id}/metadata.xml",
            _saml_metadata,
            methods=["GET"],
        ),
        Route(
            "/saml/{tenant_id}/acs",
            _saml_acs,
            methods=["POST"],
        ),
    ]
