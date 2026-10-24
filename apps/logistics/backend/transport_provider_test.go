package main

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"testing"
)

// Sample-only providers must not satisfy transport demand or invent destination receipts.
func TestTransportSeededProvidersCompleteTheirOwnWorkflow(t *testing.T) {
	s := testStore(t)
	s.C.Providers = map[string]string{"transport": "synthetic", "destinations": "synthetic"}
	ctx := context.Background()
	// Existing Seed is the public controller hook; autonomous providers must use domain jobs.
	for tick := 1; tick <= 85; tick++ {
		if e := s.Seed(ctx); e != nil {
			t.Fatal(e)
		}
		r, _ := s.Run(ctx)
		if ok, e := s.Prepare(ctx, float64(tick), r["epoch"].(string)); e != nil || !ok {
			t.Fatalf("prepare %d: %v %v", tick, ok, e)
		}
		s.Grant(ctx, float64(tick), r["epoch"].(string))
		s.Heartbeat(ctx, "controller", "")
		jobs, e := s.Dispatchable(ctx)
		if e != nil {
			t.Fatal(e)
		}
		for _, j := range jobs {
			if _, e = s.Execute(ctx, j["job_id"].(string)); e != nil {
				t.Fatal(e)
			}
		}
	}
	var received int
	if e := s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_transfers WHERE status='received' AND provider").Scan(&received); e != nil || received < 1 {
		t.Fatalf("no completed provider transport: %d %v", received, e)
	}
}
func TestTransportScenarioRejectsDanglingRoutes(t *testing.T) {
	var s Scenario
	if e := json.Unmarshal([]byte(`{"transport":{"locations":[{"code":"A"},{"code":"B"}],"routes":[{"code":"A-B","origin":"A","destination":"MISSING","journey_seconds":2}],"vehicles":[{"code":"V","capacity":1,"location":"A"}]}}`), &s); e == nil {
		t.Fatal("accepted dangling route")
	}
}
func TestTransportNativePeerDeduplicationAndCustody(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	s.C.FederationID = "transport-test"
	s.C.Peers = map[string]Peer{"transport": {Source: "storage", Endpoint: "storage/events"}}
	body := row{"schema_version": "1.0", "type": "logistics.request.v1", "event_id": uuid.NewString(), "run_id": r["id"], "epoch": r["epoch"], "federation_id": "transport-test", "aggregate_id": uuid.NewString(), "aggregate_version": 1, "correlation_id": uuid.NewString(), "causation_id": uuid.NewString(), "source": "storage", "destination": "logistics", "boundary": "transport", "effective_time": 1, "wall_time": "2026-10-24T00:00:00Z", "quantity_unit": "item", "payload": row{"route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": 5}}
	raw, _ := json.Marshal(body)
	// Use the same ingestion entry point that the HTTP adapter poll uses.
	if _, e := s.IngestTransport(ctx, raw, "storage/events"); e != nil {
		t.Fatal(e)
	}
	if result, e := s.IngestTransport(ctx, raw, "storage/events"); e != nil || result != "duplicate" {
		t.Fatalf("duplicate %s %v", result, e)
	}
	body["event_id"] = uuid.NewString()
	raw, _ = json.Marshal(body)
	if _, e := s.IngestTransport(ctx, raw, "storage/events"); e == nil {
		t.Fatal("accepted second event for immutable peer aggregate")
	}
	if _, e := s.IngestTransport(ctx, raw, "spoof/events"); e == nil {
		t.Fatal("accepted wrong sender")
	}
	var count int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_commands").Scan(&count)
	if count != 1 {
		t.Fatalf("duplicate command %d", count)
	}
}
func TestTransportStorageTransferHandoffPreservesReference(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	s.C.FederationID = "transport-test"
	s.C.Peers = map[string]Peer{"transport": {Source: "storage", Endpoint: "storage/events"}}
	external := uuid.NewString()
	correlation := uuid.NewString()
	env := row{"schema_version": "1.0", "type": "storage.transfer.completed.v1", "event_id": uuid.NewString(), "federation_id": "transport-test", "run_id": r["id"], "epoch": r["epoch"], "correlation_id": correlation, "causation_id": uuid.NewString(), "aggregate_id": external, "aggregate_version": 2, "source": "storage", "destination": "logistics", "boundary": "transport", "effective_time": 1, "wall_time": "2026-10-24T00:00:00Z", "quantity_unit": "item", "payload": row{"id": external, "run_id": r["id"], "reservation_id": uuid.NewString(), "sku": "PRODUCT", "origin": "WAREHOUSE", "destination": "DISPATCH", "quantity": 5, "correlation_id": correlation, "status": "in_transit", "version": 2}}
	raw, _ := json.Marshal(env)
	if _, e := s.IngestTransport(ctx, raw, "storage/events"); e != nil {
		t.Fatal(e)
	}
	r, _ = s.Run(ctx)
	s.Prepare(ctx, 1, r["epoch"].(string))
	s.Grant(ctx, 1, r["epoch"].(string))
	s.Heartbeat(ctx, "controller", "")
	jobs, _ := s.Dispatchable(ctx)
	for _, j := range jobs {
		if _, e := s.Execute(ctx, j["job_id"].(string)); e != nil {
			t.Fatal(e)
		}
	}
	snap := transportSnapshot(t, s)
	tr := snap["transfers"].([]any)[0].(map[string]any)
	if tr["external_reference"] != external || tr["correlation_id"] != correlation {
		t.Fatal(tr)
	}
}
func TestTransportReceiptRejectsDifferentCorrelation(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	id := requestedTransfer(t, s, 2)
	r, _ := s.Run(ctx)
	s.C.FederationID = "transport-test"
	s.C.Peers = map[string]Peer{"destinations": {Source: "shipping", Endpoint: "shipping/events"}}
	env := row{"schema_version": "1.0", "type": "logistics.receipt.v1", "event_id": uuid.NewString(), "federation_id": "transport-test", "run_id": r["id"], "epoch": r["epoch"], "aggregate_id": uuid.NewString(), "aggregate_version": 1, "correlation_id": uuid.NewString(), "causation_id": uuid.NewString(), "source": "shipping", "destination": "logistics", "boundary": "destinations", "effective_time": 2, "wall_time": "2026-10-24T00:00:00Z", "quantity_unit": "item", "payload": row{"reference": id}}
	raw, _ := json.Marshal(env)
	if _, e := s.IngestTransport(ctx, raw, "shipping/events"); e == nil {
		t.Fatal("accepted unrelated destination receipt")
	}
}

func TestTransportRejectedProviderAssignmentCanRetry(t *testing.T) {
	s := testStore(t)
	s.C.Providers = map[string]string{"transport": "helics", "destinations": "helics"}
	ctx := context.Background()
	id := requestedTransfer(t, s, 5)
	if _, e := s.DB.Exec(ctx, "UPDATE transport_transfers SET provider=true WHERE id=$1", id); e != nil {
		t.Fatal(e)
	}
	if e := s.Seed(ctx); e != nil {
		t.Fatal(e)
	}
	// An employee wins the vehicle before the previously scheduled provider assignment.
	if _, e := s.DB.Exec(ctx, "UPDATE transport_vehicles SET location='DISPATCH' WHERE code='TRUCK-1'"); e != nil {
		t.Fatal(e)
	}
	r, _ := s.Run(ctx)
	s.Prepare(ctx, 2, r["epoch"].(string))
	s.Grant(ctx, 2, r["epoch"].(string))
	s.Heartbeat(ctx, "controller", "")
	jobs, _ := s.Dispatchable(ctx)
	for _, j := range jobs {
		if _, e := s.Execute(ctx, j["job_id"].(string)); e != nil {
			t.Fatal(e)
		}
	}
	if _, e := s.DB.Exec(ctx, "UPDATE transport_vehicles SET location='WAREHOUSE' WHERE code='TRUCK-1'"); e != nil {
		t.Fatal(e)
	}
	if e := s.Seed(ctx); e != nil {
		t.Fatal(e)
	}
	r, _ = s.Run(ctx)
	s.Prepare(ctx, 3, r["epoch"].(string))
	s.Grant(ctx, 3, r["epoch"].(string))
	s.Heartbeat(ctx, "controller", "")
	jobs, _ = s.Dispatchable(ctx)
	for _, j := range jobs {
		if _, e := s.Execute(ctx, j["job_id"].(string)); e != nil {
			t.Fatal(e)
		}
	}
	if tr := transferByID(t, s, id); tr["status"] != "assigned" {
		t.Fatalf("provider never retried after availability recovered: %v", tr)
	}
}
func TestTransportDefaultRoutesPersistInRunConfiguration(t *testing.T) {
	s := testStore(t)
	r, e := s.Run(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	if r["scenario"].(map[string]any)["transport"] == nil {
		t.Fatal("default fleet and routes were not persisted")
	}
}
