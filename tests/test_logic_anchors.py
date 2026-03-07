import pytest
import re

from axon.stdlib.anchors.checkers import (
    check_agnostic_fallback,
    check_chain_of_thought,
    check_requires_citation,
    check_syllogism,
)
from axon.stdlib.anchors.definitions import (
    AgnosticFallback,
    ChainOfThoughtValidator,
    RequiresCitation,
    SyllogismChecker,
)


# ═══════════════════════════════════════════════════════════════════
#  SYLLOGISM CHECKER
# ═══════════════════════════════════════════════════════════════════


def test_syllogism_valid_basic():
    """Premise + Conclusion passes."""
    valid = "Premise: All men are mortal. Conclusion: Socrates is mortal."
    passed, violations = check_syllogism(valid)
    assert passed is True
    assert violations == []


def test_syllogism_missing_premise():
    """Conclusion without premise fails with specific message."""
    text = "Conclusion: Therefore it rains."
    passed, violations = check_syllogism(text)
    assert passed is False
    assert any("No 'Premise:' marker" in v for v in violations)


def test_syllogism_missing_conclusion():
    """Premise without conclusion fails."""
    text = "Premise: The sky is blue."
    passed, violations = check_syllogism(text)
    assert passed is False
    assert any("No 'Conclusion:' marker" in v for v in violations)


def test_syllogism_prose_logic_false_negative():
    """Valid prose logic without markers fails — documented behavior."""
    text = "Since all dogs bark, and Rex is a dog, Rex barks."
    passed, violations = check_syllogism(text)
    assert passed is False


def test_syllogism_multiple_premises():
    """Multiple labeled premises + single conclusion passes."""
    text = (
        "Premise 1: All mammals are warm-blooded.\n"
        "Premise 2: A whale is a mammal.\n"
        "Conclusion: A whale is warm-blooded."
    )
    passed, violations = check_syllogism(text)
    assert passed is True
    assert violations == []


def test_syllogism_major_minor_premises():
    """Major/Minor premise labels pass."""
    text = (
        "Major Premise: All humans are mortal.\n"
        "Minor Premise: Socrates is human.\n"
        "Conclusion: Socrates is mortal."
    )
    passed, violations = check_syllogism(text)
    assert passed is True


def test_syllogism_multiple_conclusions_fails():
    """Multiple Conclusion: markers fail."""
    text = (
        "Premise: A is B.\n"
        "Conclusion: Therefore B.\n"
        "Conclusion: Also C."
    )
    passed, violations = check_syllogism(text)
    assert passed is False
    assert any("exactly one conclusion" in v for v in violations)


# ═══════════════════════════════════════════════════════════════════
#  CHAIN OF THOUGHT VALIDATOR
# ═══════════════════════════════════════════════════════════════════


def test_cot_numbered_steps():
    """Numbered Step N pattern passes."""
    text = "Step 1: Calculate mass. Step 2: Apply gravity. Result: 9.8N."
    passed, violations = check_chain_of_thought(text)
    assert passed is True


def test_cot_ordinal_markers():
    """Ordinal markers (First, Secondly, Finally) pass."""
    text = "First, let's look at the data. Secondly, apply the formula. Finally, compare."
    passed, violations = check_chain_of_thought(text)
    assert passed is True


def test_cot_reasoning_openers():
    """Reasoning openers pass."""
    text = "Let's think about this problem carefully. The answer is 42."
    passed, violations = check_chain_of_thought(text)
    assert passed is True


def test_cot_direct_answer_fails():
    """Direct answer without any reasoning markers fails."""
    text = "The answer is 42."
    passed, violations = check_chain_of_thought(text)
    assert passed is False
    assert "intermediate reasoning" in violations[0]


def test_cot_step_regex_various_numbers():
    """Step with various numbers (Step 3, Step 10, etc.) passes."""
    text = "Step 3: Validate input. Step 10: Deploy."
    passed, violations = check_chain_of_thought(text)
    assert passed is True


# ═══════════════════════════════════════════════════════════════════
#  REQUIRES CITATION
# ═══════════════════════════════════════════════════════════════════


def test_citation_bracket():
    """Bracket notation [1] passes."""
    passed, _ = check_requires_citation("The earth is round [1].")
    assert passed is True


def test_citation_author_year():
    """Author-year notation (Smith, 2024) passes."""
    passed, _ = check_requires_citation("The sky is blue (Smith, 2024).")
    assert passed is True


def test_citation_url():
    """URL citation passes."""
    passed, _ = check_requires_citation("Based on https://example.com/data")
    assert passed is True


def test_citation_doi():
    """DOI reference passes."""
    passed, _ = check_requires_citation("See doi:10.1038/s41586-023-06600-9")
    assert passed is True


def test_citation_doi_case_insensitive():
    """DOI reference is case-insensitive."""
    passed, _ = check_requires_citation("See DOI:10.1000/xyz123")
    assert passed is True


def test_citation_missing_fails():
    """No citation of any kind fails."""
    passed, violations = check_requires_citation("The capital of France is Paris.")
    assert passed is False
    assert "HighConfidenceFact" in violations[0]


# ═══════════════════════════════════════════════════════════════════
#  AGNOSTIC FALLBACK
# ═══════════════════════════════════════════════════════════════════


def test_agnostic_honest_ignorance_passes():
    """Honest ignorance passes."""
    text = "I do not have sufficient data to answer this definitively."
    passed, violations = check_agnostic_fallback(text)
    assert passed is True


def test_agnostic_guessing_without_honesty_fails():
    """Guessing without admission of uncertainty fails."""
    text = "I'm guessing it might be around 5 million."
    passed, violations = check_agnostic_fallback(text)
    assert passed is False
    assert "unwarranted" in violations[0]


def test_agnostic_guessing_with_honesty_passes():
    """Guessing accompanied by explicit uncertainty admission passes."""
    text = "I am unsure, but my best guess based on similar data..."
    passed, violations = check_agnostic_fallback(text)
    assert passed is True


def test_agnostic_new_speculation_markers():
    """New speculation markers are detected."""
    text = "Let me speculate: the answer could be 42."
    passed, violations = check_agnostic_fallback(text)
    assert passed is False
    assert "let me speculate" in violations[0]


def test_agnostic_new_admission_markers():
    """New admission markers are recognized."""
    text = "I don't know the answer, but let me speculate a bit."
    passed, violations = check_agnostic_fallback(text)
    assert passed is True  # admission + speculation = pass


def test_agnostic_clean_response_passes():
    """Normal response without guessing or admissions passes."""
    text = "The capital of France is Paris."
    passed, violations = check_agnostic_fallback(text)
    assert passed is True


# ═══════════════════════════════════════════════════════════════════
#  ANCHOR INTERACTION & PRIORITY
# ═══════════════════════════════════════════════════════════════════


def test_anchor_interaction_agnostic_vs_citation():
    """AgnosticFallback passes on honest ignorance; RequiresCitation fails.

    This test documents the raw checker behavior. The priority logic
    in the Executor handles this by bypassing RequiresCitation when
    AgnosticFallback passes.
    """
    honest = "I do not know the answer and lack sufficient data."

    passed_agnostic, _ = check_agnostic_fallback(honest)
    assert passed_agnostic is True

    passed_cite, viols = check_requires_citation(honest)
    assert passed_cite is False
    assert len(viols) == 1


# ═══════════════════════════════════════════════════════════════════
#  SELF-HEALING INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class _MockSelfHealingClient:
    """Mock client to test Self-Healing with Logic Checkers."""

    def __init__(
        self,
        initial_response: str,
        corrected_response: str,
        expected_violation: str,
    ):
        self.initial_response = initial_response
        self.corrected_response = corrected_response
        self.expected_violation = expected_violation
        self.call_count = 0
        self.failure_contexts: list[str] = []

    async def call(self, *args, **kwargs):
        self.call_count += 1
        from axon.runtime.executor import ModelResponse

        failure_context = kwargs.get("failure_context")

        if self.call_count == 1:
            assert not failure_context
            return ModelResponse(
                raw=self.initial_response, content=self.initial_response
            )

        assert failure_context is not None
        self.failure_contexts.append(failure_context)
        assert self.expected_violation in failure_context

        return ModelResponse(
            raw=self.corrected_response, content=self.corrected_response
        )


def test_self_healing_logic_anchors():
    """Verify anchor failure injects context for the RetryEngine."""
    from axon.backends.base_backend import CompiledExecutionUnit, CompiledStep
    from axon.runtime.executor import Executor

    mock_client = _MockSelfHealingClient(
        initial_response="The sky is blue.",
        corrected_response=(
            "Premise: The physical scattering of light makes the sky blue. "
            "Conclusion: The sky is blue."
        ),
        expected_violation="No 'Premise:' marker",
    )

    executor = Executor(client=mock_client)  # type: ignore

    step = CompiledStep(
        step_name="logic_test",
        system_prompt="Test",
        user_prompt="Question",
        output_schema=None,
        tool_declarations=[],
        metadata={"refine": {"max_attempts": 3, "on_exhaustion": "skip"}},
    )
    unit = CompiledExecutionUnit(
        flow_name="test_unit",
        steps=[step],
        active_anchors=[
            {"name": "SyllogismChecker", "anchor_obj": SyllogismChecker}
        ],
    )

    from axon.runtime.tracer import Tracer
    import asyncio

    results = asyncio.run(executor._execute_unit(unit, tracer=Tracer()))

    assert mock_client.call_count == 2
    assert "No 'Premise:' marker" in mock_client.failure_contexts[0]

    final_output = results.step_results[0].response.raw
    assert "Premise:" in final_output
    assert "Conclusion:" in final_output
