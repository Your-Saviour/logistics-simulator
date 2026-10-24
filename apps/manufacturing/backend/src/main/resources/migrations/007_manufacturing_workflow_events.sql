ALTER TABLE production_orders DROP CONSTRAINT production_orders_status_check;
UPDATE production_orders SET status=CASE status WHEN 'draft' THEN 'queued' WHEN 'released' THEN 'ready' ELSE status END;
ALTER TABLE production_orders ADD CONSTRAINT production_orders_status_check CHECK(status IN ('queued','ready','held','running','completed'));
CREATE TABLE production_events (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), order_id uuid NOT NULL UNIQUE REFERENCES production_orders(id),
 envelope jsonb NOT NULL, sent_at timestamptz
);
