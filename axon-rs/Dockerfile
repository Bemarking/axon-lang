# Multi-stage build para axon-server (Rust)
# Stage 1: Builder
FROM rust:latest AS builder

WORKDIR /build

# Instalar dependencias del sistema necesarias para compilar
# sqlx con tls-rustls + pkg-config
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copiar Cargo.toml y Cargo.lock para cachear dependencias
COPY Cargo.toml Cargo.lock ./

# Crear un src/main.rs dummy para compilar dependencias
RUN mkdir src && echo 'fn main(){}' > src/main.rs

# Compilar en release mode para cachear las dependencias
# Esto aprovecha Docker layer caching si solo cambian archivos de src/
RUN cargo build --release

# Remover el dummy main.rs
RUN rm src/main.rs

# Copiar el código fuente real
COPY src/ src/
COPY migrations/ migrations/

# Recompilación real del binario (Las dependencias ya están cacheadas)
RUN touch src/main.rs && cargo build --release

# Stage 2: Runtime (imagen final, mucho más pequeña)
FROM debian:bookworm-slim

# Instalar solo las dependencias de runtime necesarias
# ca-certificates para validación TLS
# libssl3 para TLS (tls-rustls usa esto)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario sin privilegios para ejecutar el servidor
RUN useradd -r -s /bin/false axon

# Setup del directorio de trabajo
WORKDIR /app

# Copiar SOLO el binario compilado desde el builder
COPY --from=builder /build/target/release/axon /app/axon

# Nota: Las migraciones SQL NO se copian aquí
# Están embebidas en el binario con sqlx::migrate!("./migrations")
# El macro incrusta los archivos SQL en compile time

# Cambiar usuario a axon (sin privilegios)
USER axon

# Exponer el puerto del servidor
EXPOSE 8420

# Health check — verifica que el servidor está listo
# startPeriod=30s: espera antes de empezar los checks
# interval=30s: check cada 30 segundos
# timeout=10s: timeout de 10s por check
# retries=3: marcar como unhealthy después de 3 fallos
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8420/v1/health/live || exit 1

# Entrypoint: ejecutar el comando `axon serve`
# El servidor arranca en 0.0.0.0:8420 por default
ENTRYPOINT ["/app/axon"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8420"]
