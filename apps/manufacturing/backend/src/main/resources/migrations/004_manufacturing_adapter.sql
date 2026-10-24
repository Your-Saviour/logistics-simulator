-- Native session ownership and retryable HTTP operation intents belong to the Java backend.
CREATE TABLE IF NOT EXISTS manufacturing_adapter_sessions (
 run_id uuid NOT NULL, epoch uuid NOT NULL, session_id uuid NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(run_id,epoch)
);
CREATE TABLE IF NOT EXISTS manufacturing_adapter_operations (
 request_id uuid PRIMARY KEY, run_id uuid NOT NULL, epoch uuid NOT NULL,
 session_id uuid NOT NULL, operation text NOT NULL, request jsonb NOT NULL,
 response jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
