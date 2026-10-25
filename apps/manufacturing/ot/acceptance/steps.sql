-- Read-only check: every completed logical interval occurs exactly once and no
-- request/grant skips an equipment second. The unique deployment owns this DB.
DO $$
DECLARE bad integer;
BEGIN
 SELECT count(*) INTO bad FROM (
   SELECT run_id, (request->'payload'->>'simulation_time')::bigint AS target,
          row_number() OVER (PARTITION BY run_id ORDER BY (request->'payload'->>'simulation_time')::bigint) AS ordinal
   FROM ot_operations WHERE operation='step' AND status='completed'
 ) steps WHERE target <> ordinal;
 IF bad <> 0 THEN RAISE EXCEPTION 'Equipment intervals skipped or replayed: %', bad; END IF;
 IF EXISTS (SELECT 1 FROM ot_cells c JOIN runs r ON r.id=c.run_id WHERE c.settled>floor(r.granted)) THEN
   RAISE EXCEPTION 'Equipment exceeded actual persisted grant';
 END IF;
END $$;
