CREATE TABLE transport_custody (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL, destination text NOT NULL, correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('accepted','received','acknowledged')),
 offer jsonb NOT NULL, acceptance jsonb NOT NULL, receipt jsonb,
 command_id uuid NOT NULL REFERENCES transport_commands(id)
);
CREATE UNIQUE INDEX transport_custody_pending_slot ON transport_custody(run_id,epoch,destination) WHERE state='accepted';
CREATE UNIQUE INDEX transport_custody_pending_unit ON transport_custody(run_id,epoch,unit_id) WHERE state='accepted';
CREATE TABLE transport_custody_events (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), envelope jsonb NOT NULL,
 command_id uuid NOT NULL REFERENCES transport_commands(id)
);
ALTER TABLE transport_commands ADD COLUMN retryable_capacity boolean NOT NULL DEFAULT false;
