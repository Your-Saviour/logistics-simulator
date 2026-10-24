CREATE TABLE shipping_orders (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id),
 customer text NOT NULL, destination text NOT NULL, correlation_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'new', autonomous boolean NOT NULL DEFAULT false,
 version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE shipping_lines (
 id uuid PRIMARY KEY, order_id uuid NOT NULL REFERENCES shipping_orders(id),
 sku text NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 reserved integer NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=quantity),
 received integer NOT NULL DEFAULT 0 CHECK(received>=0 AND received<=quantity),
 reservation_id uuid, transfer_id uuid, replenished boolean NOT NULL DEFAULT false,
 UNIQUE(order_id,sku)
);
CREATE TABLE shipping_shipments (
 id uuid PRIMARY KEY, order_id uuid NOT NULL UNIQUE REFERENCES shipping_orders(id),
 status text NOT NULL DEFAULT 'awaiting_carrier', journey_id uuid,
 confirmation_id uuid, delivered_at double precision
);
CREATE TABLE shipping_commands (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id),
 body jsonb NOT NULL, outcome text NOT NULL DEFAULT 'pending', error text,
 completed_at double precision
);
CREATE TABLE shipping_intents (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
 order_id uuid NOT NULL REFERENCES shipping_orders(id), line_id uuid REFERENCES shipping_lines(id),
 kind text NOT NULL, owner text NOT NULL, request jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending', response jsonb, fact_id uuid,
 UNIQUE(order_id,line_id,kind,id)
);
CREATE INDEX shipping_pending_intents ON shipping_intents(run_id,state);
CREATE TABLE shipping_history (
 sequence bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
 order_id uuid NOT NULL REFERENCES shipping_orders(id), event text NOT NULL,
 simulation_time double precision NOT NULL, detail jsonb NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
