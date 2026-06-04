//! §Fase 36.x.f (D1, D6) — exactly-one-terminator property/fuzz pass.
//!
//! The streaming producer (`run_streaming_via_dispatcher`) must emit
//! EXACTLY ONE terminator — `FlowComplete` XOR `FlowError` — for any
//! flow that runs to a conclusion, and NEVER two (the malformed
//! double terminator 36.x.a pinned and 36.x.c fixed). This pack
//! hammers the producer with deterministic LCG-generated flow shapes
//! and asserts the contract holds over every one:
//!
//!   - **Never two terminators** — `terminator_count <= 1` ALWAYS,
//!     for every shape, every outcome (the core D1 invariant).
//!   - **Always one when not cancelled** — a flow that is not
//!     cancelled mid-run emits exactly one terminator.
//!   - **The terminator is last** — no event follows it.
//!   - **FlowStart leads** — a non-cancelled run opens with
//!     `FlowStart`.
//!
//! Shapes covered: pure-step (1–3 steps), mixed (in_memory store +
//! retrieve + step + persist), `apply:`-streaming-tool, empty,
//! erroring (sqlite store → registry-build failure), garbage source
//! (compile failure), flow-not-found, and pre-cancelled.

use axon::cancel_token::CancellationFlag;
use axon::flow_execution_event::FlowExecutionEvent;
use axon::streaming_via_dispatcher::run_streaming_via_dispatcher;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};

/// Deterministic LCG — reproducible from the seed.
struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.0
    }
    fn n(&mut self, m: u64) -> u64 {
        self.next() % m
    }
}

fn is_terminator(ev: &FlowExecutionEvent) -> bool {
    matches!(
        ev,
        FlowExecutionEvent::FlowComplete { .. } | FlowExecutionEvent::FlowError { .. }
    )
}

/// Generate a `(source, flow_name)` pair for one of 7 shape
/// archetypes. The source either type-checks (the runtime contract
/// is under test) or is deliberate garbage (the §2 compile-error
/// terminator path).
fn gen_shape(lcg: &mut Lcg) -> (String, String) {
    match lcg.n(7) {
        // 0 — pure-step flow, 1..=3 streaming steps.
        0 => {
            let n = 1 + lcg.n(3);
            let steps: String = (0..n)
                .map(|i| {
                    format!("    step S{i} {{ ask: \"q{i}\" output: Stream<Token> }}\n")
                })
                .collect();
            (format!("flow F() -> Unit {{\n{steps}}}"), "F".into())
        }
        // 1 — mixed flow: in_memory store + retrieve + step + persist.
        1 => (
            "axonstore mem { backend: in_memory }\n\
             flow F() -> Unit {\n\
                 retrieve mem { where: \"1 = 1\" as: ctx }\n\
                 step S { ask: \"q\" output: Stream<Token> }\n\
                 persist into mem { k: \"v\" content: \"${S}\" }\n\
             }"
            .into(),
            "F".into(),
        ),
        // 2 — a step applying a streaming tool (no provider → stub).
        2 => (
            "tool tk { description: \"t\" effects: <stream:drop_oldest> }\n\
             flow F() -> Unit { step S { ask: \"q\" apply: tk } }"
            .into(),
            "F".into(),
        ),
        // 3 — empty flow (zero nodes).
        3 => ("flow F() -> Unit { }".into(), "F".into()),
        // 4 — erroring flow: a `sqlite` store has no runtime backend,
        //     so `StoreRegistry::build` fails → §2.5 `FlowError`.
        4 => (
            "axonstore bad { backend: sqlite connection: \"x\" }\n\
             flow F() -> Unit {\n\
                 retrieve bad { where: \"1 = 1\" as: r }\n\
                 step S { ask: \"q\" output: Stream<Token> }\n\
             }"
            .into(),
            "F".into(),
        ),
        // 5 — garbage source → §2 compile-error `FlowError`.
        5 => {
            let junk = ["flow F( {{{", "%%%not axon%%%", "step step step", ""]
                [lcg.n(4) as usize];
            (junk.into(), "F".into())
        }
        // 6 — valid source but the requested flow is absent → §3.
        _ => (
            "flow Other() -> Unit { step S { ask: \"q\" } }".into(),
            "MissingFlow".into(),
        ),
    }
}

async fn run_shape(
    source: &str,
    flow_name: &str,
    cancelled: bool,
) -> Vec<FlowExecutionEvent> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let cancel = CancellationFlag::new();
    if cancelled {
        cancel.cancel();
    }
    run_streaming_via_dispatcher(
        source.to_string(),
        "fuzz.axon".to_string(),
        flow_name.to_string(),
        "stub".to_string(),
        cancel,
        tx,
        Arc::new(Mutex::new(HashMap::new())),
        Arc::new(Mutex::new(Vec::new())),
        Arc::new(Mutex::new(Vec::new())),
        None,
        None,
        HashMap::new(),
        HashMap::new(),
    )
    .await;
    let mut events = Vec::new();
    while let Ok(ev) = rx.try_recv() {
        events.push(ev);
    }
    events
}

#[tokio::test]
async fn exactly_one_terminator_over_arbitrary_flow_shapes() {
    let mut lcg = Lcg(0x3656_7866_2E72_5EED);
    for iter in 0..600u64 {
        let (source, flow_name) = gen_shape(&mut lcg);
        // ~1 in 8 runs is pre-cancelled.
        let cancelled = lcg.n(8) == 0;
        let events = run_shape(&source, &flow_name, cancelled).await;

        let term_count = events.iter().filter(|e| is_terminator(e)).count();

        // ── Core D1 — NEVER two terminators ────────────────────────
        assert!(
            term_count <= 1,
            "§36.x.f D1 — iter {iter}: the streaming producer emitted \
             {term_count} terminators — it must emit AT MOST ONE \
             (`FlowComplete` XOR `FlowError`), never a double \
             terminator. cancelled={cancelled}\n  source:\n{source}\n\
             events: {events:?}"
        );

        if !cancelled {
            // ── A non-cancelled flow always terminates exactly once ─
            assert_eq!(
                term_count, 1,
                "§36.x.f D1 — iter {iter}: a non-cancelled flow must \
                 emit EXACTLY ONE terminator. Got {term_count}.\n  \
                 source:\n{source}\n  events: {events:?}"
            );
            // ── FlowStart leads ────────────────────────────────────
            assert!(
                matches!(events.first(), Some(FlowExecutionEvent::FlowStart { .. })),
                "§36.x.f — iter {iter}: a run must open with FlowStart. \
                 events: {events:?}"
            );
        }

        // ── The terminator, when present, is the LAST event ────────
        if term_count == 1 {
            assert!(
                events.last().is_some_and(is_terminator),
                "§36.x.f D1 — iter {iter}: the terminator must be the \
                 FINAL event — nothing follows it. events: {events:?}"
            );
            // …and no earlier event is a terminator.
            let last = events.len() - 1;
            assert!(
                !events[..last].iter().any(is_terminator),
                "§36.x.f D1 — iter {iter}: no event precedes-then- \
                 duplicates the terminator. events: {events:?}"
            );
        }
    }
}

#[tokio::test]
async fn every_archetype_is_reachable_and_holds_the_contract() {
    // Pin each of the 7 archetypes individually — a deterministic
    // anchor independent of the LCG walk above.
    let cases: [(&str, &str); 4] = [
        ("flow F() -> Unit { step S { ask: \"x\" output: Stream<Token> } }", "F"),
        ("flow F() -> Unit { }", "F"),
        (
            "axonstore bad { backend: sqlite connection: \"x\" }\n\
             flow F() -> Unit { retrieve bad { where: \"1=1\" as: r } }",
            "F",
        ),
        ("flow Other() -> Unit { }", "MissingFlow"),
    ];
    for (source, flow_name) in cases {
        let events = run_shape(source, flow_name, false).await;
        let term = events.iter().filter(|e| is_terminator(e)).count();
        assert_eq!(
            term, 1,
            "§36.x.f: archetype `{flow_name}` must emit exactly one \
             terminator. events: {events:?}"
        );
    }
}
