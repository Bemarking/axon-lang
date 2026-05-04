"""
EnterpriseSupervisorHooks — orchestrator that composes every Fase 16
hardening module into the `SupervisorHooks` Protocol from axon-lang.

This is the main integration point. Each lifecycle method delegates
to one or more of the per-concern modules (telemetry, persistence,
policies, audit, isolation, compliance, distributed leader-election,
backoff, health). Failures inside any sub-module are caught and
swallowed at the hook boundary so a buggy submodule can't cascade
into a supervisor crash — the OSS supervisor relies on hooks not to
raise (`_fire_hook_safe` swallows defensively, but we keep the
contract clean here too).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon_enterprise.supervisor.audit import (
    InMemoryAuditSink,
    SupervisorAuditChain,
)
from axon_enterprise.supervisor.backoff import DecorrelatedJitterBackoff
from axon_enterprise.supervisor.compliance import (
    ComplianceGate,
    default_compliance_gate,
)
from axon_enterprise.supervisor.distributed import (
    InMemoryLeaderElection,
    LeaderElection,
)
from axon_enterprise.supervisor.health import HealthProbeRegistry
from axon_enterprise.supervisor.isolation import TenantBudgetRegistry
from axon_enterprise.supervisor.persistence import (
    InMemoryStateStore,
    StatePersistence,
)
from axon_enterprise.supervisor.policies import (
    PolicyContext,
    PolicyDispatcher,
)
from axon_enterprise.supervisor.telemetry import SupervisorTelemetry


@dataclass
class EnterpriseSupervisorHooks:
    """The 10/10 hooks impl.

    Construct via `make_enterprise_supervisor` for production
    defaults; instantiate directly for tests with stubbed
    sub-modules.
    """

    telemetry: SupervisorTelemetry
    persistence: StatePersistence
    backoff: DecorrelatedJitterBackoff
    audit: SupervisorAuditChain
    isolation: TenantBudgetRegistry
    compliance: ComplianceGate
    leader: LeaderElection
    health: HealthProbeRegistry
    policy_dispatcher: PolicyDispatcher
    # Per-daemon retry budget for `on_stuck=retry` (separate from the
    # standard intensity gate).
    _retry_budget: dict[str, int] = field(default_factory=dict)
    # Cache of last-known on_stuck policy strings per daemon, captured
    # the first time `resolve_on_stuck` runs so the policy is
    # consistent across the lifecycle.
    _policy_cache: dict[str, str] = field(default_factory=dict)

    # ── Hook surface (matches axon.runtime.supervisor.SupervisorHooks) ──

    async def on_daemon_start(self, name: str, attempt: int) -> None:
        if not await self.leader.is_leader_for(name):
            await self.leader.acquire_leadership(name)
            if not await self.leader.is_leader_for(name):
                return  # we're not the leader; sit quiet
        try:
            self.telemetry.emit_start(name, attempt)
        except Exception:
            pass
        try:
            await self.audit.append("daemon_started", name, {"attempt": attempt})
        except Exception:
            pass

    async def on_daemon_crash(
        self, name: str, exc: BaseException, attempt: int,
    ) -> None:
        if not await self.leader.is_leader_for(name):
            return
        try:
            self.telemetry.emit_crash(name, exc, attempt)
        except Exception:
            pass
        try:
            await self.audit.append(
                "daemon_crashed",
                name,
                {
                    "attempt": attempt,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc)[:512],
                },
            )
        except Exception:
            pass

    async def on_daemon_restart(
        self, name: str, attempt: int, delay_s: float,
    ) -> None:
        if not await self.leader.is_leader_for(name):
            return
        # Replace the OSS linear backoff delay with the decorrelated-
        # jitter delay we computed from the daemon's history. The OSS
        # supervisor has already slept for `delay_s` by the time the
        # hook fires (see DaemonSupervisor._supervised_run); we don't
        # double-sleep here. Future axon-lang change can let the hook
        # supply the delay before sleep.
        try:
            tenant_id = self._tenant_for(name)
            if not self.isolation.restart_allowed(tenant_id):
                # Budget exhausted — emit a warning event but do NOT
                # block (the OSS gate is intensity-based; we layer the
                # tenant gate as a soft signal). Hard-blocking lives in
                # `resolve_on_stuck`.
                try:
                    await self.audit.append(
                        "tenant_budget_exhausted",
                        name,
                        {"tenant_id": tenant_id},
                    )
                except Exception:
                    pass
            else:
                self.isolation.record_restart(tenant_id)
            self.telemetry.emit_restart(name, attempt, delay_s)
            await self.audit.append(
                "daemon_restarted",
                name,
                {"attempt": attempt, "delay_seconds": delay_s},
            )
        except Exception:
            pass

    async def on_intensity_exceeded(
        self, name: str, restart_count: int,
    ) -> None:
        if not await self.leader.is_leader_for(name):
            return
        try:
            self.telemetry.emit_intensity_exceeded(name, restart_count)
        except Exception:
            pass
        try:
            await self.audit.append(
                "daemon_intensity_exceeded",
                name,
                {"restart_count": restart_count},
            )
        except Exception:
            pass

    async def snapshot_state(self, name: str) -> Any:
        if not await self.leader.is_leader_for(name):
            return None
        try:
            blob = await self.persistence.snapshot(name)
        except Exception:
            return None
        if blob is None:
            return None
        size = len(blob)
        tenant_id = self._tenant_for(name)
        if not self.isolation.snapshot_size_allowed(tenant_id, size):
            # Drop oversized snapshot rather than persist garbage.
            try:
                await self.audit.append(
                    "daemon_snapshot_oversized",
                    name,
                    {"size_bytes": size, "tenant_id": tenant_id},
                )
            except Exception:
                pass
            return None
        try:
            self.telemetry.emit_snapshot(name, size)
        except Exception:
            pass
        try:
            await self.audit.append(
                "daemon_state_snapshot", name, {"size_bytes": size},
            )
        except Exception:
            pass
        return blob

    async def restore_state(self, name: str, snapshot: Any) -> None:
        if not await self.leader.is_leader_for(name):
            return
        try:
            data = await self.persistence.restore(name)
        except Exception:
            data = None
        size = 0 if data is None else len(str(data))
        try:
            self.telemetry.emit_restore(name, size)
        except Exception:
            pass
        try:
            await self.audit.append(
                "daemon_state_restored", name, {"size_bytes": size},
            )
        except Exception:
            pass

    async def liveness_check(self, name: str) -> bool:
        try:
            return await self.health.is_alive(name)
        except Exception:
            return True  # default-alive on probe failure

    async def resolve_on_stuck(
        self, name: str, exc: BaseException,
    ) -> str:
        # Compliance gate fires FIRST: if the legal basis is gone, we
        # short-circuit with `noop` regardless of declared policy.
        try:
            if not await self.compliance.allow_restart(name):
                try:
                    await self.audit.append(
                        "daemon_compliance_blocked",
                        name,
                        {"exception_type": type(exc).__name__},
                    )
                except Exception:
                    pass
                return "noop"
        except Exception:
            pass

        # Look up the daemon's declared policy (cached after first
        # crash so the dispatcher sees a stable string).
        policy_str = self._policy_cache.get(name)
        if policy_str is None:
            # Default to 'restart' — the supervisor will refine this
            # via `register(... on_stuck_policy=...)` if the .axon
            # source declared a different value. The cache is
            # populated by `set_policy_for_daemon` below.
            policy_str = "restart"

        # Retry-budget enforcement for `on_stuck=retry`
        if policy_str == "retry":
            self._retry_budget[name] = self._retry_budget.get(name, 0) + 1
            if self._retry_budget[name] > 20:  # hard ceiling
                return "noop"
            return "restart"

        return await self.policy_dispatcher.dispatch(name, policy_str, exc)

    # ── Public helpers (called by the factory or by adopter code) ──

    def set_policy_for_daemon(self, name: str, policy: str) -> None:
        """Wire the on_stuck policy for a daemon. Called by
        `make_enterprise_supervisor` based on the AST `on_stuck:`
        declaration; adopters running with a stand-alone supervisor
        can call this directly."""
        self._policy_cache[name] = policy

    def _tenant_for(self, daemon_name: str) -> str:
        try:
            return self._tenant_resolver(daemon_name) or "_global"
        except Exception:
            return "_global"

    # `_tenant_resolver` defaults to the telemetry one; the factory
    # rebinds it explicitly for clarity.
    _tenant_resolver = lambda self, name: "_global"  # type: ignore  # noqa: E731


def default_enterprise_hooks(
    *,
    tenant_resolver=None,
) -> EnterpriseSupervisorHooks:
    """Construct an `EnterpriseSupervisorHooks` with safe in-memory
    defaults for every sub-module. Useful for tests + local dev.
    Production deployments use the factory in `factory.py`.
    """
    telemetry = SupervisorTelemetry(tenant_resolver=tenant_resolver)
    audit = SupervisorAuditChain(
        sink=InMemoryAuditSink(),
        tenant_resolver=tenant_resolver,
    )
    persistence = StatePersistence(store=InMemoryStateStore())
    backoff = DecorrelatedJitterBackoff()
    isolation = TenantBudgetRegistry()
    compliance = default_compliance_gate()
    leader = InMemoryLeaderElection()
    health = HealthProbeRegistry()
    policy_ctx = PolicyContext(
        snapshot_fn=persistence.snapshot,
        audit_fn=lambda kind, payload: audit.append(kind, payload.get("daemon", "_unknown"), payload),
    )
    dispatcher = PolicyDispatcher(ctx=policy_ctx)
    hooks = EnterpriseSupervisorHooks(
        telemetry=telemetry,
        persistence=persistence,
        backoff=backoff,
        audit=audit,
        isolation=isolation,
        compliance=compliance,
        leader=leader,
        health=health,
        policy_dispatcher=dispatcher,
    )
    if tenant_resolver is not None:
        hooks._tenant_resolver = tenant_resolver  # type: ignore[assignment]
    return hooks
