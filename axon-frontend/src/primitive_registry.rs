//! The closed registry of every primitive AXON exposes as a named
//! language construct.
//!
//! # Why this exists
//!
//! Before §Fase 6.a, the answer to "what primitives does AXON have?"
//! was scattered across the parser dispatch table, the type checker's
//! validation arms, the ℰMCP knowledge corpus, and a half-dozen
//! markdown reference pages. There was no machine-readable canonical
//! list. A new primitive landing in the parser could go undocumented
//! for a release cycle (or three) before someone noticed.
//!
//! `PRIMITIVE_REGISTRY` closes that gap. It is **the** single source
//! of truth for the closed set of primitive names — consumed by:
//!
//! - **ℰMCP coverage gate** — tests under `axon-emcp` that assert
//!   every `Documented` entry has a markdown body in the corpus, AND
//!   that every markdown body has a `Documented` entry here. The
//!   closed set is enforced on BOTH sides; the corpus cannot drift.
//! - **`axon-emcp scaffold-primitive` CLI** — reads the entry, stamps
//!   a markdown skeleton with frontmatter pre-populated from the
//!   registry. Reduces "add new primitive doc" to a 30-second task.
//! - **Future LSP completions / docs site / `axon.primitives()` tool**
//!   — any consumer that needs a deterministic catalogue iterates
//!   over `PRIMITIVE_REGISTRY` directly.
//!
//! # Discipline
//!
//! When a new primitive lands in the parser, the SAME PR adds the
//! entry here AND the markdown doc under
//! `src/knowledge/primitives/<name>.md`. The two are atomic. No
//! orphan parser productions, no orphan corpus entries.
//!
//! For primitives that exist in the parser today but haven't been
//! documented yet, the entry lives here with `doc_status: Pending`.
//! The §Fase 6.b–d roadmap flips each `Pending` → `Documented` as
//! its `.md` lands.

/// One primitive's **shallow** metadata. Deep documentation (grammar,
/// fields, runtime behaviour, examples, see-also) lives in the
/// markdown corpus under `src/knowledge/primitives/<name>.md` —
/// surfaced by the ℰMCP catalogue loader via
/// `axon.primitive_doc(<name>)`. The registry carries only what every
/// consumer needs to identify and classify the primitive.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PrimitiveInfo {
    /// Canonical name as it appears in source (`persona`, `flow`,
    /// `socket`, `axonendpoint`, …). Doubles as the markdown file
    /// stem (`<name>.md`) and the URL slug for
    /// `axon://primitives/{name}`.
    pub name: &'static str,
    /// Closed-catalogue family. Drives the
    /// `axon.primitives(filter)` facet and the `category:` field of
    /// the corpus frontmatter. Valid values: `"cognition"`,
    /// `"cognitive_io"`, `"data_plane"`, `"session_types"`, `"wire"`,
    /// `"operators"`. Validated against the ℰMCP `Category` enum at
    /// catalog-load time — a category string here that does not
    /// deserialize into a `Category` is a coverage-gate failure.
    pub category: &'static str,
    /// `true` ⇒ this primitive is a top-level declaration (it stands
    /// alone at the program root). `false` ⇒ it only appears nested
    /// inside another construct (e.g. `step` inside a `flow`).
    pub top_level: bool,
    /// The cycle that introduced this primitive (e.g. `"v0.1.0"`,
    /// `"Fase 41.b (v2.3.0)"`). Surfaced verbatim in the corpus
    /// frontmatter `since:` field.
    pub since: &'static str,
    /// One-line summary used by `axon.primitives()` listings and by
    /// the `axon-emcp scaffold-primitive` CLI when stamping a new
    /// doc's frontmatter. Should fit on one line, end with a period.
    pub summary: &'static str,
    /// Whether the primitive has a corresponding markdown doc in the
    /// ℰMCP corpus today. The §Fase 6 plan ships every primitive's
    /// doc in tiers (6.b, 6.c, 6.d); entries flip from `Pending` to
    /// `Documented` as their `.md` lands.
    pub doc_status: DocStatus,
}

/// Coverage status for one primitive's documentation. The coverage
/// gate in `axon-emcp` asserts that:
///
/// 1. every `Documented` entry has a `.md` under
///    `src/knowledge/primitives/`;
/// 2. every `.md` under that directory has a `Documented` entry here.
///
/// `Pending` entries are visible in the registry (so the catalogue
/// is honestly complete) but the coverage gate does NOT require
/// their docs yet — that is the §Fase 6.b–d roadmap.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DocStatus {
    /// Documented — has a markdown body in the corpus + passes the
    /// drift-gated canonical-program test where applicable. The
    /// coverage gate requires `<name>.md` to exist.
    Documented,
    /// Pending — the primitive exists in the language but its
    /// markdown doc has not landed yet. The §Fase 6 roadmap names
    /// the cycle (6.b / 6.c / 6.d) that closes the gap.
    Pending,
}

impl DocStatus {
    /// Stringify for diagnostics. Mirrors the `serde` rename rule
    /// the ℰMCP catalogue uses for its own enums.
    pub fn as_str(self) -> &'static str {
        match self {
            DocStatus::Documented => "documented",
            DocStatus::Pending => "pending",
        }
    }
}

/// The closed catalogue — **47 primitives**, ordered by category
/// for readability. Consumers must not depend on declaration order;
/// they iterate and filter.
///
/// Section breakdown:
/// - Cognition (15) — what an LLM does.
/// - Cognitive I/O (10) — resources + reconciliation + self-defence.
/// - Data plane (6) — typed persistence + provenance.
/// - Session types (2) — §Fase 41 algebra.
/// - Wire (6) — actor + transport surfaces.
/// - Operators (8) — specialised cognitive transforms.
///
/// Tier 0 — Documented as of §Fase 5 (7): `persona`, `flow`, `step`,
/// `anchor`, `tool`, `reason`, `socket`.
///
/// Tier 1 / 2 / 3 — Pending (40), landing in §Fase 6.b / 6.c / 6.d.
pub const PRIMITIVE_REGISTRY: &[PrimitiveInfo] = &[
    // ── Cognition ─────────────────────────────────────────────────────
    PrimitiveInfo {
        name: "persona",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "Declares the identity, expertise, and refusal posture an agent adopts when executing a flow.",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "context",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "Declares the conversational frame — memory scope, depth, max tokens, temperature — a flow operates within.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "flow",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "The orchestration primitive — a typed, ordered composition of cognitive steps with parameters and a return type.",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "anchor",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "A typed grounding constraint — declares the conditions a flow's outputs MUST satisfy, with a structured violation policy.",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "tool",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "A declarative binding for an external capability (search, web fetch, code interpreter, …) callable from within a flow.",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "intent",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "A declarative target outcome — what the flow is trying to achieve, separately from how it gets there.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "memory",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "Declares a typed memory store — session, persistent, vector — for cross-step state with retrieval + decay semantics.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "agent",
        category: "cognition",
        top_level: true,
        since: "Fase 18",
        summary: "An orchestrated cognitive entity — composes personas, tools, contexts under a coordination strategy.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "run",
        category: "cognition",
        top_level: true,
        since: "v0.1.0",
        summary: "Binds a flow to a persona, context, and anchors — the statement that EXECUTES a declared flow.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "step",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "A single cognitive operation inside a flow — typed input (given), prompt (ask), and typed output.",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "reason",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "An explicit-reasoning operation — declares HOW the model should think (chain-of-thought, debate, …).",
        doc_status: DocStatus::Documented,
    },
    PrimitiveInfo {
        name: "probe",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "A diagnostic / probing operation inside a step — emits observations without changing the trajectory.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "validate",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "Enforces a typed invariant on a step's output before subsequent steps consume it.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "refine",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "Iteratively improves a candidate output via a declared refinement strategy.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "weave",
        category: "cognition",
        top_level: false,
        since: "v0.1.0",
        summary: "Multi-thread reasoning braid — composes multiple sub-derivations into a unified conclusion.",
        doc_status: DocStatus::Pending,
    },
    // ── Cognitive I/O ─────────────────────────────────────────────────
    PrimitiveInfo {
        name: "resource",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "Declares an external compute/storage resource (database, S3, ML endpoint) consumable by a flow.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "fabric",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "The cloud-substrate declaration — provider, region, zones, ephemerality, bound shield.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "manifest",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "Bundles resources + fabric + compliance tags into a deployable, audit-tracked unit.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "observe",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "Declares an observability surface — sources, quorum, timeout, certainty floor, partition policy.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "reconcile",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "A typed reconciliation loop — observes drift against a manifest and applies bounded corrections.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "lease",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "Time-bounded resource acquisition with typed expiry, renewal, and revocation semantics.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "ensemble",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 6",
        summary: "Coordinates multiple cognitive entities under a consensus or quorum protocol with structured tie-breaking.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "immune",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 19",
        summary: "Continuous-monitoring agent that learns a baseline + emits epistemic-level signals on anomalies.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "reflex",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 19",
        summary: "An automatic-response trigger bound to an immune system's level — fires structured actions on threshold breach.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "heal",
        category: "cognitive_io",
        top_level: true,
        since: "Fase 19",
        summary: "A recovery routine bound to an immune system's level — runs scoped repairs, often human-in-the-loop.",
        doc_status: DocStatus::Pending,
    },
    // ── Data plane ────────────────────────────────────────────────────
    PrimitiveInfo {
        name: "type",
        category: "data_plane",
        top_level: true,
        since: "v0.1.0",
        summary: "Declares a structured data type with optional refinements, ranges, where clauses, and compliance tags.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "axonstore",
        category: "data_plane",
        top_level: true,
        since: "Fase 36",
        summary: "A typed, audit-chained data store — relational backend, isolation level, encryption, retention, on-breach policy.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "dataspace",
        category: "data_plane",
        top_level: true,
        since: "Fase 36",
        summary: "A named, isolated data namespace — multi-tenant by construction, with cross-tenant proof obligations.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "corpus",
        category: "data_plane",
        top_level: true,
        since: "Fase 36",
        summary: "A retrieval-ready collection of documents — backs RAG and grounded retrieval with citation provenance.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "pix",
        category: "data_plane",
        top_level: true,
        since: "Fase 19",
        summary: "Provenance Index — an append-only, hash-linked chain of every state transition with tamper-evident verification.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "transact",
        category: "data_plane",
        top_level: false,
        since: "Fase 36",
        summary: "A flow-body block that wraps multiple data-plane mutations in a single transactional unit with rollback semantics.",
        doc_status: DocStatus::Pending,
    },
    // ── Session types (§Fase 41) ──────────────────────────────────────
    PrimitiveInfo {
        name: "session",
        category: "session_types",
        top_level: true,
        since: "Fase 41.a (v2.3.0)",
        summary: "Declares the typed bidirectional dialogue protocol a socket carries — §41 algebra (send/receive/select/branch/loop/end).",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "socket",
        category: "session_types",
        top_level: true,
        since: "Fase 41.b (v2.3.0)",
        summary: "Session-typed WebSocket transport with credit-refined backpressure, typed reconnection, and SSE-as-fragment projection.",
        doc_status: DocStatus::Documented,
    },
    // ── Wire ──────────────────────────────────────────────────────────
    PrimitiveInfo {
        name: "axonendpoint",
        category: "wire",
        top_level: true,
        since: "Fase 32",
        summary: "HTTP REST primitive — exposes a flow on a typed route with body/output schemas, transport classification, and compliance.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "axpoint",
        category: "wire",
        top_level: true,
        since: "Fase 32",
        summary: "Lightweight axonendpoint — for simple request/response flows without the full request-binding schema scaffolding.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "daemon",
        category: "wire",
        top_level: true,
        since: "Fase 16",
        summary: "A long-lived, supervised cognitive process — reacts to events on declared listeners with structured restart semantics.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "mcp",
        category: "wire",
        top_level: true,
        since: "Fase 33+",
        summary: "Declares an outbound MCP server binding — turns axon into an MCP client of another server.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "taint",
        category: "wire",
        top_level: true,
        since: "Fase 26",
        summary: "A typed tag carrying provenance + integrity status across the boundary of trust.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "listen",
        category: "wire",
        top_level: false,
        since: "Fase 16",
        summary: "A flow/daemon-body listener — binds to an event source and dispatches typed messages downstream.",
        doc_status: DocStatus::Pending,
    },
    // ── Operators ─────────────────────────────────────────────────────
    PrimitiveInfo {
        name: "shield",
        category: "operators",
        top_level: true,
        since: "Fase 20",
        summary: "A composable defence layer — scans inputs/outputs for declared threats with a structured on-breach policy.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "mandate",
        category: "operators",
        top_level: true,
        since: "Fase 21",
        summary: "A typed approval requirement — gates a flow's execution on a capability check + optional segregation of duties.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "compute",
        category: "operators",
        top_level: true,
        since: "Fase 17",
        summary: "Binds a flow to a specific compute backend — model selection, effort hint, parallelism, deterministic seed.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "lambda",
        category: "operators",
        top_level: true,
        since: "Fase 15",
        summary: "An anonymous, typed function bound to a flow's data plane — supports lambda apply semantics for inline composition.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "forge",
        category: "operators",
        top_level: false,
        since: "Fase 18",
        summary: "A flow-body block that constructs typed values from sub-step outputs under explicit construction discipline.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "ots",
        category: "operators",
        top_level: true,
        since: "Fase 11",
        summary: "One-shot transform — a closed-catalogue media transformation (audio, image, format) with native/ffmpeg backend dispatch.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "psyche",
        category: "operators",
        top_level: true,
        since: "Fase 14",
        summary: "Declares the psychological model a persona enacts — beliefs, desires, traits, behavioural disposition.",
        doc_status: DocStatus::Pending,
    },
    PrimitiveInfo {
        name: "logic",
        category: "operators",
        top_level: true,
        since: "Fase 23",
        summary: "Declares a logic surface — propositional rules, predicate constraints, algebraic-effect handlers.",
        doc_status: DocStatus::Pending,
    },
];

/// Lookup one primitive by canonical name. O(n) over the 47-entry
/// table — n is small, the linear scan beats any hash overhead.
/// Returns `None` for unknown names; callers surface a structured
/// "unknown primitive" diagnostic.
pub fn find(name: &str) -> Option<&'static PrimitiveInfo> {
    PRIMITIVE_REGISTRY.iter().find(|i| i.name == name)
}

/// Filter the registry by closed-catalogue category. Returns an
/// iterator so callers can chain into collectors of their choice.
/// An unknown category returns an empty iterator — by design;
/// validation against the closed set is the caller's responsibility.
///
/// Lifetime `'a` ties the returned iterator to the input string so
/// edition-2021 implicit-capture rules accept the closure's borrow.
pub fn by_category<'a>(category: &'a str) -> impl Iterator<Item = &'static PrimitiveInfo> + 'a {
    PRIMITIVE_REGISTRY.iter().filter(move |i| i.category == category)
}

/// Filter the registry by documentation status. The §Fase 6 coverage
/// gate uses `with_status(DocStatus::Documented)` to know which
/// entries MUST have a corresponding `.md`.
pub fn with_status(status: DocStatus) -> impl Iterator<Item = &'static PrimitiveInfo> {
    PRIMITIVE_REGISTRY.iter().filter(move |i| i.doc_status == status)
}

/// Count primitives by `(category, doc_status)`. Used in tests + the
/// `axon-emcp` coverage gate's diagnostic output so a gate failure
/// surfaces a structured "what's missing" report rather than an
/// opaque assertion.
pub fn coverage_summary() -> CoverageSummary {
    let mut summary = CoverageSummary::default();
    for info in PRIMITIVE_REGISTRY {
        match info.doc_status {
            DocStatus::Documented => summary.documented += 1,
            DocStatus::Pending => summary.pending += 1,
        }
    }
    summary.total = PRIMITIVE_REGISTRY.len();
    summary
}

/// Aggregate documentation-coverage counts. Used by the §Fase 6
/// coverage gate + future telemetry to surface "we have N
/// primitives, M documented, N-M pending" at a glance.
#[derive(Debug, Default, Clone, Copy)]
pub struct CoverageSummary {
    pub total: usize,
    pub documented: usize,
    pub pending: usize,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    /// The valid category strings — must match the closed set in
    /// the ℰMCP `Category` enum. The coverage gate test in
    /// `axon-emcp` does the cross-check; here we just validate
    /// shape locally so the registry is self-consistent without
    /// needing the downstream crate.
    const VALID_CATEGORIES: &[&str] = &[
        "cognition",
        "cognitive_io",
        "data_plane",
        "session_types",
        "wire",
        "operators",
    ];

    #[test]
    fn registry_contains_the_expected_count() {
        // The total count is meaningful — a regression that drops a
        // primitive would manifest as a smaller catalogue. We pin
        // the count so the regression surface is the test, not
        // post-hoc debugging.
        assert_eq!(
            PRIMITIVE_REGISTRY.len(),
            47,
            "PRIMITIVE_REGISTRY count drift — add the new primitive intentionally + update this assertion"
        );
    }

    #[test]
    fn every_entry_has_a_non_empty_name_and_summary() {
        for info in PRIMITIVE_REGISTRY {
            assert!(!info.name.is_empty(), "empty name in registry");
            assert!(
                !info.summary.is_empty(),
                "primitive `{}` has an empty summary — scaffold + listings would be unhelpful",
                info.name
            );
            assert!(
                !info.since.is_empty(),
                "primitive `{}` has an empty since — corpus frontmatter would be invalid",
                info.name
            );
        }
    }

    #[test]
    fn every_entry_has_a_valid_category() {
        for info in PRIMITIVE_REGISTRY {
            assert!(
                VALID_CATEGORIES.contains(&info.category),
                "primitive `{}` has invalid category `{}` — valid: {VALID_CATEGORIES:?}",
                info.name, info.category
            );
        }
    }

    #[test]
    fn primitive_names_are_unique() {
        let mut seen: HashSet<&str> = HashSet::new();
        for info in PRIMITIVE_REGISTRY {
            assert!(
                seen.insert(info.name),
                "duplicate primitive name in registry: `{}`",
                info.name
            );
        }
    }

    #[test]
    fn documented_tier_matches_phase_5_baseline() {
        // §Fase 5 baseline: 7 primitives documented (persona, flow,
        // step, anchor, tool, reason, socket). A regression that
        // accidentally flipped a Documented entry to Pending — or
        // vice versa — would show up here.
        let documented: HashSet<&str> = with_status(DocStatus::Documented)
            .map(|i| i.name)
            .collect();
        let expected: HashSet<&str> = ["persona", "flow", "step", "anchor", "tool", "reason", "socket"]
            .into_iter()
            .collect();
        assert_eq!(
            documented, expected,
            "Documented set drift — Fase 5 baseline is 7 specific primitives"
        );
    }

    #[test]
    fn coverage_summary_is_arithmetic() {
        let s = coverage_summary();
        assert_eq!(s.total, 47);
        assert_eq!(s.documented + s.pending, s.total);
        assert_eq!(s.documented, 7);
        assert_eq!(s.pending, 40);
    }

    #[test]
    fn find_resolves_documented_and_pending_entries() {
        assert_eq!(find("persona").map(|i| i.name), Some("persona"));
        assert_eq!(find("axonendpoint").map(|i| i.name), Some("axonendpoint"));
        assert!(find("does_not_exist").is_none());
    }

    #[test]
    fn by_category_filters_to_the_named_family() {
        let cog: Vec<&str> = by_category("cognition").map(|i| i.name).collect();
        assert!(cog.contains(&"persona"));
        assert!(cog.contains(&"flow"));
        assert!(!cog.contains(&"socket"), "socket is session_types, not cognition");
        assert!(!cog.contains(&"axonendpoint"), "axonendpoint is wire, not cognition");
    }

    #[test]
    fn nested_primitives_carry_top_level_false() {
        // The "lives only inside a parent" set — coverage gate cross-
        // checks against `axon://grammar/top_level` which is the
        // human-readable mirror of this same polarity.
        for nested in ["step", "reason", "probe", "validate", "refine", "weave",
                       "listen", "forge", "transact"] {
            let info = find(nested).expect("must be in registry");
            assert!(
                !info.top_level,
                "primitive `{}` should be nested (top_level: false)",
                info.name
            );
        }
    }
}
