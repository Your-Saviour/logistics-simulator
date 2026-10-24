CREATE TABLE shipping_goods_reservations (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 line_id uuid NOT NULL UNIQUE REFERENCES shipping_lines(id), fact jsonb NOT NULL,
 state text NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','admitted','blocked','released')), reason text
);
ALTER TABLE shipping_unit_plans ADD COLUMN reservation_id uuid REFERENCES shipping_goods_reservations(id);
ALTER TABLE shipping_unit_plans ADD COLUMN source_manifest jsonb;
ALTER TABLE shipping_unit_plans ADD COLUMN destination text;
CREATE UNIQUE INDEX shipping_expected_receiving_slot ON shipping_unit_plans(run_id,destination) WHERE state='expected' AND destination IS NOT NULL;
