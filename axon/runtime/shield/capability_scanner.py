"""
Capability validate strategy — D8 capability-gate cryptographic
verification (Fase 20.d).

Adds the ``capability_validate`` scan category to the threat
taxonomy and ships a baseline scanner that verifies HMAC-signed
capability tokens against a configured signer. Generalises the
existing allow/deny tool list (which only checks names, not
authenticity) into a cryptographic gate: adopters mint signed
capabilities upstream (typically via
:class:`ContinuityTokenSigner`), and the Shield rejects any token
that fails verification.

Two verification modes:

  1. **HMAC** (default, OSS) — reuses
     :class:`axon.runtime.pem.continuity_token.ContinuityTokenSigner`
     so adopters who already have a signer for ``hibernate`` can
     reuse it for capability validation. The Shield's ``config``
     dict carries the signer instance under
     ``capability_signer``.
  2. **ed25519 / JWT** — signature-only verification (no payload
     state), useful for capability tokens minted by an upstream
     IdP. Implementations live in axon-enterprise (vertical IdP
     integrations: Auth0, Okta, AWS IAM, Azure AD); the OSS
     baseline ships HMAC only.

The target inspected by the scanner is the capability token
itself — adopters typically place it in a context variable
(``$capability_token``) and reference it from the Shield
declaration.

Per the axon-enterprise charter: this OSS file ships the HMAC
verifier + the registration mechanism. Vertical token shapes
(JWT with custom claim sets, AWS STS sessions, OAuth introspection
endpoints) live in ``axon-enterprise`` and register against the
same registry under
``(category="capability_validate", strategy="ed25519")`` /
``"jwt"`` / etc.
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.runtime.pem.continuity_token import (
    ContinuityTokenError,
    ContinuityTokenSigner,
    TokenExpired,
    TokenForgedOrRotated,
    TokenMalformed,
)
from axon.runtime.shield_scanners import (
    ScanContext,
    ScanResult,
    default_registry,
)


# ═══════════════════════════════════════════════════════════════════
#  HMAC SCANNER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HmacCapabilityScanner:
    """Verify a capability token's HMAC signature using the
    :class:`ContinuityTokenSigner` configured on the Shield.

    The Shield declaration MUST place the signer (or its key) in
    ``ScanContext.config`` under one of:

      * ``capability_signer``: a live ``ContinuityTokenSigner``
        instance.
      * ``capability_key``: bytes; we construct a
        ``ContinuityTokenSigner(capability_key)`` on the fly.

    If neither is present, the scanner reports breach with reason
    ``signer_not_configured`` — fail-safe: an unconfigured
    capability gate must not silently let everything pass.
    """

    def scan(self, target: str, context: ScanContext) -> ScanResult:
        if not target:
            return ScanResult(
                passed=False, confidence=1.0,
                reason="empty capability token",
                detail={"verifier": "hmac"},
            )

        cfg = context.config or {}
        signer: ContinuityTokenSigner | None = cfg.get("capability_signer")
        if signer is None:
            key = cfg.get("capability_key")
            if isinstance(key, (bytes, bytearray)):
                signer = ContinuityTokenSigner(bytes(key))

        if signer is None:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=(
                    "capability_validate: no signer configured. "
                    "Set `capability_signer` or `capability_key` in "
                    "the Shield's config."
                ),
                detail={"verifier": "hmac", "stage": "config"},
            )

        try:
            verified = signer.verify(target)
        except TokenMalformed as exc:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=f"capability token malformed: {exc}",
                detail={"verifier": "hmac", "error_kind": "malformed"},
            )
        except TokenForgedOrRotated as exc:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=f"capability signature mismatch: {exc}",
                detail={"verifier": "hmac", "error_kind": "forged_or_rotated"},
            )
        except TokenExpired as exc:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=f"capability expired: {exc}",
                detail={"verifier": "hmac", "error_kind": "expired"},
            )
        except ContinuityTokenError as exc:
            return ScanResult(
                passed=False, confidence=1.0,
                reason=f"capability validation error: {exc}",
                detail={"verifier": "hmac", "error_kind": "other"},
            )

        return ScanResult(
            passed=True, confidence=1.0,
            reason="capability HMAC verified + not expired",
            detail={
                "verifier": "hmac",
                "session_id": verified.session_id,
                "expires_at": verified.expires_at.isoformat(),
            },
        )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


def _register_oss_capability() -> None:
    """Register the HMAC capability validator under
    ``(category="capability_validate", strategy="pattern")``.

    "pattern" is the strategy default the dispatcher falls back to
    when a Shield omits ``strategy:``; using it here means a Shield
    declared as ``shield CapGate { scan: [capability_validate] }``
    works without any extra configuration. Adopters / enterprise
    overlays that need ed25519 / JWT register additional strategies
    under the same category.
    """
    default_registry.register(
        "capability_validate", HmacCapabilityScanner(),
        strategy="pattern",
    )
    # Also register under the explicit "hmac" strategy alias so
    # adopters who write `strategy: hmac` get the right scanner.
    default_registry.register(
        "capability_validate", HmacCapabilityScanner(),
        strategy="hmac",
    )


_register_oss_capability()


__all__ = [
    "HmacCapabilityScanner",
]
