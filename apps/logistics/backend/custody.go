package main

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"reflect"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func custodyFields(value row, fields ...string) error {
	if len(value) != len(fields) {
		return Conflict("Complete custody object required")
	}
	for _, field := range fields {
		if _, ok := value[field]; !ok {
			return Conflict("Missing custody field: " + field)
		}
	}
	return nil
}
func custodyInteger(value any, minimum float64) bool {
	n, ok := value.(float64)
	return ok && finite(n) && n >= minimum && n <= handlingMaxCounter && n == math.Trunc(n)
}
func custodyEndpoint(id any, owner, category string) bool {
	name, ok := id.(string)
	if !ok {
		return false
	}
	location, ok := physicalLocations[name]
	if !ok || location.Owner != owner {
		return false
	}
	for _, allowed := range location.Compatible {
		if allowed == category {
			return true
		}
	}
	return false
}
func validateCustody(env TransportEnvelope) (row, error) {
	var h row
	if err := json.Unmarshal(env.Payload, &h); err != nil {
		return nil, err
	}
	if err := custodyFields(h, "id", "run_id", "epoch", "source", "destination_owner", "origin", "destination", "state", "unit", "departure_token", "receipt_id", "reason"); err != nil {
		return nil, err
	}
	for _, field := range []string{"id", "run_id", "epoch"} {
		text, ok := h[field].(string)
		if !ok {
			return nil, Conflict("Custody UUID required")
		}
		if _, err := uuid.Parse(text); err != nil {
			return nil, err
		}
	}
	unit, ok := h["unit"].(map[string]any)
	if !ok {
		return nil, Conflict("Custody unit required")
	}
	if err := custodyFields(unit, "id", "barcode", "run_id", "epoch", "contents", "category", "state", "owner", "version", "custody_generation", "last_sequence", "position", "origin", "destination", "handoff_id"); err != nil {
		return nil, err
	}
	id, ok := unit["id"].(string)
	if !ok {
		return nil, Conflict("Unit UUID required")
	}
	if _, err := uuid.Parse(id); err != nil {
		return nil, err
	}
	contents, ok := unit["contents"].([]any)
	if !ok || len(contents) != 1 {
		return nil, Conflict("One complete SKU per native handling unit required")
	}
	item, ok := contents[0].(map[string]any)
	if !ok {
		return nil, Conflict("Whole contents required")
	}
	if err := custodyFields(item, "sku", "quantity"); err != nil {
		return nil, err
	}
	sku, ok := item["sku"].(string)
	if !ok || !transportCode.MatchString(sku) || !custodyInteger(item["quantity"], 1) || num(item, "quantity") > 10000 {
		return nil, Conflict("Invalid whole contents")
	}
	category, ok := unit["category"].(string)
	if !ok || (category != "raw" && category != "finished") {
		return nil, Conflict("Invalid unit category")
	}
	source, ok := h["source"].(string)
	if !ok || source == "logistics" || !containsCustodyOwner(source) || h["destination_owner"] != "logistics" || unit["owner"] != source {
		return nil, Conflict("Custody endpoint ownership mismatch")
	}
	if !custodyEndpoint(h["origin"], source, category) || !custodyEndpoint(h["destination"], "logistics", category) {
		return nil, Conflict("Unknown or incompatible physical endpoint")
	}
	if physicalLocations[h["destination"].(string)].Kind != "dock" {
		return nil, Conflict("Custody receipt requires a receiving dock; truck placement requires assigned loading and capacity checks")
	}
	if unit["barcode"] != "HU-"+strings.ToUpper(strings.ReplaceAll(id, "-", "")) || unit["run_id"] != h["run_id"] || unit["epoch"] != h["epoch"] || !custodyInteger(unit["version"], 1) || !custodyInteger(unit["custody_generation"], 0) || !custodyInteger(unit["last_sequence"], 0) {
		return nil, Conflict("Unit identity, scope or version mismatch")
	}
	state, ok := h["state"].(string)
	if !ok || env.Type != "handling."+state+".v1" || env.Source != source || env.Destination != "logistics" || env.RunID != h["run_id"] || env.Epoch != h["epoch"] || env.AggregateID != h["id"] || env.CausationID != h["id"] || float64(env.AggregateVersion) != num(unit, "version") {
		return nil, Conflict("Custody envelope metadata mismatch")
	}
	if h["reason"] != nil {
		if _, ok := h["reason"].(string); !ok {
			return nil, Conflict("Invalid custody reason")
		}
	}
	switch state {
	case "offered":
		// Source departure and receiver receipt each advance version/sequence.
		if num(unit, "version") > handlingMaxCounter-2 || num(unit, "last_sequence") > handlingMaxCounter-2 || num(unit, "custody_generation") > handlingMaxCounter-1 {
			return nil, Conflict("Custody counters lack SQL movement headroom")
		}
		if unit["state"] != "reserved" || unit["position"] != h["origin"] || unit["origin"] != nil || unit["destination"] != nil || unit["handoff_id"] != nil || h["departure_token"] != nil || h["receipt_id"] != nil {
			return nil, Conflict("Offer requires confirmed reserved source placement")
		}
	case "departed", "acknowledged":
		if num(unit, "version") > handlingMaxCounter-1 || num(unit, "last_sequence") > handlingMaxCounter-1 {
			return nil, Conflict("Departure counters lack receipt headroom")
		}
		token, ok := h["departure_token"].(map[string]any)
		if !ok {
			return nil, Conflict("Source departure token required")
		}
		if err := custodyFields(token, "id", "handoff_id", "unit_id", "run_id", "epoch", "custody_generation", "last_sequence", "unit_version"); err != nil {
			return nil, err
		}
		tokenID, ok := token["id"].(string)
		if !ok {
			return nil, Conflict("Token UUID required")
		}
		if _, err := uuid.Parse(tokenID); err != nil {
			return nil, err
		}
		for field, expected := range (row{"handoff_id": h["id"], "unit_id": id, "run_id": h["run_id"], "epoch": h["epoch"], "custody_generation": unit["custody_generation"], "last_sequence": unit["last_sequence"], "unit_version": unit["version"]}) {
			if token[field] != expected {
				return nil, Conflict("Departure token identity or version mismatch")
			}
		}
		if unit["state"] != "in_transit" || unit["position"] != nil || unit["origin"] != h["origin"] || unit["destination"] != h["destination"] || unit["handoff_id"] != h["id"] || num(unit, "custody_generation") < 1 || num(unit, "last_sequence") < 1 {
			return nil, Conflict("Departure requires unplaced source custody")
		}
		if state == "acknowledged" {
			id, ok := h["receipt_id"].(string)
			if !ok {
				return nil, Conflict("Receipt UUID required")
			}
			if _, err := uuid.Parse(id); err != nil {
				return nil, err
			}
		}
	default:
		return nil, Conflict("Unsupported destination custody transition")
	}
	return h, nil
}
func containsCustodyOwner(owner string) bool {
	return owner == "storage" || owner == "manufacturing" || owner == "shipping" || owner == "logistics"
}
func copyCustody(value row) row {
	result := row{}
	for key, item := range value {
		result[key] = item
	}
	return result
}

func (s *Store) ingestCustody(ctx context.Context, raw []byte, env TransportEnvelope, endpoint string) (result string, err error) {
	if env.SchemaVersion != "1.0" || env.QuantityUnit != "item" || !finite(env.EffectiveTime) || env.EffectiveTime < 0 {
		return "", Conflict("Invalid custody envelope")
	}
	if _, err = time.Parse(time.RFC3339Nano, env.WallTime); err != nil {
		return
	}
	err = s.transaction(ctx, func(tx pgx.Tx) error {
		r, e := lockRun(ctx, tx)
		if e != nil {
			return e
		}
		quarantine := func(reason string) error {
			if failure := recordCustodyQuarantine(ctx, tx, r, raw, env.EventID, endpoint, "ingest", reason, nil); failure != nil {
				return failure
			}
			result = "quarantined"
			return nil
		}
		if env.RunID != r["id"] || env.Epoch != r["epoch"] {
			return quarantine("Custody run or epoch mismatch")
		}
		seen, failure := custodyQuarantineSeen(ctx, tx, r, raw, env.EventID)
		if failure != nil {
			return failure
		}
		if seen {
			result = "quarantined"
			return nil
		}
		if _, failure = validateCustody(env); failure != nil {
			return quarantine(failure.Error())
		}
		old, e := object(ctx, tx, "SELECT * FROM transport_custody_events WHERE event_id=$1", env.EventID)
		if e == nil {
			var value row
			json.Unmarshal(raw, &value)
			if !reflect.DeepEqual(old["envelope"], value) {
				return quarantine("Custody event identity changed")
			}
			if active(r) {
				if _, e = tx.Exec(ctx, "UPDATE jobs SET status='pending',due_at=$1,retry_after=clock_timestamp(),error=NULL WHERE id=$2 AND EXISTS(SELECT 1 FROM transport_commands WHERE id=$2 AND retryable_capacity)", math.Max(num(r, "granted"), env.EffectiveTime), old["command_id"]); e != nil {
					return e
				}
				if _, e = tx.Exec(ctx, "UPDATE transport_commands SET status='pending',reason=NULL,completed_at=NULL,retryable_capacity=false WHERE id=$1 AND retryable_capacity", old["command_id"]); e != nil {
					return e
				}
				if _, e = tx.Exec(ctx, "UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=$1", old["command_id"]); e != nil {
					return e
				}
				if e = replayCustody(ctx, tx, r, env); e != nil {
					return e
				}
			}
			result = "duplicate"
			return nil
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if !active(r) {
			return quarantine("Inactive custody run")
		}
		id := uuid.NewString()
		payload, _ := json.Marshal(row{"custody": env, "custody_endpoint": endpoint})
		command, _ := json.Marshal(row{"action": "custody", "handoff_id": env.AggregateID, "state": strings.TrimSuffix(strings.TrimPrefix(env.Type, "handling."), ".v1")})
		due := math.Max(num(r, "granted"), env.EffectiveTime)
		if _, e = tx.Exec(ctx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES($1,$2,$3,$4,$5,$6,$7)", id, r["id"], r["epoch"], "boundary:"+env.EventID, due, env.EffectiveTime, payload); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, "INSERT INTO transport_commands(id,run_id,command,provider) VALUES($1,$2,$3,true)", id, r["id"], command); e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, "INSERT INTO transport_custody_events(event_id,run_id,envelope,command_id) VALUES($1,$2,$3,$4)", env.EventID, r["id"], raw, id); e != nil {
			return e
		}
		result = "accepted"
		return nil
	})
	return
}

type custodyCapacity struct{}

func (custodyCapacity) Error() string {
	return "Destination physical capacity unavailable; retry identical custody offer after capacity frees"
}
func (s *Store) executeCustody(ctx context.Context, tx pgx.Tx, r, j row) error {
	raw, _ := json.Marshal(j["payload"].(map[string]any)["custody"])
	var env TransportEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return err
	}
	save, err := tx.Begin(ctx)
	if err != nil {
		return err
	}
	err = s.applyCustody(ctx, save, r, j, env)
	var conflict Conflict
	var capacity custodyCapacity
	if errors.As(err, &conflict) || errors.As(err, &capacity) {
		if e := save.Rollback(ctx); e != nil {
			return e
		}
		if errors.As(err, &conflict) {
			endpoint, _ := j["payload"].(map[string]any)["custody_endpoint"].(string)
			if failure := recordCustodyQuarantine(ctx, tx, r, raw, env.EventID, endpoint, "apply", err.Error(), j["id"]); failure != nil {
				return failure
			}
		}
		_, err = tx.Exec(ctx, "UPDATE transport_commands SET status='rejected',reason=$1,completed_at=$2,retryable_capacity=$3 WHERE id=$4", err.Error(), r["granted"], errors.As(err, &capacity), j["id"])
	} else if err != nil {
		save.Rollback(ctx)
		return err
	} else {
		if err = save.Commit(ctx); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, "UPDATE transport_commands SET status='completed',completed_at=$1 WHERE id=$2", r["granted"], j["id"])
	}
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", j["id"], r["id"], r["epoch"]); err != nil {
		return err
	}
	_, err = tx.Exec(ctx, "UPDATE jobs SET status='completed',error=NULL WHERE id=$1", j["id"])
	return err
}
func (s *Store) applyCustody(ctx context.Context, tx pgx.Tx, r, j row, env TransportEnvelope) error {
	h, err := validateCustody(env)
	if err != nil {
		return err
	}
	unit := h["unit"].(map[string]any)
	old, err := object(ctx, tx, "SELECT * FROM transport_custody WHERE id=$1", h["id"])
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if old != nil && old["correlation_id"] != env.CorrelationID {
		return Conflict("Custody correlation changed")
	}
	if h["state"] == "offered" {
		if old != nil {
			if !reflect.DeepEqual(old["offer"], h) {
				return Conflict("Handoff identity changed")
			}
			return nil
		}
		if _, err := expectedCustody(ctx, tx, r, h, env.CorrelationID); err != nil {
			return err
		}
		var known bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE id=$1) OR EXISTS(SELECT 1 FROM transport_custody WHERE unit_id=$1 AND state='accepted')", unit["id"]).Scan(&known); err != nil {
			return err
		}
		if known {
			return Conflict("Barcode already known or accepted")
		}
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE run_id=$1 AND epoch=$2 AND (position=$3 OR (state='in_transit' AND destination=$3))) OR EXISTS(SELECT 1 FROM transport_custody WHERE run_id=$1 AND epoch=$2 AND destination=$3 AND state='accepted') OR EXISTS(SELECT 1 FROM transport_expected_units WHERE run_id=$1 AND epoch=$2 AND active AND destination=$3 AND unit_id<>$4)", r["id"], r["epoch"], h["destination"], unit["id"]).Scan(&known); err != nil {
			return err
		}
		if known {
			return custodyCapacity{}
		}
		accepted := copyCustody(h)
		accepted["state"] = "accepted"
		offerRaw, _ := json.Marshal(h)
		acceptedRaw, _ := json.Marshal(accepted)
		if _, err = tx.Exec(ctx, "INSERT INTO transport_custody(id,run_id,epoch,unit_id,destination,correlation_id,state,offer,acceptance,command_id) VALUES($1,$2,$3,$4,$5,$6,'accepted',$7,$8,$9)", h["id"], r["id"], r["epoch"], unit["id"], h["destination"], env.CorrelationID, offerRaw, acceptedRaw, j["id"]); err != nil {
			return err
		}
		return s.publishCustody(ctx, tx, r, env, accepted)
	}
	if old == nil {
		return Conflict("Departure requires prior durable capacity acceptance")
	}
	base := old["offer"].(map[string]any)
	for _, field := range []string{"id", "run_id", "epoch", "source", "destination_owner", "origin", "destination"} {
		if base[field] != h[field] {
			return Conflict("Departure changed accepted handoff")
		}
	}
	expected := copyCustody(base["unit"].(map[string]any))
	expected["state"] = "in_transit"
	expected["position"] = nil
	expected["origin"] = base["origin"]
	expected["destination"] = base["destination"]
	expected["handoff_id"] = base["id"]
	for _, field := range []string{"custody_generation", "last_sequence", "version"} {
		expected[field] = num(expected, field) + 1
	}
	if !reflect.DeepEqual(expected, unit) {
		return Conflict("Departure changed whole contents or skipped custody sequence")
	}
	if old["receipt"] != nil {
		receipt := old["receipt"].(map[string]any)
		check := copyCustody(h)
		check["state"] = "received"
		check["receipt_id"] = receipt["receipt_id"]
		if !reflect.DeepEqual(check, receipt) || (h["state"] == "acknowledged" && h["receipt_id"] != receipt["receipt_id"]) {
			return Conflict("Conflicting custody receipt proof")
		}
		if h["state"] == "acknowledged" {
			_, err = tx.Exec(ctx, "UPDATE transport_custody SET state='acknowledged' WHERE id=$1", h["id"])
		}
		return err
	}
	if h["state"] != "departed" {
		return Conflict("Acknowledgement preceded receipt")
	}
	item := unit["contents"].([]any)[0].(map[string]any)
	location := "WAREHOUSE"
	if h["source"] == "shipping" {
		location = "DISPATCH"
	}
	planned, err := expectedCustody(ctx, tx, r, h, env.CorrelationID)
	if err != nil {
		return err
	}
	state := "available"
	var transfer any
	if planned != nil {
		state = "reserved"
		location = planned["origin"].(string)
		transfer = planned["transfer_id"]
	}
	receivedUnit, err := object(ctx, tx, "INSERT INTO transport_handling_units(id,barcode,run_id,epoch,sku,quantity,category,logical_location,state,position,version,last_sequence,custody_generation,command_id,transfer_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$14,$9,$10,$11,$12,$13,$15) RETURNING *", unit["id"], unit["barcode"], r["id"], r["epoch"], item["sku"], int(num(item, "quantity")), unit["category"], location, h["destination"], int(num(unit, "version")), int(num(unit, "last_sequence")), int(num(unit, "custody_generation")), j["id"], state, transfer)
	if err != nil {
		return err
	}
	if planned != nil {
		if _, err = tx.Exec(ctx, "INSERT INTO transport_unit_allocations(transfer_id,unit_id) VALUES($1,$2)", transfer, unit["id"]); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_expected_units SET state='received' WHERE transfer_id=$1 AND unit_id=$2", transfer, unit["id"]); err != nil {
			return err
		}
	}
	if err = handlingMovement(ctx, tx, r, j, receivedUnit, "receive", h["origin"], h["destination"].(string), env.CorrelationID, nil); err != nil {
		return err
	}
	receipt := copyCustody(h)
	receipt["state"] = "received"
	receipt["receipt_id"] = uuid.NewSHA1(uuid.MustParse(h["id"].(string)), []byte("logistics-receipt")).String()
	receiptRaw, _ := json.Marshal(receipt)
	if _, err = tx.Exec(ctx, "UPDATE transport_custody SET state='received',receipt=$1 WHERE id=$2", receiptRaw, h["id"]); err != nil {
		return err
	}
	return s.publishCustody(ctx, tx, r, env, receipt)
}
func (s *Store) publishCustody(ctx context.Context, tx pgx.Tx, r row, incoming TransportEnvelope, h row) error {
	id := uuid.NewSHA1(uuid.MustParse(h["id"].(string)), []byte("logistics:"+h["state"].(string))).String()
	boundary := "requests"
	if h["source"] == "shipping" {
		boundary = "carrier"
	}
	if h["source"] == "manufacturing" {
		boundary = "supply"
	}
	envelope := TransportEnvelope{SchemaVersion: "1.0", Type: "handling." + h["state"].(string) + ".v1", EventID: id, FederationID: s.C.FederationID, RunID: r["id"].(string), Epoch: r["epoch"].(string), CorrelationID: incoming.CorrelationID, CausationID: h["id"].(string), AggregateID: h["id"].(string), AggregateVersion: int(num(h["unit"].(map[string]any), "version")), Source: "logistics", Destination: h["source"].(string), Boundary: boundary, EffectiveTime: num(r, "granted") + s.C.Quantum, WallTime: time.Now().UTC().Format(time.RFC3339Nano), QuantityUnit: "item"}
	envelope.Payload, _ = json.Marshal(h)
	raw, _ := json.Marshal(envelope)
	_, err := tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3) ON CONFLICT(id) DO NOTHING", id, r["id"], raw)
	return err
}

// Each retry has a new private publication operation but retains the complete
// original peer envelope, including its event identity and source evidence.
func replayCustody(ctx context.Context, tx pgx.Tx, r row, incoming TransportEnvelope) error {
	state := ""
	switch incoming.Type {
	case "handling.offered.v1":
		state = "accepted"
	case "handling.departed.v1":
		state = "received"
	default:
		return nil
	}
	event := uuid.NewSHA1(uuid.MustParse(incoming.AggregateID), []byte("logistics:"+state)).String()
	rows, err := objects(ctx, tx, "SELECT envelope FROM boundary_outbox b WHERE b.run_id=$1 AND b.envelope->>'type' LIKE 'handling.%' AND b.envelope->>'event_id'=$2 AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'type' LIKE 'handling.%' AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds')) LIMIT 1", r["id"], event)
	if err != nil {
		return err
	}
	if len(rows) > 0 {
		raw, _ := json.Marshal(rows[0]["envelope"])
		_, err = tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw)
	}
	return err
}
func recoverCustody(ctx context.Context, tx pgx.Tx, r row) (int, error) {
	rows, err := objects(ctx, tx, "SELECT DISTINCT b.envelope FROM boundary_outbox b JOIN transport_custody c ON c.id::text=b.envelope->'payload'->>'id' AND c.state=b.envelope->'payload'->>'state' WHERE c.run_id=$1 AND c.epoch=$2 AND c.state IN ('accepted','received') AND b.run_id=$1 AND b.envelope->>'type' LIKE 'handling.%' AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'type' LIKE 'handling.%' AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds'))", r["id"], r["epoch"])
	if err != nil {
		return 0, err
	}
	for _, value := range rows {
		raw, _ := json.Marshal(value["envelope"])
		if _, err = tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) VALUES($1,$2,$3)", uuid.NewString(), r["id"], raw); err != nil {
			return 0, err
		}
	}
	return len(rows), nil
}
