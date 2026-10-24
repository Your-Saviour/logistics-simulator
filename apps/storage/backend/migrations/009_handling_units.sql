-- Additive physical ledger. Legacy quantities are intentionally not backfilled.
ALTER TABLE warehouse_receipts ADD COLUMN unit_manifest jsonb;
CREATE TABLE warehouse_handling_units (
 id uuid PRIMARY KEY,
 barcode text NOT NULL UNIQUE CHECK(barcode='HU-'||upper(replace(id::text,'-',''))),
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 sku text NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 category text NOT NULL CHECK(category IN ('raw','finished')),
 state text NOT NULL CHECK(state IN ('available','reserved','in_transit','consumed','dispatched')),
 logical_location text NOT NULL, position text, origin text, destination text, handoff_id uuid,
 receipt_id uuid REFERENCES warehouse_receipts(id), conversion_id uuid REFERENCES warehouse_commands(id),
 correlation_id uuid NOT NULL, reservation_id uuid REFERENCES warehouse_reservations(id),
 transfer_id uuid REFERENCES warehouse_transfers(id),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 custody_generation integer NOT NULL DEFAULT 0 CHECK(custody_generation>=0),
 last_sequence integer NOT NULL DEFAULT 0 CHECK(last_sequence>=0),
 CHECK((state IN ('available','reserved') AND position IS NOT NULL) OR
       (state IN ('in_transit','consumed','dispatched') AND position IS NULL)),
 CHECK(state<>'in_transit' OR (origin IS NOT NULL AND destination IS NOT NULL AND handoff_id IS NOT NULL)),
 CHECK((receipt_id IS NULL)<>(conversion_id IS NULL)),
 FOREIGN KEY(run_id,sku,logical_location) REFERENCES warehouse_stock(run_id,sku,location)
);
CREATE UNIQUE INDEX warehouse_one_unit_per_position ON warehouse_handling_units(run_id,epoch,position) WHERE position IS NOT NULL;
CREATE INDEX warehouse_units_available ON warehouse_handling_units(run_id,sku,logical_location,state);
CREATE TABLE warehouse_unit_allocations (
 reservation_id uuid NOT NULL REFERENCES warehouse_reservations(id),
 unit_id uuid NOT NULL REFERENCES warehouse_handling_units(id),
 PRIMARY KEY(reservation_id,unit_id)
);
CREATE TABLE warehouse_unit_movements (
 id uuid PRIMARY KEY, unit_id uuid NOT NULL REFERENCES warehouse_handling_units(id),
 barcode text NOT NULL, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 command_id uuid NOT NULL REFERENCES warehouse_commands(id),
 sequence integer NOT NULL CHECK(sequence>0), custody_generation integer NOT NULL CHECK(custody_generation>=0),
 action text NOT NULL, origin text, destination text NOT NULL,
 simulation_time double precision NOT NULL CHECK(simulation_time>=0),
 "references" jsonb NOT NULL, correlation_id uuid NOT NULL,
 UNIQUE(unit_id,sequence), UNIQUE(command_id,unit_id)
);
CREATE INDEX warehouse_unit_history ON warehouse_unit_movements(run_id,epoch,unit_id,sequence);
