"""
AXON Runtime — KubernetesHandler
==================================
Interprets the Intention Tree against a Kubernetes cluster.

The handler uses the official `kubernetes` Python client to materialize
manifests as Deployments (plus Services when a resource exposes an
endpoint).  It mirrors the topology:

    IRResource (kind)   →   Kubernetes primitive
    ─────────────────────────────────────────────
    postgres / redis    →   apps/v1 Deployment + v1 Service
    compute / custom    →   apps/v1 Deployment

Configuration is read from the default kubeconfig file unless the
`KUBECONFIG` env var points elsewhere, or the handler is constructed with
`in_cluster=True` for pod-side execution.

Design anchors:
  • D1 — handler = β-reduction site; no Axon source knows about k8s.
  • D4 — `urllib3`/`kubernetes.client.exceptions.ApiException` with
         connection-class failures is re-raised as `NetworkPartitionError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
    CallerBlameError,
    Continuation,
    Handler,
    HandlerOutcome,
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
)


_KIND_IMAGE: dict[str, str] = {
    "postgres": "postgres:16",
    "redis":    "redis:7",
    "compute":  "alpine:3.20",
    "custom":   "alpine:3.20",
}

_KIND_PORT: dict[str, int] = {
    "postgres": 5432,
    "redis":    6379,
}


@dataclass(frozen=True)
class K8sManifestSpec:
    """Planned Kubernetes objects for a single IRManifest."""
    namespace: str
    deployments: tuple[dict[str, Any], ...]
    services: tuple[dict[str, Any], ...]


def _sanitize_name(name: str) -> str:
    """k8s object names must be lowercase RFC-1123 identifiers."""
    return "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in name.lower()).strip("-") or "axon"


def _deployment_spec(resource: IRResource, namespace: str) -> dict[str, Any]:
    name = _sanitize_name(resource.name)
    image = _KIND_IMAGE.get(resource.kind, "alpine:3.20")
    replicas = 1 if resource.capacity is None else max(1, min(resource.capacity, 10))
    container: dict[str, Any] = {"name": name, "image": image}
    if resource.kind in _KIND_PORT:
        container["ports"] = [{"containerPort": _KIND_PORT[resource.kind]}]
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "axon.io/resource-name": resource.name,
                "axon.io/resource-kind": resource.kind,
                "axon.io/managed-by": "axon",
            },
        },
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {"containers": [container]},
            },
        },
    }


def _service_spec(resource: IRResource, namespace: str) -> dict[str, Any] | None:
    port = _KIND_PORT.get(resource.kind)
    if port is None:
        return None
    name = _sanitize_name(resource.name)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "axon.io/managed-by": "axon",
            },
        },
        "spec": {
            "selector": {"app": name},
            "ports": [{"port": port, "targetPort": port}],
            "type": "ClusterIP",
        },
    }


def plan_manifest(
    manifest: IRManifest,
    resources: dict[str, IRResource],
    fabrics: dict[str, IRFabric],
) -> K8sManifestSpec:
    """Pure planning function — deterministic K8sManifestSpec from IR."""
    fabric = fabrics.get(manifest.fabric_ref) if manifest.fabric_ref else None
    namespace = _sanitize_name(manifest.name) if fabric is None else _sanitize_name(
        fabric.region or manifest.name
    )
    deployments: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    for res_name in manifest.resources:
        resource = resources.get(res_name)
        if resource is None:
            continue
        deployments.append(_deployment_spec(resource, namespace))
        svc = _service_spec(resource, namespace)
        if svc is not None:
            services.append(svc)
    return K8sManifestSpec(
        namespace=namespace,
        deployments=tuple(deployments),
        services=tuple(services),
    )


class KubernetesHandler(Handler):
    """
    Applies plan output to a Kubernetes cluster via the official Python client.

    Parameters
    ----------
    in_cluster : bool
        If True, load config from the pod's service account.  Otherwise
        use the default kubeconfig (or whatever `KUBECONFIG` points to).
    dry_run : bool
        If True, objects are validated but not persisted (server-side
        dry run).  Useful in CI.
    """

    name: str = "kubernetes"

    def __init__(self, *, in_cluster: bool = False, dry_run: bool = False) -> None:
        try:
            from kubernetes import client, config  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "kubernetes client not installed. "
                "Install with `pip install axon-lang[kubernetes]` or "
                "`pip install kubernetes`."
            ) from exc

        self._client_mod = client
        try:
            if in_cluster:
                config.load_incluster_config()
            else:
                config.load_kube_config()
        except Exception as exc:  # noqa: BLE001
            raise InfrastructureBlameError(
                f"failed to load kubeconfig: {exc}"
            ) from exc

        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()
        self.dry_run = dry_run

    # ── Handler protocol ──────────────────────────────────────────

    def supports(self, node: IRNode) -> bool:
        return isinstance(node, (IRManifest, IRObserve))

    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        plan = plan_manifest(manifest, resources, fabrics)
        self._ensure_namespace(plan.namespace)
        applied_deployments: list[str] = []
        applied_services: list[str] = []

        dry_run_flag = ["All"] if self.dry_run else None

        for dep in plan.deployments:
            self._apply(
                kind="Deployment",
                namespace=plan.namespace,
                name=dep["metadata"]["name"],
                spec=dep,
                create=lambda body, ns=plan.namespace: self.apps.create_namespaced_deployment(
                    ns, body, dry_run=dry_run_flag
                ),
                replace=lambda body, ns=plan.namespace, nm=dep["metadata"]["name"]:
                    self.apps.replace_namespaced_deployment(nm, ns, body, dry_run=dry_run_flag),
                read=lambda ns=plan.namespace, nm=dep["metadata"]["name"]:
                    self.apps.read_namespaced_deployment(nm, ns),
            )
            applied_deployments.append(dep["metadata"]["name"])

        for svc in plan.services:
            self._apply(
                kind="Service",
                namespace=plan.namespace,
                name=svc["metadata"]["name"],
                spec=svc,
                create=lambda body, ns=plan.namespace: self.core.create_namespaced_service(
                    ns, body, dry_run=dry_run_flag
                ),
                replace=lambda body, ns=plan.namespace, nm=svc["metadata"]["name"]:
                    self.core.replace_namespaced_service(nm, ns, body, dry_run=dry_run_flag),
                read=lambda ns=plan.namespace, nm=svc["metadata"]["name"]:
                    self.core.read_namespaced_service(nm, ns),
            )
            applied_services.append(svc["metadata"]["name"])

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok" if not self.dry_run else "partial",
            envelope=make_envelope(c=0.96, rho=self.name, delta="observed"),
            data={
                "namespace": plan.namespace,
                "deployments": applied_deployments,
                "services": applied_services,
                "dry_run": self.dry_run,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        namespace = _sanitize_name(manifest.name)
        try:
            deployments = self.apps.list_namespaced_deployment(
                namespace,
                label_selector="axon.io/managed-by=axon",
            )
        except Exception as exc:  # noqa: BLE001
            raise self._classify_exception(exc) from exc

        snapshots = []
        ready_count = 0
        for dep in deployments.items:
            status = dep.status
            ready = (status.ready_replicas or 0) if status else 0
            desired = (status.replicas or 0) if status else 0
            if ready == desired and desired > 0:
                ready_count += 1
            snapshots.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "ready_replicas": ready,
                "replicas": desired,
            })

        total = len(snapshots) or 1
        certainty = min(1.0, ready_count / total + 0.05)
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=certainty, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "namespace": namespace,
                "sources": list(obs.sources),
                "deployments": snapshots,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        # The python kubernetes client uses urllib3 connection pools that
        # are cleaned up by garbage collection; nothing explicit to do.
        return None

    # ── Internals ─────────────────────────────────────────────────

    def _ensure_namespace(self, namespace: str) -> None:
        try:
            self.core.read_namespace(namespace)
        except Exception as exc:  # noqa: BLE001
            classified = self._classify_exception(exc)
            if isinstance(classified, NetworkPartitionError):
                raise classified from exc
            # Not-found → create.  Any other API failure is CT-3.
            body = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
            try:
                self.core.create_namespace(body)
            except Exception as create_exc:  # noqa: BLE001
                # If the namespace already exists due to a race, silently
                # continue; otherwise re-raise.
                if self._is_already_exists(create_exc):
                    return
                raise self._classify_exception(create_exc) from create_exc

    def _apply(
        self,
        *,
        kind: str,
        namespace: str,
        name: str,
        spec: dict[str, Any],
        create,
        replace,
        read,
    ) -> None:
        try:
            read()
            exists = True
        except Exception as exc:  # noqa: BLE001
            if not self._is_not_found(exc):
                raise self._classify_exception(exc) from exc
            exists = False

        try:
            if exists:
                replace(spec)
            else:
                create(spec)
        except Exception as exc:  # noqa: BLE001
            raise self._classify_exception(exc) from exc

    def _classify_exception(self, exc: Exception) -> Exception:
        msg = str(exc)
        lowered = msg.lower()
        if any(m in lowered for m in ("connection refused", "timed out", "unreachable", "no route to host")):
            return NetworkPartitionError(f"kubernetes API partition: {msg}")
        if self._is_already_exists(exc):
            return CallerBlameError(f"kubernetes conflict: {msg}")
        if self._status_code(exc) in (401, 403):
            return InfrastructureBlameError(f"kubernetes auth failure: {msg}")
        return InfrastructureBlameError(f"kubernetes API error: {msg}")

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        return getattr(exc, "status", None)

    @classmethod
    def _is_not_found(cls, exc: Exception) -> bool:
        return cls._status_code(exc) == 404

    @classmethod
    def _is_already_exists(cls, exc: Exception) -> bool:
        return cls._status_code(exc) == 409


__all__ = [
    "K8sManifestSpec",
    "KubernetesHandler",
    "plan_manifest",
]
