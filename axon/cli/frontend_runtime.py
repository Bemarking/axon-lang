"""Shared frontend bootstrap policy for AXON product entrypoints."""

from __future__ import annotations

import sys

from axon.compiler import bootstrap_frontend


FRONTEND_COMMANDS = frozenset(
    {"check", "compile", "run", "dossier", "sbom", "audit", "evidence-package"}
)
MVP_FRONTEND_COMMANDS = frozenset({"check", "compile"})


def initialize_frontend_runtime(command: str, *, allowed_commands: set[str] | frozenset[str]) -> int | None:
    """Bootstrap the frontend for entrypoints that expose frontend commands."""
    if command not in allowed_commands:
        return None

    try:
        bootstrap_frontend()
    except ValueError as exc:
        print(f"✗ Frontend bootstrap failed: {exc}", file=sys.stderr)
        return 2

    return None