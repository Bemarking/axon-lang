"""
AXON Runtime — Epistemic Intrusion Detector (ESK Fase 6.7)
=============================================================
Extends Fase 5's `immune` sensor with Free-Energy spikes + shield routing
to detect intrusions at the semantic layer (not just signatures).

An IDS based on signatures (Snort, Suricata) is blind to zero-day
patterns with no prior signature.  The EID operates on the HealthReport
stream from `immune`: any spike in the free-energy proxy (KL) crossing
the intrusion threshold is classified as an EID event, routed through
the shield gate, and recorded in the ESK provenance chain.

This gives us:
  • Signature-free detection — behavioural anomaly is the signal.
  • Cryptographic forensics — every event lands in the ProvenanceChain.
  • Shield-gated response — compliance modes (audit / human-in-loop /
    adversarial) apply uniformly to immune and intrusion events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from axon.runtime.handlers.base import (
    CallerBlameError,
    InfrastructureBlameError,
    LambdaEnvelope,
    make_envelope,
    now_iso,
)
from axon.runtime.immune import HealthReport, level_at_least

from .provenance import ProvenanceChain, SignedEntry


# ═══════════════════════════════════════════════════════════════════
#  Intrusion event
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IntrusionEvent:
    """One EID activation — what happened, why, and with what evidence."""
    immune_name: str
    classification: str              # matches HealthReport.classification
    kl_divergence: float
    severity: str                    # low | medium | high | critical
    signature: str                   # anomaly_signature from the HealthReport
    shield_verdict: str              # approved | denied | deferred
    chain_entry: SignedEntry | None  # provenance anchor, if chain enabled
    envelope: LambdaEnvelope

    def to_dict(self) -> dict[str, Any]:
        return {
            "immune_name":     self.immune_name,
            "classification":  self.classification,
            "kl_divergence":   self.kl_divergence,
            "severity":        self.severity,
            "signature":       self.signature,
            "shield_verdict":  self.shield_verdict,
            "chain_index":     self.chain_entry.index if self.chain_entry else None,
            "chain_hash":      self.chain_entry.chain_hash if self.chain_entry else "",
            "envelope":        self.envelope.to_dict(),
        }


# ═══════════════════════════════════════════════════════════════════
#  Severity mapping
# ═══════════════════════════════════════════════════════════════════

def _severity_for(level: str, kl: float) -> str:
    if level == "doubt" or kl >= 0.95:
        return "critical"
    if level == "speculate" or kl >= 0.75:
        return "high"
    if level == "believe" or kl >= 0.45:
        return "medium"
    return "low"


# ═══════════════════════════════════════════════════════════════════
#  Shield gate protocol
# ═══════════════════════════════════════════════════════════════════

ShieldVerdictFn = Callable[[HealthReport, str], str]
"""
(health_report, severity) → 'approved' | 'denied' | 'deferred'

'deferred' signals human-in-loop review (SIEM queue); the EID still
records the event but does not act autonomously.
"""


def always_approve(_report: HealthReport, _severity: str) -> str:
    return "approved"


def always_defer(_report: HealthReport, _severity: str) -> str:
    return "deferred"


# ═══════════════════════════════════════════════════════════════════
#  EpistemicIntrusionDetector
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EpistemicIntrusionDetector:
    """EID wrapper that combines an immune HealthReport stream with a
    ProvenanceChain and a shield verdict function.

    `trigger_level` is the minimum epistemic level at which the EID
    records an event; by default `speculate` (any substantial drift).
    """

    trigger_level: str = "speculate"
    chain: ProvenanceChain | None = None
    shield_verdict: ShieldVerdictFn = field(default=always_approve)
    events: list[IntrusionEvent] = field(default_factory=list)

    def observe(self, report: HealthReport) -> IntrusionEvent | None:
        """Inspect a HealthReport.  Returns an IntrusionEvent iff the
        epistemic level is at or above `trigger_level`."""
        if not level_at_least(report.classification, self.trigger_level):
            return None

        severity = _severity_for(report.classification, report.kl_divergence)
        verdict = self.shield_verdict(report, severity)

        payload: dict[str, Any] = {
            "immune_name": report.immune_name,
            "classification": report.classification,
            "kl_divergence": report.kl_divergence,
            "severity": severity,
            "signature": report.anomaly_signature,
            "shield_verdict": verdict,
        }
        entry: SignedEntry | None = None
        if self.chain is not None:
            entry = self.chain.append(payload)

        event = IntrusionEvent(
            immune_name=report.immune_name,
            classification=report.classification,
            kl_divergence=report.kl_divergence,
            severity=severity,
            signature=report.anomaly_signature,
            shield_verdict=verdict,
            chain_entry=entry,
            envelope=make_envelope(
                c=report.envelope.c,
                rho=f"eid:{report.immune_name}",
                delta="observed",
                tau=now_iso(),
            ),
        )
        self.events.append(event)
        return event


__all__ = [
    "EpistemicIntrusionDetector",
    "IntrusionEvent",
    "ShieldVerdictFn",
    "always_approve",
    "always_defer",
]
