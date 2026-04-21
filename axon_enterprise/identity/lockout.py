"""Progressive login lockout policy.

Thresholds (configurable):

    - ``lockout_threshold_soft``       (default 5)  → 15 minute lock
    - ``lockout_threshold_hard``       (default 10) → 1 hour lock
    - ``lockout_threshold_permanent``  (default 20) → indefinite lock

The policy is pure — given the current ``failed_logins`` count and the
settings, it decides whether to lock and for how long. The AuthService
stores the resulting ``locked_until`` on the user row and clears
``failed_logins`` on successful login.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from axon_enterprise.config import IdentitySettings, get_settings


@dataclass(frozen=True)
class LockoutDecision:
    """Outcome of ``LockoutPolicy.evaluate``."""

    should_lock: bool
    locked_until: datetime | None  # None + should_lock=True → permanent lock
    reason: str

    @classmethod
    def none(cls) -> LockoutDecision:
        return cls(should_lock=False, locked_until=None, reason="below threshold")


@dataclass(frozen=True)
class LockoutPolicy:
    """Maps a count of consecutive failures to a lock duration."""

    settings: IdentitySettings

    @classmethod
    def default(cls) -> LockoutPolicy:
        return cls(settings=get_settings().identity)

    def evaluate(
        self,
        *,
        failed_logins: int,
        now: datetime | None = None,
    ) -> LockoutDecision:
        """Return the lock decision for the new ``failed_logins`` count.

        ``failed_logins`` should be the post-increment value — i.e. pass
        ``old_count + 1`` so the decision reflects the current failure.
        """
        now = now or datetime.now(timezone.utc)
        s = self.settings

        if failed_logins >= s.lockout_threshold_permanent:
            return LockoutDecision(
                should_lock=True,
                locked_until=None,
                reason=f"permanent lock at {failed_logins} failures",
            )
        if failed_logins >= s.lockout_threshold_hard:
            return LockoutDecision(
                should_lock=True,
                locked_until=now + timedelta(minutes=s.lockout_duration_hard_minutes),
                reason=f"hard lock ({s.lockout_duration_hard_minutes}m) at {failed_logins} failures",
            )
        if failed_logins >= s.lockout_threshold_soft:
            return LockoutDecision(
                should_lock=True,
                locked_until=now + timedelta(minutes=s.lockout_duration_soft_minutes),
                reason=f"soft lock ({s.lockout_duration_soft_minutes}m) at {failed_logins} failures",
            )
        return LockoutDecision.none()

    @staticmethod
    def is_currently_locked(
        locked_until: datetime | None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """True when the user row's ``locked_until`` is still in the future.

        Rows with ``locked_until = None`` are NOT locked (lock was never
        applied or has been cleared). Permanently-locked users have a
        separate ``status = 'locked'`` flag on the user row — this
        helper only answers the time-based question.
        """
        if locked_until is None:
            return False
        now = now or datetime.now(timezone.utc)
        return locked_until > now
