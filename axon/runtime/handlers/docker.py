"""
AXON Runtime — DockerHandler
==============================
Interprets the Intention Tree against a local Docker / Podman daemon.

Provisions each IRResource as a container with deterministic naming.
Observations report container status + health; missing containers
translate to `doubt`-class certainty, not exceptions, because a stopped
container is still observed state — only an unreachable daemon raises
`NetworkPartitionError` per Decision D4.

Resource mapping:
    postgres → postgres:16      port 5432
    redis    → redis:7          port 6379
    compute  → alpine:3.20      (sleep container for placeholder)
    custom   → alpine:3.20      (noop)
"""

from __future__ import annotations

from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
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

_KIND_ENV: dict[str, dict[str, str]] = {
    "postgres": {"POSTGRES_PASSWORD": "axon"},
}

_KIND_CMD: dict[str, list[str]] = {
    "compute": ["sleep", "infinity"],
    "custom":  ["sleep", "infinity"],
}


def _container_name(resource_name: str, manifest_name: str) -> str:
    safe_r = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in resource_name).strip("-_").lower() or "resource"
    safe_m = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in manifest_name).strip("-_").lower() or "manifest"
    return f"axon-{safe_m}-{safe_r}"


class DockerHandler(Handler):
    """
    Local container provisioner using the `docker` Python SDK.

    Parameters
    ----------
    base_url : str | None
        Docker daemon URL.  `None` falls back to the SDK's default (honours
        `DOCKER_HOST`).  Pass e.g. "unix:///run/podman/podman.sock" for Podman.
    network : str
        Name of a pre-existing Docker network to attach containers to.
        The handler never creates networks — that is a fabric-level concern.
    """

    name: str = "docker"

    def __init__(self, *, base_url: str | None = None, network: str = "bridge") -> None:
        try:
            import docker  # type: ignore[import-not-found]
            from docker import errors as docker_errors  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "docker Python SDK not installed. "
                "Install with `pip install axon-lang[docker]` or `pip install docker`."
            ) from exc

        try:
            self._client = docker.DockerClient(base_url=base_url) if base_url else docker.from_env()
            # Ping eagerly so we fail fast with a clear CT-3 if the daemon
            # is unreachable (rather than failing on first provision call).
            self._client.ping()
        except docker_errors.DockerException as exc:
            raise NetworkPartitionError(
                f"unable to reach Docker daemon: {exc}"
            ) from exc

        self._docker = docker
        self._docker_errors = docker_errors
        self.network = network

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
        started: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            resource = resources.get(res_name)
            if resource is None:
                continue
            record = self._run_container(resource, manifest.name)
            started.append(record)

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=0.98, rho=self.name, delta="observed"),
            data={"manifest": manifest.name, "containers": started},
            handler=self.name,
        )
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        snapshots: list[dict[str, Any]] = []
        running = 0
        for res_name in manifest.resources:
            container_name = _container_name(res_name, manifest.name)
            snap = self._inspect_container(container_name, res_name)
            snapshots.append(snap)
            if snap["status"] == "running":
                running += 1

        total = len(snapshots) or 1
        certainty = min(1.0, running / total + 0.05)
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=certainty, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "sources": list(obs.sources),
                "containers": snapshots,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Internals ─────────────────────────────────────────────────

    def _run_container(self, resource: IRResource, manifest_name: str) -> dict[str, Any]:
        name = _container_name(resource.name, manifest_name)
        image = _KIND_IMAGE.get(resource.kind, "alpine:3.20")
        ports: dict[str, int] | None = None
        if resource.kind in _KIND_PORT:
            ports = {f"{_KIND_PORT[resource.kind]}/tcp": _KIND_PORT[resource.kind]}
        env = _KIND_ENV.get(resource.kind, {})
        cmd = _KIND_CMD.get(resource.kind)

        try:
            self._ensure_image(image)
            # Remove any previous container with the same name to make the
            # provision operation idempotent.  This preserves Linear Logic
            # semantics at the handler layer: the new token replaces the old.
            try:
                existing = self._client.containers.get(name)
                existing.remove(force=True)
            except self._docker_errors.NotFound:
                pass

            container = self._client.containers.run(
                image=image,
                name=name,
                detach=True,
                network=self.network,
                environment=env or None,
                ports=ports,
                command=cmd,
                labels={
                    "axon.managed-by": "axon",
                    "axon.resource-name": resource.name,
                    "axon.resource-kind": resource.kind,
                    "axon.manifest": manifest_name,
                },
            )
            return {
                "name": resource.name,
                "container_name": name,
                "container_id": container.id[:12],
                "image": image,
                "kind": resource.kind,
                "status": "running",
            }
        except self._docker_errors.ImageNotFound as exc:
            raise InfrastructureBlameError(
                f"image '{image}' not found: {exc}"
            ) from exc
        except self._docker_errors.APIError as exc:
            raise InfrastructureBlameError(
                f"docker API error running '{name}': {exc}"
            ) from exc
        except self._docker_errors.DockerException as exc:
            raise NetworkPartitionError(
                f"docker daemon lost while running '{name}': {exc}"
            ) from exc

    def _inspect_container(self, container_name: str, resource_name: str) -> dict[str, Any]:
        try:
            container = self._client.containers.get(container_name)
        except self._docker_errors.NotFound:
            return {
                "name": resource_name,
                "container_name": container_name,
                "status": "missing",
            }
        except self._docker_errors.APIError as exc:
            raise InfrastructureBlameError(
                f"docker API error inspecting '{container_name}': {exc}"
            ) from exc
        except self._docker_errors.DockerException as exc:
            raise NetworkPartitionError(
                f"docker daemon lost while inspecting '{container_name}': {exc}"
            ) from exc

        state = container.attrs.get("State", {})
        return {
            "name": resource_name,
            "container_name": container_name,
            "container_id": container.id[:12],
            "status": state.get("Status", "unknown"),
            "health": state.get("Health", {}).get("Status", ""),
            "started_at": state.get("StartedAt", ""),
        }

    def _ensure_image(self, image: str) -> None:
        try:
            self._client.images.get(image)
        except self._docker_errors.ImageNotFound:
            try:
                self._client.images.pull(image)
            except self._docker_errors.APIError as exc:
                raise InfrastructureBlameError(
                    f"failed to pull image '{image}': {exc}"
                ) from exc


__all__ = ["DockerHandler"]
