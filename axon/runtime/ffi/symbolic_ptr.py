"""
AXON Runtime — SymbolicPtr[T] (§λ-L-E Fase 11.b).

A thin copyable handle to a resource that lives elsewhere. Clone is
O(1); the handle NEVER materialises the underlying bytes — callers
must go through the :meth:`deref` method (or one of the specialised
accessors) to actually touch the data.

The design mirrors a ``std::sync::Arc`` on the Rust side. In Python
we use strong references plus a ``threading.Lock``-guarded refcount
view for observability. The pointed-to resource is kept alive by
ordinary Python refcounting; :class:`SymbolicPtr` is a marker, not a
garbage-collection primitive.

Typical usage::

    buf = ZeroCopyBuffer(data, BufferKind.pcm16())
    ptr = SymbolicPtr(buf)

    # Fan-out to two consumers without copying.
    a = ptr.clone()
    b = ptr.clone()

    # Consumer A still has zero-copy access.
    mv = a.deref().as_memoryview()

The :class:`SymbolicPtr` itself is intentionally light — no
instrumentation at the hot path, observability surfaced via the
``refcount`` property for dashboards and a ``weakref`` hook so
adopters can wire their own tracing on drop.
"""

from __future__ import annotations

import threading
import weakref
from typing import Generic, TypeVar

T = TypeVar("T")


class SymbolicPtr(Generic[T]):
    """Shared handle over a payload. Copy-on-clone, read-on-deref."""

    # `__weakref__` slot lets :func:`weakref.finalize` attach a
    # finalizer to each instance so refcounts decrement on drop.
    __slots__ = ("_resource", "_live_clones", "_lock", "__weakref__")

    def __init__(self, resource: T) -> None:
        self._resource: T = resource
        # Shared mutable counter across all clones; tracks how many
        # live :class:`SymbolicPtr` instances currently reference the
        # same resource. Started at 1 for the constructing instance.
        self._live_clones: list[int] = [1]
        self._lock: threading.RLock = threading.RLock()
        # Register a finalizer that decrements the counter when the
        # pointer is garbage-collected; adopters can subscribe via
        # ``weakref.finalize`` on the resource itself for drop hooks.
        weakref.finalize(self, _decrement, self._lock, self._live_clones)

    @classmethod
    def _view(
        cls,
        resource: T,
        live_clones: list[int],
        lock: threading.RLock,
    ) -> "SymbolicPtr[T]":
        inst = cls.__new__(cls)
        inst._resource = resource
        inst._live_clones = live_clones
        inst._lock = lock
        weakref.finalize(inst, _decrement, lock, live_clones)
        return inst

    def clone(self) -> "SymbolicPtr[T]":
        """Return a new handle over the same resource. O(1)."""
        with self._lock:
            self._live_clones[0] += 1
        return SymbolicPtr._view(self._resource, self._live_clones, self._lock)

    def deref(self) -> T:
        """Access the pointed-to resource. Does NOT copy; callers that
        need to detach from the shared carrier do so via the resource's
        own API (e.g. :meth:`ZeroCopyBuffer.as_bytes`)."""
        return self._resource

    @property
    def refcount(self) -> int:
        """Current live-clone count. Snapshot only; don't rely on it
        for flow control."""
        with self._lock:
            return self._live_clones[0]

    @property
    def is_unique(self) -> bool:
        """Useful for hand-off optimisations: if no one else holds a
        clone, the caller can safely mutate via a fresh copy."""
        return self.refcount == 1

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"SymbolicPtr({type(self._resource).__name__}, "
            f"refcount={self.refcount})"
        )


def _decrement(lock: threading.RLock, counter: list[int]) -> None:
    """Finalizer shared by every clone of the same resource."""
    with lock:
        if counter[0] > 0:
            counter[0] -= 1


__all__ = ["SymbolicPtr"]
