"""Operational bootstrap for selecting AXON frontend implementations.

This module owns implementation registration and selection policy so the
stable frontend facade can remain focused on contract and delegation.
"""

from __future__ import annotations

import os
from typing import Callable

from .frontend import (
    FrontendImplementation,
    NativeDevelopmentFrontendImplementation,
    NativeFrontendPlaceholder,
    PythonFrontendImplementation,
    get_frontend_implementation,
    set_frontend_implementation,
)


FrontendImplementationFactory = Callable[[], FrontendImplementation]
FRONTEND_IMPLEMENTATION_ENV_VAR = "AXON_FRONTEND_IMPLEMENTATION"

_IMPLEMENTATION_FACTORIES: dict[str, FrontendImplementationFactory] = {
    "python": PythonFrontendImplementation,
    "native-dev": NativeDevelopmentFrontendImplementation,
    "native": NativeFrontendPlaceholder,
}


def list_frontend_implementations() -> tuple[str, ...]:
    """List registered frontend implementation names."""
    return tuple(sorted(_IMPLEMENTATION_FACTORIES))


def register_frontend_implementation(
    name: str,
    factory: FrontendImplementationFactory,
) -> None:
    """Register a frontend implementation factory under a stable name."""
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Frontend implementation name must not be empty")
    _IMPLEMENTATION_FACTORIES[normalized] = factory


def create_frontend_implementation(name: str) -> FrontendImplementation:
    """Create a registered frontend implementation by name."""
    normalized = name.strip().lower()
    try:
        factory = _IMPLEMENTATION_FACTORIES[normalized]
    except KeyError as exc:
        available = ", ".join(list_frontend_implementations())
        raise ValueError(
            f"Unknown frontend implementation '{name}'. Available: {available}"
        ) from exc
    return factory()


def bootstrap_frontend(name: str | None = None) -> FrontendImplementation:
    """Select and activate a frontend implementation by name or environment."""
    selected_name = name or os.getenv(FRONTEND_IMPLEMENTATION_ENV_VAR, "python")
    implementation = create_frontend_implementation(selected_name)
    set_frontend_implementation(implementation)
    return implementation


def current_frontend_selection() -> str | None:
    """Return the registered name for the active implementation when known."""
    active = get_frontend_implementation()
    for name, factory in _IMPLEMENTATION_FACTORIES.items():
        produced = factory()
        if type(active) is type(produced):
            return name
    return None