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
    log_level: str = "INFO"
    default_backend: str = "anthropic"
