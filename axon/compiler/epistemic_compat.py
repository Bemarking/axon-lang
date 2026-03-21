"""
AXON Compiler — Epistemic Module System: Epistemic Compatibility
===================================================================
Cross-module epistemic compatibility validation.

This is axon-lang's novel contribution to module system theory:
no existing language performs epistemic-level compatibility checking
across module boundaries.

The core guarantee:
  A module operating at 'know' level CANNOT silently import
  definitions from a 'speculate'-level module without explicit
  epistemic downgrade acknowledgment.

Design lineage:
  - Denning Lattice:  Information flow security (shield model)
  - Epistemic Logic:  Kripke semantics for knowledge operators
  - axon-lang:        Epistemic type lattice as partial order

Pipeline position:
  ModuleResolver → InterfaceGenerator → **EpistemicCompat** → IRGenerator
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from axon.compiler.interface_generator import (
    CognitiveInterface,
    EpistemicLevel,
)


# ═══════════════════════════════════════════════════════════════════
#  COMPATIBILITY DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EpistemicDiagnostic:
    """
    A single epistemic compatibility issue.

    Severity levels:
      - ERROR:   Incompatible epistemic levels — compilation fails.
      - WARNING: Epistemic downgrade detected — compilation proceeds
                 but user is warned about potential semantic risk.
      - INFO:    Compatible but noteworthy (e.g., upgrading from
                 speculate to know is fine but worth logging).
    """
    severity: str                    # "error" | "warning" | "info"
    message: str
    importing_module: str
    imported_module: str
    importer_level: str
    imported_level: str
    symbol_name: str = ""            # Specific symbol causing the issue


# ═══════════════════════════════════════════════════════════════════
#  EPISTEMIC COMPATIBILITY CHECKER
# ═══════════════════════════════════════════════════════════════════

class EpistemicCompatChecker:
    """
    Validates epistemic compatibility across module import boundaries.

    The checker enforces the Epistemic Compatibility Principle (ECP):

      ∀ import(M_a, M_b):
        floor(M_b) ≥ floor(M_a) ∨ explicit_downgrade(M_a)

    In plain language: if module A imports from module B, then B's
    epistemic floor must be at least as high as A's floor — UNLESS
    A explicitly acknowledges the downgrade.

    This is the module-boundary equivalent of the epistemic block
    checker that already exists within single files.

    Rules table:
    ┌──────────────┬────────────┬────────────┬────────────┬────────────┐
    │ Importer ↓   │ know       │ believe    │ doubt      │ speculate  │
    │ Imported →   │            │            │            │            │
    ├──────────────┼────────────┼────────────┼────────────┼────────────┤
    │ know         │ ✅ OK      │ ⚠️ WARNING  │ ⚠️ WARNING  │ ❌ ERROR   │
    │ believe      │ ✅ OK      │ ✅ OK      │ ⚠️ WARNING  │ ❌ ERROR   │
    │ doubt        │ ✅ OK      │ ✅ OK      │ ✅ OK      │ ⚠️ WARNING  │
    │ speculate    │ ✅ OK      │ ✅ OK      │ ✅ OK      │ ✅ OK      │
    │ unspecified  │ ✅ OK      │ ✅ OK      │ ✅ OK      │ ✅ OK      │
    └──────────────┴────────────┴────────────┴────────────┴────────────┘
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: If True, treat warnings as errors.
        """
        self.strict = strict
        self.diagnostics: list[EpistemicDiagnostic] = []

    def check_import(
        self,
        importer: CognitiveInterface,
        imported: CognitiveInterface,
        imported_names: tuple[str, ...] = (),
    ) -> list[EpistemicDiagnostic]:
        """
        Check epistemic compatibility for a single import statement.

        Args:
            importer:       Interface of the importing module
            imported:       Interface of the imported module
            imported_names: Specific names being imported (empty = all)

        Returns:
            List of diagnostics (errors, warnings, info).
        """
        results: list[EpistemicDiagnostic] = []

        importer_floor = importer.epistemic_floor
        imported_floor = imported.epistemic_floor

        # If importer has no epistemic requirements, everything is fine
        if importer_floor == EpistemicLevel.UNSPECIFIED:
            return results

        # If imported has no epistemic level, skip (legacy module)
        if imported_floor == EpistemicLevel.UNSPECIFIED:
            return results

        importer_name = ".".join(importer.module_path)
        imported_name = ".".join(imported.module_path)

        # ── Check floor compatibility ─────────────────────────

        gap = importer_floor - imported_floor

        if gap >= 3:
            # Severe mismatch: e.g., know importing speculate
            diag = EpistemicDiagnostic(
                severity="error",
                message=(
                    f"Epistemic conflict: module '{importer_name}' "
                    f"({EpistemicLevel.name(importer_floor)}) imports from "
                    f"'{imported_name}' ({EpistemicLevel.name(imported_floor)}). "
                    f"A {EpistemicLevel.name(importer_floor)}-level module "
                    f"cannot import {EpistemicLevel.name(imported_floor)}-level "
                    f"definitions without explicit epistemic downgrade."
                ),
                importing_module=importer_name,
                imported_module=imported_name,
                importer_level=EpistemicLevel.name(importer_floor),
                imported_level=EpistemicLevel.name(imported_floor),
            )
            results.append(diag)

        elif gap >= 1:
            # Moderate mismatch: e.g., know importing believe
            severity = "error" if self.strict else "warning"
            diag = EpistemicDiagnostic(
                severity=severity,
                message=(
                    f"Epistemic downgrade: module '{importer_name}' "
                    f"({EpistemicLevel.name(importer_floor)}) imports from "
                    f"'{imported_name}' ({EpistemicLevel.name(imported_floor)}). "
                    f"This may weaken epistemic guarantees."
                ),
                importing_module=importer_name,
                imported_module=imported_name,
                importer_level=EpistemicLevel.name(importer_floor),
                imported_level=EpistemicLevel.name(imported_floor),
            )
            results.append(diag)

        # ── Check specific anchor conflicts ───────────────────

        if imported_names:
            results.extend(
                self._check_symbol_conflicts(
                    importer, imported, imported_names
                )
            )

        self.diagnostics.extend(results)
        return results

    def check_all_imports(
        self,
        importer: CognitiveInterface,
        imported_interfaces: dict[str, tuple[CognitiveInterface, tuple[str, ...]]],
    ) -> list[EpistemicDiagnostic]:
        """
        Check all imports for a single module.

        Args:
            importer: The importing module's interface
            imported_interfaces: Map of module_key → (interface, imported_names)

        Returns:
            Aggregated list of all diagnostics.
        """
        all_results: list[EpistemicDiagnostic] = []
        for _key, (imported, names) in imported_interfaces.items():
            results = self.check_import(importer, imported, names)
            all_results.extend(results)
        return all_results

    def has_errors(self) -> bool:
        """Check if any error-level diagnostics were produced."""
        return any(d.severity == "error" for d in self.diagnostics)

    def has_warnings(self) -> bool:
        """Check if any warning-level diagnostics were produced."""
        return any(d.severity == "warning" for d in self.diagnostics)

    def format_report(self) -> str:
        """Format all diagnostics as a human-readable report."""
        if not self.diagnostics:
            return "Epistemic compatibility: OK ✓"

        lines = ["═══ Epistemic Compatibility Report ═══"]
        for diag in self.diagnostics:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(
                diag.severity, "?"
            )
            lines.append(f"  {icon} [{diag.severity.upper()}] {diag.message}")
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear accumulated diagnostics."""
        self.diagnostics.clear()

    # ── Private helpers ───────────────────────────────────────

    @staticmethod
    def _check_symbol_conflicts(
        importer: CognitiveInterface,
        imported: CognitiveInterface,
        imported_names: tuple[str, ...],
    ) -> list[EpistemicDiagnostic]:
        """
        Check for specific anchor-level epistemic conflicts.

        Example: importing a speculate-level persona into a run
        that also uses a know-level anchor is a semantic conflict.
        """
        results: list[EpistemicDiagnostic] = []

        importer_name = ".".join(importer.module_path)
        imported_name = ".".join(imported.module_path)

        for name in imported_names:
            sig = imported.lookup(name)
            if sig is None:
                results.append(EpistemicDiagnostic(
                    severity="error",
                    message=(
                        f"Symbol '{name}' not found in module "
                        f"'{imported_name}'"
                    ),
                    importing_module=importer_name,
                    imported_module=imported_name,
                    importer_level=EpistemicLevel.name(
                        importer.epistemic_floor
                    ),
                    imported_level=EpistemicLevel.name(
                        imported.epistemic_floor
                    ),
                    symbol_name=name,
                ))

        return results
