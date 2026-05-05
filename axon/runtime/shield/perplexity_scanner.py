"""
Perplexity strategy — entropy-based adversarial detection
(Fase 20.g).

Adversarial prompts (jailbreaks, gradient-crafted attacks like
GCG / AutoDAN, encoded payloads) tend to have **higher perplexity**
than natural language under the base model — they're statistically
unusual sequences that don't fit normal training-distribution
phrasing. Computing per-token log-probabilities and aggregating
gives a cheap signal that flags suspicious inputs without needing
a separate classifier.

**Hard limitation:** computing perplexity requires access to the
model's logits. The current Anthropic SDK does NOT expose logits;
neither do most managed inference APIs. Backends that DO expose
logits include OpenAI completions API (with ``logprobs``),
self-hosted vLLM / llama.cpp / Ollama, AWS Bedrock for some
models, and the Anthropic on-prem deployment.

So this scanner is **feature-flagged**: it activates only when the
configured backend (or an explicit ``perplexity_provider`` callable
in the shield config) can return token-level log-probabilities for
arbitrary text. When unavailable, the scan reports a **fail-safe
breach** with reason ``perplexity_unavailable`` so adopters who
declare ``strategy: perplexity`` against an Anthropic-bound flow
get a loud failure rather than silent passes — never a false
security guarantee.

Per the axon-enterprise charter: this OSS file ships the
arithmetic + the calling convention. Vertical perplexity
calibrations (HIPAA-grade thresholds derived from medical-domain
text distributions, legal-document baselines) live in
axon-enterprise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  PROVIDER PROTOCOL
# ═══════════════════════════════════════════════════════════════════
#
# A perplexity provider is a callable that takes a string and
# returns its per-token log-probabilities. Adopters wire one of
# these in the shield config when their backend supports it.

PerplexityProvider = Callable[[str], Sequence[float]]


# ═══════════════════════════════════════════════════════════════════
#  CALCULATION
# ═══════════════════════════════════════════════════════════════════


def _perplexity_from_logprobs(logprobs: Sequence[float]) -> float:
    """Standard perplexity = exp(-mean(log_probs)). Returns
    ``float('inf')`` for an empty sequence (no tokens → cannot
    score → treat as max-suspicious)."""
    if not logprobs:
        return float("inf")
    mean_logp = sum(logprobs) / len(logprobs)
    # Clamp to avoid overflow on very-low-probability sequences.
    return math.exp(min(-mean_logp, 700.0))


# ═══════════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PerplexityScanner:
    """Computes perplexity of the target via the configured provider
    and flags high-perplexity strings as suspicious.

    Configuration via ``ScanContext.config``:

      * ``perplexity_provider`` (callable, REQUIRED) — a callable
        ``(text: str) -> Sequence[float]`` returning per-token
        log-probabilities.
      * ``perplexity_threshold`` (float, default 100.0) — perplexity
        above this counts as a breach. Calibrate per domain;
        natural English sits ~10–50, code ~3–8, adversarial often
        > 200.

    No provider configured ⇒ fail-safe breach.
    """

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"strategy": "perplexity"},
            )

        cfg = context.config or {}
        provider: PerplexityProvider | None = cfg.get("perplexity_provider")
        threshold = float(cfg.get("perplexity_threshold", 100.0))

        if provider is None:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=(
                    "perplexity_unavailable: no perplexity_provider "
                    "configured. Backends without logits exposure "
                    "(Anthropic SDK as of v1.14.0) cannot use this "
                    "strategy. Fall back to dual_llm + classifier "
                    "or pass an explicit provider. Fail-safe default "
                    "= breach."
                ),
                detail={"strategy": "perplexity", "stage": "config"},
            )

        try:
            logprobs = provider(target)
        except Exception as exc:  # pragma: no cover — adopter provider errors
            return ScanResult(
                passed=False, confidence=1.0,
                reason=(
                    f"perplexity_provider error: "
                    f"{type(exc).__name__}: {exc}"
                ),
                detail={
                    "strategy": "perplexity",
                    "stage": "provider_call",
                    "exc_type": type(exc).__name__,
                },
            )

        ppl = _perplexity_from_logprobs(list(logprobs))
        passed = ppl < threshold

        # Confidence: log-distance from threshold, normalised.
        # Far from threshold (either side) → high confidence;
        # near threshold → low confidence.
        if ppl == float("inf"):
            confidence = 1.0
        else:
            confidence = min(
                abs(math.log10(max(ppl, 1e-6) / threshold)) * 0.5,
                1.0,
            )

        return ScanResult(
            passed=passed,
            confidence=confidence,
            reason=(
                f"perplexity={ppl:.2f} "
                f"{'<' if passed else '>='} threshold={threshold}"
            ),
            detail={
                "strategy": "perplexity",
                "category": context.category,
                "perplexity": (
                    round(ppl, 4) if ppl != float("inf") else "inf"
                ),
                "threshold": threshold,
                "token_count": len(list(logprobs)),
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


def _register_oss_perplexity() -> None:
    """Register the perplexity scanner under the categories where
    it's the most informative (prompt_injection + jailbreak —
    adversarial prompts are the canonical perplexity-anomaly
    target)."""
    scanner = PerplexityScanner()
    for category in ("prompt_injection", "jailbreak"):
        default_registry.register(
            category, scanner, strategy="perplexity",
        )


_register_oss_perplexity()


__all__ = [
    "PerplexityProvider",
    "PerplexityScanner",
]
