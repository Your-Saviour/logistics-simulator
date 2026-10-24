CREATE TABLE production_output_custody (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL UNIQUE REFERENCES production_handling_units(id),
 batch_id uuid NOT NULL REFERENCES production_orders(id), correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('offered','departed','acknowledged')),
 offer jsonb NOT NULL, departure jsonb, acknowledgement jsonb
);
