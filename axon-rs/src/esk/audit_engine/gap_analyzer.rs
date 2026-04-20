//! AXON Audit Evidence Engine — GapAnalyzer
//!
//! Direct port of `axon/runtime/esk/audit_engine/gap_analyzer.py`.
//!
//! Runs the framework catalog against a compiled `IRProgram` and returns
//! a deterministic gap analysis categorising each control as
//! `ready` / `pending_code` / `pending_external`.

#![allow(dead_code)]

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::Serialize;
use serde_json::{Map, Value};

use crate::ir_nodes::IRProgram;

use super::frameworks::{Control, EvidenceKind, FrameworkId, controls_for};

/// Per-control verdict.
#[derive(Debug, Clone, Serialize)]
pub struct ControlAssessment {
    pub control_id: String,
    pub title: String,
    pub axon_primitive: String,
    pub evidence_kind: String,
    pub evidence_locator: String,
    pub status: String,
    pub rationale: String,
}

/// Full gap analysis for one framework.
#[derive(Debug, Clone)]
pub struct GapAnalysis {
    pub framework: String,
    pub total_controls: usize,
    pub ready: usize,
    pub pending_code: usize,
    pub pending_external: usize,
    pub assessments: Vec<ControlAssessment>,
    pub missing_features: Vec<String>,
}

impl GapAnalysis {
    pub fn readiness_percent(&self) -> f64 {
        if self.total_controls == 0 {
            return 100.0;
        }
        100.0 * self.ready as f64 / self.total_controls as f64
    }

    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("schema".into(), "axon.esk.audit_gap_analysis.v1".into());
        m.insert("framework".into(), self.framework.clone().into());
        m.insert("total_controls".into(), (self.total_controls as i64).into());
        m.insert("ready".into(), (self.ready as i64).into());
        m.insert("pending_code".into(), (self.pending_code as i64).into());
        m.insert("pending_external".into(), (self.pending_external as i64).into());
        // Python uses `round(x, 2)`; serde_json will serialise f64 faithfully.
        let pct = (self.readiness_percent() * 100.0).round() / 100.0;
        m.insert("readiness_percent".into(), Value::from(pct));
        m.insert(
            "missing_features".into(),
            Value::Array(
                self.missing_features.iter().cloned().map(Value::String).collect(),
            ),
        );
        m.insert(
            "assessments".into(),
            Value::Array(
                self.assessments
                    .iter()
                    .map(|a| {
                        let mut am = Map::new();
                        am.insert("control_id".into(), a.control_id.clone().into());
                        am.insert("title".into(), a.title.clone().into());
                        am.insert("axon_primitive".into(), a.axon_primitive.clone().into());
                        am.insert("evidence_kind".into(), a.evidence_kind.clone().into());
                        am.insert("evidence_locator".into(), a.evidence_locator.clone().into());
                        am.insert("status".into(), a.status.clone().into());
                        am.insert("rationale".into(), a.rationale.clone().into());
                        Value::Object(am)
                    })
                    .collect(),
            ),
        );
        Value::Object(m)
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Feature detection
// ═══════════════════════════════════════════════════════════════════

fn program_features(program: &IRProgram) -> HashSet<String> {
    let mut features: HashSet<String> = HashSet::new();
    if !program.shields.is_empty()      { features.insert("has_shield".into()); }
    if !program.resources.is_empty()    { features.insert("has_resource".into()); }
    if !program.manifests.is_empty()    { features.insert("has_manifest".into()); }
    if !program.observations.is_empty() { features.insert("has_observe".into()); }
    if !program.immunes.is_empty()      { features.insert("has_immune".into()); }
    if !program.reflexes.is_empty()     { features.insert("has_reflex".into()); }
    if !program.heals.is_empty()        { features.insert("has_heal".into()); }
    if !program.reconciles.is_empty()   { features.insert("has_reconcile".into()); }
    if !program.leases.is_empty()       { features.insert("has_lease".into()); }
    if !program.ensembles.is_empty()    { features.insert("has_ensemble".into()); }
    if !program.topologies.is_empty()   { features.insert("has_topology".into()); }
    if !program.endpoints.is_empty()    { features.insert("has_endpoint".into()); }

    let has_any_compliance = program.types.iter().any(|t| !t.compliance.is_empty())
        || program.shields.iter().any(|s| !s.compliance.is_empty())
        || program.endpoints.iter().any(|e| !e.compliance.is_empty())
        || program.manifests.iter().any(|m| !m.compliance.is_empty());
    if has_any_compliance {
        features.insert("has_compliance_annotation".into());
    }
    features
}

// ═══════════════════════════════════════════════════════════════════
//  Rules
// ═══════════════════════════════════════════════════════════════════

fn feature_requirements() -> HashMap<&'static str, HashSet<&'static str>> {
    let mut m: HashMap<&'static str, HashSet<&'static str>> = HashMap::new();
    // SOC 2
    m.insert("CC3.2",  HashSet::from(["has_immune"]));
    m.insert("CC3.3",  HashSet::from(["has_reflex"]));
    m.insert("CC6.3",  HashSet::from(["has_lease"]));
    m.insert("CC6.6",  HashSet::from(["has_shield", "has_endpoint"]));
    m.insert("CC6.8",  HashSet::new());
    m.insert("CC7.1",  HashSet::from(["has_immune"]));
    m.insert("CC7.2",  HashSet::from(["has_immune"]));
    m.insert("CC7.3",  HashSet::from(["has_immune"]));
    m.insert("CC7.4",  HashSet::from(["has_reflex", "has_heal"]));
    m.insert("CC7.5",  HashSet::from(["has_reconcile"]));
    m.insert("C1.1",   HashSet::from(["has_compliance_annotation"]));
    m.insert("PI1.4",  HashSet::from(["has_ensemble"]));
    m.insert("P1.1",   HashSet::from(["has_compliance_annotation"]));
    m.insert("P6.1",   HashSet::from(["has_shield", "has_compliance_annotation"]));
    // ISO 27001
    m.insert("A.5.2",  HashSet::from(["has_heal"]));
    m.insert("A.5.7",  HashSet::from(["has_immune"]));
    m.insert("A.5.23", HashSet::new());
    m.insert("A.5.24", HashSet::from(["has_immune", "has_reflex", "has_heal"]));
    m.insert("A.5.30", HashSet::from(["has_reconcile"]));
    m.insert("A.5.34", HashSet::from(["has_compliance_annotation"]));
    m.insert("A.8.2",  HashSet::from(["has_lease"]));
    m.insert("A.8.7",  HashSet::from(["has_immune", "has_reflex"]));
    m.insert("A.8.8",  HashSet::from(["has_heal"]));
    m.insert("A.8.13", HashSet::from(["has_resource"]));
    m
}

const PENDING_KEYWORD: &str = "PENDING";

fn is_external_kind(kind: EvidenceKind) -> bool {
    matches!(
        kind,
        EvidenceKind::ExternalOperational | EvidenceKind::ManualPolicy
    )
}

fn assess_control(control: &Control, features: &HashSet<String>) -> ControlAssessment {
    let locator = control.evidence_locator;
    let is_pending = locator.contains(PENDING_KEYWORD);
    let reqs = feature_requirements();
    let required: HashSet<&str> = reqs.get(control.control_id).cloned().unwrap_or_default();
    let missing: Vec<&str> = required
        .iter()
        .filter(|f| !features.contains(**f))
        .copied()
        .collect();

    let (status, rationale) = if is_pending && is_external_kind(control.evidence_kind) {
        (
            "pending_external",
            format!(
                "requires external engagement (accredited lab / CPA) — {locator}"
            ),
        )
    } else if is_pending {
        (
            "pending_code",
            format!("evidence artifact not yet produced — {locator}"),
        )
    } else if !missing.is_empty() {
        let mut m_sorted: Vec<&str> = missing.clone();
        m_sorted.sort();
        (
            "pending_code",
            format!(
                "program does not declare required primitive(s): {}",
                m_sorted.join(", ")
            ),
        )
    } else if control.evidence_kind == EvidenceKind::ExternalOperational {
        ("ready", format!("operational artifact: {locator}"))
    } else {
        ("ready", format!("enforced by {}", control.axon_primitive))
    };

    ControlAssessment {
        control_id: control.control_id.into(),
        title: control.title.into(),
        axon_primitive: control.axon_primitive.into(),
        evidence_kind: control.evidence_kind.as_str().into(),
        evidence_locator: locator.into(),
        status: status.into(),
        rationale,
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Public API
// ═══════════════════════════════════════════════════════════════════

pub fn analyze_gaps(program: &IRProgram, framework: FrameworkId) -> GapAnalysis {
    let features = program_features(program);
    let controls = controls_for(framework);
    let mut analysis = GapAnalysis {
        framework: framework.as_str().into(),
        total_controls: controls.len(),
        ready: 0,
        pending_code: 0,
        pending_external: 0,
        assessments: Vec::new(),
        missing_features: Vec::new(),
    };
    let reqs = feature_requirements();
    for c in &controls {
        let a = assess_control(c, &features);
        match a.status.as_str() {
            "ready" => analysis.ready += 1,
            "pending_code" => {
                analysis.pending_code += 1;
                if let Some(req) = reqs.get(c.control_id) {
                    for feat in req {
                        if !features.contains(*feat)
                            && !analysis.missing_features.contains(&feat.to_string())
                        {
                            analysis.missing_features.push(feat.to_string());
                        }
                    }
                }
            }
            "pending_external" => analysis.pending_external += 1,
            _ => {}
        }
        analysis.assessments.push(a);
    }
    analysis
}

pub fn analyze_all(program: &IRProgram) -> BTreeMap<String, GapAnalysis> {
    let mut m = BTreeMap::new();
    for f in super::frameworks::all_frameworks() {
        m.insert(f.as_str().into(), analyze_gaps(program, f));
    }
    m
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir_generator::IRGenerator;
    use crate::lexer::Lexer;
    use crate::parser::Parser;

    fn compile(source: &str) -> IRProgram {
        let tokens = Lexer::new(source, "t").tokenize().unwrap();
        let program = Parser::new(tokens).parse().unwrap();
        IRGenerator::new().generate(&program)
    }

    #[test]
    fn empty_program_counts_sum_to_total_controls() {
        let ir = compile("type X { field: String }");
        let gap = analyze_gaps(&ir, FrameworkId::Soc2TypeII);
        assert_eq!(
            gap.ready + gap.pending_code + gap.pending_external,
            gap.total_controls
        );
        // At least the feature-gated controls must be pending_code on an
        // empty program (no immune / heal / reflex / ...).
        assert!(gap.pending_code > 0);
    }

    #[test]
    fn program_with_full_stack_passes_most_soc2_controls() {
        let ir = compile(r#"
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
            observe O2 from M { sources: [cw] quorum: 1 }
            reconcile Rec { observe: O }
            lease L { resource: Db duration: 30m }
            ensemble En { observations: [O, O2] quorum: 2 }
            immune I { watch: [O] scope: tenant }
            reflex Rf { trigger: I on_level: doubt action: quarantine scope: tenant }
            heal H { source: I scope: tenant }
        "#);
        let gap = analyze_gaps(&ir, FrameworkId::Soc2TypeII);
        assert!(
            gap.ready >= 25,
            "expected >= 25 ready, got {} (missing: {:?})",
            gap.ready,
            gap.missing_features
        );
    }

    #[test]
    fn fips_has_pending_external_for_lab_engagement() {
        let ir = compile("type T { x: String }");
        let gap = analyze_gaps(&ir, FrameworkId::Fips140_3);
        assert!(
            gap.pending_external > 0,
            "FIPS must carry ≥1 pending_external entry"
        );
    }

    #[test]
    fn analyze_all_covers_every_framework() {
        let ir = compile("type T { x: String }");
        let all = analyze_all(&ir);
        assert_eq!(all.len(), 4);
        for fw in super::super::frameworks::all_frameworks() {
            assert!(all.contains_key(fw.as_str()));
        }
    }

    #[test]
    fn readiness_percent_sane_bounds() {
        let ir = compile("type T { x: String }");
        let gap = analyze_gaps(&ir, FrameworkId::Iso27001);
        let pct = gap.readiness_percent();
        assert!((0.0..=100.0).contains(&pct));
    }

    #[test]
    fn gap_analysis_deterministic() {
        let ir = compile(r#"
            type T compliance [GDPR] { x: String }
            resource R { kind: postgres lifetime: linear }
        "#);
        let a = analyze_gaps(&ir, FrameworkId::Iso27001).to_value();
        let b = analyze_gaps(&ir, FrameworkId::Iso27001).to_value();
        assert_eq!(
            serde_json::to_string(&a).unwrap(),
            serde_json::to_string(&b).unwrap()
        );
    }
}
