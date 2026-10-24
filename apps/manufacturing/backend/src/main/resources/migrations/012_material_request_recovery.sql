CREATE TABLE production_material_requests (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 batch_id uuid NOT NULL REFERENCES production_orders(id), release_id uuid NOT NULL REFERENCES production_commands(id),
 payload jsonb NOT NULL, correlation_id uuid NOT NULL, generation integer NOT NULL DEFAULT 0 CHECK(generation>=0),
 state text NOT NULL CHECK(state IN ('requested','reserved','received','retry_pending','release_pending','blocked')), reason text
);
CREATE TABLE production_material_attempts (
 event_id uuid PRIMARY KEY, request_id uuid NOT NULL REFERENCES production_material_requests(id),
 generation integer NOT NULL CHECK(generation>=0), aggregate_id uuid NOT NULL UNIQUE,
 envelope jsonb NOT NULL, state text NOT NULL CHECK(state IN ('requested','reserved','received','rejected','released')), outcome jsonb,
 UNIQUE(request_id,generation)
);
CREATE TABLE production_material_failures (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id), epoch uuid NOT NULL,
 envelope jsonb NOT NULL, command_id uuid REFERENCES production_commands(id),
 state text NOT NULL CHECK(state IN ('queued','applied','quarantined')), reason text
);
CREATE TABLE production_material_releases (
 event_id uuid PRIMARY KEY, request_id uuid NOT NULL REFERENCES production_material_requests(id),
 reservation_id uuid NOT NULL REFERENCES production_material_plans(id), envelope jsonb NOT NULL,
 state text NOT NULL CHECK(state IN ('requested','released','rejected')), outcome jsonb
);
-- Preserve native requests already emitted by the preceding additive version.
INSERT INTO production_material_requests(id,run_id,epoch,batch_id,release_id,payload,correlation_id,state)
SELECT DISTINCT (b.envelope->>'aggregate_id')::uuid,b.run_id,(b.envelope->>'epoch')::uuid,
 (c.command->>'reference')::uuid,c.id,b.envelope->'payload',(b.envelope->>'correlation_id')::uuid,'requested'
FROM boundary_outbox b JOIN production_commands c ON c.id::text=b.envelope->>'causation_id' AND c.run_id=b.run_id
WHERE b.envelope->>'type'='storage.request.v1' AND c.command->>'action'='release';
INSERT INTO production_material_attempts(event_id,request_id,generation,aggregate_id,envelope,state)
SELECT DISTINCT (b.envelope->>'event_id')::uuid,r.id,0,r.id,b.envelope,'requested'
FROM boundary_outbox b JOIN production_material_requests r ON r.id::text=b.envelope->>'aggregate_id'
WHERE b.envelope->>'type'='storage.request.v1';
UPDATE production_material_attempts a SET state=CASE WHEN p.status='received' THEN 'received' ELSE 'reserved' END
FROM production_material_plans p WHERE p.fact->>'causation_id'=a.event_id::text;
UPDATE production_material_requests r SET state=a.state
FROM production_material_attempts a WHERE a.request_id=r.id AND a.generation=r.generation;
