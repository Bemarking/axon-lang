"""§Fase 28.g — Structured JSON output tests.

D5 ratified 2026-05-10: rustc-compatible field shapes. The wire
format mirrors ``rustc --error-format=json`` so adopters who
already consume Rust compiler output (or who map rustc JSON to
LSP `Diagnostic`) work against ``axon parse --json`` without
code changes.

Test classes:

  * TestErrorToJson      — single-error → diagnostic dict
  * TestFileResultToJson — per-file shape (clean / errors / I/O)
  * TestReportSerialize  — array vs ndjson formats, edge cases
  * TestLspMapping       — to_lsp_diagnostic conversion
  * TestCmdParseJson     — end-to-end CLI integration
  * TestRustcParity      — golden field-shape contract pinned
"""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from axon.cli._json_output import (
    FORMAT_ARRAY,
    FORMAT_NDJSON,
    SUPPORTED_FORMATS,
    diagnostics_iter,
    error_to_json,
    file_result_to_json,
    report_to_json,
    to_lsp_diagnostic,
)
from axon.cli._multi_file import AggregateReport, FileResult, run
from axon.cli.parse_cmd import cmd_parse
from axon.compiler.errors import AxonParseError, SourceSnippet


# ── helpers ──────────────────────────────────────────────────────


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ──────────────────────────────────────────────────────────────────────────
# TestErrorToJson
# ──────────────────────────────────────────────────────────────────────────


class TestErrorToJson:
    def test_basic_shape_has_required_fields(self):
        err = AxonParseError("oops", line=3, column=5)
        d = error_to_json(err, file_name="foo.axon")
        # rustc-compatible field set (D5).
        for key in ("severity", "code", "source", "message", "spans", "children"):
            assert key in d
        assert d["severity"] == "error"
        assert d["code"] == "AXON_PARSE_ERROR"
        assert d["source"] == "axon-lang"
        assert d["message"] == "oops"
        assert d["children"] == []
        assert isinstance(d["spans"], list) and len(d["spans"]) == 1

    def test_span_uses_attached_snippet_filename(self):
        err = AxonParseError("oops", line=2, column=3)
        err.attach_source("alpha\nbeta\ngamma", "g.axon")
        d = error_to_json(err)
        assert d["spans"][0]["file_name"] == "g.axon"
        # Source-text window pulls 2 before + 2 after (D4).
        assert d["spans"][0]["source_text"] == ["alpha", "beta", "gamma"]

    def test_explicit_file_name_overrides_snippet_filename(self):
        err = AxonParseError("oops", line=1, column=1)
        err.attach_source("x\n", "old.axon")
        d = error_to_json(err, file_name="new.axon")
        assert d["spans"][0]["file_name"] == "new.axon"

    def test_no_snippet_yields_empty_source_text(self):
        err = AxonParseError("oops", line=4, column=2)
        d = error_to_json(err, file_name="foo.axon")
        span = d["spans"][0]
        assert span["source_text"] == []
        assert span["line_start"] == 4
        assert span["column_start"] == 2

    def test_default_file_name_when_none_provided(self):
        err = AxonParseError("oops", line=1, column=1)
        d = error_to_json(err)
        assert d["spans"][0]["file_name"] == "<source>"

    def test_span_is_primary_true(self):
        # Every parser error has exactly one location at this layer.
        err = AxonParseError("x", line=1, column=1)
        d = error_to_json(err)
        assert d["spans"][0]["is_primary"] is True

    def test_span_label_field_is_null(self):
        err = AxonParseError("x", line=1, column=1)
        d = error_to_json(err)
        assert d["spans"][0]["label"] is None

    def test_line_end_equals_line_start(self):
        # Single-token errors collapse to a point span.
        err = AxonParseError("x", line=7, column=4)
        d = error_to_json(err)
        span = d["spans"][0]
        assert span["line_start"] == span["line_end"] == 7
        assert span["column_start"] == span["column_end"] == 4


# ──────────────────────────────────────────────────────────────────────────
# TestFileResultToJson
# ──────────────────────────────────────────────────────────────────────────


class TestFileResultToJson:
    def test_clean_file_yields_empty_list(self, tmp_path: Path):
        fr = FileResult(path=tmp_path / "a.axon")
        assert file_result_to_json(fr) == []

    def test_errored_file_yields_one_diag_per_error(self, tmp_path: Path):
        errs = (
            AxonParseError("e1", line=1, column=1),
            AxonParseError("e2", line=2, column=1),
        )
        fr = FileResult(path=tmp_path / "a.axon", parse_errors=errs)
        out = file_result_to_json(fr)
        assert len(out) == 2
        assert out[0]["message"] == "e1"
        assert out[1]["message"] == "e2"
        # File name attached from FileResult.path.
        assert all(d["spans"][0]["file_name"] == str(tmp_path / "a.axon") for d in out)

    def test_io_error_yields_synthetic_diag(self, tmp_path: Path):
        fr = FileResult(path=tmp_path / "a.axon", io_error="permission denied")
        out = file_result_to_json(fr)
        assert len(out) == 1
        d = out[0]
        assert d["code"] == "AXON_IO_ERROR"
        assert d["message"] == "permission denied"
        assert d["spans"][0]["line_start"] == 0
        assert d["spans"][0]["source_text"] == []


# ──────────────────────────────────────────────────────────────────────────
# TestReportSerialize
# ──────────────────────────────────────────────────────────────────────────


class TestReportSerialize:
    def _report_with(self, results: list[FileResult]) -> AggregateReport:
        rep = AggregateReport()
        rep.results = results
        return rep

    def test_empty_array_is_valid_json(self):
        out = report_to_json(self._report_with([]), format=FORMAT_ARRAY)
        assert out == "[]"
        assert json.loads(out) == []

    def test_empty_ndjson_is_empty_string(self):
        out = report_to_json(self._report_with([]), format=FORMAT_NDJSON)
        assert out == ""

    def test_array_serializes_all_diagnostics(self, tmp_path: Path):
        fr = FileResult(
            path=tmp_path / "a.axon",
            parse_errors=(
                AxonParseError("e1", line=1, column=1),
                AxonParseError("e2", line=2, column=2),
            ),
        )
        out = report_to_json(self._report_with([fr]), format=FORMAT_ARRAY)
        parsed = json.loads(out)
        assert len(parsed) == 2
        assert [d["message"] for d in parsed] == ["e1", "e2"]

    def test_ndjson_one_object_per_line(self, tmp_path: Path):
        fr = FileResult(
            path=tmp_path / "a.axon",
            parse_errors=(
                AxonParseError("e1", line=1, column=1),
                AxonParseError("e2", line=2, column=1),
            ),
        )
        out = report_to_json(self._report_with([fr]), format=FORMAT_NDJSON)
        # Trailing newline guaranteed.
        assert out.endswith("\n")
        lines = out.rstrip("\n").split("\n")
        assert len(lines) == 2
        # Each line is a complete JSON object.
        parsed = [json.loads(line) for line in lines]
        assert [d["message"] for d in parsed] == ["e1", "e2"]

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown format"):
            report_to_json(self._report_with([]), format="bogus")

    def test_indent_pretty_prints_array(self, tmp_path: Path):
        fr = FileResult(
            path=tmp_path / "a.axon",
            parse_errors=(AxonParseError("e1", line=1, column=1),),
        )
        out = report_to_json(self._report_with([fr]), format=FORMAT_ARRAY, indent=2)
        # Newlines + 2-space indent.
        assert "\n  " in out

    def test_supported_formats_pinned(self):
        assert SUPPORTED_FORMATS == ("array", "ndjson")

    def test_diagnostics_iter_preserves_order(self, tmp_path: Path):
        fr1 = FileResult(
            path=tmp_path / "a.axon",
            parse_errors=(AxonParseError("a", line=1, column=1),),
        )
        fr2 = FileResult(
            path=tmp_path / "b.axon",
            parse_errors=(AxonParseError("b", line=1, column=1),),
        )
        rep = self._report_with([fr1, fr2])
        msgs = [d["message"] for d in diagnostics_iter(rep)]
        assert msgs == ["a", "b"]


# ──────────────────────────────────────────────────────────────────────────
# TestLspMapping
# ──────────────────────────────────────────────────────────────────────────


class TestLspMapping:
    def test_severity_error_maps_to_one(self):
        diag = error_to_json(AxonParseError("x", line=1, column=1))
        lsp = to_lsp_diagnostic(diag)
        assert lsp["severity"] == 1

    def test_line_column_converted_to_zero_based(self):
        diag = error_to_json(AxonParseError("x", line=3, column=5))
        lsp = to_lsp_diagnostic(diag)
        assert lsp["range"]["start"] == {"line": 2, "character": 4}
        assert lsp["range"]["end"] == {"line": 2, "character": 4}

    def test_zero_value_clamped_to_zero(self):
        diag = error_to_json(AxonParseError("x", line=0, column=0))
        lsp = to_lsp_diagnostic(diag)
        # max(0, 0 - 1) → 0, not -1.
        assert lsp["range"]["start"]["line"] == 0
        assert lsp["range"]["start"]["character"] == 0

    def test_required_lsp_keys_present(self):
        diag = error_to_json(AxonParseError("hello", line=1, column=1))
        lsp = to_lsp_diagnostic(diag)
        for key in ("range", "severity", "code", "source", "message"):
            assert key in lsp
        assert lsp["message"] == "hello"
        assert lsp["source"] == "axon-lang"
        assert lsp["code"] == "AXON_PARSE_ERROR"


# ──────────────────────────────────────────────────────────────────────────
# TestCmdParseJson — end-to-end CLI
# ──────────────────────────────────────────────────────────────────────────


def _ns(**kwargs) -> Namespace:
    base = dict(
        patterns=[],
        max_errors=None,
        ignore=None,
        jobs=None,
        no_color=True,
        json=False,
        format="array",
    )
    base.update(kwargs)
    return Namespace(**base)


class TestCmdParseJson:
    def test_clean_corpus_emits_empty_array(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."], json=True))
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert json.loads(out) == []

    def test_errored_corpus_emits_array_diagnostics(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."], json=True))
        assert rc == 1
        out = capsys.readouterr().out
        diags = json.loads(out)
        assert len(diags) == 1
        d = diags[0]
        # Smart-suggest hint flows through.
        assert "Did you mean `flow`?" in d["message"]
        # File name is the absolute path.
        assert d["spans"][0]["file_name"].endswith("bad.axon")
        # Source-text block populated by 28.d snippet.
        assert d["spans"][0]["source_text"] == ["flwo F() {}"]

    def test_ndjson_format_one_per_line(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flwo A() {}\n")
        _write(tmp_path, "b.axon", "flow B() { stepp S {} }\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."], json=True, format="ndjson"))
        assert rc == 1
        out = capsys.readouterr().out
        # Trailing newline + each line a complete JSON object.
        lines = out.rstrip("\n").split("\n")
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert obj["severity"] == "error"
            assert obj["code"] == "AXON_PARSE_ERROR"

    def test_no_match_emits_empty_array_no_stderr_warning(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        # In JSON mode the human-friendly stderr warning is
        # suppressed so tooling consuming the pipe gets clean JSON.
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["nope/*.axon"], json=True))
        assert rc == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out.strip()) == []
        # No "no .axon files matched" warning to stderr.
        assert "no .axon files matched" not in captured.err


# ──────────────────────────────────────────────────────────────────────────
# TestRustcParity — golden field-shape contract pinned
# ──────────────────────────────────────────────────────────────────────────


class TestRustcParity:
    """Pinned wire shape. Field NAMES match rustc's
    ``--error-format=json`` exactly. Adding new fields is fine
    (rustc adds them too over time); RENAMING an existing field is
    a breaking change for adopter tooling.
    """

    def test_top_level_keys_are_rustc_compatible(self):
        d = error_to_json(AxonParseError("x", line=1, column=1))
        assert set(d.keys()) == {
            "severity", "code", "source", "message", "spans", "children",
        }

    def test_span_keys_are_rustc_compatible(self):
        d = error_to_json(AxonParseError("x", line=1, column=1))
        span = d["spans"][0]
        assert set(span.keys()) == {
            "file_name",
            "line_start",
            "line_end",
            "column_start",
            "column_end",
            "is_primary",
            "label",
            "source_text",
        }

    def test_severity_is_lowercase_string(self):
        # rustc uses lowercase "error" / "warning" / "note" / "help".
        d = error_to_json(AxonParseError("x", line=1, column=1))
        assert d["severity"] == "error"

    def test_source_text_is_list_of_strings(self):
        err = AxonParseError("x", line=2, column=1)
        err.attach_source("a\nb\nc\n", "f.axon")
        d = error_to_json(err)
        st = d["spans"][0]["source_text"]
        assert isinstance(st, list)
        assert all(isinstance(line, str) for line in st)
        # No trailing newlines on individual lines.
        assert all("\n" not in line for line in st)
