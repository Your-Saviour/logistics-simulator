-- Additive storage-owned journal. Existing migrations remain byte-identical.
CREATE TABLE IF NOT EXISTS storage_adapter_sessions (
 run_id uuid PRIMARY KEY REFERENCES runs(id), epoch uuid NOT NULL,
 session_id uuid NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS storage_adapter_operations (
 request_id uuid PRIMARY KEY, session_id uuid NOT NULL,
 operation_key text NOT NULL, request jsonb NOT NULL, response jsonb,
 UNIQUE(session_id,operation_key)
);
