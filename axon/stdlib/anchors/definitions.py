"""
AXON Standard Library — Anchor Definitions
============================================
All 12 built-in anchors from the AXON language.

Each anchor is an ``IRAnchor`` wrapped in ``StdlibAnchor``
with a checker function for runtime enforcement.

Core Anchors (spec §8.3)::

    NoHallucination  — Requires cited sources
    FactualOnly      — No opinions unless declared
    SafeOutput       — No harmful content
    PrivacyGuard     — No PII exposure
    NoBias           — Political/demographic neutrality
    ChildSafe        — Appropriate for minors
    NoCodeExecution  — Prevents runaway code
    AuditTrail       — Forces full reasoning trace

Logic & Epistemic Anchors (Phase 4)::

    SyllogismChecker         — Enforces Premise:/Conclusion: structure
    ChainOfThoughtValidator  — Requires step-by-step reasoning
    RequiresCitation         — Demands inline academic citations
    AgnosticFallback         — Enforces epistemic honesty over guessing
"""

from __future__ import annotations

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
    # Phase 4
    check_syllogism,
    check_chain_of_thought,
    check_requires_citation,
    check_agnostic_fallback,
)
from axon.stdlib.base import StdlibAnchor


# ═══════════════════════════════════════════════════════════════════
#  ANCHOR DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

NoHallucination = StdlibAnchor(
    ir=IRAnchor(
        name="NoHallucination",
        require="source_citation",
        reject=("speculation", "unverifiable_claim"),
        confidence_floor=0.80,
        unknown_response="I don't have sufficient information to make this determination.",
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_no_hallucination,
    description=(
        "Requires cited sources for all claims. Rejects speculation "
        "and unverifiable assertions."
    ),
    severity="error",
)

FactualOnly = StdlibAnchor(
    ir=IRAnchor(
        name="FactualOnly",
        require="factual_grounding",
        reject=("opinion", "speculation"),
        confidence_floor=0.85,
        unknown_response="Insufficient factual evidence to respond.",
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_factual_only,
    description=(
        "Restricts output to factual claims only. No opinions, "
        "unless explicitly declared as Opinion type."
    ),
    severity="error",
)

SafeOutput = StdlibAnchor(
    ir=IRAnchor(
        name="SafeOutput",
        reject=("harmful_content", "violence", "hate_speech"),
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_safe_output,
    description="Rejects harmful content, violence, and hate speech.",
    severity="error",
)

PrivacyGuard = StdlibAnchor(
    ir=IRAnchor(
        name="PrivacyGuard",
        reject=("pii", "personal_data", "ssn", "phone_number"),
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_privacy_guard,
    description=(
        "Prevents exposure of personally identifiable information "
        "(SSNs, credit cards, emails, phone numbers)."
    ),
    severity="error",
)

NoBias = StdlibAnchor(
    ir=IRAnchor(
        name="NoBias",
        reject=("political_bias", "demographic_bias", "gender_bias"),
        on_violation="warn",
    ),
    checker_fn=check_no_bias,
    description=(
        "Enforces political and demographic neutrality. "
        "Detects loaded language and explicit bias."
    ),
    severity="warning",
)

ChildSafe = StdlibAnchor(
    ir=IRAnchor(
        name="ChildSafe",
        reject=("adult_content", "violence", "profanity", "drugs"),
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_child_safe,
    description=(
        "Ensures all content is appropriate for minors. "
        "Rejects adult content, graphic violence, profanity, and drugs."
    ),
    severity="error",
)

NoCodeExecution = StdlibAnchor(
    ir=IRAnchor(
        name="NoCodeExecution",
        reject=("code_execution", "system_command", "file_write"),
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_no_code_execution,
    description=(
        "Prevents the model from executing code, running system "
        "commands, or performing file operations."
    ),
    severity="error",
)

AuditTrail = StdlibAnchor(
    ir=IRAnchor(
        name="AuditTrail",
        require="human_review",
        on_violation="warn",
    ),
    checker_fn=check_audit_trail,
    description=(
        "Forces full reasoning trace in output. Requires visible "
        "reasoning steps for audit and review purposes."
    ),
    severity="warning",
)


# ═══════════════════════════════════════════════════════════════════
#  LOGIC & EPISTEMIC ANCHORS (PHASE 4)
# ═══════════════════════════════════════════════════════════════════

SyllogismChecker = StdlibAnchor(
    ir=IRAnchor(
        name="SyllogismChecker",
        require="logical_structure",
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_syllogism,
    description=(
        "Syntactically enforces a standard logical format using 'Premise:' "
        "and 'Conclusion:' identifiers. Useful for structured parsing."
    ),
    severity="error",
)

ChainOfThoughtValidator = StdlibAnchor(
    ir=IRAnchor(
        name="ChainOfThoughtValidator",
        require="step_by_step",
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_chain_of_thought,
    description=(
        "Forces the model to explicitly write out step sequences "
        "before producing a final answer, aiding reasoning quality."
    ),
    severity="error",
)

RequiresCitation = StdlibAnchor(
    ir=IRAnchor(
        name="RequiresCitation",
        require="inline_citation",
        reject=("unverifiable_claim",),
        confidence_floor=0.90,
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_requires_citation,
    description=(
        "Strict verification enforcing explicit academic-style inline citations "
        "or external URLs for factual claims."
    ),
    severity="error",
)

AgnosticFallback = StdlibAnchor(
    ir=IRAnchor(
        name="AgnosticFallback",
        require="epistemic_honesty",
        reject=("unwarranted_speculation",),
        on_violation="raise",
        on_violation_target="AnchorBreachError",
    ),
    checker_fn=check_agnostic_fallback,
    description=(
        "Requires the model to explicitly state a lack of information instead "
        "of speculating or guessing when sufficient data is unavailable."
    ),
    severity="error",
)

# ── Canonical list for registration ──────────────────────────────

ALL_ANCHORS: tuple[StdlibAnchor, ...] = (
    NoHallucination,
    FactualOnly,
    SafeOutput,
    PrivacyGuard,
    NoBias,
    ChildSafe,
    NoCodeExecution,
    AuditTrail,
    # Phase 4
    SyllogismChecker,
    ChainOfThoughtValidator,
    RequiresCitation,
    AgnosticFallback,
)
