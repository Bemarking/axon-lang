//! §Fase 35.b (v1.30.0) — Parameterized `where`-expression filter
//! compiler for the `axonstore` cognitive data plane.
//!
//! # D4 — SQL-injection-proof by construction
//!
//! A `retrieve from S where "<expr>"` step carries `where_expr` as a
//! raw string. This module compiles that string into a parameterized
//! Postgres `WHERE` clause: the SQL **structure** (column identifiers,
//! operators, connectors) and the user **values** are separated, and
//! every value renders as a `$N` bind placeholder. **No code path in
//! this module interpolates a user value into SQL text** — that is the
//! load-bearing D4 invariant, fuzzed in 35.k.
//!
//! ```text
//!   where "id = 1 AND name = 'Alice'"
//!     →  ("\"id\" = $1 AND \"name\" = $2", [Integer(1), Text("Alice")])
//! ```
//!
//! # Grammar (closed)
//!
//! ```text
//!   filter     := condition (connector condition)*
//!   condition  := column operator value
//!   column     := [A-Za-z_][A-Za-z0-9_]*           (ASCII; ≤ 63 bytes)
//!   operator   := '=' | '==' | '!=' | '<>' | '>' | '>=' | '<' | '<=' | LIKE
//!   connector  := AND | OR                          (case-insensitive)
//!   value      := string-literal | number | TRUE | FALSE | NULL
//! ```
//!
//! Operator precedence is **SQL's native precedence** (`AND` binds
//! tighter than `OR`) — the flat condition list renders verbatim and
//! Postgres applies precedence. Parenthesized grouping is a documented
//! future extension; v1.30.0's `where` grammar is the flat form.
//!
//! # Why this is stricter than the Python reference
//!
//! The frozen Python `filter_parser.py` has a real defect: a trailing
//! connector (`"id = 1 AND"`) parses to one condition + one connector
//! and renders the broken SQL `"id" = $1 AND`. This compiler rejects a
//! dangling connector as a typed [`FilterError`]. It is **total**:
//! every input either compiles to a parameterized clause or returns a
//! named error — never a panic, never broken SQL.

use std::fmt;

/// Postgres `NAMEDATALEN - 1` — the maximum identifier byte length.
/// A longer column name cannot name a real Postgres column, so it is
/// rejected here with a clear error rather than deferred to a cryptic
/// runtime SQL failure.
const MAX_COLUMN_LEN: usize = 63;

/// Upper bound on conditions in a single `where` expression. A real
/// agent store query never approaches this; the cap is a denial-of-
/// service guard (an adversarial `a=1 AND a=1 AND …` cannot allocate
/// an unbounded parameter vector) and stays far inside Postgres' own
/// 65535-bind-parameter ceiling.
const MAX_CONDITIONS: usize = 256;

// ════════════════════════════════════════════════════════════════════
//  Value catalog
// ════════════════════════════════════════════════════════════════════

/// A typed filter value — the closed catalog of things that can appear
/// in value position. Every non-[`SqlValue::Null`] value is rendered as
/// a `$N` bind placeholder; `Null` is folded into `IS NULL` /
/// `IS NOT NULL` and so never occupies a parameter slot.
#[derive(Debug, Clone, PartialEq)]
pub enum SqlValue {
    /// A string literal (quote characters stripped, escapes resolved).
    Text(String),
    /// An integer literal that fits in `i64`.
    Integer(i64),
    /// A finite floating-point literal.
    Float(f64),
    /// A boolean literal (`true` / `false`, case-insensitive).
    Boolean(bool),
    /// The SQL `NULL` literal.
    Null,
}

impl SqlValue {
    /// A human-readable type name, used in error messages.
    pub fn type_name(&self) -> &'static str {
        match self {
            SqlValue::Text(_) => "text",
            SqlValue::Integer(_) => "integer",
            SqlValue::Float(_) => "float",
            SqlValue::Boolean(_) => "boolean",
            SqlValue::Null => "null",
        }
    }
}

// ════════════════════════════════════════════════════════════════════
//  Operator catalog (closed, whitelisted)
// ════════════════════════════════════════════════════════════════════

/// A comparison operator. The whitelist IS the catalog — there is no
/// path by which an un-listed operator reaches the rendered SQL.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Operator {
    /// `=` / `==`
    Eq,
    /// `!=` / `<>`
    Ne,
    /// `>`
    Gt,
    /// `>=`
    Ge,
    /// `<`
    Lt,
    /// `<=`
    Le,
    /// `LIKE` (case-insensitive surface spelling)
    Like,
}

impl Operator {
    /// The canonical SQL spelling of this operator.
    pub fn as_sql(self) -> &'static str {
        match self {
            Operator::Eq => "=",
            Operator::Ne => "!=",
            Operator::Gt => ">",
            Operator::Ge => ">=",
            Operator::Lt => "<",
            Operator::Le => "<=",
            Operator::Like => "LIKE",
        }
    }

    /// Resolve a comparison *symbol* (not `LIKE`) to its operator.
    /// `==` normalizes to `=`; `<>` normalizes to `!=`.
    fn from_symbol(sym: &str) -> Option<Operator> {
        Some(match sym {
            "=" | "==" => Operator::Eq,
            "!=" | "<>" => Operator::Ne,
            ">" => Operator::Gt,
            ">=" => Operator::Ge,
            "<" => Operator::Lt,
            "<=" => Operator::Le,
            _ => return None,
        })
    }

    /// `true` iff this operator is meaningful against `NULL`. Only
    /// equality (`=` → `IS NULL`) and inequality (`!=` → `IS NOT NULL`)
    /// are; an ordering or `LIKE` comparison with `NULL` is always
    /// `UNKNOWN` in SQL and is therefore a user error, rejected here.
    fn accepts_null(self) -> bool {
        matches!(self, Operator::Eq | Operator::Ne)
    }
}

impl fmt::Display for Operator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_sql())
    }
}

// ════════════════════════════════════════════════════════════════════
//  Connector catalog (closed)
// ════════════════════════════════════════════════════════════════════

/// A boolean connector joining two adjacent conditions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Connector {
    /// `AND`
    And,
    /// `OR`
    Or,
}

impl Connector {
    /// The canonical SQL spelling of this connector.
    pub fn as_sql(self) -> &'static str {
        match self {
            Connector::And => "AND",
            Connector::Or => "OR",
        }
    }
}

impl fmt::Display for Connector {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_sql())
    }
}

// ════════════════════════════════════════════════════════════════════
//  Filter AST
// ════════════════════════════════════════════════════════════════════

/// A single `column op value` predicate.
#[derive(Debug, Clone, PartialEq)]
pub struct FilterCondition {
    /// The column identifier (validated `[A-Za-z_]\w*`, ≤ 63 bytes).
    pub column: String,
    /// The comparison operator.
    pub op: Operator,
    /// The typed right-hand value.
    pub value: SqlValue,
}

/// A parsed `where` expression: a flat list of conditions joined by
/// connectors. The structural invariant — enforced by [`parse_filter`]
/// — is `connectors.len() + 1 == conditions.len()` whenever
/// `conditions` is non-empty (and both empty for an empty expression).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Filter {
    /// The conditions, in source order.
    pub conditions: Vec<FilterCondition>,
    /// `connectors[i]` joins `conditions[i]` and `conditions[i + 1]`.
    pub connectors: Vec<Connector>,
}

impl Filter {
    /// `true` iff this filter carries no conditions (an empty `where`).
    pub fn is_empty(&self) -> bool {
        self.conditions.is_empty()
    }
}

// ════════════════════════════════════════════════════════════════════
//  Error catalog (typed, total — D7 honest failure surface)
// ════════════════════════════════════════════════════════════════════

/// Every way a `where` expression can fail to compile. The compiler is
/// total: it returns one of these or a clause — never a panic.
#[derive(Debug, Clone, PartialEq)]
pub enum FilterError {
    /// A character outside the grammar's alphabet (e.g. `;`, `(`, `%`).
    UnexpectedChar { ch: char, pos: usize },
    /// A string literal opened but never closed.
    UnterminatedString { pos: usize },
    /// A numeric token that is neither a valid `i64` nor a finite `f64`.
    InvalidNumber { token: String },
    /// A column identifier was expected but a non-identifier was found.
    ExpectedColumn { found: String },
    /// A column identifier exceeds Postgres' 63-byte limit.
    ColumnTooLong { column: String, len: usize },
    /// An operator was expected after a column but something else was found.
    ExpectedOperator { column: String, found: String },
    /// The expression ended where an operator was expected.
    MissingOperator { column: String },
    /// A value was expected after an operator but a symbol was found.
    ExpectedValue { found: String },
    /// The expression ended where a value was expected.
    MissingValue { column: String },
    /// A bare word in value position — string values must be quoted.
    UnquotedValue { token: String },
    /// Two conditions were adjacent with no `AND`/`OR` between them.
    ExpectedConnector { found: String },
    /// A trailing `AND`/`OR` with no following condition (the defect
    /// the frozen Python reference silently mis-renders).
    DanglingConnector { connector: Connector },
    /// `NULL` compared with an operator other than `=` / `!=`.
    NullWithNonEqualityOp { column: String, op: Operator },
    /// `LIKE` applied to a non-text value.
    LikeRequiresText { column: String, found: &'static str },
    /// More than [`MAX_CONDITIONS`] conditions in one expression.
    TooManyConditions { limit: usize },
}

impl fmt::Display for FilterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FilterError::UnexpectedChar { ch, pos } => write!(
                f,
                "unexpected character {ch:?} at position {pos} — the \
                 where-grammar alphabet is identifiers, comparison \
                 symbols, quoted strings and numbers"
            ),
            FilterError::UnterminatedString { pos } => {
                write!(f, "unterminated string literal opened at position {pos}")
            }
            FilterError::InvalidNumber { token } => write!(
                f,
                "invalid numeric literal `{token}` — expected an integer \
                 or a finite decimal"
            ),
            FilterError::ExpectedColumn { found } => write!(
                f,
                "expected a column name, found `{found}` — a condition \
                 is `column op value`"
            ),
            FilterError::ColumnTooLong { column, len } => write!(
                f,
                "column name `{column}` is {len} bytes — exceeds the \
                 Postgres {MAX_COLUMN_LEN}-byte identifier limit"
            ),
            FilterError::ExpectedOperator { column, found } => write!(
                f,
                "expected a comparison operator after column `{column}`, \
                 found `{found}`"
            ),
            FilterError::MissingOperator { column } => write!(
                f,
                "expected a comparison operator after column `{column}`, \
                 found end of expression"
            ),
            FilterError::ExpectedValue { found } => write!(
                f,
                "expected a value, found `{found}`"
            ),
            FilterError::MissingValue { column } => write!(
                f,
                "expected a value for column `{column}`, found end of \
                 expression"
            ),
            FilterError::UnquotedValue { token } => write!(
                f,
                "unquoted value `{token}` — string values must be quoted \
                 (`'{token}'`); only numbers and `true`/`false`/`null` \
                 are bare"
            ),
            FilterError::ExpectedConnector { found } => write!(
                f,
                "expected `AND` or `OR` between conditions, found `{found}`"
            ),
            FilterError::DanglingConnector { connector } => write!(
                f,
                "expression ends with a dangling `{connector}` — a \
                 connector must be followed by another condition"
            ),
            FilterError::NullWithNonEqualityOp { column, op } => write!(
                f,
                "`null` compared with `{op}` on column `{column}` — \
                 `null` is only valid with `=` (renders `IS NULL`) or \
                 `!=` (renders `IS NOT NULL`)"
            ),
            FilterError::LikeRequiresText { column, found } => write!(
                f,
                "`LIKE` on column `{column}` requires a text value, \
                 found {found}"
            ),
            FilterError::TooManyConditions { limit } => write!(
                f,
                "where expression exceeds the {limit}-condition limit"
            ),
        }
    }
}

impl std::error::Error for FilterError {}

// ════════════════════════════════════════════════════════════════════
//  Tokenizer
// ════════════════════════════════════════════════════════════════════

/// A lexical token. The tokenizer is purely lexical — keyword meaning
/// (`AND`/`OR`/`LIKE`/`TRUE`/`FALSE`/`NULL`) is assigned positionally
/// by the parser.
#[derive(Debug, Clone, PartialEq)]
enum Token {
    /// An ASCII identifier-shaped word: a column or a keyword.
    Word(String),
    /// A comparison symbol: one of `= == != <> > >= < <=`.
    Symbol(String),
    /// A string literal's content (quotes stripped, escapes resolved).
    Str(String),
    /// A raw numeric token (sign + digits + dots), parsed later.
    Num(String),
}

/// A short human description of a token, for error messages.
fn describe(tok: &Token) -> String {
    match tok {
        Token::Word(w) => w.clone(),
        Token::Symbol(s) => s.clone(),
        Token::Str(s) => format!("'{s}'"),
        Token::Num(n) => n.clone(),
    }
}

/// Lex a `where` expression into tokens. Total: every input either
/// yields a token vector or a [`FilterError`].
fn tokenize(expr: &str) -> Result<Vec<Token>, FilterError> {
    let chars: Vec<char> = expr.chars().collect();
    let n = chars.len();
    let mut tokens: Vec<Token> = Vec::new();
    let mut i = 0;

    while i < n {
        let c = chars[i];

        // — whitespace —
        if c.is_whitespace() {
            i += 1;
            continue;
        }

        // — string literal (single- or double-quoted) —
        if c == '\'' || c == '"' {
            let quote = c;
            let mut buf = String::new();
            let mut j = i + 1;
            let mut closed = false;
            while j < n {
                let cj = chars[j];
                if cj == '\\' {
                    // An escape takes the NEXT char literally. A
                    // trailing backslash leaves the string unclosed.
                    if j + 1 < n {
                        buf.push(chars[j + 1]);
                        j += 2;
                        continue;
                    }
                    break;
                }
                if cj == quote {
                    closed = true;
                    j += 1;
                    break;
                }
                buf.push(cj);
                j += 1;
            }
            if !closed {
                return Err(FilterError::UnterminatedString { pos: i });
            }
            tokens.push(Token::Str(buf));
            i = j;
            continue;
        }

        // — comparison symbols —
        if c == '=' || c == '!' || c == '<' || c == '>' {
            if i + 1 < n {
                let two = match (c, chars[i + 1]) {
                    ('=', '=') => Some("=="),
                    ('!', '=') => Some("!="),
                    ('<', '=') => Some("<="),
                    ('>', '=') => Some(">="),
                    ('<', '>') => Some("<>"),
                    _ => None,
                };
                if let Some(sym) = two {
                    tokens.push(Token::Symbol(sym.to_string()));
                    i += 2;
                    continue;
                }
            }
            // `!` is only ever valid as the start of `!=`.
            if c == '!' {
                return Err(FilterError::UnexpectedChar { ch: '!', pos: i });
            }
            tokens.push(Token::Symbol(c.to_string()));
            i += 1;
            continue;
        }

        // — numeric literal (optional leading `-`, digits, dots) —
        if c.is_ascii_digit()
            || (c == '-' && i + 1 < n && chars[i + 1].is_ascii_digit())
        {
            let start = i;
            let mut j = if c == '-' { i + 1 } else { i };
            while j < n && (chars[j].is_ascii_digit() || chars[j] == '.') {
                j += 1;
            }
            tokens.push(Token::Num(chars[start..j].iter().collect()));
            i = j;
            continue;
        }

        // — identifier / keyword word —
        if c.is_ascii_alphabetic() || c == '_' {
            let start = i;
            let mut j = i;
            while j < n && (chars[j].is_ascii_alphanumeric() || chars[j] == '_')
            {
                j += 1;
            }
            tokens.push(Token::Word(chars[start..j].iter().collect()));
            i = j;
            continue;
        }

        return Err(FilterError::UnexpectedChar { ch: c, pos: i });
    }

    Ok(tokens)
}

/// Parse a numeric token into a typed [`SqlValue`]. Prefers `i64`;
/// falls back to a finite `f64`; otherwise a typed error.
fn parse_number(raw: &str) -> Result<SqlValue, FilterError> {
    if let Ok(n) = raw.parse::<i64>() {
        return Ok(SqlValue::Integer(n));
    }
    if let Ok(x) = raw.parse::<f64>() {
        if x.is_finite() {
            return Ok(SqlValue::Float(x));
        }
    }
    Err(FilterError::InvalidNumber { token: raw.to_string() })
}

/// Resolve a token in *value position* to a typed [`SqlValue`].
fn parse_value(tok: &Token) -> Result<SqlValue, FilterError> {
    match tok {
        Token::Str(s) => Ok(SqlValue::Text(s.clone())),
        Token::Num(raw) => parse_number(raw),
        Token::Word(w) => match w.to_ascii_lowercase().as_str() {
            "true" => Ok(SqlValue::Boolean(true)),
            "false" => Ok(SqlValue::Boolean(false)),
            "null" => Ok(SqlValue::Null),
            _ => Err(FilterError::UnquotedValue { token: w.clone() }),
        },
        Token::Symbol(s) => Err(FilterError::ExpectedValue { found: s.clone() }),
    }
}

// ════════════════════════════════════════════════════════════════════
//  Parser
// ════════════════════════════════════════════════════════════════════

/// Parse a `where` expression into a [`Filter`] AST. An empty (or
/// whitespace-only) expression yields an empty filter. Total: every
/// input yields a `Filter` or a [`FilterError`].
pub fn parse_filter(expr: &str) -> Result<Filter, FilterError> {
    let tokens = tokenize(expr)?;
    let mut filter = Filter::default();
    let mut i = 0;
    let n = tokens.len();

    while i < n {
        // — column —
        let column = match &tokens[i] {
            Token::Word(w) => w.clone(),
            other => {
                return Err(FilterError::ExpectedColumn {
                    found: describe(other),
                })
            }
        };
        if column.len() > MAX_COLUMN_LEN {
            return Err(FilterError::ColumnTooLong {
                len: column.len(),
                column,
            });
        }
        i += 1;

        // — operator —
        if i >= n {
            return Err(FilterError::MissingOperator { column });
        }
        let op = match &tokens[i] {
            Token::Symbol(sym) => Operator::from_symbol(sym).ok_or_else(|| {
                FilterError::ExpectedOperator {
                    column: column.clone(),
                    found: sym.clone(),
                }
            })?,
            Token::Word(w) if w.eq_ignore_ascii_case("like") => Operator::Like,
            other => {
                return Err(FilterError::ExpectedOperator {
                    column,
                    found: describe(other),
                })
            }
        };
        i += 1;

        // — value —
        if i >= n {
            return Err(FilterError::MissingValue { column });
        }
        let value = parse_value(&tokens[i])?;
        i += 1;

        // — semantic checks —
        if matches!(value, SqlValue::Null) && !op.accepts_null() {
            return Err(FilterError::NullWithNonEqualityOp { column, op });
        }
        if op == Operator::Like && !matches!(value, SqlValue::Text(_)) {
            return Err(FilterError::LikeRequiresText {
                column,
                found: value.type_name(),
            });
        }

        filter.conditions.push(FilterCondition { column, op, value });
        if filter.conditions.len() > MAX_CONDITIONS {
            return Err(FilterError::TooManyConditions {
                limit: MAX_CONDITIONS,
            });
        }

        // — connector (only between conditions) —
        if i < n {
            let connector = match &tokens[i] {
                Token::Word(w) if w.eq_ignore_ascii_case("and") => Connector::And,
                Token::Word(w) if w.eq_ignore_ascii_case("or") => Connector::Or,
                other => {
                    return Err(FilterError::ExpectedConnector {
                        found: describe(other),
                    })
                }
            };
            i += 1;
            filter.connectors.push(connector);
            // A connector MUST be followed by another condition.
            if i >= n {
                return Err(FilterError::DanglingConnector { connector });
            }
        }
    }

    Ok(filter)
}

// ════════════════════════════════════════════════════════════════════
//  Renderer — parameterized Postgres WHERE
// ════════════════════════════════════════════════════════════════════

/// Compile a `where` expression into a parameterized Postgres `WHERE`
/// clause body and its ordered bind parameters.
///
/// - An empty / whitespace-only expression yields `("TRUE", [])`.
/// - `param_offset` shifts the `$N` numbering: pass the count of bind
///   parameters already consumed by an enclosing statement (e.g. an
///   `UPDATE … SET` list) so the `WHERE` placeholders continue the
///   sequence. `param_offset == 0` yields `$1, $2, …`.
/// - `NULL` values fold into `IS NULL` / `IS NOT NULL` and consume no
///   placeholder; the returned parameter vector therefore never
///   contains [`SqlValue::Null`].
///
/// D4: the column identifier is double-quoted (it is validated against
/// `[A-Za-z_]\w*`, so it cannot carry a quote) and every value is a
/// `$N` placeholder — no user value is ever interpolated into the SQL.
pub fn build_pg_where(
    expr: &str,
    param_offset: usize,
) -> Result<(String, Vec<SqlValue>), FilterError> {
    if expr.trim().is_empty() {
        return Ok(("TRUE".to_string(), Vec::new()));
    }

    let filter = parse_filter(expr)?;
    if filter.is_empty() {
        return Ok(("TRUE".to_string(), Vec::new()));
    }

    let mut clause = String::new();
    let mut params: Vec<SqlValue> = Vec::new();
    let mut idx = param_offset + 1;

    for (i, cond) in filter.conditions.iter().enumerate() {
        if i > 0 {
            // The parser guarantees `connectors.len() + 1 ==
            // conditions.len()`, so this index is always in bounds.
            clause.push(' ');
            clause.push_str(filter.connectors[i - 1].as_sql());
            clause.push(' ');
        }
        match &cond.value {
            SqlValue::Null => {
                // The parser guarantees `op ∈ {Eq, Ne}` for a `NULL`
                // value; the `_` arm is defensive totality only.
                let tail = match cond.op {
                    Operator::Ne => "IS NOT NULL",
                    _ => "IS NULL",
                };
                clause.push_str(&format!("\"{}\" {tail}", cond.column));
            }
            bound => {
                clause.push_str(&format!(
                    "\"{}\" {} ${idx}",
                    cond.column,
                    cond.op.as_sql()
                ));
                params.push(bound.clone());
                idx += 1;
            }
        }
    }

    Ok((clause, params))
}

// ════════════════════════════════════════════════════════════════════
//  Unit tests
// ════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    fn ok(expr: &str) -> (String, Vec<SqlValue>) {
        build_pg_where(expr, 0).expect("expected the filter to compile")
    }

    fn err(expr: &str) -> FilterError {
        build_pg_where(expr, 0).expect_err("expected a compile error")
    }

    // ── Empty ────────────────────────────────────────────────────────

    #[test]
    fn empty_expression_renders_true() {
        assert_eq!(ok(""), ("TRUE".to_string(), vec![]));
    }

    #[test]
    fn whitespace_only_renders_true() {
        assert_eq!(ok("   \t \n "), ("TRUE".to_string(), vec![]));
    }

    // ── Single conditions, each value type ───────────────────────────

    #[test]
    fn single_integer_condition() {
        let (clause, params) = ok("id = 1");
        assert_eq!(clause, "\"id\" = $1");
        assert_eq!(params, vec![SqlValue::Integer(1)]);
    }

    #[test]
    fn single_string_condition_single_quoted() {
        let (clause, params) = ok("name = 'Alice'");
        assert_eq!(clause, "\"name\" = $1");
        assert_eq!(params, vec![SqlValue::Text("Alice".to_string())]);
    }

    #[test]
    fn single_string_condition_double_quoted() {
        let (_, params) = ok("name = \"Bob\"");
        assert_eq!(params, vec![SqlValue::Text("Bob".to_string())]);
    }

    #[test]
    fn negative_integer_value() {
        let (clause, params) = ok("balance >= -100");
        assert_eq!(clause, "\"balance\" >= $1");
        assert_eq!(params, vec![SqlValue::Integer(-100)]);
    }

    #[test]
    fn float_value() {
        let (_, params) = ok("score > 3.14");
        assert_eq!(params, vec![SqlValue::Float(3.14)]);
    }

    #[test]
    fn boolean_values() {
        assert_eq!(ok("active = true").1, vec![SqlValue::Boolean(true)]);
        assert_eq!(ok("active = false").1, vec![SqlValue::Boolean(false)]);
    }

    #[test]
    fn integer_overflowing_i64_falls_back_to_float() {
        // 10^25 does not fit i64 — must compile as a finite float.
        let (_, params) = ok("n = 10000000000000000000000000");
        assert!(matches!(params[0], SqlValue::Float(_)));
    }

    // ── Operators ────────────────────────────────────────────────────

    #[test]
    fn every_operator_renders_canonically() {
        assert_eq!(ok("a = 1").0, "\"a\" = $1");
        assert_eq!(ok("a != 1").0, "\"a\" != $1");
        assert_eq!(ok("a > 1").0, "\"a\" > $1");
        assert_eq!(ok("a >= 1").0, "\"a\" >= $1");
        assert_eq!(ok("a < 1").0, "\"a\" < $1");
        assert_eq!(ok("a <= 1").0, "\"a\" <= $1");
        assert_eq!(ok("a LIKE 'x%'").0, "\"a\" LIKE $1");
    }

    #[test]
    fn operator_aliases_normalize() {
        // `==` → `=`, `<>` → `!=`.
        assert_eq!(ok("a == 1").0, "\"a\" = $1");
        assert_eq!(ok("a <> 1").0, "\"a\" != $1");
    }

    #[test]
    fn like_is_case_insensitive_and_renders_uppercase() {
        assert_eq!(ok("a like 'x%'").0, "\"a\" LIKE $1");
        assert_eq!(ok("a LiKe 'x%'").0, "\"a\" LIKE $1");
    }

    // ── Connectors + multi-condition ─────────────────────────────────

    #[test]
    fn two_conditions_joined_by_and() {
        let (clause, params) = ok("id = 1 AND name = 'Alice'");
        assert_eq!(clause, "\"id\" = $1 AND \"name\" = $2");
        assert_eq!(
            params,
            vec![SqlValue::Integer(1), SqlValue::Text("Alice".to_string())]
        );
    }

    #[test]
    fn two_conditions_joined_by_or() {
        assert_eq!(ok("a = 1 OR b = 2").0, "\"a\" = $1 OR \"b\" = $2");
    }

    #[test]
    fn connectors_are_case_insensitive() {
        assert_eq!(ok("a = 1 and b = 2").0, "\"a\" = $1 AND \"b\" = $2");
        assert_eq!(ok("a = 1 Or b = 2").0, "\"a\" = $1 OR \"b\" = $2");
    }

    #[test]
    fn three_condition_mixed_chain_preserves_order() {
        let (clause, params) = ok("a = 1 AND b = 2 OR c = 3");
        assert_eq!(clause, "\"a\" = $1 AND \"b\" = $2 OR \"c\" = $3");
        assert_eq!(params.len(), 3);
    }

    // ── NULL folding ─────────────────────────────────────────────────

    #[test]
    fn null_equality_folds_to_is_null() {
        let (clause, params) = ok("deleted_at = null");
        assert_eq!(clause, "\"deleted_at\" IS NULL");
        assert!(params.is_empty(), "IS NULL consumes no bind parameter");
    }

    #[test]
    fn null_inequality_folds_to_is_not_null() {
        let (clause, params) = ok("deleted_at != NULL");
        assert_eq!(clause, "\"deleted_at\" IS NOT NULL");
        assert!(params.is_empty());
    }

    #[test]
    fn null_does_not_occupy_a_parameter_slot() {
        // `a` is NULL (folded, no slot) so `b` takes $1, not $2.
        let (clause, params) = ok("a = null AND b = 5");
        assert_eq!(clause, "\"a\" IS NULL AND \"b\" = $1");
        assert_eq!(params, vec![SqlValue::Integer(5)]);
    }

    #[test]
    fn rendered_params_never_contain_null() {
        let (_, params) = ok("a = null AND b = 1 OR c != null");
        assert!(params.iter().all(|v| !matches!(v, SqlValue::Null)));
    }

    // ── param_offset ─────────────────────────────────────────────────

    #[test]
    fn param_offset_shifts_placeholder_numbering() {
        let (clause, _) = build_pg_where("id = 1", 2).unwrap();
        assert_eq!(clause, "\"id\" = $3");
    }

    #[test]
    fn param_offset_shifts_every_placeholder() {
        let (clause, _) = build_pg_where("a = 1 AND b = 2", 5).unwrap();
        assert_eq!(clause, "\"a\" = $6 AND \"b\" = $7");
    }

    // ── D4 — SQL-injection resistance ────────────────────────────────

    #[test]
    fn injection_payload_inside_a_quoted_string_is_an_inert_bind_param() {
        // The classic payload — fully contained in a string literal —
        // compiles to ONE harmless bound parameter. The SQL structure
        // is `"name" = $1`; the payload never reaches SQL text.
        let (clause, params) = ok("name = '; DROP TABLE users; --'");
        assert_eq!(clause, "\"name\" = $1");
        assert_eq!(
            params,
            vec![SqlValue::Text("; DROP TABLE users; --".to_string())]
        );
    }

    #[test]
    fn injection_via_statement_terminator_is_rejected_at_tokenize() {
        // A bare `;` is outside the grammar alphabet.
        assert!(matches!(
            err("name = 'x'; DROP TABLE users"),
            FilterError::UnexpectedChar { ch: ';', .. }
        ));
    }

    #[test]
    fn injection_via_comment_marker_is_rejected() {
        // `--` lexes as two `-` — and a `-` not before a digit is
        // outside the alphabet.
        assert!(matches!(
            err("a = 1 -- comment"),
            FilterError::UnexpectedChar { ch: '-', .. }
        ));
    }

    #[test]
    fn injection_via_bare_or_tautology_is_rejected() {
        // `name = 'x' OR 1=1` — after the OR, `1` is in column
        // position and is not an identifier.
        assert!(matches!(
            err("name = 'x' OR 1 = 1"),
            FilterError::ExpectedColumn { .. }
        ));
    }

    // ── String escapes ──────────────────────────────────────────────

    #[test]
    fn escaped_quote_inside_string_is_resolved() {
        let (_, params) = ok("name = 'O\\'Brien'");
        assert_eq!(params, vec![SqlValue::Text("O'Brien".to_string())]);
    }

    #[test]
    fn escaped_backslash_is_resolved() {
        let (_, params) = ok("path = 'a\\\\b'");
        assert_eq!(params, vec![SqlValue::Text("a\\b".to_string())]);
    }

    // ── Lexical errors ──────────────────────────────────────────────

    #[test]
    fn unterminated_string_errors() {
        assert!(matches!(
            err("name = 'unclosed"),
            FilterError::UnterminatedString { .. }
        ));
    }

    #[test]
    fn unexpected_character_errors() {
        assert!(matches!(
            err("a = 1 & b = 2"),
            FilterError::UnexpectedChar { ch: '&', .. }
        ));
    }

    #[test]
    fn bare_bang_is_rejected() {
        assert!(matches!(
            err("a ! 1"),
            FilterError::UnexpectedChar { ch: '!', .. }
        ));
    }

    #[test]
    fn invalid_number_errors() {
        assert!(matches!(
            err("a = 1.2.3"),
            FilterError::InvalidNumber { .. }
        ));
    }

    // ── Structural / parse errors ────────────────────────────────────

    #[test]
    fn missing_operator_errors() {
        assert!(matches!(err("id"), FilterError::MissingOperator { .. }));
    }

    #[test]
    fn missing_value_errors() {
        assert!(matches!(err("id ="), FilterError::MissingValue { .. }));
    }

    #[test]
    fn unquoted_string_value_errors() {
        assert!(matches!(
            err("status = active"),
            FilterError::UnquotedValue { .. }
        ));
    }

    #[test]
    fn dangling_connector_errors() {
        // The exact defect the frozen Python reference mis-renders.
        assert!(matches!(
            err("id = 1 AND"),
            FilterError::DanglingConnector {
                connector: Connector::And
            }
        ));
    }

    #[test]
    fn two_conditions_without_connector_errors() {
        assert!(matches!(
            err("a = 1 b = 2"),
            FilterError::ExpectedConnector { .. }
        ));
    }

    #[test]
    fn column_position_non_identifier_errors() {
        assert!(matches!(err("1 = 1"), FilterError::ExpectedColumn { .. }));
    }

    #[test]
    fn operator_position_non_operator_errors() {
        assert!(matches!(
            err("a b c"),
            FilterError::ExpectedOperator { .. }
        ));
    }

    // ── Semantic errors ─────────────────────────────────────────────

    #[test]
    fn null_with_ordering_operator_errors() {
        assert!(matches!(
            err("score > null"),
            FilterError::NullWithNonEqualityOp { op: Operator::Gt, .. }
        ));
    }

    #[test]
    fn null_with_like_errors() {
        assert!(matches!(
            err("name LIKE null"),
            FilterError::NullWithNonEqualityOp { op: Operator::Like, .. }
        ));
    }

    #[test]
    fn like_with_non_text_value_errors() {
        assert!(matches!(
            err("age LIKE 5"),
            FilterError::LikeRequiresText { found: "integer", .. }
        ));
    }

    // ── Bounds ───────────────────────────────────────────────────────

    #[test]
    fn column_at_the_length_limit_compiles() {
        let col = "c".repeat(MAX_COLUMN_LEN);
        assert!(build_pg_where(&format!("{col} = 1"), 0).is_ok());
    }

    #[test]
    fn column_over_the_length_limit_errors() {
        let col = "c".repeat(MAX_COLUMN_LEN + 1);
        assert!(matches!(
            build_pg_where(&format!("{col} = 1"), 0),
            Err(FilterError::ColumnTooLong { .. })
        ));
    }

    #[test]
    fn condition_count_at_the_limit_compiles() {
        let expr = (0..MAX_CONDITIONS)
            .map(|i| format!("c{i} = {i}"))
            .collect::<Vec<_>>()
            .join(" AND ");
        let (_, params) = build_pg_where(&expr, 0).unwrap();
        assert_eq!(params.len(), MAX_CONDITIONS);
    }

    #[test]
    fn condition_count_over_the_limit_errors() {
        let expr = (0..=MAX_CONDITIONS)
            .map(|i| format!("c{i} = {i}"))
            .collect::<Vec<_>>()
            .join(" AND ");
        assert!(matches!(
            build_pg_where(&expr, 0),
            Err(FilterError::TooManyConditions { .. })
        ));
    }

    // ── AST shape via parse_filter ───────────────────────────────────

    #[test]
    fn parse_filter_exposes_the_typed_ast() {
        let filter = parse_filter("id = 1 AND name LIKE 'A%'").unwrap();
        assert_eq!(filter.conditions.len(), 2);
        assert_eq!(filter.connectors, vec![Connector::And]);
        assert_eq!(
            filter.conditions[0],
            FilterCondition {
                column: "id".to_string(),
                op: Operator::Eq,
                value: SqlValue::Integer(1),
            }
        );
        assert_eq!(filter.conditions[1].op, Operator::Like);
        assert_eq!(
            filter.conditions[1].value,
            SqlValue::Text("A%".to_string())
        );
    }

    #[test]
    fn parse_filter_invariant_connectors_plus_one_equals_conditions() {
        for expr in ["a = 1", "a = 1 AND b = 2", "a = 1 OR b = 2 AND c = 3"] {
            let f = parse_filter(expr).unwrap();
            assert_eq!(f.connectors.len() + 1, f.conditions.len());
        }
    }

    #[test]
    fn empty_filter_is_empty() {
        assert!(parse_filter("").unwrap().is_empty());
        assert!(parse_filter("  ").unwrap().is_empty());
        assert!(!parse_filter("a = 1").unwrap().is_empty());
    }

    // ── Error Display is non-empty + informative ─────────────────────

    #[test]
    fn every_error_has_a_non_empty_display() {
        let samples = [
            err("a = 1 ;"),
            err("a = 'x"),
            err("a = 1.2.3"),
            err("1 = 1"),
            err("id"),
            err("id ="),
            err("a = b"),
            err("a = 1 b = 2"),
            err("a = 1 AND"),
            err("a > null"),
            err("a LIKE 5"),
        ];
        for e in samples {
            assert!(!e.to_string().is_empty());
        }
    }
}
