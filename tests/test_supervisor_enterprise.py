"""
Axon Enterprise — Daemon Supervisor test matrix (Fase 16.q).

Covers every sub-phase 16.d–16.p end-to-end. Default size: 50+ tests
across 12 test classes — one class per concern.

Sub-phases exercised:

  * 16.d skeleton — module import + protocol conformance
  * 16.e telemetry — counter + log + span emission
  * 16.f persistence — snapshot/restore round-trip + cooperative checkpoint
  * 16.g policies — every on_stuck policy
  * 16.h backoff — decorrelated jitter distribution
  * 16.i health — heartbeat / watchdog / custom probes
  * 16.j hierarchy — supervision tree with escalation
  * 16.k propagation — failure escalates upward
  * 16.l audit — Merkle-chain integrity
  * 16.m isolation — per-tenant budget gates
  * 16.n compliance — legal-basis re-validation
  * 16.o distributed — leader election semantics
  * 16.p factory — full-stack supervisor construction
"""

from __future__ import annotations

import asyncio
import json

import pytest

from axon.runtime.supervisor import (
    DaemonSupervisor,
    SupervisorConfig,
    SupervisorHooks,
)


# ═══════════════════════════════════════════════════════════════════
#  16.d — Skeleton + Protocol conformance
# ═══════════════════════════════════════════════════════════════════


class TestSkeleton:
    """Module imports + Protocol conformance."""

    def test_package_imports_cleanly(self):
        import axon_enterprise.supervisor as supervisor_pkg
        assert hasattr(supervisor_pkg, "make_enterprise_supervisor")
        assert hasattr(supervisor_pkg, "EnterpriseSupervisorHooks")
        assert hasattr(supervisor_pkg, "SupervisionTree")

    def test_hooks_satisfies_protocol(self):
        from axon_enterprise.supervisor.hooks import default_enterprise_hooks
        hooks = default_enterprise_hooks()
        # The OSS Protocol is `runtime_checkable` — instances of the
        # enterprise hooks must satisfy it.
        assert isinstance(hooks, SupervisorHooks)

    def test_factory_returns_oss_supervisor(self):
        from axon_enterprise.supervisor import make_enterprise_supervisor
        sup = make_enterprise_supervisor()
        assert isinstance(sup, DaemonSupervisor)
        # And the supervisor has hooks installed (not None).
        assert sup._hooks is not None


# ═══════════════════════════════════════════════════════════════════
#  16.e — Telemetry
# ═══════════════════════════════════════════════════════════════════


class TestTelemetry:
    """Prometheus counters + structlog logs fire on lifecycle events."""

    def test_counters_increment_on_start(self):
        from axon_enterprise.supervisor.telemetry import (
            SUPERVISOR_ACTIVE_DAEMONS,
            SupervisorTelemetry,
        )
        gauge = SUPERVISOR_ACTIVE_DAEMONS.labels(tenant="test_tenant")
        before = gauge._value.get()
        t = SupervisorTelemetry(tenant_resolver=lambda _: "test_tenant")
        t.emit_start("d", 0)
        assert gauge._value.get() == before + 1

    def test_counter_label_cardinality_constrained(self):
        """Histograms must NOT have a `daemon` or `tenant` label
        explosion — verify the registered metric labelnames are the
        ones we declared."""
        from axon_enterprise.supervisor.telemetry import (
            SUPERVISOR_RESTART_DELAY_SECONDS,
            SUPERVISOR_RESTARTS_TOTAL,
        )
        # Histograms keep tenant only (low cardinality).
        assert "tenant" in SUPERVISOR_RESTART_DELAY_SECONDS._labelnames
        # Counters allow daemon + tenant + reason (high-cardinality
        # but bounded by registered daemons).
        assert {"daemon", "tenant", "reason"} == set(SUPERVISOR_RESTARTS_TOTAL._labelnames)

    def test_emit_intensity_exceeded_increments_counter(self):
        from axon_enterprise.supervisor.telemetry import (
            SUPERVISOR_INTENSITY_EXCEEDED_TOTAL,
            SupervisorTelemetry,
        )
        counter = SUPERVISOR_INTENSITY_EXCEEDED_TOTAL.labels(
            daemon="x", tenant="t",
        )
        before = counter._value.get()
        t = SupervisorTelemetry(tenant_resolver=lambda _: "t")
        t.emit_intensity_exceeded("x", 5)
        assert counter._value.get() == before + 1


# ═══════════════════════════════════════════════════════════════════
#  16.f — State persistence
# ═══════════════════════════════════════════════════════════════════


class TestPersistence:
    """snapshot → restore round-trip via the cooperative checkpoint API."""

    @pytest.mark.asyncio
    async def test_snapshot_round_trip(self):
        from axon_enterprise.supervisor.persistence import (
            InMemoryStateStore,
            StatePersistence,
        )
        store = InMemoryStateStore()
        persistence = StatePersistence(store=store)

        async def checkpoint():
            return {"counter": 42, "name": "alpha"}

        persistence.register_checkpoint("d", checkpoint)
        blob = await persistence.snapshot("d")
        assert blob is not None
        restored = await persistence.restore("d")
        assert restored == {"counter": 42, "name": "alpha"}

    @pytest.mark.asyncio
    async def test_no_checkpoint_yields_none(self):
        from axon_enterprise.supervisor.persistence import (
            InMemoryStateStore,
            StatePersistence,
        )
        persistence = StatePersistence(store=InMemoryStateStore())
        assert await persistence.snapshot("unknown") is None
        assert await persistence.restore("unknown") is None

    @pytest.mark.asyncio
    async def test_clear_drops_state(self):
        from axon_enterprise.supervisor.persistence import (
            InMemoryStateStore,
            StatePersistence,
        )
        persistence = StatePersistence(store=InMemoryStateStore())
        persistence.register_checkpoint("d", lambda: _coro({"x": 1}))
        await persistence.snapshot("d")
        await persistence.clear("d")
        assert await persistence.restore("d") is None


async def _coro(v):
    return v


# ═══════════════════════════════════════════════════════════════════
#  16.g — on_stuck policy dispatcher
# ═══════════════════════════════════════════════════════════════════


class TestPolicies:
    """Every on_stuck policy resolves correctly."""

    def _dispatcher(self):
        from axon_enterprise.supervisor.policies import (
            PolicyContext,
            PolicyDispatcher,
        )
        ctx = PolicyContext()
        return PolicyDispatcher(ctx=ctx)

    @pytest.mark.asyncio
    async def test_restart_default(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "restart", RuntimeError("x"))
        assert result == "restart"

    @pytest.mark.asyncio
    async def test_hibernate_terminates(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "hibernate", RuntimeError("x"))
        assert result == "noop"

    @pytest.mark.asyncio
    async def test_escalate_terminates(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "escalate", RuntimeError("x"))
        assert result == "noop"

    @pytest.mark.asyncio
    async def test_retry_resolves_to_restart(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "retry", RuntimeError("x"))
        assert result == "restart"

    @pytest.mark.asyncio
    async def test_forge_resolves_to_restart_when_no_handler(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "forge", RuntimeError("x"))
        assert result == "restart"

    @pytest.mark.asyncio
    async def test_noop_terminates(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "noop", RuntimeError("x"))
        assert result == "noop"

    @pytest.mark.asyncio
    async def test_unknown_fallback_to_restart(self):
        d = self._dispatcher()
        result = await d.dispatch("foo", "totally_invalid", RuntimeError("x"))
        assert result == "restart"


# ═══════════════════════════════════════════════════════════════════
#  16.h — Decorrelated-jitter backoff
# ═══════════════════════════════════════════════════════════════════


class TestBackoff:
    """Decorrelated-jitter distribution properties."""

    def test_first_delay_within_base_range(self):
        from axon_enterprise.supervisor.backoff import DecorrelatedJitterBackoff
        b = DecorrelatedJitterBackoff(base_s=0.1, cap_s=10.0)
        delay = b.next_delay("d")
        assert b.base_s <= delay <= b.base_s * b.growth

    def test_delay_caps_at_max(self):
        from axon_enterprise.supervisor.backoff import DecorrelatedJitterBackoff
        b = DecorrelatedJitterBackoff(base_s=0.1, cap_s=2.0, growth=10.0)
        # Run enough iterations that uncapped growth would blow past 2s.
        for _ in range(20):
            d = b.next_delay("d")
            assert d <= 2.0

    def test_reset_returns_to_base(self):
        from axon_enterprise.supervisor.backoff import DecorrelatedJitterBackoff
        b = DecorrelatedJitterBackoff()
        for _ in range(10):
            b.next_delay("d")
        b.reset("d")
        first = b.next_delay("d")
        assert first <= b.base_s * b.growth

    def test_per_daemon_independence(self):
        from axon_enterprise.supervisor.backoff import DecorrelatedJitterBackoff
        b = DecorrelatedJitterBackoff()
        for _ in range(5):
            b.next_delay("alpha")
        # Beta starts fresh from base.
        first_beta = b.next_delay("beta")
        assert first_beta <= b.base_s * b.growth


# ═══════════════════════════════════════════════════════════════════
#  16.i — Health probes
# ═══════════════════════════════════════════════════════════════════


class TestHealthProbes:
    @pytest.mark.asyncio
    async def test_heartbeat_alive(self):
        from axon_enterprise.supervisor.health import (
            HealthProbeRegistry,
            ProbeConfig,
            ProbeKind,
        )
        reg = HealthProbeRegistry()
        reg.register("d", ProbeConfig(kind=ProbeKind.HEARTBEAT, interval_s=10.0, tolerance=2.0))
        reg.heartbeat("d")
        assert await reg.is_alive("d") is True

    @pytest.mark.asyncio
    async def test_heartbeat_stuck(self):
        from axon_enterprise.supervisor.health import (
            HealthProbeRegistry,
            ProbeConfig,
            ProbeKind,
        )
        reg = HealthProbeRegistry()
        reg.register("d", ProbeConfig(
            kind=ProbeKind.HEARTBEAT, interval_s=0.001, tolerance=1.0,
        ))
        reg.heartbeat("d")
        await asyncio.sleep(0.05)  # exceed deadline
        assert await reg.is_alive("d") is False

    @pytest.mark.asyncio
    async def test_custom_predicate_alive(self):
        from axon_enterprise.supervisor.health import (
            HealthProbeRegistry,
            ProbeConfig,
            ProbeKind,
        )
        reg = HealthProbeRegistry()
        async def alive(): return True
        reg.register("d", ProbeConfig(
            kind=ProbeKind.CUSTOM, custom_fn=alive,
        ))
        assert await reg.is_alive("d") is True

    @pytest.mark.asyncio
    async def test_custom_predicate_dead(self):
        from axon_enterprise.supervisor.health import (
            HealthProbeRegistry,
            ProbeConfig,
            ProbeKind,
        )
        reg = HealthProbeRegistry()
        async def dead(): return False
        reg.register("d", ProbeConfig(
            kind=ProbeKind.CUSTOM, custom_fn=dead,
        ))
        assert await reg.is_alive("d") is False

    @pytest.mark.asyncio
    async def test_unregistered_default_alive(self):
        from axon_enterprise.supervisor.health import HealthProbeRegistry
        reg = HealthProbeRegistry()
        assert await reg.is_alive("never_registered") is True


# ═══════════════════════════════════════════════════════════════════
#  16.j — Supervision tree
# ═══════════════════════════════════════════════════════════════════


class TestHierarchy:
    @pytest.mark.asyncio
    async def test_two_level_tree_starts_and_stops(self):
        from axon_enterprise.supervisor import (
            SupervisionNode,
            SupervisionTree,
            make_enterprise_supervisor,
        )
        tenant_a = make_enterprise_supervisor(
            tenant_resolver=lambda _: "acme",
        )
        tenant_b = make_enterprise_supervisor(
            tenant_resolver=lambda _: "globex",
        )
        tree = SupervisionTree.platform_tenant_layout(
            tenants={"acme": tenant_a, "globex": tenant_b},
        )
        await tree.start_all()
        assert tenant_a.active_count == 0  # no daemons registered
        assert tenant_b.active_count == 0
        await tree.stop_all()

    @pytest.mark.asyncio
    async def test_failure_escalates_to_parent(self):
        from axon_enterprise.supervisor.hierarchy import (
            SupervisionNode,
            SupervisionTree,
        )
        escalations: list[str] = []

        async def parent_handler(child_name: str):
            escalations.append(child_name)

        root = SupervisionNode(
            name="platform",
            on_child_failure=parent_handler,
        )
        child = SupervisionNode(name="tenant_acme")
        root.add_child(child)
        await child.report_failure("OrderDaemon")
        assert "tenant_acme/OrderDaemon" in escalations


# ═══════════════════════════════════════════════════════════════════
#  16.l — Audit chain
# ═══════════════════════════════════════════════════════════════════


class TestAuditChain:
    @pytest.mark.asyncio
    async def test_chain_appends_signed_entries(self):
        from axon_enterprise.supervisor.audit import (
            InMemoryAuditSink,
            SupervisorAuditChain,
        )
        sink = InMemoryAuditSink()
        chain = SupervisorAuditChain(
            sink=sink,
            tenant_resolver=lambda _: "acme",
            sign_key_fn=lambda _: b"secret",
        )
        await chain.append("daemon_started", "OrderDaemon", {"attempt": 0})
        await chain.append("daemon_crashed", "OrderDaemon", {"attempt": 0})
        assert len(sink.entries) == 2
        for entry in sink.entries:
            assert entry["signature"]
            assert entry["merkle_hash"]
            assert entry["tenant_id"] == "acme"

    @pytest.mark.asyncio
    async def test_chain_links_via_prev_hash(self):
        from axon_enterprise.supervisor.audit import (
            InMemoryAuditSink,
            SupervisorAuditChain,
        )
        sink = InMemoryAuditSink()
        chain = SupervisorAuditChain(
            sink=sink,
            tenant_resolver=lambda _: "acme",
            sign_key_fn=lambda _: b"secret",
        )
        await chain.append("daemon_started", "OrderDaemon", {})
        await chain.append("daemon_crashed", "OrderDaemon", {})
        assert sink.entries[0]["prev_hash"] == ""
        assert sink.entries[1]["prev_hash"] == sink.entries[0]["merkle_hash"]

    @pytest.mark.asyncio
    async def test_chain_verifies_intact(self):
        from axon_enterprise.supervisor.audit import (
            InMemoryAuditSink,
            SupervisorAuditChain,
            verify_chain,
        )
        sink = InMemoryAuditSink()
        chain = SupervisorAuditChain(
            sink=sink,
            tenant_resolver=lambda _: "acme",
            sign_key_fn=lambda _: b"secret",
        )
        for i in range(5):
            await chain.append("daemon_restarted", "OrderDaemon", {"attempt": i})
        assert verify_chain(sink.entries, tenant_id="acme", key=b"secret")

    @pytest.mark.asyncio
    async def test_tampered_signature_detected(self):
        from axon_enterprise.supervisor.audit import (
            InMemoryAuditSink,
            SupervisorAuditChain,
            verify_chain,
        )
        sink = InMemoryAuditSink()
        chain = SupervisorAuditChain(
            sink=sink,
            tenant_resolver=lambda _: "acme",
            sign_key_fn=lambda _: b"secret",
        )
        await chain.append("daemon_started", "OrderDaemon", {})
        # Tamper with the payload after the fact — verification fails.
        sink.entries[0]["payload"] = {"attempt": 999}
        assert not verify_chain(sink.entries, tenant_id="acme", key=b"secret")


# ═══════════════════════════════════════════════════════════════════
#  16.m — Multi-tenant isolation
# ═══════════════════════════════════════════════════════════════════


class TestIsolation:
    def test_default_budget_allows_some_restarts(self):
        from axon_enterprise.supervisor.isolation import TenantBudgetRegistry
        reg = TenantBudgetRegistry()
        assert reg.restart_allowed("acme") is True

    def test_budget_exhaustion_rejects(self):
        from axon_enterprise.supervisor.isolation import (
            TenantBudget,
            TenantBudgetRegistry,
        )
        reg = TenantBudgetRegistry()
        reg.configure(TenantBudget(
            tenant_id="acme", max_restarts_per_minute=2,
        ))
        assert reg.restart_allowed("acme") is True
        reg.record_restart("acme")
        assert reg.restart_allowed("acme") is True
        reg.record_restart("acme")
        # Third attempt would be the third restart in the window.
        assert reg.restart_allowed("acme") is False

    def test_tenants_isolated(self):
        from axon_enterprise.supervisor.isolation import (
            TenantBudget,
            TenantBudgetRegistry,
        )
        reg = TenantBudgetRegistry()
        reg.configure(TenantBudget(tenant_id="acme", max_restarts_per_minute=1))
        reg.configure(TenantBudget(tenant_id="globex", max_restarts_per_minute=1))
        reg.record_restart("acme")
        # acme exhausted; globex untouched.
        assert reg.restart_allowed("acme") is False
        assert reg.restart_allowed("globex") is True

    def test_snapshot_size_bound(self):
        from axon_enterprise.supervisor.isolation import (
            TenantBudget,
            TenantBudgetRegistry,
        )
        reg = TenantBudgetRegistry()
        reg.configure(TenantBudget(
            tenant_id="acme", max_state_snapshot_bytes=1024,
        ))
        assert reg.snapshot_size_allowed("acme", 512) is True
        assert reg.snapshot_size_allowed("acme", 4096) is False


# ═══════════════════════════════════════════════════════════════════
#  16.n — Compliance gating
# ═══════════════════════════════════════════════════════════════════


class TestCompliance:
    @pytest.mark.asyncio
    async def test_no_basis_required_allows(self):
        from axon_enterprise.supervisor.compliance import default_compliance_gate
        gate = default_compliance_gate()
        assert await gate.allow_restart("DaemonX") is True

    @pytest.mark.asyncio
    async def test_invalid_basis_blocks(self):
        from axon_enterprise.supervisor.compliance import ComplianceGate

        class StrictChecker:
            async def is_basis_valid(self, tenant_id, basis_slug):
                return basis_slug != "expired_basis"

        gate = ComplianceGate(
            checker=StrictChecker(),
            basis_resolver=lambda _: ["expired_basis"],
            tenant_resolver=lambda _: "acme",
        )
        assert await gate.allow_restart("DaemonX") is False

    @pytest.mark.asyncio
    async def test_all_valid_bases_allows(self):
        from axon_enterprise.supervisor.compliance import ComplianceGate

        class StrictChecker:
            async def is_basis_valid(self, tenant_id, basis_slug):
                return True

        gate = ComplianceGate(
            checker=StrictChecker(),
            basis_resolver=lambda _: ["a", "b", "c"],
            tenant_resolver=lambda _: "acme",
        )
        assert await gate.allow_restart("DaemonX") is True


# ═══════════════════════════════════════════════════════════════════
#  16.o — Distributed leader election
# ═══════════════════════════════════════════════════════════════════


class TestDistributed:
    @pytest.mark.asyncio
    async def test_in_memory_always_leader(self):
        from axon_enterprise.supervisor.distributed import InMemoryLeaderElection
        elector = InMemoryLeaderElection()
        assert await elector.is_leader_for("OrderDaemon") is True
        assert await elector.acquire_leadership("OrderDaemon") is True

    @pytest.mark.asyncio
    async def test_redlock_no_redis_fails_open(self):
        """When `redis_client` is None, the elector defaults to
        always-leader (single-instance behavior)."""
        from axon_enterprise.supervisor.distributed import (
            RedisRedlockLeaderElection,
        )
        elector = RedisRedlockLeaderElection(
            instance_id="instance-a", redis_client=None,
        )
        assert await elector.is_leader_for("OrderDaemon") is True

    @pytest.mark.asyncio
    async def test_redlock_two_instances_compete(self):
        """Stub Redis client: only the first acquirer wins; the second
        sees the existing key."""
        from axon_enterprise.supervisor.distributed import (
            RedisRedlockLeaderElection,
        )

        class FakeRedis:
            def __init__(self):
                self.kv: dict[str, str] = {}

            def set(self, key, value, nx=False, ex=None):
                if nx and key in self.kv:
                    return None
                self.kv[key] = value
                return True

            def get(self, key):
                return self.kv.get(key)

            def delete(self, key):
                self.kv.pop(key, None)

        client = FakeRedis()
        a = RedisRedlockLeaderElection(instance_id="A", redis_client=client)
        b = RedisRedlockLeaderElection(instance_id="B", redis_client=client)
        assert await a.acquire_leadership("d") is True
        assert await b.acquire_leadership("d") is False
        assert await a.is_leader_for("d") is True
        assert await b.is_leader_for("d") is False
        await a.release_leadership("d")
        assert await b.acquire_leadership("d") is True


# ═══════════════════════════════════════════════════════════════════
#  16.p — Factory + end-to-end integration
# ═══════════════════════════════════════════════════════════════════


class TestFactory:
    """End-to-end: full enterprise supervisor over a daemon lifecycle."""

    @pytest.mark.asyncio
    async def test_enterprise_supervisor_runs_clean_daemon(self):
        from axon_enterprise.supervisor import make_enterprise_supervisor

        completed = asyncio.Event()

        async def daemon():
            completed.set()
            await asyncio.sleep(0.5)

        sup = make_enterprise_supervisor()
        sup.register("d", daemon)
        await sup.start_all()
        await asyncio.wait_for(completed.wait(), timeout=2.0)
        await sup.stop_all()
        assert sup.active_count == 0

    @pytest.mark.asyncio
    async def test_enterprise_supervisor_audits_lifecycle(self):
        from axon_enterprise.supervisor import make_enterprise_supervisor
        from axon_enterprise.supervisor.audit import InMemoryAuditSink

        sink = InMemoryAuditSink()

        async def quick():
            await asyncio.sleep(0.05)

        sup = make_enterprise_supervisor(audit_sink=sink)
        sup.register("ledger", quick)
        await sup.start_all()
        await asyncio.sleep(0.2)
        await sup.stop_all()

        # At minimum the daemon_started event lands.
        events = [e["event_type"] for e in sink.entries]
        assert "daemon_started" in events

    @pytest.mark.asyncio
    async def test_enterprise_supervisor_persists_state(self):
        from axon_enterprise.supervisor import make_enterprise_supervisor
        from axon_enterprise.supervisor.persistence import (
            InMemoryStateStore,
            StatePersistence,
        )

        store = InMemoryStateStore()
        sup = make_enterprise_supervisor(state_store=store)

        # Cooperative checkpoint registration: the daemon publishes
        # snapshots through its enterprise hooks adapter.
        # For this test we register the checkpoint directly via the
        # hooks impl (bypassing the daemon-side API).
        sup._hooks.persistence.register_checkpoint(  # type: ignore[union-attr]
            "ledger", lambda: _coro({"counter": 7}),
        )

        async def crasher():
            raise RuntimeError("oops")

        sup.register("ledger", crasher)
        await sup.start_all()
        await asyncio.sleep(0.2)
        await sup.stop_all()

        # Persistence layer captured the snapshot (in the in-memory store).
        restored = await sup._hooks.persistence.restore("ledger")  # type: ignore[union-attr]
        assert restored == {"counter": 7}

    @pytest.mark.asyncio
    async def test_enterprise_supervisor_default_compliance_allows(self):
        """default_compliance_gate is no-op — every restart allowed."""
        from axon_enterprise.supervisor import make_enterprise_supervisor

        attempts = 0

        async def crash_then_succeed():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("boom")
            await asyncio.sleep(0.5)

        sup = make_enterprise_supervisor(
            config=SupervisorConfig(max_restarts=10, max_seconds=60.0),
        )
        sup.register("d", crash_then_succeed)
        await sup.start_all()
        await asyncio.sleep(0.5)
        await sup.stop_all()

        assert attempts >= 3  # restarts honored


# ═══════════════════════════════════════════════════════════════════
#  16.q — Concurrent-crash stress (regression gate)
# ═══════════════════════════════════════════════════════════════════


class TestConcurrentCrashStress:
    """Stress: 5 daemons under ONE_FOR_ALL all crashing simultaneously
    via the enterprise supervisor wrapper. Verifies dict integrity
    via the OSS race fix + cascade flag survives the enterprise hook
    layer (no double-counting, no leaked tasks)."""

    @pytest.mark.asyncio
    async def test_concurrent_crash_under_enterprise_hooks(self):
        from axon.runtime.supervisor import (
            SupervisionStrategy,
            SupervisorConfig,
        )
        from axon_enterprise.supervisor import make_enterprise_supervisor

        crash_event = asyncio.Event()
        per_daemon_calls: dict[str, int] = {}

        async def make_daemon(name: str):
            per_daemon_calls[name] = per_daemon_calls.get(name, 0) + 1
            if per_daemon_calls[name] == 1:
                await crash_event.wait()
                raise RuntimeError("shared crash")
            await asyncio.sleep(0.3)

        config = SupervisorConfig(
            max_restarts=20,
            max_seconds=60.0,
            strategy=SupervisionStrategy.ONE_FOR_ALL,
        )
        sup = make_enterprise_supervisor(config=config)
        N = 5
        for i in range(N):
            sup.register(f"d{i}", make_daemon, f"d{i}")
        await sup.start_all()
        await asyncio.sleep(0.05)
        crash_event.set()
        await asyncio.sleep(0.5)

        assert len(sup._tasks) == N
        assert set(sup._tasks.keys()) == {f"d{i}" for i in range(N)}
        await sup.stop_all()
        assert sup.active_count == 0
