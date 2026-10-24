ALTER TABLE shipping_commands ADD COLUMN retryable_capacity boolean NOT NULL DEFAULT false;
