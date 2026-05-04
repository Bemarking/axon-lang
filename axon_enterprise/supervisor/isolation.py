"""
Multi-tenant isolation: per-tenant restart budgets (Fase 16.m).

A misbehaving tenant's daemons must not starve sibling tenants' restart
budgets. This module enforces:

  * `max_restarts_per_minute`     — sliding-window restart count cap
  * `max_concurrent_restarts`     — semaphore on restart cascades
  * `max_state_snapshot_bytes`    — cap on persisted snapshot size

When a budget is exhausted, restart attempts are rejected with a
telemetry event + audit-chain entry. The daemon stays down until the
window resets or an operator extends the budget.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class TenantBudget:
    """Per-tenant resource budget for the supervisor."""

    tenant_id: str
    max_restarts_per_minute: int = 30
    max_concurrent_restarts: int = 4
    max_state_snapshot_bytes: int = 1_048_576  # 1 MiB


@dataclass
class _BudgetState:
    budget: TenantBudget
    restarts: Deque[float] = field(default_factory=deque)
    semaphore: asyncio.Semaphore | None = None

    def __post_init__(self) -> None:
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.budget.max_concurrent_restarts)


class TenantBudgetRegistry:
    """Per-supervisor tenant budget tracker.

    The supervisor's hooks consult this registry on every restart
    attempt; rejected attempts emit `tenant_budget_exhausted` events
    instead of consuming the daemon's intensity gate.
    """

    def __init__(
        self,
        *,
        default_budget: TenantBudget | None = None,
    ) -> None:
        self._states: dict[str, _BudgetState] = {}
        self._default = default_budget or TenantBudget(tenant_id="_global")

    def configure(self, budget: TenantBudget) -> None:
        self._states[budget.tenant_id] = _BudgetState(budget=budget)

    def _state(self, tenant_id: str) -> _BudgetState:
        state = self._states.get(tenant_id)
        if state is None:
            # Lazy default — every tenant gets the global budget unless
            # explicitly configured.
            state = _BudgetState(
                budget=TenantBudget(
                    tenant_id=tenant_id,
                    max_restarts_per_minute=self._default.max_restarts_per_minute,
                    max_concurrent_restarts=self._default.max_concurrent_restarts,
                    max_state_snapshot_bytes=self._default.max_state_snapshot_bytes,
                ),
            )
            self._states[tenant_id] = state
        return state

    def record_restart(self, tenant_id: str) -> None:
        """Mark a restart in the rolling minute window."""
        state = self._state(tenant_id)
        now = time.monotonic()
        state.restarts.append(now)
        cutoff = now - 60.0
        while state.restarts and state.restarts[0] < cutoff:
            state.restarts.popleft()

    def restart_allowed(self, tenant_id: str) -> bool:
        """Check whether the tenant has budget remaining for another
        restart in the current minute window."""
        state = self._state(tenant_id)
        now = time.monotonic()
        cutoff = now - 60.0
        recent = sum(1 for ts in state.restarts if ts >= cutoff)
        return recent < state.budget.max_restarts_per_minute

    def snapshot_size_allowed(
        self, tenant_id: str, size_bytes: int,
    ) -> bool:
        state = self._state(tenant_id)
        return 0 <= size_bytes <= state.budget.max_state_snapshot_bytes

    def cascade_lock(self, tenant_id: str) -> asyncio.Semaphore:
        """Per-tenant semaphore bounding concurrent restart cascades."""
        return self._state(tenant_id).semaphore  # type: ignore[return-value]
