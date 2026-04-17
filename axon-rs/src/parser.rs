//! AXON Parser — recursive descent, fail-fast.
//!
//! Direct port of axon/compiler/parser.py.
//!
//! Tier 1 constructs (persona, context, anchor, memory, tool, type,
//! flow, step, intent, run, epistemic, if, for, let, return) are
//! fully parsed into typed AST nodes.
//!
//! Tier 2+ constructs are parsed structurally (balanced braces) into
//! `GenericDeclaration` / `GenericFlowStep`.

use crate::ast::*;
use crate::tokens::{is_declaration_keyword, Token, TokenType};

// ── Public error type ────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct ParseError {
    pub message: String,
    pub line: u32,
    pub column: u32,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[line {}:{}] {}", self.line, self.column, self.message)
    }
}

// ── Parser ───────────────────────────────────────────────────────────────────

pub struct Parser {
    tokens: Vec<Token>,
    pos: usize,
}

impl Parser {
    pub fn new(tokens: Vec<Token>) -> Self {
        Parser { tokens, pos: 0 }
    }

    // ── public API ───────────────────────────────────────────────

    pub fn parse(&mut self) -> Result<Program, ParseError> {
        let mut program = Program {
            declarations: Vec::new(),
            loc: Loc { line: 1, column: 1 },
        };
        while !self.check(TokenType::Eof) {
            let decl = self.parse_declaration()?;
            program.declarations.push(decl);
        }
        Ok(program)
    }

    // ── token helpers ────────────────────────────────────────────

    fn current(&self) -> &Token {
        if self.pos >= self.tokens.len() {
            self.tokens.last().unwrap() // EOF sentinel
        } else {
            &self.tokens[self.pos]
        }
    }

    fn advance(&mut self) -> &Token {
        let idx = self.pos;
        if self.pos < self.tokens.len() {
            self.pos += 1;
        }
        &self.tokens[idx]
    }

    fn check(&self, tt: TokenType) -> bool {
        self.current().ttype == tt
    }

    fn consume(&mut self, expected: TokenType) -> Result<Token, ParseError> {
        let tok = self.current().clone();
        if tok.ttype != expected {
            return Err(ParseError {
                message: format!(
                    "Expected {:?}, found {:?}('{}')",
                    expected, tok.ttype, tok.value
                ),
                line: tok.line,
                column: tok.column,
            });
        }
        self.pos += 1;
        Ok(tok)
    }

    /// Consume any identifier or keyword-used-as-value.
    fn consume_any_ident_or_kw(&mut self) -> Result<Token, ParseError> {
        let tok = self.current().clone();
        match tok.ttype {
            TokenType::Identifier | TokenType::Bool | TokenType::StringLit
            | TokenType::Integer | TokenType::Float => {
                self.pos += 1;
                Ok(tok)
            }
            _ => {
                // Allow any keyword token whose value is alphabetic
                if !tok.value.is_empty()
                    && tok.value.chars().all(|c| c.is_alphanumeric() || c == '_')
                    && tok.ttype != TokenType::Eof
                {
                    self.pos += 1;
                    Ok(tok)
                } else {
                    Err(ParseError {
                        message: format!(
                            "Expected identifier or keyword value, found {:?}('{}')",
                            tok.ttype, tok.value
                        ),
                        line: tok.line,
                        column: tok.column,
                    })
                }
            }
        }
    }

    fn consume_number(&mut self) -> Result<f64, ParseError> {
        let tok = self.current().clone();
        match tok.ttype {
            TokenType::Float | TokenType::Integer => {
                self.pos += 1;
                tok.value.parse::<f64>().map_err(|_| ParseError {
                    message: format!("Invalid number '{}'", tok.value),
                    line: tok.line,
                    column: tok.column,
                })
            }
            _ => Err(ParseError {
                message: format!("Expected number, found {:?}('{}')", tok.ttype, tok.value),
                line: tok.line,
                column: tok.column,
            }),
        }
    }

    fn parse_bool(&mut self) -> Result<bool, ParseError> {
        let tok = self.consume(TokenType::Bool)?;
        Ok(tok.value == "true")
    }

    fn loc_of(&self, tok: &Token) -> Loc {
        Loc {
            line: tok.line,
            column: tok.column,
        }
    }

    fn check_comparison(&self) -> bool {
        matches!(
            self.current().ttype,
            TokenType::Lt | TokenType::Gt | TokenType::Lte
                | TokenType::Gte | TokenType::Eq | TokenType::Neq
        )
    }

    fn check_run_modifier(&self) -> bool {
        matches!(
            self.current().ttype,
            TokenType::As
                | TokenType::Within
                | TokenType::ConstrainedBy
                | TokenType::OnFailure
                | TokenType::OutputTo
                | TokenType::Effort
        )
    }

    // ── list helpers ─────────────────────────────────────────────

    fn parse_string_list(&mut self) -> Result<Vec<String>, ParseError> {
        self.consume(TokenType::LBracket)?;
        let mut items = Vec::new();
        items.push(self.consume(TokenType::StringLit)?.value);
        while self.check(TokenType::Comma) {
            self.advance();
            items.push(self.consume(TokenType::StringLit)?.value);
        }
        self.consume(TokenType::RBracket)?;
        Ok(items)
    }

    fn parse_identifier_list(&mut self) -> Result<Vec<String>, ParseError> {
        let mut names = Vec::new();
        names.push(self.consume(TokenType::Identifier)?.value);
        while self.check(TokenType::Comma) {
            self.advance();
            names.push(self.consume(TokenType::Identifier)?.value);
        }
        Ok(names)
    }

    fn parse_bracketed_identifiers(&mut self) -> Result<Vec<String>, ParseError> {
        self.consume(TokenType::LBracket)?;
        let items = self.parse_extended_identifier_list()?;
        self.consume(TokenType::RBracket)?;
        Ok(items)
    }

    fn parse_extended_identifier_list(&mut self) -> Result<Vec<String>, ParseError> {
        let mut items = Vec::new();
        items.push(self.consume_any_ident_or_kw()?.value);
        while self.check(TokenType::Comma) {
            self.advance();
            items.push(self.consume_any_ident_or_kw()?.value);
        }
        Ok(items)
    }

    fn parse_dotted_identifier(&mut self) -> Result<String, ParseError> {
        let mut parts = vec![self.consume_any_ident_or_kw()?.value];
        while self.check(TokenType::Dot) {
            self.advance();
            parts.push(self.consume_any_ident_or_kw()?.value);
        }
        Ok(parts.join("."))
    }

    fn parse_expression_string(&mut self) -> Result<String, ParseError> {
        if self.check(TokenType::LBracket) {
            let items = self.parse_bracketed_dot_identifiers()?;
            return Ok(format!("[{}]", items.join(", ")));
        }
        self.parse_dotted_identifier()
    }

    fn parse_bracketed_dot_identifiers(&mut self) -> Result<Vec<String>, ParseError> {
        self.consume(TokenType::LBracket)?;
        let mut items = vec![self.parse_dotted_identifier()?];
        while self.check(TokenType::Comma) {
            self.advance();
            items.push(self.parse_dotted_identifier()?);
        }
        self.consume(TokenType::RBracket)?;
        Ok(items)
    }

    fn parse_argument_list(&mut self) -> Result<Vec<String>, ParseError> {
        let mut args = Vec::new();
        while !self.check(TokenType::RParen) {
            let tok = self.current().clone();
            match tok.ttype {
                TokenType::StringLit | TokenType::Integer | TokenType::Float => {
                    self.advance();
                    args.push(tok.value);
                }
                TokenType::Identifier => {
                    self.advance();
                    let mut val = tok.value;
                    if self.check(TokenType::Dot) {
                        self.advance();
                        val.push('.');
                        val.push_str(&self.consume_any_ident_or_kw()?.value);
                    }
                    args.push(val);
                }
                _ => {
                    self.advance();
                    let key = tok.value;
                    if self.check(TokenType::Colon) {
                        self.advance();
                        let v = self.advance().value.clone();
                        args.push(format!("{key}:{v}"));
                    } else {
                        args.push(key);
                    }
                }
            }
            if self.check(TokenType::Comma) {
                self.advance();
            }
        }
        Ok(args)
    }

    /// Skip a single value or balanced bracketed/braced block (unknown field).
    fn skip_value(&mut self) {
        match self.current().ttype {
            TokenType::LBracket => {
                self.advance();
                let mut depth = 1u32;
                while depth > 0 && !self.check(TokenType::Eof) {
                    if self.check(TokenType::LBracket) {
                        depth += 1;
                    } else if self.check(TokenType::RBracket) {
                        depth -= 1;
                    }
                    self.advance();
                }
            }
            TokenType::LBrace => {
                self.advance();
                let mut depth = 1u32;
                while depth > 0 && !self.check(TokenType::Eof) {
                    if self.check(TokenType::LBrace) {
                        depth += 1;
                    } else if self.check(TokenType::RBrace) {
                        depth -= 1;
                    }
                    self.advance();
                }
            }
            TokenType::Lt => {
                // effect row: <io, network, ...>
                self.advance();
                let mut depth = 1u32;
                while depth > 0 && !self.check(TokenType::Eof) {
                    if self.check(TokenType::Lt) {
                        depth += 1;
                    } else if self.check(TokenType::Gt) {
                        depth -= 1;
                    }
                    self.advance();
                }
            }
            _ => {
                self.advance();
                while self.check(TokenType::Dot) {
                    self.advance();
                    self.advance();
                }
            }
        }
    }

    /// Skip a balanced `{ ... }` block including its braces.
    fn skip_braced_block(&mut self) -> Result<(), ParseError> {
        self.consume(TokenType::LBrace)?;
        let mut depth = 1u32;
        while depth > 0 {
            if self.check(TokenType::Eof) {
                let tok = self.current();
                return Err(ParseError {
                    message: "Unterminated block — expected '}'".to_string(),
                    line: tok.line,
                    column: tok.column,
                });
            }
            if self.check(TokenType::LBrace) {
                depth += 1;
            } else if self.check(TokenType::RBrace) {
                depth -= 1;
            }
            self.advance();
        }
        Ok(())
    }

    fn at_declaration_start(&self) -> bool {
        is_declaration_keyword(&self.current().ttype) || self.check(TokenType::Eof)
    }

    // ── top-level dispatch ───────────────────────────────────────

    fn parse_declaration(&mut self) -> Result<Declaration, ParseError> {
        let tok = self.current().clone();

        match tok.ttype {
            TokenType::Import => self.parse_import().map(Declaration::Import),
            TokenType::Persona => self.parse_persona().map(Declaration::Persona),
            TokenType::Context => self.parse_context().map(Declaration::Context),
            TokenType::Anchor => self.parse_anchor().map(Declaration::Anchor),
            TokenType::Memory => self.parse_memory().map(Declaration::Memory),
            TokenType::Tool => self.parse_tool().map(Declaration::Tool),
            TokenType::Type => self.parse_type_def().map(Declaration::Type),
            TokenType::Flow => self.parse_flow().map(Declaration::Flow),
            TokenType::Intent => self.parse_intent().map(Declaration::Intent),
            TokenType::Run => self.parse_run().map(Declaration::Run),
            TokenType::Let => self.parse_let().map(Declaration::Let),
            TokenType::Know | TokenType::Believe | TokenType::Speculate | TokenType::Doubt => {
                self.parse_epistemic_block().map(Declaration::Epistemic)
            }
            TokenType::Lambda => self.parse_lambda_data().map(Declaration::LambdaData),

            // ── Tier 2 declarations (full AST) ──────────────────
            TokenType::Agent => self.parse_agent().map(Declaration::Agent),
            TokenType::Shield => self.parse_shield().map(Declaration::Shield),
            TokenType::Pix => self.parse_pix().map(Declaration::Pix),
            TokenType::Psyche => self.parse_psyche().map(Declaration::Psyche),
            TokenType::Corpus => self.parse_corpus().map(Declaration::Corpus),
            TokenType::Dataspace => self.parse_dataspace().map(Declaration::Dataspace),
            TokenType::Ots => self.parse_ots().map(Declaration::Ots),
            TokenType::Mandate => self.parse_mandate().map(Declaration::Mandate),
            TokenType::Compute => self.parse_compute().map(Declaration::Compute),
            TokenType::Daemon => self.parse_daemon().map(Declaration::Daemon),
            TokenType::AxonStore => self.parse_axonstore().map(Declaration::AxonStore),
            TokenType::AxonEndpoint => self.parse_axonendpoint().map(Declaration::AxonEndpoint),

            // ── Tier 3+ structural fallback ─────────────────────
            // Store operations: keyword target { ... } or keyword target ...
            TokenType::Ingest
            | TokenType::Persist
            | TokenType::Retrieve
            | TokenType::Mutate
            | TokenType::Purge
            | TokenType::Transact => self.parse_generic_declaration(),

            // MCP declaration
            TokenType::Mcp => self.parse_generic_declaration(),

            _ => Err(ParseError {
                message: format!(
                    "Unexpected token at top level: '{}' — expected declaration \
                     (persona, context, anchor, flow, run, ...)",
                    tok.value
                ),
                line: tok.line,
                column: tok.column,
            }),
        }
    }

    // ── IMPORT ───────────────────────────────────────────────────

    fn parse_import(&mut self) -> Result<ImportNode, ParseError> {
        let tok = self.consume(TokenType::Import)?;
        let loc = self.loc_of(&tok);

        let mut path_parts = Vec::new();

        // Optional @ scope
        if self.check(TokenType::At) {
            self.advance();
            let first = self.consume(TokenType::Identifier)?;
            path_parts.push(format!("@{}", first.value));
        } else {
            let first = self.consume(TokenType::Identifier)?;
            path_parts.push(first.value);
        }

        while self.check(TokenType::Dot) {
            self.advance();
            if self.check(TokenType::LBrace) {
                break;
            }
            let part = self.consume(TokenType::Identifier)?;
            path_parts.push(part.value);
        }

        let mut names = Vec::new();
        if self.check(TokenType::LBrace) {
            self.advance();
            names = self.parse_identifier_list()?;
            self.consume(TokenType::RBrace)?;
        }

        // Skip optional APX policy (with apx { ... })
        if self.current().value == "with" {
            self.advance();
            self.advance(); // consume "apx"
            if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }

        Ok(ImportNode {
            module_path: path_parts,
            names,
            loc,
        })
    }

    // ── PERSONA ──────────────────────────────────────────────────

    fn parse_persona(&mut self) -> Result<PersonaDefinition, ParseError> {
        let tok = self.consume(TokenType::Persona)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = PersonaDefinition {
            name,
            domain: Vec::new(),
            tone: String::new(),
            confidence_threshold: None,
            cite_sources: None,
            refuse_if: Vec::new(),
            language: String::new(),
            description: String::new(),
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "domain" => node.domain = self.parse_string_list()?,
                "tone" => node.tone = self.consume_any_ident_or_kw()?.value,
                "confidence_threshold" => {
                    node.confidence_threshold = Some(self.consume_number()?)
                }
                "cite_sources" => node.cite_sources = Some(self.parse_bool()?),
                "refuse_if" => node.refuse_if = self.parse_bracketed_identifiers()?,
                "language" => node.language = self.consume(TokenType::StringLit)?.value,
                "description" => node.description = self.consume(TokenType::StringLit)?.value,
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── CONTEXT ──────────────────────────────────────────────────

    fn parse_context(&mut self) -> Result<ContextDefinition, ParseError> {
        let tok = self.consume(TokenType::Context)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = ContextDefinition {
            name,
            memory_scope: String::new(),
            language: String::new(),
            depth: String::new(),
            max_tokens: None,
            temperature: None,
            cite_sources: None,
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "memory" => node.memory_scope = self.consume_any_ident_or_kw()?.value,
                "language" => node.language = self.consume(TokenType::StringLit)?.value,
                "depth" => node.depth = self.consume_any_ident_or_kw()?.value,
                "max_tokens" => {
                    node.max_tokens = Some(
                        self.consume(TokenType::Integer)?
                            .value
                            .parse::<i64>()
                            .unwrap_or(0),
                    )
                }
                "temperature" => node.temperature = Some(self.consume_number()?),
                "cite_sources" => node.cite_sources = Some(self.parse_bool()?),
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── ANCHOR ───────────────────────────────────────────────────

    fn parse_anchor(&mut self) -> Result<AnchorConstraint, ParseError> {
        let tok = self.consume(TokenType::Anchor)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = AnchorConstraint {
            name,
            require: String::new(),
            reject: Vec::new(),
            enforce: String::new(),
            description: String::new(),
            confidence_floor: None,
            unknown_response: String::new(),
            on_violation: String::new(),
            on_violation_target: String::new(),
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "require" => node.require = self.consume_any_ident_or_kw()?.value,
                "description" => node.description = self.consume(TokenType::StringLit)?.value,
                "reject" => node.reject = self.parse_bracketed_identifiers()?,
                "enforce" => node.enforce = self.consume_any_ident_or_kw()?.value,
                "confidence_floor" => node.confidence_floor = Some(self.consume_number()?),
                "unknown_response" => {
                    node.unknown_response = self.consume(TokenType::StringLit)?.value
                }
                "on_violation" => {
                    // Parse: raise ErrorName | fallback(...) | identifier
                    let action = self.consume_any_ident_or_kw()?.value;
                    node.on_violation = action.clone();
                    if action == "raise" || action == "fallback" {
                        node.on_violation_target = self.consume_any_ident_or_kw()?.value;
                    }
                }
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── MEMORY ───────────────────────────────────────────────────

    fn parse_memory(&mut self) -> Result<MemoryDefinition, ParseError> {
        let tok = self.consume(TokenType::Memory)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = MemoryDefinition {
            name,
            store: String::new(),
            backend: String::new(),
            retrieval: String::new(),
            decay: String::new(),
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "store" => node.store = self.consume_any_ident_or_kw()?.value,
                "backend" => node.backend = self.consume_any_ident_or_kw()?.value,
                "retrieval" => node.retrieval = self.consume_any_ident_or_kw()?.value,
                "decay" => {
                    if self.check(TokenType::Duration) {
                        node.decay = self.advance().value.clone();
                    } else {
                        node.decay = self.consume_any_ident_or_kw()?.value;
                    }
                }
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── TOOL ─────────────────────────────────────────────────────

    fn parse_tool(&mut self) -> Result<ToolDefinition, ParseError> {
        let tok = self.consume(TokenType::Tool)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = ToolDefinition {
            name,
            provider: String::new(),
            max_results: None,
            filter_expr: String::new(),
            timeout: String::new(),
            runtime: String::new(),
            sandbox: None,
            effects: None,
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "provider" => node.provider = self.consume_any_ident_or_kw()?.value,
                "max_results" => {
                    node.max_results = Some(
                        self.consume(TokenType::Integer)?
                            .value
                            .parse::<i64>()
                            .unwrap_or(0),
                    )
                }
                "filter" => node.filter_expr = self.parse_filter_expression()?,
                "timeout" => node.timeout = self.consume(TokenType::Duration)?.value,
                "runtime" => node.runtime = self.consume_any_ident_or_kw()?.value,
                "sandbox" => node.sandbox = Some(self.parse_bool()?),
                "effects" => node.effects = Some(self.parse_effect_row()?),
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_filter_expression(&mut self) -> Result<String, ParseError> {
        let name = self.consume_any_ident_or_kw()?.value;
        if self.check(TokenType::LParen) {
            self.advance();
            let mut parts = vec![name, "(".to_string()];
            while !self.check(TokenType::RParen) {
                parts.push(self.advance().value.clone());
            }
            self.consume(TokenType::RParen)?;
            parts.push(")".to_string());
            Ok(parts.join(""))
        } else {
            Ok(name)
        }
    }

    fn parse_effect_row(&mut self) -> Result<EffectRow, ParseError> {
        let tok = self.consume(TokenType::Lt)?;
        let loc = self.loc_of(&tok);
        let mut effects = Vec::new();
        let mut epistemic_level = String::new();

        while !self.check(TokenType::Gt) {
            let name = self.consume_any_ident_or_kw()?.value;
            if self.check(TokenType::Colon) {
                self.advance();
                let level = self.consume_any_ident_or_kw()?.value;
                if name == "epistemic" {
                    epistemic_level = level;
                } else {
                    effects.push(format!("{name}:{level}"));
                }
            } else {
                effects.push(name);
            }
            if self.check(TokenType::Comma) {
                self.advance();
            }
        }
        self.consume(TokenType::Gt)?;

        Ok(EffectRow {
            effects,
            epistemic_level,
            loc,
        })
    }

    // ── TYPE ─────────────────────────────────────────────────────

    fn parse_type_def(&mut self) -> Result<TypeDefinition, ParseError> {
        let tok = self.consume(TokenType::Type)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;

        let mut node = TypeDefinition {
            name,
            fields: Vec::new(),
            range_constraint: None,
            where_clause: None,
            loc: loc.clone(),
        };

        // Optional range: (0.0..1.0)
        if self.check(TokenType::LParen) {
            self.advance();
            let min_val = self.consume_number()?;
            self.consume(TokenType::DotDot)?;
            let max_val = self.consume_number()?;
            self.consume(TokenType::RParen)?;
            node.range_constraint = Some(RangeConstraint {
                min_value: min_val,
                max_value: max_val,
                loc: loc.clone(),
            });
        }

        // Optional where clause
        if self.check(TokenType::Where) {
            self.advance();
            let mut expr_parts = Vec::new();
            while !self.check(TokenType::LBrace) && !self.at_declaration_start() {
                if self.check(TokenType::Eof) {
                    break;
                }
                expr_parts.push(self.advance().value.clone());
            }
            node.where_clause = Some(WhereClause {
                expression: expr_parts.join(" "),
                loc: loc.clone(),
            });
        }

        // Optional body: { field: Type, ... }
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) {
                let field_name = self.consume(TokenType::Identifier)?;
                let field_loc = self.loc_of(&field_name);
                self.consume(TokenType::Colon)?;
                let type_expr = self.parse_type_expr()?;
                node.fields.push(TypeField {
                    name: field_name.value,
                    type_expr,
                    loc: field_loc,
                });
                if self.check(TokenType::Comma) {
                    self.advance();
                }
            }
            self.consume(TokenType::RBrace)?;
        }

        Ok(node)
    }

    fn parse_type_expr(&mut self) -> Result<TypeExpr, ParseError> {
        let name_tok = self.consume(TokenType::Identifier)?;
        let loc = self.loc_of(&name_tok);
        let mut generic_param = String::new();
        let mut optional = false;

        if self.check(TokenType::Lt) {
            self.advance();
            generic_param = self.consume(TokenType::Identifier)?.value;
            self.consume(TokenType::Gt)?;
        }
        if self.check(TokenType::Question) {
            self.advance();
            optional = true;
        }

        Ok(TypeExpr {
            name: name_tok.value,
            generic_param,
            optional,
            loc,
        })
    }

    // ── FLOW ─────────────────────────────────────────────────────

    fn parse_flow(&mut self) -> Result<FlowDefinition, ParseError> {
        let tok = self.consume(TokenType::Flow)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;

        self.consume(TokenType::LParen)?;
        let mut parameters = Vec::new();
        if !self.check(TokenType::RParen) {
            parameters = self.parse_param_list()?;
        }
        self.consume(TokenType::RParen)?;

        let mut return_type = None;
        if self.check(TokenType::Arrow) {
            self.advance();
            return_type = Some(self.parse_type_expr()?);
        }

        self.consume(TokenType::LBrace)?;
        let mut body = Vec::new();
        while !self.check(TokenType::RBrace) {
            body.push(self.parse_flow_step()?);
        }
        self.consume(TokenType::RBrace)?;

        Ok(FlowDefinition {
            name,
            parameters,
            return_type,
            body,
            loc,
        })
    }

    fn parse_param_list(&mut self) -> Result<Vec<Parameter>, ParseError> {
        let mut params = Vec::new();

        let name = self.consume(TokenType::Identifier)?;
        let ploc = self.loc_of(&name);
        self.consume(TokenType::Colon)?;
        let type_expr = self.parse_type_expr()?;
        params.push(Parameter {
            name: name.value,
            type_expr,
            loc: ploc,
        });

        while self.check(TokenType::Comma) {
            self.advance();
            let name = self.consume(TokenType::Identifier)?;
            let ploc = self.loc_of(&name);
            self.consume(TokenType::Colon)?;
            let type_expr = self.parse_type_expr()?;
            params.push(Parameter {
                name: name.value,
                type_expr,
                loc: ploc,
            });
        }
        Ok(params)
    }

    // ── FLOW STEP dispatch ───────────────────────────────────────

    fn parse_flow_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();

        match tok.ttype {
            TokenType::Step => self.parse_step().map(FlowStep::Step),
            TokenType::If => self.parse_if().map(FlowStep::If),
            TokenType::For => self.parse_for_in().map(FlowStep::ForIn),
            TokenType::Let => self.parse_let().map(FlowStep::Let),
            TokenType::Return => self.parse_return().map(FlowStep::Return),
            TokenType::Lambda => self.parse_lambda_data_apply().map(FlowStep::LambdaDataApply),

            // ── Tier 2 flow steps (typed AST) ─────────────────────
            TokenType::Probe => self.parse_flow_step_simple("probe").map(|l| FlowStep::Probe(ProbeStep { target: l.1, loc: l.0 })),
            TokenType::Reason => self.parse_flow_step_simple("reason").map(|l| FlowStep::Reason(ReasonStep { strategy: String::new(), target: l.1, loc: l.0 })),
            TokenType::Validate => self.parse_flow_step_simple("validate").map(|l| FlowStep::Validate(ValidateStep { target: l.1, rule: String::new(), loc: l.0 })),
            TokenType::Refine => self.parse_flow_step_simple("refine").map(|l| FlowStep::Refine(RefineStep { target: l.1, strategy: String::new(), loc: l.0 })),
            TokenType::Weave => self.parse_weave_step(),
            TokenType::Use => self.parse_use_step(),
            TokenType::Remember => self.parse_remember_step(),
            TokenType::Recall => self.parse_recall_step(),
            TokenType::Par => self.parse_block_step("par").map(|l| FlowStep::Par(ParBlock { loc: l })),
            TokenType::Hibernate => self.parse_hibernate_step(),
            TokenType::Deliberate => self.parse_block_step("deliberate").map(|l| FlowStep::Deliberate(DeliberateBlock { loc: l })),
            TokenType::Consensus => self.parse_block_step("consensus").map(|l| FlowStep::Consensus(ConsensusBlock { loc: l })),
            TokenType::Forge => self.parse_block_step("forge").map(|l| FlowStep::Forge(ForgeBlock { loc: l })),
            TokenType::Focus => self.parse_flow_step_simple("focus").map(|l| FlowStep::Focus(FocusStep { expression: l.1, loc: l.0 })),
            TokenType::Associate => self.parse_associate_step(),
            TokenType::Aggregate => self.parse_aggregate_step(),
            TokenType::Explore => self.parse_explore_step(),
            TokenType::Ingest => self.parse_ingest_step(),
            TokenType::Shield => self.parse_apply_step("shield").map(|l| FlowStep::ShieldApply(ShieldApplyStep { shield_name: l.1, target: l.2, output_type: l.3, loc: l.0 })),
            TokenType::Stream => self.parse_block_step("stream").map(|l| FlowStep::Stream(StreamBlock { loc: l })),
            TokenType::Navigate => self.parse_navigate_step(),
            TokenType::Drill => self.parse_drill_step(),
            TokenType::Trail => self.parse_flow_step_simple("trail").map(|l| FlowStep::Trail(TrailStep { navigate_ref: l.1, loc: l.0 })),
            TokenType::Corroborate => self.parse_corroborate_step(),
            TokenType::Ots => self.parse_apply_step("ots").map(|l| FlowStep::OtsApply(OtsApplyStep { ots_name: l.1, target: l.2, output_type: l.3, loc: l.0 })),
            TokenType::Mandate => self.parse_apply_step("mandate").map(|l| FlowStep::MandateApply(MandateApplyStep { mandate_name: l.1, target: l.2, output_type: l.3, loc: l.0 })),
            TokenType::Compute => self.parse_apply_step("compute").map(|l| FlowStep::ComputeApply(ComputeApplyStep { compute_name: l.1, arguments: Vec::new(), output_name: l.3, loc: l.0 })),
            TokenType::Listen => self.parse_listen_step(),
            TokenType::Daemon => self.parse_flow_step_simple("daemon").map(|l| FlowStep::DaemonStep(DaemonStepNode { daemon_ref: l.1, loc: l.0 })),
            TokenType::Persist => self.parse_flow_step_simple("persist").map(|l| FlowStep::Persist(PersistStep { store_name: l.1, loc: l.0 })),
            TokenType::Retrieve => self.parse_retrieve_step(),
            TokenType::Mutate => self.parse_flow_step_simple("mutate").map(|l| FlowStep::Mutate(MutateStep { store_name: l.1, where_expr: String::new(), loc: l.0 })),
            TokenType::Purge => self.parse_flow_step_simple("purge").map(|l| FlowStep::Purge(PurgeStep { store_name: l.1, where_expr: String::new(), loc: l.0 })),
            TokenType::Transact => self.parse_block_step("transact").map(|l| FlowStep::Transact(TransactBlock { loc: l })),

            _ => Err(ParseError {
                message: format!(
                    "Unexpected token in flow body: '{}' — expected step, if, for, let, return, ...",
                    tok.value
                ),
                line: tok.line,
                column: tok.column,
            }),
        }
    }

    // ── STEP ─────────────────────────────────────────────────────

    fn parse_step(&mut self) -> Result<StepNode, ParseError> {
        let tok = self.consume(TokenType::Step)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;

        let mut persona_ref = String::new();
        if self.check(TokenType::Use) {
            self.advance();
            persona_ref = self.consume_any_ident_or_kw()?.value;
        }

        self.consume(TokenType::LBrace)?;

        let mut node = StepNode {
            name,
            persona_ref,
            given: String::new(),
            ask: String::new(),
            output_type: String::new(),
            confidence_floor: None,
            navigate_ref: String::new(),
            apply_ref: String::new(),
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let inner = self.current().clone();

            match inner.ttype {
                TokenType::Given => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.given = self.parse_expression_string()?;
                }
                TokenType::Ask => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.ask = self.consume(TokenType::StringLit)?.value;
                }
                TokenType::Output => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.output_type = self.consume(TokenType::Identifier)?.value;
                }
                TokenType::Navigate => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.navigate_ref = self.parse_dotted_identifier()?;
                }
                TokenType::Identifier if inner.value == "confidence_floor" => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.confidence_floor = Some(self.consume_number()?);
                }
                TokenType::Identifier if inner.value == "apply" => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.apply_ref = self.consume_any_ident_or_kw()?.value;
                }
                // Sub-constructs (use, probe, reason, weave, stream) → skip structurally
                TokenType::Use | TokenType::Probe | TokenType::Reason
                | TokenType::Weave | TokenType::Stream => {
                    self.skip_flow_step_structural()?;
                }
                _ => {
                    return Err(ParseError {
                        message: format!(
                            "Unexpected token in step body: '{}' — expected given, ask, use, \
                             probe, reason, weave, stream, output, confidence_floor, navigate, apply",
                            inner.value
                        ),
                        line: inner.line,
                        column: inner.column,
                    });
                }
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    /// Skip a flow-level sub-construct structurally (consume keyword + args + optional block).
    fn skip_flow_step_structural(&mut self) -> Result<(), ParseError> {
        // Consume the keyword
        self.advance();
        // Consume tokens until we hit a { or a closing }, or a known flow step keyword
        while !self.check(TokenType::LBrace) && !self.check(TokenType::RBrace)
            && !self.check(TokenType::Eof)
        {
            // Check if we hit a new step-level keyword (means this was a one-liner)
            let tt = &self.current().ttype;
            if matches!(
                tt,
                TokenType::Step | TokenType::Given | TokenType::Ask
                    | TokenType::Output | TokenType::Navigate
                    | TokenType::Use | TokenType::Probe
                    | TokenType::Reason | TokenType::Weave
                    | TokenType::Stream | TokenType::If
                    | TokenType::For | TokenType::Let | TokenType::Return
            ) {
                return Ok(());
            }
            self.advance();
        }
        // If block, skip it
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }
        Ok(())
    }

    // ── INTENT ───────────────────────────────────────────────────

    fn parse_intent(&mut self) -> Result<IntentNode, ParseError> {
        let tok = self.consume(TokenType::Intent)?;
        let loc = self.loc_of(&tok);
        let name = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::LBrace)?;

        let mut node = IntentNode {
            name,
            given: String::new(),
            ask: String::new(),
            output_type: None,
            confidence_floor: None,
            loc,
        };

        while !self.check(TokenType::RBrace) {
            let field_name = self.current().value.clone();
            self.advance();
            self.consume(TokenType::Colon)?;

            match field_name.as_str() {
                "given" => node.given = self.consume(TokenType::Identifier)?.value,
                "ask" => node.ask = self.consume(TokenType::StringLit)?.value,
                "output" => node.output_type = Some(self.parse_type_expr()?),
                "confidence_floor" => node.confidence_floor = Some(self.consume_number()?),
                _ => self.skip_value(),
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── RUN ──────────────────────────────────────────────────────

    fn parse_run(&mut self) -> Result<RunStatement, ParseError> {
        let tok = self.consume(TokenType::Run)?;
        let loc = self.loc_of(&tok);
        let flow_name = self.consume(TokenType::Identifier)?.value;

        self.consume(TokenType::LParen)?;
        let mut arguments = Vec::new();
        if !self.check(TokenType::RParen) {
            arguments = self.parse_argument_list()?;
        }
        self.consume(TokenType::RParen)?;

        let mut node = RunStatement {
            flow_name,
            arguments,
            persona: String::new(),
            context: String::new(),
            anchors: Vec::new(),
            on_failure: String::new(),
            on_failure_params: Vec::new(),
            output_to: String::new(),
            effort: String::new(),
            loc,
        };

        while self.check_run_modifier() {
            let mod_tok = self.current().clone();
            match mod_tok.ttype {
                TokenType::As => {
                    self.advance();
                    node.persona = self.consume(TokenType::Identifier)?.value;
                }
                TokenType::Within => {
                    self.advance();
                    node.context = self.consume(TokenType::Identifier)?.value;
                }
                TokenType::ConstrainedBy => {
                    self.advance();
                    node.anchors = self.parse_bracketed_identifiers()?;
                }
                TokenType::OnFailure => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.on_failure = self.consume_any_ident_or_kw()?.value;
                    // Parse optional params: (key: val, ...)
                    if self.check(TokenType::LParen) {
                        self.advance();
                        while !self.check(TokenType::RParen) && !self.check(TokenType::Eof) {
                            let key = self.consume_any_ident_or_kw()?.value;
                            self.consume(TokenType::Colon)?;
                            let val = self.consume_any_ident_or_kw()?.value;
                            node.on_failure_params.push((key, val));
                            if self.check(TokenType::Comma) {
                                self.advance();
                            }
                        }
                        if self.check(TokenType::RParen) {
                            self.advance();
                        }
                    }
                }
                TokenType::OutputTo => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.output_to = self.consume(TokenType::StringLit)?.value;
                }
                TokenType::Effort => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.effort = self.consume_any_ident_or_kw()?.value;
                }
                _ => break,
            }
        }

        Ok(node)
    }

    // ── EPISTEMIC BLOCK ──────────────────────────────────────────

    fn parse_epistemic_block(&mut self) -> Result<EpistemicBlock, ParseError> {
        let tok = self.current().clone();
        let mode = match tok.ttype {
            TokenType::Know => "know",
            TokenType::Believe => "believe",
            TokenType::Speculate => "speculate",
            TokenType::Doubt => "doubt",
            _ => unreachable!(),
        };
        self.advance();
        let loc = self.loc_of(&tok);

        self.consume(TokenType::LBrace)?;
        let mut body = Vec::new();
        while !self.check(TokenType::RBrace) {
            body.push(self.parse_declaration()?);
        }
        self.consume(TokenType::RBrace)?;

        Ok(EpistemicBlock {
            mode: mode.to_string(),
            body,
            loc,
        })
    }

    // ── IF ────────────────────────────────────────────────────────

    fn parse_if(&mut self) -> Result<ConditionalNode, ParseError> {
        let tok = self.consume(TokenType::If)?;
        let loc = self.loc_of(&tok);

        // Parse condition
        let mut parts = vec![self.consume_any_ident_or_kw()?.value];
        while self.check(TokenType::Dot) {
            self.advance();
            parts.push(self.consume_any_ident_or_kw()?.value);
        }
        let condition = parts.join(".");

        let mut comparison_op = String::new();
        let mut comparison_value = String::new();
        if self.check_comparison() {
            comparison_op = self.advance().value.clone();
            let val_tok = self.current().clone();
            if val_tok.ttype == TokenType::StringLit {
                comparison_value = val_tok.value;
                self.advance();
            } else {
                comparison_value = self.advance().value.clone();
            }
        }

        // Compound conditions (or)
        let mut conditions = Vec::new();
        let mut conjunctor = String::new();
        while self.check(TokenType::Or) {
            conjunctor = "or".to_string();
            self.advance();
            let mut cond_parts = vec![self.consume_any_ident_or_kw()?.value];
            while self.check(TokenType::Dot) {
                self.advance();
                cond_parts.push(self.consume_any_ident_or_kw()?.value);
            }
            let cond_str = cond_parts.join(".");
            let mut cond_op = String::new();
            let mut cond_val = String::new();
            if self.check_comparison() {
                cond_op = self.advance().value.clone();
                let val_tok = self.current().clone();
                if val_tok.ttype == TokenType::StringLit {
                    cond_val = val_tok.value;
                    self.advance();
                } else {
                    cond_val = self.advance().value.clone();
                }
            }
            conditions.push((cond_str, cond_op, cond_val));
        }

        let mut then_body = Vec::new();
        let mut else_body = Vec::new();

        // Arrow form or block form
        if self.check(TokenType::Arrow) {
            self.advance();
            then_body.push(self.parse_flow_step()?);
        } else if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) {
                then_body.push(self.parse_flow_step()?);
            }
            self.consume(TokenType::RBrace)?;
        }

        // Else branch
        if self.check(TokenType::Else) {
            self.advance();
            if self.check(TokenType::Arrow) {
                self.advance();
                else_body.push(self.parse_flow_step()?);
            } else if self.check(TokenType::LBrace) {
                self.advance();
                while !self.check(TokenType::RBrace) {
                    else_body.push(self.parse_flow_step()?);
                }
                self.consume(TokenType::RBrace)?;
            }
        }

        Ok(ConditionalNode {
            condition,
            comparison_op,
            comparison_value,
            then_body,
            else_body,
            conditions,
            conjunctor,
            loc,
        })
    }

    // ── FOR IN ───────────────────────────────────────────────────

    fn parse_for_in(&mut self) -> Result<ForInStatement, ParseError> {
        let tok = self.consume(TokenType::For)?;
        let loc = self.loc_of(&tok);
        let variable = self.consume(TokenType::Identifier)?.value;
        self.consume(TokenType::In)?;
        let iterable = self.parse_dotted_identifier()?;

        self.consume(TokenType::LBrace)?;
        let mut body = Vec::new();
        while !self.check(TokenType::RBrace) {
            body.push(self.parse_flow_step()?);
        }
        self.consume(TokenType::RBrace)?;

        Ok(ForInStatement {
            variable,
            iterable,
            body,
            loc,
        })
    }

    // ── LET ──────────────────────────────────────────────────────

    fn parse_let(&mut self) -> Result<LetStatement, ParseError> {
        let tok = self.consume(TokenType::Let)?;
        let loc = self.loc_of(&tok);

        // Name can be an identifier or a keyword used as binding name
        let name = self.consume_any_ident_or_kw()?.value;
        self.consume(TokenType::Assign)?;
        let value = self.parse_let_value_expr()?;

        Ok(LetStatement {
            identifier: name,
            value_expr: value,
            loc,
        })
    }

    fn parse_let_value_expr(&mut self) -> Result<String, ParseError> {
        let atom = self.parse_let_atom()?;

        // Arithmetic expression: collect as string
        if matches!(
            self.current().ttype,
            TokenType::Plus | TokenType::Minus | TokenType::Star | TokenType::Slash
        ) {
            let mut parts = vec![atom];
            while matches!(
                self.current().ttype,
                TokenType::Plus | TokenType::Minus | TokenType::Star | TokenType::Slash
            ) {
                parts.push(self.advance().value.clone());
                parts.push(self.parse_let_atom()?);
            }
            return Ok(parts.join(" "));
        }
        Ok(atom)
    }

    fn parse_let_atom(&mut self) -> Result<String, ParseError> {
        let tok = self.current().clone();

        match tok.ttype {
            TokenType::StringLit => {
                self.advance();
                Ok(tok.value)
            }
            TokenType::Integer | TokenType::Float => {
                self.advance();
                Ok(tok.value)
            }
            TokenType::Bool => {
                self.advance();
                Ok(tok.value)
            }
            TokenType::Identifier => self.parse_dotted_identifier(),
            TokenType::LBracket => self.parse_let_list_literal(),
            _ => {
                // Keywords starting a dotted path (pix.document_tree)
                if self.pos + 1 < self.tokens.len()
                    && self.tokens[self.pos + 1].ttype == TokenType::Dot
                {
                    return self.parse_dotted_identifier();
                }
                Err(ParseError {
                    message: format!(
                        "Expected value expression, found {:?}('{}')",
                        tok.ttype, tok.value
                    ),
                    line: tok.line,
                    column: tok.column,
                })
            }
        }
    }

    fn parse_let_list_literal(&mut self) -> Result<String, ParseError> {
        self.consume(TokenType::LBracket)?;
        let mut items = Vec::new();
        if !self.check(TokenType::RBracket) {
            items.push(self.parse_let_value_expr()?);
            while self.check(TokenType::Comma) {
                self.advance();
                if self.check(TokenType::RBracket) {
                    break; // trailing comma
                }
                items.push(self.parse_let_value_expr()?);
            }
        }
        self.consume(TokenType::RBracket)?;
        Ok(format!("[{}]", items.join(", ")))
    }

    // ── RETURN ───────────────────────────────────────────────────

    fn parse_return(&mut self) -> Result<ReturnStatement, ParseError> {
        let tok = self.consume(TokenType::Return)?;
        let loc = self.loc_of(&tok);
        let value = self.parse_let_value_expr()?;
        Ok(ReturnStatement {
            value_expr: value,
            loc,
        })
    }

    // ── TIER 2 FLOW STEP HELPERS ────────────────────────────────────

    /// Parse: keyword target (consumes keyword + one identifier/keyword-as-value).
    fn parse_flow_step_simple(&mut self, _kw: &str) -> Result<(Loc, String), ParseError> {
        let tok = self.current().clone();
        self.advance(); // consume keyword
        let target = if self.at_declaration_start() || self.check(TokenType::RBrace) || self.check(TokenType::Eof) {
            String::new()
        } else {
            self.consume_any_ident_or_kw()?.value.clone()
        };
        // Skip optional braced block
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }
        Ok((Loc { line: tok.line, column: tok.column }, target))
    }

    /// Parse: keyword { ... } — block-level step, skip body structurally.
    fn parse_block_step(&mut self, _kw: &str) -> Result<Loc, ParseError> {
        let tok = self.current().clone();
        self.advance();
        // Skip optional arguments before brace
        while !self.check(TokenType::LBrace) && !self.check(TokenType::RBrace) && !self.check(TokenType::Eof)
            && !self.at_declaration_start() {
            self.advance();
        }
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }
        Ok(Loc { line: tok.line, column: tok.column })
    }

    /// Parse: keyword Name on target -> output_type (apply pattern).
    fn parse_apply_step(&mut self, _kw: &str) -> Result<(Loc, String, String, String), ParseError> {
        let tok = self.current().clone();
        self.advance(); // consume keyword
        let name = self.consume_any_ident_or_kw()?.value.clone();
        let mut target = String::new();
        let mut output_type = String::new();
        // "on" target
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "on" {
                self.advance();
                target = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        // -> output_type
        if self.check(TokenType::Arrow) {
            self.advance();
            output_type = self.consume_any_ident_or_kw()?.value.clone();
        }
        // Skip optional braced block
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }
        Ok((Loc { line: tok.line, column: tok.column }, name, target, output_type))
    }

    fn parse_weave_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let mut node = WeaveStep {
            sources: Vec::new(), target: String::new(), format_type: String::new(),
            priority: Vec::new(), style: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
                let f = self.current().value.clone();
                self.advance();
                if self.check(TokenType::Colon) {
                    self.advance();
                    match f.as_str() {
                        "sources" => node.sources = self.parse_bracketed_identifiers()?,
                        "target" => node.target = self.consume_any_ident_or_kw()?.value.clone(),
                        "format" => node.format_type = self.consume_any_ident_or_kw()?.value.clone(),
                        "priority" => node.priority = self.parse_bracketed_identifiers()?,
                        "style" => node.style = self.consume_any_ident_or_kw()?.value.clone(),
                        _ => self.skip_value(),
                    }
                }
            }
            if self.check(TokenType::RBrace) { self.advance(); }
        }
        Ok(FlowStep::Weave(node))
    }

    fn parse_use_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let tool_name = self.consume_any_ident_or_kw()?.value.clone();
        let mut argument = String::new();
        // "on" argument
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "on" {
                self.advance();
                argument = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        if self.check(TokenType::LBrace) { self.skip_braced_block()?; }
        Ok(FlowStep::UseTool(UseToolStep { tool_name, argument, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_remember_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let expr = self.consume_any_ident_or_kw()?.value.clone();
        let mut mem = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "in" || next.ttype == TokenType::In {
                self.advance();
                mem = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        Ok(FlowStep::Remember(RememberStep { expression: expr, memory_target: mem, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_recall_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let query = if self.check(TokenType::StringLit) {
            self.consume(TokenType::StringLit)?.value.clone()
        } else {
            self.consume_any_ident_or_kw()?.value.clone()
        };
        let mut mem = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "from" || next.ttype == TokenType::From {
                self.advance();
                mem = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        Ok(FlowStep::Recall(RecallStep { query, memory_source: mem, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_hibernate_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let mut event = String::new();
        let mut timeout = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            event = self.consume_any_ident_or_kw()?.value.clone();
        }
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.ttype == TokenType::Duration {
                self.advance();
                timeout = next.value.clone();
            }
        }
        Ok(FlowStep::Hibernate(HibernateStep { event_name: event, timeout, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_associate_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let left = self.consume_any_ident_or_kw()?.value.clone();
        let mut right = String::new();
        let mut using = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            right = self.consume_any_ident_or_kw()?.value.clone();
        }
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "using" {
                self.advance();
                using = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        Ok(FlowStep::Associate(AssociateStep { left, right, using_field: using, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_aggregate_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let target = self.consume_any_ident_or_kw()?.value.clone();
        let mut group_by = Vec::new();
        let mut alias = String::new();
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
                let f = self.current().value.clone();
                self.advance();
                if self.check(TokenType::Colon) {
                    self.advance();
                    match f.as_str() {
                        "group_by" => group_by = self.parse_bracketed_identifiers()?,
                        "alias" | "as" => alias = self.consume_any_ident_or_kw()?.value.clone(),
                        _ => self.skip_value(),
                    }
                }
            }
            if self.check(TokenType::RBrace) { self.advance(); }
        }
        Ok(FlowStep::Aggregate(AggregateStep { target, group_by, alias, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_explore_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let target = self.consume_any_ident_or_kw()?.value.clone();
        let mut limit = None;
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            if self.current().ttype == TokenType::Integer {
                limit = self.current().value.parse::<i64>().ok();
                self.advance();
            }
        }
        Ok(FlowStep::ExploreStep(ExploreStepNode { target, limit, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_ingest_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let source = self.consume_any_ident_or_kw()?.value.clone();
        let mut target = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) {
            let next = self.current().clone();
            if next.value == "into" || next.ttype == TokenType::Into {
                self.advance();
                target = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        if self.check(TokenType::LBrace) { self.skip_braced_block()?; }
        Ok(FlowStep::Ingest(IngestStep { source, target, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_navigate_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let pix_name = self.consume_any_ident_or_kw()?.value.clone();
        let mut node = NavigateStep {
            pix_name, corpus_name: String::new(), query_expr: String::new(),
            trail_enabled: false, output_name: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
                let f = self.current().value.clone();
                self.advance();
                if self.check(TokenType::Colon) {
                    self.advance();
                    match f.as_str() {
                        "corpus" => node.corpus_name = self.consume_any_ident_or_kw()?.value.clone(),
                        "query" => node.query_expr = self.consume(TokenType::StringLit)?.value.clone(),
                        "trail" => node.trail_enabled = self.consume_any_ident_or_kw()?.value == "true",
                        "output" | "as" => node.output_name = self.consume_any_ident_or_kw()?.value.clone(),
                        _ => self.skip_value(),
                    }
                }
            }
            if self.check(TokenType::RBrace) { self.advance(); }
        }
        Ok(FlowStep::Navigate(node))
    }

    fn parse_drill_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let pix_name = self.consume_any_ident_or_kw()?.value.clone();
        let mut node = DrillStep {
            pix_name, subtree_path: String::new(), query_expr: String::new(), output_name: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
                let f = self.current().value.clone();
                self.advance();
                if self.check(TokenType::Colon) {
                    self.advance();
                    match f.as_str() {
                        "subtree" | "path" => node.subtree_path = self.consume(TokenType::StringLit)?.value.clone(),
                        "query" => node.query_expr = self.consume(TokenType::StringLit)?.value.clone(),
                        "output" | "as" => node.output_name = self.consume_any_ident_or_kw()?.value.clone(),
                        _ => self.skip_value(),
                    }
                }
            }
            if self.check(TokenType::RBrace) { self.advance(); }
        }
        Ok(FlowStep::Drill(node))
    }

    fn parse_corroborate_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let nav_ref = self.consume_any_ident_or_kw()?.value.clone();
        let mut output = String::new();
        if self.check(TokenType::Arrow) {
            self.advance();
            output = self.consume_any_ident_or_kw()?.value.clone();
        }
        Ok(FlowStep::Corroborate(CorroborateStep { navigate_ref: nav_ref, output_name: output, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_listen_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let channel = if self.check(TokenType::StringLit) {
            self.consume(TokenType::StringLit)?.value.clone()
        } else {
            self.consume_any_ident_or_kw()?.value.clone()
        };
        let mut alias = String::new();
        if !self.at_declaration_start() && !self.check(TokenType::RBrace) && !self.check(TokenType::LBrace) {
            let next = self.current().clone();
            if next.value == "as" || next.ttype == TokenType::As {
                self.advance();
                alias = self.consume_any_ident_or_kw()?.value.clone();
            }
        }
        if self.check(TokenType::LBrace) { self.skip_braced_block()?; }
        Ok(FlowStep::Listen(ListenStep { channel, event_alias: alias, loc: Loc { line: tok.line, column: tok.column } }))
    }

    fn parse_retrieve_step(&mut self) -> Result<FlowStep, ParseError> {
        let tok = self.current().clone();
        self.advance();
        let store = self.consume_any_ident_or_kw()?.value.clone();
        let mut where_expr = String::new();
        let mut alias = String::new();
        if self.check(TokenType::LBrace) {
            self.advance();
            while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
                let f = self.current().value.clone();
                self.advance();
                if self.check(TokenType::Colon) {
                    self.advance();
                    match f.as_str() {
                        "where" => where_expr = self.consume(TokenType::StringLit)?.value.clone(),
                        "as" | "alias" => alias = self.consume_any_ident_or_kw()?.value.clone(),
                        _ => self.skip_value(),
                    }
                }
            }
            if self.check(TokenType::RBrace) { self.advance(); }
        }
        Ok(FlowStep::Retrieve(RetrieveStep { store_name: store, where_expr, alias, loc: Loc { line: tok.line, column: tok.column } }))
    }

    // ── TIER 2 DECLARATIONS ────────────────────────────────────────

    fn parse_agent(&mut self) -> Result<AgentDefinition, ParseError> {
        let tok = self.consume(TokenType::Agent)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = AgentDefinition {
            name, goal: String::new(), tools: Vec::new(), memory_ref: String::new(),
            strategy: String::new(), on_stuck: String::new(), shield_ref: String::new(),
            max_iterations: None, max_tokens: None, max_time: String::new(), max_cost: None,
            loc: Loc { line: tok.line, column: tok.column },
        };
        // Skip optional parameters/return type before brace
        while !self.check(TokenType::LBrace) && !self.check(TokenType::Eof) {
            self.advance();
        }
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field = self.current().clone();
            let field_name = field.value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "goal" => node.goal = self.consume(TokenType::StringLit)?.value.clone(),
                    "tools" => node.tools = self.parse_bracketed_identifiers()?,
                    "memory" => node.memory_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    "strategy" => node.strategy = self.consume_any_ident_or_kw()?.value.clone(),
                    "on_stuck" => node.on_stuck = self.consume_any_ident_or_kw()?.value.clone(),
                    "shield" => node.shield_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    "max_iterations" => node.max_iterations = self.parse_optional_int(),
                    "max_tokens" => node.max_tokens = self.parse_optional_int(),
                    "max_time" => node.max_time = self.consume_any_ident_or_kw()?.value.clone(),
                    "max_cost" => node.max_cost = self.parse_optional_float(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_shield(&mut self) -> Result<ShieldDefinition, ParseError> {
        let tok = self.consume(TokenType::Shield)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = ShieldDefinition {
            name, scan: Vec::new(), strategy: String::new(), on_breach: String::new(),
            severity: String::new(), quarantine: String::new(), max_retries: None,
            confidence_threshold: None, allow_tools: Vec::new(), deny_tools: Vec::new(),
            sandbox: None, redact: Vec::new(), log: String::new(), deflect_message: String::new(),
            taint: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "scan" => node.scan = self.parse_bracketed_identifiers()?,
                    "strategy" => node.strategy = self.consume_any_ident_or_kw()?.value.clone(),
                    "on_breach" => node.on_breach = self.consume_any_ident_or_kw()?.value.clone(),
                    "severity" => node.severity = self.consume_any_ident_or_kw()?.value.clone(),
                    "quarantine" => node.quarantine = self.consume(TokenType::StringLit)?.value.clone(),
                    "max_retries" => node.max_retries = self.parse_optional_int(),
                    "confidence_threshold" => node.confidence_threshold = self.parse_optional_float(),
                    "allow_tools" => node.allow_tools = self.parse_bracketed_identifiers()?,
                    "deny_tools" => node.deny_tools = self.parse_bracketed_identifiers()?,
                    "sandbox" => node.sandbox = Some(self.consume_any_ident_or_kw()?.value == "true"),
                    "redact" => node.redact = self.parse_bracketed_identifiers()?,
                    "log" => node.log = self.consume_any_ident_or_kw()?.value.clone(),
                    "deflect_message" => node.deflect_message = self.consume(TokenType::StringLit)?.value.clone(),
                    "taint" => node.taint = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_pix(&mut self) -> Result<PixDefinition, ParseError> {
        let tok = self.consume(TokenType::Pix)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = PixDefinition {
            name, source: String::new(), depth: None, branching: None,
            model: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "source" => node.source = self.consume(TokenType::StringLit)?.value.clone(),
                    "depth" => node.depth = self.parse_optional_int(),
                    "branching" => node.branching = self.parse_optional_int(),
                    "model" => node.model = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_psyche(&mut self) -> Result<PsycheDefinition, ParseError> {
        let tok = self.consume(TokenType::Psyche)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = PsycheDefinition {
            name, dimensions: Vec::new(), manifold_noise: None, manifold_momentum: None,
            safety_constraints: Vec::new(), quantum_enabled: None, inference_mode: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "dimensions" => node.dimensions = self.parse_bracketed_identifiers()?,
                    "manifold_noise" => node.manifold_noise = self.parse_optional_float(),
                    "manifold_momentum" => node.manifold_momentum = self.parse_optional_float(),
                    "safety_constraints" => node.safety_constraints = self.parse_bracketed_identifiers()?,
                    "quantum_enabled" => node.quantum_enabled = Some(self.consume_any_ident_or_kw()?.value == "true"),
                    "inference_mode" => node.inference_mode = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_corpus(&mut self) -> Result<CorpusDefinition, ParseError> {
        let tok = self.consume(TokenType::Corpus)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = CorpusDefinition {
            name, documents: Vec::new(), mcp_server: String::new(), mcp_resource_uri: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        // corpus Name from mcp("server", "uri") — short form
        if self.check(TokenType::From) {
            self.advance();
            self.consume(TokenType::Mcp)?;
            self.consume(TokenType::LParen)?;
            node.mcp_server = self.consume(TokenType::StringLit)?.value.clone();
            self.consume(TokenType::Comma)?;
            node.mcp_resource_uri = self.consume(TokenType::StringLit)?.value.clone();
            self.consume(TokenType::RParen)?;
            return Ok(node);
        }
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "documents" => node.documents = self.parse_bracketed_identifiers()?,
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_dataspace(&mut self) -> Result<DataspaceDefinition, ParseError> {
        let tok = self.consume(TokenType::Dataspace)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let node = DataspaceDefinition {
            name,
            loc: Loc { line: tok.line, column: tok.column },
        };
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }
        Ok(node)
    }

    fn parse_ots(&mut self) -> Result<OtsDefinition, ParseError> {
        let tok = self.consume(TokenType::Ots)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = OtsDefinition {
            name, teleology: String::new(), homotopy_search: String::new(),
            loss_function: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        // Skip optional type params <In, Out>
        if self.check(TokenType::Lt) {
            while !self.check(TokenType::Gt) && !self.check(TokenType::Eof) {
                self.advance();
            }
            if self.check(TokenType::Gt) { self.advance(); }
        }
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "teleology" => node.teleology = self.consume(TokenType::StringLit)?.value.clone(),
                    "homotopy_search" => node.homotopy_search = self.consume_any_ident_or_kw()?.value.clone(),
                    "loss_function" => node.loss_function = self.consume(TokenType::StringLit)?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_mandate(&mut self) -> Result<MandateDefinition, ParseError> {
        let tok = self.consume(TokenType::Mandate)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = MandateDefinition {
            name, constraint: String::new(), kp: None, ki: None, kd: None,
            tolerance: None, max_steps: None, on_violation: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "constraint" => node.constraint = self.consume(TokenType::StringLit)?.value.clone(),
                    "kp" | "Kp" => node.kp = self.parse_optional_float(),
                    "ki" | "Ki" => node.ki = self.parse_optional_float(),
                    "kd" | "Kd" => node.kd = self.parse_optional_float(),
                    "tolerance" => node.tolerance = self.parse_optional_float(),
                    "max_steps" => node.max_steps = self.parse_optional_int(),
                    "on_violation" => node.on_violation = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_compute(&mut self) -> Result<ComputeDefinition, ParseError> {
        let tok = self.consume(TokenType::Compute)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = ComputeDefinition {
            name, shield_ref: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        // Skip optional parameters/return type before brace
        while !self.check(TokenType::LBrace) && !self.check(TokenType::Eof) {
            self.advance();
        }
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "shield" => node.shield_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_daemon(&mut self) -> Result<DaemonDefinition, ParseError> {
        let tok = self.consume(TokenType::Daemon)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = DaemonDefinition {
            name, goal: String::new(), tools: Vec::new(), memory_ref: String::new(),
            strategy: String::new(), on_stuck: String::new(), shield_ref: String::new(),
            max_tokens: None, max_time: String::new(), max_cost: None,
            loc: Loc { line: tok.line, column: tok.column },
        };
        // Skip optional parameters/return type before brace
        while !self.check(TokenType::LBrace) && !self.check(TokenType::Eof) {
            self.advance();
        }
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field = self.current().clone();
            let field_name = field.value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "goal" => node.goal = self.consume(TokenType::StringLit)?.value.clone(),
                    "tools" => node.tools = self.parse_bracketed_identifiers()?,
                    "memory" => node.memory_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    "strategy" => node.strategy = self.consume_any_ident_or_kw()?.value.clone(),
                    "on_stuck" => node.on_stuck = self.consume_any_ident_or_kw()?.value.clone(),
                    "shield" => node.shield_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    "max_tokens" => node.max_tokens = self.parse_optional_int(),
                    "max_time" => node.max_time = self.consume_any_ident_or_kw()?.value.clone(),
                    "max_cost" => node.max_cost = self.parse_optional_float(),
                    _ => self.skip_value(),
                }
            } else if field.ttype == TokenType::Listen {
                // listen blocks — skip structurally for now
                if self.check(TokenType::LBrace) {
                    self.skip_braced_block()?;
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_axonstore(&mut self) -> Result<AxonStoreDefinition, ParseError> {
        let tok = self.consume(TokenType::AxonStore)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = AxonStoreDefinition {
            name, backend: String::new(), connection: String::new(),
            confidence_floor: None, isolation: String::new(), on_breach: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field = self.current().clone();
            let field_name = field.value.clone();
            // schema block — skip structurally
            if field.ttype == TokenType::Schema {
                self.advance();
                if self.check(TokenType::LBrace) {
                    self.skip_braced_block()?;
                }
                continue;
            }
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "backend" => node.backend = self.consume_any_ident_or_kw()?.value.clone(),
                    "connection" => node.connection = self.consume(TokenType::StringLit)?.value.clone(),
                    "confidence_floor" => node.confidence_floor = self.parse_optional_float(),
                    "isolation" => node.isolation = self.consume_any_ident_or_kw()?.value.clone(),
                    "on_breach" => node.on_breach = self.consume_any_ident_or_kw()?.value.clone(),
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_axonendpoint(&mut self) -> Result<AxonEndpointDefinition, ParseError> {
        let tok = self.consume(TokenType::AxonEndpoint)?;
        let name = self.consume(TokenType::Identifier)?.value;
        let mut node = AxonEndpointDefinition {
            name, method: String::new(), path: String::new(), body_type: String::new(),
            execute_flow: String::new(), output_type: String::new(), shield_ref: String::new(),
            retries: None, timeout: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };
        self.consume(TokenType::LBrace)?;
        while !self.check(TokenType::RBrace) && !self.check(TokenType::Eof) {
            let field_name = self.current().value.clone();
            self.advance();
            if self.check(TokenType::Colon) {
                self.advance();
                match field_name.as_str() {
                    "method" => {
                        let v = self.consume_any_ident_or_kw()?.value;
                        node.method = v.to_uppercase();
                    }
                    "path" => node.path = self.consume(TokenType::StringLit)?.value.clone(),
                    "body" => node.body_type = self.consume_any_ident_or_kw()?.value.clone(),
                    "execute" => node.execute_flow = self.consume_any_ident_or_kw()?.value.clone(),
                    "output" => node.output_type = self.consume_any_ident_or_kw()?.value.clone(),
                    "shield" => node.shield_ref = self.consume_any_ident_or_kw()?.value.clone(),
                    "retries" => node.retries = self.parse_optional_int(),
                    "timeout" => {
                        let t = self.current().clone();
                        self.advance();
                        node.timeout = t.value.clone();
                    }
                    _ => self.skip_value(),
                }
            } else if self.check(TokenType::LBrace) {
                self.skip_braced_block()?;
            }
        }
        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    // ── Numeric helpers for Tier 2 field parsing ────────────────────

    fn parse_optional_int(&mut self) -> Option<i64> {
        let tok = self.current().clone();
        match tok.ttype {
            TokenType::Integer => {
                self.advance();
                tok.value.parse::<i64>().ok()
            }
            _ => {
                self.advance();
                None
            }
        }
    }

    fn parse_optional_float(&mut self) -> Option<f64> {
        let tok = self.current().clone();
        match tok.ttype {
            TokenType::Float | TokenType::Integer => {
                self.advance();
                tok.value.parse::<f64>().ok()
            }
            _ => {
                self.advance();
                None
            }
        }
    }

    // ── LAMBDA DATA (ΛD) ──────────────────────────────────────────

    fn parse_lambda_data(&mut self) -> Result<LambdaDataDefinition, ParseError> {
        let tok = self.consume(TokenType::Lambda)?;
        let name = self.consume(TokenType::Identifier)?;
        self.consume(TokenType::LBrace)?;

        let mut node = LambdaDataDefinition {
            name: name.value.clone(),
            ontology: String::new(),
            certainty: 1.0,
            temporal_frame_start: String::new(),
            temporal_frame_end: String::new(),
            provenance: String::new(),
            derivation: String::new(),
            loc: Loc { line: tok.line, column: tok.column },
        };

        while !self.check(TokenType::RBrace) {
            let field = self.current().clone();
            match field.ttype {
                TokenType::Ontology => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.ontology = self.consume(TokenType::StringLit)?.value.clone();
                }
                TokenType::Certainty => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    let val = self.current().clone();
                    match val.ttype {
                        TokenType::Float => {
                            self.advance();
                            node.certainty = val.value.parse::<f64>().unwrap_or(1.0);
                        }
                        TokenType::Integer => {
                            self.advance();
                            node.certainty = val.value.parse::<f64>().unwrap_or(1.0);
                        }
                        _ => {
                            return Err(ParseError {
                                message: format!("Expected number for certainty, got '{}'", val.value),
                                line: val.line,
                                column: val.column,
                            });
                        }
                    }
                }
                TokenType::TemporalFrame => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.temporal_frame_start = self.consume(TokenType::StringLit)?.value.clone();
                    // Optional second string for end frame
                    if self.check(TokenType::StringLit) {
                        node.temporal_frame_end = self.consume(TokenType::StringLit)?.value.clone();
                    }
                }
                TokenType::Provenance => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    node.provenance = self.consume(TokenType::StringLit)?.value.clone();
                }
                TokenType::Derivation => {
                    self.advance();
                    self.consume(TokenType::Colon)?;
                    let d = self.current().clone();
                    self.advance();
                    node.derivation = d.value.clone();
                }
                _ => {
                    // Skip unknown fields gracefully
                    self.advance();
                    if self.check(TokenType::Colon) {
                        self.advance();
                        self.skip_value();
                    }
                }
            }
        }

        self.consume(TokenType::RBrace)?;
        Ok(node)
    }

    fn parse_lambda_data_apply(&mut self) -> Result<LambdaDataApplyNode, ParseError> {
        let tok = self.consume(TokenType::Lambda)?;
        let lambda_name = self.consume(TokenType::Identifier)?;

        // Expect "on" keyword (parsed as identifier since it's not reserved)
        let on_tok = self.current().clone();
        self.advance();
        if on_tok.value != "on" {
            return Err(ParseError {
                message: format!(
                    "Expected 'on' after lambda data name in flow step, got '{}'",
                    on_tok.value
                ),
                line: on_tok.line,
                column: on_tok.column,
            });
        }

        let target = self.current().clone();
        self.advance();

        let mut output_type = String::new();
        if self.check(TokenType::Arrow) {
            self.advance();
            output_type = self.consume(TokenType::Identifier)?.value.clone();
        }

        Ok(LambdaDataApplyNode {
            lambda_data_name: lambda_name.value.clone(),
            target: target.value.clone(),
            output_type,
            loc: Loc { line: tok.line, column: tok.column },
        })
    }

    // ── GENERIC (Tier 2+) ────────────────────────────────────────

    fn parse_generic_declaration(&mut self) -> Result<Declaration, ParseError> {
        let kw_tok = self.current().clone();
        self.advance(); // consume keyword

        // Try to consume a name (identifier or keyword-as-name)
        let name = if self.current().ttype == TokenType::Identifier {
            let n = self.current().value.clone();
            self.advance();
            n
        } else if !self.check(TokenType::LBrace)
            && !self.check(TokenType::LParen)
            && !self.check(TokenType::Eof)
            && self.current().value.chars().all(|c| c.is_alphanumeric() || c == '_')
        {
            let n = self.current().value.clone();
            self.advance();
            n
        } else {
            String::new()
        };

        // Skip optional parens: (...)
        if self.check(TokenType::LParen) {
            self.advance();
            let mut depth = 1u32;
            while depth > 0 && !self.check(TokenType::Eof) {
                if self.check(TokenType::LParen) {
                    depth += 1;
                } else if self.check(TokenType::RParen) {
                    depth -= 1;
                }
                self.advance();
            }
        }

        // Skip tokens until LBrace or next declaration
        while !self.check(TokenType::LBrace) && !self.at_declaration_start() {
            if self.check(TokenType::Eof) {
                break;
            }
            self.advance();
        }

        // Skip braced block if present
        if self.check(TokenType::LBrace) {
            self.skip_braced_block()?;
        }

        Ok(Declaration::Generic(GenericDeclaration {
            keyword: kw_tok.value,
            name,
            loc: Loc {
                line: kw_tok.line,
                column: kw_tok.column,
            },
        }))
    }

}
