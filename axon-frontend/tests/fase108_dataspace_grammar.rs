//! §Fase 108.b — the typed `dataspace` declaration: grammar + AST + the
//! schema law (`axon-T928`) + IR emission (un-skipped `dataspace_specs`).
//! See `docs/fase/fase_108_deterministic_data_plane.md` (axon-enterprise).
//!
//! Pinned properties:
//! 1. `dataspace X { column a: Int … }` parses into typed `DataspaceColumn`s;
//!    aliases (`int`, `text`, …) are accepted and canonicalized at IR time.
//! 2. **axon-T928** — the schema law: empty schema / duplicate column /
//!    unknown type are refused; all violations accumulate in one compile.
//! 3. The body grammar is CLOSED: a non-`column` entry is a parse error
//!    (the §1 disease — a silently-discarded body — cannot recur).
//! 4. `dataspace_specs` is SERIALIZED into the IR JSON with canonical
//!    type names — the §108 ground-truth fix (the runtime can now see a
//!    declared dataspace).

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn parse(src: &str) -> axon_frontend::ast::Program {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    Parser::new(tokens).parse().expect("parse")
}

fn check_errors(src: &str) -> Vec<String> {
    let prog = parse(src);
    TypeChecker::new(&prog)
        .check()
        .iter()
        .map(|e| e.message.clone())
        .collect()
}

fn ir_json(src: &str) -> String {
    let prog = parse(src);
    let ir = IRGenerator::new().generate(&prog);
    serde_json::to_string(&ir).expect("serialize IR")
}

const GOOD: &str = r#"
dataspace Leads {
    column email:     Text
    column score:     Float
    column visits:    Int
    column active:    Bool
    column first_at:  Timestamp
    column raw:       Json
}
"#;

// ── 1. Grammar + AST ─────────────────────────────────────────────────────────

#[test]
fn parses_typed_columns_into_ast() {
    let prog = parse(GOOD);
    let ds = prog
        .declarations
        .iter()
        .find_map(|d| match d {
            axon_frontend::ast::Declaration::Dataspace(n) => Some(n),
            _ => None,
        })
        .expect("dataspace declaration present");
    assert_eq!(ds.name, "Leads");
    assert_eq!(ds.columns.len(), 6);
    assert_eq!(ds.columns[0].name, "email");
    assert_eq!(ds.columns[0].declared_type, "Text");
    assert_eq!(ds.columns[4].declared_type, "Timestamp");
}

#[test]
fn lowercase_aliases_parse_and_check_clean() {
    // The §38 from_token convention: common aliases resolve.
    let src = r#"
dataspace Metrics {
    column name:  text
    column n:     integer
    column ratio: double
    column ok:    boolean
}
"#;
    let errs = check_errors(src);
    assert!(
        !errs.iter().any(|e| e.contains("axon-T928")),
        "aliases must resolve against the closed catalog: {errs:?}"
    );
}

#[test]
fn non_column_body_entry_is_a_parse_error() {
    // The grammar is CLOSED — the pre-108.b behaviour (any body silently
    // discarded by skip_braced_block) must be impossible to reintroduce.
    let src = r#"
dataspace X {
    retention: 7
}
"#;
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    let err = Parser::new(tokens).parse().expect_err("must refuse");
    assert!(
        err.message.contains("column"),
        "the error must teach the grammar: {}",
        err.message
    );
}

// ── 2. axon-T928 — the schema law ────────────────────────────────────────────

#[test]
fn t928_refuses_an_empty_schema() {
    for src in ["dataspace Empty { }", "dataspace Bare"] {
        let errs = check_errors(src);
        assert!(
            errs.iter()
                .any(|e| e.contains("axon-T928") && e.contains("no columns")),
            "a dataspace IS its schema — `{src}` must refuse: {errs:?}"
        );
    }
}

#[test]
fn t928_refuses_a_duplicate_column() {
    let src = r#"
dataspace Dup {
    column email: Text
    column email: Int
}
"#;
    let errs = check_errors(src);
    assert!(
        errs.iter()
            .any(|e| e.contains("axon-T928") && e.contains("more than once")),
        "one name, one buffer: {errs:?}"
    );
}

#[test]
fn t928_refuses_an_unknown_type_with_a_suggestion() {
    let src = r#"
dataspace Bad {
    column score: Flaot
}
"#;
    let errs = check_errors(src);
    let t928 = errs
        .iter()
        .find(|e| e.contains("axon-T928") && e.contains("unknown type"))
        .expect("unknown type must refuse");
    assert!(
        t928.contains("Float"),
        "the closed catalog (and ideally the smart-suggest hint) must name Float: {t928}"
    );
}

#[test]
fn t928_violations_accumulate_in_one_compile() {
    // Duplicate AND unknown type in one declaration: both surface.
    let src = r#"
dataspace Multi {
    column a: Text
    column a: Text
    column b: Decimal
}
"#;
    let errs: Vec<String> = check_errors(src)
        .into_iter()
        .filter(|e| e.contains("axon-T928"))
        .collect();
    assert!(
        errs.len() >= 2,
        "all schema errors accumulate (parser keeps types raw): {errs:?}"
    );
}

// ── 3. IR emission — the un-skip ─────────────────────────────────────────────

#[test]
fn ir_json_carries_dataspace_specs_with_canonical_types() {
    let json = ir_json(GOOD);
    assert!(
        json.contains("\"dataspace_specs\""),
        "dataspace_specs must be SERIALIZED (the §108 ground-truth fix)"
    );
    assert!(json.contains("\"Leads\""));
    assert!(
        json.contains("\"column_type\":\"Timestamp\""),
        "canonical type names in the IR: {json}"
    );
}

#[test]
fn ir_canonicalizes_aliases() {
    let src = r#"
dataspace M {
    column n: integer
}
"#;
    let json = ir_json(src);
    assert!(
        json.contains("\"column_type\":\"Int\""),
        "alias `integer` canonicalizes to `Int` at IR generation: {json}"
    );
}
