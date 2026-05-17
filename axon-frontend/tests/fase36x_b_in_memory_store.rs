//! §Fase 36.x.b (D2) — `in_memory` is a first-class declarable
//! `axonstore` backend.
//!
//! The runtime `StoreRegistry::classify_backend` already maps
//! `"in_memory"` → `StoreHandle::InMemory`. The only gap was the
//! frontend: `VALID_STORE_BACKENDS` omitted `in_memory`, so a
//! source-declared in-memory store was a compile error — and the
//! canonical agent flow could not run or be tested without a live
//! Postgres. 36.x.b closes it.
//!
//! Pins:
//!   1. `axonstore X { backend: in_memory }` type-checks clean.
//!   2. …with NO `connection:` — it is optional for `in_memory`.
//!   3. The three SQL backends still type-check (no regression).
//!   4. An unknown backend is still rejected.
//!   5. The full agent flow — `in_memory` store + retrieve + step +
//!      persist + a streaming `axonendpoint` — compiles with zero
//!      errors.

use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn errors(src: &str) -> Vec<String> {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    let prog = Parser::new(tokens).parse().expect("parse");
    TypeChecker::new(&prog)
        .check()
        .into_iter()
        .map(|e| e.message)
        .collect()
}

fn backend_errors(src: &str) -> Vec<String> {
    errors(src)
        .into_iter()
        .filter(|m| m.to_lowercase().contains("backend"))
        .collect()
}

// ─── §1 — `in_memory` type-checks clean ────────────────────────────

#[test]
fn s1_in_memory_store_type_checks_clean() {
    let errs = backend_errors("axonstore mem { backend: in_memory connection: \"\" }");
    assert!(
        errs.is_empty(),
        "36.x.b D2: `backend: in_memory` must type-check — it is a \
         first-class declarable axonstore backend. Got: {errs:?}"
    );
}

// ─── §2 — `connection:` is optional for `in_memory` ────────────────

#[test]
fn s2_in_memory_store_needs_no_connection() {
    let errs = errors("axonstore mem { backend: in_memory }");
    assert!(
        errs.is_empty(),
        "36.x.b D2: an `in_memory` store needs no `connection:` — the \
         declaration must type-check with zero errors. Got: {errs:?}"
    );
}

// ─── §3 — the SQL backends still type-check (no regression) ────────

#[test]
fn s3_sql_backends_still_valid() {
    for b in ["postgresql", "mysql", "sqlite"] {
        let errs =
            backend_errors(&format!("axonstore s {{ backend: {b} connection: \"x\" }}"));
        assert!(
            errs.is_empty(),
            "36.x.b D5: `backend: {b}` must remain valid — no \
             regression. Got: {errs:?}"
        );
    }
}

// ─── §4 — an unknown backend is still rejected ─────────────────────

#[test]
fn s4_unknown_store_backend_still_rejected() {
    let errs = backend_errors("axonstore s { backend: redis connection: \"x\" }");
    assert!(
        errs.iter().any(|m| m.contains("redis")),
        "36.x.b: an unknown store backend is still a compile error. \
         Got: {errs:?}"
    );
}

// ─── §5 — the full agent flow compiles ─────────────────────────────

#[test]
fn s5_agent_flow_with_in_memory_store_compiles_clean() {
    // retrieve context → deliberate (step) → persist result, against
    // an in-memory store, behind a streaming axonendpoint — the
    // canonical agent shape, now declarable with zero infrastructure.
    let src = "axonstore mem { backend: in_memory }\n\
        flow AgentFlow() -> Unit {\n\
            retrieve mem { where: \"kind = 'history'\" as: history }\n\
            step Deliberate { ask: \"answer\" output: Stream<Token> }\n\
            persist into mem { kind: \"reply\" content: \"done\" }\n\
        }\n\
        axonendpoint AgentE { method: POST path: \"/agent\" \
        execute: AgentFlow backend: stub transport: sse }";
    let errs = errors(src);
    assert!(
        errs.is_empty(),
        "36.x.b D2: the canonical agent flow (retrieve → step → \
         persist) against an `in_memory` store must compile with zero \
         errors. Got: {errs:?}"
    );
}
