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
