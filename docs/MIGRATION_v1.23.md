# AXON Migration Guide — v1.22.x → v1.23.0

> **Scope:** the Fase 32 *Axonendpoint as First-Class HTTP REST*
> surface introduced in v1.23.0. Adopters upgrading from v1.22.x
> (Fase 31 type-driven wire inference) read this doc to decide which
> migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.23.0 is **strictly additive** (D10). If you don't change
> anything, nothing changes — your v1.22.x behavior is preserved
> verbatim. `POST /v1/execute` continues to work; every existing
> axonendpoint without new fields keeps current behavior. You **may**
> opt in to: declared paths becoming real routes (default), body /
> output schema validation (per-endpoint), Idempotency-Key, auth scope
> via `requires:`, and replay-token binding via `replay:`.

---

## What changed in v1.23.0

| Surface | v1.22.x | v1.23.0 |
|---|---|---|
| `axonendpoint Chat { path: "/chat" }` | Decorative metadata; route never registered | **`POST /chat` is a real route.** Closes the Kivi case at the wire layer. |
| `POST /v1/execute` with `{"flow": "Chat"}` | The only entry point | **Preserved verbatim** — coexists with the new dynamic route (D10). |
| `body: T` on axonendpoint | Parsed; no runtime effect | **400 Bad Request** with structured diagnostic on schema violation. |
| `output: T` on axonendpoint | Parsed; no runtime effect | **OWASP-safe 500** to client + full diagnostic in audit log on flow output violation. |
| `Idempotency-Key: <key>` header on POST/PUT | Ignored | **Stripe-compatible cache** — `same_key + same_body ⟹ byte-identical replay` (24h retention). |
| New `requires: [slug, slug]` field | — | **403 Forbidden** when bearer's `capabilities` JWT claim doesn't satisfy the declared list. |
| New `replay: true | false` field | — | Every successful 2xx POST/PUT writes a replay binding; auditors retrieve via `GET /v1/replay/<trace_id>`. |
| `X-Axon-Trace-Id: <uuid>` response header | — | **Attached on every dynamic-route response** (correlation anchor). |
| Disable-dynamic-routes opt-out | — | `axon serve --disable-dynamic-routes` OR `AXON_DISABLE_DYNAMIC_ROUTES=1`. |

The new fields (`requires:`, `replay:`) are **optional** with adopter-
friendly defaults (no auth gate by default; replay default-on for
POST/PUT, default-off for GET/DELETE).

---

## Scenario A — You are the Kivi case 2026-05-11 (the trigger)

**Symptom:** You declared `path: "/chat"` on your axonendpoint, but
hitting `POST /chat` returns 404 — only `POST /v1/execute` works.

**Fix (60 seconds):** Upgrade to v1.23.0. Your `path:` declarations
become real routes automatically at deploy time. No source changes
needed.

```bash
pip install --upgrade axon-lang>=1.23.0
# or for Rust callers:
cargo update -p axon-lang --precise 1.23.0
```

Redeploy. `POST /chat` now serves the declared flow. The fix has been
available since v1.23.0 — Fase 30 + 31 transport semantics apply
uniformly on the new dynamic route.

---

## Scenario B — You want body-schema validation on existing endpoints

**Use case:** Your axonendpoints accept structured JSON bodies; you
want adopter-facing 400s for malformed input instead of trusting the
flow to handle every possible shape gracefully.

**Recipe:**

1. Define the body type:

```axon
type LoanApplication {
    amount: Money
    applicant: String
    purpose: String?       // optional field
}
```

2. Add `body: LoanApplication` to the axonendpoint:

```axon
axonendpoint LoanDecision {
    method:  POST
    path:    "/loan/decision"
    body:    LoanApplication            // ← add this
    execute: ApproveOrDeny
}
```

3. Deploy. Malformed bodies now return 400 with structured field-path
   diagnostics. See [`ADOPTER_REST.md` §4](ADOPTER_REST.md#body-schema-validation-body-t-d4)
   for the supported type shapes + the 400 envelope shape.

**No client changes required.** Clients sending well-formed bodies see
no behavior change. Clients sending malformed bodies now see a 400
instead of a downstream flow failure.

---

## Scenario C — Banking adopter wants Idempotency-Key retries

**Use case:** Your clients retry POST requests on flaky networks; you
want the Stripe / Plaid / Square idempotency contract.

**Recipe:**

1. No source changes needed — the runtime honors `Idempotency-Key`
   automatically on every POST/PUT axonendpoint after upgrade.

2. Update your client to send the header:

```javascript
fetch("/loan/decision", {
    method: "POST",
    headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(payload),
})
```

3. Retries that reuse the same key + same body return byte-identical
   responses + the `Idempotency-Status: replayed` header. Retries with
   the same key + DIFFERENT body return 422 — your client should
   surface the conflict to the user (this means the original request
   succeeded and the user shouldn't double-submit).

**Cross-tenant isolation:** keys are scoped per `(client_id, path,
key)`. Two tenants cannot collide.

---

## Scenario D — Auth-scoped endpoints for regulated verticals

**Use case:** You want every banking / government / legal / medicine
endpoint to require specific bearer capabilities (e.g.
`bank.officer`, `hipaa.phi.read`).

**Recipe:**

1. Declare the capabilities on the axonendpoint:

```axon
axonendpoint AdminPolicyUpdate {
    method:   POST
    path:     "/admin/policy"
    body:     PolicyUpdate
    requires: [admin, policy.write]   // ← AND semantics
    execute:  ApplyPolicyUpdate
}
```

2. Issue JWTs with the `capabilities` claim:

```json
{
  "sub": "alice",
  "tenant_id": "bank-1",
  "capabilities": ["admin", "policy.write", "audit.read"],
  "exp": 1735689600
}
```

3. Deploy. Bearers missing any declared capability now see 403 with
   a structured `missing_capability` envelope. See
   [`ADOPTER_REST.md` §8](ADOPTER_REST.md#auth-scope--requires-field-d8)
   for the full deny shape + the slug grammar.

---

## Scenario E — Replay-token binding for regulatory audit

**Use case:** Banking PCI DSS Req 10 / Government FedRAMP AU-2 /
Legal FRE 502 / Medicine 21 CFR Part 11 — you need to retrieve the
exact request + response for any logged transaction.

**Recipe:**

1. Default behavior post-upgrade: every successful 2xx POST/PUT to a
   dynamic route ALREADY writes a replay binding. No source changes
   needed.

2. Retrieve a binding by trace_id (returned in the
   `X-Axon-Trace-Id` response header of every dynamic-route response):

```bash
TRACE_ID=$(curl -i -X POST http://localhost:8000/loan/decision \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{...}' \
    | grep -i 'x-axon-trace-id:' | awk '{print $2}' | tr -d '\r')

curl http://localhost:8000/v1/replay/$TRACE_ID \
    -H "Authorization: Bearer $READ_ONLY_TOKEN"
```

3. To opt OUT for high-throughput non-audited endpoints:

```axon
axonendpoint HighThroughputPing {
    method:  POST
    path:    "/ping"
    execute: Ping
    replay:  false       // ← skip binding for this endpoint
}
```

See [`ADOPTER_REST.md` §9](ADOPTER_REST.md#replay-token-binding--regulator-grade-audit-d9)
for the full retrieval shape, retention policy (30 days default), and
the deterministic / non-deterministic distinction.

---

## Scenario F — Disable dynamic routes entirely (D8 opt-out)

**Use case:** You have an existing reverse proxy that already maps
adopter paths to `/v1/execute`. You don't want axon to register
competing routes.

**Recipe (one of):**

```bash
# CLI flag
axon serve --disable-dynamic-routes

# Env var (12-factor app)
AXON_DISABLE_DYNAMIC_ROUTES=1 axon serve
```

Both surfaces preserved across the cross-stack (Python + Rust) D11
contract. `/v1/execute` continues to serve every flow; declared paths
return 404 (the runtime never registers them).

---

## Compatibility matrix

| Action | v1.20.x clients | v1.21.x clients | v1.22.x clients | v1.23.0 clients |
|---|---|---|---|---|
| `POST /v1/execute` with `{"flow": "X"}` | ✅ unchanged | ✅ unchanged | ✅ unchanged | ✅ unchanged |
| `POST /chat` (declared path) | 404 | 404 | 404 | ✅ serves the flow |
| `body: T` enforcement | n/a | n/a | n/a | ✅ enforced on dynamic routes |
| `Idempotency-Key` honored | n/a | n/a | n/a | ✅ on POST/PUT |
| `requires: [cap]` enforcement | n/a | n/a | n/a | ✅ on dynamic routes |
| `replay: true` binding | n/a | n/a | n/a | ✅ on POST/PUT default |
| `X-Axon-Trace-Id` header | n/a | n/a | n/a | ✅ every dynamic response |

Every row above the dotted line represents **strictly additive**
behavior (D10). No v1.20.x–v1.22.x client breaks on upgrade.

---

## Where to file bugs

https://github.com/Bemarking/axon-lang/issues — please include the
`X-Axon-Trace-Id` from any failing dynamic-route call; it correlates
the client log to the server audit chain.

---

## See also

- [`ADOPTER_REST.md`](ADOPTER_REST.md) — comprehensive v1.23.0
  REST surface guide.
- [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — § Dynamic routes
  section for per-endpoint transport semantics.
- [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Pattern 7
  walks the path-collision + schema-violation + missing-auth errors.
- [Plan vivo Fase 32](fase_32_axonendpoint_first_class_rest.md) —
  engineering spec with all 12 D-letters ratified.
