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

func TestCustodyReceiptRequiresDurableDepartureAndPreservesWholeIdentity(t *testing.T) {
	s := testStore(t)
	s.C.Peers = map[string]Peer{"transport": {Source: "shipping", Endpoint: "shipping/events"}}
	ctx := context.Background()
	run, err := s.Run(ctx)
	if err != nil {
		t.Fatal(err)
	}
	id, handoff, correlation := uuid.NewString(), uuid.NewString(), uuid.NewString()
	unit := row{"id": id, "barcode": "HU-" + strings.ToUpper(strings.ReplaceAll(id, "-", "")), "run_id": run["id"], "epoch": run["epoch"], "contents": []row{{"sku": "PRODUCT", "quantity": 3}}, "category": "finished", "state": "reserved", "owner": "shipping", "version": 1, "custody_generation": 0, "last_sequence": 1, "position": "shipping.outbound.dock01", "origin": nil, "destination": nil, "handoff_id": nil}
	offer := row{"id": handoff, "run_id": run["id"], "epoch": run["epoch"], "source": "shipping", "destination_owner": "logistics", "origin": unit["position"], "destination": "logistics.outbound.staging01", "state": "offered", "unit": unit, "departure_token": nil, "receipt_id": nil, "reason": nil}
	wire := func(h row) []byte {
		current, e := s.Run(ctx)
		if e != nil {
			t.Fatal(e)
		}
		u := h["unit"].(row)
		raw, _ := json.Marshal(row{"schema_version": "1.0", "type": "handling." + h["state"].(string) + ".v1", "event_id": uuid.NewString(), "federation_id": s.C.FederationID, "run_id": run["id"], "epoch": run["epoch"], "correlation_id": correlation, "causation_id": h["id"], "aggregate_id": h["id"], "aggregate_version": u["version"], "source": "shipping", "destination": "logistics", "boundary": "transport", "effective_time": num(current, "granted") + 1, "wall_time": time.Now().UTC().Format(time.RFC3339Nano), "quantity_unit": "item", "payload": h})
		return raw
	}
	execute := func(raw []byte) {
		t.Helper()
		var e row
		json.Unmarshal(raw, &e)
		var job row
		err := s.transaction(ctx, func(tx pgx.Tx) error {
			// Controlled peer fixture acknowledges durable publications; native IO
			// is covered separately by connected acceptance.
			if _, failure := tx.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", run["id"]); failure != nil {
				return failure
			}
			var failure error
			job, failure = object(ctx, tx, "SELECT id FROM jobs WHERE idempotency_key=$1", "boundary:"+e["event_id"].(string))
			return failure
		})
		if err != nil {
			t.Fatal(err)
		}
		due := e["effective_time"].(float64)
		current, _ := s.Run(ctx)
		if due > num(current, "granted") {
			if ok, err := s.Prepare(ctx, due, run["epoch"].(string)); err != nil || !ok {
				t.Fatalf("prepare: %v %v", ok, err)
			}
			if _, err := s.Grant(ctx, due, run["epoch"].(string)); err != nil {
				t.Fatal(err)
			}
		}
		s.Heartbeat(ctx, "controller", "")
		if result, err := s.Execute(ctx, job["id"].(string)); err != nil || result != "completed" {
			t.Fatalf("worker: %s %v", result, err)
		}
	}
	directTruck := copyCustody(offer)
	directTruck["destination"] = "logistics.outbound.truck02.slot01"
	if result, err := s.IngestTransport(ctx, wire(directTruck), "shipping/events"); err != nil || result != "quarantined" {
		t.Fatal("peer receipt bypassed assigned vehicle loading and capacity checks")
	}
	for _, test := range []struct {
		field string
		value any
	}{{"custody_generation", 1e30}, {"last_sequence", 1e30}, {"custody_generation", float64(2147483647)}, {"last_sequence", float64(2147483646)}, {"version", float64(2147483646)}} {
		badUnit := copyCustody(unit)
		badUnit[test.field] = test.value
		bad := copyCustody(offer)
		bad["unit"] = badUnit
		if result, err := s.IngestTransport(ctx, wire(bad), "shipping/events"); err != nil || result != "quarantined" {
			t.Fatalf("unsupported counter accepted: %s=%v", test.field, test.value)
		}
	}
	raw := wire(offer)
	if _, err := s.IngestTransport(ctx, raw, "intruder/events"); err == nil {
		t.Fatal("unconfigured endpoint accepted custody")
	}
	if result, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil || result != "accepted" {
		t.Fatalf("offer: %s %v", result, err)
	}
	execute(raw)
	handling := transportSnapshot(t, s)["handling"].(map[string]any)
	if len(handling["units"].([]any)) != 0 {
		t.Fatal("acceptance invented destination stock")
	}
	if len(handling["handoffs"].([]any)) != 1 {
		t.Fatal("capacity acceptance not durable")
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=$1", run["id"]); err != nil {
		t.Fatal(err)
	}
	if result, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil || result != "duplicate" {
		t.Fatalf("acceptance recovery: %s %v", result, err)
	}
	var pending int
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM boundary_outbox WHERE run_id=$1 AND sent_at IS NULL", run["id"]).Scan(&pending); err != nil || pending != 1 {
		t.Fatalf("lost acceptance not republished: %d %v", pending, err)
	}
	if _, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil {
		t.Fatal(err)
	}
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM boundary_outbox WHERE run_id=$1 AND sent_at IS NULL", run["id"]).Scan(&pending); err != nil || pending != 1 {
		t.Fatalf("unbounded acceptance retries: %d %v", pending, err)
	}
	departedUnit := row{}
	for k, v := range unit {
		departedUnit[k] = v
	}
	for k, v := range (row{"state": "in_transit", "position": nil, "origin": offer["origin"], "destination": offer["destination"], "handoff_id": handoff, "custody_generation": 1, "last_sequence": 2, "version": 2}) {
		departedUnit[k] = v
	}
	departed := row{}
	for k, v := range offer {
		departed[k] = v
	}
	departed["state"] = "departed"
	departed["unit"] = departedUnit
	departed["departure_token"] = row{"id": uuid.NewString(), "handoff_id": handoff, "unit_id": id, "run_id": run["id"], "epoch": run["epoch"], "custody_generation": 1, "last_sequence": 2, "unit_version": 2}
	invalid := copyCustody(departed)
	badToken := copyCustody(departed["departure_token"].(row))
	badToken["unit_id"] = uuid.NewString()
	invalid["departure_token"] = badToken
	if result, err := s.IngestTransport(ctx, wire(invalid), "shipping/events"); err != nil || result != "quarantined" {
		t.Fatal("token for another unit authorized receipt")
	}
	if len(transportSnapshot(t, s)["handling"].(map[string]any)["units"].([]any)) != 0 {
		t.Fatal("invalid proof placed stock")
	}
	corrupt := copyCustody(departed)
	corruptUnit := copyCustody(departedUnit)
	corruptUnit["contents"] = []row{{"sku": "PRODUCT", "quantity": 4}}
	corrupt["unit"] = corruptUnit
	corruptRaw := wire(corrupt)
	if result, err := s.IngestTransport(ctx, corruptRaw, "shipping/events"); err != nil || result != "accepted" {
		t.Fatalf("corrupt proof admission: %s %v", result, err)
	}
	execute(corruptRaw)
	quarantineHandling := transportSnapshot(t, s)["handling"].(map[string]any)
	if cases, ok := quarantineHandling["quarantine"].([]any); !ok || len(cases) == 0 {
		t.Fatal("rejected custody proof must be retained in the quarantine read model")
	}
	if result, err := s.IngestTransport(ctx, corruptRaw, "shipping/events"); err != nil || result != "quarantined" {
		t.Fatalf("rejected proof replay: %s %v", result, err)
	}

	raw = wire(departed)
	if result, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil || result != "accepted" {
		t.Fatalf("departure: %s %v", result, err)
	}
	execute(raw)
	handling = transportSnapshot(t, s)["handling"].(map[string]any)
	units := handling["units"].([]any)
	if len(units) != 1 {
		t.Fatalf("received units: %v", units)
	}
	received := units[0].(map[string]any)
	if received["id"] != id || received["position"] != offer["destination"] || received["last_sequence"] != float64(3) || received["custody_generation"] != float64(1) {
		t.Fatalf("receipt changed identity, placement or sequence: %v", received)
	}
	if result, err := s.IngestTransport(ctx, raw, "shipping/events"); err != nil || result != "duplicate" {
		t.Fatalf("redelivery: %s %v", result, err)
	}
	if len(transportSnapshot(t, s)["handling"].(map[string]any)["movements"].([]any)) != 1 {
		t.Fatal("redelivery repeated physical receipt")
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=$1", run["id"]); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(ctx, "UPDATE transport_handling_units SET version=2147483647 WHERE id=$1", id); err != nil {
		t.Fatal(err)
	}
	command := transportCommand(t, s, "request", row{"route": "DISPATCH-CUSTOMER", "sku": "PRODUCT", "quantity": 3, "correlation_id": uuid.NewString(), "unit_ids": []string{id}})
	if command["status"] != "rejected" {
		t.Fatalf("exhausted unit counter was allocated: %v", command)
	}
	if _, err := s.DB.Exec(ctx, "UPDATE transport_handling_units SET version=3 WHERE id=$1", id); err != nil {
		t.Fatal(err)
	}
	otherUnit := copyCustody(unit)
	otherID := uuid.NewString()
	otherUnit["id"] = otherID
	otherUnit["barcode"] = "HU-" + strings.ToUpper(strings.ReplaceAll(otherID, "-", ""))
	otherUnit["position"] = "shipping.outbound.dock02"
	other := copyCustody(offer)
	other["id"] = uuid.NewString()
	other["unit"] = otherUnit
	other["origin"] = otherUnit["position"]
	blockedRaw := wire(other)
	if _, err := s.IngestTransport(ctx, blockedRaw, "shipping/events"); err != nil {
		t.Fatal(err)
	}
	execute(blockedRaw)
	var count int
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_custody WHERE id=$1", other["id"]).Scan(&count); err != nil || count != 0 {
		t.Fatalf("full slot accepted: %d %v", count, err)
	}
	// Controlled fixture confirms the first unit off-site, freeing the endpoint.
	if _, err := s.DB.Exec(ctx, "UPDATE transport_handling_units SET state='dispatched',position=NULL,version=version+1 WHERE id=$1", id); err != nil {
		t.Fatal(err)
	}
	if result, err := s.IngestTransport(ctx, blockedRaw, "shipping/events"); err != nil || result != "duplicate" {
		t.Fatalf("capacity retry: %s %v", result, err)
	}
	execute(blockedRaw)
	if err := s.DB.QueryRow(ctx, "SELECT count(*) FROM transport_custody WHERE id=$1 AND state='accepted'", other["id"]).Scan(&count); err != nil || count != 1 {
		t.Fatalf("identical offer could not recover after capacity freed: %d %v", count, err)
	}
	if _, err := s.DB.Exec(ctx, "UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=$1", run["id"]); err != nil {
		t.Fatal(err)
	}
	retries := 0
	if err := s.transaction(ctx, func(tx pgx.Tx) error {
		current, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		retries, e = recoverCustody(ctx, tx, current)
		return e
	}); err != nil || retries != 2 {
		t.Fatalf("durable receiver stage recovery: %d %v", retries, err)
	}
	if err := s.transaction(ctx, func(tx pgx.Tx) error {
		current, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		retries, e = recoverCustody(ctx, tx, current)
		return e
	}); err != nil || retries != 0 {
		t.Fatalf("recovery flooded pending publications: %d %v", retries, err)
	}
	var stale row
	json.Unmarshal(wire(offer), &stale)
	epoch := uuid.NewString()
	stale["epoch"] = epoch
	payload := stale["payload"].(map[string]any)
	payload["epoch"] = epoch
	payload["unit"].(map[string]any)["epoch"] = epoch
	staleRaw, _ := json.Marshal(stale)
	if result, err := s.IngestTransport(ctx, staleRaw, "shipping/events"); err != nil || result != "quarantined" {
		t.Fatalf("stale custody scope: %s %v", result, err)
	}

}
