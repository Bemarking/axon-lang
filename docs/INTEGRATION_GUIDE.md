# Adopter Integration Guide

Audience: an operator integrating a service with an axon-enterprise
installation. After reading this you should be able to bootstrap your
client with **one configured environment variable** and discover
everything else at runtime — no out-of-band handover of issuer strings,
JWKS URLs, or audience values required.

> **Single env var contract.** The only configuration value Bemarking
> hands you out-of-band is the **base URL** of your axon-enterprise
> installation. Everything else (issuer, audience, JWKS, supported
> algorithms, registered Shield strategies, available SSO providers)
> is discoverable at runtime. If you find yourself receiving a private
> hostname, an S3 bucket name, or an internal environment label —
> stop. That is a regression of this contract; report it.

---

## TL;DR

```bash
# 1. The only thing your service needs to know:
export AXON_API_BASE="https://api.axon.example.com"

# 2. Discover everything else:
curl -s "$AXON_API_BASE/.well-known/openid-configuration" | jq .

# 3. Authenticate as a tenant user (or via SSO):
curl -s -X POST "$AXON_API_BASE/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email":"alice@acme.example","password":"...","tenant_id":"acme","totp_code":"123456"}'

# 4. Verify what your tenant has provisioned:
curl -s -H "Authorization: Bearer $JWT" \
     "$AXON_API_BASE/api/v1/tenant/me/integration-context/" | jq .
```

That is the whole bootstrap loop. The rest of this guide breaks down
each step and references the standards each endpoint implements.

---

## 1. Bootstrap — discover the integration parameters

Your service starts with one value: `AXON_API_BASE`. From that, fetch
the OIDC discovery document:

```python
import httpx

base = os.environ["AXON_API_BASE"]
disco = httpx.get(f"{base}/.well-known/openid-configuration").json()

issuer = disco["issuer"]
audience = disco["audience_supported"][0]
jwks_uri = disco["jwks_uri"]
signing_alg = disco["id_token_signing_alg_values_supported"][0]
```

The document is a standard **OIDC Connect Discovery 1.0** payload
([spec][oidc-disco]). Any compliant OIDC client library (`authlib`,
`python-jose`, `oidc-client-js`, `node-openid-client`) accepts the URL
and parses the rest itself.

If you prefer the broader **OAuth 2.0 Authorization Server Metadata**
([RFC 8414][rfc-8414]), the same data is published at
`/.well-known/oauth-authorization-server` with OAuth-specific fields
(`grant_types_supported`, `revocation_endpoint`, `token_endpoint_auth_methods_supported`).
The two documents agree on every shared field; consume whichever your
library expects.

Cache the discovery doc using its `Cache-Control` + `ETag`. Re-fetch on
boot or after restart; do not call it on every request.

[oidc-disco]: https://openid.net/specs/openid-connect-discovery-1_0.html
[rfc-8414]: https://datatracker.ietf.org/doc/html/rfc8414

---

## 2. Authenticate

axon-enterprise issues RS256-signed JWTs. Three flows are supported,
all returning the same JWT shape:

| Flow | Endpoint | When |
|---|---|---|
| Password + TOTP | `POST /api/v1/auth/login` | First-class users with credentials |
| Refresh token rotation | `POST /api/v1/auth/refresh` | Renew before expiry |
| OIDC SSO | `GET /api/v1/sso/oidc/initiate` | Federated identity (Google Workspace, Okta, …) |
| SAML SSO | `GET /api/v1/sso/saml/<tenant_id>/initiate` | Enterprise IdPs |

The JWT carries (at minimum): `iss`, `aud`, `sub`, `exp`, `iat`,
`tenant_id`, `email`, `roles`, `plan`. See `docs/JWT.md` for the full
claim contract and rotation semantics.

Verify the JWT against the `jwks_uri` and the `issuer` / `audience`
you read from discovery. Standard library example (`PyJWT`):

```python
from jwt import PyJWKClient
import jwt as pyjwt

jwks = PyJWKClient(jwks_uri, cache_keys=True, lifespan=600)
signing_key = jwks.get_signing_key_from_jwt(token).key

claims = pyjwt.decode(
    token,
    signing_key,
    algorithms=[signing_alg],
    issuer=issuer,
    audience=audience,
    options={"require": ["exp", "iat", "iss", "aud", "sub"]},
)
```

---

## 3. Inspect your tenant's integration context

Authenticated. The integration-context endpoint returns the parameters
visible to your tenant from your own perspective — useful for
populating an internal dashboard ("here is what is configured for us")
without contacting Bemarking.

```bash
curl -s -H "Authorization: Bearer $JWT" \
     "$AXON_API_BASE/api/v1/tenant/me/integration-context/"
```

```json
{
  "tenant_id": "acme",
  "plan": "enterprise",
  "auth": {
    "issuer": "https://api.axon.example.com",
    "audience": "axon-api",
    "expected_signing_alg": "RS256",
    "access_token_ttl_seconds": 3600
  },
  "discovery": {
    "openid_configuration": "https://api.axon.example.com/.well-known/openid-configuration",
    "oauth_authorization_server": "https://api.axon.example.com/.well-known/oauth-authorization-server",
    "jwks": "https://api.axon.example.com/.well-known/jwks.json"
  },
  "axon_enterprise_version": "1.4.0",
  "axon_integration_context_schema_version": "1.0"
}
```

RLS is enforced by construction: the response only ever surfaces your
own `tenant_id`. Cross-tenant introspection is impossible — there is
no request parameter for "give me a different tenant's context".

`Cache-Control: private, max-age=N` — intermediaries must not cache
across tenants. Your local client may cache for the indicated TTL;
re-fetch with `If-None-Match: <etag>` to receive a 304 when nothing
changed.

> Fields like per-tenant rate limits, feature flags, vertical pack
> subscriptions, and shield-category enforcement are not yet in the
> response — those data models do not exist in v1 of this endpoint.
> When they ship, they appear without a breaking change and the
> `axon_integration_context_schema_version` bumps from `1.0` to `1.1`.

---

## 4. Discover server capabilities

For SDK authors, ops dashboards, and any client that needs to adapt to
the server's runtime configuration:

```bash
curl -s "$AXON_API_BASE/.well-known/axon-capabilities.json"
```

```json
{
  "axon_enterprise_version": "1.4.0",
  "axon_lang_installed_version": "1.11.0",
  "sso_providers_supported": ["oidc", "saml"],
  "shield_strategies_supported": ["canary", "classifier", "dual_llm",
                                   "ensemble", "hmac", "pattern", "perplexity"],
  "shield_categories_supported": ["capability_validate", "code_injection",
                                   "data_exfil", "hallucination", "jailbreak",
                                   "model_theft", "pii_leak", "prompt_injection",
                                   "social_engineering", "toxicity",
                                   "training_poisoning"],
  "discovery_endpoints": {
    "openid_configuration": "/.well-known/openid-configuration",
    "oauth_authorization_server": "/.well-known/oauth-authorization-server",
    "jwks": "/.well-known/jwks.json",
    "capabilities": "/.well-known/axon-capabilities.json"
  },
  "axon_capabilities_schema_version": "1.0"
}
```

Every advertised value is introspected from a real source — nothing is
hardcoded. If a probe fails (axon-lang module unavailable, registry
not initialised), the corresponding field is `null` rather than a
fabricated default. Trust the `null` and degrade your client behaviour
accordingly.

---

## 5. Health checking + version

For Kubernetes / ECS / Nomad orchestrators and post-deploy verification:

| Endpoint | Purpose | Behaviour |
|---|---|---|
| `GET /healthz` | Liveness | Always 200 if the process is up. K8s will restart the container on failure. |
| `GET /livez` | Liveness (k8s-modern alias) | Identical to `/healthz`. Use whichever name your orchestrator prefers. |
| `GET /readyz` | Readiness | 200 when DB pool + critical deps are reachable; 503 otherwise. K8s will pull the pod from the load balancer (without restart) on failure. |
| `GET /version` | Build identity | JSON with `axon_enterprise_version`, `axon_lang_installed_version`, `python_version`, `build_sha`, `build_date`. Compare to your expected release after `kubectl rollout status`. |

Health endpoints **do not require authentication**. They are intended
to be hit thousands of times per minute by infrastructure probes; the
cost is intentionally negligible.

---

## 6. Cache and ETag discipline

Every well-known + discovery + version endpoint emits:

- `Cache-Control: public, max-age=600` (default; configurable)
- `ETag: "<sha256-hex>"` — strong ETag of the canonical JSON body
- `If-None-Match` request header → `304 Not Modified` with empty body

Use these. Polling discovery endpoints every minute without
`If-None-Match` wastes both your bandwidth and ours; conditional
requests are cheap and the spec is stable across most bumps.

The integration-context endpoint uses `Cache-Control: **private**,
max-age=600` because the body contains a tenant identifier and must
not be cached by shared intermediaries.

---

## 7. Interactive API reference

A full OpenAPI 3.1.0 specification of every documented endpoint lives at:

- **`GET /openapi.json`** — machine-readable spec (regenerated on every
  request from live mounts).
- **`GET /docs`** — Swagger UI (browser).
- **`GET /redoc`** — ReDoc (browser).

Generate a typed client in your language of choice from
`/openapi.json` using your favourite generator (`openapi-generator`,
`openapi-typescript`, `oapi-codegen`).

---

## 8. What we deliberately do not expose

The discovery surface is product-facing. It exposes **stable product
names** (DNS, audience strings, schema versions) — never internal
deployment artefacts (load balancer hostnames, S3 bucket names,
internal environment labels).

If your integration ever requires a value of one of those classes, it
is a sign that the discovery surface is missing a capability we should
add — not a sign that you should hardcode the value. Open an issue.

A CI drift gate enforces this contract on the server side; see the
`tests/discovery/test_discovery_drift_gate.py` suite for the exact
forbidden-substring list.

---

## 9. Endpoint reference (single page)

| Method + Path | Auth | Doc |
|---|---|---|
| `GET /.well-known/openid-configuration` | Public | OIDC Connect Discovery 1.0 |
| `GET /.well-known/oauth-authorization-server` | Public | RFC 8414 OAuth metadata |
| `GET /.well-known/jwks.json` | Public | JWKS (RFC 7517) — JWT signing keys |
| `GET /.well-known/axon-capabilities.json` | Public | axon-namespaced runtime capability advertisement |
| `GET /openapi.json` | Public | OpenAPI 3.1.0 spec |
| `GET /docs` | Public | Swagger UI |
| `GET /redoc` | Public | ReDoc |
| `GET /healthz` · `/livez` | Public | Liveness probe |
| `GET /readyz` | Public | Readiness probe |
| `GET /version` | Public | Build identity |
| `POST /api/v1/auth/login` | Public | Password + TOTP login |
| `POST /api/v1/auth/refresh` | Public | Refresh-token rotation |
| `POST /api/v1/auth/logout` | Public | Session revocation |
| `GET /api/v1/sso/oidc/initiate` | Public | Begin OIDC SSO |
| `GET /api/v1/sso/oidc/callback` | Public | OIDC callback |
| `GET /api/v1/tenant/me/integration-context/` | Bearer JWT | Tenant introspection (this guide §3) |
| `GET /api/v1/tenant/users/` | Bearer JWT | Tenant user management — see `PORTAL_API.md` |
| `GET /api/v1/tenant/api-keys/` | Bearer JWT | Tenant API key management — see `PORTAL_API.md` |
| `GET /api/v1/tenant/usage/` | Bearer JWT | Period usage — see `PORTAL_API.md` |
| `GET /api/v1/tenant/compliance/` | Bearer JWT | Compliance exports — see `PORTAL_API.md` |
| `GET /api/v1/primitives/` | Public | Closed catalogues + seeded registries |
| `POST /webhooks/stripe` | HMAC | Inbound Stripe billing events |

---

## 10. Versioning + deprecation policy

- Every discovery doc carries an `axon_*_schema_version` semver field.
- Additive changes (new fields, new enum values) bump **minor**: clients
  that ignore unknown fields keep working.
- Removals or semantic changes bump **major** and ship with a 90-day
  deprecation window announced in the `meta.deprecations` field of the
  affected doc.
- The HTTP API itself follows the same discipline: `/api/v1/*` is the
  current major; `/api/v2/*` would be additive and overlap before
  cutover.

---

## 11. Where to ask

- Spec questions, integration patterns: `docs/PORTAL_API.md`,
  `docs/JWT.md`, `docs/SSO.md` in this repository.
- Bugs, missing capabilities, or any field of this guide that does not
  match production: open an issue against `axon-enterprise`.

If a value you need is not discoverable here, that is feedback we want.
The integration surface is a product, not a chore.
