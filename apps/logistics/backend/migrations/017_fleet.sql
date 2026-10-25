-- Requests and business proofs are committed before any fleet HTTP I/O.
CREATE TABLE transport_fleet_jobs (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    epoch uuid NOT NULL,
    request jsonb NOT NULL,
    snapshot jsonb,
    admitted boolean NOT NULL DEFAULT false,
    departure jsonb,
    departure_sent boolean NOT NULL DEFAULT false,
    receipt jsonb,
    receipt_sent boolean NOT NULL DEFAULT false,
    error text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX transport_fleet_scope ON transport_fleet_jobs(run_id,epoch);
