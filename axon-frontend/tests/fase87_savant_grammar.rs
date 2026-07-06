//! §Fase 87.a — grammar + AST + IR for the `savant` primitive
//! (`savant <Name> { domain:, cognition{…}, memory{…}, budget{…},
//! mandate <M> {…} }`). See `docs/fase/fase_87_savant.md` (axon-enterprise repo).
//!
//! Pinned properties (surface only — the §87.b/c checker owns semantics):
//! 1. A full `savant` parses into `SavantDefinition` (every field + sub-block).
//! 2. It lowers to `IRSavant`; absent optionals are ELIDED from the JSON.
//! 3. **IR-SHA invariance**: a program with no `savant` serialises with no
//!    `savants` key — byte-identical to pre-§87 IR.
//! 4. Multiple `mandate` blocks accumulate; comma- and newline-separated
//!    fields both parse.
//! 5. **D83.7** — an unknown field (top-level OR in any sub-block) is a hard
//!    parse error, never a silent skip.
//! 6. A minimal `savant` (domain + one mandate) parses.
//! 7. §87.a surface is check-clean: a savant with as-yet-unresolved refs
//!    (undeclared `memory` backend / output type) yields NO diagnostics — the
//!    checker lands in §87.b/c.

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::{ParseError, Parser};
use axon_frontend::type_checker::TypeChecker;

fn parse(src: &str) -> axon_frontend::ast::Program {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    Parser::new(tokens).parse().expect("parse")
}

fn try_parse(src: &str) -> Result<axon_frontend::ast::Program, ParseError> {
    let tokens = Lexer::new(src, "<test>").tokenize().expect("lex");
    Parser::new(tokens).parse()
}

fn check_errors(src: &str) -> Vec<String> {
    let prog = parse(src);
    TypeChecker::new(&prog)
        .check()
        .iter()
        .map(|e| e.message.clone())
        .collect()
}

fn first_savant(prog: &axon_frontend::ast::Program) -> &axon_frontend::ast::SavantDefinition {
    prog.declarations
        .iter()
        .find_map(|d| match d {
            axon_frontend::ast::Declaration::Savant(s) => Some(s),
            _ => None,
        })
        .expect("no savant declaration")
}

fn ir_json(src: &str) -> String {
    let prog = parse(src);
    let ir = IRGenerator::new().generate(&prog);
    serde_json::to_string(&ir).expect("serialize IR")
}

const FLOW: &str = "flow Chat() -> Unit { step S { ask: \"hi\" } }\n";

const FULL: &str = r#"
savant DeepTechAnalyst {
    domain: "Quantum Computing Error Correction",
    cognition {
        depth: hyper,
        entropic_threshold: 0.001,
        divergence: high
    }
    memory {
        backend: ResearchStore,
        corpus_graph: true,
        isolation_level: strict
    }
    budget {
        max_iterations: 50000,
        max_tool_synth: 12
    }
    mandate resolve_decoherence {
        objective: "Synthesise 2024-2026 topological-code papers and propose 3 novel architectures.",
        output: FormalReport
    }
}
"#;

// ── Property 1: full parse into the AST ──────────────────────────────────────

#[test]
fn full_savant_parses_every_field() {
    let prog = parse(FULL);
    let s = first_savant(&prog);
    assert_eq!(s.name, "DeepTechAnalyst");
    assert_eq!(s.domain, "Quantum Computing Error Correction");

    let cog = s.cognition.as_ref().expect("cognition block");
    assert_eq!(cog.depth, "hyper");
    assert_eq!(cog.entropic_threshold, Some(0.001));
    assert_eq!(cog.divergence, "high");

    let mem = s.memory.as_ref().expect("memory block");
    assert_eq!(mem.backend, "ResearchStore");
    assert!(mem.corpus_graph);
    assert_eq!(mem.isolation_level, "strict");

    let bud = s.budget.as_ref().expect("budget block");
    assert_eq!(bud.max_iterations, Some(50000));
    assert_eq!(bud.max_tool_synth, Some(12));

    assert_eq!(s.mandates.len(), 1);
    assert_eq!(s.mandates[0].name, "resolve_decoherence");
    assert!(s.mandates[0].objective.starts_with("Synthesise"));
    assert_eq!(s.mandates[0].output_type, "FormalReport");
}

// ── Property 2: lowering + optional elision ──────────────────────────────────

#[test]
fn full_savant_lowers_to_ir() {
    let json = ir_json(FULL);
    assert!(json.contains("\"savants\""), "savants key present: {json}");
    assert!(json.contains("\"DeepTechAnalyst\""));
    assert!(json.contains("\"Quantum Computing Error Correction\""));
    assert!(json.contains("\"resolve_decoherence\""));
    assert!(json.contains("\"FormalReport\""));
}

#[test]
fn minimal_savant_elides_absent_optionals() {
    let src = r#"
savant Minimal {
    domain: "x"
    mandate only { objective: "o", output: T }
}
"#;
    let json = ir_json(src);
    // The three optional sub-blocks are absent → their keys must NOT appear.
    assert!(!json.contains("\"cognition\""), "cognition elided: {json}");
    assert!(!json.contains("\"memory\""), "memory elided: {json}");
    assert!(!json.contains("\"budget\""), "budget elided: {json}");
    assert!(json.contains("\"savants\""));
}

// ── Property 3: IR-SHA invariance ────────────────────────────────────────────

#[test]
fn no_savant_leaves_ir_byte_identical() {
    let json = ir_json(FLOW);
    assert!(
        !json.contains("savants"),
        "a savant-less program must not carry a `savants` key: {json}"
    );
}

// ── Property 4: multiple mandates + separator flexibility ─────────────────────

#[test]
fn multiple_mandates_accumulate() {
    let src = r#"
savant Multi {
    domain: "d"
    mandate a { objective: "oa", output: T }
    mandate b { objective: "ob", output: U }
    mandate c { objective: "oc", output: V }
}
"#;
    let s_prog = parse(src);
    let s = first_savant(&s_prog);
    assert_eq!(s.mandates.len(), 3);
    assert_eq!(s.mandates[1].name, "b");
    assert_eq!(s.mandates[2].output_type, "V");
}

#[test]
fn newline_separated_fields_parse() {
    // Same as FULL but with no commas anywhere.
    let src = r#"
savant NoCommas {
    domain: "d"
    cognition {
        depth: deep
        entropic_threshold: 0.5
        divergence: low
    }
    mandate m { objective: "o" output: R }
}
"#;
    let prog = parse(src);
    let s = first_savant(&prog);
    assert_eq!(s.cognition.as_ref().unwrap().depth, "deep");
    assert_eq!(s.mandates[0].output_type, "R");
}

// ── Property 5: D83.7 — unknown fields are hard parse errors ──────────────────

#[test]
fn unknown_top_level_field_is_a_parse_error() {
    let src = r#"
savant Bad {
    domain: "d"
    nonsense: 3
    mandate m { objective: "o", output: T }
}
"#;
    let err = try_parse(src).expect_err("unknown top-level field must fail parse");
    assert!(
        err.message.contains("nonsense"),
        "error names the offending field: {}",
        err.message
    );
}

#[test]
fn unknown_cognition_field_is_a_parse_error() {
    let src = r#"
savant Bad {
    domain: "d"
    cognition { depth: deep, bogus: 1 }
    mandate m { objective: "o", output: T }
}
"#;
    let err = try_parse(src).expect_err("unknown cognition field must fail parse");
    assert!(err.message.contains("bogus"), "{}", err.message);
}

#[test]
fn unknown_mandate_field_is_a_parse_error() {
    let src = r#"
savant Bad {
    domain: "d"
    mandate m { objective: "o", output: T, extra: 9 }
}
"#;
    let err = try_parse(src).expect_err("unknown mandate field must fail parse");
    assert!(err.message.contains("extra"), "{}", err.message);
}

// ── Property 6: minimal form ─────────────────────────────────────────────────

#[test]
fn minimal_savant_parses() {
    let src = "savant M { domain: \"d\" mandate only { objective: \"o\", output: T } }\n";
    let prog = parse(src);
    let s = first_savant(&prog);
    assert_eq!(s.name, "M");
    assert_eq!(s.mandates.len(), 1);
    assert!(s.cognition.is_none());
    assert!(s.budget.is_none());
}

// ── Property 7: §87.a is check-clean (semantics deferred) ────────────────────

#[test]
fn surface_savant_is_check_clean() {
    // Unresolved `memory` backend + output type + no budget: all deferred to
    // §87.b/c, so §87.a must report NO diagnostics for a savant program.
    let src = format!("{FULL}{FLOW}");
    let errs = check_errors(&src);
    assert!(
        errs.is_empty(),
        "§87.a surface must be diagnostic-free (checker is §87.b/c): {errs:?}"
    );
}
