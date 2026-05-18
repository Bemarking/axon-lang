# AXON Adopter REST Guide

> **Audience:** engineers building HTTP REST APIs on top of axon-lang —
> from a hobbyist `axonendpoint Chat { … }` chat-with-llm app to a
> banking team deploying a SOC 2-audited credit decision pipeline.
>
> **Scope:** the full Fase 32 surface introduced in axon-lang **v1.23.0**.
> Every `axonendpoint` declaration in your deployed source produces a
> **first-class HTTP REST route** at the declared `(method, path)` with
> body validation, output validation, per-endpoint transport, Stripe-
> compatible Idempotency-Key, capability-based auth scope, and
> regulator-grade replay binding.
>
> **Founder principle:** *the declarative source IS the HTTP behavior.*
> An auditor reading your `.axon` file knows the contract verbatim —
> the runtime honors every declaration. No middleware-of-middleware.

---

## Table of Contents

1. [What changed in v1.23.0](#what-changed-in-v1230)
2. [Your first axonendpoint REST route](#your-first-axonendpoint-rest-route)
3. [The axonendpoint declaration — every field](#the-axonendpoint-declaration--every-field)
4. [Body schema validation (`body: T`, D4)](#body-schema-validation-body-t-d4)
5. [The Request Binding Contract (v1.36.0)](#the-request-binding-contract-v1360)
6. [Output schema validation (`output: T`, D5)](#output-schema-validation-output-t-d5)
7. [Per-endpoint transport on dynamic routes (D6)](#per-endpoint-transport-on-dynamic-routes-d6)
8. [Idempotency-Key — Stripe-compatible retries (D7)](#idempotency-key--stripe-compatible-retries-d7)
9. [Auth scope — `requires:` field (D8)](#auth-scope--requires-field-d8)
10. [Replay-token binding — regulator-grade audit (D9)](#replay-token-binding--regulator-grade-audit-d9)
11. [Multi-endpoint deployment + path collision diagnostics (D2)](#multi-endpoint-deployment--path-collision-diagnostics-d2)
12. [EventSource on arbitrary paths](#eventsource-on-arbitrary-paths)
13. [Vertical cookbook — banking, government, legal, medicine](#vertical-cookbook--banking-government-legal-medicine)
14. [Backwards compatibility — `/v1/execute` preserved (D10)](#backwards-compatibility--v1execute-preserved-d10)
15. [Production deployment checklist](#production-deployment-checklist)
16. [Troubleshooting](#troubleshooting)
17. [Cross-stack contract: Python ↔ Rust (D11)](#cross-stack-contract-python--rust-d11)
18. [Four-pillar trace](#four-pillar-trace)
19. [Where to file bugs](#where-to-file-bugs)

---

## What changed in v1.23.0

Pre-v1.23.0, every axonendpoint multiplexed through `POST /v1/execute`
with the flow name in the request body. Adopters wrote `path: "/chat"`
in their source, but the runtime never registered that path as a real
route — it was decorative metadata. The Kivi adopter case 2026-05-11
(8 version iterations 1.16.2 → 1.22.0) surfaced this gap empirically.

v1.23.0 closes it: every `axonendpoint` declaration produces exactly
one HTTP route at the declared `(method, path)`, with the full
declarative contract honored end-to-end.

| Surface | v1.22.x | v1.23.0 |
|---|---|---|
| `axonendpoint Chat { path: "/chat" }` | Decorative metadata; route never registered | **Registered as `POST /chat`** — Kivi case closed at the wire layer |
| `body: T` declaration | No runtime effect | **400 Bad Request** with structured diagnostic on schema violation |
| `output: T` declaration | No runtime effect | OWASP-safe **500** to client + full diagnostic in `audit_log` on flow output violation |
| `transport: sse` on `/v1/execute` | Honored | **Honored on declared path too** — `POST /chat` returns `text/event-stream` |
| `keepalive: 5s/15s/30s/60s` | Honored on `/v1/execute/sse` | **Honored on declared path too** |
| `Idempotency-Key: <uuid>` header | Ignored | **Stripe-compatible** — `same_key + same_body ⟹ byte-identical replay` within 24h retention |
| `requires: [bank.officer]` declaration | New field — parsed but no enforcement | **403 Forbidden** when bearer's `capabilities` claim doesn't satisfy the declared list |
| `replay: true | false` declaration | New field — parsed but no enforcement | Every successful 2xx POST/PUT writes a replay binding; auditors retrieve via `GET /v1/replay/<trace_id>` |
| `X-Axon-Trace-Id` response header | — | **Attached on every dynamic-route response** — correlation anchor between client logs, server audit, replay retrieval |
| `POST /v1/execute` legacy path | The only entry point | **Preserved verbatim (D10)** — coexists with dynamic routes |

---

## Your first axonendpoint REST route

```axon
flow Echo(message: String) -> String {
    let result = message
    return result
}

axonendpoint EchoEndpoint {
    method:  POST
    path:    "/echo"
    execute: Echo
}
```

Deploy:

```bash
curl -X POST http://localhost:8000/v1/deploy \
  -H "Content-Type: application/json" \
  -d '{"source_file": "echo.axon", "source": "..."}'
```

Call the endpoint:

```bash
curl -X POST http://localhost:8000/echo \
  -H "Content-Type: application/json" \
  -d '{}'
```

You'll get back a JSON response from the `Echo` flow + an
`X-Axon-Trace-Id: <uuid>` header. The path `/echo` is real — the
runtime registered it at deploy time.

---

## The axonendpoint declaration — every field

```axon
axonendpoint LoanDecision {
    method:    POST                              // D3: GET | POST | PUT | DELETE | PATCH
    path:      "/loan/decision"                  // D1: real HTTP path
    body:      LoanApplication                   // D4: request body schema
    output:    Decision                          // D5: response body schema
    execute:   ApproveOrDeny                     // the flow that runs
    transport: json                              // D6: json | sse | ndjson
    keepalive: 15s                               // D6: only for sse/ndjson
    requires:  [bank.officer]                    // D8: capability list (AND semantics)
    replay:    true                              // D9: write replay binding
    compliance: [PCI_DSS, SOC_2]                 // ESK Fase 6.1: regulatory annotations
    retries:   2                                 // legacy field
    timeout:   10s                               // legacy field
    shield:    EdgeShield                        // optional ESK shield
}
```

Every field is optional except `method`, `path`, and `execute`. Omitted
fields fall back to documented defaults — see each section below for
the per-field semantics + the D-letter that ratifies the contract.

---

## Body schema validation (`body: T`, D4)

When you declare `body: T`, every accepted request body MUST match
`T`'s declared shape. The runtime validates BEFORE flow dispatch;
malformed bodies never reach the flow.

```axon
type Money {
    amount: Float
    currency: String
}

type LoanApplication {
    amount: Money
    applicant: String
    purpose: String?       // optional field
}

axonendpoint LoanDecision {
    method:  POST
    path:    "/loan/decision"
    body:    LoanApplication
    execute: ApproveOrDeny
}
```

**Accepted body:**

```json
{
  "amount": {"amount": 50000.0, "currency": "USD"},
  "applicant": "Alice Citizen"
}
```

**Rejected body (`amount` as raw number instead of `Money` struct):**

```json
{"amount": 50000, "applicant": "Alice Citizen"}
```

→ `400 Bad Request`:

```json
{
  "error": "body_schema_violation",
  "expected_type": "LoanApplication",
  "field_path": "amount",
  "expected": "Money",
  "got": "integer",
  "hint": "Body field `amount` must be a `Money` (JSON object) but received a integer.",
  "d_letter": "D4"
}
```

The `field_path` is dotted for nested structs and bracket-indexed for
list elements (`symptoms[2].score` for the third element of a `List<
Symptom>` field's `score` sub-field).

### Supported type shapes

| Declared type | Accepts | Rejects |
|---|---|---|
| `String` | JSON string | anything else |
| `Integer` | JSON integer | floats, booleans, strings |
| `Float` | JSON integer or fractional number | booleans, strings |
| `Boolean` | `true` / `false` | strings even if `"true"` |
| `Duration` | JSON string (semantic parsing at runtime) | anything else |
| `Any` | any JSON value | nothing — universal accept |
| `List<X>` | JSON array; every element validated against `X` | non-arrays |
| `RiskScore` / `ConfidenceScore` | JSON number ∈ [0, 1] | out-of-range, non-numeric |
| `SentimentScore` | JSON number ∈ [-1, 1] | out-of-range, non-numeric |
| `type T { … }` (declared) | JSON object with every declared field | missing required field, type mismatch on any field |

**Postel's Law extras:** unknown fields in a structured body are
silently accepted (clients can pass extra payload the flow ignores).
Strict-mode rejection is a future opt-in.

**D9 backwards-compat:** omit `body:` and the endpoint accepts free-
form JSON. Existing v1.22.x axonendpoints without `body:` declarations
keep current behavior.

---

## The Request Binding Contract (v1.36.0)

Schema validation (above) checks that a request body *matches* `T`.
The **Request Binding Contract** is the next step: the body's fields
**populate the parameters of the flow** the endpoint executes.

An AI agent is a function of its input. The canonical agent flow —
retrieve context → deliberate → persist — is *parametric*: it takes a
`message`, a `session_id`, a `tenant_id`. Those parameters arrive in
the request body. v1.36.0 makes the binding from one to the other a
**typed, compile-time-proven, runtime-delivered contract**.

```axon
type ChatRequest {
    message:    String
    session_id: String
    tenant_id:  String
}

axonstore mem { backend: in_memory }

flow ChatFlow(message: String, session_id: String, tenant_id: String) -> Unit {
    retrieve mem { where: "tenant_id" as: history }
    step Deliberate {
        ask: "Tenant ${tenant_id}, session ${session_id}: ${message}"
        output: Stream<Token>
    }
    persist into mem { session: "${session_id}" reply: "${Deliberate}" }
}

axonendpoint Chat {
    method:  POST
    path:    "/api/chat"
    body:    ChatRequest
    execute: ChatFlow
    transport: sse
}
```

`POST /api/chat` with `{"message": "…", "session_id": "…",
"tenant_id": "…"}` binds each field to the same-named flow parameter.
`${tenant_id}`, `${session_id}`, `${message}` then interpolate
everywhere downstream — `where:` clauses, step `ask:` prompts,
`persist`/`mutate` field blocks.

### What the contract guarantees

- **Binding by name (D1).** A body field binds to the flow parameter
  of the *same name*. The runtime delivers it identically on the
  `transport: sse` and `transport: json` routes.

- **Compile-time totality (D2).** The type-checker proves *every*
  required parameter of `execute: F` is covered by a same-named,
  type-compatible field of `body: T`. An uncovered required parameter
  is a **compile error** at `axon check` and `POST /v1/deploy` — not
  a runtime surprise:

  ```
  error: axonendpoint 'Chat' executes flow 'ChatFlow' whose required
  parameter 'tenant_id: String' has no matching field in body type
  'ChatRequest' …
  ```

  This is what no mainstream framework offers — FastAPI, Spring
  `@RequestBody`, NestJS DTOs all discover a missing field at runtime
  (a `KeyError`, an `undefined`). AXON proves the binding total
  *before the endpoint can deploy*. An optional parameter
  (`note: String?`) is exempt — it need not be covered.

- **Untrusted by birth (D3).** A value that crossed the network
  boundary is `Untrusted`. Where a `${param}` reaches a store `where:`
  clause it is compiled to a **`$N` bind parameter** — never spliced
  into the filter source. A value carrying `'`, `;`, `--`, or
  `OR '1'='1'` cannot inject: it is data, bound out-of-band. OWASP A03
  is closed by construction, not by developer discipline.

- **Only declared parameters bind (D4).** A body field that matches no
  declared flow parameter is *not* injected into the interpolation
  scope — so a typo'd `${tenat_id}` is a missing binding the totality
  check catches, never a silently-empty surprise.

### Backwards compatibility

A flow with no parameters behind an endpoint with no `body:` is
unchanged. `/v1/execute` is unchanged. The binding is purely additive
(D5). Full upgrade detail: `docs/MIGRATION_v1.36.md`.

---

## Output schema validation (`output: T`, D5)

Symmetric of `body:`. When you declare `output: T`, the runtime
validates the flow's response against `T` BEFORE returning to the
client. Violation → **GENERIC 500** to the client (OWASP — schema
details never leak) + **full diagnostic in `audit_log`** for adopter
inspection.

```axon
axonendpoint LoanDecision {
    method:  POST
    path:    "/loan/decision"
    body:    LoanApplication
    output:  Decision
    execute: ApproveOrDeny
}
```

When the flow returns something other than a `Decision`:

**Client sees** (no schema details — recon-vector hardening):

```json
{
  "error": "internal_validation_error",
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "hint": "The flow produced a response that did not match the declared output schema. The adopter-facing diagnostic is in the audit trail (GET /v1/audit).",
  "d_letter": "D5"
}
```

**Audit log captures**:

```json
{
  "event": "output_schema_violation",
  "endpoint": "LoanDecision",
  "flow_name": "ApproveOrDeny",
  "method": "POST",
  "path": "/loan/decision",
  "expected_type": "Decision",
  "field_path": "approved",
  "expected": "Boolean",
  "got": "string",
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "d_letter": "D5"
}
```

The `trace_id` correlates client log ↔ audit ↔ replay retrieval (see
[§9](#replay-token-binding--regulator-grade-audit-d9)).

**SSE/ndjson responses bypass** the gate — streaming wire format
can't be validated against a static type at the wire layer.

---

## Per-endpoint transport on dynamic routes (D6)

The Fase 30/31 negotiation matrix applies uniformly to dynamic routes:

| `transport:` declared? | flow has stream effects? | strict mode? | Client `Accept: text/event-stream`? | Wire format |
|---|---|---|---|---|
| `sse` or `ndjson` | * | * | * | **SSE** (D5 declared) |
| `json` | * | * | * | **JSON** (D3 sacred opt-out) |
| omitted | yes (inference fires) | yes | * | **SSE** (D1 inference) |
| omitted | yes | no | yes | **SSE** (D4 fallback) |
| omitted | yes | no | no | **JSON** (D9 legacy) |
| omitted | no | * | * | **JSON** |

The matrix is per-route, not per-flow. Two axonendpoints sharing a
flow but declaring different transports each honor their own
contract.

### Keepalive

When `transport: sse` is declared (or inferred), an optional
`keepalive: 5s | 15s | 30s | 60s` controls the SSE comment-line
heartbeat. Default 15s. See [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md)
for the full SSE wire-format spec.

---

## Idempotency-Key — Stripe-compatible retries (D7)

Banking-grade primitive. The contract: **same_key + same_body ⟹
byte-identical response within the 24h retention window**.

```http
POST /loan/decision HTTP/1.1
Content-Type: application/json
Idempotency-Key: 7f6a8c2e-0b4d-4e8a-9c1f-3d5b7e9a0c1f
Authorization: Bearer <jwt>

{"amount": {"amount": 50000, "currency": "USD"}, "applicant": "Alice"}
```

| Scenario | Response |
|---|---|
| First request with key | Execute + cache. Return `200 OK` with body. |
| Repeat with same key AND same body | Replay cached body verbatim + `Idempotency-Status: replayed` response header. |
| Repeat with same key AND **different** body | `422 Unprocessable Entity` with `idempotency_key_reused_with_different_request` |
| Request without key | Normal execute; no caching. |
| Key on GET/DELETE | Header ignored (HTTP-spec idempotent). |

### Cross-tenant isolation

Cache key = `(client_id, endpoint_path, idempotency_key)`. Two tenants
cannot collide on the same Idempotency-Key value because the client_id
(from `Authorization: Bearer`) namespaces every entry.

### Conflict diagnostic (422 envelope)

```json
{
  "error": "idempotency_key_reused_with_different_request",
  "idempotency_key": "7f6a8c2e-0b4d-4e8a-9c1f-3d5b7e9a0c1f",
  "endpoint": "LoanDecision",
  "method": "POST",
  "path": "/loan/decision",
  "cached_body_hash_prefix": "a1b2c3d4e5f60718",
  "hint": "The Idempotency-Key was previously used with a DIFFERENT request body for this endpoint. Generate a new key for the new request, or send the same body to replay the original response.",
  "d_letter": "D7"
}
```

The `cached_body_hash_prefix` is the first 8 bytes of the SHA-256 hash
(hex) — sufficient for adopter correlation, doesn't leak the full
hash (defense-in-depth).

**Body hashing is whitespace-sensitive** — matches Stripe's documented
behavior. Clients that want semantic equality must canonicalize on
their side.

---

## Auth scope — `requires:` field (D8)

Declare the capability slugs the request bearer MUST hold for the
endpoint to dispatch (AND semantics — every declared slug must be
present in the bearer's `capabilities` JWT claim).

```axon
axonendpoint AdminPolicyUpdate {
    method:   POST
    path:     "/admin/policy"
    body:     PolicyUpdate
    requires: [admin, policy.write]   // bearer must have BOTH
    execute:  ApplyPolicyUpdate
}
```

### Closed slug grammar

`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` — dot-separated lowercase
identifiers starting with a letter. Examples valid: `admin`,
`legal.read`, `hipaa.phi.read`, `bank.officer.senior`. Invalid:
`Admin` (uppercase), `bank-officer` (hyphen), `1admin` (digit first).
Invalid slugs are rejected at **parse time** with adopter-actionable
diagnostic.

### 403 deny envelope

```json
{
  "error": "missing_capability",
  "missing": ["policy.write"],
  "required": ["admin", "policy.write"],
  "have": ["admin"],
  "endpoint": "AdminPolicyUpdate",
  "method": "POST",
  "path": "/admin/policy",
  "hint": "Bearer is missing capabilities [\"policy.write\"] required by axonendpoint 'AdminPolicyUpdate'. Reissue the bearer with the declared capabilities or contact the endpoint's owner to grant access.",
  "d_letter": "D8"
}
```

### Auth gate fires BEFORE idempotency lookup

Information-leak hardening: an unauthorized client cannot distinguish
"key cached" from "key absent" because the auth gate rejects them
before the cache is consulted.

### OSS vs enterprise

- **OSS**: capabilities are read from the JWT bearer's
  `capabilities` claim via unverified base64 decode. Production
  deployments layer signature verification via the existing
  `tenant_extractor_middleware` when `AXON_JWT_JWKS_URL` is set.
- **Enterprise** (Fase 21 integration surface): capabilities are
  registered + version-introspected via `/.well-known/axon-capabilities`;
  auditors verify the runtime's capability set matches the deployed
  source.

---

## Replay-token binding — regulator-grade audit (D9)

Every successful 2xx POST/PUT response writes a replay binding keyed
by `trace_id`. Auditors retrieve the recorded (request body, response
body, metadata) tuple via `GET /v1/replay/<trace_id>` — the foundation
of audit-defensible AI in regulated production (PCI DSS Req 10,
FedRAMP AU-2, FRE 502, 21 CFR Part 11).

### Default semantics

| Method | Default `replay` | Override via |
|---|---|---|
| POST | **true** | `replay: false` |
| PUT | **true** | `replay: false` |
| GET | **false** | `replay: true` |
| DELETE | **false** | `replay: true` |

### Retrieval

```http
GET /v1/replay/f47ac10b-58cc-4372-a567-0e02b2c3d479
Authorization: Bearer <jwt-with-read-only-auth>
```

Response:

```json
{
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "timestamp_ms": 1715459123000,
  "endpoint_name": "LoanDecision",
  "flow_name": "ApproveOrDeny",
  "method": "POST",
  "path": "/loan/decision",
  "client_id": "Bearer eyJ…",
  "capabilities_used": ["bank.officer"],
  "request_body_hash_hex": "…",
  "request_body_base64": "…",
  "response_status": 200,
  "response_body_hash_hex": "…",
  "response_body_base64": "…",
  "response_content_type": "application/json",
  "model_version": "axon.runtime.dynamic_route.v1",
  "deterministic": true
}
```

Response header: `Replay-Status: deterministic | non_deterministic`
per backend determinism.

### Skip conditions

The runtime does NOT write a binding for:
- Non-2xx responses (errors aren't typed flow output).
- SSE/ndjson responses (streaming wire format; per-event token chain
  is a future fase).
- GET/DELETE without explicit `replay: true`.

### Deterministic vs non-deterministic

| Backend | `deterministic` flag |
|---|---|
| `stub` | `true` |
| LLM backends (anthropic, openai, gemini, …) | `false` by default |
| Locked-model with seed + temperature=0 | `true` (via enterprise layer) |

For deterministic backends, an auditor can re-execute the original
request body and confirm byte-identical response → regulatory replay
primitive.

### Retention

30 days default; in-memory + capacity-bounded LRU (10k entries).
Enterprise persistence backends extend retention indefinitely + add
HMAC chain sealing per tenant.

---

## Multi-endpoint deployment + path collision diagnostics (D2)

Two axonendpoints with the same `(method, path)` tuple fail at deploy
time:

```axon
axonendpoint One { method: POST path: "/x" execute: Foo }
axonendpoint Two { method: POST path: "/x" execute: Bar }
```

`POST /v1/deploy` returns:

```json
{
  "success": false,
  "error": "Path collision (D2): axonendpoint 'One' and 'Two' both declare `method: POST path: /x`. Resolve by editing one of the two axonendpoints to use a distinct (method, path) tuple.",
  "phase": "route_registration",
  "d_letter": "D2"
}
```

Cross-deploy collisions (deploying a NEW source with `POST /x` while a
different axonendpoint already owns it from a prior deploy) fire the
same diagnostic.

**Different methods, same path**: NO collision. `GET /x` and `POST /x`
are distinct routes per HTTP semantics.

---

## EventSource on arbitrary paths

Browsers' EventSource API works directly against declared paths when
the endpoint declares `transport: sse`:

```javascript
const evt = new EventSource("https://api.example.com/chat");
evt.onmessage = (e) => console.log(e.data);
```

Where the source has:

```axon
axonendpoint Chat {
    method:    POST
    path:      "/chat"
    execute:   StreamingChat
    transport: sse
    keepalive: 15s
}
```

EventSource sends `Accept: text/event-stream` automatically; the
`transport: sse` declaration honors it. See
[ADOPTER_STREAMING.md](ADOPTER_STREAMING.md) for the full
EventSource client recipe.

---

## Vertical cookbook — banking, government, legal, medicine

Each canonical pattern below is regression-tested via
`axon-rs/tests/fase32_vertical_patterns.rs` (4/4 E2E green) and
defended against the listed regulatory framework.

### Banking (PCI DSS Req 10 + SOC 2 CC6)

```axon
type Money { amount: Float currency: String }
type Person { full_name: String ssn_last4: String }
type LoanApplication { amount: Money applicant: Person }
type Decision { approved: Boolean basis: String }

flow ApproveOrDeny() -> String { let result = "approved" return result }

axonendpoint LoanDecision {
    method:   POST
    path:     "/loan/decision"
    body:     LoanApplication
    output:   Decision
    execute:  ApproveOrDeny
    requires: [bank.officer]
    replay:   true
}
```

**What an auditor inspecting this surface knows:**
- The endpoint serves `POST /loan/decision`.
- Bodies must satisfy `LoanApplication` — any other shape rejected at 400.
- Bearer must hold `bank.officer` capability — missing → 403.
- Every successful decision is registered in the replay log →
  `GET /v1/replay/<trace_id>` retrieves the exact (request, response,
  capabilities_used) tuple for PCI audit.
- Idempotency-Key supported — banking clients retry safely on flaky
  networks (Stripe / Plaid pattern industry-standard).

### Government (FedRAMP AU-2 + FISMA)

```axon
type BenefitsClaim { citizen_id: String claim_type: String }
type EligibilityVerdict { eligible: Boolean basis: String }

flow AssessEligibility() -> String { let result = "verified" return result }

axonendpoint BenefitsEligibility {
    method:   POST
    path:     "/benefits/eligibility"
    body:     BenefitsClaim
    output:   EligibilityVerdict
    execute:  AssessEligibility
    requires: [agency.case_officer]
    replay:   true
}
```

**FOIA + appeal audit:** every benefits decision is registered in the
ReplayLog. FOIA requests produce the exact request that resulted in any
verdict on demand. Administrative appeals retrieve the recorded
assessment via `trace_id`.

### Legal (FRE 502 + ABA Rule 1.6)

```axon
type DiscoveryDocument { case_id: String party: String }
type PrivilegeAssessment { privileged: Boolean doctrine: String }

flow AssessPrivilege() -> String { let result = "privileged" return result }

axonendpoint DiscoveryPrivilege {
    method:   POST
    path:     "/discovery/privilege"
    body:     DiscoveryDocument
    output:   PrivilegeAssessment
    execute:  AssessPrivilege
    requires: [legal.privileged_review]
    replay:   true
}
```

**FRE 502 inadvertent-waiver doctrine:** auditors trace back — was the
AI assessment performed by a privileged reviewer (auth scope
`legal.privileged_review`)? What was the exact document content +
assessment? The replay binding produces both, structurally preventing
waiver-by-AI-disclosure.

### Medicine (HIPAA + 21 CFR Part 11)

```axon
type Symptom { name: String score: ConfidenceScore }
type ClinicalDecisionRequest { patient_id: String symptoms: List<Symptom> }
type Recommendation { text: String }
type ClinicalDecisionSupport { recommendations: List<Recommendation> }

flow GenerateCDS() -> String { let result = "consider hydration" return result }

axonendpoint CDSEndpoint {
    method:    POST
    path:      "/clinical/decision-support"
    body:      ClinicalDecisionRequest
    output:    ClinicalDecisionSupport
    execute:   GenerateCDS
    transport: sse                          // streaming token-by-token to clinician UI
    keepalive: 15s
    requires:  [hipaa.phi.read, clinician]
    replay:    true
}
```

**HIPAA Safe Harbor + 21 CFR Part 11 §11.10:** PHI scrubber (Fase 27.g
enterprise kernel) runs upstream of every request. The replay binding
registers the **scrubbed** request in the audit chain. A clinical
adverse event review can later replay the exact PHI-redacted
assessment that led to a recommendation. The `ConfidenceScore` range
validation rejects out-of-range severities at parse-time (e.g.
`symptoms[0].score: 1.5` → 400 with `field_path "symptoms[0].score"`).

---

## Backwards compatibility — `/v1/execute` preserved (D10)

`POST /v1/execute` is preserved verbatim for v1.20.x–v1.22.x clients.
Every legacy adopter sees zero behavior change. The dynamic routes are
**strictly additive**.

Clients hitting `POST /v1/execute` with `{"flow": "X"}` continue to
work; clients hitting `POST /chat` (the declared path) get the new
behavior. The two coexist on every dynamic-route server.

To disable dynamic routes (e.g. when an existing reverse proxy already
maps paths to `/v1/execute`):

```bash
axon serve --disable-dynamic-routes
# or
AXON_DISABLE_DYNAMIC_ROUTES=1 axon serve
```

Opt-out is deploy-time only; routes never silently disappear.

---

## Production deployment checklist

Before flipping a v1.22.x → v1.23.0 deployment in production:

1. **Audit your axonendpoint declarations** — every `path:` field is
   now a real route. Verify no path collides with an existing
   reverse-proxy route or with another axonendpoint.

2. **Add `body:` declarations** to every POST/PUT endpoint that
   accepts structured input. Existing endpoints without `body:` keep
   accepting free-form JSON (D9), but the schema gate is your guard
   against malformed clients.

3. **Add `output:` declarations** to every endpoint serving regulated
   downstream consumers. Schema violations land in `/v1/audit` —
   adopters see them; clients see only a generic 500.

4. **Configure auth tokens** for `/v1/replay/<id>` retrieval if
   regulators / auditors will consume it (`AccessLevel::ReadOnly` —
   same precedent as `/v1/audit`).

5. **Decide replay binding policy** — leave default-on for POST/PUT
   (recommended for regulated verticals) OR opt out per-endpoint with
   `replay: false` for high-throughput non-audited endpoints.

6. **Test the Idempotency-Key header path** if your clients ever
   retry POSTs on flaky networks (recommended for banking + payments).

7. **Verify the CI workflow `fase_32_rest_routes.yml`** is in your
   pipeline so adopter-facing regressions surface before release.

---

## Troubleshooting

### "POST /chat returns 404"

The fallback handler returns 404 with the full registered-routes list:

```json
{
  "error": "axonendpoint_not_found",
  "method": "POST",
  "path": "/chat",
  "registered_routes": [
    {"method": "POST", "path": "/loan/decision"},
    {"method": "GET", "path": "/health"}
  ],
  "hint": "deploy an axonendpoint with this method+path, or use POST /v1/execute with the flow name in the body for the legacy RPC path"
}
```

Check the registered-routes list — your axonendpoint declaration
didn't make it into the deployed source.

### "POST /chat returns body_schema_violation but my body looks right"

Read the `field_path` in the 400 envelope — it points at the EXACT
field that violated the schema. The most common case: declaring a
field as `Money` but sending a raw number (`5000` vs
`{"amount": 5000, "currency": "USD"}`). See [§4](#body-schema-validation-body-t-d4)
for the supported type shapes.

### "I get 403 but my bearer has the right capability"

Verify the bearer's `capabilities` claim is a JSON array of strings.
The slug grammar `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` applies on
BOTH sides — the runtime ignores non-string entries in the bearer's
array (defense-in-depth).

### "Idempotency replay returns the old body but the cache should have expired"

24h default retention. Verify your clock + the server's clock are in
sync (NTP drift can keep entries alive past expected expiry on
in-memory stores). For longer retention, layer enterprise persistence.

### "GET /v1/replay/<id> returns 404"

Either: (a) the trace_id is wrong, (b) the entry expired past the
30-day retention window, (c) the original endpoint had `replay: false`
declared, or (d) the original response was non-2xx / SSE.

---

## Cross-stack contract: Python ↔ Rust (D11)

Both stacks parse identical sources and produce **byte-identical**
route tables + schema-validation verdicts. The drift gates lock the
contract:

- [`tests/fixtures/fase32_routes/corpus.json`](../tests/fixtures/fase32_routes/corpus.json)
  — 14-entry route-table corpus.
- [`tests/fixtures/fase32_body_schema/corpus.json`](../tests/fixtures/fase32_body_schema/corpus.json)
  — 29-entry body-validation corpus.

Both stacks parametrize over these corpora; if either drifts, CI
fails. See `.github/workflows/fase_32_rest_routes.yml` for the
five-lane CI matrix.

---

## Four-pillar trace

Every D-letter of Fase 32 traces to at least one of the four
foundational pillars:

- **MATHEMATICS** — schema validation is total + deterministic;
  replay is `same_input + same_model_state ⟹ same_output` for
  deterministic backends.
- **LOGIC** — routing is exhaustive (every axonendpoint reachable;
  orphan paths impossible); subset checks are precise + decidable.
- **PHILOSOPHY** — declarative source IS the HTTP behavior;
  auditors inspect source + KNOW the contract.
- **COMPUTING** — D8 + D9 + D10 backwards-compat absolute;
  `/v1/execute` preserved verbatim; opt-out flag for adopters who
  don't want dynamic routes.

---

## Where to file bugs

- Adopter-facing issues: https://github.com/Bemarking/axon-lang/issues
- Enterprise integration questions: contact your axon-enterprise
  representative or open an issue on the enterprise tracker.
- Vertical-specific compliance questions (HIPAA / PCI / FedRAMP /
  FRE 502): consult [`docs/enterprise/`](enterprise/) — vertical-
  specific deployment guides ship as part of axon-enterprise v1.13.0+.

---

## See also

- [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — Fase 30 + 31 SSE
  surface; § Dynamic routes section explains the per-endpoint transport.
- [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Pattern 7
  walks through path-collision + schema-violation + missing-auth
  error diagnostics.
- [`MIGRATION_v1.23.md`](MIGRATION_v1.23.md) — v1.22.x → v1.23.0
  migration recipes.
- [Plan vivo Fase 32](fase_32_axonendpoint_first_class_rest.md) — the
  engineering spec.

---

*This document covers axon-lang v1.23.0 and later. For earlier versions
see the corresponding `MIGRATION_v*.md`.*
