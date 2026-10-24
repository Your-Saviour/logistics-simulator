package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"log"
	"time"
)

func (s *Store) advanceLocal(ctx context.Context) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["state"] != "running" {
			return nil
		}
		busy, e := outstanding(ctx, tx, r)
		if e != nil || busy {
			return e
		}
		var due bool
		if e = tx.QueryRow(ctx, "SELECT extract(epoch FROM clock_timestamp()-anchor)*speed >= $1 FROM runs WHERE id=$2", s.C.Quantum, r["id"]).Scan(&due); e != nil {
			return e
		}
		if !due {
			return nil
		}
		_, e = tx.Exec(ctx, "UPDATE runs SET committed=granted,requested=granted+$1,granted=granted+$1,anchor=clock_timestamp() WHERE id=$2", s.C.Quantum, r["id"])
		return e
	})
}
func controller(ctx context.Context, s *Store) error {
	for ctx.Err() == nil {
		lease, e := s.DB.Acquire(ctx)
		if e != nil {
			logDependency("controller database", e)
			if !pause(ctx, time.Second) {
				return nil
			}
			continue
		}
		var held bool
		e = lease.QueryRow(ctx, "SELECT pg_try_advisory_lock(8192102)").Scan(&held)
		if e != nil || !held {
			lease.Release()
			if e != nil {
				if !pause(ctx, time.Second) {
					return nil
				}
				continue
			}
			return errors.New("another controller owns this simulator")
		}
		r, e := s.Run(ctx)
		if e != nil {
			lease.Conn().Close(ctx)
			lease.Release()
			if !pause(ctx, time.Second) {
				return nil
			}
			continue
		}
		epoch := r["epoch"].(string)
		var adapter *Adapter
		if s.C.Mode == "helics" {
			adapter, e = newAdapter(ctx, s, r)
			if e != nil {
				s.Stall(ctx, epoch, e.Error())
				lease.Conn().Close(ctx)
				lease.Release()
				return e
			}
		}
		lastCustodyRetry := time.Time{}
		for ctx.Err() == nil {
			if _, e = lease.Exec(ctx, "SELECT 1"); e != nil {
				break
			}
			r, e = s.Run(ctx)
			if e != nil {
				break
			}
			epoch = r["epoch"].(string)
			if e = s.Heartbeat(ctx, "controller", ""); e != nil {
				break
			}
			if r["state"] == "failed" || r["state"] == "stalled" || r["state"] == "finalized" {
				if adapter != nil || !pause(ctx, 100*time.Millisecond) {
					break
				}
				continue
			}
			if adapter != nil {
				if e = adapter.Tick(ctx, r); e != nil {
					break
				}
				// Tick completes SQL finalization only after native ACK.
				r, e = s.Run(ctx)
				if e != nil {
					break
				}
				if r["state"] == "finalized" {
					break
				}
			} else {
				if s.C.Autonomous {
					if e = s.Seed(ctx); e != nil {
						break
					}
				}
				if e = s.advanceLocal(ctx); e != nil {
					break
				}
			}
			if adapter != nil && r["state"] == "running" && time.Since(lastCustodyRetry) >= time.Second {
				e = s.transaction(ctx, func(tx pgx.Tx) error {
					current, err := lockRun(ctx, tx)
					if err != nil {
						return err
					}
					if current["state"] != "running" {
						return nil
					}
					_, err = recoverCustody(ctx, tx, current)
					return err
				})
				if e != nil {
					break
				}
				lastCustodyRetry = time.Now()
			}
			if !pause(ctx, 50*time.Millisecond) {
				break
			}
		}
		// A connected owner loss cannot recreate native state. Local mode can reacquire
		// the lease and resume from SQL, preserving the jobs and grant barrier.
		if adapter != nil && e != nil {
			log.Printf("connected controller stalled: %v", e)
			s.Stall(context.Background(), epoch, e.Error())
		}
		lease.Conn().Close(context.Background())
		lease.Release()
		if adapter != nil {
			return e
		}
		if e == nil {
			return nil
		}
		logDependency("controller dependency unavailable; SQL state retained", e)
		if !pause(ctx, time.Second) {
			return nil
		}
	}
	return nil
}

type Envelope struct {
	SchemaVersion    string  `json:"schema_version"`
	Type             string  `json:"type"`
	EventID          string  `json:"event_id"`
	FederationID     string  `json:"federation_id"`
	RunID            string  `json:"run_id"`
	Epoch            string  `json:"epoch"`
	CorrelationID    string  `json:"correlation_id"`
	CausationID      string  `json:"causation_id"`
	AggregateID      string  `json:"aggregate_id"`
	AggregateVersion int     `json:"aggregate_version"`
	Source           string  `json:"source"`
	Destination      string  `json:"destination"`
	Boundary         string  `json:"boundary"`
	EffectiveTime    float64 `json:"effective_time"`
	WallTime         string  `json:"wall_time"`
	QuantityUnit     string  `json:"quantity_unit"`
	Payload          struct {
		Quantity int `json:"quantity"`
	} `json:"payload"`
}

func (e Envelope) Validate() error {
	for _, v := range []string{e.EventID, e.RunID, e.Epoch, e.CorrelationID, e.CausationID, e.AggregateID} {
		if _, err := uuid.Parse(v); err != nil {
			return err
		}
	}
	if e.SchemaVersion != "1.0" || e.Type != "sample.completed.v1" || e.QuantityUnit != "item" || e.AggregateVersion < 1 || e.FederationID == "" || len(e.FederationID) > 128 || e.Source == "" || e.Destination == "" || e.Boundary == "" || !finite(e.EffectiveTime) || e.EffectiveTime < 0 || e.Payload.Quantity < 1 || e.Payload.Quantity > 10000 {
		return errors.New("invalid boundary envelope")
	}
	if _, err := time.Parse(time.RFC3339Nano, e.WallTime); err != nil {
		return err
	}
	return nil
}
func (s *Store) Ingest(ctx context.Context, envelope Envelope, source string) (result string, e error) {
	if e = envelope.Validate(); e != nil {
		return "", e
	}
	peer, ok := s.C.Peers[envelope.Boundary]
	if !ok || peer.Source != envelope.Source || peer.Endpoint != source || envelope.Destination != "logistics" || envelope.FederationID != s.C.FederationID {
		return "", Conflict("Unconfigured HELICS sender or federation")
	}
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if envelope.RunID != r["id"] || envelope.Epoch != r["epoch"] {
			result = "fenced"
			return nil
		}
		var exists bool
		if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM inbox WHERE event_id=$1)", envelope.EventID).Scan(&exists); e != nil {
			return e
		}
		if exists {
			result = "duplicate"
			return nil
		}
		if envelope.EffectiveTime < num(r, "granted") {
			return Conflict("Late event cannot change committed history")
		}
		if _, e = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3)", envelope.EventID, r["id"], r["epoch"]); e != nil {
			return e
		}
		payload, _ := json.Marshal(envelope.Payload)
		_, e = tx.Exec(ctx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES($1,$2,$3,$4,$5,$5,$6)", uuid.NewString(), r["id"], r["epoch"], "boundary:"+envelope.EventID, envelope.EffectiveTime, payload)
		result = "accepted"
		return e
	})
	return
}
func boundaryEnvelope(c Config, r row, out row, route Output) Envelope {
	sample := out["envelope"].(map[string]any)
	var e Envelope
	e.SchemaVersion = "1.0"
	e.Type = "sample.completed.v1"
	e.EventID = out["id"].(string)
	e.FederationID = c.FederationID
	e.RunID = r["id"].(string)
	e.Epoch = r["epoch"].(string)
	e.CorrelationID = sample["job_id"].(string)
	e.CausationID = e.CorrelationID
	e.AggregateID = e.CorrelationID
	e.AggregateVersion = 1
	e.Source = "logistics"
	e.Destination = route.Destination
	e.Boundary = route.Boundary
	e.EffectiveTime = num(sample, "time") + c.Quantum
	e.WallTime = out["created_at"].(string)
	e.QuantityUnit = "item"
	e.Payload.Quantity = int(num(sample, "quantity"))
	return e
}
func adapterError(status int, body []byte) error {
	return fmt.Errorf("adapter HTTP %d: %s", status, truncate(string(body), 500))
}
