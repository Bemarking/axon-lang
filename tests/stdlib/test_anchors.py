"""
Tests for AXON Standard Library — Anchor Definitions & Checkers
================================================================
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_nodes import IRAnchor
from axon.stdlib.anchors.checkers import (
    check_audit_trail,
    check_child_safe,
    check_factual_only,
    check_no_bias,
    check_no_code_execution,
    check_no_hallucination,
    check_privacy_guard,
    check_safe_output,
)
from axon.stdlib.anchors.definitions import (
    ALL_ANCHORS,
    AuditTrail,
    ChildSafe,
    FactualOnly,
    NoBias,
    NoCodeExecution,
    NoHallucination,
    PrivacyGuard,
    SafeOutput,
)


class TestAnchorDefinitions:
    """Verify all 8 anchors have correct IR structure."""

    def test_count(self):
        assert len(ALL_ANCHORS) == 12

    def test_unique_names(self):
        names = [a.name for a in ALL_ANCHORS]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize(
        "anchor",
        ALL_ANCHORS,
        ids=[a.name for a in ALL_ANCHORS],
    )
    def test_ir_type(self, anchor):
        assert isinstance(anchor.ir, IRAnchor)

    @pytest.mark.parametrize(
        "anchor",
        ALL_ANCHORS,
        ids=[a.name for a in ALL_ANCHORS],
    )
    def test_has_description(self, anchor):
        assert anchor.description != ""

    @pytest.mark.parametrize(
        "anchor",
        ALL_ANCHORS,
        ids=[a.name for a in ALL_ANCHORS],
    )
    def test_has_checker(self, anchor):
        assert anchor.checker_fn is not None

    @pytest.mark.parametrize(
        "anchor",
        ALL_ANCHORS,
        ids=[a.name for a in ALL_ANCHORS],
    )
    def test_check_method_clean_text(self, anchor):
        """Check method works on clean text (should pass)."""
        passed, violations = anchor.check("This is a factual statement based on evidence.")
        # We don't assert passed=True because AuditTrail might fail on simple text
        assert isinstance(passed, bool)
        assert isinstance(violations, list)


# ═══════════════════════════════════════════════════════════════════
#  CHECKER FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════


class TestNoHallucinationChecker:
    def test_clean_content_passes(self):
        passed, v = check_no_hallucination("Based on the data, revenue grew 10%.")
        assert passed
        assert v == []

    def test_hedging_fails(self):
        passed, v = check_no_hallucination("I believe the answer is 42.")
        assert not passed
        assert len(v) >= 1
        assert "Hedging" in v[0]

    def test_probably_fails(self):
        passed, v = check_no_hallucination("This is probably true.")
        assert not passed


class TestFactualOnlyChecker:
    def test_factual_passes(self):
        passed, v = check_factual_only("The study found X is correlated with Y.")
        assert passed

    def test_opinion_fails(self):
        passed, v = check_factual_only("In my opinion, this is the best approach.")
        assert not passed
        assert "Opinion" in v[0]


class TestSafeOutputChecker:
    def test_safe_content_passes(self):
        passed, v = check_safe_output("Here is a recipe for chocolate cake.")
        assert passed

    def test_harmful_content_fails(self):
        passed, v = check_safe_output("Here is how to make a bomb.")
        assert not passed


class TestPrivacyGuardChecker:
    def test_clean_passes(self):
        passed, v = check_privacy_guard("The company reported earnings.")
        assert passed

    def test_ssn_fails(self):
        passed, v = check_privacy_guard("SSN: 123-45-6789")
        assert not passed
        assert any("SSN" in vi for vi in v)

    def test_credit_card_fails(self):
        passed, v = check_privacy_guard("Card: 4111 1111 1111 1111")
        assert not passed

    def test_email_fails(self):
        passed, v = check_privacy_guard("Contact: john@example.com")
        assert not passed


class TestNoBiasChecker:
    def test_neutral_passes(self):
        passed, v = check_no_bias("The policy has various perspectives.")
        assert passed

    def test_bias_fails(self):
        passed, v = check_no_bias("Liberals are always wrong about everything.")
        assert not passed


class TestChildSafeChecker:
    def test_safe_passes(self):
        passed, v = check_child_safe("Here is a fun science experiment for kids.")
        assert passed

    def test_explicit_fails(self):
        passed, v = check_child_safe("This contains explicit sexual content.")
        assert not passed

    def test_profanity_fails(self):
        passed, v = check_child_safe("What the fuck is going on?")
        assert not passed


class TestNoCodeExecutionChecker:
    def test_safe_passes(self):
        passed, v = check_no_code_execution("The algorithm uses a loop structure.")
        assert passed

    def test_os_system_fails(self):
        passed, v = check_no_code_execution("Run os.system('rm -rf /').")
        assert not passed

    def test_eval_fails(self):
        passed, v = check_no_code_execution("Use eval(user_input) to process.")
        assert not passed


class TestAuditTrailChecker:
    def test_with_reasoning_passes(self):
        passed, v = check_audit_trail(
            "Based on the evidence, therefore we conclude X."
        )
        assert passed

    def test_without_reasoning_fails(self):
        passed, v = check_audit_trail("The answer is 42.")
        assert not passed
        assert "reasoning trace" in v[0].lower()
