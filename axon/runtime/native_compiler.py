"""
AXON Runtime — Native Compiler
=================================
Compiles Rust or C source to shared libraries for FFI execution.

This module implements the compilation tiers described in Paper §5:

  Tier 1 (Rust — preferred):
    logic_source → RustTranspiler → .rs file → rustc --crate-type cdylib → .dll/.so
    Security: borrow checker + no-unsafe guarantee
    Speed: native LLVM-optimized machine code

  Tier 2 (C — fallback):
    logic_source → C transpilation → .c file → gcc/tcc/cl → .dll/.so
    Security: pure function, no includes, no I/O
    Speed: native machine code, slightly less safe than Rust

Both tiers produce a C-ABI shared library loadable via ctypes.

Compilation cache:
  Libraries are cached under a temporary directory keyed by the
  SHA-256 hash of the logic_source.  Repeated calls with the same
  logic skip compilation entirely.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axon.runtime.ffi_bridge import FFIBridge
from axon.runtime.rust_transpiler import RustTranspiler, TranspileResult


@dataclass(frozen=True)
class CompileResult:
    """Result of compiling a compute block to a shared library."""

    lib_path: Path
    fn_name: str
    source_hash: str
    tier: str  # "rust", "c", or "python"
    cached: bool


class NativeCompiler:
    """Compile AXON compute logic to native shared libraries.

    Attempts compilation in order of preference:
      1. Rust (rustc) — maximum safety + speed
      2. C (gcc/tcc/cl) — fast fallback
      3. Python (no compilation) — always-available fallback

    Compiled libraries are cached by source hash to avoid
    recompilation on repeated invocations.
    """

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        if cache_dir is None:
            self._cache_dir = Path(
                tempfile.gettempdir(), "axon_compute_cache",
            )
        else:
            self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._transpiler = RustTranspiler()
        self._lib_ext = FFIBridge.lib_extension()

        # Detect available compilers once at init
        self._rustc = shutil.which("rustc")
        self._gcc = shutil.which("gcc")
        self._tcc = shutil.which("tcc")
        self._cl = shutil.which("cl")

    @property
    def available_tier(self) -> str:
        """Return the best available compilation tier."""
        if self._rustc:
            return "rust"
        if self._gcc or self._tcc or self._cl:
            return "c"
        return "python"

    def compile(
        self,
        logic_source: str,
        fn_name: str,
        param_names: list[str],
    ) -> CompileResult:
        """Compile a compute block to a shared library.

        Args:
            logic_source: The raw logic DSL string.
            fn_name: Compute block name.
            param_names: Input parameter names.

        Returns:
            CompileResult with path to the shared library.
        """
        source_hash = hashlib.sha256(
            logic_source.encode("utf-8"),
        ).hexdigest()[:16]

        # Check cache first
        cached_lib = self._cache_dir / f"{source_hash}{self._lib_ext}"
        cached_meta = self._cache_dir / f"{source_hash}.meta"
        if cached_lib.exists() and cached_meta.exists():
            rust_fn_name = cached_meta.read_text().strip()
            return CompileResult(
                lib_path=cached_lib,
                fn_name=rust_fn_name,
                source_hash=source_hash,
                tier=self._detect_cached_tier(source_hash),
                cached=True,
            )

        # Try Tier 1: Rust
        if self._rustc:
            result = self._compile_rust(
                logic_source, fn_name, param_names, source_hash,
            )
            if result is not None:
                return result

        # Try Tier 2: C
        c_compiler = self._gcc or self._tcc or self._cl
        if c_compiler:
            result = self._compile_c(
                logic_source, fn_name, param_names,
                source_hash, c_compiler,
            )
            if result is not None:
                return result

        # Tier 3: Python fallback
        return CompileResult(
            lib_path=Path(""),
            fn_name=f"axon_compute_{self._sanitize(fn_name)}",
            source_hash=source_hash,
            tier="python",
            cached=False,
        )

    def _compile_rust(
        self,
        logic_source: str,
        fn_name: str,
        param_names: list[str],
        source_hash: str,
    ) -> CompileResult | None:
        """Tier 1: Transpile to Rust and compile with rustc."""
        try:
            transpiled = self._transpiler.transpile(
                logic_source, fn_name, param_names,
            )

            # Write Rust source to temp file
            rs_path = self._cache_dir / f"{source_hash}.rs"
            rs_path.write_text(transpiled.rust_source, encoding="utf-8")

            # Compile: rustc --crate-type cdylib -O -o output.dll source.rs
            lib_path = self._cache_dir / f"{source_hash}{self._lib_ext}"
            result = subprocess.run(
                [
                    self._rustc,
                    "--crate-type", "cdylib",
                    "-O",
                    "-o", str(lib_path),
                    str(rs_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and lib_path.exists():
                # Write metadata for cache lookup
                meta_path = self._cache_dir / f"{source_hash}.meta"
                meta_path.write_text(transpiled.fn_name, encoding="utf-8")

                # Also save tier info
                tier_path = self._cache_dir / f"{source_hash}.tier"
                tier_path.write_text("rust", encoding="utf-8")

                return CompileResult(
                    lib_path=lib_path,
                    fn_name=transpiled.fn_name,
                    source_hash=source_hash,
                    tier="rust",
                    cached=False,
                )

            # Compilation failed — fall through to next tier
            return None

        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None

    def _compile_c(
        self,
        logic_source: str,
        fn_name: str,
        param_names: list[str],
        source_hash: str,
        compiler: str,
    ) -> CompileResult | None:
        """Tier 2: Transpile to C and compile with gcc/tcc/cl."""
        try:
            c_fn_name = f"axon_compute_{self._sanitize(fn_name)}"
            c_source = self._transpile_to_c(
                logic_source, c_fn_name, param_names,
            )

            c_path = self._cache_dir / f"{source_hash}.c"
            c_path.write_text(c_source, encoding="utf-8")

            lib_path = self._cache_dir / f"{source_hash}{self._lib_ext}"

            # Build command based on compiler
            if "cl" in Path(compiler).name.lower():
                # MSVC: cl /LD /O2 /Fe:output.dll source.c
                cmd = [compiler, "/LD", "/O2",
                       f"/Fe:{lib_path}", str(c_path)]
            else:
                # GCC/TCC: gcc -shared -O2 -o output.so source.c
                cmd = [compiler, "-shared", "-O2",
                       "-o", str(lib_path), str(c_path)]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and lib_path.exists():
                meta_path = self._cache_dir / f"{source_hash}.meta"
                meta_path.write_text(c_fn_name, encoding="utf-8")

                tier_path = self._cache_dir / f"{source_hash}.tier"
                tier_path.write_text("c", encoding="utf-8")

                return CompileResult(
                    lib_path=lib_path,
                    fn_name=c_fn_name,
                    source_hash=source_hash,
                    tier="c",
                    cached=False,
                )

            return None

        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None

    def _transpile_to_c(
        self,
        logic_source: str,
        fn_name: str,
        param_names: list[str],
    ) -> str:
        """Transpile logic_source to a minimal C function.

        Security: No #include, no I/O, no malloc. Pure arithmetic only.
        """
        params_c = ", ".join(f"double {self._sanitize(p)}" for p in param_names)

        lines = logic_source.strip().splitlines()
        body_lines: list[str] = []
        has_return = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            let_match = re.match(r"^let\s+(\w+)\s*=\s*(.+)$", line)
            if let_match:
                var = self._sanitize(let_match.group(1))
                expr = let_match.group(2).strip()
                body_lines.append(f"    double {var} = {expr};")
                continue

            return_match = re.match(r"^return\s+(.+)$", line)
            if return_match:
                expr = return_match.group(1).strip()
                body_lines.append(f"    return {expr};")
                has_return = True
                continue

        if not has_return:
            body_lines.append("    return 0.0;")

        body = "\n".join(body_lines)

        # Platform-specific export macro
        if sys.platform == "win32":
            export = "__declspec(dllexport)"
        else:
            export = "__attribute__((visibility(\"default\")))"

        return (
            f"/* Auto-generated by AXON C Transpiler */\n"
            f"/* Pure deterministic morphism — no I/O, no alloc */\n"
            f"\n"
            f"{export}\n"
            f"double {fn_name}({params_c}) {{\n"
            f"{body}\n"
            f"}}\n"
        )

    def _detect_cached_tier(self, source_hash: str) -> str:
        """Detect which tier was used for a cached compilation."""
        tier_path = self._cache_dir / f"{source_hash}.tier"
        if tier_path.exists():
            return tier_path.read_text().strip()
        return "unknown"

    @staticmethod
    def _sanitize(name: str) -> str:
        """Sanitize an identifier for C/Rust."""
        return re.sub(r"[^a-zA-Z0-9_]", "_", name)

    def clear_cache(self) -> None:
        """Remove all cached compilations."""
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
