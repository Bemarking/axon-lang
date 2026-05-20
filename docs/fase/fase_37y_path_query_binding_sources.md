---
title: "Plan vivo: Fase 37.y — Path + Query as Request Binding sources (extending the Fase 37 Request Binding Contract)"
status: ⏳ OPEN 2026-05-20 — adopter follow-up; awaiting execution.
owner: AXON Language + Runtime Team
created: 2026-05-20
target: |
  axon-lang **v1.38.5** (PATCH — additive binding sources; D5 backwards-compat absolute)
  axon-frontend **0.19.3** (AST gains `path_params` + `query_params`; D2 logic gains `axon-T901`)
  axon-enterprise **v1.29.4** (catch-up per standing rule)
depends_on: |
  Fase 37 CLOSED 2026-05-18 (Request Binding Contract; v1.36.0 — D1 by-name body
  binding + D2 compile-time totality + D4 only-declared-parameters-bind).
  Fase 37.x CLOSED 2026-05-19 (Pooler-coherent Store; v1.37.0).
  Fase 38.x.a–d CLOSED 2026-05-20 (Pooler-coherent Transactions + Admin Schema
  Isolation + IDENTITY recognition end-to-end).
  37.y is the second-half extension of the v1.36.0 Request Binding Contract:
  D2 totality stays the gate, but the BINDING SOURCES expand from "body only"
  to "path + query + body". The contract semantics (typed, by-name, totality-
  enforced) carry forward unchanged.

charter_class: |
  OSS end to end. Touches `axon-frontend/src/parser.rs` (extract path
  placeholders, parse new `query:` block), `axon-frontend/src/ast.rs`
  + `ir_nodes.rs` (two new AST/IR fields), `axon-frontend/src/type_checker.rs`
  (D2 union check + T901 collision error), `axon-rs/src/request_binding.rs`
  (new merged-source signature), `axon-rs/src/axon_server.rs` (axum
  extractor plumbing). Pure language substrate, vertical-agnostic.

# ▶ 1. The adopter's verdict on v1.38.4 (2026-05-20)

> *"Hallazgo importante: axon D2 NO auto-bindea path params al body.
> El endpoint POST /api/tenants/{tenant_id}/secrets/{secret_name}
> con body SecretWriteRequest exige que tenant_id y secret_name estén
> EN EL BODY también, no sólo en la URL. (Esto vale anotarlo a axon
> — UX mejorable: el path-param binding sería más natural.)"*

The adopter framed it as "UX mejorable" — improvable, not blocking.
The Fase 37.y cycle agrees with that framing: the contract works
correctly today (D1 binds by name from body, D2 catches missing
required params at compile time), but the BINDING SOURCE SET is
narrower than the natural HTTP REST pattern. An adopter who writes:

```axon
axonendpoint write_secret {
    method: POST
    path: "/api/tenants/{tenant_id}/secrets/{secret_name}"
    body: SecretWriteRequest
    execute: WriteSecret
}

type SecretWriteRequest { value: Text }

flow WriteSecret(tenant_id: Text, secret_name: Text, value: Text) -> WriteResult { … }
```

gets two compile errors:

```
axon-T??? axonendpoint 'write_secret' executes flow 'WriteSecret'
          whose required parameter 'tenant_id: Text' has no matching
          field in body type 'SecretWriteRequest'. … (Fase 37 D2).
axon-T??? axonendpoint 'write_secret' executes flow 'WriteSecret'
          whose required parameter 'secret_name: Text' has no matching
          field in body type 'SecretWriteRequest'. … (Fase 37 D2).
```

The adopter's workaround: ADD `tenant_id` + `secret_name` to
`SecretWriteRequest`, even though they're already in the URL path.
That works (D2 passes; runtime takes them from body, ignoring the
path) but produces an unnatural REST API surface.

# ▶ 2. Root cause: single-source binding

Two sites limit binding to body-only:

**Compile-time** — `axon-frontend/src/type_checker.rs:3373-3429`. For each flow
parameter, `body.fields.iter().find(|f| f.name == param.name)` — only
the body type's fields are scanned.

**Runtime** — `axon-rs/src/request_binding.rs:34-49`. Signature is
`bind_request_body(flow, body: Option<&Value>)`. The function reads
exclusively from the JSON body object; path / query never enter.

Fase 37.y extends both surfaces to a three-source set (path + query +
body) without changing the by-name + typed + totality semantics.

# ▶ 3. The Path-and-Query Binding Sources Contract — five D-letters

**D1 — Path params extracted at parse time, typed as `Text`.** The
`path: "/api/tenants/{tenant_id}/secrets/{secret_name}"` string is
scanned for `{name}` placeholders. Names appear on
`AxonEndpointDefinition.path_params: Vec<String>` and `IRAxonEndpoint.path_params`.
The HTTP convention is that path segments are text; v1.38.5 honors
that — every path param binds as `Text`. (Explicit type override per
path param — e.g. `{tenant_id: Uuid}` grammar — is honest-deferred to
Fase 37.z.)

**D2 — `query:` is a new optional inline block on `axonendpoint`.** The
adopter declares query parameters explicitly:

```axon
axonendpoint list_secrets {
    method: GET
    path: "/api/tenants/{tenant_id}/secrets"
    query: { status: Text?, limit: Int?, after: Uuid? }
    execute: ListSecrets
}
```

Closed type catalog: `{Text, Int, Float, Bool, Uuid}` (HTTP query
values are always strings until validated; this is the catalog the
parser converts to). Required vs optional declared via the existing
`?` suffix on type expressions. The inline syntax mirrors Fase 38's
inline `schema { col: Type }` block — same grammar shape, smaller
catalog, no constraint keywords (query params have no
`primary_key`/`identity`/etc analogue).

**D3 — D2 totality check runs over the UNION of three sources.** For
each required flow parameter, the type-checker searches:

1. `path_params` (typed as `Text`)
2. `query_params` (declared type)
3. `body.fields` (declared type)

If found in EXACTLY ONE source, D2 passes. If found in ZERO sources
AND parameter is required, the existing D2 error emits (now naming
all three sources in the hint). If found in MORE than one source,
**D4** fires.

**D4 — `axon-T901 parameter_name_clash` — new compile error code.**
When the same flow parameter name appears in two or more binding
sources, the type-checker emits:

```
axon-T901 axonendpoint 'write_secret' parameter 'tenant_id' is
          declared in BOTH path (`{tenant_id}`) and body type
          `SecretWriteRequest` (field `tenant_id: Text`). The
          Request Binding Contract forbids a name in multiple
          sources to keep the runtime binding unambiguous. Remove
          the field from the body OR rename the path placeholder.
          (Fase 37.y D4).
```

Opens a new `axon-T9nn` error namespace for Request Binding extensions
(distinct from `axon-T8nn` Store family). The strict-disambiguation
rule keeps the runtime merge order semantically irrelevant (no source
ever overrides another — every name resolves uniquely by construction).

**D5 — Absolute backwards-compat.** An endpoint with:

- a `path:` string containing NO `{name}` placeholders, AND
- no `query:` block

binds exactly as in v1.38.4 (body-only). D2 emits the legacy error
verbatim when a required param has no body field. Adopters NOT using
path/query parameters see zero behavioral change.

# ▶ 4. Sub-fases (37.y.a — single-cycle patch, parser-first)

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **37.y.1** | `axon-frontend/src/parser.rs` — scan `path:` string for `{name}` placeholders at parse time; populate `AxonEndpointDefinition.path_params`. | D1 | ✅ SHIPPED 2026-05-20 — new `pub path_params: Vec<String>` field on `AxonEndpointDefinition` ([ast.rs:858-878](../../axon-frontend/src/ast.rs#L858-L878)); new pure helper `extract_path_param_names(path: &str) -> Result<Vec<String>, String>` (hand-rolled scanner, zero regex dep, identifier grammar `[A-Za-z_][A-Za-z0-9_]*`, returns `Err(name)` on duplicate, ignores malformed brace content silently); hook in `parse_axonendpoint` after the `path:` field is consumed (duplicate placeholder → parse error with axonendpoint name + path + duplicate name in the message). **12 unit tests** in `parser::path_param_extraction_tests` covering: empty path, single placeholder, multiple in declaration order, the kivi corpus `/api/tenants/{tenant_id}/secrets/{secret_name}`, duplicate detection (adjacent + non-adjacent), underscore+numeric in names, leading underscore, malformed placeholder silently skipped, unterminated brace, boundary placeholders, light fuzz (9 weird inputs — emoji, null byte, `{{{`, etc. — never panic). **405/405** axon-frontend lib tests + **2096/2096** axon-rs lib tests green; zero regressions. NOT yet visible to adopter — field populated but not yet consumed by D2 or runtime (those land in 37.y.4 + 37.y.5/y.6). |
| **37.y.2** | `axon-frontend/src/parser.rs` — new `query: { name: Type, name: Type? }` inline block. Closed type catalog `{Text, Int, Float, Bool, Uuid}`. Mirror of Fase 38 inline `schema:` shape. | D2 | ✅ SHIPPED 2026-05-20 (100% robusto — hardened post initial impl) — new `pub query_params: Vec<TypeField>` field on `AxonEndpointDefinition` (reuses existing `TypeField` struct → D2 totality check downstream stays UNIFORM across body fields and query params). New closed-catalog constant `pub const AXONENDPOINT_QUERY_PARAM_TYPES: &[&str] = &["Text", "Int", "Float", "Bool", "Uuid"]` + helper `axonendpoint_is_valid_query_param_type`. New `"query"` arm in `parse_axonendpoint` field loop: parses `{ name: Type [, name: Type?]* }`, reuses `parse_type_expr` (so `?` optional suffix works identically to flow params); duplicate name within the block → parse error naming the duplicate; off-catalog type → parse error with **Fase 28-style smart-suggest hint** (`Did you mean \`Text\` or \`Int\`?`) AND the full catalog list in the message. Trailing comma optional (parser-style consistency). **Robustness hardening (post-initial)**: (a) **double-`query:` block** → parse error (silent merge masked adopter copy-paste typos; now surfaces line + column + "combine all params into a single block" hint); (b) **generic types** (`Optional<Text>`, `List<Int>`, `Stream<T>`, etc.) → parse error with type-specific canonical-syntax guidance: `Optional<X>` → "Use `X?` (the `?` suffix)"; `List<T>` → explicit deferral message naming multi-value query params + plan vivo §7; other generics → generic-rejection + closed-catalog list; (c) `Uuid?` + every-catalog-type-cross-optional verified composes cleanly; (d) `query: { }` empty block accepted as no-op (semantically equivalent to omitting the block). **19 unit tests total** in `parser::query_param_catalog_tests` + `parser::query_param_parser_tests` — 13 original + 6 hardening: `double_query_block_is_parse_error`, `optional_generic_type_is_parse_error_with_canonical_hint`, `list_generic_type_is_parse_error_with_deferral_hint`, `other_generic_types_caught_generically`, `uuid_optional_parses_cleanly`, `empty_query_block_yields_empty_vec`. Covers: every catalog entry accepted, off-catalog rejected (10 cases including lowercase/whitespace/`List<T>`/`Timestamp`/empty), catalog size pinned at 5, no-query-block ⇒ empty vec (D5), single required, single optional via `?`, multiple in declaration order (names + types + optional flags), duplicate parse error, off-catalog with full-catalog message, close-typo smart-suggest hint, every catalog type round-trips, comma-optional separator, **double-block rejection**, **generic-type rejection with canonical syntax hints**, AND the **kivi combined corpus** — `path: "/api/tenants/{tenant_id}/secrets/{secret_name}"` + `query: { dry_run: Bool?, overwrite: Bool? }` + `body: SecretWriteRequest` all parse cleanly with the right field populations from BOTH 37.y.1 and 37.y.2. **424/424** axon-frontend lib + **2096/2096** axon-rs lib green; zero regressions. NOT yet visible to adopter — field populated but D2 totality still runs body-only (lands in 37.y.4). |
| **37.y.3** | `axon-frontend/src/ast.rs` + `ir_nodes.rs` — add `path_params: Vec<String>` + `query_params: Vec<QueryParam>` to `AxonEndpointDefinition` + IR mirror. Serde `skip_serializing_if = empty` keeps IR JSON byte-identical for endpoints without path/query (D5). | D1, D2, D5 | ✅ SHIPPED 2026-05-20 — AST fields (`path_params: Vec<String>` + `query_params: Vec<TypeField>`) landed alongside 37.y.1 + 37.y.2; this sub-fase ships the IR mirror. (a) `IRTypeField` gains `Clone` (was Debug+Serialize only; needed for the query_params lowering map+collect path). (b) `IRAxonEndpoint` gains two new fields: `path_params: Vec<String>` + `query_params: Vec<IRTypeField>`, both with `#[serde(default, skip_serializing_if = "Vec::is_empty")]` so the v1.38.4 IR-JSON snapshot of an endpoint WITHOUT path placeholders + WITHOUT a query block is byte-identical to v1.38.5 — D5 IR-JSON backwards-compat absolute. (c) `IRGenerator::visit_axonendpoint` extended: `path_params` is a direct clone of the AST field; `query_params` maps each AST `TypeField` to an `IRTypeField` with `node_type: "type_field"` + `source_line`/`source_column` from the field's own loc + the type expression's `name`/`generic_param`/`optional` lowered as-is. **6 new unit tests** in `ir_generator::fase37y_ir_mirror_tests`: `ir_carries_path_params_from_ast`, `ir_carries_query_params_with_type_field_shape`, **`d5_byte_identity_when_no_path_or_query`** (the load-bearing D5 assertion — no `path_params` OR `query_params` key in JSON when both vecs are empty), `ir_json_emits_path_params_when_present`, `ir_json_emits_query_params_as_type_field_array`, AND the **kivi combined IR round-trip** — `path: "/api/tenants/{tenant_id}/secrets/{secret_name}"` + `query: { dry_run: Bool?, overwrite: Bool? }` + `body: SecretWriteRequest` all round-trip through IRGenerator with correct field shapes. **430/430** axon-frontend lib + **2096/2096** axon-rs lib green; zero regressions. Adopter LSP tools / `axon emit-ir` consumers see the new fields on endpoints with path/query declarations; pre-37.y endpoints (no path placeholders + no query block) emit byte-identical IR JSON to v1.38.4. |
| **37.y.4** | `axon-frontend/src/type_checker.rs` — D2 union check across path + query + body. New `axon-T901` collision error. Existing D2 error message updated to name all three sources in the "add the field" hint. | D3, D4 | ✅ SHIPPED 2026-05-20 — the load-bearing semantic shift. **Gate change**: pre-37.y the D2 check required `!body_type.is_empty() && !execute_flow.is_empty()`; post-37.y it requires `!execute_flow.is_empty() && (body OR path OR query)`. Endpoint with zero sources + zero required params remains a no-op (v1.36.0 honest scope preserved). **For each required flow param**, the checker now resolves THREE binding-source candidates: `path_hit` (any path placeholder matches the param name), `query_hit` (any query param matches), `body_hit` (any body field matches). The 3-way decision: **0 sources** → extended missing-binding error naming path placeholder + query block + body field as candidate fixes (load-bearing extension of the legacy Fase 37 D2 hint); **>1 source** → new `axon-T901 parameter_name_clash` error naming the colliding sources ("path and body", "path and query", "query and body", or "path, query, and body" with Oxford comma) + explicit count of removals needed ("Remove the declaration from N of the sources"); **exactly 1 source** → type-compatibility check per source-type: path implies `Text` no-generic (mismatch → error pointing at "change flow param to Text" OR "move to query"); query → exact name+generic match against the declared type (mismatch → error naming `query: { … }` block); body → preserved v1.36.0 logic verbatim. **12 new tests** in `type_checker::fase37y_d3_d4_tests`: D3 path-only / query-only / mixed coverage passes; D3 missing-param extended hint names all 3 sources; D4 collision for path+body, path+query, query+body, AND triple-source (with Oxford comma assertion); D3 path-typed-non-Text type-mismatch error; D3 query-type-mismatch error; D5 body-only legacy behavior intact (the v1.36.0 happy path AND missing-binding diagnostic shape unchanged for endpoints without path/query); AND the **kivi end-to-end corpus** — the exact `write_secret` endpoint with path `/api/tenants/{tenant_id}/secrets/{secret_name}` + query `{ dry_run: Bool?, overwrite: Bool? }` + body `SecretWriteRequest { value: Text }` + a 5-param flow now compiles GREEN (pre-37.y it was the blocking compile error). **442/442** axon-frontend lib + **2096/2096** axon-rs lib green; zero regressions. **First sub-fase visible to adopter** — `axon check` now accepts path/query-bound flows AND rejects collisions with T901. Runtime delivery still uses the legacy body-only binder; that lands in 37.y.5 + 37.y.6. |
| **37.y.5** | `axon-rs/src/request_binding.rs` — new signature `bind_request(path, query, body)` returning `Vec<(String, String)>`. Path values are `Text` (raw URL-decoded); query values are stringified per the existing `binding_string` rules; body fields binding unchanged. Legacy `bind_request_body` retained as a thin delegate calling `bind_request(empty, empty, body)` so existing tests + non-axon-server callers stay unchanged. | D5 | ✅ SHIPPED 2026-05-20 — new `pub fn bind_request(flow, path: &HashMap<String,String>, query: &HashMap<String,String>, body: Option<&Value>) -> Vec<(String, String)>`. Source precedence path > query > body (D4 invariant — by construction the value is in AT MOST one source via `axon-T901`; the precedence order is documentation, not semantics). Path + query values clone directly (already text); body values stringify via the existing `binding_string` (D5 preserved — JSON string → raw, null → empty, scalars → canonical, struct/array → compact JSON). The legacy `bind_request_body(flow, body)` is now a thin delegate `bind_request(flow, &HashMap::new(), &HashMap::new(), body)` — all 6 pre-37.y unit tests in this module pass unchanged (D5 byte-identical), no source change needed at non-axon-server callers. **8 new tests**: `d3_path_only_binding`, `d3_query_only_binding`, `d3_mixed_path_query_body`, `d4_invariant_value_taken_from_earliest_source_in_precedence` (documents the source order; D4 makes the case impossible at compile time), `d5_bind_request_body_legacy_delegate_byte_identical`, `d5_empty_inputs_yield_empty_binding`, `d4_undeclared_path_or_query_keys_are_ignored` (mirrors the body-side D4 from v1.36.0), AND `kivi_end_to_end_runtime_binding` (5 flow params resolving from 3 sources — path: tenant_id + secret_name, query: dry_run + overwrite, body: value — all in declaration order). **14/14** request_binding tests green (6 v1.36.0 + 8 new). **2104/2104** axon-rs lib green; zero regressions. The binder is READY for the axum extractor to wire in (37.y.6) — the runtime path can now bind a multi-source HTTP request to a flow per the 37.y contract end-to-end. |
| **37.y.6** | `axon-rs/src/axon_server.rs` — axum extractor plumbing: `axum::extract::Path<HashMap<String, String>>` for path captures + `axum::extract::Query<HashMap<String, String>>` for query string. Wire both into the `bind_request` call site that already handles body. | D5 | ✅ SHIPPED 2026-05-20 — **load-bearing implementation closing the runtime gap.** Discovered pre-37.y `dynamic_endpoint_handler` did EXACT-string `(method, path)` lookup against the registered routes table — so a deployed `/api/tenants/{tenant_id}` would NEVER match real request URLs like `/api/tenants/acme`. The path placeholders were declared but structurally unreachable from the runtime. **5 new public helpers** in `axon_server.rs`: (1) `match_path_template(template, actual) -> Option<HashMap<String,String>>` — pure + total scanner over `/`-split segments; `{name}` segments capture; non-placeholder segments require byte-equality; defense-in-depth identifier-shape validation; placeholder against empty actual segment fails (HTTP `/api/{id}` MUST NOT match `/api/`). (2) `parse_query_string(Option<&str>) -> HashMap<String,String>` — `&`-split key=value pairs; first-value semantics for multi-value keys (deferred per plan vivo §7); calls (3). (3) `url_decode(s)` — minimal `%XX` + `+` decoder; lossy UTF-8 from hostile clients gets replacement chars rather than panic. (4) Two-step route lookup in `dynamic_endpoint_handler`: fast-path exact lookup (D5 — legacy routes without placeholders preserve v1.38.4 hot-path performance), then linear scan template-match fallback over routes with `path_params` non-empty; first match wins (intra-program collision check from Fase 32 D2 ensures no two TEMPLATES capture the same actual URL under the same method). (5) `DynamicEndpointRoute` gains `path_params: Vec<String>` (copied from AST at `collect_axonendpoint_routes`). **Signature thread-through across 5 layers**: `ExecuteRequest` + `StreamExecuteRequest` gain `request_path: HashMap<String,String>` + `request_query: HashMap<String,String>` (serde `#[serde(default)]` → D5 backwards-compat for `/v1/execute` JSON RPC callers); `server_execute` + `execute_with_fallback` + `runner::execute_server_flow` + `axon_server::server_execute_streaming` + `streaming_via_dispatcher::run_streaming_via_dispatcher` all accept the two new maps. **End-to-end pipeline**: HTTP request → axum `.fallback()` → `dynamic_endpoint_handler` extracts path+query → `ExecuteRequest`/`StreamExecuteRequest` → `execute_handler`/`execute_sse_handler_inner` → `execute_with_fallback`/`server_execute_streaming` → `runner::execute_server_flow`/`run_streaming_via_dispatcher` → `request_binding::bind_request(path, query, body)` → `ExecContext.let_bindings` / `DispatchCtx.let_bindings` → `${tenant_id}` interpolates in `where:`/`persist`/`mutate`/`ask:`. **5 call-site updates**: 4 `run_streaming_via_dispatcher` test sites + `execute_handler_with_negotiation` JSON→SSE promotion path (path+query travel across the content-negotiation transition). **442/442** axon-frontend lib + **2104/2104** axon-rs lib green; zero regressions. **Adopter visible end-to-end** — a deployed `axonendpoint write_secret { path: "/api/tenants/{tenant_id}/secrets/{secret_name}" query: { dry_run: Bool? } body: SecretWriteRequest execute: WriteSecret }` now (a) routes the request to the right flow via template matching, (b) extracts tenant_id + secret_name from the URL captures, (c) extracts dry_run from the query string, (d) extracts value from the JSON body, (e) seeds all FIVE into the flow's `let_bindings` BEFORE the first step runs — exactly as the kivi adopter requested. |
| **37.y.7** | New anchor `axon-rs/tests/fase37y_path_query_binding_sources.rs` — 7 §-assertions covering D1–D5. | All | ✅ SHIPPED 2026-05-20 — single anchor file [axon-rs/tests/fase37y_path_query_binding_sources.rs](../../axon-rs/tests/fase37y_path_query_binding_sources.rs) pins the v1.38.5 surface end-to-end via the public `build_router` + `Lexer`+`Parser`+`TypeChecker` surfaces (no `pub(crate)` reach-through). **8 tests** = 7 §-assertions + 1 STATIC grep §S: **§1** D1 path-param extraction (`Lexer` + `Parser` on the kivi corpus `/api/tenants/{tenant_id}/secrets/{secret_name}` → `AxonEndpointDefinition.path_params == ["tenant_id", "secret_name"]` in declaration order); **§2** D3 path-only coverage (typecheck-level: flow with `tenant_id: Text` covered SOLELY by path placeholder + body without `tenant_id` → no `axon-T??? Request Binding` error in result set; the legacy v1.38.4 "no matching field in body" error is gone); **§3** D3 query-only coverage (typecheck-level: flow `status: Text` covered by `query: { status: Text }` block; no body declared); **§4** D3 mixed coverage end-to-end (deploy + `POST /api/tenants/TENANT_S4/secrets?dry_run=DRY_S4` + body `{"value":"VALUE_S4"}` through axum router; all 3 values reach the step's `ask:` interpolation; no `${name}` token survives un-interpolated); **§5** D4 T901 collision (typecheck-level: `tenant_id` declared in path AND body → `axon-T901 parameter_name_clash` error naming `tenant_id` + BOTH `"path"` AND `"body"` source words); **§6** D5 backwards-compat (deploy body-only `payload: String` flow + hit `/legacy` → wire byte-identical to v1.38.4 anchor surface); **§7** runtime merges deterministically (5-param flow spanning all 3 sources: `tenant_id`+`secret_name` from path, `dry_run`+`overwrite` from query, `value` from body; every value reaches the step in declared param order; D4 invariant guards every name from leftover un-interpolated tokens). **§S STATIC grep** reads `axon-frontend/src/ast.rs` + `axon-frontend/src/parser.rs` + `axon-rs/src/request_binding.rs` + `axon-rs/src/axon_server.rs` at test time via `include_str!` and pins 7 surface declarations (`pub path_params: Vec<String>`, `pub query_params: Vec<TypeField>`, `pub(crate) fn extract_path_param_names`, `pub const AXONENDPOINT_QUERY_PARAM_TYPES`, `pub fn bind_request`, `pub fn bind_request_body`, `pub(crate) fn match_path_template`, `pub path_params: Vec<String>` on `DynamicEndpointRoute`) — a future refactor that drops any of these silently regresses the load-bearing 37.y D1-D5 surface and this assertion catches it before the runtime tests even load. **Type-discipline learnings baked in** (so 37.y stays a teachable anchor for future fases): (a) path-bound flow params MUST be `Text` (HTTP path-segment convention enforced by the D3 type-compat check); (b) body fields MUST use the route-schema builtin primitives `{String, Integer, Float, Boolean, Duration, Any}` (the runtime body-schema validator gates on this catalog; `Text` is unknown there); (c) query-param types MUST be from the catalog `{Text, Int, Float, Bool, Uuid}`. **442/442** axon-frontend lib + **2104/2104** axon-rs lib + **8/8** 37.y anchor green; zero regressions. The anchor file is the load-bearing single-source-of-truth for the 37.y contract — every future "Request Binding source" extension (headers in 37.z, etc.) adds a § here. |
| **37.y.8** | Coordinated patch release axon-lang **v1.38.5** + axon-frontend **0.19.3** (additive AST + IR fields + new compile error). axon-enterprise **v1.29.4** catch-up per the standing rule. | — | ⏳ |

# ▶ 5. Test surface — 7 §-assertions

| § | What it pins | Mode |
|---|---|---|
| **§1** | D1 path-param extraction: `path: "/api/tenants/{tenant_id}/secrets/{secret_name}"` → `path_params = ["tenant_id", "secret_name"]` (parser unit test) | unit |
| **§2** | D3 path-only param coverage: endpoint with `path={tenant_id}` + body=SecretWriteRequest (no `tenant_id` field) + flow takes `tenant_id: Text` → `axon check` passes (the legacy v1.38.4 error is GONE) | integration |
| **§3** | D3 query-only param coverage: endpoint with `query: { status: Text? }` + flow takes `status: Text?` → `axon check` passes | integration |
| **§4** | D3 mixed coverage: endpoint with `path={tenant_id}` + `query: { limit: Int? }` + `body: T { value: Text }` + flow takes all three → passes | integration |
| **§5** | D4 collision T901: endpoint with `path={tenant_id}` AND `body: T { tenant_id: Text, value: Text }` → compile error `axon-T901` naming both sources | integration |
| **§6** | D5 backwards-compat: endpoint with no path placeholders + no query block + body-only flow → behavior byte-identical to v1.38.4 | integration |
| **§7** | Runtime binding merges path + query + body deterministically; D4 invariant means merge order is irrelevant; flow with `tenant_id` from path receives the path value (not the body value, which can't exist post-D4) | integration |

Plus a STATIC grep §-assertion in the same anchor file pinning that
the new `path_params` field appears in the AST struct definition AND
the parser's `parse_axonendpoint` populates it. The grep guards
against a future refactor accidentally dropping the surface.

# ▶ 6. Forward-compatibility commitments

- **`axon-T9nn` namespace** is reserved for future Request Binding
  extensions (Fase 37.z, 38.x extensions, etc.). T901 opens it; T902+
  is available.
- **Path-param type declaration `{tenant_id: Uuid}`** is a future
  Fase 37.z surface; today every path param binds as `Text`. The
  `path_params: Vec<String>` representation can grow to
  `Vec<PathParam { name, type_expr }>` without breaking v1.38.5
  manifests (no manifest format change in this cycle — endpoints
  don't roundtrip through a manifest).
- **Headers as binding source** is a future Fase 37.z candidate. The
  current `bind_request(path, query, body)` signature can grow a
  `headers` parameter additively without breaking existing callers.
- **Multi-value query params** (`?tag=a&tag=b`) bind as the FIRST
  observed value in v1.38.5 (semantics axum's `Query<HashMap>`
  provides). A future Fase 37.z can expose `List<T>` query params
  honestly.

# ▶ 7. What is intentionally NOT in v1.38.5

- **Path-param type override grammar** (`{tenant_id: Uuid}`) —
  Fase 37.z candidate. Today every path param is `Text`; flow
  parameters consume the textual value or validate explicitly.
- **Headers as binding source** — Fase 37.z candidate.
- **Multi-value query params** — first-value semantics in v1.38.5.
- **Python parser parity for the new `query:` block** — per
  founder directive *"todo encaminado a ser 100% Rust + C, 0 Python"*,
  Python frontend stays at v1.33 surface. Adopters using the Rust
  binary (the `axon/axon-enterprise:vX.Y.Z` Docker image) get the
  full surface.
- **Form-encoded bodies (`application/x-www-form-urlencoded`)** —
  axon's `body:` contract is JSON-only today; form encoding stays
  out of scope. Adopters needing form-encoded bodies use query
  params for the same fields.

# ▶ 8. The two-question gate

Per standing rule (memory `feedback_plan_vivo_two_questions`), every
axon plan vivo answers both questions honestly with concrete points.

## Q1 — Is this market standard, or superior to what other languages offer?

**Axis 1: source set (path + query + body) — PARITY.** Every
mainstream HTTP framework offers all three binding sources:

| Framework | Path | Query | Body | Mechanism |
|---|---|---|---|---|
| FastAPI (Python) | `Path(...)` | `Query(...)` | `Body(...)` | Annotated parameters |
| Express (Node.js) | `req.params.tenant_id` | `req.query.status` | `req.body.value` | Unified `req` object |
| Spring (Java) | `@PathVariable` | `@RequestParam` | `@RequestBody` | Annotations |
| Axum (Rust) | `Path<HashMap<String,String>>` | `Query<HashMap<String,String>>` | `Json<T>` | Extractors |
| Rails (Ruby) | `params[:tenant_id]` (unified) | `params[:status]` (unified) | `params[:value]` (unified) | Unified `params` hash |
| NestJS (Node) | `@Param('tenant_id')` | `@Query('status')` | `@Body()` | Decorators |

37.y closes axon's parity gap. The source set is table-stakes.

**Axis 2: safety guarantees — SUPERIOR.** Where axon advances the
state of the art:

| Property | axon 37.y (this) | FastAPI | Express | Spring | Axum |
|---|---|---|---|---|---|
| Compile-time totality (required param missing → build fails) | ✅ D3 | ❌ runtime 422 | ❌ runtime undef | ❌ runtime null | ❌ runtime 400 |
| Compile-time collision rejection (name in 2+ sources → build fails) | ✅ D4 T901 | ❌ silent precedence | ❌ silent precedence | ❌ silent precedence | ❌ silent precedence |
| Type-checked binding across all sources | ✅ via Fase 37 D2 | ⚠️ Pydantic runtime | ❌ untyped | ⚠️ runtime cast | ⚠️ serde runtime |

The TWO superiority axes — **compile-time totality** (Fase 37 D2) and
**compile-time collision rejection** (37.y D4) — are not present in
any framework reviewed. Adopters who pass `axon check` cannot deploy
an endpoint with a missing-required-binding OR an ambiguous-source
name. Other frameworks catch both at request time, with 4xx
responses. axon catches them at build time, refusing to ship the
binary.

This continues axon's pattern: "every adopter dimension that matters
is proven before a request is served" (Pillar V framing). Fase 37
established the binding-source-totality theorem for body-only; 37.y
extends it to the three-source universe.

## Q2 — Minimum to run, or robust and complete for large, complex adopters?

**Target adopter profile:** multitenant SaaS adopters serving
regulated verticals (HIPAA / FRE 502 / BSA-OFAC / FedRAMP) AND general-
purpose LLM-powered applications. The 95% case for these adopters is
REST APIs with: typed path identifiers (tenant_id, resource_id),
optional query filters (status, pagination, search), structured JSON
bodies (payload + metadata). 37.y serves this case end-to-end.

**ROBUST scope in v1.38.5:**

- ✅ Path params extracted + bound + typed (`Text` convention)
- ✅ Query params declared via inline `query: { … }` block (5 primitive
  types: Text / Int / Float / Bool / Uuid)
- ✅ Body params (unchanged from Fase 37 v1.36.0)
- ✅ Type-system integration — every source's type-checked
- ✅ Compile-time totality (D3) AND compile-time collision rejection
  (D4 T901)
- ✅ axum runtime extractor wiring for all three sources
- ✅ D5 backwards-compat absolute — endpoints w/o path placeholders +
  w/o query block byte-identical to v1.38.4
- ✅ 7 §-assertions + STATIC grep §-assertion (regression guard)
- ✅ Cross-stack release (axon-lang + axon-frontend + axon-enterprise
  catch-up per the standing rule)

**HONESTLY DEFERRED to Fase 37.z (next cycle if adopter demand
materializes):**

- ❌ **Headers as binding source** — needed by multitenant SaaS
  using header-based tenant routing (`X-Tenant-ID`). Non-trivial:
  case-insensitive name resolution + kebab-case-to-snake_case
  mapping + multi-value semantics + filtering reserved headers
  (`Host`, `User-Agent`).
- ❌ **Path-param type override** — `path: "/users/{id: Uuid}"`
  grammar lets adopter declare path-param types beyond the default
  `Text`. Today the flow can validate explicitly (Fase 37 Untrusted
  type discipline), so this is ergonomic-only.
- ❌ **Multi-value query params** — `?tag=a&tag=b` binds as the FIRST
  value in v1.38.5. A future arm exposes `List<T>` query types
  honestly.
- ❌ **Form-encoded bodies** (`application/x-www-form-urlencoded`)
  — out of scope. axon's `body:` contract is JSON-only;
  form-encoded fields can be modeled via query params.
- ❌ **Python parser parity** for the new `query: { … }` block —
  Rust-canonical per founder directive 2026-05-15; Python frontend
  stays at v1.33 surface.

**Forward-compat commitments** (so deferred items ship additively):

- `bind_request(path, query, body)` signature can grow `headers` as
  a fourth parameter without breaking existing callers.
- `path_params: Vec<String>` can grow to `Vec<PathParam { name,
  type_expr }>` when the type-override grammar lands — IR JSON
  emits `path_params: [{name: …}]` either way.
- `axon-T9nn` error namespace reserved for future Request Binding
  extensions; T902–T999 available.

**The honest answer to Q2: ROBUST for the 95% multitenant SaaS REST
adopter; HONESTLY DOCUMENTED gaps for the 5% header-routed
multitenant + form-encoded + multi-value query case.** Large
regulated-vertical adopters (HIPAA / FRE 502 / BSA-OFAC / FedRAMP)
typically fall in the 95% set. An adopter who needs headers today
files a Fase 37.z trigger report; the architecture is ready to grow
additively.

# ▶ 9. The trigger source

- 2026-05-20 — kivi adopter migration doc, post-v1.38.4 follow-up:
  *"Hallazgo importante: axon D2 NO auto-bindea path params al body.
  […] vale anotarlo a axon — UX mejorable: el path-param binding
  sería más natural."*
- Founder principle: *"Seguimos avanzando en hacer de axon un
  lenguaje sólido, completo y sofisticado."* — natural REST
  ergonomics is part of "sólido + completo + sofisticado".
- Standing rule (memory `feedback_enterprise_catch_up_always`): every
  axon-lang release ships an axon-enterprise catch-up.

Closed when axon-lang v1.38.5 + axon-enterprise v1.29.4 are both
live cross-stack (PyPI + crates.io + GitHub Release + Rust binaries
+ ECR Private image).
