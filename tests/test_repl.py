"""
AXON CLI — REPL tests.

Tests the REPL command's internal functions without launching an
interactive session.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from axon.cli.repl_cmd import (
    _eval_source,
    _handle_dot_command,
    _list_stdlib,
)


# ══════════════════════════════════════════════════════════════════
#  Dot-command dispatch
# ══════════════════════════════════════════════════════════════════


class TestDotCommands:
    """Test .help, .quit, .clear, and namespace commands."""

    def test_quit_returns_false(self):
        assert _handle_dot_command(".quit") is False

    def test_exit_returns_false(self):
        assert _handle_dot_command(".exit") is False

    def test_q_returns_false(self):
        assert _handle_dot_command(".q") is False

    def test_help_returns_true(self, capsys):
        assert _handle_dot_command(".help") is True
        out = capsys.readouterr().out
        assert ".help" in out
        assert ".quit" in out
        assert ".anchors" in out

    def test_clear_returns_true(self, capsys):
        assert _handle_dot_command(".clear") is True

    def test_anchors_returns_true(self, capsys):
        assert _handle_dot_command(".anchors") is True
        out = capsys.readouterr().out
        assert "ANCHORS" in out

    def test_personas_returns_true(self, capsys):
        assert _handle_dot_command(".personas") is True
        out = capsys.readouterr().out
        assert "PERSONAS" in out

    def test_unknown_command(self, capsys):
        assert _handle_dot_command(".foobar") is True
        out = capsys.readouterr().out
        assert "Unknown command" in out


# ══════════════════════════════════════════════════════════════════
#  Eval pipeline
# ══════════════════════════════════════════════════════════════════


class TestEvalSource:
    """Test the Lex → Parse → IR pipeline on inline AXON."""

    def test_valid_persona(self, capsys):
        source = 'persona Tester { domain: ["testing"] tone: precise }'
        _eval_source(source)
        out = capsys.readouterr().out
        # Should produce IR JSON with the persona name
        assert "Tester" in out

    def test_invalid_syntax_recovers(self, capsys):
        source = "persona {"  # bad syntax
        _eval_source(source)
        out = capsys.readouterr().out
        err = capsys.readouterr().err  # may be in stdout
        combined = out + err
        # Should show an error message, not crash
        assert "error" in combined.lower() or "Error" in combined or "error" in out.lower()

    def test_lexer_error_recovers(self, capsys):
        source = "@@invalid tokens@@"
        _eval_source(source)
        out = capsys.readouterr().out
        # Should recover gracefully
        assert "error" in out.lower() or len(out) > 0


# ══════════════════════════════════════════════════════════════════
#  Stdlib listing from REPL
# ══════════════════════════════════════════════════════════════════


class TestStdlibListing:
    """Test _list_stdlib for each namespace."""

    def test_list_anchors(self, capsys):
        _list_stdlib("anchors")
        out = capsys.readouterr().out
        assert "ANCHORS" in out
        assert "NoHallucination" in out

    def test_list_personas(self, capsys):
        _list_stdlib("personas")
        out = capsys.readouterr().out
        assert "PERSONAS" in out

    def test_list_tools(self, capsys):
        _list_stdlib("tools")
        out = capsys.readouterr().out
        assert "TOOLS" in out

    def test_invalid_namespace(self, capsys):
        _list_stdlib("nonexistent")
        out = capsys.readouterr().out
        assert "Invalid namespace" in out or "No nonexistent" in out
