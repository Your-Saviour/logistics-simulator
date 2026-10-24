-- Existing quantity-only transfers remain legacy; no invented unit backfill.
ALTER TABLE transport_transfers ADD COLUMN unit_ids jsonb NOT NULL DEFAULT '[]';
CREATE TABLE transport_handling_units (
 id uuid PRIMARY KEY, barcode text NOT NULL UNIQUE CHECK(barcode='HU-'||upper(replace(id::text,'-',''))),
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 sku text NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 category text NOT NULL CHECK(category IN ('raw','finished')),
 logical_location text NOT NULL, state text NOT NULL CHECK(state IN ('available','reserved','in_transit','dispatched','consumed')),
 position text, origin text, destination text, handoff_id uuid,
 version integer NOT NULL DEFAULT 1 CHECK(version>0), last_sequence integer NOT NULL DEFAULT 0 CHECK(last_sequence>=0),
 custody_generation integer NOT NULL DEFAULT 0 CHECK(custody_generation>=0),
 command_id uuid NOT NULL REFERENCES transport_commands(id), transfer_id uuid REFERENCES transport_transfers(id),
 CHECK((state IN ('available','reserved') AND position IS NOT NULL) OR (state IN ('in_transit','dispatched','consumed') AND position IS NULL)),
 CHECK(state<>'in_transit' OR (origin IS NOT NULL AND destination IS NOT NULL AND handoff_id IS NOT NULL))
);
CREATE UNIQUE INDEX transport_one_unit_per_position ON transport_handling_units(run_id,epoch,position) WHERE position IS NOT NULL;
CREATE TABLE transport_unit_allocations (
 transfer_id uuid NOT NULL REFERENCES transport_transfers(id), unit_id uuid NOT NULL REFERENCES transport_handling_units(id),
 active boolean NOT NULL DEFAULT true, PRIMARY KEY(transfer_id,unit_id)
);
CREATE UNIQUE INDEX transport_one_active_unit_allocation ON transport_unit_allocations(unit_id) WHERE active;
CREATE TABLE transport_unit_movements (
 id uuid PRIMARY KEY, unit_id uuid NOT NULL REFERENCES transport_handling_units(id), barcode text NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL, command_id uuid NOT NULL REFERENCES transport_commands(id),
 sequence integer NOT NULL CHECK(sequence>0), custody_generation integer NOT NULL CHECK(custody_generation>=0),
 action text NOT NULL, origin text, destination text NOT NULL, simulation_time double precision NOT NULL CHECK(simulation_time>=0),
 "references" jsonb NOT NULL, correlation_id uuid NOT NULL,
 UNIQUE(unit_id,sequence), UNIQUE(command_id,unit_id)
);
