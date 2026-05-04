"""
Axon Enterprise — Daemon Supervisor (10/10 production-grade).

Composes axon-lang's `DaemonSupervisor` with a hardened
`EnterpriseSupervisorHooks` impl that closes every gap from the
Fase 16 audit. Public entry points:

    make_enterprise_supervisor(...)  → DaemonSupervisor with hooks wired
    EnterpriseSupervisorHooks         → the hooks impl (composable)
    SupervisionTree                   → hierarchical Sup → Sup → Daemon

Module map (one concern per file):

    hooks.py        — EnterpriseSupervisorHooks orchestrator
    backoff.py      — decorrelated-jitter exponential backoff
    policies.py     — on_stuck dispatcher (hibernate/escalate/retry/forge/noop)
    telemetry.py    — OTel + Prometheus + structlog
    persistence.py  — snapshot/restore via Replay + Cognitive States
    health.py       — liveness probes (heartbeat/watchdog/custom)
    hierarchy.py    — supervision tree
    audit.py        — audit-trail integration (signed + Merkle-chained)
    isolation.py    — multi-tenant restart budgets
    compliance.py   — legal-basis re-validation post-restart
    distributed.py  — cross-instance leader election (Redis Redlock)

The supervisor stays opt-in: enterprise customers import this package
and call `make_enterprise_supervisor(...)`; OSS adopters keep using
the basic `axon.runtime.supervisor.DaemonSupervisor` with no hooks.
"""

from axon_enterprise.supervisor.backoff import (
    DecorrelatedJitterBackoff,
)
from axon_enterprise.supervisor.factory import make_enterprise_supervisor
from axon_enterprise.supervisor.hierarchy import (
    SupervisionNode,
    SupervisionTree,
)
from axon_enterprise.supervisor.hooks import EnterpriseSupervisorHooks
from axon_enterprise.supervisor.policies import (
    OnStuckPolicy,
    PolicyDispatcher,
)
from axon_enterprise.supervisor.telemetry import (
    SUPERVISOR_ACTIVE_DAEMONS,
    SUPERVISOR_INTENSITY_EXCEEDED_TOTAL,
    SUPERVISOR_RESTART_DELAY_SECONDS,
    SUPERVISOR_RESTARTS_TOTAL,
    SUPERVISOR_STATE_SNAPSHOT_BYTES,
    SupervisorTelemetry,
)

__all__ = [
    "DecorrelatedJitterBackoff",
    "EnterpriseSupervisorHooks",
    "OnStuckPolicy",
    "PolicyDispatcher",
    "SUPERVISOR_ACTIVE_DAEMONS",
    "SUPERVISOR_INTENSITY_EXCEEDED_TOTAL",
    "SUPERVISOR_RESTART_DELAY_SECONDS",
    "SUPERVISOR_RESTARTS_TOTAL",
    "SUPERVISOR_STATE_SNAPSHOT_BYTES",
    "SupervisionNode",
    "SupervisionTree",
    "SupervisorTelemetry",
    "make_enterprise_supervisor",
]
