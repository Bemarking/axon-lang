"""Version + build metadata endpoint — ``/version``.

Public, unauthenticated. Returns identifying information about the
running server: package versions, Python runtime, build SHA, build
date. Used by orchestrators, observability dashboards, and
post-deploy verification scripts to confirm what's actually live.

Build metadata sources:

- ``AXON_BUILD_SHA`` env var — set at container build time (e.g.,
  Docker build arg from CI). ``null`` when unset (dev environments).
- ``AXON_BUILD_DATE`` env var — set at container build time. ``null``
  when unset.

We do NOT shell out to ``git rev-parse`` at runtime — that would
require git in the production container and add a runtime fork on
every request. Build-time injection is the correct boundary.

Cache-Control: ``public, max-age=N`` aligned with the discovery docs.
Version is stable per process; restart means new metadata, and the
cache TTL bounds staleness for cross-deploy observability.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from axon_enterprise.config import get_settings
from axon_enterprise.http.discovery._helpers import (
    axon_enterprise_version,
    serialize_canonical,
    strong_etag,
)


def build_version_document() -> dict[str, Any]:
    """Build the version document by introspecting live state."""
    return {
        "axon_enterprise_version": axon_enterprise_version(),
        "axon_lang_installed_version": _axon_lang_installed_version(),
        "python_version": _python_version(),
        "build_sha": os.environ.get("AXON_BUILD_SHA") or None,
        "build_date": os.environ.get("AXON_BUILD_DATE") or None,
    }


def _axon_lang_installed_version() -> str | None:
    try:
        import importlib.metadata

        return importlib.metadata.version("axon-lang")
    except Exception:
        return None


def _python_version() -> str:
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"


async def version_endpoint(request: Request) -> Response:
    """``GET /version`` — server version + build metadata."""
    s = get_settings()
    cache_seconds = s.jwt.jwks_cache_control_seconds

    body = serialize_canonical(build_version_document())
    etag = strong_etag(body)

    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"public, max-age={cache_seconds}",
            },
        )

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Cache-Control": f"public, max-age={cache_seconds}",
            "ETag": etag,
        },
    )
