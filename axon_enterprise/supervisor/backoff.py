"""
Decorrelated-jitter exponential backoff (Fase 16.h).

Reference: Marc Brooker, "Exponential Backoff And Jitter", AWS
Architecture Blog, 2015. The decorrelated-jitter algorithm provides
the best statistical properties for a distributed restart scenario:

    sleep = min(cap, random.uniform(base, prev_sleep * 3))

This gives:
  * Lower variance than full jitter at low call counts.
  * No thundering herd: 100 simultaneous restarts spread across the
    range, not all at the cap.
  * Bounded by `cap` so a runaway daemon can't sleep forever.

The OSS supervisor uses a simple linear-cap backoff
(`0.1 * min(restart_count, 10)`); the enterprise hook replaces it
with this algorithm. State (the previous sleep) lives in the
`DecorrelatedJitterBackoff` instance, indexed by daemon name.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Final


_DEFAULT_BASE_S: Final[float] = 0.1
_DEFAULT_CAP_S: Final[float] = 300.0  # 5 minutes — enough for transient infra blips
_DEFAULT_GROWTH: Final[float] = 3.0


@dataclass
class DecorrelatedJitterBackoff:
    """Per-daemon decorrelated-jitter backoff state.

    Construct one supervisor-wide instance and call
    `next_delay(daemon_name)` from inside `on_daemon_restart`. The
    instance keeps a per-daemon `prev_delay` so each daemon's backoff
    grows independently.
    """

    base_s: float = _DEFAULT_BASE_S
    cap_s: float = _DEFAULT_CAP_S
    growth: float = _DEFAULT_GROWTH
    _prev_delay: dict[str, float] = field(default_factory=dict)

    def next_delay(self, daemon_name: str) -> float:
        """Compute the next backoff delay for `daemon_name`.

        The first call for a given daemon seeds `prev_delay = base_s`.
        Subsequent calls compute `min(cap, U(base, prev * growth))`.
        Thread/async-safe: only one writer per daemon name expected
        (the supervisor's restart cascade is serialized via the
        `_cascade_in_progress` flag).
        """
        prev = self._prev_delay.get(daemon_name, self.base_s)
        upper = max(self.base_s, prev * self.growth)
        delay = min(self.cap_s, random.uniform(self.base_s, upper))
        self._prev_delay[daemon_name] = delay
        return delay

    def reset(self, daemon_name: str) -> None:
        """Clear the per-daemon backoff state. Call after a successful
        run so the next crash starts from `base_s` again."""
        self._prev_delay.pop(daemon_name, None)

    def reset_all(self) -> None:
        """Clear backoff state for every daemon."""
        self._prev_delay.clear()
