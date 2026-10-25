CREATE TABLE production_fleet_jobs (
 id uuid PRIMARY KEY, run_id uuid NOT NULL, epoch uuid NOT NULL,
 request jsonb, snapshot jsonb, departure jsonb, receipt jsonb,
 admitted boolean NOT NULL DEFAULT false, departure_sent boolean NOT NULL DEFAULT false,
 receipt_sent boolean NOT NULL DEFAULT false, error text,
 polled_at timestamptz NOT NULL DEFAULT '-infinity'
);
