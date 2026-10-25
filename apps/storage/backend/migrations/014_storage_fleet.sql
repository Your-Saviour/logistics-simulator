-- Native durable intent/proof delivery. HTTP never participates in a SQL transaction.
CREATE TABLE warehouse_fleet_jobs (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 request jsonb NOT NULL, observation jsonb, error text,
 departure jsonb, receipt jsonb,
 native_command uuid REFERENCES warehouse_commands(id), logical_destination text, quantity integer CHECK(quantity>0)
);
CREATE TABLE warehouse_fleet_outbox (
 id uuid PRIMARY KEY, job_id uuid NOT NULL REFERENCES warehouse_fleet_jobs(id),
 kind text NOT NULL CHECK(kind IN ('request','departure','receipt')), body jsonb NOT NULL,
 sent_at timestamptz, UNIQUE(job_id,kind)
);
