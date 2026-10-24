CREATE TABLE control_receipts (
 run_id uuid NOT NULL REFERENCES runs(id), actor text NOT NULL, idempotency_key varchar(128) NOT NULL,
 action text NOT NULL CHECK(action IN ('hold','resume')), request jsonb NOT NULL, response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(run_id,actor,idempotency_key)
);
