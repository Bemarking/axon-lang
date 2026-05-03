---
title: "Plan vivo: Fase 14 — Lossless lexing + trivia channel"
status: SHIPPED — sub-fases 14.a (v1.8.0) + 14.b/14.c/14.d/14.f (v1.9.0) completadas 2026-04-27
owner: AXON Language Team
created: 2026-05-02
updated: 2026-04-27
target: axon-lang v1.9.0 (PyPI + crates.io)
depends_on: Fase 13 (typed channels) DONE
---

# FASE 14 — LOSSLESS LEXING + TRIVIA CHANNEL

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** the lexer used to silently strip comments at lex-time (`// …` and `/* … */` were thrown away). The AST therefore had no trivia channel — every comment a user wrote was unrecoverable downstream. **14.a closes that**: the lexer now emits four discriminated comment kinds (`LineComment`, `BlockComment`, `DocLineComment`, `DocBlockComment`) and the parser materialises them into `Trivia` attached to AST nodes (Python: `leading_trivia` + `trailing_trivia` fields on `ASTNode`; Rust: `Program.declaration_trivia` parallel array).
- **Why:** unblocks LSP hover with docstrings, `axon fmt` round-trip preservation, rustdoc-style doc generators, refactoring that doesn't lose comments, and `// SECURITY:` / `// PII:` audit annotations.
- **Reported by:** an adopter reading `axon-frontend 0.2.0` source noted: *"el lexer omite los comentarios durante el tiempo de análisis léxico (lexer.rs:125,127) y el AST no tiene un canal de trivia"*. Confirmed empirically and closed in v1.8.0.
- **Doc-comment distinction (Rust convention):**
  - `//` regular line comment
  - `///` doc line comment (outer doc — documents the next item)
  - `/*` regular block comment
  - `/**` doc block comment (outer doc — documents the next item)
  - `////` (4+ slashes) and `/**/` (empty block) stay regular.

---

## 2. Design — Roslyn-style trivia, asymmetric materialisation

The lexer emits comments as first-class tokens. The parser separates the raw token stream into:
1. **Effective tokens** — what the grammar consumes. The parser cursor advances over these as before; existing parser code does not need to know about trivia.
2. **Parallel `leading_trivia` / `trailing_trivia` arrays** indexed by effective-token position.
   - Comments on a fresh line attach as **leading trivia** of the next effective token.
   - Comments on the same line as an effective token attach as **trailing trivia** of that token.
   - This is the convention used by C# Roslyn, Swift, and rust-analyzer.

### Materialisation differs by language

**Python** — every `ASTNode` gains `leading_trivia: tuple[Trivia, ...]` and `trailing_trivia: tuple[Trivia, ...]` fields with empty defaults. The parser auto-decorates every `_parse_*` method on `__init__` so trivia attach is transparent across the ~50 grammar rules:

```python
for name in dir(type(self)):
    if name.startswith("_parse_"):
        method = getattr(self, name)
        if callable(method):
            setattr(self, name, self._with_trivia(method))
```

**Rust** — Rust structs have no inheritance and 97 AST structs would each need two new fields plus updates to every test fixture. Instead, `Program` carries a `declaration_trivia: Vec<DeclarationTrivia>` parallel to `declarations`. A `DeclarationTrivia` holds `leading: Vec<Trivia>` and `trailing: Vec<Trivia>` indexed by declaration position. Same data reaches the consumer; AST shape and JSON parity are preserved.

If a future sub-phase needs per-node trivia inside the Rust AST (full mirror of the Python shape), this side-channel is the seed: every `DeclarationTrivia` already carries the data; spreading it into the structs is mechanical.

### Backward compatibility

- AST nodes default to empty trivia tuples — every existing fixture and test that constructs an `ASTNode` without trivia continues to work.
- `Lexer.tokenize(strip_comments=True)` (Python) / `Lexer::tokenize_with(true)` (Rust) reproduces the pre-14.a behaviour for downstream tooling that treats comments as pure whitespace (cost estimators, IR golden-file generators).
- IR JSON byte-identical Python ↔ Rust **stays intact** — trivia is an AST-only concern; it never reaches the IR generator.

---

## 3. Use cases unlocked

| Use case | How trivia delivers it |
|---|---|
| **LSP hover with docstrings** | Look up the AST node at the cursor; render `node.leading_trivia[*].stripped_text()` for trivia where `is_doc=True`. |
| **`axon fmt` round-trip preservation** | When re-emitting code, walk the AST top-down emitting `node.leading_trivia` before each node and `node.trailing_trivia` after — preserves comments verbatim. |
| **Doc generator (rustdoc / godoc style)** | Filter `leading_trivia` for `is_doc=True` on every top-level definition to produce a documentation index. |
| **Refactoring (rename, move)** | Trivia travels with the AST node it documents, so refactoring tools no longer drop comments. |
| **Audit annotations** | Lint passes scan trivia for `// SECURITY:` / `// PII:` / `// COMPLIANCE:` markers without re-parsing source text. |
| **`channel_analysis::channel_hover_markdown`** (Fase 13.g) | Can be enriched in a future sub-phase to read `IRChannel.source_line` → look up the `ChannelDefinition` AST node → return its leading doc comment as the hover content. |

---

## 4. Sub-phases

### 14.a — Lexer + AST + Parser end-to-end (Python + Rust) `[DONE]` ✓

Shipped as `axon-lang v1.8.0` on 2026-05-02.

#### 14.a.1 — Token kinds + Trivia struct (Python + Rust)

- **Python `tokens.py`**: four new `TokenType` variants — `LINE_COMMENT`, `BLOCK_COMMENT`, `DOC_LINE_COMMENT`, `DOC_BLOCK_COMMENT`. Pre-existing `COMMENT` kept for backward compat.
- **Python `ast_nodes.py`**: new `Trivia` frozen dataclass with `kind: str` (`"line"` | `"block"` | `"doc_line"` | `"doc_block"`), `text: str`, `line: int`, `column: int`. Plus `is_doc` property and `stripped_text()` method.
- **Rust `tokens.rs`**: same four new `TokenType` variants. New `Trivia { kind: TriviaKind, text, line, column }` struct + `TriviaKind` enum + `is_doc()` and `stripped_text()` methods.

#### 14.a.2 — Lexer emits comment tokens

- **Python `lexer.py`**: `_skip_whitespace` → `_consume_trivia`; `_skip_line_comment` → `_consume_line_comment` (emits a token with the doc-comment heuristic applied); `_skip_block_comment` → `_consume_block_comment` (same). New `tokenize(strip_comments: bool = False)` parameter for legacy callers.
- **Rust `lexer.rs`**: same renames + heuristic. New `tokenize_with(strip_comments: bool)` method; `tokenize()` keeps a no-arg shim that defaults to `strip_comments=false`.

Doc-comment heuristic (identical Python ↔ Rust): a `//` line is doc iff it starts with EXACTLY three slashes (`///` followed by a non-`/`); a `/*` block is doc iff it starts with `/**` followed by a non-`/`.

#### 14.a.3 — Parser materialises trivia

- **Python `parser.py`**: constructor splits the raw stream into effective tokens + parallel `_leading_trivia` / `_trailing_trivia` arrays. Auto-decorator pattern wraps every `_parse_*` method so the AST node returned by any production gets `leading_trivia` and `trailing_trivia` populated transparently. First-writer-wins so the innermost AST node along a chain of nested productions keeps the trivia.
- **Rust `parser.rs`**: constructor performs the same split (effective tokens + parallel arrays). `parse()` populates `Program.declaration_trivia` in lockstep with `Program.declarations`. Per-node trivia (mirror of Python's shape across the 97 structs) is deferred — the side-channel covers every adopter use case identified to date.

#### 14.a.4 — Tests

- **Python**: 26 in `tests/test_fase_14a_lossless_lexing.py` covering lexer emission of all four kinds, doc-comment heuristic, `Trivia` helpers, `ASTNode` field defaults, parser leading/trailing attachment, multi-decl scenarios, backward-compat with comment-free programs.
- **Python (regression)**: 5 pre-existing tests updated for the new token-count expectations (`168 → 170` tokens for `contract_analyzer.axon` because comments are now counted in the tally).
- **Rust**: 19 inline (10 in `lexer::fase14a_trivia_tests`, 9 in `parser::fase14a_declaration_trivia_tests`).

#### 14.a.5 — Suites

- Python: **4110 passed, 23 skipped, 0 failed** (+26 net vs v1.7.0).
- axon-frontend `--lib`: **128 passed, 0 failed** (109 baseline + 19 new).
- axon-rs `--lib`: **1031 passed, 0 failed** (no regression — golden IR parity intact).

---

### 14.b — Spread trivia into Rust AST structs `[DONE]` ✓

Shipped as part of `axon-lang v1.9.0` on 2026-04-27.

In 14.a the Rust side carried trivia as a parallel `Program.declaration_trivia` array — a side-channel that kept the existing 41 Declaration variant structs untouched. 14.b pours that data into the structs themselves:

- **`axon-frontend/src/ast.rs`**: every Declaration variant struct (`FlowDefinition`, `ChannelDefinition`, `PersonaDefinition`, `DaemonDefinition`, … 41 in total) gains `pub leading_trivia: Vec<Trivia>` and `pub trailing_trivia: Vec<Trivia>` fields with empty defaults.
- **`axon-frontend/src/parser.rs`**: a new `attach_trivia_to_decl(&mut decl, leading, trailing)` helper writes the trivia into the per-struct fields in lockstep with `Program.declaration_trivia`. Both the side-channel and the per-struct fields hold identical data so callers can use whichever access path they prefer.
- **Tests**: 5 new in `parser::fase14b_per_struct_trivia_tests` covering doc-line on flows, trailing comments on flows, doc-line on channels, side-channel ↔ per-struct equivalence, and the comment-free baseline.

This is the Rust mirror of Python's 14.a shape (where every `ASTNode` already carried `leading_trivia` / `trailing_trivia`), so adopters consuming the AST in either language now see the same surface.

### 14.c — Inner doc comments (`//!`, `/*!`) `[DONE]` ✓

Shipped as part of `axon-lang v1.9.0` on 2026-04-27.

Adds the Rust-style inner-doc convention to the lossless lexing channel:

| Marker | Kind | Documents | Token (Python / Rust) |
|---|---|---|---|
| `//` | regular line | nothing | `LINE_COMMENT` / `LineComment` |
| `///` | outer doc line (14.a) | next item | `DOC_LINE_COMMENT` / `DocLineComment` |
| `//!` | inner doc line (**14.c**) | enclosing module/file | `INNER_DOC_LINE_COMMENT` / `InnerDocLineComment` |
| `/* */` | regular block | nothing | `BLOCK_COMMENT` / `BlockComment` |
| `/** */` | outer doc block (14.a) | next item | `DOC_BLOCK_COMMENT` / `DocBlockComment` |
| `/*! */` | inner doc block (**14.c**) | enclosing module/file | `INNER_DOC_BLOCK_COMMENT` / `InnerDocBlockComment` |

- **Python `tokens.py` + `lexer.py`**: two new `TokenType` variants and the `_consume_line_comment` / `_consume_block_comment` heuristic extended to recognise `!` after `//` and `/*` respectively. The parser's `_COMMENT_TOKEN_KINDS` set and `_TRIVIA_KIND_BY_TOKEN` map gain the two new entries so trivia flows through unchanged.
- **Python `ast_nodes.py`**: `Trivia.is_inner_doc` property + `is_doc` property extended to include inner kinds. `stripped_text()` strips `//!` / `/*! … */` markers like the outer counterparts.
- **Rust `tokens.rs`**: two new `TokenType` variants + two new `TriviaKind` enum variants + `Trivia::is_inner_doc()` method. Same heuristic, identical to Python.
- **Tests**: 15 Python in `tests/test_fase_14c_inner_doc_comments.py` (lexer, helpers, parser end-to-end); 8 Rust (4 lexer, 4 parser).

Inner doc comments ride through the same `leading_trivia` / `trailing_trivia` arrays as outer doc comments — downstream consumers (axon doc, LSP) decide how to interpret `is_inner_doc()`. 14.f below is the first such consumer.

### 14.d — `axon fmt` MVP `[DONE]` ✓

Shipped as part of `axon-lang v1.9.0` on 2026-04-27.

A token-level formatter that consumes the lossless lexing channel to round-trip AXON source byte-identically (modulo two cosmetic normalisations) and a CLI subcommand wired to drive it:

- **`axon/compiler/formatter.py`**: `format_source(src: str) -> str` walks every token in source order (effective + comment), re-emitting each at its original `(line, column)` position. The output is canonicalised so each line has no trailing whitespace and the file ends with exactly one `\n`. Idempotent — `format_source(format_source(x)) == format_source(x)` for every input.
- **`axon/cli/fmt_cmd.py`**: `axon fmt <file>` writes formatted output to stdout; `--check` exits 1 if the file would be reformatted (CI gate, source untouched); `--write` rewrites in place.
- **`axon/cli/__init__.py`**: subcommand wired into the dispatcher; the dispatcher itself was refactored from a 14-branch if-chain into a `_DISPATCH` table for clarity.
- **`axon/cli/frontend_runtime.py`**: `fmt` added to `FRONTEND_COMMANDS` so the bootstrap pulls in the lexer/parser at command launch.
- **Tests**: 22 in `tests/test_fase_14d_formatter.py` covering all six comment kinds, cosmetic normalisations, idempotence (parametrised), and four CLI smoke tests (stdout, --check pass/fail, --write, missing file).

Layout canonicalisation (consistent indent width, brace style) is intentionally out of scope for the MVP — the formatter preserves the author's existing layout. A future phase can layer canonical reformatting on top of the same trivia channel without re-architecting.

### 14.f — LSP hover enrichment `[DONE]` ✓

Shipped as part of `axon-lang v1.9.0` on 2026-04-27.

`channel_hover_markdown` (the LSP `textDocument/hover` content for a `ChannelDefinition`) now reads `channel.leading_trivia` and prepends a Markdown paragraph built from any **outer** doc comments (`///`, `/** */`) attached to the declaration:

- **`axon-frontend/src/channel_analysis.rs`**: new `doc_comment_lines(&[Trivia]) -> Vec<String>` helper extracts outer doc bodies, strips conventional prefixes (`///` leading space, `* ` block-style decoration), and returns Markdown-ready lines. `channel_hover_markdown` calls it before the existing signature block.
- **Inner doc comments (`//!` / `/*! */`) are intentionally excluded** from per-channel hover. They document the enclosing module, not the declaration, so surfacing them on a single channel would mislead. They remain available to other consumers via `Trivia::is_inner_doc()`.
- **Regular comments (`//` / `/* */`) are excluded too** — they are not documentation. Only outer doc trivia reaches the hover paragraph.
- **Tests**: 6 new in `channel_analysis::tests` covering line and block doc rendering, multi-line doc paragraphs, inner-doc exclusion, regular-comment exclusion, and backward-compat for declarations without doc comments.

This delivers the first concrete adopter use case from §3 of this document. Other LSP hovers (flow, persona, daemon, …) can follow the same pattern; the helper is generic and reusable.

---

## 5. Possible future sub-phases

| Sub-phase | Goal | Trigger |
|---|---|---|
| 14.e | `axon doc` doc generator (rustdoc-style) | When public docs derived from `///` blocks become required |
| 14.g | Layout canonicalisation in `axon fmt` (consistent indent, brace style) | When a strict-format CI gate is on the roadmap |
| 14.h | LSP hover enrichment for flow/persona/daemon (mirror of 14.f) | When non-channel hovers need doc paragraphs |

---

## 6. Closure criterion (14.a)

✓ Reported gap closed: comments are now lossless from source through to the AST.
✓ Python tests: 26 new + 5 updated, suite green.
✓ Rust tests: 19 new (lexer + parser), workspace green.
✓ IR golden parity preserved (trivia never serialised).
✓ `Lexer.tokenize(strip_comments=True)` / `Lexer::tokenize_with(true)` opt-in for callers that want the legacy stream.
✓ Plan vivo (this document) + commit + tag + GitHub Release shipped.

## 7. Closure criterion (14.b / 14.c / 14.d / 14.f — v1.9.0)

✓ 14.b — 41 Declaration variant structs in Rust carry per-struct trivia fields; side-channel preserved for backward compat; 5 new Rust tests.
✓ 14.c — `//!` and `/*! */` recognised by both lexers; `Trivia.is_inner_doc` discriminator; 23 new tests (15 Python + 8 Rust).
✓ 14.d — `axon fmt` MVP with `--check` / `--write`; round-trip preservation, idempotence, and CLI integration; 22 new Python tests.
✓ 14.f — Outer doc comments rendered as Markdown paragraph in channel hover; inner doc and regular comments deliberately excluded; 6 new Rust tests.
✓ Combined: 4183 Python tests pass (+22 net vs v1.8.0), 147 axon-frontend tests pass (+19 net), 1031 axon-rs tests pass (no regression).
✓ IR golden parity preserved across all four sub-phases (trivia never serialised, formatter never touches IR).
