//! §Fase 41.d — the **runtime** of a session-typed dialogue.
//!
//! `axon-frontend::session` (§41.a/b/c) gives the static algebra: the
//! `SessionType` grammar, the duality involution, the regular-coinductive
//! equality, and the Presburger-decidable credit-refined backpressure
//! index `!ⁿA.S`. This crate's `session_runtime` module is the dynamic
//! counterpart — the operational state machine that *runs* a session
//! type over a network carrier.
//!
//! Layering:
//! - [`state::SessionRuntime`] is **transport-agnostic**: it owns a
//!   cursor (the residual session type after the trace so far), a
//!   [`state::CreditWindow`] (the runtime witness of `!ⁿA.S`), and one
//!   method per operational rule (`try_send` / `try_recv` / `try_select`
//!   / `try_offer` / `try_end`). The same runtime would plug into a
//!   QUIC stream, an in-process channel, or unit-test scaffolding.
//! - [`wire::Frame`] is the **closed-catalog JSON envelope** carried by
//!   one WebSocket text message per operational step. Versioned (`v:1`)
//!   first key, `kind` discriminator, fully `serde`-checked.
//! - [`ws`] is the **RFC 6455 carrier**: an axum upgrade-handler-shaped
//!   driver that reads peer frames, routes them onto the runtime, emits
//!   our outgoing frames in turn, and closes with `1000 normal closure`
//!   on `end` or `1002 protocol error` on a [`error::ProtocolError`].
//!
//! The carrier in 41.d is WebSocket; future fases extend the same
//! `SessionRuntime` over:
//! - 41.f: the enterprise axum server (multi-tenant + RLS + audit per
//!   utterance — the Kivi single-image unblock);
//! - 41.g: typed reconnection via `cognitive_states` (the §41.a residual
//!   type sealed at disconnect resumes from the same cursor);
//! - 41.h: multiparty projection (the global-type `G` projected to each
//!   role `G⌐r`, each running its own `SessionRuntime`).

/// §Fase 111.i — the SessionType compiler: `IRSession` → [`crate::session::SessionType`].
///
/// The declarations reached the IR all along; nothing read them. The type-checker
/// lowered the roles to prove duality and dropped the result, and the enterprise
/// server — which *does* serve the wire — substituted a hardcoded chat schema for
/// every deployed socket. So a protocol could be *proven* dual at compile time and
/// a **different one** enforced at runtime. This module closes that gap.
pub mod compile;
pub mod error;
pub mod sse;
pub mod state;
pub mod wire;
pub mod ws;

pub use error::ProtocolError;
pub use sse::drive_sse_producer;
pub use state::{
    CreditWindow, ParkedContinuation, ResumeError, SealedRuntime, SessionRuntime,
    SEALED_RUNTIME_VERSION,
};
pub use compile::{credit_for_socket, schema_for_socket, server_schema, session_type_of_role};
pub use wire::{Frame, AXON_WIRE_VERSION};
pub use ws::{drive, PeerRole};
