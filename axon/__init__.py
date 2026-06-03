"""axon-lang — the formal cognitive language (native Rust + C23).

================================================================
§Fase 39.h — Pure Silicon Cognition. v2.0.0 era.
================================================================

As of v2.0.0 the axon language is implemented ENTIRELY in Rust + C23
(`axon-rs/`, `axon-frontend/`, `axon-csys/`). The Python compiler /
runtime / server / CLI that bootstrapped the language through the
v1.x era have been retired (Fase 39 Pure Silicon Cognition).

This package is now a DISTRIBUTION SHIM only: `pip install axon-lang`
fetches the precompiled native binary for your platform and the
`axon` console script execs it. There is no Python language code here
— see `axon/_bootstrap.py` for the launcher.

To use the language directly without the PyPI shim:
  - `cargo install axon-lang`
  - download a release binary from
    https://github.com/Bemarking/axon-lang/releases
  - `docker pull` the axon-enterprise image (Rust adopters)
"""

from __future__ import annotations

# Lives in lockstep with `axon-rs/Cargo.toml`, `pyproject.toml`, and
# `axon/_bootstrap.py::_VERSION`. §Fase 39.i bumps to v2.0.0.
__version__ = "2.6.0"

__all__ = ["__version__", "main"]


def main() -> int:
    """Re-export the native binary launcher (console-script target)."""
    from axon._bootstrap import main as _main

    return _main()
