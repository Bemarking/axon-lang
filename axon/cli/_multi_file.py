"""§Fase 28.f — Multi-file aggregator core.

Pure module (no argparse, no stdout) so the file-walking + parse +
aggregation logic is fully testable. The CLI subcommand
`axon parse <pattern> ...` wraps this module — see
`axon/cli/parse_cmd.py`.

Adopters with substantial `.axon` codebases (Kivi-style migration
hits 30+ files) want one pass that surfaces every diagnostic across
the whole corpus rather than one-error-per-deploy. 28.f delivers
that pass; per-file errors come out of the recovery-mode parser
(28.b) decorated with the rustc-style source-context block (28.d)
and smart-suggest hints (28.e).

D6 ratified 2026-05-10: no default cap on the number of errors
reported. The CLI exposes `--max-errors N` as an opt-in cap when
adopters are running against a noisy corpus.

Public API:

    collect_paths(patterns, *, root, ignore_patterns) -> list[Path]
        Resolve `patterns` (file paths, directories, glob patterns)
        into a sorted list of `.axon` files. Respects ignore.

    parse_files_concurrent(paths, *, max_workers) -> list[FileResult]
        Parse each path in a thread pool using
        `Parser(source=...).parse_with_recovery()`. Order of
        returned results matches input order.

    aggregate(results, *, max_errors) -> AggregateReport
        Roll up per-file results into a corpus-wide report,
        applying the optional max-errors cap.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from axon.compiler.errors import AxonLexerError, AxonParseError
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# §Fase 28.f — Default file extension. Adopters can pass explicit
# paths to override (`axon parse foo.txt`), but glob/directory walks
# only pick up `.axon` files automatically.
_AXON_EXTENSION: str = ".axon"


# §Fase 28.f — Default ignore-file name. If a directory contains an
# `.axonignore` file, its patterns are loaded and applied to every
# file discovered under that directory.
_AXONIGNORE_NAME: str = ".axonignore"


# §Fase 28.f — Built-in directory exclusions. These are always
# skipped during recursive walks regardless of `.axonignore`. Adopters
# never want their `.git` history or build artifacts parsed.
_BUILT_IN_IGNORES: tuple[str, ...] = (
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "node_modules",
    "__pycache__",
    "target",
    "dist", "build",
)


@dataclass(frozen=True)
class FileResult:
    """Outcome of parsing a single file in the multi-file pass.

    Exactly one of `io_error` or `parse_errors` is meaningful at a
    time:

      * `io_error` is non-None when the file couldn't be read
        (permission denied, encoding error, etc.). `parse_errors` is
        empty in that case — we never even reached the parser.
      * `io_error` is None when the file was read; `parse_errors`
        holds every error the recovery-mode parser collected (empty
        list = clean parse).
    """

    path: Path
    parse_errors: tuple[AxonParseError, ...] = ()
    io_error: str | None = None

    @property
    def is_clean(self) -> bool:
        return self.io_error is None and not self.parse_errors

    @property
    def has_errors(self) -> bool:
        return self.io_error is not None or bool(self.parse_errors)


@dataclass
class AggregateReport:
    """Corpus-wide roll-up of per-file results.

    Returned by `aggregate()`. Adopters consume this to render the
    summary block at the end of `axon parse`. The `truncated` flag
    tells the CLI whether `--max-errors` cut the report short, so it
    can print a "showing N of M errors" footer.
    """

    files_seen: int = 0
    files_clean: int = 0
    files_with_errors: int = 0
    files_with_io_error: int = 0
    total_errors: int = 0
    truncated: bool = False
    results: list[FileResult] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.files_with_errors == 0 and self.files_with_io_error == 0


# ── path collection ────────────────────────────────────────────────


def collect_paths(
    patterns: list[str],
    *,
    root: Path | None = None,
    ignore_patterns: list[str] | None = None,
) -> list[Path]:
    """Resolve adopter-supplied patterns to a sorted list of `.axon` files.

    `patterns` accepts any of:
      * A direct file path: ``foo.axon`` — taken verbatim regardless
        of extension (adopters may rename files; if they explicitly
        named one, parse it).
      * A directory: ``src/`` — recursively walks all `.axon` files
        under it.
      * A glob: ``"src/**/*.axon"`` — expanded relative to ``root``.

    `root` defaults to the current working directory and is the base
    against which relative globs and directories are resolved.

    Ignore patterns combine three sources:
      * Built-in directory ignores (`.git`, `node_modules`, etc.).
      * `.axonignore` files found in `root` or in any directory
        encountered during a recursive walk.
      * Caller-supplied `ignore_patterns` (CLI `--ignore` flag).

    Returns a deterministic, alphabetically-sorted list with each
    path appearing at most once. Empty patterns produce an empty
    result without raising — the CLI prints "no files matched".
    """
    if root is None:
        root = Path.cwd()
    extra_ignores = list(ignore_patterns or ())

    # Combine built-in dir ignores + adopter-supplied glob ignores +
    # any `.axonignore` in `root`.
    file_ignores = list(extra_ignores)
    root_ignore_file = root / _AXONIGNORE_NAME
    if root_ignore_file.is_file():
        file_ignores.extend(_load_axonignore(root_ignore_file))

    seen: set[Path] = set()
    out: list[Path] = []

    for pattern in patterns:
        candidate = (root / pattern) if not Path(pattern).is_absolute() else Path(pattern)
        # Direct file: keep regardless of extension. Adopters who
        # explicitly name a file want it parsed.
        if candidate.is_file():
            _add_unique(candidate.resolve(), seen, out, file_ignores, root)
            continue

        if candidate.is_dir():
            _walk_dir(candidate, seen, out, file_ignores, root)
            continue

        # Treat as a glob. `Path.glob` is the relative form; for
        # absolute patterns we fall back to splitting & globbing.
        for hit in _expand_glob(pattern, root):
            if hit.is_file():
                _add_unique(hit.resolve(), seen, out, file_ignores, root)

    out.sort()
    return out


def _add_unique(
    path: Path,
    seen: set[Path],
    out: list[Path],
    ignores: list[str],
    root: Path,
) -> None:
    """Append `path` to `out` if not already seen and not ignored."""
    if path in seen:
        return
    if _is_ignored(path, ignores, root):
        return
    seen.add(path)
    out.append(path)


def _walk_dir(
    directory: Path,
    seen: set[Path],
    out: list[Path],
    ignores: list[str],
    root: Path,
) -> None:
    """Recursively collect `.axon` files under `directory`.

    Built-in directory ignores apply at every level (`.git`,
    `node_modules`, etc.). Each subdirectory's `.axonignore` is
    loaded and applied to descendants; patterns there cascade down,
    not up.
    """
    local_ignores = list(ignores)
    nested_ignore = directory / _AXONIGNORE_NAME
    if nested_ignore.is_file():
        local_ignores.extend(_load_axonignore(nested_ignore))

    for entry in sorted(directory.iterdir()):
        name = entry.name
        if entry.is_dir():
            if name in _BUILT_IN_IGNORES:
                continue
            if _is_ignored(entry, local_ignores, root):
                continue
            _walk_dir(entry, seen, out, local_ignores, root)
            continue
        if not entry.is_file():
            continue
        if entry.suffix != _AXON_EXTENSION:
            continue
        _add_unique(entry.resolve(), seen, out, local_ignores, root)


def _expand_glob(pattern: str, root: Path) -> list[Path]:
    """Expand `pattern` to concrete paths relative to `root`.

    Supports the same shape as `pathlib.Path.glob` including the
    `**` recursive wildcard.
    """
    p = Path(pattern)
    if p.is_absolute():
        # Split anchor + relative remainder; glob from anchor.
        anchor = Path(p.anchor)
        rel = p.relative_to(p.anchor)
        return list(anchor.glob(str(rel)))
    return list(root.glob(pattern))


def _load_axonignore(path: Path) -> list[str]:
    """Read an `.axonignore` file into a list of fnmatch patterns.

    Comments (`#`-prefixed lines) and blank lines are stripped.
    Trailing whitespace is preserved (filenames may legitimately
    end in spaces — let `fnmatch` handle the literal match).
    """
    patterns: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _is_ignored(path: Path, patterns: list[str], root: Path) -> bool:
    """Return True if `path` matches any of the ignore `patterns`.

    A pattern matches against:
      * the full absolute path string,
      * the path relative to `root`,
      * the basename.

    This mirrors gitignore's "any-segment" matching well enough for
    the adopter-facing surface without pulling in a full gitignore
    library.
    """
    if not patterns:
        return False
    abs_str = str(path)
    name = path.name
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = abs_str
    for pat in patterns:
        if fnmatch(name, pat) or fnmatch(rel, pat) or fnmatch(abs_str, pat):
            return True
    return False


# ── parse + aggregate ──────────────────────────────────────────────


def _parse_one(path: Path) -> FileResult:
    """Parse a single file; never raise — package errors into FileResult.

    Threads share this entry point. `AxonLexerError` is converted
    into a synthetic `AxonParseError` so the per-file error list has
    a uniform type — adopters see a unified diagnostic stream
    regardless of whether the failure was lexical or grammatical.
    OS-level read failures become `io_error` strings.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return FileResult(path=path, io_error=f"{exc.__class__.__name__}: {exc}")
    except UnicodeDecodeError as exc:
        return FileResult(path=path, io_error=f"UnicodeDecodeError: {exc}")

    try:
        tokens = Lexer(source).tokenize()
    except AxonLexerError as exc:
        # Lexer error masquerading as a parse error so the unified
        # report shape applies. The adopter still sees the original
        # message + line/col + (best-effort) source-context block
        # via the parse-error attach plumbing from 28.d.
        synthetic = AxonParseError(
            str(exc.message),
            line=exc.line,
            column=exc.column,
        )
        synthetic.attach_source(source, str(path))
        return FileResult(path=path, parse_errors=(synthetic,))

    parser = Parser(tokens, source=source, filename=str(path))
    result = parser.parse_with_recovery()
    return FileResult(path=path, parse_errors=tuple(result.errors))


def parse_files_concurrent(
    paths: list[Path],
    *,
    max_workers: int | None = None,
) -> list[FileResult]:
    """Parse `paths` in a thread pool; return results in input order.

    Threads are appropriate here because each parse is CPU-bound but
    file I/O dominates startup; the GIL doesn't hurt much in
    practice. `max_workers=None` lets the executor pick a sensible
    default (Python 3.13: `min(32, os.cpu_count() + 4)`).

    Empty `paths` returns an empty list without spinning up the
    pool.
    """
    if not paths:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_parse_one, paths))


def aggregate(
    results: list[FileResult],
    *,
    max_errors: int | None = None,
) -> AggregateReport:
    """Roll up per-file results into a corpus-wide report.

    `max_errors` (D6 ratified): when non-None, the report stops
    accumulating into `results` once the running total of
    parse-errors crosses the cap. Files counted before the cap hit
    keep their full error lists; the truncation flag signals the
    CLI to print a "showing N of M errors" footer. Files BEYOND the
    cap aren't included in `results` at all so the CLI doesn't
    render them.
    """
    report = AggregateReport()
    accumulated_errors = 0
    for fr in results:
        report.files_seen += 1
        if fr.io_error is not None:
            report.files_with_io_error += 1
            report.results.append(fr)
            continue
        if not fr.parse_errors:
            report.files_clean += 1
            report.results.append(fr)
            continue
        # File has parse errors. Apply the cap.
        if max_errors is None:
            report.results.append(fr)
            report.files_with_errors += 1
            accumulated_errors += len(fr.parse_errors)
            report.total_errors = accumulated_errors
            continue
        remaining = max_errors - accumulated_errors
        if remaining <= 0:
            report.truncated = True
            # Don't include this file or any subsequent erroring
            # files. Continue scanning so files_seen still reflects
            # the full corpus.
            continue
        if len(fr.parse_errors) <= remaining:
            report.results.append(fr)
            report.files_with_errors += 1
            accumulated_errors += len(fr.parse_errors)
            report.total_errors = accumulated_errors
            continue
        # Partial inclusion — keep the first `remaining` errors
        # from this file, mark truncated.
        clipped = FileResult(
            path=fr.path,
            parse_errors=fr.parse_errors[:remaining],
            io_error=None,
        )
        report.results.append(clipped)
        report.files_with_errors += 1
        accumulated_errors += remaining
        report.total_errors = accumulated_errors
        report.truncated = True
    return report


def run(
    patterns: list[str],
    *,
    root: Path | None = None,
    ignore_patterns: list[str] | None = None,
    max_errors: int | None = None,
    max_workers: int | None = None,
) -> AggregateReport:
    """Top-level convenience: collect → parse-concurrent → aggregate.

    The CLI subcommand calls this and renders the report. Tests can
    call it directly with a list of literal paths/patterns.
    """
    paths = collect_paths(patterns, root=root, ignore_patterns=ignore_patterns)
    results = parse_files_concurrent(paths, max_workers=max_workers)
    return aggregate(results, max_errors=max_errors)


# ── §Fase 28.h — strict (fail-on-first) mode ───────────────────────


def _parse_one_strict(path: Path) -> FileResult:
    """Strict-mode single-file parser.

    Uses the legacy fail-fast `Parser.parse()` API instead of
    `parse_with_recovery()`. The first error is captured into a
    1-element `parse_errors` tuple — same `FileResult` shape as
    the recovery path so `aggregate()` and rendering work
    unchanged.

    Adopters opt into this via `--strict` / `AXON_PARSER_STRICT=1`
    when they want the legacy v1.19.x behavior (one diagnostic per
    file maximum, fail the build on the first issue).
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return FileResult(path=path, io_error=f"{exc.__class__.__name__}: {exc}")
    except UnicodeDecodeError as exc:
        return FileResult(path=path, io_error=f"UnicodeDecodeError: {exc}")

    try:
        tokens = Lexer(source).tokenize()
    except AxonLexerError as exc:
        synthetic = AxonParseError(
            str(exc.message),
            line=exc.line,
            column=exc.column,
        )
        synthetic.attach_source(source, str(path))
        return FileResult(path=path, parse_errors=(synthetic,))

    parser = Parser(tokens, source=source, filename=str(path))
    try:
        parser.parse()
    except AxonParseError as e:
        return FileResult(path=path, parse_errors=(e,))
    return FileResult(path=path)


def run_strict(
    patterns: list[str],
    *,
    root: Path | None = None,
    ignore_patterns: list[str] | None = None,
) -> AggregateReport:
    """Strict-mode top-level entry point.

    Walks files in deterministic order and parses each with the
    fail-fast `Parser.parse()` API. Stops at the FIRST file that
    surfaces a parse error: subsequent files in the corpus are not
    parsed, and the report's `truncated` flag is set so the CLI
    can print the "remaining files skipped" footer.

    The single-thread sequential walk is intentional in strict
    mode — we don't want a concurrent worker to over-read past the
    first error and waste work, and adopter expectation under
    strict mode is "halt at first failure" with zero ambiguity
    about which file tripped the build.

    `max_errors` is intentionally not exposed for strict mode —
    strict mode caps at exactly 1 error by definition. `max_workers`
    is also omitted because the walk is sequential.
    """
    paths = collect_paths(patterns, root=root, ignore_patterns=ignore_patterns)
    report = AggregateReport()
    halted = False
    for path in paths:
        if halted:
            # Don't parse remaining files; report.files_seen still
            # reflects the full corpus discovery for the summary.
            report.files_seen += 1
            continue
        report.files_seen += 1
        fr = _parse_one_strict(path)
        if fr.io_error is not None:
            report.files_with_io_error += 1
            report.results.append(fr)
            halted = True
            report.truncated = len(paths) - report.files_seen > 0
            continue
        if fr.parse_errors:
            report.files_with_errors += 1
            report.total_errors = 1
            report.results.append(fr)
            halted = True
            report.truncated = len(paths) - report.files_seen > 0
            continue
        report.files_clean += 1
        report.results.append(fr)
    return report
