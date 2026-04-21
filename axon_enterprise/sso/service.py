"""SsoService — orchestrates login + auto-provisioning end-to-end.

Composes OidcProvider / SamlProvider with the identity layer so a
single call transforms an IdP response into an authenticated
``Session`` row:

    1. Delegate to the provider to get a ``MappedIdentity``.
    2. Upsert the ``User`` row (creating on first login when
       ``auto_provision=true``; existing users refresh display_name +
       email_verified).
    3. Upsert ``TenantMembership`` + assign ``default_role_id`` when
       provisioning is happening and a default was configured.
    4. Apply ``role_map`` to bind IdP groups to Axon roles.
    5. Mint a fresh ``Session`` via ``SessionService``.

Rate limiting: every auto-provisioning call consults
``InMemoryRateLimiter`` to cap new-user creations per IdP per
minute — defence against token-forgery floods.

Audit emission is stubbed (structured log) until Fase 10.g wires the
hash-chained audit log; callers who pass an ``audit_context`` helper
have their event emitted via that path when the audit service is in
place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.identity.models import (
    MembershipStatus,
    TenantMembership,
    User,
    UserStatus,
)
from axon_enterprise.identity.sessions import IssuedSession, SessionService
from axon_enterprise.rbac.models import Role, UserRole
from axon_enterprise.rbac.service import RbacService
from axon_enterprise.sso.configurations import (
    SsoConfigurationService,
)
from axon_enterprise.sso.errors import (
    SsoConfigurationInvalid,
)
from axon_enterprise.sso.mapper import (
    MappedIdentity,
    map_oidc_identity,
    map_saml_identity,
    resolve_axon_roles,
)
from axon_enterprise.sso.models import SsoProviderType
from axon_enterprise.sso.oidc import OidcProvider
from axon_enterprise.sso.rate_limit import InMemoryRateLimiter
from axon_enterprise.sso.saml import SamlProvider

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.sso.service"
)


class SsoLoginResult(NamedTuple):
    user: User
    session: IssuedSession
    is_new_user: bool


@dataclass
class SsoService:
    """Orchestrates the full ``initiate`` / ``complete`` login cycle."""

    oidc: OidcProvider
    saml: SamlProvider
    config_store: SsoConfigurationService
    sessions: SessionService
    rbac: RbacService
    rate_limiter: InMemoryRateLimiter

    @classmethod
    def build(cls) -> SsoService:
        return cls(
            oidc=OidcProvider.build(),
            saml=SamlProvider.build(),
            config_store=SsoConfigurationService.default(),
            sessions=SessionService.default(),
            rbac=RbacService.default(),
            rate_limiter=InMemoryRateLimiter.default(),
        )

    async def aclose(self) -> None:
        await self.oidc.aclose()

    # ── Initiate ──────────────────────────────────────────────────────

    async def initiate_oidc(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        return_url: str | None = None,
    ) -> str:
        """Return the authorization URL to redirect the browser to."""
        result = await self.oidc.initiate(
            db, tenant_id=tenant_id, return_url=return_url
        )
        return result.authorization_url

    async def initiate_saml(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        return_url: str | None = None,
    ) -> str:
        result = await self.saml.initiate(
            db, tenant_id=tenant_id, return_url=return_url
        )
        return result.redirect_url

    # ── Complete ──────────────────────────────────────────────────────

    async def complete_oidc(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        state: str,
        code: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> SsoLoginResult:
        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.OIDC
        )
        validated = await self.oidc.complete(
            db, tenant_id=tenant_id, state=state, code=code
        )
        mapped = map_oidc_identity(
            validated.claims, attribute_map=config.attribute_map
        )
        return await self._finalise(
            db,
            tenant_id=tenant_id,
            provider_type=SsoProviderType.OIDC,
            mapped=mapped,
            role_map=config.role_map,
            auto_provision=config.auto_provision,
            default_role_id=config.default_role_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def complete_saml(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        saml_response_b64: str,
        relay_state: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> SsoLoginResult:
        config = await self.config_store.get(
            db, tenant_id=tenant_id, provider_type=SsoProviderType.SAML
        )
        assertion = await self.saml.complete(
            db,
            tenant_id=tenant_id,
            saml_response_b64=saml_response_b64,
            relay_state=relay_state,
        )
        mapped = map_saml_identity(
            assertion.subject_nameid,
            assertion.attributes,
            attribute_map=config.attribute_map,
        )
        return await self._finalise(
            db,
            tenant_id=tenant_id,
            provider_type=SsoProviderType.SAML,
            mapped=mapped,
            role_map=config.role_map,
            auto_provision=config.auto_provision,
            default_role_id=config.default_role_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    # ── Shared finalise ──────────────────────────────────────────────

    async def _finalise(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_type: SsoProviderType,
        mapped: MappedIdentity,
        role_map: dict[str, str],
        auto_provision: bool,
        default_role_id: object | None,
        user_agent: str | None,
        ip_address: str | None,
    ) -> SsoLoginResult:
        # 1. Upsert user
        user = await db.scalar(select(User).where(User.email == mapped.email))
        is_new_user = False
        now = datetime.now(timezone.utc)
        if user is None:
            if not auto_provision:
                raise SsoConfigurationInvalid(
                    f"{mapped.email} has no account and auto_provision=false"
                )
            self.rate_limiter.check_and_record(
                tenant_id=tenant_id, provider_type=provider_type.value
            )
            user = User(
                email=mapped.email,
                display_name=mapped.display_name,
                email_verified=True,
                email_verified_at=now,
                status=UserStatus.ACTIVE.value,
            )
            db.add(user)
            await db.flush()
            is_new_user = True
            _logger.info(
                "sso_user_provisioned",
                tenant_id=tenant_id,
                provider=provider_type.value,
                user_id=str(user.user_id),
                email=user.email,
            )
        else:
            # Refresh display_name + verification on every login.
            if mapped.display_name and user.display_name != mapped.display_name:
                user.display_name = mapped.display_name
            if not user.email_verified:
                user.email_verified = True
                user.email_verified_at = now
            user.last_login_at = now
            user.last_login_ip = ip_address
            await db.flush()

        # 2. Upsert membership
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user.user_id,
            )
        )
        if membership is None:
            membership = TenantMembership(
                tenant_id=tenant_id,
                user_id=user.user_id,
                status=MembershipStatus.ACTIVE.value,
                joined_at=now,
            )
            db.add(membership)
            await db.flush()
        elif membership.status == MembershipStatus.INVITED.value:
            membership.status = MembershipStatus.ACTIVE.value
            membership.joined_at = now
            await db.flush()

        # 3. Default role for new users + any role_map hits
        if is_new_user and default_role_id is not None:
            await self.rbac.assign_role(
                db,
                user_id=user.user_id,
                role_id=default_role_id,  # type: ignore[arg-type]
                tenant_id=tenant_id,
            )

        mapped_role_names = resolve_axon_roles(mapped, role_map=role_map)
        if mapped_role_names:
            await self._sync_mapped_roles(
                db,
                tenant_id=tenant_id,
                user_id=user.user_id,
                role_names=mapped_role_names,
            )

        # 4. Issue session
        issued = await self.sessions.create(
            db,
            user_id=user.user_id,
            tenant_id=tenant_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await db.flush()

        _logger.info(
            "sso_login_complete",
            tenant_id=tenant_id,
            provider=provider_type.value,
            user_id=str(user.user_id),
            is_new_user=is_new_user,
            session_id=str(issued.session.session_id),
        )
        return SsoLoginResult(user=user, session=issued, is_new_user=is_new_user)

    async def _sync_mapped_roles(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id,
        role_names: list[str],
    ) -> None:
        """Assign each role in ``role_names`` that exists in this tenant.

        We deliberately do NOT revoke roles not present in the map —
        admins can grant additional roles out-of-band and those should
        survive an SSO login. If a tenant wants strict IdP-driven
        role sync, a future ``role_sync_mode=strict`` flag on the
        SsoConfiguration enables the revoke path.
        """
        if not role_names:
            return
        rows = (
            (
                await db.execute(
                    select(Role).where(
                        Role.tenant_id == tenant_id,
                        Role.name.in_(role_names),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_assignments = {
            (ur.role_id, ur.user_id)
            for ur in (
                (
                    await db.execute(
                        select(UserRole).where(
                            UserRole.user_id == user_id,
                            UserRole.tenant_id == tenant_id,
                        )
                    )
                ).scalars()
            )
        }
        for role in rows:
            if (role.role_id, user_id) in existing_assignments:
                continue
            await self.rbac.assign_role(
                db,
                user_id=user_id,
                role_id=role.role_id,
                tenant_id=tenant_id,
            )
