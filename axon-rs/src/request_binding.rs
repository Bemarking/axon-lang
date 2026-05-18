//! §Fase 37 — The Request Binding Contract (runtime delivery).
//!
//! An `axonendpoint` declares `body: T` (the typed request body) and
//! `execute: F` (a flow with declared parameters). The contract: the
//! request body's fields populate F's parameters — BY NAME (D1).
//!
//! Only DECLARED flow parameters bind (D4): a body field that matches
//! no parameter is NOT silently injected into the interpolation
//! scope, so the compile-time totality check (37.c / D2) stays the
//! single gate on what a `${x}` can resolve to — a typo'd `${tenat}`
//! is a missing binding, never a silently-empty surprise.
//!
//! This module is the runtime delivery, consumed by BOTH execution
//! paths — the streaming dispatcher (`DispatchCtx.let_bindings`) and
//! the synchronous runner (`ExecContext`) — so an `axonendpoint`'s
//! `transport: sse` and `transport: json` routes bind identically.

use crate::ir_nodes::IRFlow;

/// Bind a parsed JSON request body to a flow's declared parameters.
///
/// For each parameter `p` of `flow`, if `body` is a JSON object
/// carrying a field named `p.name`, that field's value is bound to
/// `p.name` (D1 — by name). A body field that matches no declared
/// parameter is ignored (D4). The result is ordered by the flow's
/// parameter declaration order — deterministic for tests and the
/// 37.g property pass.
///
/// `body` is `None` (or a non-object JSON value) for a request with
/// no body, or a body that is a bare scalar / array — in every such
/// case the binding is empty and the flow runs with whatever bindings
/// its own `let` statements and step outputs produce (D5: a flow with
/// no parameters behind an endpoint with no `body:` is unaffected).
pub fn bind_request_body(
    flow: &IRFlow,
    body: Option<&serde_json::Value>,
) -> Vec<(String, String)> {
    let Some(serde_json::Value::Object(fields)) = body else {
        return Vec::new();
    };
    flow.parameters
        .iter()
        .filter_map(|param| {
            fields
                .get(&param.name)
                .map(|value| (param.name.clone(), binding_string(value)))
        })
        .collect()
}

/// Stringify a JSON value for the `String`-valued interpolation map
/// (`${name}` substitution is textual).
///
/// A JSON string binds to its raw contents (no surrounding quotes —
/// the value, not its JSON literal); `null` binds to the empty
/// string; a number / boolean binds to its canonical JSON form
/// (`42`, `true`). An array / object binds to its compact JSON form —
/// a structured parameter is honest future scope (the 37.c totality
/// check names a structured parameter explicitly rather than this
/// path binding it silently), but binding the compact JSON keeps the
/// function total and panic-free over every parsed body.
fn binding_string(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Null => String::new(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir_nodes::{IRFlow, IRParameter};

    fn param(name: &str) -> IRParameter {
        IRParameter {
            node_type: "parameter",
            source_line: 0,
            source_column: 0,
            name: name.into(),
            type_name: "String".into(),
            generic_param: String::new(),
            optional: false,
        }
    }

    fn flow_with_params(names: &[&str]) -> IRFlow {
        IRFlow {
            node_type: "flow",
            source_line: 0,
            source_column: 0,
            name: "F".into(),
            parameters: names.iter().map(|n| param(n)).collect(),
            return_type_name: "Unit".into(),
            return_type_generic: String::new(),
            return_type_optional: false,
            steps: Vec::new(),
            edges: Vec::new(),
            execution_levels: Vec::new(),
        }
    }

    #[test]
    fn binds_each_declared_parameter_by_name() {
        let flow = flow_with_params(&["message", "tenant_id"]);
        let body = serde_json::json!({
            "message": "hello",
            "tenant_id": "83d078e1-b372-42ba-9572-ff8dc521386e",
        });
        let bound = bind_request_body(&flow, Some(&body));
        assert_eq!(
            bound,
            vec![
                ("message".into(), "hello".into()),
                (
                    "tenant_id".into(),
                    "83d078e1-b372-42ba-9572-ff8dc521386e".into()
                ),
            ],
            "D1 — each declared parameter binds from its same-named body field"
        );
    }

    #[test]
    fn d4_an_undeclared_body_field_is_not_bound() {
        let flow = flow_with_params(&["message"]);
        let body = serde_json::json!({ "message": "hi", "extra": "ignored" });
        let bound = bind_request_body(&flow, Some(&body));
        assert_eq!(
            bound,
            vec![("message".into(), "hi".into())],
            "D4 — a body field with no matching declared parameter is \
             NOT bound; the contract stays tight"
        );
    }

    #[test]
    fn an_uncovered_parameter_simply_does_not_bind() {
        // D2 (37.c) makes this a compile error; at runtime the binding
        // is just absent — never a panic.
        let flow = flow_with_params(&["message", "session_id"]);
        let body = serde_json::json!({ "message": "hi" });
        let bound = bind_request_body(&flow, Some(&body));
        assert_eq!(bound, vec![("message".into(), "hi".into())]);
    }

    #[test]
    fn scalar_values_bind_as_their_string_form() {
        let flow = flow_with_params(&["s", "n", "b", "z"]);
        let body = serde_json::json!({
            "s": "raw", "n": 42, "b": true, "z": null,
        });
        let bound = bind_request_body(&flow, Some(&body));
        assert_eq!(
            bound,
            vec![
                ("s".into(), "raw".into()),   // string: no quotes
                ("n".into(), "42".into()),    // number: canonical
                ("b".into(), "true".into()),  // bool: canonical
                ("z".into(), String::new()),  // null: empty
            ]
        );
    }

    #[test]
    fn no_body_or_non_object_body_binds_nothing() {
        let flow = flow_with_params(&["message"]);
        assert!(bind_request_body(&flow, None).is_empty());
        assert!(bind_request_body(&flow, Some(&serde_json::json!("bare"))).is_empty());
        assert!(bind_request_body(&flow, Some(&serde_json::json!([1, 2]))).is_empty());
    }

    #[test]
    fn a_flow_with_no_parameters_binds_nothing() {
        let flow = flow_with_params(&[]);
        let body = serde_json::json!({ "message": "hi" });
        assert!(
            bind_request_body(&flow, Some(&body)).is_empty(),
            "D5 — a parameter-less flow is unaffected by any body"
        );
    }
}
