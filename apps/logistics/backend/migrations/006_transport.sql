CREATE TABLE transport_vehicles (
 run_id uuid NOT NULL REFERENCES runs(id), code text NOT NULL,
 capacity integer NOT NULL CHECK(capacity BETWEEN 1 AND 10000), location text NOT NULL,
 PRIMARY KEY(run_id,code)
);
CREATE TABLE transport_commands (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id),
 command jsonb NOT NULL, provider boolean NOT NULL DEFAULT false,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','rejected')),
 reason text, completed_at double precision
);
CREATE TABLE transport_transfers (
 id uuid PRIMARY KEY REFERENCES transport_commands(id), run_id uuid NOT NULL REFERENCES runs(id),
 epoch uuid NOT NULL, correlation_id uuid NOT NULL, external_reference uuid,
 route text NOT NULL, origin text NOT NULL, destination text NOT NULL, journey_seconds double precision NOT NULL CHECK(journey_seconds>=1),
 sku text NOT NULL, quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
 vehicle text, status text NOT NULL CHECK(status IN ('requested','assigned','loaded','in_transit','arrived','unloaded','received')),
 custody text NOT NULL CHECK(custody IN ('origin','vehicle','destination')),
 provider boolean NOT NULL DEFAULT false, version integer NOT NULL DEFAULT 1,
 planned_eta double precision, departed_at double precision, arrived_at double precision,
 unloaded_at double precision, received_at double precision,
 FOREIGN KEY(run_id,vehicle) REFERENCES transport_vehicles(run_id,code)
);
CREATE UNIQUE INDEX transport_exclusive_assignment ON transport_transfers(run_id,vehicle)
 WHERE status IN ('assigned','loaded','in_transit','arrived');
CREATE TABLE transport_movements (
 id uuid PRIMARY KEY, transfer_id uuid NOT NULL REFERENCES transport_transfers(id),
 run_id uuid NOT NULL REFERENCES runs(id), command_id uuid NOT NULL UNIQUE REFERENCES transport_commands(id),
 action text NOT NULL, simulation_time double precision NOT NULL, quantity integer NOT NULL,
 custody text NOT NULL, version integer NOT NULL, UNIQUE(transfer_id,version)
);
CREATE TABLE transport_peer_commands (
 run_id uuid NOT NULL REFERENCES runs(id), source text NOT NULL, aggregate_id uuid NOT NULL,
 event_id uuid NOT NULL UNIQUE, body jsonb NOT NULL,
 PRIMARY KEY(run_id,source,aggregate_id)
);
