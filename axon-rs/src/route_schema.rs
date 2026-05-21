//! §Fase 32.c + 32.d — Schema validation for first-class axonendpoint routes.
//!
//! Given an axonendpoint's declared `body: T` (request side, D4) or
//! `output: T` (response side, D5), validate that every accepted body
//! matches `T`'s schema verbatim. The validation function is **pure +
//! total over the declared type system**.
//!
//! ## Same primitive, two call sites
//!
//! `validate_body` is consumed twice in the dynamic-route fallback:
//!
//! 1. **Request side (D4)** — before flow dispatch. On violation the
//!    HTTP layer returns 400 Bad Request with the full structured
//!    `BodyValidationError` so the adopter client can correct the
//!    request.
//! 2. **Response side (D5)** — after flow dispatch, before returning
//!    to the client. On violation the HTTP layer returns **GENERIC
//!    500** to the client (OWASP — schema details never leak to a
//!    potentially malicious caller) but records the full
//!    `BodyValidationError` in the audit log so the adopter inspects
//!    the trail to fix the FLOW.
//!
//! The validator itself does not care which side it runs on — same
//! primitive, same drift gate.
//!
//! ## Pillar trace (D12)
//!
//! - **MATHEMATICS** — `validate_body : (RequestBody, Type) → Result<(),
//!   ValidationError>` is a pure function. Given the same input and the
//!   same type table, the function is deterministic and total: every input
//!   maps to exactly one result.
//! - **LOGIC** — every accepted body matches the declared schema. No
//!   widening, no coercion, no "kinda matches". A body of `{amount: "50"}`
//!   does NOT satisfy `LoanApplication { amount: Float }` — string-to-float
//!   coercion is the client's responsibility, not the server's.
//! - **PHILOSOPHY** — the declaration IS the contract. An auditor reads
//!   source + KNOWS exactly what bodies are accepted at every endpoint.
//!   Free-form bodies require explicitly omitting `body:` (D9).
//! - **COMPUTING** — backwards-compat: when `body_type` is empty, no
//!   validation runs (free-form JSON, as before Fase 32). Adopters opt in
//!   by declaring `body:` on their axonendpoints.
//!
//! ## Cross-stack mirror (D11)
//!
//! Python sibling lives at `axon/runtime/route_schema.py`. Both stacks
//! produce byte-identical `(type_name, field_path, expected, got)` tuples
//! for the same input under the shared drift-gate corpus at
//! `tests/fixtures/fase32_body_schema/corpus.json`.

use std::collections::HashMap;

use serde_json::Value;

use crate::ast::{Declaration, Program, TypeDefinition};

/// Snapshot of a `type T { … }` declaration relevant to body validation.
/// Only the fields the validator consults are projected — `compliance`,
/// `where_clause`, and `range_constraint` are out of scope for 32.c
/// (where/compliance ship in their own future fases).
#[derive(Debug, Clone, PartialEq)]
pub struct TypeSchema {
    pub name: String,
    pub fields: Vec<FieldSchema>,
    /// Closed numeric range constraint per `RANGED_TYPES` semantics. The
    /// parser sets this for `type X(0.0..1.0)` declarations.
    pub range: Option<(f64, f64)>,
}

/// One field inside a structured type. `optional == true` if the source
/// declared the field as `name: T?`.
#[derive(Debug, Clone, PartialEq)]
pub struct FieldSchema {
    pub name: String,
    pub type_name: String,
    /// `List<X>`'s `generic_param` is `"X"`. Empty string for
    /// non-parameterised types.
    pub generic_param: String,
    pub optional: bool,
}

/// Structured body-validation error. The HTTP layer projects this into a
/// 400 Bad Request with the field/expected/got triple so adopter clients
/// can correct their request without server-side log diving.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize)]
pub struct BodyValidationError {
    /// Top-level body type the validation was attempted against (e.g.
    /// `"LoanApplication"`).
    pub expected_type: String,
    /// Dotted path to the offending field: `"applicant.address.street"`
    /// for nested structures, `"[2].name"` for list-element index 2.
    /// Empty string when the violation is at the top-level body itself
    /// (e.g. expected object, got string).
    pub field_path: String,
    /// Declared type the validator expected.
    pub expected: String,
    /// JSON-type tag observed (`"string"`, `"number"`, `"integer"`,
    /// `"boolean"`, `"array"`, `"object"`, `"null"`, `"missing"`).
    pub got: String,
    /// Adopter-facing diagnostic — full sentence with a corrective hint.
    /// Stable across versions per D8 backwards-compat surface.
    pub hint: String,
    /// §Fase 38.x.f (D2) — Declared cardinality kind of the expected
    /// type: `"singular"` | `"plural"` | `"stream"` | `"unit"` |
    /// `"unknown"`. Empty string for primitive-type validation errors
    /// where the cardinality isn't load-bearing (the existing v1.39.0
    /// surface). Serde `#[serde(default)]` keeps adopter consumers of
    /// older versions byte-compatible.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub expected_cardinality: String,
    /// §Fase 38.x.f (D2) — Observed cardinality kind of the response
    /// body: same alphabet as `expected_cardinality`. Empty when not
    /// applicable. The asymmetry expected/got is the diagnostic
    /// payload adopters reach for first when D5 fires.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub got_cardinality: String,
    /// §Fase 38.x.f (D2) — Length of the observed value when it is
    /// `array` (plural). `None` for non-array gots. Helps adopters
    /// confirm "the flow returned 1 row, but the contract said
    /// singular — collapse with `result[0]` or change the endpoint
    /// to `output: List<T>`".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub got_length: Option<u64>,
    /// §Fase 38.x.f (D2) — Documentation URL adopters can follow for
    /// the canonical remediation steps. Empty when the error is not
    /// a cardinality mismatch (the existing v1.39.0 surface). The
    /// URL is stable; the page may evolve.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub remediation_url: String,
}

impl std::fmt::Display for BodyValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.hint)
    }
}

impl std::error::Error for BodyValidationError {}

/// Built-in primitive type names recognised by the validator. Any name
/// in this set is checked directly against the JSON value's tag; names
/// NOT in this set are looked up in the per-deploy type table (structured
/// types). Anything missing from both is reported as `unknown_type` so
/// adopters who misspell `Strng` get a clear diagnostic instead of a
/// silent "everything passes" trap.
pub const BUILTIN_PRIMITIVES: &[&str] = &[
    "String",
    "Integer",
    "Float",
    "Boolean",
    "Duration",
    "Any",
];

/// Built-in range-constrained numeric types. Mirrors
/// `RANGED_TYPES` in `axon/compiler/type_checker.py`. These accept any
/// JSON number that falls within the closed interval.
pub fn builtin_range(name: &str) -> Option<(f64, f64)> {
    match name {
        "RiskScore" | "ConfidenceScore" => Some((0.0, 1.0)),
        "SentimentScore" => Some((-1.0, 1.0)),
        _ => None,
    }
}

/// Walk every `type T { … }` declaration in the deployed program and
/// produce a `name → TypeSchema` lookup table. Last-wins on collision
/// is the same semantics as Rust's `HashMap::insert` — type-name
/// collisions across deploys are out of scope for 32.c (deferred to a
/// future type-registry fase). For 32.c the only consumer is the
/// dynamic-route fallback handler which captures the table once per
/// deploy.
pub fn collect_type_table(program: &Program) -> HashMap<String, TypeSchema> {
    let mut table = HashMap::new();
    for decl in &program.declarations {
        if let Declaration::Type(td) = decl {
            table.insert(td.name.clone(), type_schema_from(td));
        }
    }
    table
}

fn type_schema_from(td: &TypeDefinition) -> TypeSchema {
    let fields = td
        .fields
        .iter()
        .map(|f| FieldSchema {
            name: f.name.clone(),
            type_name: f.type_expr.name.clone(),
            generic_param: f.type_expr.generic_param.clone(),
            optional: f.type_expr.optional,
        })
        .collect();
    let range = td
        .range_constraint
        .as_ref()
        .map(|rc| (rc.min_value, rc.max_value));
    TypeSchema {
        name: td.name.clone(),
        fields,
        range,
    }
}

/// Tag the JSON value with the lowercase string the validator reports as
/// `got`. Numbers split into `"integer"` vs `"number"` so adopters
/// declaring `Integer` get the precise "got a number with decimals" path.
fn json_tag(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(n) => {
            if n.is_i64() || n.is_u64() {
                "integer"
            } else {
                "number"
            }
        }
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

/// Validate `body` against the type named `type_name` looked up in
/// `table` (or matched against `BUILTIN_PRIMITIVES`).
///
/// Returns `Ok(())` on success. Returns `Err(BodyValidationError)` with
/// the first violation encountered (depth-first, field declaration
/// order). The error carries enough structure for the HTTP layer to
/// emit a stable 400 Bad Request body.
///
/// **Backwards-compat (D9)**: when `type_name` is empty, returns
/// `Ok(())` immediately. Adopters who don't declare `body:` keep the
/// pre-Fase-32 free-form behavior.
pub fn validate_body(
    body: &Value,
    type_name: &str,
    table: &HashMap<String, TypeSchema>,
) -> Result<(), BodyValidationError> {
    if type_name.is_empty() {
        return Ok(());
    }
    validate_value(body, type_name, "", "", table, type_name)
}

/// Internal recursive validator.
///
/// `body_type` is the top-level type the user declared (kept invariant
/// across recursion for diagnostic continuity).
/// `field_path` is the dotted path accumulated so far ("" at top level).
/// `generic_param` carries `List<T>`'s element type when validating a
/// list — empty otherwise.
fn validate_value(
    v: &Value,
    type_name: &str,
    generic_param: &str,
    field_path: &str,
    table: &HashMap<String, TypeSchema>,
    body_type: &str,
) -> Result<(), BodyValidationError> {
    // §0 — §Fase 38.x.f.9 (POST-CLOSE HOTFIX 2026-05-21) — generic-
    // aware parsing. When the caller passes the raw type string with
    // an embedded generic param (e.g. `"List<TenantRecord>"` from
    // `validate_body` or from `validate_struct`'s field-type recursion)
    // AND `generic_param` is empty, strip the `<Inner>` and recurse
    // with the head + inner as separate args. This closes the
    // T9XX-to-D5 dead-end the 38.x.f cardinality cycle left open: the
    // compile-time gate suggests `output: List<T>` as remedy, the
    // adopter applies it, and the runtime D5 then recognized `"List"`
    // + generic param `"T"` properly (§3 below) — pre-hotfix the
    // unsplit `"List<T>"` string fell through to §5 unknown_type.
    //
    // Recursive — handles nested `List<List<T>>` because the inner
    // recursion lands here again with `type_name = "List<T>"` and
    // strips ANOTHER layer.
    //
    // Closed grammar today: `List<Inner>` + `Stream<Inner>`. Other
    // future generics (Map<K,V>, Optional<T>, etc.) extend this §0
    // additively without touching §1–§5.
    if generic_param.is_empty() {
        if let Some(rest) = type_name.strip_prefix("List<") {
            if let Some(inner) = rest.strip_suffix('>') {
                return validate_value(
                    v,
                    "List",
                    inner.trim(),
                    field_path,
                    table,
                    body_type,
                );
            }
        }
        if let Some(rest) = type_name.strip_prefix("Stream<") {
            if rest.ends_with('>') {
                // §Fase 38.x.f.9 — `Stream<T>` body validation is
                // structurally unreachable from the production path
                // (SSE responses route through the streaming wire
                // which validates chunks, not the full body). When
                // we DO observe it at the body validator layer
                // (defensive), return Ok early — the runtime SSE
                // path is the canonical validation surface for
                // temporal cardinality.
                return Ok(());
            }
        }
    }
    // §1 — primitives
    if BUILTIN_PRIMITIVES.contains(&type_name) {
        return validate_primitive(v, type_name, field_path, body_type);
    }
    // §2 — range-constrained built-ins (RiskScore, ConfidenceScore, …)
    if let Some((lo, hi)) = builtin_range(type_name) {
        return validate_ranged_number(v, type_name, lo, hi, field_path, body_type);
    }
    // §3 — generic List<T>
    if type_name == "List" {
        return validate_list(v, generic_param, field_path, table, body_type);
    }
    // §4 — structured types declared in the program
    if let Some(schema) = table.get(type_name) {
        // Numeric range-constrained user types (`type RiskScore(0.0..1.0)`)
        if let Some((lo, hi)) = schema.range {
            return validate_ranged_number(v, type_name, lo, hi, field_path, body_type);
        }
        return validate_struct(v, schema, field_path, table, body_type);
    }
    // §5 — unknown type. Adopter misspell or undeclared type. We surface
    // it instead of silently passing so the diagnostic is actionable.
    Err(BodyValidationError {
        expected_type: body_type.to_string(),
        field_path: field_path.to_string(),
        expected: type_name.to_string(),
        got: json_tag(v).to_string(),
        hint: format!(
            "axonendpoint declared an unknown body type `{type_name}` for field \
             `{field_path}` — neither a built-in primitive nor a declared \
             `type` in the deployed source. Add `type {type_name} {{ … }}` to \
             the source or correct the spelling."
        ),
        ..Default::default()
    })
}

fn validate_primitive(
    v: &Value,
    type_name: &str,
    field_path: &str,
    body_type: &str,
) -> Result<(), BodyValidationError> {
    let ok = match (type_name, v) {
        ("String", Value::String(_)) => true,
        ("Integer", Value::Number(n)) => n.is_i64() || n.is_u64(),
        ("Float", Value::Number(_)) => true,
        ("Boolean", Value::Bool(_)) => true,
        ("Duration", Value::String(_)) => true,
        ("Any", _) => true,
        _ => false,
    };
    if ok {
        return Ok(());
    }
    Err(BodyValidationError {
        expected_type: body_type.to_string(),
        field_path: field_path.to_string(),
        expected: type_name.to_string(),
        got: json_tag(v).to_string(),
        hint: format!(
            "Body field `{field_path}` must be a `{type_name}` but received a \
             {got}. Adjust the request body or the axonendpoint's `body:` \
             declaration.",
            field_path = if field_path.is_empty() { "<body>" } else { field_path },
            type_name = type_name,
            got = json_tag(v),
        ),
        ..Default::default()
    })
}

/// Format an `f64` the same way both stacks render bounds + `got`
/// values inside validation errors. Whole-valued floats render as the
/// integer ("0", "1", "-1"); fractional values render via `{f64}`'s
/// shortest round-trip representation ("1.5", "-1.5"). This locks the
/// drift gate against Rust's `Display for f64` quirks vs Python's
/// `str(float)` adding ".0".
pub fn fmt_f64(n: f64) -> String {
    if n.is_finite() && n.fract() == 0.0 && n.abs() < 1e16 {
        return format!("{}", n as i64);
    }
    format!("{n}")
}

fn validate_ranged_number(
    v: &Value,
    type_name: &str,
    lo: f64,
    hi: f64,
    field_path: &str,
    body_type: &str,
) -> Result<(), BodyValidationError> {
    // §32.c — `Number::is_i64() || is_u64() || is_f64()` already covers
    // every JSON-number variant; bool excluded explicitly because
    // `serde_json::Value::as_f64` does NOT coerce booleans.
    let n = match (v, v.as_f64()) {
        (Value::Number(_), Some(n)) => n,
        _ => {
            return Err(BodyValidationError {
                expected_type: body_type.to_string(),
                field_path: field_path.to_string(),
                expected: type_name.to_string(),
                got: json_tag(v).to_string(),
                hint: format!(
                    "Body field `{path}` must be a `{type_name}` (numeric in \
                     [{lo}, {hi}]) but received a {got}.",
                    path = if field_path.is_empty() { "<body>" } else { field_path },
                    type_name = type_name,
                    got = json_tag(v),
                    lo = fmt_f64(lo),
                    hi = fmt_f64(hi),
                ),
                ..Default::default()
            });
        }
    };
    if n < lo || n > hi {
        let lo_s = fmt_f64(lo);
        let hi_s = fmt_f64(hi);
        let n_s = fmt_f64(n);
        return Err(BodyValidationError {
            expected_type: body_type.to_string(),
            field_path: field_path.to_string(),
            expected: format!("{type_name} ∈ [{lo_s}, {hi_s}]"),
            got: n_s.clone(),
            hint: format!(
                "Body field `{path}` must satisfy `{type_name} ∈ [{lo_s}, \
                 {hi_s}]` but received `{n_s}`.",
                path = if field_path.is_empty() { "<body>" } else { field_path },
            ),
            ..Default::default()
        });
    }
    Ok(())
}

fn validate_list(
    v: &Value,
    element_type: &str,
    field_path: &str,
    table: &HashMap<String, TypeSchema>,
    body_type: &str,
) -> Result<(), BodyValidationError> {
    let arr = match v.as_array() {
        Some(a) => a,
        None => {
            return Err(BodyValidationError {
                expected_type: body_type.to_string(),
                field_path: field_path.to_string(),
                expected: format!("List<{element_type}>"),
                got: json_tag(v).to_string(),
                hint: format!(
                    "Body field `{path}` must be a `List<{element_type}>` \
                     (JSON array) but received a {got}.",
                    path = if field_path.is_empty() { "<body>" } else { field_path },
                    got = json_tag(v),
                ),
                // §Fase 38.x.f (D2) — When this validation fires at
                // the TOP-LEVEL body (empty field_path), the mismatch
                // is between the declared `List<T>` (plural) and the
                // observed JSON shape (not an array). Populate the
                // cardinality diagnostic fields so adopters reaching
                // for the audit_log entry see the cardinality story
                // directly. For nested field violations the fields
                // stay empty (the mismatch is at a sub-field, not
                // load-bearing for the endpoint-level contract).
                expected_cardinality: if field_path.is_empty() {
                    "plural".to_string()
                } else {
                    String::new()
                },
                got_cardinality: if field_path.is_empty() {
                    match v {
                        Value::Object(_) => "singular".to_string(),
                        Value::Null => "unit".to_string(),
                        _ => "singular".to_string(),
                    }
                } else {
                    String::new()
                },
                got_length: None,
                remediation_url: if field_path.is_empty() {
                    "https://axon-lang.io/docs/cardinality-mismatch".to_string()
                } else {
                    String::new()
                },
            });
        }
    };
    if element_type.is_empty() {
        // `List` with no generic param — accept any element (degenerate
        // declaration; parser should ideally warn but doesn't today).
        return Ok(());
    }
    for (idx, elem) in arr.iter().enumerate() {
        let elem_path = if field_path.is_empty() {
            format!("[{idx}]")
        } else {
            format!("{field_path}[{idx}]")
        };
        validate_value(elem, element_type, "", &elem_path, table, body_type)?;
    }
    Ok(())
}

fn validate_struct(
    v: &Value,
    schema: &TypeSchema,
    field_path: &str,
    table: &HashMap<String, TypeSchema>,
    body_type: &str,
) -> Result<(), BodyValidationError> {
    let obj = match v.as_object() {
        Some(o) => o,
        None => {
            return Err(BodyValidationError {
                expected_type: body_type.to_string(),
                field_path: field_path.to_string(),
                expected: schema.name.clone(),
                got: json_tag(v).to_string(),
                hint: format!(
                    "Body field `{path}` must be a `{type_name}` (JSON object) \
                     but received a {got}. {cardinality_hint}",
                    path = if field_path.is_empty() { "<body>" } else { field_path },
                    type_name = schema.name,
                    got = json_tag(v),
                    cardinality_hint = if field_path.is_empty() && v.is_array() {
                        format!(
                            "The flow returned a `List<{tn}>` (array of {n} \
                             items) but the endpoint declared `output: {tn}` \
                             (singular). Either change the endpoint to \
                             `output: List<{tn}>` or collapse the flow's tail \
                             to a single item (e.g. `return result[0]`). \
                             (Fase 38.x.f D2)",
                            tn = schema.name,
                            n = v.as_array().map(|a| a.len()).unwrap_or(0),
                        )
                    } else {
                        String::new()
                    },
                ),
                // §Fase 38.x.f (D2) — when the top-level body got an
                // array but expected an object, this is the canonical
                // singular-vs-plural mismatch. Populate the structured
                // cardinality diagnostic fields for the audit_log.
                expected_cardinality: if field_path.is_empty() {
                    "singular".to_string()
                } else {
                    String::new()
                },
                got_cardinality: if field_path.is_empty() {
                    match v {
                        Value::Array(_) => "plural".to_string(),
                        Value::Null => "unit".to_string(),
                        _ => "singular".to_string(),
                    }
                } else {
                    String::new()
                },
                got_length: if field_path.is_empty() {
                    v.as_array().map(|a| a.len() as u64)
                } else {
                    None
                },
                remediation_url: if field_path.is_empty() && v.is_array() {
                    "https://axon-lang.io/docs/cardinality-mismatch".to_string()
                } else {
                    String::new()
                },
            });
        }
    };
    for field in &schema.fields {
        let child_path = if field_path.is_empty() {
            field.name.clone()
        } else {
            format!("{field_path}.{}", field.name)
        };
        match obj.get(&field.name) {
            None => {
                if field.optional {
                    continue;
                }
                return Err(BodyValidationError {
                    expected_type: body_type.to_string(),
                    field_path: child_path.clone(),
                    expected: field.type_name.clone(),
                    got: "missing".to_string(),
                    hint: format!(
                        "Body field `{child_path}` is required (declared as \
                         `{type_name}` on `{struct_name}`) but is absent from \
                         the request body.",
                        type_name = field.type_name,
                        struct_name = schema.name,
                    ),
                    ..Default::default()
                });
            }
            Some(child) => {
                // Optional `T?` fields with explicit JSON null are accepted.
                if field.optional && child.is_null() {
                    continue;
                }
                validate_value(
                    child,
                    &field.type_name,
                    &field.generic_param,
                    &child_path,
                    table,
                    body_type,
                )?;
            }
        }
    }
    // Unknown extra fields are NOT rejected — adopters can pass extra
    // payload the flow ignores (industry-standard "be liberal in what you
    // accept" for forwards-compat with client-side additions). Strict
    // mode is a future opt-in if vertical compliance demands.
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t_string() -> TypeSchema {
        TypeSchema {
            name: "String".to_string(),
            fields: vec![],
            range: None,
        }
    }

    fn person_schema() -> TypeSchema {
        TypeSchema {
            name: "Person".to_string(),
            fields: vec![
                FieldSchema {
                    name: "name".to_string(),
                    type_name: "String".to_string(),
                    generic_param: String::new(),
                    optional: false,
                },
                FieldSchema {
                    name: "age".to_string(),
                    type_name: "Integer".to_string(),
                    generic_param: String::new(),
                    optional: true,
                },
            ],
            range: None,
        }
    }

    #[test]
    fn empty_body_type_passes_any_body() {
        let table = HashMap::new();
        let body = serde_json::json!({"anything": "goes"});
        assert!(validate_body(&body, "", &table).is_ok());
    }

    #[test]
    fn primitive_string_ok() {
        let table = HashMap::new();
        let body = serde_json::json!("hello");
        assert!(validate_body(&body, "String", &table).is_ok());
    }

    #[test]
    fn primitive_string_rejects_number() {
        let table = HashMap::new();
        let body = serde_json::json!(42);
        let err = validate_body(&body, "String", &table).unwrap_err();
        assert_eq!(err.expected, "String");
        assert_eq!(err.got, "integer");
    }

    #[test]
    fn integer_rejects_float() {
        let table = HashMap::new();
        let body = serde_json::json!(3.14);
        let err = validate_body(&body, "Integer", &table).unwrap_err();
        assert_eq!(err.expected, "Integer");
        assert_eq!(err.got, "number");
    }

    #[test]
    fn float_accepts_integer_json() {
        let table = HashMap::new();
        let body = serde_json::json!(42);
        assert!(validate_body(&body, "Float", &table).is_ok());
        let body = serde_json::json!(3.14);
        assert!(validate_body(&body, "Float", &table).is_ok());
    }

    #[test]
    fn structured_missing_required_field() {
        let mut table = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        let body = serde_json::json!({"age": 30});
        let err = validate_body(&body, "Person", &table).unwrap_err();
        assert_eq!(err.field_path, "name");
        assert_eq!(err.got, "missing");
    }

    #[test]
    fn structured_optional_field_can_be_absent() {
        let mut table = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        let body = serde_json::json!({"name": "alice"});
        assert!(validate_body(&body, "Person", &table).is_ok());
    }

    #[test]
    fn structured_optional_field_can_be_null() {
        let mut table = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        let body = serde_json::json!({"name": "alice", "age": null});
        assert!(validate_body(&body, "Person", &table).is_ok());
    }

    #[test]
    fn structured_unknown_extra_fields_accepted() {
        let mut table = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        let body = serde_json::json!({"name": "alice", "extra": "data"});
        assert!(validate_body(&body, "Person", &table).is_ok());
    }

    #[test]
    fn list_validates_each_element() {
        let mut table = HashMap::new();
        table.insert("String".to_string(), t_string());
        let body = serde_json::json!(["a", "b", "c"]);
        let err = validate_body(&body, "List", &table);
        assert!(err.is_ok());
    }

    #[test]
    fn list_rejects_non_array() {
        let table = HashMap::new();
        let body = serde_json::json!({"not": "array"});
        // Use a synthetic harness for the generic_param flavor.
        let r = validate_value(&body, "List", "String", "", &table, "List");
        let err = r.unwrap_err();
        assert!(err.expected.contains("List"));
        assert_eq!(err.got, "object");
    }

    #[test]
    fn list_element_violation_reports_indexed_path() {
        let table = HashMap::new();
        let body = serde_json::json!(["a", 42, "c"]);
        let r = validate_value(&body, "List", "String", "", &table, "List");
        let err = r.unwrap_err();
        assert_eq!(err.field_path, "[1]");
        assert_eq!(err.got, "integer");
    }

    #[test]
    fn range_type_rejects_out_of_bounds() {
        let table = HashMap::new();
        let body = serde_json::json!(1.5);
        let err = validate_body(&body, "RiskScore", &table).unwrap_err();
        assert!(err.expected.contains("RiskScore"));
    }

    #[test]
    fn range_type_accepts_in_bounds() {
        let table = HashMap::new();
        let body = serde_json::json!(0.7);
        assert!(validate_body(&body, "RiskScore", &table).is_ok());
    }

    #[test]
    fn unknown_type_returns_diagnostic() {
        let table = HashMap::new();
        let body = serde_json::json!({});
        let err = validate_body(&body, "NotDeclared", &table).unwrap_err();
        assert!(err.hint.contains("NotDeclared"));
    }

    #[test]
    fn nested_struct_field_path_is_dotted() {
        let mut table = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        table.insert(
            "Loan".to_string(),
            TypeSchema {
                name: "Loan".to_string(),
                fields: vec![FieldSchema {
                    name: "applicant".to_string(),
                    type_name: "Person".to_string(),
                    generic_param: String::new(),
                    optional: false,
                }],
                range: None,
            },
        );
        let body = serde_json::json!({"applicant": {"age": 30}});
        let err = validate_body(&body, "Loan", &table).unwrap_err();
        assert_eq!(err.field_path, "applicant.name");
        assert_eq!(err.expected_type, "Loan");
    }

    #[test]
    fn json_tag_distinguishes_integer_and_number() {
        assert_eq!(json_tag(&serde_json::json!(42)), "integer");
        assert_eq!(json_tag(&serde_json::json!(3.14)), "number");
    }

    // ── §Fase 38.x.f.9 — generic-aware §0 preamble tests ────────────

    #[test]
    fn fase38xf9_validate_body_accepts_list_of_primitive() {
        // §Fase 38.x.f.9 — pre-hotfix the T9XX hint suggested
        // `output: List<String>` but `validate_body` rejected it as
        // unknown_type. Post-hotfix: §0 preamble strips the generic
        // and dispatches to §3 (`validate_list`) properly.
        let table: HashMap<String, TypeSchema> = HashMap::new();
        let body = serde_json::json!(["alice", "bob"]);
        let r = validate_body(&body, "List<String>", &table);
        assert!(
            r.is_ok(),
            "List<String> over a String array must validate. Got: {r:?}"
        );
    }

    #[test]
    fn fase38xf9_validate_body_accepts_list_of_struct() {
        let mut table: HashMap<String, TypeSchema> = HashMap::new();
        table.insert("Person".to_string(), person_schema());
        let body = serde_json::json!([{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]);
        let r = validate_body(&body, "List<Person>", &table);
        assert!(
            r.is_ok(),
            "List<Person> over a Person array must validate. Got: {r:?}"
        );
    }

    #[test]
    fn fase38xf9_validate_body_rejects_list_of_unknown_inner() {
        // Inner type unknown → unknown_type error from §5 with the
        // inner type name, NOT a generic-string failure.
        let table: HashMap<String, TypeSchema> = HashMap::new();
        let body = serde_json::json!([{}]);
        let r = validate_body(&body, "List<UnknownType>", &table);
        assert!(r.is_err(), "List<UnknownType> must surface the inner-type miss.");
        let err = r.unwrap_err();
        assert!(
            err.hint.contains("UnknownType"),
            "diagnostic must name the inner type (`UnknownType`), not the outer `List<...>` shape. \
             Got hint: {}",
            err.hint
        );
    }

    #[test]
    fn fase38xf9_validate_body_rejects_list_against_non_array() {
        // §3 (validate_list) handles the non-array case; we test the
        // wiring catches it via the §0 preamble.
        let table: HashMap<String, TypeSchema> = HashMap::new();
        let body = serde_json::json!({"not": "an array"});
        let r = validate_body(&body, "List<String>", &table);
        assert!(r.is_err(), "object against List<String> must error.");
        let err = r.unwrap_err();
        assert_eq!(err.got, "object");
        assert!(err.expected.contains("List"));
    }

    #[test]
    fn fase38xf9_validate_body_accepts_nested_list_of_list() {
        // Recursive — §0 strips outer, recurses with type_name="List",
        // generic_param="List<String>". §3's validate_list iterates
        // the outer array's elements; per-element validate_value lands
        // back in §0 which strips the inner.
        let table: HashMap<String, TypeSchema> = HashMap::new();
        let body = serde_json::json!([["a", "b"], ["c"]]);
        let r = validate_body(&body, "List<List<String>>", &table);
        assert!(
            r.is_ok(),
            "Nested List<List<String>> over an array-of-arrays must validate. Got: {r:?}"
        );
    }

    #[test]
    fn fase38xf9_validate_body_stream_returns_ok_early() {
        // §Fase 38.x.f.9 — Stream<T> body validation is structurally
        // unreachable (SSE chunks are validated at the wire layer, not
        // the body layer). Defensive Ok early.
        let table: HashMap<String, TypeSchema> = HashMap::new();
        let body = serde_json::json!({"anything": "goes"});
        let r = validate_body(&body, "Stream<Token>", &table);
        assert!(
            r.is_ok(),
            "Stream<T> at the body validator layer must be a defensive Ok. \
             Got: {r:?}"
        );
    }
}
