"""
Fase 14.d — ``axon fmt`` MVP formatter tests
==============================================

Validates the round-trip preservation contract of the token-level
formatter introduced in 14.d. The MVP guarantees:

  1. Every comment kind (regular, outer doc, inner doc; line and block)
     survives :func:`format_source` byte-identically.
  2. Trailing whitespace is trimmed from every line.
  3. The output ends with exactly one trailing newline.
  4. The function is idempotent: ``format_source(format_source(x)) ==
     format_source(x)``.

It also smoke-tests the ``axon fmt`` CLI subcommand: default mode
(stdout), ``--check`` (CI gate exit code), and ``--write`` (in-place
rewrite).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from axon.compiler.formatter import format_source


ROOT = Path(__file__).resolve().parent.parent
CLI_MODULE = [sys.executable, "-m", "axon.cli"]
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


# ═══════════════════════════════════════════════════════════════════
#  14.d.1 — format_source preserves all comment kinds verbatim
# ═══════════════════════════════════════════════════════════════════


class TestFormatPreservesComments:
    def test_regular_line_comment_preserved(self) -> None:
        src = "// header\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_outer_doc_line_comment_preserved(self) -> None:
        src = "/// documents F\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_inner_doc_line_comment_preserved(self) -> None:
        src = "//! file-level docs\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_outer_doc_block_comment_preserved(self) -> None:
        src = "/** documents F */\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_inner_doc_block_comment_preserved(self) -> None:
        src = "/*! file-level docs */\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_regular_block_comment_preserved(self) -> None:
        src = "/* aside */\nflow F() -> Out { }\n"
        assert format_source(src) == src

    def test_trailing_comment_preserved(self) -> None:
        src = "flow F() -> Out { } // trailing\n"
        assert format_source(src) == src

    def test_multiple_comments_in_source_order(self) -> None:
        src = (
            "//! module docs\n"
            "/// outer for A\n"
            "// header\n"
            "flow A() -> Out { }\n"
            "\n"
            "/// outer for B\n"
            "flow B() -> Out { }\n"
        )
        assert format_source(src) == src


# ═══════════════════════════════════════════════════════════════════
#  14.d.2 — Cosmetic normalisations
# ═══════════════════════════════════════════════════════════════════


class TestCosmeticNormalisations:
    def test_trailing_whitespace_trimmed(self) -> None:
        src = "flow F() -> Out { }   \n"
        assert format_source(src) == "flow F() -> Out { }\n"

    def test_trailing_blank_lines_collapse_to_single_newline(self) -> None:
        src = "flow F() -> Out { }\n\n\n\n"
        assert format_source(src) == "flow F() -> Out { }\n"

    def test_missing_final_newline_added(self) -> None:
        src = "flow F() -> Out { }"
        assert format_source(src) == "flow F() -> Out { }\n"

    def test_internal_blank_lines_preserved(self) -> None:
        # Single blank lines between declarations are layout the author
        # chose; the MVP does not collapse them.
        src = "flow A() -> Out { }\n\nflow B() -> Out { }\n"
        assert format_source(src) == src


# ═══════════════════════════════════════════════════════════════════
#  14.d.3 — Idempotence
# ═══════════════════════════════════════════════════════════════════


class TestIdempotence:
    @pytest.mark.parametrize(
        "src",
        [
            "flow F() -> Out { }\n",
            "/// docs\nflow F() -> Out { }\n",
            "//! header\n/// outer\nflow F() -> Out { }\n",
            "flow F() -> Out { }   \n",  # trailing whitespace
            "flow F() -> Out { }\n\n\n",  # extra blanks
        ],
    )
    def test_format_is_a_fixed_point(self, src: str) -> None:
        once = format_source(src)
        twice = format_source(once)
        assert once == twice


# ═══════════════════════════════════════════════════════════════════
#  14.d.4 — CLI smoke tests
# ═══════════════════════════════════════════════════════════════════


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=30,
        env=ENV,
        check=False,
    )


class TestFmtCli:
    def test_fmt_to_stdout(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.axon"
        # Trailing whitespace + no final newline → cosmetics will fire.
        f.write_text("flow F() -> Out { }   ", encoding="utf-8")
        result = _run("fmt", str(f))
        assert result.returncode == 0
        assert result.stdout == "flow F() -> Out { }\n"

    def test_fmt_check_passes_on_canonical(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.axon"
        f.write_text("flow F() -> Out { }\n", encoding="utf-8")
        result = _run("fmt", str(f), "--check", "--no-color")
        assert result.returncode == 0

    def test_fmt_check_fails_on_noncanonical(self, tmp_path: Path) -> None:
        f = tmp_path / "dirty.axon"
        f.write_text("flow F() -> Out { }   \n", encoding="utf-8")
        result = _run("fmt", str(f), "--check", "--no-color")
        assert result.returncode == 1
        # Source must be untouched on --check.
        assert f.read_text(encoding="utf-8") == "flow F() -> Out { }   \n"

    def test_fmt_write_rewrites_in_place(self, tmp_path: Path) -> None:
        f = tmp_path / "dirty.axon"
        f.write_text("flow F() -> Out { }   \n", encoding="utf-8")
        result = _run("fmt", str(f), "--write", "--no-color")
        assert result.returncode == 0
        assert f.read_text(encoding="utf-8") == "flow F() -> Out { }\n"

    def test_fmt_missing_file(self) -> None:
        result = _run("fmt", "examples/__missing__.axon", "--no-color")
        assert result.returncode == 2
