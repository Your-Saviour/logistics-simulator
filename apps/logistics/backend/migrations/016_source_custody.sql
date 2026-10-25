-- Outgoing raw custody has its own durable source state, not destination stock.
CREATE TABLE transport_source_custody (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL REFERENCES transport_handling_units(id), correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('offered','departed','acknowledged')),
 offer jsonb NOT NULL, departure jsonb, receipt jsonb,
 command_id uuid NOT NULL REFERENCES transport_commands(id)
);
CREATE UNIQUE INDEX transport_one_pending_source_custody ON transport_source_custody(unit_id)
 WHERE state <> 'acknowledged';
