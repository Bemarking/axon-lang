"""
AXON APX - Package Infrastructure and Registry (Phase 4)

Implements package-level infrastructure for APX:
- immutable package registration (ECID-bound)
- PCC verification at admission time
- epistemic version DAG (Epi-Ver)
- incremental resolution cache with generation invalidation
- EPR-driven quarantine controls
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from time import time
from typing import Any

from axon.engine.apx.epr import EpistemicPageRank
from axon.engine.apx.graph import EdgeKind, EpistemicContract, EpistemicEdge, EpistemicGraph, EpistemicNode
from axon.engine.apx.lattice import EpistemicLevel
from axon.engine.apx.observability import APXCompliancePolicy, APXEventType, APXObservability


class APXRegistryError(Exception):
    """Base error for APX registry operations."""


class APXDecision(str, Enum):
    RESOLVED = "resolved"
    WARNED = "warned"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class APXDependency:
    package_id: str
    version: str
    edge_kind: EdgeKind = EdgeKind.DEPENDS_ON
    weight: float = 1.0


@dataclass(frozen=True)
class APXPackageManifest:
    package_id: str
    version: str
    level: EpistemicLevel
    ecid: str
    certificate_hash: str
    witnesses: tuple[str, ...] = ()
    dependencies: tuple[APXDependency, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def key(self) -> str:
        return f"{self.package_id}@{self.version}"

    def validate_mec(self) -> None:
        if not self.package_id or not self.version:
            raise APXRegistryError("package_id/version cannot be empty")
        if not self.ecid:
            raise APXRegistryError("MEC violation: missing ECID")
        if not self.certificate_hash:
            raise APXRegistryError("MEC violation: missing certificate hash")
        if len(self.witnesses) == 0:
            raise APXRegistryError("MEC violation: at least one witness is required")


@dataclass(frozen=True)
class APXPackageRecord:
    manifest: APXPackageManifest
    source_hash: str
    registered_at: float
    parent_versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class APXResolutionResult:
    package_key: str
    score: float
    decision: APXDecision
    warnings: tuple[str, ...] = ()
    cache_hit: bool = False


class APXRegistry:
    """Immutable package registry with epistemic ranking and quarantine."""

    def __init__(self, observability: APXObservability | None = None) -> None:
        self._records: dict[str, APXPackageRecord] = {}
        self._version_parents: dict[str, set[str]] = {}
        self._quarantined: set[str] = set()
        self._cache_generation: int = 0
        self._resolution_cache: dict[tuple[str, float, str, int], APXResolutionResult] = {}
        self._ranking = EpistemicPageRank()
        self.observability = observability or APXObservability(component="apx.registry")

    @property
    def package_count(self) -> int:
        return len(self._records)

    @property
    def generation(self) -> int:
        return self._cache_generation

    def compliance_report(self) -> dict[str, Any]:
        """Return current registry compliance report."""
        return self.observability.compliance_report()

    def assert_compliance(self, policy: APXCompliancePolicy | None = None) -> None:
        """Raise if registry compliance gates are violated."""
        self.observability.assert_compliance(policy)

    def register(
        self,
        manifest: APXPackageManifest,
        source_hash: str,
        pcc_hash: str,
        parent_versions: tuple[str, ...] = (),
    ) -> APXPackageRecord:
        """Register an immutable package node after MEC/PCC checks."""
        with self.observability.track("register"):
            manifest.validate_mec()
            if not source_hash:
                raise APXRegistryError("source_hash cannot be empty")

            pcc_ok = pcc_hash == manifest.certificate_hash
            self.observability.emit(
                APXEventType.PCC_VERIFICATION,
                operation="register",
                status="ok" if pcc_ok else "failed",
                package_key=manifest.key(),
            )
            if not pcc_ok:
                raise APXRegistryError("PCC verification failed")

            key = manifest.key()
            if key in self._records:
                raise APXRegistryError(f"immutable node violation: '{key}' already registered")

            rec = APXPackageRecord(
                manifest=manifest,
                source_hash=source_hash,
                registered_at=time(),
                parent_versions=parent_versions,
            )
            self._records[key] = rec
            self._version_parents[key] = set(parent_versions)

            self._validate_version_dag_acyclic()
            self._bump_generation()
            self.observability.emit(
                APXEventType.REGISTRY_REGISTER,
                operation="register",
                status="ok",
                package_key=key,
                generation=self._cache_generation,
            )
            return rec

    def get(self, package_id: str, version: str) -> APXPackageRecord | None:
        return self._records.get(f"{package_id}@{version}")

    def list_versions(self, package_id: str) -> list[str]:
        versions: list[str] = []
        prefix = f"{package_id}@"
        for key in self._records:
            if key.startswith(prefix):
                versions.append(key[len(prefix):])
        return sorted(versions)

    def verify_pcc(self, package_id: str, version: str, pcc_hash: str) -> bool:
        rec = self.get(package_id, version)
        if rec is None:
            return False
        return rec.manifest.certificate_hash == pcc_hash

    def build_epistemic_graph(self, include_quarantined: bool = False) -> EpistemicGraph:
        graph = EpistemicGraph("apx-registry")

        for key, rec in self._records.items():
            if not include_quarantined and key in self._quarantined:
                continue
            contract = EpistemicContract(
                ecid=rec.manifest.ecid,
                certificate_hash=rec.manifest.certificate_hash,
                witness_count=len(rec.manifest.witnesses),
            )
            graph.add_node(
                EpistemicNode(
                    package_id=key,
                    level=rec.manifest.level,
                    contract=contract,
                )
            )

        for key, rec in self._records.items():
            if key not in graph.node_ids():
                continue
            for dep in rec.manifest.dependencies:
                dep_key = f"{dep.package_id}@{dep.version}"
                if dep_key not in graph.node_ids():
                    continue
                graph.add_edge(
                    EpistemicEdge(
                        source_id=key,
                        target_id=dep_key,
                        kind=dep.edge_kind,
                        weight=dep.weight,
                    )
                )

        errors = graph.validate_all()
        if errors:
            raise APXRegistryError("invalid registry graph: " + "; ".join(errors))

        return graph

    def rank_packages(self, include_quarantined: bool = False) -> dict[str, float]:
        graph = self.build_epistemic_graph(include_quarantined=include_quarantined)
        return self._ranking.compute(graph)

    def quarantine_below(self, threshold: float) -> list[str]:
        if not (0.0 <= threshold <= 1.0):
            raise APXRegistryError("threshold must be in [0,1]")

        scores = self.rank_packages(include_quarantined=True)
        affected: list[str] = []
        for key, score in scores.items():
            if score <= threshold and key not in self._quarantined:
                self._quarantined.add(key)
                affected.append(key)

        if affected:
            self._bump_generation()
            for key in affected:
                self.observability.emit(
                    APXEventType.QUARANTINE_ACTION,
                    operation="quarantine_below",
                    status="ok",
                    package_key=key,
                    threshold=threshold,
                )
        return sorted(affected)

    def clear_quarantine(self, package_key: str) -> None:
        if package_key in self._quarantined:
            self._quarantined.remove(package_key)
            self._bump_generation()

    def is_quarantined(self, package_id: str, version: str) -> bool:
        return f"{package_id}@{version}" in self._quarantined

    def resolve(
        self,
        package_id: str,
        version: str,
        min_epr: float = 0.0,
        on_low_rank: str = "warn",
        use_cache: bool = True,
    ) -> APXResolutionResult:
        with self.observability.track("resolve"):
            key = f"{package_id}@{version}"
            if key not in self._records:
                raise APXRegistryError(f"package not found: {key}")

            action = on_low_rank.lower()
            if action not in {"warn", "quarantine", "block"}:
                raise APXRegistryError("on_low_rank must be warn|quarantine|block")

            cache_key = (key, float(min_epr), action, self._cache_generation)
            if use_cache and cache_key in self._resolution_cache:
                cached = self._resolution_cache[cache_key]
                result = APXResolutionResult(
                    package_key=cached.package_key,
                    score=cached.score,
                    decision=cached.decision,
                    warnings=cached.warnings,
                    cache_hit=True,
                )
                self.observability.emit(
                    APXEventType.REGISTRY_RESOLVE,
                    operation="resolve",
                    status="ok",
                    package_key=key,
                    decision=result.decision.value,
                    cache_hit=True,
                )
                return result

            if self.is_quarantined(package_id, version):
                result = APXResolutionResult(
                    package_key=key,
                    score=0.0,
                    decision=APXDecision.QUARANTINED,
                    warnings=("package is quarantined",),
                    cache_hit=False,
                )
                self._resolution_cache[cache_key] = result
                self.observability.emit(
                    APXEventType.REGISTRY_RESOLVE,
                    operation="resolve",
                    status="ok",
                    package_key=key,
                    decision=result.decision.value,
                    cache_hit=False,
                )
                return result

            scores = self.rank_packages(include_quarantined=True)
            score = scores.get(key, 0.0)

            if score < min_epr:
                if action == "warn":
                    result = APXResolutionResult(
                        package_key=key,
                        score=score,
                        decision=APXDecision.WARNED,
                        warnings=(f"low EPR score {score:.4f}",),
                        cache_hit=False,
                    )
                elif action == "quarantine":
                    self._quarantined.add(key)
                    self._bump_generation()
                    self.observability.emit(
                        APXEventType.QUARANTINE_ACTION,
                        operation="resolve",
                        status="ok",
                        package_key=key,
                        threshold=min_epr,
                    )
                    result = APXResolutionResult(
                        package_key=key,
                        score=score,
                        decision=APXDecision.QUARANTINED,
                        warnings=(f"low EPR score {score:.4f}",),
                        cache_hit=False,
                    )
                else:
                    result = APXResolutionResult(
                        package_key=key,
                        score=score,
                        decision=APXDecision.BLOCKED,
                        warnings=(f"low EPR score {score:.4f}",),
                        cache_hit=False,
                    )
            else:
                result = APXResolutionResult(
                    package_key=key,
                    score=score,
                    decision=APXDecision.RESOLVED,
                    warnings=(),
                    cache_hit=False,
                )

            # store cache using fresh generation after potential bump
            cache_key = (key, float(min_epr), action, self._cache_generation)
            self._resolution_cache[cache_key] = result
            self.observability.emit(
                APXEventType.REGISTRY_RESOLVE,
                operation="resolve",
                status="ok",
                package_key=key,
                decision=result.decision.value,
                cache_hit=False,
            )
            return result

    @staticmethod
    def compute_ecid(package_id: str, version: str, source_hash: str, certificate_hash: str) -> str:
        raw = f"{package_id}|{version}|{source_hash}|{certificate_hash}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _bump_generation(self) -> None:
        self._cache_generation += 1
        # incremental invalidation by generation key; old cache can stay allocated

    def _validate_version_dag_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise APXRegistryError(f"Epi-Ver DAG cycle detected at '{node}'")
            if node in visited:
                return
            visiting.add(node)
            for parent in self._version_parents.get(node, set()):
                if parent not in self._version_parents:
                    continue
                dfs(parent)
            visiting.remove(node)
            visited.add(node)

        for key in self._version_parents:
            dfs(key)
