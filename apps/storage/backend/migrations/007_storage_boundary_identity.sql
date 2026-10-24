-- Immutable workflow versions travel in domain facts. A peer command aggregate
-- is immutable: retry with its original event ID, never allocate a new command.
ALTER TABLE warehouse_receipts ADD COLUMN version integer NOT NULL DEFAULT 1;
ALTER TABLE warehouse_reservations ADD COLUMN version integer NOT NULL DEFAULT 1;
ALTER TABLE warehouse_transfers ADD COLUMN version integer NOT NULL DEFAULT 1;
CREATE TABLE warehouse_boundary_commands (
 run_id uuid NOT NULL REFERENCES runs(id), source text NOT NULL, type text NOT NULL,
 aggregate_id uuid NOT NULL, event_id uuid NOT NULL UNIQUE,
 command_id uuid NOT NULL REFERENCES warehouse_commands(id),
 PRIMARY KEY(run_id,source,type,aggregate_id)
);
