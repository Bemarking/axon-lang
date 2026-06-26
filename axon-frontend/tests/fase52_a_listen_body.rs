//! §Fase 52.a — the `listen` handler body now executes (parsed, not skipped).
//!
//! Pre-§52.a the `listen … { … }` block was `skip_braced_block`'d: the
//! listener was declarable but inert, and a `daemon`'s listeners were dropped
//! entirely at IR lowering. §52.a un-skips the body — it parses into real
//! flow-steps, lowers into `IRListenStep.body` (+ the daemon's `IRDaemon.
//! listeners` now survive), and is type-checked like any flow body. This is the
//! foundation the §52.b cron channel + §52.c runtime executor build on.

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::ir_nodes::{IRFlowNode, IRProgram};
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn ir_of(src: &str) -> IRProgram {
    let tokens = Lexer::new(src, "d.axon").tokenize().expect("lex");
    let program = Parser::new(tokens).parse().expect("parse");
    IRGenerator::new().generate(&program)
}

fn errors_of(src: &str) -> Vec<String> {
    let tokens = Lexer::new(src, "d.axon").tokenize().expect("lex");
    let program = Parser::new(tokens).parse().expect("parse");
    TypeChecker::new(&program)
        .check()
        .into_iter()
        .map(|e| e.message)
        .collect()
}

fn has(errs: &[String], needle: &str) -> bool {
    errs.iter().any(|e| e.contains(needle))
}

// ── Daemon listener body ─────────────────────────────────────────────────────

#[test]
fn daemon_listener_body_is_parsed_and_lowered_to_ir() {
    // The daemon's listener now survives lowering (was dropped) AND carries its
    // handler body (was skipped).
    let src = "daemon Cleaner {\n\
                 goal: \"clean\"\n\
                 listen \"ticks\" as e {\n\
                    let n = \"noop\"\n\
                 }\n\
               }";
    let ir = ir_of(src);
    let daemon = ir.daemons.iter().find(|d| d.name == "Cleaner").expect("daemon in IR");
    assert_eq!(daemon.listeners.len(), 1, "the listener must survive lowering");
    assert_eq!(
        daemon.listeners[0].body.len(),
        1,
        "the handler body must be lowered (1 step), not skipped"
    );
    assert_eq!(daemon.listeners[0].event_alias, "e");
}

#[test]
fn bodyless_listen_lowers_to_an_empty_body() {
    // Back-compat: a `listen <channel>` with no `{ … }` keeps an empty body —
    // the serialized IR stays byte-identical to the pre-§52.a shape (D8).
    let src = "daemon Cleaner {\n\
                 goal: \"clean\"\n\
                 listen \"ticks\" as e\n\
               }";
    let ir = ir_of(src);
    let daemon = ir.daemons.iter().find(|d| d.name == "Cleaner").unwrap();
    assert_eq!(daemon.listeners.len(), 1);
    assert!(
        daemon.listeners[0].body.is_empty(),
        "a bodyless listen has no steps"
    );
}

#[test]
fn daemon_listener_body_is_type_checked() {
    // Proof the body is WALKED (not skipped): a `yield` is only well-formed
    // inside a `quant` block, so a `yield` in a listener body must raise
    // axon-E0787. Pre-§52.a (body skipped) this produced no error.
    let src = "daemon Cleaner {\n\
                 goal: \"clean\"\n\
                 listen \"ticks\" as e {\n\
                    yield e\n\
                 }\n\
               }";
    assert!(
        has(&errors_of(src), "axon-E0787"),
        "a yield in a listener body must be type-checked → E0787: {:?}",
        errors_of(src)
    );
}

// ── Flow-body listener body ──────────────────────────────────────────────────

#[test]
fn flow_body_listen_carries_its_body_in_ir() {
    let src = "flow F() -> Unit {\n\
                 listen \"ticks\" as e {\n\
                    let n = \"noop\"\n\
                 }\n\
               }";
    let ir = ir_of(src);
    let flow = ir.flows.iter().find(|f| f.name == "F").expect("flow F");
    let listen = flow
        .steps
        .iter()
        .find_map(|n| match n {
            IRFlowNode::Listen(l) => Some(l),
            _ => None,
        })
        .expect("a Listen node in the flow body");
    assert_eq!(
        listen.body.len(),
        1,
        "the flow-body listen handler must carry its lowered step"
    );
}
