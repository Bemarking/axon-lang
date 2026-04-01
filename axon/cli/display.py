from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO


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