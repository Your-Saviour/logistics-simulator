CREATE TABLE IF NOT EXISTS command_audit (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), actor text NOT NULL,
 role text NOT NULL, request_id uuid NOT NULL, action text NOT NULL,
 outcome text NOT NULL CHECK(outcome IN ('accepted','rejected')),
 status_code integer NOT NULL, idempotency_key text NOT NULL DEFAULT '',
 peer text NOT NULL DEFAULT '', target_id uuid,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS command_audit_run_time ON command_audit(run_id,recorded_at);
