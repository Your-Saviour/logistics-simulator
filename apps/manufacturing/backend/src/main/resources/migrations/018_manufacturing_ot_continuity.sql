-- Source continuity survives reconnects at consecutive simulation seconds.
ALTER TABLE ot_cells ADD COLUMN continuity bigint NOT NULL DEFAULT 0;
ALTER TABLE ot_observations ADD COLUMN continuity bigint NOT NULL DEFAULT 0;
CREATE TABLE ot_source_events (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 kind text NOT NULL, detail text NOT NULL, simulation_time double precision NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ot_source_events_scope ON ot_source_events(run_id,epoch,id DESC);
