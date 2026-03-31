"""APX Phase 6 tests: compliance gates, forensic export, and operational hardening."""

from __future__ import annotations

import pytest

from axon.engine.apx import (
    APXComplianceError,
    APXCompliancePolicy,
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
from axon.runtime.apx_resolver import APXContract, APXPolicy, APXResolver


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
    g = EpistemicGraph("runtime-apx-phase6")
    g.add_node(EpistemicNode("base.core", EpistemicLevel.CITED_FACT, _contract("base")))
    g.add_node(EpistemicNode("pkg.safe", EpistemicLevel.FACTUAL_CLAIM, _contract("safe")))
    g.add_edge(EpistemicEdge("pkg.safe", "base.core", EdgeKind.DEPENDS_ON, 1.0))
    return g


def test_export_events_json_and_jsonl() -> None:
    obs = APXObservability(component="apx.test")
    obs.emit(APXEventType.PCC_VERIFICATION, operation="register", status="ok", package_key="pkg@1")

    as_json = obs.export_events("json")
    as_jsonl = obs.export_events("jsonl")

    assert as_json.startswith("[")
    assert "pcc_verification" in as_json
    assert "pcc_verification" in as_jsonl
    assert "\n" not in as_json


def test_recent_events_can_filter_by_type() -> None:
    obs = APXObservability(component="apx.test")
    obs.emit(APXEventType.PCC_VERIFICATION, operation="register", status="ok")
    obs.emit(APXEventType.RUNTIME_RESOLVE, operation="resolve", status="ok")

    filtered = obs.recent_events(limit=5, event_type=APXEventType.PCC_VERIFICATION)
    assert len(filtered) == 1
    assert filtered[0].event_type == APXEventType.PCC_VERIFICATION


def test_compliance_gate_passes_under_default_policy() -> None:
    obs = APXObservability(component="apx.test")
    obs.emit(APXEventType.PCC_VERIFICATION, operation="register", status="ok")
    obs.assert_compliance()


def test_compliance_gate_fails_for_blame_faults() -> None:
    obs = APXObservability(component="apx.test")
    obs.emit(APXEventType.PCC_VERIFICATION, operation="register", status="ok")
    obs.emit(APXEventType.BLAME_FAULT, operation="execute_with_contract", status="failed")

    with pytest.raises(APXComplianceError, match="blame_faults_exceeded"):
        obs.assert_compliance(APXCompliancePolicy(max_blame_faults=0))


def test_registry_and_resolver_operational_compliance_helpers() -> None:
    obs_registry = APXObservability(component="apx.registry.test")
    reg = APXRegistry(observability=obs_registry)
    low = _manifest("pkg.low", "1.0.0", EpistemicLevel.UNCERTAINTY, "cert-low")
    reg.register(low, source_hash="src-pkg.low-1.0.0", pcc_hash="cert-low")
    _ = reg.resolve("pkg.low", "1.0.0", min_epr=0.95, on_low_rank="quarantine")

    report = reg.compliance_report()
    assert report["quarantine_actions"] >= 1

    strict_policy = APXCompliancePolicy(max_quarantine_actions=0)
    with pytest.raises(APXComplianceError):
        reg.assert_compliance(strict_policy)

    obs_runtime = APXObservability(component="apx.runtime.test")
    resolver = APXResolver(observability=obs_runtime)

    def _call(args):
        return {"ok": False}

    _ = resolver.resolve(
        graph=_graph(),
        package_id="pkg.safe",
        policy=APXPolicy(min_epr=0.0, on_low_rank="warn", ffi_mode="taint"),
        provided_pcc_hash="hash-safe",
        ffi_payload={"k": 1},
    )
    _ = resolver.execute_with_contract(
        "pkg.safe",
        {},
        _call,
        APXContract(name="X", postcondition=lambda r: r.get("ok", False), on_violation="warn"),
    )

    runtime_report = resolver.compliance_report()
    assert runtime_report["contract_violations"] >= 1


def test_export_events_rejects_unknown_format() -> None:
    obs = APXObservability(component="apx.test")
    with pytest.raises(ValueError, match="unsupported export format"):
        obs.export_events("csv")
