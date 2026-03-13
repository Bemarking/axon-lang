"""
AXON Runtime — Real Backends Package
======================================
Production-ready tool implementations that replace Phase 4 stubs.

Each backend inherits from ``BaseTool``, sets ``IS_STUB = False``,
and makes real I/O calls (HTTP APIs, filesystem, subprocess).

Call ``register_all_backends(registry)`` to load all backends
whose dependencies are satisfied (checked at import time).

Quick start::

    from axon.runtime.tools import create_default_registry

    registry = create_default_registry(mode="real")  # loads real backends
"""

from __future__ import annotations

import logging
import os
from typing import Any

from axon.runtime.tools.registry import RuntimeToolRegistry

logger = logging.getLogger(__name__)


def register_all_backends(
    registry: RuntimeToolRegistry,
    *,
    config: dict[str, Any] | None = None,
) -> None:
    """Register all available real backend implementations.

    Tools whose required dependencies or API keys are missing
    are skipped with a warning.  Stubs for those tools remain
    in effect if the registry was pre-loaded with
    ``register_all_stubs()``.

    Args:
        registry: The tool registry to populate.
        config:   Optional global config dict.  If ``None``,
                  keys are read from environment variables.
    """
    cfg = config or {}

    # ── WebSearch: Serper.dev ─────────────────────────────────
    serper_key = cfg.get("serper_api_key") or os.getenv("SERPER_API_KEY")
    if serper_key:
        try:
            from axon.runtime.tools.backends.web_search_serper import (
                WebSearchSerper,
            )

            registry.register(WebSearchSerper)
            logger.info("Registered backend: WebSearch (Serper.dev)")
        except ImportError:
            logger.warning(
                "WebSearchSerper unavailable — install httpx: "
                "pip install httpx"
            )
    else:
        logger.info(
            "WebSearch backend skipped — no SERPER_API_KEY found. "
            "Get one at: https://serper.dev/"
        )

    # ── FileReader: Local filesystem ─────────────────────────
    from axon.runtime.tools.backends.file_reader_local import (
        FileReaderLocal,
    )

    registry.register(FileReaderLocal)
    logger.info("Registered backend: FileReader (local)")

    # ── CodeExecutor: Subprocess ─────────────────────────────
    from axon.runtime.tools.backends.code_executor_subprocess import (
        CodeExecutorSubprocess,
    )

    registry.register(CodeExecutorSubprocess)
    logger.info("Registered backend: CodeExecutor (subprocess)")

    # ── APICall: httpx (v0.11.0 — W9) ───────────────────────
    try:
        from axon.runtime.tools.backends.api_call_httpx import (
            APICallHTTPX,
        )

        registry.register(APICallHTTPX)
        logger.info("Registered backend: APICall (httpx)")
    except ImportError:
        logger.info(
            "APICall backend skipped — install httpx: "
            "pip install httpx"
        )

    # ── PDFExtractor: PyMuPDF (v0.11.0 — W9) ────────────────
    try:
        from axon.runtime.tools.backends.pdf_extractor_pymupdf import (
            PDFExtractorPyMuPDF,
        )

        registry.register(PDFExtractorPyMuPDF)
        logger.info("Registered backend: PDFExtractor (PyMuPDF)")
    except ImportError:
        logger.info(
            "PDFExtractor backend skipped — install PyMuPDF: "
            "pip install PyMuPDF"
        )

    # ── Calculator & DateTime stay from stubs (already real) ─
    # CalculatorTool (IS_STUB=False) and DateTimeTool (IS_STUB=False)
    # are pre-registered by register_all_stubs() and are NOT
    # replaced here.  They are already production-ready wrappers
    # around the stdlib executors.
