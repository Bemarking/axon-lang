"""§Fase 28.d — Source-context diagnostic block tests (Python side).

Mirror file on Rust side: `mod fase28_source_context_tests` in
`axon-frontend/src/parser.rs`. The two stacks must produce
byte-identical render output on the same input — D7 ratified
(byte-identical error lists). The cross-stack drift gate (28.i)
will lock that in CI; here we cover the Python rendering correctness
+ the Parser-attach plumbing.

Test classes:

  * TestSnippetRendering — pure-text rendering of `SourceSnippet.render()`
  * TestSnippetEdgeCases — empty source, OOB line, unicode, EOL caret
  * TestParserAttach     — Parser(source=…) attaches snippet to errors
  * TestRecoveryAttach   — every recovered error carries a snippet
  * TestStrictAttach     — `parse()` strict mode also attaches
  * TestBackwardsCompat  — Parser(tokens) without source still works
  * TestRustParityShape  — golden-text fixtures shared with Rust pack
"""
from __future__ import annotations

import pytest

from axon.compiler.errors import (
    AxonParseError,
    SourceSnippet,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# ── helpers ──────────────────────────────────────────────────────────────


def _snippet(
    source: str,
    line: int,
    column: int,
    filename: str = "<source>",
) -> str:
    return SourceSnippet(
        source=source,
        line=line,
        column=column,
        filename=filename,
    ).render()


# ──────────────────────────────────────────────────────────────────────────
# TestSnippetRendering — pure rendering tests (no Parser involvement)
# ──────────────────────────────────────────────────────────────────────────


class TestSnippetRendering:
    def test_rustc_style_block_for_middle_line(self):
        src = "line one\nline two\nline three\nline four\nline five"
        out = _snippet(src, line=3, column=6, filename="x.axon")
        # Gutter width = 1 (max line = 5). 3 is the middle.
        assert "--> x.axon:3:6" in out
        assert "1 | line one" in out
        assert "2 | line two" in out
        assert "3 | line three" in out
        assert "4 | line four" in out
        assert "5 | line five" in out
        # Caret column 6 → 5 spaces of pad. Empty gutter is 1 space.
        assert "\n  |      ^" in out

    def test_caret_column_one_renders_correctly(self):
        src = "abc\n"
        out = _snippet(src, line=1, column=1)
        assert "\n  | ^" in out  # zero leading spaces before caret

    def test_first_line_clamps_context_before_to_zero(self):
        src = "first\nsecond\nthird\nfourth\nfifth"
        out = _snippet(src, line=1, column=1)
        # No line 0; rendering starts at line 1. Gutter = 1.
        assert "1 | first" in out
        assert "2 | second" in out
        assert "3 | third" in out  # context_after = 2
        assert "4 | fourth" not in out  # past context_after

    def test_last_line_clamps_context_after_to_eof(self):
        src = "first\nsecond\nthird\nfourth\nfifth"
        out = _snippet(src, line=5, column=2)
        assert "5 | fifth" in out
        # context_before = 2 → lines 3, 4 included; line 2 excluded.
        assert "3 | third" in out
        assert "4 | fourth" in out
        assert "2 | second" not in out

    def test_gutter_width_grows_with_line_count(self):
        # 12-line source, error on line 12 → 2-digit gutter.
        src = "\n".join(f"line{i}" for i in range(1, 13))
        out = _snippet(src, line=12, column=1)
        assert "12 | line12" in out
        # Gutter width = 2 → " 10" should appear right-aligned.
        assert "10 | line10" in out


# ──────────────────────────────────────────────────────────────────────────
# TestSnippetEdgeCases
# ──────────────────────────────────────────────────────────────────────────


class TestSnippetEdgeCases:
    def test_empty_source_returns_empty(self):
        assert _snippet("", line=1, column=1) == ""

    def test_zero_line_returns_empty(self):
        assert _snippet("hi", line=0, column=1) == ""

    def test_out_of_range_line_returns_empty(self):
        assert _snippet("hi", line=99, column=1) == ""

    def test_caret_clamps_past_eol(self):
        # Line is 5 chars; column 50 should clamp to col=6 (len+1).
        src = "hello"
        out = _snippet(src, line=1, column=50)
        # Caret renders at position len+1 = 6, so 5 spaces of pad.
        assert "\n  |      ^" in out

    def test_unicode_codepoint_count_for_caret_clamp(self):
        # 4 user-perceived chars; column past EOL clamps to 5.
        src = "héllo"
        out = _snippet(src, line=1, column=99)
        # codepoint count for "héllo" = 5 → caret at col 6 → 5-space pad
        assert "\n  |      ^" in out

    def test_trailing_newline_does_not_create_phantom_last_line(self):
        # Python's str.splitlines() drops the trailing empty entry; the
        # Rust mirror also strips a single trailing empty entry. This
        # test pins that contract.
        src = "first\nsecond\n"
        out = _snippet(src, line=2, column=1)
        assert "3 |" not in out  # phantom line guard
        assert "2 | second" in out


# ──────────────────────────────────────────────────────────────────────────
# TestParserAttach — Parser(source=...) plumbing
# ──────────────────────────────────────────────────────────────────────────


class TestParserAttach:
    def test_strict_parse_attaches_snippet_when_source_given(self):
        src = "garbage_token\nflow F() { }"
        tokens = Lexer(src).tokenize()
        parser = Parser(tokens, source=src, filename="x.axon")
        with pytest.raises(AxonParseError) as excinfo:
            parser.parse()
        err = excinfo.value
        assert err.source_snippet is not None
        assert "--> x.axon:" in str(err)

    def test_strict_parse_no_snippet_when_no_source(self):
        # Backwards compat: legacy callers pass only tokens.
        src = "garbage_token"
        tokens = Lexer(src).tokenize()
        parser = Parser(tokens)  # no source kwarg
        with pytest.raises(AxonParseError) as excinfo:
            parser.parse()
        err = excinfo.value
        assert err.source_snippet is None
        # Single-line shape preserved.
        assert "\n  -->" not in str(err)


# ──────────────────────────────────────────────────────────────────────────
# TestRecoveryAttach — every recovered error gets a snippet
# ──────────────────────────────────────────────────────────────────────────


class TestRecoveryAttach:
    def test_every_recovered_error_has_snippet(self):
        src = "garbage1\nflow F() { }\ngarbage2\nflow G() { }"
        tokens = Lexer(src).tokenize()
        result = Parser(tokens, source=src, filename="multi.axon").parse_with_recovery()
        assert len(result.errors) >= 1
        for err in result.errors:
            assert err.source_snippet is not None
            assert "--> multi.axon:" in str(err)

    def test_recovery_no_snippet_when_no_source(self):
        src = "garbage1 garbage2"
        tokens = Lexer(src).tokenize()
        result = Parser(tokens).parse_with_recovery()
        for err in result.errors:
            assert err.source_snippet is None

    def test_snippet_points_at_correct_line_for_each_error(self):
        # Multi-line source with errors on distinct lines.
        src = "garbage_a\nflow F() { }\ngarbage_b\nflow G() { }"
        tokens = Lexer(src).tokenize()
        result = Parser(tokens, source=src, filename="x").parse_with_recovery()
        for err in result.errors:
            sn = err.source_snippet
            assert sn is not None
            # Line referenced in the snippet matches err.line.
            assert sn.line == err.line


# ──────────────────────────────────────────────────────────────────────────
# TestBackwardsCompat
# ──────────────────────────────────────────────────────────────────────────


class TestBackwardsCompat:
    def test_legacy_constructor_still_works(self):
        src = "flow F() { }"
        tokens = Lexer(src).tokenize()
        parser = Parser(tokens)
        prog = parser.parse()
        assert len(prog.declarations) == 1

    def test_attach_source_method_idempotent(self):
        err = AxonParseError("bad", line=2, column=3)
        err.attach_source("a\nb\nc\n", "f.axon")
        first = str(err)
        err.attach_source("a\nb\nc\n", "f.axon")
        second = str(err)
        assert first == second

    def test_attach_source_noop_when_line_zero(self):
        err = AxonParseError("bad", line=0, column=0)
        err.attach_source("a\nb\nc\n", "f.axon")
        assert err.source_snippet is None


# ──────────────────────────────────────────────────────────────────────────
# TestRustParityShape — fixed golden strings the Rust pack must match
# ──────────────────────────────────────────────────────────────────────────


class TestRustParityShape:
    """These golden strings are duplicated verbatim in the Rust test
    pack. The cross-stack drift gate (28.i) compares input → output
    on both stacks and asserts byte-identical equality. Edits here
    must be mirrored on the Rust side and vice versa.
    """

    def test_golden_simple_three_line_block(self):
        src = "alpha\nbeta\ngamma"
        out = _snippet(src, line=2, column=3, filename="g.axon")
        expected = (
            "  --> g.axon:2:3\n"
            "  |\n"
            "1 | alpha\n"
            "2 | beta\n"
            "  |   ^\n"
            "3 | gamma"
        )
        assert out == expected

    def test_golden_first_line_caret(self):
        src = "abc\ndef\n"
        out = _snippet(src, line=1, column=1, filename="x")
        expected = (
            "  --> x:1:1\n"
            "  |\n"
            "1 | abc\n"
            "  | ^\n"
            "2 | def"
        )
        assert out == expected

    def test_golden_two_digit_gutter(self):
        src = "\n".join(f"L{i}" for i in range(1, 12))
        out = _snippet(src, line=10, column=2, filename="big")
        # Gutter width = 2.
        expected_lines = [
            "   --> big:10:2",
            "   |",
            " 8 | L8",
            " 9 | L9",
            "10 | L10",
            "   |  ^",
            "11 | L11",
        ]
        assert out == "\n".join(expected_lines)
