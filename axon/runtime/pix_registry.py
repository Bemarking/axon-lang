"""
PixRegistry — adopter-supplied lookup from `pix_ref` (the symbolic
name used in `drill`/`trail` AXON statements) to a live
:class:`PixNavigator` (Fase 19.b/c).

Architectural decision: the AXON language references PIX trees by
opaque names (e.g. ``drill DocTree into chapters.intro with query``).
The runtime needs to map ``DocTree`` → an actual ``PixNavigator``
instance (which in turn carries the ``DocumentTree`` + ``ScoringFunction``
the adopter wants to use for that tree). This registry is that map.

Defaults: an empty :class:`InMemoryPixRegistry`. Adopters MUST register
their navigators before running flows that contain ``drill``/``trail``
steps — the dispatcher fails loudly with ``AxonRuntimeError`` when a
``pix_ref`` is unknown rather than silently degrading to a stub
(Fase 18.j MVP behavior is removed in 19.b).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from axon.engine.pix.navigator import PixNavigator


class PixRegistry(Protocol):
    """Adopter-supplied ``pix_ref`` → ``PixNavigator`` registry.

    Implementations may be backed by an in-memory dict (default), an
    application config object, or a service locator — whatever fits
    the adopter's deployment.
    """

    def register(self, pix_ref: str, navigator: "PixNavigator") -> None:
        """Bind a navigator to a name. Overwrites any prior binding
        for the same ``pix_ref``."""
        ...

    def get(self, pix_ref: str) -> "PixNavigator | None":
        """Return the navigator for ``pix_ref`` or ``None`` if no
        binding exists."""
        ...

    def has(self, pix_ref: str) -> bool:
        """Return ``True`` iff a navigator is registered under
        ``pix_ref``."""
        ...

    def known_refs(self) -> list[str]:
        """Return all currently-registered ``pix_ref`` names — used by
        the dispatcher to surface a useful error message when an
        unknown ref is referenced."""
        ...


class InMemoryPixRegistry:
    """Thread-safe in-memory implementation of :class:`PixRegistry`.

    Suitable for tests and single-process deployments. Adopters
    needing process-shared registries (rare; navigators usually carry
    process-local LLM clients) can implement the Protocol over a
    different backing store.
    """

    __slots__ = ("_navigators", "_lock")

    def __init__(self) -> None:
        self._navigators: dict[str, "PixNavigator"] = {}
        self._lock = threading.Lock()

    def register(self, pix_ref: str, navigator: "PixNavigator") -> None:
        if not pix_ref:
            raise ValueError("pix_ref must not be empty")
        if navigator is None:
            raise ValueError("navigator must not be None")
        with self._lock:
            self._navigators[pix_ref] = navigator

    def get(self, pix_ref: str) -> "PixNavigator | None":
        if not pix_ref:
            return None
        with self._lock:
            return self._navigators.get(pix_ref)

    def has(self, pix_ref: str) -> bool:
        if not pix_ref:
            return False
        with self._lock:
            return pix_ref in self._navigators

    def known_refs(self) -> list[str]:
        with self._lock:
            return sorted(self._navigators.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._navigators)


__all__ = [
    "InMemoryPixRegistry",
    "PixRegistry",
]
