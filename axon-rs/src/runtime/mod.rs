//! AXON Runtime primitives (§λ-L-E Fases 3 + 5).
//!
//! Direct port of `axon/runtime/` sub-modules (lease_kernel, reconcile_loop,
//! ensemble_aggregator, immune kernels).

pub mod ensemble_aggregator;
pub mod immune;
pub mod lease_kernel;
pub mod reconcile_loop;
