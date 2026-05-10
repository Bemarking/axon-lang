---
title: "Plan vivo: Fase 28 — Adopter Diagnostic Robustness"
status: IN PROGRESS 2026-05-10 — 28.a + 28.b + 28.c + 28.d + 28.e + 28.f + 28.g + 28.h SHIPPED (D1–D12 ratificadas en bloque por founder "todas las Recommendation: notes ratified verbatim, full 100% robusto"); 28.i–28.k execution starting; target axon-lang v1.20.0
owner: AXON Compiler Team
created: 2026-05-10
target: axon-lang v1.20.0 (minor release, cross-stack — Python + Rust)
depends_on: v1.19.4 SHIPPED (cumulative parser-diagnostic patch series 1.19.2/1.19.3/1.19.4)
charter_class: OSS — every adopter benefits; no enterprise-only surface
---

## ▶ Status snapshot (2026-05-10 — IN PROGRESS)

D1–D12 ratificadas en bloque por founder ("todas las Recommendation:
notes ratified verbatim, full 100% robusto") — 28.a SHIPPED. 28.b–28.k
executing sub-fase a sub-fase con incremental sign-off por sub-fase.

Trigger event: an enterprise adopter team (Kivi) hit FOUR distinct parser
issues during their migration to axon-lang within a single 4-hour window
(2026-05-09 → 2026-05-10). Each deploy attempt exposed one error; we
shipped three consecutive patches (v1.19.2 + v1.19.3 + v1.19.4) covering
lexical / grammatical / diagnostic layers. Their bootstrap log reported
**30 .axon files in the parse-error skip list** — they were discovering
issues serially, one per deploy cycle.

This is non-scalable for any adopter migrating a substantial codebase.
Fase 28 delivers the systemic fix: **the parser surfaces the WHOLE
landscape of errors in one pass**, every error carries source context,
typos get "did you mean X?" suggestions, and adopters running CI against
multi-file projects get aggregated diagnostics across the full corpus.

Founder principle: *"adopters never diagnose our bugs; we diagnose theirs"*.
Every parser error message must be self-explanatory + every error pass
must surface every problem.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 28.a Engineering spec + D-letter ratification | ✅ SHIPPED 2026-05-10 | doc-only | — | This doc (commit `d93e99a` initial draft + this commit ratification) + memoria `project_fase_28_plan.md` + D1–D12 ratificadas verbatim per founder bloque approval |
| 28.b Parser error recovery (Python) | ✅ SHIPPED 2026-05-10 | ~280 (parser) + ~500 (tests) | Python | `axon/compiler/parser.py` + new `parse_with_recovery()` API; panic-mode recovery; sync rule = top-level keyword at brace-depth ≤ 0 OR EOF; `_TOP_LEVEL_DECLARATION_KEYWORDS` frozenset (~50 token types); `ParseResult { program, errors, has_errors, is_clean }` return type; existing `parse()` API preserved verbatim (D9). Tests: 126/126 pass — 9 classes covering backwards compat (3) + single-error recovery (4) + multi-error (3) + sync points (4) + ParseResult API (4) + edge cases (6) + 1000-iter deterministic-seeded fuzz (100 buckets × 10 mutations) + ghost-error guard (1) + integration with v1.19.4 colon diagnostic (1). Full Python regression sweep: **5175 passed, 4 skipped, 0 failures** |
| 28.c Parser error recovery (Rust frontend) | ✅ SHIPPED 2026-05-10 | ~270 (parser) + ~540 (tests) | Rust | `axon-frontend/src/parser.rs` mirror implementation: `ParseResult { program, errors }` with `has_errors`/`is_clean`; `parse_with_recovery()` method; `is_top_level_decl_kw_for_recovery` const fn (47 token variants — superset of `is_declaration_keyword` to include Know/Believe/Speculate/Doubt/Ots/Ingest/etc that begin top-level decls but aren't counted by the structural counter); `advance_to_sync_point` walker with depth ≤ 0 sync rule (matches Python). 27 tests in `mod fase28_recovery_tests` covering backwards_compat (3) + single_error (4) + multi_error (3) + sync_points (4) + ParseResult API (4) + edge_cases (5) + 1000-iter deterministic-seeded xorshift fuzz + integration_with_colon_diagnostic + recovery preserves declaration ordering. Full axon-frontend regression: **179/179 pass**. axon-rs (consumer crate) builds clean. Recovery additions clippy-clean (pre-existing tech debt in channel_analysis.rs unrelated). Cross-stack drift gate (Python ↔ Rust byte-identical error lists on shared corpora) is wired in 28.i — the test contract here ensures input-shape parity: same test class names + invariants as Python pack |
| 28.d Source-context diagnostic block | ✅ SHIPPED 2026-05-10 | ~280 (Py errors + parser) + ~370 (Rust parser) + ~280 + ~310 (tests) | Python + Rust | New `SourceSnippet` type on both stacks (rustc-style line+caret+2-before+2-after, gutter right-align, EOL caret clamp, Python `splitlines()` trailing-newline parity); `AxonError.source_snippet` optional field + `attach_source()` fluent method; `Parser(tokens, source=..., filename=...)` Python kwarg + `Parser::with_source()` Rust fluent builder; both `parse()` and `parse_with_recovery()` attach snippet when source is provided; struct-literal back-compat via `#[derive(Default)]` + `..Default::default()`. Python: 22/22 source-context tests pass + 5175 full sweep clean. Rust: 22/22 mirror tests + 201/201 axon-frontend regression + axon-rs consumer crate builds (touched 2 destructure sites in compiler.rs/runner.rs to add `..` for the new field). Cross-stack render parity: 3 golden-string tests duplicated verbatim across `tests/test_fase28_source_context.py::TestRustParityShape` + Rust `mod fase28_source_context_tests::golden_*` — byte-identical output asserted on both stacks. D4 ratified: 2 lines before + 2 lines after; D7 byte-identical render contract enforced by golden tests |
| 28.e Smart-suggest for unknown tokens | ✅ SHIPPED 2026-05-10 | ~190 (Py module) + ~270 (Rust module) + ~310 (Py tests) + ~250 (Rust tests) | Python + Rust (full robusto, cross-stack despite plan saying Python-only — drift-gate parity preferred) | New `axon/compiler/_smart_suggest.py` + `axon-frontend/src/smart_suggest.rs` modules with byte-identical Levenshtein DP shape + `suggest()` + `format_suggestion_hint()` + `suggest_for()` convenience. D3 ratified: max distance ≤ 2, max 3 candidates (revised down from plan's "max 5"). D11 always on. Wired into both error sites: top-level `parse_declaration` _ arm + flow-body `parse_flow_step` _ arm; uses canonical keyword-name tuples (`_TOP_LEVEL_KEYWORD_NAMES` 49 keywords + `_FLOW_BODY_KEYWORD_NAMES` 41 keywords) duplicated across stacks. Hint formatter: `Did you mean \`flow\`?` (1) / `Did you mean \`flow\` or \`flop\`?` (2) / Oxford-or for 3+. Recovery mode propagates hint per error. Python: 38/38 tests pass. Rust: 36/36 tests pass + axon-frontend full regression 239/239. axon-rs builds clean. Cross-stack golden parity locked by `TestRustParityShape` (Py) + `golden_*` (Rust) — same 8 levenshtein pairs + 3 suggest cases + 1 hint format duplicated verbatim |
| 28.f Multi-file aggregator | ✅ SHIPPED 2026-05-10 | ~390 (`_multi_file.py`) + ~170 (`parse_cmd.py`) + ~360 (tests) | Python | New `axon parse <pattern> [--max-errors N] [--ignore PAT] [--jobs N] [--no-color]` CLI subcommand. Helper module `axon/cli/_multi_file.py` (testable without argparse): `collect_paths()` walks files / dirs (recursive) / globs respecting built-in dir ignores (.git/.hg/.svn/.venv/venv/env/node_modules/__pycache__/target/dist/build) + per-directory `.axonignore` cascading + caller-supplied `--ignore PAT` patterns; `parse_files_concurrent()` thread-pool dispatch with `parse_with_recovery()` per file (source attached for 28.d snippets); `aggregate()` rolls up per-file `FileResult`s with D6 `--max-errors N` cap (default unlimited; clean + I/O-error files keep showing past the cap, only erroring files truncated). Exit codes: 0 clean, 1 parse-errors, 2 I/O errors, 3 both. Each rendered error includes 28.d source-context + 28.e smart-suggest hint flowing through transitively. **34/34 tests pass** (TestCollectPaths 13, TestParseFilesConcurrent 5, TestAggregate 6, TestRun 5, TestCmdParse 5) covering single file / dir recursion / globs / explicit-file extension override / built-in ignores / .axonignore root + subdir / explicit ignore / dedup / deterministic alphabetical order / empty / no-match / I/O error packaging / order preservation / D6 max-errors-cap edge cases (zero, boundary, clean+IO not dropped) / smart-suggest+source-context propagation / CLI exit codes |
| 28.g Structured diagnostic output (JSON) | ✅ SHIPPED 2026-05-10 | ~280 (`_json_output.py`) + ~25 (CLI wiring) + ~330 (tests) | Python | New `axon/cli/_json_output.py`: `error_to_json`, `file_result_to_json`, `report_to_json`, `diagnostics_iter`, `to_lsp_diagnostic`. D5 ratified — rustc-compatible at field level: top-level `{severity, code, source, message, spans, children}` + per-span `{file_name, line_start, line_end, column_start, column_end, is_primary, label, source_text}` matches `rustc --error-format=json` exactly so adopter tooling that already maps rustc JSON → LSP works without code changes. Two CLI formats: `array` (default, single JSON array) + `ndjson` (one diagnostic per line, streaming-friendly). Wired into `axon parse` as `--json` + `--format={array,ndjson}`; JSON mode short-circuits human-friendly rendering and suppresses stderr warnings so tooling consumes clean JSON. `to_lsp_diagnostic` helper for adopter LSP wrappers (1-based → 0-based line/col conversion + severity-int mapping). I/O errors emit synthetic `AXON_IO_ERROR` diagnostics so the JSON stream has uniform shape regardless of failure mode. **31/31 tests pass**: TestErrorToJson (8), TestFileResultToJson (3), TestReportSerialize (8), TestLspMapping (4), TestCmdParseJson (4), TestRustcParity (4 golden field-shape pins) |
| 28.h `--strict` opt-in flag for fail-on-first | ✅ SHIPPED 2026-05-10 | ~115 (`run_strict` + `_parse_one_strict` in `_multi_file.py`) + ~30 (CLI wiring + env-var helper) + ~250 (tests) | Python | New `axon/cli/_multi_file.py::run_strict()` + `_parse_one_strict()` use legacy `Parser.parse()` fail-fast API; sequential walk halts at first failing file with `report.truncated` set + remaining files skipped (still counted in `files_seen` for honest summary). New `--strict` argparse flag + `AXON_PARSER_STRICT` env var (truthy: 1/true/yes/on/y/t case-insensitive, whitespace-stripped); OR semantics so CI pipelines flip via either source. Strict mode caps at exactly 1 error per failing file; smart-suggest hint (28.e) + source-context block (28.d) preserved. Strict-mode footer differentiated from D6 max-errors footer ("strict mode halted at first failing file; N remaining file(s) skipped"). Compatible with `--json` (emits 1-element JSON array). **34/34 tests pass**: TestRunStrictHelper (7), TestStrictEnvVar (16 incl. parametrized truthy/falsy), TestCmdParseStrict (6), TestStrictBackwardsCompat (2 — default behavior + max-errors interaction unchanged). D8 + D9 ratified |
| 28.i CI matrix + drift gate + fuzz pack | ⏳ pending | ~600 (YAML + tests) | YAML + Python | Extends `.github/workflows/ci.yml` with new "diagnostics" lane: deterministic-seeded fuzz pack (1000 iterations of malformed `.axon` inputs) verifies recovery never crashes the parser; cross-stack drift gate asserts Python + Rust produce identical error lists; structured-output schema validation against the published JSON schema |
| 28.j ADOPTER_DIAGNOSTICS.md guide | ⏳ pending | ~500 (Markdown) | Docs | Top-level adopter-facing guide explaining: error-recovery posture, structured output schema, smart-suggest behavior, `--strict` opt-in, common error patterns + fixes, IDE integration recipe (LSP-style); links from INTEGRATION_GUIDE.md |
| 28.k Coordinated cross-stack release v1.20.0 | ⏳ pending | release | — | bump-my-version 1.19.4 → 1.20.0 (minor — new `parse_with_recovery()` API + `--strict` flag are additive) + commit + tags `v1.20.0` + `rust-v1.20.0` + push origin + cargo publish axon-lang 1.20.0 + GitHub Release with comprehensive notes + axon-frontend bump |

**Tests target**: ~120 new tests covering:
  - Recovery (Python): malformed inputs produce N errors, parser doesn't crash on any pathological input (60-iter fuzz seeded), recovery sync points hit correctly (~30 tests)
  - Recovery (Rust): drift-gate parity with Python on same inputs (~20 tests)
  - Source-context: snippet rendering across multi-line files, edge cases (line 1, last line, EOF, unicode) (~15 tests)
  - Smart-suggest: typo detection for keywords, no-suggestion when too far, multi-candidate ranking (~15 tests)
  - Multi-file: glob patterns, .axonignore, concurrent parse correctness, deterministic ordering (~20 tests)
  - Structured JSON: schema validation, severity field, NDJSON vs array (~10 tests)
  - Strict opt-in: backwards-compat regression baseline (~10 tests)

**Total ship**: ~3500 LOC + ~120 tests + 1 markdown guide + CI workflow extension.

---

## 1. Investigation summary — why a diagnostic-robustness phase now

The v1.19.x patch trilogy surfaced a fundamental scaling issue with the
parser's error model. Each individual fix was correct + tightly scoped,
but the cumulative pattern revealed:

  1. **Adopters with substantial `.axon` codebases hit multiple errors**
     across their files. They cannot fix issues in parallel because the
     parser stops at the first error.
  2. **The "fail on first error" mode hides the systematic structure**
     of what's wrong — adopters can't see if 30 files have the SAME
     problem or 30 different problems until they fix one and try again.
  3. **CI integrations (Kivi's bootstrap deploy in particular) are
     forced to maintain a "skip list"** of broken files, which silently
     drops production code from validation.
  4. **Structured diagnostic output is a baseline expectation** for
     modern compiler integrations — IDE plugins, LSP servers, CI
     dashboards all want machine-parseable error streams.

What rustc, clang, and TypeScript got right + we should match:

  - **Multi-error reporting**: every compile pass yields all errors,
    not just the first.
  - **Source-context blocks**: every error shows a source snippet with
    the offending token highlighted.
  - **Did-you-mean suggestions**: when typos look like valid
    identifiers, suggest the closest match.
  - **Structured JSON**: every diagnostic has machine-parseable fields
    that LSP servers consume verbatim.

These are not bells-and-whistles — they are the load-bearing surface
for any compiler that wants adopter integration without friction.

---

## 2. TL;DR (resume in 30 seconds)

  - **What**: comprehensive overhaul of axon-lang's parser diagnostic
    surface. Multi-error reporting, source-context rendering,
    smart-suggest typos, multi-file aggregation, structured JSON
    output, backwards-compatible opt-in for old behavior.
  - **Why**: adopters with substantial codebases (Kivi) can't migrate
    efficiently when the parser fails on first error and forces them
    to discover issues serially. The systemic fix unblocks every
    future migration.
  - **Cross-stack**: Python (`axon/compiler/parser.py`) + Rust
    (`axon-frontend/src/parser.rs`) need parity. Drift gate verifies
    error lists are byte-identical across the two implementations.
  - **Backwards compat**: existing `parse()` API preserved verbatim;
    new `parse_with_recovery()` is additive; `--strict` flag opts back
    into old behavior for adopters who depend on it.
  - **Robustness target**: 1000-iter deterministic fuzz never crashes
    the parser; drift gate cross-stack 100% byte-identical;
    structured JSON validates against the published schema for every
    test input.
  - **Target version**: axon-lang v1.20.0 (minor release because the
    new APIs are additive). axon-frontend bumps to v0.8.0 (minor —
    same recovery surface).

---

## 3. Architecture — operational design

### 3.1 Recovery strategy: panic-mode with sync points

When the parser hits an error, it:

  1. Records the error in an internal `errors: list[AxonParseError]`.
  2. Skips tokens until it reaches a known sync point.
  3. Resumes parsing from there.
  4. After the full input is consumed, returns `ParseResult { program,
     errors }` — `program` may be partial (containing the
     successfully-parsed declarations), `errors` lists everything
     that went wrong.

**Sync points** (D2 — to be ratified):
  - Top-level keywords: `flow`, `intent`, `tool`, `persona`, `daemon`,
    `agent`, `dataspace`, `forge`, `psyche`, `axonendpoint`, `mandate`,
    `psyche`, `mcp`.
  - Closing braces: `}` at any nesting depth (most reliable sync).
  - End of file.

The granularity choice is intentional: blocks-and-declarations resync,
NOT every-token-fence (which would emit one error per token in a
catastrophic file). One file with 30 broken flows produces ~30
errors, not ~30,000.

### 3.2 Source-context rendering

Every `AxonParseError` carries an optional `source_text` reference
(set by the parser when constructed from a source string). The
formatter renders:

```
AxonParseError [line 3184, col 20]: Did you forget `:` between `arg`
and `String`? Parameter and field declarations use `name: Type`
syntax (e.g. `arg: String`), not `name Type`.
   --> kivi_brain.axon:3184:20
    |
3182|         input: Document,
3183|         output: Stream<String>,
3184|         arg String
    |             ^^^^^^ expected `:` before type
3185|         next: Int,
    |
```

The format mirrors rustc's diagnostic block. JSON mode emits the
same fields without the rendering.

### 3.3 Smart-suggest for unknown tokens

When the parser encounters an unknown IDENTIFIER in a context where
specific keywords are valid (e.g. inside a step body), it computes
Levenshtein distance against the valid set + suggests the closest
match if distance ≤ 2.

```
AxonParseError [line 100, col 5]: Unexpected token in step body
(expected: given, ask, ..., output, ..., found: 'outpu')
help: did you mean `output`?
```

### 3.4 Multi-file aggregator

CLI subcommand `axon parse <pattern> [--strict] [--json]`:

```bash
axon parse 'src/**/*.axon'                # all errors across all files
axon parse 'src/**/*.axon' --json         # structured output
axon parse 'src/**/*.axon' --format=ndjson # one JSON-line per error
axon parse 'src/**/*.axon' --strict       # fail on first error
```

Concurrent parse via thread pool (Python's GIL is fine here because
the parser is CPU-bound but each file is independent — the threads
serve to overlap I/O + CPU, not to parallelize CPU work).

### 3.5 Backwards compatibility

  - `Parser(tokens).parse() -> ProgramNode` API unchanged. Raises on
    first error as before.
  - New `Parser(tokens).parse_with_recovery() -> ParseResult` API
    additive.
  - `axon parse <pattern>` CLI defaults to recovery; `--strict`
    opts back into old behavior for adopters whose CI pipelines
    depend on the fail-on-first error code.
  - `AXON_PARSER_STRICT=1` env var equivalent to `--strict` for
    adopters configuring via env.
  - Existing tests + adopter integrations pass unchanged (verified
    in 28.h regression baseline).

### 3.6 Cross-stack drift gate

Per Fase 18 / 19 / 23 / 25.i pattern: the Rust frontend MUST produce
byte-identical error lists for any input that exercises the recovery
path. Drift gate runs deterministic-seeded fuzz (1000 iterations)
plus a curated set of adversarial inputs (every test case in
`tests/`) and asserts both implementations produce the same error
sequence in the same order with the same spans.

---

## 4. D-letters — RATIFIED 2026-05-10 (bloque approval)

All twelve D-letters ratified verbatim with the recommendations as
originally written. Founder direction: *"todas las Recommendation:
notes ratified verbatim, full 100% robusto"*. Status flip from
DRAFTED → IN PROGRESS; 28.a SHIPPED; 28.b execution starts on
explicit founder go-ahead per sub-fase.

**D1 — Default mode**: recovery (multi-error) vs strict (fail-on-first)?

  ✅ RATIFIED: **recovery default**. Adopters benefit from seeing
  all errors at once; the v1.19.4 series demonstrated the cost of
  serial discovery. Backwards compat preserved via `--strict` opt-in
  + existing `parse()` API. Minor-release-safe because the new behavior
  is observed via a NEW API (`parse_with_recovery`) + a NEW CLI subcommand
  (`axon parse`); existing programmatic users see no change.

**D2 — Recovery sync points**: which tokens count as safe restart
boundaries?

  Recommendation: top-level keywords (`flow`, `intent`, `tool`,
  `persona`, `daemon`, `agent`, `dataspace`, `forge`, `psyche`,
  `axonendpoint`, `mandate`, `mcp`) + closing brace `}` at any depth
  + EOF. NOT every token fence (catastrophic-error blast).

**D3 — Smart-suggest threshold**: Levenshtein distance ≤ 2? max 5
candidates?

  ✅ RATIFIED: **distance ≤ 2 + max 3 candidates** (rustc uses 2;
  TypeScript uses 3). More candidates create noise; fewer miss
  obvious typos. Suggestions are case-insensitive (catch
  `Output` vs `output`).

**D4 — Source-context block**: how many lines before/after to show?

  ✅ RATIFIED: **2 before + 2 after** (rustc uses 1+1 or 2+2
  depending on context; clang uses 1+1). For long lines (>120
  chars), truncate with `...` ellipsis around the offending column.

**D5 — Structured JSON shape**: rustc-compatible? clippy-compatible?
custom?

  ✅ RATIFIED: **rustc-compatible at the field level** (the
  `severity / message / spans / labels` tree). Adopters with rustc-
  json tooling can reuse parsers. Custom extensions go under a
  reserved `axon` namespace key.

**D6 — Multi-file aggregator**: per-file or global error budget?

  ✅ RATIFIED: **no error budget by default**. Some adopters
  may want a `--max-errors=N` flag (matches gcc / clang
  `-fmax-errors`); shipped as a documented flag for CI tooling
  but no default cap.

**D7 — Cross-stack drift gate posture**: byte-identical error lists?

  ✅ RATIFIED: **yes, byte-identical**. Same input, same error
  list (order + content + spans). Any divergence = build-time CI
  failure. Same posture as Fase 18 cross-stack drift gate.

**D8 — Strict-mode opt-in surface**: CLI flag, env var, config
file, all?

  ✅ RATIFIED: **CLI flag `--strict` AND env var
  `AXON_PARSER_STRICT=1`**. CLI for ad-hoc use; env var for CI
  pipeline configuration. No config file (one source of truth per
  invocation).

**D9 — Backwards compat for `parse()` API**: preserve verbatim?

  ✅ RATIFIED: **yes, preserved verbatim**. `parse()` continues
  to raise on first error. The new behavior is opt-in via
  `parse_with_recovery()`. Internal callers can migrate at their own
  pace; external integrations don't break.

**D10 — Documentation strategy**: standalone guide or integration?

  ✅ RATIFIED: **standalone `docs/ADOPTER_DIAGNOSTICS.md` AND
  cross-link from `docs/INTEGRATION_GUIDE.md`**. The diagnostic
  surface is substantial enough to deserve its own page; the
  integration guide gets a "Diagnostics" section pointing at it.

**D11 — Smart-suggest activation**: always on or opt-in?

  ✅ RATIFIED: **always on**. Suggestions are pure additions to
  the error message; cannot break existing tools. Cost is one
  Levenshtein scan per error which is O(N×K) where N = number of
  candidates (typically 10-20) and K = average string length
  (5-15) — negligible.

**D12 — Test budget for fuzz**: 1000 iterations per CI run?

  ✅ RATIFIED: **1000 iterations**, deterministic-seeded so
  failures reproduce. CI wall time impact is minimal (each iteration
  is ms-scale). Same posture as Fase 25.i fuzz drift gate.

---

## 5. Sub-phase calendar

```
Día 1: 28.a + 28.b  (spec + Python recovery — load-bearing)
Día 2: 28.c          (Rust recovery + drift-gate parity)
Día 3: 28.d + 28.e   (source context + smart-suggest)
Día 4: 28.f + 28.g + 28.h  (multi-file + JSON + strict opt-in)
Día 5: 28.i + 28.j   (CI matrix + adopter docs)
Día 6: 28.k          (release v1.20.0)
```

Estimated 5-6 días focused. Larger than v1.19.x patches because the
phase delivers a complete diagnostic surface, not a single bug fix.

---

## 6. Out of scope (sesión 2+)

  - **LSP server implementation**: structured JSON output is the
    foundation; an actual LSP server (axon-lsp or equivalent) is its
    own phase.
  - **Auto-fix suggestions**: rustc has `cargo fix`. Implementing
    it for axon-lang (rewriting source on-disk based on diagnostics)
    is a separate phase.
  - **IR-level diagnostics**: Fase 28 covers parse-time only.
    Type-checker + IR-generator already produce diagnostics; uniting
    them under the same recovery + structured-output surface is a
    Fase 29 candidate.
  - **Performance optimization**: the recovery + suggest paths add
    overhead. Optimizing them (caching candidate sets, parallel
    Levenshtein, etc.) is a follow-up perf fase.

---

## 7. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Recovery diverges between Python + Rust → drift-gate failures | Medium | Cross-stack inconsistency | 28.i drift gate runs on every PR; fuzz pack catches divergence before merge |
| Recovery generates "ghost errors" on cascade failures (one real error → many spurious) | High (canonical recovery problem) | Adopter confusion | Aggressive sync-point selection (D2): only resync on top-level keywords + `}`; one error per logically broken block, not per token |
| Source-context rendering breaks on Unicode-heavy lines (multi-byte chars + caret alignment) | Medium | Garbled output | Test pack includes Unicode + RTL + emoji edge cases; render uses character-not-byte indexing |
| Smart-suggest produces false positives ("did you mean X?" when X is unrelated) | Low | Noise in error output | Threshold ≤ 2 + max 3 candidates; suggestions are HINTS, not assertions; adopters can ignore |
| Multi-file aggregator non-deterministic (concurrent parse → varying error order) | Medium | CI flakiness | Output sorted by file path + line + column; thread pool collects then sorts before emit |
| `--strict` adopters confused when recovery is on by default | Low | Migration friction | ADOPTER_DIAGNOSTICS.md explicitly documents the change; release notes call out the default flip |
| Structured JSON schema breaking changes between minor versions | Low | IDE plugin breakage | Schema versioned + backwards-compat tested; new fields are additive only |

---

## 8. Cómo fue motivada

Trigger directo: durante la migración del enterprise adopter team Kivi
a axon-lang el 2026-05-09, encontraron CUATRO errores parser distintos
en su `.axon` codebase dentro de una ventana de 4 horas. Cada deploy
exponía uno; nosotros shipeamos tres patches consecutivos
(v1.19.2 + v1.19.3 + v1.19.4) cubriendo capas lexical / grammatical
/ diagnostic.

Su bootstrap log decía "30 archivos skipados (parse-error skip
list)" — Kivi estaba descubriendo problemas serialmente, uno por
deploy cycle. Su workflow de migración era:

  1. Deploy → primer error
  2. Identificar archivo + línea + commit fix
  3. Deploy → segundo error en otro archivo
  4. Repeat hasta cubrir los 30

Esto no escala. El siguiente adopter (sea Kivi-2 o cualquier otro
con codebase substantial) hit el mismo wall. Fase 28 entrega el fix
sistémico: parser ve TODA la landscape en un pase, output es
machine-readable, typos sugieren correcciones, errores carry
spatial context.

Founder principle (re-confirmed durante la sesión v1.19.x):
"adopters never diagnose our bugs; we diagnose theirs". Fase 28
materialise ese principle a nivel sistémico — no más loops de "deploy
→ fail → fix → deploy → fail" donde el adopter es el bottleneck.

---

## 9. Next operational step

D1–D12 ratificadas en bloque por founder 2026-05-10
("todas las Recommendation: notes ratified verbatim, full 100%
robusto"). 28.a SHIPPED. 28.b execution awaits explicit founder
"procede con 28.b" per the incremental sign-off cadence.

Estimated calendar: 5-6 días focused desde 28.b hasta v1.20.0
publicado.

Esta es una **minor release** porque las nuevas APIs son aditivas —
existing programmatic users + CI integrations continúan funcionando
sin cambios. Solo el `axon parse` CLI subcommand + el comportamiento
default de la herramienta cambian, y ambos están protegidos por
backwards-compat opt-in (`--strict` flag + env var).
