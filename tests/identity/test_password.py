"""Unit tests for ``PasswordHasher``. No Docker required."""

from __future__ import annotations

import pytest

from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.errors import InvalidCredentialsError
from axon_enterprise.identity.password import PasswordHasher


@pytest.fixture
def hasher() -> PasswordHasher:
    # Smaller parameters so tests don't burn a full second of CPU each.
    return PasswordHasher.from_settings(
        IdentitySettings(
            argon2_time_cost=2,
            argon2_memory_cost_kib=19_456,
            argon2_parallelism=1,
        )
    )


def test_hash_and_verify_roundtrip(hasher: PasswordHasher) -> None:
    h = hasher.hash("CorrectHorseBatteryStaple")
    assert h.startswith("$argon2id$")
    assert hasher.verify(h, "CorrectHorseBatteryStaple") is True


def test_wrong_password_raises(hasher: PasswordHasher) -> None:
    h = hasher.hash("secret")
    with pytest.raises(InvalidCredentialsError):
        hasher.verify(h, "wrong")


def test_unparseable_hash_raises(hasher: PasswordHasher) -> None:
    with pytest.raises(InvalidCredentialsError):
        hasher.verify("not-a-hash", "secret")


def test_hash_is_never_the_same_twice(hasher: PasswordHasher) -> None:
    a = hasher.hash("same-password")
    b = hasher.hash("same-password")
    assert a != b, "each hash uses a fresh salt"


def test_needs_rehash_on_unparseable(hasher: PasswordHasher) -> None:
    assert hasher.needs_rehash("not-a-hash") is True


def test_needs_rehash_false_for_current_params(hasher: PasswordHasher) -> None:
    h = hasher.hash("current")
    assert hasher.needs_rehash(h) is False


def test_needs_rehash_true_for_stronger_params(hasher: PasswordHasher) -> None:
    # Hash with weak params, verify with stronger params → rehash required.
    weak_hasher = PasswordHasher.from_settings(
        IdentitySettings(
            argon2_time_cost=2, argon2_memory_cost_kib=19_456, argon2_parallelism=1
        )
    )
    strong_hasher = PasswordHasher.from_settings(
        IdentitySettings(
            argon2_time_cost=3, argon2_memory_cost_kib=65_536, argon2_parallelism=4
        )
    )
    h = weak_hasher.hash("pw")
    assert strong_hasher.needs_rehash(h) is True


def test_burn_equivalent_time_does_not_raise(hasher: PasswordHasher) -> None:
    # Must silently complete — timing-parity side of login.
    hasher.burn_equivalent_time("ignored-password")
