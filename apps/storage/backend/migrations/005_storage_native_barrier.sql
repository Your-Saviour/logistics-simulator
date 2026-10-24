ALTER TABLE storage_adapter_sessions ADD COLUMN IF NOT EXISTS native_pending boolean NOT NULL DEFAULT true;
ALTER TABLE storage_adapter_sessions ADD COLUMN IF NOT EXISTS native_state text NOT NULL DEFAULT 'initializing';
