//! AXON Runtime — DryRunHandler
//!
//! Direct port of `axon/runtime/handlers/dry_run.py`.
//!
//! Deterministic, in-memory interpreter of the Intention Tree. Performs
//! no external I/O — records every provisioning/observation request and
//! returns outcomes with certainty 1.0 (the handler is omniscient over
//! its own synthetic world). Primary test vehicle for the CPS machinery.

#![allow(dead_code)]

use std::collections::HashMap;

use serde_json::{Map, Value};

use crate::ir_nodes::{IRFabric, IRManifest, IRObserve, IRResource};

use super::base::{
    Continuation, Handler, HandlerError, HandlerOutcome, make_envelope,
};

/// Captured side-effects for inspection in tests.
#[derive(Debug, Default)]
pub struct DryRunState {
    pub provisioned: HashMap<String, Value>,
    pub observations: Vec<Value>,
    pub outcomes: Vec<HandlerOutcome>,
}

/// Deterministic, in-memory handler — pure function from Intention Tree
/// to recorded side-effects.
pub struct DryRunHandler {
    pub simulate_partition: bool,
    pub state: DryRunState,
    name: String,
}

impl DryRunHandler {
    pub fn new() -> Self {
        DryRunHandler {
            simulate_partition: false,
            state: DryRunState::default(),
            name: "dry_run".into(),
        }
    }

    pub fn with_partition() -> Self {
        DryRunHandler {
            simulate_partition: true,
            state: DryRunState::default(),
            name: "dry_run".into(),
        }
    }
}

impl Default for DryRunHandler {
    fn default() -> Self { Self::new() }
}

impl Handler for DryRunHandler {
    fn name(&self) -> &str { &self.name }

    fn provision(
        &mut self,
        manifest: &IRManifest,
        resources: &HashMap<String, IRResource>,
        fabrics: &HashMap<String, IRFabric>,
        _cont: &mut Continuation<'_>,
    ) -> Result<HandlerOutcome, HandlerError> {
        let fabric_snapshot: Value = if !manifest.fabric_ref.is_empty() {
            if let Some(f) = fabrics.get(&manifest.fabric_ref) {
                let mut m = Map::new();
                m.insert("name".into(), f.name.clone().into());
                m.insert("provider".into(), f.provider.clone().into());
                m.insert("region".into(), f.region.clone().into());
                m.insert(
                    "zones".into(),
                    f.zones.map(Value::from).unwrap_or(Value::Null),
                );
                m.insert(
                    "ephemeral".into(),
                    f.ephemeral.map(Value::from).unwrap_or(Value::Null),
                );
                Value::Object(m)
            } else {
                Value::Null
            }
        } else {
            Value::Null
        };

        let resolved: Vec<Value> = manifest
            .resources
            .iter()
            .map(|res_name| {
                let mut m = Map::new();
                m.insert("name".into(), res_name.clone().into());
                if let Some(r) = resources.get(res_name) {
                    m.insert("kind".into(), r.kind.clone().into());
                    m.insert("lifetime".into(), r.lifetime.clone().into());
                    m.insert("endpoint".into(), r.endpoint.clone().into());
                    m.insert(
                        "capacity".into(),
                        r.capacity.map(Value::from).unwrap_or(Value::Null),
                    );
                    m.insert(
                        "certainty_floor".into(),
                        r.certainty_floor.map(Value::from).unwrap_or(Value::Null),
                    );
                } else {
                    m.insert("kind".into(), "unknown".into());
                    m.insert("lifetime".into(), "affine".into());
                    m.insert("endpoint".into(), "".into());
                    m.insert("capacity".into(), Value::Null);
                    m.insert("certainty_floor".into(), Value::Null);
                }
                Value::Object(m)
            })
            .collect();

        let mut record = Map::new();
        record.insert("manifest".into(), manifest.name.clone().into());
        record.insert("resources".into(), Value::Array(resolved));
        record.insert("fabric".into(), fabric_snapshot);
        record.insert("region".into(), manifest.region.clone().into());
        record.insert(
            "zones".into(),
            manifest.zones.map(Value::from).unwrap_or(Value::Null),
        );
        record.insert(
            "compliance".into(),
            Value::Array(manifest.compliance.iter().cloned().map(Value::String).collect()),
        );
        let record_value = Value::Object(record.clone());
        self.state.provisioned.insert(manifest.name.clone(), record_value);

        let outcome = HandlerOutcome::new(
            "provision",
            manifest.name.clone(),
            "ok",
            make_envelope(1.0, &self.name, "axiomatic", None),
            self.name.clone(),
        )
        .with_data(record);
        self.state.outcomes.push(outcome.clone());
        Ok(outcome)
    }

    fn observe(
        &mut self,
        obs: &IRObserve,
        manifest: &IRManifest,
        _cont: &mut Continuation<'_>,
    ) -> Result<HandlerOutcome, HandlerError> {
        if self.simulate_partition {
            // Decision D4: partition = ⊥ void, NEVER downgraded to `doubt`.
            return Err(HandlerError::network_partition(format!(
                "simulated partition while observing '{}' from '{}' (sources: {:?})",
                obs.name, manifest.name, obs.sources
            )));
        }

        let quorum = obs.quorum.unwrap_or(obs.sources.len() as i64);
        let mut record = Map::new();
        record.insert("observe".into(), obs.name.clone().into());
        record.insert("manifest".into(), manifest.name.clone().into());
        record.insert(
            "sources".into(),
            Value::Array(obs.sources.iter().cloned().map(Value::String).collect()),
        );
        record.insert("quorum".into(), quorum.into());
        record.insert("timeout".into(), obs.timeout.clone().into());
        record.insert("on_partition".into(), obs.on_partition.clone().into());
        record.insert(
            "resources_observed".into(),
            Value::Array(
                manifest.resources.iter().cloned().map(Value::String).collect(),
            ),
        );
        self.state.observations.push(Value::Object(record.clone()));

        let outcome = HandlerOutcome::new(
            "observe",
            obs.name.clone(),
            "ok",
            make_envelope(1.0, &self.name, "observed", None),
            self.name.clone(),
        )
        .with_data(record);
        self.state.outcomes.push(outcome.clone());
        Ok(outcome)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::handlers::base::HandlerErrorKind;
    use crate::ir_generator::IRGenerator;
    use crate::lexer::Lexer;
    use crate::parser::Parser;

    fn compile(source: &str) -> crate::ir_nodes::IRProgram {
        let tokens = Lexer::new(source, "t").tokenize().unwrap();
        let program = Parser::new(tokens).parse().unwrap();
        IRGenerator::new().generate(&program)
    }

    #[test]
    fn interprets_intention_tree_records_provision_and_observe() {
        let ir = compile(r#"
            resource Db { kind: postgres lifetime: linear }
            fabric Vpc { provider: aws region: "us-east-1" zones: 1 }
            manifest M { resources: [Db] fabric: Vpc }
            observe O from M { sources: [prom] quorum: 1 }
        "#);
        let mut h = DryRunHandler::new();
        let outcomes = h.interpret_program(&ir).expect("interpret");
        assert_eq!(outcomes.len(), 2);
        assert_eq!(outcomes[0].operation, "provision");
        assert_eq!(outcomes[1].operation, "observe");
        assert!(h.state.provisioned.contains_key("M"));
        assert_eq!(h.state.observations.len(), 1);
    }

    #[test]
    fn provision_outcome_has_c_1_axiomatic_envelope() {
        let ir = compile(r#"
            resource Db { kind: postgres }
            fabric Vpc { provider: aws }
            manifest M { resources: [Db] fabric: Vpc }
            observe O from M { sources: [prom] quorum: 1 }
        "#);
        let mut h = DryRunHandler::new();
        let outcomes = h.interpret_program(&ir).unwrap();
        let prov = outcomes.iter().find(|o| o.operation == "provision").unwrap();
        assert_eq!(prov.envelope.c, 1.0);
        assert_eq!(prov.envelope.delta, "axiomatic");
    }

    #[test]
    fn observe_outcome_has_c_1_observed_envelope() {
        let ir = compile(r#"
            resource Db { kind: postgres }
            fabric Vpc { provider: aws }
            manifest M { resources: [Db] fabric: Vpc }
            observe O from M { sources: [prom] quorum: 1 }
        "#);
        let mut h = DryRunHandler::new();
        let outcomes = h.interpret_program(&ir).unwrap();
        let obs = outcomes.iter().find(|o| o.operation == "observe").unwrap();
        assert_eq!(obs.envelope.c, 1.0);
        assert_eq!(obs.envelope.delta, "observed");
    }

    #[test]
    fn simulate_partition_raises_ct3() {
        let ir = compile(r#"
            resource Db { kind: postgres }
            fabric Vpc { provider: aws }
            manifest M { resources: [Db] fabric: Vpc }
            observe O from M { sources: [prom] quorum: 1 }
        "#);
        let mut h = DryRunHandler::with_partition();
        match h.interpret_program(&ir) {
            Err(e) => {
                assert_eq!(e.kind, HandlerErrorKind::NetworkPartition);
                assert_eq!(e.blame, "CT-3");
            }
            Ok(_) => panic!("simulate_partition must raise CT-3"),
        }
    }

    #[test]
    fn provision_record_includes_fabric_snapshot() {
        let ir = compile(r#"
            resource Db { kind: postgres lifetime: linear }
            fabric Vpc { provider: aws region: "us-east-1" zones: 2 ephemeral: true }
            manifest M { resources: [Db] fabric: Vpc }
        "#);
        let mut h = DryRunHandler::new();
        let _ = h.interpret_program(&ir).unwrap();
        let rec = &h.state.provisioned["M"];
        assert_eq!(rec["fabric"]["provider"], "aws");
        assert_eq!(rec["fabric"]["ephemeral"], true);
    }

    #[test]
    fn provision_record_propagates_compliance() {
        let ir = compile(r#"
            resource Db { kind: postgres }
            fabric Vpc { provider: aws }
            manifest M { resources: [Db] fabric: Vpc compliance: [HIPAA, GDPR] }
        "#);
        let mut h = DryRunHandler::new();
        let _ = h.interpret_program(&ir).unwrap();
        let rec = &h.state.provisioned["M"];
        assert_eq!(rec["compliance"], serde_json::json!(["HIPAA", "GDPR"]));
    }
}
