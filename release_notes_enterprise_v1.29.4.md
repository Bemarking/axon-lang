# axon-enterprise v1.29.4 — catch-up to axon-lang 1.38.5 (Path + Query as Request Binding sources, Fase 37.y)

**Patch catch-up.** Lifts the enterprise stack to axon-lang 1.38.5 + axon-frontend 0.19.3, inheriting transitively the Fase 37.y Request Binding source-set extension (path + query + body).

## What enterprise tenants get

Adopters building REST APIs in the enterprise Docker image (`axon/axon-enterprise:v1.29.4`) now declare their full request surface natively:

```axon
axonendpoint WriteSecret {
    method: POST
    path: "/api/tenants/{tenant_id}/secrets/{secret_name}"
    query: { dry_run: Bool? }
    body: SecretWriteRequest
    execute: WriteSecret
}
```

Path placeholders + query params + body fields all bind by name into the flow's parameter list with the same totality + collision-rejection guarantees (D3 + D4 `axon-T901`) that distinguish axon's compile-time discipline from FastAPI / Express / Spring / Axum runtime 4xx handling.

## Vertical inheritance

- **HIPAA Safe Harbor + 21 CFR Part 11** — clinical REST APIs `POST /api/patients/{patient_id}/observations` bind `patient_id` from the URL without a body-shadow field; the audit chain anchors the URL-path-derived identifier directly.
- **FRE 502 + Upjohn / Hickman** — privilege-review APIs `GET /api/matters/{matter_id}/documents?privilege_status=asserted` bind matter_id from path + privilege_status from query in a single declaration; D4 collision rejection prevents an accidental body-shadow that would mask the URL-derived value.
- **BSA / OFAC / MiFID II** — investigative APIs `POST /api/aml/cases/{case_id}/actions` with path-bound case_id + body-bound action — the catch-up unlocks the natural REST surface today (header binding is the next 37.z step).
- **FedRAMP AU-2** — government services `GET /api/applications/{application_id}/status?effective_date=YYYY-MM-DD` bind both segments compile-time-typed; the build refuses to ship an endpoint with a missing required binding.

## 5 D-letters (inherited from axon-lang 1.38.5)

- **D1** — Path placeholders extracted at parse time, typed `Text`.
- **D2** — Inline `query: { name: Type }` block with closed catalog `{Text, Int, Float, Bool, Uuid}`.
- **D3** — Totality check spans the union of three sources.
- **D4** — `axon-T901 parameter_name_clash` compile error for any name in 2+ sources — strict disambiguation.
- **D5** — Absolute backwards-compat for endpoints without path placeholders + without query blocks.

## Catch-up surface

- `pyproject.toml`: version 1.29.3 → 1.29.4, dep pin `axon-lang>=1.38.4` → `>=1.38.5`.
- `axon_enterprise/__init__.py`: `__version__` 1.29.3 → 1.29.4.

axon-frontend Rust crate dep bumps transitively from 0.19.2 → 0.19.3 (parser + AST + type-checker + IR generator changes for path+query surface).

v1.29.4 is a lean catch-up — same shape as v1.29.0 / v1.29.1 / v1.29.2 / v1.29.3. Per the standing rule (every axon-lang release ships an axon-enterprise catch-up), this closes the cycle in lockstep with axon-lang v1.38.5.
