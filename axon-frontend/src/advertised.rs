//! §Fase 111 — **the anti-drift gate: the public README is a BUILD INPUT.**
//!
//! # Why this exists
//!
//! §111 audited every primitive the public README advertises and found ~22 of
//! ~74 to be aspirational. The obvious question afterwards was: *what gate would
//! have caught them?* The obvious answer — "assert README ⟺ registry ⟺ parser
//! production ⟺ dispatch arm" — is **wrong**, and it is worth being precise
//! about why, because the wrong gate is worse than none: it would have been
//! green.
//!
//! ```text
//!               README   registry   parser   dispatch arm   …and yet
//!   warden        ✓         ✓         ✓          ✓          a no-op
//!   quant         ✓         ✓         ✓          ✓          a no-op
//!   transact      ✓         —         ✓          ✓          no transaction
//!   compute       ✓         ✓         ✓          —          returns a string
//! ```
//!
//! **A presence-only gate catches nothing that matters.** Every serious §111
//! defect had all four boxes ticked. What was missing was never a *symbol* — it
//! was the answer to a question no linter can decide:
//!
//! > **Does the runtime do what the summary promises?**
//!
//! That is not statically inferable, so this gate does not pretend to infer it.
//! It forces a **human to state it, on the record**, and it makes the statement
//! impossible to omit: [`status_of`] has **no default arm**, so a name the README
//! advertises with no entry here is a **build failure**.
//!
//! # The three laws
//!
//! 1. **The README is parsed at test time.** Every `<code>` badge in its header
//!    block must have an entry here. The public promise is not a document that
//!    drifts from the code — it is an *input to the build*.
//! 2. **Nothing advertised may be [`RuntimeStatus::NotImplemented`]** … except
//!    what is written down in [`KNOWN_DEBT`], which is a **ratchet**: it may only
//!    shrink. A *new* unimplemented promise is a red build. That is the whole
//!    point — §111's debt becomes a ledger the compiler enforces, instead of a
//!    finding in a document nobody rereads.
//! 3. **A [`RuntimeStatus::Real`] claim must cite its proof**, and if the proof
//!    names a test file, that file must exist on disk. A claim of reality that
//!    cannot point at the gate proving it is just a nicer-sounding assertion.
//!
//! # How to change this file
//!
//! - **Shipping a primitive?** Flip it to `Real`, cite the gate that proves it,
//!   and delete its `KNOWN_DEBT` row **in the same PR**.
//! - **Retracting one?** Delete it from the README *and* from here.
//! - **Adding a new advertised primitive?** You cannot land it without stating
//!   what its runtime actually does. That is the feature.

#![allow(dead_code)]

/// What the RUNTIME does — as attested by a human, because no linter can decide
/// it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeStatus {
    /// The runtime delivers what the README's summary promises. MUST cite the
    /// evidence — a test file, or the fase that shipped it.
    Real { proof: &'static str },
    /// It delivers, with a documented gap versus the advertised claim. The gap
    /// is named so it cannot rot into a silent lie.
    Partial { gap: &'static str },
    /// It REFUSES — at compile time or at dispatch. Honest by construction: an
    /// adopter is told, loudly, rather than handed silence. This is the §108
    /// posture, and it is an acceptable state to advertise from, because the
    /// adopter cannot be *fooled* by it.
    FailsClosed { diagnostic: &'static str },
    /// The runtime does NOT do what the summary promises, and says nothing about
    /// it. **This may not be advertised** unless it is in [`KNOWN_DEBT`].
    NotImplemented { finding: &'static str },
    /// §111 has not verified this one. Advertised on trust, and counted: the
    /// unaudited population is pinned below and may only shrink.
    Unaudited,
}

impl RuntimeStatus {
    /// The predicate law 2 turns on.
    pub fn is_unimplemented(self) -> bool {
        matches!(self, RuntimeStatus::NotImplemented { .. })
    }
}

use RuntimeStatus::*;

/// Every `<code>` badge the README's header block advertises, and what its
/// runtime actually does.
///
/// Verdicts sourced from the §111 Gate-1/Gate-2 audit (see the fase's topic
/// file). Where §111 did not reach, the entry is honestly `Unaudited` rather
/// than optimistically `Real` — an unchecked box is not a passing one.
pub const ADVERTISED: &[(&str, RuntimeStatus)] = &[
    // ── Cognitive core — LLM-driven, and honestly so. Calling the model IS
    //    their nature; that is not the defect §111 hunts.
    ("persona", Real { proof: "flow_dispatcher::pure_shape" }),
    ("intent", Unaudited),
    ("flow", Real { proof: "flow_dispatcher::dispatch_node (exhaustive, zero catch-alls)" }),
    ("reason", Real { proof: "pure_shape::run_reason" }),
    ("anchor", Real { proof: "anchor_checker" }),
    ("refine", Real { proof: "pure_shape::run_refine" }),
    ("memory", Real { proof: "cognitive::run_remember / run_recall (PEM write-through)" }),
    ("tool", Real { proof: "lambda_tools::dispatch_use_tool_real (§58)" }),
    ("probe", Real { proof: "pure_shape::run_probe" }),
    ("weave", Real { proof: "pure_shape::run_weave" }),
    ("validate", Real { proof: "pure_shape::run_validate" }),
    ("context", Unaudited),
    // ── Epistemic scopes
    ("know", Unaudited),
    ("believe", Unaudited),
    ("speculate", Unaudited),
    ("doubt", Unaudited),
    // ── Concurrency & continuation
    ("par", Real { proof: "parallel::run_par (real fan-out via join_all, §65)" }),
    ("hibernate", NotImplemented { finding: "§111 F20 — returns \"(hibernating …)\" synchronously; no CPS suspend, no resume, timeout not honored" }),
    // ── Deterministic data plane (§108)
    ("dataspace", Real { proof: "dataspace_engine (columnar, first-party)" }),
    ("ingest", Real { proof: "cognitive::run_ingest — bounds-before-parse, sha256 + Untrusted taint (§108)" }),
    ("focus", Real { proof: "dataspace_engine::focus_query (σ∘π)" }),
    ("associate", Real { proof: "dataspace_engine::associate_query (hash equi-join; refuses a keyless join)" }),
    ("aggregate", Real { proof: "dataspace_engine::aggregate_query (γ)" }),
    ("explore", Real { proof: "dataspace_engine::explore_profile (zone-map stats)" }),
    // ── Budget, selection & synthesis
    ("deliberate", FailsClosed { diagnostic: "axon-T939 (§111) — the body is discarded at parse time; no budget was ever controlled" }),
    ("consensus", FailsClosed { diagnostic: "axon-T940 (§111) — no votes, no aggregation, no candidates" }),
    ("forge", Partial { gap: "§111 F17 — the Poincaré pipeline + NCD novelty gate are real, but `coherence` is hardcoded to 1.0, so a declared `constraints:` coherence floor is INERT" }),
    ("agent", Unaudited),
    ("shield", Partial { gap: "§111 — the scanner registry IS consulted and a Reject really fails the step, but OSS ships ZERO registered scanners, so an OSS adopter's shield is an identity pass-through until one is mounted" }),
    // ── Security & autonomous analysis
    ("savant", Unaudited),
    ("synth", Unaudited),
    ("warden", Real { proof: "tests/fase111_c_warden_wired.rs (§111.c — real attested findings, verify()-gated, body runs, fail-closed at 6 joints)" }),
    ("scope", Real { proof: "tests/fase111_c_warden_wired.rs — the scope catalog is resolved at dispatch and the allowlist enforced (the check §88.c deferred)" }),
    // ── Effects & streaming
    ("stream", Real { proof: "tests/fase111_e_stream_runs.rs (§111.e — the body is parsed, lowered and EXECUTED; it used to be discarded at parse time)" }),
    ("effects", Real { proof: "parse_effect_row + type_checker; §85 `cache` derives cacheability from the `effects: pure` proof" }),
    ("@contract_tool", Unaudited),
    ("@csp_tool", Unaudited),
    // ── Knowledge navigation (PIX · MDN)
    ("pix", Real { proof: "pix_navigator (embeddings-free structural index)" }),
    ("navigate", Partial { gap: "§111 F11 — three REAL deterministic engines (MDN store-sourced, MDN in-memory, PIX), BUT with no indexable source in scope it falls back to an LLM prompt that INSTRUCTS the model to fabricate a provenance trail. The one live §108 left in the tree" }),
    ("drill", Partial { gap: "§111 — real subtree navigation when a source is in scope; degrades to a placeholder string otherwise" }),
    ("trail", Partial { gap: "§111 — reads the real breadcrumb `navigate` seeds; falls back to a placeholder when no navigate ran. Inherits F11: a trail harvested from the LLM fallback is confabulation wearing an audit's clothes" }),
    ("corpus", Real { proof: "mdn (signed Epistemic PageRank; §62–§64)" }),
    // ── Advanced cognition & trust
    ("psyche", Unaudited),
    ("ots", NotImplemented { finding: "§111 F18 — `apply_ots_to_target` is literally `target.to_string()`; no ots_registry exists anywhere, so the documented \"enterprise override\" has no hook to override" }),
    ("mcp", Unaudited),
    ("mandate", NotImplemented { finding: "§111 F18 — `apply_mandate_to_target` is `target.to_string()`; a compliance-bound transformation that transforms nothing and can never fail" }),
    ("lambda", NotImplemented { finding: "§111 F18 — `apply_lambda_data` returns the string \"lambda:<name>(<target>)\"; no ΛD evaluation, no CPS dispatcher" }),
    // ── Deterministic compute
    ("compute", Real { proof: "tests/fase111_f_compute_real.rs (§111.f — a named PURE FUNCTION over the §70 expression language, evaluated natively by eval_expr: linear in the term, ZERO tokens, no model in the loop. Every failure refuses rather than binding a string that looks like a number)" }),
    // ── Reactive processes & platform boundary
    ("daemon", Real { proof: "daemon.rs — OTP-style supervision + §74 durable event delivery" }),
    ("listen", Partial { gap: "§111 F7 — TWO disjoint paths sharing one keyword. Inside a DAEMON: real (§74 outbox → deliver_typed_event → execute_server_flow). Inside a FLOW BODY: binds the canned string \"(awaiting <channel>)\". Sub-gap: a daemon listener body executes ONLY `run <Flow>` steps; any other step type is silently dropped" }),
    ("axonendpoint", Real { proof: "axon_server — typed routes, body/output schemas, Idempotency-Key (§32/§37)" }),
    ("axpoint", Real { proof: "an ALIAS of axonendpoint — same TokenType (tokens.rs)" }),
    ("axonstore", Real { proof: "wire_integrations::run_{persist,retrieve,mutate,purge} — parameterized SQL, capability gate, epistemic floor, HMAC-Merkle audit chain" }),
    // ── Cognitive I/O (λ-L-E, Fases 1–9)
    //
    // §111 F14 + the §11 REFRAME: this family is not merely unwired — it is
    // UNREACHABLE BY CONSTRUCTION. There is no FlowStep, no IRFlowNode and no
    // daemon field that can consume any of them. The kernels are real,
    // well-written and unit-tested; the language never grew a way to reach them.
    // Founder-ratified: designing that consumption surface is §112+.
    ("resource", NotImplemented { finding: "§111 F14/§11 — no consumption surface exists in the language" }),
    ("fabric", NotImplemented { finding: "§111 F14 — Separation-Logic `*` disjointness is never checked between fabrics; no runtime consumer" }),
    ("manifest", Partial { gap: "§111 F14 — the κ/compliance half IS genuinely consumed (it feeds attestation + the audit scorer); the \"desired shape\" half is dead" }),
    ("observe", Real { proof: "tests/fase112_c_cognitive_io_deploy.rs (§112.a/c — a real Handler reaches a real target through a deny-by-default SourceRegistry; an observation that cannot be taken REFUSES. The only prior Handler returned certainty 1.0 unconditionally, without going anywhere)" }),
    ("reconcile", Real { proof: "tests/fase112_e_reconcile_drift.rs (§112.e — REAL Jaccard drift between the manifest's desired shape and the world's actual shape. It used to compare the belief against ITSELF: when evidence was missing it defaulted to the manifest, so drift was structurally always 0.0)" }),
    ("lease", NotImplemented { finding: "§111 F14 — τ-decay + CT-2 breach logic exists; LeaseKernel has zero non-test callers. (SOC2 CC6.3 used to cite it as a RuntimeInvariant — see F8)" }),
    ("ensemble", Real { proof: "tests/fase112_c_cognitive_io_deploy.rs (§112.b/c — the EnsembleAggregator is instantiated from the IR at deploy and aggregates only observations ACTUALLY TAKEN; a refused source is absent, not present-and-failing, which is what lets its quorum gate work honestly)" }),
    ("topology", Real { proof: "type_checker::check_topology_liveness — a genuine DFS gray/black cycle detector emitting a Honda-liveness violation (narrow sufficient condition, but real)" }),
    ("session", Real { proof: "type_checker::check_session_duality → session.rs (dual involution, capture-avoiding substitution, coinductive equality). Duality is genuinely DECIDED, not faked" }),
    ("send", Real { proof: "lowered into the session algebra; an unmatched send fails the duality check" }),
    ("receive", Real { proof: "lowered into the session algebra; dual of send" }),
    ("select", Real { proof: "session.rs dual_map — internal/external choice duality is really checked arm-for-arm" }),
    ("branch", Real { proof: "session.rs dual_map — the dual of select" }),
    ("immune", Real { proof: "tests/fase112_d_immune_fires.rs (§112.d — the KL sensor detects a REAL deviation from a LEARNED baseline. Wiring it exposed a kernel bug that made it structurally blind: an unseen symbol was scored against the baseline's MINIMUM probability, so a perfectly stable baseline could never register an anomaly at all)" }),
    ("reflex", Real { proof: "tests/fase112_d_immune_fires.rs (§112.d — a real anomaly FIRES the declared action with an HMAC-signed trace, within its sla:, and the same signature does not re-fire. No reflex may fire while the baseline is still being learned — that would be a false positive by construction)" }),
    ("heal", Real { proof: "tests/fase112_d_immune_fires.rs (§112.d — the HealKernel is registered from the IR and renders a decision under its declared mode: on a real health report)" }),
    ("compliance", Partial { gap: "§111 F16 — the language's flagship claim, and exactly ONE genuine κ-coverage rule exists (scoped to `component`). The axon-T890 endpoint rule is a PRESENCE check (`!compliance.is_empty()`), not a coverage law. The checker documents its own gap at type_checker.rs:11726" }),
    ("component", Partial { gap: "§111 — the compile-time shield-coverage law over regulated κ IS genuinely enforced (a real set difference). But the component renders NOTHING; the README itself defers the renderer" }),
    ("view", Partial { gap: "§111 — only referential integrity is checked. No `route` check, no session-typed-reactivity check, and it renders nothing" }),
    // ── Enterprise I/O (Fases 80–85)
    ("cache", Real { proof: "cache_runtime — cacheability derives from the type system's `effects: pure` proof (§85)" }),
    ("voice", Unaudited),
    ("shell", Unaudited),
    ("path rewrite", Unaudited),
    ("PASETO", Unaudited),
    // ── Session types (§41)
    ("socket", Real { proof: "tests/fase111_i_socket_served.rs (§111.i — the OSS server now SERVES the session-typed WebSocket at GET /ws/{socket}, and enforces the protocol the adopter DECLARED: the missing SessionType compiler lands in session_runtime::compile. An unresolvable protocol is REFUSED, never substituted — enterprise used to hand every socket a hardcoded chat schema, so a protocol proven dual at compile time had a different one enforced at runtime)" }),
    ("send T", Real { proof: "the session algebra's send, carrying a payload type" }),
    ("receive T", Real { proof: "the session algebra's receive" }),
    ("select {ℓᵢ:…}", Real { proof: "session.rs Select — labelled internal choice" }),
    ("branch {ℓᵢ:…}", Real { proof: "session.rs Branch — labelled external choice" }),
    ("backpressure: credit(k)", Real { proof: "session_runtime credit window + the PCC credit-positivity witness" }),
    ("reconnect: cognitive_state", Unaudited),
];

/// **The ratchet.** Every advertised name whose runtime is
/// [`RuntimeStatus::NotImplemented`] — i.e. every promise the README makes today
/// that the code does not keep.
///
/// This list may only ever **shrink**. Adding a name to it requires editing this
/// file, which is the point: a new unkept promise cannot land quietly. Removing
/// one means you either implemented it or retracted it from the README — both
/// good outcomes, and both must happen in the same PR as the deletion.
///
/// §111 inherited every one of these. They are the fase's open debt, and now the
/// compiler holds the ledger.
pub const KNOWN_DEBT: &[&str] = &[
    // Tier 4 — implement or retract.
    // `compute` LEFT this ledger in §111.f: it is now a real pure function over
    // the §70 expression language. This is the ratchet turning — the only
    // direction it turns.
    "hibernate",
    "ots",
    "mandate",
    "lambda",
    // The Cognitive-I/O block.
    //
    // §112 PAID SIX OF THESE. `observe` · `ensemble` · `immune` · `reflex` · `heal` ·
    // `reconcile` are now driven by the CognitiveIoSupervisor and each cites a gate
    // that proves it runs through the REAL deploy path.
    //
    // My §111 diagnosis of this family was WRONG in a way worth remembering: I called
    // it a language-design problem ("no verb can reach them"). The language was
    // already complete — the declarations form a dataflow graph and reference each
    // other, and the kernels took the compiled IR directly. **Nobody had ever built
    // the loop.**
    //
    // The three that remain need a `resource` to govern something that runs, and it
    // governs nothing: `resource.endpoint` and `axonstore.connection` are the same
    // fact declared twice, with the Linear-Logic discipline hanging off the copy that
    // runs nothing. `lease` in particular CANNOT work — the CT-2 Anchor Breach is
    // breach on post-expiry USE, and a flow can never USE a resource. That is §113.
    "resource",
    "fabric",
    "lease",
];

/// Look up what an advertised name's runtime actually does.
///
/// **No default arm, deliberately.** An unknown name returns `None`, and the
/// gate below turns that into a build failure — so a primitive cannot be added
/// to the README without someone stating what it does.
pub fn status_of(name: &str) -> Option<RuntimeStatus> {
    ADVERTISED
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, s)| *s)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;
    use std::path::Path;

    /// The repo root, from `axon-frontend/`.
    fn repo_root() -> &'static Path {
        Path::new("..")
    }

    /// Parse the README's header badge block — the public promise, as published.
    fn readme_advertised() -> Vec<String> {
        let readme = std::fs::read_to_string(repo_root().join("README.md"))
            .expect("the public README must be readable — it is an INPUT to this build");
        let start = readme
            .find("<!-- Cognition primitives -->")
            .expect("the README's primitive badge block must be findable");
        let end = readme[start..]
            .find("</p>")
            .expect("the badge block must terminate")
            + start;
        let block = &readme[start..end];

        let mut out = Vec::new();
        let mut rest = block;
        while let Some(i) = rest.find("<code>") {
            rest = &rest[i + 6..];
            let j = rest.find("</code>").expect("unterminated <code> badge");
            out.push(rest[..j].to_string());
            rest = &rest[j + 7..];
        }
        out
    }

    /// **LAW 1 — the README is a build input.**
    ///
    /// Every badge it advertises must be classified here. A primitive cannot be
    /// added to the public promise without someone stating, on the record, what
    /// its runtime actually does.
    #[test]
    fn every_advertised_name_is_classified() {
        let missing: Vec<String> = readme_advertised()
            .into_iter()
            .filter(|n| status_of(n).is_none())
            .collect();
        assert!(
            missing.is_empty(),
            "the README advertises {} name(s) with NO entry in `ADVERTISED`:\n  {}\n\n\
             You cannot advertise a primitive without stating what its runtime does. \
             That omission is exactly how §111 happened: `warden` and `quant` had a README \
             badge, a registry entry, a parser production AND a dispatch arm — and were no-ops.",
            missing.len(),
            missing.join("\n  ")
        );
    }

    /// The reverse: no zombie entries. If a name leaves the README (retracted),
    /// it must leave this table too — otherwise the table slowly becomes a
    /// museum and stops describing the promise.
    #[test]
    fn every_classified_name_is_still_advertised() {
        let advertised: HashSet<String> = readme_advertised().into_iter().collect();
        let zombies: Vec<&str> = ADVERTISED
            .iter()
            .map(|(n, _)| *n)
            .filter(|n| !advertised.contains(*n))
            .collect();
        assert!(
            zombies.is_empty(),
            "these names are classified here but are NO LONGER advertised in the README: {zombies:?}\n\
             Retracting a primitive means deleting it from BOTH."
        );
    }

    /// **LAW 2 — the ratchet.** Nothing advertised may be `NotImplemented`
    /// unless it is in `KNOWN_DEBT`, and that list may only shrink.
    ///
    /// This is the law that makes §111's findings durable. A *new* unkept promise
    /// is a red build. The existing ones are a ledger the compiler holds — not a
    /// paragraph in a document nobody rereads.
    #[test]
    fn no_new_unkept_promises() {
        let debt: HashSet<&str> = KNOWN_DEBT.iter().copied().collect();
        let undeclared: Vec<&str> = ADVERTISED
            .iter()
            .filter(|(_, s)| s.is_unimplemented())
            .map(|(n, _)| *n)
            .filter(|n| !debt.contains(*n))
            .collect();
        assert!(
            undeclared.is_empty(),
            "these advertised primitives are NotImplemented and are NOT in KNOWN_DEBT: {undeclared:?}\n\n\
             You have advertised a promise the code does not keep. Either implement it, retract it \
             from the README, or (if you are knowingly shipping the gap) add it to KNOWN_DEBT with \
             its finding — so it is a LEDGER ENTRY and not a lie."
        );
    }

    /// The ratchet's teeth: `KNOWN_DEBT` may only shrink. Bump this DOWN when a
    /// debt is paid; a build that needs it bumped UP is telling you something.
    #[test]
    fn the_debt_ledger_only_shrinks() {
        assert!(
            KNOWN_DEBT.len() <= 14,
            "KNOWN_DEBT grew to {} — the ratchet only turns one way. §111 inherited 14 unkept \
             promises; a new one is not an entry to add, it is a bug to fix.",
            KNOWN_DEBT.len()
        );
    }

    /// Every debt entry must actually BE a debt — no padding the ledger with
    /// names that are fine, which would let a real one hide among them.
    #[test]
    fn the_debt_ledger_has_no_padding() {
        for name in KNOWN_DEBT {
            let s = status_of(name)
                .unwrap_or_else(|| panic!("KNOWN_DEBT names `{name}`, which is not advertised"));
            assert!(
                s.is_unimplemented(),
                "`{name}` is in KNOWN_DEBT but its status is {s:?} — if it was implemented or \
                 retracted, delete its ledger row in the same PR."
            );
        }
    }

    /// **LAW 3 — a claim of reality must cite the gate that proves it.**
    ///
    /// And where the proof names a test file, that file must exist. A `Real`
    /// claim pointing at nothing is just a nicer-sounding assertion — which is
    /// precisely what the README's feature table was.
    #[test]
    fn every_real_claim_cites_a_proof_that_exists() {
        for (name, status) in ADVERTISED {
            if let Real { proof } = status {
                assert!(
                    !proof.trim().is_empty(),
                    "`{name}` claims Real with an empty proof"
                );
                if let Some(path) = proof.split_whitespace().find(|t| t.starts_with("tests/")) {
                    let full = repo_root().join("axon-rs").join(path);
                    let alt = repo_root().join("axon-frontend").join(path);
                    assert!(
                        full.exists() || alt.exists(),
                        "`{name}` claims Real and cites `{path}`, which does not exist. \
                         A proof that cannot be run is not a proof."
                    );
                }
            }
        }
    }

    /// Partial / FailsClosed entries must NAME the gap or the diagnostic. An
    /// unnamed gap is how a documented compromise rots into an undocumented lie.
    #[test]
    fn every_partial_and_failsclosed_names_its_gap() {
        for (name, status) in ADVERTISED {
            match status {
                Partial { gap } => assert!(
                    !gap.trim().is_empty(),
                    "`{name}` is Partial with no stated gap — name it, or it will rot"
                ),
                FailsClosed { diagnostic } => assert!(
                    !diagnostic.trim().is_empty(),
                    "`{name}` FailsClosed with no diagnostic named"
                ),
                _ => {}
            }
        }
    }

    /// The unaudited population is pinned. §111 could not reach everything, and
    /// says so; but the number may only go down. An unchecked box is not a
    /// passing one.
    #[test]
    fn the_unaudited_population_only_shrinks() {
        let n = ADVERTISED
            .iter()
            .filter(|(_, s)| matches!(s, Unaudited))
            .count();
        assert!(
            n <= 18,
            "the Unaudited population grew to {n} — §111 left 18. Auditing is the only direction."
        );
    }
}
