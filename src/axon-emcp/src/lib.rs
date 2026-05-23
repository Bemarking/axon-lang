//! `axon-emcp` — the official ℰMCP (Epistemic Model Context Protocol)
//! server for AXON, exposed as a library so integration tests under
//! `tests/` can drive the same `compiler_pipeline` and `knowledge`
//! surfaces the `main` binary uses at runtime.
//!
//! The binary entrypoint lives in `src/main.rs`; everything callable
//! from outside the crate (tests, future embedders) goes through the
//! re-exports here. Keeping a hybrid bin+lib crate avoids duplicating
//! module bodies and ensures the in-binary code path and the
//! integration-test code path compile from the exact same source.

#![forbid(unsafe_code)]

pub mod compiler_pipeline;
pub mod compose;
pub mod knowledge;
pub mod otlp;
pub mod prompts;
pub mod resources;
pub mod scaffold;
pub mod server;
pub mod telemetry;
pub mod tools;
