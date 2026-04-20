//! AXON Audit Evidence Engine — ControlImplementationStatement
//!
//! Direct port of `axon/runtime/esk/audit_engine/control_statements.py`.
//!
//! For every control in a framework, produce the auditor-ready
//! "Implementation Statement" that an organization typically writes
//! by hand during the audit-prep cycle. AXON can pre-populate most of
//! these from the framework catalog + IR program inspection.

#![allow(dead_code)]

use std::collections::HashMap;

use serde_json::{Map, Value};

use crate::ir_nodes::IRProgram;

use super::frameworks::{Control, EvidenceKind, FrameworkId, controls_for};
use super::gap_analyzer::analyze_gaps;

// ═══════════════════════════════════════════════════════════════════
//  Owner + frequency defaults per evidence kind
// ═══════════════════════════════════════════════════════════════════

fn owner_for_kind(kind: EvidenceKind) -> &'static str {
    match kind {
        EvidenceKind::CompileTime         => "Engineering (Language Team)",
        EvidenceKind::RuntimeInvariant    => "Engineering (Runtime Team)",
        EvidenceKind::AutomatedArtifact   => "Engineering (CI/CD)",
        EvidenceKind::TestSuite           => "Engineering (QA)",
        EvidenceKind::ManualPolicy        => "Security / GRC",
        EvidenceKind::ExternalOperational => "Operations / SRE",
    }
}

fn frequency_for_kind(kind: EvidenceKind) -> &'static str {
    match kind {
        EvidenceKind::CompileTime         => "continuous",    // every commit via axon check
        EvidenceKind::RuntimeInvariant    => "continuous",    // every request
        EvidenceKind::AutomatedArtifact   => "per-release",
        EvidenceKind::TestSuite           => "per-commit",
        EvidenceKind::ManualPolicy        => "annual_review",
        EvidenceKind::ExternalOperational => "per-release",
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Implementation statement
// ═══════════════════════════════════════════════════════════════════

#[derive(Debug, Clone)]
pub struct ControlImplementationStatement {
    pub control_id: String,
    pub control_title: String,
    pub status: String,
    pub implementation_detail: String,
    pub evidence: Vec<String>,
    pub owner_role: String,
    pub test_frequency: String,
}

impl ControlImplementationStatement {
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("control_id".into(), self.control_id.clone().into());
        m.insert("control_title".into(), self.control_title.clone().into());
        m.insert("status".into(), self.status.clone().into());
        m.insert(
            "implementation_detail".into(),
            self.implementation_detail.clone().into(),
        );
        m.insert(
            "evidence".into(),
            Value::Array(self.evidence.iter().cloned().map(Value::String).collect()),
        );
        m.insert("owner_role".into(), self.owner_role.clone().into());
        m.insert("test_frequency".into(), self.test_frequency.clone().into());
        Value::Object(m)
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Status mapping
// ═══════════════════════════════════════════════════════════════════

fn status_from_analysis(assessment_status: &str) -> &'static str {
    match assessment_status {
        "ready"            => "implemented",
        "pending_code"     => "partially_implemented",
        "pending_external" => "planned",
        _                  => "not_applicable",
    }
}

fn implementation_detail(control: &Control) -> String {
    format!(
        "{}. Evidence kind: {}. Verification locus: {}.",
        control.axon_primitive,
        control.evidence_kind.as_str(),
        control.evidence_locator,
    )
}

// ═══════════════════════════════════════════════════════════════════
//  Public API
// ═══════════════════════════════════════════════════════════════════

pub fn generate_control_statements(
    program: &IRProgram,
    framework: FrameworkId,
) -> Vec<ControlImplementationStatement> {
    let analysis = analyze_gaps(program, framework);
    let by_id: HashMap<String, String> = analysis
        .assessments
        .iter()
        .map(|a| (a.control_id.clone(), a.status.clone()))
        .collect();

    let mut statements: Vec<ControlImplementationStatement> = Vec::new();
    for control in controls_for(framework) {
        let status_raw = by_id
            .get(control.control_id)
            .cloned()
            .unwrap_or_else(|| "pending_code".to_string());
        statements.push(ControlImplementationStatement {
            control_id: control.control_id.into(),
            control_title: control.title.into(),
            status: status_from_analysis(&status_raw).into(),
            implementation_detail: implementation_detail(&control),
            evidence: vec![control.evidence_locator.into()],
            owner_role: owner_for_kind(control.evidence_kind).into(),
            test_frequency: frequency_for_kind(control.evidence_kind).into(),
        });
    }
    statements
}

pub fn statements_to_value(
    statements: &[ControlImplementationStatement],
    framework: FrameworkId,
) -> Value {
    let mut m = Map::new();
    m.insert(
        "schema".into(),
        "axon.esk.control_implementation_statements.v1".into(),
    );
    m.insert("framework".into(), framework.as_str().into());
    m.insert("total_controls".into(), (statements.len() as i64).into());
    m.insert(
        "statements".into(),
        Value::Array(statements.iter().map(|s| s.to_value()).collect()),
    );
    Value::Object(m)
}

#[cfg(test)]
mod tests {
    use super::super::frameworks::{all_frameworks, control_count};
    use super::*;
    use crate::ir_generator::IRGenerator;
    use crate::lexer::Lexer;
    use crate::parser::Parser;

    fn compile(source: &str) -> IRProgram {
        let tokens = Lexer::new(source, "t").tokenize().unwrap();
        let program = Parser::new(tokens).parse().unwrap();
        IRGenerator::new().generate(&program)
    }

    fn full_program() -> IRProgram {
        compile(r#"
            type R compliance [HIPAA] { x: String }
            flow F(r: R) -> R { step S { ask: "x" output: R } }
            shield G {
                scan: [prompt_injection]
                on_breach: halt
                severity: high
                compliance: [HIPAA]
            }
            axonendpoint E {
                method: POST path: "/p" body: R execute: F output: R
                shield: G
                compliance: [HIPAA]
            }
            resource Db { kind: postgres lifetime: linear }
            fabric Vpc { provider: aws }
            manifest M { resources: [Db] fabric: Vpc compliance: [HIPAA] }
            observe O from M { sources: [prom] quorum: 1 }
            reconcile Rec { observe: O }
            lease L { resource: Db duration: 30m }
            immune I { watch: [O] scope: tenant }
            reflex Rf { trigger: I on_level: doubt action: quarantine scope: tenant }
            heal H { source: I scope: tenant }
        "#)
    }

    #[test]
    fn one_statement_per_control() {
        let ir = full_program();
        for f in all_frameworks() {
            let statements = generate_control_statements(&ir, f);
            assert_eq!(statements.len(), control_count(f), "framework {:?}", f);
        }
    }

    #[test]
    fn statuses_only_from_canonical_set() {
        let ir = full_program();
        let canonical = [
            "implemented",
            "partially_implemented",
            "planned",
            "not_applicable",
        ];
        for f in all_frameworks() {
            for s in generate_control_statements(&ir, f) {
                assert!(
                    canonical.contains(&s.status.as_str()),
                    "{:?} {} had non-canonical status {}",
                    f,
                    s.control_id,
                    s.status
                );
            }
        }
    }

    #[test]
    fn statements_to_value_schema() {
        let ir = full_program();
        let stmts = generate_control_statements(&ir, FrameworkId::Soc2TypeII);
        let v = statements_to_value(&stmts, FrameworkId::Soc2TypeII);
        assert_eq!(
            v["schema"],
            "axon.esk.control_implementation_statements.v1"
        );
        assert_eq!(v["framework"], FrameworkId::Soc2TypeII.as_str());
        assert_eq!(v["total_controls"], stmts.len() as i64);
    }

    #[test]
    fn status_mapping_matches_python_reference() {
        assert_eq!(status_from_analysis("ready"), "implemented");
        assert_eq!(status_from_analysis("pending_code"), "partially_implemented");
        assert_eq!(status_from_analysis("pending_external"), "planned");
        assert_eq!(status_from_analysis("something_else"), "not_applicable");
    }

    #[test]
    fn implementation_detail_mentions_primitive_and_locus() {
        let ir = full_program();
        let stmts = generate_control_statements(&ir, FrameworkId::Soc2TypeII);
        assert!(!stmts.is_empty());
        for s in &stmts {
            assert!(
                s.implementation_detail.contains("Evidence kind:"),
                "detail missing marker: {}",
                s.implementation_detail
            );
            assert!(
                s.implementation_detail.contains("Verification locus:"),
                "detail missing locus: {}",
                s.implementation_detail
            );
        }
    }

    #[test]
    fn statements_deterministic_on_equal_input() {
        let ir = full_program();
        let a = statements_to_value(
            &generate_control_statements(&ir, FrameworkId::Iso27001),
            FrameworkId::Iso27001,
        );
        let b = statements_to_value(
            &generate_control_statements(&ir, FrameworkId::Iso27001),
            FrameworkId::Iso27001,
        );
        assert_eq!(
            serde_json::to_string(&a).unwrap(),
            serde_json::to_string(&b).unwrap()
        );
    }
}
