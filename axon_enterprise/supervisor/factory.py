"""
Factory: construct a fully-wired `DaemonSupervisor` with the
enterprise hooks plugged in (Fase 16.p).

Production deployments call `make_enterprise_supervisor(...)` once
at AxonServer bootstrap; the returned supervisor has all 12 audit
gaps closed.

Defaults are conservative for tests + local dev (in-memory state
store, in-memory audit sink, single-instance leader election). Each
parameter can be overridden with a production adapter:

    make_enterprise_supervisor(
        config=SupervisorConfig(...),
        state_store=postgres_replay_state_store,
        audit_sink=postgres_audit_sink,
        tenant_resolver=request_tenant_resolver,
        compliance=enterprise_compliance_gate,
        leader=redis_redlock_leader,
    )
"""

from __future__ import annotations

from typing import Awaitable, Callable

from axon.runtime.supervisor import DaemonSupervisor, SupervisorConfig

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
from axon_enterprise.supervisor.hooks import EnterpriseSupervisorHooks
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


def make_enterprise_supervisor(
    *,
    config: SupervisorConfig | None = None,
    state_store=None,
    audit_sink=None,
    tenant_resolver: Callable[[str], str] | None = None,
    compliance: ComplianceGate | None = None,
    leader: LeaderElection | None = None,
    sign_key_fn: Callable[[str], bytes] | None = None,
    backoff: DecorrelatedJitterBackoff | None = None,
    health: HealthProbeRegistry | None = None,
    isolation: TenantBudgetRegistry | None = None,
    alert_fn: Callable[[str, str], Awaitable[None]] | None = None,
    forge_fn: Callable[[str, BaseException], Awaitable[None]] | None = None,
) -> DaemonSupervisor:
    """Construct a `DaemonSupervisor` with `EnterpriseSupervisorHooks`
    pre-wired. Returns the raw OSS supervisor type — callers use it
    exactly like the basic supervisor (`register`, `start_all`,
    `stop_all`).

    Every parameter has a sensible in-memory default so tests can
    construct one in one line. Production wiring lives in the
    enterprise AxonServer bootstrap and replaces the in-memory
    defaults with the Postgres / Redis / Vault adapters.
    """
    config = config or SupervisorConfig()
    state_store = state_store or InMemoryStateStore()
    audit_sink = audit_sink or InMemoryAuditSink()
    tenant_resolver = tenant_resolver or (lambda _: "_global")
    compliance = compliance or default_compliance_gate()
    leader = leader or InMemoryLeaderElection()
    backoff = backoff or DecorrelatedJitterBackoff()
    health = health or HealthProbeRegistry()
    isolation = isolation or TenantBudgetRegistry()

    telemetry = SupervisorTelemetry(tenant_resolver=tenant_resolver)
    audit = SupervisorAuditChain(
        sink=audit_sink,
        tenant_resolver=tenant_resolver,
        sign_key_fn=sign_key_fn,
    )
    persistence = StatePersistence(store=state_store)
    policy_ctx = PolicyContext(
        snapshot_fn=persistence.snapshot,
        alert_fn=alert_fn,
        audit_fn=lambda kind, payload: audit.append(
            kind, payload.get("daemon", "_unknown"), payload,
        ),
        forge_fn=forge_fn,
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
    hooks._tenant_resolver = tenant_resolver  # type: ignore[assignment]

    return DaemonSupervisor(config=config, hooks=hooks)
