package main

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// A missing transport endpoint, early physical movement or lost custody fails these real SQL tests.
func transportRequest(t *testing.T, s *Store, method, path, key string, body row, code int) row {
	t.Helper()
	if method == "POST" && path == "/api/transport/commands" && body["action"] == "request" && body["unit_ids"] == nil && (code == 200 || code == 409) {
		seedTransportFixture(t, s, key, body)
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(method, path, strings.NewReader(string(raw)))
	req.SetBasicAuth("employee", "employee")
	req.Header.Set("Idempotency-Key", key)
	w := httptest.NewRecorder()
	api(s, func() bool { return true }).ServeHTTP(w, req)
	if w.Code != code {
		t.Fatalf("%s %s: want %d got %d %s", method, path, code, w.Code, w.Body.String())
	}
	var v row
	if err := json.Unmarshal(w.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v
}

// Older fleet/clock fixtures now declare pre-existing whole finished pallets.
// This is fixture provenance (sequence zero), not invented physical history.
func seedTransportFixture(t *testing.T, s *Store, key string, body row) {
	t.Helper()
	ctx := context.Background()
	unitID := uuid.NewSHA1(uuid.NameSpaceOID, []byte(fmt.Sprint(body["run_id"])+":"+key)).String()
	body["unit_ids"] = []string{unitID}
	quantity, ok := body["quantity"].(int)
	if !ok || quantity < 1 || quantity > 10000 {
		return
	}
	if err := s.transaction(ctx, func(tx pgx.Tx) error {
		run, err := lockRun(ctx, tx)
		if err != nil {
			return err
		}
		if run["id"] != body["run_id"] || run["epoch"] != body["epoch"] {
			return nil
		}
		var exists bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE id=$1)", unitID).Scan(&exists); err != nil || exists {
			return err
		}
		if err = ensureTransport(ctx, tx, run); err != nil {
			return err
		}
		origin := "WAREHOUSE"
		for _, route := range transportConfig(run).Routes {
			if route.Code == body["route"] {
				origin = route.Origin
			}
		}
		position, err := freeHandlingPosition(ctx, tx, run, "logistics.outbound.staging", "finished")
		if err != nil {
			return err
		}
		command := uuid.NewSHA1(uuid.MustParse(unitID), []byte("fixture-provenance")).String()
		if _, err = tx.Exec(ctx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload,status) VALUES($1,$2,$3,$4,0,0,'{}','completed')", command, run["id"], run["epoch"], "fixture:"+key); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO transport_commands(id,run_id,command,status) VALUES($1,$2,'{\"action\":\"fixture\"}','completed')", command, run["id"]); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, "INSERT INTO transport_handling_units(id,barcode,run_id,epoch,sku,quantity,category,logical_location,state,position,command_id) VALUES($1,$2,$3,$4,$5,$6,'finished',$7,'available',$8,$9)", unitID, "HU-"+strings.ToUpper(strings.ReplaceAll(unitID, "-", "")), run["id"], run["epoch"], body["sku"], quantity, origin, position, command)
		return err
	}); err != nil {
		t.Fatal(err)
	}
}
func transportSnapshot(t *testing.T, s *Store) row {
	return transportRequest(t, s, "GET", "/api/transport", "", nil, 200)
}
func transportCommand(t *testing.T, s *Store, action string, fields row) row {
	t.Helper()
	ctx := context.Background()
	r, err := s.Run(ctx)
	if err != nil {
		t.Fatal(err)
	}
	due := num(r, "requested") + 1
	if num(r, "granted") >= due {
		due = num(r, "granted") + 1
	}
	body := row{"run_id": r["id"], "epoch": r["epoch"], "due_at": due, "action": action}
	for k, v := range fields {
		body[k] = v
	}
	c := transportRequest(t, s, "POST", "/api/transport/commands", uuid.NewString(), body, 200)
	if ok, e := s.Prepare(ctx, due, r["epoch"].(string)); e != nil || !ok {
		t.Fatalf("prepare %v %v", ok, e)
	}
	if _, e := s.Grant(ctx, due, r["epoch"].(string)); e != nil {
		t.Fatal(e)
	}
	if e := s.Heartbeat(ctx, "controller", ""); e != nil {
		t.Fatal(e)
	}
	if result, e := s.Execute(ctx, c["id"].(string)); e != nil || result != "completed" {
		t.Fatalf("execute %s %v", result, e)
	}
	snap := transportSnapshot(t, s)
	for _, v := range snap["commands"].([]any) {
		command := v.(map[string]any)
		if command["id"] == c["id"] {
			return command
		}
	}
	t.Fatal("command absent")
	return nil
}
func requestedTransfer(t *testing.T, s *Store, quantity int) string {
	t.Helper()
	c := transportCommand(t, s, "request", row{"route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": quantity, "correlation_id": uuid.NewString()})
	if c["status"] != "completed" {
		t.Fatalf("request %v", c)
	}
	return c["id"].(string)
}
func transferByID(t *testing.T, s *Store, id string) row {
	t.Helper()
	for _, v := range transportSnapshot(t, s)["transfers"].([]any) {
		r := v.(map[string]any)
		if r["id"] == id {
			return r
		}
	}
	t.Fatal("transfer absent")
	return nil
}
func TestTransportLifecycleKeepsCustodyUntilReceipt(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	id := requestedTransfer(t, s, 8)
	for _, step := range []struct {
		action, state, custody string
		fields                 row
	}{
		{"assign", "assigned", "origin", row{"reference": id, "vehicle": "TRUCK-1"}},
		{"load", "loaded", "vehicle", row{"reference": id}},
		{"depart", "in_transit", "vehicle", row{"reference": id}},
	} {
		c := transportCommand(t, s, step.action, step.fields)
		tr := transferByID(t, s, id)
		if c["status"] != "completed" || tr["status"] != step.state || tr["custody"] != step.custody {
			t.Fatalf("%s %v %v", step.action, c, tr)
		}
	}
	tr := transferByID(t, s, id)
	if tr["arrived_at"] != nil || tr["received_at"] != nil || num(tr, "planned_eta") != 14 {
		t.Fatalf("ETA falsely arrived: %v", tr)
	}
	c := transportCommand(t, s, "arrive", row{"reference": id})
	if c["status"] != "rejected" || transferByID(t, s, id)["status"] != "in_transit" {
		t.Fatalf("early arrival %v", c)
	}
	r, _ := s.Run(ctx)
	if ok, e := s.Prepare(ctx, 14, r["epoch"].(string)); e != nil || !ok {
		t.Fatal(e)
	}
	s.Grant(ctx, 14, r["epoch"].(string))
	s.Heartbeat(ctx, "controller", "")
	var arrival string
	if e := s.DB.QueryRow(ctx, "SELECT id::text FROM jobs WHERE run_id=$1 AND due_at=14 AND status='pending'", r["id"]).Scan(&arrival); e != nil {
		t.Fatal(e)
	}
	if ok, _ := s.Prepare(ctx, 15, r["epoch"].(string)); ok {
		t.Fatal("advanced over unsettled arrival")
	}
	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, e := s.Execute(ctx, arrival); e != nil {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	tr = transferByID(t, s, id)
	if tr["status"] != "arrived" || num(tr, "arrived_at") != 14 || tr["received_at"] != nil {
		t.Fatalf("arrival %v", tr)
	}
	for _, a := range []string{"unload", "receive"} {
		if c := transportCommand(t, s, a, row{"reference": id}); c["status"] != "completed" {
			t.Fatalf("%s %v", a, c)
		}
	}
	tr = transferByID(t, s, id)
	if tr["status"] != "received" || tr["custody"] != "destination" {
		t.Fatal(tr)
	}
	var arrivals int
	if e := s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_movements WHERE transfer_id=$1 AND action='arrive'", id).Scan(&arrivals); e != nil || arrivals != 1 {
		t.Fatalf("duplicate arrival effects %d %v", arrivals, e)
	}
	c = transportCommand(t, s, "arrive", row{"reference": id})
	if c["status"] != "rejected" {
		t.Fatal("arrived twice")
	}
}
func TestTransportFleetCapacityAndConflictingAssignment(t *testing.T) {
	s := testStore(t)
	first := requestedTransfer(t, s, 8)
	second := requestedTransfer(t, s, 8)
	large := requestedTransfer(t, s, 101)
	for _, v := range []struct{ id, status string }{{large, "rejected"}, {first, "completed"}, {second, "rejected"}} {
		c := transportCommand(t, s, "assign", row{"reference": v.id, "vehicle": "TRUCK-1"})
		if c["status"] != v.status {
			t.Fatalf("capacity/assignment %v", c)
		}
	}
	if tr := transferByID(t, s, second); tr["status"] != "requested" || tr["vehicle"] != nil {
		t.Fatalf("partial failed assignment %v", tr)
	}
	c := transportCommand(t, s, "depart", row{"reference": first})
	if c["status"] != "rejected" {
		t.Fatal("departed before load")
	}
}
func TestTransportHTTPValidationReplayAuditAndEpoch(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	body := row{"run_id": r["id"], "epoch": r["epoch"], "due_at": 1, "action": "request", "route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": 5, "correlation_id": uuid.NewString()}
	a := transportRequest(t, s, "POST", "/api/transport/commands", "replay", body, 200)
	b := transportRequest(t, s, "POST", "/api/transport/commands", "replay", body, 200)
	if a["id"] != b["id"] {
		t.Fatal("replay duplicated")
	}
	body["quantity"] = 6
	transportRequest(t, s, "POST", "/api/transport/commands", "replay", body, 409)
	for _, v := range []any{true, 1.5, "2", 0, nil} {
		body["quantity"] = v
		transportRequest(t, s, "POST", "/api/transport/commands", uuid.NewString(), body, 422)
	}
	body["quantity"] = 5
	body["vehicle"] = "TRUCK-1"
	transportRequest(t, s, "POST", "/api/transport/commands", "extra", body, 422)
	delete(body, "vehicle")
	if _, e := s.Control(ctx, "reset", 1, r["id"].(string), nil, nil); e != nil {
		t.Fatal(e)
	}
	transportRequest(t, s, "POST", "/api/transport/commands", "old", body, 409)
	if result, e := s.Execute(ctx, a["id"].(string)); e != nil || result != "fenced" {
		t.Fatalf("stale delivery %s %v", result, e)
	}
	var count int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM command_audit WHERE outcome='accepted'").Scan(&count)
	if count != 2 {
		t.Fatal(fmt.Sprint("accepted audit ", count))
	}
}

// Removing the current-run transaction lock must allow these assignments to collide.
func TestTransportConcurrentAssignmentsAndAuditRollback(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	first := requestedTransfer(t, s, 10)
	second := requestedTransfer(t, s, 10)
	r, _ := s.Run(ctx)
	due := num(r, "granted") + 1
	ids := []string{}
	for _, ref := range []string{first, second} {
		body := row{"run_id": r["id"], "epoch": r["epoch"], "due_at": due, "action": "assign", "reference": ref, "vehicle": "TRUCK-1"}
		c := transportRequest(t, s, "POST", "/api/transport/commands", uuid.NewString(), body, 200)
		ids = append(ids, c["id"].(string))
	}
	s.Prepare(ctx, due, r["epoch"].(string))
	s.Grant(ctx, due, r["epoch"].(string))
	s.Heartbeat(ctx, "controller", "")
	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			if _, e := s.Execute(ctx, id); e != nil {
				t.Error(e)
			}
		}(id)
	}
	wg.Wait()
	var assigned, rejected int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_transfers WHERE status='assigned'").Scan(&assigned)
	s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_commands WHERE status='rejected'").Scan(&rejected)
	if assigned != 1 || rejected != 1 {
		t.Fatalf("reservation conflict: assigned=%d rejected=%d", assigned, rejected)
	}
	raw := fmt.Sprintf(`{"run_id":%q,"epoch":%q,"due_at":10,"action":"request","route":"WAREHOUSE-DISPATCH","sku":"PRODUCT","quantity":1,"unit_ids":["10000000-0000-4000-8000-000000000001"],"correlation_id":%q}`, r["id"], r["epoch"], uuid.NewString())
	c, e := parseTransport(strings.NewReader(raw))
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.ScheduleTransport(ctx, "bad-audit", c, &Audit{Actor: "employee", Role: "employee", RequestID: "invalid", Action: "request"}); e == nil {
		t.Fatal("invalid audit accepted")
	}
	var jobs int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM jobs WHERE idempotency_key='bad-audit'").Scan(&jobs)
	if jobs != 0 {
		t.Fatal("command survived audit rollback")
	}
}
func TestTransportIdempotencyKeyCannotCollideWithSampleJob(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	if _, e := s.Schedule(ctx, "shared-key", JobCommand{1, 1}, nil, nil); e != nil {
		t.Fatal(e)
	}
	transportRequest(t, s, "POST", "/api/transport/commands", "shared-key", row{"run_id": r["id"], "epoch": r["epoch"], "due_at": 1, "action": "request", "route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": 1, "correlation_id": uuid.NewString()}, 409)
}
func TestTransportFailedUnloadKeepsCustodyAndReservation(t *testing.T) {
	s := testStore(t)
	id := requestedTransfer(t, s, 5)
	if c := transportCommand(t, s, "assign", row{"reference": id, "vehicle": "TRUCK-1"}); c["status"] != "completed" {
		t.Fatal(c)
	}
	if c := transportCommand(t, s, "unload", row{"reference": id}); c["status"] != "rejected" {
		t.Fatal("unloaded before journey arrival")
	}
	tr := transferByID(t, s, id)
	if tr["status"] != "assigned" || tr["custody"] != "origin" || tr["vehicle"] != "TRUCK-1" {
		t.Fatalf("failed unload changed custody: %v", tr)
	}
	for _, v := range transportSnapshot(t, s)["vehicles"].([]any) {
		vehicle := v.(map[string]any)
		if vehicle["code"] == "TRUCK-1" && vehicle["transfer_id"] != id {
			t.Fatalf("failed unload released vehicle: %v", vehicle)
		}
	}
}
