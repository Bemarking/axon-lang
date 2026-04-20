"""
AXON — Phase 7 Audit Evidence Engine tests
=============================================
Covers the audit-readiness layer introduced on top of the ESK:

  * Framework catalogs (SOC 2 / ISO 27001 / FIPS 140-3 / CC EAL 4+)
  * GapAnalyzer — deterministic verdicts per control
  * RiskRegister — ISO 27005-shaped register pruned by program features
  * ControlImplementationStatement — pre-filled audit intake answers
  * EvidencePackage — deterministic ZIP with per-file SHA-256 manifest
  * CLI commands — `axon audit` and `axon evidence-package`

External auditors (accredited labs / CPA firms) cannot be replaced by
software; these tests verify everything an engineering team CAN do
before the external engagement begins.
"""

from __future__ import annotations

import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from axon.cli import main as cli_main
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.esk import (
    FrameworkId,
    analyze_all,
    analyze_gaps,
    build_evidence_package,
    control_count,
    controls_for,
    generate_control_statements,
    generate_risk_register,
    risk_register_to_dict,
    statements_to_dict,
)


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

_HEALTHCARE_REFERENCE = (
    Path(__file__).resolve().parent.parent / "examples" / "healthcare_reference.axon"
)


_MINIMAL_PROGRAM = """
type Basic { note: String }

flow Echo(n: Basic) -> Basic {
  step Pass {
    ask: "echo"
    output: Basic
  }
}
"""


def _compile(source: str):
    return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())


@pytest.fixture(scope="module")
def full_ir():
    return _compile(_HEALTHCARE_REFERENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def minimal_ir():
    return _compile(_MINIMAL_PROGRAM)


# ═══════════════════════════════════════════════════════════════════
#  Framework catalogs
# ═══════════════════════════════════════════════════════════════════

class TestFrameworks:

    def test_all_frameworks_have_nonzero_controls(self):
        for f in FrameworkId:
            assert control_count(f) > 0, f

    def test_control_ids_are_unique_within_framework(self):
        for f in FrameworkId:
            ids = [c.control_id for c in controls_for(f)]
            assert len(ids) == len(set(ids)), f"duplicates in {f}"

    def test_every_control_has_axon_primitive(self):
        for f in FrameworkId:
            for c in controls_for(f):
                assert c.axon_primitive, c.control_id
                assert c.evidence_locator, c.control_id


# ═══════════════════════════════════════════════════════════════════
#  GapAnalyzer
# ═══════════════════════════════════════════════════════════════════

class TestGapAnalyzer:

    def test_full_program_soc2_is_high_readiness(self, full_ir):
        a = analyze_gaps(full_ir, FrameworkId.SOC2_TYPE_II)
        assert a.total_controls == control_count(FrameworkId.SOC2_TYPE_II)
        assert a.ready + a.pending_code + a.pending_external == a.total_controls
        assert a.readiness_percent >= 90.0

    def test_minimal_program_has_more_pending(self, minimal_ir, full_ir):
        minimal = analyze_gaps(minimal_ir, FrameworkId.SOC2_TYPE_II)
        full = analyze_gaps(full_ir, FrameworkId.SOC2_TYPE_II)
        assert minimal.pending_code > full.pending_code

    def test_minimal_missing_features_include_immune(self, minimal_ir):
        a = analyze_gaps(minimal_ir, FrameworkId.SOC2_TYPE_II)
        assert "has_immune" in a.missing_features

    def test_analyze_all_covers_every_framework(self, full_ir):
        by_framework = analyze_all(full_ir)
        assert set(by_framework.keys()) == {f.value for f in FrameworkId}
        for analysis in by_framework.values():
            assert analysis.total_controls > 0

    def test_result_is_deterministic(self, full_ir):
        a = analyze_gaps(full_ir, FrameworkId.ISO_27001).to_dict()
        b = analyze_gaps(full_ir, FrameworkId.ISO_27001).to_dict()
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_fips_has_pending_external_entries(self, full_ir):
        a = analyze_gaps(full_ir, FrameworkId.FIPS_140_3)
        assert a.pending_external > 0, (
            "FIPS 140-3 requires accredited-lab evidence — at least one "
            "entry must be marked pending_external"
        )


# ═══════════════════════════════════════════════════════════════════
#  RiskRegister
# ═══════════════════════════════════════════════════════════════════

class TestRiskRegister:

    def test_full_program_emits_multiple_risks(self, full_ir):
        risks = generate_risk_register(full_ir)
        assert len(risks) >= 8

    def test_minimal_program_prunes_feature_gated_risks(self, minimal_ir, full_ir):
        minimal = generate_risk_register(minimal_ir)
        full = generate_risk_register(full_ir)
        assert len(minimal) < len(full)

    def test_ids_are_sequential_and_unique(self, full_ir):
        ids = [r.risk_id for r in generate_risk_register(full_ir)]
        assert len(ids) == len(set(ids))
        for i, rid in enumerate(ids, start=1):
            assert rid == f"AXON-RISK-{i:03d}"

    def test_residual_score_in_range(self, full_ir):
        for r in generate_risk_register(full_ir):
            assert 1 <= r.residual_score <= 9

    def test_to_dict_shape(self, full_ir):
        payload = risk_register_to_dict(generate_risk_register(full_ir))
        assert payload["schema"] == "axon.esk.risk_register.v1"
        assert payload["total_risks"] == len(payload["risks"])


# ═══════════════════════════════════════════════════════════════════
#  ControlImplementationStatement
# ═══════════════════════════════════════════════════════════════════

class TestControlStatements:

    def test_one_statement_per_control(self, full_ir):
        for f in FrameworkId:
            statements = generate_control_statements(full_ir, f)
            assert len(statements) == control_count(f)

    def test_statuses_only_from_canonical_set(self, full_ir):
        canonical = {"implemented", "partially_implemented", "planned", "not_applicable"}
        for f in FrameworkId:
            for s in generate_control_statements(full_ir, f):
                assert s.status in canonical, (f, s.control_id, s.status)

    def test_statements_to_dict_schema(self, full_ir):
        stmts = generate_control_statements(full_ir, FrameworkId.SOC2_TYPE_II)
        d = statements_to_dict(stmts, FrameworkId.SOC2_TYPE_II)
        assert d["schema"] == "axon.esk.control_implementation_statements.v1"
        assert d["framework"] == FrameworkId.SOC2_TYPE_II.value
        assert d["total_controls"] == len(stmts)


# ═══════════════════════════════════════════════════════════════════
#  EvidencePackage
# ═══════════════════════════════════════════════════════════════════

class TestEvidencePackage:

    def test_package_contains_expected_top_level_files(self, full_ir):
        pkg = build_evidence_package(full_ir, source_files={"prog.axon": "// src"})
        names = set(pkg.filenames())
        for required in {
            "MANIFEST.json",
            "README.md",
            "program_sbom.json",
            "program_dossier.json",
            "in_toto_statement.json",
            "risk_register.json",
        }:
            assert required in names

    def test_per_framework_files_exist(self, full_ir):
        pkg = build_evidence_package(full_ir)
        names = set(pkg.filenames())
        for f in FrameworkId:
            assert f"gap_analysis/{f.value}.json" in names
            assert f"control_statements/{f.value}.json" in names

    def test_manifest_contains_sha256_for_every_other_file(self, full_ir):
        pkg = build_evidence_package(full_ir)
        manifest = json.loads(pkg.files["MANIFEST.json"].decode("utf-8"))
        recorded = {e["name"] for e in manifest["files"]}
        for name in pkg.filenames():
            if name == "MANIFEST.json":
                continue
            assert name in recorded, name

    def test_sha256s_match_content(self, full_ir):
        import hashlib
        pkg = build_evidence_package(full_ir)
        manifest = json.loads(pkg.files["MANIFEST.json"].decode("utf-8"))
        for entry in manifest["files"]:
            if entry["name"] == "MANIFEST.json":
                continue
            actual = hashlib.sha256(pkg.files[entry["name"]]).hexdigest()
            assert actual == entry["sha256"], entry["name"]

    def test_zip_is_openable_and_complete(self, full_ir, tmp_path):
        pkg = build_evidence_package(full_ir)
        out = pkg.write_zip(tmp_path / "ev.zip")
        assert out.exists() and out.stat().st_size > 0
        with zipfile.ZipFile(out) as zf:
            zip_names = set(zf.namelist())
        assert zip_names == set(pkg.filenames())

    def test_zip_is_deterministic(self, full_ir):
        a = build_evidence_package(full_ir).to_zip_bytes()
        b = build_evidence_package(full_ir).to_zip_bytes()
        assert a == b, "Evidence ZIP must be byte-identical on equal input"

    def test_source_snapshot_included(self, full_ir):
        pkg = build_evidence_package(
            full_ir,
            source_files={"prog.axon": "// content\n"},
        )
        assert b"// content" in pkg.files["source/prog.axon"]

    def test_auditor_note_surfaces_in_readme(self, full_ir):
        pkg = build_evidence_package(full_ir, auditor_note="Engaged with FirmX on 2026-04")
        readme = pkg.files["README.md"].decode("utf-8")
        assert "Engaged with FirmX" in readme


# ═══════════════════════════════════════════════════════════════════
#  CLI: axon audit + axon evidence-package
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def axon_file(tmp_path: Path) -> Path:
    p = tmp_path / "cli_case.axon"
    p.write_text(_HEALTHCARE_REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    return p


class TestAuditCli:

    def test_audit_all_frameworks_exit_zero(self, axon_file: Path, tmp_path: Path):
        out = tmp_path / "audit.json"
        rc = cli_main(["audit", str(axon_file), "-o", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["schema"] == "axon.esk.audit_gap_report.v1"
        assert set(payload["frameworks"].keys()) == {f.value for f in FrameworkId}

    def test_audit_single_framework(self, axon_file: Path, tmp_path: Path):
        out = tmp_path / "soc2.json"
        rc = cli_main(["audit", str(axon_file), "--framework", "soc2", "-o", str(out)])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["analysis"]["framework"] == FrameworkId.SOC2_TYPE_II.value

    def test_audit_unknown_framework_exits_two(
        self, axon_file: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # argparse rejects the choice with SystemExit(2) before cmd_audit runs.
        with pytest.raises(SystemExit) as exc:
            cli_main(["audit", str(axon_file), "--framework", "banana"])
        assert exc.value.code == 2

    def test_audit_missing_file_exits_two(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.axon"
        rc = cli_main(["audit", str(missing)])
        assert rc == 2

    def test_audit_bad_source_exits_one(self, tmp_path: Path):
        bad = tmp_path / "bad.axon"
        bad.write_text("flow Broken( -> Nope {\n", encoding="utf-8")
        rc = cli_main(["audit", str(bad)])
        assert rc == 1


class TestEvidencePackageCli:

    def test_package_written_and_valid(self, axon_file: Path, tmp_path: Path):
        out = tmp_path / "package.zip"
        rc = cli_main(["evidence-package", str(axon_file), "-o", str(out)])
        assert rc == 0
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert "MANIFEST.json" in names
        assert any(n.startswith("source/") for n in names)

    def test_default_output_path_is_suffixed(self, axon_file: Path):
        rc = cli_main(["evidence-package", str(axon_file)])
        assert rc == 0
        expected = axon_file.with_suffix(".evidence.zip")
        assert expected.exists()

    def test_missing_file_exits_two(self, tmp_path: Path):
        rc = cli_main(["evidence-package", str(tmp_path / "absent.axon")])
        assert rc == 2
