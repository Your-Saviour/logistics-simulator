package main

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"math"
	"strings"
	"time"
)

//go:embed migrations/*.sql
var migrations embed.FS

type Store struct {
	DB *pgxpool.Pool
	C  Config
}
type Audit struct{ RunID, Actor, Role, RequestID, Action, Key, Peer string }
type row = map[string]any

func object(ctx context.Context, tx pgx.Tx, sql string, args ...any) (row, error) {
	var raw []byte
	err := tx.QueryRow(ctx, "WITH r AS ("+sql+") SELECT row_to_json(r) FROM r", args...).Scan(&raw)
	if err != nil {
		return nil, err
	}
	var m row
	err = json.Unmarshal(raw, &m)
	return m, err
}
func objects(ctx context.Context, tx pgx.Tx, sql string, args ...any) ([]row, error) {
	rows, e := tx.Query(ctx, "WITH r AS ("+sql+") SELECT row_to_json(r) FROM r", args...)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	result := []row{}
	for rows.Next() {
		var raw []byte
		if e = rows.Scan(&raw); e != nil {
			return nil, e
		}
		var r row
		if e = json.Unmarshal(raw, &r); e != nil {
			return nil, e
		}
		result = append(result, r)
	}
	return result, rows.Err()
}
func (s *Store) transaction(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(8192103)"); e != nil {
		return e
	}
	if e = fn(tx); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func lockRun(ctx context.Context, tx pgx.Tx) (row, error) {
	for i := 0; i < 10; i++ {
		r, e := object(ctx, tx, "SELECT * FROM runs WHERE current FOR UPDATE")
		if !errors.Is(e, pgx.ErrNoRows) {
			return r, e
		}
	}
	return nil, Conflict("Current run changed repeatedly; retry the command")
}
func (s *Store) Migrate(ctx context.Context) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(8192101)"); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(8192103)"); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, "CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"); e != nil {
		return e
	}
	files, _ := migrations.ReadDir("migrations")
	for _, f := range files {
		raw, _ := migrations.ReadFile("migrations/" + f.Name())
		digest := sha256.Sum256(raw)
		checksum := hex.EncodeToString(digest[:])
		var old string
		e = tx.QueryRow(ctx, "SELECT checksum FROM schema_migrations WHERE name=$1", f.Name()).Scan(&old)
		if e == nil {
			if old != checksum {
				return Conflict("Applied migration was edited: " + f.Name())
			}
			continue
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if _, e = tx.Exec(ctx, string(raw)); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, "INSERT INTO schema_migrations(name,checksum) VALUES($1,$2)", f.Name(), checksum); e != nil {
			return e
		}
	}
	r, e := object(ctx, tx, "SELECT * FROM runs WHERE current")
	if errors.Is(e, pgx.ErrNoRows) {
		run, epoch := s.C.RunID, s.C.Epoch
		if s.C.Mode == "helics" && (run == "" || epoch == "") {
			return Conflict("Federation owner must supply run and epoch IDs")
		}
		if run == "" {
			run = uuid.NewString()
		}
		if epoch == "" {
			epoch = uuid.NewString()
		}
		raw, _ := json.Marshal(s.C.Scenario)
		r, e = object(ctx, tx, "INSERT INTO runs(id,epoch,mode,scenario) VALUES($1,$2,$3,$4) RETURNING *", run, epoch, s.C.Mode, raw)
	}
	if e != nil {
		return e
	}
	if r["mode"] != s.C.Mode {
		return Conflict("Persisted run mode differs; use a fresh deployment database")
	}
	if s.C.Mode == "helics" && (r["id"] != s.C.RunID || r["epoch"] != s.C.Epoch) {
		return Conflict("Persisted federation identity differs; archive and use a fresh database")
	}
	if len(r["scenario"].(map[string]any)) == 0 {
		raw, _ := json.Marshal(s.C.Scenario)
		if _, e = tx.Exec(ctx, "UPDATE runs SET scenario=$1 WHERE id=$2", raw, r["id"]); e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}
func (s *Store) Run(ctx context.Context) (r row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error { r, e = lockRun(ctx, tx); return e })
	return
}
func num(r row, k string) float64 { v, _ := r[k].(float64); return v }
func active(r row) bool           { return r["state"] == "running" || r["state"] == "held" }
func audit(ctx context.Context, tx pgx.Tx, run string, a *Audit, outcome string, status int, target any) error {
	if a == nil {
		return nil
	}
	_, e := tx.Exec(ctx, "INSERT INTO command_audit(id,run_id,actor,role,request_id,action,outcome,status_code,idempotency_key,peer,target_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)", uuid.NewString(), run, a.Actor, a.Role, a.RequestID, truncate(a.Action, 256), outcome, status, truncate(a.Key, 128), truncate(a.Peer, 128), target)
	return e
}
func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
func (s *Store) Reject(ctx context.Context, a *Audit, status int) error {
	// A rejected command retains its captured run/principal even when the client
	// disconnects after receiving the error. Bound this independent audit write.
	auditCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	return s.transaction(auditCtx, func(tx pgx.Tx) error { return audit(auditCtx, tx, a.RunID, a, "rejected", status, nil) })
}
func (s *Store) Status(ctx context.Context) (result row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		jobs, e := objects(ctx, tx, "SELECT * FROM jobs WHERE run_id=$1 ORDER BY created_at DESC LIMIT 100", r["id"])
		if e != nil {
			return e
		}
		heartbeats, e := objects(ctx, tx, "SELECT role,seen_at,detail,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats")
		if e != nil {
			return e
		}
		var effects, pending int
		if e = tx.QueryRow(ctx, "SELECT COALESCE(sum(quantity),0) FROM effects WHERE run_id=$1", r["id"]).Scan(&effects); e != nil {
			return e
		}
		if e = tx.QueryRow(ctx, "SELECT count(*) FROM boundary_outbox WHERE run_id=$1 AND sent_at IS NULL", r["id"]).Scan(&pending); e != nil {
			return e
		}
		result = row{"run": r, "jobs": jobs, "effects": effects, "heartbeats": heartbeats, "pending_boundary_outputs": pending}
		return nil
	})
	return
}
func (s *Store) Schedule(ctx context.Context, key string, j JobCommand, a *Audit, input row) (job row, e error) {
	if key == "" || len(key) > 128 || !finite(j.DueAt) || j.DueAt < 0 || j.Quantity < 1 || j.Quantity > 10000 {
		return nil, Conflict("Valid idempotency key, finite due time and quantity required")
	}
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if input != nil && (input["run_id"] != r["id"] || input["epoch"] != r["epoch"]) {
			return Conflict("Seeded input belongs to a different run or epoch")
		}
		old, e := object(ctx, tx, "SELECT * FROM jobs WHERE run_id=$1 AND idempotency_key=$2", r["id"], key)
		payload, _ := json.Marshal(row{"quantity": j.Quantity})
		var boundary any
		if input != nil {
			boundary, _ = json.Marshal(input)
		}
		if e == nil {
			oldInput, _ := json.Marshal(old["boundary_input"])
			newInput, _ := json.Marshal(input)
			if num(old, "original_due_at") != j.DueAt || num(old["payload"].(map[string]any), "quantity") != float64(j.Quantity) || string(oldInput) != string(newInput) {
				return Conflict("Idempotency key already used with a different command")
			}
			job = old
			return audit(ctx, tx, r["id"].(string), a, "accepted", 200, job["id"])
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if !active(r) || j.DueAt < math.Max(num(r, "granted"), num(r, "requested"))+s.C.Quantum {
			return Conflict("Schedule at least one quantum beyond granted/requested time in an active run")
		}
		job, e = object(ctx, tx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload,boundary_input) VALUES($1,$2,$3,$4,$5,$5,$6,$7) RETURNING *", uuid.NewString(), r["id"], r["epoch"], key, j.DueAt, payload, boundary)
		if e != nil {
			return e
		}
		return audit(ctx, tx, r["id"].(string), a, "accepted", 200, job["id"])
	})
	return
}
func outstanding(ctx context.Context, tx pgx.Tx, r row) (bool, error) {
	var busy bool
	e := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND due_at<=$2 AND status NOT IN ('completed','fenced')) OR EXISTS(SELECT 1 FROM boundary_outbox WHERE run_id=$1 AND sent_at IS NULL)", r["id"], r["granted"]).Scan(&busy)
	return busy, e
}
func (s *Store) Execute(ctx context.Context, id string) (result string, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		j, e := object(ctx, tx, "SELECT * FROM jobs WHERE id=$1 FOR UPDATE", id)
		if errors.Is(e, pgx.ErrNoRows) || e == nil && (j["run_id"] != r["id"] || j["epoch"] != r["epoch"]) {
			result = "fenced"
			return nil
		}
		if e != nil {
			return e
		}
		if j["status"] == "completed" {
			result = "duplicate"
			return nil
		}
		if j["status"] == "dead" {
			result = "dead"
			return nil
		}
		result = "waiting"
		if r["state"] != "running" || num(j, "due_at") > num(r, "granted") {
			return nil
		}
		var eligible bool
		if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM heartbeats WHERE role='controller' AND seen_at>clock_timestamp()-interval '15 seconds') AND retry_after<=clock_timestamp() FROM jobs WHERE id=$1", id).Scan(&eligible); e != nil {
			return e
		}
		if !eligible {
			return nil
		}
		if j["payload"].(map[string]any)["transport"] != nil {
			result = "completed"
			return executeTransport(ctx, tx, r, j)
		}
		quantity := num(j["payload"].(map[string]any), "quantity")
		if quantity < 1 || quantity > 10000 || quantity != math.Trunc(quantity) {
			return Conflict("Invalid persisted sample quantity")
		}
		if _, e = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", id, r["id"], r["epoch"]); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, "INSERT INTO effects(job_id,run_id,quantity) VALUES($1,$2,$3)", id, r["id"], int(quantity)); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, "UPDATE jobs SET status='completed',error=NULL WHERE id=$1", id); e != nil {
			return e
		}
		if r["mode"] == "helics" && !strings.HasPrefix(j["idempotency_key"].(string), "boundary:") {
			raw, _ := json.Marshal(row{"job_id": id, "quantity": int(quantity), "time": r["granted"]})
			if _, e = tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw); e != nil {
				return e
			}
		}
		result = "completed"
		return nil
	})
	return
}
func (s *Store) Fail(ctx context.Context, id, message string) (result string, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		j, e := object(ctx, tx, "SELECT * FROM jobs WHERE id=$1 FOR UPDATE", id)
		if errors.Is(e, pgx.ErrNoRows) || e == nil && (j["run_id"] != r["id"] || j["epoch"] != r["epoch"] || j["status"] == "completed") {
			result = "fenced"
			return nil
		}
		if e != nil {
			return e
		}
		attempts := int(num(j, "attempts")) + 1
		status := "pending"
		result = "retry"
		if attempts >= 3 || j["status"] == "dead" {
			status = "dead"
			result = "dead"
		}
		if _, e = tx.Exec(ctx, "UPDATE jobs SET attempts=$1,status=$2,error=$3,retry_after=clock_timestamp()+interval '2 seconds' WHERE id=$4", attempts, status, truncate(message, 1000), id); e != nil {
			return e
		}
		if status == "dead" {
			_, e = tx.Exec(ctx, "UPDATE runs SET state='failed',error='Job retry limit exceeded' WHERE id=$1", r["id"])
		}
		return e
	})
	return
}
func (s *Store) Heartbeat(ctx context.Context, role, detail string) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		_, e := tx.Exec(ctx, "INSERT INTO heartbeats(role,detail) VALUES($1,$2) ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp(),detail=EXCLUDED.detail", role, detail)
		return e
	})
}
func (s *Store) Grant(ctx context.Context, target float64, epoch string) (ok bool, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["epoch"] != epoch {
			return Conflict("Stale controller epoch")
		}
		if !active(r) || r["mode"] == "standalone" && r["state"] == "held" {
			return nil
		}
		if !finite(target) || target < num(r, "granted") || target > num(r, "requested") {
			return Conflict("Grant must be finite, monotonic and within the requested target")
		}
		_, e = tx.Exec(ctx, "UPDATE runs SET granted=$1,anchor=clock_timestamp() WHERE id=$2", target, r["id"])
		ok = e == nil
		return e
	})
	return
}
func (s *Store) Prepare(ctx context.Context, target float64, epoch string) (ok bool, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["epoch"] != epoch || r["state"] != "running" {
			return nil
		}
		busy, e := outstanding(ctx, tx, r)
		if e != nil || busy {
			return e
		}
		if !finite(target) || target <= num(r, "granted") {
			return Conflict("Next request must advance time")
		}
		if r["mode"] == "helics" {
			var ready bool
			err := tx.QueryRow(ctx, "SELECT native_state='executing' AND NOT pending AND NOT processing FROM logistics_adapter_sessions WHERE run_id=$1 AND epoch=$2", r["id"], r["epoch"]).Scan(&ready)
			if errors.Is(err, pgx.ErrNoRows) {
				return nil
			}
			if err != nil {
				return err
			}
			if !ready {
				return nil
			}
			if _, err = tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET pending=true WHERE run_id=$1 AND epoch=$2", r["id"], r["epoch"]); err != nil {
				return err
			}
		}
		_, e = tx.Exec(ctx, "UPDATE runs SET committed=granted,requested=$1 WHERE id=$2", target, r["id"])
		ok = e == nil
		return e
	})
	return
}
func (s *Store) Control(ctx context.Context, action string, speed int, confirmation string, a *Audit, scenario *Scenario) (value row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if scenario != nil && action != "reset" {
			return Conflict("Scenario changes require a confirmed new run")
		}
		switch action {
		case "reset":
			if confirmation == "" || confirmation != r["id"] {
				return Conflict("Reset confirmation does not match the current run")
			}
			if r["mode"] == "helics" {
				return Conflict("Finalize the federation and allocate a new deployment run/epoch; live reset is forbidden")
			}
			raw, _ := json.Marshal(r["scenario"])
			if scenario != nil {
				if e = scenario.Validate(); e != nil {
					return e
				}
				raw, _ = json.Marshal(scenario)
			}
			if _, e = tx.Exec(ctx, "UPDATE runs SET current=false WHERE id=$1", r["id"]); e != nil {
				return e
			}
			_, e = tx.Exec(ctx, "INSERT INTO runs(id,epoch,mode,scenario) VALUES($1,$2,$3,$4)", uuid.NewString(), uuid.NewString(), s.C.Mode, raw)
		case "hold", "resume":
			if !active(r) {
				return Conflict("Cannot resume a failed, stalled or finalized run")
			}
			state := "running"
			if action == "hold" {
				state = "held"
			}
			_, e = tx.Exec(ctx, "UPDATE runs SET state=$1,anchor=clock_timestamp() WHERE id=$2", state, r["id"])
		case "speed":
			if r["mode"] != "standalone" || (speed != 1 && speed != 5 && speed != 20 && speed != 60) {
				return Conflict("Only standalone speeds 1, 5, 20, 60 are supported")
			}
			_, e = tx.Exec(ctx, "UPDATE runs SET speed=$1,anchor=clock_timestamp() WHERE id=$2", speed, r["id"])
		case "finalize":
			if r["mode"] == "helics" {
				if !active(r) {
					return Conflict("Only an active connected run can begin finalization")
				}
				var ready bool
				err := tx.QueryRow(ctx, "SELECT native_state='executing' AND NOT pending AND NOT processing FROM logistics_adapter_sessions WHERE run_id=$1 AND epoch=$2", r["id"], r["epoch"]).Scan(&ready)
				if errors.Is(err, pgx.ErrNoRows) || err == nil && !ready {
					return Conflict("Native initialization, time request or processing is pending; settle before finalizing")
				}
				if err != nil {
					return err
				}
			}
			busy, err := outstanding(ctx, tx, r)
			if err != nil {
				return err
			}
			if busy {
				return Conflict("Hold and settle current-time work before finalizing")
			}
			if r["mode"] == "helics" {
				// The run lock serializes this intent with native processing
				// and time preparation. Native acknowledgement completes it.
				if _, e = tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET native_state='finalizing',pending=true,processing=false WHERE run_id=$1 AND epoch=$2", r["id"], r["epoch"]); e != nil {
					return e
				}
				_, e = tx.Exec(ctx, "UPDATE runs SET state='finalizing' WHERE id=$1", r["id"])
			} else {
				_, e = tx.Exec(ctx, "UPDATE runs SET state='finalized' WHERE id=$1", r["id"])
			}
		default:
			return Conflict("Unknown control")
		}
		if e != nil {
			return e
		}
		return audit(ctx, tx, r["id"].(string), a, "accepted", 200, nil)
	})
	if e == nil {
		value, e = s.Status(ctx)
	}
	return
}
func (s *Store) Dispatchable(ctx context.Context) (rows []row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		rows = []row{}
		if r["state"] != "running" {
			return nil
		}
		_, e = tx.Exec(ctx, "INSERT INTO outbox(id,job_id,run_id) SELECT gen_random_uuid(),id,run_id FROM jobs WHERE run_id=$1 AND epoch=$2 AND due_at<=$3 AND status IN ('pending','queued') AND retry_after<=clock_timestamp() ON CONFLICT(job_id) DO NOTHING", r["id"], r["epoch"], r["granted"])
		if e != nil {
			return e
		}
		rows, e = objects(ctx, tx, "SELECT o.id,o.job_id FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.run_id=$1 AND j.epoch=$2 AND j.status IN ('pending','queued') AND j.due_at<=$3 AND j.retry_after<=clock_timestamp() AND o.retry_after<=clock_timestamp()", r["id"], r["epoch"], r["granted"])
		return e
	})
	return
}
func (s *Store) Published(ctx context.Context, id string) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "UPDATE outbox SET sent_at=clock_timestamp(),retry_after=clock_timestamp()+interval '5 seconds' WHERE id=$1 AND run_id=$2", id, r["id"])
		return e
	})
}
func (s *Store) Seed(ctx context.Context) error { return s.SeedTransport(ctx) }
func (s *Store) Stall(ctx context.Context, epoch, message string) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["epoch"] != epoch || (!active(r) && r["state"] != "finalizing") {
			return nil
		}
		_, e = tx.Exec(ctx, "UPDATE runs SET state='stalled',error=$1 WHERE id=$2", truncate(message, 1000), r["id"])
		return e
	})
}
func (s *Store) AuditEvents(ctx context.Context) (rows []row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		var e error
		rows, e = objects(ctx, tx, "SELECT * FROM command_audit ORDER BY recorded_at DESC,id DESC LIMIT 100")
		return e
	})
	return
}
func stringify(v any) string { return fmt.Sprint(v) }
