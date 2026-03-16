"""
AXON Runtime — Epistemic Inference Engine (v0.14.0)
======================================================
Static heuristics for inferring epistemic classification
of Python tools based on their signatures and behavior.

Theoretical foundation — Convergence Theorem 4:

    Given a Python function ``f``, we infer its epistemic level
    by analyzing its signature and observable properties:

    1. **Pure functions** (no I/O, no side effects) → ``know``
       Mathematical functions: f(x) = y, deterministic, referentially
       transparent.

    2. **Cached/memoized** → ``believe``
       Results are reproducible but may be stale.

    3. **Network/API calls** → ``speculate``
       Results depend on external state that the system cannot
       control or verify.

    4. **Non-deterministic** (random, model inference) → ``doubt``
       Results are intentionally stochastic.

The inference is conservative: in ambiguity, it assigns the LOWER
epistemic level (more skeptical) to preserve security guarantees.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════
#  HEURISTIC MATCHERS — signature-based inference rules
# ═══════════════════════════════════════════════════════════════════

# Keywords in parameter names or function names that suggest I/O
_IO_KEYWORDS = frozenset({
    "url", "endpoint", "api_key", "api_url", "host", "port",
    "base_url", "webhook", "request", "response", "http",
    "fetch", "download", "upload", "send", "post", "get",
})

# Keywords suggesting non-determinism
_RANDOM_KEYWORDS = frozenset({
    "random", "sample", "seed", "temperature", "top_p", "top_k",
    "stochastic", "probabilistic", "inference", "predict",
    "generate", "model", "llm", "chat", "complete",
})

# Keywords suggesting I/O operations (file, database)
_STORAGE_KEYWORDS = frozenset({
    "file", "path", "directory", "database", "db", "sql",
    "read_file", "write_file", "save", "load", "persist",
    "connect", "cursor", "query", "insert", "update",
})

# Keywords suggesting pure computation
_PURE_KEYWORDS = frozenset({
    "compute", "calculate", "transform", "convert", "parse",
    "format", "validate", "check", "compare", "sort", "filter",
    "map", "reduce", "aggregate", "sum", "count", "average",
    "encode", "decode", "hash", "encrypt", "decrypt",
})

# Async functions are more likely to involve I/O
# Sync functions are more likely to be pure

# ═══════════════════════════════════════════════════════════════════
#  INFERENCE ENGINE
# ═══════════════════════════════════════════════════════════════════

def infer_epistemic_level(func: Callable) -> str:
    """
    Infer a tool's epistemic level from its Python signature.

    Rules (applied in order, first match wins):
      1. Non-deterministic keywords in name/params → ``doubt``
      2. Network/API keywords in name/params → ``speculate``
      3. Async function with storage keywords → ``speculate``
      4. Async function without pure keywords → ``believe``
      5. Pure computation keywords → ``know``
      6. Default → ``believe`` (conservative)

    Returns:
        One of: "know", "believe", "speculate", "doubt"
    """
    func_name = getattr(func, "__name__", "").lower()
    sig = inspect.signature(func)
    param_names = {p.lower() for p in sig.parameters}
    # Split compound names (compute_sum → {compute, sum, compute_sum})
    all_names: set[str] = set()
    for name in param_names | {func_name}:
        all_names.add(name)
        all_names.update(name.split("_"))

    # Rule 1: Non-deterministic keywords → doubt
    if all_names & _RANDOM_KEYWORDS:
        return "doubt"

    # Rule 2: Network/API keywords → speculate
    if all_names & _IO_KEYWORDS:
        return "speculate"

    # Rule 3: Async + storage → speculate
    is_async = asyncio.iscoroutinefunction(func) if _HAS_ASYNCIO else False
    if is_async and (all_names & _STORAGE_KEYWORDS):
        return "speculate"

    # Rule 4: Sync + pure keywords → know
    if not is_async and (all_names & _PURE_KEYWORDS):
        return "know"

    # Rule 5: Async without clear markers → believe (conservative)
    if is_async:
        return "believe"

    # Rule 6: Sync without clear markers → believe (conservative)
    return "believe"


def infer_effect_row(func: Callable) -> tuple[str, ...]:
    """
    Infer the effect row from a Python function's signature.

    Rules:
      1. Network/API keywords → ("io", "network")
      2. Storage keywords → ("io",)
      3. Random/model keywords → ("io",)
      4. Pure computation → ("pure",)
      5. Default → ("io",) (conservative — assume side effects)

    Returns:
        Tuple of effect names, e.g., ("io", "network")
    """
    func_name = getattr(func, "__name__", "").lower()
    sig = inspect.signature(func)
    param_names = {p.lower() for p in sig.parameters}
    # Split compound names (fetch_url → {fetch, url, fetch_url})
    all_names: set[str] = set()
    for name in param_names | {func_name}:
        all_names.add(name)
        all_names.update(name.split("_"))

    effects: list[str] = []

    if all_names & _IO_KEYWORDS:
        effects.extend(["io", "network"])
    elif all_names & _STORAGE_KEYWORDS:
        effects.append("io")
    elif all_names & _RANDOM_KEYWORDS:
        effects.append("io")  # model inference is I/O
    elif all_names & _PURE_KEYWORDS:
        effects.append("pure")
    else:
        effects.append("io")  # conservative default

    return tuple(sorted(set(effects)))


# Lazy asyncio import guard (for pure-sync contexts)
try:
    import asyncio
    _HAS_ASYNCIO = True
except ImportError:
    _HAS_ASYNCIO = False
