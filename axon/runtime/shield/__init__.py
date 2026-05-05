"""
Shield runtime — production scanner implementations (Fase 20).

This package houses the OSS scanner implementations registered into
``axon.runtime.shield_scanners.default_registry`` at import time:

  * :mod:`axon.runtime.shield.pattern_scanner` (Fase 20.b) — regex
    against curated baseline threat catalogs.
  * :mod:`axon.runtime.shield.canary_scanner` (Fase 20.c) — per-flow
    canary token mint + leak detection.
  * :mod:`axon.runtime.shield.capability_scanner` (Fase 20.d) —
    ed25519 / HMAC / JWT capability token validation reusing the
    ContinuityToken signing infrastructure.
  * :mod:`axon.runtime.shield.classifier_scanner` (Fase 20.e) —
    HuggingFace embedding cosine; soft-dep on ``transformers``.
  * :mod:`axon.runtime.shield.dual_llm_scanner` (Fase 20.f) — judge
    LLM with rubric.
  * :mod:`axon.runtime.shield.perplexity_scanner` (Fase 20.g) —
    entropy threshold; feature-flagged when backend exposes logits.
  * :mod:`axon.runtime.shield.ensemble_scanner` (Fase 20.h) —
    composes N scanners with vote/threshold strategies.

Per the axon-enterprise charter (see
``memory/project_axon_enterprise_charter.md``), this package contains
OSS BASELINE scanners + GENERIC catalogs only. Vertical R&D
(HIPAA PHI patterns, legal privilege markers, fintech AML rules,
healthcare-grade ensemble configs) lives in the private
``axon-enterprise`` package and registers against the same registry
at import time.

Importing this package auto-registers the OSS baselines into
:data:`axon.runtime.shield_scanners.default_registry` — adopters who
construct a bare ``Executor(client=...)`` get pattern + canary +
capability_validate working without any setup.
"""

# Side-effectful imports: each module's import-time hook calls
# `default_registry.register(...)` for its baseline scanners. Order
# matters only for diagnostic clarity (later registrations shadow
# earlier under the same `(category, strategy)` key); the OSS
# baselines avoid collisions by design.
from axon.runtime.shield import (  # noqa: F401 — import for side effects
    pattern_scanner,
    canary_scanner,
    capability_scanner,
)


__all__ = [
    "pattern_scanner",
    "canary_scanner",
    "capability_scanner",
]
