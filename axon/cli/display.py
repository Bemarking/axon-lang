from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO


_ASCII_FALLBACKS = {
    "✓": "OK",
    "✗": "X",
    "→": "->",
    "═": "=",
    "┌": "+",
    "└": "`",
    "│": "|",
    "─": "-",
}


def format_cli_path(path: str | Path) -> str:
    """Return a stable, shell-friendly path for CLI messages.

    The observable CLI contract should not vary with the host OS path
    separator, so paths are rendered using forward slashes.
    """
    return os.fspath(path).replace("\\", "/")


def supports_text(stream: TextIO, text: str) -> bool:
    """Return whether *stream* can encode *text* without replacement."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return False
    except LookupError:
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            return False
    return True


def safe_text(text: str, stream: TextIO) -> str:
    """Return *text* unchanged when encodable, else downgraded to ASCII."""
    if supports_text(stream, text):
        return text

    for source, replacement in _ASCII_FALLBACKS.items():
        text = text.replace(source, replacement)

    return text