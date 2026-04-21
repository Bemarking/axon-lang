"""Sliding-window rate limiter for SSO auto-provisioning.

Defends against an IdP bug or malicious token-issuing IdP causing a
flood of new-user creations. Per ``(tenant_id, provider_type)`` we
allow ``sso.auto_provision_rate_limit_per_minute`` successful
provisions; additional attempts within the window raise
``SsoRateLimited``.

Storage: in-process for now (single-container deployments and tests).
A distributed variant (Redis) lands in Fase 10.i when the platform
runs multi-replica. The interface is deliberately synchronous so the
swap is a one-line change in ``SsoService``.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.errors import SsoRateLimited


@dataclass
class _Window:
    timestamps: deque[float] = field(default_factory=deque)


@dataclass
class InMemoryRateLimiter:
    """Sliding-window counter keyed by ``(tenant_id, provider_type)``."""

    settings: SsoSettings
    _windows: dict[tuple[str, str], _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def default(cls) -> InMemoryRateLimiter:
        return cls(settings=get_settings().sso)

    def _prune(self, w: _Window, now: float) -> None:
        window_seconds = 60.0
        cutoff = now - window_seconds
        while w.timestamps and w.timestamps[0] < cutoff:
            w.timestamps.popleft()

    def check_and_record(self, *, tenant_id: str, provider_type: str) -> None:
        """Allow + count one event. Raise ``SsoRateLimited`` on overflow."""
        now = time.monotonic()
        key = (tenant_id, provider_type)
        with self._lock:
            w = self._windows.setdefault(key, _Window())
            self._prune(w, now)
            if len(w.timestamps) >= self.settings.auto_provision_rate_limit_per_minute:
                raise SsoRateLimited(
                    f"auto-provision rate limit ({self.settings.auto_provision_rate_limit_per_minute}/min) "
                    f"exceeded for {tenant_id}/{provider_type}"
                )
            w.timestamps.append(now)

    def reset(self) -> None:
        """Testing hook — clear all windows."""
        with self._lock:
            self._windows.clear()
