package main

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"math"
	"strings"
)

func ensureTransport(ctx context.Context, tx pgx.Tx, r row) error {
	// Freeze defaults once when opening a pre-V1 run; later builds do not redefine its routes.
	if r["scenario"].(map[string]any)["transport"] == nil {
		scenario := scenarioFrom(r)
		raw, _ := json.Marshal(scenario)
		if _, e := tx.Exec(ctx, "UPDATE runs SET scenario=$1 WHERE id=$2", raw, r["id"]); e != nil {
			return e
		}
		var persisted row
		json.Unmarshal(raw, &persisted)
		r["scenario"] = persisted
	}

	for _, v := range transportConfig(r).Vehicles {
		if _, e := tx.Exec(ctx, "INSERT INTO transport_vehicles(run_id,code,capacity,location) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING", r["id"], v.Code, v.Capacity, v.Location); e != nil {
			return e
		}
	}
	return nil
}
func (s *Store) Transport(ctx context.Context) (result row, e error) {
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, err := lockRun(ctx, tx)
		if err != nil {
			return err
		}
		if err = ensureTransport(ctx, tx, r); err != nil {
			return err
		}
		result = row{"configuration": transportConfig(r)}
		handling, err := handlingSnapshot(ctx, tx, r)
		if err != nil {
			return err
		}
		result["handling"] = handling
		queries := map[string]string{
			"vehicles":  "SELECT v.*,t.id AS transfer_id FROM transport_vehicles v LEFT JOIN transport_transfers t ON t.run_id=v.run_id AND t.vehicle=v.code AND t.status IN ('assigned','loaded','in_transit','arrived') WHERE v.run_id=$1 ORDER BY v.code",
			"transfers": "SELECT * FROM transport_transfers WHERE run_id=$1 ORDER BY id",
			"commands":  "SELECT c.*,j.due_at,j.status AS job_status,j.attempts FROM transport_commands c JOIN jobs j ON j.id=c.id WHERE c.run_id=$1 ORDER BY j.created_at DESC LIMIT 100",
			"movements": "SELECT * FROM transport_movements WHERE run_id=$1 ORDER BY simulation_time DESC,id LIMIT 100"}
		for k, q := range queries {
			v, err := objects(ctx, tx, q, r["id"])
			if err != nil {
				return err
			}
			result[k] = v
		}
		return nil
	})
	return
}
func transportJob(ctx context.Context, tx pgx.Tx, r row, key string, c TransportCommand, a *Audit, provider bool) (job row, e error) {
	raw, _ := json.Marshal(c)
	old, err := object(ctx, tx, "SELECT c.*,j.idempotency_key FROM transport_commands c JOIN jobs j ON j.id=c.id WHERE c.run_id=$1 AND j.idempotency_key=$2", r["id"], key)
	if err == nil {
		oldRaw, _ := json.Marshal(old["command"])
		var expected any
		json.Unmarshal(raw, &expected)
		canonical, _ := json.Marshal(expected)
		if string(oldRaw) != string(canonical) {
			return nil, Conflict("Idempotency key already used for a different transport command")
		}
		return old, audit(ctx, tx, r["id"].(string), a, "accepted", 200, old["id"])
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	if c.RunID != r["id"] || c.Epoch != r["epoch"] {
		return nil, Conflict("Transport command belongs to a different run or epoch")
	}
	var occupiedKey bool
	if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND idempotency_key=$2)", r["id"], key).Scan(&occupiedKey); err != nil {
		return nil, err
	}
	if occupiedKey {
		return nil, Conflict("Idempotency key already used for another job type")
	}
	if !active(r) || c.DueAt <= num(r, "granted") {
		return nil, Conflict("Transport commands must be scheduled beyond granted/requested time in an active run")
	}
	id := uuid.NewString()
	payload, _ := json.Marshal(row{"transport": c})
	if _, e = tx.Exec(ctx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES($1,$2,$3,$4,$5,$5,$6)", id, r["id"], r["epoch"], key, c.DueAt, payload); e != nil {
		return nil, e
	}
	job, e = object(ctx, tx, "INSERT INTO transport_commands(id,run_id,command,provider) VALUES($1,$2,$3,$4) RETURNING *", id, r["id"], raw, provider)
	if e != nil {
		return nil, e
	}
	return job, audit(ctx, tx, r["id"].(string), a, "accepted", 200, id)
}
func (s *Store) ScheduleTransport(ctx context.Context, key string, c TransportCommand, a *Audit) (job row, e error) {
	if key == "" || len(key) > 128 {
		return nil, Conflict("Valid idempotency key required")
	}
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, err := lockRun(ctx, tx)
		if err != nil {
			return err
		}
		if err = ensureTransport(ctx, tx, r); err != nil {
			return err
		}
		// Replays remain valid after completion, but never cross a run/epoch boundary.
		if c.RunID != r["id"] || c.Epoch != r["epoch"] {
			return Conflict("Stale transport run or epoch")
		}
		var exists bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND idempotency_key=$2)", r["id"], key).Scan(&exists); err != nil {
			return err
		}
		if !exists && c.DueAt < math.Max(num(r, "granted"), num(r, "requested"))+s.C.Quantum {
			return Conflict("Schedule at least one quantum beyond granted/requested time")
		}
		job, err = transportJob(ctx, tx, r, key, c, a, false)
		return err
	})
	return
}
func (s *Store) executeTransport(ctx context.Context, tx pgx.Tx, r, j row) error {
	var c TransportCommand
	raw, _ := json.Marshal(j["payload"].(map[string]any)["transport"])
	if e := json.Unmarshal(raw, &c); e != nil {
		return e
	}
	save, e := tx.Begin(ctx)
	if e != nil {
		return e
	}
	e = s.applyTransport(ctx, save, r, j, c)
	var wait fleetWait
	if errors.As(e, &wait) {
		if failure := save.Commit(ctx); failure != nil {
			return failure
		}
		return fleetDefer(ctx, tx, r, j, s.C.Quantum)
	}
	var conflict Conflict
	if errors.As(e, &conflict) {
		if err := save.Rollback(ctx); err != nil {
			return err
		}
		_, e = tx.Exec(ctx, "UPDATE transport_commands SET status='rejected',reason=$1,completed_at=$2 WHERE id=$3", string(conflict), r["granted"], j["id"])
	} else if e != nil {
		save.Rollback(ctx)
		return e
	} else {
		if e = save.Commit(ctx); e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "UPDATE transport_commands SET status='completed',reason=NULL,completed_at=$1 WHERE id=$2", r["granted"], j["id"])
	}
	if e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", j["id"], r["id"], r["epoch"]); e != nil {
		return e
	}
	_, e = tx.Exec(ctx, "UPDATE jobs SET status='completed',error=NULL WHERE id=$1", j["id"])
	return e
}
func (s *Store) applyTransport(ctx context.Context, tx pgx.Tx, r, j row, c TransportCommand) error {
	if e := ensureTransport(ctx, tx, r); e != nil {
		return e
	}
	if c.Action == "handoff" {
		return s.beginSourceCustody(ctx, tx, r, j, c)
	}
	if c.Action == "intake" {
		return intakeHandling(ctx, tx, r, j, c)
	}
	id := c.Reference
	if c.Action == "request" {
		var route *Route
		for _, v := range transportConfig(r).Routes {
			if v.Code == c.Route {
				v := v
				route = &v
				break
			}
		}
		if route == nil {
			return Conflict("Unknown transport route")
		}
		var provider bool
		if e := tx.QueryRow(ctx, "SELECT provider FROM transport_commands WHERE id=$1", j["id"]).Scan(&provider); e != nil {
			return e
		}
		var external any
		if c.ExternalReference != "" {
			external = c.ExternalReference
		}
		id = j["id"].(string)
		if _, e := tx.Exec(ctx, "INSERT INTO transport_transfers(id,run_id,epoch,correlation_id,external_reference,route,origin,destination,journey_seconds,sku,quantity,status,custody,provider) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'requested','origin',$12)", id, r["id"], r["epoch"], c.CorrelationID, external, route.Code, route.Origin, route.Destination, route.JourneySeconds, c.SKU, c.Quantity, provider); e != nil {
			return e
		}
		if c.CustomerDestination != "" {
			if _, err := tx.Exec(ctx, "UPDATE transport_transfers SET customer_destination=$1 WHERE id=$2", c.CustomerDestination, id); err != nil {
				return err
			}
		}
		transfer, err := object(ctx, tx, "SELECT * FROM transport_transfers WHERE id=$1", id)
		if err != nil {
			return err
		}
		if len(c.ExpectedUnits) > 0 {
			err = planExpectedUnits(ctx, tx, r, transfer, c)
		} else {
			err = reserveHandling(ctx, tx, r, transfer, c)
		}
		if err != nil {
			return err
		}
		ids, _ := json.Marshal(c.UnitIDs)
		if _, err = tx.Exec(ctx, "UPDATE transport_transfers SET unit_ids=$1 WHERE id=$2", ids, id); err != nil {
			return err
		}
	} else {
		tr, e := object(ctx, tx, "SELECT * FROM transport_transfers WHERE id=$1 AND run_id=$2 FOR UPDATE", id, r["id"])
		if errors.Is(e, pgx.ErrNoRows) {
			return Conflict("Unknown transfer in this run")
		}
		if e != nil {
			return e
		}
		want := map[string]string{"assign": "requested", "load": "assigned", "depart": "loaded", "arrive": "in_transit", "unload": "arrived", "receive": "unloaded"}[c.Action]
		if tr["status"] != want {
			return Conflict("Transfer cannot " + c.Action + " from " + tr["status"].(string))
		}
		switch c.Action {
		case "assign":
			v, e := object(ctx, tx, "SELECT * FROM transport_vehicles WHERE run_id=$1 AND code=$2", r["id"], c.Vehicle)
			if errors.Is(e, pgx.ErrNoRows) {
				return Conflict("Unknown vehicle")
			}
			if e != nil {
				return e
			}
			var expected bool
			if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_expected_units WHERE transfer_id=$1 AND active)", id).Scan(&expected); err != nil {
				return err
			}
			if expected {
				physical := false
				for index, configured := range transportConfig(r).Vehicles {
					if configured.Code == c.Vehicle && index < 4 {
						physical = true
					}
				}
				if !physical {
					return Conflict("Expected custody requires a vehicle with fixed physical truck slots")
				}
			}
			if v["location"] != tr["origin"] || num(v, "capacity") < num(tr, "quantity") {
				return Conflict("Vehicle is at another location or load exceeds capacity")
			}
			var occupied bool
			if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_transfers WHERE run_id=$1 AND vehicle=$2 AND status IN ('assigned','loaded','in_transit','arrived'))", r["id"], c.Vehicle).Scan(&occupied); e != nil {
				return e
			}
			if occupied {
				return Conflict("Vehicle already reserved by another transfer")
			}
			if err := reserveExpectedDestinations(ctx, tx, r, tr); err != nil {
				return err
			}
			_, e = tx.Exec(ctx, "UPDATE transport_transfers SET vehicle=$1,status='assigned',version=version+1 WHERE id=$2", c.Vehicle, id)
			if e != nil {
				return e
			}
		case "load":
			if e = loadHandling(ctx, tx, r, j, tr); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, "UPDATE transport_transfers SET status='loaded',custody='vehicle',version=version+1 WHERE id=$1", id); e != nil {
				return e
			}
		case "depart":
			if e = departHandling(ctx, tx, r, tr); e != nil {
				return e
			}
			eta := num(r, "granted") + num(tr, "journey_seconds")
			if _, e = tx.Exec(ctx, "UPDATE transport_transfers SET status='in_transit',departed_at=$1,planned_eta=$2,version=version+1 WHERE id=$3", r["granted"], eta, id); e != nil {
				return e
			}
			_, e = transportJob(ctx, tx, r, "transport:arrival:"+id, TransportCommand{RunID: r["id"].(string), Epoch: r["epoch"].(string), DueAt: eta, Action: "arrive", Reference: id}, nil, true)
			if e != nil {
				return e
			}
		case "arrive":
			if num(r, "granted") < num(tr, "planned_eta") {
				return Conflict("Journey has not reached planned ETA")
			}
			if _, e = tx.Exec(ctx, "UPDATE transport_transfers SET status='arrived',arrived_at=$1,version=version+1 WHERE id=$2", r["granted"], id); e != nil {
				return e
			}
		case "unload":
			if e = unloadHandling(ctx, tx, r, j, tr); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, "UPDATE transport_transfers SET status='unloaded',custody='destination',unloaded_at=$1,version=version+1 WHERE id=$2", r["granted"], id); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, "UPDATE transport_vehicles SET location=$1 WHERE run_id=$2 AND code=$3", tr["destination"], r["id"], tr["vehicle"]); e != nil {
				return e
			}
		case "receive":
			if e = receiveHandling(ctx, tx, tr); e != nil {
				return e
			}
			if _, e = tx.Exec(ctx, "UPDATE transport_transfers SET status='received',received_at=$1,version=version+1 WHERE id=$2", r["granted"], id); e != nil {
				return e
			}
		}
	}
	tr, e := object(ctx, tx, "SELECT * FROM transport_transfers WHERE id=$1", id)
	if e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, "INSERT INTO transport_movements(id,transfer_id,run_id,command_id,action,simulation_time,quantity,custody,version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)", uuid.NewString(), id, r["id"], j["id"], c.Action, r["granted"], int(num(tr, "quantity")), tr["custody"], int(num(tr, "version"))); e != nil {
		return e
	}
	if r["mode"] == "helics" {
		raw, _ := json.Marshal(row{"type": "logistics." + c.Action + ".completed.v1", "transfer": tr, "command_id": j["id"], "time": r["granted"]})
		_, e = tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw)
	}
	return e
}
func reservedTransportKey(key string) bool {
	return strings.HasPrefix(key, "transport:") || strings.HasPrefix(key, "synthetic:") || strings.HasPrefix(key, "boundary:") || strings.HasPrefix(key, "synthetic-sample:")
}
