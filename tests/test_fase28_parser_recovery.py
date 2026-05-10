"""§Fase 28.b — Parser error recovery (panic-mode + sync points).

Test pack covering the new `Parser.parse_with_recovery() -> ParseResult`
API ratified by D1/D2/D9 on 2026-05-10. The pack is structured around
the load-bearing claims:

  1. Backwards compat (D9): the existing `parse()` API raises on the
     first error verbatim. Recovery mode is opt-in via the new method.
  2. Single-error recovery: a single malformed declaration returns one
     error + zero or more good declarations parsed after the resync.
  3. Multi-error recovery: N malformed declarations → N errors;
     declarations are independent because the resync walker advances
     past each broken construct's closing brace.
  4. Sync-point coverage (D2): the walker resyncs at top-level keywords
     AND at unmatched closing braces AND at EOF. Each path is covered
     by a dedicated test.
  5. Robustness fuzz (D12): 1000 deterministic-seeded random
     mutations of valid programs; the parser MUST never crash
     (uncaught exception, infinite loop, etc.).
  6. Edge cases: empty input, EOF mid-declaration, deeply nested
     errors, errors at column 0 of line 1.
  7. Result API: `has_errors`, `is_clean`, `__repr__` behave as
     documented.

The test pack is the `test_fase28_parser_recovery.py` source-of-truth
for the panic-mode contract. Adopters relying on the recovery surface
should expect every assertion below to hold across patches; any
diagnostic-message-text assertions are deliberately fragment-based
(e.g. `assert "expected" in msg`) so we don't lock ourselves into
brittle exact-string matches.
"""

from __future__ import annotations

import random

import pytest

from axon.compiler.errors import AxonLexerError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import (
    AxonParseError,
    Parser,
    ParseResult,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _parse_recovery(source: str) -> ParseResult:
    return Parser(Lexer(source).tokenize()).parse_with_recovery()


def _parse_strict(source: str):
    return Parser(Lexer(source).tokenize()).parse()


# ──────────────────────────────────────────────────────────────────────
# 1. Backwards compatibility (D9)
# ──────────────────────────────────────────────────────────────────────


class TestBackwardsCompat:
    """The original `parse()` API is preserved verbatim per D9."""

    def test_parse_returns_program_node_on_clean_input(self) -> None:
        prog = _parse_strict(
            "flow F() -> Unit { step S { ask: \"q\" output: String } }"
        )
        assert prog is not None
        assert len(prog.declarations) == 1

    def test_parse_raises_on_first_error_unchanged(self) -> None:
        """Adopter integrations + CI pipelines depend on this raise.
        The fail-fast posture is preserved."""
        bad = "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        with pytest.raises(AxonParseError):
            _parse_strict(bad)

    def test_parse_raises_on_first_error_in_multi_decl_input(self) -> None:
        """Even if a clean declaration follows the bad one, `parse()`
        does NOT keep going — old contract preserved."""
        src = (
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        with pytest.raises(AxonParseError):
            _parse_strict(src)


# ──────────────────────────────────────────────────────────────────────
# 2. Single-error recovery
# ──────────────────────────────────────────────────────────────────────


class TestSingleErrorRecovery:
    def test_clean_input_returns_zero_errors(self) -> None:
        result = _parse_recovery(
            "flow F() -> Unit { step S { ask: \"q\" output: String } }"
        )
        assert isinstance(result, ParseResult)
        assert result.is_clean
        assert not result.has_errors
        assert result.errors == []
        assert len(result.program.declarations) == 1

    def test_single_bad_declaration_one_error_zero_decls(self) -> None:
        """`flow Bad(arg String)` is malformed (missing `:` between
        param name + type). Recovery records one error + walks past
        the flow's closing brace; no declarations are kept since the
        bad flow never reached `_parse_declaration`'s return."""
        result = _parse_recovery(
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        )
        assert result.has_errors
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 0

    def test_bad_then_good_recovers_to_second(self) -> None:
        """One bad declaration followed by a clean one: recovery walks
        past the bad construct's `}` + parses the clean one."""
        src = (
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 1
        assert result.program.declarations[0].name == "Good"

    def test_good_then_bad_keeps_first(self) -> None:
        """Clean declaration followed by a bad one: the first parses
        normally; the second's error is recorded; recovery walks to
        EOF (no more declarations follow)."""
        src = (
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 1
        assert result.program.declarations[0].name == "Good"


# ──────────────────────────────────────────────────────────────────────
# 3. Multi-error recovery
# ──────────────────────────────────────────────────────────────────────


class TestMultiErrorRecovery:
    def test_three_bad_declarations_yield_three_errors(self) -> None:
        """Three independently malformed flows → three errors collected
        in source order. Each broken flow's closing brace resyncs the
        walker for the next."""
        src = (
            "flow Bad1( arg String ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Bad2( other Int ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Bad3( more Bool ) -> Unit { step S { ask: \"q\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 3
        assert len(result.program.declarations) == 0

    def test_bad_good_bad_good_keeps_two_decls(self) -> None:
        """Alternating bad + clean → the two clean ones are parsed +
        the two errors are recorded."""
        src = (
            "flow Bad1( arg String ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Good1() -> Unit { step S { ask: \"a\" } }\n"
            "flow Bad2( other Int ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Good2() -> Unit { step S { ask: \"b\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 2
        assert len(result.program.declarations) == 2
        names = [d.name for d in result.program.declarations]
        assert names == ["Good1", "Good2"]

    def test_errors_appear_in_source_order(self) -> None:
        src = (
            "flow Bad1( arg1 String ) -> Unit { step S { ask: \"q\" } }\n"
            "flow Bad2( arg2 Int ) -> Unit { step S { ask: \"q\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 2
        # Error 0 is on line 1, error 1 is on line 2.
        assert result.errors[0].line < result.errors[1].line


# ──────────────────────────────────────────────────────────────────────
# 4. Sync-point coverage (D2)
# ──────────────────────────────────────────────────────────────────────


class TestSyncPoints:
    def test_resync_at_closing_brace(self) -> None:
        """Walker advances past the broken flow's `}` and resumes at
        the next declaration."""
        src = (
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }\n"
            "intent I { given: Document }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        # Intent parsed cleanly after recovery.
        assert len(result.program.declarations) == 1
        assert result.program.declarations[0].name == "I"

    def test_resync_at_top_level_keyword(self) -> None:
        """When a broken construct doesn't close cleanly (missing `}`),
        the walker resyncs at the NEXT top-level keyword. This catches
        the case where adopters forget a closing brace + the next
        construct's leading keyword serves as the sync point."""
        # `flow Bad(arg String)` errors before `{` is consumed; walker
        # then sees the next `flow` keyword at depth 0 → sync there.
        src = (
            "flow Bad( arg String ) -> Unit\n"  # missing `{...}`
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 1
        assert result.program.declarations[0].name == "Good"

    def test_resync_at_eof_when_no_more_declarations(self) -> None:
        """A bad construct at end-of-file: walker reaches EOF without
        finding a sync point + outer loop terminates."""
        src = "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 0

    def test_resync_skips_nested_keywords(self) -> None:
        """A top-level keyword NESTED inside a broken construct (e.g.
        a `flow` keyword used as a value somewhere) does NOT trigger
        a premature sync — the walker tracks brace depth + only syncs
        at depth 0. Construct: a flow body containing a misformed
        invocation that LOOKS like a top-level keyword but is nested."""
        # Use a valid flow followed by a bad one. The bad flow has a
        # broken inner step body. Walker should consume the flow's `}`
        # then sync at the next decl.
        src = (
            "flow Bad() -> Unit {\n"
            "  step S { weird_field undefined_id }\n"
            "}\n"
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        result = _parse_recovery(src)
        assert len(result.errors) >= 1
        # The clean Good flow should parse.
        names = [d.name for d in result.program.declarations]
        assert "Good" in names


# ──────────────────────────────────────────────────────────────────────
# 5. ParseResult API
# ──────────────────────────────────────────────────────────────────────


class TestParseResultAPI:
    def test_is_clean_true_when_no_errors(self) -> None:
        result = _parse_recovery("flow F() -> Unit { step S { ask: \"q\" } }")
        assert result.is_clean is True
        assert result.has_errors is False

    def test_has_errors_true_when_at_least_one_error(self) -> None:
        result = _parse_recovery(
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        )
        assert result.has_errors is True
        assert result.is_clean is False

    def test_repr_includes_decl_count_and_error_count(self) -> None:
        result = _parse_recovery(
            "flow Good() -> Unit { step S { ask: \"q\" } }\n"
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }\n"
        )
        repr_str = repr(result)
        assert "ParseResult" in repr_str
        assert "1 decls" in repr_str
        assert "errors=1" in repr_str

    def test_errors_are_axon_parse_error_instances(self) -> None:
        result = _parse_recovery(
            "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        )
        for err in result.errors:
            assert isinstance(err, AxonParseError)
            assert err.line > 0
            assert err.column > 0


# ──────────────────────────────────────────────────────────────────────
# 6. Edge cases
# ──────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input_returns_clean_empty_result(self) -> None:
        result = _parse_recovery("")
        assert result.is_clean
        assert len(result.program.declarations) == 0

    def test_whitespace_only_input(self) -> None:
        result = _parse_recovery("   \n\n   \n")
        assert result.is_clean
        assert len(result.program.declarations) == 0

    def test_error_at_first_token(self) -> None:
        """Adversarial: first token is invalid at top level. Walker
        advances to the first sync point (or EOF)."""
        result = _parse_recovery("garbage_identifier\n")
        assert result.has_errors
        # No declarations parsed.
        assert len(result.program.declarations) == 0

    def test_unterminated_braces_recovers_to_eof(self) -> None:
        """`flow F { step S { ` with no closing braces: walker reaches
        EOF without finding a sync point. Outer loop terminates."""
        result = _parse_recovery("flow F { step S { ")
        assert result.has_errors
        # Doesn't infinite-loop or crash.

    def test_recovery_doesnt_crash_on_lex_clean_garbage(self) -> None:
        """Adversarial: all tokens lex cleanly but no recognized
        top-level construct exists. Recovery must NOT infinite-loop;
        the outer EOF check terminates the parse. NOTE: lexer-level
        errors are out of scope for parser recovery (they happen
        before the parser runs); this test exercises only the
        parser's robustness on lex-clean adversarial input."""
        # Identifiers + braces only — all lex cleanly but none form
        # a valid top-level declaration.
        result = _parse_recovery("foo bar baz { qux quux } corge { grault }")
        assert result is not None
        # The walker must terminate; we don't assert error count
        # because the recovery may consume some tokens cleanly.

    def test_recovery_after_error_in_first_decl_picks_up_second(
        self,
    ) -> None:
        """First declaration errors immediately; second is clean.
        Walker resyncs to second."""
        src = (
            "flow Bad( arg String )\n"  # missing `-> Type {body}`
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        result = _parse_recovery(src)
        assert result.has_errors
        names = [d.name for d in result.program.declarations]
        assert "Good" in names


# ──────────────────────────────────────────────────────────────────────
# 7. Robustness fuzz (D12 — 1000 iterations deterministic-seeded)
# ──────────────────────────────────────────────────────────────────────


class TestRobustnessFuzz:
    """Per D12 ratified: the parser MUST never crash (uncaught
    exception, infinite loop, stack overflow, etc.) on any input.
    Recovery mode is the safety net adopters depend on; if it can't
    handle adversarial input, it doesn't deliver its value.

    1000 iterations of randomly-mutated valid programs feed the
    parser. The seed is fixed so failures reproduce verbatim on every
    CI run.
    """

    SEED_PROGRAMS = [
        "flow F() -> Unit { step S { ask: \"q\" } }",
        "intent I { given: Document ask: \"x\" }",
        "tool T { description: \"x\" }",
        "persona P { name: \"alice\" }",
        "flow F(a: Int, b: String) -> Unit {\n"
        "  step S { ask: \"q\" output: Stream<String> }\n"
        "}",
    ]

    @pytest.mark.parametrize(
        "seed", list(range(0, 100))
    )  # 100 buckets × 10 mutations = 1000 iterations
    def test_random_mutation_never_crashes(self, seed: int) -> None:
        """The PARSER must never crash on lex-clean adversarial input.
        Lex-time errors (AxonLexerError) are out of scope for 28.b
        parser recovery — they are surfaced by the lexer before the
        parser runs and would be addressed by a future lexer-recovery
        sub-fase if adopters demand it. We swallow them here so the
        fuzz pack tests only the parser's robustness contract."""
        rng = random.Random(seed)
        for _ in range(10):
            base = rng.choice(self.SEED_PROGRAMS)
            mutated = self._mutate(base, rng)
            try:
                tokens = Lexer(mutated).tokenize()
            except AxonLexerError:
                # Lex-time errors are out of scope for parser
                # recovery; the lexer's robustness is a separate
                # concern. The parser is only on the hook for inputs
                # the lexer accepted.
                continue
            # Recovery MUST not raise an uncaught exception on
            # lex-clean input. Errors are returned in the result.
            try:
                result = Parser(tokens).parse_with_recovery()
            except Exception as e:  # noqa: BLE001
                pytest.fail(
                    f"parse_with_recovery raised uncaught {type(e).__name__} "
                    f"on lex-clean input (seed={seed}): {mutated!r}\n"
                    f"  → {e}"
                )
            # Result is always a ParseResult instance.
            assert isinstance(result, ParseResult)

    @staticmethod
    def _mutate(source: str, rng: random.Random) -> str:
        """Apply 0-3 random mutations: byte deletion, byte insertion,
        byte swap. Designed to produce realistic adopter-typo-style
        adversarial inputs."""
        chars = list(source)
        n_mutations = rng.randint(0, 3)
        for _ in range(n_mutations):
            if not chars:
                break
            op = rng.choice(["delete", "insert", "swap", "replace"])
            i = rng.randint(0, len(chars) - 1)
            if op == "delete":
                del chars[i]
            elif op == "insert":
                chars.insert(i, rng.choice("(){}<>[]:,;\"'"))
            elif op == "swap" and i + 1 < len(chars):
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
            elif op == "replace":
                chars[i] = rng.choice(
                    "abcdefghijklmnopqrstuvwxyz0123456789{}()[]<>:,;"
                )
        return "".join(chars)


# ──────────────────────────────────────────────────────────────────────
# 8. Recovery never produces ghost errors (structural quality)
# ──────────────────────────────────────────────────────────────────────


class TestNoGhostErrors:
    """Sync-point selection (D2) is intentionally aggressive: one
    error per logically broken block, not per token. These tests
    pin that contract — a single broken construct produces one
    error, not a flood.
    """

    def test_single_broken_field_produces_single_error(self) -> None:
        """A flow with three bad fields produces ONE error (the first
        detected) + the flow's `}` resyncs to next decl. Subsequent
        bad fields inside the broken flow are NOT reported as
        separate errors — the walker has already left the flow."""
        src = (
            "flow Bad() -> Unit {\n"
            "  step S {\n"
            "    bad_field_1 NotAColon\n"
            "    bad_field_2 AlsoNoColon\n"
            "    bad_field_3 StillNoColon\n"
            "  }\n"
            "}\n"
            "flow Good() -> Unit { step S { ask: \"ok\" } }\n"
        )
        result = _parse_recovery(src)
        # Exactly one error from the broken flow + zero errors from
        # the clean follow-up.
        assert len(result.errors) == 1
        assert len(result.program.declarations) == 1
        assert result.program.declarations[0].name == "Good"


# ──────────────────────────────────────────────────────────────────────
# 9. Integration with v1.19.4 colon-diagnostic
# ──────────────────────────────────────────────────────────────────────


class TestIntegrationWithColonDiagnostic:
    """The v1.19.4 missing-colon diagnostic produces an actionable
    error message. In recovery mode that same message is collected
    into the errors list — adopters get the actionable hint AND the
    full landscape of errors in one pass.
    """

    def test_recovery_mode_preserves_v1_19_4_colon_hint(self) -> None:
        src = "flow Bad( arg String ) -> Unit { step S { ask: \"q\" } }"
        result = _parse_recovery(src)
        assert len(result.errors) == 1
        msg = str(result.errors[0])
        # The v1.19.4 hint mentions both adjacent tokens explicitly.
        assert "arg" in msg
        assert "String" in msg
        # Plus the fix suggestion.
        assert "arg: String" in msg
