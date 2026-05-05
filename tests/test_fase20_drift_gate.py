"""
Fase 20.j — Shield drift gate extension.

Two structural assertions that prevent the v1.14.0 regression
(``scan_passed = True`` literal) from ever returning, and prevent
adopters silently shipping with empty scanner coverage:

  1. **No scan_passed=True / scan_passed=False literal** in
     ``axon/runtime/executor.py``. Comments explaining the
     historical pre-Fase-20 state are allowed (the literal must
     not appear inside a function body).
  2. **Every member of `_VALID_SHIELD_STRATEGIES`** has at least
     one registered scanner in ``default_registry`` after the
     runtime imports complete. If a strategy survives the
     TypeChecker but has no runtime scanner, that's a
     compile-only/runtime-stub gap — exactly the bug pattern
     Fase 17 / 18 / 19 / 20 closed reactively, now structurally
     guarded.
  3. **Charter compliance**: assert the OSS catalog source files do
     NOT import / register vertical-specific scanners. HIPAA PHI /
     legal privilege / fintech AML scanner names must NEVER appear
     in OSS code, only in the private axon-enterprise package.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════
#  ANTI-REGRESSION — scan_passed literal
# ═══════════════════════════════════════════════════════════════════


def test_executor_has_no_scan_passed_literal_assignment():
    """The pre-Fase-20 dispatcher assigned ``scan_passed = True``
    unconditionally — a false security guarantee. Fase 20 removed
    the literal in favor of registry dispatch. Regression to the
    literal form must fail CI."""
    src = (
        _project_root() / "axon" / "runtime" / "executor.py"
    ).read_text(encoding="utf-8")

    # Strip out comments AND docstrings so we don't false-positive
    # on prose explaining the historical literal.
    no_comments = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    # Naive strip of triple-quoted blocks. Won't handle nested
    # strings perfectly but good enough — production code rarely
    # has triple-quoted strings inside function bodies.
    no_docstrings = re.sub(
        r'""".*?"""', "", no_comments, flags=re.DOTALL,
    )
    no_docstrings = re.sub(
        r"'''.*?'''", "", no_docstrings, flags=re.DOTALL,
    )

    forbidden = [
        r"\bscan_passed\s*=\s*True\b",
        r"\bscan_passed\s*=\s*False\b",
    ]
    for pattern in forbidden:
        m = re.search(pattern, no_docstrings)
        assert m is None, (
            f"axon/runtime/executor.py contains forbidden literal "
            f"matching {pattern!r}: {m.group(0) if m else 'n/a'}\n"
            f"\nFase 20.a removed the unconditional `scan_passed = "
            f"True` assignment in favor of registry-driven dispatch. "
            f"If this regressed, the Shield runtime is back to "
            f"falsely-guaranteed pass — see "
            f"docs/fase_20_production_shield_runtime.md §3.1."
        )


# ═══════════════════════════════════════════════════════════════════
#  COVERAGE — every strategy in the typechecker has a scanner
# ═══════════════════════════════════════════════════════════════════


def test_every_valid_shield_strategy_has_at_least_one_scanner():
    """The typechecker accepts 6 strategies. Each MUST have at
    least one scanner registered somewhere in the default registry.
    A strategy that the TypeChecker validates but has no runtime
    scanner is the compile-only/runtime-stub gap we're closing."""
    from axon.compiler.type_checker import TypeChecker
    from axon.runtime.shield_scanners import default_registry

    valid_strategies = TypeChecker._VALID_SHIELD_STRATEGIES
    known = default_registry.known()
    seen_strategies = {
        strategy
        for strategies in known.values()
        for strategy in strategies
    }
    missing = valid_strategies - seen_strategies
    assert not missing, (
        "Strategies validated by TypeChecker but with NO runtime "
        f"scanner registered:\n  {sorted(missing)}\n\n"
        "Every member of _VALID_SHIELD_STRATEGIES must have a "
        "scanner in axon.runtime.shield_scanners.default_registry. "
        "See docs/fase_20_production_shield_runtime.md §3.2."
    )


def test_capability_validate_category_present_in_typechecker():
    """Fase 20.d added `capability_validate` to the threat
    taxonomy. Regression check."""
    from axon.compiler.type_checker import TypeChecker
    assert (
        "capability_validate"
        in TypeChecker._VALID_SCAN_CATEGORIES
    ), (
        "capability_validate (Fase 20.d) missing from "
        "TypeChecker._VALID_SCAN_CATEGORIES."
    )


def test_capability_validate_has_oss_baseline_scanner():
    """Adopter declaring `scan: [capability_validate]` MUST get a
    working scanner from OSS — fail-safe by registry, not by
    silent typecheck pass."""
    from axon.runtime.shield_scanners import default_registry
    scanner = default_registry.lookup("capability_validate", "hmac")
    assert scanner is not None, (
        "OSS HmacCapabilityScanner missing for "
        "(capability_validate, hmac). Auto-registration in "
        "axon.runtime.shield.capability_scanner regressed."
    )


# ═══════════════════════════════════════════════════════════════════
#  CHARTER COMPLIANCE — no vertical R&D in OSS code
# ═══════════════════════════════════════════════════════════════════


def test_oss_shield_files_do_not_reference_vertical_terms():
    """Per memory/project_axon_enterprise_charter.md, vertical
    R&D (HIPAA / legal / fintech / FDA) lives ONLY in
    axon-enterprise. The OSS shield code (everything under
    axon/runtime/shield/) must NEVER import or register
    vertical-specific scanners."""
    shield_dir = _project_root() / "axon" / "runtime" / "shield"
    forbidden_terms_in_code = [
        "icd10", "ICD10", "ICD-10",
        "BioBERT_pretrained", "LegalBERT_pretrained",
        "AML_smurf", "PAN_with_luhn",
        "attorney_client_privilege", "work_product_doctrine",
        "MRN_format", "NPI_provider",
        "drug_dea", "schedule_drug_pattern",
    ]

    offenders: list[tuple[Path, str, int]] = []
    for path in shield_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Allow these terms in COMMENTS (#) and DOCSTRINGS (""")
        # because we explicitly call out what's enterprise-only.
        # Forbid them in actual code (string literals registered
        # into the registry, function names, regex patterns).
        no_comments = re.sub(r"#.*", "", text)
        no_docstrings = re.sub(
            r'""".*?"""', "", no_comments, flags=re.DOTALL,
        )
        for term in forbidden_terms_in_code:
            for line_no, line in enumerate(no_docstrings.splitlines(), 1):
                if term.lower() in line.lower():
                    offenders.append((path, term, line_no))

    assert not offenders, (
        f"OSS shield/ contains vertical R&D references that should "
        f"live in axon-enterprise (per charter):\n"
        + "\n".join(
            f"  {p.name}:{n} — '{t}'"
            for p, t, n in offenders
        )
    )


def test_oss_pattern_catalogs_have_no_vertical_labels():
    """The pattern scanner's catalog labels are user-facing (they
    appear in trace events). Adopters running the OSS without
    enterprise should never see HIPAA / legal / fintech-specific
    label names — those leak vertical R&D."""
    from axon.runtime.shield.pattern_scanner import _CATALOGS
    forbidden = [
        "phi_", "icd10", "icd-10", "mrn_", "npi_",
        "privilege_", "attorney_",
        "aml_", "pan_luhn", "iban_",
        "fda_", "dea_",
    ]
    all_labels = [
        label
        for catalog in _CATALOGS.values()
        for _, _, label in catalog
    ]
    for term in forbidden:
        for label in all_labels:
            assert term.lower() not in label.lower(), (
                f"OSS pattern catalog contains vertical-specific "
                f"label '{label}' matching forbidden term '{term}'. "
                f"Move to axon-enterprise."
            )


def test_pattern_scanner_oss_catalogs_count_is_documented():
    """Sanity: the OSS catalog has at least 9 categories with
    non-empty patterns. If this drops, someone removed catalog
    entries silently."""
    from axon.runtime.shield.pattern_scanner import _CATALOGS
    nonempty = [k for k, v in _CATALOGS.items() if v]
    assert len(nonempty) >= 9, (
        f"OSS pattern catalogs collapsed to {len(nonempty)} "
        f"non-empty categories. Expected ≥9. Current: "
        f"{sorted(nonempty)}"
    )
