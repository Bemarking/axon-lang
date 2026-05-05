"""
Canary strategy — per-flow canary tokens + leak detection
(Fase 20.c).

Canary tokens are short, unique strings injected into the model's
context (typically as part of a system prompt or as decoy data) that
should NEVER appear in normal outputs. If the target contains a
canary token, the scanner reports a breach — the model has leaked
private context, which is a strong signal of data exfiltration or
prompt injection success.

Two sources of canary tokens this scanner inspects:

  1. **Per-scan tokens**: passed via ``ScanContext.canary_tokens``.
     Adopters wire these by calling
     ``ctx.set_variable("__canary_tokens__", [...])`` before the
     shield step, or by registering a custom scanner that derives
     them from another source.
  2. **OSS baseline pattern**: matches strings shaped
     ``AXON_CANARY_<32-hex>`` — the canonical prefix the AXON
     runtime mints when the scanner is asked to generate one. This
     catches accidental leaks even when an adopter forgets to
     register their tokens explicitly.

What is NOT in this OSS file (per the axon-enterprise charter):

  * Vertical canary catalogs (HIPAA test patient names, legal
    fictitious party names, fintech synthetic account numbers).
  * Steganographic canaries (zero-width joiners, homoglyphs) —
    those live in axon-enterprise where the cultural / linguistic
    review can be done.

Mint helper :func:`mint_canary_token` is exposed for adopters who
want to generate fresh tokens programmatically.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  TOKEN MINTING
# ═══════════════════════════════════════════════════════════════════


_CANARY_PREFIX = "AXON_CANARY_"
_CANARY_HEX_LENGTH = 32
_CANARY_PATTERN = re.compile(
    rf"\b{re.escape(_CANARY_PREFIX)}[0-9a-f]{{{_CANARY_HEX_LENGTH}}}\b",
)


def mint_canary_token() -> str:
    """Mint a fresh canary token. Tokens are 32-hex-char suffixes —
    128 bits of entropy, sufficient that a collision against an
    accidentally-canary-shaped string in user content is
    cryptographically negligible."""
    return f"{_CANARY_PREFIX}{secrets.token_hex(_CANARY_HEX_LENGTH // 2)}"


# ═══════════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CanaryScanner:
    """Looks for canary tokens in the target. Pass = no leak; breach
    = at least one canary appeared.

    Confidence is binary: 1.0 on breach (any leaked canary is a
    deterministic signal), 1.0 on pass (the absence of a known
    pattern is also deterministic).
    """

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="empty target",
                detail={"matches": [], "tokens_checked": 0},
            )

        matches: list[dict[str, str]] = []

        # Source 1 — explicit canary tokens passed via ScanContext.
        for token in context.canary_tokens:
            if not token:
                continue
            idx = target.find(token)
            if idx != -1:
                matches.append({
                    "source": "context_canary_tokens",
                    "token": token,
                    "position": str(idx),
                })

        # Source 2 — OSS baseline pattern (AXON_CANARY_<32-hex>).
        # Catches leaks even when the adopter forgot to register
        # their tokens, since any AXON-minted canary follows this
        # shape.
        for m in _CANARY_PATTERN.finditer(target):
            matches.append({
                "source": "axon_canary_pattern",
                "token": m.group(0),
                "position": str(m.start()),
            })

        tokens_checked = len(context.canary_tokens) + 1  # +1 for the AXON pattern source

        if not matches:
            return ScanResult(
                passed=True, confidence=1.0,
                reason="no canary tokens leaked",
                detail={
                    "matches": [],
                    "tokens_checked": tokens_checked,
                },
            )

        return ScanResult(
            passed=False, confidence=1.0,
            reason=(
                f"{len(matches)} canary token(s) leaked — first hit: "
                f"{matches[0]['source']} at position {matches[0]['position']}"
            ),
            detail={
                "match_count": len(matches),
                "matches": matches[:10],
                "tokens_checked": tokens_checked,
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════
#
# Canary as a strategy applies to the data_exfil category by default
# — it's the most natural fit. Adopters can also register
# CanaryScanner under any other category (e.g. "pii_leak") if they
# embed canary tokens in PII fields specifically.

def _register_oss_canary() -> None:
    scanner = CanaryScanner()
    default_registry.register("data_exfil", scanner, strategy="canary")
    # Also register canary as a fallback strategy under prompt_injection
    # because adopters often canary the system prompt (if a canary
    # from the system prompt appears in the model output, prompt
    # injection has succeeded).
    default_registry.register(
        "prompt_injection", scanner, strategy="canary",
    )


_register_oss_canary()


__all__ = [
    "CanaryScanner",
    "mint_canary_token",
]
