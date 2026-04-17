//! Migrations — embedded database schema migration runner.
//!
//! Uses sqlx's built-in migration system to manage schema versions.
//! Migrations are embedded at compile time from the `migrations/` directory.
//!
//! On server startup, `run()` applies any pending migrations automatically.
//! This ensures the database schema is always up-to-date.

use crate::storage::StorageError;
use sqlx::PgPool;

/// Run all pending database migrations.
///
/// Migrations are embedded from `./migrations/` at compile time.
/// Safe to call repeatedly — already-applied migrations are skipped.
pub async fn run(pool: &PgPool) -> Result<(), StorageError> {
    tracing::info!("db_migrations_starting");

    sqlx::migrate!("./migrations")
        .run(pool)
        .await
        .map_err(|e| {
            tracing::error!(error = %e, "db_migrations_failed");
            StorageError::QueryError(format!("Migration failed: {e}"))
        })?;

    tracing::info!("db_migrations_completed");
    Ok(())
}
