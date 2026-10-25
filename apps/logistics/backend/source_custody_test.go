package main

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestUnloadedRawUnitTransfersToStorageOnlyAfterPositiveCustodyProofs(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	s.C.Providers = map[string]string{"transport": "helics", "destinations": "helics"}
	s.C.Peers = map[string]Peer{"destinations": {Source: "storage", Endpoint: "storage/events"}}
	id, correlation := uuid.NewString(), uuid.NewString()
	transportCommand(t, s, "intake", row{"sku": "COMPONENT", "category": "raw", "quantity": 2, "location": "DISPATCH", "correlation_id": correlation, "units": []row{{"id": id, "quantity": 2}}})
	unit := func() row {
		for _, value := range transportSnapshot(t, s)["handling"].(map[string]any)["units"].([]any) {
			if u := value.(map[string]any); u["id"] == id {
				return u
			}
		}
		t.Fatal("raw unit missing")
		return nil
	}
	fields := row{"reference": id, "destination": "storage.inbound.dock01", "correlation_id": correlation}
	if command := transportCommand(t, s, "handoff", fields); command["status"] != "rejected" {
		t.Fatal("intake alone cannot stand in for truck unloading", command)
	}
	request := transportCommand(t, s, "request", row{"route": "DISPATCH-WAREHOUSE", "sku": "COMPONENT", "quantity": 2, "correlation_id": correlation, "unit_ids": []string{id}})
	transfer := request["id"].(string)
	transportCommand(t, s, "assign", row{"reference": transfer, "vehicle": "VAN-1"})
	transportCommand(t, s, "load", row{"reference": transfer})
	transportCommand(t, s, "depart", row{"reference": transfer})
	r, _ := s.Run(ctx)
	eta := num(transferByID(t, s, transfer), "planned_eta")
	if ok, err := s.Prepare(ctx, eta, r["epoch"].(string)); err != nil || !ok {
		t.Fatalf("prepare arrival %v %v", ok, err)
	}
	if _, err := s.Grant(ctx, eta, r["epoch"].(string)); err != nil {
		t.Fatal(err)
	}
	var arrival string
	if err := s.DB.QueryRow(ctx, "SELECT id::text FROM jobs WHERE idempotency_key=$1", "transport:arrival:"+transfer).Scan(&arrival); err != nil {
		t.Fatal(err)
	}
	if err := s.Heartbeat(ctx, "controller", ""); err != nil {
		t.Fatal(err)
	}
	if result, err := s.Execute(ctx, arrival); err != nil || result != "completed" {
		t.Fatalf("native arrival %s %v", result, err)
	}
	transportCommand(t, s, "unload", row{"reference": transfer})
	transportCommand(t, s, "receive", row{"reference": transfer})
	if command := transportCommand(t, s, "handoff", fields); command["status"] != "completed" {
		t.Fatal(command)
	}
	if unit()["state"] != "reserved" || !strings.HasPrefix(unit()["position"].(string), "logistics.inbound.dock") {
		t.Fatal("offer relinquished stock before acceptance", unit())
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp()"); err != nil {
		t.Fatal(err)
	}
	if command := transportCommand(t, s, "handoff", fields); command["status"] != "rejected" {
		t.Fatal("unit offered twice", command)
	}
	publication := func(kind string) row {
		var result row
		if err := s.DB.QueryRow(ctx, "SELECT envelope FROM boundary_outbox WHERE envelope->>'type'=$1 ORDER BY created_at DESC LIMIT 1", "handling."+kind+".v1").Scan(&result); err != nil {
			t.Fatal(err)
		}
		return result
	}
	proof := func(publication row, state string) []byte {
		raw, _ := json.Marshal(publication)
		var e row
		json.Unmarshal(raw, &e)
		r, _ := s.Run(ctx)
		e["event_id"] = uuid.NewString()
		e["type"] = "handling." + state + ".v1"
		e["source"] = "storage"
		e["destination"] = "logistics"
		e["boundary"] = "destinations"
		e["effective_time"] = num(r, "granted") + 1
		e["wall_time"] = time.Now().UTC().Format(time.RFC3339Nano)
		h := e["payload"].(map[string]any)
		h["state"] = state
		if state == "received" {
			h["receipt_id"] = uuid.NewString()
		}
		raw, _ = json.Marshal(e)
		return raw
	}
	accepted := proof(publication("offered"), "accepted")
	var corrupt row
	json.Unmarshal(accepted, &corrupt)
	corrupt["event_id"] = uuid.NewString()
	corrupt["payload"].(map[string]any)["unit"].(map[string]any)["contents"].([]any)[0].(map[string]any)["quantity"] = 3
	bad, _ := json.Marshal(corrupt)
	if result, err := s.IngestTransport(ctx, bad, "storage/events"); err != nil || result != "accepted" {
		t.Fatalf("conflicting acceptance ingest %s %v", result, err)
	}
	executePeerTransport(t, s, bad)
	if unit()["state"] != "reserved" || len(transportSnapshot(t, s)["handling"].(map[string]any)["quarantine"].([]any)) != 1 {
		t.Fatal("changed acceptance was not quarantined without departure")
	}
	if result, err := s.IngestTransport(ctx, accepted, "storage/events"); err != nil || result != "accepted" {
		t.Fatalf("acceptance %s %v", result, err)
	}
	executePeerTransport(t, s, accepted)
	if unit()["state"] != "in_transit" || unit()["position"] != nil || num(unit(), "custody_generation") != 1 {
		t.Fatal("departure must retain unplaced custody", unit())
	}
	departure := publication("departed")
	before := unit()["version"]
	if result, err := s.IngestTransport(ctx, accepted, "storage/events"); err != nil || result != "duplicate" {
		t.Fatalf("acceptance retry %s %v", result, err)
	}
	if unit()["version"] != before {
		t.Fatal("acceptance retry departed twice")
	}
	received := proof(departure, "received")
	if result, err := s.IngestTransport(ctx, received, "storage/events"); err != nil || result != "accepted" {
		t.Fatalf("receipt %s %v", result, err)
	}
	executePeerTransport(t, s, received)
	if unit()["state"] != "dispatched" || unit()["position"] != nil {
		t.Fatal("durable Storage receipt must retire Logistics stock", unit())
	}
	ack := publication("acknowledged")
	if ack["destination"] != "storage" || ack["boundary"] != "supply" {
		t.Fatal("acknowledgement routed to wrong receiver", ack)
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE envelope->>'event_id'=$1", ack["event_id"]); err != nil {
		t.Fatal(err)
	}
	before = unit()["version"]
	if result, err := s.IngestTransport(ctx, received, "storage/events"); err != nil || result != "duplicate" {
		t.Fatalf("lost acknowledgement retry %s %v", result, err)
	}
	if !reflect.DeepEqual(publication("acknowledged"), ack) || unit()["version"] != before {
		t.Fatal("acknowledgement retry changed envelope or retired stock twice")
	}
	var retried int
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM boundary_outbox WHERE envelope->>'event_id'=$1 AND sent_at IS NULL", ack["event_id"]).Scan(&retried); err != nil || retried != 1 {
		t.Fatalf("lost acknowledgement was not republished %d %v", retried, err)
	}
	var pending int
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_unit_allocations WHERE unit_id=$1 AND active", id).Scan(&pending); err != nil || pending != 0 {
		t.Fatalf("source allocation leaked %d %v", pending, err)
	}
}
