"""APX Phase 4 tests: package infrastructure and APX registry."""

from __future__ import annotations

import pytest

from axon.engine.apx import (
    APXDecision,
    APXDependency,
    APXPackageManifest,
    APXRegistry,
    APXRegistryError,
    EdgeKind,
    EpistemicLevel,
)


def _manifest(
    package_id: str,
    version: str,
    level: EpistemicLevel,
    cert_hash: str,
    deps: tuple[APXDependency, ...] = (),
) -> APXPackageManifest:
    src_hash = f"src-{package_id}-{version}"
    ecid = APXRegistry.compute_ecid(package_id, version, src_hash, cert_hash)
    return APXPackageManifest(
        package_id=package_id,
        version=version,
        level=level,
        ecid=ecid,
        certificate_hash=cert_hash,
        witnesses=("w1",),
        dependencies=deps,
    )


def test_registry_register_and_fetch() -> None:
    reg = APXRegistry()
    m = _manifest("pkg.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-core")
    rec = reg.register(m, source_hash="src-pkg.core-1.0.0", pcc_hash="cert-core")

    assert reg.package_count == 1
    fetched = reg.get("pkg.core", "1.0.0")
    assert fetched is not None
    assert fetched.manifest.package_id == rec.manifest.package_id


def test_registry_rejects_duplicate_immutable_node() -> None:
    reg = APXRegistry()
    m = _manifest("pkg.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-core")
    reg.register(m, source_hash="src-pkg.core-1.0.0", pcc_hash="cert-core")

    with pytest.raises(APXRegistryError, match="immutable node violation"):
        reg.register(m, source_hash="src-pkg.core-1.0.0", pcc_hash="cert-core")


def test_registry_rejects_pcc_mismatch() -> None:
    reg = APXRegistry()
    m = _manifest("pkg.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-core")

    with pytest.raises(APXRegistryError, match="PCC verification failed"):
        reg.register(m, source_hash="src-pkg.core-1.0.0", pcc_hash="wrong")


def test_registry_version_dag_cycle_detected() -> None:
    reg = APXRegistry()
    m1 = _manifest("pkg.a", "1.0.0", EpistemicLevel.FACTUAL_CLAIM, "cert-a1")
    m2 = _manifest("pkg.a", "1.1.0", EpistemicLevel.CITED_FACT, "cert-a2")

    reg.register(m1, source_hash="src-pkg.a-1.0.0", pcc_hash="cert-a1")
    reg.register(
        m2,
        source_hash="src-pkg.a-1.1.0",
        pcc_hash="cert-a2",
        parent_versions=("pkg.a@1.0.0",),
    )

    # Inject a cycle by registering a version that points back and using
    # the existing node as a parent.
    m3 = _manifest("pkg.a", "2.0.0", EpistemicLevel.CITED_FACT, "cert-a3")
    reg.register(
        m3,
        source_hash="src-pkg.a-2.0.0",
        pcc_hash="cert-a3",
        parent_versions=("pkg.a@1.1.0",),
    )

    # mutate parent pointers to create explicit cycle and assert detector
    reg._version_parents["pkg.a@1.0.0"].add("pkg.a@2.0.0")
    with pytest.raises(APXRegistryError, match="Epi-Ver DAG cycle"):
        reg._validate_version_dag_acyclic()


def test_registry_build_graph_and_rank() -> None:
    reg = APXRegistry()
    base = _manifest("base.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-base")
    app = _manifest(
        "pkg.app",
        "1.0.0",
        EpistemicLevel.FACTUAL_CLAIM,
        "cert-app",
        deps=(APXDependency("base.core", "1.0.0", EdgeKind.DEPENDS_ON, 1.0),),
    )

    reg.register(base, source_hash="src-base.core-1.0.0", pcc_hash="cert-base")
    reg.register(app, source_hash="src-pkg.app-1.0.0", pcc_hash="cert-app")

    graph = reg.build_epistemic_graph()
    assert graph.node_count == 2
    assert graph.edge_count == 1

    scores = reg.rank_packages()
    assert "base.core@1.0.0" in scores
    assert "pkg.app@1.0.0" in scores


def test_registry_quarantine_below_threshold() -> None:
    reg = APXRegistry()
    strong = _manifest("pkg.strong", "1.0.0", EpistemicLevel.CITED_FACT, "cert-s")
    weak = _manifest("pkg.weak", "1.0.0", EpistemicLevel.UNCERTAINTY, "cert-w")

    reg.register(strong, source_hash="src-pkg.strong-1.0.0", pcc_hash="cert-s")
    reg.register(weak, source_hash="src-pkg.weak-1.0.0", pcc_hash="cert-w")

    quarantined = reg.quarantine_below(0.2)
    assert isinstance(quarantined, list)
    assert reg.is_quarantined("pkg.weak", "1.0.0") or reg.is_quarantined("pkg.strong", "1.0.0")


def test_registry_resolve_with_incremental_cache() -> None:
    reg = APXRegistry()
    base = _manifest("base.core", "1.0.0", EpistemicLevel.CITED_FACT, "cert-base")
    app = _manifest(
        "pkg.app",
        "1.0.0",
        EpistemicLevel.FACTUAL_CLAIM,
        "cert-app",
        deps=(APXDependency("base.core", "1.0.0"),),
    )

    reg.register(base, source_hash="src-base.core-1.0.0", pcc_hash="cert-base")
    reg.register(app, source_hash="src-pkg.app-1.0.0", pcc_hash="cert-app")

    r1 = reg.resolve("pkg.app", "1.0.0", min_epr=0.0, on_low_rank="warn", use_cache=True)
    r2 = reg.resolve("pkg.app", "1.0.0", min_epr=0.0, on_low_rank="warn", use_cache=True)

    assert r1.decision in (APXDecision.RESOLVED, APXDecision.WARNED)
    assert r2.cache_hit is True

    # new registration bumps generation and invalidates effective cache key
    extra = _manifest("pkg.extra", "1.0.0", EpistemicLevel.FACTUAL_CLAIM, "cert-extra")
    reg.register(extra, source_hash="src-pkg.extra-1.0.0", pcc_hash="cert-extra")

    r3 = reg.resolve("pkg.app", "1.0.0", min_epr=0.0, on_low_rank="warn", use_cache=True)
    assert r3.cache_hit is False


def test_registry_resolve_quarantine_and_block_policies() -> None:
    reg = APXRegistry()
    low = _manifest("pkg.low", "1.0.0", EpistemicLevel.UNCERTAINTY, "cert-low")
    reg.register(low, source_hash="src-pkg.low-1.0.0", pcc_hash="cert-low")

    q = reg.resolve("pkg.low", "1.0.0", min_epr=0.95, on_low_rank="quarantine")
    assert q.decision == APXDecision.QUARANTINED

    b = reg.resolve("pkg.low", "1.0.0", min_epr=0.95, on_low_rank="block")
    assert b.decision in (APXDecision.BLOCKED, APXDecision.QUARANTINED)


def test_verify_pcc_and_list_versions() -> None:
    reg = APXRegistry()
    m1 = _manifest("pkg.core", "1.0.0", EpistemicLevel.FACTUAL_CLAIM, "cert-1")
    m2 = _manifest("pkg.core", "1.1.0", EpistemicLevel.CITED_FACT, "cert-2")

    reg.register(m1, source_hash="src-pkg.core-1.0.0", pcc_hash="cert-1")
    reg.register(m2, source_hash="src-pkg.core-1.1.0", pcc_hash="cert-2")

    assert reg.verify_pcc("pkg.core", "1.0.0", "cert-1") is True
    assert reg.verify_pcc("pkg.core", "1.0.0", "wrong") is False
    assert reg.list_versions("pkg.core") == ["1.0.0", "1.1.0"]
