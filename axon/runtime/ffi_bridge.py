"""
AXON Runtime — FFI Bridge
============================
Zero-copy Foreign Function Interface for native compute execution.

Loads shared libraries (.dll/.so/.dylib) compiled from AXON compute
blocks and invokes them via Python's ctypes.  This is the final stage
of the Fast-Path pipeline:

  logic_source → Rust/C transpiler → compiler → shared lib → **FFI Bridge** → result

The bridge enforces type safety by declaring all parameters and return
values as ``ctypes.c_double`` (f64), matching the Rust transpiler's
output signature.

Paper §5.3 — Zero-Copy FFI Execution:
  Arguments are passed as native f64 values directly to the compiled
  function.  No JSON serialization, no Python object boxing on the
  hot path.  The compiled function operates at silicon speed.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any


class FFIBridge:
    """Load and call native compute functions via ctypes FFI.

    The bridge manages loaded shared libraries and provides a clean
    interface for the NativeComputeDispatcher to call compiled
    compute functions.

    Thread safety: each FFIBridge instance maintains its own library
    cache.  The underlying ctypes calls are thread-safe for pure
    functions (no shared mutable state).
    """

    # Platform-specific shared library extension
    _LIB_EXT = {
        "win32": ".dll",
        "linux": ".so",
        "darwin": ".dylib",
    }

    def __init__(self) -> None:
        self._loaded: dict[str, ctypes.CDLL] = {}

    @classmethod
    def lib_extension(cls) -> str:
        """Return the shared library extension for the current platform."""
        for platform, ext in cls._LIB_EXT.items():
            if sys.platform.startswith(platform):
                return ext
        return ".so"  # Default to .so for unknown platforms

    def load(self, lib_path: str | Path) -> ctypes.CDLL:
        """Load a shared library, caching by path.

        Args:
            lib_path: Absolute path to the .dll/.so/.dylib file.

        Returns:
            The loaded ctypes.CDLL handle.

        Raises:
            OSError: If the library cannot be loaded.
        """
        key = str(lib_path)
        if key not in self._loaded:
            self._loaded[key] = ctypes.CDLL(key)
        return self._loaded[key]

    def call(
        self,
        lib_path: str | Path,
        fn_name: str,
        args: list[float],
    ) -> float:
        """Call a native compute function via FFI.

        Args:
            lib_path: Path to the shared library.
            fn_name: The exported function name (e.g. "axon_compute_CalculateTax").
            args: List of f64 arguments.

        Returns:
            The f64 result from the native function.

        Raises:
            OSError: If the library cannot be loaded.
            AttributeError: If the function is not found in the library.
        """
        lib = self.load(lib_path)

        func = getattr(lib, fn_name)
        func.restype = ctypes.c_double
        func.argtypes = [ctypes.c_double] * len(args)

        c_args = [ctypes.c_double(a) for a in args]
        return func(*c_args)

    def unload_all(self) -> None:
        """Clear all loaded library handles.

        Note: ctypes does not support explicit unloading on all platforms.
        This clears our references so the OS can reclaim resources.
        """
        self._loaded.clear()
