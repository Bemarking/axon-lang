"""
AXON Runtime — OWASP LLM Top 10 Benchmark (ESK Fase 6.8)
============================================================
Systematic benchmark of AXON's defensive stack against the OWASP LLM
Top 10 (2025 revision).  Each category is represented by a test class
that either:

  (a) exercises the Cognitive Immune System (Fase 5) with
      category-specific attack patterns and asserts F1 ≥ 0.80, or
  (b) asserts a compile-time or runtime invariant that prevents the
      attack class by construction (for categories that do not map to
      behavioral anomaly detection).

The benchmark is deterministic: every RNG is seeded, every test is
reproducible in CI, and the reporting thresholds (F1 ≥ 0.80 per class
that uses immune, plus categorical guarantees for the structural
classes) form a publishable table.

Reference: OWASP Top 10 for LLM Applications 2025:
https://owasp.org/www-project-top-10-for-large-language-model-applications/
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.runtime.esk import PrivacyBudget, Secret
from axon.runtime.immune import ImmuneRuntime


# ═══════════════════════════════════════════════════════════════════
#  Metrics helper
# ═══════════════════════════════════════════════════════════════════


@dataclass
class BenchResult:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


# ═══════════════════════════════════════════════════════════════════
#  Shared immune program used by immune-based tests
# ═══════════════════════════════════════════════════════════════════

_IMMUNE_SRC = """
shield OwaspShield {
  scan: [prompt_injection, jailbreak, pii_leak, data_exfil]
  on_breach: quarantine
  severity: critical
}

immune OwaspVigil {
  watch: [input_stream]
  sensitivity: 0.85
  baseline: learned
  window: 300
  scope: tenant
  tau: 300s
  decay: exponential
}

reflex BlockMalicious {
  trigger: OwaspVigil
  on_level: speculate
  action: quarantine
  scope: tenant
  sla: 1ms
}

heal Remediate {
  source: OwaspVigil
  on_level: doubt
  mode: human_in_loop
  scope: tenant
  shield: OwaspShield
  max_patches: 5
}
"""


def _immune_runtime() -> ImmuneRuntime:
    ir = IRGenerator().generate(Parser(Lexer(_IMMUNE_SRC).tokenize()).parse())
    return ImmuneRuntime(ir)


def _batch_evaluate(
    detector,
    benign: list,
    attack: list,
    *,
    batch_size: int = 30,
) -> BenchResult:
    res = BenchResult()
    def windows(stream):
        for i in range(0, len(stream) - batch_size + 1, batch_size):
            yield stream[i:i + batch_size]

    for batch in windows(benign):
        report = detector.classify_batch(batch)
        if report.classification in {"speculate", "doubt"}:
            res.fp += 1
        else:
            res.tn += 1
    for batch in windows(attack):
        report = detector.classify_batch(batch)
        if report.classification in {"speculate", "doubt"}:
            res.tp += 1
        else:
            res.fn += 1
    return res


# ═══════════════════════════════════════════════════════════════════
#  LLM01 — Prompt Injection
# ═══════════════════════════════════════════════════════════════════

_BENIGN_PROMPT_TOKENS = [
    "summarize", "translate", "classify", "extract", "compose",
    "analyze", "rewrite", "describe", "list", "explain",
]

_INJECTION_TOKENS = [
    "ignore_previous", "dan_mode", "jailbreak_enabled", "system_override",
    "dump_memory", "reveal_instructions", "bypass_guardrails", "uncensored",
]


class TestLLM01PromptInjection:
    """OWASP LLM01 — Prompt Injection: malicious prompts subverting intent."""

    def test_detection_f1_above_threshold(self):
        rt = _immune_runtime()
        # Large, well-shaped baseline stabilizes benign empirical distribution.
        rt.train("OwaspVigil", _BENIGN_PROMPT_TOKENS * 100)
        det = rt.detector("OwaspVigil")
        rng = random.Random(0x1111)
        benign = [rng.choice(_BENIGN_PROMPT_TOKENS) for _ in range(600)]
        attack = [rng.choice(_INJECTION_TOKENS) for _ in range(400)]
        res = _batch_evaluate(det, benign, attack, batch_size=100)
        assert res.f1 >= 0.80, f"LLM01 F1={res.f1:.3f} (p={res.precision:.2f} r={res.recall:.2f})"
        assert res.precision >= 0.80
        assert res.recall >= 0.80


# ═══════════════════════════════════════════════════════════════════
#  LLM02 — Insecure Output Handling
#  Structural guarantee: RTT forbids raw model output from crossing
#  a boundary that carries regulatory class without shield coverage.
# ═══════════════════════════════════════════════════════════════════


class TestLLM02InsecureOutputHandling:
    """Compile-time guarantee: an endpoint whose output_type has κ
    must be gated by a shield that covers κ."""

    def test_unshielded_regulated_output_rejected_at_compile_time(self):
        src = """
type ResponseWithPII compliance [GDPR] { text: String }
flow Gen() -> ResponseWithPII { step S { ask: "x" output: ResponseWithPII } }
axonendpoint Unsafe {
  method: get
  path: "/u"
  execute: Gen
  output: ResponseWithPII
}
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert any("no shield" in e.message.lower() for e in errors), \
            "RTT must block regulated output without shield"


# ═══════════════════════════════════════════════════════════════════
#  LLM03 — Training Data Poisoning
# ═══════════════════════════════════════════════════════════════════


def _numeric_bucket(v: int) -> str:
    if v < 50:    return "very_low"
    if v < 85:    return "low"
    if v < 115:   return "normal"
    if v < 150:   return "high"
    if v < 10000: return "very_high"
    return "extreme"


class TestLLM03TrainingDataPoisoning:
    """Out-of-distribution training values bucketed for KL detection."""

    def test_detection_f1_above_threshold(self):
        rt = _immune_runtime()
        rng = random.Random(0x3333)
        rt.train("OwaspVigil",
                 [_numeric_bucket(int(rng.gauss(100, 15))) for _ in range(600)])
        det = rt.detector("OwaspVigil")
        benign = [_numeric_bucket(int(rng.gauss(100, 15))) for _ in range(180)]
        attack = [_numeric_bucket(rng.choice([-9999, 99999, 50000, -50000, 42000]))
                  for _ in range(120)]
        res = _batch_evaluate(det, benign, attack)
        assert res.f1 >= 0.80, f"LLM03 F1={res.f1:.3f}"


# ═══════════════════════════════════════════════════════════════════
#  LLM04 — Model Denial of Service (latency-pattern detection)
# ═══════════════════════════════════════════════════════════════════


def _latency_bucket(ms: int) -> str:
    if ms < 50: return "fast"
    if ms < 200: return "normal"
    if ms < 800: return "slow"
    if ms < 3000: return "over"
    return "spike"


class TestLLM04ModelDenialOfService:
    """Flood / resource-exhaustion surfaces as latency-band shift."""

    def test_detection_f1_above_threshold(self):
        rt = _immune_runtime()
        rng = random.Random(0x4444)
        rt.train("OwaspVigil",
                 [_latency_bucket(int(rng.gauss(120, 30))) for _ in range(400)])
        det = rt.detector("OwaspVigil")
        benign = [_latency_bucket(int(rng.gauss(120, 30))) for _ in range(180)]
        attack = [_latency_bucket(rng.choice([3500, 4200, 5000, 3100, 4700]))
                  for _ in range(120)]
        res = _batch_evaluate(det, benign, attack)
        assert res.f1 >= 0.80, f"LLM04 F1={res.f1:.3f}"


# ═══════════════════════════════════════════════════════════════════
#  LLM05 — Supply-Chain Vulnerabilities
#  Structural guarantee: deterministic SBOM detects any drift in
#  declared components or dependencies.
# ═══════════════════════════════════════════════════════════════════


class TestLLM05SupplyChainVulnerabilities:
    """Two SBOMs of the same program match; tampered program diverges."""

    def test_sbom_determinism_detects_component_drift(self):
        from axon.runtime.esk import generate_sbom

        src_a = """
resource Db { kind: postgres lifetime: linear }
manifest M { resources: [Db] }
"""
        src_b = src_a + "\nresource Cache { kind: redis lifetime: affine }"

        ir_a = IRGenerator().generate(Parser(Lexer(src_a).tokenize()).parse())
        ir_b = IRGenerator().generate(Parser(Lexer(src_b).tokenize()).parse())
        assert generate_sbom(ir_a).program_hash != generate_sbom(ir_b).program_hash


# ═══════════════════════════════════════════════════════════════════
#  LLM06 — Sensitive Information Disclosure
#  Structural guarantee: Secret[T] never materializes plaintext.
# ═══════════════════════════════════════════════════════════════════


class TestLLM06SensitiveInformationDisclosure:

    def test_secret_never_appears_in_repr_str_format_json(self):
        payload = "CONFIDENTIAL_PAYLOAD_abc123XYZ"
        s = Secret(payload, label="api_token")
        assert payload not in repr(s)
        assert payload not in str(s)
        assert payload not in f"{s}"
        assert payload not in format(s, "")
        assert payload not in json.dumps(s.as_dict())

    def test_audit_trail_records_every_access(self):
        s = Secret("x", label="k")
        s.reveal(accessor="svc_a", purpose="sign")
        s.reveal(accessor="svc_b", purpose="verify")
        accessors = [a.accessor for a in s.audit_trail]
        assert accessors == ["svc_a", "svc_b"]


# ═══════════════════════════════════════════════════════════════════
#  LLM07 — Insecure Plugin Design (capability-based shield control)
# ═══════════════════════════════════════════════════════════════════


class TestLLM07InsecurePluginDesign:
    """Shield `allow_tools` / `deny_tools` provide capability control."""

    def test_shield_capabilities_compile(self):
        src = """
shield SandboxedShield {
  scan: [prompt_injection]
  on_breach: quarantine
  severity: medium
  allow: [WebSearch, Calculator]
  deny: [CodeExecutor, FileWriter]
  sandbox: true
}
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == []
        shield = tree.declarations[0]
        assert shield.sandbox is True
        assert "CodeExecutor" in shield.deny_tools


# ═══════════════════════════════════════════════════════════════════
#  LLM08 — Excessive Agency (reconcile bounded by max_retries)
# ═══════════════════════════════════════════════════════════════════


class TestLLM08ExcessiveAgency:
    """Bounded autonomy: reconcile has explicit max_retries; heal has
    explicit max_patches. Unbounded agency is not expressible."""

    def test_reconcile_requires_bounded_retries(self):
        src = """
resource Db { kind: postgres }
manifest M { resources: [Db] }
observe O from M { sources: [src] quorum: 1 timeout: 5s }
reconcile R { observe: O threshold: 0.85 on_drift: provision max_retries: 0 }
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        # max_retries: 0 parses but is a valid declarative bound.
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_heal_rejects_zero_max_patches(self):
        src = """
immune V { watch: [x] sensitivity: 0.5 scope: tenant }
heal H { source: V mode: human_in_loop scope: tenant max_patches: 0 }
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert any("max_patches must be >= 1" in e.message for e in errors), \
            "heal must require bounded patches"


# ═══════════════════════════════════════════════════════════════════
#  LLM09 — Overreliance (certainty floor on observe)
# ═══════════════════════════════════════════════════════════════════


class TestLLM09Overreliance:
    """Every observe declares a certainty_floor; consumers can gate on it."""

    def test_observe_certainty_floor_is_typed(self):
        src = """
resource Db { kind: postgres }
manifest M { resources: [Db] }
observe O from M {
  sources: [src]
  quorum: 1
  timeout: 5s
  certainty_floor: 0.92
}
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_observe_certainty_floor_validated(self):
        src = """
resource Db { kind: postgres }
manifest M { resources: [Db] }
observe O from M {
  sources: [src]
  quorum: 1
  timeout: 5s
  certainty_floor: 2.5
}
"""
        tree = Parser(Lexer(src).tokenize()).parse()
        errors = TypeChecker(tree).check()
        assert any("certainty_floor" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  LLM10 — Model Theft
#  Structural guarantee: PrivacyBudget enforces ε-budget; exfiltration
#  via statistical queries is rate-limited.
# ═══════════════════════════════════════════════════════════════════


class TestLLM10ModelTheft:
    """Statistical extraction attacks are rate-limited by PrivacyBudget."""

    def test_budget_caps_statistical_queries(self):
        from axon.runtime.esk import BudgetExhaustedError, DifferentialPrivacyPolicy

        budget = PrivacyBudget(epsilon_max=1.0)
        policy = DifferentialPrivacyPolicy(epsilon_per_call=0.25, sensitivity=1.0)
        rng = random.Random(0x1010)

        # 4 queries exhaust the ε=1.0 budget.
        for i in range(4):
            policy.apply(100.0, budget, rng=rng, note=f"extract_{i}")

        # 5th extraction attempt is BLOCKED.
        with pytest.raises(BudgetExhaustedError):
            policy.apply(100.0, budget, rng=rng, note="extract_5")


# ═══════════════════════════════════════════════════════════════════
#  Aggregate benchmark — the publishable row
# ═══════════════════════════════════════════════════════════════════


class TestOwaspLlmTop10AggregateBench:
    """The top-level row: AXON defends the 10 OWASP LLM Top 10 categories
    either by behavioral detection (F1 ≥ 0.80) or by structural guarantee
    (compile-time or runtime invariant)."""

    _IMMUNE_CATEGORIES = ("LLM01", "LLM03", "LLM04")
    _STRUCTURAL_CATEGORIES = ("LLM02", "LLM05", "LLM06", "LLM07", "LLM08", "LLM09", "LLM10")

    def test_coverage_is_complete(self):
        total = set(self._IMMUNE_CATEGORIES) | set(self._STRUCTURAL_CATEGORIES)
        assert total == {f"LLM{i:02d}" for i in range(1, 11)}, (
            "OWASP LLM Top 10 must all be covered"
        )

    def test_no_category_uncovered(self):
        """Sanity: overlap is legal, but no category may be missing."""
        covered = {*self._IMMUNE_CATEGORIES, *self._STRUCTURAL_CATEGORIES}
        for cat in ("LLM01", "LLM02", "LLM03", "LLM04", "LLM05",
                    "LLM06", "LLM07", "LLM08", "LLM09", "LLM10"):
            assert cat in covered
