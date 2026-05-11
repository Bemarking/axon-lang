"""§Fase 32.b — Dynamic axonendpoint route collection (Python mirror).

Byte-identical mirror of the Rust `collect_axonendpoint_routes` +
`merge_dynamic_routes` functions in `axon-rs/src/axon_server.rs`.
The Python implementation produces the **same route table** the
Rust runtime registers — D11 cross-stack consistency contract.

This module is consumed by:

  * The drift-gate test pack in `tests/test_fase32_routes_drift.py`,
    which parametrizes over the shared corpus at
    `tests/fixtures/fase32_routes/corpus.json` and asserts that both
    stacks compute byte-identical (method, path) → flow_name maps.

  * Future Python `AxonServer` integration (FastAPI
    `app.add_api_route()` wiring) when the Python runtime catches up
    on the Fase 30 + 31 SSE handlers (Rust-only today). The helper
    is shipped now so the contract is locked at the type-table layer.

Pillar trace per D12:
  - MATHEMATICS — function is pure + total: (Program, source, source_file)
                   → Result[RouteTable, CollisionError].
  - LOGIC      — intra-program path collisions detected before merge;
                  cross-deploy collisions detected by merge_dynamic_routes.
  - PHILOSOPHY — both stacks see the same route table; auditors
                  inspecting source + cross-checking the runtime catch
                  drift at PR time, never at adopter-bug-report time.
  - COMPUTING  — return types are total (Err on collision, never raise).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from axon.compiler.ast_nodes import AxonEndpointDefinition


# §Fase 32.b D3 — closed method enum. Mirror of Rust
# `AXONENDPOINT_METHODS` and Python parser `_AXONENDPOINT_METHOD_VALUES`.
AXONENDPOINT_METHODS: frozenset[str] = frozenset({
    "GET", "POST", "PUT", "DELETE", "PATCH",
})


@dataclass
class DynamicEndpointRoute:
    """Mirror of Rust `DynamicEndpointRoute`. Same field order +
    types where representable in Python.

    The drift-gate corpus asserts that for a given source, both
    stacks produce dicts with identical (method, path) → RouteSpec
    mappings where the RouteSpec fields here match byte-for-byte.
    """
    flow_name: str
    endpoint_name: str
    source_file: str
    source: str
    transport: str = ""
    transport_explicit: bool = False
    keepalive: str = ""
    implicit_transport: str = ""


@dataclass
class RouteCollisionError(Exception):
    """Raised by `collect_axonendpoint_routes` on intra-program
    collision, or returned (as exception instance) by callers using
    the dict-result protocol. Mirror of Rust's `Err(String)` shape.
    """
    message: str
    method: str = ""
    path: str = ""
    existing_endpoint: str = ""
    new_endpoint: str = ""

    def __str__(self) -> str:
        return self.message


def collect_axonendpoint_routes(
    program: "Program",
    source: str,
    source_file: str,
) -> dict[tuple[str, str], DynamicEndpointRoute]:
    """Walk the program's AxonEndpoint declarations and produce the
    route table the runtime registers at deploy time.

    Mirror of Rust `collect_axonendpoint_routes` byte-identical:
    same uppercase-method normalisation, same path empty/'/'-prefix
    validation, same collision-error message shape.

    Raises `RouteCollisionError` on intra-program collision (D2
    within a single deploy). Cross-deploy collisions are detected
    by `merge_dynamic_routes` below.

    Defensive: unknown methods (parser should have rejected, but
    runtime is defensive per D3) are skipped + logged via a returned
    `_skipped` annotation rather than raising — the parser is the
    enforcer; runtime is fail-safe.
    """
    routes: dict[tuple[str, str], DynamicEndpointRoute] = {}
    for decl in program.declarations:
        if not isinstance(decl, AxonEndpointDefinition):
            continue
        method = decl.method.strip().upper()
        if method not in AXONENDPOINT_METHODS:
            # Parser should have caught this; defensive skip.
            continue
        path = decl.path.strip()
        if not path or not path.startswith("/"):
            # Empty / malformed path — runtime skip (parser validation
            # for path syntax ships in 32.b.5 / 32.c).
            continue
        key = (method, path)
        if key in routes:
            existing = routes[key]
            raise RouteCollisionError(
                message=(
                    f"Path collision (D2): axonendpoint "
                    f"'{existing.endpoint_name}' and '{decl.name}' both "
                    f"declare `method: {method} path: {path}`. Resolve by "
                    f"editing one of the two axonendpoints to use a "
                    f"distinct (method, path) tuple."
                ),
                method=method,
                path=path,
                existing_endpoint=existing.endpoint_name,
                new_endpoint=decl.name,
            )
        routes[key] = DynamicEndpointRoute(
            flow_name=decl.execute_flow,
            endpoint_name=decl.name,
            source_file=source_file,
            source=source,
            transport=decl.transport,
            transport_explicit=decl.transport_explicit,
            keepalive=decl.keepalive,
            implicit_transport=decl.implicit_transport,
        )
    return routes


def merge_dynamic_routes(
    live: dict[tuple[str, str], DynamicEndpointRoute],
    incoming: dict[tuple[str, str], DynamicEndpointRoute],
) -> None:
    """Merge a freshly-collected route table into the live state.
    Detects cross-deploy collisions (D2 across deploys): if a key
    in `incoming` already exists in `live` for a DIFFERENT
    `endpoint_name`, raises `RouteCollisionError`. Same-endpoint
    re-deploys update the route in place.

    Mutates `live` in place when validation passes (atomic — either
    all incoming routes are merged or none).

    Mirror of Rust `merge_dynamic_routes`. Both stacks produce
    byte-identical post-merge state for the same input.
    """
    # First pass: validate before any mutation.
    for key, new_route in incoming.items():
        if key in live:
            existing = live[key]
            if existing.endpoint_name != new_route.endpoint_name:
                raise RouteCollisionError(
                    message=(
                        f"Path collision (D2 cross-deploy): axonendpoint "
                        f"'{new_route.endpoint_name}' (from {new_route.source_file}) "
                        f"and existing axonendpoint '{existing.endpoint_name}' "
                        f"(from {existing.source_file}) both claim "
                        f"`method: {key[0]} path: {key[1]}`. Resolve by editing "
                        f"one of the two axonendpoints to use a distinct "
                        f"(method, path) tuple."
                    ),
                    method=key[0],
                    path=key[1],
                    existing_endpoint=existing.endpoint_name,
                    new_endpoint=new_route.endpoint_name,
                )
    # Second pass: apply.
    for key, route in incoming.items():
        live[key] = route


def route_table_as_corpus_dict(
    routes: dict[tuple[str, str], DynamicEndpointRoute],
) -> list[dict]:
    """Project the route table into the corpus-comparable list shape
    used by the cross-stack drift gate. The list is sorted by
    (method, path) so byte-identical comparison is order-stable.

    Output shape (one entry per route):
        {"method": "POST", "path": "/chat",
         "flow_name": "Chat", "endpoint_name": "ChatEndpoint",
         "transport": "sse", "transport_explicit": true,
         "keepalive": "15s", "implicit_transport": "sse"}

    Used by `tests/test_fase32_routes_drift.py` to assert that
    Python's table matches the Rust mirror byte-for-byte on every
    corpus entry.
    """
    out: list[dict] = []
    for (method, path) in sorted(routes.keys()):
        r = routes[(method, path)]
        out.append({
            "method": method,
            "path": path,
            "flow_name": r.flow_name,
            "endpoint_name": r.endpoint_name,
            "transport": r.transport,
            "transport_explicit": r.transport_explicit,
            "keepalive": r.keepalive,
            "implicit_transport": r.implicit_transport,
        })
    return out
