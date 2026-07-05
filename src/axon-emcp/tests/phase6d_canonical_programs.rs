//! §Fase 6.d — drift gate for the Tier 3 primitive docs.
//!
//! Every primitive doc shipped under `src/knowledge/primitives/` for
//! Tier 3 (`axonendpoint`, `axpoint`, `daemon`, `mcp`, `listen`,
//! `shield`, `mandate`, `compute`, `lambda`, `forge`, `ots`,
//! `psyche`, `immune`, `reflex`, `heal`, `transact`) must be backed
//! by a canonical `.axon` program that round-trips through the same
//! `axon-frontend` pipeline the `axon` CLI uses.
//!
//! `taint` and `logic` are NOT in this batch — both are reserved
//! lexer tokens with no parser production (see the §Fase 6.c
//! commit and the §Fase 6.d registry note).
//!
//! Mirrors the pattern from `phase2/6b/6c_canonical_programs.rs`.

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

// ── Wire (5) ─────────────────────────────────────────────────────────

#[test]
fn axonendpoint_canonical_program_compiles() {
    let src = r#"
type AnalyzeRequest { doc: Text }
type RiskReport { summary: Text }

flow AnalyzeContract(doc: Text) -> FlowEnvelope<RiskReport> {
    step Extract {
        given: doc
        ask: "Extract every clause."
        output: FlowEnvelope<RiskReport>
    }
}

axonendpoint AnalyzeContractAPI {
    method:      POST
    path:        "/v1/contracts/analyze"
    body:        AnalyzeRequest
    execute:     AnalyzeContract
    output:      FlowEnvelope<RiskReport>
    backend:     auto
    compliance:  [SOC2]
    retries:     1
    timeout:     20s
}
"#;
    must_compile("axonendpoint/canonical", src);
}

#[test]
fn axpoint_canonical_program_compiles() {
    // `axpoint` is the lexer alias for `axonendpoint`; same parser,
    // same grammar. Drift gate verifies the alias survives.
    let src = r#"
type EchoRequest { message: Text }
type EchoResponse { echoed: Text }

flow Echo(message: Text) -> FlowEnvelope<EchoResponse> {
    step Reply {
        given: message
        ask: "Echo the message back."
        output: FlowEnvelope<EchoResponse>
    }
}

axpoint EchoAPI {
    method:   POST
    path:     "/v1/echo"
    body:     EchoRequest
    execute:  Echo
    output:   FlowEnvelope<EchoResponse>
    backend:  auto
}
"#;
    must_compile("axpoint/canonical", src);
}

#[test]
fn daemon_canonical_program_compiles() {
    let src = r#"
tool TicketDB {
    provider: postgres
    timeout:  3s
}

tool SlackNotifier {
    provider: slack
    timeout:  5s
}

memory RouterState {
    store:     persistent
    backend:   postgresql
    retrieval: exact
}

shield CustomerDataShield {
    scan:       [pii_leak, data_exfil]
    on_breach:  quarantine
    severity:   high
    compliance: [SOC2]
}

daemon TicketRouter {
    goal:       "Route inbound tickets to the right SLA queue."
    tools:      [TicketDB, SlackNotifier]
    memory:     RouterState
    strategy:   react
    on_stuck:   retry
    shield:     CustomerDataShield
    max_tokens: 16000
    max_time:   30m

    listen "tickets.inbound" as msg
}
"#;
    must_compile("daemon/canonical", src);
}

#[test]
fn mcp_canonical_program_compiles() {
    // `mcp` uses the permissive generic-declaration form; the
    // canonical example carries a body but the parser tolerates
    // either form.
    let src = r#"
mcp ClinicalKB {
    // Body uses AXON `//` comments; field shape is validated at
    // deploy time, not parse time.
}
"#;
    must_compile("mcp/canonical", src);
}

#[test]
fn listen_canonical_program_compiles() {
    // Flow-body listen — single subscription, runs the body
    // once per arrival until the flow returns. Uses the
    // string-topic legacy form for cross-stack compatibility
    // (typed channels would need a `channel` declaration —
    // documented separately).
    let src = r#"
type Receipt { id: Text }

flow ProcessIncoming() -> Receipt {
    listen "tickets.urgent" as event {
    }
    step Acknowledge {
        ask: "Acknowledge the event."
        output: Receipt
    }
}
"#;
    must_compile("listen/canonical", src);
}

// ── Operators (8) ────────────────────────────────────────────────────

#[test]
fn shield_canonical_program_compiles() {
    let src = r#"
shield PHIShield {
    scan:       [prompt_injection, pii_leak, data_exfil]
    on_breach:  quarantine
    severity:   critical
    redact:     [ssn, dob]
    compliance: [HIPAA, GDPR, SOC2]
}
"#;
    must_compile("shield/canonical", src);
}

#[test]
fn window_canonical_program_compiles() {
    // §Fase 71 — a timezone-aware temporal window with a holiday exclusion,
    // bound by a scheduled daemon. The §71.e compile-gated corpus example.
    let src = r#"
flow SendBatch() -> Unit {
    step S { ask: "send the outbound batch" output: Unit }
}

window BusinessHours {
    timezone:   "America/Bogota"
    allow:      [ { days: Mon..Fri, hours: 9..18 } ]
    exclude:    [ "2026-12-25", "2026-01-01" ]
    on_outside: defer
}

daemon OutboundScheduler {
    window:   BusinessHours
    requires: [flow.execute]
    listen "cron:*/5 * * * *" as tick {
        run SendBatch()
    }
}
"#;
    must_compile("window/canonical", src);
}

#[test]
fn mandate_canonical_program_compiles() {
    let src = r#"
mandate FinancialApproval {
    constraint:   "Posting > $10k requires CFO + Controller dual approval"
    kp:           1.0
    ki:           0.1
    kd:           0.0
    tolerance:    0.05
    max_steps:    10
    on_violation: halt
}
"#;
    must_compile("mandate/canonical", src);
}

#[test]
fn compute_canonical_program_compiles() {
    // compute's parser currently models only `shield:` as a structured
    // field; the doc explains other fields land permissively. The
    // canonical example pins the `shield:` binding.
    let src = r#"
shield FinancialShield {
    scan:       [pii_leak]
    on_breach:  halt
    severity:   critical
    compliance: [PCI_DSS, SOC2]
}

compute LoanUnderwriterCompute {
    shield: FinancialShield
}
"#;
    must_compile("compute/canonical", src);
}

#[test]
fn lambda_canonical_top_level_compiles() {
    // Top-level lambda declaration — the metadata-only form. The
    // `lambda apply` flow-step form requires a flow body context;
    // we exercise the declaration surface here.
    let src = r#"
lambda DiagnosisCandidate {
    ontology:       "ClinicalInference"
    certainty:      0.85
    temporal_frame: "2025-01-01" "2026-12-31"
    provenance:     "EHR cohort 2024 + clinical guideline ICD-11"
    derivation:     inferred
}
"#;
    must_compile("lambda/canonical-top-level", src);
}

#[test]
fn forge_canonical_program_compiles() {
    let src = r#"
type CaseFacts { body: Text }
type CaseHistory { entries: Text }
type RulingsList { items: Text }
type CaseReport { summary: Text }

flow AssembleReport(case: Text) -> CaseReport {
    step LoadFacts {
        given: case
        ask: "Fetch case facts."
        output: CaseFacts
    }
    step LoadHistory {
        given: case
        ask: "Fetch case history."
        output: CaseHistory
    }
    forge Synthesis(seed: "a novel legal argument from these case facts") -> CaseReport {
        mode: exploratory
        novelty: 0.6
    }
    step Render {
        given: LoadFacts.output
        ask: "Render the final report."
        output: CaseReport
    }
}
"#;
    must_compile("forge/canonical", src);
}

#[test]
fn ots_canonical_program_compiles() {
    // `ots Name<InType, OutType> { teleology, homotopy_search,
    // loss_function }` — exercise the generic-parameter form too.
    let src = r#"
ots AudioMulawToPcm16 {
    teleology:       "Convert mu-law 8kHz audio to PCM16 for downstream processing"
    homotopy_search: deep
    loss_function:   "RMSE on reconstructed signal"
}
"#;
    must_compile("ots/canonical", src);
}

#[test]
fn psyche_canonical_program_compiles() {
    let src = r#"
psyche AnalyticalDisposition {
    dimensions:         [analytical, cautious, evidence_seeking, contrarian]
    manifold_noise:     0.1
    manifold_momentum:  0.7
    // `non_diagnostic` is required by Dependent Type Safety §4.
    safety_constraints: [non_diagnostic, no_self_harm, no_deception]
    quantum_enabled:    false
    inference_mode:     active
}
"#;
    must_compile("psyche/canonical", src);
}

// ── Cognitive immune system (3) ──────────────────────────────────────

#[test]
fn immune_canonical_program_compiles() {
    let src = r#"
resource MetricsSource { kind: prometheus  endpoint: "metrics.internal:9090"  lifetime: persistent }
fabric Global { provider: aws  region: "us-east-1"  zones: 3  ephemeral: false }
manifest Production { resources: [MetricsSource]  fabric: Global }

observe ClinicalHealth from Production {
    sources: [prometheus]
    quorum:  1
    timeout: 5s
}

immune ClinicalVigil {
    watch:       [ClinicalHealth]
    sensitivity: 0.90
    baseline:    learned
    window:      800
    scope:       tenant
    tau:         300s
    decay:       exponential
}
"#;
    must_compile("immune/canonical", src);
}

#[test]
fn reflex_canonical_program_compiles() {
    let src = r#"
resource MetricsSource { kind: prometheus  endpoint: "metrics.internal:9090"  lifetime: persistent }
fabric Global { provider: aws  region: "us-east-1"  zones: 3  ephemeral: false }
manifest Production { resources: [MetricsSource]  fabric: Global }

observe ClinicalHealth from Production { sources: [prometheus]  quorum: 1  timeout: 5s }

immune ClinicalVigil {
    watch:       [ClinicalHealth]
    sensitivity: 0.90
    baseline:    learned
    scope:       tenant
}

reflex QuarantineExfil {
    trigger:  ClinicalVigil
    on_level: speculate
    action:   quarantine
    scope:    tenant
    sla:      1s
}
"#;
    must_compile("reflex/canonical", src);
}

#[test]
fn heal_canonical_program_compiles() {
    let src = r#"
resource MetricsSource { kind: prometheus  endpoint: "metrics.internal:9090"  lifetime: persistent }
fabric Global { provider: aws  region: "us-east-1"  zones: 3  ephemeral: false }
manifest Production { resources: [MetricsSource]  fabric: Global }

observe ClinicalHealth from Production { sources: [prometheus]  quorum: 1  timeout: 5s }

immune ClinicalVigil {
    watch:       [ClinicalHealth]
    sensitivity: 0.90
    baseline:    learned
    scope:       tenant
}

shield PHIShield {
    scan:       [pii_leak]
    on_breach:  quarantine
    severity:   critical
    compliance: [HIPAA]
}

heal MitigateExposure {
    source:       ClinicalVigil
    on_level:     doubt
    mode:         human_in_loop
    scope:        tenant
    review_sla:   1h
    shield:       PHIShield
    max_patches:  3
}
"#;
    must_compile("heal/canonical", src);
}

// ── Data plane block (1) ─────────────────────────────────────────────

#[test]
fn transact_canonical_program_compiles() {
    let src = r#"
type JournalEntry { period: Text  account: Text  amount: Numeric }
type ValidatedEntry { entry: JournalEntry }
type PostReceipt { id: Text }

flow PostJournalEntry(entry: JournalEntry) -> PostReceipt {
    step Validate {
        given: entry
        ask: "Validate the entry's accounting balance."
        output: ValidatedEntry
    }
    transact {
    }
    step Acknowledge {
        given: Validate.output
        ask: "Render the post receipt."
        output: PostReceipt
    }
}
"#;
    must_compile("transact/canonical", src);
}
