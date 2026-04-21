"""Pure-Python unit tests for the ``axk_`` key format + prefix index."""

from __future__ import annotations

import pytest

from axon_enterprise.api_keys import ApiKeyInvalid
from axon_enterprise.api_keys.service import ApiKeyService, _PREFIX
from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.password import PasswordHasher


def _svc() -> ApiKeyService:
    return ApiKeyService(
        hasher=PasswordHasher(
            settings=IdentitySettings(
                argon2_time_cost=2,
                argon2_memory_cost_kib=19_456,
                argon2_parallelism=1,
                password_min_length=12,
                password_zxcvbn_min_score=0,
                password_check_hibp=False,
            )
        )
    )


def test_prefix_constant_is_stable() -> None:
    # Grep target — stays greppable in logs / access records.
    assert _PREFIX == "axk_"


@pytest.mark.asyncio
async def test_verify_rejects_non_hex_body() -> None:
    svc = _svc()
    with pytest.raises(ApiKeyInvalid):
        await svc.verify(db=None, raw_key="axk_shortkey")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_verify_rejects_missing_prefix() -> None:
    svc = _svc()
    body = "a" * 32  # correct length, wrong prefix
    with pytest.raises(ApiKeyInvalid):
        await svc.verify(db=None, raw_key=body)  # type: ignore[arg-type]
