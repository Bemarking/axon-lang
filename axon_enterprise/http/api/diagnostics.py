"""§Fase 29.e — `/api/v1/tenant/diagnostics/recent` HTTP endpoint.

D4 + D8 + D9 + Q4 resolution (auth via existing tenant-context
middleware, no new RBAC slug) ratificadas 2026-05-12.

## Endpoint surface

``GET /api/v1/tenant/diagnostics/recent``

Returns the last N parser diagnostics for the authenticated
tenant, optionally aggregated by ``(file_path, code, line_bucket)``.

### Query parameters

- ``since`` — ISO-8601 UTC timestamp; only diagnostics emitted
  strictly after this point are returned. Acts as the pagination
  cursor (subsequent pages: pass the response's ``last_seen``
  as ``since``).
- ``limit`` — max records / aggregated groups; default 50, clamped
  to ``[1, 500]``.
- ``aggregated`` — ``true`` (default) or ``false``. Aggregated mode
  groups by ``(file_path, code, line_bucket)``; raw mode returns
  individual records.
- ``file_path`` — equality filter (raw mode only).
- ``code`` — equality filter (raw mode only).
- ``bucket_size`` — line bucket size for aggregated mode; default
  10, range ``[1, 1000]``.

### Response shape

```json
{
  "tenant_id": "<authenticated-tenant>",
  "vertical": "<resolved-vertical-or-generic>",
  "mode": "aggregated" | "raw",
  "entries": [...]
}
```

Aggregated entries:

```json
{
  "file_path": "src/flow.axon",
  "code": "AX-0042",
  "line_bucket": 10,
  "vertical": "hipaa",
  "count": 7,
  "first_seen": "2026-05-12T...",
  "last_seen": "2026-05-12T..."
}
```

Raw entries:

```json
{
  "code": "AX-0042",
  "file_path": "src/flow.axon",
  "line": 17,
  "column": 4,
  "vertical": "hipaa",
  "severity": "error",
  "timestamp": "2026-05-12T..."
}
```

### Privacy boundary (D4)

**NO source text in any response field.** The store
:class:`DiagnosticRecord` carries only structural attributes;
this handler never attempts to fetch source. Adopter clients
fetch source separately via existing repo access controls if
they need the full block.

### Tenant isolation (D8)

Every query is keyed on ``require_principal().tenant_id`` —
cross-tenant retrieval is structurally impossible from this
endpoint. The authenticated tenant cannot see another tenant's
diagnostics by altering query parameters.

### Auth (Q4 resolution)

Uses ``require_principal()`` only — no new RBAC slug introduced
(``diagnostics:read`` deferred to v1.15.x patch if adopter demand
surfaces). The existing JWT/session middleware populates
``CURRENT_PRINCIPAL``; this handler raises 401 implicitly when
unauthenticated (``require_principal`` raises RuntimeError that
the ASGI error handler converts to 401).

### Backwards-compat (D9)

When the authenticated tenant has no registered vertical, the
endpoint still works — it serves an empty ``entries`` array (or
whatever the store has for that tenant, which is typically empty
because GENERIC tenants are telemetry-disabled by default). No
behavior change for OSS-only tenants.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.diagnostics.policy import (
    TenantVertical,
    get_tenant_vertical,
)
from axon_enterprise.diagnostics.store import (
    AggregatedDiagnostic,
    DiagnosticRecord,
    get_default_store,
)
from axon_enterprise.identity.principal import require_principal


# ──────────────────────────────────────────────────────────────────
#  Query-parameter parsing
# ──────────────────────────────────────────────────────────────────


_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50
_MAX_BUCKET = 1000
_DEFAULT_BUCKET = 10


def _parse_int(
    raw: str | None,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    """Clamped integer parser. Returns `default` when raw is missing
    or unparseable; clamps to ``[min_value, max_value]`` otherwise.
    """
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    """Truthy alphabet mirrors :func:`parse_truthy_env` from axon-rs:
    `{1, true, yes, on}` case-insensitive; everything else falsy.
    """
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_since(raw: str | None) -> datetime | None:
    """Parse ISO-8601 datetime. Returns None for missing / malformed
    input (silently — pagination cursors that arrive corrupted just
    behave like a fresh first-page query).
    """
    if raw is None or raw == "":
        return None
    try:
        # ``datetime.fromisoformat`` accepts the canonical
        # ``2026-05-12T...+00:00`` shape we emit on the way out;
        # tolerate the ``Z`` trailing suffix by normalising.
        normalised = raw.rstrip("Z")
        if normalised != raw:
            normalised += "+00:00"
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    # Force UTC for consistency.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ──────────────────────────────────────────────────────────────────
#  Serialisation (privacy-preserving)
# ──────────────────────────────────────────────────────────────────


def _record_to_json(record: DiagnosticRecord) -> dict[str, Any]:
    """Project a :class:`DiagnosticRecord` onto the wire JSON shape.

    Structural fields only — D4 enforced by the type's slot set
    (no source text exists in the record).
    """
    return {
        "code": record.code,
        "file_path": record.file_path,
        "line": record.line,
        "column": record.column,
        "vertical": record.vertical,
        "severity": record.severity,
        "timestamp": record.timestamp.isoformat(),
    }


def _aggregated_to_json(agg: AggregatedDiagnostic) -> dict[str, Any]:
    """Project an :class:`AggregatedDiagnostic` onto the wire shape."""
    return {
        "file_path": agg.file_path,
        "code": agg.code,
        "line_bucket": agg.line_bucket,
        "vertical": agg.vertical,
        "count": agg.count,
        "first_seen": agg.first_seen.isoformat(),
        "last_seen": agg.last_seen.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────
#  Handler
# ──────────────────────────────────────────────────────────────────


async def _recent_handler(request: Request) -> JSONResponse:
    """GET /api/v1/tenant/diagnostics/recent — see module docstring.

    Q4 ratificada — auth via existing tenant-context middleware.
    `require_principal()` raises if unauthenticated; the ASGI
    error handler maps that to 401.

    D8 ratificada — `principal.tenant_id` is the ONLY tenant key
    used to query the store. The authenticated tenant cannot reach
    another tenant's records by manipulating query parameters.
    """
    principal = require_principal()
    tenant_id = principal.tenant_id

    params = request.query_params
    limit = _parse_int(
        params.get("limit"),
        default=_DEFAULT_LIMIT,
        min_value=1,
        max_value=_MAX_LIMIT,
    )
    aggregated = _parse_bool(params.get("aggregated"), default=True)
    since = _parse_since(params.get("since"))

    vertical = get_tenant_vertical(tenant_id).value

    store = get_default_store()

    if aggregated:
        bucket_size = _parse_int(
            params.get("bucket_size"),
            default=_DEFAULT_BUCKET,
            min_value=1,
            max_value=_MAX_BUCKET,
        )
        groups = store.aggregated_for_tenant(
            tenant_id,
            since=since,
            limit=limit,
            bucket_size=bucket_size,
        )
        entries = [_aggregated_to_json(g) for g in groups]
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "vertical": vertical,
                "mode": "aggregated",
                "bucket_size": bucket_size,
                "limit": limit,
                "entries": entries,
            }
        )

    # Raw mode.
    file_path = params.get("file_path")
    code = params.get("code")
    records = store.recent_for_tenant(
        tenant_id,
        since=since,
        limit=limit,
        file_path=file_path,
        code=code,
    )
    entries = [_record_to_json(r) for r in records]
    return JSONResponse(
        {
            "tenant_id": tenant_id,
            "vertical": vertical,
            "mode": "raw",
            "limit": limit,
            "entries": entries,
        }
    )


# ──────────────────────────────────────────────────────────────────
#  Route registration
# ──────────────────────────────────────────────────────────────────


def routes() -> list[Route]:
    """Return the route list mounted under
    `/api/v1/tenant/diagnostics`.
    """
    return [
        Route("/recent", _recent_handler, methods=["GET"]),
    ]


__all__ = ["routes"]
