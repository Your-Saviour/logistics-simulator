CREATE TABLE shipping_handling_departures (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL REFERENCES shipping_handling_units(id), correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('offered','departed','acknowledged')),
 offer jsonb NOT NULL, departure jsonb, acknowledgement jsonb,
 command_id uuid NOT NULL REFERENCES shipping_commands(id)
);
CREATE UNIQUE INDEX shipping_one_pending_departure ON shipping_handling_departures(unit_id) WHERE state IN ('offered','departed');
