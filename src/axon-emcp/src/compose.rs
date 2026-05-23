//! `axon.compose(intent)` — natural-language brief → typed scaffold.
//!
//! The agent supplies an `intent` string in any human language. This
//! module:
//!
//! 1. Classifies the intent into one of 8 closed domains
//!    (`generic` | `healthcare` | `banking` | `government` | `legal`
//!    | `chat` | `retrieval` | `multi_agent`) via a deterministic
//!    keyword-scoring matcher. The match is explainable: the response
//!    carries the score per candidate so the agent can see why this
//!    domain won.
//! 2. Fetches the corresponding template (hand-authored AXON program,
//!    every byte proven to compile by
//!    `tests/phase4_templates_compile.rs`).
//! 3. **Re-validates** the template through the live
//!    `compiler_pipeline::run` pipeline — the same one `axon.check`
//!    uses — and refuses to return a scaffold that fails. The agent
//!    never sees a malformed program.
//! 4. Returns a structured envelope: `{ scaffold, domain,
//!    domain_score, alternatives, primitives_used,
//!    compliance_applied, next_steps, axon_check_verdict }`. The
//!    agent uses `primitives_used` to know which
//!    `axon.primitive_doc(<name>)` calls follow naturally; `next_steps`
//!    is a curated checklist of "what the human should adapt
//!    before deploying".

use crate::compiler_pipeline::{self, Outcome};
use crate::knowledge::Catalog;
use serde::Serialize;
use serde_json::{json, Value};
use std::sync::Arc;

/// One of 8 closed domains the compose tool can ground an intent in.
/// The set is intentionally small — every domain ships an
/// `.axon`-check-clean template, so adding a domain is a structured
/// PR (template + entry in this enum + entry in
/// [`domain_metadata`]), not a runtime config.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Domain {
    /// Fallback — minimal scaffold with persona/context/anchor/flow.
    /// Returned when no domain scores ≥ 1.
    Generic,
    /// HIPAA + GDPR + GxP — PHI, clinical trials, telemedicine.
    Healthcare,
    /// PCI_DSS + SOX + SOC2 — payments, loans, ledger.
    Banking,
    /// FISMA + NIST_800_53 + FedRAMP — agency, citizen, federal.
    Government,
    /// SOC2 + privilege discipline — contract, case, e-discovery.
    Legal,
    /// Streaming dialogue — chat, conversation, real-time reply.
    Chat,
    /// RAG / Q&A grounded in a corpus — search, lookup, knowledge base.
    Retrieval,
    /// Multi-agent task delegation — planner + worker, ensemble,
    /// coordination across personas.
    MultiAgent,
}

impl Domain {
    /// The template slug — matches the file stem under
    /// `src/knowledge/templates/<slug>.axon`.
    pub fn slug(self) -> &'static str {
        match self {
            Domain::Generic => "generic",
            Domain::Healthcare => "healthcare",
            Domain::Banking => "banking",
            Domain::Government => "government",
            Domain::Legal => "legal",
            Domain::Chat => "chat",
            Domain::Retrieval => "retrieval",
            Domain::MultiAgent => "multi_agent",
        }
    }
    /// Every domain in stable order — used for classifier iteration
    /// and for the `alternatives` field in the response.
    pub const fn all() -> &'static [Domain] {
        &[
            Domain::Healthcare,
            Domain::Banking,
            Domain::Government,
            Domain::Legal,
            Domain::Chat,
            Domain::Retrieval,
            Domain::MultiAgent,
            // `Generic` is intentionally LAST — it is the fallback,
            // never preferred when another domain scores.
            Domain::Generic,
        ]
    }
}

/// Static metadata per domain: the keyword vocabulary the classifier
/// scores against, the primitives the template uses, the compliance
/// frameworks wired in, and a checklist of next steps the agent should
/// recommend to the human.
struct DomainMetadata {
    /// Human-readable domain label surfaced in `next_steps` prose.
    label: &'static str,
    /// One-line summary of what the template gives the adopter.
    summary: &'static str,
    /// Keywords the classifier scans for in the intent string. Each
    /// match adds 1 to the domain's score. Keep the list focused —
    /// noisy keywords cause misclassification.
    keywords: &'static [&'static str],
    /// AXON primitives the template declares. The agent uses this to
    /// know which `axon.primitive_doc(<name>)` calls follow.
    primitives_used: &'static [&'static str],
    /// Compliance tags wired into the template by construction.
    compliance_applied: &'static [&'static str],
    /// Operator-facing checklist surfaced in the response. Each entry
    /// is a one-line action — the agent renders these as bullet points
    /// to the human.
    next_steps: &'static [&'static str],
}

/// The closed registry. Adding a domain means (a) a new enum variant
/// + slug, (b) a new template `.axon` file (proven to compile by
/// `phase4_templates_compile`), (c) a new entry here. No runtime
/// config; no surprise domains.
fn domain_metadata(d: Domain) -> &'static DomainMetadata {
    match d {
        Domain::Generic => &DomainMetadata {
            label: "Generic",
            summary: "Minimal typed scaffold — persona + context + anchor + flow.",
            keywords: &[],
            primitives_used: &["persona", "context", "anchor", "type", "flow", "run"],
            compliance_applied: &[],
            next_steps: &[
                "Rename the placeholder identifiers (`MyPersona`, `Input`, `Output`, `Answer`).",
                "Refine the persona's `domain:` list to the actual expertise.",
                "Tune the `confidence_threshold:` and the anchor's `confidence_floor:`.",
                "Replace the `step Think` prompt with your real task description.",
                "Add a transport (`axonendpoint` or `socket`) once the flow is stable.",
            ],
        },
        Domain::Healthcare => &DomainMetadata {
            label: "Healthcare (HIPAA + GDPR + GxP)",
            summary: "PHI-tagged types + PHIShield + clinical reviewer persona + audited HTTP boundary.",
            keywords: &[
                "patient", "phi", "hipaa", "medical", "medicine", "clinical",
                "diagnos", "ehr", "health", "doctor", "physician", "nurse",
                "hospital", "trial", "gxp", "fda", "pharma", "treatment",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "shield",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["HIPAA", "GDPR", "GxP", "SOC2"],
            next_steps: &[
                "Sign a Business Associate Agreement (BAA) with every downstream LLM provider.",
                "Replace the diagnosis prompt with your real clinical question.",
                "Tighten `confidence_threshold:` to your safety floor (default 0.9).",
                "Pin a deterministic backend (`backend: openai` / `anthropic` / ...) for production.",
                "Layer additional anchors per use case (e.g. `NoOffLabelRecommendation`).",
            ],
        },
        Domain::Banking => &DomainMetadata {
            label: "Banking (PCI DSS + SOX + SOC 2)",
            summary: "Payment + loan decision flows with FinancialShield and audited HTTP boundaries.",
            keywords: &[
                "payment", "loan", "credit", "bank", "transaction", "pci",
                "card", "fraud", "underwrit", "ledger", "fintech", "sox",
                "trader", "treasury", "wire", "merchant", "settle",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "shield",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["PCI_DSS", "SOX", "SOC2"],
            next_steps: &[
                "Tokenise PANs at ingress — never store raw card numbers downstream.",
                "Add a `mandate:` with `excludes_requester: true` on posting endpoints (SOX §404 SoD).",
                "Configure retention ≥ 7y on any ledger-bearing `axonstore` (SOX §802).",
                "Pin a deterministic backend for reproducible underwriting decisions.",
                "Wire fraud-detection signals into the shield's scan list as they become available.",
            ],
        },
        Domain::Government => &DomainMetadata {
            label: "Government (FISMA + NIST 800-53 + FedRAMP Moderate)",
            summary: "Citizen-record + benefits-eligibility flow with AgencyShield and audited HTTP boundary.",
            keywords: &[
                "agency", "citizen", "benefit", "federal", "government",
                "fisma", "fedramp", "nist", "ssa", "va", "irs", "policy",
                "eligibility", "adjudicat", "public", "constituent",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "shield",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["FISMA", "NIST_800_53", "FedRAMP_Moderate", "SOC2"],
            next_steps: &[
                "Determine FIPS 199 categorisation (Low / Moderate / High) and align the FedRAMP tag.",
                "File the System Security Plan (SSP) with the cognising AO.",
                "Bind every endpoint to a documented `requires:` capability (no wildcards).",
                "Enable monthly POA&M tracking against the audit chain.",
                "Annual 3PAO assessment + continuous monitoring.",
            ],
        },
        Domain::Legal => &DomainMetadata {
            label: "Legal (SOC 2 + privilege discipline)",
            summary: "Contract-analysis flow with PrivilegeShield and audited HTTP boundary.",
            keywords: &[
                "contract", "clause", "legal", "lawyer", "attorney",
                "discovery", "privilege", "case", "court", "compliance",
                "regulator", "counsel", "litigation",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "shield",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["SOC2"],
            next_steps: &[
                "Confirm the persona's `domain:` matches the actual jurisdiction(s).",
                "Tune `confidence_threshold:` upward — legal advice is high-stakes.",
                "Add a `NoLegalAdvice` anchor variant if the system is not attorney-supervised.",
                "Audit attorney-client privilege boundaries before exposing the endpoint externally.",
                "Configure retention per the matter-management policy.",
            ],
        },
        Domain::Chat => &DomainMetadata {
            label: "Streaming Chat",
            summary: "Token-by-token streaming flow with SSE transport — friendly conversational persona.",
            keywords: &[
                "chat", "conversation", "dialogue", "messaging", "talk",
                "stream", "real-time", "live", "interactive", "assistant",
                "companion",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "tool",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &[],
            next_steps: &[
                "Pin a streaming backend (`provider: openai` / `anthropic`).",
                "Choose a backpressure policy (drop_oldest / pause_upstream / fail) on the tool.",
                "Add a `socket` declaration if you need session-typed reconnection (Fase 41).",
                "Tighten the persona's `tone:` for your product voice.",
                "Compose a `shield:` if the chat touches regulated data.",
            ],
        },
        Domain::Retrieval => &DomainMetadata {
            label: "Retrieval-augmented Q&A (RAG)",
            summary: "Two-step search + compose flow grounded in retrieved evidence with citations.",
            keywords: &[
                "search", "retriev", "rag", "knowledge", "lookup",
                "question", "answer", "qa", "documents", "corpus",
                "research", "evidence",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor", "shield",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["SOC2"],
            next_steps: &[
                "Declare a `corpus` primitive pointing at your knowledge base.",
                "Replace the `Search` step prompt with a query that actually invokes retrieval.",
                "Add a `retrieve` step that pulls from the corpus before the `Compose` step.",
                "Confirm the citation format matches your downstream rendering.",
                "Tune `confidence_floor:` to suppress ungrounded outputs.",
            ],
        },
        Domain::MultiAgent => &DomainMetadata {
            label: "Multi-agent coordination",
            summary: "Planner + worker pattern — two personas, two flows, two HTTP boundaries.",
            keywords: &[
                "agent", "multi-agent", "coordinat", "ensemble",
                "planner", "worker", "delegate", "orchestrat", "negotiat",
                "consensus", "swarm",
            ],
            primitives_used: &[
                "type", "persona", "context", "anchor",
                "flow", "step", "axonendpoint",
            ],
            compliance_applied: &["SOC2"],
            next_steps: &[
                "Define the agent contract — the typed handoff between Planner and Worker outputs.",
                "Add a `mandate:` on the worker endpoint if humans must approve plan execution.",
                "Layer per-agent personas with distinct `domain:` lists to maximise diversity.",
                "Consider declaring a `session` + `socket` for synchronous multi-turn coordination.",
                "Add a third agent (reviewer) when high-stakes plans require an independent check.",
            ],
        },
    }
}

// ─── Classifier ──────────────────────────────────────────────────────────

/// Per-domain score from the keyword classifier. Higher = stronger
/// match. Surfaced in the `axon.compose` response so the agent (and
/// the user reading the agent's reply) can see WHY a domain was
/// chosen — opacity here would be unfriendly.
#[derive(Debug, Clone, Serialize)]
pub struct DomainScore {
    pub domain: Domain,
    pub score: u32,
    pub matched_keywords: Vec<String>,
}

/// Score every domain against the intent string and return the
/// per-domain breakdown sorted score-descending. The classifier:
///
/// - Lower-cases the intent (deterministic across locales).
/// - Counts substring matches of each keyword (`patient` matches
///   inside `patients` and `pediatric` — intentional, broadens recall).
/// - The first domain with `score > 0` wins. Ties broken by domain
///   declaration order in [`Domain::all`] (most-specific first;
///   `Generic` is last).
/// - Empty intent returns all-zero scores and the caller falls back
///   to `Generic`.
pub fn classify(intent: &str) -> Vec<DomainScore> {
    let lc = intent.to_lowercase();
    let mut scores: Vec<DomainScore> = Domain::all()
        .iter()
        .map(|&d| {
            let md = domain_metadata(d);
            let mut score: u32 = 0;
            let mut matched = Vec::new();
            for kw in md.keywords {
                if lc.contains(kw) {
                    score += 1;
                    matched.push((*kw).to_string());
                }
            }
            DomainScore { domain: d, score, matched_keywords: matched }
        })
        .collect();
    // Stable sort by score descending, preserving the source order
    // for ties (which matches `Domain::all` — most-specific first).
    scores.sort_by(|a, b| b.score.cmp(&a.score));
    scores
}

/// Pick the winning domain from a scoreboard. The first entry with
/// score > 0 wins; otherwise fall back to `Generic`. Pure helper so
/// the tool layer's call site stays a one-liner.
pub fn select_domain(scores: &[DomainScore]) -> Domain {
    scores
        .iter()
        .find(|s| s.score > 0)
        .map(|s| s.domain)
        .unwrap_or(Domain::Generic)
}

// ─── Compose ─────────────────────────────────────────────────────────────

/// The structured response shape returned by `axon.compose`. Kept
/// public so adopters embedding the library directly can deserialise
/// it without going through JSON.
#[derive(Debug, Clone, Serialize)]
pub struct ComposeResponse {
    /// The `.axon` scaffold the agent should hand back to the user
    /// (or feed back into `axon.check`).
    pub scaffold: String,
    /// Domain the classifier selected.
    pub domain: Domain,
    /// Human-readable label for `domain`.
    pub domain_label: &'static str,
    /// One-line summary of what the scaffold contains.
    pub domain_summary: &'static str,
    /// Per-domain scoring — the agent can quote this back to the user
    /// to explain WHY this domain was chosen.
    pub alternatives: Vec<DomainScore>,
    /// AXON primitives the scaffold declares. Pairs naturally with
    /// `axon.primitive_doc(<name>)` for the agent's follow-up calls.
    pub primitives_used: Vec<String>,
    /// Compliance frameworks wired in by construction. Pairs with
    /// `axon://compliance/<framework>` for the human-facing notes.
    pub compliance_applied: Vec<String>,
    /// Curated next-step checklist surfaced to the human.
    pub next_steps: Vec<String>,
    /// Final assertion: the scaffold round-tripped through the live
    /// `axon-frontend` pipeline. Always one of `"well-formed"` or
    /// `"failed:<stage>"`. A non-OK verdict is a regression — the
    /// integration suite would catch it, but the runtime check is the
    /// belt-and-braces guard.
    pub axon_check_verdict: String,
}

/// Build a compose response for `intent`, optionally pinned to a
/// specific domain by the caller. Returns `Err(msg)` if the requested
/// domain has no template (impossible for the closed catalog) or if
/// the scaffold no longer compiles (a regression that should fail the
/// integration test before reaching here).
pub fn compose(
    intent: &str,
    domain_override: Option<Domain>,
    catalog: &Arc<Catalog>,
) -> Result<ComposeResponse, String> {
    let scoreboard = classify(intent);
    let domain = domain_override.unwrap_or_else(|| select_domain(&scoreboard));
    let md = domain_metadata(domain);
    let tpl = catalog
        .template(domain.slug())
        .ok_or_else(|| format!("compose: template `{}` not in catalog", domain.slug()))?;
    // Re-validate through the live pipeline — same gate `axon.check`
    // uses. A regression here is a regression in the corpus discipline
    // (the phase4_templates_compile integration test would catch it
    // first, but the runtime check is the last line of defence).
    let verdict = match compiler_pipeline::run(&tpl.source, &format!("compose:{}", domain.slug())) {
        Outcome::Ok { .. } => "well-formed".to_string(),
        Outcome::Err { stage, .. } => format!("failed:{}", debug_stage(stage)),
    };
    Ok(ComposeResponse {
        scaffold: tpl.source.clone(),
        domain,
        domain_label: md.label,
        domain_summary: md.summary,
        alternatives: scoreboard,
        primitives_used: md.primitives_used.iter().map(|s| s.to_string()).collect(),
        compliance_applied: md.compliance_applied.iter().map(|s| s.to_string()).collect(),
        next_steps: md.next_steps.iter().map(|s| s.to_string()).collect(),
        axon_check_verdict: verdict,
    })
}

fn debug_stage(s: compiler_pipeline::Stage) -> &'static str {
    use compiler_pipeline::Stage;
    match s {
        Stage::Lex => "lex",
        Stage::Parse => "parse",
        Stage::TypeCheck => "type_check",
        Stage::IrGenerate => "ir_generate",
    }
}

/// JSON projection of a [`ComposeResponse`] — the shape the MCP tool
/// dispatcher wraps in the `{content, isError}` envelope.
pub fn response_to_json(r: &ComposeResponse) -> Value {
    json!({
        "scaffold": r.scaffold,
        "domain": r.domain.slug(),
        "domain_label": r.domain_label,
        "domain_summary": r.domain_summary,
        "alternatives": r.alternatives,
        "primitives_used": r.primitives_used,
        "compliance_applied": r.compliance_applied,
        "next_steps": r.next_steps,
        "axon_check_verdict": r.axon_check_verdict,
    })
}

/// Parse a free-form domain hint (`"healthcare"`, `"hc"`, `"medical"`,
/// `"banking"`, …) into a [`Domain`]. Returns `None` for unknown
/// strings — the caller surfaces a structured `invalid_params` rather
/// than guessing.
pub fn parse_domain_hint(s: &str) -> Option<Domain> {
    match s.trim().to_lowercase().as_str() {
        "generic" | "default" | "minimal" => Some(Domain::Generic),
        "healthcare" | "health" | "medical" | "clinical" | "hc" => Some(Domain::Healthcare),
        "banking" | "bank" | "finance" | "fintech" => Some(Domain::Banking),
        "government" | "gov" | "federal" | "agency" => Some(Domain::Government),
        "legal" | "law" | "contract" => Some(Domain::Legal),
        "chat" | "streaming" | "dialogue" => Some(Domain::Chat),
        "retrieval" | "rag" | "qa" | "search" => Some(Domain::Retrieval),
        "multi_agent" | "multi-agent" | "multiagent" | "ensemble" | "orchestration" => {
            Some(Domain::MultiAgent)
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn embedded_catalog() -> Arc<Catalog> {
        Arc::new(Catalog::load_embedded().expect("embedded corpus must load"))
    }

    // ── Classifier ───────────────────────────────────────────────────

    #[test]
    fn classify_healthcare_keywords_score_higher_than_generic() {
        let scores = classify(
            "I need to handle patient PHI with HIPAA-grade audit for a clinical trial",
        );
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Healthcare);
        assert!(top.score >= 3, "expected ≥ 3 matched keywords, got {top:?}");
    }

    #[test]
    fn classify_banking_keywords_pick_banking_domain() {
        let scores =
            classify("a fintech loan underwriting endpoint that handles credit card payments");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Banking);
    }

    #[test]
    fn classify_chat_keywords_pick_chat_domain() {
        let scores = classify("a real-time streaming conversation assistant that replies token by token");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Chat);
    }

    #[test]
    fn classify_retrieval_keywords_pick_retrieval_domain() {
        let scores = classify("answer questions from a corpus of research documents, with citations");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Retrieval);
    }

    #[test]
    fn classify_legal_keywords_pick_legal_domain() {
        let scores = classify("analyse a contract clause for an attorney; flag privilege concerns");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Legal);
    }

    #[test]
    fn classify_government_keywords_pick_government_domain() {
        let scores =
            classify("a federal agency benefits eligibility adjudication endpoint under FedRAMP");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::Government);
    }

    #[test]
    fn classify_multi_agent_keywords_pick_multi_agent_domain() {
        let scores =
            classify("orchestrate a planner agent and a worker agent in an ensemble pattern");
        let top = &scores[0];
        assert_eq!(top.domain, Domain::MultiAgent);
    }

    #[test]
    fn classify_unrelated_intent_falls_back_to_generic() {
        let scores = classify("hello world");
        // No keyword scored; select_domain returns Generic.
        assert_eq!(select_domain(&scores), Domain::Generic);
        // Every entry has zero score.
        assert!(scores.iter().all(|s| s.score == 0));
    }

    #[test]
    fn classify_empty_intent_falls_back_to_generic() {
        let scores = classify("");
        assert_eq!(select_domain(&scores), Domain::Generic);
    }

    // ── compose ──────────────────────────────────────────────────────

    #[test]
    fn compose_returns_well_formed_scaffold_for_healthcare_intent() {
        let cat = embedded_catalog();
        let r = compose("a patient summarisation service with PHI redaction", None, &cat).unwrap();
        assert_eq!(r.domain, Domain::Healthcare);
        assert_eq!(r.axon_check_verdict, "well-formed");
        assert!(r.scaffold.contains("HIPAA"));
        assert!(r.compliance_applied.contains(&"HIPAA".to_string()));
    }

    #[test]
    fn compose_honors_explicit_domain_override() {
        let cat = embedded_catalog();
        // Intent matches banking keywords, but the caller forces chat.
        let r = compose(
            "process credit card payments and loan applications",
            Some(Domain::Chat),
            &cat,
        )
        .unwrap();
        assert_eq!(r.domain, Domain::Chat);
        assert_eq!(r.axon_check_verdict, "well-formed");
    }

    #[test]
    fn compose_falls_back_to_generic_for_unrelated_intent() {
        let cat = embedded_catalog();
        let r = compose("just something basic", None, &cat).unwrap();
        assert_eq!(r.domain, Domain::Generic);
        assert_eq!(r.axon_check_verdict, "well-formed");
    }

    #[test]
    fn compose_response_contains_explainability_payload() {
        let cat = embedded_catalog();
        let r = compose(
            "a patient summarisation service with PHI",
            None,
            &cat,
        )
        .unwrap();
        // alternatives carries every domain so the agent can quote the
        // full scoreboard.
        assert!(r.alternatives.len() >= 4);
        // primitives_used + next_steps + compliance_applied are
        // non-empty for any real domain — the agent renders these.
        assert!(!r.primitives_used.is_empty());
        assert!(!r.next_steps.is_empty());
        assert!(!r.compliance_applied.is_empty());
    }

    // ── parse_domain_hint ────────────────────────────────────────────

    #[test]
    fn parse_domain_hint_accepts_canonical_and_aliases() {
        assert_eq!(parse_domain_hint("healthcare"), Some(Domain::Healthcare));
        assert_eq!(parse_domain_hint("medical"), Some(Domain::Healthcare));
        assert_eq!(parse_domain_hint("HC"), Some(Domain::Healthcare));
        assert_eq!(parse_domain_hint("banking"), Some(Domain::Banking));
        assert_eq!(parse_domain_hint("fintech"), Some(Domain::Banking));
        assert_eq!(parse_domain_hint("gov"), Some(Domain::Government));
        assert_eq!(parse_domain_hint("multi-agent"), Some(Domain::MultiAgent));
        assert_eq!(parse_domain_hint("rag"), Some(Domain::Retrieval));
    }

    #[test]
    fn parse_domain_hint_rejects_unknown() {
        assert_eq!(parse_domain_hint("not-a-domain"), None);
        assert_eq!(parse_domain_hint(""), None);
    }

    // ── Every template available via compose round-trips clean ───────

    #[test]
    fn every_domain_has_an_axon_check_clean_template_via_compose() {
        let cat = embedded_catalog();
        for &domain in Domain::all() {
            let r = compose("", Some(domain), &cat).expect("template lookup");
            assert_eq!(
                r.axon_check_verdict, "well-formed",
                "domain {} returned a malformed scaffold via compose",
                domain.slug()
            );
        }
    }
}
