"""structlog configuration — JSON to stdout, ContextVar-aware correlation.

Correlation keys (``tenant_id``, ``user_id``, ``request_id``, ``trace_id``)
are bound into every log line via ``contextvars``. The ASGI middleware
sets them on request entry; downstream services read them implicitly
without having to call ``logger.bind(tenant_id=...)`` every time.

Output destinations
-------------------
- stdout (JSON) in production — K8s logs pick this up, fluentd /
  vector / stern parse it without regex
- console (coloured pretty-print) in dev — operator-friendly

Never logs plaintext secrets — ``SecretValue`` from 10.f already
redacts itself in ``repr`` / ``str``, so any ``SecretValue`` passed
as a log kwarg surfaces as ``<SecretValue len=N fingerprint=...>``.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from typing import Any

import structlog

from axon_enterprise.config import ObservabilitySettings, get_settings

# ── Correlation ContextVars ──────────────────────────────────────────
#
# These are independent from ``CURRENT_TENANT`` / ``CURRENT_PRINCIPAL``
# because the logging layer must not hard-depend on the identity
# layer (it needs to work even during startup, before the request
# pipeline is wired).

_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "axon.log_context", default={}
)


def set_log_context(**kwargs: Any) -> contextvars.Token[dict[str, Any]]:
    """Overlay new keys onto the current log context.

    Returns the ContextVar token so callers can ``reset`` on exit
    (``finally: _LOG_CONTEXT.reset(token)``). The middleware uses
    this to scope a request's correlation keys to that request's
    task tree.
    """
    merged = {**_LOG_CONTEXT.get(), **kwargs}
    return _LOG_CONTEXT.set(merged)


def clear_log_context() -> None:
    """Replace the context with an empty dict. Used at process startup."""
    _LOG_CONTEXT.set({})


def _merge_contextvars(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor: inject contextvars into every log record."""
    ctx = _LOG_CONTEXT.get()
    for key, value in ctx.items():
        event_dict.setdefault(key, value)
    return event_dict


# ── Configuration ─────────────────────────────────────────────────────


def configure_logging(settings: ObservabilitySettings | None = None) -> None:
    """Wire structlog + stdlib logging once at process startup.

    Safe to call multiple times — reconfiguration replaces the
    existing setup atomically.
    """
    s = settings or get_settings().observability

    level = getattr(logging, s.log_level, logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if s.log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True, pad_event=30)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.WriteLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Fetch a logger — equivalent to ``structlog.get_logger(name)``.

    Kept as a thin wrapper so callers only import from
    ``axon_enterprise.observability`` and we can swap the underlying
    library in a future fase without touching every call site.
    """
    return structlog.get_logger(name) if name else structlog.get_logger()
