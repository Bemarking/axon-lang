//! Session types — the algebra of typed bidirectional dialogue.
//!
//! §Fase 41.a — *WebSocket as a Cognitive Primitive*. This module is the pure
//! mathematical core of the paper (`docs/paper_websocket_cognitive_primitive.md`):
//! the session-type grammar (§3.1), the **duality** involution `(·)⊥` (§3.2),
//! the **regular-coinductive equality** for recursive (`μ`) types, and the
//! **connection law** — a connection with endpoints typed `S` and `T` is
//! well-formed iff `T ≡ S⊥`. Grounded in Caires & Pfenning's Curry–Howard
//! correspondence (session types ARE intuitionistic linear-logic propositions),
//! it is the static guarantee RFC 6455 lacks: *what one end sends, the other
//! expects* — making a dialogue **deadlock-free and protocol-conformant by
//! construction**, not by per-message runtime validation.
//!
//! This is the pure algebra only: no parser/AST (Fase 41.b), no credit-refined
//! backpressure index (41.c), no runtime (41.d), no multiparty projection
//! (41.h). The payload carried by `send`/`recv` is an opaque [`Payload`]
//! (a canonical type name); 41.b binds it to the real AST value types — the
//! duality + equality algebra here depends only on payload *equality*, never on
//! payload structure, so it is decoupled by construction.

use std::collections::BTreeMap;
use std::fmt;

/// The value type carried by a `send`/`recv`. Opaque at this layer (a canonical
/// type name); Fase 41.b replaces it with the real AST value type. Duality and
/// equality treat it nominally — only `Payload == Payload` matters.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Payload(pub String);

impl Payload {
    pub fn new(name: impl Into<String>) -> Self {
        Payload(name.into())
    }
}

impl fmt::Display for Payload {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// A session type — the protocol of one endpoint of a connection (§3.1 of the
/// paper). `Select`/`Branch` carry their labelled continuations in a `BTreeMap`
/// so the label set is canonically ordered (deterministic duality + equality).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum SessionType {
    /// `end` — the dialogue is complete.
    End,
    /// `!A.S` — send a value of type `A`, then behave as `S`.
    Send(Payload, Box<SessionType>),
    /// `?A.S` — receive a value of type `A`, then behave as `S`.
    Recv(Payload, Box<SessionType>),
    /// `⊕{ℓᵢ:Sᵢ}` — internal choice: this endpoint *selects* a label.
    Select(BTreeMap<String, SessionType>),
    /// `&{ℓᵢ:Sᵢ}` — external choice: this endpoint *offers* the branches.
    Branch(BTreeMap<String, SessionType>),
    /// `μX.S` — recursive session (equirecursive: `μX.S ≡ S[μX.S/X]`).
    Rec(String, Box<SessionType>),
    /// `X` — a recursion variable (bound by an enclosing `Rec`).
    Var(String),
}

impl SessionType {
    // ── Smart constructors (ergonomic + keep call sites readable) ──────────

    pub fn send(payload: impl Into<String>, then: SessionType) -> Self {
        SessionType::Send(Payload::new(payload), Box::new(then))
    }
    pub fn recv(payload: impl Into<String>, then: SessionType) -> Self {
        SessionType::Recv(Payload::new(payload), Box::new(then))
    }
    pub fn select(branches: impl IntoIterator<Item = (String, SessionType)>) -> Self {
        SessionType::Select(branches.into_iter().collect())
    }
    pub fn branch(branches: impl IntoIterator<Item = (String, SessionType)>) -> Self {
        SessionType::Branch(branches.into_iter().collect())
    }
    pub fn rec(var: impl Into<String>, body: SessionType) -> Self {
        SessionType::Rec(var.into(), Box::new(body))
    }
    pub fn var(name: impl Into<String>) -> Self {
        SessionType::Var(name.into())
    }

    // ── Duality (§3.2): the involution that swaps the two sides ────────────

    /// The dual `S⊥`: swaps `send`↔`recv` and `select`↔`branch`, recursing into
    /// continuations; `end`, `Rec` binders and `Var`s are preserved. Payloads
    /// are **unchanged** (`(!A.S)⊥ = ?A.S⊥` — same `A`, opposite direction).
    pub fn dual(&self) -> SessionType {
        match self {
            SessionType::End => SessionType::End,
            SessionType::Send(a, k) => SessionType::Recv(a.clone(), Box::new(k.dual())),
            SessionType::Recv(a, k) => SessionType::Send(a.clone(), Box::new(k.dual())),
            SessionType::Select(m) => SessionType::Branch(dual_map(m)),
            SessionType::Branch(m) => SessionType::Select(dual_map(m)),
            SessionType::Rec(x, b) => SessionType::Rec(x.clone(), Box::new(b.dual())),
            SessionType::Var(x) => SessionType::Var(x.clone()),
        }
    }

    // ── Equirecursive unfolding + capture-stopping substitution ────────────

    /// Substitute the free variable `var` by `repl`. Stops at a shadowing
    /// `Rec(var, …)` (the inner binder re-captures the name).
    fn subst(&self, var: &str, repl: &SessionType) -> SessionType {
        match self {
            SessionType::End => SessionType::End,
            SessionType::Send(a, k) => SessionType::Send(a.clone(), Box::new(k.subst(var, repl))),
            SessionType::Recv(a, k) => SessionType::Recv(a.clone(), Box::new(k.subst(var, repl))),
            SessionType::Select(m) => SessionType::Select(subst_map(m, var, repl)),
            SessionType::Branch(m) => SessionType::Branch(subst_map(m, var, repl)),
            SessionType::Rec(x, b) => {
                if x == var {
                    self.clone() // shadowed — leave the inner Rec untouched
                } else {
                    SessionType::Rec(x.clone(), Box::new(b.subst(var, repl)))
                }
            }
            SessionType::Var(x) => {
                if x == var {
                    repl.clone()
                } else {
                    self.clone()
                }
            }
        }
    }

    /// Unfold every *leading* `Rec` so the head constructor is exposed:
    /// `μX.S ↦ S[μX.S/X]`, repeated. Terminates for **contractive** types
    /// (a guard appears under each `Rec` before the variable recurs).
    fn unfold_head(&self) -> SessionType {
        let mut t = self.clone();
        while let SessionType::Rec(x, b) = t {
            let whole = SessionType::Rec(x.clone(), b.clone());
            t = b.subst(&x, &whole);
        }
        t
    }

    // ── Regular-coinductive equality ──────────────────────────────────────

    /// Equirecursive equality: `S ≡ T` iff their infinite unfoldings coincide.
    /// Decided by the standard coinductive algorithm — assume the pair equal,
    /// unfold leading `Rec`s, compare heads, recurse; a re-encountered pair is
    /// discharged by the assumption (the greatest fixed point). Terminates
    /// because a regular type has finitely many distinct sub-pairs.
    pub fn equiv(&self, other: &SessionType) -> bool {
        let mut assumed: Vec<(SessionType, SessionType)> = Vec::new();
        equiv_inner(self, other, &mut assumed)
    }

    /// The **connection law** (§3.2): a connection whose two endpoints are typed
    /// `self` and `peer` is well-formed iff `peer ≡ self⊥`. Symmetric up to
    /// involutivity (`(S⊥)⊥ ≡ S`).
    pub fn is_dual_to(&self, peer: &SessionType) -> bool {
        peer.equiv(&self.dual())
    }
}

fn dual_map(m: &BTreeMap<String, SessionType>) -> BTreeMap<String, SessionType> {
    m.iter().map(|(l, s)| (l.clone(), s.dual())).collect()
}

fn subst_map(m: &BTreeMap<String, SessionType>, var: &str, repl: &SessionType) -> BTreeMap<String, SessionType> {
    m.iter().map(|(l, s)| (l.clone(), s.subst(var, repl))).collect()
}

fn equiv_inner(s: &SessionType, t: &SessionType, assumed: &mut Vec<(SessionType, SessionType)>) -> bool {
    // Coinduction: a pair we are already proving equal is taken as equal.
    if assumed.iter().any(|(x, y)| x == s && y == t) {
        return true;
    }
    assumed.push((s.clone(), t.clone()));

    match (s.unfold_head(), t.unfold_head()) {
        (SessionType::End, SessionType::End) => true,
        (SessionType::Send(a, sk), SessionType::Send(b, tk)) => a == b && equiv_inner(&sk, &tk, assumed),
        (SessionType::Recv(a, sk), SessionType::Recv(b, tk)) => a == b && equiv_inner(&sk, &tk, assumed),
        (SessionType::Select(m1), SessionType::Select(m2)) => equiv_maps(&m1, &m2, assumed),
        (SessionType::Branch(m1), SessionType::Branch(m2)) => equiv_maps(&m1, &m2, assumed),
        // A bare `Var` survives unfolding only if it is free (open type); compare
        // nominally. Closed, contractive types never reach this with a head Var.
        (SessionType::Var(x), SessionType::Var(y)) => x == y,
        _ => false,
    }
}

fn equiv_maps(
    m1: &BTreeMap<String, SessionType>,
    m2: &BTreeMap<String, SessionType>,
    assumed: &mut Vec<(SessionType, SessionType)>,
) -> bool {
    // Same label set, and equal continuations label-by-label.
    if m1.len() != m2.len() || !m1.keys().all(|l| m2.contains_key(l)) {
        return false;
    }
    m1.iter().all(|(l, s1)| equiv_inner(s1, &m2[l], assumed))
}

impl fmt::Display for SessionType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SessionType::End => f.write_str("end"),
            SessionType::Send(a, k) => write!(f, "!{a}.{k}"),
            SessionType::Recv(a, k) => write!(f, "?{a}.{k}"),
            SessionType::Select(m) => write_choice(f, "+", m),
            SessionType::Branch(m) => write_choice(f, "&", m),
            SessionType::Rec(x, b) => write!(f, "rec {x}.{b}"),
            SessionType::Var(x) => f.write_str(x),
        }
    }
}

fn write_choice(f: &mut fmt::Formatter<'_>, sym: &str, m: &BTreeMap<String, SessionType>) -> fmt::Result {
    write!(f, "{sym}{{")?;
    for (i, (l, s)) in m.iter().enumerate() {
        if i > 0 {
            f.write_str(", ")?;
        }
        write!(f, "{l}: {s}")?;
    }
    f.write_str("}")
}

#[cfg(test)]
mod tests {
    use super::*;

    // Helpers for readable session-type literals.
    fn sel(pairs: &[(&str, SessionType)]) -> SessionType {
        SessionType::select(pairs.iter().map(|(l, s)| (l.to_string(), s.clone())))
    }
    fn brn(pairs: &[(&str, SessionType)]) -> SessionType {
        SessionType::branch(pairs.iter().map(|(l, s)| (l.to_string(), s.clone())))
    }

    // ── Duality basics ─────────────────────────────────────────────────────

    #[test]
    fn dual_swaps_send_recv_and_keeps_payload() {
        let s = SessionType::send("Int", SessionType::End);
        assert_eq!(s.dual(), SessionType::recv("Int", SessionType::End));
        // The payload (`Int`) is unchanged — only the direction flips.
        assert_eq!(SessionType::recv("Int", SessionType::End).dual(), s);
    }

    #[test]
    fn dual_swaps_select_branch() {
        let s = sel(&[("a", SessionType::End), ("b", SessionType::send("T", SessionType::End))]);
        let d = s.dual();
        assert!(matches!(d, SessionType::Branch(_)));
        // …and the continuations are dualised too.
        assert_eq!(d, brn(&[("a", SessionType::End), ("b", SessionType::recv("T", SessionType::End))]));
    }

    // ── Involutivity: (S⊥)⊥ ≡ S — the cornerstone of the connection law ─────

    #[test]
    fn duality_is_an_involution() {
        let samples = vec![
            SessionType::End,
            SessionType::send("A", SessionType::recv("B", SessionType::End)),
            sel(&[("x", SessionType::End), ("y", SessionType::recv("Q", SessionType::End))]),
            // recursive: rec X. !Msg. &{ more: X, done: end }
            SessionType::rec(
                "X",
                SessionType::send("Msg", brn(&[("more", SessionType::var("X")), ("done", SessionType::End)])),
            ),
        ];
        for s in samples {
            assert!(s.dual().dual().equiv(&s), "(S⊥)⊥ ≢ S for {s}");
        }
    }

    // ── The connection law: S is dual to S⊥, and only to S⊥ ─────────────────

    #[test]
    fn connection_law_holds_for_dual_and_fails_otherwise() {
        let s = SessionType::send("Q", SessionType::recv("R", SessionType::End));
        assert!(s.is_dual_to(&s.dual()), "a session must be dual to its own dual");
        // Not dual to itself (it sends where the peer must receive).
        assert!(!s.is_dual_to(&s));
        // Not dual to a peer with a mismatched payload.
        let wrong = SessionType::recv("Q", SessionType::send("WRONG", SessionType::End));
        assert!(!s.is_dual_to(&wrong));
    }

    // ── Regular-coinductive equality: fold/unfold + α-renaming ──────────────

    #[test]
    fn equirecursive_fold_unfold_equality() {
        // μX. !A.X  ≡  !A.(μX. !A.X)   — one unfolding is equal.
        let folded = SessionType::rec("X", SessionType::send("A", SessionType::var("X")));
        let unfolded = SessionType::send("A", folded.clone());
        assert!(folded.equiv(&unfolded));
        assert!(unfolded.equiv(&folded));
    }

    #[test]
    fn equality_is_insensitive_to_bound_variable_name() {
        let x = SessionType::rec("X", SessionType::send("A", SessionType::var("X")));
        let y = SessionType::rec("Y", SessionType::send("A", SessionType::var("Y")));
        assert!(x.equiv(&y), "α-equivalent recursive sessions must be equal");
    }

    #[test]
    fn equality_reflexive_and_rejects_real_differences() {
        let s = sel(&[("a", SessionType::send("T", SessionType::End)), ("b", SessionType::End)]);
        assert!(s.equiv(&s));
        // Direction differs.
        assert!(!SessionType::send("T", SessionType::End).equiv(&SessionType::recv("T", SessionType::End)));
        // Payload differs.
        assert!(!SessionType::send("A", SessionType::End).equiv(&SessionType::send("B", SessionType::End)));
        // Label set differs.
        let s2 = sel(&[("a", SessionType::send("T", SessionType::End)), ("c", SessionType::End)]);
        assert!(!s.equiv(&s2));
        // Choice kind differs (select vs branch).
        assert!(!sel(&[("a", SessionType::End)]).equiv(&brn(&[("a", SessionType::End)])));
    }

    #[test]
    fn connection_law_holds_for_recursive_dialogue() {
        // A realistic chat dialogue: rec X. +{ ask: !Utterance. &{ token: ?Token.X, done: end }, cancel: end }
        let client = SessionType::rec(
            "X",
            sel(&[
                (
                    "ask",
                    SessionType::send(
                        "Utterance",
                        brn(&[("token", SessionType::recv("Token", SessionType::var("X"))), ("done", SessionType::End)]),
                    ),
                ),
                ("cancel", SessionType::End),
            ]),
        );
        // The server endpoint is the structural dual; the law must accept it,
        // and reject the (non-dual) identical copy.
        assert!(client.is_dual_to(&client.dual()));
        assert!(!client.is_dual_to(&client));
        // equiv terminates on this recursive type (no stack blow-up).
        assert!(client.equiv(&client));
    }

    #[test]
    fn display_is_readable() {
        let s = SessionType::send("Int", SessionType::recv("Bool", SessionType::End));
        assert_eq!(s.to_string(), "!Int.?Bool.end");
        assert_eq!(SessionType::rec("X", SessionType::var("X")).to_string(), "rec X.X");
    }
}
