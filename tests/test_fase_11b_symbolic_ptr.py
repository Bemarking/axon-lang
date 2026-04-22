"""
Unit tests — §λ-L-E Fase 11.b SymbolicPtr[T] handle.
"""

from __future__ import annotations

import gc

from axon.runtime.ffi.buffer import BufferKind, ZeroCopyBuffer
from axon.runtime.ffi.symbolic_ptr import SymbolicPtr


def test_construct_starts_refcount_at_one() -> None:
    buf = ZeroCopyBuffer(b"hello", BufferKind.raw())
    ptr = SymbolicPtr(buf)
    assert ptr.refcount == 1
    assert ptr.is_unique


def test_clone_increments_refcount_for_all_sharers() -> None:
    buf = ZeroCopyBuffer(b"hello", BufferKind.raw())
    ptr = SymbolicPtr(buf)
    a = ptr.clone()
    b = ptr.clone()
    assert ptr.refcount == 3
    assert a.refcount == 3
    assert b.refcount == 3
    assert not ptr.is_unique


def test_deref_returns_same_resource_across_clones() -> None:
    buf = ZeroCopyBuffer(b"hello", BufferKind.raw())
    ptr = SymbolicPtr(buf)
    clone = ptr.clone()
    assert ptr.deref() is clone.deref() is buf


def test_drop_decrements_refcount() -> None:
    buf = ZeroCopyBuffer(b"hello", BufferKind.raw())
    ptr = SymbolicPtr(buf)
    clone = ptr.clone()
    assert ptr.refcount == 2
    del clone
    # Python's GC is deterministic enough for CPython to drop the
    # weakref finalizer; force a pass to be portable across impls.
    gc.collect()
    assert ptr.refcount == 1


def test_zero_copy_fanout_through_symbolic_ptr() -> None:
    # The canonical 11.b use case: ingest produces one buffer;
    # multiple consumers receive cheap handles; no one copies bytes.
    buf = ZeroCopyBuffer(b"x" * 1024 * 1024, BufferKind.pcm16())
    origin = SymbolicPtr(buf)

    handles = [origin.clone() for _ in range(100)]
    assert origin.refcount == 101

    # Each consumer sees the same bytes via zero-copy memoryview.
    for h in handles:
        mv = h.deref().as_memoryview()
        assert len(mv) == 1024 * 1024


def test_drop_all_clones_leaves_original_at_one() -> None:
    buf = ZeroCopyBuffer(b"x", BufferKind.raw())
    ptr = SymbolicPtr(buf)
    clones = [ptr.clone() for _ in range(5)]
    del clones
    gc.collect()
    assert ptr.refcount == 1
