CREATE TABLE shipping_incoming_events (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), envelope jsonb NOT NULL
);
