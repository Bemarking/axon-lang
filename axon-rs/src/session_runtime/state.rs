//! The operational state machine for a single session-typed dialogue.
//!
//! §Fase 41.d. A [`SessionRuntime`] is the runtime witness of a §41.a
//! `SessionType`: it carries a **cursor** (the residual type after every
//! step so far) and a [`CreditWindow`] (the dynamic counterpart of the
//! §41.c index `!ⁿA.S`), and exposes one method per operational rule —
//! `try_send`, `try_recv`, `try_select`, `try_offer`, `try_end`. Each
//! method enforces the static discipline *defence-in-depth*: a violation
//! (wrong-kind frame, wrong payload, exhausted credit, post-`end` traffic)
//! returns a [`ProtocolError`] and leaves the cursor unchanged. The
//! caller's contract is to close the transport on first error.
//!
//! Recursion is handled by [`SessionType::unfold_head`] — the cursor is
//! kept in "head-unfolded" form: never a leading `Rec` or `Var`. This
//! keeps the rule for every action a single pattern match on the cursor.
//!
//! The runtime is **transport-agnostic** — it knows nothing about
//! WebSockets, JSON, or `tokio`. The [`crate::session_runtime::ws`]
//! module is one carrier; the runtime would slot identically over QUIC,
//! a TCP stream, or an in-process channel.

use std::collections::BTreeMap;

use axon_frontend::session::{Payload, SessionType};

use super::error::ProtocolError;

/// Dynamic counterpart of the §41.c credit index `!ⁿA.S`. Tracks the
/// number of in-flight sends the producer is currently allowed; a `send`
/// decrements `available`, a `recv` refills it (capped at `budget`,
/// standard TCP-window semantics). The static analysis
/// (`SessionType::credit_analyse`) has already verified the protocol is
/// conformant under this budget — this is the runtime safety net for an
/// off-spec peer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CreditWindow {
    /// Maximum credit the producer may hold at any one time (`k` in the
    /// `socket { backpressure: credit(k) }` annotation).
    pub budget: u64,
    /// Current available credit. Invariant: `0 ≤ available ≤ budget`.
    pub available: u64,
}

impl CreditWindow {
    /// Open a fresh window with the full budget available.
    pub fn new(budget: u64) -> Self {
        Self { budget, available: budget }
    }
    /// Try to consume one credit; returns the remaining count, or `None`
    /// if exhausted (the runtime witness of the "no rule at n=0" axiom).
    fn try_consume(&mut self) -> Option<u64> {
        if self.available == 0 {
            None
        } else {
            self.available -= 1;
            Some(self.available)
        }
    }
    /// Refill one credit, capped at the budget. Cannot fail.
    fn refill(&mut self) {
        if self.available < self.budget {
            self.available += 1;
        }
    }
}

/// The session-type runtime cursor + credit window.
///
/// Held by **each** side of a connection — the server runtime is
/// initialised with the server-role type, the client with the dual. Every
/// transition is local: there is no cross-process synchronisation here;
/// the carrier delivers frames in order and the two cursors stay in lock
/// step because they were initialised from a duality-checked pair.
#[derive(Debug, Clone)]
pub struct SessionRuntime {
    /// The original session type (the protocol "schema"). Kept so the
    /// runtime can re-report it on errors and so the cursor's invariants
    /// are documented at the type level (the cursor is always reachable
    /// from `schema` along the trace so far).
    schema: SessionType,
    /// The residual type — the unfinished part of the protocol. Always
    /// head-unfolded (never a leading `Rec` or `Var`).
    cursor: SessionType,
    /// The dynamic credit window, or `None` for the unbounded fragment
    /// (no `backpressure` annotation in the socket).
    credit: Option<CreditWindow>,
}

impl SessionRuntime {
    /// Create a runtime for the given role's session type. `budget`
    /// mirrors the socket's `credit(k)`; pass `None` for the unbounded
    /// fragment (statically equivalent to omitting `backpressure:`).
    pub fn new(schema: SessionType, budget: Option<u64>) -> Self {
        let cursor = schema.unfold_head();
        Self {
            schema,
            cursor,
            credit: budget.map(CreditWindow::new),
        }
    }

    /// The original session type — useful for error messages and logs.
    pub fn schema(&self) -> &SessionType {
        &self.schema
    }

    /// The current residual cursor — always head-unfolded.
    pub fn cursor(&self) -> &SessionType {
        &self.cursor
    }

    /// The dynamic credit window snapshot (or `None` for the unbounded
    /// fragment).
    pub fn credit(&self) -> Option<CreditWindow> {
        self.credit
    }

    /// `true` once the cursor reaches `end` — both sides should now close
    /// the carrier cleanly. The runtime rejects further actions after
    /// this point with [`ProtocolError::AlreadyComplete`].
    pub fn is_complete(&self) -> bool {
        matches!(self.cursor, SessionType::End)
    }

    // ── Operational rules ──────────────────────────────────────────────

    /// Producer step `!A.S → S`. Succeeds iff:
    /// 1. the cursor is `Send { payload, … }` with `payload == got`;
    /// 2. the credit window (if any) has `available > 0` — otherwise the
    ///    §41.c "no rule at n=0" axiom fires.
    /// On success the cursor advances (unfolded) and one credit is
    /// consumed (when the window is present).
    pub fn try_send(&mut self, got: &str) -> Result<(), ProtocolError> {
        if self.is_complete() {
            return Err(ProtocolError::AlreadyComplete { frame_kind: "send" });
        }
        let (expected_payload, cont) = match &self.cursor {
            SessionType::Send { payload, cont, .. } => (payload.clone(), cont.clone()),
            other => {
                return Err(ProtocolError::UnexpectedFrame {
                    cursor_kind: kind_of(other),
                    frame_kind: "send",
                });
            }
        };
        let got_payload = Payload::new(got);
        if expected_payload != got_payload {
            return Err(ProtocolError::PayloadMismatch {
                expected: expected_payload,
                got: got_payload,
            });
        }
        // Credit decrement — the dynamic witness of `!ⁿA.S, n > 0`.
        if let Some(w) = self.credit.as_mut() {
            if w.try_consume().is_none() {
                return Err(ProtocolError::CreditExhausted {
                    payload: expected_payload,
                    budget: w.budget,
                });
            }
        }
        self.advance(*cont);
        Ok(())
    }

    /// Consumer step `?A.S → S`. The peer just produced an `!A.S` frame.
    /// Symmetric to [`try_send`] — payload must match, the cursor advances,
    /// and one credit is refilled (if a window is present).
    pub fn try_recv(&mut self, got: &str) -> Result<(), ProtocolError> {
        if self.is_complete() {
            return Err(ProtocolError::AlreadyComplete { frame_kind: "send" });
        }
        let (expected_payload, cont) = match &self.cursor {
            SessionType::Recv { payload, cont, .. } => (payload.clone(), cont.clone()),
            other => {
                return Err(ProtocolError::UnexpectedFrame {
                    cursor_kind: kind_of(other),
                    frame_kind: "send",
                });
            }
        };
        let got_payload = Payload::new(got);
        if expected_payload != got_payload {
            return Err(ProtocolError::PayloadMismatch {
                expected: expected_payload,
                got: got_payload,
            });
        }
        // Refill — the peer just delivered, the in-flight count drops by 1.
        if let Some(w) = self.credit.as_mut() {
            w.refill();
        }
        self.advance(*cont);
        Ok(())
    }

    /// Internal choice (`⊕`) — *we* select the labelled arm. Cursor must
    /// be `Select { arms }` containing `label`; on success the cursor
    /// advances into that arm's continuation.
    pub fn try_select(&mut self, label: &str) -> Result<(), ProtocolError> {
        self.advance_into_arm(label, true)
    }

    /// External choice (`&`) — the *peer* selected this label; we accept.
    /// Cursor must be `Branch { arms }` containing `label`.
    pub fn try_offer(&mut self, label: &str) -> Result<(), ProtocolError> {
        self.advance_into_arm(label, false)
    }

    /// `end` step — terminates the dialogue. Cursor must already be
    /// `End`; otherwise the peer is signalling termination mid-protocol.
    pub fn try_end(&mut self) -> Result<(), ProtocolError> {
        match &self.cursor {
            SessionType::End => Ok(()),
            other => Err(ProtocolError::UnexpectedFrame {
                cursor_kind: kind_of(other),
                frame_kind: "end",
            }),
        }
    }

    // ── Internal helpers ───────────────────────────────────────────────

    /// Set the cursor to the head-unfolded form of `next`. This is the
    /// single invariant maintained across every step — after any advance
    /// the cursor never has a leading `Rec` (and never a leading bare
    /// `Var` on a *closed* type, which 41.a/b/c statically guarantee).
    fn advance(&mut self, next: SessionType) {
        self.cursor = next.unfold_head();
    }

    fn advance_into_arm(&mut self, label: &str, internal: bool) -> Result<(), ProtocolError> {
        if self.is_complete() {
            return Err(ProtocolError::AlreadyComplete {
                frame_kind: if internal { "select" } else { "branch" },
            });
        }
        let arms = match (&self.cursor, internal) {
            (SessionType::Select(m), true) => m.clone(),
            (SessionType::Branch(m), false) => m.clone(),
            (other, _) => {
                return Err(ProtocolError::UnexpectedFrame {
                    cursor_kind: kind_of(other),
                    frame_kind: if internal { "select" } else { "select" },
                });
            }
        };
        match arms.get(label) {
            Some(cont) => {
                let cont = cont.clone();
                self.advance(cont);
                Ok(())
            }
            None => Err(ProtocolError::UnknownLabel {
                label: label.to_string(),
                expected: keys_of(&arms),
            }),
        }
    }
}

/// Symbolic name of the cursor's head constructor — used to enrich error
/// messages without leaking the full type body.
fn kind_of(t: &SessionType) -> &'static str {
    match t {
        SessionType::End => "end",
        SessionType::Send { .. } => "send",
        SessionType::Recv { .. } => "recv",
        SessionType::Select(_) => "select",
        SessionType::Branch(_) => "branch",
        SessionType::Rec(_, _) => "rec", // never reached on a head-unfolded cursor
        SessionType::Var(_) => "var",    // ditto, on closed types
    }
}

fn keys_of(m: &BTreeMap<String, SessionType>) -> Vec<String> {
    m.keys().cloned().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── CreditWindow primitives ─────────────────────────────────────────

    #[test]
    fn credit_window_decrements_and_refills_within_budget() {
        let mut w = CreditWindow::new(2);
        assert_eq!(w.try_consume(), Some(1));
        assert_eq!(w.try_consume(), Some(0));
        assert!(w.try_consume().is_none()); // exhausted
        w.refill();
        assert_eq!(w.available, 1);
        w.refill();
        assert_eq!(w.available, 2);
        // Refill beyond budget is a no-op (capped at k).
        w.refill();
        assert_eq!(w.available, 2);
    }

    // ── try_send / try_recv on linear types ─────────────────────────────

    #[test]
    fn try_send_advances_on_matching_payload() {
        // Type: !Msg.end
        let schema = SessionType::send("Msg", SessionType::End);
        let mut r = SessionRuntime::new(schema, None);
        r.try_send("Msg").expect("step");
        assert!(r.is_complete());
    }

    #[test]
    fn try_send_rejects_wrong_payload() {
        let schema = SessionType::send("Msg", SessionType::End);
        let mut r = SessionRuntime::new(schema, None);
        match r.try_send("WrongType") {
            Err(ProtocolError::PayloadMismatch { expected, got }) => {
                assert_eq!(expected, Payload::new("Msg"));
                assert_eq!(got, Payload::new("WrongType"));
            }
            other => panic!("expected PayloadMismatch, got {other:?}"),
        }
        // The cursor is unchanged on error.
        assert!(matches!(r.cursor(), SessionType::Send { .. }));
    }

    #[test]
    fn try_recv_rejects_when_cursor_is_send() {
        let schema = SessionType::send("Msg", SessionType::End);
        let mut r = SessionRuntime::new(schema, None);
        match r.try_recv("Msg") {
            Err(ProtocolError::UnexpectedFrame { cursor_kind: "send", .. }) => {}
            other => panic!("expected UnexpectedFrame(send→send), got {other:?}"),
        }
    }

    // ── Credit accounting ───────────────────────────────────────────────

    #[test]
    fn credit_exhaustion_blocks_send_at_zero() {
        // Type: !A.!B.end with budget = 1
        let schema = SessionType::send("A", SessionType::send("B", SessionType::End));
        let mut r = SessionRuntime::new(schema, Some(1));
        // First send consumes the credit (budget→0).
        r.try_send("A").expect("first send");
        assert_eq!(r.credit().unwrap().available, 0);
        // Second send hits the n=0 axiom.
        match r.try_send("B") {
            Err(ProtocolError::CreditExhausted { payload, budget: 1 }) => {
                assert_eq!(payload, Payload::new("B"));
            }
            other => panic!("expected CreditExhausted, got {other:?}"),
        }
    }

    #[test]
    fn recv_refills_credit_capped_at_budget() {
        // Type: !A.?Ack.!B.end with budget = 1 (sustainable: each send
        // is followed by a refill).
        let schema = SessionType::send(
            "A",
            SessionType::recv("Ack", SessionType::send("B", SessionType::End)),
        );
        let mut r = SessionRuntime::new(schema, Some(1));
        r.try_send("A").expect("send A");
        assert_eq!(r.credit().unwrap().available, 0);
        r.try_recv("Ack").expect("recv Ack refills");
        assert_eq!(r.credit().unwrap().available, 1);
        r.try_send("B").expect("send B uses refilled credit");
        assert!(r.is_complete());
    }

    // ── select / branch / recursion ─────────────────────────────────────

    #[test]
    fn select_advances_into_named_arm() {
        let schema = SessionType::select([
            ("ask".into(), SessionType::send("Q", SessionType::End)),
            ("quit".into(), SessionType::End),
        ]);
        let mut r = SessionRuntime::new(schema, None);
        r.try_select("ask").expect("select ask");
        assert!(matches!(r.cursor(), SessionType::Send { .. }));
        r.try_send("Q").expect("send Q");
        assert!(r.is_complete());
    }

    #[test]
    fn select_rejects_unknown_label() {
        let schema = SessionType::select([
            ("ask".into(), SessionType::End),
            ("quit".into(), SessionType::End),
        ]);
        let mut r = SessionRuntime::new(schema, None);
        match r.try_select("nope") {
            Err(ProtocolError::UnknownLabel { label, expected }) => {
                assert_eq!(label, "nope");
                assert_eq!(expected, vec!["ask".to_string(), "quit".to_string()]);
            }
            other => panic!("expected UnknownLabel, got {other:?}"),
        }
    }

    #[test]
    fn offer_advances_into_peer_selected_arm() {
        let schema = SessionType::branch([
            ("ack".into(), SessionType::End),
            ("err".into(), SessionType::End),
        ]);
        let mut r = SessionRuntime::new(schema, None);
        r.try_offer("ack").expect("offer ack");
        assert!(r.is_complete());
    }

    #[test]
    fn recursion_unfolds_one_step_at_a_time() {
        // rec X. !A.?Ack.X — should support unbounded iteration under
        // budget=1 (Δ = 0 per recurring iteration).
        let schema = SessionType::rec(
            "X",
            SessionType::send("A", SessionType::recv("Ack", SessionType::var("X"))),
        );
        let mut r = SessionRuntime::new(schema, Some(1));
        for _ in 0..5 {
            r.try_send("A").expect("send");
            r.try_recv("Ack").expect("recv");
        }
        // The cursor is still at the start-of-iteration shape (unfolded
        // form of `Rec(X, …)`), which is `!A.?Ack.<unfolded rec>`.
        assert!(matches!(r.cursor(), SessionType::Send { .. }));
        // Definitely not at `end` — the dialogue is unbounded.
        assert!(!r.is_complete());
    }

    // ── Post-end safety net ─────────────────────────────────────────────

    #[test]
    fn post_end_traffic_is_rejected() {
        let mut r = SessionRuntime::new(SessionType::End, None);
        r.try_end().expect("end on End is OK");
        match r.try_send("X") {
            Err(ProtocolError::AlreadyComplete { frame_kind: "send" }) => {}
            other => panic!("expected AlreadyComplete, got {other:?}"),
        }
    }

    // ── A realistic chat dialogue runs to completion ────────────────────

    #[test]
    fn realistic_chat_dialogue_runs_to_completion() {
        // The 41.a sample type: rec X. +{ ask: !Utterance. &{ token:
        // ?Token.X, done: end }, cancel: end }
        let schema = SessionType::rec(
            "X",
            SessionType::select([
                (
                    "ask".into(),
                    SessionType::send(
                        "Utterance",
                        SessionType::branch([
                            ("token".into(), SessionType::recv("Token", SessionType::var("X"))),
                            ("done".into(), SessionType::End),
                        ]),
                    ),
                ),
                ("cancel".into(), SessionType::End),
            ]),
        );
        let mut client = SessionRuntime::new(schema, Some(4));
        // Iter 1: ask → send Utt → server says token → recv Token → loop.
        client.try_select("ask").unwrap();
        client.try_send("Utterance").unwrap();
        client.try_offer("token").unwrap();
        client.try_recv("Token").unwrap();
        // Iter 2: ask → send Utt → server says done.
        client.try_select("ask").unwrap();
        client.try_send("Utterance").unwrap();
        client.try_offer("done").unwrap();
        client.try_end().unwrap();
        assert!(client.is_complete());
    }
}
