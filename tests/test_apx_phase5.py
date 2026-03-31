"""APX Phase 5 tests: observability, audit trail, and compliance reports."""

from __future__ import annotations

import pytest

from axon.engine.apx import (
    APXDependency,
    APXEventType,
    APXObservability,
    APXPackageManifest,
    APXRegistry,
    EdgeKind,
    EpistemicContract,
    EpistemicEdge,
    EpistemicGraph,
    EpistemicLevel,
    EpistemicNode,
)
from axon.runtime.apx_resolver import APXContract, APXDecision, APXPolicy, APXResolver


def _manifest(
    package_id: str,
    version: str,
    level: EpistemicLevel,
    cert_hash: str,
    deps: tuple[APXDependency, ...] = (),
) -> APXPackageManifest:
    ecid = APXRegistry.compute_ecid(package_id, version, f"src-{package_id}-{version}", cert_hash)
    return APXPackageManifest(
        package_id=package_id,
        version=version,
        level=level,
        ecid=ecid,
        certificate_hash=cert_hash,
        witnesses=("w1",),
        dependencies=deps,
    )


def _contract(seed: str) -> EpistemicContract:
    return EpistemicContract(ecid=f"ecid-{seed}", certificate_hash=f"hash-{seed}", witness_count=2)


def _graph() -> EpistemicGraph:
    g = EpistemicGraph("runtime-apx-observability")
    g.add_node(EpistemicNode("base.core", EpistemicLevel.CITED_FACT, _contract("base")))
    g.add_node(EpistemicNode("pkg.safe", EpistemicLevel.FACTUAL_CLAIM, _contract("safe")))
    g.add_edge(EpistemicEdge("pkg.safe", "base.core", EdgeKind.DEPENDS_ON, 1.0))
    return g


def test_observability_track_and_snapshot() -> None:
    obs = APXObservability(component="apx.test")
    with obs.track("resolve"):
        _ = 1 + 1

    snap = obs.snapshot()
    assert snap["component"] == "apx.test"
    assert snap["metrics"]["resolve"]["count"] == 1
    assert snap["metrics"]["resolve"]["errors"] == 0


def test_registry_emits_register_and_pcc_events() -> None:
    obs = APXObservability(component="apx.registry.test")
    reg = APXRegistry(observability=obs)
    m = _manifest("pkg.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-core")

    reg.register(m, source_hash="src-pkg.core-1.0.0", pcc_hash="cert-core")

    event_types = [e.event_type for e in obs.events]
    assert APXEventType.PCC_VERIFICATION in event_types
    assert APXEventType.REGISTRY_REGISTER in event_types


def test_registry_compliance_report_flags_quarantine_activity() -> None:
    obs = APXObservability(component="apx.registry.test")
    reg = APXRegistry(observability=obs)
    low = _manifest("pkg.low", "1.0.0", EpistemicLevel.UNCERTAINTY, "cert-low")

    reg.register(low, source_hash="src-pkg.low-1.0.0", pcc_hash="cert-low")
    _ = reg.resolve("pkg.low", "1.0.0", min_epr=0.95, on_low_rank="quarantine")

    report = obs.compliance_report()
    assert report["quarantine_actions"] >= 1
    assert report["pcc_checks"] >= 1


def test_runtime_resolver_emits_resolution_and_ffi_events() -> None:
    obs = APXObservability(component="apx.runtime.test")
    resolver = APXResolver(observability=obs)

    result = resolver.resolve(
        graph=_graph(),
        package_id="pkg.safe",
        policy=APXPolicy(min_epr=0.0, on_low_rank="warn", ffi_mode="sanitize"),
        provided_pcc_hash="hash-safe",
        ffi_payload={"keep": 1, "api_token": "x"},
    )

    assert result.decision == APXDecision.RESOLVED
    event_types = [e.event_type for e in obs.events]
    assert APXEventType.RUNTIME_RESOLVE in event_types
    assert APXEventType.FFI_DEGRADATION in event_types


def test_runtime_contract_faults_are_audited() -> None:
    obs = APXObservability(component="apx.runtime.test")
    resolver = APXResolver(observability=obs)

    def _call(args):
        return {"ok": False}

    contract = APXContract(
        name="C",
        postcondition=lambda r: r.get("ok", False) is True,
        on_violation="warn",
    )

    output = resolver.execute_with_contract("pkg.safe", {}, _call, contract)
    assert "warning" in output

    event_types = [e.event_type for e in obs.events]
    assert APXEventType.BLAME_FAULT in event_types
    assert APXEventType.CONTRACT_VIOLATION in event_types


def test_observability_track_captures_errors() -> None:
    obs = APXObservability(component="apx.test")

    with pytest.raises(RuntimeError):
        with obs.track("register"):
            raise RuntimeError("boom")

    snap = obs.snapshot()
    assert snap["metrics"]["register"]["count"] == 1
    assert snap["metrics"]["register"]["errors"] == 1
