"""Signing-key lifecycle: register, rotate, retire.

One row in ``jwt_signing_keys`` at any time has ``status='active'``;
that is the key ``JwtIssuer`` currently signs with. When operators
rotate, the current active key transitions to ``grace`` (retained
in JWKS so tokens minted moments before rotation still verify) and
a fresh key is inserted as ``active``. A daily cron retires grace
keys whose ``grace_until`` is in the past.

Operator invocations (typically via the CLI in 10.j):

    await KeyManagementService().register_kms_key(
        db, kms_key_arn="arn:aws:kms:us-east-1:...:key/..."
    )
    await KeyManagementService().rotate(db)
    await KeyManagementService().retire_expired_grace_keys(db)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import JwtSettings, get_settings
from axon_enterprise.jwt_issuer.errors import (
    JwtKeyNotFound,
    NoActiveSigningKey,
)
from axon_enterprise.jwt_issuer.kms_signer import KmsSigner
from axon_enterprise.jwt_issuer.local_signer import LocalSigner
from axon_enterprise.jwt_issuer.models import JwtSigningKey, SigningKeyStatus
from axon_enterprise.jwt_issuer.signer import Signer

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.jwt_issuer.key_management"
)


@dataclass(frozen=True)
class KeyManagementService:
    """CRUD + transitions for ``jwt_signing_keys`` rows."""

    # ── Queries ───────────────────────────────────────────────────────

    async def get_active(self, db: AsyncSession) -> JwtSigningKey:
        row = await db.scalar(
            select(JwtSigningKey).where(
                JwtSigningKey.status == SigningKeyStatus.ACTIVE.value
            )
        )
        if row is None:
            raise NoActiveSigningKey("no signing key has status='active'")
        return row

    async def list_verifiable(self, db: AsyncSession) -> Sequence[JwtSigningKey]:
        """Keys that belong in the JWKS response (active + grace)."""
        res = await db.execute(
            select(JwtSigningKey).where(
                JwtSigningKey.status.in_(
                    (
                        SigningKeyStatus.ACTIVE.value,
                        SigningKeyStatus.GRACE.value,
                    )
                )
            )
        )
        return list(res.scalars())

    async def get_by_kid(self, db: AsyncSession, kid: str) -> JwtSigningKey:
        row = await db.scalar(
            select(JwtSigningKey).where(JwtSigningKey.kid == kid)
        )
        if row is None:
            raise JwtKeyNotFound(kid)
        return row

    # ── Registration ──────────────────────────────────────────────────

    async def register_local_key(
        self,
        db: AsyncSession,
        signer: LocalSigner,
        *,
        status: SigningKeyStatus = SigningKeyStatus.ACTIVE,
    ) -> JwtSigningKey:
        """Register a LocalSigner as a signing key row.

        Used by bootstrap / tests. Ensures no other row shares the
        same ``kid``.
        """
        existing = await db.scalar(
            select(JwtSigningKey).where(JwtSigningKey.kid == signer.info.kid)
        )
        if existing is not None:
            return existing
        if status is SigningKeyStatus.ACTIVE:
            await self._demote_current_active(db)
        now = datetime.now(timezone.utc)
        row = JwtSigningKey(
            kid=signer.info.kid,
            algorithm=signer.info.algorithm,
            backend="local",
            key_material_ref=f"local:{signer.info.kid}",
            public_key_pem=signer.info.public_key_pem,
            status=status.value,
            activated_at=now if status is SigningKeyStatus.ACTIVE else None,
        )
        db.add(row)
        await db.flush()
        _logger.info(
            "signing_key_registered",
            backend="local",
            kid=signer.info.kid,
            status=status.value,
        )
        return row

    async def register_kms_key(
        self,
        db: AsyncSession,
        *,
        kms_key_arn: str,
        algorithm: str = "RS256",
        region: str | None = None,
        status: SigningKeyStatus = SigningKeyStatus.ACTIVE,
    ) -> JwtSigningKey:
        """Fetch the public key from KMS + insert the row."""
        signer = KmsSigner.from_kms_arn(
            kms_key_arn, algorithm=algorithm, region=region
        )
        existing = await db.scalar(
            select(JwtSigningKey).where(JwtSigningKey.kid == signer.info.kid)
        )
        if existing is not None:
            return existing
        if status is SigningKeyStatus.ACTIVE:
            await self._demote_current_active(db)
        now = datetime.now(timezone.utc)
        row = JwtSigningKey(
            kid=signer.info.kid,
            algorithm=signer.info.algorithm,
            backend="kms",
            key_material_ref=kms_key_arn,
            public_key_pem=signer.info.public_key_pem,
            status=status.value,
            activated_at=now if status is SigningKeyStatus.ACTIVE else None,
        )
        db.add(row)
        await db.flush()
        _logger.info(
            "signing_key_registered",
            backend="kms",
            kid=signer.info.kid,
            kms_arn=kms_key_arn,
            status=status.value,
        )
        return row

    # ── Rotation ─────────────────────────────────────────────────────

    async def rotate(
        self,
        db: AsyncSession,
        *,
        new_kms_key_arn: str | None = None,
        new_local_signer: LocalSigner | None = None,
        settings: JwtSettings | None = None,
    ) -> JwtSigningKey:
        """Move the current active key to ``grace`` and insert a new active.

        Either supply a ``new_kms_key_arn`` (production path) or a
        ``new_local_signer`` (tests / operator-bootstrap).
        """
        settings = settings or get_settings().jwt
        if new_kms_key_arn is not None:
            return await self.register_kms_key(
                db,
                kms_key_arn=new_kms_key_arn,
                algorithm=settings.algorithm,
                region=settings.kms_region,
                status=SigningKeyStatus.ACTIVE,
            )
        if new_local_signer is not None:
            return await self.register_local_key(
                db, new_local_signer, status=SigningKeyStatus.ACTIVE
            )
        raise ValueError(
            "rotate() requires either new_kms_key_arn or new_local_signer"
        )

    async def retire_expired_grace_keys(self, db: AsyncSession) -> int:
        """Transition ``grace`` keys past their ``grace_until`` to ``retired``.

        Safe to run as a daily cron. Returns the number of rows
        moved. Retired keys stay in the table for audit but are
        excluded from the JWKS response.
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(JwtSigningKey)
            .where(
                JwtSigningKey.status == SigningKeyStatus.GRACE.value,
                JwtSigningKey.grace_until.is_not(None),
                JwtSigningKey.grace_until <= now,
            )
            .values(status=SigningKeyStatus.RETIRED.value, retired_at=now)
        )
        await db.flush()
        n = int(result.rowcount or 0)
        if n:
            _logger.info("grace_keys_retired", count=n)
        return n

    # ── Internals ─────────────────────────────────────────────────────

    async def _demote_current_active(self, db: AsyncSession) -> None:
        """Move the current active row (if any) to ``grace``."""
        settings = get_settings().jwt
        now = datetime.now(timezone.utc)
        grace_until = now + timedelta(days=settings.rotation_grace_days)
        await db.execute(
            update(JwtSigningKey)
            .where(JwtSigningKey.status == SigningKeyStatus.ACTIVE.value)
            .values(
                status=SigningKeyStatus.GRACE.value,
                grace_until=grace_until,
            )
        )
        await db.flush()


def resolve_active_kms_signer(settings: JwtSettings) -> KmsSigner:
    """Synchronous lookup used by ``Signer.build_default_signer``.

    Falls back to a simple env-var-driven construction when no row
    is available yet; at runtime the JwtIssuer uses ``load_signer``
    which goes through the DB.
    """
    import os

    arn = os.environ.get("AXON_JWT_KMS_KEY_ARN")
    if not arn:
        raise NoActiveSigningKey(
            "AXON_JWT_KMS_KEY_ARN unset. Register a key via "
            "`KeyManagementService.register_kms_key` or export the "
            "env var for the current active key."
        )
    return KmsSigner.from_kms_arn(
        arn, algorithm=settings.algorithm, region=settings.kms_region
    )


async def load_signer_for_row(
    row: JwtSigningKey, *, settings: JwtSettings | None = None
) -> Signer:
    """Hydrate a ``Signer`` instance from a ``JwtSigningKey`` row.

    The DB row contains the public key; the private material lives
    in-process (local) or in KMS (kms).
    """
    settings = settings or get_settings().jwt
    if row.backend == "kms":
        return KmsSigner.from_kms_arn(
            row.key_material_ref,
            algorithm=row.algorithm,
            region=settings.kms_region,
            kid=row.kid,
        )
    # Local backend: the private key must be available to this process
    # via AXON_JWT_LOCAL_PRIVATE_KEY_PEM. The DB row stores only the
    # public PEM — never the private key.
    if settings.local_private_key_pem is None:
        raise NoActiveSigningKey(
            f"row kid={row.kid} is local-backed but no private key "
            "configured in this process; set AXON_JWT_LOCAL_PRIVATE_KEY_PEM"
        )
    return LocalSigner.from_pem(
        settings.local_private_key_pem.get_secret_value(),
        algorithm=row.algorithm,
        kid=row.kid,
    )
