---
title: "Plan vivo: Fase 14 — Lossless lexing + trivia channel"
status: SHIPPED — sub-fase 14.a completada 2026-05-02 (release v1.8.0)
owner: AXON Language Team
created: 2026-05-02
updated: 2026-05-02
target: axon-lang v1.8.0 (PyPI + crates.io)
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

## 5. Possible future sub-phases (not in 14.a)

| Sub-phase | Goal | Trigger |
|---|---|---|
| 14.b | Spread trivia into individual Rust AST structs (full mirror of Python's shape) | An adopter requests per-node trivia inside the AST instead of the side-channel |
| 14.c | Inner doc comments (`//!`, `/*!`) à la Rust | Module-level documentation requirements |
| 14.d | `axon fmt` formatter that consumes the trivia channel | When a stable formatter is on the roadmap |
| 14.e | `axon doc` doc generator (rustdoc-style) | When public docs derived from `///` blocks become required |
| 14.f | LSP hover enrichment in `channel_analysis::channel_hover_markdown` | When the LSP integration starts shipping rich hovers |

---

## 6. Closure criterion (14.a)

✓ Reported gap closed: comments are now lossless from source through to the AST.
✓ Python tests: 26 new + 5 updated, suite green.
✓ Rust tests: 19 new (lexer + parser), workspace green.
✓ IR golden parity preserved (trivia never serialised).
✓ `Lexer.tokenize(strip_comments=True)` / `Lexer::tokenize_with(true)` opt-in for callers that want the legacy stream.
✓ Plan vivo (this document) + commit + tag + GitHub Release shipped.
