-- Twin-owned read model only. Departmental schemas/ledgers are never queried.
CREATE TABLE twin_sources (
 name text PRIMARY KEY,
 website_url text,
 configured boolean NOT NULL DEFAULT true,
 connected boolean NOT NULL DEFAULT false,
 status jsonb,
 snapshot jsonb,
 cursor text,
 observed_at timestamptz,
 last_success_at timestamptz,
 error text,
 retired_epochs jsonb NOT NULL DEFAULT '[]',
 generation bigint NOT NULL DEFAULT 0
);
CREATE TABLE twin_events (
 source text NOT NULL REFERENCES twin_sources(name),
 run_id text NOT NULL,
 epoch text NOT NULL,
 id text NOT NULL,
 payload jsonb NOT NULL,
 PRIMARY KEY(source,run_id,epoch,id)
);
CREATE TABLE twin_revisions (
 id bigserial PRIMARY KEY,
 source text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX twin_event_scope ON twin_events(source,run_id,epoch);
