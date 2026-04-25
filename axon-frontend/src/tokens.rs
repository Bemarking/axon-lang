//! AXON token types and keyword lookup table.
//! Direct port of axon/compiler/tokens.py.

/// A single token produced by the AXON lexer.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct Token {
    pub ttype: TokenType,
    pub value: String,
    pub line: u32,
    pub column: u32,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TokenType {
    // ── Keywords ──────────────────────────────────────────────────
    Persona, Context, Intent, Flow, Reason, Anchor, Validate, Refine,
    Memory, Tool, Probe, Weave, Step, Type, Import, Run, If, Else,
    Use, Remember, Recall,
    // Epistemic
    Know, Believe, Speculate, Doubt,
    // Parallel / yielding
    Par, Consolidate, Hibernate, Deliberate, Consensus,
    // Creative synthesis
    Forge,
    // OTS
    Ots, Teleology, HomotopySearch, LinearConstraints, LossFunction,
    // Streaming & effects
    Stream, OnChunk, OnComplete, Effects, Pure, Network,
    // Agent
    Agent, Goal, Tools, Budget, Strategy, OnStuck,
    // Shield
    Shield, Scan, OnBreach, Severity, Allow, Deny, Sandbox, Quarantine, Redact,
    // PIX
    Pix, Navigate, Drill, Trail,
    // Psyche
    Psyche, Dimensions, Manifold, Quantum, Inference,
    // MDN
    Corpus, Corroborate, EdgeFilter,
    // Data Science
    Dataspace, Ingest, Focus, Associate, Aggregate, Explore,
    // EMCP
    Mcp, Taint,
    // Mandate
    Mandate, Constraint, Kp, Ki, Kd, Tolerance, MaxSteps, OnViolation,
    // Daemon
    Daemon, Listen, BudgetPerEvent,
    // Compute
    Compute, Logic,
    // Lambda Data
    Lambda, Ontology, Certainty, TemporalFrame, Provenance, Derivation,
    // AxonStore
    AxonStore, Schema, Persist, Retrieve, Mutate, Purge, Transact,
    // AxonEndpoint
    AxonEndpoint,
    // I/O Cognitivo (§λ-L-E Fase 1 — Resources)
    Resource, Fabric, Manifest, Observe,
    // Control Cognitivo (§λ-L-E Fase 3)
    Reconcile, Lease, Ensemble,
    // Topology & Session (§λ-L-E Fase 4 — π-calculus)
    Topology, Session, Send, Receive, Loop, End,
    // Immune System (§λ-L-E Fase 5)
    Immune, Reflex, Heal,
    // UI Cognitiva (§λ-L-E Fase 9 — 100% .axon apps)
    Component, View,
    // Mobile Typed Channels (§λ-L-E Fase 13 — π-calc mobility)
    Channel, Emit, Publish, Discover,
    // Modifiers
    As, Within, ConstrainedBy, OnFailure, OutputTo, Effort,
    // Contextual
    For, In, Into, Against, About, From, Where, Let, Return, Or,
    // Field keywords
    Given, Ask, Output,

    // ── Literals ──────────────────────────────────────────────────
    StringLit, Integer, Float, Bool, Duration, Identifier,

    // ── Symbols ───────────────────────────────────────────────────
    LBrace, RBrace, LParen, RParen, LBracket, RBracket,
    Colon, Comma, Dot, Arrow, DotDot, Question, At,
    Lt, Gt, Lte, Gte, Eq, Neq, Assign,
    Plus, Minus, Star, Slash,

    // ── Special ───────────────────────────────────────────────────
    Eof,
}

pub fn keyword_type(word: &str) -> TokenType {
    match word {
        "persona"          => TokenType::Persona,
        "context"          => TokenType::Context,
        "intent"           => TokenType::Intent,
        "flow"             => TokenType::Flow,
        "reason"           => TokenType::Reason,
        "anchor"           => TokenType::Anchor,
        "validate"         => TokenType::Validate,
        "refine"           => TokenType::Refine,
        "memory"           => TokenType::Memory,
        "tool"             => TokenType::Tool,
        "probe"            => TokenType::Probe,
        "weave"            => TokenType::Weave,
        "step"             => TokenType::Step,
        "type"             => TokenType::Type,
        "import"           => TokenType::Import,
        "run"              => TokenType::Run,
        "if"               => TokenType::If,
        "else"             => TokenType::Else,
        "use"              => TokenType::Use,
        "remember"         => TokenType::Remember,
        "recall"           => TokenType::Recall,
        "know"             => TokenType::Know,
        "believe"          => TokenType::Believe,
        "speculate"        => TokenType::Speculate,
        "doubt"            => TokenType::Doubt,
        "par"              => TokenType::Par,
        "consolidate"      => TokenType::Consolidate,
        "hibernate"        => TokenType::Hibernate,
        "deliberate"       => TokenType::Deliberate,
        "consensus"        => TokenType::Consensus,
        "forge"            => TokenType::Forge,
        "ots"              => TokenType::Ots,
        "teleology"        => TokenType::Teleology,
        "homotopy_search"  => TokenType::HomotopySearch,
        "linear_constraints" => TokenType::LinearConstraints,
        "loss_function"    => TokenType::LossFunction,
        "stream"           => TokenType::Stream,
        "on_chunk"         => TokenType::OnChunk,
        "on_complete"      => TokenType::OnComplete,
        "effects"          => TokenType::Effects,
        "pure"             => TokenType::Pure,
        "network"          => TokenType::Network,
        "agent"            => TokenType::Agent,
        "goal"             => TokenType::Goal,
        "tools"            => TokenType::Tools,
        "budget"           => TokenType::Budget,
        "strategy"         => TokenType::Strategy,
        "on_stuck"         => TokenType::OnStuck,
        "shield"           => TokenType::Shield,
        "scan"             => TokenType::Scan,
        "on_breach"        => TokenType::OnBreach,
        "severity"         => TokenType::Severity,
        "allow"            => TokenType::Allow,
        "deny"             => TokenType::Deny,
        "sandbox"          => TokenType::Sandbox,
        "quarantine"       => TokenType::Quarantine,
        "redact"           => TokenType::Redact,
        "pix"              => TokenType::Pix,
        "navigate"         => TokenType::Navigate,
        "drill"            => TokenType::Drill,
        "trail"            => TokenType::Trail,
        "psyche"           => TokenType::Psyche,
        "dimensions"       => TokenType::Dimensions,
        "manifold"         => TokenType::Manifold,
        "quantum"          => TokenType::Quantum,
        "inference"        => TokenType::Inference,
        "corpus"           => TokenType::Corpus,
        "corroborate"      => TokenType::Corroborate,
        "edge_filter"      => TokenType::EdgeFilter,
        "dataspace"        => TokenType::Dataspace,
        "ingest"           => TokenType::Ingest,
        "focus"            => TokenType::Focus,
        "associate"        => TokenType::Associate,
        "aggregate"        => TokenType::Aggregate,
        "explore"          => TokenType::Explore,
        "mcp"              => TokenType::Mcp,
        "taint"            => TokenType::Taint,
        "mandate"          => TokenType::Mandate,
        "constraint"       => TokenType::Constraint,
        "kp"               => TokenType::Kp,
        "ki"               => TokenType::Ki,
        "kd"               => TokenType::Kd,
        "tolerance"        => TokenType::Tolerance,
        "max_steps"        => TokenType::MaxSteps,
        "on_violation"     => TokenType::OnViolation,
        "daemon"           => TokenType::Daemon,
        "listen"           => TokenType::Listen,
        "budget_per_event" => TokenType::BudgetPerEvent,
        "compute"          => TokenType::Compute,
        "logic"            => TokenType::Logic,
        "lambda"           => TokenType::Lambda,
        "ontology"         => TokenType::Ontology,
        "certainty"        => TokenType::Certainty,
        "temporal_frame"   => TokenType::TemporalFrame,
        "provenance"       => TokenType::Provenance,
        "derivation"       => TokenType::Derivation,
        "axonstore"        => TokenType::AxonStore,
        "schema"           => TokenType::Schema,
        "persist"          => TokenType::Persist,
        "retrieve"         => TokenType::Retrieve,
        "mutate"           => TokenType::Mutate,
        "purge"            => TokenType::Purge,
        "transact"         => TokenType::Transact,
        "axonendpoint" | "axpoint" => TokenType::AxonEndpoint,
        // I/O Cognitivo (§λ-L-E Fase 1 — Resources)
        "resource"         => TokenType::Resource,
        "fabric"           => TokenType::Fabric,
        "manifest"         => TokenType::Manifest,
        "observe"          => TokenType::Observe,
        // Control Cognitivo (§λ-L-E Fase 3)
        "reconcile"        => TokenType::Reconcile,
        "lease"            => TokenType::Lease,
        "ensemble"         => TokenType::Ensemble,
        // Topology & Session (§λ-L-E Fase 4 — π-calculus)
        "topology"         => TokenType::Topology,
        "session"          => TokenType::Session,
        "send"             => TokenType::Send,
        "receive"          => TokenType::Receive,
        "loop"             => TokenType::Loop,
        "end"              => TokenType::End,
        // Immune System (§λ-L-E Fase 5)
        "immune"           => TokenType::Immune,
        "reflex"           => TokenType::Reflex,
        "heal"             => TokenType::Heal,
        // UI Cognitiva (§λ-L-E Fase 9)
        "component"        => TokenType::Component,
        "view"             => TokenType::View,
        // Mobile Typed Channels (§λ-L-E Fase 13)
        "channel"          => TokenType::Channel,
        "emit"             => TokenType::Emit,
        "publish"          => TokenType::Publish,
        "discover"         => TokenType::Discover,
        "as"               => TokenType::As,
        "within"           => TokenType::Within,
        "constrained_by"   => TokenType::ConstrainedBy,
        "on_failure"       => TokenType::OnFailure,
        "output_to"        => TokenType::OutputTo,
        "effort"           => TokenType::Effort,
        "for"              => TokenType::For,
        "in"               => TokenType::In,
        "into"             => TokenType::Into,
        "against"          => TokenType::Against,
        "about"            => TokenType::About,
        "from"             => TokenType::From,
        "where"            => TokenType::Where,
        "let"              => TokenType::Let,
        "return"           => TokenType::Return,
        "or"               => TokenType::Or,
        "given"            => TokenType::Given,
        "ask"              => TokenType::Ask,
        "output"           => TokenType::Output,
        "true" | "false"   => TokenType::Bool,
        _                  => TokenType::Identifier,
    }
}

/// Returns true for keywords that open a top-level declaration.
/// Used by the structural declaration counter (depth-0 scan).
pub fn is_declaration_keyword(tt: &TokenType) -> bool {
    matches!(
        tt,
        TokenType::Persona
            | TokenType::Flow
            | TokenType::Anchor
            | TokenType::Context
            | TokenType::Intent
            | TokenType::Type
            | TokenType::Memory
            | TokenType::Tool
            | TokenType::Probe
            | TokenType::Weave
            | TokenType::Agent
            | TokenType::Shield
            | TokenType::Pix
            | TokenType::Psyche
            | TokenType::Corpus
            | TokenType::Dataspace
            | TokenType::Mcp
            | TokenType::Daemon
            | TokenType::Compute
            | TokenType::Mandate
            | TokenType::Lambda
            | TokenType::AxonStore
            | TokenType::AxonEndpoint
            | TokenType::Import
            | TokenType::Run
            // §λ-L-E Fase 1–5 — I/O cognitivo, control, topology, immune
            | TokenType::Resource
            | TokenType::Fabric
            | TokenType::Manifest
            | TokenType::Observe
            | TokenType::Reconcile
            | TokenType::Lease
            | TokenType::Ensemble
            | TokenType::Topology
            | TokenType::Session
            | TokenType::Immune
            | TokenType::Reflex
            | TokenType::Heal
            // §λ-L-E Fase 9 — UI cognitiva
            | TokenType::Component
            | TokenType::View
            // §λ-L-E Fase 13 — Mobile typed channels
            | TokenType::Channel
    )
}

#[cfg(test)]
mod tests_lang_extensions {
    //! Regression tests for the Fase 1–5 keyword additions.
    use super::*;

    fn check(word: &str, expected: TokenType) {
        assert_eq!(keyword_type(word), expected, "keyword '{word}'");
    }

    #[test]
    fn fase1_io_cognitivo_keywords() {
        check("resource", TokenType::Resource);
        check("fabric",   TokenType::Fabric);
        check("manifest", TokenType::Manifest);
        check("observe",  TokenType::Observe);
    }

    #[test]
    fn fase3_control_keywords() {
        check("reconcile", TokenType::Reconcile);
        check("lease",     TokenType::Lease);
        check("ensemble",  TokenType::Ensemble);
    }

    #[test]
    fn fase4_topology_and_session_keywords() {
        check("topology", TokenType::Topology);
        check("session",  TokenType::Session);
        check("send",     TokenType::Send);
        check("receive",  TokenType::Receive);
        check("loop",     TokenType::Loop);
        check("end",      TokenType::End);
    }

    #[test]
    fn fase5_immune_keywords() {
        check("immune", TokenType::Immune);
        check("reflex", TokenType::Reflex);
        check("heal",   TokenType::Heal);
    }

    #[test]
    fn new_decl_keywords_are_declaration_level() {
        for tt in [
            TokenType::Resource, TokenType::Fabric, TokenType::Manifest, TokenType::Observe,
            TokenType::Reconcile, TokenType::Lease, TokenType::Ensemble,
            TokenType::Topology, TokenType::Session,
            TokenType::Immune, TokenType::Reflex, TokenType::Heal,
        ] {
            assert!(is_declaration_keyword(&tt), "{tt:?} must be a top-level decl");
        }
    }

    #[test]
    fn session_body_keywords_are_not_declaration_level() {
        for tt in [TokenType::Send, TokenType::Receive, TokenType::Loop, TokenType::End] {
            assert!(
                !is_declaration_keyword(&tt),
                "{tt:?} is a session-body step, not a top-level decl"
            );
        }
    }

    #[test]
    fn unknown_words_fall_back_to_identifier() {
        assert_eq!(keyword_type("frobnicate"), TokenType::Identifier);
        assert_eq!(keyword_type("PatientRecord"), TokenType::Identifier);
    }

    // §λ-L-E Fase 13 — Mobile typed channels.

    #[test]
    fn fase13_channel_keywords() {
        check("channel",  TokenType::Channel);
        check("emit",     TokenType::Emit);
        check("publish",  TokenType::Publish);
        check("discover", TokenType::Discover);
    }

    #[test]
    fn fase13_channel_is_top_level_decl() {
        assert!(is_declaration_keyword(&TokenType::Channel),
            "channel must be a top-level decl");
    }

    #[test]
    fn fase13_emit_publish_discover_are_flow_steps_not_decls() {
        for tt in [TokenType::Emit, TokenType::Publish, TokenType::Discover] {
            assert!(
                !is_declaration_keyword(&tt),
                "{tt:?} is a flow-step reduction, not a top-level decl"
            );
        }
    }
}
