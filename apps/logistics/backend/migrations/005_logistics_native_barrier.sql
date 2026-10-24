-- Native state is metadata, never a promise of SQL-to-HELICS reconstruction.
ALTER TABLE logistics_adapter_sessions ADD COLUMN IF NOT EXISTS native_state text NOT NULL DEFAULT 'initializing';
ALTER TABLE logistics_adapter_sessions ADD COLUMN IF NOT EXISTS pending boolean NOT NULL DEFAULT true;
ALTER TABLE logistics_adapter_sessions ADD COLUMN IF NOT EXISTS processing boolean NOT NULL DEFAULT false;
