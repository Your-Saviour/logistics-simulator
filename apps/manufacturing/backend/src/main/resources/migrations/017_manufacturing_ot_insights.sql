-- SIMU-77: observational history never grants time or mutates production.
CREATE TABLE ot_observations (
 id bigserial PRIMARY KEY, operation_id uuid NOT NULL UNIQUE,
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 order_id uuid, simulation_time double precision NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 telemetry jsonb NOT NULL, signals jsonb NOT NULL, scenario_id uuid
);
CREATE INDEX ot_observations_scope ON ot_observations(run_id,epoch,id DESC);
CREATE TABLE ot_alarms (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 source text NOT NULL, severity text NOT NULL, impact text NOT NULL,
 active boolean NOT NULL DEFAULT true, first_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 last_at timestamptz NOT NULL DEFAULT clock_timestamp(), cleared_at timestamptz,
 acknowledged_at timestamptz, acknowledged_by text, order_id uuid
);
CREATE UNIQUE INDEX ot_active_alarm ON ot_alarms(run_id,epoch,source) WHERE active;
CREATE TABLE ot_sensor_scenarios (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 version integer NOT NULL DEFAULT 1, profile text NOT NULL, seed integer NOT NULL,
 started_simulation_time double precision NOT NULL, stopped_simulation_time double precision,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), stopped_at timestamptz,
 actor text NOT NULL
);
CREATE UNIQUE INDEX ot_active_sensor_scenario ON ot_sensor_scenarios(run_id,epoch) WHERE stopped_at IS NULL;
CREATE TABLE ot_insight_receipts (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 actor text NOT NULL, idempotency_key text NOT NULL, body jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(run_id,actor,idempotency_key)
);
