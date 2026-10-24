ALTER TABLE warehouse_transfers DROP CONSTRAINT warehouse_transfers_status_check;
ALTER TABLE warehouse_transfers ADD CONSTRAINT warehouse_transfers_status_check CHECK(status IN ('awaiting_acceptance','in_transit','received'));
ALTER TABLE warehouse_transfers ADD COLUMN destination_owner text CHECK(destination_owner='shipping');
ALTER TABLE warehouse_custody_sources ADD COLUMN transfer_id uuid REFERENCES warehouse_transfers(id);
