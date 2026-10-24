-- Route destination remains the configured logical stop; customer address is
-- immutable request context, not an invented world coordinate.
ALTER TABLE transport_transfers ADD COLUMN customer_destination text;
