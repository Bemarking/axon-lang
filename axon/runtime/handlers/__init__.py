"""
AXON Runtime — Handlers Package
=================================
Public API for the Free Monad interpreters that turn an `IRIntentionTree`
into physical infrastructure.

Concrete handlers (Terraform, Kubernetes, AWS, Docker) are lazy-imported
so that users who don't install the corresponding SDK can still import
`axon.runtime.handlers` without error.

See docs/plan_io_cognitivo.md — Fase 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    BLAME_CALLEE,
    BLAME_CALLER,
    BLAME_INFRASTRUCTURE,
    CalleeBlameError,
    CallerBlameError,
    Continuation,
    Handler,
    HandlerError,
    HandlerOutcome,
    HandlerRegistry,
    HandlerUnavailableError,
    InfrastructureBlameError,
    LambdaEnvelope,
    LeaseExpiredError,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
    now_iso,
)
from .dry_run import DryRunHandler, DryRunState

if TYPE_CHECKING:  # pragma: no cover — typing only
    from .aws import AwsHandler
    from .docker import DockerHandler
    from .grpc import GrpcEndpoint, GrpcHandler
    from .kubernetes import KubernetesHandler
    from .mq import MessageQueueHandler
    from .terraform import TerraformHandler


_LAZY_HANDLERS: dict[str, tuple[str, str]] = {
    "AwsHandler":          ("axon.runtime.handlers.aws",        "AwsHandler"),
    "DockerHandler":       ("axon.runtime.handlers.docker",     "DockerHandler"),
    "GrpcEndpoint":        ("axon.runtime.handlers.grpc",       "GrpcEndpoint"),
    "GrpcHandler":         ("axon.runtime.handlers.grpc",       "GrpcHandler"),
    "KubernetesHandler":   ("axon.runtime.handlers.kubernetes", "KubernetesHandler"),
    "MessageQueueHandler": ("axon.runtime.handlers.mq",         "MessageQueueHandler"),
    "TerraformHandler":    ("axon.runtime.handlers.terraform",  "TerraformHandler"),
}


def __getattr__(name: str):
    """Lazy-import optional handlers so missing SDKs do not break the package."""
    if name in _LAZY_HANDLERS:
        import importlib

        module_path, attr = _LAZY_HANDLERS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module 'axon.runtime.handlers' has no attribute {name!r}")


__all__ = [
    # Base interface
    "BLAME_CALLEE",
    "BLAME_CALLER",
    "BLAME_INFRASTRUCTURE",
    "CalleeBlameError",
    "CallerBlameError",
    "Continuation",
    "Handler",
    "HandlerError",
    "HandlerOutcome",
    "HandlerRegistry",
    "HandlerUnavailableError",
    "InfrastructureBlameError",
    "LambdaEnvelope",
    "LeaseExpiredError",
    "NetworkPartitionError",
    "identity_continuation",
    "make_envelope",
    "now_iso",
    # Deterministic handler (always available)
    "DryRunHandler",
    "DryRunState",
    # Lazy handlers (require optional deps)
    "AwsHandler",
    "DockerHandler",
    "GrpcEndpoint",
    "GrpcHandler",
    "KubernetesHandler",
    "MessageQueueHandler",
    "TerraformHandler",
]
