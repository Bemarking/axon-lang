-- AXON v1.0.0 Performance Indexes

CREATE INDEX IF NOT EXISTS idx_traces_flow_name ON traces(flow_name);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_traces_correlation ON traces(correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);

CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(actor);

CREATE INDEX IF NOT EXISTS idx_event_history_topic ON event_history(topic);
CREATE INDEX IF NOT EXISTS idx_event_history_timestamp ON event_history(timestamp_utc DESC);

CREATE INDEX IF NOT EXISTS idx_cost_tracking_flow ON cost_tracking(flow_name);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_timestamp ON cost_tracking(timestamp_utc DESC);

CREATE INDEX IF NOT EXISTS idx_execution_cache_flow ON execution_cache(flow_name);

CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope);
