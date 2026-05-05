"""
Ensemble strategy — vote-based composition of N scanners
(Fase 20.h).

Ensemble runs multiple scanners (typically across different
strategies — pattern + classifier + dual_llm) on the same target
and aggregates the verdicts. The aggregation strategy is
configurable: ``majority`` (>50%), ``unanimous`` (all pass),
``threshold`` (>= K passing), or ``weighted`` (custom per-scanner
weights summed against a threshold).

This is the strategy enterprise overlays compose for
production-grade healthcare / legal / fintech configs:

    healthcare_ensemble = pattern (HIPAA bank)
                        + classifier (PHI BioBERT)
                        + dual_llm (HIPAA Security Rule judge)
                        with vote_strategy = threshold(2 of 3)

Per the axon-enterprise charter: this OSS file ships the ensemble
**operator** + the four built-in vote strategies. Vertical
**ensemble configs** (which scanners + thresholds + weights for
HIPAA / GDPR / MiFID II) live in axon-enterprise as named factories
that return preconfigured ensemble scanners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    ShieldScanner,
    ScannerCallable,
    default_registry,
    invoke_scanner,
)


# ═══════════════════════════════════════════════════════════════════
#  VOTE STRATEGIES
# ═══════════════════════════════════════════════════════════════════


def _majority_vote(results: list[ScanResult]) -> bool:
    """Pass iff strictly more than half the sub-scanners passed.
    Ties (even count, half-half) count as breach — fail-safe."""
    pass_count = sum(1 for r in results if r.passed)
    return pass_count * 2 > len(results)


def _unanimous_vote(results: list[ScanResult]) -> bool:
    """Pass iff EVERY sub-scanner passed. Most paranoid setting —
    a single dissent breaches."""
    return all(r.passed for r in results)


def _threshold_vote(results: list[ScanResult], k: int) -> bool:
    """Pass iff at least ``k`` sub-scanners passed. ``k`` is read
    from the shield config; defaults to ``len(results)`` when
    unset (degenerates to unanimous)."""
    pass_count = sum(1 for r in results if r.passed)
    return pass_count >= k


def _weighted_vote(
    results: list[ScanResult], weights: list[float], threshold: float,
) -> bool:
    """Pass iff the sum of weights of passing scanners >= threshold.
    Weights aligned to scanner order; missing weights default to
    1.0."""
    score = 0.0
    for i, r in enumerate(results):
        w = weights[i] if i < len(weights) else 1.0
        if r.passed:
            score += w
    return score >= threshold


# ═══════════════════════════════════════════════════════════════════
#  ENSEMBLE SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EnsembleScanner:
    """Composes a list of sub-scanners + a vote strategy.

    Construct with a list of ``(strategy_name, scanner)`` tuples; at
    scan time, runs each scanner with a derived context (same
    category, but `strategy` field reflects the sub-scanner's name
    for trace clarity) and aggregates.

    Configuration via ``ScanContext.config`` of the shield:

      * ``vote_strategy`` (str, default ``"majority"``) — one of
        ``majority`` / ``unanimous`` / ``threshold`` / ``weighted``.
      * ``vote_threshold`` (int) — required for ``threshold`` mode.
      * ``vote_weights`` (list[float]) — per-sub-scanner weights for
        ``weighted`` mode (parallel to the constructor's scanner
        list).
      * ``vote_weighted_threshold`` (float, default 0.5*sum(weights)) —
        cutoff for ``weighted`` mode.

    For the OSS auto-registered ensemble: composes the THREE
    deterministic strategies (pattern + classifier + dual_llm) when
    a Shield declares ``strategy: ensemble`` without further config.
    Adopters / enterprise overlays re-register their own composed
    EnsembleScanner under the same `(category, ensemble)` key.
    """

    sub_scanners: tuple[tuple[str, ShieldScanner | ScannerCallable], ...] = ()

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not self.sub_scanners:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=(
                    "ensemble_unconfigured: no sub-scanners registered. "
                    "Construct an EnsembleScanner with sub_scanners or "
                    "let the OSS auto-registration wire pattern + "
                    "classifier + dual_llm."
                ),
                detail={"strategy": "ensemble", "stage": "config"},
            )

        cfg = context.config or {}
        vote_strategy = cfg.get("vote_strategy", "majority")

        # Run each sub-scanner with a derived context that carries
        # its own strategy name for trace clarity.
        sub_results: list[ScanResult] = []
        sub_detail: list[dict[str, Any]] = []
        for sub_name, sub_scanner in self.sub_scanners:
            sub_ctx = ScanContext(
                flow_name=context.flow_name,
                shield_name=context.shield_name,
                category=context.category,
                strategy=sub_name,
                capabilities=context.capabilities,
                canary_tokens=context.canary_tokens,
                config=context.config,
            )
            try:
                r = invoke_scanner(sub_scanner, target, sub_ctx)
            except Exception as exc:  # pragma: no cover — sub-scanner failure
                # A sub-scanner crash counts as breach for that
                # sub — fail-safe. The aggregate still computes.
                r = ScanResult(
                    passed=False, confidence=0.0,
                    reason=(
                        f"sub-scanner {sub_name} raised "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    detail={"sub_strategy": sub_name, "error": True},
                )
            sub_results.append(r)
            sub_detail.append({
                "strategy": sub_name,
                "passed": r.passed,
                "confidence": r.confidence,
                "reason": r.reason[:120],
            })

        # Aggregate.
        if vote_strategy == "unanimous":
            passed = _unanimous_vote(sub_results)
        elif vote_strategy == "threshold":
            k = int(cfg.get("vote_threshold", len(sub_results)))
            passed = _threshold_vote(sub_results, k)
        elif vote_strategy == "weighted":
            weights = list(cfg.get("vote_weights", []))
            default_threshold = sum(weights) * 0.5 if weights else 0.5
            threshold = float(
                cfg.get("vote_weighted_threshold", default_threshold),
            )
            passed = _weighted_vote(sub_results, weights, threshold)
        else:  # majority (default + unknown fallback)
            vote_strategy = "majority"
            passed = _majority_vote(sub_results)

        pass_count = sum(1 for r in sub_results if r.passed)
        # Confidence: mean of sub-confidences weighted by agreement
        # with the verdict. High when scanners agree; low when split.
        agreeing = [r for r in sub_results if r.passed == passed]
        if agreeing:
            confidence = sum(r.confidence for r in agreeing) / len(agreeing)
        else:
            confidence = 0.5

        return ScanResult(
            passed=passed,
            confidence=confidence,
            reason=(
                f"ensemble {vote_strategy}: {pass_count}/{len(sub_results)} "
                f"sub-scanners passed"
            ),
            detail={
                "strategy": "ensemble",
                "category": context.category,
                "vote_strategy": vote_strategy,
                "pass_count": pass_count,
                "sub_count": len(sub_results),
                "sub_results": sub_detail,
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


def _register_oss_ensemble() -> None:
    """Auto-register a baseline ensemble that composes pattern +
    classifier + dual_llm for the categories where all three OSS
    baselines exist. Adopters / enterprise overlays shadow with
    their own composed configs.
    """
    # Categories where all three OSS sub-scanners are registered.
    common_categories = {
        "prompt_injection", "jailbreak", "data_exfil",
        "social_engineering",
    }

    for category in common_categories:
        # Look up the existing baselines (already auto-registered
        # by the per-strategy modules at import time).
        pattern = default_registry.lookup(category, "pattern")
        classifier = default_registry.lookup(category, "classifier")
        dual_llm = default_registry.lookup(category, "dual_llm")
        sub: list[tuple[str, Any]] = []
        if pattern is not None:
            sub.append(("pattern", pattern))
        if classifier is not None:
            sub.append(("classifier", classifier))
        if dual_llm is not None:
            sub.append(("dual_llm", dual_llm))
        if not sub:
            continue
        ensemble = EnsembleScanner(sub_scanners=tuple(sub))
        default_registry.register(
            category, ensemble, strategy="ensemble",
        )


_register_oss_ensemble()


__all__ = [
    "EnsembleScanner",
]
