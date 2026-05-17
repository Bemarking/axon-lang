---
title: "Plan vivo: Fase 16 — Daemon Supervisor hardening (10/10 production)"
status: PLANNED — sub-fases 16.a–16.r por shippear
owner: AXON Language Team (hooks) + Bemarking AI Enterprise (hardening)
created: 2026-05-04
updated: 2026-05-04
target: axon-lang vNEXT (hook protocols only) + axon-enterprise vNEXT (full hardening)
depends_on: Fase 15 (lambda apply runtime) DONE
---

# FASE 16 — DAEMON SUPERVISOR HARDENING

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## ⚠️ SCOPE BOUNDARY — READ FIRST

**This phase has TWO target repos and TWO distinct scopes. The advanced supervisor is exclusively an axon-enterprise feature. It MUST NOT bleed into the open-source axon-lang.**

| Repo | What ships | Why |
|---|---|---|
| **`axon-lang`** (OSS, public, MIT) | Minimal hook protocols + injection points + a single docstring honesty fix. **Zero behavior change for OSS adopters.** All existing tests stay green; the basic OTP-style supervisor (one_for_one / one_for_all / rest_for_one + bounded restart intensity) keeps its current semantics when no hooks are registered. Default = no hooks = today's behavior. | The OSS layer should expose **extension points**, not bake commercial features. Adopters running the open compiler/runtime get the simple, audit-able supervisor with no enterprise dependencies (no audit trail, no Postgres, no Vault, no telemetry stack). |
| **`axon-enterprise`** (proprietary, Bemarking AI commercial) | **Everything that turns the supervisor 10/10 production-grade**: StateBackend integration via Replay tokens + Cognitive States, OTel + Prometheus + structlog telemetry, on_stuck policy dispatcher (hibernate/escalate/retry/forge), exponential backoff with jitter, liveness probes, hierarchical supervision tree, mutex-protected mutations, failure propagation upward, restart log eviction, audit trail integration (every restart event canonical-hashed + Merkle-chained), multi-tenant isolation (per-tenant restart budgets), compliance-aware restart hooks (legal basis re-validation post-restart), distributed supervision (cross-instance leader election). | Production-grade supervision is what enterprise customers pay for. It depends on enterprise-only modules (`audit/`, `observability/`, `replay/`, `cognitive_states/`, `tenant/`, `compliance/`) and infrastructure (Postgres, Redis, Vault, Stripe). |

**The OSS supervisor does not get downgraded.** It stays at its current 4/10 — *honest* 4/10, with documented limitations and explicit hook points where enterprise plugs in. The 10/10 score belongs to the **enterprise stack** running on top of axon-lang.

Every sub-phase below is tagged `[OSS]` (lands in axon-lang), `[ENT]` (lands in axon-enterprise), or `[BOTH]` (coordinated landing).

---

## 1. TL;DR (resume in 30 seconds)

- **What:** the open-source supervisor in `axon/runtime/supervisor.py` is honest 4/10 — works for "single daemon crashes, restart it, give up after N tries" but doesn't deliver on the OTP-style promises in its own docstring (no StateBackend integration, no telemetry, no `on_stuck` dispatch, races in `one_for_all`/`rest_for_one`, no failure propagation, restart log leaks memory, no liveness probe, no Rust counterpart). **Fase 16 closes the gap to 10/10 production — but only inside axon-enterprise.**
- **Why:** the docstring lies must be either resolved or qualified, and enterprise customers expect a supervisor that survives node failures, integrates with the audit trail, exposes telemetry, and reasons about the `on_stuck` policy adopters declare in their `.axon` source.
- **How:** axon-lang gets ~50 LOC of new hook protocols (`SupervisorHooks` Protocol, optional `hooks=` constructor arg, optional `on_stuck_policy` field on `DaemonSpec`, no-op default behavior). axon-enterprise gets a new top-level package `axon_enterprise/supervisor/` (~2000 LOC across 8-10 modules) implementing all the hardening, plus a comprehensive test suite (target: 80+ tests covering concurrent crashes, all 3 strategies, state restore, audit chain, telemetry assertions, multi-tenant isolation, distributed leader failover).
- **Impact on adopters:** OSS users see no breaking change. Enterprise users get a drop-in `EnterpriseDaemonSupervisor` that the AxonServer can be configured to use instead of the basic one — same `register / start_all / stop_all` API, vastly more capable internals.

---

## 2. Audit findings (the 4/10 baseline)

The 12 gaps that motivated this phase, evidenced from `axon/runtime/supervisor.py` (220 LOC) and `tests/test_daemon.py` (5 supervisor tests):

| # | Gap | Evidence |
|---|---|---|
| 1 | StateBackend integration **not implemented** despite docstring claim | `supervisor.py:78` says *"preserves the daemon's global memory (stored in StateBackend)"* — `_supervised_run` makes ZERO state-persistence calls. Crash → in-memory state lost. |
| 2 | `on_stuck` policies (hibernate/escalate/retry/forge) **not dispatched** | `executor.py:3679-3683` documents the AST-level policies; supervisor responds with blunt restart to every exception regardless of policy. |
| 3 | `_restart_log` **grows unbounded** | `list[tuple[str, float]]` only `.append()`s; `_exceeds_restart_intensity` filters by window but never trims. Long-running supervisor → memory leak. |
| 4 | **Zero telemetry** | `except Exception:` swallows the exception with no structured log, no metric, no OTel span. `break` on intensity-exceeded is silent. |
| 5 | **No failure propagation upward** | Docstring lines 18-23 promise propagation; actual code is just `break` out of `while`. `_running` stays True; no callback fired; no parent supervisor exists. |
| 6 | **Single-level only** — no supervision tree | Flat list of daemons under one supervisor. No `Supervisor of Supervisors` nesting. |
| 7 | `one_for_all` / `rest_for_one` **race conditions** | `_restart_all_except` and `_restart_after` mutate `self._tasks[name]` from inside the crashed daemon's task. Concurrent crashes can clobber the dict. No lock. |
| 8 | **No pre-restart hook / state snapshot** | Failing exception silently dropped; observers can't correlate "daemon X crashed because Y". |
| 9 | **No Rust counterpart** | `axon-rs` mentions `daemon_supervisor` only as string in `event_bus.rs` and `axon_server.rs`. No supervisor module exists in the Rust runtime. |
| 10 | **Backoff is linear, capped at 1s** | `0.1 * min(restart_count, 10)`. Transient infra failures (DB blip, 30s) cause restart hammering. |
| 11 | **No liveness probe** | Supervisor only reacts to exceptions. Stuck-but-not-crashed daemons (deadlocks, infinite loops) count as `active`. |
| 12 | **`restart_count` per spec never resets** | After successful run, `spec.restart_count` keeps incrementing. The intensity check uses `_restart_log` (correct), but the per-spec field is permanently inflated. |

Plus: thin test coverage (5 tests cover register / start-stop / restart-on-crash / intensity-limit / defaults; no tests for `one_for_all`, `rest_for_one`, concurrent crashes, state preservation, or failure propagation).

---

## 3. Architecture — extension by hook injection (axon-lang) + full implementation (axon-enterprise)

### 3.1 Open/Closed boundary

axon-lang's `DaemonSupervisor` becomes **closed for modification, open for extension** via two new optional surfaces:

```python
# axon/runtime/supervisor.py — proposed additions (16.a)

from typing import Protocol, runtime_checkable, Any

@runtime_checkable
class SupervisorHooks(Protocol):
    """Optional injection point for enterprise / observability layers.

    Default: no hooks registered → today's behavior preserved exactly.
    """
    async def on_daemon_start(self, name: str, attempt: int) -> None: ...
    async def on_daemon_crash(self, name: str, exc: BaseException, attempt: int) -> None: ...
    async def on_daemon_restart(self, name: str, attempt: int, delay_s: float) -> None: ...
    async def on_intensity_exceeded(self, name: str, restart_count: int) -> None: ...
    async def snapshot_state(self, name: str) -> Any | None: ...      # called pre-restart
    async def restore_state(self, name: str, snapshot: Any) -> None:  # called post-restart
        ...
    async def liveness_check(self, name: str) -> bool: ...            # optional health probe
    async def resolve_on_stuck(self, name: str, exc: BaseException) -> str:
        """Return one of: 'restart' (default) | 'hibernate' | 'escalate' | 'forge' | 'noop'."""
        ...
```

```python
@dataclass
class DaemonSpec:
    name: str
    start_fn: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    restart_count: int = 0
    last_restart: float = 0.0
    on_stuck_policy: str = "restart"   # NEW (16.a) — default preserves today's behavior
```

```python
class DaemonSupervisor:
    def __init__(
        self,
        config: SupervisorConfig | None = None,
        *,
        hooks: SupervisorHooks | None = None,   # NEW (16.a) — default None = no-op
    ) -> None:
        ...
        self._hooks = hooks
```

The `_supervised_run` body is amended to call hook methods if `self._hooks is not None`. **All hook calls are guarded with `if self._hooks: ...` so the no-hooks path stays byte-for-byte equivalent to today's code path.** Default behavior is preserved; the Fase 15 acceptance gate template applies (zero regression in existing tests).

### 3.2 Enterprise implementation — the 10/10 layer

The `axon_enterprise/supervisor/` package implements `SupervisorHooks` end-to-end and wires every gap from §2:

```
axon_enterprise/supervisor/
├── __init__.py              — public API: EnterpriseDaemonSupervisor + factory
├── hooks.py                 — EnterpriseSupervisorHooks (the hook impl)
├── persistence.py           — snapshot/restore via Replay tokens + Cognitive States
├── telemetry.py             — OTel spans + Prometheus counters + structlog
├── policies.py              — on_stuck dispatcher (hibernate / escalate / retry / forge)
├── backoff.py               — exponential backoff + decorrelated jitter
├── health.py                — liveness probes (heartbeat, watchdog, custom checks)
├── hierarchy.py             — supervision tree (Sup → Sup → Daemon)
├── audit.py                 — audit-trail integration (every event signed + Merkle-chained)
├── isolation.py             — multi-tenant: per-tenant restart budgets, blast-radius caps
├── compliance.py            — compliance-aware restart hooks (legal-basis re-validation)
├── distributed.py           — cross-instance leader election (Redis Redlock / etcd Raft)
└── lock.py                  — asyncio.Lock helpers for race-free dict mutations
```

The `EnterpriseDaemonSupervisor` is constructed by composing `axon-lang`'s `DaemonSupervisor` with an `EnterpriseSupervisorHooks` instance:

```python
# axon_enterprise/supervisor/__init__.py — sketch

from axon.runtime.supervisor import DaemonSupervisor, SupervisorConfig
from .hooks import EnterpriseSupervisorHooks

def make_enterprise_supervisor(
    *,
    config: SupervisorConfig,
    state_backend,        # axon_enterprise.cognitive_states adapter
    audit_sink,           # axon_enterprise.audit adapter
    telemetry_provider,   # OTel meter + Prometheus registry
    tenant_resolver,      # axon_enterprise.tenant context
    compliance_checker,   # axon_enterprise.compliance lookup
) -> DaemonSupervisor:
    hooks = EnterpriseSupervisorHooks(
        state_backend=state_backend,
        audit_sink=audit_sink,
        telemetry_provider=telemetry_provider,
        tenant_resolver=tenant_resolver,
        compliance_checker=compliance_checker,
    )
    return DaemonSupervisor(config=config, hooks=hooks)
```

This composition pattern means the OSS supervisor stays the load-bearing core; enterprise just plugs in the hardened behavior via the hook contract.

### 3.3 Why hooks instead of subclassing

Subclassing `DaemonSupervisor` would require enterprise to override several private methods (`_supervised_run`, `_exceeds_restart_intensity`, `_restart_all_except`). That couples the proprietary layer to OSS internals — every refactor in axon-lang risks breaking enterprise. Hooks are the **stable contract**: as long as the lifecycle methods (`on_daemon_start`, `on_daemon_crash`, `on_daemon_restart`, `on_intensity_exceeded`, `snapshot_state`, `restore_state`, `liveness_check`, `resolve_on_stuck`) keep their signatures, axon-lang is free to refactor the internals.

### 3.4 Why no Rust supervisor in this phase

`axon-rs` doesn't have a daemon supervisor today, and adding one is a separate undertaking (Tokio-based, integrating with the same hook contract via FFI or a Rust-side trait). For Fase 16 we explicitly defer the Rust counterpart — the production runtime that matters today is Python, and the Rust binary's role in the enterprise container image is the lang frontend + CLI + executor stub, not daemon supervision. Future Fase 17+ may add `axon-enterprise-rs` (proprietary Rust) with a parallel hardened supervisor; the current scope keeps it Python-only.

---

## 4. Use cases unlocked (post-Fase 16)

| Capability | What enterprise customers can do |
|---|---|
| **State-preserving restart** | A daemon that holds 10 minutes of accumulated context (BDI matrix, replay log offset, AxonStore session) survives a crash without starting from scratch. Implemented via Cognitive States serializer + Replay token continuation. |
| **Audit-grade restart trail** | Every crash + restart + intensity-exceeded event lands in the immutable audit log, signed (HMAC-SHA256 + Ed25519 chained) and Merkle-anchored so SOC2/GDPR auditors can reconstruct the full lifecycle of any daemon. |
| **Tenant-fair restart budgets** | Tenant A's misbehaving daemon can't blow Tenant B's restart budget. Per-tenant intensity counters with isolation. |
| **`on_stuck: hibernate` honored** | When an adopter declares `on_stuck: hibernate` on a `daemon Foo { ... }`, the supervisor actually serializes the BDI matrix to PEM and pauses the daemon instead of restart-thrashing. Same for `escalate` (notify operators), `retry` (with declared backoff), `forge` (creative-synthesis recovery via the Poincaré pipeline). |
| **OTel + Prometheus visibility** | `axon_supervisor_restarts_total{daemon=...,tenant=...,reason=...}`, `axon_supervisor_intensity_window_seconds`, `axon_supervisor_state_snapshot_bytes`, `axon_supervisor_active_daemons`, etc. OTel traces span the full crash → snapshot → restart → restore lifecycle. |
| **Hierarchical supervision** | A platform supervisor manages tenant supervisors which manage daemon supervisors. Tenant-level intensity exceeded → escalates to platform supervisor without taking down sibling tenants. |
| **Liveness probe for stuck daemons** | Configurable health check (heartbeat, watchdog timer, custom predicate). Stuck-but-not-crashed daemons get terminated and restarted instead of running forever as "active". |
| **Distributed leader election** | In a multi-instance AxonServer deployment, exactly one supervisor instance is the leader for any given daemon; failover via Redis Redlock or etcd lease. Restart budgets and audit trails are globally coherent. |
| **Compliance-aware restart** | If a tenant's legal basis (`@legal_basis: GDPR.Art6.Consent`) expires between crash and restart, the supervisor refuses to restart the daemon and emits a compliance violation event instead. |

---

## 5. Sub-phases

> Tag legend: `[OSS]` lands in axon-lang • `[ENT]` lands in axon-enterprise • `[BOTH]` coordinated landing.

### 16.a — Hook protocol surface in axon-lang  `[OSS]` `[PLANNED]`

Add to `axon/runtime/supervisor.py`:
- `SupervisorHooks` `Protocol` (8 methods, all `async`, all returning Optional/None).
- `hooks: SupervisorHooks | None = None` parameter on `DaemonSupervisor.__init__`.
- `on_stuck_policy: str = "restart"` field on `DaemonSpec` (default preserves today's behavior).
- Hook calls inside `_supervised_run`, `_restart_all_except`, `_restart_after`, all guarded with `if self._hooks:`.
- A single `asyncio.Lock` field on `DaemonSupervisor` (used in 16.j to fix the race conditions); registered in the constructor, default unused on the no-hooks path so OSS behavior is unchanged.

**Fix the docstring lie** in the same commit: replace *"preserves the daemon's global memory (stored in StateBackend)"* with *"if a SupervisorHooks instance is registered, its `snapshot_state` / `restore_state` are invoked across the crash boundary; the OSS supervisor itself does not persist state — see axon-enterprise for the production-grade hooks impl."*

**Test discipline:** every existing test in `tests/test_daemon.py` MUST still pass with no modification. Add 4 new OSS-side tests:
1. `test_hooks_default_no_op` — `DaemonSupervisor()` with no hooks behaves identically to today.
2. `test_hooks_lifecycle_callbacks_fire` — register a recording hook, verify start/crash/restart/intensity-exceeded fire in order.
3. `test_hooks_snapshot_restore_round_trip` — register a hook that snapshots + restores; verify daemon receives the snapshot post-restart.
4. `test_on_stuck_policy_string_passthrough` — `DaemonSpec.on_stuck_policy` field is plumbed and accessible via hook callbacks.

Sub-target: **axon-lang vNEXT (no SemVer change required if no behavior change)**. The release commit that bumps the floor for enterprise will also include the docstring fix.

### 16.b — Restart-log eviction + memory bound  `[OSS]` `[PLANNED]`

Replace `_restart_log: list[tuple[str, float]]` with a deque + per-daemon ringbuffer indexed by `name`. After every append, evict entries older than `max_seconds` so memory is bounded by `O(daemons × max_restarts)`.

Test: `test_restart_log_eviction` — push 1000 synthetic restart events spaced beyond the window, assert the log size stays bounded.

Sub-target: same release as 16.a.

### 16.c — Race-condition fix: serialize dict mutations  `[OSS]` `[PLANNED]`

Wrap `self._tasks[name] = ...` mutations in `_restart_all_except`, `_restart_after`, and `start_all` with `async with self._lock:` (the `asyncio.Lock` introduced in 16.a). This is the smallest change that fixes the concurrent-crash race without touching the strategy semantics.

Test: `test_concurrent_crashes_no_dict_corruption` — register 10 daemons that all crash simultaneously under `ONE_FOR_ALL`; assert all 10 are restarted exactly once and the task dict has exactly 10 entries.

Sub-target: same release as 16.a.

### 16.d — `axon_enterprise/supervisor/` skeleton  `[ENT]` `[PLANNED]`

Create the package with the 10 modules listed in §3.2. Every module starts as a stub with public API + docstring + raised `NotImplementedError` in method bodies. The `EnterpriseSupervisorHooks` class implements `SupervisorHooks` with all methods routed to `NotImplementedError` so import works but invocation surfaces missing implementations clearly. Follow-up sub-phases fill in the bodies.

Tests: `test_module_layout` + `test_protocol_conformance` (verify `EnterpriseSupervisorHooks` satisfies `runtime_checkable` `SupervisorHooks`). Sub-target: enterprise scaffolding-only release; no production wiring yet.

### 16.e — Telemetry: OTel + Prometheus + structlog  `[ENT]` `[PLANNED]`

`telemetry.py` implements:
- OTel spans wrapping each daemon lifecycle (`axon.supervisor.daemon` span with `daemon.name`, `daemon.tenant`, `daemon.attempt`, `daemon.outcome` attributes).
- Prometheus counters/gauges/histograms:
  - `axon_supervisor_restarts_total{daemon,tenant,reason}` (Counter)
  - `axon_supervisor_active_daemons{tenant}` (Gauge)
  - `axon_supervisor_restart_delay_seconds{daemon,tenant}` (Histogram)
  - `axon_supervisor_state_snapshot_bytes{daemon}` (Histogram)
  - `axon_supervisor_intensity_exceeded_total{daemon,tenant}` (Counter)
- `structlog`-based structured logger with consistent fields (`daemon`, `tenant`, `attempt`, `exception_type`, `exception_message`, `correlation_id`).

Hook methods `on_daemon_start`, `on_daemon_crash`, `on_daemon_restart`, `on_intensity_exceeded` all emit telemetry.

Tests: assert metric values + log records + span attributes after orchestrating a synthetic crash sequence.

### 16.f — State persistence: snapshot + restore  `[ENT]` `[PLANNED]`

`persistence.py` implements `snapshot_state` and `restore_state` hooks via:
- **Replay tokens**: every daemon snapshot becomes a canonical-hashed Replay token persisted to the `axon_enterprise/replay/` Postgres adapter.
- **Cognitive States**: BDI matrix + per-daemon PEM state serialized via the Q32.32 fixed-point density-matrix encoder (already implemented in `axon_enterprise/cognitive_states/`).

Snapshot is best-effort pre-crash (called from `on_daemon_crash` which receives the exception — at this point we only have the spec metadata, not the live daemon state). The fuller pre-crash snapshot path requires a daemon-side cooperative API that lets long-running daemons periodically checkpoint their state; this is added in 16.f.2.

**16.f.1**: post-crash snapshot from spec + restore on next `on_daemon_start`.
**16.f.2**: cooperative checkpoint API (`daemon_checkpoint(state)` callable injected into the daemon's runtime context); allows the daemon to publish snapshots at sensible points during normal execution.

Tests: 8 scenarios — fresh start, restart with state, restart without state, snapshot too large, snapshot serialization failure, replay token round-trip, cognitive-state round-trip, restore failure handling.

### 16.g — `on_stuck` policy dispatcher  `[ENT]` `[PLANNED]`

`policies.py` implements `resolve_on_stuck`. The hook reads `DaemonSpec.on_stuck_policy` and dispatches:

| Policy | Behavior |
|---|---|
| `restart` (default) | Today's behavior — restart with intensity gate. |
| `hibernate` | Serialize BDI matrix via cognitive-states, mark spec as hibernated, do NOT restart. Operator wakes it via control plane. |
| `escalate` | Emit alert via observability adapter (PagerDuty / Slack / email per tenant config), do NOT restart. |
| `retry` | Restart with exponential backoff (16.h); ignore the standard intensity cap up to a separate `retry_max` ceiling. |
| `forge` | Trigger creative-synthesis recovery: invoke the Poincaré forge pipeline with the crash exception + last known good state as the prompt, hoping the LLM produces a corrective action. (Advanced, optional — gated behind `enterprise.experimental.forge_recovery: true`.) |
| `noop` | Mark the daemon as terminally stopped; no further action. |

Tests: 6 (one per policy + one for unknown-policy fallback to `restart`).

### 16.h — Exponential backoff with decorrelated jitter  `[ENT]` `[PLANNED]`

`backoff.py` implements the AWS-recommended **decorrelated jitter** algorithm (Marc Brooker, 2015):

```python
delay = min(cap, random.uniform(base, prev_delay * 3))
```

with `base=0.1s`, `cap=300s`. Replaces the OSS `0.1 * min(restart_count, 10)` linear backoff for enterprise-supervised daemons. Hook is invoked from `on_daemon_restart` and the supervisor uses the returned delay instead of the OSS default.

Tests: distribution properties (mean, max, no thundering herd under 100 simultaneous restarts).

### 16.i — Liveness probes  `[ENT]` `[PLANNED]`

`health.py` implements three probe styles, configurable per-daemon:

1. **Heartbeat**: daemon must call `heartbeat()` injected callable at least every `heartbeat_interval_seconds`; probe asserts `now - last_heartbeat < interval × tolerance`.
2. **Watchdog timer**: declarative max-step-duration; supervisor cancels the daemon task if any single execution exceeds the watchdog.
3. **Custom predicate**: user-provided `async fn () -> bool` invoked every `probe_interval_seconds`.

`liveness_check` hook returns False → supervisor cancels the task and triggers `on_stuck` policy dispatch (16.g).

Tests: 5 scenarios per probe style (alive, slow, hung, custom-true, custom-false).

### 16.j — Hierarchical supervision tree  `[ENT]` `[PLANNED]`

`hierarchy.py` introduces `SupervisorTree` — a node that holds either child supervisors or daemons. Failures escalate up the tree:
- Daemon crash too many times → escalate to parent supervisor.
- Parent supervisor decides whether to restart the failing child supervisor (taking ALL its daemons down with it under `ONE_FOR_ALL`) or continue running siblings.

Default deployment topology in enterprise:
```
PlatformSupervisor (ONE_FOR_ONE — tenant supervisors are independent)
├── TenantSupervisor("acme")     (REST_FOR_ONE — daemons share state lineage)
│   ├── OrderDaemon
│   ├── BillingDaemon
│   └── AnalyticsDaemon
├── TenantSupervisor("globex")   (ONE_FOR_ALL — daemons share a session)
│   ├── ChatDaemon
│   └── HandoffDaemon
└── ...
```

Tests: 8 scenarios — flat tree, two-level escalation, sibling isolation, parent-restart cascading.

### 16.k — Failure propagation upward  `[ENT]` `[PLANNED]`

`on_intensity_exceeded` hook is wired to:
1. Emit a telemetry event (16.e).
2. Append an audit-chain entry (16.l).
3. Notify the parent supervisor (16.j).
4. Optionally: trigger PagerDuty/Slack alert based on per-tenant config.

The OSS supervisor's `break` stays — the hook does the upward propagation.

Tests: assertion that all four side effects fire in order on intensity exceeded.

### 16.l — Audit trail integration  `[ENT]` `[PLANNED]`

`audit.py` integrates with `axon_enterprise/audit/` so every supervisor event becomes an immutable, canonical-hashed entry:
- Event types: `daemon_started`, `daemon_crashed`, `daemon_restarted`, `daemon_intensity_exceeded`, `daemon_state_snapshot`, `daemon_state_restored`, `daemon_hibernated`, `daemon_escalated`, `liveness_probe_failed`, `tenant_budget_exhausted`.
- Each entry signed (HMAC-SHA256 with the tenant key + Ed25519 supervisor key).
- Merkle-chained per tenant so audit log can be verified end-to-end.

Tests: 6 scenarios — event signed correctly, Merkle chain verifies, tampered entry detected, replay attack prevented, multi-tenant isolation, event time-ordering.

### 16.m — Multi-tenant isolation  `[ENT]` `[PLANNED]`

`isolation.py` introduces per-tenant restart budgets:
- Each tenant gets `tenant.max_restarts_per_minute`, `tenant.max_concurrent_restarts`, `tenant.max_state_snapshot_bytes` (read from `axon_enterprise/config/`).
- A misbehaving tenant's daemons cannot starve sibling tenants — restart attempts that would exceed the tenant budget are rejected with a telemetry event + audit entry.
- The `tenant_resolver` hook resolves the active tenant for any given daemon name (defaults to `_global` for non-tenant daemons).

Tests: 5 scenarios — single tenant, two tenants with one misbehaving, budget exhaustion, budget reset on window expiry, global daemons unaffected.

### 16.n — Compliance-aware restart hooks  `[ENT]` `[PLANNED]`

`compliance.py` integrates with `axon_enterprise/compliance/`:
- Before restarting any daemon, look up the active legal basis for the daemon's operations.
- If legal basis has expired or been revoked between crash and restart (e.g., GDPR consent withdrawal), refuse to restart and emit a compliance violation event instead.
- Honored by `EnterpriseSupervisorHooks.on_daemon_restart` returning a special sentinel that the supervisor interprets as "do not restart, log compliance violation".

Tests: 4 scenarios — valid basis, expired basis, revoked basis, basis upgraded mid-flight.

### 16.o — Distributed supervision (cross-instance)  `[ENT]` `[PLANNED]`

`distributed.py` implements leader election for supervisor instances in a multi-replica AxonServer deployment:
- Leader election via Redis Redlock or etcd lease (configurable).
- Exactly one instance is the leader for any given daemon at any time.
- Leadership lost (network partition, lease expired) → daemons stop locally; the new leader picks them up with the last persisted state (16.f).
- Restart budgets are globally coherent (Redis-backed counters with atomic increments).

This sub-phase is the most complex; ships behind a feature flag (`enterprise.distributed_supervision: true`) and defaults to single-instance mode.

Tests: 6 scenarios — single instance, leader election, leadership handover, network partition, split-brain prevention, lease expiry recovery.

### 16.p — Wire into `AxonServer` (enterprise install path)  `[ENT]` `[PLANNED]`

`axon_enterprise/server_bootstrap.py` (new) provides a drop-in replacement constructor for the AxonServer's supervisor:

```python
# OSS path (axon-lang AxonServer):
supervisor = DaemonSupervisor(config=...)

# Enterprise path:
from axon_enterprise.supervisor import make_enterprise_supervisor
supervisor = make_enterprise_supervisor(
    config=...,
    state_backend=enterprise.cognitive_states.adapter(),
    audit_sink=enterprise.audit.adapter(),
    telemetry_provider=enterprise.observability.adapter(),
    tenant_resolver=enterprise.tenant.resolver(),
    compliance_checker=enterprise.compliance.checker(),
)
```

The enterprise AxonServer subclass wires this in by default; OSS AxonServer keeps the basic supervisor.

Tests: integration test asserting the enterprise server boots with the hardened supervisor and survives a synthetic crash + restart with state preserved.

### 16.q — Test matrix consolidation  `[ENT]` `[PLANNED]`

Final test sweep: target 80+ tests across the enterprise supervisor package. Coverage gates:
- All 3 OSS strategies under enterprise wrapping (one_for_one, one_for_all, rest_for_one).
- All 6 `on_stuck` policies (restart, hibernate, escalate, retry, forge, noop).
- All 3 liveness probe styles (heartbeat, watchdog, custom).
- Hierarchical tree (3-level deep, 5 daemons per leaf).
- Distributed mode (3 instances, leader election + handover + partition recovery).
- Multi-tenant isolation (4 tenants, budget exhaustion under each).
- Compliance gating (4 legal-basis scenarios).
- Audit chain verification (1000 events, Merkle proof, tamper detection).
- Telemetry assertions (every metric/span/log fires expected values).
- Concurrent crash stress test (50 daemons crashing in parallel, no dict corruption, all restarted exactly once).

### 16.r — Documentation honesty + release notes  `[BOTH]` `[PLANNED]`

- axon-lang: update `axon/runtime/supervisor.py` module docstring to point to docs/fase/fase_16 + the OSS scope boundary.
- axon-lang: README Phase XX row (if applicable) qualified to "OSS basic + enterprise hardened".
- axon-enterprise: README adds new section "Production Daemon Supervision" with the §4 use-case table.
- axon-enterprise: 4 new docs under `docs/`:
  - `docs/supervisor_architecture.md` — the overall design
  - `docs/supervisor_operations.md` — ops runbook
  - `docs/supervisor_compliance_matrix.md` — SOC2/GDPR/HIPAA/PCI control mappings
  - `docs/supervisor_distributed_deployment.md` — multi-instance topology guide
- Release notes for both axon-lang vNEXT (hooks land) and axon-enterprise vNEXT (full hardening).

---

## 6. Out of scope

- **Rust supervisor counterpart**: deferred to Fase 17+. The Rust runtime in axon-lang is currently stub for daemons; production daemon execution lives in Python. Adding a Tokio-based hardened supervisor in `axon-rs` is a separate undertaking.
- **Replacing OSS supervisor with the enterprise one in axon-lang**: explicitly forbidden by §SCOPE BOUNDARY. The OSS layer keeps the basic supervisor.
- **Generalizing supervision to non-daemon primitives**: this phase is daemon-only. Supervised flows / supervised endpoints could be future work but are not in scope.
- **Removing the OSS supervisor's `_restart_log` data structure**: 16.b adds bounded eviction; the structure stays.

---

## 7. Acceptance criteria (for declaring Fase 16 SHIPPED)

1. Every sub-phase 16.a–16.r marked `[DONE]` ✓ with a release reference.
2. **OSS regression gate**: existing `axon-lang` test count strictly preserved + 4 new OSS-side tests (16.a) + 1 race fix test (16.c) + 1 eviction test (16.b). No existing test modified.
3. **Enterprise test count**: 80+ tests under `axon-enterprise/tests/test_supervisor*.py` covering the matrix in 16.q.
4. **Score self-assessment**: re-run the `axon/runtime/supervisor.py` audit against the 12-gap checklist in §2 — all 12 must be either CLOSED (in enterprise) or DOCUMENTED-NOT-APPLICABLE (in OSS with explicit rationale).
5. **Observability gate**: every supervisor lifecycle event must emit at least one OTel span + one Prometheus metric + one structured log entry with consistent correlation IDs.
6. **Audit gate**: every supervisor lifecycle event must land in the immutable audit chain with a verifiable Merkle proof.
7. **Compliance gate**: SOC2 control mapping document (16.r) reviewed and signed off.
8. **Distributed gate**: chaos test passes — kill the leader supervisor instance, verify failover within 5s with zero state loss for in-flight daemons.
9. **Released as**: `axon-lang vNEXT` (hooks-only minor bump) + `axon-enterprise vNEXT` (major bump justifying the new advanced supervisor). Coordinated release notes cross-link both.
10. **README restoration**: any qualifier added to README during the bring-up commit is restored to a clean ✅ entry once both releases ship.

---

## 8. Non-goals — explicit reminder

- **No silent enterprise feature in OSS.** If a feature lands in axon-lang, it must be documented as either neutral (a hook protocol that does nothing by itself) or as a basic primitive that adopters can use without enterprise. Anything that requires Postgres, Vault, OTel, structlog, Prometheus, Stripe, etc. lives in axon-enterprise. Period.
- **No coupling of OSS supervisor to enterprise modules.** `axon/runtime/supervisor.py` MUST NOT import from `axon_enterprise/*`. The reverse direction is fine.
- **No proprietary algorithms exposed in OSS docs.** This plan describes the public surface and the high-level architecture of the enterprise hardening; it does not reveal proprietary algorithms (e.g., the exact backoff jitter parameters tuned against Bemarking's production telemetry, the multi-tenant budget allocation algorithm, the leader-election fallback hierarchy). Those live in `axon-enterprise/docs/` (proprietary).
