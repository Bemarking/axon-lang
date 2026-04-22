"""
AXON Compiler — Fase 11.a refinement + stream flow-level checks.
================================================================

Python mirror of the Rust pass in ``axon-rs/src/type_checker.rs``
(methods ``check_refinement_and_stream_contracts`` and friends).

The two implementations MUST agree on which programs pass. The
parity test suite asserts equality of diagnostics between Rust and
Python on every sample in ``tests/parity/``.

This module is consumed by ``axon/compiler/type_checker.py`` as a
post-pass: after per-declaration checks, we walk every flow and
enforce:

1. A flow using ``Stream[T]`` in its signature must reach at least
   one tool declaring a ``stream:<policy>`` effect from the closed
   :data:`~axon.runtime.stream_primitive.BACKPRESSURE_CATALOG`.
2. A flow accepting ``Untrusted[T]`` in its signature must reach
   at least one tool declaring a ``trust:<proof>`` effect from the
   closed :data:`~axon.runtime.trust.TRUST_CATALOG`.

"Reach" is a conservative approximation: we scan the flow body
recursively and collect the ``apply_ref`` / ``navigate_ref`` of
every ``StepNode``. Full dataflow analysis lives in future 11.a
follow-ups; the conservative pass still catches the "I wrote a
Stream-consuming flow and forgot the backpressure handler" case,
which is the load-bearing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from axon.runtime.stream_primitive import BACKPRESSURE_CATALOG
from axon.runtime.trust import TRUST_CATALOG

# Mirror the Rust constants so Python code doesn't have to import two
# places. Same STRING VALUES — the source of truth is still the
# runtime module.
STREAM_TYPE_CTOR = "Stream"
TRUSTED_TYPE_CTOR = "Trusted"
UNTRUSTED_TYPE_CTOR = "Untrusted"


def is_stream_type(type_name: str) -> bool:
    return type_name == STREAM_TYPE_CTOR


def is_refinement_type(type_name: str) -> bool:
    return type_name in (TRUSTED_TYPE_CTOR, UNTRUSTED_TYPE_CTOR)


def is_untrusted_type(type_name: str) -> bool:
    return type_name == UNTRUSTED_TYPE_CTOR


def is_trusted_type(type_name: str) -> bool:
    return type_name == TRUSTED_TYPE_CTOR


# ── Diagnostic type ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RefinementDiagnostic:
    """One compiler error emitted by the Fase 11.a pass."""

    message: str
    line: int
    column: int = 0


# ── Pure helpers (testable without the AST) ──────────────────────────


def classify_effect(effect: str) -> tuple[str, str | None]:
    """Split ``name:qualifier`` into ``(name, qualifier)``.

    Composite effect names are the convention the existing Rust
    type-checker already uses for ``io:network`` / ``storage:kv``
    etc. Fase 11.a adds ``stream:<policy>`` and ``trust:<proof>``.
    """
    base, sep, qualifier = effect.partition(":")
    return (base, qualifier if sep else None)


def effect_carries_backpressure(effect: str) -> bool:
    base, qual = classify_effect(effect)
    return base == "stream" and qual is not None and qual in BACKPRESSURE_CATALOG


def effect_carries_trust_proof(effect: str) -> bool:
    base, qual = classify_effect(effect)
    return base == "trust" and qual is not None and qual in TRUST_CATALOG


def tool_declares_backpressure(effects: Iterable[str]) -> bool:
    return any(effect_carries_backpressure(e) for e in effects)


def tool_declares_trust_proof(effects: Iterable[str]) -> bool:
    return any(effect_carries_trust_proof(e) for e in effects)


# ── Flow-level check (AST-shaped) ────────────────────────────────────


def check_flow_refinement_and_stream(
    *,
    flow_name: str,
    flow_loc_line: int,
    flow_loc_column: int,
    param_type_names: Iterable[str],
    return_type_name: str | None,
    apply_refs: Iterable[str],
    tool_effects_by_name: Mapping[str, Iterable[str]],
) -> list[RefinementDiagnostic]:
    """Run the §Fase 11.a flow-level pass.

    Arguments mirror the subset of the AST the pass actually needs —
    we take the project-specific AST node apart at the call site in
    ``type_checker.py``, then feed this function plain strings. That
    keeps this module free of AST dependencies and directly unit-
    testable.

    Returns a list of :class:`RefinementDiagnostic` — empty on success.
    """
    uses_stream = any(is_stream_type(t) for t in param_type_names)
    if return_type_name is not None and is_stream_type(return_type_name):
        uses_stream = True
    uses_untrusted = any(is_untrusted_type(t) for t in param_type_names)

    if not uses_stream and not uses_untrusted:
        return []

    observed_backpressure = False
    observed_trust_proof = False
    for tool_ref in apply_refs:
        if not tool_ref:
            continue
        effects = tool_effects_by_name.get(tool_ref, ())
        if tool_declares_backpressure(effects):
            observed_backpressure = True
        if tool_declares_trust_proof(effects):
            observed_trust_proof = True
        if observed_backpressure and observed_trust_proof:
            break

    diagnostics: list[RefinementDiagnostic] = []
    if uses_stream and not observed_backpressure:
        diagnostics.append(
            RefinementDiagnostic(
                message=(
                    f"Flow '{flow_name}' uses 'Stream<T>' in its signature "
                    f"but no reachable tool declares a 'stream:<policy>' "
                    f"effect. Every Stream<T> needs a backpressure policy: "
                    f"{', '.join(BACKPRESSURE_CATALOG)}. Declare the policy "
                    f"on the tool that produces or consumes the stream "
                    f"(e.g. `effects: [stream:drop_oldest]`)."
                ),
                line=flow_loc_line,
                column=flow_loc_column,
            )
        )
    if uses_untrusted and not observed_trust_proof:
        diagnostics.append(
            RefinementDiagnostic(
                message=(
                    f"Flow '{flow_name}' accepts 'Untrusted<T>' in its "
                    f"signature but no reachable tool declares a "
                    f"'trust:<proof>' effect. Untrusted payloads MUST be "
                    f"refined via one of the catalogue verifiers: "
                    f"{', '.join(TRUST_CATALOG)}. Add the appropriate "
                    f"effect to the verifier tool "
                    f"(e.g. `effects: [trust:hmac]`)."
                ),
                line=flow_loc_line,
                column=flow_loc_column,
            )
        )
    return diagnostics


__all__ = [
    "RefinementDiagnostic",
    "STREAM_TYPE_CTOR",
    "TRUSTED_TYPE_CTOR",
    "UNTRUSTED_TYPE_CTOR",
    "check_flow_refinement_and_stream",
    "classify_effect",
    "effect_carries_backpressure",
    "effect_carries_trust_proof",
    "is_refinement_type",
    "is_stream_type",
    "is_trusted_type",
    "is_untrusted_type",
    "tool_declares_backpressure",
    "tool_declares_trust_proof",
]
