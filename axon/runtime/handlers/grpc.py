"""
AXON Runtime — GrpcHandler
=============================
Free-Monad handler (Fase 2) that delegates `provision` and `observe`
to a gRPC service exposing a thin Axon-native API.

Motivation
----------
Many enterprise platforms expose provisioning control planes as gRPC
services (Kubernetes CRDs, Crossplane, Terraform Cloud).  Axon can
consume these uniformly via a small proto contract the adopter
implements on their side:

    service AxonProvisioner {
        rpc Provision (ProvisionRequest) returns (ProvisionResponse);
        rpc Observe   (ObserveRequest)   returns (ObserveResponse);
    }

The handler serializes the IR manifest/observe to a JSON string
(already canonical via ESK's ``canonical_bytes``) and ships it as the
proto payload; the response is parsed back into a HandlerOutcome.

This gives Axon a **language-level RPC protocol** for infrastructure
control that is broker-agnostic — adopters on gRPC, grpc-web, Connect,
or Twirp can all plug in by implementing the same two RPCs.

The handler lazy-imports ``grpcio``; without it, instantiation raises
``HandlerUnavailableError``.  A dynamically-generated service stub is
used so that the Axon package ships no compiled .proto artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass
class GrpcEndpoint:
    """Configuration for a gRPC AxonProvisioner target."""
    address: str                   # e.g. "provisioner.internal:50051"
    use_tls: bool = False
    root_certs: bytes | None = None
    private_key: bytes | None = None
    cert_chain: bytes | None = None
    timeout_seconds: float = 30.0


class GrpcHandler(Handler):
    """
    Handler that calls a remote AxonProvisioner gRPC service.

    Parameters
    ----------
    endpoint : GrpcEndpoint
        Address + TLS configuration of the remote provisioner.
    proto_module : Any | None
        Optional pre-generated protobuf stubs.  If None, the handler
        uses the generic-channel API (``channel.unary_unary``) which
        requires the caller to serialize to bytes upstream.
    """

    name: str = "grpc"

    def __init__(
        self,
        endpoint: GrpcEndpoint,
        *,
        proto_module: Any | None = None,
    ) -> None:
        try:
            import grpc  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "GrpcHandler requires 'grpcio'. "
                "Install with `pip install axon-lang[grpc]`."
            ) from exc
        self._grpc = grpc
        self.endpoint = endpoint
        self._proto_module = proto_module
        self._channel = self._build_channel()

    def _build_channel(self):
        grpc = self._grpc
        if self.endpoint.use_tls:
            credentials = grpc.ssl_channel_credentials(
                root_certificates=self.endpoint.root_certs,
                private_key=self.endpoint.private_key,
                certificate_chain=self.endpoint.cert_chain,
            )
            return grpc.secure_channel(self.endpoint.address, credentials)
        return grpc.insecure_channel(self.endpoint.address)

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
        payload = {
            "operation": "provision",
            "manifest": manifest.name,
            "resources": list(manifest.resources),
            "compliance": list(manifest.compliance),
            "region": manifest.region,
            "zones": manifest.zones,
        }
        response = self._call("/axon.Provisioner/Provision", payload)
        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status=response.get("status", "ok"),
            envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "remote_response": response,
                "endpoint": self.endpoint.address,
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
        payload = {
            "operation": "observe",
            "observe": obs.name,
            "manifest": manifest.name,
            "sources": list(obs.sources),
            "quorum": obs.quorum,
            "on_partition": obs.on_partition,
        }
        response = self._call("/axon.Provisioner/Observe", payload)
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status=response.get("status", "ok"),
            envelope=make_envelope(c=0.92, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "remote_response": response,
                "endpoint": self.endpoint.address,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        try:
            self._channel.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Internals ─────────────────────────────────────────────────

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Generic unary RPC: send JSON bytes, receive JSON bytes.

        The remote service is expected to deserialize `payload` as JSON
        and respond with JSON-encoded bytes.  This avoids shipping
        pre-compiled protobuf stubs with the Axon package.
        """
        grpc = self._grpc
        try:
            stub = self._channel.unary_unary(
                method,
                request_serializer=lambda x: x,
                response_deserializer=lambda x: x,
            )
            request_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
            response_bytes = stub(request_bytes, timeout=self.endpoint.timeout_seconds)
            return json.loads(response_bytes.decode("utf-8"))
        except grpc.RpcError as exc:
            status_code = exc.code() if hasattr(exc, "code") else None
            code_name = status_code.name if status_code else "UNKNOWN"
            # UNAVAILABLE / DEADLINE_EXCEEDED map to CT-3 partition.
            if code_name in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
                raise NetworkPartitionError(
                    f"gRPC {method} unreachable at '{self.endpoint.address}': {exc}"
                ) from exc
            raise InfrastructureBlameError(
                f"gRPC {method} failed ({code_name}) at '{self.endpoint.address}': {exc}"
            ) from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InfrastructureBlameError(
                f"gRPC {method} returned malformed response: {exc}"
            ) from exc


__all__ = ["GrpcEndpoint", "GrpcHandler"]
