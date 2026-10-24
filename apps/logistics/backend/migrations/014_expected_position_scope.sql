ALTER TABLE transport_expected_units ADD COLUMN run_id uuid REFERENCES runs(id);
ALTER TABLE transport_expected_units ADD COLUMN epoch uuid;
UPDATE transport_expected_units e SET run_id=t.run_id,epoch=t.epoch FROM transport_transfers t WHERE t.id=e.transfer_id;
ALTER TABLE transport_expected_units ALTER COLUMN run_id SET NOT NULL;
ALTER TABLE transport_expected_units ALTER COLUMN epoch SET NOT NULL;
DROP INDEX transport_expected_position_reservation;
CREATE UNIQUE INDEX transport_expected_position_reservation ON transport_expected_units(run_id,epoch,destination) WHERE active AND destination IS NOT NULL;
