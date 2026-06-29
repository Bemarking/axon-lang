//! §Fase 52.c.2 — the single-node `daemon` runtime: cron scheduling + the
//! handler-body executor.
//!
//! §52.b parsed + validated `listen "cron:<expr>"` listeners; §52.c.1 made the
//! handler body executable flow-steps (incl. `run <Flow>`). This module is the
//! engine that makes a `daemon` actually FIRE on a single node:
//!
//!   1. [`next_fire_after`] — given a validated [`CronSchedule`] (its fields
//!      already expanded to value sets by §52.b) and an instant, the next
//!      wall-clock minute that matches. Pure + exhaustively tested; the timer
//!      and the §52.d enterprise HA scheduler both compute fire times with it.
//!   2. [`cron_listeners`] — extract a daemon's cron listeners (schedule + body)
//!      from its IR.
//!   3. [`run_invocations`] — the `run <Flow>` steps a handler body invokes.
//!   4. [`execute_listener_body`] — run those invocations through the proven
//!      [`crate::runner::execute_server_flow`] (whose registry path runs a flow
//!      by name with default persona/context — no top-level `run` required).
//!   5. [`run_daemon`] — the async driver: per cron listener, sleep to the next
//!      fire and execute the body, until cancelled. Single-node (the OSS
//!      privilege); the §52.d enterprise layer adds multi-tenant mount + HA
//!      fire-once-across-replicas on top of this same scheduling math.
//!
//! **dom/dow semantics (honest v1):** matching is AND across all five fields.
//! POSIX cron's special-case OR between day-of-month and day-of-week (when BOTH
//! are restricted) is a deferred refinement — it only differs when neither is
//! `*`, and the expanded `CronSchedule` does not retain the wildcard-vs-full
//! distinction needed to detect that case. Every schedule with a `*` in dom or
//! dow (the overwhelming majority) is identical under AND and OR.

use chrono::{DateTime, Datelike, Duration, Timelike, Utc};

use axon_frontend::cron::{cron_expr, CronSchedule};
use axon_frontend::ir_nodes::{IRDaemon, IRFlowNode, IRListenStep, IRRun, IRWindow};

use crate::window::{decide, WindowAction};

/// A clock — injected so the scheduler is testable with a fixed time.
pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

/// The production clock (wall-clock UTC).
#[derive(Debug, Clone, Copy, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

/// The next instant strictly after `after` that matches `schedule`, at
/// minute granularity. `None` if no match within ~366 days (an impossible
/// schedule, e.g. Feb 30). Deterministic + side-effect free.
pub fn next_fire_after(schedule: &CronSchedule, after: DateTime<Utc>) -> Option<DateTime<Utc>> {
    // Start at the next whole minute strictly after `after`.
    let mut t = (after + Duration::minutes(1))
        .with_second(0)
        .and_then(|t| t.with_nanosecond(0))?;
    let limit = after + Duration::days(366);
    while t <= limit {
        if matches_minute(schedule, t) {
            return Some(t);
        }
        t += Duration::minutes(1);
    }
    None
}

/// The next `n` fire times from `from` (each strictly after the previous).
/// Stops early if the schedule has no further match within the horizon.
pub fn next_fires(schedule: &CronSchedule, from: DateTime<Utc>, n: usize) -> Vec<DateTime<Utc>> {
    let mut out = Vec::with_capacity(n);
    let mut cursor = from;
    for _ in 0..n {
        match next_fire_after(schedule, cursor) {
            Some(t) => {
                out.push(t);
                cursor = t;
            }
            None => break,
        }
    }
    out
}

/// Does this wall-clock minute match every field of the schedule? (AND
/// semantics — see the module note on dom/dow.)
fn matches_minute(s: &CronSchedule, t: DateTime<Utc>) -> bool {
    let dow = t.weekday().num_days_from_sunday(); // 0 = Sunday … 6 = Saturday
    s.minute.contains(&t.minute())
        && s.hour.contains(&t.hour())
        && s.day_of_month.contains(&t.day())
        && s.month.contains(&t.month())
        && s.day_of_week.contains(&dow)
}

/// One cron-scheduled listener of a daemon: its validated schedule + a borrow
/// of its handler body (the flow-steps to run on each fire).
pub struct CronListener<'a> {
    /// The parsed cron schedule (channel was `"cron:<expr>"`).
    pub schedule: CronSchedule,
    /// The handler body — flow-steps executed per fire.
    pub body: &'a [IRFlowNode],
    /// The listener's source channel string (for diagnostics/audit).
    pub channel: String,
}

/// Extract a daemon's CRON listeners (channel `"cron:<expr>"` that parses).
/// Event (non-cron) listeners are ignored here — they fire on the event bus,
/// not the timer. A malformed cron is skipped (it was already `axon-E0789` at
/// type-check; defensively skipped at runtime rather than panicking).
pub fn cron_listeners(daemon: &IRDaemon) -> Vec<CronListener<'_>> {
    daemon
        .listeners
        .iter()
        .filter_map(|l: &IRListenStep| {
            let expr = cron_expr(&l.channel)?;
            let schedule = CronSchedule::parse(expr).ok()?;
            Some(CronListener {
                schedule,
                body: &l.body,
                channel: l.channel.clone(),
            })
        })
        .collect()
}

/// §Fase 71.c — the `window` primitive a daemon binds via `window:`, resolved
/// against the program's window declarations. `None` when the daemon has no
/// temporal guard (the common case — behaviour is byte-identical to pre-§71).
/// A dangling `window_ref` (rejected by `axon-T825` at compile time) resolves
/// to `None` here, so the daemon fires unguarded rather than panicking.
pub fn bound_window<'a>(
    ir: &'a axon_frontend::ir_nodes::IRProgram,
    daemon: &IRDaemon,
) -> Option<&'a IRWindow> {
    if daemon.window_ref.is_empty() {
        return None;
    }
    ir.windows.iter().find(|w| w.name == daemon.window_ref)
}

/// The `run <Flow>` invocations in a handler body, in order. v1 scheduled
/// handlers ORCHESTRATE flows (the logic lives in the flows they run); this is
/// the set of flows a tick dispatches.
pub fn run_invocations(body: &[IRFlowNode]) -> Vec<&IRRun> {
    body.iter()
        .filter_map(|n| match n {
            IRFlowNode::Run(r) => Some(r),
            _ => None,
        })
        .collect()
}

/// Execute a handler body once (one tick): dispatch each `run <Flow>`
/// invocation through [`crate::runner::execute_server_flow`]. Returns the
/// per-invocation results (`Ok` metrics or an error string), in order.
///
/// `ir` is the full program (the flow registry `execute_server_flow` resolves
/// the invoked flow against). Synchronous: a tick runs its flows to completion
/// before the next sleep.
pub fn execute_listener_body(
    ir: &axon_frontend::ir_nodes::IRProgram,
    body: &[IRFlowNode],
    backend: &str,
    source_file: &str,
    // §Fase 72.c — the daemon's linear-effect budget gate (shared across ticks so
    // bucket/window state is cumulative). `None` for a budgetless daemon.
    budget: Option<std::sync::Arc<std::sync::Mutex<crate::runtime::budget_kernel::BudgetGate>>>,
) -> Vec<(String, Result<crate::runner::ServerRunnerMetrics, String>)> {
    let empty = std::collections::HashMap::new();
    run_invocations(body)
        .into_iter()
        .map(|run| {
            let result = crate::runner::execute_server_flow(
                ir,
                &run.flow_name,
                backend,
                source_file,
                None,
                None,
                &empty,
                &empty,
                None,
                // §Fase 24.g.2 — OSS daemon: env/default LLM endpoint
                // (per-tenant override is the enterprise supervisor's path).
                None,
                None,
                // §Fase 72.c — the daemon's effect budget gate.
                budget.clone(),
            );
            (run.flow_name.clone(), result)
        })
        .collect()
}

/// §52.c.2 — the single-node daemon driver. For each cron listener, loops:
/// compute the next fire from the clock, sleep until then, execute the body.
/// Returns when `cancel` is triggered. Each listener is driven on its own
/// spawned task so independent schedules don't block each other.
///
/// Single-node by construction: it fires once PER PROCESS. A multi-replica
/// deploy must NOT run this directly (it would double-fire) — the §52.d
/// enterprise supervisor adds the fire-once-across-replicas guard on top of the
/// same [`next_fire_after`] math.
pub async fn run_daemon(
    ir: std::sync::Arc<axon_frontend::ir_nodes::IRProgram>,
    daemon_name: String,
    backend: String,
    clock: std::sync::Arc<dyn Clock>,
    cancel: crate::cancel_token::CancellationFlag,
) {
    // Snapshot the daemon's cron schedules + bodies (owned, so the spawned
    // per-listener tasks don't borrow `ir`'s daemon list). §Fase 71.c also
    // snapshots the bound `window` (cloned once — it is the same guard for every
    // listener of the daemon).
    // §Fase 72.c also builds the daemon's `budget { … }` gate ONCE (shared
    // `Arc<Mutex>` across every listener + tick, so the rate buckets / max windows
    // accumulate across the daemon's whole lifetime — a daily `max` spans ticks).
    type SharedBudget = Option<std::sync::Arc<std::sync::Mutex<crate::runtime::budget_kernel::BudgetGate>>>;
    let (listeners, window, budget): (
        Vec<(CronSchedule, Vec<IRFlowNode>, String)>,
        Option<IRWindow>,
        SharedBudget,
    ) = {
        let Some(daemon) = ir.daemons.iter().find(|d| d.name == daemon_name) else {
            eprintln!("§52.c.2 run_daemon: daemon '{daemon_name}' not in IR — nothing to drive");
            return;
        };
        let window = bound_window(&ir, daemon).cloned();
        let budget = daemon.budget.as_ref().map(|b| {
            std::sync::Arc::new(std::sync::Mutex::new(
                crate::runtime::budget_kernel::BudgetGate::from_ir(b, &daemon_name, clock.now()),
            ))
        });
        let listeners = cron_listeners(daemon)
            .into_iter()
            .map(|l| (l.schedule, l.body.to_vec(), l.channel))
            .collect();
        (listeners, window, budget)
    };

    let mut tasks = Vec::new();
    for (schedule, body, channel) in listeners {
        let ir = ir.clone();
        let clock = clock.clone();
        let cancel = cancel.clone();
        let daemon_name = daemon_name.clone();
        let backend = backend.clone();
        let window = window.clone();
        let budget = budget.clone();
        tasks.push(tokio::spawn(async move {
            loop {
                let now = clock.now();
                let Some(next) = next_fire_after(&schedule, now) else {
                    eprintln!(
                        "§52.c.2 daemon '{daemon_name}' listener '{channel}': schedule never \
                         fires within the horizon — stopping this listener"
                    );
                    return;
                };
                let wait = (next - now).to_std().unwrap_or(std::time::Duration::ZERO);
                tokio::select! {
                    _ = cancel.cancelled() => return,
                    _ = tokio::time::sleep(wait) => {
                        // §Fase 71.c — the temporal guard. `next` is the wall-clock
                        // minute the tick fires at; evaluate the bound window there.
                        if let Some(w) = &window {
                            match decide(next, w) {
                                WindowAction::Fire => {} // inside → fall through and fire.
                                WindowAction::Skip => {
                                    eprintln!(
                                        "§71.c daemon '{daemon_name}' tick at {next} is OUTSIDE \
                                         window '{}' (on_outside: skip) — dropped",
                                        w.name
                                    );
                                    continue;
                                }
                                WindowAction::Warn => {
                                    eprintln!(
                                        "§71.c daemon '{daemon_name}' tick at {next} is OUTSIDE \
                                         window '{}' (on_outside: warn) — firing anyway",
                                        w.name
                                    );
                                    // fall through and fire.
                                }
                                WindowAction::Defer { open_at } => {
                                    // The OSS single-process supervisor cannot persist a
                                    // defer ledger; it degrades `defer` to a logged skip.
                                    // True coalesced fire-once-when-open is the §71.d
                                    // enterprise defer-ledger.
                                    eprintln!(
                                        "§71.c daemon '{daemon_name}' tick at {next} is OUTSIDE \
                                         window '{}' (on_outside: defer) — OSS degrades defer to \
                                         skip (next opening {open_at:?}); the enterprise \
                                         defer-ledger fires it once when the window opens",
                                        w.name
                                    );
                                    continue;
                                }
                            }
                        }
                        let results =
                            execute_listener_body(&ir, &body, &backend, "<daemon>", budget.clone());
                        for (flow, res) in results {
                            if let Err(e) = res {
                                eprintln!(
                                    "§52.c.2 daemon '{daemon_name}' tick → flow '{flow}' failed: {e}"
                                );
                            }
                        }
                    }
                }
            }
        }));
    }
    for t in tasks {
        let _ = t.await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(y: i32, mo: u32, d: u32, h: u32, mi: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, mo, d, h, mi, 0).unwrap()
    }

    #[test]
    fn every_five_minutes_next_fire() {
        let s = CronSchedule::parse("*/5 * * * *").unwrap();
        // 10:02 → next is 10:05.
        assert_eq!(next_fire_after(&s, at(2026, 6, 26, 10, 2)), Some(at(2026, 6, 26, 10, 5)));
        // 10:05 exactly → strictly after → 10:10.
        assert_eq!(next_fire_after(&s, at(2026, 6, 26, 10, 5)), Some(at(2026, 6, 26, 10, 10)));
        // 10:57 → rolls to 11:00.
        assert_eq!(next_fire_after(&s, at(2026, 6, 26, 10, 57)), Some(at(2026, 6, 26, 11, 0)));
    }

    #[test]
    fn daily_at_specific_time_rolls_to_next_day() {
        let s = CronSchedule::parse("30 9 * * *").unwrap(); // 09:30 daily
        assert_eq!(next_fire_after(&s, at(2026, 6, 26, 9, 0)), Some(at(2026, 6, 26, 9, 30)));
        // After today's 09:30 → tomorrow 09:30.
        assert_eq!(next_fire_after(&s, at(2026, 6, 26, 9, 30)), Some(at(2026, 6, 27, 9, 30)));
    }

    #[test]
    fn weekday_business_hours_skips_weekend() {
        // 0 9 * * 1-5 = 09:00 Mon–Fri. 2026-06-26 is a Friday; next Mon is 29th.
        let s = CronSchedule::parse("0 9 * * 1-5").unwrap();
        // Friday 10:00 → next is Monday 09:00 (skips Sat/Sun).
        let fired = next_fire_after(&s, at(2026, 6, 26, 10, 0)).unwrap();
        assert_eq!(fired, at(2026, 6, 29, 9, 0));
        assert_eq!(fired.weekday().num_days_from_sunday(), 1, "Monday");
    }

    #[test]
    fn next_fires_sequence() {
        let s = CronSchedule::parse("*/15 * * * *").unwrap();
        let fires = next_fires(&s, at(2026, 6, 26, 8, 0), 3);
        assert_eq!(
            fires,
            vec![at(2026, 6, 26, 8, 15), at(2026, 6, 26, 8, 30), at(2026, 6, 26, 8, 45)]
        );
    }

    #[test]
    fn impossible_schedule_yields_none() {
        // Feb 30 never occurs.
        let s = CronSchedule::parse("0 0 30 2 *").unwrap();
        assert_eq!(next_fire_after(&s, at(2026, 1, 1, 0, 0)), None);
    }

    fn ir_with_daemon(src: &str) -> axon_frontend::ir_nodes::IRProgram {
        let tokens = axon_frontend::lexer::Lexer::new(src, "d.axon").tokenize().unwrap();
        let program = axon_frontend::parser::Parser::new(tokens).parse().unwrap();
        axon_frontend::ir_generator::IRGenerator::new().generate(&program)
    }

    #[test]
    fn extracts_cron_listeners_and_invocations() {
        let ir = ir_with_daemon(
            "flow HibernateSession() -> Unit { step S { ask: \"x\" output: Unit } }\n\
             daemon Cleaner {\n\
               goal: \"clean\"\n\
               listen \"cron:*/5 * * * *\" as tick { run HibernateSession() }\n\
               listen \"user_events\" as e { run HibernateSession() }\n\
             }",
        );
        let daemon = ir.daemons.iter().find(|d| d.name == "Cleaner").unwrap();
        let crons = cron_listeners(daemon);
        // Only the cron listener is a timer source (the event listener is not).
        assert_eq!(crons.len(), 1);
        assert_eq!(crons[0].channel, "cron:*/5 * * * *");
        let invs = run_invocations(crons[0].body);
        assert_eq!(invs.len(), 1);
        assert_eq!(invs[0].flow_name, "HibernateSession");
    }

    #[test]
    fn bound_window_resolves_the_daemon_guard() {
        let ir = ir_with_daemon(
            "flow Send() -> Unit { step S { ask: \"x\" output: Unit } }\n\
             window BusinessHours {\n\
               timezone: \"America/Bogota\"\n\
               allow: [ { days: Mon..Fri, hours: 9..18 } ]\n\
               on_outside: skip\n\
             }\n\
             daemon Scheduler {\n\
               window: BusinessHours\n\
               requires: [flow.execute]\n\
               listen \"cron:*/5 * * * *\" as tick { run Send() }\n\
             }",
        );
        let daemon = ir.daemons.iter().find(|d| d.name == "Scheduler").unwrap();
        assert_eq!(daemon.window_ref, "BusinessHours");
        let w = bound_window(&ir, daemon).expect("window resolves");
        assert_eq!(w.name, "BusinessHours");
        assert_eq!(w.timezone, "America/Bogota");
        assert_eq!(w.on_outside, "skip");

        // A daemon with no `window:` resolves to None (unguarded — pre-§71).
        let unguarded = ir_with_daemon(
            "flow Send() -> Unit { step S { ask: \"x\" output: Unit } }\n\
             daemon Plain {\n\
               listen \"cron:*/5 * * * *\" as tick { run Send() }\n\
             }",
        );
        let d2 = unguarded.daemons.iter().find(|d| d.name == "Plain").unwrap();
        assert!(bound_window(&unguarded, d2).is_none());
    }

    #[test]
    fn budget_gate_builds_from_a_parsed_daemon_and_enforces() {
        // §Fase 72.c — parse → IR → BudgetGate, end to end. A daemon whose budget
        // allows 1 TelnyxCall/hour: the first emission is granted, the second is
        // denied under the (default) `block` policy.
        let ir = ir_with_daemon(
            "tool TelnyxCall { provider: telnyx timeout: 5s }\n\
             flow SendBatch() -> Unit { step S { ask: \"x\" output: Unit } }\n\
             daemon OutboundScheduler {\n\
               requires: [flow.execute]\n\
               budget {\n\
                 max: 1 per hour on Tool(TelnyxCall)\n\
                 on_exhausted: block\n\
               }\n\
               listen \"cron:*/5 * * * *\" as t { run SendBatch() }\n\
             }",
        );
        let daemon = ir.daemons.iter().find(|d| d.name == "OutboundScheduler").unwrap();
        let budget = daemon.budget.as_ref().expect("budget lowered onto the daemon");
        let now: chrono::DateTime<chrono::Utc> = "2026-06-29T00:00:00Z".parse().unwrap();
        let mut gate = crate::runtime::budget_kernel::BudgetGate::from_ir(budget, &daemon.name, now);

        use crate::runtime::budget_kernel::GateDecision;
        assert_eq!(gate.gate("TelnyxCall", now), GateDecision::Allow);
        match gate.gate("TelnyxCall", now) {
            GateDecision::Deny { on_exhausted, .. } => assert_eq!(on_exhausted, "block"),
            other => panic!("expected Deny, got {other:?}"),
        }
        // A tool with no quota is never gated.
        assert_eq!(gate.gate("SomeOtherTool", now), GateDecision::Allow);
    }
}
