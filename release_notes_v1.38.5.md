# axon-lang v1.38.5 — Path + Query as Request Binding sources (Fase 37.y)

**Patch.** Extends the v1.36.0 Request Binding Contract from body-only to a three-source set: **path placeholders + query string + body**. The contract semantics (typed, by-name, totality-enforced) carry forward — only the source universe is wider.

## What's new

The `axonendpoint` declaration now declares its full request surface:

```axon
type SecretWriteRequest { value: String }

axonendpoint WriteSecret {
    method: POST
    path: "/api/tenants/{tenant_id}/secrets/{secret_name}"
    query: { dry_run: Bool? }
    body: SecretWriteRequest
    execute: WriteSecret
}

flow WriteSecret(tenant_id: Text, secret_name: Text, dry_run: Text, value: String) -> WriteResult { … }
```

A request to `POST /api/tenants/acme/secrets/api-key?dry_run=true` with body `{"value":"S3CR3T"}` now binds all four parameters — `tenant_id`, `secret_name` from the path; `dry_run` from the query; `value` from the body — before the first step runs. Pre-v1.38.5 the adopter had to add path-shadow fields to the body type, producing an unnatural REST surface.

## Five D-letters

- **D1 — Path params extracted at parse time, typed as `Text`.** `{name}` placeholders in the `path:` string become `AxonEndpointDefinition.path_params` in declaration order. Duplicates raise a parse error.
- **D2 — New `query: { name: Type, name: Type? }` inline block.** Closed type catalog: `{Text, Int, Float, Bool, Uuid}`. Optional via the existing `?` suffix. Generic types (`Optional<X>`, `List<T>`) rejected with canonical-syntax guidance. Double `query:` block rejected — the adopter copy-paste typo is now surfaced rather than silently merged.
- **D3 — D2 totality check runs over the union of THREE sources.** For each required flow parameter, the checker counts hits across path, query, and body. Zero hits = extended "missing binding" error naming all three candidate sources. Exactly one hit = per-source type-compatibility check. The legacy v1.38.4 "no matching field in body" error is gone for path/query-bound params.
- **D4 — `axon-T901 parameter_name_clash` — new compile error.** When the same parameter name appears in 2+ sources, the type-checker rejects the program at build time (Oxford-comma source listing: "path, query, and body"). The strict-disambiguation rule keeps the runtime merge order semantically irrelevant — no source ever overrides another.
- **D5 — Absolute backwards-compat.** Endpoints with no `{name}` in the path and no `query:` block bind exactly as in v1.38.4. `bind_request_body(flow, body)` is preserved as a thin delegate calling `bind_request(flow, empty, empty, body)` — byte-identical behavior for v1.36.0-style callers.

## Where axon advances the state of the art

Mainstream HTTP frameworks (FastAPI, Express, Spring, Axum, Rails, NestJS) all offer all three binding sources. axon's contribution is at the **safety** layer:

| Property | axon 37.y | FastAPI | Express | Spring | Axum |
|---|---|---|---|---|---|
| Compile-time totality (required param missing → build fails) | ✅ D3 | ❌ runtime 422 | ❌ runtime undef | ❌ runtime null | ❌ runtime 400 |
| Compile-time collision rejection (name in 2+ sources → build fails) | ✅ D4 T901 | ❌ silent precedence | ❌ silent precedence | ❌ silent precedence | ❌ silent precedence |

Adopters who pass `axon check` cannot deploy an endpoint with a missing-required-binding or an ambiguous-source name. Other frameworks catch both at request time with 4xx responses; axon catches them at build time, refusing to ship the binary.

## Runtime: dynamic-route dispatcher with template matching

The pre-37.y dispatcher did an exact-string `(method, path)` lookup against the registered routes table — so a deployed `/api/tenants/{tenant_id}` would never match real request URLs like `/api/tenants/acme`. v1.38.5 adds a two-step lookup:

1. **Fast path**: exact `(method, path)` match — preserves v1.38.4 hot-path performance for placeholder-less routes (D5).
2. **Template-match fallback**: linear scan over routes with non-empty `path_params`; first template that matches the actual URL wins. Captures the placeholder values into a `HashMap<String,String>` that threads through the full pipeline:

```
HTTP request → axum .fallback() → dynamic_endpoint_handler
  → ExecuteRequest/StreamExecuteRequest (path+query as serde-defaulted fields)
  → execute_handler/execute_sse_handler_inner
  → execute_with_fallback/server_execute_streaming
  → runner::execute_server_flow/run_streaming_via_dispatcher
  → request_binding::bind_request(path, query, body)
  → ExecContext.let_bindings / DispatchCtx.let_bindings
  → ${name} interpolates in where:/persist/mutate/ask:
```

The two-step lookup + serde-defaulted `request_path` + `request_query` fields preserve byte-identical behavior for every non-dynamic-route caller (legacy `/v1/execute` JSON RPC, all internal tests).

## What's intentionally NOT in v1.38.5

- Path-param type override grammar (`{tenant_id: Uuid}`) — Fase 37.z candidate; today every path param is `Text`.
- Headers as binding source — Fase 37.z candidate; the architecture is ready to grow additively.
- Multi-value query params (`?tag=a&tag=b`) — first-value semantics in v1.38.5; honest `List<T>` query types are Fase 37.z.
- Form-encoded bodies — axon's `body:` contract is JSON-only.
- Python parser parity for the new `query:` block — per founder directive "todo encaminado a ser 100% Rust + C, 0 Python"; Python frontend stays at v1.33 surface.

## Test surface

- **442/442** axon-frontend lib tests green (12 new in `type_checker::fase37y_d3_d4_tests`, 19 new in `parser::query_param_*` + `path_param_extraction_tests`, 6 new in `ir_generator::fase37y_ir_mirror_tests`).
- **2104/2104** axon-rs lib tests green (8 new in `request_binding::tests` for the 3-source binder).
- **8/8** new anchor `axon-rs/tests/fase37y_path_query_binding_sources.rs` — 7 §-assertions covering D1–D5 + a STATIC grep §S pinning the surface declarations.
- Zero regressions cross-stack.

## Trigger

kivi adopter migration doc, post-v1.38.4 follow-up: *"Hallazgo importante: axon D2 NO auto-bindea path params al body. […] vale anotarlo a axon — UX mejorable: el path-param binding sería más natural."* Closed with strict-disambiguation D4 invariant — the source set grew without compromising the safety guarantees that distinguish axon from every framework reviewed.

Plan vivo: [docs/fase/fase_37y_path_query_binding_sources.md](docs/fase/fase_37y_path_query_binding_sources.md).
