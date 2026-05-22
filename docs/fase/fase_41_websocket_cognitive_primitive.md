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
| **41.b** 🟡 CORE SHIPPED 2026-05-22 (design discovery — see note) | **The `socket` primitive surface**: parser + AST + IR for the `socket { protocol, backpressure, duality, reconnect, legal_basis }` block; the session-type concrete syntax (`send`/`recv`/`select`/`branch`/`rec`/`end`). Cross-stack drift gate (Rust frontend ⇄ Python wrapper). | 🟡 **Design discovery**: the language **already has the protocol surface** — Fase 4 `session Name { role1: [..], role2: [..] }` (`SessionDefinition`/`SessionRole`/`SessionStep` = `send`/`receive`/`loop`/`end`). 41.b therefore does NOT invent a parallel grammar; its keystone is to **ground that existing surface in the §41.a algebra**: new `lower_session_role` (role step-list → `SessionType`; `loop`↦`μX.…X`) + `check_session_duality` **rewired** from the old ad-hoc positional check (equal-length + pairwise `steps_dual`, which treated `loop` as a token, not recursion) to the rigorous **connection law** `T₂ ≡ T₁⊥` via regular-coinductive `is_dual_to` — recursion-correct, linear-logic-grounded. Retired `steps_dual`/`format_step`. 4 tests (lowering send/recv/end + loop→μ; dual recursive roles pass; non-dual + payload-mismatch rejected); zero new warnings. Commit `653c4a3`. **REMAINING (pending a founder design call)**: (1) **choice** — extend `SessionStep` with `select`/`branch` (⊕/&) so the language grammar reaches the full §41.a expressiveness; (2) the **`socket` transport-binding** — whether it is a new declaration `socket Name { protocol: <session-ref>, backpressure: credit(n), reconnect, legal_basis }`, an attribute on a `topology` edge, or a `channel` extension. Since `session` already owns the protocol, `socket` is the **WS transport wrapper** around it — the surface choice is a language-design decision. |
| **41.c** | **Credit-refined backpressure typing** (D2): the index ${!}^{n}/{?}^{n}$, the `credit(k)` annotation, the Presburger discharge of credit constraints; the "no rule at $n=0$" error. Decidability + termination tests. |
| **41.d** | **Runtime: typed WS endpoint over π-channels** in `axon-rs`: a `tokio` WebSocket realized as a Fase 13 typed channel; the send/recv/select/branch operational rules; credit accounting at runtime. E2E against a local axum WS mock. |
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
