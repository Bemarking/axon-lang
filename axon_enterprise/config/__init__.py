"""Typed configuration for Axon Enterprise.

Every knob is loaded from environment variables (prefix ``AXON_``) via
``pydantic-settings``. Secrets are wrapped in ``SecretStr`` so they never
surface in ``repr()`` or structured logs.
"""

from axon_enterprise.config.settings import (
    DatabaseSettings,
    EnvelopeBackend,
    EnvelopeSettings,
    Environment,
    IdentitySettings,
    Settings,
    SsoSettings,
    get_settings,
)

__all__ = [
    "DatabaseSettings",
    "EnvelopeBackend",
    "EnvelopeSettings",
    "Environment",
    "IdentitySettings",
    "Settings",
    "SsoSettings",
    "get_settings",
]
