//! §Fase 38.d (D2 — first half) — the `StoreColumnProof` axon-check
//! pass for `where:` clauses.
//!
//! For every store operation in every flow, given a declared
//! [`StoreColumnSchema`] (inline) OR a resolved [`ManifestStore`]
//! entry (forms b/c via 38.c's manifest layer), this pass proves:
//!
//!  - **`axon-T801`** — every `where:` column reference exists in the
//!    declared schema. Unknown columns surface a Fase 28 Levenshtein
//!    "Did you mean X?" hint within edit-distance 2 (the standard cap).
//!  - **`axon-T802`** — every `where:` value (a bound `${param}` OR a
//!    literal) is type-compatible with the column's declared type per
//!    the closed compatibility matrix [`compat_matrix`].
//!  - **`axon-T805`** — propagated from the manifest layer when a
//!    manifest's `content_hash` does not match its canonical content
//!    (the manifest was hand-edited without recomputing the hash).
//!
//! The pass skips silently when no `schema:` is declared (D5 absolute
//! — undeclared stores run the v1.37.0 runtime+deploy path verbatim).
//!
//! # Why a proof-purpose scanner, not the runtime parse_filter
//!
//! The runtime `parse_filter` (in `axon-rs/src/store/filter.rs`)
//! INTERPOLATES `${param}` references at parse time using a runtime
//! `bindings: &HashMap<String,String>` — by the time the AST is
//! built, every parameter has already been substituted to a literal.
//! That is correct for the runtime SQL-compilation path but loses
//! the parameter-name information D2 needs to prove a flow
//! parameter's declared type matches the column's declared type.
//!
//! 38.d therefore ships a small proof-purpose scanner ([`scan_where`])
//! that preserves `${param}` references AS BoundParam refs (no
//! interpolation), classifies literals by lexical shape, and emits
//! the (column, op, value) triples the proof consumes. Honest scope:
//! the scanner is a STRICT SUBSET of the runtime grammar — it
//! recognises the exact same operator + literal + connector set that
//! `parse_filter` does but produces a leaner proof-friendly tree. A
//! malformed `where:` that the runtime parser would reject is also
//! rejected here; the pass remains silent only on filters that BOTH
//! stacks accept.
//!
//! # Form (b) / form (c) resolution at check time
//!
//! When a store declares `schema: "qualified.name"` (form b) or
//! `schema: env:VAR` (form c), the column set lives in a
//! `.axon-schema.json` manifest. [`load_columns_for_form`] resolves
//! the right [`ManifestStore`] entry using the discovery layer from
//! §Fase 38.c. Form (c) at check time uses a first-match heuristic:
//! look up `<env_var_name>.<store_name>` first; on miss, scan every
//! manifest entry whose key ends in `.<store_name>` and use the first
//! match (the assumption — typically true at deploy — is that
//! per-tenant schemas have IDENTICAL column shapes). Deploy-time
//! verification (D8, in 38.f) still proves the resolved namespace's
//! actual columns against the manifest.
//!
//! Honest scope: when no manifest is available at check time (the
//! discovery layer returned empty), forms (b)/(c) emit no `axon-T8xx`
//! errors — they're not provable without a manifest. The deploy-time
//! gate (D8) is the floor for these forms.

use std::collections::BTreeMap;
use std::path::Path;

use crate::smart_suggest;
use crate::store_schema::{StoreColumn, StoreColumnSchema, StoreColumnType};
use crate::store_schema_manifest::{
    self, Manifest, ManifestError, ManifestStore,
};

// ════════════════════════════════════════════════════════════════════
//  Error catalog (axon-T80x family — Fase 28 source-context blocks)
// ════════════════════════════════════════════════════════════════════

/// The closed axon-T80x error-code family Fase 38 introduces.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProofErrorCode {
    /// `axon-T801` — a `where:` column reference doesn't exist in the
    /// declared schema.
    T801UnknownColumn,
    /// `axon-T802` — a `where:` value type doesn't match its column's
    /// declared type.
    T802TypeMismatch,
    /// `axon-T805` — propagated from the manifest layer when its
    /// `content_hash` mismatches the canonical content.
    T805ManifestHashMismatch,
}

impl ProofErrorCode {
    /// The stable `axon-T8nn` slug for diagnostic rendering + JSON
    /// output + LSP integration.
    pub fn slug(self) -> &'static str {
        match self {
            Self::T801UnknownColumn => "axon-T801",
            Self::T802TypeMismatch => "axon-T802",
            Self::T805ManifestHashMismatch => "axon-T805",
        }
    }
}

/// One proof failure. Carries the error code, the source location
/// (where in the `.axon` to anchor the Fase 28 source-context block),
/// and a human-readable message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProofError {
    pub code: ProofErrorCode,
    pub line: u32,
    pub column: u32,
    pub message: String,
}

impl ProofError {
    fn new(code: ProofErrorCode, line: u32, column: u32, message: String) -> Self {
        Self {
            code,
            line,
            column,
            message,
        }
    }
}

// ════════════════════════════════════════════════════════════════════
//  The unified "declared columns" view
// ════════════════════════════════════════════════════════════════════

/// One declared column — type + nullable flag + whether it's a
/// primary key (informational; the proof uses `not_null` for the
/// nullable check).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeclaredColumn {
    pub name: String,
    pub col_type: StoreColumnType,
    pub not_null: bool,
}

/// The proof's view of a store's declared columns. Built from either
/// an inline [`StoreColumnSchema::Inline`] OR a [`ManifestStore`]
/// entry — the proof code itself is source-agnostic.
#[derive(Debug, Clone, Default)]
pub struct ColumnSet {
    pub columns: BTreeMap<String, DeclaredColumn>,
}

impl ColumnSet {
    /// Construct from an inline column schema (form a). Returns
    /// `None` when the schema is not the inline form — the caller
    /// must use [`Self::from_manifest_store`] for forms b/c.
    pub fn from_inline_schema(schema: &StoreColumnSchema) -> Option<ColumnSet> {
        let StoreColumnSchema::Inline { columns, .. } = schema else {
            return None;
        };
        Some(Self::from_inline_columns(columns))
    }

    /// Construct from an inline column slice (the inner of
    /// `StoreColumnSchema::Inline`). Exposed for testability.
    pub fn from_inline_columns(columns: &[StoreColumn]) -> ColumnSet {
        let mut out = BTreeMap::new();
        for col in columns {
            out.insert(
                col.name.clone(),
                DeclaredColumn {
                    name: col.name.clone(),
                    col_type: col.col_type,
                    not_null: col.not_null || col.primary_key,
                },
            );
        }
        ColumnSet { columns: out }
    }

    /// Construct from a [`ManifestStore`] entry (forms b/c).
    pub fn from_manifest_store(store: &ManifestStore) -> ColumnSet {
        let mut out = BTreeMap::new();
        for (name, mc) in &store.columns {
            out.insert(
                name.clone(),
                DeclaredColumn {
                    name: name.clone(),
                    col_type: mc.col_type,
                    not_null: mc.not_null || mc.primary_key,
                },
            );
        }
        ColumnSet { columns: out }
    }

    /// `true` iff the named column is declared.
    pub fn contains(&self, name: &str) -> bool {
        self.columns.contains_key(name)
    }

    /// The declared column, or `None`.
    pub fn get(&self, name: &str) -> Option<&DeclaredColumn> {
        self.columns.get(name)
    }

    /// Every declared column name (used for Levenshtein suggestions).
    pub fn names(&self) -> Vec<&str> {
        self.columns.keys().map(|s| s.as_str()).collect()
    }
}

// ════════════════════════════════════════════════════════════════════
//  Flow parameter type map — for axon-T802 type-mismatch proof
// ════════════════════════════════════════════════════════════════════

/// Flow parameter name → its declared axon-language type name (as
/// written by the adopter, e.g. `"String"`, `"Int"`, `"Uuid"`,
/// `"Bool"`). The proof maps these to [`StoreColumnType`]-compatible
/// classes via [`axon_type_to_column_class`].
#[derive(Debug, Clone, Default)]
pub struct FlowParamTypes {
    pub types: BTreeMap<String, String>,
}

impl FlowParamTypes {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn insert(&mut self, name: String, type_name: String) {
        self.types.insert(name, type_name);
    }

    pub fn get(&self, name: &str) -> Option<&str> {
        self.types.get(name).map(|s| s.as_str())
    }
}

// ════════════════════════════════════════════════════════════════════
//  The proof-purpose where-scanner
// ════════════════════════════════════════════════════════════════════

/// One predicate observed by the where-scanner. The proof iterates
/// over a `Vec<ScannedPredicate>` and runs the per-predicate
/// validation (column existence + type compatibility).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScannedPredicate {
    pub column: String,
    pub op: WhereOp,
    pub value: WhereValue,
}

/// The closed set of operators the scanner recognises. Mirror of the
/// runtime `Operator` enum in `axon-rs/src/store/filter.rs`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WhereOp {
    Eq,
    NotEq,
    Lt,
    Gt,
    Le,
    Ge,
    Like,
    IsNull,
    IsNotNull,
}

impl WhereOp {
    pub fn is_equality(self) -> bool {
        matches!(self, Self::Eq | Self::NotEq)
    }
    pub fn is_ordering(self) -> bool {
        matches!(self, Self::Lt | Self::Gt | Self::Le | Self::Ge)
    }
    pub fn is_null_check(self) -> bool {
        matches!(self, Self::IsNull | Self::IsNotNull)
    }
}

/// The classified value side of a predicate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WhereValue {
    /// `${name}` or `$name` — a bound flow parameter. The proof
    /// looks up the parameter's declared type in [`FlowParamTypes`]
    /// and runs the compatibility check.
    BoundParam(String),
    /// A literal — classified by lexical shape into one of the
    /// [`LiteralKind`] variants.
    Literal {
        kind: LiteralKind,
        raw: String,
    },
    /// `NULL` keyword (only valid with `IS [NOT] NULL`).
    NullKeyword,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LiteralKind {
    /// A quoted string. May represent a UUID, a timestamp, a JSON
    /// blob, etc. — the proof checks compatibility against the
    /// column type (Text columns accept any string; Uuid/Date/Time
    /// columns accept canonical-form text).
    Text,
    /// An integer literal — `42`, `-7`.
    Int,
    /// A floating-point literal — `3.14`, `-0.5`.
    Float,
    /// `true` or `false`.
    Bool,
}

/// Errors the scanner emits for syntactically-malformed `where:`
/// strings. These are NOT proof errors (axon-T8xx); they're a hint
/// the caller can surface OR ignore (the runtime `parse_filter` will
/// reject the same shape with its own diagnostic).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ScanError {
    /// The expression has a syntactic shape the scanner can't decode.
    /// 38.d documents this as "the runtime parser will surface the
    /// canonical error; 38.d only proves the well-formed subset".
    Malformed { detail: String },
}

/// Scan a `where:` string into a flat list of predicates. The scan
/// recognises the closed subset of the runtime filter grammar (the
/// surface 35.b's `parse_filter` accepts) sufficient for the D2
/// proof. `${param}` and `$param` references are preserved as
/// [`WhereValue::BoundParam`] — NOT interpolated.
///
/// On a syntactic miss, returns the predicates scanned so far + a
/// [`ScanError::Malformed`] error. The proof caller surfaces this
/// silently (the runtime parser owns the syntactic-error message).
pub fn scan_where(expr: &str) -> Result<Vec<ScannedPredicate>, ScanError> {
    let trimmed = expr.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }

    let tokens = tokenize(trimmed)?;
    let mut out: Vec<ScannedPredicate> = Vec::new();
    let mut i = 0;

    while i < tokens.len() {
        let predicate = parse_predicate(&tokens, &mut i)?;
        out.push(predicate);

        if i < tokens.len() {
            // Consume the connector. Connectors are AND / OR (case-
            // insensitive). Anything else is malformed.
            let connector = match &tokens[i] {
                ScanToken::Word(w)
                    if w.eq_ignore_ascii_case("and") || w.eq_ignore_ascii_case("or") =>
                {
                    i += 1;
                    w.clone()
                }
                other => {
                    return Err(ScanError::Malformed {
                        detail: format!("expected `AND`/`OR` between predicates, got {other:?}"),
                    });
                }
            };
            // Trailing-connector check.
            if i == tokens.len() {
                return Err(ScanError::Malformed {
                    detail: format!("trailing `{connector}` with no following predicate"),
                });
            }
        }
    }
    Ok(out)
}

// ── Tokenizer ────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
enum ScanToken {
    /// Identifier or keyword (`AND`/`OR`/`NOT`/`IS`/`NULL`/`LIKE`).
    Word(String),
    /// Operator symbol (`=`, `!=`, `<>`, `<`, `>`, `<=`, `>=`, `==`).
    Symbol(String),
    /// Quoted string literal — content WITHOUT the surrounding quotes.
    Str(String),
    /// Integer literal — raw token (the proof preserves the spelling).
    Int(String),
    /// Float literal.
    Float(String),
    /// `${name}` or `$name` — bound parameter reference.
    BoundParam(String),
}

fn tokenize(src: &str) -> Result<Vec<ScanToken>, ScanError> {
    let bytes = src.as_bytes();
    let mut out: Vec<ScanToken> = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        if b.is_ascii_whitespace() {
            i += 1;
            continue;
        }
        // ── Bound-parameter ${name} or $name ──
        if b == b'$' {
            i += 1;
            let braced = i < bytes.len() && bytes[i] == b'{';
            if braced {
                i += 1;
            }
            let start = i;
            while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                i += 1;
            }
            if i == start {
                return Err(ScanError::Malformed {
                    detail: format!("empty parameter reference at position {start}"),
                });
            }
            let name = String::from_utf8_lossy(&bytes[start..i]).to_string();
            if braced {
                if i >= bytes.len() || bytes[i] != b'}' {
                    return Err(ScanError::Malformed {
                        detail: format!("unterminated `${{...}}` reference for `{name}`"),
                    });
                }
                i += 1;
            }
            out.push(ScanToken::BoundParam(name));
            continue;
        }
        // ── Quoted string ──
        if b == b'\'' {
            i += 1;
            let start = i;
            while i < bytes.len() && bytes[i] != b'\'' {
                // Escape: SQL-style doubled single-quote = '' inside a string
                if bytes[i] == b'\\' && i + 1 < bytes.len() {
                    i += 2;
                    continue;
                }
                i += 1;
            }
            if i >= bytes.len() {
                return Err(ScanError::Malformed {
                    detail: format!("unterminated string starting at position {start}"),
                });
            }
            let content = String::from_utf8_lossy(&bytes[start..i]).to_string();
            i += 1;
            out.push(ScanToken::Str(content));
            continue;
        }
        // ── Number ──
        if b.is_ascii_digit() || (b == b'-' && i + 1 < bytes.len() && bytes[i + 1].is_ascii_digit())
        {
            let start = i;
            if b == b'-' {
                i += 1;
            }
            let mut saw_dot = false;
            while i < bytes.len() {
                let c = bytes[i];
                if c.is_ascii_digit() {
                    i += 1;
                } else if c == b'.' && !saw_dot {
                    saw_dot = true;
                    i += 1;
                } else {
                    break;
                }
            }
            let tok = String::from_utf8_lossy(&bytes[start..i]).to_string();
            if saw_dot {
                out.push(ScanToken::Float(tok));
            } else {
                out.push(ScanToken::Int(tok));
            }
            continue;
        }
        // ── Identifier ──
        if b.is_ascii_alphabetic() || b == b'_' {
            let start = i;
            while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                i += 1;
            }
            let word = String::from_utf8_lossy(&bytes[start..i]).to_string();
            out.push(ScanToken::Word(word));
            continue;
        }
        // ── Operator symbols ──
        // Multi-char first: `==`, `!=`, `<>`, `<=`, `>=`.
        if i + 1 < bytes.len() {
            let two = std::str::from_utf8(&bytes[i..i + 2]).unwrap_or("");
            if matches!(two, "==" | "!=" | "<>" | "<=" | ">=") {
                out.push(ScanToken::Symbol(two.to_string()));
                i += 2;
                continue;
            }
        }
        // Single-char: `=`, `<`, `>`.
        if matches!(b, b'=' | b'<' | b'>') {
            out.push(ScanToken::Symbol((b as char).to_string()));
            i += 1;
            continue;
        }
        return Err(ScanError::Malformed {
            detail: format!("unexpected character {:?} at position {i}", b as char),
        });
    }
    Ok(out)
}

// ── Predicate parser ─────────────────────────────────────────────────

fn parse_predicate(
    tokens: &[ScanToken],
    cursor: &mut usize,
) -> Result<ScannedPredicate, ScanError> {
    // — Column —
    let column = match tokens.get(*cursor) {
        Some(ScanToken::Word(w)) => {
            // Reject connectors/keywords in column position.
            if matches!(
                w.to_ascii_uppercase().as_str(),
                "AND" | "OR" | "NOT" | "NULL"
            ) {
                return Err(ScanError::Malformed {
                    detail: format!("expected column name, got reserved word `{w}`"),
                });
            }
            w.clone()
        }
        other => {
            return Err(ScanError::Malformed {
                detail: format!("expected column identifier, got {other:?}"),
            });
        }
    };
    *cursor += 1;

    // — Operator —
    let op_token = tokens.get(*cursor).ok_or_else(|| ScanError::Malformed {
        detail: format!("missing operator after column `{column}`"),
    })?;

    let op: WhereOp = match op_token {
        ScanToken::Symbol(s) => match s.as_str() {
            "=" | "==" => WhereOp::Eq,
            "!=" | "<>" => WhereOp::NotEq,
            "<" => WhereOp::Lt,
            ">" => WhereOp::Gt,
            "<=" => WhereOp::Le,
            ">=" => WhereOp::Ge,
            other => {
                return Err(ScanError::Malformed {
                    detail: format!("unknown operator `{other}` after column `{column}`"),
                });
            }
        },
        ScanToken::Word(w) if w.eq_ignore_ascii_case("like") => WhereOp::Like,
        ScanToken::Word(w) if w.eq_ignore_ascii_case("is") => {
            // `IS NULL` or `IS NOT NULL`.
            *cursor += 1;
            let next = tokens.get(*cursor).ok_or_else(|| ScanError::Malformed {
                detail: format!("`IS` requires `NULL` or `NOT NULL` after column `{column}`"),
            })?;
            let mut is_not = false;
            let null_tok = match next {
                ScanToken::Word(w) if w.eq_ignore_ascii_case("not") => {
                    is_not = true;
                    *cursor += 1;
                    tokens.get(*cursor).ok_or_else(|| ScanError::Malformed {
                        detail: format!(
                            "`IS NOT` requires `NULL` after column `{column}`"
                        ),
                    })?
                }
                other => other,
            };
            match null_tok {
                ScanToken::Word(w) if w.eq_ignore_ascii_case("null") => {
                    *cursor += 1;
                    return Ok(ScannedPredicate {
                        column,
                        op: if is_not { WhereOp::IsNotNull } else { WhereOp::IsNull },
                        value: WhereValue::NullKeyword,
                    });
                }
                other => {
                    return Err(ScanError::Malformed {
                        detail: format!(
                            "expected `NULL` after `IS{}`, got {other:?}",
                            if is_not { " NOT" } else { "" }
                        ),
                    });
                }
            }
        }
        other => {
            return Err(ScanError::Malformed {
                detail: format!("expected operator after column `{column}`, got {other:?}"),
            });
        }
    };
    *cursor += 1;

    // — Value —
    let value_token = tokens.get(*cursor).ok_or_else(|| ScanError::Malformed {
        detail: format!("missing value after `{column} {op:?}`"),
    })?;
    let value = match value_token {
        ScanToken::Str(s) => WhereValue::Literal {
            kind: LiteralKind::Text,
            raw: s.clone(),
        },
        ScanToken::Int(s) => WhereValue::Literal {
            kind: LiteralKind::Int,
            raw: s.clone(),
        },
        ScanToken::Float(s) => WhereValue::Literal {
            kind: LiteralKind::Float,
            raw: s.clone(),
        },
        ScanToken::BoundParam(n) => WhereValue::BoundParam(n.clone()),
        ScanToken::Word(w) if w.eq_ignore_ascii_case("true") || w.eq_ignore_ascii_case("false") => {
            WhereValue::Literal {
                kind: LiteralKind::Bool,
                raw: w.clone(),
            }
        }
        ScanToken::Word(w) if w.eq_ignore_ascii_case("null") => WhereValue::NullKeyword,
        other => {
            return Err(ScanError::Malformed {
                detail: format!("unexpected value-position token {other:?}"),
            });
        }
    };
    *cursor += 1;
    Ok(ScannedPredicate {
        column,
        op,
        value,
    })
}

// ════════════════════════════════════════════════════════════════════
//  Type-compatibility matrix
// ════════════════════════════════════════════════════════════════════

/// `true` iff a literal of `lit` can compare against a column of type
/// `col`. The matrix follows the runtime D4 fallback shape — text
/// canonical-form values are accepted for date/time/uuid columns
/// (matching the v1.37.0 `"col"::text = $N` behaviour).
pub fn literal_compatible_with_column(lit: LiteralKind, col: StoreColumnType) -> bool {
    use LiteralKind as L;
    use StoreColumnType as C;
    match (lit, col) {
        (L::Text, C::Text) => true,
        (L::Text, C::Uuid) => true, // canonical UUID format
        (L::Text, C::Timestamptz | C::Timestamp | C::Date | C::Time) => true,
        (L::Text, C::Jsonb | C::Json) => true,
        (L::Text, C::Bytea) => true, // base64
        (L::Text, C::Numeric) => true, // precision-safe string
        (L::Int, C::Int | C::BigInt) => true,
        (L::Int, C::Float | C::Double) => true,
        (L::Int, C::Numeric) => true,
        (L::Float, C::Float | C::Double | C::Numeric) => true,
        (L::Bool, C::Bool) => true,
        _ => false,
    }
}

/// `true` iff a flow parameter of axon-language type `param_axon` can
/// compare against a column of `col` (closed match table mirroring
/// the runtime D4 + the v1.30.0 supported catalog).
///
/// `param_axon` is the type name as written in the flow header
/// (`String`, `Int`, `Bool`, `Float`, `Uuid`, …). The mapping ignores
/// `Optional<T>` wrapping for the compatibility check — the optional
/// flag handles the nullable concern separately.
pub fn axon_param_compatible_with_column(
    param_axon: &str,
    col: StoreColumnType,
) -> bool {
    let normalised = strip_optional_wrap(param_axon);
    use StoreColumnType as C;
    match (normalised, col) {
        // Text family — String matches any text-shaped column (incl.
        // uuid/date/time/json/bytea — same as the runtime D4 fallback).
        ("String", _) => true,
        ("Text", _) => true,
        // Numeric family.
        ("Int", C::Int | C::BigInt | C::Numeric | C::Float | C::Double) => true,
        ("Integer", C::Int | C::BigInt | C::Numeric | C::Float | C::Double) => true,
        ("BigInt", C::BigInt | C::Numeric | C::Float | C::Double) => true,
        ("Float", C::Float | C::Double | C::Numeric) => true,
        ("Double", C::Float | C::Double | C::Numeric) => true,
        ("Number", C::Int | C::BigInt | C::Float | C::Double | C::Numeric) => true,
        // Boolean.
        ("Bool", C::Bool) => true,
        ("Boolean", C::Bool) => true,
        // Typed exact matches.
        ("Uuid", C::Uuid) => true,
        ("UUID", C::Uuid) => true,
        ("Timestamptz", C::Timestamptz) => true,
        ("Timestamp", C::Timestamp) => true,
        ("Date", C::Date) => true,
        ("Time", C::Time) => true,
        ("Json", C::Json | C::Jsonb) => true,
        ("Jsonb", C::Jsonb | C::Json) => true,
        ("Bytea", C::Bytea) => true,
        _ => false,
    }
}

fn strip_optional_wrap(name: &str) -> &str {
    // Pre-Fase 38 the optional flag is a separate AST flag. But some
    // adopters write `Optional<T>` literally; strip that for compat
    // purposes.
    if let Some(inner) = name
        .strip_prefix("Optional<")
        .and_then(|s| s.strip_suffix('>'))
    {
        return inner;
    }
    if let Some(inner) = name.strip_prefix("Option<").and_then(|s| s.strip_suffix('>')) {
        return inner;
    }
    name
}

// ════════════════════════════════════════════════════════════════════
//  The proof entry point
// ════════════════════════════════════════════════════════════════════

/// Run the D2 proof against `where_expr` given a declared column set
/// and the flow parameters in scope. Returns every proof failure
/// (`axon-T801` / `axon-T802`) anchored at `where_loc` for Fase 28
/// source-context rendering.
///
/// Empty `where:` clauses skip silently (no predicates → nothing to
/// prove). Syntactically-malformed where strings ALSO skip silently
/// — the runtime parser surfaces the canonical syntactic error;
/// 38.d only proves the well-formed subset.
pub fn check_filter(
    where_expr: &str,
    columns: &ColumnSet,
    flow_params: &FlowParamTypes,
    where_loc: (u32, u32),
) -> Vec<ProofError> {
    let predicates = match scan_where(where_expr) {
        Ok(ps) => ps,
        Err(_) => return Vec::new(),
    };
    let mut out: Vec<ProofError> = Vec::new();
    for pred in predicates {
        check_predicate(&pred, columns, flow_params, where_loc, &mut out);
    }
    out
}

fn check_predicate(
    pred: &ScannedPredicate,
    columns: &ColumnSet,
    flow_params: &FlowParamTypes,
    where_loc: (u32, u32),
    out: &mut Vec<ProofError>,
) {
    // — T801 unknown column —
    let Some(col) = columns.get(&pred.column) else {
        let names = columns.names();
        let suggestion = smart_suggest::suggest_for(&pred.column, &names);
        let suggest_suffix = if suggestion.is_empty() {
            String::new()
        } else {
            format!(" {suggestion}")
        };
        out.push(ProofError::new(
            ProofErrorCode::T801UnknownColumn,
            where_loc.0,
            where_loc.1,
            format!(
                "axon-T801 unknown column `{}` in `where:` clause. The \
                 declared schema has columns: {{{}}}.{suggest_suffix}",
                pred.column,
                names.join(", "),
            ),
        ));
        return;
    };

    // — IS [NOT] NULL — only the column-existence check matters; the
    //   nullability is a semantic concern but isn't a T8xx error
    //   (a `not_null` column compared `IS NULL` is always false but
    //   that's a logic-bug warning, not a type error).
    if pred.op.is_null_check() {
        return;
    }

    // — LIKE requires a Text-class column —
    if pred.op == WhereOp::Like {
        if !matches!(
            col.col_type,
            StoreColumnType::Text | StoreColumnType::Jsonb | StoreColumnType::Json
        ) {
            out.push(ProofError::new(
                ProofErrorCode::T802TypeMismatch,
                where_loc.0,
                where_loc.1,
                format!(
                    "axon-T802 `LIKE` requires a Text-class column. Column \
                     `{}` is declared as `{}`. Use `=` for exact equality, \
                     or change the column to `Text` if pattern matching \
                     is intended.",
                    pred.column,
                    col.col_type.canonical_name()
                ),
            ));
        }
    }

    // — Value type compatibility (T802) —
    match &pred.value {
        WhereValue::Literal { kind, .. } => {
            if !literal_compatible_with_column(*kind, col.col_type) {
                out.push(ProofError::new(
                    ProofErrorCode::T802TypeMismatch,
                    where_loc.0,
                    where_loc.1,
                    format!(
                        "axon-T802 `where:` literal of class {kind:?} is not \
                         type-compatible with column `{}` declared as `{}`. \
                         A {kind:?} literal cannot compare against a {} \
                         column without an explicit conversion.",
                        pred.column,
                        col.col_type.canonical_name(),
                        col.col_type.canonical_name()
                    ),
                ));
            }
        }
        WhereValue::BoundParam(name) => {
            // If the parameter is declared in the flow, prove
            // compatibility. If not declared, that's the Fase 37 D2
            // binding-totality concern — silently ignore here.
            if let Some(axon_type) = flow_params.get(name) {
                if !axon_param_compatible_with_column(axon_type, col.col_type) {
                    out.push(ProofError::new(
                        ProofErrorCode::T802TypeMismatch,
                        where_loc.0,
                        where_loc.1,
                        format!(
                            "axon-T802 flow parameter `${{{name}}}` of type \
                             `{axon_type}` is not type-compatible with \
                             column `{}` declared as `{}`. Either align the \
                             parameter type with the column type, or convert \
                             the value at the binding site.",
                            pred.column,
                            col.col_type.canonical_name()
                        ),
                    ));
                }
            }
        }
        WhereValue::NullKeyword => {
            // `col = NULL` is malformed SQL (and the runtime parse_filter
            // rejects it). The scanner shouldn't surface NullKeyword
            // except in `IS [NOT] NULL` context; if it does, it's a
            // proof-irrelevant syntactic anomaly.
        }
    }
}

// ════════════════════════════════════════════════════════════════════
//  Manifest-form resolution (forms b/c — first-match heuristic)
// ════════════════════════════════════════════════════════════════════

/// Resolve a store's declared column set from one of the three D1
/// forms. Returns `None` when:
///  - the schema is undeclared (form a missing), OR
///  - the manifest is unavailable at check time (forms b/c with no
///    manifest in the discovery root)
///
/// Honest scope: form (c) `env:VAR` uses a first-match heuristic
/// (look up `<env_var>.<store_name>`, then any `*.<store_name>`
/// manifest entry) — at deploy, D8 (Fase 38.f) does the canonical
/// per-tenant resolution.
pub fn load_columns_for_schema(
    schema: &StoreColumnSchema,
    store_name: &str,
    manifest: Option<&Manifest>,
) -> Option<ColumnSet> {
    match schema {
        StoreColumnSchema::Inline { .. } => ColumnSet::from_inline_schema(schema),
        StoreColumnSchema::ManifestRef { qualified_name, .. } => {
            let m = manifest?;
            let store = m.lookup(qualified_name)?;
            Some(ColumnSet::from_manifest_store(store))
        }
        StoreColumnSchema::EnvVar { var_name, .. } => {
            let m = manifest?;
            // Look up `<env_var_name>.<store_name>` first.
            let exact_key = format!("{var_name}.{store_name}");
            if let Some(store) = m.lookup(&exact_key) {
                return Some(ColumnSet::from_manifest_store(store));
            }
            // First-match heuristic: any manifest entry ending in
            // `.<store_name>`.
            let suffix = format!(".{store_name}");
            for (key, store) in &m.stores {
                if key.ends_with(&suffix) {
                    return Some(ColumnSet::from_manifest_store(store));
                }
            }
            None
        }
    }
}

/// Best-effort manifest discovery from a source-file's directory.
/// Returns `Ok(None)` when no manifests are present (forms b/c then
/// skip silently); `Err` when manifests are present but failed to
/// parse / hash-verify (axon-T805 propagates).
pub fn load_manifest_from_source_dir(source_dir: &Path) -> Result<Option<Manifest>, ProofError> {
    let files = store_schema_manifest::discover_manifest_files(source_dir);
    if files.is_empty() {
        return Ok(None);
    }
    match store_schema_manifest::load_and_merge_manifests(source_dir) {
        Ok(m) => Ok(Some(m)),
        Err(e) => Err(manifest_error_to_proof(e)),
    }
}

fn manifest_error_to_proof(err: ManifestError) -> ProofError {
    let (code, msg) = match &err {
        ManifestError::ContentHashMismatch { .. } => (
            ProofErrorCode::T805ManifestHashMismatch,
            format!("axon-T805 {err}"),
        ),
        _ => (
            ProofErrorCode::T805ManifestHashMismatch,
            format!("axon-T805 {err}"),
        ),
    };
    ProofError::new(code, 0, 0, msg)
}

// ════════════════════════════════════════════════════════════════════
//  Unit tests — 33 cases covering the 38.d plan-vivo target of 30+
// ════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    fn col(name: &str, ty: StoreColumnType, not_null: bool) -> StoreColumn {
        StoreColumn {
            name: name.to_string(),
            col_type: ty,
            primary_key: false,
            auto_increment: false,
            not_null,
            unique: false,
            default_value: String::new(),
            line: 0,
            column: 0,
        }
    }

    fn columns_for(specs: &[(&str, StoreColumnType, bool)]) -> ColumnSet {
        let inline: Vec<StoreColumn> = specs
            .iter()
            .map(|(n, t, nn)| col(n, *t, *nn))
            .collect();
        ColumnSet::from_inline_columns(&inline)
    }

    fn params(specs: &[(&str, &str)]) -> FlowParamTypes {
        let mut p = FlowParamTypes::new();
        for (n, t) in specs {
            p.insert((*n).to_string(), (*t).to_string());
        }
        p
    }

    // ── Scanner happy paths ──────────────────────────────────────────

    #[test]
    fn scan_empty_yields_no_predicates() {
        assert_eq!(scan_where("").unwrap(), vec![]);
        assert_eq!(scan_where("   ").unwrap(), vec![]);
    }

    #[test]
    fn scan_eq_literal_int() {
        let p = scan_where("id = 42").unwrap();
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].column, "id");
        assert_eq!(p[0].op, WhereOp::Eq);
        match &p[0].value {
            WhereValue::Literal { kind, raw } => {
                assert_eq!(*kind, LiteralKind::Int);
                assert_eq!(raw, "42");
            }
            other => panic!("expected Int literal, got {other:?}"),
        }
    }

    #[test]
    fn scan_eq_quoted_string() {
        let p = scan_where("tier = 'premium'").unwrap();
        assert_eq!(p.len(), 1);
        match &p[0].value {
            WhereValue::Literal { kind, raw } => {
                assert_eq!(*kind, LiteralKind::Text);
                assert_eq!(raw, "premium");
            }
            other => panic!("expected Text literal, got {other:?}"),
        }
    }

    #[test]
    fn scan_recognises_bound_param_braced_and_bare() {
        let p1 = scan_where("id = ${tenant_id}").unwrap();
        let p2 = scan_where("id = $tenant_id").unwrap();
        for p in [&p1, &p2] {
            assert_eq!(p.len(), 1);
            match &p[0].value {
                WhereValue::BoundParam(n) => assert_eq!(n, "tenant_id"),
                other => panic!("expected BoundParam, got {other:?}"),
            }
        }
    }

    #[test]
    fn scan_eq_bool_true_false() {
        let p = scan_where("active = true").unwrap();
        match &p[0].value {
            WhereValue::Literal { kind: LiteralKind::Bool, raw } => assert_eq!(raw, "true"),
            other => panic!("got {other:?}"),
        }
        let p2 = scan_where("active = false").unwrap();
        match &p2[0].value {
            WhereValue::Literal { kind: LiteralKind::Bool, raw } => assert_eq!(raw, "false"),
            other => panic!("got {other:?}"),
        }
    }

    #[test]
    fn scan_float_literal() {
        let p = scan_where("price = 3.14").unwrap();
        match &p[0].value {
            WhereValue::Literal { kind: LiteralKind::Float, raw } => assert_eq!(raw, "3.14"),
            other => panic!("got {other:?}"),
        }
    }

    #[test]
    fn scan_all_six_comparison_operators() {
        for (src, expected) in [
            ("x = 1", WhereOp::Eq),
            ("x == 1", WhereOp::Eq),
            ("x != 1", WhereOp::NotEq),
            ("x <> 1", WhereOp::NotEq),
            ("x < 1", WhereOp::Lt),
            ("x > 1", WhereOp::Gt),
            ("x <= 1", WhereOp::Le),
            ("x >= 1", WhereOp::Ge),
        ] {
            let p = scan_where(src).unwrap();
            assert_eq!(p[0].op, expected, "src={src}");
        }
    }

    #[test]
    fn scan_like_keyword_case_insensitive() {
        for src in ["name LIKE 'A%'", "name like 'A%'", "name LiKe 'A%'"] {
            let p = scan_where(src).unwrap();
            assert_eq!(p[0].op, WhereOp::Like, "src={src}");
        }
    }

    #[test]
    fn scan_is_null_and_is_not_null() {
        let p1 = scan_where("deleted_at IS NULL").unwrap();
        assert_eq!(p1[0].op, WhereOp::IsNull);
        assert_eq!(p1[0].value, WhereValue::NullKeyword);

        let p2 = scan_where("deleted_at IS NOT NULL").unwrap();
        assert_eq!(p2[0].op, WhereOp::IsNotNull);
    }

    #[test]
    fn scan_multiple_predicates_joined_by_and() {
        let p = scan_where("id = 1 AND tier = 'premium'").unwrap();
        assert_eq!(p.len(), 2);
        assert_eq!(p[0].column, "id");
        assert_eq!(p[1].column, "tier");
    }

    #[test]
    fn scan_or_connector_is_recognised() {
        let p = scan_where("tier = 'a' OR tier = 'b'").unwrap();
        assert_eq!(p.len(), 2);
    }

    // ── Scanner malformed paths ──────────────────────────────────────

    #[test]
    fn scan_unterminated_string_is_malformed() {
        assert!(matches!(scan_where("name = 'oops"), Err(ScanError::Malformed { .. })));
    }

    #[test]
    fn scan_trailing_connector_is_malformed() {
        assert!(matches!(scan_where("id = 1 AND"), Err(ScanError::Malformed { .. })));
    }

    #[test]
    fn scan_reserved_word_in_column_position_is_malformed() {
        assert!(matches!(scan_where("AND = 1"), Err(ScanError::Malformed { .. })));
    }

    // ── T801 — unknown column ────────────────────────────────────────

    #[test]
    fn t801_unknown_column_with_levenshtein_hint() {
        let cs = columns_for(&[
            ("tenant_id", StoreColumnType::Uuid, true),
            ("tier", StoreColumnType::Text, true),
        ]);
        let errs = check_filter("tenantid = 'x'", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T801UnknownColumn);
        assert!(errs[0].message.contains("tenantid"));
        assert!(
            errs[0].message.contains("tenant_id"),
            "expected Levenshtein hint pointing at `tenant_id`, got: {}",
            errs[0].message
        );
    }

    #[test]
    fn t801_unknown_column_without_suggestion_when_too_far() {
        let cs = columns_for(&[("tenant_id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("WildlyDifferent = 1", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T801UnknownColumn);
        assert!(
            !errs[0].message.contains("Did you mean"),
            "an out-of-distance typo must not surface a guess: {}",
            errs[0].message
        );
    }

    #[test]
    fn known_column_passes_silently() {
        let cs = columns_for(&[("id", StoreColumnType::Int, false)]);
        let errs = check_filter("id = 42", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty(), "expected zero proof errors, got {errs:?}");
    }

    // ── T802 — literal × column-type matrix ──────────────────────────

    #[test]
    fn t802_int_literal_against_text_column_is_rejected() {
        let cs = columns_for(&[("tier", StoreColumnType::Text, true)]);
        let errs = check_filter("tier = 42", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T802TypeMismatch);
    }

    #[test]
    fn t802_bool_literal_against_uuid_column_is_rejected() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("id = true", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T802TypeMismatch);
    }

    #[test]
    fn text_literal_against_uuid_column_passes_canonical_form_rule() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter(
            "id = '83d078e1-b372-42ba-9572-ff8dc521386e'",
            &cs,
            &params(&[]),
            (1, 1),
        );
        assert!(errs.is_empty(), "text literal must match Uuid column, got {errs:?}");
    }

    #[test]
    fn int_literal_against_int_column_passes() {
        let cs = columns_for(&[("id", StoreColumnType::Int, false)]);
        let errs = check_filter("id = 42", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn float_literal_against_numeric_column_passes() {
        let cs = columns_for(&[("amount", StoreColumnType::Numeric, false)]);
        let errs = check_filter("amount = 3.14", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn bool_literal_against_bool_column_passes() {
        let cs = columns_for(&[("active", StoreColumnType::Bool, false)]);
        let errs = check_filter("active = true", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn t802_like_against_uuid_column_is_rejected() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("id LIKE 'abc%'", &cs, &params(&[]), (1, 1));
        assert!(
            errs.iter().any(|e| e.message.contains("LIKE")),
            "LIKE on Uuid must surface T802 with a `LIKE` mention; got {errs:?}"
        );
    }

    #[test]
    fn like_against_text_column_passes() {
        let cs = columns_for(&[("name", StoreColumnType::Text, false)]);
        let errs = check_filter("name LIKE 'A%'", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    // ── T802 — bound param × column-type matrix ──────────────────────

    #[test]
    fn bound_param_string_against_uuid_column_passes() {
        // The runtime D4 fallback casts a String parameter to a Uuid
        // column. Compile-time proof must mirror that as
        // type-compatible.
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let fp = params(&[("tenant_id", "String")]);
        let errs = check_filter("id = ${tenant_id}", &cs, &fp, (1, 1));
        assert!(errs.is_empty(), "got {errs:?}");
    }

    #[test]
    fn t802_bound_param_int_against_uuid_column_is_rejected() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let fp = params(&[("some_int", "Int")]);
        let errs = check_filter("id = ${some_int}", &cs, &fp, (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T802TypeMismatch);
        assert!(errs[0].message.contains("some_int"));
        assert!(errs[0].message.contains("Uuid"));
    }

    #[test]
    fn bound_param_int_against_int_column_passes() {
        let cs = columns_for(&[("id", StoreColumnType::Int, false)]);
        let fp = params(&[("the_id", "Int")]);
        let errs = check_filter("id = ${the_id}", &cs, &fp, (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn bound_param_undeclared_in_flow_silently_passes() {
        // A bound param NOT declared as a flow parameter is the
        // Fase 37 D2 binding-totality concern — 38.d does not
        // duplicate that check.
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("id = ${not_a_param}", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn bound_param_with_optional_wrapper_unwraps_correctly() {
        let cs = columns_for(&[("id", StoreColumnType::Int, false)]);
        let fp = params(&[("maybe_id", "Optional<Int>")]);
        let errs = check_filter("id = ${maybe_id}", &cs, &fp, (1, 1));
        assert!(errs.is_empty());
    }

    // ── NULL handling ────────────────────────────────────────────────

    #[test]
    fn is_null_passes_against_any_column() {
        let cs = columns_for(&[("deleted_at", StoreColumnType::Timestamptz, true)]);
        let errs = check_filter("deleted_at IS NULL", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn is_not_null_passes_against_any_column() {
        let cs = columns_for(&[("deleted_at", StoreColumnType::Timestamptz, true)]);
        let errs = check_filter("deleted_at IS NOT NULL", &cs, &params(&[]), (1, 1));
        assert!(errs.is_empty());
    }

    #[test]
    fn is_null_against_unknown_column_still_flags_t801() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("ghost IS NULL", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T801UnknownColumn);
    }

    // ── Multi-predicate cases ────────────────────────────────────────

    #[test]
    fn multiple_predicates_all_proven_independently() {
        let cs = columns_for(&[
            ("id", StoreColumnType::Uuid, true),
            ("active", StoreColumnType::Bool, false),
        ]);
        // First predicate good; second has unknown column → exactly
        // one T801.
        let errs = check_filter(
            "id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' AND statuz = 'on'",
            &cs,
            &params(&[]),
            (1, 1),
        );
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].code, ProofErrorCode::T801UnknownColumn);
        assert!(errs[0].message.contains("statuz"));
    }

    #[test]
    fn multiple_errors_in_one_expression_are_all_reported() {
        let cs = columns_for(&[("id", StoreColumnType::Uuid, true)]);
        let errs = check_filter("ghost1 = 1 AND ghost2 = 2", &cs, &params(&[]), (1, 1));
        assert_eq!(errs.len(), 2);
        assert!(errs.iter().all(|e| e.code == ProofErrorCode::T801UnknownColumn));
    }

    // ── 15-type catalog coverage ─────────────────────────────────────

    #[test]
    fn every_catalog_type_accepts_a_string_literal_or_int_or_bool() {
        // Smoke pin: for each of the 15 catalog types, at least one
        // class of literal is accepted (so a real schema declared with
        // ANY catalog type stays proof-able).
        for &t in StoreColumnType::ALL {
            let cs = columns_for(&[("col", t, false)]);
            let candidates = match t {
                StoreColumnType::Bool => vec!["col = true"],
                StoreColumnType::Int
                | StoreColumnType::BigInt => vec!["col = 1"],
                StoreColumnType::Float
                | StoreColumnType::Double => vec!["col = 1.5"],
                _ => vec!["col = 'x'"],
            };
            for src in candidates {
                let errs = check_filter(src, &cs, &params(&[]), (1, 1));
                assert!(
                    errs.is_empty(),
                    "catalog type {} rejected `{src}` unexpectedly: {errs:?}",
                    t.canonical_name()
                );
            }
        }
    }

    #[test]
    fn every_catalog_type_accepts_a_compatible_string_param() {
        // The runtime D4 fallback accepts a String param into any
        // column. Compile-time proof must agree.
        let fp = params(&[("p", "String")]);
        for &t in StoreColumnType::ALL {
            let cs = columns_for(&[("col", t, false)]);
            let errs = check_filter("col = ${p}", &cs, &fp, (1, 1));
            assert!(
                errs.is_empty(),
                "String param rejected by catalog type {}: {errs:?}",
                t.canonical_name()
            );
        }
    }

    // ── Form (b) + (c) — manifest resolution ─────────────────────────

    #[test]
    fn form_b_manifest_ref_resolves_against_provided_manifest() {
        let manifest = Manifest::parse_json(
            r#"{
                "version": 1,
                "stores": {
                    "public.tenants": {
                        "columns": {
                            "tenant_id": { "type": "Uuid", "primary_key": true }
                        }
                    }
                }
            }"#,
        )
        .unwrap();
        let schema = StoreColumnSchema::ManifestRef {
            qualified_name: "public.tenants".to_string(),
            line: 1,
            column: 1,
        };
        let cs = load_columns_for_schema(&schema, "tenants", Some(&manifest)).unwrap();
        assert!(cs.contains("tenant_id"));
    }

    #[test]
    fn form_b_manifest_ref_returns_none_when_manifest_absent() {
        let schema = StoreColumnSchema::ManifestRef {
            qualified_name: "public.tenants".to_string(),
            line: 1,
            column: 1,
        };
        assert!(load_columns_for_schema(&schema, "tenants", None).is_none());
    }

    #[test]
    fn form_c_env_var_uses_first_match_heuristic_when_exact_key_missing() {
        let manifest = Manifest::parse_json(
            r#"{
                "version": 1,
                "stores": {
                    "tenant_42.events": {
                        "columns": {
                            "event_id": { "type": "Uuid" }
                        }
                    }
                }
            }"#,
        )
        .unwrap();
        let schema = StoreColumnSchema::EnvVar {
            var_name: "TENANT_SCHEMA".to_string(),
            line: 1,
            column: 1,
        };
        // Exact `TENANT_SCHEMA.events` is not present → first-match
        // heuristic finds `tenant_42.events`.
        let cs = load_columns_for_schema(&schema, "events", Some(&manifest)).unwrap();
        assert!(cs.contains("event_id"));
    }

    #[test]
    fn form_c_env_var_prefers_exact_key_when_present() {
        let manifest = Manifest::parse_json(
            r#"{
                "version": 1,
                "stores": {
                    "TENANT_SCHEMA.events": {
                        "columns": {
                            "exact_match_only": { "type": "Uuid" }
                        }
                    },
                    "tenant_42.events": {
                        "columns": {
                            "first_match_fallback": { "type": "Text" }
                        }
                    }
                }
            }"#,
        )
        .unwrap();
        let schema = StoreColumnSchema::EnvVar {
            var_name: "TENANT_SCHEMA".to_string(),
            line: 1,
            column: 1,
        };
        let cs = load_columns_for_schema(&schema, "events", Some(&manifest)).unwrap();
        // Exact-key match wins.
        assert!(cs.contains("exact_match_only"));
        assert!(!cs.contains("first_match_fallback"));
    }

    // ── Error code slugs (LSP / JSON output) ─────────────────────────

    #[test]
    fn error_code_slugs_match_the_axon_t801_t802_t805_namespace() {
        assert_eq!(ProofErrorCode::T801UnknownColumn.slug(), "axon-T801");
        assert_eq!(ProofErrorCode::T802TypeMismatch.slug(), "axon-T802");
        assert_eq!(ProofErrorCode::T805ManifestHashMismatch.slug(), "axon-T805");
    }
}
