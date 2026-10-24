package main

import (
	"context"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"math"
)

// Explicit providers schedule the same durable commands as employees. No peer-loss fallback.
func (s *Store) SeedTransport(ctx context.Context) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["state"] != "running" {
			return nil
		}
		if e = ensureTransport(ctx, tx, r); e != nil {
			return e
		}
		due := math.Max(num(r, "granted"), num(r, "requested")) + s.C.Quantum
		schedule := func(key, action, reference, vehicle string) error {
			_, err := transportJob(ctx, tx, r, key, TransportCommand{RunID: r["id"].(string), Epoch: r["epoch"].(string), DueAt: due, Action: action, Reference: reference, Vehicle: vehicle}, nil, true)
			return err
		}
		if s.C.Providers["transport"] == "synthetic" {
			scenario := scenarioFrom(r)
			interval := float64(scenario.IntervalSeconds)
			slot := int(math.Max(1, math.Ceil(due/interval)))
			seedDue, err := nextBusinessDue(scenario, float64((slot-1)*scenario.IntervalSeconds), interval)
			if err != nil {
				return err
			}
			slot = int(math.Ceil(seedDue / interval))
			input := seededInput(scenario, r["id"].(string), r["epoch"].(string), "transport", slot, seedDue)
			key := "transport:demand:" + input["input_id"].(string)
			var exists bool
			if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND idempotency_key=$2)", r["id"], key).Scan(&exists); err != nil {
				return err
			}
			if !exists {
				cfg := transportConfig(r)
				route := cfg.Routes[(slot-1)%len(cfg.Routes)]
				unitID := uuid.NewSHA1(uuid.MustParse(input["input_id"].(string)), []byte("whole-unit")).String()
				intakeKey := "transport:intake:" + input["input_id"].(string)
				var supplied bool
				if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND idempotency_key=$2)", r["id"], intakeKey).Scan(&supplied); err != nil {
					return err
				}
				if !supplied {
					if _, err = transportJob(ctx, tx, r, intakeKey, TransportCommand{RunID: r["id"].(string), Epoch: r["epoch"].(string), DueAt: seedDue, Action: "intake", SKU: "PRODUCT", Quantity: input["quantity"].(int), Category: "finished", Location: route.Origin, CorrelationID: input["input_id"].(string), Units: []HandlingManifest{{ID: unitID, Quantity: input["quantity"].(int)}}}, nil, true); err != nil {
						return err
					}
				}
				_, err = transportJob(ctx, tx, r, key, TransportCommand{RunID: r["id"].(string), Epoch: r["epoch"].(string), DueAt: seedDue + s.C.Quantum, Action: "request", Route: route.Code, SKU: "PRODUCT", Quantity: input["quantity"].(int), CorrelationID: input["input_id"].(string), UnitIDs: []string{unitID}}, nil, true)
				if err != nil {
					return err
				}
			}
		}
		transfers, e := objects(ctx, tx, "SELECT * FROM transport_transfers WHERE run_id=$1 AND status!='received' ORDER BY id", r["id"])
		if e != nil {
			return e
		}
		for _, tr := range transfers {
			action := ""
			vehicle := ""
			if tr["provider"] == true && tr["status"] == "unloaded" && s.C.Providers["destinations"] == "synthetic" {
				action = "receive"
			} else if tr["provider"] == true {
				switch tr["status"] {
				case "requested":
					available, err := objects(ctx, tx, "SELECT v.code FROM transport_vehicles v WHERE v.run_id=$1 AND v.location=$2 AND v.capacity>=$3 AND NOT EXISTS(SELECT 1 FROM transport_transfers t WHERE t.run_id=v.run_id AND t.vehicle=v.code AND t.status IN ('assigned','loaded','in_transit','arrived')) ORDER BY v.code", r["id"], tr["origin"], int(num(tr, "quantity")))
					if err != nil {
						return err
					}
					var planned bool
					if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_expected_units WHERE transfer_id=$1 AND active)", tr["id"]).Scan(&planned); err != nil {
						return err
					}
					physical := map[string]bool{}
					for index, v := range transportConfig(r).Vehicles {
						if index < 4 {
							physical[v.Code] = true
						}
					}
					for _, candidate := range available {
						code := candidate["code"].(string)
						if !planned || physical[code] {
							action = "assign"
							vehicle = code
							break
						}
					}
				case "assigned":
					var missing bool
					if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_expected_units WHERE transfer_id=$1 AND active AND state='expected')", tr["id"]).Scan(&missing); err != nil {
						return err
					}
					if !missing {
						action = "load"
					}
				case "loaded":
					action = "depart"
				case "arrived":
					action = "unload"
				}
			}
			if action == "" {
				continue
			}
			reference := tr["id"].(string)
			var rejected int
			if e = tx.QueryRow(ctx, "SELECT count(*) FROM transport_commands WHERE run_id=$1 AND provider AND command->>'reference'=$2 AND command->>'action'=$3 AND status='rejected'", r["id"], reference, action).Scan(&rejected); e != nil {
				return e
			}
			key := fmt.Sprintf("transport:provider:%s:%s:%g:%d", reference, action, num(tr, "version"), rejected)
			var exists bool
			if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=$1 AND idempotency_key=$2)", r["id"], key).Scan(&exists); e != nil {
				return e
			}
			if exists {
				continue
			}
			// Two pending provider assignments cannot claim the same free vehicle.
			if action == "assign" {
				var pending bool
				if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_commands WHERE run_id=$1 AND status='pending' AND command->>'action'='assign' AND command->>'vehicle'=$2)", r["id"], vehicle).Scan(&pending); e != nil {
					return e
				}
				if pending {
					continue
				}
			}
			if e = schedule(key, action, reference, vehicle); e != nil {
				return e
			}
		}
		return nil
	})
}
