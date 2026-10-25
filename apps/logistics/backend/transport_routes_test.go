package main

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestTransportOutputRoutesUseDistinctOperationsAndEventIDs(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	id := requestedTransfer(t, s, 5)
	tr := transferByID(t, s, id)
	tr["external_reference"] = uuid.NewString()
	r, _ := s.Run(ctx)
	raw, _ := json.Marshal(row{"type": "logistics.unload.completed.v1", "transfer": tr, "command_id": uuid.NewString(), "time": 1})
	if _, e := s.DB.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw); e != nil {
		t.Fatal(e)
	}
	events := map[string]bool{}
	operations := map[string]bool{}
	publications := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		var body row
		if e := json.NewDecoder(req.Body).Decode(&body); e != nil {
			t.Error(e)
		}
		if body["operation"] == "publish" {
			publications++
			operations[body["request_id"].(string)] = true
			envelope := body["payload"].(map[string]any)["envelope"].(map[string]any)
			events[envelope["event_id"].(string)] = true
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(row{"version": "1.0", "request_id": body["request_id"], "result": row{"state": "executing"}})
	}))
	defer server.Close()
	s.C.AdapterURL = server.URL
	s.C.FederationID = "test"
	s.C.Outputs = []Output{{Endpoint: "peer/events", Destination: "shipping", Boundary: "transport"}, {Endpoint: "peer/events", Destination: "storage", Boundary: "requests"}}
	a := &Adapter{Store: s, RunID: r["id"].(string), Epoch: r["epoch"].(string), SessionID: uuid.NewString(), Client: server.Client()}
	if e := a.settle(ctx, r); e != nil {
		t.Fatal(e)
	}
	if publications != 2 || len(operations) != 2 || len(events) != 2 {
		t.Fatalf("routes collapsed: publishes=%d operations=%d eventIDs=%d", publications, len(operations), len(events))
	}
}
func TestTransportInternalNamespaceReservedOnLegacyEndpoint(t *testing.T) {
	s := testStore(t)
	transportRequest(t, s, "POST", "/api/jobs", "transport:arrival:reserved", row{"due_at": 1, "quantity": 1}, 409)
}

func TestLocalTransportFactsDoNotLeakIntoShippingOrRawCustodySupply(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	id := requestedTransfer(t, s, 2)
	tr := transferByID(t, s, id)
	r, _ := s.Run(ctx)
	local, _ := json.Marshal(row{"type": "logistics.request.completed.v1", "transfer": tr, "command_id": uuid.NewString(), "time": 1})
	tr["external_reference"] = uuid.NewString()
	requested, _ := json.Marshal(row{"type": "logistics.unload.completed.v1", "transfer": tr, "command_id": uuid.NewString(), "time": 2})
	for _, raw := range [][]byte{local, requested} {
		if _, err := s.DB.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw); err != nil {
			t.Fatal(err)
		}
	}
	publications := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		var body row
		json.NewDecoder(req.Body).Decode(&body)
		if body["operation"] == "publish" {
			publications++
			payload := body["payload"].(map[string]any)
			e := payload["envelope"].(map[string]any)
			if payload["endpoint"] != "shipping/events" || e["type"] != "logistics.unload.completed.v1" {
				t.Errorf("unowned transport output escaped: %v", payload)
			}
		}
		json.NewEncoder(w).Encode(row{"version": "1.0", "request_id": body["request_id"], "result": row{"state": "executing"}})
	}))
	defer server.Close()
	s.C.AdapterURL = server.URL
	s.C.Outputs = []Output{{Endpoint: "shipping/events", Destination: "shipping", Boundary: "carrier"}, {Endpoint: "storage/events", Destination: "storage", Boundary: "supply"}}
	a := &Adapter{Store: s, RunID: r["id"].(string), Epoch: r["epoch"].(string), SessionID: uuid.NewString(), Client: server.Client()}
	if err := a.settle(ctx, r); err != nil {
		t.Fatal(err)
	}
	if publications != 1 {
		t.Fatalf("expected only the referenced Shipping outcome, got %d publications", publications)
	}
}

func TestCustodyOutputPreservesEnvelopeAndUsesOnlyConfiguredRecipient(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	identity := uuid.NewString()
	envelope := row{"schema_version": "1.0", "type": "handling.accepted.v1", "event_id": identity, "destination": "shipping", "boundary": "carrier", "payload": row{"id": uuid.NewString()}}
	raw, _ := json.Marshal(envelope)
	if _, err := s.DB.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw); err != nil {
		t.Fatal(err)
	}
	publications := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		var body row
		json.NewDecoder(req.Body).Decode(&body)
		if body["operation"] == "publish" {
			publications++
			payload := body["payload"].(map[string]any)
			value := payload["envelope"].(map[string]any)
			if payload["endpoint"] != "shipping/events" || value["event_id"] != identity || value["type"] != "handling.accepted.v1" || value["payload"].(map[string]any)["id"] != envelope["payload"].(row)["id"] {
				t.Errorf("custody evidence rewritten or misrouted: %v", payload)
			}
		}
		json.NewEncoder(w).Encode(row{"version": "1.0", "request_id": body["request_id"], "result": row{"state": "executing"}})
	}))
	defer server.Close()
	s.C.AdapterURL = server.URL
	s.C.Outputs = []Output{{Endpoint: "storage/events", Destination: "storage", Boundary: "requests"}, {Endpoint: "shipping/events", Destination: "shipping", Boundary: "carrier"}}
	a := &Adapter{Store: s, RunID: r["id"].(string), Epoch: r["epoch"].(string), SessionID: uuid.NewString(), Client: server.Client()}
	if err := a.settle(ctx, r); err != nil {
		t.Fatal(err)
	}
	if publications != 1 {
		t.Fatalf("custody publication count: %d", publications)
	}
}
