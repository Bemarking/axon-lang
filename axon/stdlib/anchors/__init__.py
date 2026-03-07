"""
AXON Standard Library — Built-in Anchors
==========================================
12 pre-defined hard constraints: 8 core (spec §8.3) + 4 Logic & Epistemic (Phase 4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from axon.stdlib.anchors.definitions import ALL_ANCHORS

if TYPE_CHECKING:
    from axon.stdlib.base import StdlibRegistry


def register_all(registry: StdlibRegistry) -> None:
    """Register all built-in anchors with the stdlib registry."""
    for anchor in ALL_ANCHORS:
        registry.register("anchors", anchor)


__all__ = ["register_all", "ALL_ANCHORS"]
