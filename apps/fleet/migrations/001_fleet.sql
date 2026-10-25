CREATE TABLE fleet_runs (
    id uuid PRIMARY KEY,
    epoch uuid NOT NULL,
    current boolean NOT NULL DEFAULT true,
    generation bigint NOT NULL DEFAULT 0,
    revision bigint NOT NULL DEFAULT 0,
    committed double precision NOT NULL DEFAULT 0 CHECK (committed >= 0),
    state text NOT NULL DEFAULT 'held',
    reason text,
    sources jsonb NOT NULL,
    observations jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX fleet_one_current ON fleet_runs(current) WHERE current;
CREATE TABLE fleet_robots (
    run_id uuid NOT NULL REFERENCES fleet_runs ON DELETE CASCADE,
    id text NOT NULL,
    pose jsonb NOT NULL,
    parking jsonb NOT NULL,
    PRIMARY KEY(run_id,id)
);
CREATE TABLE fleet_jobs (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES fleet_runs ON DELETE CASCADE,
    epoch uuid NOT NULL,
    ordinal bigserial UNIQUE,
    unit_id uuid NOT NULL,
    producer text NOT NULL,
    request jsonb NOT NULL,
    state text NOT NULL DEFAULT 'queued',
    robot_id text,
    route jsonb,
    phase_started double precision,
    elapsed double precision NOT NULL DEFAULT 0,
    release_time double precision NOT NULL,
    carried boolean NOT NULL DEFAULT false,
    progress double precision NOT NULL DEFAULT 0,
    waiting_reason text,
    blockers jsonb NOT NULL DEFAULT '[]',
    proofs jsonb NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id,robot_id) REFERENCES fleet_robots(run_id,id)
);
CREATE UNIQUE INDEX fleet_active_unit ON fleet_jobs(run_id,unit_id) WHERE state NOT IN ('completed','cancelled');
CREATE UNIQUE INDEX fleet_active_robot ON fleet_jobs(run_id,robot_id) WHERE state NOT IN ('completed','cancelled');
CREATE TABLE fleet_reservations (
    resource text PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES fleet_jobs ON DELETE CASCADE
);
CREATE TABLE fleet_outbox (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES fleet_jobs ON DELETE CASCADE,
    kind text NOT NULL,
    body jsonb NOT NULL,
    acknowledged boolean NOT NULL DEFAULT false,
    UNIQUE(job_id,kind)
);
CREATE TABLE fleet_audit (
    ordinal bigserial PRIMARY KEY,
    run_id uuid REFERENCES fleet_runs ON DELETE CASCADE,
    job_id uuid,
    actor text NOT NULL,
    action text NOT NULL,
    simulation_time double precision,
    detail jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
