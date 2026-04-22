"""
Unit tests — §λ-L-E Fase 11.b Python ZeroCopyBuffer + BufferMut + pool.
"""

from __future__ import annotations

import hashlib

import pytest

from axon.runtime.ffi.buffer import (
    BufferKind,
    BufferMut,
    BufferPool,
    BufferPoolSnapshot,
    PoolClass,
    ZeroCopyBuffer,
    global_kind_registry,
)


# ── BufferKind ────────────────────────────────────────────────────────


def test_seeded_kinds_are_interned() -> None:
    a = BufferKind.pcm16()
    b = BufferKind("pcm16")
    assert a == b
    assert a.slug == "pcm16"
    # Interned → slug strings are the same object.
    assert a.slug is b.slug


def test_custom_kind_registers_once() -> None:
    k1 = BufferKind("siemens_dicom")
    k2 = BufferKind("siemens_dicom")
    assert k1 == k2
    assert k1.slug is k2.slug
    assert "siemens_dicom" in global_kind_registry().known_slugs()


def test_different_slugs_are_not_equal() -> None:
    assert BufferKind("a") != BufferKind("b")


# ── ZeroCopyBuffer ────────────────────────────────────────────────────


def test_constructor_from_bytes() -> None:
    b = ZeroCopyBuffer(b"hello", BufferKind.raw())
    assert len(b) == 5
    assert b.as_bytes() == b"hello"
    assert b.kind == BufferKind.raw()
    assert b.tenant_id is None


def test_constructor_accepts_bytearray_and_memoryview() -> None:
    b1 = ZeroCopyBuffer(bytearray(b"x" * 8), "raw")
    assert len(b1) == 8
    b2 = ZeroCopyBuffer(memoryview(b"y" * 4), "raw")
    assert b2.as_bytes() == b"yyyy"


def test_slice_returns_view_over_same_carrier() -> None:
    b = ZeroCopyBuffer(bytes(range(10)), "raw")
    s = b.slice(2, 6)
    assert s.as_bytes() == bytes([2, 3, 4, 5])
    assert len(s) == 4


def test_slice_of_slice_computes_correct_range() -> None:
    b = ZeroCopyBuffer(bytes(range(100)), "raw")
    mid = b.slice(10, 60)
    inner = mid.slice(5, 15)
    assert inner.as_bytes() == bytes(range(15, 25))


def test_slice_rejects_out_of_range() -> None:
    b = ZeroCopyBuffer(b"abc", "raw")
    with pytest.raises(IndexError):
        b.slice(0, 10)
    with pytest.raises(IndexError):
        b.slice(5, 2)


def test_retag_preserves_original_kind() -> None:
    b = ZeroCopyBuffer(b"data", BufferKind.raw())
    j = b.retag(BufferKind.jpeg())
    assert b.kind == BufferKind.raw()
    assert j.kind == BufferKind.jpeg()
    # Carrier is shared.
    assert b.as_bytes() == j.as_bytes()


def test_sha256_matches_hashlib_over_visible_slice() -> None:
    b = ZeroCopyBuffer(b"hello world", "raw")
    assert b.sha256() == hashlib.sha256(b"hello world").digest()
    mid = b.slice(6, 11)  # "world"
    assert mid.sha256() == hashlib.sha256(b"world").digest()


def test_tenant_tag_propagates_through_slice_and_retag() -> None:
    b = ZeroCopyBuffer(b"abc", "raw").with_tenant("alpha")
    assert b.slice(0, 1).tenant_id == "alpha"
    assert b.retag("jpeg").tenant_id == "alpha"


def test_memoryview_is_readonly() -> None:
    b = ZeroCopyBuffer(b"abc", "raw")
    mv = b.as_memoryview()
    assert mv.readonly
    with pytest.raises(TypeError):
        mv[0] = 99  # type: ignore[index]


def test_buffer_protocol_exposes_memoryview() -> None:
    # Adopter libraries consume via `memoryview(buf)` or via the
    # buffer protocol on Python 3.12+.
    b = ZeroCopyBuffer(b"hello", "raw")
    mv = memoryview(b.as_memoryview())
    assert bytes(mv) == b"hello"


# ── BufferMut ─────────────────────────────────────────────────────────


def test_mut_accumulates_then_freezes_into_immutable() -> None:
    bm = BufferMut(capacity=1024, kind=BufferKind.raw())
    for chunk in [b"hello ", b"world"]:
        bm.extend_from_slice(chunk)
    frozen = bm.freeze()
    assert frozen.as_bytes() == b"hello world"
    assert frozen.kind == BufferKind.raw()


def test_mut_freeze_is_once_only() -> None:
    bm = BufferMut(capacity=8, kind="raw")
    bm.extend_from_slice(b"abc")
    bm.freeze()
    with pytest.raises(RuntimeError, match="already frozen"):
        bm.freeze()


def test_mut_rejects_extend_after_freeze() -> None:
    bm = BufferMut(capacity=8, kind="raw")
    bm.extend_from_slice(b"abc")
    bm.freeze()
    with pytest.raises(RuntimeError, match="after freeze"):
        bm.extend_from_slice(b"def")


def test_mut_with_tenant_propagates() -> None:
    bm = BufferMut(capacity=8, kind="raw").with_tenant("alpha")
    bm.extend_from_slice(b"abc")
    frozen = bm.freeze()
    assert frozen.tenant_id == "alpha"


# ── Pool ──────────────────────────────────────────────────────────────


def test_pool_size_class_mapping() -> None:
    assert PoolClass.for_size(1) is PoolClass.SMALL
    assert PoolClass.for_size(4 * 1024) is PoolClass.SMALL
    assert PoolClass.for_size(4 * 1024 + 1) is PoolClass.MEDIUM
    assert PoolClass.for_size(64 * 1024) is PoolClass.MEDIUM
    assert PoolClass.for_size(64 * 1024 + 1) is PoolClass.LARGE
    assert PoolClass.for_size(1024 * 1024) is PoolClass.LARGE
    assert PoolClass.for_size(1024 * 1024 + 1) is PoolClass.HUGE
    assert PoolClass.for_size(10 * 1024 * 1024) is PoolClass.HUGE
    assert PoolClass.for_size(10 * 1024 * 1024 + 1) is PoolClass.OVERSIZE


def test_pool_acquire_release_reuse() -> None:
    pool = BufferPool()
    slab, cls = pool.acquire(1000)
    assert cls is PoolClass.SMALL
    assert slab.__class__ is bytearray
    pool.release(slab, cls)
    slab2, cls2 = pool.acquire(1000)
    assert cls == cls2
    assert len(slab2) == 0  # cleared
    snap = pool.snapshot()
    assert snap.pool_hits[PoolClass.SMALL] == 1
    assert snap.pool_misses[PoolClass.SMALL] == 1


def test_pool_oversize_bypasses_class_cache() -> None:
    pool = BufferPool()
    slab, cls = pool.acquire(50 * 1024 * 1024)
    assert cls is PoolClass.OVERSIZE
    pool.release(slab, cls)
    snap = pool.snapshot()
    assert snap.oversize_allocations_total == 1
    assert snap.pool_hits[PoolClass.HUGE] == 0


def test_pool_tenant_soft_limit_exceeded_counter() -> None:
    pool = BufferPool(default_tenant_soft_limit_bytes=1024)
    pool.record_tenant_allocation("alpha", 2048)
    pool.record_tenant_allocation("alpha", 512)
    snap = pool.snapshot()
    assert snap.tenant_soft_limit_exceeded_total["alpha"] == 2
    assert snap.tenant_live_bytes["alpha"] == 2560


def test_pool_tenant_release_decrements_live_bytes() -> None:
    pool = BufferPool(default_tenant_soft_limit_bytes=1024)
    pool.record_tenant_allocation("alpha", 1000)
    pool.record_tenant_release("alpha", 400)
    snap = pool.snapshot()
    assert snap.tenant_live_bytes["alpha"] == 600


def test_pool_per_tenant_override() -> None:
    pool = BufferPool(default_tenant_soft_limit_bytes=1024)
    pool.set_tenant_soft_limit("premium", 10 * 1024)
    pool.record_tenant_allocation("premium", 5 * 1024)
    snap = pool.snapshot()
    assert snap.tenant_soft_limit_exceeded_total["premium"] == 0


def test_pool_free_list_cap_does_not_blow_up() -> None:
    pool = BufferPool()
    for _ in range(200):
        slab, cls = pool.acquire(1000)
        pool.release(slab, cls)
    # Last acquire still works — freelist cap is silent.
    slab, cls = pool.acquire(1000)
    assert cls is PoolClass.SMALL
