"""
Vertical shield scanner tests (axon-enterprise Fase 20 / v1.7.0).

Three suites — one per vertical — plus an inverted charter test
that asserts the enterprise package DOES contain the vertical R&D
that OSS deliberately excludes (mirror image of the OSS charter
test that asserts those terms do NOT appear there).

Coverage:
  * Healthcare HIPAA PHI scanner: each Safe Harbor identifier
    category caught; clean text passes; no model call;
    co-occurrence of name+DOB+MRN flagged as composite identifier.
  * Legal privilege scanner: attorney-client / work-product / FRE
    408 markers caught; bare case citations alone do NOT trigger
    (public information).
  * Fintech AML scanner: Luhn-validated PAN caught; IBAN mod-97
    validated; smurf signature requires ≥2 amounts; bare 16-digit
    string that fails Luhn does NOT trigger (avoids false
    positives on receipt timestamps etc.).
  * Auto-registration: importing the package puts every vertical
    scanner under its explicit alias in ``default_registry``;
    OSS baselines are NOT shadowed.
  * Ensemble factories produce composed scanners with the right
    sub-scanner count + vote behaviour.
  * Charter inversion: the enterprise package source files DO
    contain `hipaa`, `attorney`, `aml` markers (mirror of OSS
    drift gate that forbids them).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axon.runtime.shield_scanners import (
    ScanContext,
    default_registry,
)


def _ctx(category: str, strategy: str, **config) -> ScanContext:
    return ScanContext(
        flow_name="ent_test", shield_name="EntShield",
        category=category, strategy=strategy, config=config,
    )


# ═══════════════════════════════════════════════════════════════════
#  AUTO-REGISTRATION
# ═══════════════════════════════════════════════════════════════════


class TestAutoRegistration:
    def test_healthcare_pattern_registered_under_hipaa(self):
        # Side-effect import.
        import axon_enterprise.shield  # noqa: F401
        assert default_registry.lookup("pii_leak", "hipaa") is not None
        assert default_registry.lookup("data_exfil", "hipaa") is not None

    def test_healthcare_judge_registered_under_hipaa_judge(self):
        import axon_enterprise.shield  # noqa: F401
        assert default_registry.lookup("pii_leak", "hipaa_judge") is not None

    def test_legal_pattern_registered_under_legal(self):
        import axon_enterprise.shield  # noqa: F401
        assert default_registry.lookup("data_exfil", "legal") is not None

    def test_fintech_pattern_registered_under_aml(self):
        import axon_enterprise.shield  # noqa: F401
        assert default_registry.lookup("pii_leak", "aml") is not None

    def test_oss_baselines_not_shadowed(self):
        """Critical multi-vertical safety: vertical scanners
        register under explicit aliases, NOT under the generic
        OSS strategy keys. So the OSS pattern / dual_llm /
        classifier scanners must still be reachable after
        importing axon_enterprise.shield."""
        import axon_enterprise.shield  # noqa: F401
        # OSS pattern still under the bare 'pattern' alias.
        assert default_registry.lookup("pii_leak", "pattern") is not None
        assert default_registry.lookup("data_exfil", "pattern") is not None
        # OSS dual_llm under bare 'dual_llm' alias.
        assert default_registry.lookup("data_exfil", "dual_llm") is not None


# ═══════════════════════════════════════════════════════════════════
#  HEALTHCARE — HIPAA PHI scanner
# ═══════════════════════════════════════════════════════════════════


class TestHipaaPhiScanner:
    @pytest.fixture(autouse=True)
    def _import_pkg(self):
        import axon_enterprise.shield  # noqa: F401

    def _scan(self, target: str):
        scanner = default_registry.lookup("pii_leak", "hipaa")
        return scanner.scan(target, _ctx("pii_leak", "hipaa"))

    def test_ssn_format_caught(self):
        result = self._scan("Patient SSN: 123-45-6789 in chart")
        assert result.passed is False
        labels = [m["label"] for m in result.detail["matches"]]
        assert "hipaa_ssn" in labels

    def test_mrn_labeled_caught(self):
        result = self._scan("MRN: 12345678 admitted today")
        assert result.passed is False

    def test_full_date_caught(self):
        result = self._scan("Procedure date: 2024-03-15")
        assert result.passed is False

    def test_phone_caught(self):
        result = self._scan("Contact: (617) 555-0123 for follow-up")
        assert result.passed is False

    def test_name_dob_composite_caught(self):
        result = self._scan(
            "Patient John Doe, DOB 1980-05-15, presented with chest pain"
        )
        assert result.passed is False
        labels = [m["label"] for m in result.detail["matches"]]
        assert "hipaa_name_dob_composite" in labels

    def test_clean_text_passes(self):
        result = self._scan(
            "82% of N=1247 patients showed improvement at 6 weeks"
        )
        assert result.passed is True

    def test_empty_target_passes(self):
        result = self._scan("")
        assert result.passed is True


# ═══════════════════════════════════════════════════════════════════
#  LEGAL — privilege scanner
# ═══════════════════════════════════════════════════════════════════


class TestLegalPrivilegeScanner:
    @pytest.fixture(autouse=True)
    def _import_pkg(self):
        import axon_enterprise.shield  # noqa: F401

    def _scan(self, target: str):
        scanner = default_registry.lookup("data_exfil", "legal")
        return scanner.scan(target, _ctx("data_exfil", "legal"))

    def test_privileged_and_confidential_marker_caught(self):
        result = self._scan(
            "PRIVILEGED AND CONFIDENTIAL — analysis enclosed"
        )
        assert result.passed is False

    def test_attorney_client_privilege_caught(self):
        result = self._scan(
            "This communication is subject to attorney-client privilege"
        )
        assert result.passed is False

    def test_work_product_caught(self):
        result = self._scan(
            "Memo prepared in anticipation of litigation re: Smith matter"
        )
        assert result.passed is False

    def test_settlement_communication_caught(self):
        result = self._scan(
            "Per FRE 408, settlement offer of $50K without prejudice"
        )
        assert result.passed is False

    def test_bare_case_citation_passes(self):
        # Public-record citations alone are NOT privileged.
        result = self._scan(
            "See Marbury v. Madison, 5 U.S. 137 — established judicial review"
        )
        assert result.passed is True
        assert result.detail.get("low_severity_only") is True

    def test_clean_text_passes(self):
        result = self._scan(
            "Contract law generally requires offer + acceptance + consideration"
        )
        assert result.passed is True


# ═══════════════════════════════════════════════════════════════════
#  FINTECH — AML scanner
# ═══════════════════════════════════════════════════════════════════


class TestFintechAmlScanner:
    @pytest.fixture(autouse=True)
    def _import_pkg(self):
        import axon_enterprise.shield  # noqa: F401

    def _scan(self, target: str):
        scanner = default_registry.lookup("pii_leak", "aml")
        return scanner.scan(target, _ctx("pii_leak", "aml"))

    def test_luhn_valid_pan_caught(self):
        # 4242 4242 4242 4242 is a Stripe test card, valid Luhn.
        result = self._scan("Card: 4242 4242 4242 4242 charge $50")
        assert result.passed is False
        labels = [m["label"] for m in result.detail["matches"]]
        assert "fintech_pan_luhn_validated" in labels

    def test_luhn_invalid_pan_passes(self):
        # 16 digits that fail Luhn (e.g. all 1s) — should NOT trigger
        # PAN even though shape matches. False-positive guard.
        result = self._scan("Order ID 1111-1111-1111-1111 received")
        # Check that no PAN match appears (Luhn must filter it out).
        labels = [m["label"] for m in result.detail.get("matches", [])]
        assert "fintech_pan_luhn_validated" not in labels

    def test_iban_mod97_valid_caught(self):
        # GB82 WEST 1234 5698 7654 32 — canonical valid example.
        result = self._scan(
            "Wire to GB82WEST12345698765432 for amount due"
        )
        assert result.passed is False
        labels = [m["label"] for m in result.detail["matches"]]
        assert "fintech_iban_mod97_validated" in labels

    def test_iban_mod97_invalid_passes(self):
        result = self._scan("Code GB99WEST12345698765432 (bad checksum)")
        labels = [m["label"] for m in result.detail.get("matches", [])]
        assert "fintech_iban_mod97_validated" not in labels

    def test_smurf_signature_requires_two_amounts(self):
        # Single $9,999 = not smurfing (could be a price).
        single = self._scan("Watch retails at $9,999")
        single_labels = [m["label"] for m in single.detail.get("matches", [])]
        assert "fintech_smurf_structured_transactions" not in single_labels

        # Two amounts = smurf signal.
        double = self._scan(
            "Wire $9,999 on Monday and $9,500 on Wednesday"
        )
        double_labels = [m["label"] for m in double.detail.get("matches", [])]
        assert "fintech_smurf_structured_transactions" in double_labels

    def test_ofac_signal_caught(self):
        result = self._scan(
            "Cross-check against the OFAC Sanctions List before disbursing"
        )
        assert result.passed is False

    def test_clean_text_passes(self):
        result = self._scan(
            "General market commentary on Q3 earnings season"
        )
        assert result.passed is True


# ═══════════════════════════════════════════════════════════════════
#  ENSEMBLE FACTORIES
# ═══════════════════════════════════════════════════════════════════


class TestEnsembleFactories:
    @pytest.fixture(autouse=True)
    def _import_pkg(self):
        import axon_enterprise.shield  # noqa: F401

    def test_healthcare_ensemble_composes_three_scanners(self):
        from axon_enterprise.shield.ensemble_configs import (
            healthcare_ensemble,
        )
        ens = healthcare_ensemble()
        # hipaa_pattern + oss_pattern + hipaa_judge.
        assert len(ens.sub_scanners) == 3
        names = [name for name, _ in ens.sub_scanners]
        assert "hipaa_pattern" in names
        assert "hipaa_judge" in names

    def test_legal_ensemble_composes_three_scanners(self):
        from axon_enterprise.shield.ensemble_configs import legal_ensemble
        ens = legal_ensemble()
        assert len(ens.sub_scanners) == 3
        names = [name for name, _ in ens.sub_scanners]
        assert "legal_pattern" in names
        assert "legal_judge" in names

    def test_fintech_ensemble_composes_three_scanners(self):
        from axon_enterprise.shield.ensemble_configs import (
            fintech_ensemble,
        )
        ens = fintech_ensemble()
        assert len(ens.sub_scanners) == 3
        names = [name for name, _ in ens.sub_scanners]
        assert "aml_pattern" in names
        assert "aml_judge" in names

    def test_register_vertical_ensembles_idempotent(self):
        from axon_enterprise.shield.ensemble_configs import (
            register_vertical_ensembles,
        )
        register_vertical_ensembles()
        register_vertical_ensembles()  # second call must not raise
        assert default_registry.lookup(
            "pii_leak", "healthcare_ensemble",
        ) is not None
        assert default_registry.lookup(
            "data_exfil", "legal_ensemble",
        ) is not None
        assert default_registry.lookup(
            "pii_leak", "fintech_ensemble",
        ) is not None


# ═══════════════════════════════════════════════════════════════════
#  CHARTER INVERSION — enterprise package MUST contain vertical R&D
# ═══════════════════════════════════════════════════════════════════
#
# Mirror image of the OSS drift gate
# (`tests/test_fase19_drift_gate.py::test_oss_shield_files_do_not_
# reference_vertical_terms`): there, the OSS source forbids these
# terms. Here, the enterprise source REQUIRES them — proof that
# the vertical R&D actually lives in the enterprise package, not
# silently leaked to OSS.


class TestCharterInversion:
    def _enterprise_shield_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "axon_enterprise" / "shield"

    def test_healthcare_module_contains_hipaa_terms(self):
        src = (
            self._enterprise_shield_dir() / "healthcare" /
            "hipaa_patterns.py"
        ).read_text(encoding="utf-8").lower()
        for required in ("hipaa", "phi", "icd", "mrn"):
            assert required in src, (
                f"Healthcare module missing required vertical term "
                f"'{required}'. The HIPAA R&D must live in the "
                f"enterprise package, not be silently moved to OSS."
            )

    def test_legal_module_contains_privilege_terms(self):
        src = (
            self._enterprise_shield_dir() / "legal" /
            "privilege_patterns.py"
        ).read_text(encoding="utf-8").lower()
        for required in ("privilege", "attorney", "work-product"):
            assert required in src, (
                f"Legal module missing required vertical term "
                f"'{required}'. The legal-privilege R&D must "
                f"live in the enterprise package."
            )

    def test_fintech_module_contains_aml_terms(self):
        src = (
            self._enterprise_shield_dir() / "fintech" /
            "aml_patterns.py"
        ).read_text(encoding="utf-8").lower()
        for required in ("aml", "luhn", "iban", "ofac"):
            assert required in src, (
                f"Fintech module missing required vertical term "
                f"'{required}'. The AML / KYC R&D must live in "
                f"the enterprise package."
            )
