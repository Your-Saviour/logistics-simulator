CREATE TABLE production_custody_quarantine (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 event_id uuid NOT NULL, envelope jsonb NOT NULL, endpoint text NOT NULL,
 phase text NOT NULL CHECK(phase IN ('ingest','apply')), reason text NOT NULL,
 command_id uuid REFERENCES production_commands(id), simulation_time double precision NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX production_quarantine_event ON production_custody_quarantine(run_id,epoch,event_id);
