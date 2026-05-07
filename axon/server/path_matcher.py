"""URL path template matcher for the axon HTTP endpoint dispatcher.

Endpoint flows declare paths with ``{name}`` placeholder syntax —
``/api/tenants/{tenant_id}``, ``/api/orders/{order_id}/items/{item_id}``.
Pre-v1.15.3 the dispatcher in ``axon.server.http_app`` compared
``ep.path == request_path`` literally, so any endpoint with a placeholder
in its path returned 404 on every request (the literal ``{name}``
characters never appeared in real URLs). v1.15.3 closes that gap.

This module supplies the primitives the dispatcher composes:

- ``compile_template`` — convert a template into a compiled regex +
  parameter-name list. Cheap to call repeatedly; callers typically
  cache per-endpoint.
- ``match_path`` — match an incoming path against a template, return
  the extracted parameters as a ``dict[str, str]`` or ``None`` if
  no match.
- ``canonical_template`` — collapse parameter names to a sentinel so
  two templates that match the same set of paths but use different
  names produce identical canonical forms. Used by collision
  detection.
- ``detect_template_collisions`` — given a list of (name, method,
  path) triples, return groups of endpoints that share a canonical
  template under the same method (the most common adopter mistake:
  declaring two endpoints with structurally identical paths).

Design constraints:

- Path parameter values **never** consume slash characters
  (``[^/]+``). This mirrors Starlette's ``Route("/x/{id}")`` default
  and prevents ``{id}`` from greedily swallowing path segments.
- Path parameters **never** match empty strings. ``/api/users/``
  must NOT route to ``/api/users/{id}`` — the trailing-slash
  variant is a separate route from the operator's perspective.
- All extracted values are returned as ``str``. Callers that need
  typed conversion (``int(payload['user_id'])``) handle it
  explicitly. Type converters in the template (``{id:int}``) are
  out of scope for v1.15.3.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Matches a placeholder like ``{name}`` where ``name`` is a Python
# identifier (letters, digits, underscore; cannot start with digit).
_PARAM_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Sentinel used by ``canonical_template`` so name-divergent templates
# that match the same paths collide explicitly. Chosen to be lexically
# distinct from any valid identifier so it never appears in real
# templates by accident.
_CANONICAL_PARAM_SENTINEL = "{*}"


def compile_template(template: str) -> tuple[re.Pattern[str], list[str]]:
    """Compile a path template into a regex + ordered parameter names.

    >>> regex, names = compile_template("/api/tenants/{tenant_id}")
    >>> names
    ['tenant_id']
    >>> regex.match("/api/tenants/abc-123").groupdict()
    {'tenant_id': 'abc-123'}
    >>> regex.match("/api/tenants/")  # empty value — must not match
    >>> regex.match("/api/tenants/abc/extra")  # slash inside value — must not match
    """
    param_names: list[str] = []
    pattern_parts: list[str] = ["^"]
    cursor = 0
    for match in _PARAM_PATTERN.finditer(template):
        # Literal segment before this placeholder.
        pattern_parts.append(re.escape(template[cursor : match.start()]))
        name = match.group(1)
        if name in param_names:
            raise ValueError(
                f"Template {template!r} declares parameter {name!r} more "
                "than once. Each path parameter name must be unique within "
                "a single endpoint declaration."
            )
        param_names.append(name)
        pattern_parts.append(f"(?P<{name}>[^/]+)")
        cursor = match.end()
    pattern_parts.append(re.escape(template[cursor:]))
    pattern_parts.append("$")
    return re.compile("".join(pattern_parts)), param_names


def match_path(template: str, path: str) -> dict[str, str] | None:
    """Match a request path against a template; return params or None.

    Convenience wrapper for one-shot matches. Hot paths should call
    ``compile_template`` once and reuse the regex.
    """
    regex, _ = compile_template(template)
    match = regex.match(path)
    return match.groupdict() if match else None


def canonical_template(template: str) -> str:
    """Collapse parameter names to a sentinel for collision detection.

    >>> canonical_template("/api/tenants/{tenant_id}")
    '/api/tenants/{*}'
    >>> canonical_template("/api/tenants/{x}") == canonical_template("/api/tenants/{y}")
    True
    """
    return _PARAM_PATTERN.sub(_CANONICAL_PARAM_SENTINEL, template)


def detect_template_collisions(
    endpoints: list[tuple[str, str, str]],
) -> dict[tuple[str, str], list[str]]:
    """Find endpoints whose templates would route the same paths.

    Args:
        endpoints: list of ``(endpoint_name, method, path)`` triples.

    Returns:
        Mapping ``(method, canonical_path) → [endpoint_name, ...]`` for
        every group with two or more endpoints. Empty dict if no
        collisions exist. Endpoints with no parameters (``"/api/me"``)
        are included — two literal endpoints with identical paths are
        also a collision.

    The dispatcher's ``_resolve()`` iterates endpoints in registration
    order and returns the first match, so a collision means the second
    declaration is silently dead. Surface this at deploy time, not
    after a confused production debugging session.
    """
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name, method, path in endpoints:
        key = (method.upper(), canonical_template(path))
        grouped[key].append(name)
    return {key: names for key, names in grouped.items() if len(names) > 1}
