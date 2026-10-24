-- Storage V1 owns all stock and workflow state. Previous migrations are immutable.
CREATE TABLE warehouse_config (
 run_id uuid PRIMARY KEY REFERENCES runs(id), configuration jsonb NOT NULL
);
CREATE TABLE warehouse_locations (
 run_id uuid NOT NULL REFERENCES runs(id), code text NOT NULL, capacity integer NOT NULL CHECK(capacity>0),
 PRIMARY KEY(run_id,code)
);
CREATE TABLE warehouse_catalog (
 run_id uuid NOT NULL REFERENCES runs(id), sku text NOT NULL, kind text NOT NULL CHECK(kind IN ('raw','finished')),
 PRIMARY KEY(run_id,sku)
);
CREATE TABLE warehouse_stock (
 run_id uuid NOT NULL, sku text NOT NULL, location text NOT NULL,
 on_hand integer NOT NULL DEFAULT 0 CHECK(on_hand>=0),
 reserved integer NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=on_hand),
 PRIMARY KEY(run_id,sku,location),
 FOREIGN KEY(run_id,sku) REFERENCES warehouse_catalog(run_id,sku),
 FOREIGN KEY(run_id,location) REFERENCES warehouse_locations(run_id,code)
);
CREATE TABLE warehouse_commands (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id),
 command jsonb NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','rejected')),
 result jsonb, error text, completed_at double precision
);
CREATE TABLE warehouse_receipts (
 id uuid PRIMARY KEY REFERENCES warehouse_commands(id), run_id uuid NOT NULL REFERENCES runs(id),
 sku text NOT NULL, location text NOT NULL, quantity integer NOT NULL CHECK(quantity>0),
 correlation_id uuid NOT NULL, status text NOT NULL DEFAULT 'expected' CHECK(status IN ('expected','received')),
 FOREIGN KEY(run_id,sku,location) REFERENCES warehouse_stock(run_id,sku,location)
);
CREATE TABLE warehouse_reservations (
 id uuid PRIMARY KEY REFERENCES warehouse_commands(id), run_id uuid NOT NULL REFERENCES runs(id),
 sku text NOT NULL, location text NOT NULL, quantity integer NOT NULL CHECK(quantity>0), correlation_id uuid NOT NULL,
 purpose text NOT NULL CHECK(purpose IN ('production','customer')),
 status text NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','picked','released','issued','transferred')),
 FOREIGN KEY(run_id,sku,location) REFERENCES warehouse_stock(run_id,sku,location)
);
CREATE TABLE warehouse_transfers (
 id uuid PRIMARY KEY REFERENCES warehouse_commands(id), run_id uuid NOT NULL REFERENCES runs(id),
 reservation_id uuid NOT NULL UNIQUE REFERENCES warehouse_reservations(id),
 sku text NOT NULL, origin text NOT NULL, destination text NOT NULL,
 quantity integer NOT NULL CHECK(quantity>0), correlation_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'in_transit' CHECK(status IN ('in_transit','received')),
 FOREIGN KEY(run_id,sku,origin) REFERENCES warehouse_stock(run_id,sku,location),
 FOREIGN KEY(run_id,sku,destination) REFERENCES warehouse_stock(run_id,sku,location)
);
CREATE TABLE warehouse_movements (
 id uuid PRIMARY KEY, command_id uuid NOT NULL REFERENCES warehouse_commands(id), run_id uuid NOT NULL REFERENCES runs(id),
 action text NOT NULL, sku text NOT NULL, location text NOT NULL,
 on_hand_delta integer NOT NULL, reserved_delta integer NOT NULL,
 quantity integer NOT NULL CHECK(quantity>0), correlation_id uuid NOT NULL,
 reference uuid NOT NULL, simulation_time double precision NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(command_id,location)
);
CREATE INDEX warehouse_movements_run ON warehouse_movements(run_id,simulation_time);
CREATE INDEX warehouse_commands_run ON warehouse_commands(run_id);
