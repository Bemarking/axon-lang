---
title: "Plan vivo: Fase 32 — Axonendpoint as First-Class HTTP REST Primitive"
status: DRAFTED 2026-05-11 — D-letter ratification PENDIENTE (D1–D12 propuestos en §4); 32.a engineering spec este doc; 32.b–32.k execution per incremental founder sign-off cadence
owner: AXON Compiler + Runtime Team
created: 2026-05-11
target: axon-lang — next available minor release after v1.22.0 (cadence determined by preceding patches; expected v1.23.0 if no v1.22.x patches intervene). Cross-stack Python + Rust. axon-enterprise catch-up follows the same shape as v1.11.0 / v1.12.0 lean catch-up pattern, BUT v1.23.0 also unlocks per-vertical enterprise features (banking / government / legal / medicine) that v1.13.0 enterprise layers on top
depends_on: Fase 11.a SHIPPED (Stream<T> + 4-policy backpressure catalog); Fase 11.c SHIPPED (Replay tokens + Cognitive State); Fase 23 SHIPPED (algebraic effects runtime — delimited continuations underpin SSE event-by-event semantics); Fase 28 SHIPPED (adopter diagnostic robustness — Fase 32 inherits source-context + smart-suggest); Fase 30 SHIPPED v1.21.0 (HTTP transport surface — Fase 32 makes per-endpoint transport real); Fase 31 SHIPPED v1.22.0 (Type-Driven Wire Inference — Fase 32 extends inference to dynamic routes)
charter_class: OSS — every adopter benefits transitively. axon-enterprise gets the surface via catch-up release after axon-lang ships; v1.13.0+ enterprise unlocks vertical-specific layers on top (HIPAA replay, FedRAMP audit chain, FRE 502 privilege scope, PCI DSS idempotency)
pillars: MATHEMATICS — schema validation is total + deterministic over declared types; LOGIC — routing is exhaustive (every axonendpoint reachable; orphan paths impossible); PHILOSOPHY — declarative source IS the HTTP behavior, no hidden coupling, no body magic; COMPUTING — D8 + D9 absolute backwards-compat with v1.20.x–v1.22.x adopters via path coexistence
---

> **Sibling adopter-facing docs (ships in 32.j):**
> - [`ADOPTER_REST.md`](ADOPTER_REST.md) (NEW, 32.j) — end-to-end adopter guide for the REST surface: routing, schema validation, auth scoping, idempotency, replay.
> - [`ADOPTER_STREAMING.md`](ADOPTER_STREAMING.md) — Fase 30/31 streaming surface; v1.23.0 extends with a "§ Dynamic routes" section explaining per-endpoint transport on registered paths.
> - [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — Fase 28 diagnostic guide; new Pattern 7 for path-conflict + schema-violation errors.
> - [`MIGRATION_v1.23.md`](MIGRATION_v1.23.md) (NEW, 32.j) — migration recipe v1.22.x → v1.23.0, including the high-profile-vertical recipes (banking idempotency, government audit chain, legal privilege scope, medicine HIPAA replay).
>
> **Vertical-specific enterprise docs (Fase 13.0+ enterprise companion):**
> - [`docs/enterprise/REST_BANKING.md`](enterprise/REST_BANKING.md) — PCI DSS / SOC 2 idempotency patterns.
> - [`docs/enterprise/REST_GOVERNMENT.md`](enterprise/REST_GOVERNMENT.md) — FedRAMP audit chain integration.
> - [`docs/enterprise/REST_LEGAL.md`](enterprise/REST_LEGAL.md) — FRE 502 privilege scope auth patterns.
> - [`docs/enterprise/REST_MEDICINE.md`](enterprise/REST_MEDICINE.md) — HIPAA Safe Harbor replay patterns.

---

## ▶ Status snapshot (2026-05-11 — DRAFTED, D1–D12 propuestos)

> **Founder directive 2026-05-11 (verbatim trigger after Kivi's 8-version journey):**
>
> *"Hacer que una aplicación AI sea determinista y fundada en nuestros cuatro pilares como lenguaje es el aporte a la humanidad por el que estamos trabajando. Visión de rayos X de adopters de alto perfil como banca, gobierno, legal, medicina, etc."*
>
> **MATHEMATICS** + **LOGIC** + **PHILOSOPHY** + **COMPUTING**. Cada decisión debe trazar de vuelta a ≥ 1 pilar; las que no, se reformulan o se cortan. **Vertical-grounded**: cada D-letter debe poder defenderse frente a un auditor de banca, gobierno, legal o medicina como contribución concreta a la deterministicidad de la AI en producción regulada.

### What this Fase exists to solve

Fase 11.a delivered `Stream<T>` algebraic effects (compile-time complete). Fase 23 delivered the algebraic effects runtime (delimited continuations + handlers). Fase 30 delivered HTTP transport for stream effects. Fase 31 delivered type-driven wire inference. **All four shipped under the assumption that adopters hit `POST /v1/execute` with `{"flow_name": "X"}` in the body** — the RPC pattern, not the declarative REST pattern.

The Kivi adopter case 2026-05-11 (8 version iterations from v1.16.2 to v1.22.0) revealed empirically what the design always implied but the runtime never honored: **adopters declare REST semantics in their `axonendpoint` blocks (`method: POST`, `path: "/chat"`, `body: Type`, `output: Type`, `transport: sse`) and expect those declarations to materialize as HTTP routes**. The runtime treats them as decorative. The adopter writes a REST endpoint; the runtime exposes an RPC.

After Fase 31 shipped 9 sub-fases + 3 opt-in surfaces + comprehensive docs + axon-W001 + X-Axon-Stream-Available header + MIGRATION_v1.22.md, the adopter said:

> *"el gap está confirmado del lado del runtime axon-rs/enterprise, NO de nuestra sintaxis. El parser acepta TODO lo que ponemos, los flows compilan, el chat ejecuta correctamente, pero Content-Type sigue siendo application/json. Necesitamos que esa feature complete su wiring."*

The diagnostic 2026-05-11 (verified by code inspection of `build_router()` in [`axon-rs/src/axon_server.rs:24573`](../axon-rs/src/axon_server.rs#L24573)): the router is constructed once with static routes; the `path:` field on every `AxonEndpointDefinition` is read at deploy time but **never registered as a route**. The adopter declared `POST /chat`; the runtime never exposed it.

Fase 30 + Fase 31 made `/v1/execute` content-aware. **Fase 32 makes every `axonendpoint` block a real REST route.** That is the language honoring its own declarations.

### What this Fase is NOT

This is NOT another iteration of the SSE-promotion documentation. The SSE promotion in `/v1/execute` works correctly (29/29 fase30 + fase31 tests verde). Fase 32 makes the SAME promotion logic apply to dynamically registered routes — when an adopter hits `POST /chat` (their declared path), the runtime honors `transport: sse` and the type-driven inference exactly as it does on `/v1/execute`.

### Why now — and why vertical-grounded

LLM-powered software is moving into regulated production. Banking, government, legal, and medicine adopters need:

1. **Path-as-contract** — auditors must be able to inspect axon source and KNOW which endpoint serves which workflow. Today, all flows multiplex through `/v1/execute`; auditors see opaque RPCs.
2. **Schema validation at the boundary** — the body of `POST /loan/decision` MUST be a `LoanApplication` per source declaration. Free-form JSON in the body is malpractice in regulated verticals.
3. **Idempotency for retries** — banking POST operations cannot double-execute on client retry. The `Idempotency-Key` HTTP header is the industry standard (Stripe/Plaid/etc.); axon should honor it natively per-endpoint.
4. **Audit chain per endpoint** — HIPAA / FedRAMP / SOC 2 auditors need the request-response trace tied to the endpoint, not buried in `/v1/execute` aggregates.
5. **Per-endpoint auth scope** — `POST /admin/policy/update` requires different auth than `POST /public/healthcheck`. Per-axonendpoint declaration of required capabilities is the natural shape.
6. **Replay for compliance** — Fase 11.c replay tokens already exist; v1.23.0 binds replay tokens to axonendpoint POSTs so a regulator can replay the exact request that produced a flagged decision.

Each of these is a real adopter requirement, not opinion. Together they make axon the **deterministic LLM application platform** the founder principle promises — the contribution to humanity is that AI applications can be REGULATED.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 32.a Engineering spec + D-letter ratification | ⏳ DRAFTED (awaiting "aprobadas todas D-letters" bloque) | doc-only | — | This doc + memory entry `project_fase_32_plan.md` + MEMORY.md index update |
| 32.b Path registration in build_router — runtime registers `<method> <path>` per axonendpoint at deploy time (D1, D2, D3, D11) | ⏳ pending | ~220 (Rust runtime) + ~180 (Python axon serve mirror) + ~250 (tests) | Python + Rust | New `register_axonendpoint_routes(program, &mut router)` function called on every `/v1/deploy` success. Per axonendpoint: register `<method> <path>` route that dispatches to a new `dynamic_endpoint_handler` which extracts the flow name from the AST + routes to the existing execute path. **Path conflict detection** (D2): if two axonendpoints declare the same `(method, path)` tuple, deploy returns a structured error naming both. **Method enum closed per D3**: `{GET, POST, PUT, DELETE, PATCH}` only — silent acceptance of `OPTIONS`/`HEAD`/etc. removed. **Hot reload**: axum 0.8's `Router::merge` API allows runtime route additions without full restart. **Cross-stack D11**: Python `AxonServer.create_app()` mirror registers via FastAPI's `app.add_api_route()`; both stacks parse the same source and produce byte-identical route sets |
| 32.c Body schema validation per `body:` declaration (D4) | ⏳ pending | ~180 (Rust schema validator) + ~120 (Python mirror) + ~200 (tests) | Python + Rust | When axonendpoint declares `body: LoanApplication`, the registered route deserializes the request body as the declared type. Schema mismatch → 400 Bad Request with structured error pointing at the offending field. **Pillar trace**: MATHEMATICS — validation is total over declared types; LOGIC — every accepted request body matches the declared schema (no widening); PHILOSOPHY — the declaration IS the contract; auditors can read source + know what bodies are accepted. **Type inference for `body:`** is from Fase 11.a + Fase 18 IR; this sub-fase wires the IR validators into the request pipeline. **Backwards compat**: omitting `body:` accepts free-form JSON (D9 — adopters without explicit schemas keep current behavior) |
| 32.d Output schema validation per `output:` declaration (D5) | ⏳ pending | ~120 (Rust validator) + ~80 (Python mirror) + ~150 (tests) | Python + Rust | Symmetric of 32.c — the response body validates against the declared `output:` type. Validation failure → 500 Internal Server Error with the diagnostic AT the server log (not leaked to client per OWASP — only generic "Internal validation error" to client). Adopter-facing tooling: the diagnostic surfaces in `axon traces` + the audit chain. **Pillar trace**: MATHEMATICS — validation is total; PHILOSOPHY — the declared output IS the contract; adopters' downstream consumers can trust the schema |
| 32.e Per-endpoint transport on dynamic routes — content-negotiation + strict-mode integration (D6) | ⏳ pending | ~100 (Rust dispatch refactor) + ~80 (tests) | Rust | The dynamic_endpoint_handler from 32.b consults the axonendpoint's `transport:` field + the server's `strict_type_driven_transport` flag + the client's `Accept:` header — same matrix as Fase 30.e + Fase 31.d, applied to ALL registered routes. Fase 30 D4 + D5 + Fase 31 D1 + D3 D6 all apply uniformly to the entire REST surface. SSE on `POST /chat` returns event-stream wire format honoring `keepalive:` exactly as `/v1/execute/sse` does today. The Kivi case is closed at the wire layer transparently |
| 32.f Idempotency-Key header support per endpoint (D7) | ⏳ pending | ~160 (Rust idempotency store + handler integration) + ~140 (tests) | Rust | When the request carries `Idempotency-Key: <key>` AND the axonendpoint declares `method: POST` or `PUT`, the runtime checks an in-memory + persisted idempotency store (`(client_id, endpoint_path, idempotency_key) → cached_response`). If a cached response exists within the retention window (default 24h, configurable per-endpoint), the cached response is returned verbatim. If absent, the request executes and the response is cached. **Banking / Stripe pattern industry-standard**: enables safe client retries on flaky networks. **Pillar trace**: LOGIC — `same_key ⟹ same_response` invariant within retention window; COMPUTING — banking adopters' SOC 2 / PCI DSS compliance requires this primitive |
| 32.g Auth scope per axonendpoint (D8) | ⏳ pending | ~140 (Rust auth integration) + ~80 (Python mirror) + ~120 (tests) | Python + Rust | New optional axonendpoint field `requires: <capability-list>` — a list of capabilities the request bearer must hold to access the endpoint. Examples: `requires: [admin]`, `requires: [legal.read, legal.write]`, `requires: [hipaa.phi.read]`. The runtime verifies the bearer token's capability claims against the declared list; missing capability → 403 Forbidden with structured error. **Cross-link with Fase 21 enterprise tenant/capability registry**: enterprise tenants get the full capability surface; OSS tenants get the simple matching primitive. **Pillar trace**: PHILOSOPHY — the access contract IS the source declaration; LOGIC — the matching predicate is precise (capability ∈ declared_set) |
| 32.h Determinism — replay tokens per axonendpoint POST (D9) | ⏳ pending | ~180 (Rust replay binding + audit chain integration) + ~150 (tests) | Rust | Every successful POST to an axonendpoint with `replay: true` (default true for `method: POST`, false for `method: GET`) is registered in the Fase 11.c ReplayLog with the (request body hash, response body hash, timestamp, trace_id, endpoint_path) tuple. Regulators / auditors can later replay the exact request via `GET /v1/replay/<trace_id>` and get the same response back (deterministic backends only — see §10 out of scope for the LLM determinism question). **Cross-link with Fase 27.f tamper-evident evidence packager** (enterprise): the ReplayLog entries are sealed via the per-tenant HMAC chain. **Pillar trace**: MATHEMATICS — same input + same model state ⟹ same output (deterministic backends — stub, locked LLM models); COMPUTING — regulatory replay is the foundation of audit-defensible AI |
| 32.i Cross-stack drift gate + 100-iter behavior fuzz + path-conflict CI matrix (D10, D12) | ⏳ pending | ~150 (YAML) + ~200 (Py drift) + ~200 (Rust drift) + ~250 (fuzz) | YAML + Python + Rust | New `.github/workflows/fase_32_rest_routes.yml` with 5 parallel lanes: (1) python-router (3.12 × 3.13; route registration + schema validation + auth + idempotency + replay tests); (2) rust-runtime (ubuntu; same surface in axon-rs); (3) cross-stack-drift (D11 — Python + Rust register byte-identical route sets from the same corpus.json sources); (4) high-profile-vertical CI lane (parametrized over banking / government / legal / medicine canonical example sources verifying their specific patterns work); (5) D12-style 100-bucket × 10-iter fuzz on route registration (path syntax + method enum + body schema + auth declaration variations — never panics) |
| 32.j Adopter documentation surface (D10) | ⏳ pending | ~520 (new `ADOPTER_REST.md`) + ~120 (new `MIGRATION_v1.23.md`) + ~80 (`ADOPTER_STREAMING.md` extension §Dynamic routes) + ~80 (`ADOPTER_DIAGNOSTICS.md` Pattern 7) + ~200 LOC enterprise vertical docs (banking/government/legal/medicine) | Docs | New `docs/ADOPTER_REST.md` — comprehensive 18-section guide: declarative REST + per-endpoint transport + body/output schema validation + Idempotency-Key + auth scoping + replay tokens + multi-endpoint deployment + path collision diagnostics + EventSource-on-arbitrary-path + 5-vertical migration cookbook (banking POST /loan/decision + government POST /benefits/eligibility + legal POST /discovery/privilege + medicine POST /clinical/decision-support + generic). New `MIGRATION_v1.23.md` — 5-scenario migration recipe (current /v1/execute clients → declared paths + idempotency-as-default-on-POST + auth-scope wiring + replay-binding + cross-vertical patterns). `ADOPTER_STREAMING.md` extension explaining how Fase 30/31 transport semantics apply to dynamic routes. `ADOPTER_DIAGNOSTICS.md` Pattern 7 walks the path-collision + schema-violation + missing-auth-capability errors |
| 32.k Coordinated cross-stack release v1.23.0 | ⏳ pending | release | All stacks | bump-my-version minor bump axon-lang v1.22.x → v1.23.0; commit + tag via `coordinated-release.yml`; cargo publish axon-frontend + axon-lang; GitHub Release with content-first notes. axon-enterprise v1.13.0 catch-up (lean bump) PLUS the substantive vertical layers (banking idempotency persistence + government audit chain + legal privilege scope + medicine HIPAA replay) ship as the same release or v1.14.0 sequential depending on scope finalization in 32.j docs |

---

## ▶ Why this matters — the four-pillar framing with vertical X-ray

### **MATHEMATICS** — schema validation is total + deterministic

Given a request body and a declared type, validation is a **pure function** returning either `Ok(typed_value)` or `Err(error_path)`. The function is total over the type system + deterministic over the input. There is no "kinda matches" — the body either satisfies the declared schema or it doesn't.

```
validate : (RequestBody, Type) → Result<Value, Error>

validate(body, T) =
  Ok(v)            if body parses + every field matches T's schema
  Err(field_path)  otherwise
```

For regulated verticals this is **non-negotiable**. Banking adopters who declare `body: LoanApplication { amount: Money, applicant: Person }` cannot accept a body where `amount` is a string or `applicant` is missing — the declaration is the contract and the runtime enforces it.

### **LOGIC** — routing is exhaustive

Every `axonendpoint` declaration in the deployed program produces exactly one HTTP route. The set of routes is a finite, decidable function of the deployed source. Orphan paths are impossible:

```
∀ ae ∈ Program.declarations.AxonEndpoint.
    route_registered(ae.method, ae.path) = true
```

Path collisions are detected at deploy time (D2). Auditors can inspect the source and KNOW the complete REST surface — there are no hidden endpoints.

### **PHILOSOPHY** — declarative source IS the HTTP behavior

The adopter who writes:

```axon
axonendpoint LoanDecision {
    method:    POST
    path:      "/loan/decision"
    body:      LoanApplication
    output:    Decision
    execute:   ApproveOrDeny
    transport: sse
    keepalive: 15s
    requires:  [bank.officer]
    replay:    true
}
```

…is making **eight first-class declarations** about HTTP behavior. The runtime honors all eight. There is no body magic ("the runtime infers the body shape from the flow signature"), no path multiplexing ("everything goes through /v1/execute"), no auth side-channel ("an external middleware enforces capabilities"). The source IS the spec; the auditor reads the source and KNOWS the contract.

This is the lambda-calculus discipline applied at the HTTP layer: the declaration IS the type IS the wire behavior.

### **COMPUTING** — D8 + D9 absolute backwards-compat via path coexistence

`POST /v1/execute` is preserved verbatim for v1.20.x–v1.22.x clients. Every legacy adopter sees zero behavior change. The dynamic routes are STRICTLY ADDITIVE: they coexist with `/v1/execute`. Clients hitting `POST /v1/execute` with `{"flow": "X"}` continue to work; clients hitting `POST /chat` (the declared path) get the new behavior.

If an adopter doesn't want the dynamic routes (e.g. their existing reverse proxy already maps paths to `/v1/execute`), they set `axon serve --disable-dynamic-routes` OR `AXON_DISABLE_DYNAMIC_ROUTES=1` (D7 cross-stack). The route registration becomes opt-out, never silent.

---

## ▶ X-ray vision: high-profile vertical adopters

Each D-letter must defend itself in front of a vertical auditor. Here is how:

### Banking (PCI DSS + SOC 2)

**Adopter shape:**
```axon
type LoanApplication { amount: Money, applicant: Person }
type Decision { approved: Bool, reason: String, risk_score: Float }

axonendpoint LoanDecision {
    method:    POST
    path:      "/loan/decision"
    body:      LoanApplication
    output:    Decision
    execute:   ApproveOrDeny
    transport: json
    requires:  [bank.officer]
    replay:    true             # PCI DSS audit trail
}
```

**Auditor inspection** (PCI DSS Req 10.2): the source declares the endpoint, the body schema, the auth requirement, and the replay binding. The auditor reads the source + KNOWS the contract. They can sample any production trace and replay it deterministically via `/v1/replay/<trace_id>` — the same `LoanApplication` produces the same `Decision` (assuming deterministic backend; stub or locked LLM model).

**Idempotency-Key support** (Stripe / Plaid pattern): banking clients retry on flaky networks; v1.23.0 honors `Idempotency-Key` natively per D7. A double-charge from a network retry is **structurally impossible** when the client sets the key correctly.

### Government (FedRAMP + FISMA)

**Adopter shape:**
```axon
type BenefitsClaim { citizen_id: ID, claim_type: ClaimType, evidence: Document }
type EligibilityVerdict { eligible: Bool, basis: LegalBasis, expires_at: Date }

axonendpoint BenefitsEligibility {
    method:    POST
    path:      "/benefits/eligibility"
    body:      BenefitsClaim
    output:    EligibilityVerdict
    execute:   AssessEligibility
    requires:  [agency.case_officer]
    replay:    true             # FOIA / appeal audit trail
}
```

**Auditor inspection** (NIST SP 800-53 AU-2): every benefits decision is registered in the Fase 11.c ReplayLog with cryptographic seal (Fase 27.d audit log mmap kernel — enterprise). FOIA requests + administrative appeals can produce the exact request that resulted in any verdict on demand. The audit chain is HMAC-SHA256 + per-tenant Merkle (existing Fase 27 surface — enterprise v1.13.0+ unlocks).

### Legal (FRE 502 + ABA Rule 1.6)

**Adopter shape:**
```axon
type DiscoveryDocument { case_id: ID, party: String, content: Encrypted }
type PrivilegeAssessment { privileged: Bool, doctrine: PrivilegeDoctrine, redactions: [Span] }

axonendpoint DiscoveryPrivilege {
    method:    POST
    path:      "/discovery/privilege"
    body:      DiscoveryDocument
    output:    PrivilegeAssessment
    execute:   AssessPrivilege
    requires:  [legal.privileged_review]
    replay:    true             # FRE 502 inadvertent-disclosure traceability
}
```

**Auditor inspection** (FRE 502 — inadvertent waiver doctrine): when a privileged document is produced in discovery, opposing counsel may claim waiver. The auditor traces back: was the AI assessment performed by a privileged reviewer (auth scope `legal.privileged_review`)? What was the exact document content + assessment? The replay binding produces both. The Fase 20 + Fase 27 vertical shield ensembles (attorney-client + work product) run upstream of this endpoint — their assessment is part of the replay record.

### Medicine (HIPAA + 21 CFR Part 11)

**Adopter shape:**
```axon
type ClinicalDecisionRequest { patient_id: ID, symptoms: [Symptom], history: PatientHistory }
type ClinicalDecisionSupport { recommendations: [Recommendation], confidence: Float, citations: [PubMedID] }

axonendpoint ClinicalDecisionSupport {
    method:    POST
    path:      "/clinical/decision-support"
    body:      ClinicalDecisionRequest
    output:    ClinicalDecisionSupport
    execute:   GenerateCDS
    transport: sse                          # streaming token-by-token CDS for clinician UI
    keepalive: 15s
    requires:  [hipaa.phi.read, clinician]
    replay:    true                         # 21 CFR Part 11 audit trail
}
```

**Auditor inspection** (HIPAA Safe Harbor + 21 CFR Part 11 §11.10): the PHI scrubber (Fase 27.g enterprise kernel) runs upstream of every request. The replay binding registers the **scrubbed** request in the audit chain. A clinical adverse event review can later replay the exact PHI-redacted assessment that led to a recommendation. SSE streaming on the same endpoint enables real-time clinician UI without bypassing the audit chain.

---

## ▶ 4. D-letter proposals (D1–D12)

| # | Statement | Pillar(s) |
|---|---|---|
| **D1** | **Axonendpoint IS a REST route declaration**: every `AxonEndpointDefinition` in a deployed program produces exactly one HTTP route at the declared `(method, path)`. The `path:` field is no longer decorative metadata — it is the canonical URL the adopter exposes | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D2** | **Path conflict resolution is deterministic**: deploying two axonendpoints with the same `(method, path)` tuple fails the deploy with a structured error naming both endpoints. No "last wins" silent override. Auditors can inspect the source + know unambiguously which endpoint serves which path | LOGIC + COMPUTING |
| **D3** | **Method enum closed**: `axonendpoint.method ∈ {GET, POST, PUT, DELETE, PATCH}`. Other methods (HEAD, OPTIONS, CONNECT, TRACE) are runtime-managed (CORS preflight, etc.) and not adopter-declarable. Closed enum refuses interpretation drift | LOGIC |
| **D4** | **Body schema validation is total**: when an axonendpoint declares `body: T`, every accepted request body matches `T`'s schema verbatim or returns 400. The validation function is pure + total over the declared type system. Free-form bodies require omitting `body:` (D9 backwards-compat) | MATHEMATICS + LOGIC + PHILOSOPHY |
| **D5** | **Output schema validation is total**: when an axonendpoint declares `output: T`, every response body matches `T`'s schema verbatim or the runtime logs a server-side error + serves a generic 500 to the client. Adopter-facing diagnostic surfaces in `axon traces` (no schema leakage to client per OWASP) | MATHEMATICS + PHILOSOPHY |
| **D6** | **Per-endpoint transport honored on registered routes**: Fase 30 D4 + D5 negotiation + Fase 31 D1 inference + D3 sacred opt-out + D6 flag-gated rollout all apply uniformly to dynamically registered routes. SSE on `POST /chat` is byte-identical to SSE on `/v1/execute/sse` | LOGIC + PHILOSOPHY + COMPUTING |
| **D7** | **Idempotency-Key per POST/PUT endpoint**: when the client sends `Idempotency-Key: <key>` AND the endpoint is POST or PUT, the runtime caches the (client, path, key) → response tuple within a configurable retention window (default 24h). Same key within the window returns the cached response verbatim — `same_key ⟹ same_response` invariant. Industry standard (Stripe / Plaid / banking) | LOGIC + COMPUTING |
| **D8** | **Auth scope per axonendpoint**: new optional `requires: [<capability>...]` field declares the capabilities the bearer must hold. Missing capability → 403 Forbidden with structured error. Cross-link with Fase 21 enterprise tenant/capability registry; OSS adopters get the simple matching primitive | PHILOSOPHY + LOGIC |
| **D9** | **Replay tokens per axonendpoint POST**: every successful POST to an axonendpoint with `replay: true` (default true for POST, false for GET — declarable to override) is registered in the Fase 11.c ReplayLog. Regulators replay via `GET /v1/replay/<trace_id>` and get the same response on deterministic backends | MATHEMATICS + COMPUTING |
| **D10** | **D8 + D9 backwards-compat via path coexistence**: `POST /v1/execute` is preserved verbatim. Dynamic routes are strictly additive. Opt-out via `axon serve --disable-dynamic-routes` OR `AXON_DISABLE_DYNAMIC_ROUTES=1`. v1.20.x–v1.22.x adopters see zero behavior change on day-1 upgrade | COMPUTING |
| **D11** | **Cross-stack consistency**: Python `AxonServer.create_app()` registers routes via `app.add_api_route()`; Rust `axon-rs` registers via `Router::merge`. Both stacks parse the same source and produce **byte-identical route sets** (same set of `(method, path)` tuples for the same input program). Drift gate over a shared corpus locks parity in CI | MATHEMATICS + COMPUTING |
| **D12** | **Four-pillar trace requirement (meta)**: every Fase 32 D-letter MUST map to ≥ 1 of {MATHEMATICS, LOGIC, PHILOSOPHY, COMPUTING}. D-letters that fail the trace are rewritten or cut. **Vertical-grounded**: each D-letter must defensible in front of a banking / government / legal / medicine auditor as a concrete contribution to regulatable AI | PHILOSOPHY (meta) |

**Bloque ratification request 2026-05-11**: founder reviews § Status + § Why this matters + § X-ray vision + this table, then approves bloque ("aprobadas todas D-letters" or selective). Until ratification, this doc is the spec; no code changes ship.

---

## ▶ 5. Cross-stack contract (Python ↔ Rust route registration)

| Source declaration | Python `AxonServer.create_app()` | Rust `build_router_with_state()` | Drift-gate corpus entry |
|---|---|---|---|
| `axonendpoint A { method: POST path: "/a" execute: F }` | `app.add_api_route("/a", ..., methods=["POST"])` | `router.route("/a", post(...))` | `simple_post_route` |
| `axonendpoint A { method: GET path: "/a/{id}" }` | `app.add_api_route("/a/{id}", ..., methods=["GET"])` | `router.route("/a/{id}", get(...))` (axum path param syntax matches FastAPI) | `path_param_get_route` |
| Two axonendpoints with same `(method, path)` | `RuntimeError` raised at create_app | `Err` returned + structured 409 on /v1/deploy | `path_collision_rejected` |
| `axonendpoint A { method: DELETE path: "/a/{id}" }` | `app.add_api_route("/a/{id}", ..., methods=["DELETE"])` | `router.route("/a/{id}", delete(...))` | `delete_route` |
| `axonendpoint A { method: OPTIONS ... }` (invalid per D3) | Parser error | Parser error | `invalid_method_rejected` (already in Fase 30.b corpus — reused) |
| `axonendpoint A { method: POST path: "/a" body: T }` | `app.add_api_route(..., dependencies=[validate_body(T)])` | `router.route("/a", post(validate_then_dispatch::<T>))` | `body_schema_route` |

Corpus lives at `tests/fixtures/fase32_rest_routes/corpus.json`. Same shape as Fase 30 / Fase 31 drift-gate corpora — JSON list of `{name, source, expected_routes: [{method, path}], expected_deploy_status}`. Both stacks parametrize over the same JSON.

---

## ▶ 6. Path syntax + validation rules

Adopter declares the path verbatim in the axonendpoint:

```axon
path: "/api/v1/loans/{loan_id}/decision"
```

**Accepted characters per D11 + RFC 3986** (URL path segment):
- ASCII alphanumeric `[a-zA-Z0-9]`
- `-`, `.`, `_`, `~`
- `/` (segment separator)
- `{name}` (path parameter; matches axum + FastAPI convention)

**Rejected at parse time** (smart-suggest hint per Fase 28.e):
- Leading whitespace (suggest: strip)
- Trailing whitespace
- Empty path string `""`
- Path not starting with `/`
- Bare query string `?foo=bar` (path doesn't carry queries)
- Bare fragment `#section`
- Percent-encoded bytes (adopter writes literal characters; encoding handled by HTTP client)

**Closed parameter name set**: `{name}` segments use bare identifier names (no regex). For typed-parameter validation an adopter can declare `body:` shapes that include path params.

---

## ▶ 7. Idempotency-Key (D7) — banking-grade contract

### 7.1 Request shape

```http
POST /loan/decision HTTP/1.1
Content-Type: application/json
Idempotency-Key: 7f6a8c2e-0b4d-4e8a-9c1f-3d5b7e9a0c1f

{"applicant_id": "X-123", "amount": 50000}
```

### 7.2 Server response semantics

| Scenario | Response |
|---|---|
| First request with key → execute, cache (key → response_hash, response_body, timestamp), return response | 200 OK with normal body |
| Repeat request with same key within retention window AND identical request body | 200 OK with **byte-identical** cached response body. New `Idempotency-Status: replayed` response header |
| Repeat request with same key within retention window AND **different** request body | 422 Unprocessable Entity with structured error: `idempotency_key_reused_with_different_request` |
| Request without key on POST/PUT endpoint | Normal execute (no idempotency caching) |
| Request with key on GET/DELETE endpoint (per HTTP spec, those are idempotent natively) | Key ignored (logged) |

### 7.3 Retention window + storage

- Default 24h (configurable per-endpoint via `idempotency_window:` field in axonendpoint declaration — D7 future extension)
- Storage: in-memory LRU + optional disk-backed (postgres via existing `database_url`)
- Cross-tenant isolation: idempotency keys scoped per `client_id` (from auth bearer) so two tenants cannot collide

### 7.4 Industry-standard compatibility

Compatible with [Stripe Idempotency-Key spec](https://stripe.com/docs/api/idempotent_requests) byte-for-byte: same header name, same semantics, same retention default. Adopters who already wrap Stripe-style clients can point them at axon endpoints unchanged.

---

## ▶ 8. Auth scoping (D8) — `requires:` field

### 8.1 Declaration

```axon
axonendpoint AdminPolicyUpdate {
    method:    POST
    path:      "/admin/policy/{id}"
    body:      PolicyUpdate
    requires:  [admin, policy.write]   # ALL listed capabilities required
    execute:   ApplyPolicyUpdate
}
```

`requires:` is a comma-separated list of capability slugs. The bearer token must carry **all** declared capabilities (logical AND); for OR semantics adopters declare multiple axonendpoints with different `requires:` shapes pointing at the same execute flow.

### 8.2 Closed slug grammar

Capability slugs are dot-separated lowercase identifiers: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`. Examples valid: `admin`, `legal.read`, `hipaa.phi.read`, `bank.officer.senior`. Invalid: spaces, capitals, slashes, starting with digit.

### 8.3 Verification path

1. Request arrives with `Authorization: Bearer <token>`.
2. Token verified via existing Fase 11.c trust catalog (JWT signature OR HMAC OR Ed25519 — locked catalogue).
3. Token payload includes a `capabilities` claim — array of slugs.
4. Runtime checks `declared_requires ⊆ token_capabilities`.
5. If subset → proceed. Otherwise → 403 Forbidden with `{"error": "missing_capability", "required": ["admin", "policy.write"], "have": ["public.read"]}`.

### 8.4 OSS vs enterprise capability surface

- OSS: simple subset matching (above). Adopters maintain their own capability dictionary.
- Enterprise (Fase 21 integration surface): capabilities are registered + version-introspected through the `/.well-known/axon-capabilities` discovery endpoint; auditors can verify the runtime's capability set matches the deployed source's declared `requires:` references.

---

## ▶ 9. Replay tokens (D9) — regulator-grade audit

### 9.1 Binding

When `replay: true` (default for POST/PUT, false for GET/DELETE — declarable to override per-endpoint):

1. Successful response → entry written to ReplayLog (Fase 11.c primitive):
   ```json
   {
     "trace_id": "uuid",
     "timestamp": 1715459123,
     "endpoint_path": "/loan/decision",
     "method": "POST",
     "request_body_hash": "sha256:...",
     "response_body_hash": "sha256:...",
     "client_id": "tenant-X",
     "capabilities_used": ["bank.officer"],
     "model": "claude-opus-4.7",
     "backend_seed": "deterministic"
   }
   ```
2. Entry sealed by the per-tenant HMAC chain (Fase 11.c; enterprise: Fase 27.d mmap audit log).
3. Available via `GET /v1/replay/<trace_id>` (requires `replay.read` capability per D8).

### 9.2 Replay semantics

`GET /v1/replay/<trace_id>` returns:
- The original request body (if retained per retention policy — default 30 days, configurable)
- The original response body (always retained per audit policy)
- The ReplayLog metadata
- A `Replay-Status: deterministic|non_deterministic` header (deterministic when the original execution used a locked LLM model or stub; non-deterministic when a temperature > 0 was used)

For deterministic backends, an auditor can re-execute the original request body and confirm byte-identical response → regulatory replay primitive.

### 9.3 Verticals

- Banking: PCI DSS Req 10 — replay supports the transaction audit trail
- Government: FedRAMP AU-2 + AU-3 — replay supports event recording + content
- Legal: FRE 502 — replay supports inadvertent-waiver doctrine
- Medicine: 21 CFR Part 11 §11.10(e) — replay supports audit trail for electronic records

---

## ▶ 10. Tests target (~520 new tests)

| Surface | Test count | Module(s) |
|---|---|---|
| Route registration — `(method, path)` pairs registered correctly across all 5 enum values | 30 | Python + Rust |
| Path conflict detection at deploy time | 10 | both stacks |
| Path syntax validation (28 corpus entries × 2 stacks) | 56 | both stacks |
| Body schema validation positive (well-formed bodies accepted) | 20 | both stacks |
| Body schema validation negative (malformed → 400 with structured error) | 20 | both stacks |
| Output schema validation (well-formed responses pass) | 15 | both stacks |
| Output schema violation (server-side 500 + adopter diagnostic) | 10 | both stacks |
| Per-endpoint transport — sse/json/ndjson honored on dynamic routes (4 cells × content-negotiation × strict-mode = 16 cells) | 32 | Rust |
| Per-endpoint keepalive honored on SSE dynamic routes | 5 | Rust |
| Idempotency-Key — first request, replay, body mismatch (422), retention expiry, cross-tenant isolation, GET key ignored | 40 | Rust |
| Auth scoping — capability subset matching, missing capability 403, OSS vs enterprise modes | 35 | Python + Rust |
| Replay binding — POST/PUT default-on, GET/DELETE default-off, declarable override, replay endpoint, deterministic-status header | 25 | Rust |
| D8 + D9 backwards-compat — `/v1/execute` preserved verbatim with dynamic routes enabled + opt-out flag honored | 30 | Rust |
| Cross-stack drift gate (28-entry corpus × 5 assertions) | 140 | both stacks |
| D12-style 100-iter behavior fuzz on route registration | 100 (Py) + 100 (Rust) | both stacks |
| Vertical example integration tests (banking + government + legal + medicine canonical sources) | 40 | both stacks |

---

## ▶ 11. Out of scope (deferred to future fases)

- **OpenAPI 3.1 auto-generation from axonendpoint declarations** — natural follow-on; deferred to Fase 33. Enterprise already ships OpenAPI for Fase 21 surface; OSS port is a separate sub-fase.
- **WebSocket per-endpoint** — current scope is HTTP/REST. WebSocket bidirectional channels remain via the Fase 13 mobile typed channels surface; binding to per-axonendpoint paths is future.
- **gRPC binding** — Fase 2 Free Monad handler protocol already supports gRPC; per-endpoint gRPC service definitions are future.
- **GraphQL** — explicit decision: GraphQL is NOT axon's adopter surface. Axon ships REST + SSE + streaming algebraic effects; GraphQL violates the path-as-contract pillar by multiplexing through `/graphql`.
- **Distributed tracing OpenTelemetry export** — Fase 11.c ReplayLog + Fase 16 supervisor telemetry already emit OTLP; per-endpoint trace correlation deeper than `trace_id` is future.
- **LLM determinism (temperature > 0)** — replay (D9) works deterministically only for backends with deterministic execution (stub backend, locked LLM models). Temperature-based LLM call non-determinism is a separate concern; replay returns the cached response for the original execution, not a re-execution.
- **Request rate limiting per axonendpoint** — current per-endpoint rate limiting from Fase 16 supervisor applies; declarative per-endpoint rate-limit field (`rate_limit: "100/min"`) is future.
- **Response caching headers (ETag / Last-Modified)** — separate from idempotency caching; HTTP caching is future.

---

## ▶ 12. Versioning + release plan

**Target**: next available minor release after v1.22.0 (expected v1.23.0). Per versioning discipline: SemVer strict, secuencial sin saltos, version ≠ Fase.

**Why minor (not major)**: D8 + D9 backwards-compat absolute — `/v1/execute` preserved verbatim; new dynamic routes strictly additive; opt-out flag for adopters who don't want them. No silent breakage. The "major bump" reserved for the day a default actually breaks v1.20.x clients (none planned).

**axon-enterprise catch-up**: v1.13.0 lean bump (axon-lang dep pin >=1.22.0 → >=1.23.0) PLUS unlocks the substantive vertical-specific layers (banking idempotency persistence + government FedRAMP audit chain + legal FRE 502 privilege scope + medicine 21 CFR Part 11 binding). Could ship as v1.13.0 single or v1.13.0 + v1.14.0 sequential depending on the size of each vertical layer in 32.j docs scoping.

---

## ▶ 13. Sub-fase execution order + dependencies

Topological order:

```
32.a (this doc + D-letter ratification)
  └─ 32.b (path registration — Python + Rust route table sync)
       ├─ 32.c (body schema validation)
       │    └─ 32.d (output schema validation)
       ├─ 32.e (per-endpoint transport on dynamic routes)
       │    └─ 32.f (Idempotency-Key support)
       ├─ 32.g (auth scoping requires: field)
       ├─ 32.h (replay token binding)
       └─ 32.i (CI matrix + drift gate + fuzz)
            └─ 32.j (adopter docs)
                 └─ 32.k (coordinated release v1.23.0)
```

32.b is the foundation — every later sub-fase depends on dynamic routes existing. 32.c–32.h are parallelizable in principle but ship serially per founder cadence (same incremental sign-off pattern as Fase 28/30/31).

---

## ▶ 14. Founder principle reinforcement

> *"Hacer que una aplicación AI sea determinista y fundada en nuestros cuatro pilares como lenguaje es el aporte a la humanidad por el que estamos trabajando"* (2026-05-11)

Fase 32 is the moment axon graduates from *describing* HTTP REST in its source to *being* the HTTP REST runtime. Every adopter — from a hobbyist building a chat-with-llm app to a banking team deploying a SOC 2-audited credit decision pipeline — declares their REST surface in source and the runtime honors it verbatim.

For high-profile verticals specifically, Fase 32 unlocks **deterministic AI in regulated production**:

- **Banking**: `Idempotency-Key` is industry-standard; `replay: true` + ReplayLog is PCI DSS Req 10; auditable.
- **Government**: declarative routes + FedRAMP audit chain (enterprise) = inspectable surface; appealable decisions.
- **Legal**: privilege scope via `requires: [legal.privileged_review]` + replay = FRE 502-defensible.
- **Medicine**: HIPAA Safe Harbor + 21 CFR Part 11 + clinician-UI SSE on same endpoint + audit trail.

Each is a concrete contribution to humanity's ability to deploy AI in stakes-bearing contexts. The four pillars are not decoration — they are the engineering substrate that makes regulatable AI possible.

---

## ▶ 15. How to apply (post-shipping troubleshooting checklist)

When shipped, if an adopter reports *"my axonendpoint isn't responding at the declared path"*, walk this checklist:

1. **Is `--disable-dynamic-routes` set?** Check the server startup banner. If dynamic routes are disabled, `POST /v1/execute` is the only entry point.
2. **Did deploy succeed?** Check the `/v1/deploy` response — path conflicts return 409.
3. **Is the method correct?** Browser default is GET; check the client is sending the declared method.
4. **Is the body schema valid?** If declared, malformed bodies return 400 with `body_schema_violation` error.
5. **Does the bearer carry the required capabilities?** Missing capability returns 403 with structured `missing_capability` error.
6. **Is the request Idempotency-Key colliding with a previous body?** 422 with `idempotency_key_reused_with_different_request`.

After Fase 32 ships, no adopter should reach 8 version iterations on REST routing — the runtime registers their declared routes at deploy time and serves them with full Fase 30/31 transport + Fase 32 validation/idempotency/auth/replay semantics.

---

*This document is part of the axon-lang internal plan-vivo surface. Sibling adopter-facing docs ship in 32.j.*
