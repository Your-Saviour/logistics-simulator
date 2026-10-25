package main

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"testing"
)

func TestFleetFactsFenceIdentityAndFutureArrival(t *testing.T) {
	request := row{"id": "job", "unit_id": "unit", "run_id": "fleet", "epoch": "epoch", "source_run_id": "source", "source_epoch": "source-epoch", "origin": "a", "destination": "b", "custody_generation": float64(2)}
	body := row{"job_id": "job", "unit_id": "unit", "run_id": "fleet", "epoch": "epoch", "source_run_id": "source", "source_epoch": "source-epoch", "origin": "a", "destination": "b", "custody_generation": float64(2), "kind": "arrival", "route_version": float64(1), "robot_id": "robot", "effective_time": float64(12)}
	if fleetFact(request, body, "arrival", 11) {
		t.Fatal("future arrival authorized receipt")
	}
	if !fleetFact(request, body, "arrival", 12) {
		t.Fatal("committed arrival was rejected")
	}
	body["epoch"] = "stale"
	if fleetFact(request, body, "arrival", 20) {
		t.Fatal("stale fleet epoch authorized receipt")
	}
}

func TestFleetOutageDefersAndReservesLocalDestination(t *testing.T) {
	s := testStore(t)
	t.Setenv("FLEET_MODE", "coordinated")
	t.Setenv("FLEET_TIME_OFFSET", "0")
	t.Setenv("FLEET_RUN_ID", "11111111-1111-4111-8111-111111111111")
	t.Setenv("FLEET_EPOCH", "22222222-2222-4222-8222-222222222222")
	t.Setenv("FLEET_URL", "http://127.0.0.1:1")
	t.Setenv("FLEET_TOKEN", "private")
	id := uuid.NewString()
	correlation := uuid.NewString()
	transportCommand(t, s, "intake", row{"correlation_id": correlation, "sku": "PRODUCT", "category": "finished", "quantity": 1, "units": []row{{"id": id, "quantity": 1}}, "location": "WAREHOUSE"})
	request := transportCommand(t, s, "request", row{"correlation_id": correlation, "route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": 1, "unit_ids": []string{id}})
	if request["status"] != "completed" {
		t.Fatal(request)
	}
	transfer := request["id"].(string)
	if assigned := transportCommand(t, s, "assign", row{"reference": transfer, "vehicle": "TRUCK-1"}); assigned["status"] != "completed" {
		t.Fatal(assigned)
	}
	r, _ := s.Run(context.Background())
	c := TransportCommand{RunID: r["id"].(string), Epoch: r["epoch"].(string), DueAt: num(r, "granted") + 2, Action: "load", Reference: transfer}
	job, err := s.ScheduleTransport(context.Background(), uuid.NewString(), c, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.DB.Exec(context.Background(), "UPDATE runs SET granted=$1,requested=$1 WHERE id=$2", c.DueAt, r["id"]); err != nil {
		t.Fatal(err)
	}
	if err = s.Heartbeat(context.Background(), "controller", ""); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Execute(context.Background(), job["id"].(string)); err != nil {
		t.Fatal(err)
	}
	var state string
	var position, destination *string
	if err = s.DB.QueryRow(context.Background(), "SELECT state,position,destination FROM transport_handling_units WHERE id=$1", id).Scan(&state, &position, &destination); err != nil {
		t.Fatal(err)
	}
	if state != "reserved" || position == nil || destination == nil {
		t.Fatal("fleet outage lost source or destination reservation", state, position, destination)
	}
	var due float64
	var status string
	s.DB.QueryRow(context.Background(), "SELECT due_at,status FROM jobs WHERE id=$1", job["id"]).Scan(&due, &status)
	if status != "pending" || due <= c.DueAt {
		t.Fatal("fleet wait blocks native grant", due, status)
	}
	var count int
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM transport_fleet_jobs").Scan(&count)
	if count != 1 {
		t.Fatal("request not durable", count)
	}
	if err = s.relayFleet(context.Background()); err != nil {
		t.Fatal(err)
	}
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM transport_fleet_jobs WHERE error IS NOT NULL").Scan(&count)
	if count != 1 {
		t.Fatal("fleet outage not visible")
	}
	var frozen row
	if err = s.transaction(context.Background(), func(tx pgx.Tx) error {
		f, e := object(context.Background(), tx, "SELECT request FROM transport_fleet_jobs LIMIT 1")
		if e == nil {
			frozen = f["request"].(map[string]any)
		}
		return e
	}); err != nil {
		t.Fatal(err)
	}
	inject := func(kind string, at float64) {
		t.Helper()
		body := row{}
		for k, v := range frozen {
			body[k] = v
		}
		delete(body, "id")
		body["job_id"] = frozen["id"]
		body["kind"] = kind
		body["robot_id"] = uuid.NewString()
		body["route_version"] = 1
		body["effective_time"] = at
		var events []row
		events = append(events, row{"job_id": frozen["id"], "kind": "pickup_ready", "body": body})
		if kind == "arrival" {
			body["kind"] = "arrival"
			pickup := row{}
			for k, v := range body {
				pickup[k] = v
			}
			pickup["kind"] = "pickup_ready"
			pickup["effective_time"] = c.DueAt
			events = []row{{"job_id": frozen["id"], "kind": "pickup_ready", "body": pickup}, {"job_id": frozen["id"], "kind": "arrival", "body": body}}
		}
		raw, _ := json.Marshal(row{"events": events})
		if _, e := s.DB.Exec(context.Background(), "UPDATE transport_fleet_jobs SET snapshot=$1", raw); e != nil {
			t.Fatal(e)
		}
	}
	execute := func(at float64) {
		t.Helper()
		s.DB.Exec(context.Background(), "UPDATE runs SET granted=$1,requested=$1", at)
		s.Heartbeat(context.Background(), "controller", "")
		if _, e := s.Execute(context.Background(), job["id"].(string)); e != nil {
			t.Fatal(e)
		}
	}
	inject("pickup_ready", c.DueAt)
	execute(c.DueAt + 1)
	s.DB.QueryRow(context.Background(), "SELECT state,position,destination FROM transport_handling_units WHERE id=$1", id).Scan(&state, &position, &destination)
	if state != "in_transit" || position != nil || destination == nil {
		t.Fatal("pickup did not remove source placement", state, position, destination)
	}
	inject("arrival", c.DueAt+3)
	execute(c.DueAt + 2)
	s.DB.QueryRow(context.Background(), "SELECT position FROM transport_handling_units WHERE id=$1", id).Scan(&position)
	if position != nil {
		t.Fatal("future arrival placed unit")
	}
	execute(c.DueAt + 3)
	s.DB.QueryRow(context.Background(), "SELECT state,position,destination FROM transport_handling_units WHERE id=$1", id).Scan(&state, &position, &destination)
	if state != "reserved" || position == nil || destination != nil {
		t.Fatal("eligible arrival did not confirm placement", state, position, destination)
	}
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM transport_fleet_jobs WHERE departure IS NOT NULL AND receipt IS NOT NULL").Scan(&count)
	if count != 1 {
		t.Fatal("native proofs not atomic with placement")
	}
}
