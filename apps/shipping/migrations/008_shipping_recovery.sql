ALTER TABLE shipping_orders ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false;
CREATE TABLE shipping_prepared_commands (
 operation_key uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
 actor text NOT NULL, fields jsonb NOT NULL, body jsonb NOT NULL
);
