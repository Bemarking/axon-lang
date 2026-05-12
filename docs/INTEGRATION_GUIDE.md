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
| `GET /api/v1/tenant/diagnostics/recent` | Bearer JWT | Vertical-aware parse-error dashboard — see §10 (Fase 29.e, v1.15.0+) |
| `GET /api/v1/primitives/` | Public | Closed catalogues + seeded registries |
| `POST /webhooks/stripe` | HMAC | Inbound Stripe billing events |

---

## 10. Vertical Diagnostic Policy (v1.15.0+)

Audience: enterprise tenants on regulated verticals (HIPAA / legal /
fintech) integrating axon-enterprise with their CI / compliance
pipelines. Generic-vertical tenants get the OSS axon-lang Fase 28
diagnostic surface unchanged — this section is opt-in.

> **D9 ratified.** If your tenant has no registered vertical, every
> surface in this section behaves identically to the OSS baseline.
> No code changes required; ignore this section.

### 10.1 Tenant vertical resolution + default policies

Every tenant resolves to exactly one **vertical** drawn from the
closed catalog:

| Vertical | strict mode | telemetry | recovery | When to use |
|---|---|---|---|---|
| `generic` | off | off | on | Default for OSS-style tenants — OSS surface unchanged (D9). |
| `hipaa` | **on** | **on** | off | Healthcare (45 CFR Parts 160 + 164). Strict by default to avoid noisy diagnostic logs in CI surfacing PHI fragments. |
| `legal` | **on** | **on** | off | Legal (FRE / FRCP / ABA Model Rules). Strict by default to keep privilege-adjacent fragments out of CI artifacts. |
| `fintech` | off | **on** | on | Banking / payments / AML (BSA / OFAC / MiFID II). Recovery + telemetry-on for full diagnostic surface — auditors expect every error captured. |

Defaults derive from **D1 + D2** ratified 2026-05-12. Adopters can
override any field per-tenant via the diagnostic-policy override
surface (see §10.2).

#### How the vertical is set

Vertical assignment is operator-driven. The bootstrap path:

```python
from axon_enterprise.diagnostics import (
    TenantVertical,
    set_tenant_vertical,
    resolve_policy_for_vertical,
)

# At tenant-provisioning time (one-shot):
set_tenant_vertical("clinic-x", TenantVertical.HIPAA)

# Anywhere else in the codebase, the policy is resolved per-request:
policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
# policy.strict_mode      → True
# policy.telemetry_enabled → True
# policy.to_parse_args()   → ["--strict"]
```

`TenantVertical` is a closed `StrEnum`. Adding a fifth vertical
requires a compiler patch + CODEOWNERS sign-off per D7. The
registry is process-local in the in-tree implementation; production
deployments wrap with a DB-backed lookup.

### 10.2 Opting into / out of strict mode per vertical

D1 ratified default-strict for HIPAA + legal; D9 leaves generic
unchanged. Individual tenants can override at runtime via
`DiagnosticPolicy.with_override(...)`:

```python
from axon_enterprise.diagnostics import resolve_policy_for_vertical, TenantVertical

# Resolve the vertical default:
base_policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
# strict_mode=True, telemetry_enabled=True

# Override strict-off for this tenant (e.g. during a backfill window):
relaxed = base_policy.with_override(strict_mode=False)

# Pass the projection to axon-lang:
import subprocess
subprocess.run(["axon", "parse", "src/", *relaxed.to_parse_args()], check=True)
```

`with_override(...)` returns a **new** `DiagnosticPolicy` instance
(frozen + slots). The original is untouched; concurrent requests
see no race.

The **vertical** itself is not overridable through this path —
changing a tenant's vertical is a tenant-management operation (set
through `set_tenant_vertical` at provisioning, not per-request).
This separation prevents accidental cross-vertical drift.

### 10.3 Configuring the telemetry sink

Every parser error emitted by `axon parse` for a tenant whose
policy has `telemetry_enabled=True` fans out to **three sinks** in
parallel (D2 ratified):

1. **OpenTelemetry span** under `axon.diagnostics.parse_error`
   with attributes `axon.tenant_id`, `axon.vertical`,
   `axon.severity`, `axon.error.code`, `axon.file`, `axon.line`,
   `axon.column`. Reuses the existing OTel pipeline configured by
   `axon_enterprise.observability.tracing`.

2. **Prometheus counter** `axon_parser_errors_total{tenant_id,
   vertical, code}`. Labels are bounded-cardinality; file path and
   line number are NOT label dimensions (explodes per-tenant
   series).

3. **Audit-log entry** of type `compliance:parse_error`
   (HMAC-chained per tenant via the existing audit_engine path).
   Payload: file path + line + column + error code + severity ONLY.

> **D4 privacy boundary (ratified).** No sink EVER carries source
> text. The privacy guarantee is baked into the `ParserDiagnostic`
> type — it has no `source` / `snippet` / `content` / `text` /
> `body` field. Even a future PR that adds a leak vector breaks
> the type-level assertion + the corpus drift gate fails.

#### Wiring the sink at app bootstrap

The telemetry sink emits via an injectable `AuditSink` Protocol.
Production deployments wire the real audit service; bootstrap
and tests use the in-memory adapter:

```python
from axon_enterprise.diagnostics import StoreBackedAuditSink, set_audit_sink
from axon_enterprise.diagnostics.store import get_default_store

# At app startup:
set_audit_sink(StoreBackedAuditSink(get_default_store()))
```

Once wired, every `emit_parser_error(diagnostic)` call fans out to
all three sinks automatically when the resolved policy has
`telemetry_enabled=True`. Telemetry is silenced for generic
tenants (D9) — no code path runs.

### 10.4 Consuming `/api/v1/tenant/diagnostics/recent`

The dashboard endpoint returns recent parse diagnostics for the
authenticated tenant. Auth via existing tenant-context middleware
(Q4 ratified — no new RBAC slug introduced).

```bash
# Aggregated mode (default) — groups by (file, code, line-bucket):
curl -s -H "Authorization: Bearer $JWT" \
     "$AXON_API_BASE/api/v1/tenant/diagnostics/recent?limit=50" | jq .

# Raw mode — one entry per diagnostic:
curl -s -H "Authorization: Bearer $JWT" \
     "$AXON_API_BASE/api/v1/tenant/diagnostics/recent?aggregated=false&limit=200" | jq .

# Pagination — pass the last_seen from the previous response as `since`:
curl -s -H "Authorization: Bearer $JWT" \
     "$AXON_API_BASE/api/v1/tenant/diagnostics/recent?since=2026-05-12T10:00:00%2B00:00"
```

#### Response shape (aggregated)

```json
{
  "tenant_id": "clinic-x",
  "vertical": "hipaa",
  "mode": "aggregated",
  "bucket_size": 10,
  "limit": 50,
  "entries": [
    {
      "file_path": "src/cds_flow.axon",
      "code": "AX-0042",
      "line_bucket": 10,
      "vertical": "hipaa",
      "count": 7,
      "first_seen": "2026-05-12T09:14:22+00:00",
      "last_seen":  "2026-05-12T09:32:01+00:00"
    }
  ]
}
```

#### Response shape (raw)

```json
{
  "tenant_id": "clinic-x",
  "vertical": "hipaa",
  "mode": "raw",
  "limit": 200,
  "entries": [
    {
      "code": "AX-0042",
      "file_path": "src/cds_flow.axon",
      "line": 17,
      "column": 4,
      "vertical": "hipaa",
      "severity": "error",
      "timestamp": "2026-05-12T09:32:01+00:00"
    }
  ]
}
```

#### Query parameters

| Param | Default | Range | Mode |
|---|---|---|---|
| `since` | (none) | ISO-8601 timestamp | both |
| `limit` | 50 | 1–500 | both |
| `aggregated` | `true` | `true` / `false` | both |
| `bucket_size` | 10 | 1–1000 | aggregated only |
| `file_path` | (none) | equality | raw only |
| `code` | (none) | equality | raw only |

#### Privacy posture (D4)

The response **NEVER** carries source text. Even when the dashboard's
underlying store hypothetically captures additional fields, the
projection layer only emits the declared structural keys. If you
need source context for an error, fetch it from your repo via
existing access controls — the diagnostic surface is intentionally
metadata-only.

### 10.5 Installing the CI compliance gate

The vertical compliance gate (29.f) wraps `/api/v1/tenant/diagnostics/recent`
+ a configurable threshold into a GitHub Actions composite action.
Adopters install via one line in their workflow file (**Q5
ratified** — composite action, not reusable workflow):

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  axon-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Run axon-lang's `axon parse` to populate the dashboard.
      - run: axon parse src/

      # Gate: fail the build if any parse error sat in the dashboard
      # for the last hour (anything before that is older state, not
      # this PR's fault).
      - uses: Bemarking/axon-enterprise/.github/actions/axon-enterprise-ci-gate@v1.15.0
        with:
          endpoint: ${{ vars.AXON_ENTERPRISE_ENDPOINT }}
          token: ${{ secrets.AXON_ENTERPRISE_TOKEN }}
          max-errors: 0
          since: 1h
```

> **Adopters MUST pass the token via `${{ secrets.* }}`, NOT
> hard-coded.** The composite action's `token` input has no
> default — workflows that omit it fail at validation time.

#### Action inputs (full reference)

| Input | Required | Default | Notes |
|---|---|---|---|
| `endpoint` | yes | — | Base URL of axon-enterprise (e.g. `https://api.example.com`). |
| `token` | yes | — | Bearer JWT for the authenticated tenant. **Use `${{ secrets.* }}`.** |
| `max-errors` | no | `0` | Maximum error-severity diagnostics before the gate fails. |
| `max-warnings` | no | (none) | Maximum warning-severity diagnostics. Empty disables the warning threshold. |
| `fail-on-hint` | no | `false` | Fail when ANY hint-severity diagnostic is present. |
| `since` | no | (none) | ISO-8601 timestamp OR relative duration (`30m`, `2h`, `1d`). |
| `mode` | no | `aggregated` | `aggregated` or `raw`. |
| `limit` | no | `500` | Dashboard fetch size; 1–500. |
| `bucket-size` | no | `10` | Line-bucket size for aggregated mode; 1–1000. |
| `python-version` | no | `3.13` | Python version for the action's CLI step. |
| `axon-enterprise-version` | no | (latest) | Pin a specific axon-enterprise CLI version. |
| `json-output` | no | `false` | Emit machine-readable JSON instead of the human summary. |

#### Outputs

| Output | Values |
|---|---|
| `verdict` | `pass` / `fail_exceeded` / `fail_input` |
| `exit-code` | `0` / `1` / `2` (matches the closed `GateVerdict.exit_code` projection) |

#### Exit codes (closed catalog)

| Exit | Meaning |
|---|---|
| `0` | Gate passed — diagnostics ≤ thresholds. |
| `1` | Gate failed — diagnostics exceed threshold. CI fails. |
| `2` | Configuration / transport error (auth failure, malformed payload, server 5xx, DNS failure). Treat as build infrastructure issue, not compliance failure. |

#### Running the gate locally

The composite action wraps `axon-enterprise diagnostics gate`. To
run the same gate locally during development:

```bash
export AXON_ENTERPRISE_ENDPOINT="https://api.example.com"
export AXON_ENTERPRISE_TOKEN="$(< ~/.axon-token)"

axon-enterprise diagnostics gate \
    --max-errors 0 \
    --since 1h
```

### 10.6 Common vertical-suggest patterns

Each regulated vertical ships a curated **suggest dictionary**
(D3 ratified) that extends axon-lang's Levenshtein `'Did you
mean X?'` hints with vertical-specific terminology. The
dictionaries live in version control at
`axon_enterprise/diagnostics/dicts/<vertical>.json`; updates ship
as PRs labeled `vertical-dict:<vertical>` with CODEOWNERS sign-off
per D7.

| Vertical | Term count | Sample terms | Anchored to |
|---|---|---|---|
| `hipaa` | 52 | `phi`, `ephi`, `covered_entity`, `safe_harbor`, `business_associate` | 45 CFR Parts 160 + 164, Safe Harbor §164.514(b)(2), PSQIA |
| `legal` | 51 | `fre_502`, `fre_408`, `attorney_client_privilege`, `work_product`, `litigation_hold` | Upjohn, Hickman, FRE 408/502/801/901, FRCP 26-65, ABA Model Rules |
| `fintech` | 51 | `kyc`, `ofac`, `sdn`, `pci_req_10`, `iban`, `bic`, `swift` | BSA / USA PATRIOT §§311-314, FinCEN SAR/CTR, FATF, PCI DSS, ISO 13616/9362/20022 |

Every entry carries a `provenance` field — explicit URL or
canonical regulatory reference. D3 ratified: empty provenance
fails the loader at module-load time AND fails the corpus drift
gate in CI.

#### Wiring suggest hints into your build

```python
from axon_enterprise.diagnostics import (
    TenantVertical,
    resolve_policy_with_dict_for_vertical,
)

# Resolve the policy + load the vertical dictionary in one call:
policy = resolve_policy_with_dict_for_vertical(TenantVertical.HIPAA)

# `policy.extra_keywords` now carries the vertical's term tuple;
# pass it to your parser-invocation wrapper to merge into the
# Levenshtein hint dictionary.
for keyword in policy.extra_keywords:
    register_suggest_keyword(keyword)  # adopter-side wiring
```

The dictionary is loaded once per process and cached; subsequent
calls return the same instance (the wrapper layer pays no
overhead).

#### Inspecting provenance for an audit

```python
from axon_enterprise.diagnostics import load_vertical_dictionary, TenantVertical

dictionary = load_vertical_dictionary(TenantVertical.HIPAA)
for entry in dictionary.entries:
    if entry.term == "phi":
        print(entry.provenance)
        # "45 CFR §160.103 — Protected Health Information definition"
```

Every term's provenance is traceable to the regulatory source it
was curated from. Compliance auditors can replay the full chain
from a deployed dictionary back to the published regulation.

### 10.7 D-letter index (operational summary)

The behavioral contract above is locked at the engineering process
level by ten ratified D-letters. Adopters citing these in audit
artifacts:

| D-letter | Locks |
|---|---|
| **D1** | HIPAA + legal default-strict; fintech recovery + telemetry-on; generic OSS surface unchanged. |
| **D2** | Three-sink telemetry shape (OTel + Prom + audit). Opt-out via existing tenant-settings toggles. |
| **D3** | Vertical-suggest dictionary entries MUST carry provenance. Updates via PR review. |
| **D4** | No source text in any sink, response, or audit-log payload. Enforced at the type level. |
| **D5** | CI gate runs at integration time; axon-lang's `axon parse` contract is unchanged. |
| **D6** | Telemetry retention follows existing per-tenant policy. |
| **D7** | Vertical-suggest dictionary updates require CODEOWNERS sign-off from the respective vertical's reviewer. |
| **D8** | Vertical X policy / dictionary / telemetry NEVER affects vertical Y tenants. Multi-tenant safety. |
| **D9** | Generic tenants get the OSS axon-lang Fase 28 surface verbatim. This entire section is invisible to them. |
| **D10** | Extend the existing INTEGRATION_GUIDE; no new file. This section IS the canonical adopter doc for Fase 29. |

The full plan vivo (with sub-fase shipped status + commit hashes
+ test counts) lives upstream in axon-lang at
`docs/fase_29_enterprise_diagnostic_enhancements.md`.

---

## 11. Versioning + deprecation policy

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

## 12. Where to ask

- Spec questions, integration patterns: `docs/PORTAL_API.md`,
  `docs/JWT.md`, `docs/SSO.md` in this repository.
- Bugs, missing capabilities, or any field of this guide that does not
  match production: open an issue against `axon-enterprise`.

If a value you need is not discoverable here, that is feedback we want.
The integration surface is a product, not a chore.
