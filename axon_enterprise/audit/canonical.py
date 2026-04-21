"""Canonical JSON + hash-chain primitives.

Matches the serialisation axon-lang's ESK uses
(``axon.runtime.esk.provenance.canonical_bytes``) so an ESK provenance
entry and an audit event computing the same payload produce
byte-identical hash input — essential for ESK stitching.

Format contract
---------------
``canonical_bytes_for_hash(obj)`` returns:

    json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=True,
               default=<stable-repr-for-uuid/datetime>)
    .encode("utf-8")

- ``sort_keys=True``: deterministic key ordering
- ``separators=(",",":")``: no spaces
- ``ensure_ascii=True``: matches Rust's ``jsonwebtoken`` + ESK
  which both produce ASCII-escaped output
- ``default=_default``: UUIDs → str(), datetimes → ISO 8601 UTC,
  bytes → base64-urlsafe-no-pad. Any unknown type raises ``TypeError``
  so malformed events fail loudly at insert time.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

# Prefix mixed with tenant_id to derive the genesis hash. Stable.
GENESIS_MAGIC: bytes = b"AXON_AUDIT_GENESIS:"


def _default(value: Any) -> Any:
    """JSON encoder fallback for UUID / datetime / bytes."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # Normalise to UTC + ISO 8601 with milliseconds, matching the
        # ESK canonical form. Naive datetimes are treated as UTC —
        # callers should always pass tz-aware, but we don't want a
        # naive-input bug to kill the write path.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (bytes, bytearray)):
        return base64.urlsafe_b64encode(bytes(value)).rstrip(b"=").decode("ascii")
    raise TypeError(
        f"audit canonical encoder cannot serialise {type(value).__name__}"
    )


def canonical_bytes_for_hash(payload: dict[str, Any]) -> bytes:
    """Serialise ``payload`` to the exact bytes fed into SHA-256."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_default,
    ).encode("utf-8")


def genesis_hash(tenant_id: str) -> bytes:
    """Return the deterministic genesis hash for ``tenant_id``.

    First-event integrity is verifiable by anyone who knows the
    tenant_id: the verifier recomputes ``SHA-256(GENESIS_MAGIC +
    tenant_id)`` and compares to the row's ``prev_hash``.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to derive genesis hash")
    return hashlib.sha256(GENESIS_MAGIC + tenant_id.encode("utf-8")).digest()


def compute_event_hash(
    *,
    prev_hash: bytes,
    tenant_id: str,
    sequence_number: int,
    event_type: str,
    payload: dict[str, Any],
) -> bytes:
    """Return ``SHA-256(prev_hash || tenant || seq || type || canonical_json)``.

    All inputs are fed into a single hash-update stream so a verifier
    that reconstructs them recomputes byte-identically.
    """
    h = hashlib.sha256()
    h.update(prev_hash)
    h.update(b"\x1e")  # field separator
    h.update(tenant_id.encode("utf-8"))
    h.update(b"\x1e")
    h.update(sequence_number.to_bytes(8, "big", signed=False))
    h.update(b"\x1e")
    h.update(event_type.encode("utf-8"))
    h.update(b"\x1e")
    h.update(canonical_bytes_for_hash(payload))
    return h.digest()
