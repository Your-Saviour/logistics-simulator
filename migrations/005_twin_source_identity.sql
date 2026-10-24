-- Fence responses from consumers using a replaced source endpoint/identity.
ALTER TABLE twin_sources ADD COLUMN source_key text;
