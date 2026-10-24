CREATE TABLE transport_expected_units (
 transfer_id uuid NOT NULL REFERENCES transport_transfers(id), unit_id uuid NOT NULL,
 source text NOT NULL CHECK(source='shipping'), sku text NOT NULL,
 quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 state text NOT NULL DEFAULT 'expected' CHECK(state IN ('expected','received')),
 active boolean NOT NULL DEFAULT true, PRIMARY KEY(transfer_id,unit_id)
);
CREATE UNIQUE INDEX transport_one_expected_allocation ON transport_expected_units(unit_id) WHERE active;
