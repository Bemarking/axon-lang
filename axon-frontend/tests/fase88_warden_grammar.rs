//! §Fase 88.a — grammar + AST + IR for the `warden` adversarial-analysis
//! flow-body block + the `scope` authorization-policy declaration. See
//! `docs/fase/fase_88_warden.md` (axon-enterprise repo).
//!
//! Pinned properties (surface only — the §88.c checker owns semantics):
//! 1. A full `scope` parses into `ScopeDefinition` (targets/depth/approver).
//! 2. A `warden(<target>) within <Scope> { body }` parses into `WardenBlock`.
//! 3. **Fail-closed by grammar** — a `warden` with no `within <Scope>` clause is
//!    a HARD parse error (a scopeless warden cannot be written).
//! 4. Both lower to IR (`IRScope` top-level, `IRWarden` as an `IRFlowNode`).
//! 5. **IR-SHA invariance** — a program with no `scope` serialises with no
//!    `scopes` key.
//! 6. **D83.7** — an unknown `scope` field is a hard parse error.
//! 7. The `warden` body (nested flow steps) is preserved.

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::{ParseError, Parser};

fn parse(src: &str) -> axon_frontend::ast::Program {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    Parser::new(tokens).parse().expect("parse")
}

fn try_parse(src: &str) -> Result<axon_frontend::ast::Program, ParseError> {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    Parser::new(tokens).parse()
}

fn ir_json(src: &str) -> String {
    let prog = parse(src);
    let ir = IRGenerator::new().generate(&prog);
    serde_json::to_string(&ir).expect("serialize IR")
}

fn first_scope(prog: &axon_frontend::ast::Program) -> &axon_frontend::ast::ScopeDefinition {
    prog.declarations
        .iter()
        .find_map(|d| match d {
            axon_frontend::ast::Declaration::Scope(s) => Some(s),
            _ => None,
        })
        .expect("no scope declaration")
}

/// Pull the first `warden` block out of the first flow's steps.
fn first_warden(prog: &axon_frontend::ast::Program) -> &axon_frontend::ast::WardenBlock {
    for d in &prog.declarations {
        if let axon_frontend::ast::Declaration::Flow(f) = d {
            for step in &f.body {
                if let axon_frontend::ast::FlowStep::Warden(w) = step {
                    return w;
                }
            }
        }
    }
    panic!("no warden block");
}

const SCOPE: &str = r#"
scope InternalAudit {
    targets: [ "svc://payments-core", "svc://ledger" ]
    depth: static_artifact
    approver: requires "security.lead"
}
"#;

const FULL: &str = r#"
scope InternalAudit {
    targets: [ "svc://payments-core" ]
    depth: static_artifact
    approver: requires "security.lead"
}
flow Audit() -> Unit {
    warden(payments_core) within InternalAudit {
        step S { ask: "analyse" }
    }
}
"#;

// ── scope (top-level declaration) ────────────────────────────────────────────

#[test]
fn full_scope_parses_every_field() {
    let prog = parse(SCOPE);
    let s = first_scope(&prog);
    assert_eq!(s.name, "InternalAudit");
    assert_eq!(s.targets.len(), 2);
    assert_eq!(s.targets[0], "svc://payments-core");
    assert_eq!(s.targets[1], "svc://ledger");
    assert_eq!(s.depth, "static_artifact");
    assert_eq!(s.approver, "security.lead");
}

#[test]
fn scope_lowers_to_ir() {
    let json = ir_json(SCOPE);
    assert!(json.contains("\"scopes\""), "scopes key present: {json}");
    assert!(json.contains("\"InternalAudit\""));
    assert!(json.contains("static_artifact"));
    assert!(json.contains("security.lead"));
}

#[test]
fn no_scope_leaves_ir_byte_identical() {
    let json = ir_json("flow Chat() -> Unit { step S { ask: \"hi\" } }\n");
    assert!(!json.contains("scopes"), "no scope ⇒ no scopes key: {json}");
}

#[test]
fn unknown_scope_field_is_a_parse_error() {
    let src = "scope S { targets: [ \"a\" ] depth: static_artifact nonsense: 3 }\n";
    let err = try_parse(src).expect_err("unknown scope field must fail parse");
    assert!(err.message.contains("nonsense"), "{}", err.message);
}

#[test]
fn approver_without_requires_sugar_parses() {
    let src = "scope S { targets: [ \"a\" ] depth: static_artifact approver: \"sec.lead\" }\n";
    let prog = parse(src);
    assert_eq!(first_scope(&prog).approver, "sec.lead");
}

// ── warden (flow-body block) ─────────────────────────────────────────────────

#[test]
fn full_warden_parses_target_scope_and_body() {
    let prog = parse(FULL);
    let w = first_warden(&prog);
    assert_eq!(w.target, "payments_core");
    assert_eq!(w.scope_ref, "InternalAudit");
    assert_eq!(w.body.len(), 1, "the nested step is preserved");
}

#[test]
fn warden_lowers_to_ir_flow_node() {
    let json = ir_json(FULL);
    assert!(json.contains("\"warden\""), "warden node present: {json}");
    assert!(json.contains("\"InternalAudit\""));
    assert!(json.contains("payments_core"));
}

#[test]
fn warden_without_within_is_a_hard_parse_error() {
    // Fail-closed by grammar: a scopeless warden cannot be written.
    let src = r#"
flow Audit() -> Unit {
    warden(target) {
        step S { ask: "x" }
    }
}
"#;
    assert!(
        try_parse(src).is_err(),
        "a warden with no `within <Scope>` must fail to parse"
    );
}

#[test]
fn warden_with_within_but_empty_body_parses() {
    let src = r#"
flow Audit() -> Unit {
    warden(t) within S { }
}
"#;
    let prog = parse(src);
    let w = first_warden(&prog);
    assert_eq!(w.scope_ref, "S");
    assert!(w.body.is_empty());
}
