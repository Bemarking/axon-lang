-- AXON v1.0.0 Initial Schema
-- Persistent storage for AxonServer runtime state.

-- Execution traces (cognitive flow execution records)
CREATE TABLE IF NOT EXISTS traces (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        BIGINT NOT NULL UNIQUE,
    timestamp_utc   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    flow_name       TEXT NOT NULL,
    status          TEXT NOT NULL,
    steps_executed  INT NOT NULL DEFAULT 0,
    latency_ms      BIGINT NOT NULL DEFAULT 0,
    tokens_input    BIGINT NOT NULL DEFAULT 0,
    tokens_output   BIGINT NOT NULL DEFAULT 0,
    anchor_checks   INT NOT NULL DEFAULT 0,
    anchor_breaches INT NOT NULL DEFAULT 0,
    errors          INT NOT NULL DEFAULT 0,
    retries         INT NOT NULL DEFAULT 0,
    source_file     TEXT NOT NULL DEFAULT '',
    backend         TEXT NOT NULL DEFAULT '',
    client_key      TEXT NOT NULL DEFAULT '',
    replay_of       BIGINT,
    correlation_id  TEXT,
    events          JSONB NOT NULL DEFAULT '[]',
    annotations     JSONB NOT NULL DEFAULT '[]'
);

-- Scoped sessions (key-value state per scope)
CREATE TABLE IF NOT EXISTS sessions (
    id            BIGSERIAL PRIMARY KEY,
    scope         TEXT NOT NULL,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_step   TEXT NOT NULL DEFAULT '',
    UNIQUE(scope, key)
);

-- Daemon registry (cognitive daemons / immortal agents)
CREATE TABLE IF NOT EXISTS daemons (
    name             TEXT PRIMARY KEY,
    state            TEXT NOT NULL DEFAULT 'idle',
    source_file      TEXT NOT NULL DEFAULT '',
    flow_name        TEXT NOT NULL DEFAULT '',
    event_count      BIGINT NOT NULL DEFAULT 0,
    restart_count    INT NOT NULL DEFAULT 0,
    trigger_topic    TEXT,
    output_topic     TEXT,
    lifecycle_events JSONB NOT NULL DEFAULT '[]'
);

-- Audit log (immutable operational audit trail)
CREATE TABLE IF NOT EXISTS audit_log (
    id            BIGSERIAL PRIMARY KEY,
    timestamp_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action        TEXT NOT NULL,
    actor         TEXT NOT NULL DEFAULT 'anonymous',
    target        TEXT NOT NULL DEFAULT '',
    detail        JSONB NOT NULL DEFAULT '{}'
);

-- AxonStore instances (cognitive persistence with ΛD envelopes)
CREATE TABLE IF NOT EXISTS axon_stores (
    name       TEXT PRIMARY KEY,
    ontology   TEXT NOT NULL DEFAULT '',
    entries    JSONB NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL,
    total_ops  BIGINT NOT NULL DEFAULT 0
);

-- Dataspaces (cognitive navigation and association)
CREATE TABLE IF NOT EXISTS dataspaces (
    name         TEXT PRIMARY KEY,
    ontology     TEXT NOT NULL DEFAULT '',
    entries      JSONB NOT NULL DEFAULT '{}',
    associations JSONB NOT NULL DEFAULT '[]',
    created_at   BIGINT NOT NULL,
    total_ops    BIGINT NOT NULL DEFAULT 0,
    next_id      BIGINT NOT NULL DEFAULT 1
);

-- Hibernation sessions (immortal agents — pause/resume lifecycle)
CREATE TABLE IF NOT EXISTS hibernations (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    operation           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    checkpoints         JSONB NOT NULL DEFAULT '[]',
    resumed_from        INT,
    created_at          BIGINT NOT NULL,
    last_status_change  BIGINT NOT NULL,
    next_checkpoint_id  INT NOT NULL DEFAULT 1
);

-- Event history (event bus replay and audit)
CREATE TABLE IF NOT EXISTS event_history (
    id            BIGSERIAL PRIMARY KEY,
    timestamp_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topic         TEXT NOT NULL,
    source        TEXT NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}'
);

-- Execution cache (cached flow results with TTL)
CREATE TABLE IF NOT EXISTS execution_cache (
    id         BIGSERIAL PRIMARY KEY,
    flow_name  TEXT NOT NULL,
    cache_key  TEXT NOT NULL UNIQUE,
    result     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_secs   INT,
    hit_count  BIGINT NOT NULL DEFAULT 0
);

-- Cost tracking (per-flow LLM cost accounting)
CREATE TABLE IF NOT EXISTS cost_tracking (
    id            BIGSERIAL PRIMARY KEY,
    flow_name     TEXT NOT NULL,
    backend       TEXT NOT NULL,
    input_tokens  BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    timestamp_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Schedules (scheduled flow executions)
CREATE TABLE IF NOT EXISTS schedules (
    name          TEXT PRIMARY KEY,
    flow_name     TEXT NOT NULL,
    interval_secs BIGINT NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    backend       TEXT NOT NULL DEFAULT 'anthropic',
    last_run      BIGINT NOT NULL DEFAULT 0,
    next_run      BIGINT NOT NULL DEFAULT 0,
    run_count     BIGINT NOT NULL DEFAULT 0,
    error_count   BIGINT NOT NULL DEFAULT 0
);

-- Backend registry (custom-registered LLM backends)
CREATE TABLE IF NOT EXISTS backend_registry (
    name       TEXT PRIMARY KEY,
    base_url   TEXT NOT NULL,
    model      TEXT NOT NULL,
    api_family TEXT NOT NULL DEFAULT 'openai_compatible',
    metadata   JSONB NOT NULL DEFAULT '{}'
);
