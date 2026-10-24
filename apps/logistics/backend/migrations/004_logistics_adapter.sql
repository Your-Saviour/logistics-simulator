-- Additive metadata only: native HELICS state cannot be reconstructed from SQL.
CREATE TABLE IF NOT EXISTS logistics_adapter_sessions (
 run_id uuid PRIMARY KEY REFERENCES runs(id), epoch uuid NOT NULL, session_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS logistics_adapter_operations (
 request_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 session_id uuid NOT NULL, operation text NOT NULL, body jsonb NOT NULL, result jsonb,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz
);
ALTER TABLE boundary_outbox ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp();
