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

const VALID_EFFECTS: &[&str] = &["io", "network", "pure", "random", "storage"];

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
                let base = e.split(':').next().unwrap_or(e);
                if !is_valid(base, VALID_EFFECTS) {
                    self.emit(
                        format!(
                            "Unknown effect '{}' in tool '{}'. Valid: {}",
                            e, node.name, valid_list(VALID_EFFECTS)
                        ),
                        &node.loc,
                    );
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
