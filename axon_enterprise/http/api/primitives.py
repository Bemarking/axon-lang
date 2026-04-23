"""``GET /api/v1/primitives`` — catalog discovery endpoint.

Clients installing Axon Enterprise need a single call to enumerate
every closed catalogue + seeded open registry. Before this endpoint
adopters had to read the operator guides or grep the source.

Shape is intentionally flat — one JSON object, four catalogues, one
registry snapshot. Cache-Control is aggressive (1 day) because the
catalogues are stable per deploy; a `v1.2.1` → `v1.2.2` bump
invalidates the cache via the `version` field that clients can
compare client-side.

Routes here are PUBLIC at the AuthMiddleware layer — there is no
sensitive information in a list of slugs. Enumeration resistance
isn't the threat model here; the closed catalogues are published
in ``docs/`` anyway and in the axon-lang source.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise import __version__ as _AXON_ENTERPRISE_VERSION


async def _primitives(request: Request) -> JSONResponse:
    """Return every known primitive catalogue + seeded registry."""
    # Import locally so the endpoint doesn't slow down module import
    # when axon-lang isn't yet resolved (e.g. during a CLI-only
    # installation).
    from axon.compiler.legal_basis import LEGAL_BASIS_CATALOG
    from axon.runtime.ffi.buffer import global_kind_registry
    from axon.runtime.ots import OTS_BACKEND_CATALOG
    from axon.runtime.stream_primitive import BACKPRESSURE_CATALOG
    from axon.runtime.trust import TRUST_CATALOG

    payload = {
        "service": "axon-enterprise",
        "service_version": _AXON_ENTERPRISE_VERSION,
        "catalogs": {
            "trust_proofs": list(TRUST_CATALOG),
            "backpressure_policies": list(BACKPRESSURE_CATALOG),
            "legal_bases": list(LEGAL_BASIS_CATALOG),
            "ots_backends": list(OTS_BACKEND_CATALOG),
        },
        "registries": {
            "buffer_kinds_seeded": global_kind_registry().known_slugs(),
        },
        "meta": {
            "documentation": {
                "trust_proofs": "docs/TRUST_TYPES.md",
                "backpressure_policies": "docs/STREAM_EFFECTS.md",
                "legal_bases": "docs/REPLAY_AND_LEGAL_BASIS.md",
                "ots_backends": "docs/OTS_BINARY_PIPELINES.md",
                "buffer_kinds": "docs/BUFFER_PROTOCOL.md",
            },
            "catalog_policies": {
                "trust_proofs": "closed — extension requires a compiler patch + security review",
                "backpressure_policies": "closed — extension requires a compiler patch",
                "legal_bases": "closed — extension requires a compiler patch + legal review",
                "ots_backends": "closed — extension requires a compiler patch",
                "buffer_kinds": "open — adopters may register custom kinds at runtime",
            },
        },
    }
    return JSONResponse(
        payload,
        headers={
            # Stable per deploy — cache aggressively + allow
            # revalidation on version change via the response body.
            "Cache-Control": "public, max-age=86400",
        },
    )


def routes() -> list[Route]:
    return [
        Route("/", _primitives, methods=["GET"]),
    ]
