//! AXON Type Checker — Phase 1: symbol table, duplicates, references, field validation.
//!
//! Direct port of axon/compiler/type_checker.py (subset).
//!
//! What it checks:
//!   - Duplicate declarations
//!   - Undefined references in `run` (flow, persona, context, anchors)
//!   - Field value validation (tone, depth, memory scope, temperature, confidence, effort)
//!   - Duplicate step names within flows
//!
//! What it does NOT check (deferred to C7+):
//!   - Epistemic lattice / type compatibility
//!   - Cross-node type inference / uncertainty propagation
//!   - Tier 2 construct-specific validation

#![allow(dead_code)]

use std::collections::HashMap;

use crate::ast::*;
use crate::epistemic;

// ── Valid value sets (mirrors Python frozensets) ─────────────────────────────

const VALID_TONES: &[&str] = &[
    "analytical", "assertive", "casual", "diplomatic",
    "empathetic", "formal", "friendly", "precise",
];

const VALID_MEMORY_SCOPES: &[&str] = &["ephemeral", "none", "persistent", "session"];

const VALID_DEPTHS: &[&str] = &["deep", "exhaustive", "shallow", "standard"];

const VALID_EFFORT_LEVELS: &[&str] = &["high", "low", "max", "medium"];

const VALID_VIOLATION_ACTIONS: &[&str] = &["escalate", "fallback", "log", "raise", "warn"];

const VALID_RETRIEVAL_STRATEGIES: &[&str] = &["exact", "hybrid", "semantic"];

// §λ-L-E Fase 11.a + 11.c + 11.e — `stream` (mandatory backpressure),
// `trust` (mandatory proof), `sensitive` (data-category jurisdiction
// — open taxonomy), `legal` (mandatory legal basis from the closed
// catalogue in `crate::legal_basis`), `ots` (subkinds `transform:
// <from>:<to>` + `backend:<native|ffmpeg>`) join the catalogue.
// Qualifiers are validated separately below.
const VALID_EFFECTS: &[&str] = &[
    "io", "network", "pure", "random", "storage", "stream", "trust",
    "sensitive", "legal", "ots",
];

const VALID_EPISTEMIC_LEVELS: &[&str] = &["believe", "doubt", "know", "speculate"];

const VALID_DERIVATIONS: &[&str] = &["aggregated", "derived", "inferred", "raw", "transformed"];

// ── Tier 2 valid-value sets (mirrors Python frozensets) ────────────────────

const VALID_AGENT_STRATEGIES: &[&str] = &["custom", "plan_and_execute", "react", "reflexion"];

const VALID_ON_STUCK_POLICIES: &[&str] = &["escalate", "forge", "hibernate", "retry"];

const VALID_SCAN_CATEGORIES: &[&str] = &[
    "bias", "code_injection", "data_exfil", "hallucination", "jailbreak",
    "model_theft", "pii_leak", "prompt_injection", "social_engineering",
    "toxicity", "training_poisoning",
];

const VALID_SHIELD_STRATEGIES: &[&str] = &[
    "canary", "classifier", "dual_llm", "ensemble", "pattern", "perplexity",
];

const VALID_ON_BREACH_POLICIES: &[&str] = &[
    "deflect", "escalate", "halt", "quarantine", "sanitize_and_retry",
];

const VALID_SEVERITY_LEVELS: &[&str] = &["critical", "high", "low", "medium"];

const VALID_OTS_HOMOTOPY: &[&str] = &["deep", "shallow", "speculative"];

const VALID_MANDATE_POLICIES: &[&str] = &["coerce", "halt", "retry"];

const VALID_STORE_BACKENDS: &[&str] = &["mysql", "postgresql", "sqlite"];

const VALID_STORE_ISOLATION: &[&str] = &["read_committed", "repeatable_read", "serializable"];

const VALID_STORE_ON_BREACH: &[&str] = &["log", "raise", "rollback"];

const VALID_ENDPOINT_METHODS: &[&str] = &["DELETE", "GET", "PATCH", "POST", "PUT"];

const VALID_INFERENCE_MODES: &[&str] = &["active", "passive"];

fn is_valid(value: &str, set: &[&str]) -> bool {
    set.contains(&value)
}

fn valid_list(set: &[&str]) -> String {
    set.join(", ")
}

// ── Type error ───────────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct TypeError {
    pub message: String,
    pub line: u32,
    pub column: u32,
}

// ── Symbol table ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct Symbol {
    name: String,
    kind: String,
    line: u32,
}

struct SymbolTable {
    symbols: HashMap<String, Symbol>,
}

impl SymbolTable {
    fn new() -> Self {
        SymbolTable {
            symbols: HashMap::new(),
        }
    }

    fn declare(&mut self, name: &str, kind: &str, line: u32) -> Option<String> {
        if let Some(existing) = self.symbols.get(name) {
            return Some(format!(
                "Duplicate declaration: '{}' already defined as {} (first defined at line {})",
                name, existing.kind, existing.line
            ));
        }
        self.symbols.insert(
            name.to_string(),
            Symbol {
                name: name.to_string(),
                kind: kind.to_string(),
                line,
            },
        );
        None
    }

    fn lookup(&self, name: &str) -> Option<&Symbol> {
        self.symbols.get(name)
    }
}

// ── Type checker ─────────────────────────────────────────────────────────────

pub struct TypeChecker<'a> {
    program: &'a Program,
    symbols: SymbolTable,
    errors: Vec<TypeError>,
}

impl<'a> TypeChecker<'a> {
    pub fn new(program: &'a Program) -> Self {
        TypeChecker {
            program,
            symbols: SymbolTable::new(),
            errors: Vec::new(),
        }
    }

    pub fn check(mut self) -> Vec<TypeError> {
        self.register_declarations(&self.program.declarations);
        self.check_declarations(&self.program.declarations);
        self.errors
    }

    // ── emit ─────────────────────────────────────────────────────

    fn emit(&mut self, message: String, loc: &Loc) {
        self.errors.push(TypeError {
            message,
            line: loc.line,
            column: loc.column,
        });
    }

    fn check_range(&mut self, value: f64, lo: f64, hi: f64, field: &str, loc: &Loc) {
        if value < lo || value > hi {
            self.emit(
                format!("{field} must be between {lo:.1} and {hi:.1}, got {value:.1}"),
                loc,
            );
        }
    }

    // ── Phase 1: registration ────────────────────────────────────

    fn register_declarations(&mut self, decls: &[Declaration]) {
        // Collect registrations first to avoid borrow conflict
        let mut registrations: Vec<(String, String, u32, Loc)> = Vec::new();

        for decl in decls {
            match decl {
                Declaration::Persona(n) => {
                    registrations.push((n.name.clone(), "persona".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Context(n) => {
                    registrations.push((n.name.clone(), "context".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Anchor(n) => {
                    registrations.push((n.name.clone(), "anchor".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Memory(n) => {
                    registrations.push((n.name.clone(), "memory".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Tool(n) => {
                    registrations.push((n.name.clone(), "tool".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Type(n) => {
                    registrations.push((n.name.clone(), "type".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Flow(n) => {
                    registrations.push((n.name.clone(), "flow".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Intent(n) => {
                    registrations.push((n.name.clone(), "intent".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::LambdaData(n) => {
                    registrations.push((n.name.clone(), "lambda_data".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Agent(n) => {
                    registrations.push((n.name.clone(), "agent".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Shield(n) => {
                    registrations.push((n.name.clone(), "shield".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Pix(n) => {
                    registrations.push((n.name.clone(), "pix".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Psyche(n) => {
                    registrations.push((n.name.clone(), "psyche".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Corpus(n) => {
                    registrations.push((n.name.clone(), "corpus".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Dataspace(n) => {
                    registrations.push((n.name.clone(), "dataspace".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Ots(n) => {
                    registrations.push((n.name.clone(), "ots".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Mandate(n) => {
                    registrations.push((n.name.clone(), "mandate".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Compute(n) => {
                    registrations.push((n.name.clone(), "compute".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Daemon(n) => {
                    registrations.push((n.name.clone(), "daemon".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::AxonStore(n) => {
                    registrations.push((n.name.clone(), "axonstore".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::AxonEndpoint(n) => {
                    registrations.push((n.name.clone(), "axonendpoint".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Resource(n) => {
                    registrations.push((n.name.clone(), "resource".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Fabric(n) => {
                    registrations.push((n.name.clone(), "fabric".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Manifest(n) => {
                    registrations.push((n.name.clone(), "manifest".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Observe(n) => {
                    registrations.push((n.name.clone(), "observe".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Reconcile(n) => {
                    registrations.push((n.name.clone(), "reconcile".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Lease(n) => {
                    registrations.push((n.name.clone(), "lease".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Ensemble(n) => {
                    registrations.push((n.name.clone(), "ensemble".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Session(n) => {
                    registrations.push((n.name.clone(), "session".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Topology(n) => {
                    registrations.push((n.name.clone(), "topology".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Immune(n) => {
                    registrations.push((n.name.clone(), "immune".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Reflex(n) => {
                    registrations.push((n.name.clone(), "reflex".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Heal(n) => {
                    registrations.push((n.name.clone(), "heal".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Component(n) => {
                    registrations.push((n.name.clone(), "component".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::View(n) => {
                    registrations.push((n.name.clone(), "view".into(), n.loc.line, n.loc.clone()));
                }
                Declaration::Generic(n) => {
                    if !n.name.is_empty() {
                        registrations.push((n.name.clone(), n.keyword.clone(), n.loc.line, n.loc.clone()));
                    }
                }
                Declaration::Epistemic(_) => {
                    // Recursion handled below
                }
                Declaration::Import(_) | Declaration::Run(_) | Declaration::Let(_) => {}
            }
        }

        for (name, kind, line, loc) in registrations {
            if let Some(err) = self.symbols.declare(&name, &kind, line) {
                self.emit(err, &loc);
            }
        }

        // Recurse into epistemic blocks
        for decl in decls {
            if let Declaration::Epistemic(eb) = decl {
                self.register_declarations(&eb.body);
            }
        }
    }

    // ── Phase 2: validation ──────────────────────────────────────

    fn check_declarations(&mut self, decls: &[Declaration]) {
        for decl in decls {
            match decl {
                Declaration::Persona(n) => self.check_persona(n),
                Declaration::Context(n) => self.check_context(n),
                Declaration::Anchor(n) => self.check_anchor(n),
                Declaration::Memory(n) => self.check_memory(n),
                Declaration::Tool(n) => self.check_tool(n),
                Declaration::Flow(n) => self.check_flow(n),
                Declaration::Intent(n) => self.check_intent(n),
                Declaration::Run(n) => self.check_run(n),
                Declaration::Epistemic(eb) => {
                    self.check_epistemic_mode(&eb.mode, &eb.loc);
                    self.check_declarations(&eb.body);
                }
                Declaration::LambdaData(n) => self.check_lambda_data(n),
                Declaration::Agent(n) => self.check_agent(n),
                Declaration::Shield(n) => self.check_shield(n),
                Declaration::Pix(n) => self.check_pix(n),
                Declaration::Psyche(n) => self.check_psyche(n),
                Declaration::Corpus(n) => self.check_corpus(n),
                Declaration::Dataspace(_) => {} // name-only, no field validation
                Declaration::Ots(n) => self.check_ots(n),
                Declaration::Mandate(n) => self.check_mandate(n),
                Declaration::Compute(_) => {} // no Python validation exists
                Declaration::Daemon(_) => {} // no Python validation exists
                Declaration::AxonStore(n) => self.check_axonstore(n),
                Declaration::AxonEndpoint(n) => self.check_axonendpoint(n),
                Declaration::Resource(n) => self.check_resource(n),
                Declaration::Fabric(n)   => self.check_fabric(n),
                Declaration::Manifest(n) => self.check_manifest(n),
                Declaration::Observe(n)  => self.check_observe(n),
                Declaration::Reconcile(n) => self.check_reconcile(n),
                Declaration::Lease(n)     => self.check_lease(n),
                Declaration::Ensemble(n)  => self.check_ensemble(n),
                Declaration::Session(n)   => self.check_session(n),
                Declaration::Topology(n)  => self.check_topology(n),
                Declaration::Immune(n)    => self.check_immune(n),
                Declaration::Reflex(n)    => self.check_reflex(n),
                Declaration::Heal(n)      => self.check_heal(n),
                Declaration::Component(n) => self.check_component(n),
                Declaration::View(n)      => self.check_view(n),
                Declaration::Import(_)
                | Declaration::Type(_)
                | Declaration::Let(_)
                | Declaration::Generic(_) => {}
            }
        }
    }

    // ── Per-construct checks ─────────────────────────────────────

    fn check_persona(&mut self, node: &PersonaDefinition) {
        if !node.tone.is_empty() && !is_valid(&node.tone, VALID_TONES) {
            self.emit(
                format!(
                    "Unknown tone '{}' for persona '{}'. Valid tones: {}",
                    node.tone, node.name, valid_list(VALID_TONES)
                ),
                &node.loc,
            );
        }
        if let Some(v) = node.confidence_threshold {
            self.check_range(v, 0.0, 1.0, "confidence_threshold", &node.loc);
        }
    }

    fn check_context(&mut self, node: &ContextDefinition) {
        if !node.memory_scope.is_empty() && !is_valid(&node.memory_scope, VALID_MEMORY_SCOPES) {
            self.emit(
                format!(
                    "Unknown memory scope '{}' in context '{}'. Valid: {}",
                    node.memory_scope, node.name, valid_list(VALID_MEMORY_SCOPES)
                ),
                &node.loc,
            );
        }
        if !node.depth.is_empty() && !is_valid(&node.depth, VALID_DEPTHS) {
            self.emit(
                format!(
                    "Unknown depth '{}' in context '{}'. Valid: {}",
                    node.depth, node.name, valid_list(VALID_DEPTHS)
                ),
                &node.loc,
            );
        }
        if let Some(v) = node.temperature {
            self.check_range(v, 0.0, 2.0, "temperature", &node.loc);
        }
        if let Some(v) = node.max_tokens {
            if v <= 0 {
                self.emit(
                    format!(
                        "max_tokens must be positive, got {} in context '{}'",
                        v, node.name
                    ),
                    &node.loc,
                );
            }
        }
    }

    fn check_anchor(&mut self, node: &AnchorConstraint) {
        if let Some(v) = node.confidence_floor {
            self.check_range(v, 0.0, 1.0, "confidence_floor", &node.loc);
        }
        if !node.on_violation.is_empty() && !is_valid(&node.on_violation, VALID_VIOLATION_ACTIONS) {
            self.emit(
                format!(
                    "Unknown on_violation action '{}' in anchor '{}'. Valid: {}",
                    node.on_violation, node.name, valid_list(VALID_VIOLATION_ACTIONS)
                ),
                &node.loc,
            );
        }
        if node.on_violation == "raise" && node.on_violation_target.is_empty() {
            self.emit(
                format!(
                    "Anchor '{}' uses 'raise' but no error type specified",
                    node.name
                ),
                &node.loc,
            );
        }
    }

    fn check_memory(&mut self, node: &MemoryDefinition) {
        if !node.store.is_empty() && !is_valid(&node.store, VALID_MEMORY_SCOPES) {
            self.emit(
                format!(
                    "Unknown store type '{}' in memory '{}'. Valid: {}",
                    node.store, node.name, valid_list(VALID_MEMORY_SCOPES)
                ),
                &node.loc,
            );
        }
        if !node.retrieval.is_empty() && !is_valid(&node.retrieval, VALID_RETRIEVAL_STRATEGIES) {
            self.emit(
                format!(
                    "Unknown retrieval strategy '{}' in memory '{}'. Valid: {}",
                    node.retrieval, node.name, valid_list(VALID_RETRIEVAL_STRATEGIES)
                ),
                &node.loc,
            );
        }
    }

    fn check_tool(&mut self, node: &ToolDefinition) {
        if let Some(v) = node.max_results {
            if v <= 0 {
                self.emit(
                    format!(
                        "max_results must be positive, got {} in tool '{}'",
                        v, node.name
                    ),
                    &node.loc,
                );
            }
        }
        if let Some(ref eff) = node.effects {
            for e in &eff.effects {
                // Handle composite effects like "name:qualifier"
                let (base, qualifier) = match e.split_once(':') {
                    Some((b, q)) => (b, Some(q)),
                    None => (e.as_str(), None),
                };
                if !is_valid(base, VALID_EFFECTS) {
                    self.emit(
                        format!(
                            "Unknown effect '{}' in tool '{}'. Valid: {}",
                            e, node.name, valid_list(VALID_EFFECTS)
                        ),
                        &node.loc,
                    );
                    continue;
                }
                // §λ-L-E Fase 11.a — qualifier enforcement for the
                // stream + trust effects. Both REQUIRE a qualifier
                // from their closed catalogue. Missing or unknown
                // qualifiers are compile errors.
                match base {
                    "stream" => match qualifier {
                        None => self.emit(
                            format!(
                                "Effect 'stream' in tool '{}' requires a \
                                 backpressure policy qualifier \
                                 'stream:<policy>'. Valid policies: {}",
                                node.name,
                                valid_list(crate::stream_effect::BACKPRESSURE_CATALOG)
                            ),
                            &node.loc,
                        ),
                        Some(q) => {
                            if !is_valid(
                                q,
                                crate::stream_effect::BACKPRESSURE_CATALOG,
                            ) {
                                self.emit(
                                    format!(
                                        "Unknown backpressure policy '{}' in tool '{}'. \
                                         Valid: {}",
                                        q,
                                        node.name,
                                        valid_list(crate::stream_effect::BACKPRESSURE_CATALOG)
                                    ),
                                    &node.loc,
                                );
                            }
                        }
                    },
                    "trust" => match qualifier {
                        None => self.emit(
                            format!(
                                "Effect 'trust' in tool '{}' requires a proof \
                                 qualifier 'trust:<proof>'. Valid proofs: {}",
                                node.name,
                                valid_list(crate::refinement::TRUST_CATALOG)
                            ),
                            &node.loc,
                        ),
                        Some(q) => {
                            if !is_valid(q, crate::refinement::TRUST_CATALOG) {
                                self.emit(
                                    format!(
                                        "Unknown trust proof '{}' in tool '{}'. \
                                         Valid: {}",
                                        q,
                                        node.name,
                                        valid_list(crate::refinement::TRUST_CATALOG)
                                    ),
                                    &node.loc,
                                );
                            }
                        }
                    },
                    // §λ-L-E Fase 11.c — `sensitive:<category>` tags
                    // effects that touch regulated data. The category
                    // is an open taxonomy (adopters write
                    // `sensitive:health_data`, `sensitive:financial_txn`
                    // etc). The qualifier presence is REQUIRED — a
                    // bare `sensitive` is ambiguous and rejected.
                    "sensitive" => {
                        if qualifier.is_none() {
                            self.emit(
                                format!(
                                    "Effect 'sensitive' in tool '{}' \
                                     requires a jurisdiction qualifier \
                                     'sensitive:<category>' (e.g. \
                                     'sensitive:health_data'). The \
                                     category is adopter-defined; the \
                                     legal basis covering it must also \
                                     be declared via 'legal:<basis>' on \
                                     the same tool.",
                                    node.name,
                                ),
                                &node.loc,
                            );
                        }
                    }
                    // §λ-L-E Fase 11.c — `legal:<basis>` declares the
                    // legal basis authorising a sensitive effect. The
                    // basis catalogue is CLOSED.
                    "legal" => match qualifier {
                        None => self.emit(
                            format!(
                                "Effect 'legal' in tool '{}' requires a \
                                 basis qualifier 'legal:<basis>'. Valid \
                                 bases: {}",
                                node.name,
                                valid_list(
                                    crate::legal_basis::LEGAL_BASIS_CATALOG
                                )
                            ),
                            &node.loc,
                        ),
                        Some(q) => {
                            if !is_valid(
                                q,
                                crate::legal_basis::LEGAL_BASIS_CATALOG,
                            ) {
                                self.emit(
                                    format!(
                                        "Unknown legal basis '{}' in tool \
                                         '{}'. Valid: {}",
                                        q,
                                        node.name,
                                        valid_list(
                                            crate::legal_basis::LEGAL_BASIS_CATALOG
                                        )
                                    ),
                                    &node.loc,
                                );
                            }
                        }
                    },
                    // §λ-L-E Fase 11.e — OTS subkinds:
                    //   ots:transform:<from>:<to>  → kind-pair
                    //   ots:backend:<native|ffmpeg> → closed backend catalogue
                    "ots" => match qualifier {
                        None => self.emit(
                            format!(
                                "Effect 'ots' in tool '{}' requires a \
                                 subkind. Expected 'ots:transform:<from>:<to>' \
                                 or 'ots:backend:<native|ffmpeg>'.",
                                node.name
                            ),
                            &node.loc,
                        ),
                        Some(inner) => {
                            let (subkind, rest) = match inner.split_once(':') {
                                Some((a, b)) => (a, Some(b)),
                                None => (inner, None),
                            };
                            match subkind {
                                "transform" => {
                                    let valid = rest
                                        .and_then(|r| r.split_once(':'))
                                        .map(|(f, t)| {
                                            !f.is_empty() && !t.is_empty()
                                        })
                                        .unwrap_or(false);
                                    if !valid {
                                        self.emit(
                                            format!(
                                                "Effect 'ots:transform' in tool \
                                                 '{}' requires '<from>:<to>' \
                                                 qualifier (e.g. \
                                                 'ots:transform:mulaw8:pcm16').",
                                                node.name
                                            ),
                                            &node.loc,
                                        );
                                    }
                                }
                                "backend" => {
                                    let qual = rest.unwrap_or("");
                                    if !is_valid(qual, crate::ots::OTS_BACKEND_CATALOG) {
                                        self.emit(
                                            format!(
                                                "Unknown OTS backend '{}' in tool '{}'. \
                                                 Valid: {}",
                                                qual,
                                                node.name,
                                                valid_list(crate::ots::OTS_BACKEND_CATALOG)
                                            ),
                                            &node.loc,
                                        );
                                    }
                                }
                                other => self.emit(
                                    format!(
                                        "Unknown 'ots' subkind '{}' in tool '{}'. \
                                         Expected 'transform' or 'backend'.",
                                        other, node.name
                                    ),
                                    &node.loc,
                                ),
                            }
                        }
                    },
                    _ => {}
                }
            }
            if !eff.epistemic_level.is_empty()
                && !is_valid(&eff.epistemic_level, VALID_EPISTEMIC_LEVELS)
            {
                self.emit(
                    format!(
                        "Unknown epistemic level '{}' in tool '{}'. Valid: {}",
                        eff.epistemic_level, node.name, valid_list(VALID_EPISTEMIC_LEVELS)
                    ),
                    &node.loc,
                );
            }
        }

        // §λ-L-E Fase 11.a — tool output/input trust coherence.
        // When a tool's declared effects announce a trust proof, we
        // don't (yet) propagate it into the return-type refinement
        // since tools don't carry explicit return TypeExprs in this
        // AST tier. Tool-level trust claims are consumed by
        // `check_flow`'s refinement pass below.

        // Mirror for stream: if a tool declares stream:<policy>, the
        // flows that use it inherit the obligation — enforced in
        // `check_flow`.

        // §λ-L-E Fase 11.c — tool-level sensitive/legal coherence.
        // A tool declaring `sensitive:<category>` MUST also declare
        // at least one `legal:<basis>` from the closed catalogue.
        // Declaring `legal:<basis>` without a `sensitive:<category>`
        // is tolerated (some tools are authorised broadly without
        // processing regulated data).
        if let Some(ref eff) = node.effects {
            let mut sensitive_categories: Vec<&str> = Vec::new();
            let mut has_legal_basis = false;
            let mut legal_bases_hipaa: Vec<&str> = Vec::new();
            let mut has_ffmpeg_backend = false;
            for e in &eff.effects {
                let (base, qual) = match e.split_once(':') {
                    Some((b, q)) => (b, Some(q)),
                    None => (e.as_str(), None),
                };
                if base == "sensitive" {
                    if let Some(q) = qual {
                        sensitive_categories.push(q);
                    }
                }
                if base == "legal" {
                    if let Some(q) = qual {
                        if is_valid(
                            q,
                            crate::legal_basis::LEGAL_BASIS_CATALOG,
                        ) {
                            has_legal_basis = true;
                            if q.starts_with("HIPAA.") {
                                legal_bases_hipaa.push(q);
                            }
                        }
                    }
                }
                if base == "ots" {
                    if let Some(inner) = qual {
                        if let Some(("backend", backend)) =
                            inner.split_once(':')
                        {
                            if backend == "ffmpeg" {
                                has_ffmpeg_backend = true;
                            }
                        }
                    }
                }
            }
            if !sensitive_categories.is_empty() && !has_legal_basis {
                self.emit(
                    format!(
                        "Tool '{}' declares sensitive effect(s) [{}] but \
                         carries no 'legal:<basis>' effect. Regulated \
                         processing requires an explicit legal basis: {}.",
                        node.name,
                        sensitive_categories.join(", "),
                        valid_list(
                            crate::legal_basis::LEGAL_BASIS_CATALOG
                        )
                    ),
                    &node.loc,
                );
            }

            // §λ-L-E Fase 11.e — HIPAA processing MUST stay in-process.
            // Spawning ffmpeg crosses a process boundary the auditor
            // cannot observe; the ePHI disclosure the BAA doesn't
            // cover. Rejected at compile time, per the same closed
            // posture as 11.a trust proofs and 11.c legal bases.
            if !legal_bases_hipaa.is_empty() && has_ffmpeg_backend {
                self.emit(
                    format!(
                        "Tool '{}' combines HIPAA legal basis ({}) with \
                         'ots:backend:ffmpeg'. ePHI MUST NOT cross the \
                         process boundary to a subprocess outside the \
                         auditable runtime. Use 'ots:backend:native' or \
                         register a native transformer that covers the \
                         required pipeline.",
                        node.name,
                        legal_bases_hipaa.join(", "),
                    ),
                    &node.loc,
                );
            }
        }
    }

    fn check_flow(&mut self, node: &FlowDefinition) {
        // Validate parameter types
        for param in &node.parameters {
            self.check_type_reference(&param.type_expr.name, &param.loc);
        }
        // Validate return type
        if let Some(ref rt) = node.return_type {
            self.check_type_reference(&rt.name, &rt.loc);
        }

        let mut step_names: Vec<String> = Vec::new();
        for step in &node.body {
            if let FlowStep::Step(s) = step {
                if step_names.contains(&s.name) {
                    self.emit(
                        format!(
                            "Duplicate step name '{}' in flow '{}'",
                            s.name, node.name
                        ),
                        &s.loc,
                    );
                } else {
                    step_names.push(s.name.clone());
                }
                if let Some(v) = s.confidence_floor {
                    self.check_range(v, 0.0, 1.0, "confidence_floor", &s.loc);
                }
            }
        }

        // Tier 2 flow step reference checks
        self.check_flow_steps(&node.body, &node.name);

        // §λ-L-E Fase 11.a — Temporal Algebraic Effects + Trust
        // Types. Enforce two contracts at the flow level:
        //
        //   1. Stream<T> in parameter/return obliges the flow's body
        //      to reach a tool that carries a `stream:<policy>` effect.
        //      Without it, we cannot guarantee the stream has a
        //      backpressure handler — compile error.
        //
        //   2. Untrusted<T> in parameter obliges the flow's body to
        //      reach a tool that carries a `trust:<proof>` effect —
        //      otherwise the untrusted payload is being consumed
        //      without verification.
        self.check_refinement_and_stream_contracts(node);
    }

    // ── §λ-L-E Fase 11.a — refinement + stream flow-level checks ─

    fn check_refinement_and_stream_contracts(
        &mut self,
        flow: &FlowDefinition,
    ) {
        // Scan flow signature for the refinement / stream markers.
        // `Trusted<T>` in a parameter imposes no new obligation on
        // this flow (the upstream already proved trust). `Untrusted<T>`
        // in a parameter obliges the flow body to refine it.
        let mut uses_stream = false;
        let mut uses_untrusted = false;

        for param in &flow.parameters {
            if crate::stream_effect::is_stream_type(&param.type_expr.name) {
                uses_stream = true;
            }
            if crate::refinement::is_untrusted_type(&param.type_expr.name) {
                uses_untrusted = true;
            }
        }
        if let Some(ref rt) = flow.return_type {
            if crate::stream_effect::is_stream_type(&rt.name) {
                uses_stream = true;
            }
            // Returning `Untrusted<T>` is legal (the flow is a pure
            // acceptor / pass-through) — the downstream consumer
            // carries the refinement obligation.
        }

        if !uses_stream && !uses_untrusted {
            return;
        }

        // Build {tool_name → Vec<effect_string>} by scanning the
        // program's declarations. Owned strings sidestep lifetime
        // gymnastics; the program-wide walk is O(N_tools) and the
        // strings are short slugs, so the allocation cost is negligible
        // for this checker pass.
        let mut tool_effects: std::collections::HashMap<String, Vec<String>> =
            std::collections::HashMap::new();
        self.collect_tool_effects(
            &self.program.declarations,
            &mut tool_effects,
        );

        // Walk the flow body and see which tools each step reaches
        // via `apply_ref` / `navigate_ref`. Record the effects we
        // witness.
        let mut observed_backpressure = false;
        let mut observed_trust_proof = false;
        self.walk_flow_steps_for_effects(
            &flow.body,
            &tool_effects,
            &mut observed_backpressure,
            &mut observed_trust_proof,
        );

        if uses_stream && !observed_backpressure {
            self.emit(
                format!(
                    "Flow '{}' uses 'Stream<T>' in its signature but no \
                     reachable tool declares a 'stream:<policy>' effect. \
                     Every Stream<T> needs a backpressure policy: {}. \
                     Declare the policy on the tool that produces or \
                     consumes the stream (e.g. `effects: [stream:drop_oldest]`).",
                    flow.name,
                    valid_list(crate::stream_effect::BACKPRESSURE_CATALOG)
                ),
                &flow.loc,
            );
        }
        if uses_untrusted && !observed_trust_proof {
            self.emit(
                format!(
                    "Flow '{}' accepts 'Untrusted<T>' in its signature but \
                     no reachable tool declares a 'trust:<proof>' effect. \
                     Untrusted payloads MUST be refined via one of the \
                     catalogue verifiers: {}. Add the appropriate effect \
                     to the verifier tool (e.g. `effects: [trust:hmac]`).",
                    flow.name,
                    valid_list(crate::refinement::TRUST_CATALOG)
                ),
                &flow.loc,
            );
        }
    }

    fn collect_tool_effects(
        &self,
        decls: &[Declaration],
        out: &mut std::collections::HashMap<String, Vec<String>>,
    ) {
        for d in decls {
            match d {
                Declaration::Tool(t) => {
                    if let Some(ref eff) = t.effects {
                        out.insert(
                            t.name.clone(),
                            eff.effects.clone(),
                        );
                    }
                }
                Declaration::Epistemic(eb) => {
                    self.collect_tool_effects(&eb.body, out);
                }
                _ => {}
            }
        }
    }

    fn walk_flow_steps_for_effects(
        &self,
        steps: &[FlowStep],
        tool_effects: &std::collections::HashMap<String, Vec<String>>,
        observed_backpressure: &mut bool,
        observed_trust_proof: &mut bool,
    ) {
        for step in steps {
            match step {
                FlowStep::Step(s) => {
                    for tool_ref in [&s.apply_ref, &s.navigate_ref] {
                        if tool_ref.is_empty() {
                            continue;
                        }
                        if let Some(effs) = tool_effects.get(tool_ref) {
                            for e in effs {
                                let (base, qual) = match e.split_once(':') {
                                    Some((b, q)) => (b, Some(q)),
                                    None => (e.as_str(), None),
                                };
                                if base == "stream" {
                                    if let Some(q) = qual {
                                        if is_valid(
                                            q,
                                            crate::stream_effect::BACKPRESSURE_CATALOG,
                                        ) {
                                            *observed_backpressure = true;
                                        }
                                    }
                                }
                                if base == "trust" {
                                    if let Some(q) = qual {
                                        if is_valid(
                                            q,
                                            crate::refinement::TRUST_CATALOG,
                                        ) {
                                            *observed_trust_proof = true;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                FlowStep::If(c) => {
                    self.walk_flow_steps_for_effects(
                        &c.then_body,
                        tool_effects,
                        observed_backpressure,
                        observed_trust_proof,
                    );
                    self.walk_flow_steps_for_effects(
                        &c.else_body,
                        tool_effects,
                        observed_backpressure,
                        observed_trust_proof,
                    );
                }
                FlowStep::ForIn(f) => {
                    self.walk_flow_steps_for_effects(
                        &f.body,
                        tool_effects,
                        observed_backpressure,
                        observed_trust_proof,
                    );
                }
                _ => {}
            }
        }
    }

    fn check_intent(&mut self, node: &IntentNode) {
        if node.ask.is_empty() {
            self.emit(
                format!(
                    "Intent '{}' is missing required 'ask' field — every intent must express a question",
                    node.name
                ),
                &node.loc,
            );
        }
        if let Some(v) = node.confidence_floor {
            self.check_range(v, 0.0, 1.0, "confidence_floor", &node.loc);
        }
    }

    fn check_run(&mut self, node: &RunStatement) {
        // Flow must exist and be a flow
        if !node.flow_name.is_empty() {
            match self.symbols.lookup(&node.flow_name) {
                None => self.emit(
                    format!("Undefined flow '{}' in run statement", node.flow_name),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "flow" => self.emit(
                    format!(
                        "'{}' is a {}, not a flow — only flows can be run",
                        node.flow_name, sym.kind
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }

        // Persona must exist
        if !node.persona.is_empty() {
            match self.symbols.lookup(&node.persona) {
                None => self.emit(
                    format!("Undefined persona '{}'", node.persona),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "persona" => self.emit(
                    format!("'{}' is a {}, not a persona", node.persona, sym.kind),
                    &node.loc,
                ),
                _ => {}
            }
        }

        // Context must exist
        if !node.context.is_empty() {
            match self.symbols.lookup(&node.context) {
                None => self.emit(
                    format!("Undefined context '{}'", node.context),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "context" => self.emit(
                    format!("'{}' is a {}, not a context", node.context, sym.kind),
                    &node.loc,
                ),
                _ => {}
            }
        }

        // Anchors must exist
        for anchor_name in &node.anchors {
            match self.symbols.lookup(anchor_name) {
                None => self.emit(
                    format!("Undefined anchor '{}'", anchor_name),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "anchor" => self.emit(
                    format!("'{}' is a {}, not an anchor", anchor_name, sym.kind),
                    &node.loc,
                ),
                _ => {}
            }
        }

        // Effort validation
        if !node.effort.is_empty() && !is_valid(&node.effort, VALID_EFFORT_LEVELS) {
            self.emit(
                format!(
                    "Unknown effort level '{}'. Valid: {}",
                    node.effort, valid_list(VALID_EFFORT_LEVELS)
                ),
                &node.loc,
            );
        }
    }

    // ── Lambda Data (ΛD) — 4 Invariants + Epistemic Degradation ──

    fn check_lambda_data(&mut self, node: &LambdaDataDefinition) {
        // Invariant 1 — Ontological Rigidity: ontology field is mandatory
        if node.ontology.is_empty() {
            self.emit(
                format!(
                    "lambda '{}' requires an 'ontology' field \
                     (Ontological Rigidity: O must classify the data domain)",
                    node.name
                ),
                &node.loc,
            );
        }

        // Invariant 4 — Epistemic Bounding: certainty ∈ [0, 1]
        if node.certainty < 0.0 || node.certainty > 1.0 {
            self.emit(
                format!(
                    "certainty coefficient must be in [0, 1], got {} \
                     (lambda '{}', Epistemic Bounding)",
                    node.certainty, node.name
                ),
                &node.loc,
            );
        }

        // Derivation validity: δ ∈ Δ
        if !node.derivation.is_empty() && !is_valid(&node.derivation, VALID_DERIVATIONS) {
            self.emit(
                format!(
                    "Unknown derivation '{}' for lambda '{}'. Valid: {}",
                    node.derivation, node.name, valid_list(VALID_DERIVATIONS)
                ),
                &node.loc,
            );
        }

        // Theorem 5.1 — Epistemic Degradation: only 'raw' may carry c = 1.0
        if node.certainty == 1.0
            && !node.derivation.is_empty()
            && node.derivation != "raw"
        {
            self.emit(
                format!(
                    "Epistemic Degradation Theorem violation: lambda '{}' \
                     has certainty=1.0 with derivation='{}'. \
                     Only 'raw' data may carry absolute certainty (c=1.0). \
                     Derived/inferred/aggregated data must have c < 1.0 \
                     (\u{2200}\u{039b}D\u{2081}\u{2218}\u{039b}D\u{2082}: c_composed \u{2264} min(c\u{2081}, c\u{2082}))",
                    node.name, node.derivation
                ),
                &node.loc,
            );
        }
    }

    // ── Tier 2 declaration checks ───────────────────────────────────

    fn check_agent(&mut self, node: &AgentDefinition) {
        // BDI requirement: every agent must declare a goal
        if node.goal.is_empty() {
            self.emit(
                format!("Agent '{}' requires a 'goal' field (BDI: every agent must declare a desired objective)", node.name),
                &node.loc,
            );
        }

        // Tool references must exist
        for tool_name in &node.tools {
            match self.symbols.lookup(tool_name) {
                None => self.emit(format!("Undefined tool '{}' in agent '{}'", tool_name, node.name), &node.loc),
                Some(sym) if sym.kind != "tool" => self.emit(
                    format!("'{}' is a {}, not a tool (referenced in agent '{}')", tool_name, sym.kind, node.name), &node.loc),
                _ => {}
            }
        }

        // Strategy enum
        if !node.strategy.is_empty() && !is_valid(&node.strategy, VALID_AGENT_STRATEGIES) {
            self.emit(
                format!("Unknown strategy '{}' in agent '{}'. Valid: {}", node.strategy, node.name, valid_list(VALID_AGENT_STRATEGIES)),
                &node.loc,
            );
        }

        // on_stuck policy enum
        if !node.on_stuck.is_empty() && !is_valid(&node.on_stuck, VALID_ON_STUCK_POLICIES) {
            self.emit(
                format!("Unknown on_stuck policy '{}' in agent '{}'. Valid: {}", node.on_stuck, node.name, valid_list(VALID_ON_STUCK_POLICIES)),
                &node.loc,
            );
        }

        // Memory reference
        if !node.memory_ref.is_empty() {
            match self.symbols.lookup(&node.memory_ref) {
                None => self.emit(format!("Undefined memory '{}' in agent '{}'", node.memory_ref, node.name), &node.loc),
                Some(sym) if sym.kind != "memory" => self.emit(
                    format!("'{}' is a {}, not a memory (referenced in agent '{}')", node.memory_ref, sym.kind, node.name), &node.loc),
                _ => {}
            }
        }

        // Shield reference
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(format!("Undefined shield '{}' in agent '{}'", node.shield_ref, node.name), &node.loc),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!("'{}' is a {}, not a shield (referenced in agent '{}')", node.shield_ref, sym.kind, node.name), &node.loc),
                _ => {}
            }
        }

        // Budget constraints (linear logic: resources must be positive)
        if let Some(v) = node.max_iterations {
            if v < 1 { self.emit(format!("max_iterations must be >= 1, got {} in agent '{}'", v, node.name), &node.loc); }
        }
        if let Some(v) = node.max_tokens {
            if v < 0 { self.emit(format!("max_tokens must be >= 0, got {} in agent '{}'", v, node.name), &node.loc); }
        }
        if let Some(v) = node.max_cost {
            if v < 0.0 { self.emit(format!("max_cost must be >= 0, got {} in agent '{}'", v, node.name), &node.loc); }
        }
    }

    fn check_shield(&mut self, node: &ShieldDefinition) {
        // Scan categories
        for cat in &node.scan {
            if !is_valid(cat, VALID_SCAN_CATEGORIES) {
                self.emit(
                    format!("Unknown scan category '{}' in shield '{}'. Valid: {}", cat, node.name, valid_list(VALID_SCAN_CATEGORIES)),
                    &node.loc,
                );
            }
        }

        // Strategy enum
        if !node.strategy.is_empty() && !is_valid(&node.strategy, VALID_SHIELD_STRATEGIES) {
            self.emit(
                format!("Unknown strategy '{}' in shield '{}'. Valid: {}", node.strategy, node.name, valid_list(VALID_SHIELD_STRATEGIES)),
                &node.loc,
            );
        }

        // on_breach policy
        if !node.on_breach.is_empty() && !is_valid(&node.on_breach, VALID_ON_BREACH_POLICIES) {
            self.emit(
                format!("Unknown on_breach policy '{}' in shield '{}'. Valid: {}", node.on_breach, node.name, valid_list(VALID_ON_BREACH_POLICIES)),
                &node.loc,
            );
        }

        // Severity level
        if !node.severity.is_empty() && !is_valid(&node.severity, VALID_SEVERITY_LEVELS) {
            self.emit(
                format!("Unknown severity '{}' in shield '{}'. Valid: {}", node.severity, node.name, valid_list(VALID_SEVERITY_LEVELS)),
                &node.loc,
            );
        }

        // max_retries >= 0
        if let Some(v) = node.max_retries {
            if v < 0 { self.emit(format!("max_retries must be >= 0, got {} in shield '{}'", v, node.name), &node.loc); }
        }

        // confidence_threshold range
        if let Some(v) = node.confidence_threshold {
            self.check_range(v, 0.0, 1.0, "confidence_threshold", &node.loc);
        }

        // allow/deny overlap
        for tool in &node.allow_tools {
            if node.deny_tools.contains(tool) {
                self.emit(
                    format!("Tool '{}' appears in both allow_tools and deny_tools in shield '{}'", tool, node.name),
                    &node.loc,
                );
            }
        }
    }

    fn check_pix(&mut self, node: &PixDefinition) {
        // Source presence
        if node.source.is_empty() {
            self.emit(format!("Pix '{}' requires a 'source' field", node.name), &node.loc);
        }

        // Depth range 1..=8
        if let Some(v) = node.depth {
            if v < 1 || v > 8 {
                self.emit(format!("depth must be between 1 and 8, got {} in pix '{}'", v, node.name), &node.loc);
            }
        }

        // Branching range 1..=10
        if let Some(v) = node.branching {
            if v < 1 || v > 10 {
                self.emit(format!("branching must be between 1 and 10, got {} in pix '{}'", v, node.name), &node.loc);
            }
        }
    }

    fn check_psyche(&mut self, node: &PsycheDefinition) {
        // §1: ψ ∈ M requires dim(M) ≥ 1
        if node.dimensions.is_empty() {
            self.emit(
                format!("Psyche '{}' requires at least one dimension (manifold dim ≥ 1)", node.name),
                &node.loc,
            );
        }

        // Duplicate dimension detection
        let mut seen: Vec<String> = Vec::new();
        for dim in &node.dimensions {
            if seen.contains(dim) {
                self.emit(format!("Duplicate dimension '{}' in psyche '{}'", dim, node.name), &node.loc);
            } else {
                seen.push(dim.clone());
            }
        }

        // Manifold noise σ ∈ (0, 1]
        if let Some(v) = node.manifold_noise {
            if v <= 0.0 || v > 1.0 {
                self.emit(
                    format!("manifold_noise must be in (0.0, 1.0], got {} in psyche '{}'", v, node.name),
                    &node.loc,
                );
            }
        }

        // Manifold momentum β ∈ [0, 1]
        if let Some(v) = node.manifold_momentum {
            self.check_range(v, 0.0, 1.0, "manifold_momentum", &node.loc);
        }

        // Safety constraints non-empty
        if node.safety_constraints.is_empty() {
            self.emit(
                format!("Psyche '{}' requires at least one safety_constraint", node.name),
                &node.loc,
            );
        } else if !node.safety_constraints.iter().any(|c| c == "non_diagnostic") {
            // §4: non_diagnostic is mandatory
            self.emit(
                format!("Psyche '{}' must include 'non_diagnostic' in safety_constraints (dependent type safety §4)", node.name),
                &node.loc,
            );
        }

        // Inference mode enum
        if !node.inference_mode.is_empty() && !is_valid(&node.inference_mode, VALID_INFERENCE_MODES) {
            self.emit(
                format!("Unknown inference_mode '{}' in psyche '{}'. Valid: {}", node.inference_mode, node.name, valid_list(VALID_INFERENCE_MODES)),
                &node.loc,
            );
        }
    }

    fn check_corpus(&mut self, node: &CorpusDefinition) {
        // Invariant G1: D ≠ ∅ — at least one document
        if node.documents.is_empty() && node.mcp_server.is_empty() {
            self.emit(
                format!("Corpus '{}' requires at least one document or an mcp_server (G1: D ≠ ∅)", node.name),
                &node.loc,
            );
        }
    }

    fn check_ots(&mut self, node: &OtsDefinition) {
        // Teleology presence (goal required)
        if node.teleology.is_empty() {
            self.emit(format!("OTS '{}' requires a 'teleology' field (goal required)", node.name), &node.loc);
        }

        // Homotopy search enum
        if !node.homotopy_search.is_empty() && !is_valid(&node.homotopy_search, VALID_OTS_HOMOTOPY) {
            self.emit(
                format!("Unknown homotopy_search '{}' in OTS '{}'. Valid: {}", node.homotopy_search, node.name, valid_list(VALID_OTS_HOMOTOPY)),
                &node.loc,
            );
        }
    }

    fn check_mandate(&mut self, node: &MandateDefinition) {
        // Constraint presence (refinement type T_M)
        if node.constraint.is_empty() {
            self.emit(
                format!("Mandate '{}' requires a 'constraint' field (refinement type T_M = {{x ∈ Σ* | M(x) ⊢ ⊤}})", node.name),
                &node.loc,
            );
        }

        // PID gains
        if let Some(v) = node.kp {
            if v <= 0.0 { self.emit(format!("kp must be > 0.0, got {} in mandate '{}'", v, node.name), &node.loc); }
        }
        if let Some(v) = node.ki {
            if v < 0.0 { self.emit(format!("ki must be >= 0.0, got {} in mandate '{}'", v, node.name), &node.loc); }
        }
        if let Some(v) = node.kd {
            if v < 0.0 { self.emit(format!("kd must be >= 0.0, got {} in mandate '{}'", v, node.name), &node.loc); }
        }

        // Tolerance ε ∈ (0, 1]
        if let Some(v) = node.tolerance {
            if v <= 0.0 || v > 1.0 {
                self.emit(format!("tolerance must be in (0.0, 1.0], got {} in mandate '{}'", v, node.name), &node.loc);
            }
        }

        // max_steps >= 1
        if let Some(v) = node.max_steps {
            if v < 1 { self.emit(format!("max_steps must be >= 1, got {} in mandate '{}'", v, node.name), &node.loc); }
        }

        // on_violation policy
        if !node.on_violation.is_empty() && !is_valid(&node.on_violation, VALID_MANDATE_POLICIES) {
            self.emit(
                format!("Unknown on_violation '{}' in mandate '{}'. Valid: {}", node.on_violation, node.name, valid_list(VALID_MANDATE_POLICIES)),
                &node.loc,
            );
        }
    }

    fn check_axonstore(&mut self, node: &AxonStoreDefinition) {
        // Backend enum
        if !node.backend.is_empty() && !is_valid(&node.backend, VALID_STORE_BACKENDS) {
            self.emit(
                format!("Unknown backend '{}' in axonstore '{}'. Valid: {}", node.backend, node.name, valid_list(VALID_STORE_BACKENDS)),
                &node.loc,
            );
        }

        // Isolation level enum
        if !node.isolation.is_empty() && !is_valid(&node.isolation, VALID_STORE_ISOLATION) {
            self.emit(
                format!("Unknown isolation '{}' in axonstore '{}'. Valid: {}", node.isolation, node.name, valid_list(VALID_STORE_ISOLATION)),
                &node.loc,
            );
        }

        // on_breach policy
        if !node.on_breach.is_empty() && !is_valid(&node.on_breach, VALID_STORE_ON_BREACH) {
            self.emit(
                format!("Unknown on_breach '{}' in axonstore '{}'. Valid: {}", node.on_breach, node.name, valid_list(VALID_STORE_ON_BREACH)),
                &node.loc,
            );
        }

        // confidence_floor range
        if let Some(v) = node.confidence_floor {
            self.check_range(v, 0.0, 1.0, "confidence_floor", &node.loc);
        }
    }

    /// §λ-L-E Fase 1 — Resource validation.
    ///
    /// Enforces: (a) lifetime ∈ {linear | affine | persistent}; (b) certainty_floor
    /// ∈ [0.0, 1.0] when present; (c) shield_ref, if non-empty, is a declared shield.
    fn check_resource(&mut self, node: &ResourceDefinition) {
        if !node.lifetime.is_empty()
            && !matches!(node.lifetime.as_str(), "linear" | "affine" | "persistent")
        {
            self.emit(
                format!(
                    "Invalid lifetime '{}' for resource '{}' — \
                     expected linear | affine | persistent",
                    node.lifetime, node.name
                ),
                &node.loc,
            );
        }
        if let Some(c) = node.certainty_floor {
            if !(0.0..=1.0).contains(&c) {
                self.emit(
                    format!(
                        "certainty_floor {c} for resource '{}' is out of range [0.0, 1.0]",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(
                    format!(
                        "Undefined shield '{}' in resource '{}'",
                        node.shield_ref, node.name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!(
                        "'{}' is a {}, not a shield (referenced in resource '{}')",
                        node.shield_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
    }

    /// §λ-L-E Fase 1 — Fabric validation.
    ///
    /// Enforces: (a) zones ≥ 1 when present; (b) shield_ref, if non-empty,
    /// is a declared shield.
    fn check_fabric(&mut self, node: &FabricDefinition) {
        if let Some(z) = node.zones {
            if z < 1 {
                self.emit(
                    format!(
                        "Fabric '{}' has invalid zones {z} — must be >= 1",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(
                    format!(
                        "Undefined shield '{}' in fabric '{}'",
                        node.shield_ref, node.name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!(
                        "'{}' is a {}, not a shield (referenced in fabric '{}')",
                        node.shield_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
    }

    /// §λ-L-E Fase 1 — Manifest validation.
    ///
    /// Enforces: (a) every name in `resources` refers to a declared resource;
    /// (b) `fabric_ref`, if non-empty, is a declared fabric; (c) no duplicate
    /// resource names within a single manifest (Separation Logic `*` disjointness
    /// within-manifest — cross-manifest aliasing is a separate check).
    fn check_manifest(&mut self, node: &ManifestDefinition) {
        // (a) resource references must resolve
        let mut seen: std::collections::HashSet<&String> = std::collections::HashSet::new();
        for res_name in &node.resources {
            if !seen.insert(res_name) {
                self.emit(
                    format!(
                        "Manifest '{}' lists resource '{}' more than once \
                         (Linear/Separation Logic disjointness)",
                        node.name, res_name
                    ),
                    &node.loc,
                );
                continue;
            }
            match self.symbols.lookup(res_name) {
                None => self.emit(
                    format!(
                        "Manifest '{}' references undefined resource '{}'",
                        node.name, res_name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "resource" => self.emit(
                    format!(
                        "'{}' is a {}, not a resource (referenced in manifest '{}')",
                        res_name, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        // (b) fabric reference
        if !node.fabric_ref.is_empty() {
            match self.symbols.lookup(&node.fabric_ref) {
                None => self.emit(
                    format!(
                        "Manifest '{}' references undefined fabric '{}'",
                        node.name, node.fabric_ref
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "fabric" => self.emit(
                    format!(
                        "'{}' is a {}, not a fabric (referenced in manifest '{}')",
                        node.fabric_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if let Some(z) = node.zones {
            if z < 1 {
                self.emit(
                    format!(
                        "Manifest '{}' has invalid zones {z} — must be >= 1",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
    }

    /// §λ-L-E Fase 1 — Observe validation.
    ///
    /// Enforces: (a) `target` refers to a declared manifest; (b) certainty_floor
    /// ∈ [0.0, 1.0] when present; (c) quorum ≥ 1 when present; (d) on_partition
    /// ∈ {fail, shield_quarantine}; (e) `sources` is non-empty.
    fn check_observe(&mut self, node: &ObserveDefinition) {
        // (a) target manifest
        if node.target.is_empty() {
            self.emit(
                format!("Observe '{}' is missing 'from <Manifest>' target", node.name),
                &node.loc,
            );
        } else {
            match self.symbols.lookup(&node.target) {
                None => self.emit(
                    format!(
                        "Observe '{}' targets undefined manifest '{}'",
                        node.name, node.target
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "manifest" => self.emit(
                    format!(
                        "'{}' is a {}, not a manifest (observed by '{}')",
                        node.target, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        // (b) certainty floor range
        if let Some(c) = node.certainty_floor {
            if !(0.0..=1.0).contains(&c) {
                self.emit(
                    format!(
                        "certainty_floor {c} for observe '{}' is out of range [0.0, 1.0]",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        // (c) quorum
        if let Some(q) = node.quorum {
            if q < 1 {
                self.emit(
                    format!(
                        "Observe '{}' has invalid quorum {q} — must be >= 1",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        // (d) on_partition enum
        if !node.on_partition.is_empty()
            && !matches!(node.on_partition.as_str(), "fail" | "shield_quarantine")
        {
            self.emit(
                format!(
                    "Invalid on_partition '{}' for observe '{}' — \
                     expected fail | shield_quarantine",
                    node.on_partition, node.name
                ),
                &node.loc,
            );
        }
        // (e) sources must be non-empty
        if node.sources.is_empty() {
            self.emit(
                format!("Observe '{}' has empty sources: list", node.name),
                &node.loc,
            );
        }
    }

    /// §λ-L-E Fase 3 — Reconcile validation.
    ///
    /// Enforces: (a) observe_ref refers to a declared observe; (b) threshold
    /// and tolerance ∈ [0.0, 1.0]; (c) shield_ref / mandate_ref (if present)
    /// resolve to correct kinds; (d) max_retries ≥ 0.
    fn check_reconcile(&mut self, node: &ReconcileDefinition) {
        if node.observe_ref.is_empty() {
            self.emit(
                format!("Reconcile '{}' is missing 'observe:' target", node.name),
                &node.loc,
            );
        } else {
            match self.symbols.lookup(&node.observe_ref) {
                None => self.emit(
                    format!(
                        "Reconcile '{}' references undefined observe '{}'",
                        node.name, node.observe_ref
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "observe" => self.emit(
                    format!(
                        "'{}' is a {}, not an observe (referenced in reconcile '{}')",
                        node.observe_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if let Some(t) = node.threshold {
            if !(0.0..=1.0).contains(&t) {
                self.emit(
                    format!(
                        "threshold {t} for reconcile '{}' is out of range [0.0, 1.0]",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        if let Some(t) = node.tolerance {
            if !(0.0..=1.0).contains(&t) {
                self.emit(
                    format!(
                        "tolerance {t} for reconcile '{}' is out of range [0.0, 1.0]",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        if node.max_retries < 0 {
            self.emit(
                format!(
                    "Reconcile '{}' has invalid max_retries {} — must be >= 0",
                    node.name, node.max_retries
                ),
                &node.loc,
            );
        }
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(
                    format!(
                        "Undefined shield '{}' in reconcile '{}'",
                        node.shield_ref, node.name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!(
                        "'{}' is a {}, not a shield (referenced in reconcile '{}')",
                        node.shield_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if !node.mandate_ref.is_empty() {
            match self.symbols.lookup(&node.mandate_ref) {
                None => self.emit(
                    format!(
                        "Undefined mandate '{}' in reconcile '{}'",
                        node.mandate_ref, node.name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "mandate" => self.emit(
                    format!(
                        "'{}' is a {}, not a mandate (referenced in reconcile '{}')",
                        node.mandate_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
    }

    /// §λ-L-E Fase 3 — Lease validation.
    ///
    /// Enforces: (a) resource_ref resolves to a declared resource; (b) duration
    /// is non-empty; (c) acquire / on_expire enums are already validated at
    /// parse time but we re-check symbolically for defence-in-depth.
    fn check_lease(&mut self, node: &LeaseDefinition) {
        if node.resource_ref.is_empty() {
            self.emit(
                format!("Lease '{}' is missing 'resource:' target", node.name),
                &node.loc,
            );
        } else {
            match self.symbols.lookup(&node.resource_ref) {
                None => self.emit(
                    format!(
                        "Lease '{}' references undefined resource '{}'",
                        node.name, node.resource_ref
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "resource" => self.emit(
                    format!(
                        "'{}' is a {}, not a resource (leased by '{}')",
                        node.resource_ref, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if node.duration.is_empty() {
            self.emit(
                format!("Lease '{}' is missing 'duration:' field", node.name),
                &node.loc,
            );
        }
    }

    /// §λ-L-E Fase 3 — Ensemble validation.
    ///
    /// Enforces: (a) each observation name refers to a declared observe;
    /// (b) quorum ≥ 1 and ≤ len(observations); (c) at least 2 observations
    /// are required for a meaningful Byzantine ensemble.
    fn check_ensemble(&mut self, node: &EnsembleDefinition) {
        if node.observations.is_empty() {
            self.emit(
                format!("Ensemble '{}' has empty observations: list", node.name),
                &node.loc,
            );
            return;
        }
        if node.observations.len() < 2 {
            self.emit(
                format!(
                    "Ensemble '{}' has {} observation(s); Byzantine quorum requires >= 2",
                    node.name, node.observations.len()
                ),
                &node.loc,
            );
        }
        let mut seen: std::collections::HashSet<&String> = std::collections::HashSet::new();
        for obs_name in &node.observations {
            if !seen.insert(obs_name) {
                self.emit(
                    format!(
                        "Ensemble '{}' lists observation '{}' more than once",
                        node.name, obs_name
                    ),
                    &node.loc,
                );
                continue;
            }
            match self.symbols.lookup(obs_name) {
                None => self.emit(
                    format!(
                        "Ensemble '{}' references undefined observation '{}'",
                        node.name, obs_name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "observe" => self.emit(
                    format!(
                        "'{}' is a {}, not an observe (referenced in ensemble '{}')",
                        obs_name, sym.kind, node.name
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if let Some(q) = node.quorum {
            if q < 1 {
                self.emit(
                    format!(
                        "Ensemble '{}' has invalid quorum {q} — must be >= 1",
                        node.name
                    ),
                    &node.loc,
                );
            } else if (q as usize) > node.observations.len() {
                self.emit(
                    format!(
                        "Ensemble '{}' quorum {q} exceeds available observations ({})",
                        node.name, node.observations.len()
                    ),
                    &node.loc,
                );
            }
        }
    }

    // ── §λ-L-E Fase 4 — Topology + π-calculus binary sessions ──────

    /// §λ-L-E Fase 4 — Session validation.
    ///
    /// Enforces: (a) exactly 2 roles; (b) role names are distinct; (c) every
    /// step has a valid op and — for send/receive — a non-empty message type;
    /// (d) Honda-Vasconcelos duality between the two roles.
    fn check_session(&mut self, node: &SessionDefinition) {
        if node.roles.len() != 2 {
            self.emit(
                format!(
                    "Session '{}' must declare exactly 2 roles (binary session); got {}",
                    node.name, node.roles.len()
                ),
                &node.loc,
            );
        } else if node.roles[0].name == node.roles[1].name {
            self.emit(
                format!(
                    "Session '{}' has duplicate role name '{}'",
                    node.name, node.roles[0].name
                ),
                &node.loc,
            );
        }
        for role in &node.roles {
            self.check_session_role(&node.name, role);
        }
        if node.roles.len() == 2 {
            self.check_session_duality(node);
        }
    }

    fn check_session_role(&mut self, session_name: &str, role: &SessionRole) {
        for (idx, step) in role.steps.iter().enumerate() {
            if !matches!(step.op.as_str(), "send" | "receive" | "loop" | "end") {
                self.emit(
                    format!(
                        "Session '{session_name}' role '{}' step #{idx} has invalid op '{}'",
                        role.name, step.op
                    ),
                    &step.loc,
                );
                continue;
            }
            if matches!(step.op.as_str(), "send" | "receive") && step.message_type.is_empty() {
                self.emit(
                    format!(
                        "Session '{session_name}' role '{}' step #{idx} '{}' \
                         requires a message type",
                        role.name, step.op
                    ),
                    &step.loc,
                );
            }
        }
    }

    fn check_session_duality(&mut self, node: &SessionDefinition) {
        let r1 = &node.roles[0];
        let r2 = &node.roles[1];
        if r1.steps.len() != r2.steps.len() {
            self.emit(
                format!(
                    "Session '{}' duality violation: roles '{}' ({} steps) and \
                     '{}' ({} steps) have different lengths",
                    node.name, r1.name, r1.steps.len(), r2.name, r2.steps.len()
                ),
                &node.loc,
            );
            return;
        }
        for (i, (s1, s2)) in r1.steps.iter().zip(r2.steps.iter()).enumerate() {
            if !steps_dual(s1, s2) {
                self.emit(
                    format!(
                        "Session '{}' duality violation at step #{i}: '{}' has \
                         '{}' but '{}' has '{}' (expected the dual)",
                        node.name, r1.name, format_step(s1),
                        r2.name, format_step(s2)
                    ),
                    &node.loc,
                );
            }
        }
    }

    /// §λ-L-E Fase 4 — Topology validation.
    ///
    /// Enforces: (a) each node name is unique + resolves to a valid kind;
    /// (b) each edge's source/target appear in `nodes`; (c) no self-loops;
    /// (d) each `session_ref` is a declared session;
    /// (e) Honda liveness — no cycle where every edge is receive-first.
    fn check_topology(&mut self, node: &TopologyDefinition) {
        const NODE_KINDS: &[&str] = &[
            "resource", "fabric", "manifest", "observe", "axonendpoint",
            "axonstore", "daemon", "agent", "shield",
        ];
        let mut seen_nodes: std::collections::HashSet<&String> = std::collections::HashSet::new();
        for n in &node.nodes {
            if !seen_nodes.insert(n) {
                self.emit(
                    format!("Topology '{}' lists node '{}' more than once", node.name, n),
                    &node.loc,
                );
                continue;
            }
            match self.symbols.lookup(n) {
                None => self.emit(
                    format!("Topology '{}' references undefined node '{}'", node.name, n),
                    &node.loc,
                ),
                Some(sym) if !NODE_KINDS.contains(&sym.kind.as_str()) => self.emit(
                    format!(
                        "Topology '{}' node '{}' is a {} — not a valid topology entity. \
                         Valid kinds: {}",
                        node.name, n, sym.kind, NODE_KINDS.join(", ")
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        for edge in &node.edges {
            self.check_topology_edge(&node.name, edge, &seen_nodes);
        }
        self.check_topology_liveness(node);
    }

    fn check_topology_edge(
        &mut self,
        topology_name: &str,
        edge: &TopologyEdge,
        declared_nodes: &std::collections::HashSet<&String>,
    ) {
        if !declared_nodes.contains(&edge.source) {
            self.emit(
                format!(
                    "Topology '{topology_name}' edge source '{}' is not in the nodes list",
                    edge.source
                ),
                &edge.loc,
            );
        }
        if !declared_nodes.contains(&edge.target) {
            self.emit(
                format!(
                    "Topology '{topology_name}' edge target '{}' is not in the nodes list",
                    edge.target
                ),
                &edge.loc,
            );
        }
        if edge.source == edge.target {
            self.emit(
                format!(
                    "Topology '{topology_name}' has self-loop edge on '{}' — \
                     π-calculus binary sessions require two distinct endpoints",
                    edge.source
                ),
                &edge.loc,
            );
        }
        if edge.session_ref.is_empty() {
            self.emit(
                format!(
                    "Topology '{topology_name}' edge {}->{} has no session reference",
                    edge.source, edge.target
                ),
                &edge.loc,
            );
            return;
        }
        match self.symbols.lookup(&edge.session_ref) {
            None => self.emit(
                format!(
                    "Topology '{topology_name}' edge {}->{} references undefined session '{}'",
                    edge.source, edge.target, edge.session_ref
                ),
                &edge.loc,
            ),
            Some(sym) if sym.kind != "session" => self.emit(
                format!(
                    "Topology '{topology_name}' edge {}->{} session ref '{}' is a {}, not a session",
                    edge.source, edge.target, edge.session_ref, sym.kind
                ),
                &edge.loc,
            ),
            _ => {}
        }
    }

    /// Honda-liveness: detect cycles whose every edge starts with `receive`
    /// on the source role. Such a cycle has no progress — static deadlock.
    fn check_topology_liveness(&mut self, node: &TopologyDefinition) {
        let mut adjacency: std::collections::HashMap<String, Vec<String>> =
            std::collections::HashMap::new();
        for edge in &node.edges {
            if !edge.source.is_empty() && !edge.target.is_empty() {
                adjacency
                    .entry(edge.source.clone())
                    .or_default()
                    .push(edge.target.clone());
            }
        }
        let cycles = find_cycles(&adjacency);
        if cycles.is_empty() {
            return;
        }
        for cycle in cycles {
            let cycle_edges = cycle_to_edges(&cycle, &node.edges);
            // Only flag if (a) we found every edge in the cycle (sanity) and
            // (b) every one of them is receive-first on the source side.
            if cycle_edges.len() == cycle.len()
                && cycle_edges.iter().all(|e| self.edge_is_receive_first(e))
            {
                let mut tour: Vec<String> = cycle.clone();
                if let Some(first) = cycle.first() {
                    tour.push(first.clone());
                }
                self.emit(
                    format!(
                        "Topology '{}' has a static deadlock: cycle [{}] where every \
                         edge waits on receive — no progress is possible (Honda liveness violation)",
                        node.name, tour.join(" -> ")
                    ),
                    &node.loc,
                );
            }
        }
    }

    /// Look up the session AST for an edge and check whether the FIRST
    /// role's first step is `receive`. Source plays the first role (fixed
    /// convention per AST docstring).
    fn edge_is_receive_first(&self, edge: &TopologyEdge) -> bool {
        let session = match find_session_by_name(self.program, &edge.session_ref) {
            Some(s) => s,
            None => return false,
        };
        let first_role = match session.roles.first() {
            Some(r) => r,
            None => return false,
        };
        first_role
            .steps
            .first()
            .map(|s| s.op == "receive")
            .unwrap_or(false)
    }

    // ── §λ-L-E Fase 5 — Cognitive immune system (paper_immune_v2.md) ───

    /// §λ-L-E Fase 5 — Immune validation.
    ///
    /// Enforces paper §8.2 mandatory scope + watch non-empty + sensitivity
    /// ∈ [0.0, 1.0] + window ≥ 1 + decay enum.
    fn check_immune(&mut self, node: &ImmuneDefinition) {
        if node.scope.is_empty() {
            self.emit(
                format!(
                    "immune '{}' requires an explicit 'scope' (tenant | flow | global). \
                     No implicit default exists — blast radius must be declared (paper §8.2)",
                    node.name
                ),
                &node.loc,
            );
        } else if !matches!(node.scope.as_str(), "tenant" | "flow" | "global") {
            self.emit(
                format!(
                    "immune '{}' has invalid scope '{}'. Valid: tenant | flow | global",
                    node.name, node.scope
                ),
                &node.loc,
            );
        }
        if node.watch.is_empty() {
            self.emit(
                format!(
                    "immune '{}' requires a non-empty 'watch' list (observables to monitor)",
                    node.name
                ),
                &node.loc,
            );
        }
        if let Some(s) = node.sensitivity {
            if !(0.0..=1.0).contains(&s) {
                self.emit(
                    format!(
                        "immune '{}' sensitivity must be in [0.0, 1.0], got {s}",
                        node.name
                    ),
                    &node.loc,
                );
            }
        }
        if node.window < 1 {
            self.emit(
                format!(
                    "immune '{}' window must be >= 1, got {}",
                    node.name, node.window
                ),
                &node.loc,
            );
        }
        if !matches!(node.decay.as_str(), "exponential" | "linear" | "none") {
            self.emit(
                format!(
                    "immune '{}' has invalid decay '{}'. Valid: exponential | linear | none",
                    node.name, node.decay
                ),
                &node.loc,
            );
        }
    }

    /// §λ-L-E Fase 5 — Reflex validation.
    ///
    /// Enforces mandatory scope + valid scope/on_level/action enums + trigger
    /// resolves to an `immune` (one-way dependency per paper §4).
    fn check_reflex(&mut self, node: &ReflexDefinition) {
        if node.scope.is_empty() {
            self.emit(
                format!(
                    "reflex '{}' requires an explicit 'scope' (tenant | flow | global) — paper §8.2",
                    node.name
                ),
                &node.loc,
            );
        } else if !matches!(node.scope.as_str(), "tenant" | "flow" | "global") {
            self.emit(
                format!("reflex '{}' has invalid scope '{}'", node.name, node.scope),
                &node.loc,
            );
        }
        if node.trigger.is_empty() {
            self.emit(
                format!("reflex '{}' requires a 'trigger: <ImmuneName>'", node.name),
                &node.loc,
            );
        } else {
            match self.symbols.lookup(&node.trigger) {
                None => self.emit(
                    format!(
                        "reflex '{}' references undefined trigger '{}' (expected an immune)",
                        node.name, node.trigger
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "immune" => self.emit(
                    format!(
                        "reflex '{}' trigger '{}' is a {}, not an immune",
                        node.name, node.trigger, sym.kind
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if !matches!(node.on_level.as_str(), "know" | "believe" | "speculate" | "doubt") {
            self.emit(
                format!(
                    "reflex '{}' invalid on_level '{}'. Valid: know | believe | speculate | doubt",
                    node.name, node.on_level
                ),
                &node.loc,
            );
        }
        if node.action.is_empty() {
            self.emit(
                format!(
                    "reflex '{}' requires an 'action' (drop | revoke | emit | redact | \
                     quarantine | terminate | alert)",
                    node.name
                ),
                &node.loc,
            );
        } else if !matches!(
            node.action.as_str(),
            "drop" | "revoke" | "emit" | "redact" | "quarantine" | "terminate" | "alert"
        ) {
            self.emit(
                format!("reflex '{}' invalid action '{}'", node.name, node.action),
                &node.loc,
            );
        }
    }

    /// §λ-L-E Fase 5 — Heal validation.
    ///
    /// Enforces mandatory scope + source is an immune + on_level/mode enums +
    /// **paper §7.3: mode='adversarial' requires a shield gate** + shield_ref
    /// (if present) resolves to a shield + max_patches ≥ 1.
    fn check_heal(&mut self, node: &HealDefinition) {
        if node.scope.is_empty() {
            self.emit(
                format!(
                    "heal '{}' requires an explicit 'scope' (tenant | flow | global) — paper §8.2",
                    node.name
                ),
                &node.loc,
            );
        } else if !matches!(node.scope.as_str(), "tenant" | "flow" | "global") {
            self.emit(
                format!("heal '{}' has invalid scope '{}'", node.name, node.scope),
                &node.loc,
            );
        }
        if node.source.is_empty() {
            self.emit(
                format!("heal '{}' requires a 'source: <ImmuneName>'", node.name),
                &node.loc,
            );
        } else {
            match self.symbols.lookup(&node.source) {
                None => self.emit(
                    format!(
                        "heal '{}' references undefined source '{}' (expected an immune)",
                        node.name, node.source
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "immune" => self.emit(
                    format!(
                        "heal '{}' source '{}' is a {}, not an immune",
                        node.name, node.source, sym.kind
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if !matches!(node.on_level.as_str(), "know" | "believe" | "speculate" | "doubt") {
            self.emit(
                format!("heal '{}' invalid on_level '{}'", node.name, node.on_level),
                &node.loc,
            );
        }
        if !matches!(node.mode.as_str(), "audit_only" | "human_in_loop" | "adversarial") {
            self.emit(
                format!(
                    "heal '{}' invalid mode '{}'. Valid: audit_only | human_in_loop | \
                     adversarial (paper §7)",
                    node.name, node.mode
                ),
                &node.loc,
            );
        }
        // Paper §7.3 — adversarial mode requires an explicit shield gate.
        if node.mode == "adversarial" && node.shield_ref.is_empty() {
            self.emit(
                format!(
                    "heal '{}' mode='adversarial' requires a 'shield' gate \
                     (no LLM-generated patch ships without review). \
                     Paper §7.3: adversarial mode needs explicit Risk Acceptance",
                    node.name
                ),
                &node.loc,
            );
        }
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(
                    format!(
                        "heal '{}' references undefined shield '{}'",
                        node.name, node.shield_ref
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!(
                        "heal '{}' shield ref '{}' is a {}, not a shield",
                        node.name, node.shield_ref, sym.kind
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
        if node.max_patches < 1 {
            self.emit(
                format!(
                    "heal '{}' max_patches must be >= 1, got {}",
                    node.name, node.max_patches
                ),
                &node.loc,
            );
        }
    }

    // ── §λ-L-E Fase 9 — UI cognitiva (component / view) ────────────
    //
    // Compile-time invariants enforced below:
    //   1. `renders` references a declared `type`.
    //   2. `on_interact` (if present) is a declared `flow` whose first
    //      parameter type matches `renders`.
    //   3. If `renders` carries κ (regulatory class), `via_shield` is
    //      MANDATORY and its `compliance` must cover every κ of the
    //      rendered type. Fase 9.5 compile-time contract.
    //   4. `via_shield` (if present) must name a declared `shield`.
    //   5. Every component listed in a `view.components` must resolve
    //      to a declared `component`.

    fn check_component(&mut self, node: &ComponentDefinition) {
        // (1) renders must resolve to a type
        let rendered_type = if node.renders.is_empty() {
            self.emit(
                format!(
                    "component '{}' requires 'renders: <TypeName>'",
                    node.name
                ),
                &node.loc,
            );
            None
        } else {
            match self.symbols.lookup(&node.renders) {
                None => {
                    self.emit(
                        format!(
                            "component '{}' references undefined type '{}'",
                            node.name, node.renders
                        ),
                        &node.loc,
                    );
                    None
                }
                Some(sym) if sym.kind != "type" => {
                    self.emit(
                        format!(
                            "component '{}' renders '{}' which is a {}, not a type",
                            node.name, node.renders, sym.kind
                        ),
                        &node.loc,
                    );
                    None
                }
                Some(_) => find_type_by_name(self.program, &node.renders),
            }
        };

        // (4) shield ref
        let shield_node = if node.via_shield.is_empty() {
            None
        } else {
            match self.symbols.lookup(&node.via_shield) {
                None => {
                    self.emit(
                        format!(
                            "component '{}' references undefined shield '{}'",
                            node.name, node.via_shield
                        ),
                        &node.loc,
                    );
                    None
                }
                Some(sym) if sym.kind != "shield" => {
                    self.emit(
                        format!(
                            "component '{}' via_shield '{}' is a {}, not a shield",
                            node.name, node.via_shield, sym.kind
                        ),
                        &node.loc,
                    );
                    None
                }
                Some(_) => find_shield_by_name(self.program, &node.via_shield),
            }
        };

        // (3) regulated-render rule — Fase 9.5
        if let Some(t) = rendered_type {
            let type_kappa: std::collections::HashSet<&str> =
                t.compliance.iter().map(|s| s.as_str()).collect();
            if !type_kappa.is_empty() {
                match shield_node {
                    None => self.emit(
                        format!(
                            "component '{}' renders regulated type '{}' \
                             (kappa = {{{}}}) but declares no 'via_shield'. \
                             Regulated renders require a shield that covers \
                             the type's kappa — Fase 9.5.",
                            node.name,
                            node.renders,
                            {
                                let mut v: Vec<&str> = type_kappa.iter().copied().collect();
                                v.sort();
                                v.join(", ")
                            }
                        ),
                        &node.loc,
                    ),
                    Some(s) => {
                        let shield_kappa: std::collections::HashSet<&str> =
                            s.compliance.iter().map(|s| s.as_str()).collect();
                        let mut missing: Vec<&str> = type_kappa
                            .difference(&shield_kappa)
                            .copied()
                            .collect();
                        missing.sort();
                        if !missing.is_empty() {
                            self.emit(
                                format!(
                                    "component '{}' via_shield '{}' does not cover \
                                     kappa = {{{}}} of type '{}'. Add these classes \
                                     to the shield's 'compliance' list or pick a \
                                     shield that already covers them.",
                                    node.name,
                                    node.via_shield,
                                    missing.join(", "),
                                    node.renders,
                                ),
                                &node.loc,
                            );
                        }
                    }
                }
            }
        }

        // (2) on_interact must resolve to a flow with compatible signature
        if !node.on_interact.is_empty() {
            match self.symbols.lookup(&node.on_interact) {
                None => self.emit(
                    format!(
                        "component '{}' references undefined flow '{}'",
                        node.name, node.on_interact
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "flow" => self.emit(
                    format!(
                        "component '{}' on_interact '{}' is a {}, not a flow",
                        node.name, node.on_interact, sym.kind
                    ),
                    &node.loc,
                ),
                Some(_) => {
                    if let Some(flow) = find_flow_by_name(self.program, &node.on_interact) {
                        if !rendered_type.is_none() {
                            if let Some(first_param) = flow.parameters.first() {
                                let pt = first_param.type_expr.name.as_str();
                                if !pt.is_empty() && pt != node.renders {
                                    self.emit(
                                        format!(
                                            "component '{}' on_interact flow '{}' \
                                             expects first parameter of type '{}', \
                                             but component renders '{}'. Signatures \
                                             must match — Fase 9.2 rule 2.",
                                            node.name,
                                            node.on_interact,
                                            pt,
                                            node.renders
                                        ),
                                        &node.loc,
                                    );
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    fn check_view(&mut self, node: &ViewDefinition) {
        if node.components.is_empty() {
            self.emit(
                format!(
                    "view '{}' has empty components list — a view must \
                     compose at least one component",
                    node.name
                ),
                &node.loc,
            );
            return;
        }
        let mut seen: std::collections::HashSet<&String> = std::collections::HashSet::new();
        for comp_name in &node.components {
            if !seen.insert(comp_name) {
                self.emit(
                    format!(
                        "view '{}' lists component '{}' more than once",
                        node.name, comp_name
                    ),
                    &node.loc,
                );
                continue;
            }
            match self.symbols.lookup(comp_name) {
                None => self.emit(
                    format!(
                        "view '{}' references undefined component '{}'",
                        node.name, comp_name
                    ),
                    &node.loc,
                ),
                Some(sym) if sym.kind != "component" => self.emit(
                    format!(
                        "view '{}' component ref '{}' is a {}, not a component",
                        node.name, comp_name, sym.kind
                    ),
                    &node.loc,
                ),
                _ => {}
            }
        }
    }

    fn check_axonendpoint(&mut self, node: &AxonEndpointDefinition) {
        // HTTP method enum
        if !node.method.is_empty() {
            let upper = node.method.to_uppercase();
            if !is_valid(&upper, VALID_ENDPOINT_METHODS) {
                self.emit(
                    format!("Unknown HTTP method '{}' in axonendpoint '{}'. Valid: {}", node.method, node.name, valid_list(VALID_ENDPOINT_METHODS)),
                    &node.loc,
                );
            }
        }

        // Path must start with /
        if !node.path.is_empty() && !node.path.starts_with('/') {
            self.emit(
                format!("Path must start with '/' in axonendpoint '{}', got '{}'", node.name, node.path),
                &node.loc,
            );
        }

        // execute_flow reference
        if !node.execute_flow.is_empty() {
            match self.symbols.lookup(&node.execute_flow) {
                None => self.emit(format!("Undefined flow '{}' in axonendpoint '{}'", node.execute_flow, node.name), &node.loc),
                Some(sym) if sym.kind != "flow" => self.emit(
                    format!("'{}' is a {}, not a flow (referenced in axonendpoint '{}')", node.execute_flow, sym.kind, node.name), &node.loc),
                _ => {}
            }
        }

        // Shield reference
        if !node.shield_ref.is_empty() {
            match self.symbols.lookup(&node.shield_ref) {
                None => self.emit(format!("Undefined shield '{}' in axonendpoint '{}'", node.shield_ref, node.name), &node.loc),
                Some(sym) if sym.kind != "shield" => self.emit(
                    format!("'{}' is a {}, not a shield (referenced in axonendpoint '{}')", node.shield_ref, sym.kind, node.name), &node.loc),
                _ => {}
            }
        }

        // Retries >= 0
        if let Some(v) = node.retries {
            if v < 0 { self.emit(format!("retries must be >= 0, got {} in axonendpoint '{}'", v, node.name), &node.loc); }
        }
    }

    // ── Flow-level reference checks ─────────────────────────────────

    fn check_flow_steps(&mut self, steps: &[FlowStep], flow_name: &str) {
        for step in steps {
            match step {
                FlowStep::ShieldApply(n) => {
                    if !n.shield_name.is_empty() {
                        match self.symbols.lookup(&n.shield_name) {
                            None => self.emit(format!("Undefined shield '{}' in flow '{}'", n.shield_name, flow_name), &n.loc),
                            Some(sym) if sym.kind != "shield" => self.emit(
                                format!("'{}' is a {}, not a shield", n.shield_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                FlowStep::OtsApply(n) => {
                    if !n.ots_name.is_empty() {
                        match self.symbols.lookup(&n.ots_name) {
                            None => self.emit(format!("Undefined OTS '{}' in flow '{}'", n.ots_name, flow_name), &n.loc),
                            Some(sym) if sym.kind != "ots" => self.emit(
                                format!("'{}' is a {}, not an OTS", n.ots_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                FlowStep::MandateApply(n) => {
                    if !n.mandate_name.is_empty() {
                        match self.symbols.lookup(&n.mandate_name) {
                            None => self.emit(format!("Undefined mandate '{}' in flow '{}'", n.mandate_name, flow_name), &n.loc),
                            Some(sym) if sym.kind != "mandate" => self.emit(
                                format!("'{}' is a {}, not a mandate", n.mandate_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                FlowStep::LambdaDataApply(n) => {
                    if !n.lambda_data_name.is_empty() {
                        match self.symbols.lookup(&n.lambda_data_name) {
                            None => self.emit(format!("Undefined lambda '{}' in flow '{}'", n.lambda_data_name, flow_name), &n.loc),
                            Some(sym) if sym.kind != "lambda_data" => self.emit(
                                format!("'{}' is a {}, not a lambda_data", n.lambda_data_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                FlowStep::Navigate(n) => {
                    if !n.pix_name.is_empty() {
                        match self.symbols.lookup(&n.pix_name) {
                            None => self.emit(format!("Undefined pix '{}' in navigate step", n.pix_name), &n.loc),
                            Some(sym) if sym.kind != "pix" => self.emit(
                                format!("'{}' is a {}, not a pix", n.pix_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                    if n.query_expr.is_empty() {
                        self.emit("Navigate step requires a query expression".to_string(), &n.loc);
                    }
                }
                FlowStep::Drill(n) => {
                    if !n.pix_name.is_empty() {
                        match self.symbols.lookup(&n.pix_name) {
                            None => self.emit(format!("Undefined pix '{}' in drill step", n.pix_name), &n.loc),
                            Some(sym) if sym.kind != "pix" => self.emit(
                                format!("'{}' is a {}, not a pix", n.pix_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                    if n.subtree_path.is_empty() {
                        self.emit("Drill step requires a subtree_path".to_string(), &n.loc);
                    }
                    if n.query_expr.is_empty() {
                        self.emit("Drill step requires a query expression".to_string(), &n.loc);
                    }
                }
                FlowStep::Trail(n) => {
                    if n.navigate_ref.is_empty() {
                        self.emit("Trail step requires a navigate_ref".to_string(), &n.loc);
                    }
                }
                FlowStep::Corroborate(n) => {
                    if n.navigate_ref.is_empty() {
                        self.emit("Corroborate step requires a navigate_ref".to_string(), &n.loc);
                    }
                }
                FlowStep::DaemonStep(n) => {
                    if !n.daemon_ref.is_empty() {
                        match self.symbols.lookup(&n.daemon_ref) {
                            None => self.emit(format!("Undefined daemon '{}' in flow '{}'", n.daemon_ref, flow_name), &n.loc),
                            Some(sym) if sym.kind != "daemon" => self.emit(
                                format!("'{}' is a {}, not a daemon", n.daemon_ref, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                FlowStep::Persist(n) => {
                    self.check_store_ref(&n.store_name, flow_name, &n.loc);
                }
                FlowStep::Retrieve(n) => {
                    self.check_store_ref(&n.store_name, flow_name, &n.loc);
                }
                FlowStep::Mutate(n) => {
                    self.check_store_ref(&n.store_name, flow_name, &n.loc);
                }
                FlowStep::Purge(n) => {
                    self.check_store_ref(&n.store_name, flow_name, &n.loc);
                }
                FlowStep::ComputeApply(n) => {
                    if !n.compute_name.is_empty() {
                        match self.symbols.lookup(&n.compute_name) {
                            None => self.emit(format!("Undefined compute '{}' in flow '{}'", n.compute_name, flow_name), &n.loc),
                            Some(sym) if sym.kind != "compute" => self.emit(
                                format!("'{}' is a {}, not a compute", n.compute_name, sym.kind), &n.loc),
                            _ => {}
                        }
                    }
                }
                // Recurse into control flow bodies
                FlowStep::If(n) => {
                    self.check_flow_steps(&n.then_body, flow_name);
                    self.check_flow_steps(&n.else_body, flow_name);
                }
                FlowStep::ForIn(n) => {
                    self.check_flow_steps(&n.body, flow_name);
                }
                // All other steps: no cross-reference checks needed
                _ => {}
            }
        }
    }

    fn check_store_ref(&mut self, store_name: &str, flow_name: &str, loc: &Loc) {
        if !store_name.is_empty() {
            match self.symbols.lookup(store_name) {
                None => self.emit(format!("Undefined axonstore '{}' in flow '{}'", store_name, flow_name), loc),
                Some(sym) if sym.kind != "axonstore" => self.emit(
                    format!("'{}' is a {}, not an axonstore", store_name, sym.kind), loc),
                _ => {}
            }
        }
    }

    // ── Type reference validation (epistemic lattice) ──────────────

    /// Verify that a type name is either built-in or user-defined.
    /// Soft check: unknown types are silently accepted (may come from imports).
    fn check_type_reference(&self, type_name: &str, _loc: &Loc) -> bool {
        if type_name.is_empty() { return true; }
        let builtin = epistemic::builtin_types();
        if builtin.contains(type_name) { return true; }
        if self.symbols.lookup(type_name).map_or(false, |s| s.kind == "type") {
            return true;
        }
        // Soft: unknown types accepted silently (may be from imports)
        true
    }

    // ── Epistemic mode validation ──────────────────────────────────

    fn check_epistemic_mode(&mut self, mode: &str, loc: &Loc) {
        const VALID_EPISTEMIC_MODES: &[&str] = &["believe", "doubt", "know", "speculate"];
        if !mode.is_empty() && !is_valid(mode, VALID_EPISTEMIC_MODES) {
            self.emit(
                format!("Unknown epistemic mode '{}'. Valid: {}", mode, valid_list(VALID_EPISTEMIC_MODES)),
                loc,
            );
        }
    }
}

// ── §λ-L-E Fase 4 — Honda-Vasconcelos helpers (free fns) ────────────────────

/// Honda-Vasconcelos duality on a single step pair:
/// `send T ↔ receive T`, `loop ↔ loop`, `end ↔ end`.
fn steps_dual(s1: &SessionStep, s2: &SessionStep) -> bool {
    match (s1.op.as_str(), s2.op.as_str()) {
        ("send", "receive") | ("receive", "send") => s1.message_type == s2.message_type,
        ("loop", "loop") | ("end", "end") => true,
        _ => false,
    }
}

fn format_step(s: &SessionStep) -> String {
    if matches!(s.op.as_str(), "send" | "receive") {
        format!("{} {}", s.op, s.message_type)
    } else {
        s.op.clone()
    }
}

/// Directed-graph cycle detector (DFS with gray/black colouring). Returns
/// one representative ordering per strongly-connected cycle found.
fn find_cycles(
    adjacency: &std::collections::HashMap<String, Vec<String>>,
) -> Vec<Vec<String>> {
    let mut color: std::collections::HashMap<String, &'static str> =
        std::collections::HashMap::new();
    let mut stack: Vec<String> = Vec::new();
    let mut cycles: Vec<Vec<String>> = Vec::new();

    fn visit(
        n: &str,
        adjacency: &std::collections::HashMap<String, Vec<String>>,
        color: &mut std::collections::HashMap<String, &'static str>,
        stack: &mut Vec<String>,
        cycles: &mut Vec<Vec<String>>,
    ) {
        color.insert(n.to_string(), "gray");
        stack.push(n.to_string());
        let targets = adjacency.get(n).cloned().unwrap_or_default();
        for tgt in targets {
            match color.get(&tgt).copied() {
                Some("gray") => {
                    if let Some(idx) = stack.iter().position(|s| s == &tgt) {
                        cycles.push(stack[idx..].to_vec());
                    }
                }
                None => visit(&tgt, adjacency, color, stack, cycles),
                _ => {}
            }
        }
        stack.pop();
        color.insert(n.to_string(), "black");
    }

    let keys: Vec<String> = adjacency.keys().cloned().collect();
    for src in keys {
        if !color.contains_key(&src) {
            visit(&src, adjacency, &mut color, &mut stack, &mut cycles);
        }
    }
    cycles
}

fn cycle_to_edges<'a>(
    cycle: &[String],
    edges: &'a [TopologyEdge],
) -> Vec<&'a TopologyEdge> {
    let n = cycle.len();
    let mut result = Vec::with_capacity(n);
    for i in 0..n {
        let src = &cycle[i];
        let tgt = &cycle[(i + 1) % n];
        if let Some(e) = edges.iter().find(|e| &e.source == src && &e.target == tgt) {
            result.push(e);
        }
    }
    result
}

/// Locate a session by name in the program's declarations (flat scan).
fn find_session_by_name<'a>(program: &'a Program, name: &str) -> Option<&'a SessionDefinition> {
    for decl in &program.declarations {
        if let Declaration::Session(s) = decl {
            if s.name == name {
                return Some(s);
            }
        }
    }
    None
}

fn find_type_by_name<'a>(program: &'a Program, name: &str) -> Option<&'a TypeDefinition> {
    for decl in &program.declarations {
        if let Declaration::Type(t) = decl {
            if t.name == name {
                return Some(t);
            }
        }
    }
    None
}

fn find_shield_by_name<'a>(program: &'a Program, name: &str) -> Option<&'a ShieldDefinition> {
    for decl in &program.declarations {
        if let Declaration::Shield(s) = decl {
            if s.name == name {
                return Some(s);
            }
        }
    }
    None
}

fn find_flow_by_name<'a>(program: &'a Program, name: &str) -> Option<&'a FlowDefinition> {
    for decl in &program.declarations {
        if let Declaration::Flow(f) = decl {
            if f.name == name {
                return Some(f);
            }
        }
    }
    None
}
