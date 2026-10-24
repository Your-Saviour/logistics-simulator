CREATE TABLE production_config (
 run_id uuid PRIMARY KEY REFERENCES runs(id), config jsonb NOT NULL
);
CREATE TABLE production_materials (
 run_id uuid NOT NULL REFERENCES runs(id), sku text NOT NULL,
 quantity integer NOT NULL DEFAULT 0 CHECK(quantity>=0), PRIMARY KEY(run_id,sku)
);
CREATE TABLE production_orders (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 product text NOT NULL, line text NOT NULL, quantity integer NOT NULL CHECK(quantity>0),
 correlation_id uuid NOT NULL, status text NOT NULL CHECK(status IN ('draft','released','held','running','completed')),
 version integer NOT NULL DEFAULT 1, started_at double precision, finish_due double precision,
 output_quantity integer NOT NULL DEFAULT 0 CHECK(output_quantity>=0), scrap_quantity integer NOT NULL DEFAULT 0 CHECK(scrap_quantity>=0),
 blocked_reason text, materials_requested boolean NOT NULL DEFAULT false
);
CREATE INDEX production_active ON production_orders(run_id,line,status);
CREATE TABLE production_commands (
 id uuid PRIMARY KEY REFERENCES jobs(id), run_id uuid NOT NULL REFERENCES runs(id), command jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','rejected')), reason text
);
CREATE TABLE production_history (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), order_id uuid, job_id uuid NOT NULL REFERENCES jobs(id),
 action text NOT NULL, simulation_time double precision NOT NULL, detail jsonb NOT NULL
);
CREATE TABLE production_movements (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), job_id uuid NOT NULL REFERENCES jobs(id),
 order_id uuid, sku text NOT NULL, quantity integer NOT NULL, kind text NOT NULL,
 simulation_time double precision NOT NULL, UNIQUE(job_id,sku,kind)
);
CREATE TABLE production_boundary_identity (
 run_id uuid NOT NULL REFERENCES runs(id), source text NOT NULL, kind text NOT NULL, aggregate_id uuid NOT NULL,
 PRIMARY KEY(run_id,source,kind,aggregate_id)
);
