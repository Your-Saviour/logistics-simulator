CREATE TABLE warehouse_custody_sources (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 unit_id uuid NOT NULL REFERENCES warehouse_handling_units(id),
 reservation_id uuid NOT NULL REFERENCES warehouse_reservations(id),
 command_id uuid NOT NULL REFERENCES warehouse_commands(id), correlation_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('offered','accepted','departed','acknowledged')),
 offer jsonb NOT NULL, acceptance jsonb, departure jsonb, acknowledgement jsonb
);
CREATE UNIQUE INDEX warehouse_custody_active_unit ON warehouse_custody_sources(unit_id)
 WHERE state IN ('offered','accepted','departed');
CREATE INDEX warehouse_custody_reservation ON warehouse_custody_sources(reservation_id);
CREATE TABLE warehouse_custody_events (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), envelope jsonb NOT NULL,
 command_id uuid NOT NULL REFERENCES warehouse_commands(id)
);
