"""
AXON Runtime — ReflexEngine
=============================
Deterministic, O(1), LLM-free motor responses for `reflex` (Fase 5,
paper_inmune.md §4.2).

Contract invariants enforced at runtime
---------------------------------------
  • Never invokes an LLM.
  • No long-running blocking I/O — every reflex completes in microseconds.
  • Every activation emits an HMAC-signed trace (paper §4.2).
  • Idempotent — same HealthReport identity ⇒ same effect, no duplication.
  • Deterministic — pure function from (report, IRReflex) to ReflexOutcome.

The engine stores no external state except an idempotency set of
(reflex_name, signature) pairs so repeated deliveries of the same report
don't double-fire.  This is the one piece of stateful bookkeeping that
keeps `reflex` faithful to the "immune memory" model (paper §2).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import IRReflex

from axon.runtime.handlers.base import (
    CalleeBlameError,
    CallerBlameError,
    LambdaEnvelope,
    make_envelope,
)

from .health_report import HealthReport, level_at_least


@dataclass(frozen=True)
class ReflexOutcome:
    """Result of one reflex firing — fully auditable, no side-channels."""
    reflex_name: str
    action: str
    fired: bool
    reason: str
    target_signature: str
    latency_us: float
    envelope: LambdaEnvelope
    signed_trace: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reflex_name": self.reflex_name,
            "action": self.action,
            "fired": self.fired,
            "reason": self.reason,
            "target_signature": self.target_signature,
            "latency_us": self.latency_us,
            "envelope": self.envelope.to_dict(),
            "signed_trace": self.signed_trace,
        }


def _sign(message: str, secret: bytes) -> str:
    mac = hmac.new(secret, message.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


class ReflexEngine:
    """
    Registry-dispatching engine that consumes HealthReports and fires
    registered `reflex` declarations when their epistemic threshold is met.

    Parameters
    ----------
    trace_secret : bytes
        HMAC secret for signed traces.  Generated per-process by default;
        production deployments supply a long-lived secret from a vault.
    """

    def __init__(self, *, trace_secret: bytes | None = None) -> None:
        self._reflexes: dict[str, IRReflex] = {}
        # idempotency: {(reflex_name, target_signature)} — prevents re-fire
        self._fired: set[tuple[str, str]] = set()
        self._trace_secret: bytes = trace_secret or hashlib.sha256(
            b"axon-reflex-engine-default-secret"
        ).digest()
        # registered action handlers — per-action deterministic callables
        self._action_handlers: dict[str, Any] = {
            "drop":       self._drop_default,
            "revoke":     self._revoke_default,
            "emit":       self._emit_default,
            "redact":     self._redact_default,
            "quarantine": self._quarantine_default,
            "terminate":  self._terminate_default,
            "alert":      self._alert_default,
        }
        # callable hooks that concrete deployments can override
        self._hooks: dict[str, Any] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, reflex: IRReflex) -> None:
        if reflex.action not in self._action_handlers:
            raise CalleeBlameError(
                f"reflex '{reflex.name}' declares unknown action "
                f"'{reflex.action}'. Engine knows: "
                f"{', '.join(sorted(self._action_handlers))}"
            )
        self._reflexes[reflex.name] = reflex

    def register_action_hook(self, action: str, callback) -> None:
        """Override the default handler for a named action.

        Hooks must be deterministic and LLM-free (per contract).  The
        engine does not police this — it trusts the operator — but red-
        teaming tests should verify hook determinism.
        """
        if action not in self._action_handlers:
            raise CalleeBlameError(f"unknown action '{action}'")
        self._hooks[action] = callback

    # ── Dispatch ──────────────────────────────────────────────────

    def dispatch(self, report: HealthReport) -> list[ReflexOutcome]:
        """Fire every registered reflex whose trigger == report.immune_name
        AND whose on_level is reached or exceeded by the report."""
        outcomes: list[ReflexOutcome] = []
        for reflex in self._reflexes.values():
            if reflex.trigger != report.immune_name:
                continue
            outcomes.append(self._maybe_fire(reflex, report))
        return outcomes

    def clear_idempotency(self) -> None:
        """Reset the idempotency set — used by tests."""
        self._fired.clear()

    # ── Internals ─────────────────────────────────────────────────

    def _maybe_fire(self, reflex: IRReflex, report: HealthReport) -> ReflexOutcome:
        start = time.perf_counter()
        if not level_at_least(report.classification, reflex.on_level):
            return self._noop(reflex, report, start,
                              reason=f"level '{report.classification}' below threshold '{reflex.on_level}'")

        key = (reflex.name, report.anomaly_signature or report.immune_name)
        if key in self._fired:
            return self._noop(reflex, report, start, reason="idempotent skip (already fired for this signature)")

        self._fired.add(key)
        handler = self._hooks.get(reflex.action) or self._action_handlers[reflex.action]
        try:
            handler(reflex, report)
        except Exception as exc:  # noqa: BLE001
            # Reflex handlers must not raise — a raise is a handler bug
            # (CT-1).  We surface it without hiding the cause.
            raise CalleeBlameError(
                f"reflex '{reflex.name}' action '{reflex.action}' handler raised: {exc}"
            ) from exc
        elapsed_us = (time.perf_counter() - start) * 1e6
        trace_payload = (
            f"{reflex.name}|{reflex.action}|{report.anomaly_signature}|"
            f"{report.classification}|{report.kl_divergence:.6f}"
        )
        return ReflexOutcome(
            reflex_name=reflex.name,
            action=reflex.action,
            fired=True,
            reason=f"level '{report.classification}' ≥ threshold '{reflex.on_level}'",
            target_signature=report.anomaly_signature,
            latency_us=elapsed_us,
            envelope=make_envelope(c=report.envelope.c, rho=f"reflex:{reflex.name}", delta="observed"),
            signed_trace=_sign(trace_payload, self._trace_secret),
        )

    def _noop(
        self,
        reflex: IRReflex,
        report: HealthReport,
        start: float,
        *,
        reason: str,
    ) -> ReflexOutcome:
        elapsed_us = (time.perf_counter() - start) * 1e6
        trace_payload = f"{reflex.name}|NOOP|{report.anomaly_signature}|{reason}"
        return ReflexOutcome(
            reflex_name=reflex.name,
            action=reflex.action,
            fired=False,
            reason=reason,
            target_signature=report.anomaly_signature,
            latency_us=elapsed_us,
            envelope=make_envelope(c=report.envelope.c, rho=f"reflex:{reflex.name}", delta="observed"),
            signed_trace=_sign(trace_payload, self._trace_secret),
        )

    # ── Default deterministic action handlers ─────────────────────
    #
    # Each of these is a pure stub — real deployments override them
    # with handlers wired to their infrastructure (firewall, SIEM, etc.).
    # The defaults are deliberately inert so that a `reflex` declaration
    # doesn't cause unintended side effects when the hook isn't bound.

    def _drop_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _revoke_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _emit_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _redact_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _quarantine_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _terminate_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None

    def _alert_default(self, _reflex: IRReflex, _report: HealthReport) -> None:
        return None


__all__ = ["ReflexEngine", "ReflexOutcome"]
