package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// Controlled peer IO; business commands still execute through the real worker.
func executePeerTransport(t *testing.T, s *Store, raw []byte) string {
	t.Helper()
	ctx := context.Background()
	var env row
	json.Unmarshal(raw, &env)
	var job row
	if err := s.transaction(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", env["run_id"]); err != nil {
			return err
		}
		var err error
		job, err = object(ctx, tx, "SELECT id,due_at FROM jobs WHERE idempotency_key=$1", "boundary:"+env["event_id"].(string))
		return err
	}); err != nil {
		t.Fatal(err)
	}
	r, _ := s.Run(ctx)
	due := num(job, "due_at")
	if due > num(r, "granted") {
		if ok, err := s.Prepare(ctx, due, r["epoch"].(string)); err != nil || !ok {
			t.Fatalf("prepare %v %v", ok, err)
		}
		if _, err := s.Grant(ctx, due, r["epoch"].(string)); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Heartbeat(ctx, "controller", ""); err != nil {
		t.Fatal(err)
	}
	if result, err := s.Execute(ctx, job["id"].(string)); err != nil || result != "completed" {
		t.Fatalf("peer execution %s %v", result, err)
	}
	return job["id"].(string)
}
func TestShippingPeerPlansWholeUnitsWithoutInventingStock(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	s.C.Peers = map[string]Peer{"transport": {Source: "shipping", Endpoint: "shipping/events"}}
	r, _ := s.Run(ctx)
	unitID, correlation, requestID := uuid.NewString(), uuid.NewString(), uuid.NewString()
	wire := func(kind string, aggregate string, version int, payload row) []byte {
		r, _ := s.Run(ctx)
		raw, _ := json.Marshal(row{"schema_version": "1.0", "type": kind, "event_id": uuid.NewString(), "federation_id": s.C.FederationID, "run_id": r["id"], "epoch": r["epoch"], "correlation_id": correlation, "causation_id": aggregate, "aggregate_id": aggregate, "aggregate_version": version, "source": "shipping", "destination": "logistics", "boundary": "transport", "effective_time": num(r, "granted") + 1, "wall_time": time.Now().UTC().Format(time.RFC3339Nano), "quantity_unit": "item", "payload": payload})
		return raw
	}
	payload := row{"customer_destination": "CUSTOMER-A", "route": "DISPATCH-CUSTOMER", "sku": "PRODUCT", "quantity": 3, "external_reference": requestID, "unit_ids": []string{unitID}, "unit_manifest": []row{{"id": unitID, "quantity": 3}}}
	raw := wire("logistics.request.v1", requestID, 1, payload)
	if result, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil || result != "accepted" {
		t.Fatalf("planned request: %s %v", result, err)
	}
	transferID := executePeerTransport(t, s, raw)
	snapshot := transportSnapshot(t, s)
	if len(snapshot["handling"].(map[string]any)["units"].([]any)) != 0 {
		t.Fatal("expected manifest created confirmed stock")
	}
	tr := transferByID(t, s, transferID)
	if tr["status"] != "requested" || tr["customer_destination"] != "CUSTOMER-A" {
		t.Fatalf("planned transfer: %v", tr)
	}
	public := row{"run_id": r["id"], "epoch": r["epoch"], "due_at": 20, "action": "request", "correlation_id": correlation}
	for k, v := range payload {
		public[k] = v
	}
	transportRequest(t, s, "POST", "/api/transport/commands", uuid.NewString(), public, 422)
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", r["id"]); err != nil {
		t.Fatal(err)
	}
	assigned := transportCommand(t, s, "assign", row{"reference": transferID, "vehicle": "VAN-1"})
	if assigned["status"] != "completed" {
		t.Fatal(assigned)
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", r["id"]); err != nil {
		t.Fatal(err)
	}
	extra := []row{}
	for index := 0; index < 16; index++ {
		extra = append(extra, row{"id": uuid.NewString(), "quantity": 1})
	}
	capacity := transportCommand(t, s, "intake", row{"sku": "EXTRA", "category": "finished", "location": "DISPATCH", "quantity": 16, "correlation_id": uuid.NewString(), "units": extra})
	if capacity["status"] != "rejected" || len(transportSnapshot(t, s)["handling"].(map[string]any)["units"].([]any)) != 0 {
		t.Fatal("intake stole assigned receiving capacity or partially committed a full manifest")
	}
	early := transportCommand(t, s, "load", row{"reference": transferID})
	if early["status"] != "rejected" {
		t.Fatal("unreceived expected unit loaded")
	}
	hID := uuid.NewString()
	unit := row{"id": unitID, "barcode": "HU-" + strings.ToUpper(strings.ReplaceAll(unitID, "-", "")), "run_id": r["id"], "epoch": r["epoch"], "contents": []row{{"sku": "PRODUCT", "quantity": 3}}, "category": "finished", "state": "reserved", "owner": "shipping", "version": 1, "custody_generation": 0, "last_sequence": 1, "position": "shipping.outbound.dock01", "origin": nil, "destination": nil, "handoff_id": nil}
	assignedTransfer := transferByID(t, s, transferID)
	destination := assignedTransfer["unit_destinations"].(map[string]any)[unitID]
	h := row{"id": hID, "run_id": r["id"], "epoch": r["epoch"], "source": "shipping", "destination_owner": "logistics", "origin": unit["position"], "destination": destination, "state": "offered", "unit": unit, "departure_token": nil, "receipt_id": nil, "reason": nil}
	offered := wire("handling.offered.v1", hID, 1, h)
	if _, err := s.IngestTransport(ctx, offered, "shipping/events"); err != nil {
		t.Fatal(err)
	}
	executePeerTransport(t, s, offered)
	unit = copyCustody(unit)
	unit["state"] = "in_transit"
	unit["position"] = nil
	unit["origin"] = h["origin"]
	unit["destination"] = h["destination"]
	unit["handoff_id"] = hID
	unit["custody_generation"] = 1
	unit["last_sequence"] = 2
	unit["version"] = 2
	departed := copyCustody(h)
	departed["state"] = "departed"
	departed["unit"] = unit
	departed["departure_token"] = row{"id": uuid.NewString(), "handoff_id": hID, "unit_id": unitID, "run_id": r["id"], "epoch": r["epoch"], "custody_generation": 1, "last_sequence": 2, "unit_version": 2}
	receipt := wire("handling.departed.v1", hID, 2, departed)
	if _, err := s.IngestTransport(ctx, receipt, "shipping/events"); err != nil {
		t.Fatal(err)
	}
	executePeerTransport(t, s, receipt)
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", r["id"]); err != nil {
		t.Fatal(err)
	}
	loaded := transportCommand(t, s, "load", row{"reference": transferID})
	if loaded["status"] != "completed" {
		t.Fatalf("confirmed planned unit could not load: %v", loaded)
	}
	units := transportSnapshot(t, s)["handling"].(map[string]any)["units"].([]any)
	actual := units[0].(map[string]any)
	if actual["id"] != unitID || actual["state"] != "reserved" || !strings.HasPrefix(actual["position"].(string), "logistics.outbound.truck02.slot") {
		t.Fatalf("assigned vehicle lost whole unit: %v", actual)
	}
}

func TestExpectedReceivingPositionsAreFencedByReset(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	s.C.Peers = map[string]Peer{"transport": {Source: "shipping", Endpoint: "shipping/events"}}
	plan := func() string {
		t.Helper()
		r, _ := s.Run(ctx)
		id, request := uuid.NewString(), uuid.NewString()
		raw, _ := json.Marshal(row{"schema_version": "1.0", "type": "logistics.request.v1", "event_id": request, "federation_id": s.C.FederationID, "run_id": r["id"], "epoch": r["epoch"], "correlation_id": uuid.NewString(), "causation_id": request, "aggregate_id": request, "aggregate_version": 1, "source": "shipping", "destination": "logistics", "boundary": "transport", "effective_time": num(r, "granted") + 1, "wall_time": time.Now().UTC().Format(time.RFC3339Nano), "quantity_unit": "item", "payload": row{"customer_destination": "CUSTOMER-A", "route": "DISPATCH-CUSTOMER", "sku": "PRODUCT", "quantity": 1, "external_reference": request, "unit_ids": []string{id}, "unit_manifest": []row{{"id": id, "quantity": 1}}}})
		if _, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil {
			t.Fatal(err)
		}
		transfer := executePeerTransport(t, s, raw)
		if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", r["id"]); err != nil {
			t.Fatal(err)
		}
		assigned := transportCommand(t, s, "assign", row{"reference": transfer, "vehicle": "VAN-1"})
		if assigned["status"] != "completed" {
			t.Fatal(assigned)
		}
		values := transferByID(t, s, transfer)["unit_destinations"].(map[string]any)
		return values[id].(string)
	}
	first := plan()
	r, _ := s.Run(ctx)
	if _, err := s.Control(ctx, "reset", 1, r["id"].(string), nil, nil); err != nil {
		t.Fatal(err)
	}
	if next := plan(); next != first {
		t.Fatalf("old epoch reservation consumed new-run capacity: %s vs %s", first, next)
	}
}
