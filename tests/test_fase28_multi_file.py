"""§Fase 28.f — Multi-file aggregator tests.

Tests the path-collection + concurrent-parse + aggregation logic
in `axon/cli/_multi_file.py`, plus smoke tests of the CLI wrapper
in `axon/cli/parse_cmd.py`.

The aggregator stacks on top of every previous 28.x mechanism:

  * 28.b recovery mode — each file's errors are collected, never
    raised
  * 28.d source-context — each error carries a SourceSnippet
    rendering of its file
  * 28.e smart-suggest — typo'd keywords get "Did you mean X?"

So this test pack also verifies the integration: an adopter parsing
a multi-file corpus with mixed clean / typo'd files sees the right
diagnostics aggregated correctly.

D6 ratified 2026-05-10: no default cap on errors. The `--max-errors`
flag opts in to truncation.
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from axon.cli._multi_file import (
    AggregateReport,
    FileResult,
    aggregate,
    collect_paths,
    parse_files_concurrent,
    run,
)
from axon.cli.parse_cmd import cmd_parse


# ── helpers ──────────────────────────────────────────────────────


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ──────────────────────────────────────────────────────────────────────────
# TestCollectPaths — file walking, glob expansion, ignore handling
# ──────────────────────────────────────────────────────────────────────────


class TestCollectPaths:
    def test_single_file_path(self, tmp_path: Path):
        p = _write(tmp_path, "a.axon", "flow A() {}\n")
        out = collect_paths(["a.axon"], root=tmp_path)
        assert out == [p.resolve()]

    def test_directory_walks_recursively(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        _write(tmp_path, "sub/b.axon", "")
        _write(tmp_path, "sub/deep/c.axon", "")
        out = collect_paths(["."], root=tmp_path)
        names = sorted(p.name for p in out)
        assert names == ["a.axon", "b.axon", "c.axon"]

    def test_directory_skips_non_axon_files(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        _write(tmp_path, "b.txt", "")
        _write(tmp_path, "c.md", "")
        out = collect_paths(["."], root=tmp_path)
        assert [p.name for p in out] == ["a.axon"]

    def test_glob_pattern(self, tmp_path: Path):
        _write(tmp_path, "src/a.axon", "")
        _write(tmp_path, "src/sub/b.axon", "")
        _write(tmp_path, "tests/c.axon", "")
        out = collect_paths(["src/**/*.axon"], root=tmp_path)
        names = sorted(p.name for p in out)
        assert names == ["a.axon", "b.axon"]

    def test_explicit_file_overrides_extension_filter(self, tmp_path: Path):
        # Adopters who explicitly pass a non-.axon path get it parsed.
        p = _write(tmp_path, "weird.txt", "flow F() {}\n")
        out = collect_paths(["weird.txt"], root=tmp_path)
        assert out == [p.resolve()]

    def test_built_in_ignores_skip_git_dir(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        _write(tmp_path, ".git/config.axon", "")
        _write(tmp_path, "node_modules/lib.axon", "")
        out = collect_paths(["."], root=tmp_path)
        assert [p.name for p in out] == ["a.axon"]

    def test_axonignore_at_root_strips_matches(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        _write(tmp_path, "vendor/big.axon", "")
        _write(tmp_path, ".axonignore", "vendor/*\n# comment line\n")
        out = collect_paths(["."], root=tmp_path)
        assert [p.name for p in out] == ["a.axon"]

    def test_axonignore_in_subdir(self, tmp_path: Path):
        _write(tmp_path, "src/a.axon", "")
        _write(tmp_path, "src/skip_me.axon", "")
        _write(tmp_path, "src/.axonignore", "skip_me.axon\n")
        out = collect_paths(["src"], root=tmp_path)
        assert [p.name for p in out] == ["a.axon"]

    def test_explicit_ignore_pattern(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        _write(tmp_path, "draft.axon", "")
        out = collect_paths(
            ["."], root=tmp_path, ignore_patterns=["draft.axon"]
        )
        assert [p.name for p in out] == ["a.axon"]

    def test_dedup_overlapping_patterns(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "")
        out = collect_paths(["a.axon", ".", "a.axon"], root=tmp_path)
        # `a.axon` appears once despite three matching patterns.
        assert len(out) == 1

    def test_deterministic_order_alphabetical(self, tmp_path: Path):
        _write(tmp_path, "z.axon", "")
        _write(tmp_path, "m.axon", "")
        _write(tmp_path, "a.axon", "")
        out = collect_paths(["."], root=tmp_path)
        names = [p.name for p in out]
        assert names == sorted(names)

    def test_empty_patterns_returns_empty(self, tmp_path: Path):
        assert collect_paths([], root=tmp_path) == []

    def test_no_matches_returns_empty(self, tmp_path: Path):
        assert collect_paths(["nope/*.axon"], root=tmp_path) == []


# ──────────────────────────────────────────────────────────────────────────
# TestParseFilesConcurrent — thread-pool parse correctness
# ──────────────────────────────────────────────────────────────────────────


class TestParseFilesConcurrent:
    def test_clean_files_yield_no_errors(self, tmp_path: Path):
        p1 = _write(tmp_path, "a.axon", "flow A() {}\n")
        p2 = _write(tmp_path, "b.axon", "intent I {}\n")
        results = parse_files_concurrent([p1, p2])
        assert all(r.is_clean for r in results)
        assert [r.path for r in results] == [p1, p2]

    def test_errored_file_carries_recovery_errors(self, tmp_path: Path):
        p = _write(tmp_path, "bad.axon", "flwo F() {}\n")
        results = parse_files_concurrent([p])
        assert results[0].has_errors
        assert results[0].parse_errors
        # 28.e — smart-suggest hint must surface.
        assert any(
            "Did you mean `flow`?" in str(e)
            for e in results[0].parse_errors
        )

    def test_io_error_packaged_into_result(self, tmp_path: Path):
        # Path that doesn't exist → read_text raises OSError →
        # FileResult.io_error is set.
        nonexistent = tmp_path / "nope.axon"
        results = parse_files_concurrent([nonexistent])
        assert len(results) == 1
        assert results[0].io_error is not None
        assert not results[0].parse_errors

    def test_order_preserved(self, tmp_path: Path):
        paths = [
            _write(tmp_path, f"f{i}.axon", "intent I {}\n") for i in range(8)
        ]
        results = parse_files_concurrent(paths, max_workers=4)
        assert [r.path for r in results] == paths

    def test_empty_paths_returns_empty(self):
        assert parse_files_concurrent([]) == []


# ──────────────────────────────────────────────────────────────────────────
# TestAggregate — D6 max-errors cap + roll-up correctness
# ──────────────────────────────────────────────────────────────────────────


def _fake_error(line: int = 1) -> object:
    """Lightweight stand-in for AxonParseError. Aggregate doesn't
    inspect fields; it only counts."""
    from axon.compiler.errors import AxonParseError
    return AxonParseError("synthetic", line=line, column=1)


class TestAggregate:
    def test_all_clean_report_is_clean(self, tmp_path: Path):
        p = _write(tmp_path, "a.axon", "")
        report = aggregate([FileResult(path=p)])
        assert report.is_clean
        assert report.files_clean == 1

    def test_io_error_does_not_count_as_parse_error(self, tmp_path: Path):
        p = tmp_path / "a.axon"
        report = aggregate([FileResult(path=p, io_error="boom")])
        assert report.files_with_io_error == 1
        assert report.total_errors == 0
        assert not report.is_clean

    def test_no_max_errors_keeps_everything(self, tmp_path: Path):
        results = [
            FileResult(
                path=tmp_path / f"{i}.axon",
                parse_errors=tuple(_fake_error() for _ in range(3)),
            )
            for i in range(4)
        ]
        report = aggregate(results, max_errors=None)
        assert report.total_errors == 12
        assert report.files_with_errors == 4
        assert not report.truncated

    def test_max_errors_cap_truncates_at_boundary(self, tmp_path: Path):
        # 4 files × 3 errors = 12 total. Cap at 5 → keep file 1 (3
        # errors) + 2 errors of file 2 → total 5, truncated=True,
        # remaining files dropped from results.
        results = [
            FileResult(
                path=tmp_path / f"{i}.axon",
                parse_errors=tuple(_fake_error() for _ in range(3)),
            )
            for i in range(4)
        ]
        report = aggregate(results, max_errors=5)
        assert report.total_errors == 5
        assert report.truncated
        # First file kept whole (3 errors); second clipped to 2.
        assert len(report.results) == 2
        assert len(report.results[0].parse_errors) == 3
        assert len(report.results[1].parse_errors) == 2

    def test_max_errors_zero_drops_everything(self, tmp_path: Path):
        results = [
            FileResult(
                path=tmp_path / "a.axon",
                parse_errors=(_fake_error(),),
            )
        ]
        report = aggregate(results, max_errors=0)
        assert report.total_errors == 0
        assert report.truncated
        assert report.results == []  # nothing kept

    def test_max_errors_does_not_drop_clean_or_io_files(self, tmp_path: Path):
        # Even when the cap is exhausted, clean files and I/O-error
        # files still appear in results — only erroring files past
        # the cap are hidden. This keeps the corpus summary honest.
        a = FileResult(path=tmp_path / "a.axon")  # clean
        b = FileResult(
            path=tmp_path / "b.axon",
            parse_errors=tuple(_fake_error() for _ in range(2)),
        )
        c = FileResult(path=tmp_path / "c.axon", io_error="boom")
        d = FileResult(
            path=tmp_path / "d.axon",
            parse_errors=tuple(_fake_error() for _ in range(2)),
        )
        report = aggregate([a, b, c, d], max_errors=2)
        # `b` keeps both errors; `d` is dropped from results because
        # the cap is exhausted. `a` and `c` are still present.
        assert report.truncated
        assert {fr.path.name for fr in report.results} == {
            "a.axon",
            "b.axon",
            "c.axon",
        }


# ──────────────────────────────────────────────────────────────────────────
# TestRun — top-level convenience entry point
# ──────────────────────────────────────────────────────────────────────────


class TestRun:
    def test_mixed_corpus_end_to_end(self, tmp_path: Path):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "flwo B() {}\n")  # typo
        _write(tmp_path, "c.axon", "flow C() { stepp S {} }\n")  # typo
        _write(tmp_path, "d.axon", "intent I {}\n")
        report = run(["."], root=tmp_path)
        assert report.files_seen == 4
        assert report.files_clean == 2
        assert report.files_with_errors == 2
        assert report.total_errors == 2

    def test_smart_suggest_flows_through(self, tmp_path: Path):
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        report = run(["."], root=tmp_path)
        # The hint must reach the rendered error message.
        msgs = [str(e) for fr in report.results for e in fr.parse_errors]
        assert any("Did you mean `flow`?" in m for m in msgs)

    def test_source_context_block_attached(self, tmp_path: Path):
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        report = run(["."], root=tmp_path)
        full = "\n".join(
            str(e) for fr in report.results for e in fr.parse_errors
        )
        # The rustc-style block has " --> " preceded by the gutter.
        assert "--> " in full
        assert "bad.axon" in full

    def test_max_errors_propagates(self, tmp_path: Path):
        # Five files each with one typo'd keyword → 5 errors total.
        # Cap at 3 → truncated, total_errors==3.
        for i in range(5):
            _write(tmp_path, f"bad{i}.axon", "flwo F() {}\n")
        report = run(["."], root=tmp_path, max_errors=3)
        assert report.truncated
        assert report.total_errors == 3

    def test_io_error_path_yields_io_error_field(self, tmp_path: Path):
        # Pass an explicit non-existent file — collect_paths' file
        # check rejects it (is_file()==False) so it never reaches
        # the parser. To exercise the I/O-error path we have to
        # delete the file between collect and parse, OR pass a path
        # that exists but isn't readable. On Windows the easier
        # approach is to call _parse_one directly with a nonexistent
        # path.
        from axon.cli._multi_file import _parse_one
        fr = _parse_one(tmp_path / "nope.axon")
        assert fr.io_error is not None


# ──────────────────────────────────────────────────────────────────────────
# TestCmdParse — CLI wrapper smoke tests
# ──────────────────────────────────────────────────────────────────────────


def _ns(**kwargs) -> Namespace:
    """Build an argparse Namespace mimicking what argparse hands to
    `cmd_parse`. Defaults match the parser definition in
    `axon/cli/__init__.py`."""
    base = dict(
        patterns=[],
        max_errors=None,
        ignore=None,
        jobs=None,
        no_color=True,
    )
    base.update(kwargs)
    return Namespace(**base)


class TestCmdParse:
    def test_no_patterns_returns_two(self, capsys):
        rc = cmd_parse(_ns(patterns=[]))
        assert rc == 2
        err = capsys.readouterr().err
        assert "at least one path" in err

    def test_no_matches_prints_warning_returns_zero(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["nope/*.axon"]))
        assert rc == 0
        err = capsys.readouterr().err
        assert "no .axon files matched" in err

    def test_clean_corpus_returns_zero(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "a.axon", "flow A() {}\n")
        _write(tmp_path, "b.axon", "intent I {}\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."]))
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 file(s) parsed cleanly" in out

    def test_errored_corpus_returns_one(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        _write(tmp_path, "ok.axon", "flow A() {}\n")
        _write(tmp_path, "bad.axon", "flwo F() {}\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."]))
        assert rc == 1
        captured = capsys.readouterr()
        # Error block printed to stdout for the bad file (errors are
        # rendered alongside the per-file header on stdout).
        assert "Did you mean `flow`?" in captured.out
        # Summary footer mentions the error count.
        assert "1 total error" in captured.out

    def test_max_errors_truncation_footer(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        for i in range(3):
            _write(tmp_path, f"bad{i}.axon", "flwo F() {}\n")
        monkeypatch.chdir(tmp_path)
        rc = cmd_parse(_ns(patterns=["."], max_errors=1))
        assert rc == 1
        out = capsys.readouterr().out
        assert "truncated by --max-errors" in out
