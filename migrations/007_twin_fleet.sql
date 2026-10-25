CREATE TABLE twin_fleet (
    id integer PRIMARY KEY CHECK(id=1),
    configured boolean NOT NULL,
    fingerprint text NOT NULL,
    generation bigint NOT NULL DEFAULT 1,
    connected boolean NOT NULL DEFAULT false,
    snapshot jsonb,
    observed_at timestamptz,
    retired_scopes jsonb NOT NULL DEFAULT '[]'
);
