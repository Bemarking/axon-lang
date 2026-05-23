---
title: "Plan vivo: Fase 41 — WebSocket as a Cognitive Primitive (session-typed bidirectional dialogue)"
status: 📝 PROPOSED — research grounded (see docs/paper_websocket_cognitive_primitive.md); awaiting founder "procede con 41.a". The bidirectional dual of Fase 33 (SSE as a cognitive primitive). Elevates RFC 6455 from an untyped 3-frame channel to a session-typed dialogue: the connection carries a session type (a linear-logic proposition), is well-formed iff endpoints are dual ($\bar S = S^{\perp}$) → deadlock-free + protocol-conformant by construction, with backpressure as a credit-refined index decidable in Presburger arithmetic.
owner: AXON Compiler + Runtime + Enterprise Team
created: 2026-05-22
target: |
  axon-lang **v2.3.0** — MINOR (additive new language primitive: the `socket`
  block + session-type checker in axon-frontend + the typed-WS runtime in
  axon-rs over the Fase 13 π-channels). Backwards-compatible.
  axon-enterprise **catch-up** — the multi-tenant, audited WebSocket SURFACE on
  the enterprise server (axum/tokio WS endpoint + RLS + audit chain + shield),
  which is what lets the demanding adopter (Kivi) collapse to a SINGLE image.
depends_on: |
  Fase 13 SHIPPED (Mobile Typed Channels — π-calculus typed channels + capability
  extrusion; the realization substrate for endpoints).
  Fase 33 SHIPPED (SSE as a cognitive primitive — the single-polarity fragment
  this generalizes; S_SSE = Π↓(S_WS)).
  Fase 40 CLOSED (axon-enterprise 100% Rust/C, v2.0.1; cognitive_states sealed
  snapshots for reconnection; the enterprise axum server + audit chain + RLS).
charter_class: |
  LANGUAGE PRIMITIVE (axon-for-axon). The primitive is OSS axon-lang (the type
  discipline + runtime); the enterprise exposes it multi-tenant/audited. Driven
  by a demanding production adopter (a large SaaS agent: skills, multiple chat
  types, websocket, webhooks, multi-tool, microservices) whose real need defines
  the primitive — the adopter makes the language better.
---

## Why Fase 41 exists

A demanding Enterprise adopter (a large multi-skill SaaS agent) wants to collapse
its deployment to a **single image** (the axon-enterprise binary, which already
runs flows + 7 LLM backends + SSE + dynamic REST + the control plane). The one
surface the Rust enterprise server does **not** yet expose is **WebSocket** (the
old Python image bound port 8001 for it; the v2.0.x image exposes only 8080 HTTP).
Rather than bolt on a raw socket, Fase 41 does the axon thing: **re-found
WebSocket as a cognitive primitive**, grounded on a top-tier paper across the four
pillars (MATHEMATICS · LOGIC · PHILOSOPHY · COMPUTATION). See
[docs/paper_websocket_cognitive_primitive.md](../paper_websocket_cognitive_primitive.md).

The gap it closes (measured): RFC 6455 frames only `text`/`binary`/`control` and
delegates protocol meaning to the application; the industry types **messages**
(Zod/tRPC/JSON-Schema), never the **conversation**; and the reference stacks
concede the interface "does not support backpressure." Fase 41 types the
conversation and makes backpressure a decidable type-level invariant.

## The two-question gate (founder directive)

1. **Market standard or superior?** **Superior.** State of the art types individual
   messages (tRPC/Zod discriminated unions) and handles backpressure operationally
   (manual pause/resume). Fase 41 types the **protocol-as-session** (duality-checked
   ⇒ deadlock-free + conformant by construction, after Caires–Pfenning /
   Honda–Yoshida–Carbone) and makes **backpressure a credit-refined linear index**
   (decidable in Presburger, after Rast). No deployed WebSocket stack does this.
2. **Minimum to run, or robust for large adopters?** **Robust.** Multi-tenant RLS
   isolation + per-utterance audit-chain provenance + shield/legal-basis on every
   move + typed reconnection via sealed `cognitive_states` + multiparty projection
   for n-agent (skills/tools) topologies. Deferred (enumerated): horizontal
   fan-out across nodes (Redis/relay) and the browser-side client codegen.

## Decisions

- **D1** — **Session types are the discipline** (not per-message schemas). A
  `socket`'s `protocol` IS a session type; the connection law is $\bar S = S^{\perp}$
  (§3.2 of the paper). Grounded in the linear-logic Curry–Howard (Caires–Pfenning).
- **D2** — **Backpressure is a typed resource**: the credit-refined send ${!}^{n}A.S$;
  a send at $n=0$ has no typing rule (compile error, not a memory blow-up). Side
  conditions discharged in Presburger arithmetic → terminating compiler pass.
- **D3** — **SSE is the single-polarity fragment, not a separate thing**:
  $S_{\mathrm{SSE}} = \Pi_{\downarrow}(S_{\mathrm{WS}})$. Generalize Fase 33; do NOT
  fork the stream theory. One stream/dialogue theory.
- **D4** — **Realize endpoints over the Fase 13 π-typed channels** + Rust `tokio`
  WS. The OSS runtime owns the transport + typing; the enterprise owns the
  multi-tenant/audited surface (charter split).
- **D5** — **Reconnection via `cognitive_states`** (Fase 40.t): on disconnect, seal
  the session *continuation* (the residual session type + state) as an
  envelope-encrypted snapshot; a typed `reconnect` resumes only at a continuation
  the session type admits.
- **D6** — **Multiparty (n>2) via global-type projection** (Honda–Yoshida–Carbone)
  for many-skilled agents: one declared global dialogue $G$, endpoints =
  $\{G\!\restriction\! r\}$. (Sub-fase 41.h; binary first.)
- **D7** — **shield + audit on every utterance** (enterprise): each move is
  capability/PII-mediated by `shield` and anchored in the per-tenant SHA-256 audit
  chain — a typed, auditable dialogue.
- **D8** — **Absolute backwards-compat**: additive primitive; existing flows + the
  SSE primitive unchanged; wire byte-compat preserved (a `socket` with a
  single-polarity protocol negotiates an SSE-equivalent stream).

## Sub-fases (topologically ordered; each gated by an explicit founder "procede")

| Sub-fase | Scope |
|---|---|
| **41.a** ✅ SHIPPED 2026-05-22 | **Session-type algebra + duality** in `axon-frontend` (pure): the type grammar (§3.1), the duality involution $(\cdot)^{\perp}$ + the regular-coinductive equality for $\mu$-types, the binary connection-law check $\bar S \stackrel{?}{=} S^{\perp}$. Property-tested (involutivity, duality round-trip). | ✅ New `axon-frontend/src/session.rs` (pure, no runtime deps): `SessionType` grammar (`end`/`!A.S`/`?A.S`/`⊕`/`&`/`μX.S`/`X`) + smart constructors; `dual()` involution (swaps send↔recv, select↔branch; preserves payload + recursion); capture-stopping `subst` + equirecursive `unfold_head`; **`equiv()`** = the regular-coinductive equality (assume-pair-equal → unfold leading Recs → compare heads → recurse; terminates on regular types); **`is_dual_to()`** = the connection law (`peer ≡ self⊥`). Payload opaque (canonical type name; 41.b binds real AST types — the algebra depends only on payload equality). **10 tests green** (duality swaps + payload preservation, involutivity incl. recursive, connection law accept-dual/reject-self+mismatch, equirecursive fold/unfold + α-equivalence, equality negatives, a realistic recursive chat dialogue that terminates without blow-up). Zero new warnings. Commit `1c2149f`. (Multiparty projection moved to 41.h per D6 — 41.a is the binary algebra.) |
| **41.b** ✅ SHIPPED 2026-05-22 | **The `socket` primitive surface**: parser + AST + IR for the `socket { protocol, backpressure, duality, reconnect, legal_basis }` block; the session-type concrete syntax (`send`/`recv`/`select`/`branch`/`rec`/`end`). Cross-stack drift gate (Rust frontend ⇄ Python wrapper). | ✅ **Three landed pieces** (all in `axon-frontend`): **(1) Duality rewired** (commit `653c4a3`) — the Fase 4 `session` surface (`SessionDefinition`/`SessionRole`/`SessionStep` = `send`/`receive`/`loop`/`end`) was already in the language; new `lower_session_role` maps a role step-list into a §41.a `SessionType` (`loop` ↦ `μX.…X`), and `check_session_duality` is rewired from the old ad-hoc positional check (equal-length + pairwise `steps_dual`, which treated `loop` as a token, not recursion) to the rigorous **connection law** `T₂ ≡ T₁⊥` via regular-coinductive `is_dual_to` — recursion-correct, linear-logic-grounded. Retired `steps_dual`/`format_step`. **(2) `socket` declaration** (commit `d8a7d27`, surface A chosen by founder — protocol + transport as separate-but-composable concepts): `socket` keyword (lexer + declaration keyword) + `SocketDefinition` AST (`protocol`/`backpressure_credit`/`reconnect`/`legal_basis`) + `parse_socket` (order-free `key: value`; `backpressure: credit(n)`, `reconnect: cognitive_state`, `legal_basis`) + `IRSocket` (+ `IRProgram.sockets` + `visit_socket`) + `check_socket` (protocol must reference a **declared `session`**; backpressure credit must be **≥ 1** — a 0-credit window can't type a send, §4.2). **(3) Choice grammar** (commit `cfd5ab5`) — extends `SessionStep` with `branches: Vec<SessionBranch>` (each `{ label, steps }`) and `select`/`branch` ops; `parse_session_choice` parses `select { ℓ: [steps], … }` (and `branch { … }`); `lower_session_steps` maps `select→⊕`, `branch→&` over the algebra, duality decided arm-for-arm by the connection law (`select ⊥ branch` via `dual_map`); `check_session_steps` recurses into arms, requires ≥1 branch with **unique labels**; `IRSessionStep.branches` + `IRSessionBranch` lowered recursively by `lower_session_step_ir`. **14 Fase 41.b tests** (4 lowering + 4 socket + 6 choice: parse, lower, `select`⊥`branch`, clean typecheck, duplicate-label reject, empty-choice reject); **491 lib tests green**, zero regressions, zero new warnings. Sufficient session-type expressiveness for 41.c (credit-refined `!ⁿ/?ⁿ`) and 41.d (runtime over π-channels). |
| **41.c** ✅ SHIPPED 2026-05-22 | **Credit-refined backpressure typing** (D2): the index ${!}^{n}/{?}^{n}$, the `credit(k)` annotation, the Presburger discharge of credit constraints; the "no rule at $n=0$" error. Decidability + termination tests. | ✅ **Algebra extended + Presburger discharge wired** (commit `2239eaf`). `SessionType::Send`/`Recv` refactored to struct variants carrying `credit: Option<u64>` — `None` is the unbounded fragment (the pre-41.c algebra, preserved by default), `Some(n)` is `!ⁿA.S` / `?ⁿA.S` (paper §4.2). Smart constructors split: `send`/`recv` stay unbounded (backwards-compat across all 41.a/41.b call sites); new `send_credit`/`recv_credit` for the refined fragment. **Duality preserves credit symmetrically** (`(!ⁿA.S)⊥ = ?ⁿA.S⊥` — sender's window-of-n = receiver's absorbing capacity; standard credit-flow semantics, Rast lineage). Equivalence distinguishes credit indices ⇒ structurally distinct types. Display: `!^n A.S` / `?^n A.S`. New algebra methods: `with_credit(n)` (idempotent stamp), `has_send_at_zero()` (the explicit `!⁰A.S` axiom — unprovable by construction, returns offending payload in linear time), `recurring_paths(x)` (every path from root to `Var(x)` — terminating arms like `cancel:end` exempt from sustainability), `credit_delta(x)` (worst-case per-iter (#send, #recv)). **`credit_analyse(budget) → Result<(), CreditError>`** is the Presburger discharge proper: abstract-interprets the type starting at full window, tracking the available-credit fixpoint across straight-line (send: avail−1; recv: min(avail+1, k)), choice (worst-arm conservative), and recursion (every recurring path must satisfy `Δ = #send − #recv ≤ 0` — the loop-fixpoint inequality; non-recurring arms exempt). Three verdict witnesses: `SendAtZero {payload}`, `BurstOverflow {payload, budget, burst}`, `LoopUnsustainable {sends_per_iter, recvs_per_iter}`. **Wired into `check_socket`**: after 41.b's protocol + credit≥1 gates, each role is lowered, stamped with `k`, and run through `credit_analyse(k)`; verdicts emitted as `socket '…' violates the credit-refined backpressure type of session '…' role '…': <CreditError> (D2)`. **Unbounded fragment** (no `backpressure:` annotation) skips analysis cleanly — pre-41.c default preserved. **+19 tests**: 12 algebra (dual preserves credit, equivalence distinguishes, with_credit idempotent, has_send_at_zero, credit_analyse accepts within-budget straight-line + rejects burst overflow + rejects explicit n=0 + rejects unsustainable loop Δ=2-1>0 + accepts balanced loop Δ=0 + walks choice arms worst-case + credit_delta on recurring paths only + total on realistic recursive chat dialogue with no stack blow-up) + 7 integration (`fase41c_credit_tests`: within-budget accepted, burst-overflow rejected on producer-only with server clean, unsustainable loop rejected at any budget incl. credit(100), balanced loop accepted at minimal budget=1, choice arms each checked, no-annotation skips analysis, zero-credit still caught by 41.b separately). **510 lib tests green**, zero regressions, zero new warnings. Decidability + termination: constraints are linear over the naturals (Presburger-decidable); the algorithm is direct abstract interpretation in linear time over type size × #choice leaves. |
| **41.d** ✅ SHIPPED 2026-05-22 | **Runtime: typed WS endpoint over π-channels** in `axon-rs`: a `tokio` WebSocket realized as a Fase 13 typed channel; the send/recv/select/branch operational rules; credit accounting at runtime. E2E against a local axum WS mock. | ✅ **New `axon-rs/src/session_runtime/` module** (commit `d577aec`, ~800 LOC across 4 files + tests). **Carrier-agnostic core + RFC 6455 binding**: `SessionRuntime` is the operational state machine — cursor (always head-unfolded via `SessionType::unfold_head`, promoted to `pub`) + `CreditWindow` (TCP-window semantics: consume on send, refill on recv capped at budget) + one method per algebra rule (`try_send`/`try_recv`/`try_select`/`try_offer`/`try_end`). `ProtocolError` is a closed catalog of runtime witnesses — `PayloadMismatch`, `UnexpectedFrame`, `UnknownLabel`, `CreditExhausted` (the §41.c "no rule at n=0" axiom at runtime), `AlreadyComplete`, `MalformedFrame`, `Transport` — each with a stable `code()` ≤ 123 bytes UTF-8 for the RFC 6455 close-frame reason payload. Wire format = closed-catalog JSON envelope `{v:1, kind, …}` — `Send {payload_type, data}`, `Select {label}`, `End`, `Error {code, detail}`; version-first key ordering via deterministic string splice (default `serde_json::Map` is BTreeMap-backed → alphabetical, which would land "kind" before "v"; splice avoids `preserve_order` feature). `ws::drive(WebSocket, SessionRuntime, PeerRole) → Result<(), ProtocolError>` is the protocol loop: when cursor is producer-state, emit outgoing frame + step local runtime first; else read peer frame, parse + apply via `try_recv`/`try_offer`/`try_end`; on `End` (both sides) close `1000 normal closure`; on `ProtocolError` (either side, including our own credit-exhaustion) emit `Frame::Error` then close `1002 protocol error` with the error's `code()` as reason. Cargo.toml: enable `axum` `ws` feature; add `tokio-tungstenite = 0.24` dev-dep (same library axum pulls server-side ⇒ one common WS impl across both peers). **+26 unit tests** (11 state + 12 wire + 3 ws) + **4 E2E** scenarios against a real axum server bound on `TcpListener::bind("127.0.0.1:0")` with a `tokio-tungstenite::connect_async` client (true bytes-on-wire, not `tower::oneshot`): happy-path runs to completion + closes 1000; payload mismatch → Error(payload_mismatch) + close 1002; unexpected frame kind → Error(unexpected_frame) + close 1002; credit exhaustion at runtime (budget=1 on `!A.!B.end`, server's second send hits n=0) → Error(credit_exhausted) + close 1002. **Bug caught in vivo by scenario 4**: first draft used `?` on apply_outgoing errors, silently closing the carrier without the Error frame. Fix: explicit match → `report_and_close` before returning `Err`. **Carry-fix from 41.b**: 3 manual `IRProgram` constructions in `cost_estimator.rs` tests didn't have the new `sockets: Vec<IRSocket>` field; added `sockets: vec![]` (the 41.b ship verified only `cargo build --lib`, not lib-test, so this surfaced now). **2231 axon-rs lib tests green** (+26 new), **510 axon-frontend lib tests green** (+0 — `unfold_head` pub promotion is a pure surface change), zero regressions across both stacks. |
| **41.e** | **SSE-as-fragment unification** (D3): prove + wire $S_{\mathrm{SSE}} = \Pi_{\downarrow}(S_{\mathrm{WS}})$; a single-polarity `socket` negotiates an SSE-equivalent stream (Fase 33 reuse, byte-compat). |
| **41.f** | **Enterprise WebSocket surface** (the Kivi unblock): the axum/tokio WS endpoint on the enterprise server, gated by the §40.w auth + RLS layer (tenant-scoped by construction), shield + audit per utterance, `EXPOSE` wired. This is what lets the adopter run real-time chat on the single enterprise image. |
| **41.g** | **Typed reconnection via `cognitive_states`** (D5): seal the residual session type + state on disconnect; the typed `reconnect` resume; replay/expiry defence (reuse Fase 40.t AAD-bound snapshots). |
| **41.h** | **Multiparty projection** (D6): global type $G$ + `G\!\restriction\! r` for n-agent skill/tool topologies; safe-realizability gate. |
| **41.i** | **CI + fuzz + docs + release**: dedicated lane (duality/projection/credit fuzz + the deadlock-freedom invariants), adopter docs, coordinated release **axon-lang v2.3.0** + **axon-enterprise catch-up**. |

## Relationship to Fase 33 (the dual)

Fase 33 made **SSE** (server→client monologue) a cognitive primitive. Fase 41 is
its **bidirectional dual completion**: the same stream theory, generalized to a
two-polarity session. Formally SSE is the downstream projection of the WebSocket
dialogue ($S_{\mathrm{SSE}} = \Pi_{\downarrow}(S_{\mathrm{WS}})$, §4.4 of the paper)
— so the implementation **reuses** the SSE machinery rather than duplicating it.
SSE typed the server's half of the conversation; Fase 41 types the whole dialogue.
