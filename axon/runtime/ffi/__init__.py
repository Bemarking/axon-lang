"""
AXON Runtime — FFI package (§λ-L-E Fase 11.b).

Zero-copy data-plane bindings. Distinct from :mod:`axon.runtime.ffi_bridge`,
which loads compiled compute kernels via ctypes; this package carries
the multimodal buffer primitives that back audio / video / file ingest.
"""

from axon.runtime.ffi.buffer import (
    BufferKind,
    BufferKindRegistry,
    BufferMut,
    BufferPool,
    BufferPoolSnapshot,
    PoolClass,
    ZeroCopyBuffer,
    global_kind_registry,
)
from axon.runtime.ffi.symbolic_ptr import SymbolicPtr

__all__ = [
    "BufferKind",
    "BufferKindRegistry",
    "BufferMut",
    "BufferPool",
    "BufferPoolSnapshot",
    "PoolClass",
    "SymbolicPtr",
    "ZeroCopyBuffer",
    "global_kind_registry",
]
