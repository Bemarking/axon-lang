"""Shared helpers for discovery endpoints (Fase 21).

Pure functions used by every discovery doc serializer. Extracted once
the third endpoint (capabilities, 21.d) joined OIDC (21.a) and OAuth
(21.b) — at that point duplication crosses the threshold where a
single source of truth pays off, and extracting prevents a divergent
ETag algorithm from silently breaking conditional requests in one doc
but not the others.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def serialize_canonical(doc: dict[str, Any]) -> bytes:
    """Canonical JSON serialization — sorted keys, no whitespace.

    Determinism matters for ETag stability across processes and across
    the lifecycle of cached docs. ``sort_keys`` guarantees byte-equal
    output for two semantically identical docs even if dict insertion
    order differs.
    """
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


def strong_etag(body: bytes) -> str:
    """Strong ETag: SHA-256 hex of the body, quoted per RFC 7232."""
    return f'"{hashlib.sha256(body).hexdigest()}"'


def axon_enterprise_version() -> str:
    """Resolve the current axon-enterprise version at runtime."""
    from axon_enterprise import __version__

    return __version__
