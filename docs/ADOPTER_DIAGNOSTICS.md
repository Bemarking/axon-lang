# AXON Adopter Diagnostics Guide

> **Audience:** engineers integrating axon-lang into a codebase, a CI
> pipeline, an IDE / LSP server, or a multi-file `.axon` corpus.
>
> **Scope:** every diagnostic surface introduced by **Fase 28 / axon-lang
> v1.20.0** — parser error recovery, source-context blocks, smart-suggest
> hints, multi-file aggregation, structured JSON output, strict opt-in.
>
> **Founder principle:** *adopters never diagnose our bugs; we diagnose
> theirs.* Every parser error message should self-explain the fix. If it
> doesn't, that's a bug in axon-lang — open an issue.

---

## Table of Contents

1. [What changed in v1.20.0](#what-changed-in-v1200)
2. [The new `axon parse` subcommand](#the-new-axon-parse-subcommand)
3. [Reading source-context error blocks](#reading-source-context-error-blocks)
4. [Smart-suggest "Did you mean X?"](#smart-suggest-did-you-mean-x)
5. [Multi-file aggregation + `.axonignore`](#multi-file-aggregation--axonignore)
6. [Structured JSON output](#structured-json-output)
7. [LSP integration recipe](#lsp-integration-recipe)
8. [Strict opt-in (fail-on-first)](#strict-opt-in-fail-on-first)
9. [Common error patterns + fixes](#common-error-patterns--fixes)
10. [CI integration cookbook](#ci-integration-cookbook)
11. [Programmatic API: `parse_with_recovery()`](#programmatic-api-parse_with_recovery)
12. [Migration path for existing `parse()` callers](#migration-path-for-existing-parse-callers)
13. [Cross-stack contract: Python ↔ Rust](#cross-stack-contract-python--rust)

---

## What changed in v1.20.0

Before v1.20.0, the parser stopped at the **first** error in the **first**
file. An adopter with 30 broken `.axon` files had to deploy 30 times to
surface every issue.

v1.20.0 closes that loop:

| Surface | Before (v1.19.x) | After (v1.20.0) |
|---|---|---|
| Single-file errors | 1 error per parse → exception | All errors collected; recovery resyncs at top-level keywords |
| Error message | `[line 3, col 5]: Unexpected token` | rustc-style block: line numbers + caret + 2 lines before/after |
| Typo'd keywords | Generic "expected token" | "Did you mean \`flow\`?" suggestion (Levenshtein ≤ 2) |
| Multi-file projects | Run `axon check` per file in a loop | `axon parse src/` walks the whole corpus |
| IDE / LSP integration | Parse text output | `axon parse --json` emits rustc-compatible diagnostics |
| Fail-on-first behavior | Default | Opt-in via `--strict` or `AXON_PARSER_STRICT=1` |

**Backwards compatibility:** the existing `parse()` Python API and
`Parser::parse()` Rust API still raise on the first error verbatim. New
behavior is opt-in via the new `parse_with_recovery()` API or the new
`axon parse` CLI subcommand.

---

## The new `axon parse` subcommand

```bash
axon parse <path-or-pattern> [<path-or-pattern> ...]
           [--strict] [--max-errors N] [--ignore PATTERN]
           [--jobs N] [--json] [--format={array,ndjson}]
           [--no-color]
```

### Quick recipes

```bash
# Parse one file, surface every error in one pass.
axon parse src/contract_analyzer.axon

# Walk a directory recursively (built-in dir ignores apply: .git,
# node_modules, target, etc.).
axon parse src/

# Glob a pattern.
axon parse "src/**/*.axon"

# Multiple paths.
axon parse intents/ flows/ shared/library.axon

# Cap the diagnostic stream at the first 50 errors.
axon parse src/ --max-errors 50

# Ignore an extra pattern on top of .axonignore + built-ins.
axon parse src/ --ignore 'experimental/*'

# Tighter CI loop: halt at the first failing file.
axon parse src/ --strict
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Every file parsed cleanly |
| `1` | One or more files had parse errors |
| `2` | One or more files couldn't be read (I/O error) |
| `3` | Both classes of error present (1 OR 2 by bitwise OR) |

CI integrations that want to distinguish "broken syntax" from
"missing/unreadable file" can branch on the bits.

---

## Reading source-context error blocks

Every parse error now carries an optional `SourceSnippet` rendered
below the message:

```
AxonParseError [line 2, col 5]: Unexpected token in flow body. Did you mean `step`? (expected step, probe, ..., found stepp)
  --> src/contract_analyzer.axon:2:5
  |
1 | flow F() {
2 |     stepp S {}
  |     ^
3 | }
```

### Anatomy of the block

| Element | Meaning |
|---|---|
| `--> file:line:col` | File path + 1-based line + 1-based column |
| `  | ` (empty gutter) | Vertical bar separator |
| `<n> | <text>` | Source line N from the file (gutter right-aligned) |
| `  | ^` | Caret pointing at the error column |

**Context window:** 2 lines before + 2 lines after the error line (D4
ratified). On line 1 the "before" range is clamped to 0; near EOF the
"after" range is clamped likewise.

**Rustc-compatible:** the field shape (line numbers + caret + adjacent
context) mirrors `rustc --error-format=human` — adopters fluent in Rust
diagnostics will recognize it instantly.

---

## Smart-suggest "Did you mean X?"

The parser appends a "Did you mean" hint when the unknown token at an
error site is within Levenshtein distance ≤ 2 of an in-scope keyword.
**Always on** (D11 ratified) — there's no flag to enable / disable. It
fires on two adopter-hot surfaces:

```axon
// Top-level: typo'd declaration keyword
flwo F() {}
//   ^^^^ "Did you mean `flow`?"

// Flow body: typo'd step keyword
flow F() {
    stepp S {}
//  ^^^^^ "Did you mean `step`?"
}
```

| Match count | Hint format |
|---|---|
| 1 | `Did you mean \`flow\`?` |
| 2 | `Did you mean \`flow\` or \`flop\`?` |
| 3+ | `Did you mean \`flow\`, \`flop\`, or \`flux\`?` (Oxford "or") |

**Far-no-suggest:** if the unknown token is more than 2 edits from any
keyword, no hint is appended. `qwerty F()` is too far from `flow` (5
edits) so adopters don't get a misleading "did you mean flow?" — the
silence is intentional.

---

## Multi-file aggregation + `.axonignore`

`axon parse` walks paths / directories / globs and parses every `.axon`
file in parallel using a thread pool. Output is one block per file, in
deterministic alphabetical order, followed by a corpus-wide summary
footer.

### Built-in directory ignores

These are always skipped during recursive walks:

```
.git  .hg  .svn
.venv  venv  env
node_modules  __pycache__
target  dist  build
```

### `.axonignore` files

Drop an `.axonignore` at the corpus root or inside any subdirectory.
Patterns are fnmatch-style, one per line. `#`-prefixed lines are
comments. Patterns cascade DOWN (apply to descendants of the directory
they live in), not up.

```
# .axonignore at project root
vendor/*
experimental/draft_*.axon
**/*.generated.axon
```

### `--ignore PATTERN` flag

Add an extra ignore on the command line, repeatable:

```bash
axon parse src/ --ignore 'experimental/*' --ignore 'work_in_progress.axon'
```

### Direct file paths bypass extension filtering

If you explicitly name a file the extension filter doesn't apply:

```bash
# Parse weird.txt even though .txt isn't a default-walked extension.
axon parse weird.txt
```

### The corpus summary footer

```
✓ alpha.axon  — clean
✗ broken.axon  — 2 error(s)
  AxonParseError [line 1, col 1]: Unexpected token at top level. Did you mean `flow`? ...
    --> broken.axon:1:1
    |
  1 | flwo F() {}
    | ^
  ...

✗ 3 clean, 1 with errors (2 total error(s))
```

---

## Structured JSON output

`axon parse --json` emits machine-readable diagnostics with a
**rustc-compatible field shape** (D5 ratified). Adopter tooling that
already consumes `rustc --error-format=json` works against axon-lang
without code changes.

### Per-diagnostic schema

```json
{
  "severity": "error",
  "code": "AXON_PARSE_ERROR",
  "source": "axon-lang",
  "message": "Unexpected token at top level. Did you mean `flow`?",
  "spans": [
    {
      "file_name": "src/broken.axon",
      "line_start": 1,
      "line_end": 1,
      "column_start": 1,
      "column_end": 1,
      "is_primary": true,
      "label": null,
      "source_text": ["flwo F() {}"]
    }
  ],
  "children": []
}
```

### Two formats

| Format | When to use |
|---|---|
| `--format=array` (default) | Single JSON array of all diagnostics. Easy to pipe through `jq`, easy to parse in one read. |
| `--format=ndjson` | One diagnostic per line, no enclosing array. Streaming-friendly for IDE / LSP servers reading the pipe incrementally. |

### Stable contract

The top-level keys (`severity`, `code`, `source`, `message`, `spans`,
`children`) and per-span keys (`file_name`, `line_start`, `line_end`,
`column_start`, `column_end`, `is_primary`, `label`, `source_text`) are
**locked** — adding new keys is allowed (rustc adds them too over time);
**renaming** an existing key is a breaking change.

### I/O errors

When `axon parse` can't read a file, it emits a synthetic diagnostic
with `code: "AXON_IO_ERROR"`. The shape is uniform — adopter tooling
processes a single stream regardless of failure mode.

---

## LSP integration recipe

The structured JSON shape maps cleanly to LSP `Diagnostic`. The Python
package ships a `to_lsp_diagnostic()` helper for the conversion:

```python
from axon.cli._json_output import error_to_json, to_lsp_diagnostic
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser

source = open("flow.axon").read()
tokens = Lexer(source).tokenize()
result = Parser(tokens, source=source, filename="flow.axon").parse_with_recovery()

# Per-error LSP frame.
for err in result.errors:
    diag = error_to_json(err, file_name="flow.axon")
    lsp_diag = to_lsp_diagnostic(diag)
    # lsp_diag is a {range, severity, code, source, message} dict
    # ready for textDocument/publishDiagnostics.
```

LSP severity mapping:

| AXON severity | LSP severity int |
|---|---|
| `error` | `1` |
| `warning` | `2` |
| `note` | `3` |
| `help` | `4` |

Line/column conversion: AXON emits 1-based line + 1-based column;
`to_lsp_diagnostic` subtracts 1 for both (LSP uses 0-based) and clamps
to `[0, ∞)` for safety.

---

## Strict opt-in (fail-on-first)

CI loops that want a tight halt-on-failure loop opt into legacy
fail-on-first behavior via `--strict` OR `AXON_PARSER_STRICT=1`. **Either
source is enough** (OR semantics).

```bash
# CLI flag.
axon parse src/ --strict

# Env var (useful when you can't edit the invocation line).
AXON_PARSER_STRICT=1 axon parse src/

# Both work; flag wins if env is unset.
```

### Truthy env values

The env var is parsed case-insensitively. These are truthy:

```
1  true  yes  on  y  t  (any casing, whitespace stripped)
```

Anything else — including unset, empty, `0`, `no`, `off`, `false`,
`bogus` — is falsy.

### What strict mode does

* Halts at the first failing file in alphabetical order.
* Caps at exactly **1 error per failing file** (uses the legacy
  fail-fast `parse()` API).
* Files alphabetically after the failing one are NOT parsed.
* The summary footer mentions how many remaining files were skipped.
* Compatible with `--json`: emits a 1-element JSON array (or single
  ndjson line) before exiting.

### Why use it

- Tight CI loops where the first failure should block the build with
  zero ambiguity about which file to fix.
- Reproducing v1.19.x behavior exactly during a phased migration.
- Shorter logs in noisy CI dashboards (one diagnostic instead of
  thousands).

---

## Common error patterns + fixes

The v1.19.x adopter-migration trilogy surfaced three recurring patterns.
v1.20.0 keeps the targeted hints from those patches AND adds the
generic source-context block on top.

### Pattern 1: Reserved keyword used as effect name

```axon
flow F {
    step S {
        output: String
        perform stream(drop_oldest)   // ← `stream` is a reserved keyword
    }
}
```

**Fix (recommended):** use the streaming output type + effects clause:

```axon
flow F {
    step S {
        output: Stream<String>
        effects: [stream:drop_oldest]
    }
}
```

**Or:** use the algebraic-effect form with capitalized effect name:

```axon
perform Stream.Yield(some_value)
```

Reserved keywords that adopters commonly hit: `stream`, `hibernate`,
`drill`, `trail`, `par`, `shield`, `listen`, `network`. The parser
emits a per-keyword targeted diagnostic on each.

### Pattern 2: Generic types in `output:` declarations

`output: Stream<String>` was rejected pre-v1.19.3 because seven
productions only consumed a single `IDENTIFIER` for the type. v1.19.3
fixed all seven; v1.20.0 inherits the fix. If you see
`Unexpected token in step body (... found <)` against an old
axon-lang, upgrade to ≥ v1.19.3.

### Pattern 3: Missing `:` in name-type pairs

```axon
intent I {
    given Patient        // ← missing `:`
    ask: "Diagnose"
    output: Diagnosis
}
```

**Fix:** every field requires the `:` separator:

```axon
intent I {
    given: Patient
    ask: "Diagnose"
    output: Diagnosis
}
```

The v1.19.4 diagnostic spells the exact rewrite for the failing pair
(e.g. `arg: String`) so adopters paste the fix directly.

### Pattern 4 (NEW in v1.20.0): Typo'd keyword

```axon
flwo F() {}   // → "Did you mean `flow`?"
```

Smart-suggest catches Levenshtein-≤-2 typos automatically — adopters
see the fix in the error message, no manual diagnosis needed.

The same smart-suggest engine fires on Fase 30 closed-enum violations:

```axon
axonendpoint Live {
    transport: streaming   // → "Did you mean `sse`? Valid: json, sse, ndjson."
}
```

### Pattern 5 (NEW in v1.21.0): `transport: sse` on a non-streaming flow

```axon
flow Compute() {
    step S { ask: "x" }   // no Stream<T> output, no stream effect
}

axonendpoint Live {
    transport: sse        // ← compile error
    execute:   Compute
}
```

The Fase 30.c type-checker enforces the **soundness invariant** that
`transport: sse|ndjson` requires the execute flow to produce a stream.
The error message offers four remediation options inline:

```
error: axonendpoint 'Live' declares `transport: sse` but flow 'Compute'
       does not produce a stream. Four ways to satisfy the contract:
         1. Add a step with `output: Stream<T>`.
         2. Use a tool with `effects: <stream:<policy>>`.
         3. Add `perform Stream.Yield(...)` in a step body.
         4. Drop `transport: sse` and emit a single JSON value.
```

See [ADOPTER_STREAMING.md](ADOPTER_STREAMING.md) for the comprehensive
streaming-surface guide, including the formal predicate, all four
backpressure policies, the SSE wire-format spec, and load-balancer
deployment recipes.

### Pattern 6 (NEW in v1.22.0): `axon-W001` — implicit `transport: sse` warning

```axon
tool chat_token_stream {
    effects: <stream:drop_oldest>
}

flow Chat() -> String {
    step Generate {
        ask: "Hello, AI"
        apply: chat_token_stream
    }
}

axonendpoint ChatEndpoint {
    method:  POST
    path:    "/chat"
    execute: Chat                  // ← stream effects but no transport: declared
}
```

```
warning[axon-W001]: implicit `transport: sse` inferred from stream
effects on axonendpoint 'ChatEndpoint' (flow 'Chat' produces a stream
via step 'Generate' applies tool 'chat_token_stream' with effects
`<stream:drop_oldest>`). Declare `transport: sse` to silence this
warning and lock in SSE behavior, or `transport: json` to opt out and
keep the legacy JSON wire format. When `strict_type_driven_transport:
true`, this endpoint emits SSE on /v1/execute by default.
```

The Fase 31.c type-checker emits this **non-fatal warning** when:

1. An axonendpoint's `execute:` flow has stream effects (the
   produces_stream predicate fires per the Fase 30.c 3-disjunct
   disjunction), AND
2. The axonendpoint omits the `transport:` declaration.

The warning is rate-limited (one per axonendpoint per build pass)
and **suppressed** when:

- The axonendpoint declares any explicit `transport:` value
  (`sse`, `json`, or `ndjson`).
- The flow does not produce a stream.
- The `execute:` flow doesn't resolve (a separate error fires).

**Three remediation paths** — pick the one that matches your intent:

1. **Lock in SSE behavior (recommended for streaming chat / live
   transcription / token-by-token UIs):**
   ```axon
   transport: sse        // explicit; future-proof; survives v2.0.0 default flip
   ```

2. **Opt out of streaming wire (D3 sacred — JSON wrapper preserved):**
   ```axon
   transport: json       // explicit opt-out; warning silenced; runtime
                         // header X-Axon-Stream-Available still fires with
                         // reason=declared_json so clients see the trade-off
   ```

3. **Flip the server flag and let inference rule the wire (one config line):**
   ```bash
   axon serve --strict-type-driven-transport
   # OR
   export AXON_STRICT_TYPE_DRIVEN_TRANSPORT=1
   ```

`--strict` mode (Fase 28.h opt-in) promotes the warning to an
error — useful for CI pipelines that want the strongest signal at
build time.

See [MIGRATION_v1.22.md](MIGRATION_v1.22.md) for the four migration
scenarios (Kivi-shape quick-fix, default-everywhere, intentional
JSON wrapping, staged rollout) and [ADOPTER_STREAMING.md §Type-driven
default transport](ADOPTER_STREAMING.md#type-driven-default-transport-fase-31-v1220)
for the complete D1-D10 ratification trace.

---

## CI integration cookbook

### GitHub Actions

```yaml
name: AXON Parse Gate
on: [push, pull_request]
jobs:
  parse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install axon-lang>=1.20.0
      # Recovery mode: surface every error in one pass.
      - run: axon parse src/
      # Or strict mode: halt on first failure.
      # - run: axon parse src/ --strict
```

### GitLab CI

```yaml
parse_axon:
  image: python:3.13
  before_script:
    - pip install axon-lang>=1.20.0
  script:
    - axon parse src/
  variables:
    # Tighter halt-on-first via env var; flips behavior without
    # editing the invocation.
    AXON_PARSER_STRICT: "1"
```

### Capturing structured output for a dashboard

```bash
axon parse src/ --json --format=array > /tmp/axon-diagnostics.json

# Count errors with jq.
jq 'length' /tmp/axon-diagnostics.json

# Group by file.
jq 'group_by(.spans[0].file_name) | map({file: .[0].spans[0].file_name, errors: length})' \
   /tmp/axon-diagnostics.json
```

### Per-PR error-budget guard (D6)

```bash
# Cap the diagnostic stream at 100 errors. If the corpus has more,
# the build still fails (exit 1) but the log doesn't drown the
# reviewer in 5000 entries.
axon parse src/ --max-errors 100
```

---

## Programmatic API: `parse_with_recovery()`

Internal callers (an axon-lang plugin, a custom IDE bridge, a homegrown
CI script) can use the parser directly:

### Python

```python
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser

source = open("flow.axon").read()
tokens = Lexer(source).tokenize()

# Recovery mode: collect every error.
parser = Parser(tokens, source=source, filename="flow.axon")
result = parser.parse_with_recovery()

print(f"errors: {len(result.errors)}")
print(f"declarations salvaged: {len(result.program.declarations)}")
for err in result.errors:
    # Each err is an AxonParseError with .source_snippet attached.
    # str(err) renders the full rustc-style block.
    print(str(err))
    print("---")
```

### Rust

```rust
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;

let source = std::fs::read_to_string("flow.axon")?;
let tokens = Lexer::new(&source, "flow.axon").tokenize()?;
let result = Parser::new(tokens)
    .with_source(&source, "flow.axon")
    .parse_with_recovery();

println!("errors: {}", result.errors.len());
for err in &result.errors {
    // Display impl renders the source-context block.
    println!("{err}");
}
```

### Strict mode (programmatic)

```python
# Python: existing `parse()` API still works fail-fast.
try:
    program = parser.parse()
except AxonParseError as e:
    print(str(e))  # Includes source-context block when source= was passed.
```

```rust
// Rust: existing `parse()` API.
match Parser::new(tokens).with_source(&source, "f.axon").parse() {
    Ok(program) => { /* ... */ }
    Err(e) => println!("{e}"),
}
```

---

## Migration path for existing `parse()` callers

`parse()` is preserved verbatim per **D9 ratified** — no breaking
changes for v1.19.x callers. Adopters migrate at their own pace:

```python
# Before (v1.19.x):
try:
    program = Parser(tokens).parse()
except AxonParseError as e:
    print(str(e))
    sys.exit(1)

# After (v1.20.0+, gradual migration):
result = Parser(tokens, source=source, filename=path).parse_with_recovery()
if result.errors:
    for e in result.errors:
        print(str(e))
    sys.exit(1)
```

The v1.20.0 form gets:
- Every error in one pass (recovery)
- Source-context block on each error (28.d)
- Smart-suggest hint on typo'd keywords (28.e)

The v1.19.x form gets the same hints + source-context **as long as**
the parser was constructed with `source=` and `filename=` — backwards
compat in shape, additive in surface.

---

## Cross-stack contract: Python ↔ Rust

axon-lang ships **two frontends** at the same version:

- **Python:** `axon-lang` PyPI package — the canonical reference
  implementation; covers the broadest CLI / runtime surface.
- **Rust:** `axon-frontend` crates.io crate — pure-frontend (lexer,
  parser, AST, type-checker, IR generator); zero runtime deps; consumed
  by `axon-rs` (the Rust runtime) and `axon-lsp` (the LSP server).

**D7 ratified — byte-identical error lists across stacks.** Both
parsers must produce the same:

- Number of recovered errors on the same input.
- Same line/column for each error.
- Same "Did you mean" suggestions (same Levenshtein ranking).
- Same salvaged declaration count.

This contract is locked in CI by the
[Fase 28 drift gate workflow](../.github/workflows/fase_28_diagnostics.yml)
which runs both stacks against a shared corpus
(`tests/fixtures/fase28_drift_gate/corpus.json`) and asserts every
expected count matches on every entry. If the two stacks ever drift,
exactly one of the two test packs fails — drift caught at PR-review
time, not at adopter-bug-report time.

### Where to file bugs

| Symptom | Where |
|---|---|
| Parser error message is misleading or unhelpful | `axon-lang` issue tracker |
| Smart-suggest missed an obvious typo | `axon-lang` issue tracker |
| Python and Rust frontends disagree on the same input | `axon-lang` issue tracker — drift-gate violation, treated as a blocker |
| LSP server doesn't render the source-context block | `axon-lsp` issue tracker |
| Multi-file aggregator skipped a file you expected | `axon-lang` issue tracker — include `.axonignore` contents |

---

## See also

- [Fase 28 plan vivo](fase_28_adopter_diagnostic_robustness.md) —
  internal sub-fase tracker + D-letter ratifications.
- [v1.19.x patch series](../README.md#release-history) — reference for
  the trilogy that motivated Fase 28.
- [`axon-lsp`](https://github.com/Bemarking/axon-lsp) — the LSP server
  that consumes the structured JSON output for IDE integration.
- [Fase 21 integration surface](fase_21_integration_surface.md) —
  enterprise integration adjacencies (OIDC, OAuth, tenant context,
  capability registry).

---

*This document is part of the axon-lang public adopter surface. PRs
welcome — see `CONTRIBUTING.md`.*
