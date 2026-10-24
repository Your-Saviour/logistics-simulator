CREATE TABLE shipping_handling_handoffs (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL, destination text NOT NULL, correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('accepted','received','acknowledged')),
 offer jsonb NOT NULL, acceptance jsonb NOT NULL, receipt jsonb,
 command_id uuid NOT NULL REFERENCES shipping_commands(id)
);
CREATE UNIQUE INDEX shipping_one_pending_handoff_slot ON shipping_handling_handoffs(run_id,epoch,destination) WHERE state='accepted';
CREATE UNIQUE INDEX shipping_one_pending_handoff_unit ON shipping_handling_handoffs(run_id,epoch,unit_id) WHERE state='accepted';
