"""
AXON Compiler — Fase 11.c tool-level sensitive/legal coherence check.

Python mirror of the Rust pass in ``axon-rs::type_checker``
(``check_tool`` — §Fase 11.c tool-level sensitive/legal coherence
block). Takes a tool's declared effect list and returns a list of
:class:`LegalBasisDiagnostic` entries — empty when the tool is
coherent, one entry per violation otherwise.

Violations caught:

1. Tool declares ``sensitive:<category>`` but carries NO
   ``legal:<basis>`` — regulated processing without a legal basis.
2. Tool declares ``legal:<basis>`` with an unknown slug — typo /
   case variant caught against the closed catalogue.
3. Tool declares ``sensitive`` without a category qualifier.
4. Tool declares ``legal`` without a basis qualifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from axon.compiler.legal_basis import (
    LEGAL_BASIS_CATALOG,
    LEGAL_EFFECT_SLUG,
    SENSITIVE_EFFECT_SLUG,
)


@dataclass(frozen=True, slots=True)
class LegalBasisDiagnostic:
    message: str
    line: int
    column: int = 0


def classify_effect(effect: str) -> tuple[str, str | None]:
    base, sep, qualifier = effect.partition(":")
    return (base, qualifier if sep else None)


def effect_declares_sensitive(effect: str) -> bool:
    base, qual = classify_effect(effect)
    return base == SENSITIVE_EFFECT_SLUG and qual is not None and len(qual) > 0


def effect_declares_legal_basis(effect: str) -> bool:
    base, qual = classify_effect(effect)
    return (
        base == LEGAL_EFFECT_SLUG
        and qual is not None
        and qual in LEGAL_BASIS_CATALOG
    )


def check_tool_sensitive_coherence(
    *,
    tool_name: str,
    tool_line: int,
    tool_column: int,
    effects: Iterable[str],
) -> list[LegalBasisDiagnostic]:
    """Verify a tool's effect list is internally coherent.

    Parameters mirror the subset of the AST shape needed; call-site
    adapts a Python :class:`ToolDefinition` into plain strings and
    an int pair before invoking this function.
    """
    diagnostics: list[LegalBasisDiagnostic] = []
    sensitive_categories: list[str] = []
    has_legal_basis = False
    legal_slug_errors: list[str] = []

    for effect in effects:
        base, qual = classify_effect(effect)
        if base == SENSITIVE_EFFECT_SLUG:
            if qual is None or not qual:
                diagnostics.append(
                    LegalBasisDiagnostic(
                        message=(
                            f"Effect 'sensitive' in tool '{tool_name}' "
                            f"requires a jurisdiction qualifier "
                            f"'sensitive:<category>' (e.g. "
                            f"'sensitive:health_data'). The category "
                            f"is adopter-defined; the legal basis "
                            f"covering it must also be declared via "
                            f"'legal:<basis>' on the same tool."
                        ),
                        line=tool_line,
                        column=tool_column,
                    )
                )
            else:
                sensitive_categories.append(qual)
        elif base == LEGAL_EFFECT_SLUG:
            if qual is None or not qual:
                diagnostics.append(
                    LegalBasisDiagnostic(
                        message=(
                            f"Effect 'legal' in tool '{tool_name}' "
                            f"requires a basis qualifier "
                            f"'legal:<basis>'. Valid bases: "
                            f"{', '.join(LEGAL_BASIS_CATALOG)}"
                        ),
                        line=tool_line,
                        column=tool_column,
                    )
                )
            elif qual in LEGAL_BASIS_CATALOG:
                has_legal_basis = True
            else:
                legal_slug_errors.append(qual)

    for q in legal_slug_errors:
        diagnostics.append(
            LegalBasisDiagnostic(
                message=(
                    f"Unknown legal basis '{q}' in tool '{tool_name}'. "
                    f"Valid: {', '.join(LEGAL_BASIS_CATALOG)}"
                ),
                line=tool_line,
                column=tool_column,
            )
        )

    if sensitive_categories and not has_legal_basis:
        diagnostics.append(
            LegalBasisDiagnostic(
                message=(
                    f"Tool '{tool_name}' declares sensitive effect(s) "
                    f"[{', '.join(sensitive_categories)}] but carries "
                    f"no 'legal:<basis>' effect. Regulated processing "
                    f"requires an explicit legal basis: "
                    f"{', '.join(LEGAL_BASIS_CATALOG)}."
                ),
                line=tool_line,
                column=tool_column,
            )
        )

    return diagnostics


__all__ = [
    "LegalBasisDiagnostic",
    "check_tool_sensitive_coherence",
    "classify_effect",
    "effect_declares_legal_basis",
    "effect_declares_sensitive",
]
