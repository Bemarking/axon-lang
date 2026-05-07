"""Discovery endpoints — well-known surfaces for adopter integration.

Public, unauthenticated endpoints under ``/.well-known/`` that let any
consumer (tenant, dashboard, third-party SDK) discover the integration
parameters of this axon-enterprise installation without out-of-band
configuration handover.

Fase 21 — Integration Surface for axon-enterprise SaaS sabor.
"""

from axon_enterprise.http.discovery.capabilities import (
    CAPABILITIES_SCHEMA_VERSION,
    build_capabilities,
    capabilities_endpoint,
)
from axon_enterprise.http.discovery.docs_ui import (
    redoc_endpoint,
    swagger_ui_endpoint,
)
from axon_enterprise.http.discovery.oauth import (
    OAUTH_METADATA_SCHEMA_VERSION,
    build_oauth_authorization_server_metadata,
    oauth_authorization_server_endpoint,
)
from axon_enterprise.http.discovery.oidc import (
    DISCOVERY_SCHEMA_VERSION,
    build_openid_configuration,
    openid_configuration_endpoint,
)
from axon_enterprise.http.discovery.openapi import (
    OPENAPI_VERSION,
    build_openapi_spec,
    openapi_endpoint,
)
from axon_enterprise.http.discovery.observability import (
    DISCOVERY_REQUESTS_TOTAL,
    DISCOVERY_REQUEST_DURATION_SECONDS,
    TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL,
    anonymize_ip,
    classify_user_agent,
    with_discovery_observability,
    with_integration_context_observability,
)
from axon_enterprise.http.discovery.version import (
    build_version_document,
    version_endpoint,
)

__all__ = [
    "CAPABILITIES_SCHEMA_VERSION",
    "DISCOVERY_REQUESTS_TOTAL",
    "DISCOVERY_REQUEST_DURATION_SECONDS",
    "DISCOVERY_SCHEMA_VERSION",
    "OAUTH_METADATA_SCHEMA_VERSION",
    "OPENAPI_VERSION",
    "TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL",
    "anonymize_ip",
    "build_capabilities",
    "build_oauth_authorization_server_metadata",
    "build_openapi_spec",
    "build_openid_configuration",
    "build_version_document",
    "capabilities_endpoint",
    "classify_user_agent",
    "oauth_authorization_server_endpoint",
    "openapi_endpoint",
    "openid_configuration_endpoint",
    "redoc_endpoint",
    "swagger_ui_endpoint",
    "version_endpoint",
    "with_discovery_observability",
    "with_integration_context_observability",
]
