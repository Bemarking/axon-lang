"""
AXON Runtime — Phase 6 ESK Acceptance Test
=============================================
The Fase 6 closing criterion per docs/plan_io_cognitivo.md:

    "ESK demostrable con un piloto cliente en banca o gobierno + al
     menos 2 certificaciones en curso."

The "piloto cliente" is a business milestone.  In code terms, we
demonstrate a **working end-to-end security posture** by exercising a
single hospital-grade program through every ESK primitive in one
coherent scenario:

  (a) a program handling PHI (HIPAA) and cardholder data (PCI_DSS)
      without proper shield coverage IS REJECTED at compile time;
  (b) the same program with correct coverage compiles cleanly;
  (c) a supply-chain SBOM is generated with per-declaration content
      hashes;
  (d) a compliance dossier enumerates every regulatory class, sector,
      and shielded endpoint for audit consumption;
  (e) a Secret<T> carrying API credentials never materializes in logs;
  (f) an ε-budget is consumed across differential-privacy observations;
  (g) an Epistemic Intrusion Detector records anomaly events into a
      tamper-evident Merkle chain;
  (h) tampering with any recorded event is detected on verify.

All eight checks pass ⇒ ESK acceptance.
"""

from __future__ import annotations

import json

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.runtime.esk import (
    COMPLIANCE_REGISTRY,
    DifferentialPrivacyPolicy,
    EpistemicIntrusionDetector,
    HmacSigner,
    PrivacyBudget,
    ProvenanceChain,
    Secret,
    generate_dossier,
    generate_sbom,
)
from axon.runtime.immune.health_report import make_health_report


# ═══════════════════════════════════════════════════════════════════
#  The scenario: a bank-grade + hospital-grade program
# ═══════════════════════════════════════════════════════════════════

_UNSAFE_PROGRAM = '''
type PatientRecord compliance [HIPAA] { ssn: String  dob: String }
type CardData     compliance [PCI_DSS] { pan: String cvv: String }

flow AnalyzeRecord(r: PatientRecord) -> String { step S { ask: "a" output: String } }
flow ChargeCard(c: CardData)         -> String { step S { ask: "b" output: String } }

shield WeakShield {
  scan: [pii_leak]
  on_breach: quarantine
  severity: high
  compliance: [SOC2]
}

axonendpoint RecordsAPI {
  method: post path: "/records"
  body: PatientRecord
  execute: AnalyzeRecord
  output: String
  shield: WeakShield
}

axonendpoint PaymentsAPI {
  method: post path: "/pay"
  body: CardData
  execute: ChargeCard
  output: String
}
'''


_SAFE_PROGRAM = '''
type PatientRecord compliance [HIPAA] { ssn: String  dob: String }
type CardData     compliance [PCI_DSS] { pan: String cvv: String }

flow AnalyzeRecord(r: PatientRecord) -> String { step S { ask: "a" output: String } }
flow ChargeCard(c: CardData)         -> String { step S { ask: "b" output: String } }

shield HealthShield {
  scan: [pii_leak]
  on_breach: quarantine
  severity: critical
  compliance: [HIPAA, SOC2]
}

shield FinancialShield {
  scan: [pii_leak]
  on_breach: quarantine
  severity: critical
  compliance: [PCI_DSS, SOX]
}

axonendpoint RecordsAPI {
  method: post path: "/records"
  body: PatientRecord
  execute: AnalyzeRecord
  output: String
  shield: HealthShield
  compliance: [HIPAA]
}

axonendpoint PaymentsAPI {
  method: post path: "/pay"
  body: CardData
  execute: ChargeCard
  output: String
  shield: FinancialShield
  compliance: [PCI_DSS]
}

immune HospitalVigil {
  watch: [RecordsAPI]
  sensitivity: 0.85
  scope: tenant
  tau: 300s
}
'''


class TestPhase6Acceptance:
    """Every `(x)` below corresponds to an ESK sub-phase acceptance check."""

    # ── (a) unsafe program rejected ───────────────────────────────

    def test_a_unsafe_program_rejected_at_compile_time(self):
        """Shield coverage missing ⇒ compile error.  The compiler is the auditor."""
        tree = Parser(Lexer(_UNSAFE_PROGRAM).tokenize()).parse()
        errors = TypeChecker(tree).check()
        messages = [e.message for e in errors]

        assert any("RecordsAPI" in m and "HIPAA" in m for m in messages), \
            "expected compile-time block on HIPAA coverage gap"
        assert any("PaymentsAPI" in m and "no shield" in m for m in messages), \
            "expected compile-time block on regulated endpoint missing shield"

    # ── (b) safe program compiles ────────────────────────────────

    def test_b_safe_program_compiles_clean(self):
        tree = Parser(Lexer(_SAFE_PROGRAM).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == [], f"safe program should compile clean, got: {[e.message for e in errors]}"

    # ── (c) SBOM ──────────────────────────────────────────────────

    def test_c_sbom_includes_every_declaration(self):
        ir = IRGenerator().generate(Parser(Lexer(_SAFE_PROGRAM).tokenize()).parse())
        sbom = generate_sbom(ir)
        names = {e.name for e in sbom.entries}
        assert {"PatientRecord", "CardData", "HealthShield",
                "FinancialShield", "RecordsAPI", "PaymentsAPI",
                "HospitalVigil"}.issubset(names)
        assert sbom.program_hash  # a real hash
        assert len(sbom.program_hash) == 64  # sha-256 hex

    # ── (d) compliance dossier ────────────────────────────────────

    def test_d_dossier_has_both_sectors(self):
        ir = IRGenerator().generate(Parser(Lexer(_SAFE_PROGRAM).tokenize()).parse())
        dossier = generate_dossier(ir)
        # Every class declared across the program is captured — both the
        # type-required classes AND the shield-covered classes.  That's
        # the full regulatory posture auditors need.
        assert {"HIPAA", "PCI_DSS"}.issubset(set(dossier.classes_covered))
        assert {"SOC2", "SOX"}.issubset(set(dossier.classes_covered))  # shield-covered
        assert {"healthcare", "financial"}.issubset(set(dossier.sectors))
        assert set(dossier.shielded_endpoints) == {"RecordsAPI", "PaymentsAPI"}
        assert dossier.unshielded_regulated == []
        # Dossier is JSON-serializable — audits consume JSON, not pickle.
        assert json.dumps(dossier.to_dict(), sort_keys=True)

    # ── (e) Secret<T> no-materialize ──────────────────────────────

    def test_e_secret_never_materializes(self):
        api_key = Secret("sk-LIVE-should-never-leak", label="stripe.api_key")

        # repr / str
        assert "sk-LIVE" not in repr(api_key)
        assert "sk-LIVE" not in str(api_key)

        # dict form (sent to SBOM / logs)
        d_text = json.dumps(api_key.as_dict())
        assert "sk-LIVE" not in d_text

        # f-string / format
        assert "sk-LIVE" not in f"{api_key}"
        assert "sk-LIVE" not in format(api_key, "")

        # reveal only with accessor (audit)
        raw = api_key.reveal(accessor="stripe_signer", purpose="auth_header")
        assert raw.startswith("sk-LIVE")
        trail = api_key.audit_trail
        assert len(trail) == 1
        assert trail[0].accessor == "stripe_signer"

    # ── (f) differential-privacy budget ───────────────────────────

    def test_f_privacy_budget_is_consumed_and_capped(self):
        budget = PrivacyBudget(epsilon_max=1.0)
        policy = DifferentialPrivacyPolicy(
            epsilon_per_call=0.2, sensitivity=1.0, mechanism="laplace",
        )
        import random
        rng = random.Random(0xA1B)

        noisy_outputs = []
        for i in range(5):
            noisy_outputs.append(policy.apply(100.0, budget, rng=rng, note=f"obs_{i}"))

        assert budget.epsilon_spent == pytest.approx(1.0, abs=1e-9)
        assert budget.epsilon_remaining == pytest.approx(0.0, abs=1e-9)

        # Sixth call exhausts the budget.
        from axon.runtime.esk import BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError, match="budget exhausted"):
            policy.apply(100.0, budget, rng=rng)

        # Outputs are noisy — none exactly 100.0
        assert all(abs(v - 100.0) > 1e-9 for v in noisy_outputs)

    # ── (g) EID + Merkle chain receives intrusion events ──────────

    def test_g_eid_events_landed_in_tamper_evident_chain(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        eid = EpistemicIntrusionDetector(trigger_level="speculate", chain=chain)

        # Two anomaly events, one benign observation (below trigger).
        eid.observe(make_health_report(
            immune_name="HospitalVigil", kl_divergence=0.92,
            signature="prompt_injection_attempt_1",
        ))
        eid.observe(make_health_report(
            immune_name="HospitalVigil", kl_divergence=0.10,
            signature="benign_observation",
        ))
        eid.observe(make_health_report(
            immune_name="HospitalVigil", kl_divergence=0.98,
            signature="data_exfil_attempt",
        ))

        # Only the two anomalies should appear; the benign one is below speculate.
        assert len(eid.events) == 2
        assert [e.severity for e in eid.events] == ["critical", "critical"]
        # Both are recorded in the Merkle chain.
        entries = chain.entries()
        assert len(entries) == 2
        # Hash links are intact.
        assert entries[1].previous_hash == entries[0].chain_hash

    # ── (h) tampering is detected ─────────────────────────────────

    def test_h_tampering_is_detected(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        chain.append({"event": "intrusion_1", "kl": 0.9})
        chain.append({"event": "intrusion_2", "kl": 0.95})
        assert chain.verify([
            {"event": "intrusion_1", "kl": 0.9},
            {"event": "intrusion_2", "kl": 0.95},
        ])
        # Any tamper invalidates the chain.
        assert not chain.verify([
            {"event": "intrusion_1", "kl": 0.9},
            {"event": "intrusion_2", "kl": 0.00},  # tampered evidence
        ])


# ═══════════════════════════════════════════════════════════════════
#  End-to-end workflow — one test that touches every primitive
# ═══════════════════════════════════════════════════════════════════


class TestEndToEndESKWorkflow:
    """The bank-pilot workflow: a single program, every ESK primitive."""

    def test_pilot_workflow_demonstrates_all_esk_primitives(self):
        # 1. Compile a safe program; verify clean type-check.
        tree = Parser(Lexer(_SAFE_PROGRAM).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == []

        # 2. Lower to IR, generate SBOM + dossier.
        ir = IRGenerator().generate(tree)
        sbom = generate_sbom(ir, axon_version="1.0.0")
        dossier = generate_dossier(ir, axon_version="1.0.0")
        assert sbom.program_hash == dossier.program_hash
        assert {"HIPAA", "PCI_DSS"}.issubset(set(dossier.classes_covered))

        # 3. Manage a secret without leakage.
        db_password = Secret("H0sp1tal!DBPass#Q9", label="postgres.hospital_ro")
        encoded = db_password.map(lambda s: s.upper(), accessor="bootstrap", purpose="connect")
        assert encoded == "H0SP1TAL!DBPASS#Q9"
        assert "H0sp1tal" not in repr(db_password)

        # 4. Enforce a differential-privacy budget across observations.
        budget = PrivacyBudget(epsilon_max=0.5)
        policy = DifferentialPrivacyPolicy(epsilon_per_call=0.1, sensitivity=1.0)
        import random
        rng = random.Random(0x5AFE)
        outputs = [policy.apply(120.0, budget, rng=rng, note=f"obs_{i}") for i in range(5)]
        assert len(outputs) == 5
        assert budget.epsilon_remaining == pytest.approx(0.0, abs=1e-9)

        # 5. Plug EID into a provenance chain.
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        eid = EpistemicIntrusionDetector(trigger_level="speculate", chain=chain)
        eid.observe(make_health_report(
            immune_name="HospitalVigil", kl_divergence=0.96,
            signature="exfil_attempt",
        ))
        assert len(eid.events) == 1
        assert chain.entries()[0].chain_hash  # Merkle-anchored

        # 6. Verify the dossier + SBOM hash is deterministic — audit can replay.
        assert generate_sbom(ir).program_hash == sbom.program_hash
        assert generate_dossier(ir).classes_covered == dossier.classes_covered
