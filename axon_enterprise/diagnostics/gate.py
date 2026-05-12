"""§Fase 29.f — Pure verdict logic for the vertical compliance gate.

D5 + D9 ratificadas 2026-05-12.

## What this module ships

The pure-function core of the CI compliance gate. Given a JSON
payload from ``/api/v1/tenant/diagnostics/recent`` + a
:class:`GateConfig`, returns a :class:`GateResult` that the CLI
projects onto an exit code.

The module deliberately has NO HTTP, NO subprocess, NO I/O — every
side effect is the caller's responsibility. This makes the verdict
unit-testable in pure form and re-usable from the HTTP CLI, from a
direct in-process call by another adopter integration, and from
future SaaS dashboard panels.

## D-letter trace

- **D5 ratificada** — enforcement happens at the CI integration
  layer (this CLI), NOT inside axon-lang. The OSS ``axon parse``
  contract (exit 0/1/2/3 over the bitwise diagnostic encoding)
  is preserved verbatim. This module reads the diagnostic dashboard
  payload AFTER axon-lang ran; axon-lang never sees the
  compliance threshold.

- **D9 ratificada** — adopters who don't install the gate get the
  OSS surface unchanged. Generic tenants whose dashboard returns
  empty entries pass every threshold trivially.

## Verdict catalog (closed enum)

:class:`GateVerdict` is a closed catalog of three outcomes:

==================== ===================================================
``PASS``             Diagnostic count below threshold; gate succeeds.
``FAIL_EXCEEDED``    Diagnostic count >= threshold; gate fails.
``FAIL_INPUT``       Payload didn't match the expected shape (parse
                     failure, missing fields). Surfaces as a
                     configuration error rather than a compliance
                     failure.
==================== ===================================================

The CLI projection maps PASS → exit 0; FAIL_EXCEEDED → exit 1;
FAIL_INPUT → exit 2 (configuration error). Transport-layer errors
(HTTP non-200, DNS failure) are handled by the CLI BEFORE the
payload reaches this module — they project to exit 2 as well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

# ──────────────────────────────────────────────────────────────────
#  Closed verdict catalog
# ──────────────────────────────────────────────────────────────────


class GateVerdict(StrEnum):
    """Closed catalog of gate outcomes. Adding a variant requires
    updating the CLI exit-code projection + the CI workflow steps.
    """

    PASS = "pass"
    FAIL_EXCEEDED = "fail_exceeded"
    FAIL_INPUT = "fail_input"


# ──────────────────────────────────────────────────────────────────
#  Severity catalog (mirror of 29.c DiagnosticSeverity)
# ──────────────────────────────────────────────────────────────────


# Recognized severity slugs — entries with unknown slugs are still
# counted toward the total but cannot be filtered via the
# ``fail-on-warning`` toggle. Mirrors the 29.c
# :class:`DiagnosticSeverity` closed catalog.
_KNOWN_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "hint"})


# ──────────────────────────────────────────────────────────────────
#  Gate configuration
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GateConfig:
    """Adopter-supplied thresholds for the gate.

    Frozen + slots so a single config can be reused across multiple
    payloads (e.g. paginated fetches).

    Attributes:
        max_errors: Maximum ``error``-severity diagnostics before the
            gate fails. Default 0 (any error fails the gate).
        max_warnings: Maximum ``warning``-severity diagnostics before
            the gate fails. ``None`` (default) disables the warning
            threshold — warnings don't fail the gate.
        fail_on_hint: When True, any ``hint``-severity diagnostic
            fails the gate. Default False.
        require_mode: Required response mode (``"aggregated"`` or
            ``"raw"``). When set, FAIL_INPUT if the payload was
            served in the other mode (defensive — protects against
            an unexpected server-side default change).
    """

    max_errors: int = 0
    max_warnings: int | None = None
    fail_on_hint: bool = False
    require_mode: str | None = None


# ──────────────────────────────────────────────────────────────────
#  Gate result
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SeverityCounts:
    """Counts of diagnostics by severity. Source for the human
    summary printed by the CLI.
    """

    errors: int = 0
    warnings: int = 0
    hints: int = 0
    unknown: int = 0

    @property
    def total(self) -> int:
        return self.errors + self.warnings + self.hints + self.unknown


@dataclass(frozen=True, slots=True)
class GateResult:
    """Result of evaluating one diagnostic payload against a
    :class:`GateConfig`. Includes the verdict + the severity
    breakdown + a human-readable reason string the CLI prints.

    Per D4 (29.e) the result NEVER carries source text — only
    structural counts + thresholds.
    """

    verdict: GateVerdict
    counts: SeverityCounts
    reason: str
    tenant_id: str | None = None
    vertical: str | None = None
    mode: str | None = None
    threshold_breached: str | None = None  # "errors" / "warnings" / "hints"

    @property
    def passed(self) -> bool:
        return self.verdict is GateVerdict.PASS

    @property
    def exit_code(self) -> int:
        """CLI exit-code projection. Closed mapping:

        - PASS → 0
        - FAIL_EXCEEDED → 1
        - FAIL_INPUT → 2 (configuration / transport error class)
        """
        if self.verdict is GateVerdict.PASS:
            return 0
        if self.verdict is GateVerdict.FAIL_EXCEEDED:
            return 1
        return 2


# ──────────────────────────────────────────────────────────────────
#  Severity counting
# ──────────────────────────────────────────────────────────────────


def _count_severities(entries: list[Mapping[str, Any]], mode: str) -> SeverityCounts:
    """Count diagnostics by severity across the payload.

    Aggregated-mode entries carry a ``count`` field (the number of
    raw diagnostics that collapsed into the group); raw-mode entries
    represent a single diagnostic each.

    Aggregated entries lack a per-record ``severity`` field; in that
    case ALL aggregated entries are counted as ``error`` severity
    (the OSS parser baseline + the conservative default). Adopters
    needing severity-aware aggregated counts can request raw mode.
    """
    errors = warnings = hints = unknown = 0
    if mode == "raw":
        for entry in entries:
            severity = str(entry.get("severity", "")).lower()
            if severity == "error":
                errors += 1
            elif severity == "warning":
                warnings += 1
            elif severity == "hint":
                hints += 1
            else:
                unknown += 1
    else:
        # Aggregated mode: count the group's `count` field as errors
        # (conservative default; severity granularity requires raw
        # mode per the dashboard contract from 29.e).
        for entry in entries:
            raw_count = entry.get("count", 0)
            try:
                count_int = int(raw_count)
            except (TypeError, ValueError):
                count_int = 0
            errors += max(0, count_int)
    return SeverityCounts(
        errors=errors,
        warnings=warnings,
        hints=hints,
        unknown=unknown,
    )


# ──────────────────────────────────────────────────────────────────
#  Verdict evaluator
# ──────────────────────────────────────────────────────────────────


def evaluate(
    payload: Mapping[str, Any],
    config: GateConfig | None = None,
) -> GateResult:
    """Evaluate a dashboard payload against ``config``. Pure function;
    no I/O.

    Returns a :class:`GateResult` whose :attr:`GateResult.exit_code`
    the CLI maps to a process exit code.

    ``payload`` is the JSON object the
    ``/api/v1/tenant/diagnostics/recent`` endpoint returns:

    .. code-block:: json

        {
          "tenant_id": "...",
          "vertical": "...",
          "mode": "aggregated" | "raw",
          "entries": [...]
        }

    Missing / malformed fields produce :attr:`GateVerdict.FAIL_INPUT`
    rather than raising — the CLI surfaces a configuration error
    rather than crashing.
    """
    config = config or GateConfig()

    if not isinstance(payload, Mapping):
        return GateResult(
            verdict=GateVerdict.FAIL_INPUT,
            counts=SeverityCounts(),
            reason="payload is not a JSON object",
        )

    tenant_id = payload.get("tenant_id")
    vertical = payload.get("vertical")
    mode_raw = payload.get("mode", "")
    mode = str(mode_raw).lower() if mode_raw else ""

    if mode not in {"aggregated", "raw"}:
        return GateResult(
            verdict=GateVerdict.FAIL_INPUT,
            counts=SeverityCounts(),
            reason=f"payload.mode must be 'aggregated' or 'raw', got {mode_raw!r}",
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
        )

    if config.require_mode is not None and config.require_mode != mode:
        return GateResult(
            verdict=GateVerdict.FAIL_INPUT,
            counts=SeverityCounts(),
            reason=(
                f"required mode {config.require_mode!r} but payload mode is "
                f"{mode!r}"
            ),
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
            mode=mode,
        )

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return GateResult(
            verdict=GateVerdict.FAIL_INPUT,
            counts=SeverityCounts(),
            reason="payload.entries must be a JSON array",
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
            mode=mode,
        )

    # Filter to mappings only (defensive — heterogeneous entry shape).
    entries: list[Mapping[str, Any]] = [
        e for e in raw_entries if isinstance(e, Mapping)
    ]

    counts = _count_severities(entries, mode)

    # Threshold checks — error first (most common adopter target),
    # then warnings, then hints.
    if counts.errors > config.max_errors:
        return GateResult(
            verdict=GateVerdict.FAIL_EXCEEDED,
            counts=counts,
            reason=(
                f"errors={counts.errors} exceeds threshold "
                f"max_errors={config.max_errors}"
            ),
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
            mode=mode,
            threshold_breached="errors",
        )

    if config.max_warnings is not None and counts.warnings > config.max_warnings:
        return GateResult(
            verdict=GateVerdict.FAIL_EXCEEDED,
            counts=counts,
            reason=(
                f"warnings={counts.warnings} exceeds threshold "
                f"max_warnings={config.max_warnings}"
            ),
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
            mode=mode,
            threshold_breached="warnings",
        )

    if config.fail_on_hint and counts.hints > 0:
        return GateResult(
            verdict=GateVerdict.FAIL_EXCEEDED,
            counts=counts,
            reason=f"hints={counts.hints} > 0 and fail_on_hint=True",
            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
            vertical=vertical if isinstance(vertical, str) else None,
            mode=mode,
            threshold_breached="hints",
        )

    # Pass: every threshold honored.
    reason = (
        f"errors={counts.errors} <= max_errors={config.max_errors}"
    )
    if config.max_warnings is not None:
        reason += f"; warnings={counts.warnings} <= max_warnings={config.max_warnings}"
    if config.fail_on_hint:
        reason += f"; hints={counts.hints} == 0"
    return GateResult(
        verdict=GateVerdict.PASS,
        counts=counts,
        reason=reason,
        tenant_id=tenant_id if isinstance(tenant_id, str) else None,
        vertical=vertical if isinstance(vertical, str) else None,
        mode=mode,
    )


# ──────────────────────────────────────────────────────────────────
#  Human-friendly summary projector
# ──────────────────────────────────────────────────────────────────


def format_summary(result: GateResult) -> str:
    """Render a multi-line human summary the CLI prints on stdout.

    Format (D4-safe — no source text):

    ::

        axon-enterprise-ci-gate: <PASS|FAIL_EXCEEDED|FAIL_INPUT>
          tenant_id: <id-or-?>
          vertical:  <slug-or-?>
          mode:      <aggregated|raw-or-?>
          errors:    <N>
          warnings:  <N>
          hints:     <N>
          unknown:   <N>
        reason: <one-line>
    """
    lines = [
        f"axon-enterprise-ci-gate: {result.verdict.value.upper()}",
        f"  tenant_id: {result.tenant_id or '?'}",
        f"  vertical:  {result.vertical or '?'}",
        f"  mode:      {result.mode or '?'}",
        f"  errors:    {result.counts.errors}",
        f"  warnings:  {result.counts.warnings}",
        f"  hints:     {result.counts.hints}",
        f"  unknown:   {result.counts.unknown}",
        f"reason: {result.reason}",
    ]
    if result.threshold_breached:
        lines.append(f"breached_threshold: {result.threshold_breached}")
    return "\n".join(lines)


__all__ = [
    "GateConfig",
    "GateResult",
    "GateVerdict",
    "SeverityCounts",
    "evaluate",
    "format_summary",
]
