//! §Fase 58.d.2 (D3) — the type-checker validates an
//! `apply: <Tool> given: <struct>` splat: the `given:` struct's fields
//! auto-map onto the tool's declared `parameters:` schema BY NAME, with
//! exact name + type validation. This is the step-`apply:` half of the
//! §58.d tool-call soundness check (the keyword form `use Tool(k = v, …)`
//! was the §58.d half). A malformed splat is CALLER blame (CT-2) at
//! compile time, before any dispatch.

use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn errors(src: &str) -> Vec<String> {
    let tokens = Lexer::new(src, "t.axon").tokenize().expect("lex");
    let prog = Parser::new(tokens).parse().expect("parse");
    TypeChecker::new(&prog)
        .check()
        .into_iter()
        .map(|e| e.message)
        .collect()
}

fn has(errs: &[String], needle: &str) -> bool {
    errs.iter().any(|e| e.contains(needle))
}

// A tool whose schema has two required params + one optional.
const TOOL: &str = r#"
tool CrmRadar {
    provider: http
    parameters: { company: String, max_results: Int, active: Bool? }
    output_type: CrmReport
}
type CrmReport { summary: String }
"#;

#[test]
fn valid_splat_typechecks_clean() {
    // The `req` struct supplies exactly the required params (+ matching
    // types); the optional `active` may be omitted.
    let src = format!(
        "{TOOL}
type LeadRequest {{ company: String, max_results: Int }}
flow Scan(req: LeadRequest) -> CrmReport {{
    step Render {{ given: req apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    let errs = errors(&src);
    assert!(errs.is_empty(), "a well-formed splat must type-check clean: {errs:?}");
}

#[test]
fn missing_required_param_is_caller_blame() {
    // The struct omits `max_results` (a required tool parameter).
    let src = format!(
        "{TOOL}
type LeadRequest {{ company: String }}
flow Scan(req: LeadRequest) -> CrmReport {{
    step Render {{ given: req apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    let errs = errors(&src);
    assert!(
        has(&errs, "does not supply required parameter 'max_results'"),
        "got: {errs:?}"
    );
}

#[test]
fn type_mismatch_is_caller_blame() {
    // `max_results` is declared `String` in the struct but `Int` in the
    // tool schema.
    let src = format!(
        "{TOOL}
type LeadRequest {{ company: String, max_results: String }}
flow Scan(req: LeadRequest) -> CrmReport {{
    step Render {{ given: req apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    let errs = errors(&src);
    assert!(
        has(&errs, "field 'max_results' has type String but tool 'CrmRadar' parameter 'max_results' expects Int"),
        "got: {errs:?}"
    );
}

#[test]
fn optional_param_may_be_omitted() {
    // The struct omits the OPTIONAL `active` — that is fine.
    let src = format!(
        "{TOOL}
type LeadRequest {{ company: String, max_results: Int }}
flow Scan(req: LeadRequest) -> CrmReport {{
    step Render {{ given: req apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    assert!(errors(&src).is_empty(), "omitting an optional param must be clean");
}

#[test]
fn extra_struct_fields_are_allowed() {
    // The struct carries MORE fields than the tool needs (`notes`). The
    // splat maps by name, so the richer caller struct is fine (lenient —
    // sound, no false positive).
    let src = format!(
        "{TOOL}
type LeadRequest {{ company: String, max_results: Int, notes: String }}
flow Scan(req: LeadRequest) -> CrmReport {{
    step Render {{ given: req apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    assert!(
        errors(&src).is_empty(),
        "extra struct fields must not be flagged (the splat maps by name)"
    );
}

#[test]
fn int_field_coerces_into_a_float_param() {
    let src = "
tool Calc { provider: http parameters: { ratio: Float } }
type Args { ratio: Int }
flow Run(a: Args) -> Any {
    step Do { given: a apply: Calc ask: \"go\" output: Any }
}";
    assert!(errors(src).is_empty(), "Int field into Float param must coerce clean");
}

#[test]
fn flow_apply_is_not_a_tool_splat() {
    // `apply: <Flow>` is flow composition, NOT a tool splat — even if the
    // given struct would not match a tool, no splat error fires.
    let src = "
type In { x: String }
type Out { y: String }
flow Helper(i: In) -> Out { step S { ask: \"go\" output: Out } }
flow Main(i: In) -> Out {
    step Compose { given: i apply: Helper ask: \"go\" output: Out }
}";
    let errs = errors(src);
    assert!(
        !errs.iter().any(|e| e.contains("does not supply required parameter")
            || e.contains("expects")),
        "a flow apply must not trigger tool-splat validation: {errs:?}"
    );
}

#[test]
fn schema_less_tool_is_skipped() {
    // A tool with no `parameters:` carries no contract — the splat skips
    // (D5 back-compat: the pre-§58 `apply: <Tool>` form is unaffected).
    let src = "
tool Plain { provider: http }
type Whatever { a: String, b: Int }
flow F(w: Whatever) -> Any {
    step S { given: w apply: Plain ask: \"go\" output: Any }
}";
    assert!(errors(src).is_empty(), "a schema-less tool splat must be skipped");
}

#[test]
fn unresolvable_given_is_skipped() {
    // `given:` is a literal — not a flow param / Step.output — so the
    // struct type is unknown → conservative skip (no false positive).
    let src = format!(
        "{TOOL}
flow Scan() -> CrmReport {{
    step Render {{ given: \"a literal\" apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    assert!(
        errors(&src).is_empty(),
        "an unresolvable `given:` must conservatively skip the splat check"
    );
}

#[test]
fn given_step_output_resolves_the_struct_type() {
    // `given: Prev.output` resolves to the prior step's declared output
    // type; a mismatch there is still caught.
    let src = format!(
        "{TOOL}
type Bundle {{ company: String, max_results: String }}
flow Scan(q: String) -> CrmReport {{
    step Prepare {{ ask: \"build\" output: Bundle }}
    step Render {{ given: Prepare.output apply: CrmRadar ask: \"go\" output: CrmReport }}
}}"
    );
    let errs = errors(&src);
    assert!(
        has(&errs, "field 'max_results' has type String but tool 'CrmRadar' parameter 'max_results' expects Int"),
        "a `given: Step.output` splat mismatch must be caught: {errs:?}"
    );
}
