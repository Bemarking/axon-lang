"""Contract tests — wire-format snapshots + spec compliance (Fase 21.j).

The final safety net before release. Two complementary mechanisms:

**Snapshot tests** — every Fase 21 doc has a golden JSON file under
``tests/discovery/golden/``. The current builder output is normalized
(volatile fields like ``axon_enterprise_version`` and the live registry
contents replaced with sentinel values) and compared byte-for-byte
against the golden. A drift in any non-volatile field fails the test
with a concrete diff.

To regen a golden file intentionally (e.g., after a Fase 21 schema
bump), delete the file and rerun the test — it auto-recreates from
the current normalized output. This forces a deliberate review-time
moment for every wire-format change.

**Spec-compliance tests** — the OpenAPI spec validates against the
official OpenAPI 3.1.0 validator (``openapi-spec-validator``); the
OIDC and OAuth metadata documents validate against minimal hand-coded
JSON Schemas based on the mandatory fields of OIDC Connect Discovery
1.0 and RFC 8414.

**Third-party parse compatibility** — authlib (a major OAuth/OIDC
library) successfully parses our OIDC discovery doc, proving real
ecosystem clients work with our wire format.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import validate as jsonschema_validate
from openapi_spec_validator import validate as openapi_validate

from axon_enterprise.http.api.integration_context import (
    build_integration_context,
)
from axon_enterprise.http.discovery import (
    build_capabilities,
    build_oauth_authorization_server_metadata,
    build_openapi_spec,
    build_openid_configuration,
    build_version_document,
)


GOLDEN_DIR = Path(__file__).parent / "golden"
NORMALIZED = "<NORMALIZED>"


# ── Per-doc normalizers ──────────────────────────────────────────────


def _normalize_oidc(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["axon_enterprise_version"] = NORMALIZED
    return doc


def _normalize_oauth(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["axon_enterprise_version"] = NORMALIZED
    return doc


def _normalize_capabilities(doc: dict[str, Any]) -> dict[str, Any]:
    """Capabilities snapshot pins Shield registry contents intentionally.

    A Fase 20 plugin add/remove will fail the snapshot — forcing the dev
    to either acknowledge the change (delete golden, regen) or back it
    out. The trade-off is intentional: silent registry drift is exactly
    the class of bug the contract gate exists to surface.
    """
    doc = copy.deepcopy(doc)
    doc["axon_enterprise_version"] = NORMALIZED
    doc["axon_lang_installed_version"] = NORMALIZED
    return doc


def _normalize_openapi(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["info"]["version"] = NORMALIZED
    return doc


def _normalize_version(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["axon_enterprise_version"] = NORMALIZED
    doc["axon_lang_installed_version"] = NORMALIZED
    doc["python_version"] = NORMALIZED
    doc["build_sha"] = NORMALIZED
    doc["build_date"] = NORMALIZED
    return doc


def _normalize_integration_context(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["axon_enterprise_version"] = NORMALIZED
    return doc


# ── Snapshot helper ──────────────────────────────────────────────────


def _assert_snapshot(name: str, current: dict[str, Any]) -> None:
    """Assert the normalized current doc matches the golden file.

    First-run behaviour: when the golden file is absent, write it from
    the current normalized doc and pass. Subsequent runs compare. To
    regenerate intentionally, delete the file and rerun.
    """
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden_path = GOLDEN_DIR / f"{name}.json"

    serialized = json.dumps(current, sort_keys=True, indent=2)

    if not golden_path.exists():
        golden_path.write_text(serialized + "\n", encoding="utf-8")
        pytest.skip(
            f"created golden file {golden_path.name} on first run; "
            "rerun to enforce future drift detection"
        )

    expected = golden_path.read_text(encoding="utf-8").rstrip("\n")
    if serialized != expected:
        raise AssertionError(
            f"{name} snapshot drift detected.\n\n"
            f"To accept the change deliberately:\n"
            f"  rm {golden_path}\n"
            f"  pytest tests/discovery/test_discovery_contracts.py::test_{name}_snapshot\n\n"
            f"Diff (expected → actual):\n"
            f"--- expected\n"
            f"+++ actual\n"
            + _unified_diff(expected, serialized)
        )


def _unified_diff(expected: str, actual: str) -> str:
    """Tiny diff so failures show what changed without a heavyweight dep."""
    import difflib

    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        lineterm="",
    )
    return "".join(diff)


# ── 1. Snapshot OIDC discovery ───────────────────────────────────────


def test_openid_configuration_snapshot() -> None:
    _assert_snapshot(
        "openid_configuration", _normalize_oidc(build_openid_configuration())
    )


# ── 2. Snapshot OAuth Authorization Server Metadata ──────────────────


def test_oauth_authorization_server_snapshot() -> None:
    _assert_snapshot(
        "oauth_authorization_server",
        _normalize_oauth(build_oauth_authorization_server_metadata()),
    )


# ── 3. Snapshot Axon Capabilities ────────────────────────────────────


def test_capabilities_snapshot() -> None:
    _assert_snapshot(
        "axon_capabilities", _normalize_capabilities(build_capabilities())
    )


# ── 4. Snapshot OpenAPI 3.1.0 spec ───────────────────────────────────


def test_openapi_spec_snapshot() -> None:
    _assert_snapshot("openapi_spec", _normalize_openapi(build_openapi_spec()))


# ── 5. Snapshot Version doc ──────────────────────────────────────────


def test_version_document_snapshot() -> None:
    _assert_snapshot("version_document", _normalize_version(build_version_document()))


# ── 6. Snapshot Integration Context (fixed principal) ────────────────


def test_integration_context_snapshot() -> None:
    """A fixed principal (tenant_id='snapshot-test', plan='enterprise')
    drives a deterministic doc. Verifies that the per-tenant fields
    (tenant_id, plan) flow through correctly without contaminating
    server-wide settings."""
    doc = build_integration_context(tenant_id="snapshot-test", plan="enterprise")
    _assert_snapshot(
        "integration_context", _normalize_integration_context(doc)
    )


# ── 7. OpenAPI spec validates against openapi-spec-validator ─────────


def test_openapi_spec_passes_official_validator() -> None:
    """``openapi-spec-validator`` is the reference implementation of the
    OpenAPI 3.x JSON Schema. Failure here means our spec is structurally
    invalid — a real OpenAPI client lib would reject it."""
    spec = build_openapi_spec()
    # Raises OpenAPIValidationError on invalid spec; nothing returned on success.
    openapi_validate(spec)


# ── 8. OIDC + OAuth docs satisfy minimal RFC schemas ────────────────


_OIDC_DISCOVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "response_types_supported",
        "subject_types_supported",
        "id_token_signing_alg_values_supported",
    ],
    "properties": {
        "issuer": {"type": "string", "format": "uri"},
        "authorization_endpoint": {"type": "string", "format": "uri"},
        "token_endpoint": {"type": "string", "format": "uri"},
        "jwks_uri": {"type": "string", "format": "uri"},
        "response_types_supported": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "subject_types_supported": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "id_token_signing_alg_values_supported": {
            "type": "array",
            "items": {"type": "string", "pattern": "^(RS|ES|PS)256|384|512$|^none$"},
            "minItems": 1,
        },
    },
}


_OAUTH_METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "issuer",
        "response_types_supported",
        "token_endpoint",
        "grant_types_supported",
        "token_endpoint_auth_methods_supported",
    ],
    "properties": {
        "issuer": {"type": "string", "format": "uri"},
        "token_endpoint": {"type": "string", "format": "uri"},
        "response_types_supported": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "grant_types_supported": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "token_endpoint_auth_methods_supported": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
}


def test_oidc_doc_satisfies_oidc_discovery_schema() -> None:
    jsonschema_validate(build_openid_configuration(), _OIDC_DISCOVERY_SCHEMA)


def test_oauth_doc_satisfies_rfc8414_schema() -> None:
    jsonschema_validate(
        build_oauth_authorization_server_metadata(), _OAUTH_METADATA_SCHEMA
    )


# ── 9. Third-party parse compat: authlib consumes OIDC discovery ────


def test_authlib_consumes_oidc_discovery_doc() -> None:
    """``authlib`` ships a server-metadata loader. A real OAuth/OIDC
    client lib successfully constructing its internal config from our
    doc proves the wire format is genuinely interoperable, not just
    schema-valid in isolation."""
    from authlib.oauth2.rfc8414 import AuthorizationServerMetadata

    doc = build_openid_configuration()
    metadata = AuthorizationServerMetadata(doc)
    metadata.validate()  # raises on any spec violation

    # Sanity: the parsed metadata exposes the same critical values.
    assert metadata["issuer"] == doc["issuer"]
    assert metadata["jwks_uri"] == doc["jwks_uri"]
    assert metadata["token_endpoint"] == doc["token_endpoint"]
