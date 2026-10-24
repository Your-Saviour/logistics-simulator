-- Whole inputs/outputs are owned here; existing material quantities stay legacy.
CREATE TABLE production_handling_units (
 id uuid PRIMARY KEY, barcode text NOT NULL UNIQUE CHECK(barcode='HU-'||upper(replace(id::text,'-',''))),
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 sku text NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 category text NOT NULL CHECK(category IN ('raw','finished')),
 state text NOT NULL CHECK(state IN ('available','reserved','consumed','in_transit','dispatched')),
 position text, origin text, destination text, handoff_id uuid,
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 custody_generation integer NOT NULL DEFAULT 0 CHECK(custody_generation>=0),
 last_sequence integer NOT NULL DEFAULT 1 CHECK(last_sequence>=0),
 command_id uuid NOT NULL REFERENCES production_commands(id), batch_id uuid REFERENCES production_orders(id),
 CHECK((state IN ('available','reserved') AND position IS NOT NULL) OR (state IN ('consumed','in_transit','dispatched') AND position IS NULL)),
 CHECK(state<>'in_transit' OR (origin IS NOT NULL AND destination IS NOT NULL AND handoff_id IS NOT NULL))
);
CREATE UNIQUE INDEX production_one_unit_per_position ON production_handling_units(run_id,epoch,position) WHERE position IS NOT NULL;
CREATE TABLE production_unit_inputs (
 batch_id uuid NOT NULL REFERENCES production_orders(id), unit_id uuid NOT NULL UNIQUE REFERENCES production_handling_units(id),
 simulation_time double precision NOT NULL CHECK(simulation_time>=0), PRIMARY KEY(batch_id,unit_id)
);
CREATE TABLE production_unit_lineage (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 batch_id uuid NOT NULL UNIQUE REFERENCES production_orders(id), payload jsonb NOT NULL
);
CREATE TABLE production_unit_movements (
 id uuid PRIMARY KEY, unit_id uuid NOT NULL REFERENCES production_handling_units(id), barcode text NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL, sequence integer NOT NULL CHECK(sequence>0),
 custody_generation integer NOT NULL CHECK(custody_generation>=0), action text NOT NULL,
 origin text, destination text NOT NULL, simulation_time double precision NOT NULL CHECK(simulation_time>=0),
 "references" jsonb NOT NULL, UNIQUE(unit_id,sequence)
);
