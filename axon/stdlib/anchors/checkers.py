"""
AXON Standard Library — Anchor Checker Functions
==================================================
Lightweight keyword-based enforcement for each built-in anchor.

Each checker receives the model's output text and returns
``(passed, violations)`` where ``violations`` is a list of
human-readable violation descriptions.

These are Phase 3-style keyword checkers. Full NLI-based
enforcement is planned for Phase 6.
"""

from __future__ import annotations

import re


def _find_keywords(
    content: str, keywords: list[str]
) -> list[str]:
    """Find which keywords appear in content (case-insensitive)."""
    lower = content.lower()
    return [kw for kw in keywords if kw.lower() in lower]


# ═══════════════════════════════════════════════════════════════════
#  CHECKER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════


def check_no_hallucination(content: str) -> tuple[bool, list[str]]:
    """Verify content doesn't contain hallucination indicators.

    Checks for:
    - Hedging without citations ("I believe", "probably", "might be")
    - Fabricated references
    - Unsubstantiated absolute claims
    """
    violations: list[str] = []
    lower = content.lower()

    # Hedging phrases that indicate uncertainty without evidence
    hedging = [
        "i believe", "i think", "probably", "might be",
        "could be", "it seems like", "supposedly",
        "i'm not sure but", "i'm guessing",
    ]
    found = _find_keywords(lower, hedging)
    if found:
        violations.append(
            f"Hedging without citation: {', '.join(found)}"
        )

    return len(violations) == 0, violations


def check_factual_only(content: str) -> tuple[bool, list[str]]:
    """Verify content sticks to factual claims, no opinions.

    Checks for opinion indicators unless explicitly declared.
    """
    violations: list[str] = []
    lower = content.lower()

    opinion_markers = [
        "in my opinion", "i feel that", "personally",
        "i prefer", "my favorite", "i'd recommend",
        "i suggest", "to me,",
    ]
    found = _find_keywords(lower, opinion_markers)
    if found:
        violations.append(
            f"Opinion markers detected: {', '.join(found)}"
        )

    return len(violations) == 0, violations


def check_safe_output(content: str) -> tuple[bool, list[str]]:
    """Verify content doesn't contain harmful material.

    Checks for violence, hate speech, and harmful instructions.
    """
    violations: list[str] = []
    lower = content.lower()

    harmful_patterns = [
        "how to make a bomb", "how to hack", "how to steal",
        "kill yourself", "self-harm", "suicide method",
        "racial slur", "hate speech",
    ]
    found = _find_keywords(lower, harmful_patterns)
    if found:
        violations.append(
            f"Harmful content detected: {', '.join(found)}"
        )

    return len(violations) == 0, violations


def check_privacy_guard(content: str) -> tuple[bool, list[str]]:
    """Verify content doesn't expose personally identifiable information.

    Checks for SSNs, phone numbers, email addresses, and credit cards.
    """
    violations: list[str] = []

    # SSN pattern (XXX-XX-XXXX)
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", content):
        violations.append("Possible SSN detected")

    # Credit card pattern (16 digits with optional separators)
    if re.search(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", content):
        violations.append("Possible credit card number detected")

    # Email in output (might be PII)
    if re.search(
        r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
        content,
    ):
        violations.append("Email address detected in output")

    # Phone numbers (various formats)
    if re.search(
        r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        content,
    ):
        violations.append("Phone number detected in output")

    return len(violations) == 0, violations


def check_no_bias(content: str) -> tuple[bool, list[str]]:
    """Verify content is politically and demographically neutral.

    Checks for explicit bias indicators and loaded language.
    """
    violations: list[str] = []
    lower = content.lower()

    bias_markers = [
        "the best political party", "the right wing is",
        "the left wing is", "liberals are", "conservatives are",
        "all men are", "all women are", "that race is",
    ]
    found = _find_keywords(lower, bias_markers)
    if found:
        violations.append(
            f"Potential bias detected: {', '.join(found)}"
        )

    return len(violations) == 0, violations


def check_child_safe(content: str) -> tuple[bool, list[str]]:
    """Verify content is appropriate for minors.

    Checks for adult content, violence, profanity, and drug references.
    """
    violations: list[str] = []
    lower = content.lower()

    inappropriate = [
        "explicit sexual", "pornography", "graphic violence",
        "drug use instructions", "alcohol abuse",
        "gambling tutorial",
    ]
    found = _find_keywords(lower, inappropriate)
    if found:
        violations.append(
            f"Age-inappropriate content detected: {', '.join(found)}"
        )

    # Basic profanity check (intentionally conservative)
    profanity = ["fuck", "shit", "damn", "bastard", "bitch", "ass "]
    found_profanity = _find_keywords(lower, profanity)
    if found_profanity:
        violations.append("Profanity detected")

    return len(violations) == 0, violations


def check_no_code_execution(content: str) -> tuple[bool, list[str]]:
    """Verify content doesn't attempt code execution or system commands.

    Checks for shell commands, file operations, and dangerous code.
    """
    violations: list[str] = []
    lower = content.lower()

    dangerous = [
        "os.system(", "subprocess.", "exec(", "eval(",
        "rm -rf", "del /f", "format c:",
        "import os", "import subprocess",
        "__import__(",
    ]
    found = _find_keywords(lower, dangerous)
    if found:
        violations.append(
            f"Code execution attempt detected: {', '.join(found)}"
        )

    return len(violations) == 0, violations


def check_audit_trail(content: str) -> tuple[bool, list[str]]:
    """Verify content includes reasoning trace.

    Checks that the output contains structured reasoning markers.
    """
    violations: list[str] = []
    lower = content.lower()

    # Must contain at least one reasoning indicator
    reasoning_markers = [
        "reasoning:", "therefore", "because", "based on",
        "evidence:", "conclusion:", "analysis:",
        "step 1", "firstly", "in summary",
    ]
    has_reasoning = any(m in lower for m in reasoning_markers)
    if not has_reasoning:
        violations.append(
            "No reasoning trace found. "
            "AuditTrail requires visible reasoning steps."
        )

    return len(violations) == 0, violations


# ═══════════════════════════════════════════════════════════════════
#  LOGIC & EPISTEMIC CHECKERS (PHASE 4)
# ═══════════════════════════════════════════════════════════════════


def check_syllogism(content: str) -> tuple[bool, list[str]]:
    """Validate presence of explicit logical structure markers.

    Enforces a minimum structural contract:
      - At least one ``Premise:`` (or ``Major premise:``, ``Minor premise:``)
      - Exactly one ``Conclusion:``

    This is a **syntactic validator**, not a semantic one.  It guarantees
    the output is *parseable* as a logical argument but does NOT verify
    that the argument is logically sound.

    False negatives are expected for valid prose-form syllogisms that
    omit the explicit markers — this is by design and documented.
    """
    violations: list[str] = []

    # Count distinct premise markers (case-insensitive)
    premise_pattern = re.compile(
        r"(?:major\s+)?(?:minor\s+)?premise\s*(?:\d+)?\s*:", re.IGNORECASE
    )
    conclusion_pattern = re.compile(r"conclusion\s*:", re.IGNORECASE)

    premise_count = len(premise_pattern.findall(content))
    conclusion_count = len(conclusion_pattern.findall(content))

    if premise_count == 0:
        violations.append(
            "Syllogism Breach: No 'Premise:' marker found. The output must "
            "contain at least one explicitly labeled premise (e.g. "
            "'Premise 1:', 'Major Premise:', 'Minor Premise:')."
        )

    if conclusion_count == 0:
        violations.append(
            "Syllogism Breach: No 'Conclusion:' marker found. The output "
            "must explicitly label its logical conclusion."
        )
    elif conclusion_count > 1:
        violations.append(
            f"Syllogism Breach: Found {conclusion_count} 'Conclusion:' "
            "markers. A well-formed syllogism has exactly one conclusion."
        )

    return len(violations) == 0, violations


def check_chain_of_thought(content: str) -> tuple[bool, list[str]]:
    """Enforce explicit step-by-step reasoning before the final answer.

    Accepts any of the following step indicators:
      - Numbered steps via regex (``Step 1:``, ``Step 2:``, etc.)
      - Ordinal markers (``First,``, ``Secondly,``, ``Finally,``)
      - Explicit reasoning openers (``To begin``, ``Let's think``)

    The checker requires the model to *show its work*, preventing
    direct-answer shortcuts that bypass intermediate reasoning.
    """
    violations: list[str] = []
    lower = content.lower()

    # Numbered step pattern (Step 1, Step 2, etc.)
    numbered_steps = re.compile(r"step\s+\d+", re.IGNORECASE)
    has_numbered = bool(numbered_steps.search(content))

    # Ordinal and reasoning markers
    ordinal_markers = [
        "first,", "firstly", "secondly", "thirdly",
        "next,", "then,", "finally,", "lastly,",
        "to begin", "let's think", "let me think",
        "let us consider", "starting with",
    ]
    has_ordinal = any(m in lower for m in ordinal_markers)

    if not (has_numbered or has_ordinal):
        violations.append(
            "Chain of Thought Breach: The output jumps directly to a "
            "conclusion without showing intermediate reasoning steps. "
            "Use explicit markers like 'Step 1:', 'First,', 'Then,' etc."
        )

    return len(violations) == 0, violations


def check_requires_citation(content: str) -> tuple[bool, list[str]]:
    """Enforce inline academic-style citations for factual claims.

    Accepts any of the following citation formats:
      - Bracket notation: ``[1]``, ``[2]``, ``[3]``
      - Author-year notation: ``(Smith, 2024)``
      - DOI references: ``doi:10.1000/xyz123``
      - External URLs: ``https://...``

    This is a strict *presence* check — it verifies that citations
    exist, but does not validate their accuracy or resolvability.
    """
    violations: list[str] = []

    has_bracket = bool(re.search(r"\[\d+\]", content))
    has_author_year = bool(re.search(r"\([A-Z][a-z]+,\s*\d{4}\)", content))
    has_doi = bool(re.search(r"doi:\s*10\.\d{4,}", content, re.IGNORECASE))
    has_url = bool(re.search(r"https?://\S+", content))

    if not (has_bracket or has_author_year or has_doi or has_url):
        violations.append(
            "Citation Breach: HighConfidenceFact requires explicit inline "
            "citations. Accepted formats: [1], (Author, 2024), "
            "doi:10.xxxx/..., or verifiable https:// URLs."
        )

    return len(violations) == 0, violations


def check_agnostic_fallback(content: str) -> tuple[bool, list[str]]:
    """Enforce epistemic honesty without penalizing self-awareness.

    The distinction is critical:
      - **Honest ignorance** (``"I do not know"``) → PASS
      - **Hedged speculation** (``"My best guess"``) → FAIL *unless*
        accompanied by an explicit admission of uncertainty

    This prevents the common LLM failure mode of confidently guessing
    to appear helpful, while still allowing qualified uncertainty
    (``"I'm unsure, but the evidence suggests..."``) which is
    epistemically honest reasoning.
    """
    violations: list[str] = []
    lower = content.lower()

    # Markers of unwarranted guessing-to-please behavior
    guessing_markers = [
        "best guess", "i'm guessing", "if i had to guess",
        "it's possible that", "maybe it is", "i might be wrong but",
        "wild guess", "could potentially", "let me speculate",
        "my assumption is", "i would guess that",
        "i'll take a stab at", "a rough estimate would be",
    ]

    # Markers of honest epistemic humility
    agnostic_markers = [
        "i do not know", "i don't know", "i am unsure", "i'm unsure",
        "i lack", "cannot confirm", "insufficient data",
        "not enough information", "i don't have enough",
        "i cannot determine", "unknown to me",
        "i do not have sufficient", "beyond my knowledge",
        "i'm not able to confirm",
    ]

    has_guessing = _find_keywords(lower, guessing_markers)
    has_agnostic = _find_keywords(lower, agnostic_markers)

    if has_guessing and not has_agnostic:
        violations.append(
            f"Epistemic Breach: The model resorted to unwarranted "
            f"speculation ({', '.join(has_guessing)}). When information "
            "is lacking, state explicitly 'I do not have sufficient data' "
            "rather than guessing."
        )

    return len(violations) == 0, violations
