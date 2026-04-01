"""
axon trace — Pretty-print a saved execution trace.

Reads a ``.trace.json`` file (produced by ``axon run --trace``)
and renders it as a human-readable timeline.

Exit codes:
  0 — success
  2 — file not found or invalid JSON
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, supports_text

# ── ANSI colors ──────────────────────────────────────────────────

_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"

_EVENT_COLORS: dict[str, str] = {
    "step_start": _CYAN,
    "step_end": _CYAN,
    "model_call": _MAGENTA,
    "model_response": _MAGENTA,
    "anchor_check": _YELLOW,
    "anchor_pass": _GREEN,
    "anchor_breach": _RED,
    "validation_pass": _GREEN,
    "validation_fail": _RED,
    "retry_attempt": _YELLOW,
    "refine_start": _YELLOW,
    "memory_read": _DIM,
    "memory_write": _DIM,
    "confidence_check": _CYAN,
}

_UNICODE_TRACE_THEME = {
    "rule": "═",
    "span_open": "┌─",
    "span_close": "└─",
    "event_prefix": "│",
}

_ASCII_TRACE_THEME = {
    "rule": "=",
    "span_open": "+-",
    "span_close": "`-",
    "event_prefix": "|",
}


def _c(text: str, code: str, *, no_color: bool = False) -> str:
    if no_color or not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def cmd_trace(args: Namespace) -> int:
    """Execute the ``axon trace`` subcommand."""
    path = Path(args.file)
    no_color = getattr(args, "no_color", False)

    if not path.exists():
        print(f"✗ File not found: {format_cli_path(path)}", file=sys.stderr)
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"✗ Invalid JSON: {exc}", file=sys.stderr)
        return 2

    _render_trace(data, no_color=no_color)
    return 0


def _render_trace(data: dict | list, *, no_color: bool) -> None:
    """Render a trace data structure to the terminal."""
    theme = _trace_theme()
    print()
    print(_c(theme["rule"] * 60, _BOLD, no_color=no_color))
    print(_c("  AXON Execution Trace", _BOLD, no_color=no_color))
    print(_c(theme["rule"] * 60, _BOLD, no_color=no_color))

    if isinstance(data, dict):
        _render_trace_dict(data, no_color=no_color, theme=theme)
    elif isinstance(data, list):
        _render_trace_list(data, no_color=no_color, theme=theme)

    print()
    print(_c(theme["rule"] * 60, _BOLD, no_color=no_color))


def _render_trace_dict(
    data: dict, *, no_color: bool, theme: dict[str, str]
) -> None:
    meta = data.get("_meta", data.get("meta", {}))
    if meta:
        _render_meta(meta, no_color=no_color)

    spans = data.get("spans", [])
    for span in spans:
        _render_span(span, indent=1, no_color=no_color, theme=theme)

    events = data.get("events", [])
    for event in events:
        _render_event(event, indent=1, no_color=no_color, theme=theme)

    if not spans and not events:
        _render_flat(data, indent=1, no_color=no_color)


def _render_trace_list(
    data: list, *, no_color: bool, theme: dict[str, str]
) -> None:
    for item in data:
        if isinstance(item, dict):
            _render_event(item, indent=1, no_color=no_color, theme=theme)
            continue
        print(f"  {item}")


def _render_meta(meta: dict, *, no_color: bool) -> None:
    print(
        _c("  source: ", _DIM, no_color=no_color)
        + format_cli_path(str(meta.get("source", "unknown")))
    )
    print(
        _c("  backend: ", _DIM, no_color=no_color)
        + str(meta.get("backend", "unknown"))
    )
    print()


def _render_span(
    span: dict,
    *,
    indent: int = 0,
    no_color: bool = False,
    theme: dict[str, str],
) -> None:
    """Render a trace span (named scope with children)."""
    prefix = "  " * indent
    name = span.get("name", "unnamed")
    duration = span.get("duration_ms", "")
    dur_str = f" ({duration}ms)" if duration else ""

    print(
        f"{prefix}{theme['span_open']} "
        f"{_c(name, _BOLD + _CYAN, no_color=no_color)}{dur_str}"
    )

    for event in span.get("events", []):
        _render_event(event, indent=indent + 1, no_color=no_color, theme=theme)

    for child in span.get("children", []):
        _render_span(child, indent=indent + 1, no_color=no_color, theme=theme)

    print(f"{prefix}{theme['span_close']}")


def _render_event(
    event: dict,
    *,
    indent: int = 0,
    no_color: bool = False,
    theme: dict[str, str],
) -> None:
    """Render a single trace event."""
    prefix = "  " * indent
    event_type = event.get("type", event.get("event_type", "unknown"))
    color = _EVENT_COLORS.get(event_type, "")
    data = event.get("data", {})
    ts_str = _render_timestamp(event)
    badge = _c(f"[{event_type}]", color + _BOLD, no_color=no_color)
    summary_text = _event_summary(data)
    summary = f"  {summary_text}" if summary_text else ""

    print(f"{prefix}{theme['event_prefix']} {ts_str}{badge}{summary}")

    if event_type in ("anchor_breach", "validation_fail", "retry_attempt"):
        _render_event_details(
            data,
            prefix=prefix,
            no_color=no_color,
            theme=theme,
        )


def _trace_theme() -> dict[str, str]:
    if supports_text(sys.stdout, "═┌└│"):
        return _UNICODE_TRACE_THEME
    return _ASCII_TRACE_THEME


def _render_timestamp(event: dict) -> str:
    timestamp = event.get("timestamp", "")
    return f"[{timestamp}] " if timestamp else ""


def _event_summary(data: dict) -> str:
    for key in ("step_name", "name", "message", "content", "reason"):
        if key in data:
            return _truncate(str(data[key]), 80)
    return ""


def _render_event_details(
    data: dict,
    *,
    prefix: str,
    no_color: bool,
    theme: dict[str, str],
) -> None:
    for key, value in data.items():
        if key in ("step_name", "name", "message"):
            continue
        print(
            f"{prefix}{theme['event_prefix']}   "
            f"{_c(key, _DIM, no_color=no_color)}: {_truncate(str(value), 60)}"
        )


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _render_flat(
    data: dict, *, indent: int = 0, no_color: bool = False
) -> None:
    """Render a dict as a simple key-value list."""
    prefix = "  " * indent
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            print(f"{prefix}{_c(key, _BOLD, no_color=no_color)}:")
            _render_flat(value, indent=indent + 1, no_color=no_color)
        elif isinstance(value, list):
            print(
                f"{prefix}{_c(key, _BOLD, no_color=no_color)}: "
                f"[{len(value)} items]"
            )
        else:
            print(f"{prefix}{_c(key, _DIM, no_color=no_color)}: {value}")
