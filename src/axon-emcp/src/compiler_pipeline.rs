//! The lex → parse → type-check → IR-generate pipeline, projected
//! through a single structured-diagnostic shape.
//!
//! `axon.check` and `axon.parse` are both thin wrappers around this
//! pipeline; the difference is only what they return on success. By
//! sharing the implementation we guarantee the diagnostics agents see
//! are byte-identical to what `axon check` prints (same lexer, same
//! parser, same type-checker — `axon-frontend` is a single dep).
//!
//! Wire shape (returned to the MCP client):
//!
//! ```jsonc
//! {
//!   "ok": false,
//!   "stage": "type_check",        // "lex" | "parse" | "type_check" | "ir_generate"
//!   "errors": [
//!     {
//!       "severity": "error",      // always "error" for blocking diagnostics
//!       "stage": "type_check",
//!       "message": "Session 'X' duality violation …",
//!       "line": 12,
//!       "column": 5
//!     }
//!   ],
//!   "warnings": [],               // populated by type_check's warning lane
//!   "summary": "1 error in type_check stage"
//! }
//! ```
//!
//! On success:
//!
//! ```jsonc
//! { "ok": true, "stage": "type_check", "errors": [], "warnings": [],
//!   "summary": "program is well-formed" }
//! ```

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::ir_nodes::IRProgram;
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;
use serde::Serialize;
use serde_json::Value;

/// The diagnostic shape every tool reports against. Uniform across
/// lex / parse / type-check so the agent's parser is one matcher.
#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    /// `"error"` or `"warning"`. We never emit `"info"` — the agent's
    /// reflex on `error` is "fix"; everything else is signal noise.
    pub severity: &'static str,
    /// Which pipeline stage produced this diagnostic.
    pub stage: Stage,
    /// Human-readable detail. Forwarded from `axon-frontend` verbatim
    /// so an agent sees exactly what `axon check` would print.
    pub message: String,
    /// 1-based source line (0 ⇒ "no source location available").
    pub line: u32,
    /// 1-based source column (0 ⇒ "no column available").
    pub column: u32,
}

/// Closed catalog of pipeline stages. Ordered: a `Lex` failure ends
/// the pipeline (parse cannot run); a `Parse` failure likewise. Only
/// `TypeCheck` collects multiple diagnostics in one pass.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    Lex,
    Parse,
    TypeCheck,
    IrGenerate,
}

impl Stage {
    fn as_str(self) -> &'static str {
        match self {
            Stage::Lex => "lex",
            Stage::Parse => "parse",
            Stage::TypeCheck => "type_check",
            Stage::IrGenerate => "ir_generate",
        }
    }
}

/// What the pipeline produced. `Ok` carries the IR (for `axon.parse`);
/// `Err` carries the diagnostics (for both `axon.check` and the failure
/// arm of `axon.parse`).
#[derive(Debug)]
pub enum Outcome {
    /// All stages passed. The IR is populated; the diagnostics vec
    /// holds any warnings the type-check stage surfaced.
    Ok {
        ir: IRProgram,
        warnings: Vec<Diagnostic>,
    },
    /// At least one stage failed. `stage` is the **first** stage that
    /// produced an error (subsequent stages did not run); `errors`
    /// holds every diagnostic from that stage.
    Err {
        stage: Stage,
        errors: Vec<Diagnostic>,
        warnings: Vec<Diagnostic>,
    },
}

/// Run the full pipeline on `source` and return the structured outcome.
///
/// `filename` is purely cosmetic — it lands in lexer errors' source
/// snippets so an agent can quote a virtual filename in its reply
/// (e.g. "your draft on line 12"). Defaults to `"<axon.check input>"`.
pub fn run(source: &str, filename: &str) -> Outcome {
    // ── Stage 1: lex ───────────────────────────────────────────────────
    let tokens = match Lexer::new(source, filename).tokenize() {
        Ok(t) => t,
        Err(e) => {
            return Outcome::Err {
                stage: Stage::Lex,
                errors: vec![Diagnostic {
                    severity: "error",
                    stage: Stage::Lex,
                    message: e.message,
                    line: e.line,
                    column: e.column,
                }],
                warnings: Vec::new(),
            };
        }
    };

    // ── Stage 2: parse ─────────────────────────────────────────────────
    let program = match Parser::new(tokens).parse() {
        Ok(p) => p,
        Err(e) => {
            return Outcome::Err {
                stage: Stage::Parse,
                errors: vec![Diagnostic {
                    severity: "error",
                    stage: Stage::Parse,
                    message: e.message,
                    line: e.line,
                    column: e.column,
                }],
                warnings: Vec::new(),
            };
        }
    };

    // ── Stage 3: type-check (collects multiple) ────────────────────────
    let (type_errors, type_warnings) = TypeChecker::new(&program).check_with_warnings();
    let warnings: Vec<Diagnostic> = type_warnings
        .into_iter()
        .map(|w| Diagnostic {
            severity: "warning",
            stage: Stage::TypeCheck,
            message: w.message,
            line: w.line,
            column: w.column,
        })
        .collect();
    if !type_errors.is_empty() {
        let errors = type_errors
            .into_iter()
            .map(|e| Diagnostic {
                severity: "error",
                stage: Stage::TypeCheck,
                message: e.message,
                line: e.line,
                column: e.column,
            })
            .collect();
        return Outcome::Err { stage: Stage::TypeCheck, errors, warnings };
    }

    // ── Stage 4: IR generate ───────────────────────────────────────────
    // IR generation is total over a well-typed program (no `Result`
    // surface) but we keep it inside the same match for symmetry with
    // future stages that may grow diagnostic surfaces.
    let ir = IRGenerator::new().generate(&program);
    Outcome::Ok { ir, warnings }
}

/// Project the [`Outcome`] into the **`axon.check`** wire shape — a
/// JSON object the agent receives verbatim. The IR is dropped (check
/// does not return it; that's `parse`'s job). Warnings are preserved.
pub fn outcome_to_check_payload(outcome: &Outcome) -> Value {
    match outcome {
        Outcome::Ok { warnings, .. } => serde_json::json!({
            "ok": true,
            "stage": Stage::TypeCheck.as_str(),
            "errors": Vec::<Diagnostic>::new(),
            "warnings": warnings,
            "summary": summary_for(true, 0, warnings.len()),
        }),
        Outcome::Err { stage, errors, warnings } => serde_json::json!({
            "ok": false,
            "stage": stage.as_str(),
            "errors": errors,
            "warnings": warnings,
            "summary": summary_for(false, errors.len(), warnings.len()),
        }),
    }
}

/// Project the [`Outcome`] into the **`axon.parse`** wire shape. On
/// success this carries the IR as a JSON value; on failure it is
/// shaped identically to `outcome_to_check_payload` so an agent can
/// reuse the same diagnostic parser.
pub fn outcome_to_parse_payload(outcome: Outcome) -> Value {
    match outcome {
        Outcome::Ok { ir, warnings } => {
            let ir_json = serde_json::to_value(&ir)
                .unwrap_or_else(|_| serde_json::json!({ "error": "ir serialisation failed" }));
            serde_json::json!({
                "ok": true,
                "stage": Stage::IrGenerate.as_str(),
                "ir": ir_json,
                "warnings": warnings,
                "summary": summary_for(true, 0, warnings.len()),
            })
        }
        Outcome::Err { stage, errors, warnings } => serde_json::json!({
            "ok": false,
            "stage": stage.as_str(),
            "errors": errors,
            "warnings": warnings,
            "summary": summary_for(false, errors.len(), warnings.len()),
        }),
    }
}

fn summary_for(ok: bool, err_count: usize, warn_count: usize) -> String {
    if ok && warn_count == 0 {
        "program is well-formed".to_string()
    } else if ok {
        format!("program is well-formed ({warn_count} warning(s))")
    } else {
        let suffix = if warn_count > 0 {
            format!(", {warn_count} warning(s)")
        } else {
            String::new()
        };
        format!("{err_count} error(s){suffix}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_source_parses_to_an_empty_program() {
        let out = run("", "<t>");
        match out {
            Outcome::Ok { ir, warnings } => {
                assert!(warnings.is_empty());
                // The IR has the canonical Program root.
                let v = serde_json::to_value(&ir).unwrap();
                assert_eq!(v["node_type"], "program");
            }
            other => panic!("empty source should parse OK, got: {other:?}"),
        }
    }

    #[test]
    fn syntactic_garbage_fails_at_lex_or_parse() {
        // `@@@` is not a valid token start in axon — lex rejects.
        let out = run("@@@", "<t>");
        match out {
            Outcome::Err { stage, errors, .. } => {
                assert!(matches!(stage, Stage::Lex | Stage::Parse));
                assert_eq!(errors.len(), 1);
                assert!(errors[0].line >= 1);
            }
            other => panic!("garbage should fail, got: {other:?}"),
        }
    }

    #[test]
    fn well_formed_program_with_no_diagnostics_returns_ok() {
        // A minimal program that lexes + parses + type-checks cleanly:
        // one persona declaration is enough.
        let src = r#"persona Tester { domain: ["test"] tone: precise }"#;
        let out = run(src, "<t>");
        match out {
            Outcome::Ok { warnings, .. } => assert!(warnings.is_empty()),
            other => panic!("well-formed program should pass, got: {other:?}"),
        }
    }

    #[test]
    fn check_payload_has_uniform_shape_on_ok() {
        let out = run("", "<t>");
        let payload = outcome_to_check_payload(&out);
        assert_eq!(payload["ok"], true);
        assert_eq!(payload["stage"], "type_check");
        assert!(payload["errors"].is_array());
        assert!(payload["warnings"].is_array());
        assert_eq!(payload["summary"], "program is well-formed");
    }

    #[test]
    fn check_payload_has_uniform_shape_on_err() {
        let out = run("@@@", "<t>");
        let payload = outcome_to_check_payload(&out);
        assert_eq!(payload["ok"], false);
        assert!(payload["errors"].as_array().unwrap().len() >= 1);
        let summary = payload["summary"].as_str().unwrap();
        assert!(summary.contains("error"));
    }

    #[test]
    fn parse_payload_includes_ir_on_success() {
        let out = run("", "<t>");
        let payload = outcome_to_parse_payload(out);
        assert_eq!(payload["ok"], true);
        assert_eq!(payload["stage"], "ir_generate");
        assert_eq!(payload["ir"]["node_type"], "program");
    }

    #[test]
    fn parse_payload_omits_ir_on_failure() {
        let out = run("@@@", "<t>");
        let payload = outcome_to_parse_payload(out);
        assert_eq!(payload["ok"], false);
        assert!(payload["ir"].is_null());
    }

    #[test]
    fn summary_phrasing_is_stable_across_branches() {
        assert_eq!(summary_for(true, 0, 0), "program is well-formed");
        assert_eq!(
            summary_for(true, 0, 2),
            "program is well-formed (2 warning(s))"
        );
        assert_eq!(summary_for(false, 3, 0), "3 error(s)");
        assert_eq!(summary_for(false, 3, 1), "3 error(s), 1 warning(s)");
    }
}
