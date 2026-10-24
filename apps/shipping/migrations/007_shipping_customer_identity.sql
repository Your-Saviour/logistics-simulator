CREATE UNIQUE INDEX shipping_customer_aggregate ON shipping_incoming_events
 (run_id,(envelope->>'source'),(envelope->>'aggregate_id'))
 WHERE envelope->>'type'='shipping.order.v1';
