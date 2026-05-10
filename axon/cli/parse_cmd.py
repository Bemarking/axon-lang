"""§Fase 28.f — `axon parse` CLI subcommand.

Multi-file aggregator: walks one-or-more file paths / directories /
glob patterns, parses every `.axon` file in the resulting set with
recovery mode (28.b), and prints an adopter-friendly summary that
includes every error from every file in one pass.

Adopters with substantial `.axon` codebases hit the diagnostic
discovery wall during migration: each `axon check <file>` failure
shows ONE error from ONE file. With a 30-file corpus that is
30 deploy cycles to surface every issue. `axon parse <pattern>`
fixes the discovery loop — adopters see the whole landscape at
once.

Exit codes:
    0   every file parsed cleanly
    1   one or more files had parse errors
    2   one or more files couldn't be read (I/O error)
    1+2 → 3 (both classes of error present)

Flags:
    --max-errors N    (D6) Cap the total number of errors reported.
                       Default: unlimited. The CLI prints a
                       "showing N of M errors — N hidden" footer
                       when the cap kicks in.
    --ignore PATTERN  Add a fnmatch-style ignore pattern (repeatable).
                       `.axonignore` files in the root + each walked
                       directory are also picked up automatically.
    --jobs N          Worker thread count. Default: auto.
    --no-color        Disable ANSI colors (also auto-disabled when
                       stdout isn't a TTY).
"""
from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from axon.cli._json_output import report_to_json
from axon.cli._multi_file import AggregateReport, FileResult, run
from axon.cli.display import safe_text


# ── ANSI colors (mirror of check_cmd) ───────────────────────────


_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _c(text: str, code: str, *, no_color: bool = False) -> str:
    text = safe_text(text, sys.stdout)
    if no_color or not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


# ── exit codes ──────────────────────────────────────────────────


def _exit_code(report: AggregateReport) -> int:
    """Combine per-class statuses into a single shell exit code.

    Bit 0 = parse errors present, Bit 1 = I/O errors present.
    Result is in {0, 1, 2, 3}. Adopters scripting `axon parse` can
    branch on the bits if they want to distinguish failure modes.
    """
    code = 0
    if report.files_with_errors > 0:
        code |= 1
    if report.files_with_io_error > 0:
        code |= 2
    return code


# ── rendering ───────────────────────────────────────────────────


def _print_file_block(fr: FileResult, *, no_color: bool) -> None:
    """Render a single file's diagnostic block — header + errors."""
    if fr.io_error is not None:
        print(
            _c(f"✗ {fr.path}", _RED + _BOLD, no_color=no_color)
            + _c(f"  — I/O error: {fr.io_error}", _RED, no_color=no_color),
            file=sys.stderr,
        )
        return
    if not fr.parse_errors:
        print(
            _c(f"✓ {fr.path}", _GREEN + _BOLD, no_color=no_color)
            + _c("  — clean", _DIM, no_color=no_color)
        )
        return
    n = len(fr.parse_errors)
    print(
        _c(f"✗ {fr.path}", _RED + _BOLD, no_color=no_color)
        + _c(f"  — {n} error(s)", _RED, no_color=no_color)
    )
    for err in fr.parse_errors:
        # The error already carries a SourceSnippet (28.d) when
        # the parser was constructed with `source=` — `str(err)`
        # renders the rustc-style block.
        text = safe_text(str(err), sys.stdout)
        for line in text.splitlines():
            print(f"  {line}")


def _print_summary(report: AggregateReport, *, no_color: bool) -> None:
    """Footer block: corpus-wide totals + truncation note (D6)."""
    if report.is_clean:
        print(
            _c(
                f"\n✓ {report.files_clean} file(s) parsed cleanly",
                _GREEN + _BOLD,
                no_color=no_color,
            )
        )
        return
    parts: list[str] = []
    parts.append(f"{report.files_clean} clean")
    if report.files_with_errors:
        parts.append(f"{report.files_with_errors} with errors")
    if report.files_with_io_error:
        parts.append(f"{report.files_with_io_error} unreadable")
    summary = ", ".join(parts)
    print(
        _c(
            f"\n✗ {summary} ({report.total_errors} total error(s))",
            _RED + _BOLD,
            no_color=no_color,
        )
    )
    if report.truncated:
        print(
            _c(
                "  — output truncated by --max-errors; rerun with a "
                "larger cap to see the rest",
                _YELLOW,
                no_color=no_color,
            )
        )


# ── entry point ─────────────────────────────────────────────────


def cmd_parse(args: Namespace) -> int:
    """Execute the ``axon parse`` subcommand."""
    no_color = getattr(args, "no_color", False)
    patterns: list[str] = list(args.patterns or [])
    if not patterns:
        print(
            _c(
                "axon parse: at least one path / pattern required",
                _RED,
                no_color=no_color,
            ),
            file=sys.stderr,
        )
        return 2

    ignore: list[str] = list(getattr(args, "ignore", None) or ())
    max_errors: int | None = getattr(args, "max_errors", None)
    jobs: int | None = getattr(args, "jobs", None)
    json_mode: bool = getattr(args, "json", False)
    json_format: str = getattr(args, "format", "array")

    report = run(
        patterns,
        ignore_patterns=ignore,
        max_errors=max_errors,
        max_workers=jobs,
    )

    # §Fase 28.g — JSON mode short-circuits human-friendly rendering.
    # No-match condition still emits valid JSON (empty array / empty
    # ndjson) so tooling consuming the pipe never sees a half-formed
    # response. The `--no-color` and stderr "no .axon files matched"
    # warnings are suppressed in JSON mode for the same reason.
    if json_mode:
        sys.stdout.write(report_to_json(report, format=json_format))
        # ndjson already ends with `\n`; array doesn't — add one for
        # POSIX-tool friendliness in either case.
        if json_format != "ndjson":
            sys.stdout.write("\n")
        return _exit_code(report)

    if report.files_seen == 0:
        print(
            _c(
                "axon parse: no .axon files matched the given pattern(s)",
                _YELLOW,
                no_color=no_color,
            ),
            file=sys.stderr,
        )
        return 0

    for fr in report.results:
        _print_file_block(fr, no_color=no_color)
    _print_summary(report, no_color=no_color)
    return _exit_code(report)
