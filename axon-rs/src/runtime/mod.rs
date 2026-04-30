//! AXON Runtime primitives (§λ-L-E Fases 3 + 5; §Fase 13.f.2 typed channels).
//!
//! Direct port of `axon/runtime/` sub-modules (lease_kernel, reconcile_loop,
//! ensemble_aggregator, immune kernels). Fase 13.f.2 adds the typed
//! channels runtime (`channels::typed::TypedEventBus`) — the Rust-runtime
//! parity for the Python `axon/runtime/channels/typed.py` module.

pub mod channels;
pub mod ensemble_aggregator;
pub mod immune;
pub mod lease_kernel;
pub mod reconcile_loop;
