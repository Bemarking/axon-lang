"""Unit tests for the progressive lockout ladder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.lockout import LockoutPolicy


def _policy(**overrides) -> LockoutPolicy:
    base = dict(
        lockout_threshold_soft=5,
        lockout_duration_soft_minutes=15,
        lockout_threshold_hard=10,
        lockout_duration_hard_minutes=60,
        lockout_threshold_permanent=20,
    )
    base.update(overrides)
    return LockoutPolicy(settings=IdentitySettings(**base))


NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("failures", [0, 1, 3, 4])
def test_below_soft_threshold_no_lock(failures: int) -> None:
    d = _policy().evaluate(failed_logins=failures, now=NOW)
    assert d.should_lock is False
    assert d.locked_until is None


def test_soft_threshold_locks_15_min() -> None:
    d = _policy().evaluate(failed_logins=5, now=NOW)
    assert d.should_lock is True
    assert d.locked_until == NOW + timedelta(minutes=15)


def test_hard_threshold_locks_60_min() -> None:
    d = _policy().evaluate(failed_logins=10, now=NOW)
    assert d.should_lock is True
    assert d.locked_until == NOW + timedelta(minutes=60)


def test_permanent_threshold_locks_indefinitely() -> None:
    d = _policy().evaluate(failed_logins=20, now=NOW)
    assert d.should_lock is True
    assert d.locked_until is None
    assert "permanent" in d.reason.lower()


def test_is_currently_locked_future() -> None:
    future = NOW + timedelta(minutes=5)
    assert LockoutPolicy.is_currently_locked(future, now=NOW) is True


def test_is_currently_locked_past() -> None:
    past = NOW - timedelta(minutes=5)
    assert LockoutPolicy.is_currently_locked(past, now=NOW) is False


def test_is_currently_locked_none() -> None:
    assert LockoutPolicy.is_currently_locked(None, now=NOW) is False
