//! `axon compile` native implementation.
//!
//! Pipeline: Source → Lex → Parse → Type-check → IR Generate → JSON

use std::io::{self, IsTerminal};
use std::path::Path;

use crate::ir_generator::IRGenerator;
use crate::lexer::{Lexer, LexerError};
use crate::parser::{ParseError, Parser};
use crate::type_checker::TypeChecker;

const AXON_VERSION: &str = "0.30.6";

// ── ANSI helpers ─────────────────────────────────────────────────────────────

fn c(text: &str, code: &str, use_color: bool) -> String {
    if use_color {
        format!("{code}{text}\x1b[0m")
    } else {
        text.to_string()
    }
}

// ── Public entry point ───────────────────────────────────────────────────────

pub fn run_compile(
    file: &str,
    backend: &str,
    output: Option<&str>,
    stdout: bool,
) -> i32 {
    let use_color = io::stdout().is_terminal();
    let path = Path::new(file);
    let filename = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| file.to_string());

    // ── 1. Read source ───────────────────────────────────────────
    let source = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "{}",
                c(&format!("X File not found: {file}"), "\x1b[1;31m", use_color)
            );
            return 2;
        }
    };

    // ── 2. Lex ───────────────────────────────────────────────────
    let tokens = match Lexer::new(&source, file).tokenize() {
        Ok(t) => t,
        Err(LexerError { message, line, column }) => {
            let loc = if column > 0 {
                format!(":{line}:{column}")
            } else {
                format!(":{line}")
            };
            eprintln!(
                "{}  {message}",
                c(&format!("X {filename}{loc}"), "\x1b[1;31m", use_color)
            );
            return 1;
        }
    };

    // ── 3. Parse ─────────────────────────────────────────────────
    let mut parser = Parser::new(tokens);
    let program = match parser.parse() {
        Ok(p) => p,
        Err(ParseError { message, line, column }) => {
            let loc = if column > 0 {
                format!(":{line}:{column}")
            } else {
                format!(":{line}")
            };
            eprintln!(
                "{}  {message}",
                c(&format!("X {filename}{loc}"), "\x1b[1;31m", use_color)
            );
            return 1;
        }
    };

    // ── 4. Type check ────────────────────────────────────────────
    let type_errors = TypeChecker::new(&program).check();
    if !type_errors.is_empty() {
        eprintln!(
            "{}  {} type error(s)",
            c(&format!("X {filename}"), "\x1b[1;31m", use_color),
            type_errors.len()
        );
        for te in &type_errors {
            eprintln!("  error [line {}]: {}", te.line, te.message);
        }
        return 1;
    }

    // ── 5. Generate IR ───────────────────────────────────────────
    let ir_program = IRGenerator::new().generate(&program);

    // ── 6. Serialize to JSON ─────────────────────────────────────
    let mut ir_value = serde_json::to_value(&ir_program).unwrap_or(serde_json::Value::Null);

    // Add _meta
    if let serde_json::Value::Object(ref mut map) = ir_value {
        let meta = serde_json::json!({
            "source": file,
            "backend": backend,
            "axon_version": AXON_VERSION,
        });
        map.insert("_meta".to_string(), meta);
    }

    let ir_json = serde_json::to_string_pretty(&ir_value).unwrap_or_default();

    // ── 7. Output ────────────────────────────────────────────────
    if stdout {
        println!("{ir_json}");
    } else {
        let out_path = match output {
            Some(o) => o.to_string(),
            None => {
                let p = Path::new(file).with_extension("ir.json");
                p.to_string_lossy().into_owned()
            }
        };
        if let Err(e) = std::fs::write(&out_path, &ir_json) {
            eprintln!("axon: failed to write {out_path}: {e}");
            return 2;
        }
        println!(
            "{}",
            c(&format!("\u{2713} Compiled \u{2192} {out_path}"), "\x1b[1;32m", use_color)
        );
    }

    0
}
