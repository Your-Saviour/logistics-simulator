package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"strings"
	"time"
)

type Adapter struct {
	PendingSince            time.Time
	Store                   *Store
	SessionID, RunID, Epoch string
	Client                  *http.Client
}

func newAdapter(ctx context.Context, s *Store, r row) (*Adapter, error) {
	a := &Adapter{Store: s, SessionID: uuid.NewString(), RunID: r["id"].(string), Epoch: r["epoch"].(string), Client: &http.Client{Timeout: 5 * time.Second}}
	e := s.transaction(ctx, func(tx pgx.Tx) error {
		current, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if current["epoch"] != a.Epoch {
			return Conflict("Stale controller epoch")
		}
		var exists bool
		if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM logistics_adapter_sessions WHERE run_id=$1)", a.RunID).Scan(&exists); e != nil {
			return e
		}
		if exists {
			return Conflict("Native session already exists; coordinated recovery with a new run/epoch required")
		}
		_, e = tx.Exec(ctx, "INSERT INTO logistics_adapter_sessions(run_id,epoch,session_id) VALUES($1,$2,$3)", a.RunID, a.Epoch, a.SessionID)
		return e
	})
	if e != nil {
		return nil, e
	}
	if _, e = a.Call(ctx, "initialize", row{}, uuid.NewString()); e != nil {
		return nil, e
	}
	return a, nil
}
func (a *Adapter) Call(ctx context.Context, operation string, payload row, id string) (result row, e error) {
	body := row{"version": "1.0", "request_id": id, "run_id": a.RunID, "epoch": a.Epoch, "session_id": a.SessionID, "operation": operation, "payload": payload}
	raw, _ := json.Marshal(body)
	var persisted []byte
	var completed []byte
	e = a.Store.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["id"] != a.RunID || r["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		_, e = tx.Exec(ctx, "INSERT INTO logistics_adapter_operations(request_id,run_id,epoch,session_id,operation,body) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING", id, a.RunID, a.Epoch, a.SessionID, operation, raw)
		if e != nil {
			return e
		}
		var same bool
		e = tx.QueryRow(ctx, "SELECT body,result,body=$2::jsonb FROM logistics_adapter_operations WHERE request_id=$1", id, raw).Scan(&persisted, &completed, &same)
		if e != nil {
			return e
		}
		if !same {
			return Conflict("Adapter operation id already used with different command")
		}
		return nil
	})
	if e != nil {
		return nil, e
	}
	if completed != nil {
		e = json.Unmarshal(completed, &result)
		return
	}
	deadline := time.Now().Add(a.Store.C.adapterTimeout())
	for {
		request, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(a.Store.C.AdapterURL, "/")+"/v1/commands", bytes.NewReader(persisted))
		if err != nil {
			return nil, err
		}
		request.Header.Set("Authorization", "Bearer "+a.Store.C.AdapterToken)
		request.Header.Set("Content-Type", "application/json")
		response, err := a.Client.Do(request)
		if err == nil {
			data, readErr := io.ReadAll(io.LimitReader(response.Body, 2<<20))
			response.Body.Close()
			if readErr != nil {
				err = readErr
			} else if response.StatusCode == 200 {
				var envelope struct {
					Version   string `json:"version"`
					RequestID string `json:"request_id"`
					Result    row    `json:"result"`
				}
				if err = json.Unmarshal(data, &envelope); err != nil {
					return nil, err
				}
				if envelope.Version != "1.0" || envelope.RequestID != id {
					return nil, errors.New("adapter response identity mismatch")
				}
				result = envelope.Result
				break
			} else {
				err = adapterError(response.StatusCode, data)
				if response.StatusCode < 500 {
					return nil, err
				}
			}
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if time.Now().After(deadline) {
			return nil, err
		}
		if !pause(ctx, 250*time.Millisecond) {
			return nil, ctx.Err()
		}
	}
	// A DB outage after a native reply retries the SQL write of the same reply;
	// it never invents another request ID or resends into a new native session.
	encoded, _ := json.Marshal(result)
	for {
		e = a.Store.transaction(ctx, func(tx pgx.Tx) error {
			r, e := lockRun(ctx, tx)
			if e != nil {
				return e
			}
			if r["id"] != a.RunID || r["epoch"] != a.Epoch {
				return Conflict("Stale adapter epoch")
			}
			_, e = tx.Exec(ctx, "UPDATE logistics_adapter_operations SET result=$1,completed_at=clock_timestamp() WHERE request_id=$2", encoded, id)
			return e
		})
		if e == nil {
			return result, nil
		}
		var conflict Conflict
		if errors.As(e, &conflict) || ctx.Err() != nil || time.Now().After(deadline) {
			return nil, e
		}
		if !pause(ctx, 250*time.Millisecond) {
			return nil, ctx.Err()
		}
	}
}
func (a *Adapter) Tick(ctx context.Context, r row) error {
	// Claim processing and read lifecycle state in one run-row transaction so
	// API finalization cannot slip between a lifecycle check and native polling.
	var e error
	r, e = a.beginTick(ctx)
	if e != nil {
		return e
	}
	if r["state"] == "finalizing" {
		return a.finalize(ctx)
	}
	if r["state"] == "finalized" {
		return nil
	}
	poll, e := a.Call(ctx, "poll", row{}, uuid.NewString())
	if e != nil {
		return e
	}
	state, _ := poll["state"].(string)
	if state == "initializing" {
		if e = a.phase(ctx, "initializing", true, false); e != nil {
			return e
		}
		return a.checkPending(true)
	}
	if state != "executing" {
		return Conflict("Adapter native session is not executing; coordinated epoch recovery required")
	}
	nativePending, validPending := poll["pending"].(bool)
	if !validPending {
		return errors.New("adapter omitted native pending state")
	}
	granted, ok := poll["granted"].(float64)
	if !ok || !finite(granted) {
		return errors.New("adapter omitted finite grant")
	}
	if _, e = a.Store.Grant(ctx, granted, a.Epoch); e != nil {
		return e
	}
	messages, validMessages := poll["messages"].([]any)
	if !validMessages {
		return errors.New("adapter omitted retained messages")
	}
	acked := []string{}
	for _, m := range messages {
		message, ok := m.(map[string]any)
		if !ok {
			return errors.New("invalid adapter message")
		}
		raw, _ := json.Marshal(message["envelope"])
		var meta struct {
			Type    string `json:"type"`
			EventID string `json:"event_id"`
		}
		if e = json.Unmarshal(raw, &meta); e != nil {
			return e
		}
		if meta.Type != "sample.completed.v1" {
			if _, e = a.Store.IngestTransport(ctx, raw, stringify(message["source"])); e != nil {
				return e
			}
		} else {
			var envelope Envelope
			if e = strictJSON(bytes.NewReader(raw), &envelope); e != nil {
				return e
			}
			if _, e = a.Store.Ingest(ctx, envelope, stringify(message["source"])); e != nil {
				return e
			}
		}
		acked = append(acked, meta.EventID)
	}
	// Only the committed grant and committed inbox inputs can clear native pending.
	if e = a.phase(ctx, "executing", nativePending, true); e != nil {
		return e
	}
	if len(acked) > 0 {
		if _, e = a.Call(ctx, "receive_ack", row{"event_ids": acked}, uuid.NewString()); e != nil {
			return e
		}
	}
	if e = a.checkPending(nativePending); e != nil {
		return e
	}
	if nativePending {
		return a.processing(ctx, false)
	}
	r, e = a.Store.Run(ctx)
	if e != nil {
		return e
	}
	if e = a.settle(ctx, r); e != nil {
		return e
	}
	if e = a.processing(ctx, false); e != nil {
		return e
	}
	if r["state"] != "running" {
		return nil
	}
	if a.Store.C.Autonomous {
		if e = a.Store.Seed(ctx); e != nil {
			return e
		}
	}
	target := num(r, "granted") + a.Store.C.Quantum
	prepared, e := a.Store.Prepare(ctx, target, a.Epoch)
	if e != nil || !prepared {
		return e
	}
	_, e = a.Call(ctx, "request_time", row{"target": target, "committed": r["granted"], "pending_work": 0, "pending_outputs": 0}, uuid.NewString())
	if e == nil {
		e = a.checkPending(true)
	}
	return e
}
func (a *Adapter) settle(ctx context.Context, r row) error {
	var outputs []row
	e := a.Store.transaction(ctx, func(tx pgx.Tx) error {
		current, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if current["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		outputs, e = objects(ctx, tx, "SELECT * FROM boundary_outbox WHERE run_id=$1 AND sent_at IS NULL ORDER BY id", a.RunID)
		return e
	})
	if e != nil {
		return e
	}
	for _, out := range outputs {
		for _, route := range a.Store.C.Outputs {
			var envelope any
			if out["envelope"].(map[string]any)["transfer"] != nil {
				body := out["envelope"].(map[string]any)
				tr := body["transfer"].(map[string]any)
				if route.Destination == "storage" && (body["type"] != "logistics.unload.completed.v1" || tr["external_reference"] == nil) {
					continue
				}
				envelope = transportBoundaryEnvelope(a.Store.C, r, out, route)
			} else {
				envelope = boundaryEnvelope(a.Store.C, r, out, route)
			}
			routeBody, _ := json.Marshal(route)
			operationID := uuid.NewSHA1(uuid.MustParse(out["id"].(string)), routeBody).String()
			if _, e = a.Call(ctx, "publish", row{"endpoint": route.Endpoint, "envelope": envelope}, operationID); e != nil {
				return e
			}
		}
		e = a.Store.transaction(ctx, func(tx pgx.Tx) error {
			current, e := lockRun(ctx, tx)
			if e != nil {
				return e
			}
			if current["epoch"] != a.Epoch {
				return Conflict("Stale adapter epoch")
			}
			_, e = tx.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE id=$1 AND run_id=$2", out["id"], a.RunID)
			return e
		})
		if e != nil {
			return e
		}
	}
	status, e := a.Store.Status(ctx)
	if e != nil {
		return e
	}
	id := uuid.NewSHA1(uuid.MustParse(a.SessionID), []byte("value:"+stringify(status["effects"])+":"+stringify(r["granted"]))).String()
	_, e = a.Call(ctx, "publish_value", row{"value": status["effects"], "unit": "item"}, id)
	return e
}

func (a *Adapter) checkPending(pending bool) error {
	if !pending {
		a.PendingSince = time.Time{}
		return nil
	}
	if a.PendingSince.IsZero() {
		a.PendingSince = time.Now()
		return nil
	}
	if time.Since(a.PendingSince) > a.Store.C.adapterTimeout() {
		return Conflict("HELICS initialization/time grant timed out; coordinated epoch recovery required")
	}
	return nil
}

func (a *Adapter) processing(ctx context.Context, value bool) error {
	return a.Store.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["id"] != a.RunID || r["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		tag, e := tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET processing=$1 WHERE run_id=$2 AND epoch=$3 AND session_id=$4", value, a.RunID, a.Epoch, a.SessionID)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return Conflict("Stale native session")
		}
		return nil
	})
}
func (a *Adapter) phase(ctx context.Context, state string, pending, processing bool) error {
	return a.Store.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if r["id"] != a.RunID || r["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		tag, e := tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET native_state=$1,pending=$2,processing=$3 WHERE run_id=$4 AND epoch=$5 AND session_id=$6", state, pending, processing, a.RunID, a.Epoch, a.SessionID)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return Conflict("Stale native session")
		}
		return nil
	})
}

func (a *Adapter) beginTick(ctx context.Context) (current row, e error) {
	e = a.Store.transaction(ctx, func(tx pgx.Tx) error {
		var err error
		current, err = lockRun(ctx, tx)
		if err != nil {
			return err
		}
		if current["id"] != a.RunID || current["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		if current["state"] == "finalized" || current["state"] == "finalizing" {
			return nil
		}
		if !active(current) {
			return Conflict("Native run is not active")
		}
		tag, err := tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET processing=true WHERE run_id=$1 AND epoch=$2 AND session_id=$3", a.RunID, a.Epoch, a.SessionID)
		if err != nil {
			return err
		}
		if tag.RowsAffected() != 1 {
			return Conflict("Stale native session")
		}
		return nil
	})
	return
}

func (a *Adapter) finalize(ctx context.Context) error {
	id := uuid.NewSHA1(uuid.MustParse(a.SessionID), []byte("finalize")).String()
	result, e := a.Call(ctx, "finalize", row{}, id)
	if e != nil {
		return e
	}
	if result["state"] != "finalized" {
		return Conflict("Adapter did not acknowledge native finalization")
	}
	return a.Store.transaction(ctx, func(tx pgx.Tx) error {
		current, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		if current["id"] != a.RunID || current["epoch"] != a.Epoch {
			return Conflict("Stale adapter epoch")
		}
		if current["state"] != "finalizing" {
			return Conflict("Run is no longer finalizing")
		}
		tag, e := tx.Exec(ctx, "UPDATE logistics_adapter_sessions SET native_state='finalized',pending=false,processing=false WHERE run_id=$1 AND epoch=$2 AND session_id=$3 AND native_state='finalizing' AND pending", a.RunID, a.Epoch, a.SessionID)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return Conflict("Stale native finalization session")
		}
		_, e = tx.Exec(ctx, "UPDATE runs SET state='finalized' WHERE id=$1 AND epoch=$2", a.RunID, a.Epoch)
		return e
	})
}
