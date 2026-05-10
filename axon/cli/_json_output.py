"""§Fase 28.g — Structured JSON output for parser diagnostics.

D5 ratified 2026-05-10: rustc-compatible at the field level. The
field names (`message`, `severity`, `code`, `spans`, `line_start`,
`line_end`, `column_start`, `column_end`, `file_name`, `is_primary`,
`label`, `source_text`, `children`) and value shapes mirror
``rustc --error-format=json`` exactly so adopter tooling that
already consumes Rust compiler output (or that maps from rustc
JSON to LSP `Diagnostic`) works against ``axon parse --json``
without code changes.

# Output formats

The CLI supports two `--format` values:

  * ``array`` (default) — emits a single JSON array. Easiest for
    "give me the whole report at once" CI integrations and `jq`
    pipelines.
  * ``ndjson`` — emits one JSON object per line, no enclosing
    array. Streaming-friendly for IDE / LSP servers reading the
    pipe incrementally.

Both formats serialize the same per-diagnostic shape — only the
framing differs.

# LSP mapping

The shape maps cleanly to LSP `Diagnostic`:

    range:    {start, end} ← line_start/column_start, line_end/column_end
    severity: 1=Error, 2=Warning, 3=Info, 4=Hint
    code:     code field (string)
    source:   "axon-lang"
    message:  message field (verbatim)

Adopters writing an LSP wrapper can build the LSP frame in ~20
lines on top of this shape — no other transformation required.

# Stack scope

Python-only. The Rust frontend (`axon-frontend`) is a library, not
a CLI; its consumers (axon-rs runtime, axon-lsp server) construct
their own diagnostic frames from the structured `ParseError`
shape directly. The cross-stack drift gate (28.i) compares the
structured field shape, not the JSON serialization, so this
module's surface stays intentionally Python-only.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from axon.cli._multi_file import AggregateReport, FileResult
from axon.compiler.errors import AxonParseError, SourceSnippet


# §Fase 28.g — Severity strings. rustc emits `error`, `warning`,
# `note`, `help`, `failure-note`. Parser diagnostics are always
# errors at this layer; type-checker diagnostics (which may be
# warnings) flow through `axon check` not `axon parse`. We pin
# the constant here so the wire format stays stable.
_SEVERITY_ERROR: str = "error"


# §Fase 28.g — Diagnostic code. Single code for now (parser-level
# error). Future sub-fases may split into AXON_PARSE_E0001 ...
# style codes once we have a code-registry doc; until then a
# single canonical string is the honest signal.
_CODE_PARSE_ERROR: str = "AXON_PARSE_ERROR"


# §Fase 28.g — Source identifier. Field appears in both rustc and
# LSP serializations and lets adopter tooling distinguish AXON
# diagnostics from sibling tools in a unified output stream.
_SOURCE_LABEL: str = "axon-lang"


def _span_from_snippet(snippet: SourceSnippet) -> dict[str, Any]:
    """Build the rustc-compatible span object from a SourceSnippet.

    The span carries the line / column window the diagnostic refers
    to plus the `source_text` lines for adopter-side rendering.
    `is_primary` is True because every parser error has exactly one
    location at this layer (no secondary spans in 28.g).
    """
    source_text_lines: list[str] = []
    if snippet.source:
        all_lines = snippet.source.splitlines()
        if all_lines and snippet.line >= 1:
            line_idx = snippet.line
            start = max(1, line_idx - snippet.context_before)
            end = min(len(all_lines), line_idx + snippet.context_after)
            source_text_lines = all_lines[start - 1:end]
    return {
        "file_name": snippet.filename,
        "line_start": snippet.line,
        "line_end": snippet.line,
        "column_start": snippet.column,
        "column_end": snippet.column,
        "is_primary": True,
        "label": None,
        "source_text": source_text_lines,
    }


def _span_from_bare(
    err: AxonParseError,
    *,
    file_name: str,
) -> dict[str, Any]:
    """Build a span when the error has no source snippet attached.

    Adopters who consume the JSON without ever calling
    `Parser(source=...)` still get a usable shape: line/col are
    populated, `source_text` is an empty array. The CLI
    (`parse_cmd.py`) always attaches snippets via the multi-file
    aggregator so this branch is for pure-API consumers.
    """
    return {
        "file_name": file_name,
        "line_start": err.line,
        "line_end": err.line,
        "column_start": err.column,
        "column_end": err.column,
        "is_primary": True,
        "label": None,
        "source_text": [],
    }


def error_to_json(
    err: AxonParseError,
    *,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Convert an `AxonParseError` to a rustc-compatible JSON dict.

    `file_name` falls back to the error's attached snippet filename
    when not supplied. When neither is available, the field defaults
    to ``"<source>"`` so the output never has a missing required key.

    The returned dict is JSON-serializable as-is; downstream callers
    pass it through ``json.dumps`` with the framing they need.
    """
    snippet = err.source_snippet
    if snippet is not None:
        span = _span_from_snippet(snippet)
        if file_name is not None:
            span["file_name"] = file_name
    else:
        resolved_name = file_name if file_name is not None else "<source>"
        span = _span_from_bare(err, file_name=resolved_name)

    return {
        "severity": _SEVERITY_ERROR,
        "code": _CODE_PARSE_ERROR,
        "source": _SOURCE_LABEL,
        "message": err.message,
        "spans": [span],
        "children": [],
    }


def file_result_to_json(fr: FileResult) -> list[dict[str, Any]]:
    """Convert a `FileResult` to a list of diagnostic dicts.

    Empty result for clean files. I/O errors emit a single synthetic
    diagnostic (`code = "AXON_IO_ERROR"`) so adopters consuming the
    JSON stream see one entry per problem regardless of whether the
    failure was lexical / grammatical / I/O.
    """
    if fr.io_error is not None:
        return [
            {
                "severity": _SEVERITY_ERROR,
                "code": "AXON_IO_ERROR",
                "source": _SOURCE_LABEL,
                "message": fr.io_error,
                "spans": [
                    {
                        "file_name": str(fr.path),
                        "line_start": 0,
                        "line_end": 0,
                        "column_start": 0,
                        "column_end": 0,
                        "is_primary": True,
                        "label": None,
                        "source_text": [],
                    }
                ],
                "children": [],
            }
        ]
    return [
        error_to_json(err, file_name=str(fr.path))
        for err in fr.parse_errors
    ]


def diagnostics_iter(report: AggregateReport) -> Iterable[dict[str, Any]]:
    """Yield diagnostic dicts in source-order across the corpus.

    Iteration order matches the file order in `report.results`,
    and within each file follows the parser's emission order
    (already source-order per 28.b).
    """
    for fr in report.results:
        for diag in file_result_to_json(fr):
            yield diag


# §Fase 28.g — Format names. Pinned as constants so the CLI can
# also expose them via `argparse` `choices=`.
FORMAT_ARRAY: str = "array"
FORMAT_NDJSON: str = "ndjson"
SUPPORTED_FORMATS: tuple[str, ...] = (FORMAT_ARRAY, FORMAT_NDJSON)


def report_to_json(
    report: AggregateReport,
    *,
    format: str = FORMAT_ARRAY,
    indent: int | None = None,
) -> str:
    """Serialize a corpus-wide report to a JSON string.

    `format`:
      * `"array"` — single JSON array of diagnostic objects.
      * `"ndjson"` — one diagnostic per line, no enclosing array.
        Trailing newline so the last record is a complete line.

    `indent`: passed straight to ``json.dumps``. ``None`` produces
    compact output; integers (e.g. ``2``) produce pretty-printed
    JSON. Ignored for `ndjson` (each line is a single compact
    object regardless).

    Empty reports produce ``"[]"`` for array format and ``""`` for
    ndjson — both are valid and idempotent under repeated parsing.
    """
    if format == FORMAT_NDJSON:
        lines = [json.dumps(d, ensure_ascii=False) for d in diagnostics_iter(report)]
        return "\n".join(lines) + ("\n" if lines else "")
    if format == FORMAT_ARRAY:
        return json.dumps(
            list(diagnostics_iter(report)),
            ensure_ascii=False,
            indent=indent,
        )
    raise ValueError(
        f"unknown format {format!r}; expected one of {SUPPORTED_FORMATS}"
    )


# ── LSP mapping helper ────────────────────────────────────────────
#
# Convenience that maps a single rustc-shape diagnostic dict to the
# LSP `Diagnostic` frame. Not used by the CLI itself; provided so
# adopters writing an axon-lang LSP wrapper can call this directly
# without re-implementing the trivial mapping.


def to_lsp_diagnostic(diag: dict[str, Any]) -> dict[str, Any]:
    """Convert a 28.g diagnostic dict to an LSP `Diagnostic` dict.

    Returns the LSP shape:

        {
          "range": {
            "start": {"line": <0-based>, "character": <0-based>},
            "end":   {"line": <0-based>, "character": <0-based>}
          },
          "severity": <1=Error / 2=Warning / 3=Info / 4=Hint>,
          "code": <string>,
          "source": <string>,
          "message": <string>
        }

    Note line/col 0-base conversion: AXON parser emits 1-based line
    and 1-based column (matches rustc + most adopter tooling). LSP
    is 0-based for both, so we subtract 1. A 0-value input produces
    a -1 output, which most LSP clients clamp gracefully — but we
    clamp it ourselves to 0 to avoid the ambiguity.
    """
    primary = next(
        (s for s in diag.get("spans", []) if s.get("is_primary")),
        None,
    )
    line_start = primary["line_start"] if primary else 0
    column_start = primary["column_start"] if primary else 0
    line_end = primary["line_end"] if primary else 0
    column_end = primary["column_end"] if primary else 0

    def _to_zero_based(n: int) -> int:
        return max(0, n - 1)

    severity_map = {"error": 1, "warning": 2, "note": 3, "help": 4}
    return {
        "range": {
            "start": {
                "line": _to_zero_based(line_start),
                "character": _to_zero_based(column_start),
            },
            "end": {
                "line": _to_zero_based(line_end),
                "character": _to_zero_based(column_end),
            },
        },
        "severity": severity_map.get(diag.get("severity", "error"), 1),
        "code": diag.get("code", ""),
        "source": diag.get("source", _SOURCE_LABEL),
        "message": diag.get("message", ""),
    }
