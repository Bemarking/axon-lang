"""
AXON Runtime — Zero-Copy Multimodal Buffers (§λ-L-E Fase 11.b).

Python reference implementation of the Rust ``axon::buffer`` module.
Design mirror is load-bearing: a flow that produces a
:class:`ZeroCopyBuffer` in Python and consumes it in Rust (or vice
versa) MUST see the same bytes, the same kind tag, and the same
slice semantics.

Storage model
-------------
The Python side wraps the bytes in :class:`memoryview` — the built-in
zero-copy buffer view. A :class:`ZeroCopyBuffer` owns a strong
reference to an immutable bytes-like carrier (``bytes`` or a frozen
``bytearray``) and exposes slices as new :class:`ZeroCopyBuffer`
instances that share the carrier.

When an adopter eventually compiles ``axon-rs`` as a PyO3 extension
and needs Python to hand Rust-owned memory back across the FFI, the
same :class:`ZeroCopyBuffer` interface applies — the backing
memoryview will expose a ``PyBUF_SIMPLE`` buffer sourced from the
Arc-held Rust slice. The interface is unchanged; the carrier is.
"""

from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Iterable,
    Optional,
    Union,
)


# ── BufferKind ────────────────────────────────────────────────────────


_SEEDED_KINDS: tuple[str, ...] = (
    "raw",
    "pcm16",
    "mulaw8",
    "wav",
    "mp3",
    "opus",
    "jpeg",
    "png",
    "webp",
    "mp4",
    "webm",
    "pdf",
    "json",
    "csv",
)


class BufferKindRegistry:
    """Interning registry for :class:`BufferKind` slugs.

    Mirror of ``axon::buffer::BufferKindRegistry``. The registry is
    open: adopters register new kinds at startup and the tag flows
    through ``BufferKind.slug``. Seeded with the same set as the
    Rust side so cross-language flows see identical defaults.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._slugs: dict[str, str] = {}
        for seeded in _SEEDED_KINDS:
            self._slugs[seeded] = seeded

    def intern(self, slug: str) -> str:
        """Return the canonical string instance for ``slug``.

        The canonical instance is the first string passed in for
        that slug; subsequent :meth:`intern` calls return the same
        object so identity comparison works as a fast-path equality
        test.
        """
        with self._lock:
            existing = self._slugs.get(slug)
            if existing is not None:
                return existing
            self._slugs[slug] = slug
            return slug

    def known_slugs(self) -> list[str]:
        with self._lock:
            return sorted(self._slugs.keys())


_GLOBAL_REGISTRY = BufferKindRegistry()


def global_kind_registry() -> BufferKindRegistry:
    """Return the process-wide registry (seeded with the common kinds)."""
    return _GLOBAL_REGISTRY


class BufferKind:
    """Interned content-kind tag, equality by slug."""

    __slots__ = ("_slug",)

    def __init__(self, slug: str) -> None:
        self._slug = _GLOBAL_REGISTRY.intern(slug)

    @property
    def slug(self) -> str:
        return self._slug

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BufferKind) and other._slug == self._slug

    def __hash__(self) -> int:
        return hash(self._slug)

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"BufferKind({self._slug!r})"

    def __str__(self) -> str:  # pragma: no cover — trivial
        return self._slug

    # ── Seeded constructors ────────────────────────────────────

    @classmethod
    def raw(cls) -> "BufferKind":
        return cls("raw")

    @classmethod
    def pcm16(cls) -> "BufferKind":
        return cls("pcm16")

    @classmethod
    def mulaw8(cls) -> "BufferKind":
        return cls("mulaw8")

    @classmethod
    def wav(cls) -> "BufferKind":
        return cls("wav")

    @classmethod
    def mp3(cls) -> "BufferKind":
        return cls("mp3")

    @classmethod
    def opus(cls) -> "BufferKind":
        return cls("opus")

    @classmethod
    def jpeg(cls) -> "BufferKind":
        return cls("jpeg")

    @classmethod
    def png(cls) -> "BufferKind":
        return cls("png")

    @classmethod
    def webp(cls) -> "BufferKind":
        return cls("webp")

    @classmethod
    def mp4(cls) -> "BufferKind":
        return cls("mp4")

    @classmethod
    def webm(cls) -> "BufferKind":
        return cls("webm")

    @classmethod
    def pdf(cls) -> "BufferKind":
        return cls("pdf")

    @classmethod
    def json(cls) -> "BufferKind":
        return cls("json")

    @classmethod
    def csv(cls) -> "BufferKind":
        return cls("csv")


# ── ZeroCopyBuffer ────────────────────────────────────────────────────


BytesLike = Union[bytes, bytearray, memoryview]


class ZeroCopyBuffer:
    """Immutable view over a bytes-like carrier.

    Semantics match ``axon::buffer::ZeroCopyBuffer`` in Rust: clone
    is O(1), :meth:`slice` shares the carrier, :meth:`retag` returns
    a new buffer that shares the carrier with a different kind.
    """

    __slots__ = ("_carrier", "_start", "_end", "_kind", "_tenant_id")

    def __init__(
        self,
        data: BytesLike,
        kind: BufferKind | str = "raw",
        *,
        tenant_id: Optional[str] = None,
    ) -> None:
        # Normalise the carrier to `bytes`. `bytes` is immutable so
        # memoryview over it is safe to expose to multiple consumers.
        if isinstance(data, (bytearray, memoryview)):
            carrier = bytes(data)
        else:
            carrier = data
        self._carrier: bytes = carrier
        self._start: int = 0
        self._end: int = len(carrier)
        self._kind: BufferKind = (
            kind if isinstance(kind, BufferKind) else BufferKind(kind)
        )
        self._tenant_id: Optional[str] = tenant_id

    # ── Internal constructor for views ─────────────────────────

    @classmethod
    def _view(
        cls,
        carrier: bytes,
        start: int,
        end: int,
        kind: BufferKind,
        tenant_id: Optional[str],
    ) -> "ZeroCopyBuffer":
        inst = cls.__new__(cls)
        inst._carrier = carrier
        inst._start = start
        inst._end = end
        inst._kind = kind
        inst._tenant_id = tenant_id
        return inst

    # ── Accessors ──────────────────────────────────────────────

    def __len__(self) -> int:
        return self._end - self._start

    @property
    def kind(self) -> BufferKind:
        return self._kind

    @property
    def tenant_id(self) -> Optional[str]:
        return self._tenant_id

    def as_memoryview(self) -> memoryview:
        """Zero-copy view over the visible slice.

        The returned memoryview is read-only. Adopters who need to
        mutate must call :meth:`to_bytes` to obtain an owned copy.
        """
        return memoryview(self._carrier)[self._start : self._end].toreadonly()

    def as_bytes(self) -> bytes:
        """Zero-copy access when the view is already the whole carrier;
        otherwise a copy. Prefer :meth:`as_memoryview` on hot paths."""
        if self._start == 0 and self._end == len(self._carrier):
            return self._carrier
        return self._carrier[self._start : self._end]

    def slice(self, start: int, end: int) -> "ZeroCopyBuffer":
        """Return a sub-view. O(1); shares the carrier."""
        length = len(self)
        if start < 0 or end < start or end > length:
            raise IndexError(
                f"slice({start}, {end}) out of range for buffer len={length}"
            )
        return ZeroCopyBuffer._view(
            self._carrier,
            self._start + start,
            self._start + end,
            self._kind,
            self._tenant_id,
        )

    def retag(self, kind: BufferKind | str) -> "ZeroCopyBuffer":
        """Return a new view tagged with a different kind. The
        original buffer's kind is unchanged — other holders keep
        seeing the old tag, as with the Rust implementation."""
        new_kind = (
            kind if isinstance(kind, BufferKind) else BufferKind(kind)
        )
        return ZeroCopyBuffer._view(
            self._carrier,
            self._start,
            self._end,
            new_kind,
            self._tenant_id,
        )

    def with_tenant(self, tenant_id: str) -> "ZeroCopyBuffer":
        return ZeroCopyBuffer._view(
            self._carrier,
            self._start,
            self._end,
            self._kind,
            tenant_id,
        )

    def sha256(self) -> bytes:
        h = hashlib.sha256()
        h.update(self.as_memoryview())
        return h.digest()

    # ── PEP 3118 buffer protocol pass-through ──────────────────
    #
    # Implementing ``__buffer__`` lets NumPy / PyTorch / Pillow
    # consume a ZeroCopyBuffer without materialising bytes. We expose
    # a read-only view so accidental in-place mutation from a C
    # extension fails fast.

    def __buffer__(self, flags: int) -> memoryview:  # pragma: no cover
        return self.as_memoryview()

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"ZeroCopyBuffer(len={len(self)}, "
            f"kind={self._kind.slug!r}, tenant={self._tenant_id!r})"
        )


# ── BufferMut — in-flight builder ─────────────────────────────────────


class BufferMut:
    """Mutable builder that freezes into a :class:`ZeroCopyBuffer`.

    Usage mirrors the Rust ``BufferMut``: allocate with a capacity
    hint, accumulate via :meth:`extend_from_slice`, call
    :meth:`freeze` exactly once to transition to immutable. Further
    use of ``BufferMut`` after freeze raises.
    """

    __slots__ = ("_data", "_kind", "_tenant_id", "_frozen")

    def __init__(
        self,
        capacity: int = 0,
        kind: BufferKind | str = "raw",
        *,
        tenant_id: Optional[str] = None,
    ) -> None:
        # `bytearray(capacity)` pre-allocates zeroed bytes, which
        # isn't what we want — we want capacity hint only. Python's
        # bytearray manages its own growth; the capacity parameter
        # is used for parity with the Rust API surface.
        self._data = bytearray()
        if capacity > 0:
            # Pre-extend then trim so the underlying storage has at
            # least `capacity` bytes reserved.
            self._data.extend(b"\x00" * capacity)
            self._data.clear()
        self._kind = (
            kind if isinstance(kind, BufferKind) else BufferKind(kind)
        )
        self._tenant_id = tenant_id
        self._frozen = False

    def __len__(self) -> int:
        return len(self._data)

    @property
    def kind(self) -> BufferKind:
        return self._kind

    def with_tenant(self, tenant_id: str) -> "BufferMut":
        if self._frozen:
            raise RuntimeError("BufferMut: cannot tag after freeze")
        self._tenant_id = tenant_id
        return self

    def extend_from_slice(self, data: BytesLike) -> None:
        if self._frozen:
            raise RuntimeError("BufferMut: cannot extend after freeze")
        self._data.extend(data)

    def freeze(self) -> ZeroCopyBuffer:
        if self._frozen:
            raise RuntimeError("BufferMut: already frozen")
        self._frozen = True
        frozen_bytes = bytes(self._data)
        self._data = bytearray()  # release
        return ZeroCopyBuffer(
            frozen_bytes, self._kind, tenant_id=self._tenant_id
        )


# ── Pool allocator ────────────────────────────────────────────────────


class PoolClass(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    OVERSIZE = "oversize"

    @property
    def capacity(self) -> int:
        return {
            PoolClass.SMALL: 4 * 1024,
            PoolClass.MEDIUM: 64 * 1024,
            PoolClass.LARGE: 1024 * 1024,
            PoolClass.HUGE: 10 * 1024 * 1024,
            PoolClass.OVERSIZE: 2**62,  # effectively unbounded sentinel
        }[self]

    @classmethod
    def for_size(cls, requested: int) -> "PoolClass":
        if requested <= cls.SMALL.capacity:
            return cls.SMALL
        if requested <= cls.MEDIUM.capacity:
            return cls.MEDIUM
        if requested <= cls.LARGE.capacity:
            return cls.LARGE
        if requested <= cls.HUGE.capacity:
            return cls.HUGE
        return cls.OVERSIZE


@dataclass
class _TenantAccount:
    soft_limit_bytes: int
    live_bytes: int = 0
    soft_limit_exceeded_total: int = 0


@dataclass(frozen=True)
class BufferPoolSnapshot:
    pool_hits: dict[PoolClass, int]
    pool_misses: dict[PoolClass, int]
    oversize_allocations_total: int
    live_bytes: int
    tenant_live_bytes: dict[str, int]
    tenant_soft_limit_exceeded_total: dict[str, int]


class BufferPool:
    """Slab-class pool. Mirror of ``axon::buffer::BufferPool``.

    Thread-safe; tenant accounting is centralised so the soft-limit
    metric is accurate under concurrent producers.
    """

    _MAX_FREE_LIST: int = 64

    def __init__(
        self, default_tenant_soft_limit_bytes: int = 256 * 1024 * 1024
    ) -> None:
        self._lock = threading.RLock()
        self._free_lists: dict[PoolClass, list[bytearray]] = {
            cls: [] for cls in _NON_OVERSIZE
        }
        self._pool_hits: dict[PoolClass, int] = defaultdict(int)
        self._pool_misses: dict[PoolClass, int] = defaultdict(int)
        self._oversize_allocations: int = 0
        self._live_bytes: int = 0
        self._tenants: dict[str, _TenantAccount] = {}
        self._default_tenant_soft_limit_bytes = (
            default_tenant_soft_limit_bytes
        )

    def set_tenant_soft_limit(
        self, tenant_id: str, soft_limit_bytes: int
    ) -> None:
        with self._lock:
            acct = self._tenants.get(tenant_id)
            if acct is None:
                self._tenants[tenant_id] = _TenantAccount(
                    soft_limit_bytes=soft_limit_bytes
                )
            else:
                acct.soft_limit_bytes = soft_limit_bytes

    def acquire(self, requested: int) -> tuple[bytearray, PoolClass]:
        """Return a cleared ``bytearray`` of capacity >= ``requested``.

        The caller appends into the bytearray and eventually hands
        it off to :class:`BufferMut` / :class:`ZeroCopyBuffer`. When
        finished, pass the bytearray back to :meth:`release`.
        """
        cls = PoolClass.for_size(requested)
        if cls is PoolClass.OVERSIZE:
            with self._lock:
                self._oversize_allocations += 1
            # Direct allocate — not pooled.
            return bytearray(requested), cls
        with self._lock:
            free = self._free_lists[cls]
            if free:
                slab = free.pop()
                slab.clear()
                self._pool_hits[cls] += 1
                return slab, cls
            self._pool_misses[cls] += 1
        # Allocate outside the lock (pure CPU; doesn't need it).
        return bytearray(cls.capacity), cls

    def release(self, slab: bytearray, cls: PoolClass) -> None:
        if cls is PoolClass.OVERSIZE:
            return  # direct allocation — let GC handle it
        with self._lock:
            free = self._free_lists[cls]
            if len(free) < self._MAX_FREE_LIST:
                slab.clear()
                free.append(slab)
            # else drop on the floor — freelist cap prevents unbounded growth

    def record_tenant_allocation(
        self, tenant_id: str, bytes_count: int
    ) -> None:
        with self._lock:
            acct = self._tenants.get(tenant_id)
            if acct is None:
                acct = _TenantAccount(
                    soft_limit_bytes=self._default_tenant_soft_limit_bytes
                )
                self._tenants[tenant_id] = acct
            acct.live_bytes += bytes_count
            if acct.live_bytes > acct.soft_limit_bytes:
                acct.soft_limit_exceeded_total += 1
            self._live_bytes += bytes_count

    def record_tenant_release(
        self, tenant_id: str, bytes_count: int
    ) -> None:
        with self._lock:
            acct = self._tenants.get(tenant_id)
            if acct is None:
                return
            acct.live_bytes = max(0, acct.live_bytes - bytes_count)
            self._live_bytes = max(0, self._live_bytes - bytes_count)

    def snapshot(self) -> BufferPoolSnapshot:
        with self._lock:
            return BufferPoolSnapshot(
                pool_hits={cls: self._pool_hits[cls] for cls in _NON_OVERSIZE},
                pool_misses={cls: self._pool_misses[cls] for cls in _NON_OVERSIZE},
                oversize_allocations_total=self._oversize_allocations,
                live_bytes=self._live_bytes,
                tenant_live_bytes={
                    k: v.live_bytes for k, v in self._tenants.items()
                },
                tenant_soft_limit_exceeded_total={
                    k: v.soft_limit_exceeded_total
                    for k, v in self._tenants.items()
                },
            )


_NON_OVERSIZE: tuple[PoolClass, ...] = (
    PoolClass.SMALL,
    PoolClass.MEDIUM,
    PoolClass.LARGE,
    PoolClass.HUGE,
)


__all__ = [
    "BufferKind",
    "BufferKindRegistry",
    "BufferMut",
    "BufferPool",
    "BufferPoolSnapshot",
    "PoolClass",
    "ZeroCopyBuffer",
    "global_kind_registry",
]
