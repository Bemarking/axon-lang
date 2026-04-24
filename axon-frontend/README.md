# axon-frontend

Pure compiler frontend for the AXON programming language: lexer, parser,
AST, epistemic type system, type checker, IR generator, and the compile-time
checker that sits above them.

## Design contract

**Zero runtime dependencies.** This crate must never depend on `tokio`,
`axum`, `sqlx`, `reqwest`, `aws-*`, `jsonwebtoken`, or any other crate
that pulls in networking, persistence, or async runtime. The only
allowed external dep is `serde` (and its proc-macro derive chain).

This contract is enforced in CI: any PR that adds a non-`serde`
dependency to `axon-frontend/Cargo.toml` fails the dep-audit job.

## Who uses this crate

- **`axon` crate** (the AXON runtime, in `../axon-rs/`) — re-exports
  `axon-frontend` modules so existing callers keep working.
- **`axon-lsp`** (the Language Server, separate repo) — consumes the
  frontend directly without dragging runtime deps.
- **Future tooling** — analyzers, formatters, linters, IDE plugins.

## Module layout

```
axon-frontend/src/
├── lib.rs             re-exports the public modules
├── tokens.rs          token enum + keyword tables                     (leaf)
├── lexer.rs           source text → tokens                             (→ tokens)
├── ast.rs             AST node definitions + helpers                   (leaf)
├── parser.rs          tokens → AST                                     (→ ast, tokens)
├── epistemic.rs       epistemic type primitives (HashMap/HashSet only) (leaf)
├── type_checker.rs    AST → type-checked AST                           (→ ast, epistemic)
├── ir_nodes.rs        IR node definitions                              (leaf)
├── ir_generator.rs    AST → IR                                         (→ ast, ir_nodes)
└── checker.rs         top-level compile-time checker                   (→ ast, lexer, parser, type_checker)
```

## Byte-identical parity with Python reference

The AXON project maintains byte-identical parity between a Python
reference implementation (in `../axon/`) and the Rust native runtime.
Because `axon-frontend` implements the parsing + type-checking layer
of the Rust side, its outputs MUST match the Python reference on the
golden-file test corpus. PRs that diverge are release blockers.
