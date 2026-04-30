//! AXON Runtime — Typed Channels (Fase 13.f.2).
//!
//! Native Rust port of the Python reference module
//! `axon/runtime/channels/typed.py` (Fase 13.d). Closes the runtime gap
//! left open by Fase 13's release v1.4.2: the frontend was at parity but
//! `axon-rs` had no executor for the new `channel`/`emit`/`publish`/
//! `discover` surface. End-to-end programs running on the Rust runtime
//! now get the same typed-channel guarantees the Python runtime offers.
//!
//! Surface re-exports: see `typed`.

pub mod typed;

pub use typed::{
    Capability, ShieldComplianceFn, TypedChannelError, TypedChannelHandle,
    TypedChannelRegistry, TypedEvent, TypedEventBus, TypedPayload,
};
