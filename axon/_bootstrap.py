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
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Bumped in lockstep with the release (Cargo.toml + pyproject.toml).
# §Fase 39.i sets this to the v2.0.0 release version.
_VERSION = "2.9.0"

_RELEASE_BASE = "https://github.com/Bemarking/axon-lang/releases/download"


def _os_name() -> str:
    """Resolve the OS token matching the release asset names.

    `platform.system()` returns "Darwin" on macOS, but the release
    assets use "macos" — map it. Linux + Windows pass through.
    """
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    return s


def _arch() -> str:
    """Resolve the arch token matching the release asset names."""
    a = platform.machine().lower()
    if a in ("x86_64", "amd64"):
        return "x86_64"
    if a in ("arm64", "aarch64"):
        return "aarch64"
    return a


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _archive_asset() -> str:
    """The release asset filename for the host platform.

    rust_release.yml publishes `.tar.gz` archives for Linux/macOS and
    a `.zip` for Windows — NOT raw binaries. The launcher downloads
    the archive then extracts the `axon` binary.
    """
    slug = f"{_os_name()}-{_arch()}"
    return f"axon-{slug}.zip" if _is_windows() else f"axon-{slug}.tar.gz"


def _binary_name() -> str:
    return "axon.exe" if _is_windows() else "axon"


def _cache_dir() -> Path:
    base = os.environ.get("AXON_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".cache" / "axon-lang"
    return root / _VERSION


def _binary_path() -> Path:
    return _cache_dir() / _binary_name()


def _download_and_extract(target: Path) -> None:
    """Fetch + extract the native binary for the host platform.

    Downloads the platform archive (`.tar.gz` / `.zip`) from the
    matching GitHub Release, extracts the `axon` binary into the
    cache dir at *target*, and marks it executable on POSIX.
    """
    asset = _archive_asset()
    url = f"{_RELEASE_BASE}/v{_VERSION}/{asset}"
    target.parent.mkdir(parents=True, exist_ok=True)
    sys.stderr.write(
        f"axon-lang: fetching native binary archive {asset} (v{_VERSION})...\n"
    )
    binary_name = _binary_name()
    try:
        with tempfile.NamedTemporaryFile(
            suffix=Path(asset).suffix, delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
            with urllib.request.urlopen(url) as resp:
                tmp.write(resp.read())
        # Extract the `axon` binary from the archive.
        if asset.endswith(".zip"):
            with zipfile.ZipFile(tmp_path) as zf:
                _extract_member(zf.namelist(), binary_name, zf, target, is_zip=True)
        else:
            with tarfile.open(tmp_path, "r:gz") as tf:
                _extract_member(tf.getnames(), binary_name, tf, target, is_zip=False)
        tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover — network/IO defensive
        sys.stderr.write(
            f"axon-lang: failed to fetch/extract native binary from {url}: {exc}\n"
            f"axon-lang: install manually from {_RELEASE_BASE}/v{_VERSION} "
            f"or use `cargo install axon-lang`.\n"
        )
        raise SystemExit(2)
    if not _is_windows():
        mode = os.stat(target).st_mode
        os.chmod(target, mode | stat.S_IEXEC)


def _extract_member(names, binary_name, archive, target: Path, *, is_zip: bool) -> None:
    """Extract the entry whose basename matches *binary_name* to *target*."""
    member = next(
        (n for n in names if Path(n).name == binary_name),
        None,
    )
    if member is None:
        raise FileNotFoundError(
            f"archive does not contain a `{binary_name}` entry (found: {names})"
        )
    if is_zip:
        data = archive.read(member)
    else:
        extracted = archive.extractfile(member)
        if extracted is None:
            raise FileNotFoundError(f"could not read `{member}` from tar archive")
        data = extracted.read()
    with open(target, "wb") as out:
        out.write(data)


def _resolve_binary() -> Path:
    binary = _binary_path()
    if not binary.exists():
        _download_and_extract(binary)
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
