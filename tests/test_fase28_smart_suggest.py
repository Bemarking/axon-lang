"""§Fase 28.e — Smart-suggest "Did you mean X?" tests (Python side).

Mirror of `mod fase28_smart_suggest_tests` in the Rust frontend.
Both stacks must produce byte-identical suggestion lists on the
same input — D7 ratified (cross-stack drift gate). Golden inputs
in `TestRustParityShape` are duplicated verbatim in the Rust pack.

Test classes:

  * TestLevenshtein     — pure edit-distance correctness
  * TestSuggest         — candidate ranking, distance threshold,
                          max-results cap, dedup, exact-match drop
  * TestHintFormat      — sentence formatting (1 / 2 / N matches)
  * TestSuggestFor      — end-to-end convenience
  * TestParserIntegration — the parser actually emits the hint
                            in unknown-keyword diagnostics
  * TestRustParityShape — golden inputs locked across stacks
"""
from __future__ import annotations

import pytest

from axon.compiler._smart_suggest import (
    MAX_DISTANCE,
    MAX_RESULTS,
    format_suggestion_hint,
    levenshtein,
    suggest,
    suggest_for,
)
from axon.compiler.errors import AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# ──────────────────────────────────────────────────────────────────────────
# TestLevenshtein
# ──────────────────────────────────────────────────────────────────────────


class TestLevenshtein:
    def test_identical_strings_distance_zero(self):
        assert levenshtein("flow", "flow") == 0

    def test_empty_left_returns_len_right(self):
        assert levenshtein("", "abc") == 3

    def test_empty_right_returns_len_left(self):
        assert levenshtein("abc", "") == 3

    def test_both_empty_distance_zero(self):
        assert levenshtein("", "") == 0

    def test_single_substitution(self):
        # `flwo` → `flow` is a single transposition (= 2 substitutions
        # in pure-Levenshtein space, NOT Damerau-Levenshtein). We use
        # plain Levenshtein for D7 cross-stack parity.
        assert levenshtein("flwo", "flow") == 2

    def test_single_deletion(self):
        assert levenshtein("flowx", "flow") == 1

    def test_single_insertion(self):
        assert levenshtein("flo", "flow") == 1

    def test_substitution(self):
        assert levenshtein("flop", "flow") == 1

    def test_unrelated_words(self):
        # "kitten" vs "sitting" — classic Wikipedia example, dist=3.
        assert levenshtein("kitten", "sitting") == 3

    def test_unicode_codepoints(self):
        # Treats codepoints as units (Python iter over str gives chars).
        # Rust mirror does the same via .chars().
        assert levenshtein("héllo", "hello") == 1

    def test_symmetry(self):
        # d(a, b) == d(b, a) for Levenshtein.
        assert levenshtein("flow", "fblo") == levenshtein("fblo", "flow")


# ──────────────────────────────────────────────────────────────────────────
# TestSuggest
# ──────────────────────────────────────────────────────────────────────────


class TestSuggest:
    def test_distance_one_returned(self):
        assert suggest("flo", ["flow", "type", "intent"]) == ["flow"]

    def test_distance_two_returned(self):
        # `flwo` → `flow` is dist=2 (2 substitutions). Threshold ≤ 2.
        assert suggest("flwo", ["flow", "type", "intent"]) == ["flow"]

    def test_distance_three_dropped(self):
        # "abcdef" vs "flow" is far above threshold.
        assert suggest("abcdef", ["flow", "type"]) == []

    def test_max_results_cap_at_three(self):
        # Five candidates all at distance 1; we keep 3.
        candidates = ["aaaa", "aaab", "aaac", "aaad", "aaae"]
        result = suggest("aaa", candidates)
        assert len(result) == MAX_RESULTS
        # Tied at distance 1 → alphabetical.
        assert result == ["aaaa", "aaab", "aaac"]

    def test_results_sorted_by_distance_then_alpha(self):
        # `flow` distance 0 (excluded — exact match), `flop` dist 1,
        # `floor` dist 2, `flux` dist 2.
        result = suggest("flow", ["flow", "flop", "floor", "flux"])
        # Exact "flow" is dropped; remaining sorted by (dist, name).
        assert result == ["flop", "floor", "flux"]

    def test_exact_match_dropped(self):
        # If the unknown literally matches a candidate, no suggestion.
        assert suggest("flow", ["flow"]) == []

    def test_dedup_input_candidates(self):
        # Iterable can yield the same candidate twice; we keep one.
        result = suggest("flo", ["flow", "flow", "flow"])
        assert result == ["flow"]

    def test_empty_unknown_returns_empty(self):
        assert suggest("", ["flow", "type"]) == []

    def test_empty_candidates_returns_empty(self):
        assert suggest("flow", []) == []

    def test_custom_max_distance(self):
        # Pinning custom threshold for adopters who want broader hints.
        assert suggest("flowwer", ["flower", "flow"], max_distance=3) == [
            "flower",
            "flow",
        ]

    def test_custom_max_results(self):
        candidates = ["a", "b", "c", "d", "e"]
        assert suggest("z", candidates, max_results=2) == ["a", "b"]


# ──────────────────────────────────────────────────────────────────────────
# TestHintFormat
# ──────────────────────────────────────────────────────────────────────────


class TestHintFormat:
    def test_empty_list_returns_empty_string(self):
        assert format_suggestion_hint([]) == ""

    def test_single_match(self):
        assert format_suggestion_hint(["flow"]) == "Did you mean `flow`?"

    def test_two_matches(self):
        assert (
            format_suggestion_hint(["flow", "flop"])
            == "Did you mean `flow` or `flop`?"
        )

    def test_three_matches_uses_oxford_or(self):
        assert (
            format_suggestion_hint(["flow", "flop", "flux"])
            == "Did you mean `flow`, `flop`, or `flux`?"
        )


# ──────────────────────────────────────────────────────────────────────────
# TestSuggestFor (convenience helper)
# ──────────────────────────────────────────────────────────────────────────


class TestSuggestFor:
    def test_end_to_end_single_match(self):
        assert (
            suggest_for("flo", ["flow", "type", "intent"])
            == "Did you mean `flow`?"
        )

    def test_end_to_end_no_match(self):
        assert suggest_for("xyz", ["flow", "type"]) == ""

    def test_end_to_end_three_matches(self):
        # `aaa` against five same-distance candidates → 3 returned.
        result = suggest_for("aaa", ["aaab", "aaac", "aaad", "aaae", "aaaf"])
        assert result == "Did you mean `aaab`, `aaac`, or `aaad`?"


# ──────────────────────────────────────────────────────────────────────────
# TestParserIntegration — actual error messages now carry the hint
# ──────────────────────────────────────────────────────────────────────────


class TestParserIntegration:
    """The parser must wire the hint into the diagnostic message at
    every unknown-keyword error site. Two key sites are covered:
    top-level declaration + flow-body step keyword.
    """

    def test_top_level_typo_suggests_flow(self):
        # `flwo` is dist=2 from `flow` — should suggest.
        src = "flwo F() { }"
        tokens = Lexer(src).tokenize()
        with pytest.raises(AxonParseError) as ei:
            Parser(tokens).parse()
        assert "Did you mean `flow`?" in str(ei.value)

    def test_top_level_unknown_far_no_suggestion(self):
        # `qwerty` is too far from any keyword; no suggestion appended.
        src = "qwerty F() { }"
        tokens = Lexer(src).tokenize()
        with pytest.raises(AxonParseError) as ei:
            Parser(tokens).parse()
        assert "Did you mean" not in str(ei.value)

    def test_flow_body_typo_suggests_step(self):
        # `stepp` is dist=1 from `step`.
        src = "flow F() { stepp S {} }"
        tokens = Lexer(src).tokenize()
        with pytest.raises(AxonParseError) as ei:
            Parser(tokens).parse()
        msg = str(ei.value)
        assert "Did you mean `step`" in msg

    def test_flow_body_typo_suggests_intent_keyword(self):
        # `reeson` (typo of `reason`) — dist=2 (delete `e` + insert `a`).
        # Actually let's pick one that's clearly within threshold.
        # `reasn` is dist=1 from `reason`.
        src = "flow F() { reasn R {} }"
        tokens = Lexer(src).tokenize()
        with pytest.raises(AxonParseError) as ei:
            Parser(tokens).parse()
        assert "Did you mean `reason`?" in str(ei.value)

    def test_recovery_mode_carries_hint(self):
        # The recovery-mode error list must also carry hints — the
        # adopter sees them on every recovered error, not only the
        # strict-mode first-error path.
        src = "flwo F() { }"
        tokens = Lexer(src).tokenize()
        result = Parser(tokens).parse_with_recovery()
        assert any("Did you mean `flow`?" in str(e) for e in result.errors)


# ──────────────────────────────────────────────────────────────────────────
# TestRustParityShape — golden inputs duplicated in the Rust pack
# ──────────────────────────────────────────────────────────────────────────


class TestRustParityShape:
    """Locked golden inputs. The Rust mirror at
    `mod fase28_smart_suggest_tests::golden_*` asserts the same
    output on the same input. Edits here must be mirrored Rust-side
    and vice versa (D7).
    """

    def test_golden_levenshtein_pairs(self):
        pairs = [
            ("flow", "flow", 0),
            ("flo", "flow", 1),
            ("flwo", "flow", 2),
            ("flox", "flow", 1),
            ("kitten", "sitting", 3),
            ("", "abc", 3),
            ("abc", "", 3),
            ("", "", 0),
        ]
        for a, b, expected in pairs:
            assert (
                levenshtein(a, b) == expected
            ), f"levenshtein({a!r}, {b!r}) != {expected}"

    def test_golden_suggest_top_level(self):
        # Subset of real top-level keywords.
        cands = ["flow", "intent", "type", "tool", "persona"]
        assert suggest("flwo", cands) == ["flow"]
        assert suggest("toll", cands) == ["tool"]
        assert suggest("intt", cands) == ["intent"]

    def test_golden_hint_three_match(self):
        assert (
            format_suggestion_hint(["a", "b", "c"])
            == "Did you mean `a`, `b`, or `c`?"
        )


def test_constants_documented():
    """Pin the public-API constants so D3 ratification is visible."""
    assert MAX_DISTANCE == 2
    assert MAX_RESULTS == 3
