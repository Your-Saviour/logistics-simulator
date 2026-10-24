ALTER TABLE warehouse_commands ADD COLUMN retryable_capacity boolean NOT NULL DEFAULT false;
CREATE TABLE warehouse_custody_receivers (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL, destination text NOT NULL, logical_location text NOT NULL,
 correlation_id uuid NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 state text NOT NULL CHECK(state IN ('accepted','received','acknowledged')),
 offer jsonb NOT NULL, acceptance jsonb NOT NULL, receipt jsonb,
 command_id uuid NOT NULL REFERENCES warehouse_commands(id)
);
CREATE UNIQUE INDEX warehouse_custody_receiving_slot ON warehouse_custody_receivers(run_id,epoch,destination) WHERE state='accepted';
CREATE UNIQUE INDEX warehouse_custody_receiving_unit ON warehouse_custody_receivers(unit_id) WHERE state='accepted';
