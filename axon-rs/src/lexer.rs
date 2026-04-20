//! AXON Lexer — direct port of axon/compiler/lexer.py.
//!
//! Source text → Vec<Token>
//!
//! Handles:
//!   - All AXON keywords (100+)
//!   - String literals with escape sequences
//!   - Integer / Float / Duration literals
//!   - Arrow (->), DotDot (..), comparison operators
//!   - Line comments (//) and block comments (/* */)
//!   - Line/column tracking for error messages

use crate::tokens::{keyword_type, Token, TokenType};

// ── Public error type ─────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct LexerError {
    pub message: String,
    pub line: u32,
    pub column: u32,
}

// ── Lexer ─────────────────────────────────────────────────────────────────────

pub struct Lexer {
    source: Vec<char>,
    _filename: String,
    pos: usize,
    line: u32,
    column: u32,
    tokens: Vec<Token>,
}

impl Lexer {
    pub fn new(source: &str, filename: &str) -> Self {
        Lexer {
            source: source.chars().collect(),
            _filename: filename.to_string(),
            pos: 0,
            line: 1,
            column: 1,
            tokens: Vec::new(),
        }
    }

    // ── public API ────────────────────────────────────────────────

    pub fn tokenize(mut self) -> Result<Vec<Token>, LexerError> {
        while !self.at_end() {
            self.skip_whitespace()?;
            if self.at_end() {
                break;
            }
            self.scan_token()?;
        }
        self.tokens.push(Token {
            ttype: TokenType::Eof,
            value: String::new(),
            line: self.line,
            column: self.column,
        });
        Ok(self.tokens)
    }

    // ── character helpers ─────────────────────────────────────────

    fn at_end(&self) -> bool {
        self.pos >= self.source.len()
    }

    fn peek(&self) -> char {
        if self.at_end() {
            '\0'
        } else {
            self.source[self.pos]
        }
    }

    fn peek_next(&self) -> char {
        if self.pos + 1 >= self.source.len() {
            '\0'
        } else {
            self.source[self.pos + 1]
        }
    }

    fn advance(&mut self) -> char {
        let ch = self.source[self.pos];
        self.pos += 1;
        if ch == '\n' {
            self.line += 1;
            self.column = 1;
        } else {
            self.column += 1;
        }
        ch
    }

    fn match_char(&mut self, expected: char) -> bool {
        if self.at_end() || self.source[self.pos] != expected {
            return false;
        }
        self.advance();
        true
    }

    fn emit(&mut self, ttype: TokenType, value: &str, line: u32, column: u32) {
        self.tokens.push(Token {
            ttype,
            value: value.to_string(),
            line,
            column,
        });
    }

    // ── whitespace & comments ─────────────────────────────────────

    fn skip_whitespace(&mut self) -> Result<(), LexerError> {
        while !self.at_end() {
            let ch = self.peek();
            if ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' {
                self.advance();
            } else if ch == '/' && self.peek_next() == '/' {
                self.skip_line_comment();
            } else if ch == '/' && self.peek_next() == '*' {
                self.skip_block_comment()?;
            } else {
                break;
            }
        }
        Ok(())
    }

    fn skip_line_comment(&mut self) {
        self.advance(); // /
        self.advance(); // /
        while !self.at_end() && self.peek() != '\n' {
            self.advance();
        }
    }

    fn skip_block_comment(&mut self) -> Result<(), LexerError> {
        let start_line = self.line;
        let start_col = self.column;
        self.advance(); // /
        self.advance(); // *
        while !self.at_end() {
            if self.peek() == '*' && self.peek_next() == '/' {
                self.advance(); // *
                self.advance(); // /
                return Ok(());
            }
            self.advance();
        }
        Err(LexerError {
            message: "Unterminated block comment".to_string(),
            line: start_line,
            column: start_col,
        })
    }

    // ── main scanner dispatch ─────────────────────────────────────

    fn scan_token(&mut self) -> Result<(), LexerError> {
        let line = self.line;
        let col = self.column;
        let ch = self.advance();

        match ch {
            '{' => self.emit(TokenType::LBrace, "{", line, col),
            '}' => self.emit(TokenType::RBrace, "}", line, col),
            '(' => self.emit(TokenType::LParen, "(", line, col),
            ')' => self.emit(TokenType::RParen, ")", line, col),
            '[' => self.emit(TokenType::LBracket, "[", line, col),
            ']' => self.emit(TokenType::RBracket, "]", line, col),
            ':' => self.emit(TokenType::Colon, ":", line, col),
            ',' => self.emit(TokenType::Comma, ",", line, col),
            '?' => self.emit(TokenType::Question, "?", line, col),
            '@' => self.emit(TokenType::At, "@", line, col),
            '+' => self.emit(TokenType::Plus, "+", line, col),
            '*' => self.emit(TokenType::Star, "*", line, col),

            '.' => {
                if self.match_char('.') {
                    self.emit(TokenType::DotDot, "..", line, col);
                } else {
                    self.emit(TokenType::Dot, ".", line, col);
                }
            }

            '-' => {
                if self.match_char('>') {
                    self.emit(TokenType::Arrow, "->", line, col);
                } else if !self.at_end() && self.peek().is_ascii_digit() {
                    self.scan_number(line, col, '\0', true)?;
                } else {
                    self.emit(TokenType::Minus, "-", line, col);
                }
            }

            '/' => self.emit(TokenType::Slash, "/", line, col),

            '<' => {
                if self.match_char('=') {
                    self.emit(TokenType::Lte, "<=", line, col);
                } else {
                    self.emit(TokenType::Lt, "<", line, col);
                }
            }
            '>' => {
                if self.match_char('=') {
                    self.emit(TokenType::Gte, ">=", line, col);
                } else {
                    self.emit(TokenType::Gt, ">", line, col);
                }
            }
            '=' => {
                if self.match_char('=') {
                    self.emit(TokenType::Eq, "==", line, col);
                } else {
                    self.emit(TokenType::Assign, "=", line, col);
                }
            }
            '!' => {
                if self.match_char('=') {
                    self.emit(TokenType::Neq, "!=", line, col);
                } else {
                    return Err(LexerError {
                        message: "Unexpected '!'. Did you mean '!='?".to_string(),
                        line,
                        column: col,
                    });
                }
            }

            '"' => self.scan_string(line, col)?,

            c if c.is_ascii_digit() => self.scan_number(line, col, c, false)?,
            c if c.is_alphabetic() || c == '_' => self.scan_identifier(line, col, c),

            c => {
                return Err(LexerError {
                    message: format!("Unexpected character {:?}", c),
                    line,
                    column: col,
                });
            }
        }

        Ok(())
    }

    // ── literal scanners ──────────────────────────────────────────

    fn scan_string(&mut self, start_line: u32, start_col: u32) -> Result<(), LexerError> {
        let mut chars = String::new();
        while !self.at_end() && self.peek() != '"' {
            if self.peek() == '\n' {
                chars.push(self.advance());
                continue;
            }
            if self.peek() == '\\' {
                self.advance(); // consume backslash
                if self.at_end() {
                    return Err(LexerError {
                        message: "Unterminated escape sequence".to_string(),
                        line: self.line,
                        column: self.column,
                    });
                }
                let esc = self.advance();
                match esc {
                    'n' => chars.push('\n'),
                    't' => chars.push('\t'),
                    '\\' => chars.push('\\'),
                    '"' => chars.push('"'),
                    c => chars.push(c),
                }
            } else {
                chars.push(self.advance());
            }
        }
        if self.at_end() {
            return Err(LexerError {
                message: "Unterminated string".to_string(),
                line: start_line,
                column: start_col,
            });
        }
        self.advance(); // closing "
        self.emit(TokenType::StringLit, &chars, start_line, start_col);
        Ok(())
    }

    /// `first_char`: the first digit already consumed (or '\0' if negative prefix).
    /// `negative`: true if a leading '-' was consumed before calling this.
    fn scan_number(
        &mut self,
        start_line: u32,
        start_col: u32,
        first_char: char,
        negative: bool,
    ) -> Result<(), LexerError> {
        let mut digits = String::new();
        if negative {
            digits.push('-');
        }
        if first_char != '\0' {
            digits.push(first_char);
        }

        // Integer part
        while !self.at_end() && self.peek().is_ascii_digit() {
            digits.push(self.advance());
        }

        let mut is_float = false;

        // Decimal point (but not range operator ..)
        if !self.at_end() && self.peek() == '.' && self.peek_next() != '.' {
            is_float = true;
            digits.push(self.advance()); // '.'
            if self.at_end() || !self.peek().is_ascii_digit() {
                return Err(LexerError {
                    message: "Expected digit after decimal point".to_string(),
                    line: self.line,
                    column: self.column,
                });
            }
            while !self.at_end() && self.peek().is_ascii_digit() {
                digits.push(self.advance());
            }
        }

        let raw = digits.clone();

        // Duration suffix?
        if !self.at_end() && self.peek().is_alphabetic() {
            let saved_pos = self.pos;
            let saved_col = self.column;
            let mut suffix = String::new();
            while !self.at_end() && self.peek().is_alphabetic() {
                suffix.push(self.advance());
            }
            if matches!(suffix.as_str(), "s" | "ms" | "m" | "h" | "d") {
                let value = format!("{}{}", raw, suffix);
                self.emit(TokenType::Duration, &value, start_line, start_col);
                return Ok(());
            } else {
                // Rewind
                self.pos = saved_pos;
                self.column = saved_col;
            }
        }

        if is_float {
            self.emit(TokenType::Float, &raw, start_line, start_col);
        } else {
            self.emit(TokenType::Integer, &raw, start_line, start_col);
        }
        Ok(())
    }

    fn scan_identifier(&mut self, start_line: u32, start_col: u32, first_char: char) {
        let mut word = String::new();
        word.push(first_char);
        while !self.at_end() && (self.peek().is_alphanumeric() || self.peek() == '_') {
            word.push(self.advance());
        }
        let ttype = keyword_type(&word);
        self.emit(ttype, &word, start_line, start_col);
    }
}

#[cfg(test)]
mod fase_1_to_5_end_to_end {
    //! Lexer integration tests covering the new Fase 1–5 keywords end-to-end.
    //! These feed real source text through the lexer and assert the emitted
    //! TokenTypes — closing the loop beyond the unit tests in `tokens.rs`.
    use super::*;

    fn kinds(source: &str) -> Vec<TokenType> {
        Lexer::new(source, "<test>")
            .tokenize()
            .expect("lex ok")
            .into_iter()
            .map(|t| t.ttype)
            .collect()
    }

    #[test]
    fn resource_decl_tokenizes() {
        let kinds = kinds("resource Db { kind: postgres lifetime: linear }");
        assert!(kinds.contains(&TokenType::Resource));
        assert!(kinds.contains(&TokenType::LBrace));
        assert!(kinds.contains(&TokenType::RBrace));
    }

    #[test]
    fn fabric_manifest_observe_tokenize() {
        let src = r#"
            fabric Vpc { provider: aws region: "us-east-1" zones: 2 }
            manifest M { resources: [Db] fabric: Vpc }
            observe O { sources: [M] quorum: 1 on_partition: degrade }
        "#;
        let k = kinds(src);
        assert!(k.contains(&TokenType::Fabric));
        assert!(k.contains(&TokenType::Manifest));
        assert!(k.contains(&TokenType::Observe));
    }

    #[test]
    fn reconcile_lease_ensemble_tokenize() {
        let src = r#"
            reconcile R { manifest: M observe: O max_retries: 3 period: "60s" }
            lease L { resource: Db ttl: "30m" renewable: true }
            ensemble E { daemons: [] quorum: 1 disagreement: degrade }
        "#;
        let k = kinds(src);
        assert!(k.contains(&TokenType::Reconcile));
        assert!(k.contains(&TokenType::Lease));
        assert!(k.contains(&TokenType::Ensemble));
    }

    #[test]
    fn topology_and_session_pi_calculus_tokenize() {
        let src = r#"
            session S {
              client: [send Request end]
              server: [receive Request end]
            }
            topology T { nodes: [A, B] edges: [A -> B : S] }
        "#;
        let k = kinds(src);
        assert!(k.contains(&TokenType::Session));
        assert!(k.contains(&TokenType::Send));
        assert!(k.contains(&TokenType::Receive));
        assert!(k.contains(&TokenType::End));
        assert!(k.contains(&TokenType::Topology));
    }

    #[test]
    fn immune_reflex_heal_tokenize() {
        let src = r#"
            immune I { sensitivity: 0.5 window: "1m" baseline: "7d" action: alert }
            reflex Rf { on: drift action: throttle }
            heal H { target: I max_patches: 3 rollback_on: divergence }
        "#;
        let k = kinds(src);
        assert!(k.contains(&TokenType::Immune));
        assert!(k.contains(&TokenType::Reflex));
        assert!(k.contains(&TokenType::Heal));
    }

    #[test]
    fn new_keywords_do_not_collide_with_identifiers() {
        // Identifiers that look similar must still lex as Identifier, not keyword.
        let k = kinds("resource_group manifested observer reconciled leased");
        for tt in k.iter() {
            assert!(
                !matches!(
                    tt,
                    TokenType::Resource
                        | TokenType::Manifest
                        | TokenType::Observe
                        | TokenType::Reconcile
                        | TokenType::Lease
                ),
                "near-match identifier wrongly classified as keyword: {tt:?}"
            );
        }
    }
}
