package main

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

func TestAdapterPersistsSessionAndRetriesIdenticalOperation(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	var mu sync.Mutex
	ids := []string{}
	bodies := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer private-token" {
			t.Error("missing private authentication")
		}
		var body row
		json.NewDecoder(request.Body).Decode(&body)
		raw, _ := json.Marshal(body)
		mu.Lock()
		ids = append(ids, body["request_id"].(string))
		bodies = append(bodies, string(raw))
		count := len(ids)
		mu.Unlock()
		if count == 1 {
			conn, _, e := w.(http.Hijacker).Hijack()
			if e == nil {
				conn.Close()
			}
			return
		}
		json.NewEncoder(w).Encode(row{"version": "1.0", "request_id": body["request_id"], "result": row{"state": "initializing"}})
	}))
	defer server.Close()
	s.C.AdapterURL = server.URL
	s.C.AdapterToken = "private-token"
	a, e := newAdapter(ctx, s, r)
	if e != nil {
		t.Fatal(e)
	}
	if len(ids) != 2 || ids[0] != ids[1] || bodies[0] != bodies[1] {
		t.Fatalf("lost reply changed operation identity: %v", ids)
	}
	var count int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM logistics_adapter_operations WHERE completed_at IS NOT NULL").Scan(&count)
	if count != 1 {
		t.Fatalf("operation result not durable %d", count)
	}
	if _, e = newAdapter(ctx, s, r); e == nil {
		t.Fatal("fresh native session took over live epoch")
	}
	if _, e = a.Call(ctx, "initialize", row{"different": true}, ids[0]); e == nil {
		t.Fatal("conflicting adapter operation replay accepted")
	}
}
func TestConnectedEarlierGrantDoesNotAuthorizeFutureWork(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	s.DB.Exec(ctx, "UPDATE runs SET mode='helics' WHERE current")
	r, _ = s.Run(ctx)
	job, e := s.Schedule(ctx, "future", JobCommand{1, 4}, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	grant := 0.0
	requested := 0.0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		var b row
		json.NewDecoder(request.Body).Decode(&b)
		result := row{}
		switch b["operation"] {
		case "initialize":
			result["state"] = "initializing"
		case "poll":
			result = row{"state": "executing", "granted": grant, "requested": requested, "pending": false, "messages": []any{}, "values": row{}}
		case "request_time":
			requested = b["payload"].(map[string]any)["target"].(float64)
			result["requested"] = requested
		case "publish_value":
			result["published"] = true
		}
		json.NewEncoder(w).Encode(row{"version": "1.0", "request_id": b["request_id"], "result": result})
	}))
	defer server.Close()
	s.C.AdapterURL = server.URL
	s.C.AdapterToken = "token"
	a, e := newAdapter(ctx, s, r)
	if e != nil {
		t.Fatal(e)
	}
	if e = a.Tick(ctx, r); e != nil {
		t.Fatal(e)
	}
	grant = .5
	r, _ = s.Run(ctx)
	if e = a.Tick(ctx, r); e != nil {
		t.Fatal(e)
	}
	s.Heartbeat(ctx, "controller", "")
	if result, e := s.Execute(ctx, job["id"].(string)); e != nil || result != "waiting" {
		t.Fatalf("earlier grant authorized future work: %s %v", result, e)
	}
	r, _ = s.Run(ctx)
	if num(r, "granted") != .5 {
		t.Fatal("earlier grant not persisted")
	}
}
func TestBoundaryInboxDeduplicatesAndFences(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	s.C.FederationID = "factory"
	s.C.Peers = map[string]Peer{"transport": {Endpoint: "storage/events", Source: "storage"}}
	e := Envelope{SchemaVersion: "1.0", Type: "sample.completed.v1", EventID: uuid.NewString(), FederationID: "factory", RunID: r["id"].(string), Epoch: r["epoch"].(string), CorrelationID: uuid.NewString(), CausationID: uuid.NewString(), AggregateID: uuid.NewString(), AggregateVersion: 1, Source: "storage", Destination: "logistics", Boundary: "transport", EffectiveTime: 1, WallTime: "2026-01-01T00:00:00Z", QuantityUnit: "item"}
	e.Payload.Quantity = 2
	if result, err := s.Ingest(ctx, e, "storage/events"); err != nil || result != "accepted" {
		t.Fatalf("input not persisted %s %v", result, err)
	}
	if result, err := s.Ingest(ctx, e, "storage/events"); err != nil || result != "duplicate" {
		t.Fatalf("input duplicated %s %v", result, err)
	}
	e.Epoch = uuid.NewString()
	if result, err := s.Ingest(ctx, e, "storage/events"); err != nil || result != "fenced" {
		t.Fatalf("old epoch input accepted %s %v", result, err)
	}
}

func TestAPIFinalizeRejectsInitializingNativeSession(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	_, e := s.DB.Exec(ctx, "UPDATE runs SET mode='helics' WHERE current")
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.DB.Exec(ctx, "INSERT INTO logistics_adapter_sessions(run_id,epoch,session_id) VALUES($1,$2,$3)", r["id"], r["epoch"], uuid.NewString())
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Control(ctx, "finalize", 1, "", nil, nil); e == nil {
		t.Fatal("API finalized SQL while native initialization remained pending")
	}
}

func TestPreparePersistsNativePendingBeforeHTTPAndBlocksFinalize(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	s.DB.Exec(ctx, "UPDATE runs SET mode='helics' WHERE current")
	id := uuid.NewString()
	_, e := s.DB.Exec(ctx, "INSERT INTO logistics_adapter_sessions(run_id,epoch,session_id,native_state,pending,processing) VALUES($1,$2,$3,'executing',false,false)", r["id"], r["epoch"], id)
	if e != nil {
		t.Fatal(e)
	}
	ok, e := s.Prepare(ctx, 1, r["epoch"].(string))
	if e != nil || !ok {
		t.Fatalf("prepare failed %v", e)
	}
	var pending bool
	s.DB.QueryRow(ctx, "SELECT pending FROM logistics_adapter_sessions WHERE run_id=$1", r["id"]).Scan(&pending)
	if !pending {
		t.Fatal("native request intent was not durable before HTTP")
	}
	if _, e = s.Control(ctx, "finalize", 1, "", nil, nil); e == nil {
		t.Fatal("finalize raced between SQL prepare and native HTTP")
	}
	s.DB.Exec(ctx, "UPDATE logistics_adapter_sessions SET pending=false,processing=true WHERE run_id=$1", r["id"])
	if _, e = s.Control(ctx, "finalize", 1, "", nil, nil); e == nil {
		t.Fatal("finalize accepted while inputs/outputs were processing")
	}
	s.DB.Exec(ctx, "UPDATE logistics_adapter_sessions SET processing=false WHERE run_id=$1", r["id"])
	if _, e = s.Control(ctx, "finalize", 1, "", nil, nil); e != nil {
		t.Fatalf("settled native session could not finalize %v", e)
	}
}
