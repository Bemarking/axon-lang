"""Timing parity — verify the user-enumeration mitigation works.

The login path calls ``PasswordHasher.burn_equivalent_time`` when
the email doesn't match so the wall-clock cost of ``authenticate``
is the same for "unknown email" and "wrong password". This is the
primary defence against user enumeration via login timing.

We don't need a perfect match — just that the two paths are within
a small tolerance of each other under identical Argon2 params.
"""

from __future__ import annotations

import time
import statistics

import pytest

from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.password import PasswordHasher


def _fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        settings=IdentitySettings(
            argon2_time_cost=2,
            argon2_memory_cost_kib=19_456,
            argon2_parallelism=1,
            password_min_length=12,
            password_zxcvbn_min_score=0,
            password_check_hibp=False,
        )
    )


def _measure(fn, *, runs: int = 5) -> float:
    """Return median elapsed seconds over ``runs`` invocations."""
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


@pytest.mark.slow
def test_burn_equivalent_time_matches_verify() -> None:
    hasher = _fast_hasher()
    password = "CorrectHorseBatteryStaple-2026"
    stored = hasher.hash(password)

    # Baseline — real verify against the stored hash.
    def _verify():
        hasher.verify(stored, password)

    # Decoy — burn equivalent time without a stored row.
    def _burn():
        hasher.burn_equivalent_time("any-incoming-attempt-value")

    verify_median = _measure(_verify)
    burn_median = _measure(_burn)

    # Tolerance: within 50% of each other. Wide because CI shared
    # runners are noisy; the important guarantee is "not a factor of
    # 10x different", which would give an attacker a reliable signal.
    ratio = max(verify_median, burn_median) / min(
        verify_median, burn_median
    )
    assert ratio < 1.5, (
        f"timing parity broken: verify={verify_median*1000:.1f}ms, "
        f"burn={burn_median*1000:.1f}ms, ratio={ratio:.2f}"
    )


@pytest.mark.slow
def test_wrong_password_verify_and_burn_comparable() -> None:
    hasher = _fast_hasher()
    stored = hasher.hash("real-password-9999999")

    def _verify_wrong():
        from argon2.exceptions import VerifyMismatchError

        try:
            hasher.verify(stored, "wrong-password-9999")
        except VerifyMismatchError:
            pass

    def _burn():
        hasher.burn_equivalent_time("any-incoming-attempt-value")

    v = _measure(_verify_wrong)
    b = _measure(_burn)
    ratio = max(v, b) / min(v, b)
    assert ratio < 1.5
