CREATE TABLE transport_custody_quarantine (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 event_id uuid NOT NULL, envelope jsonb NOT NULL, endpoint text NOT NULL,
 phase text NOT NULL CHECK(phase IN ('ingest','apply')), reason text NOT NULL,
 command_id uuid REFERENCES transport_commands(id), simulation_time double precision NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX transport_quarantine_event ON transport_custody_quarantine(run_id,epoch,event_id);
