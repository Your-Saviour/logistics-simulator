ALTER TABLE runs ADD COLUMN ot_mode text NOT NULL DEFAULT 'disabled' CHECK (ot_mode IN ('disabled','openplc'));
CREATE TABLE ot_cells (
 run_id uuid PRIMARY KEY REFERENCES runs(id), epoch uuid NOT NULL, session_id uuid NOT NULL UNIQUE,
 owner_id uuid NOT NULL, settled bigint NOT NULL DEFAULT 0 CHECK(settled>=0),
 initialized boolean NOT NULL DEFAULT false, finalized boolean NOT NULL DEFAULT false,
 active_order uuid REFERENCES production_orders(id), telemetry jsonb NOT NULL DEFAULT '{}',
 observed_at timestamptz, error text
);
CREATE TABLE ot_operations (
 id uuid PRIMARY KEY, ordinal bigserial UNIQUE, run_id uuid NOT NULL REFERENCES runs(id),
 epoch uuid NOT NULL, session_id uuid NOT NULL, order_id uuid REFERENCES production_orders(id),
 op_key text NOT NULL, operation text NOT NULL, request jsonb NOT NULL,
 response jsonb, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','rejected')),
 reason text, UNIQUE(run_id,op_key)
);
CREATE TABLE ot_batches (
 order_id uuid PRIMARY KEY REFERENCES production_orders(id), run_id uuid NOT NULL REFERENCES runs(id),
 epoch uuid NOT NULL, completed_event jsonb, committed boolean NOT NULL DEFAULT false
);
CREATE TABLE ot_commands (
 id uuid PRIMARY KEY REFERENCES ot_operations(id), run_id uuid NOT NULL REFERENCES runs(id),
 epoch uuid NOT NULL, actor text NOT NULL, idempotency_key text NOT NULL, body jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','rejected')),
 reason text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(run_id,actor,idempotency_key)
);
