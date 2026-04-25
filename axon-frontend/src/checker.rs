//! `axon check` native implementation.
//!
//! Pipeline for C6:
//!   1. Read file (exit 2 if not found)
//!   2. Lex → token list (exit 1 on lexer error)
//!   3. Parse → AST (exit 1 on parse error)
//!   4. Type check → errors (exit 1 on type errors)
//!   5. Count tokens and declarations from AST
//!   6. Report result — format matches Python check_cmd output

use std::io::{self, IsTerminal};
use std::path::Path;

use crate::ast::Declaration;
use crate::lexer::{Lexer, LexerError};
use crate::parser::{ParseError, Parser};
use crate::type_checker::TypeChecker;

// ── ANSI color helpers ────────────────────────────────────────────────────────

struct Colors {
    green_bold:  &'static str,
    red_bold:    &'static str,
    yellow_bold: &'static str,
    bold:        &'static str,
    dim:         &'static str,
    reset:       &'static str,
}

impl Colors {
    fn new(enabled: bool) -> Self {
        if enabled {
            Colors {
                green_bold:  "\x1b[1;32m",
                red_bold:    "\x1b[1;31m",
                yellow_bold: "\x1b[1;33m",
                bold:        "\x1b[1m",
                dim:         "\x1b[2m",
                reset:       "\x1b[0m",
            }
        } else {
            Colors {
                green_bold:  "",
                red_bold:    "",
                yellow_bold: "",
                bold:        "",
                dim:         "",
                reset:       "",
            }
        }
    }
}

// ── Declaration counter ──────────────────────────────────────────────────────

fn count_declarations(decls: &[Declaration]) -> usize {
    let mut count = 0;
    for decl in decls {
        count += 1;
        if let Declaration::Epistemic(eb) = decl {
            count += count_declarations(&eb.body);
        }
    }
    count
}

// ── Public entry point ────────────────────────────────────────────────────────

/// Run `axon check` natively. Returns an exit code (0 / 1 / 2).
///
/// `strict = true` (Fase 13.e D4) promotes warnings (e.g. legacy
/// string-topic listeners) to errors so the check exits non-zero.
pub fn run_check(file: &str, no_color: bool, strict: bool) -> i32 {
    let use_color = !no_color && io::stdout().is_terminal();
    let c = Colors::new(use_color);

    let path = Path::new(file);
    let filename = path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| file.to_string());

    // ── 1. Read source ────────────────────────────────────────────
    let source = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => {
            eprintln!(
                "{}X File not found: {}{}",
                c.red_bold, file, c.reset
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
                "{}X {filename}{loc}{}  {message}",
                c.red_bold, c.reset
            );
            return 1;
        }
    };

    // ── 3. Token count ───────────────────────────────────────────
    let token_count = tokens.len();

    // ── 4. Parse → AST ───────────────────────────────────────────
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
                "{}X {filename}{loc}{}  Parse error: {message}",
                c.red_bold, c.reset
            );
            return 1;
        }
    };

    // ── 5. Declaration count from AST ────────────────────────────
    let declaration_count = count_declarations(&program.declarations);

    // ── 6. Type check ────────────────────────────────────────────
    let (type_errors, type_warnings) = TypeChecker::new(&program).check_with_warnings();

    if !type_errors.is_empty() {
        eprintln!(
            "{}X {filename}{}  {} error(s){}",
            c.red_bold, c.reset, type_errors.len(),
            if type_warnings.is_empty() {
                String::new()
            } else {
                format!(", {} warning(s)", type_warnings.len())
            }
        );
        for te in &type_errors {
            eprintln!("  error [line {}]: {}", te.line, te.message);
        }
        for tw in &type_warnings {
            eprintln!("  warning [line {}]: {}", tw.line, tw.message);
        }
        return 1;
    }

    // ── 6.b §Fase 13.e — strict mode promotes warnings to errors ─
    if strict && !type_warnings.is_empty() {
        eprintln!(
            "{}X {filename}{}  0 errors, {} warning(s) {}(--strict){}",
            c.red_bold, c.reset, type_warnings.len(),
            c.red_bold, c.reset,
        );
        for tw in &type_warnings {
            eprintln!("  error [line {}]: {}", tw.line, tw.message);
        }
        return 1;
    }

    // ── 7. Report (warnings present but non-strict — pass with hint) ─
    if !type_warnings.is_empty() {
        println!(
            "{}\u{26A0}{} {}{filename}{}  {}{token_count} tokens \u{00B7} {declaration_count} declarations \u{00B7} 0 errors \u{00B7} {} warning(s){}",
            c.yellow_bold, c.reset,
            c.bold, c.reset,
            c.dim, type_warnings.len(), c.reset,
        );
        for tw in &type_warnings {
            println!("  warning [line {}]: {}", tw.line, tw.message);
        }
        return 0;
    }

    // ── 7.b. Fully clean ────────────────────────────────────────
    println!(
        "{}\u{2713}{} {}{filename}{}  {}{token_count} tokens \u{00B7} {declaration_count} declarations \u{00B7} 0 errors{}",
        c.green_bold, c.reset,
        c.bold, c.reset,
        c.dim, c.reset,
    );

    0
}
