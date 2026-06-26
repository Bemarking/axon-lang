//! §Fase 52.b — the cron-channel surface: `listen "cron:<expr>" as t { … }`.
//!
//! A `listen` whose channel is `"cron:<expr>"` is a first-class TIME trigger
//! (not a legacy string topic). The type-checker validates the 5-field cron
//! expression (so a schedule that type-checks is one the §52.c TimerSource can
//! fire), rejects a malformed schedule (`axon-E0789`), and rejects a scheduled
//! trigger with no handler body (`axon-E0790`). It must NOT emit the Fase-13
//! string-topic deprecation warning for a cron channel.

use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn check(src: &str) -> (Vec<String>, Vec<String>) {
    let tokens = Lexer::new(src, "c.axon").tokenize().expect("lex");
    let program = Parser::new(tokens).parse().expect("parse");
    let (errs, warns) = TypeChecker::new(&program).check_with_warnings();
    (
        errs.into_iter().map(|e| e.message).collect(),
        warns.into_iter().map(|w| w.message).collect(),
    )
}

fn has(v: &[String], needle: &str) -> bool {
    v.iter().any(|s| s.contains(needle))
}

const CRON_DAEMON: &str = "daemon SessionCleaner {\n\
     goal: \"hibernate idle sessions\"\n\
     listen \"cron:*/5 * * * *\" as tick {\n\
        step Hibernate { ask: \"hibernate idle sessions\" output: Unit }\n\
     }\n\
   }";

#[test]
fn valid_cron_daemon_is_clean_and_not_deprecated() {
    let (errs, warns) = check(CRON_DAEMON);
    assert!(errs.is_empty(), "a valid cron daemon must type-check clean: {errs:?}");
    assert!(
        !has(&warns, "deprecated"),
        "a cron channel is a time trigger, not a legacy string topic — no deprecation warning: {warns:?}"
    );
}

#[test]
fn malformed_cron_raises_e0789() {
    // minute 99 is out of range (0–59).
    let src = CRON_DAEMON.replace("cron:*/5 * * * *", "cron:99 * * * *");
    let (errs, _) = check(&src);
    assert!(has(&errs, "axon-E0789"), "a malformed cron must raise E0789: {errs:?}");
}

#[test]
fn cron_with_wrong_field_count_raises_e0789() {
    // Four fields, not five.
    let src = CRON_DAEMON.replace("cron:*/5 * * * *", "cron:*/5 * * *");
    let (errs, _) = check(&src);
    assert!(has(&errs, "axon-E0789"), "wrong field count must raise E0789: {errs:?}");
}

#[test]
fn cron_listener_without_a_body_raises_e0790() {
    // A scheduled trigger with no handler is a no-op.
    let src = "daemon SessionCleaner {\n\
                 goal: \"x\"\n\
                 listen \"cron:*/5 * * * *\" as tick\n\
               }";
    let (errs, _) = check(src);
    assert!(
        has(&errs, "axon-E0790"),
        "a cron listener with no body must raise E0790: {errs:?}"
    );
}

#[test]
fn non_cron_string_topic_still_warns() {
    // Regression: the cron branch must not suppress the legacy-topic warning
    // for an ordinary string topic.
    let src = "daemon D {\n\
                 goal: \"x\"\n\
                 listen \"ticks\" as e {\n\
                    step S { ask: \"do\" output: Unit }\n\
                 }\n\
               }";
    let (_, warns) = check(src);
    assert!(
        has(&warns, "deprecated"),
        "a non-cron string topic still gets the Fase-13 deprecation warning: {warns:?}"
    );
}
