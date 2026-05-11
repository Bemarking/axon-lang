"""
AXON Server — Configuration
=============================
Declarative configuration for AxonServer process.

All fields have safe defaults — ``AxonServerConfig()`` produces a
fully functional in-memory development server on localhost:8420.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.runtime.supervisor import SupervisorConfig


@dataclass
class AxonServerConfig:
    """
    Configuration for the AxonServer process.

    Attributes:
        host:              Bind address (default: 127.0.0.1)
        port:              Listen port (default: 8420 — AXON default)
        channel_backend:   Event channel backend name
                           ("memory" | "kafka" | "rabbitmq" | "eventbridge")
        channel_config:    Backend-specific channel kwargs
        state_backend:     CPS state persistence backend
                           ("memory" | "redis")
        state_config:      Backend-specific state kwargs (e.g. redis_url)
        supervisor:        OTP supervisor configuration
        auth_token:        Bearer token for HTTP API auth (empty = no auth)
        max_daemons:       Maximum concurrent daemons
        log_level:         Python logging level name
        default_backend:   Default LLM backend for compilation
    """
    host: str = "127.0.0.1"
    port: int = 8420
    channel_backend: str = "memory"
    channel_config: dict[str, Any] = field(default_factory=dict)
    state_backend: str = "memory"
    state_config: dict[str, Any] = field(default_factory=dict)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    auth_token: str = ""
    max_daemons: int = 100
    endpoint_max_concurrency: int = 64
    endpoint_queue_timeout_seconds: float = 0.25
    endpoint_request_timeout_seconds: float = 30.0
    endpoint_trace_history_size: int = 500
    endpoint_model: str = "deterministic"
    endpoint_model_provider: str = ""
    endpoint_model_name: str = ""
    endpoint_model_api_key_env: str = ""
    endpoint_model_base_url: str = ""
    endpoint_model_timeout_seconds: float = 30.0
    endpoint_model_strict: bool = False
    endpoint_model_latency_seconds: float = 0.0
    endpoint_model_max_prompt_chars: int = 16000
    endpoint_model_max_response_chars: int = 32000
    endpoint_score_weight_error: float = 1.0
    endpoint_score_weight_latency: float = 1.0
    endpoint_score_weight_volume: float = 1.0
    log_level: str = "INFO"
    default_backend: str = "anthropic"
    # §Fase 31.f (D6 + D7) — Type-Driven Wire Inference activation.
    #
    # When True, `POST /v1/execute` promotes to SSE for any flow the
    # type-checker inferred as stream-producing (D1) regardless of the
    # client's `Accept:` header. Adopters who explicitly declared
    # `transport: json` retain D3 opt-out semantics.
    #
    # The Python CLI accepts the same env var name as the Rust
    # `axon-rs` binary verbatim (`AXON_STRICT_TYPE_DRIVEN_TRANSPORT`)
    # per the D7 cross-stack consistency contract. Truthy values:
    # "1", "true", "yes", "on" (case-insensitive).
    #
    # D6 default: False in v1.22.x, flips to True in v2.0.0 (D9).
    #
    # Note: The Python AxonServer (`axon serve` Python entry point)
    # currently runs the FastAPI/uvicorn stack which does NOT yet
    # ship the SSE negotiation path that the Rust `axon-rs` runtime
    # implements (Fase 30.d/e + Fase 31.d/e are Rust-only). This
    # field is stored on the Python config for cross-stack symmetry
    # — when the Python runtime ports the negotiation path in a
    # future fase, the field is already wired.
    strict_type_driven_transport: bool = False
