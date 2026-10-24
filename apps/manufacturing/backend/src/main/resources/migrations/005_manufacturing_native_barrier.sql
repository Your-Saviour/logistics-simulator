-- A SQL completion barrier must include native initialization, time and receive work.
ALTER TABLE manufacturing_adapter_sessions ADD COLUMN IF NOT EXISTS native_pending boolean NOT NULL DEFAULT true;
ALTER TABLE manufacturing_adapter_sessions ADD COLUMN IF NOT EXISTS native_state text NOT NULL DEFAULT 'initializing';
