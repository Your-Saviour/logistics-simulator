ALTER TABLE transport_expected_units ADD COLUMN destination text;
CREATE UNIQUE INDEX transport_expected_position_reservation ON transport_expected_units(destination) WHERE active AND destination IS NOT NULL;
ALTER TABLE transport_transfers ADD COLUMN unit_destinations jsonb NOT NULL DEFAULT '{}';
