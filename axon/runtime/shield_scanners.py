"""
Shield scanner registry + pluggable scanner contract (Fase 20.a).

The TypeChecker has validated since Fase 11 that every Shield declares
one of 6 strategies (``pattern`` / ``classifier`` / ``dual_llm`` /
``canary`` / ``perplexity`` / ``ensemble``) and one of N scan
categories (``prompt_injection`` / ``jailbreak`` / ``data_exfil`` /
``pii_leak`` / ``toxicity`` / etc.). Pre-Fase-20, the runtime ignored
both — every shield trivially passed (``scan_passed = True``). This
module is the dispatch surface that closes that gap.

Architecture:

  * :class:`ShieldScanner` — Protocol that every scanner satisfies.
    A scanner inspects a string ``target`` against a ``ScanContext``
    (per-flow metadata + capabilities + canary tokens) and returns a
    :class:`ScanResult` (passed flag + confidence + reason string +
    structured detail).
  * :class:`ShieldScannerRegistry` — adopter-supplied lookup keyed by
    ``(category, strategy)``. Default :class:`InMemoryShieldRegistry`
    pre-populates the OSS baselines (pattern + canary +
    capability_validate) at construction time. Adopters add their own
    via :func:`register`; enterprise overlays plug in vertical
    scanners (HIPAA PHI, legal privilege, fintech AML — never
    published OSS per the axon-enterprise charter).
  * Per-charter SPLIT discipline: this module is OSS. The catalogs +
    pre-trained classifiers + curated judge prompts that fill the
    registry for healthcare / legal / fintech verticals live in the
    private ``axon-enterprise`` package and call ``register()`` at
    import time.

Out of scope for 20.a (covered in later sub-phases):

  * The 6 strategy implementations themselves (20.b–20.h). 20.a only
    ships the registry + Protocol + an empty default registry +
    Executor wiring; subsequent sub-phases call ``register()`` to
    populate the strategies.
  * Adversarial fuzz harness (20.i).
  * Drift gate that asserts every member of
    ``_VALID_SHIELD_STRATEGIES`` has at least one registered scanner
    (20.j).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ═══════════════════════════════════════════════════════════════════
#  SCAN CONTEXT + RESULT
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ScanContext:
    """Per-scan metadata handed to every scanner.

    Scanners inspect this rather than reaching into the global
    Executor state — keeps the contract testable + ensures scanners
    written by adopters cannot accidentally mutate the unit context.

    Fields:
        flow_name:        Name of the flow whose Shield is firing.
        shield_name:      Name of the Shield that triggered this scan.
        category:         The scan category being checked
                          (``prompt_injection`` / ``pii_leak`` / etc.).
        strategy:         The strategy the Shield declared
                          (``pattern`` / ``classifier`` / ``dual_llm``
                          / ``canary`` / ``perplexity`` / ``ensemble``).
        capabilities:     Capability tokens active for this flow.
                          Used by the ``capability_validate`` scanner
                          (Fase 20.d) to verify ed25519 / HMAC / JWT.
        canary_tokens:    Per-flow canary tokens injected by the
                          ``canary`` strategy (Fase 20.c). Scanners
                          look for these in the target as a data
                          exfil signal.
        config:           Strategy-specific config dict from the
                          shield declaration (e.g. ``threshold``,
                          ``judge_model``, ``vote_strategy``).
    """

    flow_name: str
    shield_name: str
    category: str
    strategy: str
    capabilities: tuple[str, ...] = ()
    canary_tokens: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Outcome of one scanner invocation.

    Scanners MUST return this — never raise to signal a breach. The
    Shield dispatcher inspects ``passed`` to decide the on_breach
    policy. Exceptions raised by a scanner indicate the scanner
    itself failed (model timeout / regex compile error / etc.) and
    are surfaced as ``AxonRuntimeError`` by the dispatcher, not as
    a breach.

    Fields:
        passed:      ``True`` iff the target survives the scan.
        confidence:  Score in [0.0, 1.0]. For pass: how confident the
                     scanner is that the target is clean. For breach:
                     how confident it is that a threat was detected.
        reason:      Human-readable explanation surfaced in the
                     trace event. Adopters debugging a false positive
                     read this first.
        detail:      Structured per-strategy data (e.g. matched
                     patterns, classifier scores, ensemble votes).
                     JSON-serialisable.
    """

    passed: bool
    confidence: float = 1.0
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
#  SCANNER PROTOCOL
# ═══════════════════════════════════════════════════════════════════


class ShieldScanner(Protocol):
    """Adopter-supplied scanner contract.

    Implementations may be regex matchers (``pattern`` strategy),
    LLM judges (``dual_llm``), HF classifier wrappers
    (``classifier``), or ensemble compositions (``ensemble``). The
    contract is intentionally minimal: take a ``target`` string +
    ``ScanContext``, return a ``ScanResult``. Stateful scanners
    (e.g. classifiers loading models) initialise lazily so the
    registry can be constructed cheaply at import time.

    Thread safety: the registry calls scanners concurrently when
    multiple Shield steps fire in a Par block. Implementations MUST
    be thread-safe or document otherwise (the registry currently
    does NOT serialise calls per scanner).
    """

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        """Inspect ``target`` against ``context``. Pure function:
        same input → same output. Side effects (model calls, audit
        emissions) are allowed but must not raise to signal a
        breach — return ``ScanResult(passed=False, ...)`` instead."""
        ...


# Functional alias: adopters who don't want to define a class can
# register a bare callable.
ScannerCallable = Callable[[str, ScanContext], ScanResult]


# ═══════════════════════════════════════════════════════════════════
#  REGISTRY PROTOCOL
# ═══════════════════════════════════════════════════════════════════


class ShieldScannerRegistry(Protocol):
    """Adopter-supplied lookup from ``(category, strategy)`` →
    ``ShieldScanner``.

    The default :class:`InMemoryShieldRegistry` pre-populates the OSS
    baselines (pattern + canary + capability_validate); enterprise
    overlays call :func:`register` at import time to add vertical
    catalogs (HIPAA PHI / legal privilege / fintech AML — those
    catalogs live in the private ``axon-enterprise`` package and are
    NEVER shipped here per the axon-enterprise charter).
    """

    def register(
        self, category: str, scanner: ShieldScanner | ScannerCallable,
        *, strategy: str = "pattern",
    ) -> None:
        """Register a scanner under ``(category, strategy)``. If a
        binding already exists, it's overwritten (last-registered
        wins — adopters can shadow defaults intentionally)."""
        ...

    def lookup(
        self, category: str, strategy: str,
    ) -> ShieldScanner | ScannerCallable | None:
        """Return the scanner for ``(category, strategy)`` or
        ``None`` if no binding exists. The Shield dispatcher
        treats ``None`` as a structured failure (loud
        ``AxonRuntimeError``) — never silently passes."""
        ...

    def known(self) -> dict[str, list[str]]:
        """Return a snapshot of registered ``{category: [strategy,
        ...]}``. Used by the drift gate (Fase 20.j) to assert every
        ``_VALID_SHIELD_STRATEGIES`` member has at least one
        registered category."""
        ...


# ═══════════════════════════════════════════════════════════════════
#  IN-MEMORY DEFAULT
# ═══════════════════════════════════════════════════════════════════


class InMemoryShieldRegistry:
    """Thread-safe in-memory implementation of
    :class:`ShieldScannerRegistry`.

    Suitable for OSS adopters and tests. Enterprise deployments
    typically inject an extended registry whose ``__init__`` calls
    ``register()`` for every vertical scanner the enterprise package
    ships.
    """

    __slots__ = ("_scanners", "_lock")

    def __init__(self) -> None:
        # Composite key: (category, strategy) → scanner. Composite
        # rather than nested dicts so lookup is a single hashed
        # access regardless of how many strategies a category has.
        self._scanners: dict[
            tuple[str, str], ShieldScanner | ScannerCallable,
        ] = {}
        self._lock = threading.Lock()

    def register(
        self, category: str, scanner: ShieldScanner | ScannerCallable,
        *, strategy: str = "pattern",
    ) -> None:
        if not category:
            raise ValueError("category must not be empty")
        if not strategy:
            raise ValueError("strategy must not be empty")
        if scanner is None:
            raise ValueError("scanner must not be None")
        with self._lock:
            self._scanners[(category, strategy)] = scanner

    def lookup(
        self, category: str, strategy: str,
    ) -> ShieldScanner | ScannerCallable | None:
        if not category or not strategy:
            return None
        with self._lock:
            return self._scanners.get((category, strategy))

    def has(self, category: str, strategy: str) -> bool:
        return self.lookup(category, strategy) is not None

    def known(self) -> dict[str, list[str]]:
        with self._lock:
            out: dict[str, list[str]] = {}
            for (category, strategy) in self._scanners:
                out.setdefault(category, []).append(strategy)
            for strategies in out.values():
                strategies.sort()
            return out

    def __len__(self) -> int:
        with self._lock:
            return len(self._scanners)


# ═══════════════════════════════════════════════════════════════════
#  CALL INVOCATION HELPER
# ═══════════════════════════════════════════════════════════════════


def invoke_scanner(
    scanner: ShieldScanner | ScannerCallable,
    target: str,
    context: ScanContext,
) -> ScanResult:
    """Invoke a registered scanner regardless of whether it's an
    object with a ``scan`` method (matches :class:`ShieldScanner`)
    or a bare callable. Lets adopters register either form without
    the dispatcher caring."""
    if hasattr(scanner, "scan"):
        return scanner.scan(target, context)  # type: ignore[union-attr]
    return scanner(target, context)  # type: ignore[operator]


# ═══════════════════════════════════════════════════════════════════
#  MODULE-LEVEL DEFAULT REGISTRY
# ═══════════════════════════════════════════════════════════════════
#
# Adopters who want process-global registration (the typical pattern
# — enterprise packages call `register()` at import time) use the
# module-level `default_registry`. Adopters who want per-Executor
# isolation construct their own and inject via Executor.__init__.

default_registry: ShieldScannerRegistry = InMemoryShieldRegistry()


__all__ = [
    "InMemoryShieldRegistry",
    "ScanContext",
    "ScanResult",
    "ScannerCallable",
    "ShieldScanner",
    "ShieldScannerRegistry",
    "default_registry",
    "invoke_scanner",
]


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTER OSS BASELINES
# ═══════════════════════════════════════════════════════════════════
#
# Trigger the side-effectful import of the shield/ package so each
# baseline scanner module (pattern_scanner / canary_scanner /
# capability_scanner) calls `default_registry.register()` at module
# load time. Adopters constructing a bare ``Executor(client=...)``
# get the OSS baselines without having to manually import anything.
#
# This import sits AFTER `default_registry` is defined so the
# baseline modules can find it during their own load. Standard
# Python import semantics handle the partial-module case correctly
# because every symbol the baselines need is defined above this
# line.
#
# Adopters / enterprise overlays that want to override an OSS
# default register their own scanner under the same
# `(category, strategy)` key — last registration wins.
from axon.runtime import shield as _shield_baselines  # noqa: E402,F401
