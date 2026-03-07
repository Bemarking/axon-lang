"""
axon inspect — Introspect the AXON standard library.

Usage::

    axon inspect anchors               List all anchors
    axon inspect personas              List all personas
    axon inspect flows                 List all flows
    axon inspect tools                 List all tools
    axon inspect NoHallucination       Detail for a specific component
    axon inspect --all                 List everything

Exit codes:
  0 — success
  1 — component not found
"""

from __future__ import annotations

import sys
from argparse import Namespace

# ── ANSI colors ──────────────────────────────────────────────────

_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{code}{text}{_RESET}"


# ── Namespace listing ────────────────────────────────────────────

_NAMESPACES = ("anchors", "personas", "flows", "tools")


def _print_namespace(registry, namespace: str) -> None:
    """Print all entries in a stdlib namespace."""
    entries = registry.list_all(namespace)
    if not entries:
        print(_c(f"  No {namespace} registered.", _DIM))
        return

    print(f"\n  {_c(f'{namespace.upper()} ({len(entries)})', _BOLD + _CYAN)}")
    print(f"  {'─' * 50}")

    for entry in entries:
        name = _c(entry.name, _GREEN + _BOLD)

        # Build metadata line
        meta_parts: list[str] = []
        if hasattr(entry, "severity"):
            meta_parts.append(f"severity={entry.severity}")
        if hasattr(entry, "category"):
            meta_parts.append(f"category={entry.category}")
        if hasattr(entry, "requires_api_key") and entry.requires_api_key:
            meta_parts.append("requires_api_key")
        if hasattr(entry, "version"):
            meta_parts.append(f"v{entry.version}")

        meta = _c(f"  [{', '.join(meta_parts)}]", _DIM) if meta_parts else ""
        print(f"    {name}{meta}")

        if entry.description:
            print(f"      {_c(entry.description, _DIM)}")

    print()


def _print_detail(registry, name: str) -> int:
    """Print detailed info for a specific component by name."""
    for ns in _NAMESPACES:
        if registry.has(ns, name):
            entry = registry.resolve_entry(ns, name)
            ir = entry.ir

            print(f"\n  {_c(entry.name, _GREEN + _BOLD)}  ({ns})")
            print(f"  {'═' * 50}")

            if entry.description:
                print(f"\n  {entry.description}")

            # IR node fields
            print(f"\n  {_c('IR Node:', _CYAN + _BOLD)}")
            ir_dict = ir.to_dict()
            for key, value in ir_dict.items():
                if key == "node_type" or not value:
                    continue
                print(f"    {_c(key, _YELLOW)}: {value}")

            # Extra metadata
            meta_lines: list[str] = []
            if hasattr(entry, "severity"):
                meta_lines.append(f"severity: {entry.severity}")
            if hasattr(entry, "category"):
                meta_lines.append(f"category: {entry.category}")
            if hasattr(entry, "version"):
                meta_lines.append(f"version: {entry.version}")
            if hasattr(entry, "requires_api_key"):
                meta_lines.append(f"requires_api_key: {entry.requires_api_key}")
            if hasattr(entry, "checker_fn") and entry.checker_fn:
                fn_name = entry.checker_fn.__name__
                meta_lines.append(f"checker: {fn_name}")

            if meta_lines:
                print(f"\n  {_c('Metadata:', _CYAN + _BOLD)}")
                for line in meta_lines:
                    print(f"    {line}")

            print()
            return 0

    print(_c(f"  ✗ '{name}' not found in any namespace.", _RED))
    print(f"  Available namespaces: {', '.join(_NAMESPACES)}")
    print(f"  Try: axon inspect anchors")
    return 1


# ── Entry point ──────────────────────────────────────────────────

def cmd_inspect(args: Namespace) -> int:
    """Execute the ``axon inspect`` subcommand."""
    from axon.stdlib.base import StdlibRegistry

    registry = StdlibRegistry()
    target = args.target

    # --all flag: list everything
    if getattr(args, "all", False):
        for ns in _NAMESPACES:
            _print_namespace(registry, ns)
        return 0

    # Namespace listing
    if target in _NAMESPACES:
        _print_namespace(registry, target)
        return 0

    # Specific component detail
    return _print_detail(registry, target)
