"""
AXON Runtime — ESK runtime tests (Fase 6.2 / 6.4 / 6.5 / 6.6 / 6.7)
=====================================================================
Covers: provenance signing + Merkle chain, Secret<T> no-materialize
invariant, differential privacy (Laplace / Gaussian + ε-budget),
SBOM + compliance dossier generation, Epistemic Intrusion Detector.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.esk import (
    BudgetExhaustedError,
    COMPLIANCE_REGISTRY,
    DifferentialPrivacyPolicy,
    EpistemicIntrusionDetector,
    HmacSigner,
    PrivacyBudget,
    ProvenanceChain,
    Secret,
    canonical_bytes,
    classify_sector,
    content_hash,
    covers,
    gaussian_noise,
    generate_dossier,
    generate_sbom,
    laplace_noise,
    sign_envelope,
    verify_envelope,
)
from axon.runtime.immune.health_report import make_health_report


def _compile(source: str):
    return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())


# ═══════════════════════════════════════════════════════════════════
#  compliance.py
# ═══════════════════════════════════════════════════════════════════


class TestComplianceRegistry:

    def test_registry_contains_known_classes(self):
        for label in ("HIPAA", "PCI_DSS", "GDPR", "SOX", "SOC2", "GxP"):
            assert label in COMPLIANCE_REGISTRY

    def test_covers_returns_missing(self):
        assert covers(["HIPAA"], ["HIPAA"]) == set()
        assert covers(["HIPAA"], ["HIPAA", "GDPR"]) == {"GDPR"}
        assert covers([], ["HIPAA"]) == {"HIPAA"}

    def test_classify_sector(self):
        sectors = classify_sector(["HIPAA", "PCI_DSS"])
        assert "healthcare" in sectors
        assert "financial" in sectors


# ═══════════════════════════════════════════════════════════════════
#  provenance.py — HMAC signing + Merkle chain
# ═══════════════════════════════════════════════════════════════════


class TestProvenanceSigning:

    def test_hmac_sign_and_verify(self):
        signer = HmacSigner.random()
        msg = b"payload"
        sig = signer.sign(msg)
        assert signer.verify(msg, sig)

    def test_verify_fails_on_tampered_message(self):
        signer = HmacSigner.random()
        sig = signer.sign(b"original")
        assert not signer.verify(b"tampered", sig)

    def test_signed_envelope_roundtrip(self):
        signer = HmacSigner(key=b"k" * 32)
        env = sign_envelope(
            c=0.9, tau="2026-04-19T00:00:00+00:00", rho="handler",
            delta="observed", data={"x": 1}, signer=signer,
        )
        assert verify_envelope(env, {"x": 1}, signer)

    def test_verify_envelope_fails_on_tampered_data(self):
        signer = HmacSigner(key=b"k" * 32)
        env = sign_envelope(
            c=0.9, tau="2026-04-19T00:00:00+00:00", rho="handler",
            delta="observed", data={"x": 1}, signer=signer,
        )
        assert not verify_envelope(env, {"x": 2}, signer)

    def test_canonical_bytes_is_deterministic(self):
        a = canonical_bytes({"b": 2, "a": 1})
        b = canonical_bytes({"a": 1, "b": 2})
        assert a == b

    def test_content_hash_stable(self):
        h1 = content_hash({"k": 1})
        h2 = content_hash({"k": 1})
        assert h1 == h2


class TestProvenanceChain:

    def test_append_and_verify(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        chain.append({"n": 1})
        chain.append({"n": 2})
        chain.append({"n": 3})
        assert chain.verify([{"n": 1}, {"n": 2}, {"n": 3}])

    def test_detect_payload_tampering(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        chain.append({"n": 1})
        chain.append({"n": 2})
        assert not chain.verify([{"n": 1}, {"n": 999}])

    def test_detect_reorder(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        chain.append({"n": 1})
        chain.append({"n": 2})
        assert not chain.verify([{"n": 2}, {"n": 1}])

    def test_head_updates_on_append(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        h0 = chain.head
        chain.append({"x": 1})
        h1 = chain.head
        chain.append({"x": 2})
        h2 = chain.head
        assert h0 != h1 != h2


# ═══════════════════════════════════════════════════════════════════
#  secret.py — no-materialize invariant
# ═══════════════════════════════════════════════════════════════════


class TestSecret:

    def test_repr_is_redacted(self):
        s = Secret("sk-live-abc123")
        assert repr(s) == "Secret<redacted>"
        assert str(s) == "Secret<redacted>"
        assert f"{s}" == "Secret<redacted>"

    def test_as_dict_never_contains_payload(self):
        s = Secret("sk-live-abc123", label="stripe.api_key")
        d = s.as_dict()
        assert "sk-live-abc123" not in json.dumps(d)
        assert d["redacted"] is True
        assert d["label"] == "stripe.api_key"

    def test_reveal_returns_payload(self):
        s = Secret({"pw": "x"})
        revealed = s.reveal(accessor="db_writer", purpose="connect")
        assert revealed == {"pw": "x"}

    def test_reveal_records_audit(self):
        s = Secret("payload")
        s.reveal(accessor="a1", purpose="p1")
        s.reveal(accessor="a2", purpose="p2")
        trail = s.audit_trail
        assert [a.accessor for a in trail] == ["a1", "a2"]
        assert all(a.timestamp for a in trail)

    def test_reveal_requires_accessor(self):
        s = Secret("x")
        with pytest.raises(Exception, match="accessor"):
            s.reveal(accessor="", purpose="leak")

    def test_nested_secret_rejected(self):
        inner = Secret("x")
        with pytest.raises(Exception, match="nesting"):
            Secret(inner)

    def test_equality_via_fingerprint(self):
        a = Secret("same")
        b = Secret("same")
        c = Secret("different")
        assert a == b
        assert a != c

    def test_map_hides_plaintext(self):
        s = Secret("password123")
        length = s.map(len, accessor="test", purpose="len_measurement")
        assert length == 11
        # The lambda received the payload, but the caller never held it.

    def test_allow_repr_reveals_fingerprint_but_not_payload(self):
        s = Secret("secret", label="api", allow_repr=True)
        text = repr(s)
        assert "secret" not in text
        assert "api" in text


# ═══════════════════════════════════════════════════════════════════
#  privacy.py — Laplace / Gaussian + ε-budget
# ═══════════════════════════════════════════════════════════════════


class TestNoiseMechanisms:

    def test_laplace_mean_converges_to_value(self):
        rng = random.Random(0xDA7A)
        samples = [laplace_noise(100.0, sensitivity=1.0, epsilon=1.0, rng=rng)
                   for _ in range(10000)]
        mean = sum(samples) / len(samples)
        assert abs(mean - 100.0) < 0.5

    def test_laplace_variance_scales_with_scale(self):
        rng_a = random.Random(1)
        rng_b = random.Random(1)
        loose = [laplace_noise(0.0, sensitivity=1.0, epsilon=0.1, rng=rng_a)
                 for _ in range(2000)]
        tight = [laplace_noise(0.0, sensitivity=1.0, epsilon=10.0, rng=rng_b)
                 for _ in range(2000)]
        var_loose = sum(x * x for x in loose) / len(loose)
        var_tight = sum(x * x for x in tight) / len(tight)
        assert var_loose > var_tight * 10  # much larger for smaller epsilon

    def test_laplace_rejects_bad_params(self):
        with pytest.raises(Exception):
            laplace_noise(0.0, sensitivity=1.0, epsilon=-1)
        with pytest.raises(Exception):
            laplace_noise(0.0, sensitivity=-1.0, epsilon=1.0)

    def test_gaussian_mean_converges(self):
        rng = random.Random(0xABC)
        samples = [gaussian_noise(50.0, sensitivity=1.0, epsilon=0.5,
                                  delta=1e-5, rng=rng) for _ in range(10000)]
        assert abs(sum(samples) / len(samples) - 50.0) < 0.5

    def test_gaussian_rejects_epsilon_above_one(self):
        with pytest.raises(Exception):
            gaussian_noise(0.0, sensitivity=1.0, epsilon=2.0, delta=1e-5)


class TestPrivacyBudget:

    def test_spend_within_budget(self):
        budget = PrivacyBudget(epsilon_max=1.0)
        budget.spend(0.3)
        budget.spend(0.4)
        assert budget.epsilon_remaining == pytest.approx(0.3, abs=1e-9)

    def test_spend_over_budget_raises(self):
        budget = PrivacyBudget(epsilon_max=1.0)
        budget.spend(0.5)
        with pytest.raises(BudgetExhaustedError, match="budget exhausted"):
            budget.spend(0.6)

    def test_ledger_records_every_spend(self):
        budget = PrivacyBudget(epsilon_max=1.0)
        budget.spend(0.1, note="obs_a")
        budget.spend(0.2, note="obs_b")
        notes = [entry[0] for entry in budget.ledger]
        assert notes == ["obs_a", "obs_b"]

    def test_policy_consumes_budget(self):
        budget = PrivacyBudget(epsilon_max=1.0)
        policy = DifferentialPrivacyPolicy(epsilon_per_call=0.25, sensitivity=1.0)
        rng = random.Random(0x7E57)
        noisy = policy.apply(100.0, budget, rng=rng, note="t1")
        assert budget.epsilon_spent == pytest.approx(0.25)
        assert isinstance(noisy, float)


# ═══════════════════════════════════════════════════════════════════
#  attestation.py — SBOM + dossier
# ═══════════════════════════════════════════════════════════════════


class TestSBOM:

    _SRC = '''
type PHI compliance [HIPAA] { ssn: String }
flow P(x: PHI) -> String { step S { ask: "a" output: String } }
shield S { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
axonendpoint A {
  method: post path: "/p" body: PHI execute: P output: String
  shield: S compliance: [HIPAA]
}
'''

    def test_sbom_lists_all_declarations(self):
        ir = _compile(self._SRC)
        sbom = generate_sbom(ir)
        kinds = {e.kind for e in sbom.entries}
        assert {"type", "flow", "shield", "axonendpoint"}.issubset(kinds)

    def test_sbom_content_hash_is_deterministic(self):
        ir = _compile(self._SRC)
        a = generate_sbom(ir)
        b = generate_sbom(ir)
        assert a.program_hash == b.program_hash

    def test_sbom_detects_program_change(self):
        ir_a = _compile(self._SRC)
        ir_b = _compile(self._SRC + '\ntype Extra { x: String }')
        assert generate_sbom(ir_a).program_hash != generate_sbom(ir_b).program_hash

    def test_sbom_entries_carry_compliance(self):
        ir = _compile(self._SRC)
        sbom = generate_sbom(ir)
        phi = next(e for e in sbom.entries if e.name == "PHI")
        assert phi.compliance == ("HIPAA",)


class TestComplianceDossier:

    _SRC = '''
type PHI compliance [HIPAA] { ssn: String }
type Card compliance [PCI_DSS] { pan: String }
flow Pa(x: PHI) -> String { step S { ask: "a" output: String } }
flow Pc(x: Card) -> String { step S { ask: "a" output: String } }
shield H { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
shield C { scan: [pii_leak] on_breach: quarantine severity: high compliance: [PCI_DSS] }
axonendpoint Ah {
  method: post path: "/h" body: PHI execute: Pa output: String
  shield: H compliance: [HIPAA]
}
axonendpoint Ac {
  method: post path: "/c" body: Card execute: Pc output: String
  shield: C compliance: [PCI_DSS]
}
'''

    def test_dossier_summarizes_regulatory_posture(self):
        ir = _compile(self._SRC)
        dossier = generate_dossier(ir)
        assert set(dossier.classes_covered) == {"HIPAA", "PCI_DSS"}
        assert set(dossier.sectors) == {"healthcare", "financial"}
        assert set(dossier.shielded_endpoints) == {"Ah", "Ac"}
        assert dossier.unshielded_regulated == []

    def test_dossier_is_json_serializable(self):
        ir = _compile(self._SRC)
        dossier = generate_dossier(ir)
        text = json.dumps(dossier.to_dict(), sort_keys=True)
        assert "HIPAA" in text
        assert "PCI_DSS" in text


# ═══════════════════════════════════════════════════════════════════
#  eid.py — Epistemic Intrusion Detector
# ═══════════════════════════════════════════════════════════════════


class TestEpistemicIntrusionDetector:

    def _report(self, kl: float, signature: str = "sig") -> object:
        return make_health_report(
            immune_name="V", kl_divergence=kl, signature=signature,
        )

    def test_below_trigger_returns_none(self):
        eid = EpistemicIntrusionDetector(trigger_level="speculate")
        assert eid.observe(self._report(0.1)) is None

    def test_speculate_level_fires_event(self):
        eid = EpistemicIntrusionDetector(trigger_level="speculate")
        event = eid.observe(self._report(0.75))
        assert event is not None
        assert event.severity in {"high", "critical"}
        assert event.shield_verdict == "approved"

    def test_doubt_level_is_critical(self):
        eid = EpistemicIntrusionDetector(trigger_level="speculate")
        event = eid.observe(self._report(0.98))
        assert event.severity == "critical"

    def test_provenance_chain_receives_event(self):
        signer = HmacSigner.random()
        chain = ProvenanceChain(signer)
        eid = EpistemicIntrusionDetector(
            trigger_level="speculate", chain=chain,
        )
        eid.observe(self._report(0.92, signature="attack-1"))
        eid.observe(self._report(0.95, signature="attack-2"))
        entries = chain.entries()
        assert len(entries) == 2
        # Tampering detection: entries are hash-linked.
        assert entries[1].previous_hash == entries[0].chain_hash

    def test_shield_verdict_deferred_is_recorded(self):
        from axon.runtime.esk.eid import always_defer
        eid = EpistemicIntrusionDetector(
            trigger_level="speculate", shield_verdict=always_defer,
        )
        event = eid.observe(self._report(0.95))
        assert event.shield_verdict == "deferred"
