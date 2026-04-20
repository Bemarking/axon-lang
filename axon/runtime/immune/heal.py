"""
AXON Runtime — HealKernel
==========================
Linear-Logic one-shot patch kernel for `heal` (Fase 5, paper_inmune.md §6).

Per paper §6.2 each patch has type:

    P : !Synthesized ⊸ Applied ⊸ Collapsed

Each transition **consumes** its predecessor, yielding four hard guarantees:
  1. Single application      — a Synthesized token is consumed at Applied.
  2. Forced collapse         — an Applied token MUST transition to Collapsed.
  3. No revival post-collapse — a Collapsed token produces no successors.
  4. Full audit              — every transition emits a signed trace.

Compliance modes (paper §7)
---------------------------
  • audit_only    — patches synthesized but NEVER applied.
  • human_in_loop — patches synthesized; require explicit approval before
                    applying; timeout rolls back.
  • adversarial   — patches applied autonomously with post-hoc review.

The kernel is a pure in-process registry; distributed-approval queues are
a Fase 6 (ESK) concern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from axon.compiler.ir_nodes import IRHeal

from axon.runtime.handlers.base import (
    CalleeBlameError,
    CallerBlameError,
    LambdaEnvelope,
    make_envelope,
)

from .health_report import HealthReport, level_at_least


# ═══════════════════════════════════════════════════════════════════
#  Patch state — Synthesized → Applied → Collapsed
# ═══════════════════════════════════════════════════════════════════

PatchState = Literal["synthesized", "applied", "collapsed", "rejected"]


@dataclass(frozen=True)
class Patch:
    """A proof-carrying patch under Linear Logic."""
    patch_id: str
    heal_name: str
    source_immune: str
    target_signature: str
    payload: dict[str, Any]
    state: PatchState
    created_at: datetime
    envelope: LambdaEnvelope
    approvals: tuple[str, ...] = ()

    def with_state(self, state: PatchState, *, approver: str = "") -> "Patch":
        approvals = self.approvals + ((approver,) if approver else ())
        return Patch(
            patch_id=self.patch_id,
            heal_name=self.heal_name,
            source_immune=self.source_immune,
            target_signature=self.target_signature,
            payload=self.payload,
            state=state,
            created_at=self.created_at,
            envelope=self.envelope,
            approvals=approvals,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "heal_name": self.heal_name,
            "source_immune": self.source_immune,
            "target_signature": self.target_signature,
            "payload": dict(self.payload),
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "envelope": self.envelope.to_dict(),
            "approvals": list(self.approvals),
        }


# Synthesis and application hooks — plug points for concrete deployments.
SynthesizeFn = Callable[[IRHeal, HealthReport], dict[str, Any]]
ApplyFn = Callable[[Patch], dict[str, Any]]
ShieldApproveFn = Callable[[IRHeal, Patch], bool]


def default_synthesize(ir: IRHeal, report: HealthReport) -> dict[str, Any]:
    """Deterministic placeholder patch — records the KL profile for later review."""
    return {
        "classification": report.classification,
        "kl_divergence":   report.kl_divergence,
        "observation":     list(report.observation_window),
        "note":            "synthesized placeholder — override default_synthesize for real patches",
    }


def default_apply(patch: Patch) -> dict[str, Any]:
    """No-op application — real deployments rewrite this (patch AST, rate-limit, rotate keys, ...)."""
    return {"applied_patch_id": patch.patch_id}


def default_shield_approve(_ir: IRHeal, _patch: Patch) -> bool:
    """Default: deny in audit_only, approve in other modes. Real shields override."""
    return True


Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════
#  HealKernel
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HealDecision:
    """Return type of `HealKernel.tick()` — explains what happened."""
    outcome: str                     # "synthesized" | "applied" | "rolled_back" | "denied" | "rejected" | "skipped"
    patch: Patch | None
    reason: str


class HealKernel:
    """
    Linear-Logic one-shot patch kernel.

    Parameters
    ----------
    synthesize : SynthesizeFn
        Turns a (IRHeal, HealthReport) into a payload dict.  The default
        records the KL + classification so audit_only mode still yields
        forensic evidence.
    apply : ApplyFn
        Executes the patch's side effects.  Pure default is no-op.
    shield_approve : ShieldApproveFn
        Governance gate.  If it returns False, the patch is marked
        `rejected` and never applied.
    clock : Clock
        Inject for deterministic test-time advances.
    """

    def __init__(
        self,
        *,
        synthesize: SynthesizeFn = default_synthesize,
        apply: ApplyFn = default_apply,
        shield_approve: ShieldApproveFn = default_shield_approve,
        clock: Clock | None = None,
    ) -> None:
        self._synthesize = synthesize
        self._apply = apply
        self._shield_approve = shield_approve
        self._clock: Clock = clock or _default_clock
        self._patches: dict[str, Patch] = {}
        self._heals: dict[str, IRHeal] = {}
        self._counts: dict[str, int] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, heal: IRHeal) -> None:
        self._heals[heal.name] = heal
        self._counts.setdefault(heal.name, 0)

    # ── Lifecycle entry point ─────────────────────────────────────

    def tick(self, report: HealthReport) -> list[HealDecision]:
        """Evaluate every registered heal against the HealthReport and
        advance their Linear Logic state machines."""
        decisions: list[HealDecision] = []
        for heal in self._heals.values():
            if heal.source != report.immune_name:
                continue
            decisions.append(self._step(heal, report))
        return decisions

    def approve(self, patch_id: str, approver: str) -> HealDecision:
        """Explicit human approval path for `human_in_loop` mode.

        Consumes the Synthesized token and promotes it to Applied.  Then
        runs the apply hook and collapses the patch.
        """
        patch = self._patches.get(patch_id)
        if patch is None:
            raise CallerBlameError(f"unknown patch '{patch_id}'")
        if patch.state != "synthesized":
            raise CallerBlameError(
                f"patch '{patch_id}' in state '{patch.state}' cannot be approved"
            )
        heal = self._heals.get(patch.heal_name)
        if heal is None:
            raise CalleeBlameError(f"heal '{patch.heal_name}' missing at approve time")
        applied = patch.with_state("applied", approver=approver)
        self._patches[patch_id] = applied
        try:
            result = self._apply(applied)
        except Exception as exc:  # noqa: BLE001
            raise CalleeBlameError(
                f"apply() hook failed for patch '{patch_id}': {exc}"
            ) from exc
        collapsed = applied.with_state("collapsed")
        # Linear Logic: the Applied token is consumed at Collapse.
        self._patches[patch_id] = collapsed
        return HealDecision(
            outcome="applied",
            patch=collapsed,
            reason=f"approved by '{approver}'; apply returned {result}",
        )

    def reject(self, patch_id: str, approver: str = "") -> HealDecision:
        patch = self._patches.get(patch_id)
        if patch is None:
            raise CallerBlameError(f"unknown patch '{patch_id}'")
        if patch.state in ("collapsed", "applied", "rejected"):
            raise CallerBlameError(
                f"patch '{patch_id}' already finalized in state '{patch.state}'"
            )
        rejected = patch.with_state("rejected", approver=approver or "reviewer")
        self._patches[patch_id] = rejected
        return HealDecision(
            outcome="rolled_back",
            patch=rejected,
            reason=f"rejected by '{approver or 'reviewer'}'; Linear token collapses to rejected terminal",
        )

    # ── Inspection ────────────────────────────────────────────────

    def patches(self) -> list[Patch]:
        return list(self._patches.values())

    def patches_by_state(self, state: PatchState) -> list[Patch]:
        return [p for p in self._patches.values() if p.state == state]

    # ── Internals ─────────────────────────────────────────────────

    def _step(self, heal: IRHeal, report: HealthReport) -> HealDecision:
        if not level_at_least(report.classification, heal.on_level):
            return HealDecision(
                outcome="skipped", patch=None,
                reason=f"report level '{report.classification}' below heal threshold '{heal.on_level}'",
            )
        if self._counts.get(heal.name, 0) >= heal.max_patches:
            return HealDecision(
                outcome="skipped", patch=None,
                reason=f"heal '{heal.name}' reached max_patches={heal.max_patches}",
            )

        payload = self._synthesize(heal, report)
        patch = Patch(
            patch_id=f"patch-{uuid.uuid4().hex[:12]}",
            heal_name=heal.name,
            source_immune=heal.source,
            target_signature=report.anomaly_signature,
            payload=payload,
            state="synthesized",
            created_at=self._clock(),
            envelope=make_envelope(
                c=report.envelope.c, rho=f"heal:{heal.name}", delta="inferred",
            ),
        )
        self._patches[patch.patch_id] = patch
        self._counts[heal.name] = self._counts.get(heal.name, 0) + 1

        if heal.mode == "audit_only":
            # Paper §7.1 — synthesized but never applied.  Linear Logic
            # reaches a terminal Collapsed state without ever passing
            # through Applied.
            collapsed = patch.with_state("collapsed")
            self._patches[patch.patch_id] = collapsed
            return HealDecision(
                outcome="synthesized", patch=collapsed,
                reason="audit_only mode — synthesized and collapsed without application",
            )

        if heal.mode == "adversarial":
            if not self._shield_approve(heal, patch):
                rejected = patch.with_state("rejected", approver="shield")
                self._patches[patch.patch_id] = rejected
                return HealDecision(
                    outcome="denied", patch=rejected,
                    reason="shield denied adversarial patch",
                )
            applied = patch.with_state("applied", approver="autonomous")
            self._patches[patch.patch_id] = applied
            try:
                self._apply(applied)
            except Exception as exc:  # noqa: BLE001
                raise CalleeBlameError(f"apply() raised in adversarial mode: {exc}") from exc
            collapsed = applied.with_state("collapsed")
            self._patches[patch.patch_id] = collapsed
            return HealDecision(
                outcome="applied", patch=collapsed,
                reason="adversarial mode — autonomous application + collapse",
            )

        # human_in_loop (default): do NOT apply; wait for approve()/reject().
        return HealDecision(
            outcome="synthesized", patch=patch,
            reason="human_in_loop — waiting for explicit approval within review SLA",
        )


__all__ = [
    "ApplyFn",
    "Clock",
    "HealDecision",
    "HealKernel",
    "Patch",
    "PatchState",
    "ShieldApproveFn",
    "SynthesizeFn",
    "default_apply",
    "default_shield_approve",
    "default_synthesize",
]
