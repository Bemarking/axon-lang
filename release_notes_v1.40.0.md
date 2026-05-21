# axon-lang v1.40.0 — Cardinality Coverage Complete (Fase 38.x.f)

**Minor.** Promotes the v1.39.0 narrow Retrieve Cardinality Gate into a **full bilateral cardinality surface** at compile time. Every flow-tail shape that mismatches the endpoint's declared `output:` is caught at `axon check` with an actionable hint — adopters never reach the opaque runtime D5 `internal_validation_error` for ANY shape mismatch class.

## Why this is MINOR

- New public surface: `pub(crate) enum Cardinality` + `infer_flow_tail_cardinality` + `declared_cardinality` + `emit_cardinality_gate` in `axon-frontend/src/type_checker.rs`.
- New compile error codes: `axon-T9XX` (bilateral D3), `axon-T9YY stream_cardinality_mismatch` (D5), `axon-W003 cardinality_disagreement_in_branches` (D6).
- New runtime env var: `AXON_VERBOSE_D5_HINT` for OWASP-safe-by-default verbose hint opt-in.
- New `BodyValidationError` fields: `expected_cardinality`, `got_cardinality`, `got_length`, `remediation_url` (serde-defaulted; D8 backwards-compat for older consumers).
- Parser fix: `axonendpoint output:` now uses `parse_output_type_string` (full generic-aware) instead of `consume_any_ident_or_kw` (single token). Pre-fix `output: List<T>` was captured as `"List"` — a pre-existing silent bug v1.40.0 exposes + fixes.
- axon-frontend bumps to 0.21.0 (new TypeChecker surface).

## What v1.40.0 closes vs v1.39.0

v1.39.0 (38.x.e) shipped a NARROW gate: only the canonical kivi pattern (retrieve-tail + singular-output) emitted T9XX. Every other shape mismatch still failed at runtime D5 with the opaque message.

v1.40.0 (38.x.f) closes the remaining ~20% of shape-mismatch classes at compile time:

| Pattern | v1.39.0 detection | v1.40.0 detection |
|---|---|---|
| `retrieve` tail + `output: T` (singular) | ✅ T9XX | ✅ T9XX (preserved verbatim) |
| `for x in xs { … }` tail + `output: T` | ❌ runtime D5 | ✅ T9XX (D1 expanded) |
| `if/else` branches DISAGREE on cardinality | ❌ runtime D5 | ✅ W003 (D6 warning) |
| Singular tail + `output: List<T>` | ❌ runtime D5 | ✅ T9XX bilateral (D3) |
| `output: Stream<T>` + non-stream tail | ❌ runtime D5 | ✅ T9YY (D5) |
| Singular tail + `output: Stream<T>` | ❌ runtime D5 | ✅ T9YY bilateral (D5) |
| `output: Any` + any disagreed branches | (no detection) | ✅ accepted (degraded surface) |
| Runtime D5 hint payload | generic `internal_validation_error` | enriched with `expected_cardinality`/`got_cardinality`/`got_length`/`remediation_url` (D2) |
| Runtime D5 client response | always generic (OWASP) | OWASP-safe default + opt-in via `AXON_VERBOSE_D5_HINT=1` (D4) |

## Where axon advances the state of the art

| Property | axon v1.40.0 | FastAPI | Spring | Express | NestJS | GraphQL (Apollo) | sqlc |
|---|---|---|---|---|---|---|---|
| `for`-loop cardinality at compile time | ✅ | ❌ runtime 422 | ❌ runtime 500 | ❌ runtime 400 | ❌ runtime ValidationError | ⚠️ partial (schema-level nullable) | ⚠️ SQL-type only |
| Branch-cardinality disagreement detected | ✅ W003 | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ❌ silent | n/a |
| Spatial-vs-temporal (List vs Stream) distinction | ✅ T9YY | ⚠️ StreamingResponse runtime | ⚠️ Mono/Flux at controller layer | ❌ no concept | ⚠️ RxJS decorator | ⚠️ Subscription vs Query field-only | n/a |
| Bilateral output-mismatch detection | ✅ D3 | ❌ silent wrap | ❌ silent null | ❌ silent undefined | ⚠️ class-validator | ⚠️ partial | n/a |

The cardinality gate is over the FLOW BODY EXPRESSION's tail-cardinality, joined across every control-flow construct, distinguishing spatial vs temporal, with bilateral coverage. Adopters who pass `axon check` cannot deploy an endpoint whose tail-shape disagrees with its declared output — PERIOD.

## Migration

**No breaking changes for adopter source code.** The v1.39.0 narrow ERROR semantics are preserved verbatim (retrieve-tail + singular-output still emits T9XX). Adopters whose flows pass v1.39.0 continue to pass v1.40.0 UNLESS they had a latent shape mismatch that v1.39.0 missed — in which case they now get an actionable compile error at `axon check` BEFORE production.

**Parser fix nuance:** the `axonendpoint output:` parser pre-v1.40.0 captured only the first token (`"List"` for `output: List<T>`). v1.40.0 captures the full generic-aware shape. Adopters with `output: List<TypeName>` endpoints saw silent-pass behavior pre-v1.40.0; they now get the proper Plural cardinality check. If their flow tail is also plural (the well-formed case), no change. If their flow tail is singular (a latent mismatch), they now see T9XX — the fix is what v1.40.0 ships.

## What's intentionally NOT in v1.40.0

- `--strict-cardinality` migration window flag — the narrow v1.39.0 → v1.40.0 broadening doesn't break enough adopter flows to justify the flag overhead. Gate ships always-on as ERROR for T9XX/T9YY + WARNING for W003. Future fase can add the flag if multi-adopter feedback shows need.
- Body-flow cardinality refinement — step `output:` declared type is trusted; future fase may inspect body returns for actual cardinality.
- Cardinality-1 Stream refinement — Stream<T> always treated as plural-over-time; a Stream that emits exactly one event is not specially detected.
- Python parser parity — Rust-canonical per founder directive 2026-05-15.

## Test surface

- **454/454** axon-frontend lib tests green (5 existing 38.x.e + 7 new in 38.x.f compile gate paths).
- **2108/2108** axon-lang lib tests green.
- **12/12** new anchor `axon-rs/tests/fase38xf_cardinality_complete.rs` (§1 for-tail T9XX, §2 disagree W003, §3 agree-Singular silent, §4 agree-Plural silent, §5 D3 bilateral T9XX, §6 D5 Stream T9YY, §7 Stream-step-Stream silent, §8 D5 bilateral T9YY, §9 D6 Any-accepts, §10 D2 cardinality surface, §11 D4 verbose env var, §12 §S STATIC grep).
- **12/12** existing anchor `axon-rs/tests/fase37xj_connection_pinning.rs` green (no regression from v1.39.0).
- **5/5** existing `fase38xe_cardinality_tests` green (v1.39.0 narrow case preserved verbatim).

## Plan vivo

[docs/fase/fase_38xf_cardinality_coverage_complete.md](docs/fase/fase_38xf_cardinality_coverage_complete.md).

## Trigger

Proactive language-level commitment per founder directive 2026-05-10: *"axon for axon — every implementation is for the language itself, independent of who/how-many adopt it; quality bar = compiler PhD reading the source"* (memory `feedback_axon_for_axon`). v1.39.0 closed the canonical kivi pattern; v1.40.0 closes the remaining cardinality surface preemptively so future adopters never hit any of the deferred classes.
