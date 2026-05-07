"""Drift gate — discovery surface ≡ runtime reality (Fase 21.g).

Meta-tests that protect every Fase-21-owned discovery doc against
silent divergence. Runs at builder level (no HTTP, no DB) so the gate
stays fast and unit-testable; the live behaviour is covered by 21.a–f.

Drift this gate catches:

1. **Stale OpenAPI paths**: spec references a Fase 21 endpoint that no
   longer exists, or omits one we publish.
2. **Orphan / dangling schema $refs**: the spec references a schema
   not declared in ``components.schemas``, or declares a schema no
   path references.
3. **OIDC ⇄ OAuth divergence**: the two metadata docs disagree on a
   shared field (issuer, jwks_uri, token_endpoint, scopes_supported).
4. **Capabilities ⇄ Shield registry divergence**: the capabilities doc
   advertises strategies/categories the runtime registry doesn't
   actually have, or omits ones it does.
5. **Capabilities ⇄ SsoProviderType divergence**: the capabilities doc
   advertises providers the enum doesn't have, or vice-versa.
6. **Capabilities ⇄ published well-known set divergence**: the
   ``discovery_endpoints`` map advertises paths Fase 21 doesn't
   actually publish, or omits ones it does.
7. **Internal leakage**: any discovery doc string contains an internal
   deployment marker (ALB hostname, S3 bucket, internal env name) —
   the lesson "no kitchen door" codified.
8. **Schema versions missing or malformed**.

Each test uses a single live source of truth and the builder's output —
never the deployed JSON, never a snapshot file. That way a refactor
that breaks alignment fails CI immediately.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

import pytest

from axon_enterprise.http.discovery import (
    build_capabilities,
    build_oauth_authorization_server_metadata,
    build_openapi_spec,
    build_openid_configuration,
    build_version_document,
)


# ── Fase 21 owned path manifest — single source of truth for the gate ──
#
# When a new Fase 21 endpoint ships, update this list. Adding here +
# forgetting to add to OpenAPI (or vice-versa) is exactly the drift the
# gate is designed to surface.

_FASE21_OPENAPI_DOCUMENTED_PATHS: frozenset[str] = frozenset(
    {
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/.well-known/axon-capabilities.json",
        "/.well-known/jwks.json",
        "/api/v1/tenant/me/integration-context/",
    }
)

# Well-known docs that capabilities.discovery_endpoints should advertise.
# JWKS is included because it's the existing pre-21 well-known doc that
# the integration story still depends on.
_FASE21_PUBLISHED_WELL_KNOWN: frozenset[str] = frozenset(
    {
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/.well-known/jwks.json",
        "/.well-known/axon-capabilities.json",
    }
)

# Substrings that must NEVER appear in a public discovery doc value.
# Each represents an internal-deployment artefact whose presence would
# leak infra to adopters and re-create the "kitchen door" anti-pattern.
_FORBIDDEN_INTERNAL_SUBSTRINGS: tuple[str, ...] = (
    ".elb.amazonaws.com",
    ".s3.amazonaws.com",
    "axon-prod-alb",
    "staging-internal",
    "rds.amazonaws.com",
    "internal.bemarking",
)

_SEMVER_LIKE = re.compile(r"^\d+\.\d+(\.\d+)?(-[\w.]+)?$")


# ── helpers ──────────────────────────────────────────────────────────


def _flatten_strings(obj: Any) -> Iterable[str]:
    """Recursively yield every string value contained in a JSON-shaped object."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _flatten_strings(item)


def _collect_refs(obj: Any) -> Iterable[str]:
    """Yield every ``$ref`` string nested anywhere in the spec."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from _collect_refs(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _collect_refs(item)


# ── 1. OpenAPI paths ⇄ Fase 21 manifest ──────────────────────────────


def test_openapi_documents_every_fase21_path() -> None:
    """Every endpoint Fase 21 owns must appear in the OpenAPI spec.
    Catches the case where a new Fase 21 endpoint ships but the spec
    update was forgotten (clients can't discover it via /docs)."""
    spec = build_openapi_spec()
    declared = set(spec["paths"].keys())
    missing = _FASE21_OPENAPI_DOCUMENTED_PATHS - declared
    assert not missing, (
        f"OpenAPI spec is missing Fase 21 paths: {sorted(missing)}. "
        "Add them to build_openapi_spec()._paths()."
    )


# ── 2. OpenAPI $refs all resolve + no orphan schemas ─────────────────


def test_openapi_refs_resolve_and_no_orphans() -> None:
    spec = build_openapi_spec()
    declared_schemas = set(spec["components"]["schemas"].keys())

    # Every $ref under #/components/schemas/ must resolve.
    referenced: set[str] = set()
    for ref in _collect_refs(spec):
        prefix = "#/components/schemas/"
        assert ref.startswith(prefix), f"unexpected $ref form: {ref}"
        name = ref.removeprefix(prefix)
        assert name in declared_schemas, (
            f"$ref '{ref}' has no matching schema in components.schemas"
        )
        referenced.add(name)

    # Every declared schema must be referenced at least once. Orphan
    # schemas are dead weight + a sign of drift after a refactor.
    orphans = declared_schemas - referenced
    assert not orphans, (
        f"orphan schemas declared but never $ref'd: {sorted(orphans)}"
    )


# ── 3. OIDC ⇄ OAuth shared-field consistency at builder level ────────


def test_oidc_oauth_shared_fields_byte_identical() -> None:
    oidc = build_openid_configuration()
    oauth = build_oauth_authorization_server_metadata()
    for shared in (
        "issuer",
        "jwks_uri",
        "token_endpoint",
        "authorization_endpoint",
        "scopes_supported",
    ):
        assert oidc[shared] == oauth[shared], (
            f"OIDC and OAuth metadata diverge on shared field {shared!r}: "
            f"oidc={oidc[shared]!r} vs oauth={oauth[shared]!r}"
        )


# ── 4. Capabilities ⇄ Shield registry exact match ────────────────────


def test_capabilities_shield_matches_registry() -> None:
    """The advertised Shield strategies + categories must exactly match
    the runtime registry. Adding a scanner without it appearing in
    capabilities (or removing one that still appears) is silent drift
    that confuses adopter SDKs about what they can ask the server to do."""
    caps = build_capabilities()
    try:
        from axon.runtime.shield_scanners import default_registry  # type: ignore[import-not-found]
    except Exception:
        pytest.skip("axon.runtime.shield_scanners unavailable in this env")

    known = default_registry.known()
    expected_categories = sorted(known.keys())
    expected_strategies = sorted({s for ss in known.values() for s in ss})

    assert caps["shield_categories_supported"] == expected_categories, (
        "capabilities Shield categories drift vs runtime registry"
    )
    assert caps["shield_strategies_supported"] == expected_strategies, (
        "capabilities Shield strategies drift vs runtime registry"
    )


# ── 5. Capabilities ⇄ SsoProviderType enum exact match ──────────────


def test_capabilities_sso_matches_enum() -> None:
    from axon_enterprise.sso.models import SsoProviderType

    caps = build_capabilities()
    expected = sorted(p.value for p in SsoProviderType)
    assert caps["sso_providers_supported"] == expected, (
        "capabilities sso_providers_supported drift vs SsoProviderType enum"
    )


# ── 6. Capabilities.discovery_endpoints ⇄ published well-known set ──


def test_capabilities_advertises_every_published_well_known() -> None:
    """``capabilities.discovery_endpoints`` must list every well-known doc
    Fase 21 publishes — no more, no less. A new well-known endpoint that
    isn't advertised here is invisible to discovery-driven SDKs."""
    caps = build_capabilities()
    advertised_paths = set(caps["discovery_endpoints"].values())
    missing = _FASE21_PUBLISHED_WELL_KNOWN - advertised_paths
    extra = advertised_paths - _FASE21_PUBLISHED_WELL_KNOWN
    assert not missing, f"capabilities.discovery_endpoints missing: {sorted(missing)}"
    assert not extra, f"capabilities.discovery_endpoints advertises non-published: {sorted(extra)}"


# ── 7. No internal leakage in any discovery doc ─────────────────────


def test_no_internal_deployment_leakage() -> None:
    """The "no kitchen door" lesson codified. Public discovery docs MUST
    expose stable product names (DNS, audience strings) — never internal
    infra names (ALB hostnames, S3 bucket names, internal env labels).

    A failure here means an adopter consuming the discovery doc would
    learn private deployment details that should remain encapsulated.
    """
    docs = {
        "openid-configuration": build_openid_configuration(),
        "oauth-authorization-server": build_oauth_authorization_server_metadata(),
        "axon-capabilities.json": build_capabilities(),
        "openapi.json": build_openapi_spec(),
        "version": build_version_document(),
    }
    leaks: list[str] = []
    for doc_name, doc in docs.items():
        for s in _flatten_strings(doc):
            for forbidden in _FORBIDDEN_INTERNAL_SUBSTRINGS:
                if forbidden in s:
                    leaks.append(
                        f"{doc_name}: value contains forbidden substring "
                        f"{forbidden!r}: {s!r}"
                    )
    assert not leaks, (
        "Internal deployment artefacts leaked into public discovery docs:\n  "
        + "\n  ".join(leaks)
    )


# ── 8. Every advertised schema_version is non-empty + semver-shaped ─


def test_advertised_schema_versions_are_semver_shaped() -> None:
    """Each discovery doc that publishes a ``axon_*_schema_version`` field
    must use a non-empty semver-like string. Catches accidental empty /
    None / placeholder values during refactors."""
    cases = [
        ("openid-configuration", build_openid_configuration(), "axon_discovery_schema_version"),
        ("oauth-authorization-server", build_oauth_authorization_server_metadata(), "axon_oauth_metadata_schema_version"),
        ("axon-capabilities.json", build_capabilities(), "axon_capabilities_schema_version"),
    ]
    for doc_name, doc, field in cases:
        value = doc.get(field)
        assert value, f"{doc_name}: missing or empty {field}"
        assert isinstance(value, str)
        assert _SEMVER_LIKE.match(value), (
            f"{doc_name}: {field}={value!r} is not semver-shaped"
        )


# ── 9. Capabilities + version both report SAME axon-lang version ────


def test_axon_lang_version_consistent_across_docs() -> None:
    """``axon_lang_installed_version`` is read by both capabilities and
    version endpoints. They must report the same value at the same
    instant — divergence would mean a probe got monkey-patched in one
    place but not the other."""
    caps = build_capabilities()
    ver = build_version_document()
    assert caps["axon_lang_installed_version"] == ver["axon_lang_installed_version"], (
        "axon-lang version differs between capabilities and version docs"
    )
