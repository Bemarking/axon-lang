"""§Fase 28.h — `--strict` opt-in mode tests.

D8 ratified 2026-05-10: opt-in surface = CLI flag (`--strict`) +
env var (`AXON_PARSER_STRICT`), no config file. Strict mode flips
back to legacy fail-on-first behavior — `Parser.parse()` strict
semantics — so adopters who want a tight CI halt-on-failure loop
can opt in without losing the new diagnostic surface.

Default behavior (no flag, no env var) is recovery mode (D1) and
is unchanged.

Test classes:

  * TestRunStrictHelper    — `_multi_file.run_strict()` correctness
  * TestStrictEnvVar       — env-var truthy/falsy parsing
  * TestCmdParseStrict     — CLI integration (flag + env)
  * TestStrictBackwardsCompat — default behavior unaffected
"""
from __future__ import annotations

import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from axon.cli._multi_file import run_strict
from axon.cli.parse_cmd import _STRICT_ENV_VAR, _strict_from_env, cmd_parse


# ── helpers ──────────────────────────────────────────────────────


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _ns(**kwargs) -> Namespace:
    """Argparse Namespace mirroring the parser definition."""
    base = dict(
        patterns=[],
        max_errors=None,
        ignore=None,
        jobs=None,
        no_color=True,
        json=False,
        format="array",
        strict=False,
    )
    base.update(kwargs)
    return Namespace(**base)


# ──────────────────────────────────────────────────────────────────────────
# TestRunStrictHelper — fail-on-first walker correctness
# ──────────────────────────────────────────────────────────────────────────


class TestRunStrictHelper:
    def test_clean_corpus_returns_clean_report(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "intent I {}\n")
        report = run_strict(["."], root=tmp_path)
        assert report.is_clean
        assert report.files_clean == 2
        assert not report.truncated

    def test_halts_at_first_failing_file(self, tmp_path: Path):
        # Three files; the second errs. Strict mode parses a, parses
        # b, hits the error, halts — c is never parsed.
        # Filenames are alphabetical so a < b < c is the walk order.
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "flwo F() {}\n")  # typo
        _write(tmp_path, "c.axon", "flow C() {}\n")
        report = run_strict(["."], root=tmp_path)
        assert report.files_seen == 3
        assert report.files_clean == 1
        assert report.files_with_errors == 1
        assert report.total_errors == 1
        assert report.truncated  # one file skipped after halt
        # Results contain only files that were actually parsed.
        names = sorted(fr.path.name for fr in report.results)
        assert names == ["a.axon", "b.axon"]

    def test_strict_caps_at_one_error_per_file(self, tmp_path: Path):
        # File has multiple errors; strict mode only keeps the first.
        _write(
            tmp_path,
            "many.axon",
            "flwo F() {}\nflwo G() {}\nflwo H() {}\n",
        )
        report = run_strict(["."], root=tmp_path)
        assert report.total_errors == 1
        assert len(report.results[0].parse_errors) == 1

    def test_io_error_halts_strict_walk_too(self, tmp_path: Path):
        # We can't easily make a file unreadable cross-platform, but
        # we can test the unicode-decode path: write raw bytes that
        # aren't valid UTF-8.
        bad = tmp_path / "binary.axon"
        bad.write_bytes(b"\xff\xfe\x00\x01\x02")
        _write(tmp_path, "z_after.axon", "flow Z() {}\n")
        report = run_strict(["."], root=tmp_path)
        # The binary file fires a UnicodeDecodeError → io_error;
        # walk halts and the alphabetically-later z_after.axon is
        # skipped.
        assert report.files_with_io_error == 1
        assert report.truncated
        assert all(
            fr.path.name != "z_after.axon" for fr in report.results
        )

    def test_smart_suggest_hint_preserved_in_strict_mode(
        self, tmp_path: Path
    ):
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        report = run_strict(["."], root=tmp_path)
        msgs = [str(e) for fr in report.results for e in fr.parse_errors]
        assert any("Did you mean `flow`?" in m for m in msgs)

    def test_source_context_attached_in_strict_mode(self, tmp_path: Path):
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        report = run_strict(["."], root=tmp_path)
        full = "\n".join(
            str(e) for fr in report.results for e in fr.parse_errors
        )
        assert "--> " in full
        assert "bad.axon" in full

    def test_empty_corpus_is_clean(self, tmp_path: Path):
        report = run_strict([], root=tmp_path)
        assert report.is_clean
        assert report.files_seen == 0


# ──────────────────────────────────────────────────────────────────────────
# TestStrictEnvVar — truthy/falsy parsing
# ──────────────────────────────────────────────────────────────────────────


class TestStrictEnvVar:
    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        assert _strict_from_env() is False

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, "")
        assert _strict_from_env() is False

    def test_zero_is_falsy(self, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, "0")
        assert _strict_from_env() is False

    def test_one_is_truthy(self, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, "1")
        assert _strict_from_env() is True

    @pytest.mark.parametrize(
        "raw",
        ["true", "True", "TRUE", "yes", "YES", "on", "ON", "y", "t"],
    )
    def test_truthy_strings_case_insensitive(self, raw: str, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, raw)
        assert _strict_from_env() is True

    @pytest.mark.parametrize("raw", ["no", "off", "false", "bogus", "  "])
    def test_falsy_or_unknown_returns_false(self, raw: str, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, raw)
        assert _strict_from_env() is False

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv(_STRICT_ENV_VAR, "  true  ")
        assert _strict_from_env() is True


# ──────────────────────────────────────────────────────────────────────────
# TestCmdParseStrict — CLI integration (flag + env)
# ──────────────────────────────────────────────────────────────────────────


class TestCmdParseStrict:
    def test_flag_halts_at_first_error(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "flwo F() {}\n")
        _write(tmp_path, "c.axon", "flow C() { stepp S {} }\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        rc = cmd_parse(_ns(patterns=["."], strict=True))
        assert rc == 1
        out = capsys.readouterr().out
        # Strict halts at b.axon; c.axon never parsed.
        assert "b.axon" in out
        # Strict-mode footer fires.
        assert "strict mode halted at first failing file" in out
        # Remaining-files count appears.
        assert "1 remaining file(s) skipped" in out

    def test_env_var_truthy_enables_strict(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "flwo F() {}\n")
        _write(tmp_path, "c.axon", "intent I {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(_STRICT_ENV_VAR, "1")
        rc = cmd_parse(_ns(patterns=["."], strict=False))  # flag off
        assert rc == 1
        out = capsys.readouterr().out
        # Env var alone enables strict mode → footer present.
        assert "strict mode halted at first failing file" in out

    def test_env_var_falsy_does_not_enable_strict(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flwo A() {}\n")
        _write(tmp_path, "b.axon", "flwo B() {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(_STRICT_ENV_VAR, "0")
        rc = cmd_parse(_ns(patterns=["."], strict=False))
        assert rc == 1
        out = capsys.readouterr().out
        # Recovery mode → BOTH errors surface.
        assert out.count("Did you mean `flow`?") == 2
        assert "strict mode halted" not in out

    def test_strict_works_with_json_mode(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        _write(tmp_path, "c.axon", "flwo G() {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        rc = cmd_parse(_ns(patterns=["."], strict=True, json=True))
        assert rc == 1
        out = capsys.readouterr().out
        diags = json.loads(out)
        # Strict caps at 1 error from the first failing file.
        assert len(diags) == 1
        assert "Did you mean `flow`?" in diags[0]["message"]

    def test_strict_clean_corpus_returns_zero(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "intent I {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        rc = cmd_parse(_ns(patterns=["."], strict=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 file(s) parsed cleanly" in out

    def test_flag_overrides_falsy_env(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        # `--strict` set + env var off → strict mode wins (OR semantics).
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "flwo F() {}\n")
        _write(tmp_path, "c.axon", "flwo G() {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(_STRICT_ENV_VAR, "0")
        rc = cmd_parse(_ns(patterns=["."], strict=True))
        out = capsys.readouterr().out
        assert "strict mode halted" in out
        assert rc == 1


# ──────────────────────────────────────────────────────────────────────────
# TestStrictBackwardsCompat — default behavior unchanged
# ──────────────────────────────────────────────────────────────────────────


class TestStrictBackwardsCompat:
    def test_default_no_strict_no_env_uses_recovery(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flwo A() {}\n")
        _write(tmp_path, "b.axon", "flwo B() {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        rc = cmd_parse(_ns(patterns=["."]))
        assert rc == 1
        out = capsys.readouterr().out
        # Recovery mode: BOTH errors surface, no strict footer.
        assert out.count("Did you mean `flow`?") == 2
        assert "strict mode halted" not in out

    def test_max_errors_still_works_in_recovery_mode(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        # Recovery + --max-errors should keep emitting the D6
        # truncation footer (NOT the strict-mode footer).
        _write(tmp_path, "a.axon", "flwo A() {}\n")
        _write(tmp_path, "b.axon", "flwo B() {}\n")
        _write(tmp_path, "c.axon", "flwo C() {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(_STRICT_ENV_VAR, raising=False)
        rc = cmd_parse(_ns(patterns=["."], max_errors=1, strict=False))
        assert rc == 1
        out = capsys.readouterr().out
        assert "truncated by --max-errors" in out
        assert "strict mode halted" not in out
