//! §Fase 77 — drift gate for the π-calc channel-quartet primitive docs.
//!
//! Every primitive doc shipped under `src/knowledge/primitives/` for the
//! §77 batch (`channel`, `emit`, `publish`, `discover`) must be backed by
//! a canonical `.axon` program that round-trips through the same
//! `axon-frontend` pipeline the `axon` CLI uses — the "published grammar
//! MUST compile" discipline (Kivi brief #29), applied to the constructs
//! brief #51 §B.2 caught undocumented.
//!
//! Mirrors the pattern from `phase2/6b/6c/6d_canonical_programs.rs`.

use axon_emcp::compiler_pipeline::{run, Outcome};

fn must_compile(label: &str, source: &str) {
    match run(source, label) {
        Outcome::Ok { .. } => { /* well-formed — the whole assertion */ }
        Outcome::Err {
            stage,
            errors,
            warnings,
        } => panic!(
            "{label}: expected well-formed program, got {stage:?} failure:\n\
             errors   = {errors:#?}\n\
             warnings = {warnings:#?}\n\
             source   = {source}"
        ),
    }
}

/// The brief-#51 shape: a durable channel egress-published under a
/// sign-only shield — the §77 canonical program, covering `channel`,
/// `emit`, AND `publish` (the three compose; documenting them apart
/// would hide the contract).
#[test]
fn channel_emit_publish_canonical_program_compiles() {
    let src = r#"
type SkillResult { task_id: String  tenant_id: String  status: String  result: String }

shield WebhookEgress { sign: hmac_sha256  on_breach: halt }

channel SkillCompleted {
    message: SkillResult
    qos: at_least_once
    lifetime: affine
    persistence: persistent_axonstore
    shield: WebhookEgress
}

flow CompleteSkill(task_id: String, tenant_id: String, result: String) -> Unit {
    step Build { ask: "Build the skill result payload."  output: SkillResult }
    emit SkillCompleted(Build)
    publish SkillCompleted within WebhookEgress
}

run CompleteSkill()
"#;
    must_compile("channel+emit+publish/canonical", src);
}

/// `discover` — the dual import of a published capability.
#[test]
fn discover_canonical_program_compiles() {
    let src = r#"
type Order { id: String }

shield Gate { scan: [pii_leak]  on_breach: halt }

channel Orders {
    message: Order
    shield: Gate
}

flow Producer(id: String) -> Unit {
    publish Orders within Gate
}

flow Consumer() -> Unit {
    discover Orders as live
}

run Producer()
"#;
    must_compile("discover/canonical", src);
}
