CREATE TABLE IF NOT EXISTS runs (
 id uuid PRIMARY KEY, epoch uuid NOT NULL, current boolean NOT NULL DEFAULT true,
 mode text NOT NULL CHECK(mode IN ('standalone','helics')), state text NOT NULL DEFAULT 'running',
 granted double precision NOT NULL DEFAULT 0, requested double precision NOT NULL DEFAULT 0,
 committed double precision NOT NULL DEFAULT 0, speed integer NOT NULL DEFAULT 1,
 anchor timestamptz NOT NULL DEFAULT clock_timestamp(), error text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_run ON runs(current) WHERE current;
CREATE TABLE IF NOT EXISTS jobs (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 idempotency_key text NOT NULL, due_at double precision NOT NULL CHECK(due_at >= 0),
 payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending', attempts integer NOT NULL DEFAULT 0,
 retry_after timestamptz NOT NULL DEFAULT clock_timestamp(), error text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(run_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS due_jobs ON jobs(run_id,status,due_at);
CREATE TABLE IF NOT EXISTS inbox (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL, epoch uuid NOT NULL,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS effects (
 job_id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL, quantity integer NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
 id uuid PRIMARY KEY, job_id uuid NOT NULL UNIQUE REFERENCES jobs(id), run_id uuid NOT NULL,
 sent_at timestamptz, retry_after timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS boundary_outbox (
 id uuid PRIMARY KEY, run_id uuid NOT NULL, envelope jsonb NOT NULL, sent_at timestamptz
);
CREATE TABLE IF NOT EXISTS heartbeats (
 role text PRIMARY KEY, seen_at timestamptz NOT NULL DEFAULT clock_timestamp(), detail text
);
CREATE TABLE IF NOT EXISTS source_snapshots (
 name text PRIMARY KEY, status jsonb, connected boolean NOT NULL DEFAULT false,
 observed_at timestamptz, error text
);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS blocked_reason text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS original_due_at double precision;
UPDATE jobs SET original_due_at=due_at WHERE original_due_at IS NULL;
