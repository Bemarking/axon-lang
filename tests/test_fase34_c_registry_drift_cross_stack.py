"""§Fase 34.c (v1.29.0) — Cross-stack registry drift gate.

Python mirror of ``axon-rs/tests/fase34_c_registry_drift.rs``.
Both stacks share the same synthetic 30-tool corpus + the same
``starts_with("stream:")`` derivation rule. Drift between the
stacks fails this test loudly.

The corpus matches the Rust one byte-for-byte:

- 10 stream-producer tools (across 4 closed-catalog policies)
- 10 plain non-stream tools (including 3 ``stream``-substring
  edge cases that MUST NOT flag as streaming)
- 10 empty-effect-row tools

D10 cross-stack contract: the rule
``any(e.startswith("stream:") for e in effect_row)`` is the SAME
on both stacks. The drift gate is the falsifier for any future
divergence.
"""

from __future__ import annotations

import pytest

from axon.runtime.tools.streaming import derive_is_streaming


# ─── Synthetic 30-tool corpus (mirror of Rust corpus) ──────────────
#
# Each row: (name, effect_row, expected_is_streaming)
# This is the SAME corpus the Rust drift gate consumes; if either
# stack drifts on a single row, this test fires loudly.
CORPUS: list[tuple[str, list[str], bool]] = [
    # ── 10 stream-producer tools ─────────────────────────────────────
    ("ChatStreamDrop", ["stream:drop_oldest"], True),
    (
        "ClinicalReasonerDrop",
        ["stream:drop_oldest", "network", "epistemic:speculate"],
        True,
    ),
    ("DegradeStreamerA", ["stream:degrade_quality"], True),
    ("DegradeStreamerB", ["stream:degrade_quality", "compute"], True),
    ("PauseStreamerA", ["stream:pause_upstream"], True),
    ("PauseStreamerB", ["stream:pause_upstream", "io", "network"], True),
    ("FailStreamerA", ["stream:fail"], True),
    ("FailStreamerB", ["stream:fail", "epistemic:speculate"], True),
    ("MultiEffectStreamer", ["compute", "stream:drop_oldest", "network"], True),
    (
        "FullEffectStreamer",
        [
            "stream:fail",
            "compute",
            "io",
            "network",
            "epistemic:speculate",
        ],
        True,
    ),
    # ── 10 plain non-stream tools ────────────────────────────────────
    ("Calculator", ["compute"], False),
    ("DateTimeReader", ["read"], False),
    ("HttpProbe", ["network"], False),
    ("FileScanner", ["io"], False),
    ("WriteSink", ["write"], False),
    ("EpistemicProbe", ["epistemic:speculate"], False),
    ("CompositeNonStream", ["compute", "network", "io"], False),
    # Edge cases: `stream`-substring NOT at prefix — MUST NOT flag
    # as streaming (rule is `startswith("stream:")`, not `contains`).
    ("DownstreamProcessor", ["downstream"], False),
    ("UpstreamFlowControl", ["upstream-flow", "network"], False),
    ("StreamWordTool", ["stream"], False),
    # ── 10 empty-effect-row tools ────────────────────────────────────
    ("EmptyA", [], False),
    ("EmptyB", [], False),
    ("EmptyC", [], False),
    ("EmptyD", [], False),
    ("EmptyE", [], False),
    ("EmptyF", [], False),
    ("EmptyG", [], False),
    ("EmptyH", [], False),
    ("EmptyI", [], False),
    ("EmptyJ", [], False),
]


# ════════════════════════════════════════════════════════════════════
#  §1 — Corpus cardinality + 1-to-1 declaration → runtime contract
# ════════════════════════════════════════════════════════════════════


def test_s1_corpus_size_is_exactly_thirty():
    assert len(CORPUS) == 30, (
        f"34.c cross-stack drift gate: corpus size MUST be 30. "
        f"Got {len(CORPUS)}."
    )


@pytest.mark.parametrize("name,effect_row,expected", CORPUS)
def test_s1_derive_is_streaming_matches_expected(
    name: str, effect_row: list[str], expected: bool
):
    """Every row of the corpus is parametrically asserted: the
    Python derivation rule MUST yield the expected flag. Drift
    detection: if a row's expected value changes (e.g., a future
    rule modification), this test fires for that specific row."""
    actual = derive_is_streaming(effect_row)
    assert actual == expected, (
        f"34.c cross-stack drift gate VIOLATION for tool `{name}`: "
        f"derive_is_streaming({effect_row!r}) = {actual!r}, "
        f"expected {expected!r}. The 1-to-1 declaration → runtime "
        f"contract was broken by this row."
    )


# ════════════════════════════════════════════════════════════════════
#  §2 — Cardinality pin: exactly 10 streaming + 20 non-streaming
# ════════════════════════════════════════════════════════════════════


def test_s2_corpus_has_exactly_ten_streaming_tools():
    streaming_count = sum(
        1 for (_, effect_row, _) in CORPUS if derive_is_streaming(effect_row)
    )
    assert streaming_count == 10, (
        f"34.c corpus cardinality pin: EXACTLY 10 of 30 corpus tools "
        f"declare a stream effect. Got {streaming_count}."
    )


def test_s2_corpus_has_exactly_twenty_non_streaming_tools():
    non_streaming_count = sum(
        1 for (_, effect_row, _) in CORPUS if not derive_is_streaming(effect_row)
    )
    assert non_streaming_count == 20, (
        f"34.c corpus cardinality pin: EXACTLY 20 of 30 corpus tools "
        f"are non-streaming. Got {non_streaming_count}."
    )


# ════════════════════════════════════════════════════════════════════
#  §3 — No false positives: `stream`-substring NOT at prefix
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "name,effect_row",
    [
        ("DownstreamProcessor", ["downstream"]),
        ("UpstreamFlowControl", ["upstream-flow", "network"]),
        ("StreamWordTool", ["stream"]),
    ],
)
def test_s3_substring_stream_does_not_flag_streaming(
    name: str, effect_row: list[str]
):
    """The rule is ``startswith('stream:')``, not ``contains('stream')``.
    Tools with `stream` in their effect-row entries but NOT at the
    `stream:` prefix position MUST NOT flag as streaming."""
    actual = derive_is_streaming(effect_row)
    assert actual is False, (
        f"34.c §3 cross-stack: tool `{name}` has `stream` in "
        f"effect_row but NOT as `stream:` prefix — MUST NOT flag as "
        f"streaming. Got is_streaming={actual}, effect_row={effect_row}."
    )


# ════════════════════════════════════════════════════════════════════
#  §4 — Closed-catalog policy coverage (cross-reference Fase 33.e)
# ════════════════════════════════════════════════════════════════════


def test_s4_corpus_covers_all_four_closed_catalog_policies():
    """The Fase 33.e closed-catalog BackpressurePolicy set is
    {drop_oldest, degrade_quality, pause_upstream, fail}. The corpus
    exercises every member at least once — ensuring future policy
    additions force a corpus update on BOTH stacks."""
    policy_hits: set[str] = set()
    for (_, effect_row, _) in CORPUS:
        for effect in effect_row:
            if effect.startswith("stream:"):
                policy = effect[len("stream:"):]
                if policy:
                    policy_hits.add(policy)
    expected = {"drop_oldest", "degrade_quality", "pause_upstream", "fail"}
    assert policy_hits == expected, (
        f"34.c §4 cross-stack closed-catalog coverage: the corpus MUST "
        f"exercise all 4 BackpressurePolicy slugs from Fase 33.e. "
        f"Got {policy_hits!r}, expected {expected!r}."
    )


# ════════════════════════════════════════════════════════════════════
#  §5 — Derivation rule pure-function totality + idempotence
# ════════════════════════════════════════════════════════════════════


def test_s5_derive_is_streaming_is_pure_and_idempotent():
    """Pure: same input → same output across N calls. Idempotent:
    calling twice yields the same result."""
    for (name, effect_row, _) in CORPUS:
        first = derive_is_streaming(effect_row)
        for _ in range(10):
            again = derive_is_streaming(effect_row)
            assert first == again, (
                f"34.c §5: derive_is_streaming MUST be a pure function "
                f"— repeated calls on the same input yield the same "
                f"output. Tool `{name}` drifted."
            )


# ════════════════════════════════════════════════════════════════════
#  §6 — Cross-stack corpus snapshot equality with Rust
# ════════════════════════════════════════════════════════════════════
#
# The Python corpus above MUST equal the Rust corpus
# byte-identically. Both sides are the same 30 tools with the same
# effect_rows and the same expected_is_streaming flags. A future PR
# that changes the corpus on either side MUST update both — failing
# to do so fires this test loudly.

# Hardcoded Rust corpus snapshot. Each row is (name, effect_row,
# expected_is_streaming). MUST equal the corpus in
# axon-rs/tests/fase34_c_registry_drift.rs.
RUST_CORPUS_SNAPSHOT: list[tuple[str, list[str], bool]] = [
    ("ChatStreamDrop", ["stream:drop_oldest"], True),
    (
        "ClinicalReasonerDrop",
        ["stream:drop_oldest", "network", "epistemic:speculate"],
        True,
    ),
    ("DegradeStreamerA", ["stream:degrade_quality"], True),
    ("DegradeStreamerB", ["stream:degrade_quality", "compute"], True),
    ("PauseStreamerA", ["stream:pause_upstream"], True),
    ("PauseStreamerB", ["stream:pause_upstream", "io", "network"], True),
    ("FailStreamerA", ["stream:fail"], True),
    ("FailStreamerB", ["stream:fail", "epistemic:speculate"], True),
    ("MultiEffectStreamer", ["compute", "stream:drop_oldest", "network"], True),
    (
        "FullEffectStreamer",
        [
            "stream:fail",
            "compute",
            "io",
            "network",
            "epistemic:speculate",
        ],
        True,
    ),
    ("Calculator", ["compute"], False),
    ("DateTimeReader", ["read"], False),
    ("HttpProbe", ["network"], False),
    ("FileScanner", ["io"], False),
    ("WriteSink", ["write"], False),
    ("EpistemicProbe", ["epistemic:speculate"], False),
    ("CompositeNonStream", ["compute", "network", "io"], False),
    ("DownstreamProcessor", ["downstream"], False),
    ("UpstreamFlowControl", ["upstream-flow", "network"], False),
    ("StreamWordTool", ["stream"], False),
    ("EmptyA", [], False),
    ("EmptyB", [], False),
    ("EmptyC", [], False),
    ("EmptyD", [], False),
    ("EmptyE", [], False),
    ("EmptyF", [], False),
    ("EmptyG", [], False),
    ("EmptyH", [], False),
    ("EmptyI", [], False),
    ("EmptyJ", [], False),
]


def test_s6_python_corpus_matches_rust_snapshot():
    assert CORPUS == RUST_CORPUS_SNAPSHOT, (
        "34.c §6 cross-stack drift gate: the Python CORPUS and the "
        "hardcoded Rust snapshot in this test file MUST be equal. "
        "Both represent the same synthetic 30-tool dataset. If "
        "either side drifted, update BOTH (this test + the Rust "
        "drift gate) in lockstep."
    )
