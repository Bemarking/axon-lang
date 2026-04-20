"""
AXON Enterprise — Phase 7 tests
==================================
Covers:
  • EnterpriseApplication facade (construction, provision, dossier, sbom)
  • Three production reference programs (banking, government, healthcare)
  • CLI commands `axon dossier` + `axon sbom`
  • End-to-end integration across Fases 1-6 through the facade
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.enterprise import EnterpriseApplication, EnterpriseStartupReport


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


# ═══════════════════════════════════════════════════════════════════
#  Reference programs — smoke tests that prove they compile
# ═══════════════════════════════════════════════════════════════════


class TestReferencePrograms:
    """Every production reference program must compile clean and emit a
    valid compliance dossier."""

    @pytest.mark.parametrize("filename,expected_classes,expected_sectors", [
        (
            "banking_reference.axon",
            {"PCI_DSS", "SOX", "SOC2"},
            {"financial", "cross-sector"},
        ),
        (
            "government_reference.axon",
            {"FISMA", "NIST_800_53", "SOC2"},
            {"government", "cross-sector"},
        ),
        (
            "healthcare_reference.axon",
            {"HIPAA", "GDPR", "GxP", "SOC2"},
            {"healthcare", "cross-sector", "pharma"},
        ),
    ])
    def test_reference_compiles_clean_and_covers_claimed_classes(
        self, filename, expected_classes, expected_sectors,
    ):
        path = EXAMPLES / filename
        assert path.exists(), f"missing reference program: {path}"
        source = path.read_text(encoding="utf-8")
        tree = Parser(Lexer(source).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == [], (
            f"{filename} must compile clean; got: "
            f"{[e.message for e in errors]}"
        )
        app = EnterpriseApplication.from_source(source, source_path=filename)
        dossier = app.dossier()
        assert expected_classes.issubset(set(dossier.classes_covered))
        assert expected_sectors.issubset(set(dossier.sectors))

    @pytest.mark.parametrize("filename", [
        "banking_reference.axon",
        "government_reference.axon",
        "healthcare_reference.axon",
    ])
    def test_reference_dossier_no_unshielded_regulated_endpoints(self, filename):
        """Every reference program must have every regulated endpoint
        behind a shield — zero gaps."""
        app = EnterpriseApplication.from_file(EXAMPLES / filename)
        dossier = app.dossier()
        assert dossier.unshielded_regulated == [], (
            f"{filename} has regulated endpoints without a shield: "
            f"{dossier.unshielded_regulated}"
        )


# ═══════════════════════════════════════════════════════════════════
#  EnterpriseApplication facade API
# ═══════════════════════════════════════════════════════════════════


_MINI_PROGRAM = """
type PHI compliance [HIPAA] { ssn: String }
flow P(x: PHI) -> String { step S { ask: "x" output: String } }
shield S { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
axonendpoint A {
  method: post path: "/p" body: PHI execute: P output: String
  shield: S compliance: [HIPAA]
}
resource Db { kind: postgres lifetime: linear }
manifest M { resources: [Db] compliance: [HIPAA] }
observe O from M { sources: [prometheus] quorum: 1 timeout: 5s }
"""


class TestEnterpriseApplicationFacade:

    def test_from_source_strict_rejects_bad_program(self):
        bad = """
type PHI compliance [HIPAA] { ssn: String }
flow P(x: PHI) -> String { step S { ask: "x" output: String } }
axonendpoint A { method: post path: "/p" body: PHI execute: P output: String }
"""
        with pytest.raises(ValueError, match="compile error"):
            EnterpriseApplication.from_source(bad)

    def test_from_source_non_strict_records_error_count(self):
        bad = """
type PHI compliance [HIPAA] { ssn: String }
flow P(x: PHI) -> String { step S { ask: "x" output: String } }
axonendpoint A { method: post path: "/p" body: PHI execute: P output: String }
"""
        app = EnterpriseApplication.from_source(bad, strict=False)
        report = app.provision()
        assert report.type_errors >= 1

    def test_provision_with_default_handler(self):
        app = EnterpriseApplication.from_source(_MINI_PROGRAM)
        report = app.provision()
        assert isinstance(report, EnterpriseStartupReport)
        assert report.handler == "dry_run"
        assert report.manifests_provisioned == 1
        assert report.observations_executed == 1
        assert report.type_errors == 0

    def test_provision_with_custom_handler_instance(self):
        from axon.runtime.handlers.dry_run import DryRunHandler
        app = EnterpriseApplication.from_source(_MINI_PROGRAM)
        handler = DryRunHandler()
        report = app.provision(handler=handler)
        assert report.handler == "dry_run"
        assert handler.state.provisioned  # handler was actually used

    def test_provision_with_unknown_handler_name_rejected(self):
        app = EnterpriseApplication.from_source(_MINI_PROGRAM)
        with pytest.raises(ValueError, match="unknown handler"):
            app.provision(handler="quantum_magic")

    def test_dossier_is_serializable(self):
        app = EnterpriseApplication.from_source(_MINI_PROGRAM)
        d = app.dossier().to_dict()
        assert d["schema"] == "axon.esk.compliance.v1"
        assert json.dumps(d, sort_keys=True)

    def test_sbom_is_deterministic(self):
        a = EnterpriseApplication.from_source(_MINI_PROGRAM).sbom()
        b = EnterpriseApplication.from_source(_MINI_PROGRAM).sbom()
        assert a.program_hash == b.program_hash

    def test_sbom_changes_with_program(self):
        a = EnterpriseApplication.from_source(_MINI_PROGRAM).sbom()
        b = EnterpriseApplication.from_source(
            _MINI_PROGRAM + "\ntype Extra { x: String }"
        ).sbom()
        assert a.program_hash != b.program_hash

    def test_from_file(self, tmp_path):
        path = tmp_path / "mini.axon"
        path.write_text(_MINI_PROGRAM, encoding="utf-8")
        app = EnterpriseApplication.from_file(path)
        assert app.source_path == str(path)

    def test_from_ir(self):
        tree = Parser(Lexer(_MINI_PROGRAM).tokenize()).parse()
        ir = IRGenerator().generate(tree)
        app = EnterpriseApplication.from_ir(ir)
        assert app.provision().manifests_provisioned == 1

    def test_provenance_chain_accessible(self):
        app = EnterpriseApplication.from_source(_MINI_PROGRAM)
        chain = app.provenance_chain()
        # A fresh chain has no entries yet — that is expected.
        assert chain.entries() == []


# ═══════════════════════════════════════════════════════════════════
#  CLI commands — axon dossier + axon sbom
# ═══════════════════════════════════════════════════════════════════


def _run_cli(*args, cwd=REPO_ROOT):
    """Invoke `python -m axon.cli` and capture stdout/stderr/exit."""
    return subprocess.run(
        [sys.executable, "-m", "axon.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class TestCliCommands:

    def test_dossier_stdout_is_valid_json(self):
        result = _run_cli(
            "dossier", "examples/healthcare_reference.axon",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema"] == "axon.esk.compliance.v1"
        assert "HIPAA" in payload["classes_covered"]

    def test_dossier_writes_to_output_file(self, tmp_path):
        out = tmp_path / "dossier.json"
        result = _run_cli(
            "dossier", "examples/banking_reference.axon",
            "-o", str(out),
        )
        assert result.returncode == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert set(payload["classes_covered"]) >= {"PCI_DSS", "SOX", "SOC2"}

    def test_sbom_stdout_is_valid_json(self):
        result = _run_cli(
            "sbom", "examples/government_reference.axon",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema"] == "axon.esk.sbom.v1"
        assert payload["program_hash"]
        assert len(payload["entries"]) >= 10

    def test_sbom_determinism(self):
        r1 = _run_cli("sbom", "examples/healthcare_reference.axon")
        r2 = _run_cli("sbom", "examples/healthcare_reference.axon")
        assert r1.returncode == 0 and r2.returncode == 0
        assert json.loads(r1.stdout)["program_hash"] == json.loads(r2.stdout)["program_hash"]

    def test_dossier_missing_file_exits_2(self, tmp_path):
        result = _run_cli("dossier", str(tmp_path / "nope.axon"))
        assert result.returncode == 2


# ═══════════════════════════════════════════════════════════════════
#  Fase 7 ACCEPTANCE — End-to-end integration (Fases 1-6 together)
# ═══════════════════════════════════════════════════════════════════


class TestPhase7AcceptanceE2E:
    """The Fase 7 closing criterion: a single .axon program exercises
    the whole stack (Fases 1-6) through the EnterpriseApplication
    facade and produces production-grade artifacts."""

    def test_healthcare_reference_end_to_end(self):
        app = EnterpriseApplication.from_file(
            EXAMPLES / "healthcare_reference.axon",
        )

        # Fase 2: provision via the default Free-Monad handler.
        report = app.provision(handler="dry_run")
        assert report.manifests_provisioned == 1
        assert report.observations_executed == 1

        # Fase 5: train the immune detector and observe anomalies.
        import random
        rng = random.Random(0x5AFE)
        app.train_immune(
            "ClinicalVigil",
            [rng.choice(["normal_a", "normal_b", "normal_c"]) for _ in range(200)],
        )
        hr, reflexes, heals = app.observe("ClinicalVigil", "unusual_token")
        assert hr.immune_name == "ClinicalVigil"

        # Fase 6.2: route through the EID and land in the provenance chain.
        event = app.check_intrusion(hr)
        # The observation may or may not cross the trigger level depending
        # on KL; we assert that the pipeline completes without error.
        assert event is None or event.immune_name == "ClinicalVigil"

        # Fase 6.1 + 6.6: dossier + SBOM for audit consumption.
        dossier = app.dossier()
        sbom = app.sbom()
        assert "HIPAA" in dossier.classes_covered
        assert sbom.program_hash == dossier.program_hash
        assert dossier.unshielded_regulated == []

    def test_banking_reference_produces_full_dossier(self):
        app = EnterpriseApplication.from_file(
            EXAMPLES / "banking_reference.axon",
        )
        dossier = app.dossier()
        assert {"PCI_DSS", "SOX", "SOC2"}.issubset(set(dossier.classes_covered))
        assert "PaymentsAPI" in dossier.shielded_endpoints
        assert "FraudAPI" in dossier.shielded_endpoints

    def test_government_reference_produces_full_dossier(self):
        app = EnterpriseApplication.from_file(
            EXAMPLES / "government_reference.axon",
        )
        dossier = app.dossier()
        assert {"FISMA", "NIST_800_53"}.issubset(set(dossier.classes_covered))
        assert "CaseIntakeAPI" in dossier.shielded_endpoints

    def test_all_three_references_have_unique_hashes(self):
        a = EnterpriseApplication.from_file(EXAMPLES / "banking_reference.axon").sbom()
        g = EnterpriseApplication.from_file(EXAMPLES / "government_reference.axon").sbom()
        h = EnterpriseApplication.from_file(EXAMPLES / "healthcare_reference.axon").sbom()
        assert len({a.program_hash, g.program_hash, h.program_hash}) == 3
