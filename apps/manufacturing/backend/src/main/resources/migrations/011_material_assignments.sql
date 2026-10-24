CREATE TABLE production_material_plans (
 id uuid PRIMARY KEY, event_id uuid NOT NULL UNIQUE,
 run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 batch_id uuid REFERENCES production_orders(id),
 command_id uuid NOT NULL REFERENCES production_commands(id), fact jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','planned','received','rejected')),
 unit_destinations jsonb, reason text
);
CREATE TABLE production_material_expected (
 unit_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 reservation_id uuid NOT NULL REFERENCES production_material_plans(id),
 destination text NOT NULL, offered_unit jsonb NOT NULL,
 state text NOT NULL CHECK(state IN ('expected','received'))
);
CREATE UNIQUE INDEX production_material_expected_slot ON production_material_expected(run_id,epoch,destination) WHERE state='expected';
