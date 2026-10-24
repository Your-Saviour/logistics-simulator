-- Immutable observed identities survive source retirement and epoch changes.
CREATE TABLE twin_unit_manifests (
    unit_id text PRIMARY KEY,
    barcode text UNIQUE NOT NULL,
    manifest jsonb NOT NULL,
    first_source text NOT NULL REFERENCES twin_sources(name),
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE twin_sources ADD COLUMN handling_conflicts jsonb NOT NULL DEFAULT '[]';
