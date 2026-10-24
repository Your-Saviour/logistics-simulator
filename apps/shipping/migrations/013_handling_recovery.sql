CREATE INDEX shipping_custody_event_retry ON boundary_outbox(run_id,(envelope->>'event_id'),sent_at) WHERE envelope->>'type' LIKE 'handling.%';
CREATE INDEX shipping_custody_stage_retry ON boundary_outbox(run_id,(envelope->'payload'->>'id'),(envelope->'payload'->>'state')) WHERE envelope->>'type' LIKE 'handling.%';
