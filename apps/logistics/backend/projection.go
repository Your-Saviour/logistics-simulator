package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"

	"github.com/jackc/pgx/v5"
)

// Projection reads a complete replacement under the run lock shared by domain writers.
// Unlike the interactive snapshot, this observer never initializes business records.
func (s *Store) Projection(ctx context.Context) (result row, err error) {
	err = s.transaction(ctx, func(tx pgx.Tx) error {
		run, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		snapshot := row{"configuration": transportConfig(run), "run_id": run["id"], "epoch": run["epoch"]}
		queries := map[string]string{
			"vehicles":  "SELECT v.*,t.id AS transfer_id FROM transport_vehicles v LEFT JOIN transport_transfers t ON t.run_id=v.run_id AND t.vehicle=v.code AND t.status IN ('assigned','loaded','in_transit','arrived') WHERE v.run_id=$1 ORDER BY v.code",
			"transfers": "SELECT * FROM transport_transfers WHERE run_id=$1 ORDER BY id",
			"commands":  "SELECT c.*,j.due_at,j.status AS job_status,j.attempts FROM transport_commands c JOIN jobs j ON j.id=c.id WHERE c.run_id=$1 ORDER BY j.created_at,c.id",
			"movements": "SELECT m.*,t.correlation_id FROM transport_movements m JOIN transport_transfers t ON t.id=m.transfer_id WHERE m.run_id=$1 ORDER BY m.simulation_time,m.id",
		}
		for key, query := range queries {
			values, e := objects(ctx, tx, query, run["id"])
			if e != nil {
				return e
			}
			snapshot[key] = values
		}
		events := []row{}
		for _, movement := range snapshot["movements"].([]row) {
			event := row{}
			for k, v := range movement {
				event[k] = v
			}
			event["id"] = "logistics:movement:" + movement["id"].(string)
			event["kind"] = "movement"
			events = append(events, event)
		}
		var effects int64
		if e := tx.QueryRow(ctx, "SELECT COALESCE(sum(quantity),0) FROM effects WHERE run_id=$1", run["id"]).Scan(&effects); e != nil {
			return e
		}
		result = row{"effects": effects, "version": 1, "source": "logistics", "run": run, "snapshot": snapshot, "events": events}
		heartbeats, e := objects(ctx, tx, "SELECT role,seen_at,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats ORDER BY role")
		if e != nil {
			return e
		}
		var pending, dead int64
		if e = tx.QueryRow(ctx, "SELECT count(*) FILTER (WHERE status IN ('pending','queued')),count(*) FILTER (WHERE status='dead') FROM jobs WHERE run_id=$1", run["id"]).Scan(&pending, &dead); e != nil {
			return e
		}
		result["health"] = row{"heartbeats": heartbeats, "pending_jobs": pending, "dead_letters": dead, "broker": nil, "ready": nil}
		raw, e := json.Marshal(result)
		if e != nil {
			return e
		}
		sum := sha256.Sum256(raw)
		result["cursor"] = hex.EncodeToString(sum[:])
		return nil
	})
	return
}
