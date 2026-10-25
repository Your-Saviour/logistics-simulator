-- A coordinated batch commits each physically ready unit independently. Keep
-- stock audits immutable and unique per unit, retaining legacy command uniqueness.
ALTER TABLE warehouse_movements ADD COLUMN unit_id uuid REFERENCES warehouse_handling_units(id);
ALTER TABLE warehouse_movements DROP CONSTRAINT warehouse_movements_command_id_location_key;
ALTER TABLE warehouse_movements ADD CONSTRAINT warehouse_movement_unit_once UNIQUE NULLS NOT DISTINCT(command_id,location,unit_id);
ALTER TABLE warehouse_unit_movements DROP CONSTRAINT warehouse_unit_movements_command_id_unit_id_key;
ALTER TABLE warehouse_unit_movements ADD CONSTRAINT warehouse_unit_action_once UNIQUE(command_id,unit_id,action);
ALTER TABLE warehouse_fleet_outbox ADD COLUMN retry_after timestamptz NOT NULL DEFAULT clock_timestamp();
ALTER TABLE warehouse_fleet_jobs ADD COLUMN poll_after timestamptz NOT NULL DEFAULT clock_timestamp();
