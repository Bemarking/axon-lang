"""Decorators that wire spans + metrics around service methods.

Typical usage:

    @instrument("rbac.check", metric=RBAC_CHECKS_TOTAL)
    async def check(self, db, *, user_id, tenant_id, permission):
        ...

The decorator opens an OTel span named ``rbac.check``, records the
duration into the provided histogram (optional), and increments
the counter on success / failure. Exceptions are recorded on the
span with ``Status.ERROR`` then re-raised.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable
from typing import Any, Callable, TypeVar

from prometheus_client import Counter, Histogram

from axon_enterprise.observability.tracing import get_tracer

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def instrument(
    span_name: str,
    *,
    counter: Counter | None = None,
    histogram: Histogram | None = None,
) -> Callable[[F], F]:
    """Wrap an async function with span + metrics.

    ``counter`` is incremented once per call with label
    ``outcome='success'|'error'`` — the caller is expected to
    declare a counter whose labelnames include ``outcome``.
    ``histogram`` observes the call's duration in seconds.
    """

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(span_name.split(".", 1)[0])
            started = time.perf_counter()
            outcome = "success"
            with tracer.start_as_current_span(span_name) as span:
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    outcome = "error"
                    span.record_exception(exc)
                    raise
                finally:
                    elapsed = time.perf_counter() - started
                    if histogram is not None:
                        histogram.observe(elapsed)
                    if counter is not None:
                        try:
                            counter.labels(outcome=outcome).inc()
                        except Exception:  # noqa: BLE001
                            # Metric label mismatch — log but never break
                            # the wrapped function.
                            pass

        return wrapper  # type: ignore[return-value]

    return wrap
