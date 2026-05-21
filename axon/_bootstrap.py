"""axon — native binary launcher (PyPI distribution shim).

================================================================
§Fase 39.h — DISTRIBUTION LAYER, NOT LANGUAGE RUNTIME (D13).
================================================================

This is the ONLY Python file in the `axon-lang` PyPI package as of
v2.0.0. It exists SOLELY so `pip install axon-lang` keeps working for
users who reach axon through the Python packaging ecosystem. It
contains ZERO language logic: the lexer, parser, type-checker, IR
generator, runtime, server, and CLI are all native Rust + C23
(see `axon-rs/`, `axon-frontend/`, `axon-csys/`).

The launcher resolves (and, on first run, downloads) the precompiled
native `axon` binary for the host platform from the matching GitHub
Release, caches it under the user cache dir, and `exec`s it with the
caller's arguments — so `axon check x.axon` invoked via the PyPI
console-script is byte-for-byte the native binary.

Per the founder strategic north star (memoria
`feedback_zero_py_files_north_star`): the language is 0 `.py`. This
launcher is distribution infrastructure, exempted from that count and
flagged for eventual removal once native installers (Homebrew /
chocolatey / cargo-binstall) cover every platform.
"""

from __future__ import annotations

import os
import platform
import stat
import sys
import urllib.request
from pathlib import Path

# Bumped in lockstep with the release (Cargo.toml + pyproject.toml).
# §Fase 39.i sets this to the v2.0.0 release version.
_VERSION = "2.0.0"

_RELEASE_BASE = "https://github.com/Bemarking/axon-lang/releases/download"


def _platform_slug() -> str:
    """Resolve the `<os>-<arch>` slug matching the release asset names."""
    osname = platform.system().lower()
    arch = platform.machine().lower()
    # Normalise arch aliases to the release-asset convention.
    if arch in ("x86_64", "amd64"):
        arch = "x86_64"
    elif arch in ("arm64", "aarch64"):
        arch = "aarch64"
    return f"{osname}-{arch}"


def _binary_name() -> str:
    return "axon.exe" if platform.system().lower() == "windows" else "axon"


def _cache_dir() -> Path:
    base = os.environ.get("AXON_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".cache" / "axon-lang"
    return root / _VERSION


def _binary_path() -> Path:
    return _cache_dir() / _binary_name()


def _download_binary(target: Path) -> None:
    """Fetch the native binary for the host platform into *target*."""
    slug = _platform_slug()
    ext = ".exe" if platform.system().lower() == "windows" else ""
    asset = f"axon-{slug}{ext}"
    url = f"{_RELEASE_BASE}/v{_VERSION}/{asset}"
    target.parent.mkdir(parents=True, exist_ok=True)
    sys.stderr.write(f"axon-lang: fetching native binary {asset} (v{_VERSION})...\n")
    try:
        with urllib.request.urlopen(url) as resp, open(target, "wb") as out:
            out.write(resp.read())
    except Exception as exc:  # pragma: no cover — network/IO defensive
        sys.stderr.write(
            f"axon-lang: failed to download native binary from {url}: {exc}\n"
            f"axon-lang: install the binary manually from "
            f"{_RELEASE_BASE}/v{_VERSION} or use `cargo install axon-lang`.\n"
        )
        raise SystemExit(2)
    # Mark executable on POSIX — owner-only (least privilege; the
    # cached binary lives under the user's own cache dir).
    if platform.system().lower() != "windows":
        mode = os.stat(target).st_mode
        os.chmod(target, mode | stat.S_IEXEC)


def _resolve_binary() -> Path:
    binary = _binary_path()
    if not binary.exists():
        _download_binary(binary)
    return binary


def main() -> int:
    """Console-script entry point — exec the native binary."""
    binary = _resolve_binary()
    args = [str(binary), *sys.argv[1:]]
    if platform.system().lower() == "windows":
        # Windows has no execv that replaces the process cleanly for
        # console apps; subprocess + propagate the exit code.
        import subprocess

        return subprocess.run(args, check=False).returncode
    # POSIX: replace the process image entirely (clean signal forwarding).
    os.execv(str(binary), args)
    return 0  # unreachable on POSIX


if __name__ == "__main__":
    raise SystemExit(main())
