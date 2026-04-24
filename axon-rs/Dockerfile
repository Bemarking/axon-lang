# Multi-stage build para axon-server (Rust)
#
# §Fase 12.a — `axon-rs` consume `axon-frontend` vía path dep
# (`../axon-frontend`), por lo que el build context de Docker debe
# ser la raíz del monorepo, no `axon-rs/`. Invocar desde el root:
#
#   docker build -f axon-rs/Dockerfile -t axon-server:1.4.x .
#
# Builder uses rust:latest because aws-sdk-secretsmanager (M3) and time-core
# pull in MSRVs ≥ 1.91.1 — too recent to pin to a specific image tag without
# a rust-toolchain.toml. Add a rust-toolchain.toml to lock the compiler version
# once the MSRV stabilizes across all deps.
#
# Runtime is ubuntu:24.04 (noble, glibc 2.39) to match what rust:latest links
# against. debian:bookworm-slim only ships glibc 2.36 which causes startup failures.

# Stage 1: Builder
# hadolint ignore=DL3007
FROM rust:latest AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependency-cache layer: copy BOTH crates' manifests (path dep from
# axon-rs → axon-frontend) plus a stub lib for axon-frontend so cargo
# can resolve the dep graph before real sources arrive. Re-runs only
# on Cargo.toml / Cargo.lock changes.
COPY axon-rs/Cargo.toml axon-rs/Cargo.lock axon-rs/
COPY axon-frontend/Cargo.toml axon-frontend/

RUN mkdir -p axon-rs/src axon-frontend/src \
    && echo 'fn main(){}' > axon-rs/src/main.rs \
    && echo '// stub for dep-cache layer' > axon-frontend/src/lib.rs \
    && cd axon-rs \
    && cargo build --release \
    && rm src/main.rs ../axon-frontend/src/lib.rs

# Real compilation — deps already cached above.
COPY axon-frontend/src/ axon-frontend/src/
COPY axon-rs/src/ axon-rs/src/
COPY axon-rs/migrations/ axon-rs/migrations/

# `touch` updates mtimes so cargo recompiles the project sources
# even though deps are cached.
RUN touch axon-rs/src/main.rs axon-frontend/src/lib.rs \
    && cd axon-rs \
    && cargo build --release

# Stage 2: Runtime
FROM ubuntu:24.04

# Install runtime deps and create non-root user in a single layer.
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false axon

WORKDIR /app

# Migrations are embedded at compile time via sqlx::migrate!("./migrations"),
# so only the binary is needed in the runtime image.
COPY --from=builder /build/axon-rs/target/release/axon /app/axon

USER axon

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8420/v1/health/live || exit 1

ENTRYPOINT ["/app/axon"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8420"]
